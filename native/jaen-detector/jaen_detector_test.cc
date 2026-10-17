// Standalone tests:
//   cl /std:c++20 /EHsc /utf-8 jaen_detector.cc jaen_choices.cc jaen_detector_test.cc
// A tiny greedy romaji table stands in for Mozc's; chunk shapes follow Mozc's
// composer (jaen_chunk_probe output): unknown keys stay pending.
#include "jaen_detector.h"
#include "jaen_choices.h"
#include "correction_log.h"
#include "jaen_typo.h"

#include <chrono>
#include <cmath>
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
    {"nu", "ぬ"}, {"xn", "ん"}, {"ga", "が"}, {"ri", "り"}, {"so", "そ"}, {"wa", "わ"}, {"yo", "よ"}, {"gu", "ぐ"}, {"du", "づ"},
    {"lo", "ぉ"}, {"he", "へ"}, {"two", "とぉ"}, {"ji", "じ"}, {"ja", "じゃ"}, {"pa", "ぱ"}, {"ba", "ば"}, {"bi", "び"}, {"ru", "る"}, {"fu", "ふ"}, {"la", "ぁ"}, {"n'", "ん"}, {"va", "ゔぁ"}, {"vi", "ゔぃ"}, {"xe", "ぇ"}};

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
                        "down", "load", "o'clock", "mail", "and", "ox", "file", "nax", "linux", "song", "remote", "kite", "note", "weekly", "report", "matte", "wade", "woke", "seat", "sea", "two", "git", "test", "tests", "set", "sets", "campus", "lore", "base", "lair", "vaio", "vim", "exe"}) {
    lexicon.Add(w);
  }
  lexicon.Add("youtube", true);
  lexicon.AddPlace("tokyo", "東京", "toukyou");
  lexicon.AddPlace("osaka", "大阪", "oosaka");
  lexicon.Add("slack", true);
  lexicon.Add("nec", true);
  lexicon.Add("chatgpt", true);
  lexicon.Add("ntt", true);
  lexicon.AddPhrase("see you");
  lexicon.AddPhrase("made in japan");
  lexicon.AddPhrase("log in");
  lexicon.Add("login");
  for (const char* w : {"dog", "cat"}) lexicon.Add(w);
  lexicon.Add("3d", true);
  lexicon.AddSignalOnly("dpu");
  for (const char* w : {"london", "mac", "sumo", "gand"}) lexicon.AddSignalOnly(w);
  lexicon.AddSignalOnly("kite");  // already a word: stays a plain word
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
  // 「ねぇ」を nexe と打つ: n と exe に分けて ん + EXE にしない（印のない切り出しは、打った文字の区切りの外では取らない）。
  Expect(english("nexenadenadeshite").empty(), "弱い印だけの語は、打った文字の途中から始めない（nexe の exe）");
  Expect(english("kyouhanexedesu").empty(), "弱い印だけの語は、打った文字の途中から始めない（文の途中）");
  Expect(english("naxtu").empty(), "never cut っ typed as xtu (\"nax\" is not taken)");
  Expect(english("necchuushouniki").empty(), "no word ends at the っ of っち (nec in necchuu)");
  Expect(english("chatgptttenani") == "chatgpt|", "a word may end before tte");
  Expect(english("slackkaramita") == "slack|", "a word may end before the same key (slack + kara)");
  Expect(english("linuxnokoma") == "linux|", "xn is ん, not a small kana: it may be cut");
  Expect(english("meetinggaarimasu") == "meeting|", "-ng before ga: んっ is not Japanese");
  Expect(english("seatwokau") == "seat|", "a word before the particle wo, not \"two\" (sea|two)");
  Expect(english("testshita") == "test|", "no word ends inside shi (tests|hita)");
  Expect(english("setshita") == "set|", "set|shita, not sets|hita");
  Expect(english("campushahiroi") == "campus|", "campus|ha stays: campu is no word");
  Expect(english("londonheikimasu") == "london|", "a rarer word with a sign (lo: ぉ) is taken");
  Expect(english("londonniikimasu") == "london|", "a word may end inside nn read as ん (london|ni)");
  Expect(english("matijikanntte").empty(), "no word starts at the second n of nn or ends inside って (ntt in matijikan|nntte)");
  {
    const auto [pieces, text] = split("jaamataseeyou");
    Expect(pieces.size() == 2 && pieces[1].english && pieces[1].spaces == std::vector<size_t>{10},
           "a set phrase is one piece with its space (see you)");
  }
  Expect(english("madeinjapandesu") == "madeinjapan|", "a set phrase of three words");
  Expect(english("loginnishippai").size() > 0 && split("loginnishippai").first[0].spaces.empty(),
         "a phrase that is also one word stays one word (login)");
  lexicon.Add("cd", true);
  Expect(english("jpycdake") == "jpyc|", "four unread keys are an unknown word kept as typed (jpyc|dake, not cd)");
  Expect(english("tokyp").empty(), "three unread keys stay for the typo fix");
  Expect(english("chatgptnikiku") == "chatgpt|", "a listed word wins over four unread keys inside it (chatgpt, not tgpt)");
  Expect(english("macnoterminal") == "mac|", "a rarer word with a sign (a pending c) is taken");
  Expect(english("sumodesu").empty(), "a rarer word without a sign stays Japanese");
  Expect(english("dogandcat") == "dogandcat|", "plain words win over a rarer word (gand in do|gand|cat)");
  {
    // 助詞で始まる語（deform の de）: 直前が日本語の名詞なら助詞と語に分ける。
    jaen::Lexicon particle;
    for (const char* w : {"deform", "form", "design", "sign", "default", "fault", "detouring", "touring", "token", "ken"}) {
      particle.Add(w);
    }
    particle.AddCommon("design");
    const auto split_english = [&](std::string_view raw) {
      return Text(raw, jaen::SplitEnglish(Parse(raw), particle, Parse), true);
    };
    Expect(split_english("kinoudeformwomita") == "form|", "名詞の後の deform は で + form");
    Expect(split_english("kinoudetouringshita") == "touring|", "名詞の後の detouring は で + touring");
    Expect(split_english("deformwomita") == "deform|", "文頭の deform はそのまま");
    Expect(split_english("kinounodeformwomita") == "deform|", "助詞の後の deform はそのまま");
    Expect(split_english("kinoudesignwomita") == "design|", "よく使う design はそのまま");
    Expect(split_english("kinoudefaultwomita") == "default|", "default はそのまま");
  }
  Expect(english("3dpurinnta") == "3d|", "a listed word with digits is one piece (3d|purinnta, not dpu)");
  Expect(jaen::NormalizeWord("3d") == "3d" && jaen::NormalizeWord("123").empty(), "digits need a letter to be a word");
  {
    // Readings in the Japanese dictionary (toy): only these count as Japanese.
    const std::set<std::string> readings = {"きて", "この", "てがみ", "かいぎ", "で", "はれ", "かわ", "うぉれっと", "ばせい", "ふぁいる", "ゔぁいおりん", "へゔぃめたる"};
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
    Expect(unread("kokodematteite").empty(), "a て-form stays Japanese (matte: まって)");
    Expect(unread("kawadeoyogu").empty(), "a reading plus a particle stays Japanese (wade in kawa|de)");
    Expect(unread("otowokesu").empty(), "を inside stays Japanese (woke in oto|wo|kesu)");
    Expect(unread("baseiwoabiru").empty(), "a reading holding the word and running past it stays Japanese (base in ばせい)");
    Expect(unread("basenishite") == "base|", "with no such reading the word is English (base|ni)");
    Expect(unread("vaiorinnwohiku") == "vaio|", "v at the start of a reading stays a sign (video: ゔぃでお)");
    Expect(unread("hevimetarudesu").empty(), "v typed for ゔ inside a Japanese word is no sign (vim in へゔぃめたる)");
    Expect(unread("fulairuwomiru").empty(), "a word starting at such a small kana is no word even with a waiting key (lair in ふぁいる)");
    Expect(english("atoulorettoga") == "lore|", "without the reading check a small kana is a sign (lore)");
    Expect(unread("atoulorettoga").empty(), "a small kana typed for a Japanese word is no sign (ulo of うぉれっと)");
    Expect(unread("londonheikimasu") == "london|", "a small kana in no reading is still a sign (london)");
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
                              std::string("x-1"), std::string()}) {
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
    constexpr int64_t kDay = 86400;
    const int64_t t0 = std::chrono::duration_cast<std::chrono::seconds>(
                           std::chrono::system_clock::now().time_since_epoch()).count();
    const auto strong = [](std::string_view w) { return w == "github" || w == "netflix"; };
    const auto reset = [&] {
      std::filesystem::remove(file);
      std::filesystem::remove(std::filesystem::path(file) += ".tmp");
    };
    using jaen::Choice;
    {
      jaen::ChoiceStore store(file);
      store.Record(Choice::kEnglish, "Netflix");
      store.Record(Choice::kEnglish, "netflix");
      store.Record(Choice::kJapanese, "google");
      store.Record(Choice::kJapanese, "github");
      store.Record(Choice::kJapanese, "google");
      store.Record(Choice::kEnglish, "x-1");  // not a word (a hyphen)
    }
    jaen::ChoiceStore again(file);
    auto c = again.Get();
    Expect(c->english.size() == 1 && c->english.at("netflix") == 2 && c->japanese.contains("google"),
           "store round trip");
    Expect(!c->japanese.contains("github"), "one Japanese commit does not decide (a stray pick of ぎてゅｂ)");
    {
      std::ifstream in(file);
      std::string first;
      std::getline(in, first);
      Expect(first == "# v2", "file starts with the version line");
    }
    again.Record(Choice::kEnglish, "google");
    c = jaen::ChoiceStore(file).Get();
    Expect(c->english.contains("google") && c->english.at("google") == 1 && !c->japanese.contains("google"),
           "English pick resets a Japanese mark (score 1: not yet taken)");
    {
      std::ofstream(std::filesystem::path(file) += ".tmp") << "e\tleft\t1\n";
    }
    again.Clear();
    Expect(!std::filesystem::exists(std::filesystem::path(file) += ".tmp"), "clear removes the temp file");
    Expect(!std::filesystem::exists(file) && jaen::ChoiceStore(file).Get()->english.empty(), "clear");

    // Scenarios (fixed clock).
    {
      reset();
      int64_t now = t0;
      jaen::ChoiceStore s(file, jaen::ChoiceStore::kMaxWords, [&] { return now; });
      s.SetStrongPredicate(strong);
      const auto japanese = [&](const char* w) { return s.Get()->japanese.contains(w); };
      const auto english = [&](const char* w) {
        const auto m = s.Get()->english;
        const auto it = m.find(w);
        return it == m.end() ? 0 : it->second;
      };
      // A stray pick of a brand word stays English; three deliberate ones turn it.
      s.Record(Choice::kJapanese, "github");
      Expect(!japanese("github"), "scenario: one stray Japanese pick of a brand stays English");
      s.Record(Choice::kJapanese, "github");
      Expect(!japanese("github"), "scenario: two picks of a brand are not enough");
      s.Record(Choice::kJapanese, "github");
      Expect(japanese("github"), "scenario: three deliberate picks of a brand make it Japanese");
      // One deliberate English pick undoes it at once.
      s.Record(Choice::kEnglish, "github");
      Expect(!japanese("github") && s.Score("github", now) == 1.0, "scenario: Japanese then English is undone");
      // A plain word: two deliberate picks.
      s.Record(Choice::kJapanese, "sakura");
      Expect(!japanese("sakura"), "scenario: plain word, one pick");
      s.Record(Choice::kJapanese, "sakura");
      Expect(japanese("sakura"), "scenario: two deliberate picks of a plain word make it Japanese");
      // Weak evidence counts half.
      for (int i = 0; i < 3; ++i) s.Record(Choice::kJapanese, "hello", false);
      Expect(!japanese("hello") && s.Score("hello", now) == -1.5, "scenario: three weak picks are 1.5");
      s.Record(Choice::kJapanese, "hello", false);
      Expect(japanese("hello"), "scenario: four weak picks make a plain word Japanese");
      for (int i = 0; i < 5; ++i) s.Record(Choice::kJapanese, "netflix", false);
      Expect(!japanese("netflix"), "scenario: five weak picks of a brand are not enough");
      s.Record(Choice::kJapanese, "netflix", false);
      Expect(japanese("netflix"), "scenario: six weak picks of a brand are");
      // Two picks a few days apart still count as two.
      s.Record(Choice::kJapanese, "berry", true, now);
      s.Record(Choice::kJapanese, "berry", true, now + 3 * kDay);
      Expect(s.Get(now + 3 * kDay)->japanese.contains("berry"), "scenario: picks three days apart add up");
      // English counts: a weak commit is half, one F10 is not enough.
      s.Record(Choice::kEnglish, "snsno");
      Expect(english("snsno") == 1, "scenario: one deliberate English pick counts once");
      s.Record(Choice::kEnglish, "tweet", false);
      s.Record(Choice::kEnglish, "tweet", false);
      s.Record(Choice::kEnglish, "tweet", false);
      Expect(english("tweet") == 1, "scenario: three weak English commits count once");
      s.Record(Choice::kEnglish, "tweet", false);
      Expect(english("tweet") == 2, "scenario: four weak English commits count twice");
      // Fading: the score halves every 60 days.
      Expect(japanese("sakura") && s.Get(now + 30 * kDay)->japanese.contains("sakura") == false,
             "scenario: a Japanese mark fades within 30 days (-2 -> -1.4)");
      Expect(s.Get(now + 59 * kDay)->japanese.contains("sakura") == false, "scenario: faded after 59 days");
      Expect(s.Score("sakura", now + 120 * kDay) > -0.51 && s.Score("sakura", now + 120 * kDay) < -0.49,
             "scenario: 120 days make -2 into -0.5");
      Expect(s.Get(now + 120 * kDay)->english.contains("tweet") == false, "scenario: an English count fades too");
      Expect(s.Get(now + 1000 * kDay)->japanese.empty() && s.Get(now + 1000 * kDay)->english.empty(),
             "scenario: everything fades away");
      // The new score starts from the faded one.
      now += 120 * kDay;
      s.Record(Choice::kJapanese, "sakura");
      Expect(std::abs(s.Score("sakura", now) + 1.5) < 0.01 && !japanese("sakura"),
             "scenario: a pick after 120 days adds to the faded score");
      // The file keeps all of it.
      jaen::ChoiceStore reread(file, jaen::ChoiceStore::kMaxWords, [&] { return now; });
      reread.SetStrongPredicate(strong);
      Expect(std::abs(reread.Score("sakura", now) + 1.5) < 0.01 && reread.Get()->japanese.contains("hello") == false,
             "scenario: reread after fading (hello -2 -> -0.5)");
    }

    // Old formats: e count, j 2, j 1, j alone; time from the file.
    {
      reset();
      {
        std::ofstream out(file, std::ios::binary);
        out << "e\tnetflix\t3\nj\tgoogle\t2\nj\tgithub\t1\nj\tfoo\ne\tbar\nj\tbaz\t5\r\n";
      }
      const int64_t now = t0;
      jaen::ChoiceStore s(file, jaen::ChoiceStore::kMaxWords, [&] { return now; });
      s.SetStrongPredicate(strong);
      const auto got = s.Get();
      Expect(got->english.at("netflix") == 3 && s.Score("netflix", now) > 2.9, "old format: e count is the score");
      Expect(got->japanese.contains("google") && !got->japanese.contains("github") &&
                 std::abs(s.Score("github", now) + 1) < 0.01 && std::abs(s.Score("foo", now) + 1) < 0.01,
             "old format: j 2 is -2, j 1 and bare j are -1");
      Expect(got->english.at("bar") == 1 && got->japanese.contains("baz") && std::abs(s.Score("baz", now) + 2) < 0.01,
             "old format: e without count is 1, a larger j count is -2");
      s.Record(Choice::kJapanese, "newword");  // saved as v2
      std::ifstream in(file);
      std::string text((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
      Expect(text.starts_with("# v2\n") && text.find("w\tnewword\t-1.0000\t" + std::to_string(now) + "\n") != std::string::npos &&
                 text.find("\ne\t") == std::string::npos,
             "old format: rewritten as v2");
    }
    // Old format with an old file time: the age counts.
    {
      reset();
      { std::ofstream(file, std::ios::binary) << "e\tnetflix\t4\nj\tgoogle\t2\n"; }
      std::filesystem::last_write_time(file, std::filesystem::file_time_type::clock::now() -
                                                  std::chrono::hours(24 * 60));
      jaen::ChoiceStore s(file, jaen::ChoiceStore::kMaxWords, [&] { return t0; });
      Expect(std::abs(s.Score("netflix", t0) - 2.0) < 0.05 && std::abs(s.Score("google", t0) + 1.0) < 0.05,
             "old format: the file time is the last change (60 days halve the scores)");
    }
    // Full store: the entry nearest 0 (the oldest of them) goes.
    {
      reset();
      int64_t now = t0;
      jaen::ChoiceStore s(file, 5, [&] { return now; });
      s.Record(Choice::kJapanese, "aa");
      s.Record(Choice::kJapanese, "aa");
      s.Record(Choice::kJapanese, "aa");
      s.Record(Choice::kEnglish, "bb");
      s.Record(Choice::kEnglish, "bb");
      now += 10;
      s.Record(Choice::kEnglish, "cc");
      now += 10;
      s.Record(Choice::kEnglish, "dd");
      now += 10;
      s.Record(Choice::kEnglish, "ee");
      now += 10;
      s.Record(Choice::kEnglish, "ff");  // full: cc (oldest of the weakest) goes
      Expect(s.Score("cc", now) == 0 && std::abs(s.Score("aa", now) + 3) < 0.01 &&
                 std::abs(s.Score("bb", now) - 2) < 0.01 &&
                 s.Score("dd", now) > 0.99 && s.Score("ee", now) > 0.99 && s.Score("ff", now) > 0.99,
             "full store: the weakest, oldest entry is replaced");
      s.Record(Choice::kJapanese, "zzzz");  // full store still learns Japanese
      s.Record(Choice::kJapanese, "zzzz");
      Expect(s.Get()->japanese.contains("zzzz") && std::abs(s.Score("aa", now) + 3) < 0.01 &&
                 std::abs(s.Score("bb", now) - 2) < 0.01,
             "full store: strong entries stay");
      size_t lines = 0;
      std::ifstream in(file);
      for (std::string l; std::getline(in, l);) lines += l.starts_with("w\t");
      Expect(lines == 5, "full store: the file keeps the limit");
    }
    // Edits behind our back (tools/learned-words.ps1) are noticed.
    {
      reset();
      int64_t now = t0;
      jaen::ChoiceStore s(file, jaen::ChoiceStore::kMaxWords, [&] { return now; });
      s.Record(Choice::kJapanese, "sakura");
      s.Record(Choice::kJapanese, "sakura");
      Expect(s.Get()->japanese.contains("sakura"), "outside edit: before");
      { std::ofstream(file, std::ios::binary) << "# v2\n"; }
      std::filesystem::last_write_time(file, std::filesystem::file_time_type::clock::now() +
                                                  std::chrono::hours(1));
      Expect(s.Get()->japanese.contains("sakura"), "outside edit: not looked at within 10 seconds");
      now += 20;
      Expect(!s.Get()->japanese.contains("sakura") && s.Score("sakura", now) == 0,
             "outside edit: the word is gone");
      std::filesystem::remove(file);
      now += 20;
      s.Record(Choice::kEnglish, "tweet");
      Expect(s.Get()->english.contains("tweet"), "outside edit: a deleted file starts over");
    }
    {
      // Default limit, many words.
      reset();
      jaen::ChoiceStore full(file);
      for (size_t i = 0; i < jaen::ChoiceStore::kMaxWords + 5; ++i) {
        std::string w = "w";
        for (size_t k = i; k > 0; k /= 26) w += static_cast<char>('a' + k % 26);
        full.Record(Choice::kEnglish, w);
      }
      full.Record(Choice::kJapanese, "zzzz");
      full.Record(Choice::kJapanese, "zzzz");
      const auto f = full.Get();
      Expect(f->japanese.contains("zzzz") && f->english.size() + f->japanese.size() ==
                                                  jaen::ChoiceStore::kMaxWords,
             "full store still learns Japanese");
    }
    reset();
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

  {
    // Readable slips: the edits offered, with what each kind costs.
    const auto edit = [&](std::string_view raw, std::string_view keys) -> std::optional<int> {
      for (const jaen::TypoEdit& e : jaen::ReadableTypoEdits(raw, Parse)) {
        if (e.keys == keys) return e.prior;
      }
      return std::nullopt;
    };
    Expect(edit("tsuduukete", "tsudukete") == jaen::TypoPriors{}.doubled_vowel, "a doubled vowel may be dropped cheaply (つづうけて)");
    Expect(edit("ashitadesu", "shitadesu") == std::nullopt, "the first key is never edited");
    Expect(edit("kaigidesu", "kagidesu") == std::nullopt, "a key is dropped only where it was typed twice");
    Expect(edit("hayyaku", "hayaku") == jaen::TypoPriors{}.doubled_consonant, "a doubled consonant costs more");
    Expect(edit("koukadesu", "kuokadesu") == std::nullopt, "ou is never made uo");
    Expect(edit("kuokadesu", "koukadesu") == jaen::TypoPriors{}.swapped_uo, "uo to ou costs more than other swaps (chuo for ちゅうおう)");
    Expect(edit("kyohaame", "kyouhaame") == jaen::TypoPriors{}.long_vowel, "a long vowel left out is offered first (kyoha)");
    Expect(edit("okiidesu", "ookiidesu") == jaen::TypoPriors{}.long_vowel, "also after the first key (okii for ookii)");
    Expect(edit("kyohan'demo", "kyouhan'demo") == jaen::TypoPriors{}.long_vowel, "keys with n' for ん are edited too");
    Expect(edit("kazukidesu", "kaxukidesu") == std::nullopt, "no fix brings in an x or l small kana (z next to x)");
    Expect(jaen::ReadableTypoEdits("fidesuka", Parse).empty(), "a reading with a small vowel (ふぃ) is not edited");
    Expect(!jaen::ReadableTypoEdits("tsudukete", Parse).empty() && jaen::ReadableTypoEdits("tsud", Parse).empty(),
           "only keys that read as kana are edited");
  }

  std::cout << "SUMMARY\t" << failures << '\n';
  return failures ? 1 : 0;
}
