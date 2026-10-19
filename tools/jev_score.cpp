// 判定専用の模型（Jev のような仕組み）の設計: 今の zenz を「採点だけ」に使ったときの点と時間を測る。
//
//   jev_score <model.gguf> <jobs.tsv> <out.tsv> <スレッド数> <方式,…> [候補の数の上限]
//
// jobs.tsv の1行: 番号<TAB>問い（左右の文脈と読みを含む、zenz-v3 の形）<TAB>候補<TAB>候補…
// 候補の点は「問いの後に候補の表記と文の終わりの記号が続く」対数確率の和（tools/zenz-finetune と同じ形。
// 問いの前に始まりの記号は付けない。問いと表記は別々に語片に切る）。
// 方式（コンマで並べると、同じ行を方式ごとに測る。点は最初の方式のもの）:
//   trie  共通の前置き（問い）と、候補どうしで共通の語片の前半を1回だけ並べ、全部を1回の評価で採点する
//         （語片の木。各語片に、その語片を通る候補の列の番号を全部付ける）
//   flat  問いを1回評価し、その結果を候補の数の列に写してから、全部の候補の語片を1回の評価で採点する
//   seq   問いを1回評価し、候補を1つずつ順に評価する（今の選び手の採点 ScoreSentenceSuffixes と同じ形）
//   full  候補ごとに問いから評価し直す（使い回しなし）
// out.tsv の1行: 番号<TAB>方式<TAB>問いの語片の数<TAB>評価した語片の数<TAB>ミリ秒<TAB>点<TAB>点…
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <map>
#include <sstream>
#include <string>
#include <vector>

#include "llama.h"

namespace {

std::vector<std::string> SplitTab(const std::string& line) {
  std::vector<std::string> out;
  size_t at = 0;
  while (true) {
    const size_t tab = line.find('\t', at);
    out.push_back(line.substr(at, tab == std::string::npos ? std::string::npos : tab - at));
    if (tab == std::string::npos) break;
    at = tab + 1;
  }
  return out;
}

std::vector<llama_token> Tokenize(const llama_vocab* vocab, const std::string& text) {
  std::vector<llama_token> tokens(text.size() + 8);
  int n = llama_tokenize(vocab, text.c_str(), static_cast<int32_t>(text.size()), tokens.data(),
                         static_cast<int32_t>(tokens.size()), false, false);
  if (n < 0) {
    tokens.resize(-n);
    n = llama_tokenize(vocab, text.c_str(), static_cast<int32_t>(text.size()), tokens.data(),
                       static_cast<int32_t>(tokens.size()), false, false);
  }
  tokens.resize(std::max(n, 0));
  return tokens;
}

double LogProb(const float* logits, int n_vocab, llama_token token) {
  float max = logits[0];
  for (int i = 1; i < n_vocab; ++i) max = std::max(max, logits[i]);
  double sum = 0;
  for (int i = 0; i < n_vocab; ++i) sum += std::exp(static_cast<double>(logits[i]) - max);
  return static_cast<double>(logits[token]) - max - std::log(sum);
}

struct Batch {
  llama_batch b;
  explicit Batch(int n, int seqs) : b(llama_batch_init(n, 0, seqs)) {}
  ~Batch() { llama_batch_free(b); }
  void Clear() { b.n_tokens = 0; }
  void Add(llama_token t, llama_pos pos, const std::vector<llama_seq_id>& seqs, bool logits) {
    const int i = b.n_tokens++;
    b.token[i] = t;
    b.pos[i] = pos;
    b.n_seq_id[i] = static_cast<int32_t>(seqs.size());
    for (size_t s = 0; s < seqs.size(); ++s) b.seq_id[i][s] = seqs[s];
    b.logits[i] = logits;
  }
};

struct Scorer {
  llama_context* ctx;
  const llama_vocab* vocab;
  int n_vocab;
  llama_token eos;
  int max_tokens;
  int max_seqs;

  llama_memory_t Mem() { return llama_get_memory(ctx); }

  // 問いを評価して、最後の語片の分布の対数確率を返す（列 0..seqs-1 に属させる）
  bool Prompt(Batch& batch, const std::vector<llama_token>& prompt, int seqs, std::vector<float>* first) {
    std::vector<llama_seq_id> all(seqs);
    for (int s = 0; s < seqs; ++s) all[s] = s;
    batch.Clear();
    for (size_t i = 0; i < prompt.size(); ++i)
      batch.Add(prompt[i], static_cast<llama_pos>(i), all, i + 1 == prompt.size());
    if (llama_decode(ctx, batch.b) != 0) return false;
    const float* logits = llama_get_logits_ith(ctx, batch.b.n_tokens - 1);
    first->assign(logits, logits + n_vocab);
    return true;
  }

