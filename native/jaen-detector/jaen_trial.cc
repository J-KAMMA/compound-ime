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
#include <algorithm>
#include <cstdlib>
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
  const jaen::ReadingCheck natural = [&](std::string_view kana) {
    if (!natural_limit) return g_readings.count(std::string(kana)) > 0;
    auto it = g_cost.find(std::string(kana));
    return it != g_cost.end() && it->second < natural_limit;
  };
  const bool dump_chunks = getenv("DUMP_CHUNKS");
  for (std::string line; std::getline(std::cin, line);) {
    if (!line.empty() && line.back() == '\r') line.pop_back();
    const auto chunks = Parse(line);
    if (dump_chunks) {
      for (const auto& c : chunks) std::cout << "[" << c.raw << "|" << c.conversion << "|" << c.pending << "]";
      std::cout << "\n";
    }
    const auto pieces = use_reading ? jaen::SplitEnglish(chunks, lex, parse, nullptr, &is_reading, &natural)
                                    : jaen::SplitEnglish(chunks, lex, parse);
    std::cout << line << '\t';
    const char* sep = "";
    for (const auto& piece : pieces) {
      if (!piece.english) continue;
      std::string w = line.substr(piece.begin, piece.end - piece.begin);
      for (size_t k = piece.spaces.size(); k-- > 0;) {
        if (piece.spaces[k] > piece.begin) w.insert(piece.spaces[k] - piece.begin, " ");
      }
      std::cout << sep << w;
      sep = ",";
    }
    std::cout << '\n';
  }
  return 0;
}
