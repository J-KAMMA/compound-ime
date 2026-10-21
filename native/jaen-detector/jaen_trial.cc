// 手元の試し用: Mozc なしで jaen::SplitEnglish を動かし、英語として切り出される部分を見る。
// ローマ字表は Mozc の写し（簡易）、日本語の読みの辞書は読みの一覧で代わりにする。
// 本物の変換とは細かく違う（Mozc の組み立ての癖、読みの自然さの費用）ので、語の一覧や
// 検出の変更を試すときの目安にする。最後は GitHub の試験で確かめる。
//   g++ -std=c++20 -O2 -static -I native/jaen-detector jaen_trial.cc native/jaen-detector/jaen_detector.cc -o jaen_trial
//   jaen_trial <作業の場所> [英単語の一覧の場所] < ローマ字の行
// 作業の場所に romaji.tsv（Mozc の romanji-hiragana.tsv）と、あれば readings.txt（日本語の読みを1行に1つ）、
// 環境変数 NATURAL_PROXY のとき readingcost.tsv（読み<TAB>費用）を置く。
// 英単語の一覧の場所: english-lexicon.txt curated-words.txt signal-words.txt common-words.txt joined.txt
//   phrases.txt places.tsv（tools/build_english_lexicon.py の出力と tools/data から組む）。
// 出力: 入力の行<TAB>英語として切り出した部分（コンマ区切り、2語の間は空白）。
// 環境変数 JAEN_DICT=<Mozc の data/dictionary_oss> で、本物と同じ読みの費用（自然な読みの判定）が使える。
// さらに CONTEXT=1 で、ローマ字として日本語に読める英単語を文脈で決める段（docs/all-english.md）も動く。
// CTX=名前=値,... でその段の費用を替える。READ_COST=1 なら、入力のかなの読みの費用を出す。
#include <algorithm>
#include <cstdint>
#include <cstdlib>
#include <limits>
#include <unordered_map>
#include <fstream>
#include <iostream>
#include <map>
#include <sstream>
#include <string>
#include <unordered_set>
#include <vector>

#include "jaen_detector.h"

struct Entry { std::string value, pending; };
static std::map<std::string, Entry> g_table;

static bool HasLonger(const std::string& k) {
  auto it = g_table.lower_bound(k);
  for (; it != g_table.end() && it->first.compare(0, k.size(), k) == 0; ++it) {
    if (it->first.size() > k.size()) return true;
  }
  return false;
}
static bool HasPrefixed(const std::string& k) {
  auto it = g_table.lower_bound(k);
  return it != g_table.end() && it->first.compare(0, k.size(), k) == 0;
}
static const Entry* LongestPrefixKey(const std::string& s, size_t* len) {
  for (size_t n = s.size(); n >= 1; --n) {
    auto it = g_table.find(s.substr(0, n));
    if (it != g_table.end()) { *len = n; return &it->second; }
  }
  return nullptr;
}

static std::vector<jaen::Chunk> Parse(std::string_view raw_view) {
  std::vector<jaen::Chunk> chunks;
  jaen::Chunk cur;
  bool open = false;
  auto close = [&]() { if (open) { chunks.push_back(cur); cur = jaen::Chunk(); open = false; } };
  std::string feed(raw_view);
  while (!feed.empty()) {
    const char c = feed[0];
    feed.erase(0, 1);
    open = true;
    const std::string k = cur.pending + c;
    if (HasPrefixed(k)) {
      auto it = g_table.find(k);
      if (it != g_table.end() && !HasLonger(k)) {
        cur.raw += c;
        cur.conversion += it->second.value;
        cur.pending = it->second.pending;
        if (cur.pending.empty()) close();
      } else {
        cur.raw += c;
        cur.pending = k;
      }
      continue;
    }
    size_t len = 0;
    const Entry* e = LongestPrefixKey(k, &len);
    if (e) {
      const std::string left = k.substr(len);
      cur.raw += c;
      cur.raw.erase(cur.raw.size() - left.size());
      cur.conversion += e->value;
      cur.pending = e->pending;
      close();
      feed = left + feed;
      continue;
    }
    if (cur.pending.empty() && cur.conversion.empty() && cur.raw.empty()) {
      cur.raw = std::string(1, c);
      cur.pending = std::string(1, c);
      close();
      continue;
    }
    close();
    feed = std::string(1, c) + feed;
  }
  close();
  return chunks;
}