  // 戻り値: 評価した語片の数（失敗は -1）
  int Score(const std::string& mode, const std::vector<llama_token>& prompt,
            const std::vector<std::vector<llama_token>>& cands, std::vector<double>* scores) {
    const int k = static_cast<int>(cands.size());
    const llama_pos p0 = static_cast<llama_pos>(prompt.size());
    scores->assign(k, NAN);
    llama_memory_clear(Mem(), true);
    Batch batch(max_tokens, std::max(k, 1));
    std::vector<float> first;
    int evaluated = 0;
    if (mode == "trie") {
      // 語片の木を作る（根は問いの最後の語片）
      struct Node { llama_token tok; int parent; int depth; std::vector<llama_seq_id> seqs; };
      std::vector<Node> nodes;
      std::map<std::pair<int, llama_token>, int> child;
      std::vector<std::vector<int>> paths(k);
      for (int c = 0; c < k; ++c) {
        int parent = -1;
        for (size_t j = 0; j < cands[c].size(); ++j) {
          const auto key = std::make_pair(parent, cands[c][j]);
          auto it = child.find(key);
          int id;
          if (it == child.end()) {
            id = static_cast<int>(nodes.size());
            nodes.push_back({cands[c][j], parent, static_cast<int>(j), {}});
            child[key] = id;
          } else {
            id = it->second;
          }
          nodes[id].seqs.push_back(c);
          paths[c].push_back(id);
          parent = id;
        }
      }
      if (static_cast<int>(prompt.size() + nodes.size()) > max_tokens || k > max_seqs) return -1;
      std::vector<llama_seq_id> all(k);
      for (int s = 0; s < k; ++s) all[s] = s;
      batch.Clear();
      for (size_t i = 0; i < prompt.size(); ++i)
        batch.Add(prompt[i], static_cast<llama_pos>(i), all, i + 1 == prompt.size());
      const int base = batch.b.n_tokens;
      for (const Node& n : nodes) batch.Add(n.tok, p0 + n.depth, n.seqs, true);
      if (llama_decode(ctx, batch.b) != 0) return -1;
      evaluated = batch.b.n_tokens;
      for (int c = 0; c < k; ++c) {
        double sum = 0;
        int prev = base - 1;
        for (int id : paths[c]) {
          sum += LogProb(llama_get_logits_ith(ctx, prev), n_vocab, nodes[id].tok);
          prev = base + id;
        }
        (*scores)[c] = sum;
      }
      return evaluated;
    }
    if (mode == "flat") {
      if (k > max_seqs) return -1;
      if (!Prompt(batch, prompt, 1, &first)) return -1;
      evaluated += static_cast<int>(prompt.size());
      for (int c = 1; c < k; ++c) llama_memory_seq_cp(Mem(), 0, c, -1, -1);
      batch.Clear();
      std::vector<int> start(k);
      for (int c = 0; c < k; ++c) {
        start[c] = batch.b.n_tokens;
        if (batch.b.n_tokens + static_cast<int>(cands[c].size()) > max_tokens) return -1;
        for (size_t j = 0; j < cands[c].size(); ++j)
          batch.Add(cands[c][j], p0 + static_cast<llama_pos>(j), {c}, true);
      }
      if (llama_decode(ctx, batch.b) != 0) return -1;
      evaluated += batch.b.n_tokens;
      for (int c = 0; c < k; ++c) {
        double sum = LogProb(first.data(), n_vocab, cands[c][0]);
        for (size_t j = 1; j < cands[c].size(); ++j)
          sum += LogProb(llama_get_logits_ith(ctx, start[c] + static_cast<int>(j) - 1), n_vocab, cands[c][j]);
        (*scores)[c] = sum;
      }
      return evaluated;
    }
    if (mode == "seq" || mode == "full") {
      for (int c = 0; c < k; ++c) {
        if (mode == "full" || c == 0) {
          llama_memory_clear(Mem(), true);
          if (!Prompt(batch, prompt, 1, &first)) return -1;
          evaluated += static_cast<int>(prompt.size());
        } else {
          llama_memory_seq_rm(Mem(), 0, p0, -1);
        }
        batch.Clear();
        for (size_t j = 0; j < cands[c].size(); ++j)
          batch.Add(cands[c][j], p0 + static_cast<llama_pos>(j), {0}, true);
        if (llama_decode(ctx, batch.b) != 0) return -1;
        evaluated += batch.b.n_tokens;
        double sum = LogProb(first.data(), n_vocab, cands[c][0]);
        for (size_t j = 1; j < cands[c].size(); ++j)
          sum += LogProb(llama_get_logits_ith(ctx, static_cast<int>(j) - 1), n_vocab, cands[c][j]);
        (*scores)[c] = sum;
      }
      return evaluated;
    }
    return -1;
  }
};

}  // namespace

