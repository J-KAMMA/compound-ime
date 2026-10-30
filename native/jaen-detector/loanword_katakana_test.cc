// 単体試験（loanword_katakana.inc だけで動く）:
//   g++ -std=c++20 -O2 loanword_katakana_test.cc -o loanword_katakana_test && ./loanword_katakana_test
// 最後の行が「SUMMARY<TAB>0」なら全部通っている。
//
// 引数にファイルを渡すと、その各行（読み<TAB>最良の道<TAB>期待するカタカナの語）について
// FindSpans の答えが期待と同じかを見る。最良の道は「始め,終わり,活用語,機能語,表記」を | で
// つないだもの（始めと終わりは読みのバイト位置）、期待は「始め,終わり,カタカナ」を並べ替えて
// | でつないだもの。Mozc の辞書と連接表で作った道（Python の見積もりと同じ決め方）で、
// C++ とPython の決め方が食い違わないことを確かめるのに使う。
#include <algorithm>
#include <cstddef>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <string_view>
#include <vector>

namespace {
#include "loanword_katakana.inc"

int failures = 0;
void Expect(bool ok, const std::string& name) {
  if (!ok) {
    ++failures;
    std::cout << "FAIL\t" << name << '\n';
  }
}

using loanword_katakana::PathNode;
using loanword_katakana::Span;

// Builds a path over `key` from node values and their kana lengths in bytes
// (one kana is 3 bytes). Flags: 'c' conjugating, 'f' functional.
struct Piece {
  std::string value;
  std::string reading;
  char flag = 0;
};

std::vector<PathNode> Path(const std::vector<Piece>& pieces, std::string* key, size_t start = 0) {
  std::vector<PathNode> path;
  size_t at = start;
  for (const Piece& p : pieces) {
    PathNode node;
    node.begin = at;
    node.end = at + p.reading.size();
    node.value = p.value;
    node.conjugating = p.flag == 'c';
    node.functional = p.flag == 'f';
    path.push_back(node);
    key->append(p.reading);
    at = node.end;
  }
  return path;
}

std::string Values(const std::vector<Span>& spans) {
  std::string out;
  for (const Span& s : spans) {
    if (!out.empty()) out += '|';
    out += s.value;
  }
  return out;
}

void Case(const std::string& name, const std::vector<Piece>& pieces, const std::string& expected) {
  std::string key;
  const auto path = Path(pieces, &key);
  const std::string got = Values(loanword_katakana::FindSpans(key, 0, path));
  if (got != expected) std::cout << "  got [" << got << "] want [" << expected << "]\n";
  Expect(got == expected, name);
}

std::vector<std::string> Split(const std::string& text, char sep) {
  std::vector<std::string> out;
  std::string item;
  std::istringstream in(text);
  while (std::getline(in, item, sep)) out.push_back(item);
  return out;
}

int CrossCheck(const char* file) {
  std::ifstream in(file, std::ios::binary);
  std::string line;
  int lines = 0, with_spans = 0, mismatches = 0;
  while (std::getline(in, line)) {
    if (!line.empty() && line.back() == '\r') line.pop_back();
    const auto cols = Split(line, '\t');
    if (cols.size() < 2) continue;
    ++lines;
    std::vector<PathNode> path;
    for (const auto& item : Split(cols[1], '|')) {
      const auto f = Split(item, ',');
      if (f.size() < 5) continue;
      PathNode node;
      node.begin = std::stoul(f[0]);
      node.end = std::stoul(f[1]);
      node.conjugating = f[2] == "1";
      node.functional = f[3] == "1";
      // The value itself may hold commas (、 is not one, but be safe).
      node.value = item.substr(f[0].size() + f[1].size() + f[2].size() + f[3].size() + 4);
      path.push_back(node);
    }
    std::vector<std::string> got;
    for (const Span& s : loanword_katakana::FindSpans(cols[0], 0, path))
      got.push_back(std::to_string(s.begin) + "," + std::to_string(s.end) + "," + s.value);
    std::sort(got.begin(), got.end());
    std::string joined;
    for (const auto& g : got) joined += (joined.empty() ? "" : "|") + g;
    const std::string want = cols.size() > 2 ? cols[2] : "";
    if (!want.empty()) ++with_spans;
    if (joined != want) {
      ++mismatches;
      std::cout << "MISMATCH\t" << cols[0] << "\tgot " << joined << "\twant " << want << '\n';
    }
  }
  std::cout << "CROSSCHECK\tlines " << lines << "\twith spans " << with_spans << "\tmismatches " << mismatches
            << '\n';
  return mismatches;
}
}  // namespace