// 手元の読みの費用: 環境変数 JAEN_DICT=<Mozc の data/dictionary_oss> のとき、辞書（dictionary*.txt）と
// 接続の費用（connection_single_column.txt）を読み、converter_readable_typo.inc の ReadingCost と同じ
// 計算（語の費用＋接続の費用、各位置で安い30状態、知らないかなは名詞一般 8000）で読みの費用を出す。
// 英語の別名・利用者の辞書などは入っていないので、本物とは細かく違う。
struct DictEntry { uint16_t lid, rid; int cost; bool japanese; };
static std::unordered_map<std::string, std::vector<DictEntry>> g_dict;
static std::vector<int16_t> g_conn;
static int g_conn_size = 0;
static bool g_have_dict = false;
// 値がカタカナだけ・英字だけで、かなそのもののカタカナでないもの（英語の別名）は日本語の読みにしない
// （converter_reading_check.inc の ReadsAsJapanese と同じ考え）。
static std::string KataOf(const std::string& s) {
  std::string out;
  for (size_t i = 0; i < s.size();) {
    const unsigned char b = s[i];
    const size_t len = b < 0x80 ? 1 : b < 0xE0 ? 2 : b < 0xF0 ? 3 : 4;
    if (len == 3) {
      uint32_t c = ((b & 0x0F) << 12) | ((static_cast<unsigned char>(s[i + 1]) & 0x3F) << 6) | (static_cast<unsigned char>(s[i + 2]) & 0x3F);
      if (c >= 0x3041 && c <= 0x3096) c += 0x60;
      out += static_cast<char>(0xE0 | (c >> 12));
      out += static_cast<char>(0x80 | ((c >> 6) & 0x3F));
      out += static_cast<char>(0x80 | (c & 0x3F));
    } else {
      out.append(s, i, len);
    }
    i += len;
  }
  return out;
}
static bool IsJapaneseValue(const std::string& key, const std::string& value) {
  bool all_kata = true, all_alpha = true;
  for (size_t i = 0; i < value.size();) {
    const unsigned char b = value[i];
    const size_t len = b < 0x80 ? 1 : b < 0xE0 ? 2 : b < 0xF0 ? 3 : 4;
    if (len == 3) {
      const uint32_t c = ((b & 0x0F) << 12) | ((static_cast<unsigned char>(value[i + 1]) & 0x3F) << 6) | (static_cast<unsigned char>(value[i + 2]) & 0x3F);
      if (!((c >= 0x30A1 && c <= 0x30FA) || c == 0x30FC || c == 0x30FB)) all_kata = false;
      all_alpha = false;
    } else {
      all_kata = false;
      if (!(len == 1 && isalpha(b))) all_alpha = false;
    }
    i += len;
  }
  return (!all_kata && !all_alpha) || value == KataOf(key);
}
static int Transition(int rid, int lid) { return g_conn[static_cast<size_t>(rid) * g_conn_size + lid]; }
static void LoadDict(const std::string& dir) {
  {
    std::ifstream f(dir + "/connection_single_column.txt");
    std::string l;
    std::getline(f, l);
    g_conn_size = atoi(l.c_str());
    g_conn.reserve(static_cast<size_t>(g_conn_size) * g_conn_size);
    while (std::getline(f, l)) g_conn.push_back(static_cast<int16_t>(atoi(l.c_str())));
  }
  for (int n = 0; n < 20; ++n) {
    char name[64];
    snprintf(name, sizeof name, "/dictionary%02d.txt", n);
    std::ifstream f(dir + name);
    if (!f) continue;
    for (std::string l; std::getline(f, l);) {
      const size_t a = l.find('\t'), b = l.find('\t', a + 1), c = l.find('\t', b + 1), d = l.find('\t', c + 1);
      if (d == std::string::npos) continue;
      const std::string key = l.substr(0, a);
      g_dict[key].push_back({static_cast<uint16_t>(atoi(l.c_str() + a + 1)), static_cast<uint16_t>(atoi(l.c_str() + b + 1)),
                             atoi(l.c_str() + c + 1), IsJapaneseValue(key, l.substr(d + 1))});
    }
  }
  g_have_dict = true;
}
// start_rid/end_lid: 0 は文の頭・終わり、1851 は名詞（英単語の前後）。
static int64_t LocalReadingCost(const std::string& kana, int start_rid = 0, int end_lid = 0) {
  constexpr int kUnknownPos = 1851, kUnknownCost = 8000;
  constexpr size_t kBeam = 30;
  std::vector<size_t> at;
  for (size_t i = 0; i < kana.size();) {
    at.push_back(i);
    const unsigned char b = kana[i];
    i += b < 0x80 ? 1 : b < 0xE0 ? 2 : b < 0xF0 ? 3 : 4;
  }
  at.push_back(kana.size());
  const size_t n = at.size() - 1;
  std::vector<std::unordered_map<int, int64_t>> st(n + 1), kept(n + 1);
  st[0][start_rid] = 0;
  kept[0] = st[0];
  for (size_t k = 1; k <= n; ++k) {
    for (size_t i = 0; i < k; ++i) {
      if (kept[i].empty()) continue;
      auto it = g_dict.find(kana.substr(at[i], at[k] - at[i]));
      for (const auto& [rid, cost] : kept[i]) {
        auto step = [&](int lid, int nrid, int wc) {
          const int64_t t = cost + wc + Transition(rid, lid);
          auto [e, added] = st[k].try_emplace(nrid, t);
          if (!added && t < e->second) e->second = t;
        };
        if (it != g_dict.end()) for (const auto& e : it->second) step(e.lid, e.rid, e.cost);
        if (i + 1 == k) step(kUnknownPos, kUnknownPos, kUnknownCost);
      }
    }
    if (st[k].size() > kBeam) {
      std::vector<std::pair<int, int64_t>> v(st[k].begin(), st[k].end());
      std::nth_element(v.begin(), v.begin() + kBeam, v.end(), [](auto& x, auto& y) { return x.second < y.second; });
      v.resize(kBeam);
      kept[k] = std::unordered_map<int, int64_t>(v.begin(), v.end());
    } else {
      kept[k] = st[k];
    }
  }
  int64_t best = std::numeric_limits<int64_t>::max();
  for (const auto& [rid, cost] : st[n]) best = std::min(best, cost + Transition(rid, end_lid));
  return best;
}

