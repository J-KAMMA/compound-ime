// Standalone tests:
//   cl /std:c++20 /EHsc /utf-8 jaen_detector.cc jaen_choices.cc jaen_detector_test.cc
// A tiny greedy romaji table stands in for Mozc's; chunk shapes follow Mozc's
// composer (jaen_chunk_probe output): unknown keys stay pending.
#include "jaen_detector.h"
#include "jaen_choices.h"
#include "correction_log.h"
#include "jaen_typo.h"

#include <algorithm>
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
    {"gwo", "ぐぉ"}, {"le", "ぇ"}, {"ya", "や"}, {"yu", "ゆ"}, {"mo", "も"}, {"re", "れ"}, {"ra", "ら"},
    {"tte", "って"}, {"da", "だ"}, {"chi", "ち"}, {"mi", "み"}, {"tsu", "つ"},
    {"do", "ど"}, {"xu", "ぅ"}, {"fi", "ふぃ"}, {"xtu", "っ"}, {"gi", "ぎ"}, {"li", "ぃ"},
    {"q", "く"}, {"qa", "くぁ"}, {"qi", "くぃ"}, {"qe", "くぇ"}, {"qo", "くぉ"}, {"qu", "く"}, {"qwe", "くぇ"},
    {"nu", "ぬ"}, {"xn", "ん"}, {"ga", "が"}, {"ri", "り"}, {"so", "そ"}, {"wa", "わ"}, {"yo", "よ"}, {"gu", "ぐ"}, {"du", "づ"},
    {"lo", "ぉ"}, {"he", "へ"}, {"two", "とぉ"}, {"ji", "じ"}, {"ja", "じゃ"}, {"pa", "ぱ"}, {"ba", "ば"}, {"bi", "び"}, {"ru", "る"}, {"fu", "ふ"}, {"la", "ぁ"}, {"n'", "ん"}, {"va", "ゔぁ"}, {"vi", "ゔぃ"}, {"xe", "ぇ"},
    {",", "、"}, {".", "。"}, {"!", "！"}, {"?", "？"}, {"-", "ー"}, {"dhi", "でぃ"}};

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
  lexicon.Add("qoder", true);
  lexicon.Add("qwen", true);
  lexicon.Add("qt", true);
  lexicon.Add("qa", true);
  lexicon.Add("quora", true);
  lexicon.Add("quick");
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
  Expect(english("matte").empty(), "a whole input that is a plain word read as Japanese stays Japanese (待って)");
  Expect(english("meetingwosetshita") == "meeting|set|", "word merged with wo; set before shi");
  Expect(english("downloadshita") == "download|", "adjacent words merge into one piece");
  Expect(english("youtubedemita") == "youtube|", "curated plain word");
  Expect(english("okdesu") == "ok|", "short word with pending key");
  Expect(english("mailwokaku") == "mail|", "word ending in a pending key before wo");
  Expect(english("qoderwotsukau") == "qoder|", "qo (くぉ) before a word: the curated name is taken");
  Expect(english("qwenwotamesu") == "qwen|", "q and w before n: the curated name is taken");
  Expect(english("quickwotsukau") == "quick|", "qu (く) stays a weak sign: an ordinary English word");
  Expect(english("qonnikaku").empty(), "a q loanword reading not in the list stays Japanese");
  {
    // The composer merges n with a following w ("qwen|wo" is qwe + nwo), so qwen ends inside a chunk.
    const std::vector<Chunk> chunks = {{"qwe", "くぇ", ""}, {"nwo", "んを", ""}, {"ta", "た", ""},
                                       {"me", "め", ""}, {"su", "す", ""}, {"", "", ""}};
    Expect(Text("qwenwotamesu", jaen::SplitEnglish(chunks, lexicon, Parse), true) == "qwen|",
           "a q word may end inside the chunk nwo (qwen|wo)");
  }
  {
    // A name ending in the particle's key ("mbed|de"): the composer reads the two d's as っで in one chunk.
    jaen::Lexicon names;
    names.AddSignalOnly("mbed");
    const std::vector<Chunk> chunks = {{"m", "ん", ""}, {"be", "べ", ""}, {"dde", "っで", ""},
                                       {"su", "す", ""}, {"", "", ""}};
    Expect(Text("mbeddesu", jaen::SplitEnglish(chunks, names, Parse), true) == "mbed|",
           "a name may end inside the chunk dde (mbed|de)");
  }

  {
    // A name after a particle is not stopped by a word made of the particle and the name.
    jaen::Lexicon names;
    for (const char* w : {"ham", "bed", "gab", "tom", "oar", "bad", "ton"}) names.Add(w);
    for (const char* w : {"mbed", "bios", "mrna", "arxiv", "rba", "vito"}) names.AddSignalOnly(w);
    const auto named = [&](std::string_view raw) {
      return Text(std::string(raw), jaen::SplitEnglish(Parse(raw), names, Parse), true);
    };
    Expect(named("kinouhambedwotsukatta") == "mbed|", "ha|mbed: not ham + bed");
    Expect(named("koregabiosdesu") == "bios|", "ga|bios: not gab + ios");
    Expect(named("tomodachitomrnawotsukatta") == "mrna|", "to|mrna: not tom + rna");
    Expect(named("aideawoarxivdeatsumete") == "arxiv|", "wo|arxiv: not oar + xiv");
    Expect(named("rbadeshirabeta") == "rba|", "rba|de: not stopped by bad");
    Expect(named("vitonitaihosareta").empty(), "vito|ni: ton keeps it Japanese");
  }
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
    const std::set<std::string> readings = {"きて", "この", "てがみ", "かいぎ", "で", "はれ", "かわ", "うぉれっと", "ばせい", "ふぁいる", "ゔぁいおりん", "へゔぃめたる", "はく", "からく", "よく", "すごく"};
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
    // q の語の直前の読みが く で終わる偶然の一致（はく、からく）でも、助詞・文末の直前なら英語。
    Expect(unread("watashihaqodergasukidesu.") == "qoder|", "qoder after はく: the q word is taken");
    Expect(unread("kyouhaqoderwo") == "qoder|", "Qoder before the particle wo after はく");
    Expect(unread("korekaraqoderni") == "qoder|", "Qoder after からく: a long q word is taken");
    Expect(unread("watashihaqwengasukidesu.") == "qwen|", "Qwen after はく: the q word is taken");
    Expect(unread("watashihaqtgasukidesu.") == "qt|", "Qt after は: a short q word after a particle is taken");
    Expect(unread("kyouhaqtwo") == "qt|", "Qt before wo (qtwo) after は");
    Expect(unread("watashihaquoragasukidesu.") == "quora|", "Quora after はく: qu stays a weak sign and is taken");
    // q が日本語の く の打ち方のままの文は英語にしない。
    Expect(unread("sugoqamaiyo").empty(), "q for く inside すごく stays Japanese");
    // 厳選した3文字の語（api、dao）: かなが辞書にないか、辞書にあっても自然な読みでないときだけ英語
    jaen::Lexicon short_words = lexicon;
    short_words.Add("dai", true);
    short_words.Add("tame", false);
    std::set<std::string> with_dai = readings;
    with_dai.insert("だい");
    with_dai.insert("ため");
    const jaen::ReadingCheck is_dai_reading = [&](std::string_view kana) { return with_dai.contains(std::string(kana)); };
    const jaen::ReadingCheck unnatural = [](std::string_view) { return false; };
    const jaen::ReadingCheck natural = [](std::string_view) { return true; };
    const auto three = [&](std::string_view raw, const jaen::ReadingCheck* check) {
      std::string out;
      for (const Piece& p : jaen::SplitEnglish(Parse(raw), short_words, Parse, nullptr, &is_dai_reading, check)) {
        if (p.english) out += std::string(raw.substr(p.begin, p.end - p.begin)) + "|";
      }
      return out;
    };
    Expect(three("kyouhadaiwomita", &natural) == "", "a curated 3-letter word with a natural reading stays Japanese (dai: だい)");
    Expect(three("kyouhadaiwomita", &unnatural) == "dai|", "a curated 3-letter word whose reading is not natural is English");
    Expect(three("kyouhadaiwomita", nullptr).empty(), "without the naturalness check the reading decides");
    Expect(three("kyouhatamewomita", &unnatural).empty(), "a 4-letter word that is no curated or common word is not taken by naturalness");
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
    jaen::Lexicon letters;
    letters.Add("m");
    letters.Add("r");
    for (const char* raw : {"10mm", "mm", "mmr"}) {
      const auto unit = jaen::SplitEnglish(Parse(raw), letters, Parse);
      Expect(!unit.empty() && unit.back().english && unit.back().spaces.empty(),
             "letters with no vowel stay together (10mm, not 10m m)");
    }
  }

  {
    // 文脈で決める段（JapaneseModel）: ローマ字として日本語に読める英単語は、前後の読みが日本語として
    // 自然なら日本語のまま、読みが不自然なら（英単語のつながり、英語の隣）英語にする。
    // 辞書は小さな代わり（かな→費用）、接続の費用は 0。
    const std::map<std::string, int> costs = {{"きょう", 3000}, {"は", 500}, {"さめ", 6000}, {"たけ", 6000},
                                              {"を", 300}, {"みた", 3000}, {"で", 300}, {"です", 300}, {"きょうは", 3500}};
    jaen::JapaneseModel model;
    model.prefix_words = [&](std::string_view kana, std::vector<jaen::JapaneseWord>* words) {
      for (const auto& [reading, cost] : costs) {
        if (kana.substr(0, reading.size()) == reading) words->push_back({reading.size(), 1, 1, cost});
      }
    };
    model.transition = [](uint16_t, uint16_t) { return 0; };
    jaen::Lexicon context = lexicon;
    context.Add("time");
    context.Add("take");
    context.Add("google", true);
    const auto decided = [&](std::string_view raw) {
      return jaen::SplitEnglish(Parse(raw), context, Parse, nullptr, nullptr, nullptr, &model);
    };
    const auto decided_text = [&](std::string_view raw) { return Text(raw, decided(raw), true); };
    Expect(decided_text("samewomita").empty(), "文脈: 助詞が続いて自然に読める same は日本語のまま");
    Expect(decided_text("kyouhasamewomita").empty(), "文脈: 文の中の same + を は日本語のまま");
    Expect(decided_text("takewomita").empty(), "文脈: take + を は日本語のまま");
    Expect(decided_text("kyouhasame").empty(), "文脈: 日本語の文の中の1語だけの same は日本語のまま");
    Expect(decided_text("sametime") == "sametime|", "文脈: 読みが不自然な2語のつながりは英語");
    {
      const auto pieces = decided("sametime");
      Expect(pieces.size() == 1 && pieces[0].spaces == std::vector<size_t>{4}, "文脈: つながりの語の間に空白");
    }
    Expect(decided_text("kyouhasamegoogledesu") == "samegoogle|", "文脈: 英語の隣の same は英語（google の隣）");
    Expect(english("sametime").empty() && Text("sametime", jaen::SplitEnglish(Parse("sametime"), lexicon, Parse), true).empty(),
           "文脈の段は、辞書の費用を渡さなければ働かない");
    Expect(Text("kyouhasamegoogledesu", jaen::SplitEnglish(Parse("kyouhasamegoogledesu"), context, Parse), true) == "google|",
           "文脈の段を使わないときは今までどおり（same は日本語）");

    // 直前に確定した文字が英字の語で終わるとき（make →変換→確定→空白→ sure の1語ずつ打つ人）。
    const auto after_english = [&](std::string_view raw, bool previous_english, const jaen::ContextCosts* costs = nullptr) {
      return Text(raw, jaen::SplitEnglish(Parse(raw), context, Parse, nullptr, nullptr, nullptr, &model, costs, previous_english), true);
    };
    Expect(after_english("same", false).empty(), "直前なし: 日本語に読める1語 same は日本語のまま");
    Expect(after_english("same", true) == "same|", "直前が英語: 1語の same は英語");
    Expect(after_english("take", true) == "take|", "直前が英語: 1語の take は英語");
    Expect(after_english("samewomita", true).empty(), "直前が英語でも、助詞が続いて日本語として自然な並びは日本語");
    Expect(after_english("takewomita", true).empty(), "直前が英語でも、take + を は日本語");
    Expect(after_english("kyouhasame", true).empty(), "直前が英語でも、入力の途中の1語は今までどおり日本語");
    Expect(after_english("kyouhasamewomita", true).empty(), "直前が英語でも、文の中の same + を は日本語");
    Expect(after_english("sametime", true) == "sametime|", "直前が英語: 2語のつながりは今までどおり英語");
    {
      jaen::ContextCosts off = jaen::DefaultContextCosts();
      off.follow_margin = 0;
      Expect(after_english("same", true, &off).empty(), "follow_margin が 0 なら直前を見ない");
      jaen::ContextCosts strict = jaen::DefaultContextCosts();
      strict.follow_margin = 3000;  // 6000 - 3700 = 2300 の差には届かない
      Expect(after_english("same", true, &strict).empty(), "follow_margin を大きくすると寄せが弱まる");
    }
    Expect(jaen::EndsWithEnglishWord("make") && jaen::EndsWithEnglishWord("make ") && jaen::EndsWithEnglishWord("I want to ") &&
               jaen::EndsWithEnglishWord("今日は Slack ") && jaen::EndsWithEnglishWord("iPhone"),
           "直前が英字の語で終わる");
    Expect(!jaen::EndsWithEnglishWord("") && !jaen::EndsWithEnglishWord("今日は") && !jaen::EndsWithEnglishWord("Hello, ") &&
               !jaen::EndsWithEnglishWord("2024 ") && !jaen::EndsWithEnglishWord("   ") && !jaen::EndsWithEnglishWord("Slackで"),
           "直前が日本語・記号・数・空で終わる");
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
             jaen::IsForeignChunk({"g", "", "g"}) && jaen::IsForeignChunk({"qo", "くぉ", ""}) &&
             jaen::IsForeignChunk({"q", "く", ""}),
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
    Expect(edit("kaigoidesu", "kaigidesu") == jaen::TypoPriors{}.extra_key, "a key next to a key around it may be dropped at extra_key");
    Expect(edit("kaigidesu", "kagidesu") == std::nullopt, "a key touching neither key around it is not dropped");
    Expect(edit("kiouhadesu", "kinouhadesu") == jaen::TypoPriors{}.dropped_consonant, "a consonant left out (kiou for kinou)");
    Expect(edit("dakeatokara", "dakeeatokara") != jaen::TypoPriors{}.long_vowel, "no long vowel is put in after e before another vowel (だけあとから)");
    Expect(edit("okiidesu", "ookiidesu") == jaen::TypoPriors{}.long_vowel, "a long vowel left out before a consonant (okii)");
    {
      jaen::TypoPriors off;
      off.extra_key = off.dropped_consonant = jaen::TypoPriors::kOff;
      bool offered = false;
      for (const jaen::TypoEdit& e : jaen::ReadableTypoEdits("kaigoidesu", Parse, off)) offered |= e.keys == "kaigidesu";
      Expect(!offered, "with extra_key off, a key is dropped only where it was typed twice");
    }
    Expect(edit("hayyaku", "hayaku") == jaen::TypoPriors{}.doubled_consonant, "a doubled consonant costs more");
    Expect(edit("koukadesu", "kuokadesu") == std::nullopt, "ou is never made uo");
    Expect(edit("kuokadesu", "koukadesu") == jaen::TypoPriors{}.swapped_uo, "uo to ou costs more than other swaps (chuo for ちゅうおう)");
    Expect(edit("kyohaame", "kyouhaame") == jaen::TypoPriors{}.long_vowel, "a long vowel left out is offered first (kyoha)");
    Expect(edit("okiidesu", "ookiidesu") == jaen::TypoPriors{}.long_vowel, "also after the first key (okii for ookii)");
    Expect(edit("kyohan'demo", "kyouhan'demo") == jaen::TypoPriors{}.long_vowel, "keys with n' for ん are edited too");
    Expect(edit("kazukidesu", "kaxukidesu") == std::nullopt, "no fix brings in an x or l small kana (z next to x)");
    {
      // A slip read as a listed word or acronym (FixTypoReadAsEnglish's stricter test): only one
      // English run between Japanese pieces, not before a particle, with the edit in or next to it.
      using Run = std::optional<std::pair<size_t, size_t>>;
      const std::vector<Piece> machiawase = {{0, 11, false}, {11, 14, true}, {14, 17, false}};
      Expect(jaen::EnglishRunBetweenJapanese("ekidemachiaawseta", machiawase) == Run{{11, 14}},
             "machia|aws|eta: aws between Japanese is the run");
      Expect(!jaen::EnglishRunBetweenJapanese("awsnosetteiwosuru", {{0, 3, true}, {3, 17, false}}),
             "aws at the start stays English (awsのせっていをする)");
      Expect(!jaen::EnglishRunBetweenJapanese("kinouawsnosettei", {{0, 5, false}, {5, 8, true}, {8, 16, false}}),
             "aws right before の stays English (きのうawsのせってい)");
      Expect(!jaen::EnglishRunBetweenJapanese("korehahouse", {{0, 6, false}, {6, 11, true}}),
             "a word at the end stays English");
      Expect(!jaen::EnglishRunBetweenJapanese("ahouseihouse", {{0, 1, false}, {1, 6, true}, {6, 7, false},
                                                             {7, 12, true}}),
             "two English runs are not one slip");
      Expect(jaen::EnglishRunBetweenJapanese("konokusurihasohkugo", {{0, 10, false}, {10, 13, true},
                                                                    {13, 15, true}, {15, 19, false}}) ==
                 Run{{10, 15}},
             "has|oh next to each other is one run");
      Expect(!jaen::EnglishRunBetweenJapanese("kinouawsdeshita", {{0, 5, false}, {5, 8, true}, {8, 15, false}}),
             "before で stays English");
      Expect(jaen::EditNear("ekidemachiaawseta", "ekidemachiawaseta", 11, 14), "a swap inside aws");
      Expect(jaen::EditNear("abcxyzdef", "abxxyzdef", 3, 6), "the key just before the run");
      Expect(jaen::EditNear("abcxyzdef", "abcxyzxef", 3, 6), "the key just after the run");
      Expect(!jaen::EditNear("abcxyzdef", "axcxyzdef", 3, 6), "two keys before the run is elsewhere");
      Expect(!jaen::EditNear("abcxyzdefg", "abcxyzdeqg", 3, 6), "two keys after the run is elsewhere");
      Expect(jaen::EditNear("abcxyzdef", "abcxyazdef", 3, 6), "a key put in inside the run");
      Expect(jaen::EditNear("abcxyzdef", "abcxydef", 3, 6), "a key dropped inside the run");
      Expect(!jaen::EditNear("abc", "abc", 0, 3), "no edit");
      Expect(jaen::StartsWithParticleSpelling("nosettei") && jaen::StartsWithParticleSpelling("wookuru") &&
                 !jaen::StartsWithParticleSpelling("eta") && !jaen::StartsWithParticleSpelling("kugo"),
             "particle spellings");
    }
    for (const char* letter : {"cwomotto", "bgaii", "ynoatai", "kokohaqdeii", "fnikaeru", "pkarahajimeru"}) {
      Expect(jaen::UnreadTypoEdits(letter, Parse, jaen::KanaModel({})).empty(), letter);
    }
    Expect(jaen::DropLoneLetters("道bの端") == "道の端" && jaen::DropLoneLetters("自己の損f害") == "自己の損害" &&
               jaen::DropLoneLetters("cをもっと") == "をもっと" && jaen::DropLoneLetters("PCを買う") == "PCを買う" &&
               jaen::DropLoneLetters("pcを買う") == "pcを買う" && jaen::DropLoneLetters("寝るz") == "寝るz",
           "lone letters dropped");
    Expect(!jaen::UnreadTypoEdits("michibnohashi", Parse, jaen::KanaModel({})).empty(), "a letter inside a word is a slip");
    Expect(!jaen::UnreadTypoEdits("sorehadmeda", Parse, jaen::KanaModel({})).empty(),
           "an unread key not before a particle is still weighed");
    {
      const auto edits = jaen::UnreadTypoEdits("jkamma", Parse, jaen::KanaModel({}));
      Expect(std::ranges::none_of(edits, [](const jaen::UnreadTypoEdit& e) { return e.keys[0] != 'j'; }),
             "the first key is not dropped or changed (jkamma: not かっま)");
    }
    Expect(jaen::ReadableTypoEdits("fidesuka", Parse).empty(),"a reading with a small vowel (ふぃ) is not edited");
    Expect(!jaen::ReadableTypoEdits("tsudukete", Parse).empty() && jaen::ReadableTypoEdits("tsud", Parse).empty(),
           "only keys that read as kana are edited");
  }

  {
    // Runs longer than the fixers look at are cut after particles into parts of at most 64 keys.
    const auto joined = [](const std::vector<std::string_view>& parts) {
      std::string s;
      for (const std::string_view p : parts) s += p;
      return s;
    };
    const std::string_view short_run = "kinounokaigideketteishita";
    Expect(jaen::SplitLongRomaji(short_run).size() == 1, "a run of at most 64 keys is one part");
    // 82 keys (holdout の打ち間違い 64超 の形): 来月から新しい部署に異動することになったので引き継ぎの資料を作っている
    const std::string_view long_run = "raigetsukaraatarashiibushoniidousurukotoninattanodehikitsuginooshiryouwotsukutteiru";
    const auto parts = jaen::SplitLongRomaji(long_run);
    bool short_enough = true, after_vowel = true;
    for (const std::string_view p : parts) {
      short_enough &= p.size() <= 64 && p.size() >= 12;
      after_vowel &= std::string_view("aiueo").find(p.back()) != std::string_view::npos;
    }
    Expect(parts.size() == 2 && joined(parts) == long_run && short_enough && after_vowel,
           "an 82-key run is cut into two parts that end on a vowel");
    Expect(parts[0].ends_with("ni") || parts[0].ends_with("no") || parts[0].ends_with("de") ||
               parts[0].ends_with("wo") || parts[0].ends_with("ga") || parts[0].ends_with("to"),
           "the cut is after a particle");
    // wo is the best cut, even with another particle closer to 64 keys.
    const std::string with_wo = "kosowo" + std::string("katteshimattanode") + "mokunoshinaito" + "nagaku" + "nagaku" + "nagakunagakushitekudasai";
    const auto wo_parts = jaen::SplitLongRomaji(with_wo, 64);
    Expect(joined(wo_parts) == with_wo && wo_parts.size() >= 2, "a long run is cut and joins back");
    // No cut inside a doubled consonant or before a vowel, ー or y.
    for (const std::string_view p : jaen::SplitLongRomaji(
             "kittekittekittekittekittekittekittekittekittekittekittekittekittekitte", 20, 4)) {
      Expect(!p.starts_with("t") || p.size() == 0, "never cut between the two t of tte");
    }
    // A run with no vowel to cut after stays whole.
    const std::string consonants(80, 'k');
    Expect(jaen::SplitLongRomaji(consonants).size() == 1, "no cut after a consonant");
    // Each part is at least 12 keys: a 70-key run is not cut 64 + 6.
    for (const std::string_view p : jaen::SplitLongRomaji(
             "watashihakinoutomodachitoissho" "nieiganiminiittekaerinikafedeohanashishita")) {
      Expect(p.size() >= 12, "no part shorter than 12 keys");
    }
  }

  {
    // 日本語に読める略語（ai: あい、ui: うい、ime: いめ）。打った並びに英字が残らない。
    // ai は独立した語として打たれたら（後ろが助詞・句読点・文末）AI にする。ui、ime などは手がかり方式のまま。
    Expect(english("aiwotsukau") == "ai|", "ai + を + 使う は AI（aiwotsukau）");
    Expect(english("kyouhaaiwotsukau") == "ai|", "文の途中でも AI を使う");
    Expect(english("aigakaihatsu") == "ai|", "ai + が + 開発");
    Expect(english("aiwokanjiru") == "ai|", "愛を感じる も AI（利用者の決定）");
    Expect(english("aigakowai") == "ai|", "AIが怖い は AI");
    Expect(english("ainohanashi") == "ai|", "AIの話 は AI");
    Expect(english("ainikiku") == "ai|", "AIに聞く は AI（会いに の 行く ではない）");
    Expect(english("ainimakaseru") == "ai|", "AIに任せる は AI");
    Expect(english("aidegazou") == "ai|", "AIで画像 は AI");
    Expect(english("aikarayomu") == "ai|" && english("aimadematsu") == "ai|" &&
           english("aiheokuru") == "ai|" && english("aiyoribenrida") == "ai|",
           "AIから・まで・へ・より は AI");
    Expect(english("ai") == "ai|" && english("ai,") == "ai|" && english("ai.") == "ai|", "AI だけ・句読点の前も AI");
    Expect(english("ainiiku").empty() && english("ainikita").empty() && english("ainikuru").empty() &&
           english("ainiitta").empty(), "会いに行く・来る の活用は日本語のまま");
    Expect(english("aishite").empty() && english("aisuru").empty(), "愛して・愛する は日本語のまま");
    Expect(english("aite").empty() && english("aikawarazu").empty() && english("aizu").empty() &&
           english("aida").empty(), "相手・相変わらず・合図・間 は日本語のまま");
    Expect(english("aimai").empty() && english("aisatsu").empty(), "曖昧・あいさつ は日本語のまま");
    Expect(english("aideru").empty(), "愛でる は日本語のまま");
    Expect(english("ainotsukai") == "ai|", "ai + の + 使い は AI");
    Expect(english("ai ") == "ai|" && english("ai wo tsukau") == "ai|", "空白のあと・空白で区切った助詞のあとも AI");
    Expect(english("ainiikennwoiu") == "ai|" && english("ainiikasu") == "ai|" &&
           english("ainiikousuru") == "ai|", "AIに意見・活かす・移行する は AI（行く の形に見えても）");
    Expect(english("ainiyuku").empty() && english("ainikoreru").empty() &&
           english("ainikosaseta").empty(), "会いにゆく・来れる・来させる は日本語のまま");
    Expect(english("aidesomeru").empty() && english("ainokimono").empty() &&
           english("ainotewoireru").empty(), "藍で染める・藍の着物・合いの手を入れる は日本語のまま");
    Expect(english("ainiku").empty() && english("ainorini").empty(), "生憎・相乗りに は日本語のまま");
    Expect(english("ainorisuru").empty() && english("ainorishita").empty(), "相乗りする・した は日本語のまま");
    Expect(english("ainote").empty() && english("ainotewoireru").empty(), "合いの手・合いの手を入れる は日本語のまま");
    Expect(english("aideteiru").empty(), "会いでいる は日本語のまま");
    Expect(english("aideta").empty() && english("aidemasu").empty(), "愛でた・愛でます は日本語のまま");
    Expect(english("aidea").empty() && english("aidehonnyaku") == "ai|", "アイデアは日本語のまま、AIで翻訳は AI");
    Expect(english("aideawokangaeru").empty() && english("kiminoaideaiine").empty() &&
           english("aidenteitei").empty(), "アイデア・アイデンティティ は日本語のまま");
    Expect(english("ainorisuku") == "ai|" && english("ainorisuto") == "ai|" &&
           english("ainotegaki") == "ai|", "AIのリスク・リスト・手書き は AI");
    Expect(english("ainotennkaiwotsukau") == "ai|" && english("ainori-da-wotsukau") == "ai|" &&
           english("ainoteianwotsukau") == "ai|", "AIの展開・リーダー・提案 は AI");
    Expect(english("ainorigasuki").empty() && english("ainotegasuki").empty(),
           "後ろに語が続いても 相乗り・合いの手 は日本語のまま");
    Expect(english("aideaisatsu") == "ai|", "AIであいさつ の AI（あいさつ は日本語）");
    Expect(english("tedeaiwotsukau") == "ai|", "手でAI の AI");
    Expect(english("aideimasu").empty() && english("aideteimasu").empty() &&
           english("aideteita").empty(), "会いでいます・愛でています・会いでいた は日本語のまま");
    Expect(english("naiwotsukau").empty(), "略語は打った文字の区切りから始まる（nai の ai は取らない）");
    Expect(english("uiwotsukau") == "ui|", "ui + を + 使う は UI");
    Expect(english("kouiwotsukau") == "ui|", "辞書がないときは行為を使う も取る（下は辞書があるとき）");
    {
      const jaen::ReadingCheck is_reading = [](std::string_view kana) { return kana == "こうい"; };
      const auto pieces = jaen::SplitEnglish(Parse("kouiwotsukau"), lexicon, Parse, nullptr, &is_reading);
      Expect(Text("kouiwotsukau", pieces, true).empty(), "行為（こうい）の途中の ui は取らない");
      const auto taken = jaen::SplitEnglish(Parse("aiwotsukau"), lexicon, Parse, nullptr, &is_reading);
      Expect(Text("aiwotsukau", taken, true) == "ai|", "辞書があっても AI を使う は取る");
    }
    {
      // 本物の Mozc の辞書には あいで（愛で）・あいは（相葉）・あいから（藍から）のような読みもある。
      // 後ろの読みで AI を止めないこと（止めると AIは技術だ が 愛は技術だ になる）。
      const std::set<std::string> readings = {"あいにく", "ばあい", "あいのり", "あいでる", "あいであ",
                                              "あいでんてぃてぃ", "あいのて", "あいでいます", "あいでています",
                                              "あいでいた", "あいでていた", "あいさつ", "あい",
                                              "あいで", "あいは", "あいから", "あいまで", "あいより",
                                              "あいでぃる", "あいであまん", "あいとらっきんぐ", "あいである",
                                              "あいでぃあ", "あいをよむひと", "あいときずな", "あいとかんしゃ",
                                              "であい", "にあい", "しあい", "しりあい", "かいしゃ",
                                              "じむしょ", "それ", "て", "き", "め"};
      const jaen::ReadingCheck is_reading = [&](std::string_view kana) { return readings.contains(std::string(kana)); };
      const auto with = [&](std::string_view raw) {
        return Text(std::string(raw), jaen::SplitEnglish(Parse(raw), lexicon, Parse, nullptr, &is_reading), true);
      };
      Expect(with("ainikiku") == "ai|", "辞書の あいにく より AIに聞く を優先する");
      Expect(with("ainimakaseru") == "ai|", "AIに任せる は辞書があっても AI");
      Expect(with("baai").empty() && with("kyouhabaai").empty(), "場合（ばあい）の ai は日本語のまま");
      Expect(with("ainoriyou") == "ai|", "AIの利用 は AI（相乗り より先）");
      Expect(with("aiha") == "ai|" && with("aidehonnyaku") == "ai|" &&
             with("aikarayomu") == "ai|" && with("aimadematsu") == "ai|" &&
             with("aiheokuru") == "ai|" && with("aiyoribenrida") == "ai|",
             "辞書に あいは・あいで・あいから・あいまで・あいより があっても独立した ai は AI");
      Expect(with("soredeaiwotsukau") == "ai|",
             "辞書の であい（出会い）があっても、助詞のあとの AI は AI");
      Expect(with("kyouhaaigakowai") == "ai|",
             "辞書の あいがあっても、AIが怖い は AI");
      Expect(with("shiaiwomiru").empty() && with("shiraininiau").empty() &&
             with("baaihachigau").empty(), "試合・知り合い・場合 の ai は日本語のまま");
      Expect(with("aidea").empty(), "アイデア（あいであ）は日本語のまま");
      Expect(with("aideawokangaeru").empty() && with("kiminoaideaiine").empty() &&
             with("aidenteitei").empty(), "アイデアを考える・君のアイデアいいね・アイデンティティ は日本語のまま");
      Expect(with("deai").empty() && with("deaiwotsutaeru").empty() && with("niai").empty(),
             "文頭の 出会い・似合い は辞書の読みで日本語のまま");
      Expect(with("ainorisuku") == "ai|" && with("ainorisuto") == "ai|" && with("ainotegaki") == "ai|",
             "AIのリスク・リスト・手書き は AI（相乗り・合いの手 の例外を狭める）");
      Expect(with("ainotennkaiwotsukau") == "ai|" && with("ainori-da-wotsukau") == "ai|" &&
             with("ainoteianwotsukau") == "ai|", "AIの展開・リーダー・提案 は辞書があっても AI");
      Expect(with("aideimasu").empty() && with("aideteimasu").empty() && with("aideteita").empty(),
             "会いでいます・愛でています・会いでいた は日本語のまま");
      Expect(with("aideru").empty(), "愛でる は辞書があっても日本語のまま");
      Expect(with("ainiyuku").empty() && with("ainikoreru").empty() && with("ainikosaseta").empty(),
             "会いにゆく・来れる・来させる は辞書があっても日本語のまま");
      Expect(with("aidesomeru").empty(), "藍で染める は辞書があっても日本語のまま");
      Expect(with("ainokimono").empty(), "藍の着物 は辞書があっても日本語のまま");
      Expect(with("ainotewoireru").find("ai|") == std::string::npos,
             "合いの手を入れる の ai は辞書があっても取らない");
      Expect(with("ainorigasuki").empty() && with("ainotegasuki").empty(),
             "相乗りが好き・合いの手が好き の ai は辞書があっても取らない");
      Expect(with("aideaisatsu") == "ai|" && with("aideaiwo") == "ai|",
             "AIであいさつ・AIで愛を の最初の AI は取る（後ろの あい は日本語のまま）");
      Expect(with("aidhiru").empty() && with("aideamann").empty() &&
             with("aitorakkinngu").empty() && with("aidearu").empty() &&
             with("aidearu.").empty(),
             "ai の後ろにカタカナ語の続き（アイディル・アイデアマン・アイトラッキング・アイデアル）があるときは AI にしない");
      Expect(with("aidearukara") == "ai|" && with("aidearunode") == "ai|" &&
             with("aidearuwake") == "ai|",
             "AIであるから・AIであるので・AIであるわけ の ai は AI（アイデアル だけを打ったときと分ける）");
      Expect(with("aidhia").empty(), "アイディア（あいでぃあ）は日本語のまま");
      Expect(with("aiwoyomuhito") == "ai|" && with("aitokizuna") == "ai|" &&
             with("aitokannsha") == "ai|",
             "AIを読む人・AIと絆・AIと感謝 の ai は AI（助詞から始まる日本語の句）");
      Expect(with("deaideaiwotsukau") == "ai|" && with("baaideaiwotsukau") == "ai|" &&
             with("baainiaiwotsukau") == "ai|", "出会いで・場合で・場合に のあとの AI は辞書があっても AI");
      Expect(with("tedeaiwotsukau") == "ai|" && with("kideaiwotsukau") == "ai|" &&
             with("medeaiwotsukau") == "ai|",
             "手で・木で・目で のあとの AI も取る");
      Expect(with("ainiku").empty() && with("ainorini").empty(), "生憎・相乗りに は辞書があっても日本語のまま");
      Expect(with("ainiikennwoiu") == "ai|" && with("ainiikasu") == "ai|" && with("ainiikousuru") == "ai|",
             "AIに意見・活かす・移行する は辞書があっても AI");
    }
    {
      jaen::Choices choices;
      choices.japanese.insert("ai");
      const auto pieces = jaen::SplitEnglish(Parse("aiwotsukau"), lexicon, Parse, &choices);
      Expect(Text("aiwotsukau", pieces, true).empty(), "利用者が日本語に戻した ai は取らない");
    }
    // 日本語の語としては使わない並び（方式 plain: seo）は、助詞か文の終わりが続けばよい。
    Expect(english("seowomita") == "seo|" && english("seodesu") == "seo|" && english("seo") == "seo|", "seo は助詞か文の終わりで取る");
    Expect(english("seoi").empty(), "せおい（背負い）の seo は取らない（助詞も文の終わりも続かない）");
    // ime、gui は日本語の語の中にもある（三回目の の ime、手ぬぐいの の gui）ので、手がかりが要る。
    Expect(english("imewokirikaeru") == "ime|", "ime + を + 切り替え は IME");
    Expect(english("sannkaimeno").empty(), "三回目の の ime は取らない（辞書がなくても、手がかりがない）");
    Expect(english("imeji").empty(), "イメージ の ime は取らない");
  }
  {
    // 小さい「っ」で終わる読み（うはっ）は、ha|llm の っ を日本語の語に取らない（今日はLLM が 今日hall m だった）
    jaen::Lexicon words;
    for (const char* w : {"hall", "gall"}) words.Add(w);
    words.Add("llm", true);
    const std::set<std::string> readings = {"うはっ", "うがっ", "きょう"};
    const jaen::ReadingCheck is_reading = [&](std::string_view kana) { return readings.contains(std::string(kana)); };
    const auto english = [&](std::string_view raw) {
      std::string out;
      for (const Piece& p : jaen::SplitEnglish(Parse(raw), words, Parse, nullptr, &is_reading)) {
        if (p.english) out += std::string(raw.substr(p.begin, p.end - p.begin)) + "|";
      }
      return out;
    };
    Expect(english("kyouhallmwotsukau") == "llm|", "ha|llm after a reading ending in a small tsu (うはっ)");
    Expect(english("kyougallm") == "llm|", "ga|llm after a reading ending in a small tsu (うがっ)");
  }

  std::cout << "SUMMARY\t" << failures << '\n';
  return failures ? 1 : 0;
}