int main(int argc, char** argv) {
  if (argc < 6) {
    std::fprintf(stderr, "使い方: jev_score <model.gguf> <jobs.tsv> <out.tsv> <スレッド数> <方式,…> [候補の数の上限]\n");
    return 2;
  }
  const std::string model_path = argv[1];
  const int threads = std::atoi(argv[4]);
  std::vector<std::string> modes;
  {
    std::stringstream ss(argv[5]);
    std::string m;
    while (std::getline(ss, m, ',')) modes.push_back(m);
  }
  const int max_cands = argc > 6 ? std::atoi(argv[6]) : 64;

  llama_backend_init();
  ggml_backend_load_all();
  llama_model_params mp = llama_model_default_params();
  // zenz の GGUF の前処理の名前は新しい llama.cpp が知らないので、default として読む
  std::vector<llama_model_kv_override> overrides(2);
  std::memset(overrides.data(), 0, sizeof(llama_model_kv_override) * overrides.size());
  std::snprintf(overrides[0].key, sizeof(overrides[0].key), "%s", "tokenizer.ggml.pre");
  overrides[0].tag = LLAMA_KV_OVERRIDE_TYPE_STR;
  std::snprintf(overrides[0].val_str, sizeof(overrides[0].val_str), "%s", "default");
  mp.kv_overrides = overrides.data();
  llama_model* model = llama_model_load_from_file(model_path.c_str(), mp);
  if (!model) {
    std::fprintf(stderr, "模型を読めない: %s\n", model_path.c_str());
    return 1;
  }
  llama_context_params cp = llama_context_default_params();
  cp.n_ctx = 8192;
  cp.n_batch = 4096;
  cp.n_ubatch = 4096;
  cp.n_seq_max = std::min(max_cands, 64);
  cp.kv_unified = true;
  cp.n_threads = threads;
  cp.n_threads_batch = threads;
  cp.no_perf = true;
  llama_context* ctx = llama_init_from_model(model, cp);
  if (!ctx) {
    std::fprintf(stderr, "文脈を作れない\n");
    return 1;
  }
  Scorer scorer{ctx, llama_model_get_vocab(model), 0, 0, 4096, static_cast<int>(cp.n_seq_max)};
  scorer.n_vocab = llama_vocab_n_tokens(scorer.vocab);
  scorer.eos = llama_vocab_eos(scorer.vocab);

  std::ifstream in(argv[2]);
  std::ofstream out(argv[3]);
  std::string line;
  // 最初の1行は温める（読み込み直後の遅さを測らない）
  bool warmed = false;
  int done = 0;
  while (std::getline(in, line)) {
    if (line.empty()) continue;
    const auto f = SplitTab(line);
    if (f.size() < 3) continue;
    const auto prompt = Tokenize(scorer.vocab, f[1]);
    std::vector<std::vector<llama_token>> cands;
    for (size_t i = 2; i < f.size() && static_cast<int>(cands.size()) < max_cands; ++i) {
      auto t = Tokenize(scorer.vocab, f[i]);
      t.push_back(scorer.eos);
      cands.push_back(std::move(t));
    }
    if (prompt.empty() || cands.empty()) continue;
    std::vector<double> scores;
    if (!warmed) {
      for (const auto& m : modes) scorer.Score(m, prompt, cands, &scores);
      warmed = true;
    }
    for (const auto& m : modes) {
      const auto t0 = std::chrono::steady_clock::now();
      const int evaluated = scorer.Score(m, prompt, cands, &scores);
      const double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
      out << f[0] << '\t' << m << '\t' << prompt.size() << '\t' << evaluated << '\t' << ms;
      for (double s : scores) {
        char buf[32];
        std::snprintf(buf, sizeof(buf), "%.4f", s);
        out << '\t' << buf;
      }
      out << '\n';
    }
    if (++done % 200 == 0) {
      std::fprintf(stderr, "%d 行\n", done);
      out.flush();
    }
  }
  llama_free(ctx);
  llama_model_free(model);
  llama_backend_free();
  return 0;
}
