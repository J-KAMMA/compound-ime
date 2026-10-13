// Standalone tests:
//   cl /std:c++20 /EHsc /utf-8 jaen_detector.cc jaen_choices.cc jaen_detector_test.cc
// A tiny greedy romaji table stands in for Mozc's; chunk shapes follow Mozc's
// composer (jaen_chunk_probe output): unknown keys stay pending.
#include "jaen_detector.h"
#include "jaen_choices.h"
#include "correction_log.h"

#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <set>
#include <string>
#include <vector>

namespace {
int failures = 0;
void Expect(bool ok, const char* name) {
  if (!ok) { ++failures; std::cout << "FAIL\t" << name << '\n'; }
}
using jaen::Chunk;
using jaen::Piece;
using Pieces = std::vector<Piece>;

const std::map<std::string, std::string> kTable = {
    {"a", "あ"}, {"i", "い"}, {"u", "う"}, {"e", "え"}, {"o", "お"}, {"ka", "か"}, {"ki", "き"},
    {"ku", "く"}, {"ke", "け"}, {"ko", "こ"}, {"kyo", "きょ"}, {"sa", "さ"}, {"shi", "し"},
    {"su", "す"}, {"se", "せ"}, {"ta", "た"}, {"te", "て"}, {"ti", "ち"}, {"to", "と"},
    {"na", "な"}, {"ni", "に"}, {"ne", "ね"}, {"no", "の"}, {"nn", "ん"}, {"ha", "は"},
    {"ma", "ま"}, {"me", "め"}, {"de", "で"}, {"go", "ご"}, {"pu", "ぷ"}, {"wo", "を"},
    {"gwo", "ぐぉ"}, {"le", "ぇ"}, {"ya", "や"}, {"mo", "も"}, {"re", "れ"}, {"ra", "ら"},
    {"tte", "って"}, {"da", "だ"}, {"chi", "ち"}, {"mi", "み"}, {"tsu", "つ"},
    {"do", "ど"}, {"xu", "ぅ"}, {"fi", "ふぃ"}, {"xtu", "っ"}, {"gi", "ぎ"}, {"li", "ぃ"},
    {"nu", "ぬ"}, {"xn", "ん"}, {"ga", "が"}, {"ri", "り"}, {"so", "そ"}};

// Greedy longest match; "n" before a consonant becomes ん; unknown keys pend.
std::vector<Chunk> Parse(std::string_view raw) {
  std::vector<Chunk> chunks;
  for (size_t i = 0; i < raw.size();) {
    size_t best = 0;
    for (size_t len = 1; len <= 3 && i + len <= raw.size(); ++len) {
      if (kTable.contains(std::string(raw.substr(i, len)))) best = len;
    }
    if (best > 0) {
      const std::string key(raw.substr(i, best));
      chunks.push_back({key, kTable.at(key), ""});
      i += best;
    } else if (i + 1 < raw.size() && raw[i + 1] == raw[i] && raw[i] != 'n' &&
               std::string_view("aiueo").find(raw[i]) == std::string_view::npos) {
      chunks.push_back({std::string(1, raw[i]), "っ", ""});  // doubled key: っ
      ++i;
    } else if (raw[i] == 'n' && i + 1 < raw.size()) {
      chunks.push_back({"n", "ん", ""});
      ++i;
    } else {
      chunks.push_back({std::string(1, raw[i]), "", std::string(1, raw[i])});
      ++i;
    }
  }
  return chunks;
}

std::string Text(std::string_view raw, const Pieces& pieces, bool english) {
  std::string out;
  for (const Piece& p : pieces) {
    if (p.english == english) out += std::string(raw.substr(p.begin, p.end - p.begin)) + "|";
  }
  return out;
}
}  // namespace