static std::unordered_set<std::string> g_readings;
static std::map<std::string, int> g_cost;

static std::vector<std::string> ReadLines(const std::string& p) {
  std::vector<std::string> out;
  std::ifstream f(p);
  for (std::string l; std::getline(f, l);) {
    if (!l.empty() && l.back() == '\r') l.pop_back();
    out.push_back(l);
  }
  return out;
}

int main(int argc, char** argv) {
  const std::string W = argv[1];
  for (const auto& l : ReadLines(W + "/romaji.tsv")) {
    if (l.empty() || l[0] == '#') continue;
    std::vector<std::string> p;
    std::stringstream ss(l);
    for (std::string t; std::getline(ss, t, '\t');) p.push_back(t);
    if (p.size() < 2) continue;
    g_table[p[0]] = {p[1], p.size() > 2 ? p[2] : ""};
  }
  jaen::Lexicon lex;
  const std::string L = argc > 2 ? argv[2] : "";
  if (!L.empty()) {
    for (const auto& w : ReadLines(L + "/english-lexicon.txt")) lex.Add(w);
    for (const auto& w : ReadLines(L + "/curated-words.txt")) lex.Add(w, true);
    for (const auto& w : ReadLines(L + "/joined.txt")) lex.AddJoined(w);
    for (const auto& w : ReadLines(L + "/phrases.txt")) if (!w.empty() && w[0] != '#') lex.AddPhrase(w);
    for (const auto& w : ReadLines(L + "/common-words.txt")) lex.AddCommon(w);
    for (const auto& w : ReadLines(L + "/signal-words.txt")) lex.AddSignalOnly(w);
    // あれば: 固有名詞の打つ形（signal-names.txt）と略語・サービス名（named.txt）。apply_jaen_integration.py と同じ足し方。
    for (const auto& w : ReadLines(L + "/signal-names.txt")) lex.AddSignalOnly(w);
    for (const auto& w : ReadLines(L + "/named.txt")) lex.AddNamed(w);
    for (const auto& l : ReadLines(L + "/places.tsv")) {
      std::vector<std::string> p;
      std::stringstream ss(l);
      for (std::string t; std::getline(ss, t, '\t');) p.push_back(t);
      if (p.size() == 3) lex.AddPlace(p[0], p[1], p[2]);
    }
  }
  const bool use_reading = !getenv("NO_READING");
  if (use_reading) for (const auto& r : ReadLines(W + "/readings.txt")) g_readings.insert(r);
  const jaen::RomajiParser parse = [](std::string_view raw) { return Parse(raw); };
  const jaen::ReadingCheck is_reading = [](std::string_view kana) { return g_readings.count(std::string(kana)) > 0; };
  if (getenv("NATURAL_PROXY")) {
    for (const auto& l : ReadLines(W + "/readingcost.tsv")) {
      const auto t = l.find('	');
      if (t != std::string::npos) g_cost[l.substr(0, t)] = atoi(l.c_str() + t + 1);
    }
  }
  const int natural_limit = getenv("NATURAL_PROXY") ? atoi(getenv("NATURAL_PROXY")) : 0;
  if (const char* d = getenv("JAEN_DICT")) LoadDict(d);
  std::unordered_map<std::string, int64_t> cost_cache;
  const jaen::ReadingCheck natural = [&](std::string_view kana) {
    if (g_have_dict) {
      // 本物と同じ: 辞書で日本語の読み、かつ読みの費用が 6600 未満
      if (!g_readings.count(std::string(kana))) return false;
      auto it = cost_cache.find(std::string(kana));
      if (it == cost_cache.end()) it = cost_cache.emplace(std::string(kana), LocalReadingCost(std::string(kana))).first;
      return it->second < 6600;
    }
    if (!natural_limit) return g_readings.count(std::string(kana)) > 0;
    auto it = g_cost.find(std::string(kana));
    return it != g_cost.end() && it->second < natural_limit;
  };
  // READ_COST=1: 入力の各行（かな）の読みの費用を出す（JAEN_DICT が要る）
  if (getenv("READ_COST")) {
    for (std::string line; std::getline(std::cin, line);) std::cout << line << '\t' << LocalReadingCost(line) << '\n';
    return 0;
  }
  // CONTEXT=1: 文脈で決める段（JAEN_DICT が要る）。CTX=名前=値,... で費用を替える（下の CTX の説明）。
  jaen::JapaneseModel model;
  jaen::ContextCosts ctx = jaen::DefaultContextCosts();
  const bool use_context = getenv("CONTEXT") && g_have_dict;
  if (use_context) {
    model.prefix_words = [](std::string_view kana, std::vector<jaen::JapaneseWord>* words) {
      size_t bytes = 0;
      for (int k = 0; k < 12 && bytes < kana.size(); ++k) {
        const unsigned char b = kana[bytes];
        bytes += b < 0x80 ? 1 : b < 0xE0 ? 2 : b < 0xF0 ? 3 : 4;
        auto it = g_dict.find(std::string(kana.substr(0, bytes)));
        if (it == g_dict.end()) continue;
        for (const auto& e : it->second) if (e.japanese) words->push_back({bytes, e.lid, e.rid, e.cost});
      }
    };
    model.transition = [](uint16_t rid, uint16_t lid) { return Transition(rid, lid); };
    // CTX=名前=値,...（word_base per_letter rare_extra common_bonus run_start run_end short_extra particle_extra
    // one_letter_extra margin alone_margin）で費用を替える
    if (const char* c = getenv("CTX")) {
      std::stringstream ss(c);
      for (std::string t; std::getline(ss, t, ',');) {
        const size_t eq = t.find('=');
        if (eq == std::string::npos) continue;
        const std::string k = t.substr(0, eq);
        const int v = atoi(t.c_str() + eq + 1);
        if (k == "word_base") ctx.word_base = v;
        else if (k == "per_letter") ctx.per_letter = v;
        else if (k == "rare_extra") ctx.rare_extra = v;
        else if (k == "common_bonus") ctx.common_bonus = v;
        else if (k == "run_start") ctx.run_start = v;
        else if (k == "run_end") ctx.run_end = v;
        else if (k == "short_extra") ctx.short_extra = v;
        else if (k == "particle_extra") ctx.particle_extra = v;
        else if (k == "one_letter_extra") ctx.one_letter_extra = v;
        else if (k == "margin") ctx.margin = v;
        else if (k == "alone_margin") ctx.alone_margin = v;
      }
    }
  }
  const bool dump_chunks = getenv("DUMP_CHUNKS");
  for (std::string line; std::getline(std::cin, line);) {
    if (!line.empty() && line.back() == '\r') line.pop_back();
    const auto chunks = Parse(line);
    if (dump_chunks) {
      for (const auto& c : chunks) std::cout << "[" << c.raw << "|" << c.conversion << "|" << c.pending << "]";
      std::cout << "\n";
    }
    const auto pieces = use_reading ? jaen::SplitEnglish(chunks, lex, parse, nullptr, &is_reading, &natural, use_context ? &model : nullptr, &ctx)
                                    : jaen::SplitEnglish(chunks, lex, parse);
    std::cout << line << '\t';
    const char* sep = "";
    for (const auto& piece : pieces) {
      if (!piece.english) continue;
      std::string w = line.substr(piece.begin, piece.end - piece.begin);
      // piece.spaces is in descending order, so the later positions are not shifted.
      for (const size_t at : piece.spaces) {
        if (at > piece.begin) w.insert(at - piece.begin, " ");
      }
      std::cout << sep << w;
      sep = ",";
    }
    std::cout << '\n';
  }
  return 0;
}