int main(int argc, char** argv) {
  // 閻魔|ー|タール|は: the loanword stops before は.
  Case("enma-taaru", {{"閻魔", "えんま"}, {"ー", "ー", 'f'}, {"タール", "たーる"}, {"は", "は", 'f'}},
       "エンマータール");
  // ヘ|ー|メ|ルシェン|ブル|苦情: up to three nodes after the cut ー.
  Case("heemeru",
       {{"へ", "へ", 'f'}, {"ー", "ー", 'f'}, {"め", "め"}, {"ルシェン", "るしぇん"}, {"ブル", "ぶる"},
        {"苦情", "くじょう"}},
       "ヘーメ|ヘーメルシェン|ヘーメルシェンブル");
  // む|つ|ぃ|ん|じ: a small vowel cut from つ.
  Case("mutsuinji", {{"むつ", "むつ"}, {"ぃ", "ぃ", 'f'}, {"ん", "ん"}, {"児", "じ"}, {"報告", "ほうこく"}},
       "ムツィン|ムツィンジ");
  // ディア|ね|ー|是|者: one single-kanji node may be taken in, a second may not.
  Case("dianeeze", {{"ディア", "でぃあ"}, {"ね", "ね", 'f'}, {"ー", "ー", 'f'}, {"是", "ぜ"}, {"者", "しゃ"}},
       "ネーゼ");
  // ベル|ー|さ|大陸: a two-kanji word after the cut stays a word.
  Case("beruusa", {{"ベル", "べる"}, {"ー", "ー", 'f'}, {"さ", "さ"}, {"大陸", "たいりく"}}, "ベルーサ");
  // ほんと|ー|に, だめ|ー|って|言っ: a colloquial long vowel before a particle is left alone.
  Case("hontoo", {{"ほんと", "ほんと"}, {"ー", "ー", 'f'}, {"に", "に", 'f'}}, "");
  Case("damee", {{"だめ", "だめ"}, {"ー", "ー", 'f'}, {"って", "って", 'f'}, {"言っ", "いっ", 'c'}}, "");
  // い|い|な|ー: nothing after the ー.
  Case("iinaa", {{"いい", "いい", 'c'}, {"な", "な", 'f'}, {"ー", "ー", 'f'}}, "");
  // ねぇ, わぁ: a small vowel that repeats the vowel before it is no cut.
  Case("nee", {{"ね", "ね", 'f'}, {"ぇ", "ぇ", 'f'}, {"聞い", "きい", 'c'}, {"て", "て", 'f'}}, "");
  Case("waa", {{"わ", "わ"}, {"ぁ", "ぁ"}, {"すごい", "すごい", 'c'}}, "");
  // A verb right after the cut ends the loanword.
  Case("verb", {{"ア", "あ"}, {"ー", "ー", 'f'}, {"言う", "いう", 'c'}}, "");
  // し|ぇ|っと|綸言: a quote particle (っと) after the cut ends it too.
  Case("shietto", {{"と", "と", 'f'}, {"し", "し", 'c'}, {"ぇ", "ぇ", 'f'}, {"っと", "っと", 'f'}, {"綸言", "りんげん"}},
       "");
  // A ー right after another ー or after a non-kana reading is no cut.
  Case("double", {{"あー", "あー"}, {"ー", "ー", 'f'}, {"タ", "た"}}, "");
  // ゔ becomes ヴ.
  Case("vu", {{"ゔぃ", "ゔぃ"}, {"ー", "ー", 'f'}, {"ナス", "なす"}}, "ヴィーナス");
  // The span never starts with ー, っ, ん or a small kana.
  Case("nostart", {{"ん", "ん"}, {"ー", "ー", 'f'}, {"タール", "たーる"}}, "");
  // Nodes before the conversion (history) are not used.
  {
    std::string key = "えんま";
    auto path = Path({{"ー", "ー", 'f'}, {"タール", "たーる"}}, &key, key.size());
    path.insert(path.begin(), PathNode{0, 9, "閻魔", false, false});
    Expect(loanword_katakana::FindSpans(key, 9, path).empty(), "history");
    Expect(Values(loanword_katakana::FindSpans(key, 0, path)) == "エンマータール", "history-off");
  }
  // Costs grow with the length.
  {
    std::string key;
    const auto path = Path({{"閻魔", "えんま"}, {"ー", "ー", 'f'}, {"タール", "たーる"}}, &key);
    const auto spans = loanword_katakana::FindSpans(key, 0, path);
    Expect(spans.size() == 1 && spans[0].cost == 5000 + 500 * 7 && spans[0].begin == 0 &&
               spans[0].end == key.size(),
           "cost");
  }
  // The longest span is 16 kana.
  {
    std::string key;
    const auto path = Path({{"あ", "あ"}, {"ー", "ー", 'f'}, {"x", "かきくけこさしすせそたちつてと"}}, &key);
    Expect(loanword_katakana::FindSpans(key, 0, path).empty(), "too-long");
  }
  if (argc > 1) failures += CrossCheck(argv[1]);
  std::cout << "SUMMARY\t" << failures << '\n';
  return failures == 0 ? 0 : 1;
}