int main() {
  jaen::Lexicon lexicon;
  for (const char* w : {"google", "ogle", "meeting", "set", "sets", "same", "made", "kit", "ok",
                        "down", "load", "o'clock", "mail", "and", "ox", "file", "nax", "linux", "song", "remote", "kite", "note", "weekly", "report"}) {
    lexicon.Add(w);
  }
  lexicon.Add("youtube", true);
  lexicon.AddPlace("tokyo", "東京", "toukyou");
  lexicon.AddPlace("osaka", "大阪", "oosaka");
  lexicon.Add("slack", true);
  lexicon.Add("nec", true);
  lexicon.Add("chatgpt", true);
  const auto split = [&](std::string_view raw) {
    return std::pair{jaen::SplitEnglish(Parse(raw), lexicon, Parse), std::string(raw)};
  };
  const auto english = [&](std::string_view raw) {
    const auto [pieces, text] = split(raw);
    return Text(text, pieces, true);
  };

  Expect(english("kyouhagoogledekensaku") == "google|", "foreign word between Japanese");
  Expect(english("meetingwosetshita") == "meeting|set|", "word merged with wo; set before shi");
  Expect(english("downloadshita") == "download|", "adjacent words merge into one piece");
  Expect(english("youtubedemita") == "youtube|", "curated plain word");
  Expect(english("okdesu") == "ok|", "short word with pending key");
  Expect(english("mailwokaku") == "mail|", "word ending in a pending key before wo");

  Expect(english("samewomita").empty(), "romaji-readable word stays Japanese");
  Expect(english("mademachimasu").empty(), "Japanese reading stays");
  Expect(english("kittekudasai").empty(), "lexicon word cutting a Japanese chunk is not forced");
  Expect(english("k").empty(), "no lexicon word: foreign chunk stays");
  // A weak sign (x-typed small kana) is outweighed by one word, not by two.
  Expect(english("andoxuore").empty(), "weak sign does not justify two short words");
  Expect(english("fileda") == "file|", "one word explains a weak sign");
  Expect(english("naxtu").empty(), "never cut っ typed as xtu (\"nax\" is not taken)");
  Expect(english("necchuushouniki").empty(), "no word ends at the っ of っち (nec in necchuu)");
  Expect(english("chatgptttenani") == "chatgpt|", "a word may end before tte");
  Expect(english("slackkaramita") == "slack|", "a word may end before the same key (slack + kara)");
  Expect(english("linuxnokoma") == "linux|", "xn is ん, not a small kana: it may be cut");
  Expect(english("meetinggaarimasu") == "meeting|", "-ng before ga: んっ is not Japanese");
  {
    // Readings in the Japanese dictionary (toy): only these count as Japanese.
    const std::set<std::string> readings = {"きて", "この", "てがみ", "かいぎ", "で", "はれ"};
    const jaen::ReadingCheck is_reading = [&](std::string_view kana) {
      return readings.contains(std::string(kana));
    };
    const auto unread = [&](std::string_view raw) {
      std::string out;
      for (const Piece& p : jaen::SplitEnglish(Parse(raw), lexicon, Parse, nullptr, &is_reading)) {
        if (p.english) out += std::string(raw.substr(p.begin, p.end - p.begin)) + "|";
      }
      return out;
    };
    Expect(unread("kaigiharemotedesu") == "remote|", "a word whose kana is no reading stays English");
    Expect(unread("kitewoageta").empty(), "a word whose kana is a reading stays Japanese (kite: きて)");
    Expect(unread("konotegamiwomita").empty(), "no word across a 3-kana reading (note in kono|te|gami)");
    Expect(english("kaigiharemotedesu").empty(), "without the reading check nothing changes");
    const auto spaced = jaen::SplitEnglish(Parse("weeklyreportwokaku"), lexicon, Parse);
    Expect(spaced.size() == 2 && spaced[0].english && spaced[0].spaces == std::vector<size_t>{6},
           "a space between two words that are no word together");
    const auto joined = jaen::SplitEnglish(Parse("downloadshita"), lexicon, Parse);
    Expect(!joined.empty() && joined[0].english && joined[0].spaces.size() == 1,
           "down|load (no word 'download' in this lexicon) gets a space too");
    jaen::Lexicon with_joined = lexicon;
    with_joined.AddJoined("download");
    const auto one = jaen::SplitEnglish(Parse("downloadshita"), with_joined, Parse);
    Expect(!one.empty() && one[0].english && one[0].spaces.empty(), "a joined word keeps no space");
  }

  Expect(english("konosonggasukidesu") == "song|", "-ng before ga after Japanese text");
  Expect(english("tokyonimita") == "tokyo|", "Hepburn place name before a particle");
  Expect(english("kyouhatokyo") == "tokyo|", "Hepburn place name at the end");
  Expect(english("oosakanimita").empty(), "not inside the normal spelling oosaka");
  Expect(english("osakanamita").empty(), "no particle after it (osakana)");
  Expect(lexicon.FindPlace("Tokyo") && lexicon.FindPlace("tokyo")->surface == "東京", "place lookup");
  Expect(english("").empty(), "empty composition");
  Expect(english(std::string(257, 'a')).empty(), "over-long composition untouched");

  // Partition covers the whole input with alternating pieces.
  const auto [pieces, text] = split("ashitanomeetingwotsuika");
  size_t at = 0;
  bool contiguous = true;
  for (const Piece& p : pieces) { contiguous &= p.begin == at && p.end > p.begin; at = p.end; }
  Expect(contiguous && at == text.size() && Text(text, pieces, true) == "meeting|", "contiguous partition");

  // Foreign chunk shapes.
  Expect(jaen::IsForeignChunk({"gwo", "ぐぉ", ""}) && jaen::IsForeignChunk({"le", "ぇ", ""}) &&
             jaen::IsForeignChunk({"g", "", "g"}),
         "foreign chunk shapes");
  Expect(!jaen::IsForeignChunk({"wo", "を", ""}) && !jaen::IsForeignChunk({"n", "", "n"}) &&
             !jaen::IsForeignChunk({"kyo", "きょ", ""}),
         "Japanese chunk shapes");

  // Lexicon normalization boundaries.
  jaen::Lexicon edge;
  for (const std::string w : {std::string(32, 'a'), std::string(33, 'b'), std::string("'tis"),
                              std::string("x1"), std::string()}) {
    edge.Add(w);
  }
  Expect(edge.size() == 1, "only valid words up to 32 letters are kept");
  Expect(edge.Contains(std::string(32, 'A')) && !edge.Contains(std::string(33, 'b')), "32/33-letter boundary");
  Expect(lexicon.Contains("o'clock") && !lexicon.Contains("o-clock"), "apostrophe kept, hyphen rejected");
  jaen::Lexicon four;
  four.Add("abcd", true);
  four.Add("abcde");
  four.Add("ABCDE", true);
  Expect(four.IsCurated("abcde") && four.IsCurated("ABCD"), "curated flag sticks");

  // Learned choices.
  {
    jaen::Choices choices;
    const auto with = [&](std::string_view raw) {
      return Text(raw, jaen::SplitEnglish(Parse(raw), lexicon, Parse, &choices), true);
    };
    choices.english["netflix"] = 1;  // not in the lexicon; has foreign chunks
    Expect(with("netflixdemita").empty(), "one commit is not enough");
    choices.english["netflix"] = jaen::kEnglishChoiceCount;
    Expect(with("netflixdemita") == "netflix|", "learned word outside the lexicon");
    choices.english["sakura"] = 1;   // plain romaji: one commit is not enough
    Expect(with("sakuradesu").empty(), "plain romaji needs more commits");
    choices.english["sakura"] = jaen::kPlainChoiceCount;
    Expect(with("sakuradesu") == "sakura|", "plain romaji after repeated commits");
    choices.english["kana"] = jaen::kPlainChoiceCount;
    Expect(with("kanadesu").empty(), "short plain romaji stays Japanese");
    choices.english["git"] = jaen::kEnglishChoiceCount;  // not cut out of romaji
    Expect(with("sakewonomisugita").empty(), "learned word inside plain romaji");
    choices.japanese.insert("google");
    Expect(with("kyouhagoogledekensaku").empty(), "word turned back into Japanese");
    Expect(with("meetingwosetshita") == "meeting|set|", "other words unaffected");
    choices.japanese.insert("ogle");
    choices.japanese.erase("google");
    Expect(with("kyouhagoogledekensaku") == "google|", "a longer word covering a Japanese one");
    Expect(english("netflixdemita") != "netflix|", "no choices: unchanged");
  }
  {
    std::string w;
    using jaen::Choice;
    Expect(jaen::ClassifyCommit("netflixdemita", "ねtfぃx", "netflix", &w) == Choice::kEnglish &&
               w == "netflix", "F10 to ASCII is English");
    Expect(jaen::ClassifyCommit("google", "google", "google", &w) == Choice::kNone, "kept English");
    Expect(jaen::ClassifyCommit("google", "google", "Google", &w) == Choice::kNone, "case only");
    Expect(jaen::ClassifyCommit("google", "google", "ｇｏｏｇｌｅ", &w) == Choice::kNone, "full width");
    Expect(jaen::ClassifyCommit("googledesu", "google", "ごおgぇ", &w) == Choice::kJapanese &&
               w == "google", "kana for an English piece");
    Expect(jaen::ClassifyCommit("aifon", "あいふぉん", "iPhone", &w) == Choice::kNone,
           "dictionary ASCII not typed");
    Expect(jaen::ClassifyCommit("kyou", "きょう", "今日", &w) == Choice::kNone, "plain conversion");
    Expect(jaen::ClassifyCommit("x", "x", "えっくす", &w) == Choice::kNone, "one letter is not a word");
    Expect(jaen::ClassifyCommit("ok", "ok", "おk", &w) == Choice::kJapanese, "short key");
    Expect(jaen::ClassifyCommit("ax", "あx", "x", &w) == Choice::kNone, "one letter is not a word");
  }
  {
    const auto file = std::filesystem::temp_directory_path() / "jaen_choices_test.txt";
    std::filesystem::remove(file);
    {
      jaen::ChoiceStore store(file);
      store.Record(jaen::Choice::kEnglish, "Netflix");
      store.Record(jaen::Choice::kEnglish, "netflix");
      store.Record(jaen::Choice::kJapanese, "google");
      store.Record(jaen::Choice::kEnglish, "x1");  // not a word
    }
    jaen::ChoiceStore again(file);
    auto c = again.Get();
    Expect(c->english.size() == 1 && c->english.at("netflix") == 2 && c->japanese.contains("google"),
           "store round trip");
    again.Record(jaen::Choice::kEnglish, "google");
    c = jaen::ChoiceStore(file).Get();
    Expect(c->english.contains("google") && !c->japanese.contains("google"), "latest choice wins");
    {
      std::ofstream(std::filesystem::path(file) += ".tmp") << "e\tleft\t1\n";
      jaen::ChoiceStore full(file);
      for (size_t i = 0; i < jaen::ChoiceStore::kMaxWords + 5; ++i) {
        std::string w = "w";
        for (size_t k = i; k > 0; k /= 26) w += static_cast<char>('a' + k % 26);
        full.Record(jaen::Choice::kEnglish, w);
      }
      full.Record(jaen::Choice::kJapanese, "zzzz");
      const auto f = full.Get();
      Expect(f->japanese.contains("zzzz") && f->english.size() + f->japanese.size() ==
                                                  jaen::ChoiceStore::kMaxWords,
             "full store still learns Japanese");
    }
    again.Clear();
    Expect(!std::filesystem::exists(std::filesystem::path(file) += ".tmp"), "clear removes the temp file");
    Expect(!std::filesystem::exists(file) && jaen::ChoiceStore(file).Get()->english.empty(), "clear");
  }

  {
    const auto file = std::filesystem::temp_directory_path() / "jaen_correction_test.tsv";
    std::filesystem::remove(file);
    jaen::CorrectionLog log(file);
    log.Record("candidate", "きしゃ", "汽車", "記者");
    log.Record("t13n", "to\tkyp", "とkyp", "tokyp");
    std::ifstream in(file);
    std::vector<std::string> lines;
    for (std::string l; std::getline(in, l);) lines.push_back(l);
    Expect(lines.size() == 2 && lines[1].find("to kyp") != std::string::npos &&
               std::ranges::count(lines[0], '\t') == 4,
           "correction log lines");
    in.close();
    log.Clear();
    Expect(!std::filesystem::exists(file), "correction log clear");
  }

  std::cout << "SUMMARY\t" << failures << '\n';
  return failures ? 1 : 0;
}
