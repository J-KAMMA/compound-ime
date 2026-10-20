// 判定の門を IME から呼ぶための入り口の実装（jev_gate.h）。
#define JEVGATE_THREAD_POOL 1
#include "jev_gate.h"

#include <cstdint>
#include <fstream>
#include <memory>
#include <mutex>
#include <sstream>
#include <unordered_map>

#include "jevgate_core.h"

namespace jev_gate {
namespace {

constexpr int kUnk = 1, kCls = 2, kSep = 3, kEoc = 4, kNSpecial = 5;
constexpr int kTypeSpecial = 0, kTypePrev = 1, kTypeRead = 2, kTypeCand = 3;

struct State {
  std::mutex mu;
  bool tried = false, ok = false;
  jevgate::Model model;
  std::unordered_map<uint32_t, int> index;  // 文字 → 番号
  int prev_chars = 24, read_chars = 64, cand_chars = 40;
  std::unique_ptr<jevgate::Runner> runner;
};

State& S() {
  static State* s = new State();
  return *s;
}

// UTF-8 を符号位置の列にする（壊れた並びは UNK 扱いの 0xFFFD にする）
std::vector<uint32_t> Decode(const std::string& s) {
  std::vector<uint32_t> out;
  size_t i = 0;
  while (i < s.size()) {
    const unsigned char c = static_cast<unsigned char>(s[i]);
    uint32_t cp = 0xFFFD;
    size_t n = 1;
    if (c < 0x80) {
      cp = c;
    } else if ((c >> 5) == 6 && i + 1 < s.size()) {
      cp = ((c & 0x1F) << 6) | (s[i + 1] & 0x3F);
      n = 2;
    } else if ((c >> 4) == 14 && i + 2 < s.size()) {
      cp = ((c & 0x0F) << 12) | ((s[i + 1] & 0x3F) << 6) | (s[i + 2] & 0x3F);
      n = 3;
    } else if ((c >> 3) == 30 && i + 3 < s.size()) {
      cp = ((c & 0x07) << 18) | ((s[i + 1] & 0x3F) << 12) | ((s[i + 2] & 0x3F) << 6) | (s[i + 3] & 0x3F);
      n = 4;
    }
    out.push_back(cp);
    i += n;
  }
  return out;
}

void AppendUtf8(uint32_t cp, std::string* out) {
  if (cp < 0x80) {
    out->push_back(static_cast<char>(cp));
  } else if (cp < 0x800) {
    out->push_back(static_cast<char>(0xC0 | (cp >> 6)));
    out->push_back(static_cast<char>(0x80 | (cp & 0x3F)));
  } else if (cp < 0x10000) {
    out->push_back(static_cast<char>(0xE0 | (cp >> 12)));
    out->push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3F)));
    out->push_back(static_cast<char>(0x80 | (cp & 0x3F)));
  } else {
    out->push_back(static_cast<char>(0xF0 | (cp >> 18)));
    out->push_back(static_cast<char>(0x80 | ((cp >> 12) & 0x3F)));
    out->push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3F)));
    out->push_back(static_cast<char>(0x80 | (cp & 0x3F)));
  }
}

// jevgate.py export が書く json（ensure_ascii=False）から "chars" の文字の並びと cfg の字数を読む
bool ReadVocabJson(const std::string& path, State* st) {
  std::ifstream in(path, std::ios::binary);
  if (!in) return false;
  std::stringstream ss;
  ss << in.rdbuf();
  const std::string j = ss.str();
  auto find_int = [&](const char* key, int fallback) {
    const std::string needle = std::string("\"") + key + "\"";
    const size_t p = j.find(needle);
    if (p == std::string::npos) return fallback;
    size_t q = j.find(':', p);
    if (q == std::string::npos) return fallback;
    return std::atoi(j.c_str() + q + 1);
  };
  st->prev_chars = find_int("prev_chars", 24);
  st->read_chars = find_int("read_chars", 64);
  st->cand_chars = find_int("cand_chars", 40);
  size_t p = j.find("\"chars\"");
  if (p == std::string::npos) return false;
  p = j.find('[', p);
  if (p == std::string::npos) return false;
  ++p;
  int id = kNSpecial;
  while (p < j.size()) {
    while (p < j.size() && (j[p] == ' ' || j[p] == ',' || j[p] == '\n' || j[p] == '\r' || j[p] == '\t')) ++p;
    if (p >= j.size() || j[p] == ']') break;
    if (j[p] != '"') return false;
    ++p;
    std::string s;
    while (p < j.size() && j[p] != '"') {
      if (j[p] == '\\' && p + 1 < j.size()) {
        const char e = j[p + 1];
        p += 2;
        if (e == 'u' && p + 4 <= j.size()) {
          uint32_t cp = static_cast<uint32_t>(std::strtoul(j.substr(p, 4).c_str(), nullptr, 16));
          p += 4;
          if (cp >= 0xD800 && cp < 0xDC00 && p + 6 <= j.size() && j[p] == '\\' && j[p + 1] == 'u') {
            const uint32_t lo = static_cast<uint32_t>(std::strtoul(j.substr(p + 2, 4).c_str(), nullptr, 16));
            cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00);
            p += 6;
          }
          AppendUtf8(cp, &s);
        } else if (e == 'n') {
          s.push_back('\n');
        } else if (e == 't') {
          s.push_back('\t');
        } else if (e == 'r') {
          s.push_back('\r');
        } else if (e == 'b') {
          s.push_back('\b');
        } else if (e == 'f') {
          s.push_back('\f');
        } else {
          s.push_back(e);  // \" \\ \/
        }
      } else {
        s.push_back(j[p++]);
      }
    }
    ++p;  // 閉じの引用符
    const auto cps = Decode(s);
    if (cps.size() == 1) st->index.emplace(cps[0], id);
    ++id;
  }
  return id - kNSpecial > 0;
}

