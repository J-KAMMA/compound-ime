// Unit tests for context_words (前の文の語). Build:
//   g++ -std=c++20 -I native/jaen-detector native/jaen-detector/context_words_test.cc native/jaen-detector/context_words.cc
//   cl /std:c++20 /EHsc /utf-8 context_words_test.cc context_words.cc
#include "context_words.h"

#include <iostream>
#include <map>
#include <string>

namespace {
int failures = 0;
void Expect(bool ok, const char* name) {
  if (!ok) {
    ++failures;
    std::cout << "FAIL\t" << name << '\n';
  }
}

// A small dictionary: surface -> reading.
const std::multimap<std::string, std::string>& Dictionary() {
  static const auto* const dictionary = new std::multimap<std::string, std::string>{
      {"帰還", "きかん"}, {"機関", "きかん"}, {"期間", "きかん"}, {"金融", "きんゆう"},
      {"金融機関", "きんゆうきかん"}, {"粛正", "しゅくせい"}, {"粛清", "しゅくせい"}, {"伴", "とも"},
      {"伴", "ばん"}, {"馬", "うま"}, {"馬", "ば"}, {"蜀", "しょく"}, {"地方", "ちほう"}, {"地", "ち"},
      {"方", "ほう"}, {"方", "かた"}, {"海上", "かいじょう"}, {"神幸", "しんこう"}, {"使用", "しよう"},
      {"日", "ひ"}, {"日", "にち"}, {"弓", "ゆみ"}, {"川", "かわ"}, {"川", "せん"}, {"休戦", "きゅうせん"},
      {"弓", "きゅう"}};
  return *dictionary;
}
// Words whose reading is a prefix of the key (as Mozc's LookupPrefix).
const jaen::PrefixLookup kLookup = [](std::string_view key) {
  std::vector<jaen::DictionaryWord> out;
  for (const auto& [value, reading] : Dictionary()) {
    if (key.substr(0, reading.size()) == reading) out.push_back({value, reading});
  }
  return out;
};
std::string First(const jaen::ContextWords& words, std::string_view key, size_t begin = 0) {
  const auto matches = words.MatchAt(key, begin, &kLookup);
  return matches.empty() ? "" : matches[0].surface + ":" + std::to_string(matches[0].bytes);
}
}  // namespace

int main() {
  {
    const jaen::ContextWords words("エドサルは市民の避難を支援した。");
    Expect(First(words, "えどさるは") == "エドサル:12", "a katakana word reads as written (エドサル)");
    Expect(First(words, "あえどさるは").empty(), "only at the given place");
    Expect(First(words, "あえどさるは", 3) == "エドサル:12", "at a byte offset");
    Expect(words.MatchAt("えど", 0, &kLookup).empty(), "the whole reading must be there");
    Expect(words.MatchAt("えどさるは", 0, nullptr).size() == 1, "katakana without a dictionary");
  }
  {
    const jaen::ContextWords words("戦闘時はヴァネッサが現れ、パンとリクを連れて行った・ーー");
    Expect(words.HasKatakanaReading("ゔぁねっさ"), "ヴァ reads ゔぁ");
    Expect(First(words, "ぱんどうしでは") == "パン:6", "two kana are enough for katakana (パン)");
    Expect(First(words, "りくは") == "リク:6", "リク");
    Expect(!words.HasKatakanaReading("ーー") && !words.HasKatakanaReading(""), "long marks alone are no word");
  }
  {
    const jaen::ContextWords words("これら金融機関の帰還を支持した。");
    const auto matches = words.MatchAt("きかんぶたい", 0, &kLookup);
    bool kikan = false, kikan_period = false;
    for (const auto& m : matches) {
      kikan |= m.surface == "帰還" || m.surface == "機関";
      kikan_period |= m.surface == "期間";
    }
    Expect(kikan && !kikan_period, "dictionary words written before (帰還、機関), not other homophones (期間)");
    Expect(First(words, "きんゆうきかんの") == "金融機関:21", "the longest reading first");
    Expect(words.MatchAt("きかん", 0, nullptr).empty(), "kanji need the dictionary");
  }
  {
    const jaen::ContextWords words("これら金融機関に対する粛正のことを");
    Expect(First(words, "しゅくせいのことを") == "粛正:15", "粛正, not 粛清");
  }
  {
    // 伴馬 is no dictionary word: read one kanji at a time, only as the whole run.
    const jaen::ContextWords words("当日、伴馬を感激させた。");
    const auto matches = words.MatchAt("ともうまをかんげき", 0, &kLookup);
    Expect(!matches.empty() && matches[0].surface == "伴馬" && matches[0].composed && matches[0].bytes == 12,
           "a name read one kanji at a time (伴馬: ともうま)");
    Expect(First(words, "ばんばを") == "伴馬:9", "another reading of the pieces is also a reading");
    Expect(words.MatchAt("ともを", 0, &kLookup).empty(), "a part of the run is no match");
  }
  {
    // 蜀地方: 蜀 + 地方 (a dictionary word).
    const jaen::ContextWords words("困窮して蜀地方の富豪に頼った。");
    const auto matches = words.MatchAt("しょくちほうの", 0, &kLookup);
    Expect(!matches.empty() && matches[0].surface == "蜀地方" && matches[0].composed, "蜀地方 = しょく + ちほう");
    // 海上神幸 = 海上 + 神幸: two dictionary words, no single kanji.
    const jaen::ContextWords two("この海上神幸の存在から");
    const auto m = two.MatchAt("かいじょうしんこうの", 0, &kLookup);
    Expect(!m.empty() && m[0].surface == "海上神幸" && !m[0].composed, "two dictionary words make the run");
  }
  {
    // 弓川 read as きゅう + せん matches 休戦's reading: marked composed (the caller only fills kana with it).
    const jaen::ContextWords words("弓川に稽古をさせた。");
    const auto m = words.MatchAt("きゅうせんした", 0, &kLookup);
    Expect(!m.empty() && m[0].surface == "弓川" && m[0].composed, "a composed reading is marked");
  }
  {
    const jaen::ContextWords words("日を使用する。");
    Expect(First(words, "しようと") == "使用:9", "a three-kana reading counts");
    Expect(First(words, "ひを").empty(), "a single kanji is no word");
  }
  {
    // Only the last characters count.
    const std::string far = "エドサル" + std::string(300, 'a');
    const jaen::ContextWords words(far);
    Expect(words.empty(), "words more than 200 characters back are not used");
  }
  std::cout << "SUMMARY\t" << failures << '\n';
  return failures ? 1 : 0;
}