std::vector<int> Encode(const State& st, const std::vector<uint32_t>& cps, size_t from, size_t to) {
  std::vector<int> ids;
  for (size_t i = from; i < to && i < cps.size(); ++i) {
    const auto it = st.index.find(cps[i]);
    ids.push_back(it == st.index.end() ? kUnk : it->second);
  }
  return ids;
}

// 前の文の最後の行の終わり n 字（jevgate.py の last_line_tail）
std::vector<uint32_t> LastLineTail(const std::string& prev, int n) {
  auto cps = Decode(prev);
  size_t start = 0;
  for (size_t i = 0; i < cps.size(); ++i)
    if (cps[i] == '\n') start = i + 1;
  std::vector<uint32_t> line(cps.begin() + start, cps.end());
  if (n <= 0) return {};
  if (static_cast<int>(line.size()) > n) line.erase(line.begin(), line.end() - n);
  return line;
}

jevgate::Input BuildInput(const State& st, const std::string& prev, const std::string& reading, const std::vector<Cand>& cands) {
  jevgate::Input in;
  auto push = [&](int tok, int typ, int pos, int rank, int src, int seg) {
    in.tok.push_back(tok);
    in.typ.push_back(typ);
    in.pos.push_back(pos);
    in.rank.push_back(rank);
    in.src.push_back(src);
    in.seg.push_back(seg);
  };
  const jevgate::Config& c = st.model.c;
  const auto prev_ids = Encode(st, LastLineTail(prev, st.prev_chars), 0, 1u << 30);
  const auto rcps = Decode(reading);
  const auto read_ids = Encode(st, rcps, 0, static_cast<size_t>(st.read_chars));
  int n = 0;
  auto ppos = [&](int i) { return std::min(i, c.max_prefix_pos - 1); };
  push(kCls, kTypeSpecial, ppos(n++), 0, 0, 0);
  for (int id : prev_ids) push(id, kTypePrev, ppos(n++), 0, 0, 0);
  push(kSep, kTypeSpecial, ppos(n++), 0, 0, 0);
  for (int id : read_ids) push(id, kTypeRead, ppos(n++), 0, 0, 0);
  push(kSep, kTypeSpecial, ppos(n++), 0, 0, 0);
  const int k = std::min<int>(st.model.c.k, static_cast<int>(cands.size()));
  for (int j = 0; j < k; ++j) {
    auto ids = Encode(st, Decode(cands[j].text), 0, static_cast<size_t>(st.cand_chars));
    ids.push_back(kEoc);
    for (size_t i = 0; i < ids.size(); ++i)
      push(ids[i], kTypeCand, std::min<int>(static_cast<int>(i), c.max_cand_pos - 1), std::min(j, c.max_rank - 1),
           cands[j].src, j + 1);
  }
  return in;
}

}  // namespace

bool Load(const std::string& model_path, int threads) {
  State& st = S();
  std::lock_guard<std::mutex> lock(st.mu);
  if (st.tried) return st.ok;
  st.tried = true;
#if defined(__x86_64__) || defined(_M_X64)
#if defined(__GNUC__)
  if (!__builtin_cpu_supports("avx2") || !__builtin_cpu_supports("fma")) return false;
#endif
#endif
  if (!jevgate::LoadModel(model_path, &st.model)) return false;
  if (st.model.c.version < 2 || st.model.c.k < 1) return false;
  if (!ReadVocabJson(model_path + ".vocab.json", &st)) return false;
  const int hardware = std::max(1, static_cast<int>(std::thread::hardware_concurrency()));
  if (threads <= 0) threads = hardware;
  threads = std::max(1, std::min({threads, hardware, 4}));
  jevgate::SetThreads(threads);
  st.runner = std::make_unique<jevgate::Runner>(st.model);
  st.ok = true;
  return true;
}

bool Loaded() { return S().ok; }

int CandidateLimit() { return S().ok ? S().model.c.k : 0; }

bool Predict(const std::string& prev, const std::string& reading, const std::vector<Cand>& cands, Result* out) {
  State& st = S();
  if (!st.ok || out == nullptr || cands.empty()) return false;
  std::lock_guard<std::mutex> lock(st.mu);
  const auto t0 = std::chrono::steady_clock::now();
  const jevgate::Input in = BuildInput(st, prev, reading, cands);
  jevgate::Output o;
  st.runner->Run(in, &o);
  if (o.gate.size() < 4) return false;
  out->need = o.gate[0];
  out->need_k = o.gate[1];
  out->need_top1 = o.gate[2];
  out->harm_k = o.gate[3];
  out->score = o.score;
  out->best = o.best;
  out->ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
  return true;
}

bool DebugInput(const std::string& prev, const std::string& reading, const std::vector<Cand>& cands,
                std::vector<std::vector<int>>* arrays) {
  State& st = S();
  if (!st.ok || arrays == nullptr) return false;
  const jevgate::Input in = BuildInput(st, prev, reading, cands);
  *arrays = {in.tok, in.typ, in.pos, in.rank, in.src, in.seg};
  return true;
}

}  // namespace jev_gate
