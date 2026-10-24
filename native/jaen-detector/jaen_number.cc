#include "jaen_number.h"

#include <cstdint>
#include <optional>
#include <utility>

namespace jaen {
namespace {

using Text = std::u32string;
using Piece = std::u32string_view;

struct Digit {
  Piece reading;
  int value;
  bool tsu;  // ends in っ, so a counter or a multiplier must follow
};

constexpr Digit kDigits[] = {
    {U"いち", 1, false}, {U"いっ", 1, true},  {U"に", 2, false},     {U"さん", 3, false},
    {U"よん", 4, false}, {U"よ", 4, false},   {U"し", 4, false},     {U"ご", 5, false},
    {U"ろく", 6, false}, {U"ろっ", 6, true},  {U"なな", 7, false},   {U"しち", 7, false},
    {U"はち", 8, false}, {U"はっ", 8, true},  {U"きゅう", 9, false}, {U"く", 9, false},
    {U"れい", 0, false}, {U"ぜろ", 0, false},
};

struct Multiplier {
  Piece reading;
  uint64_t value;
};

constexpr Multiplier kThousands[] = {{U"せん", 1000}, {U"ぜん", 1000}};
constexpr Multiplier kHundreds[] = {{U"ひゃく", 100}, {U"びゃく", 100}, {U"ぴゃく", 100},
                                    {U"ひゃっ", 100}, {U"びゃっ", 100}, {U"ぴゃっ", 100}};
constexpr Multiplier kTens[] = {{U"じゅう", 10}};
constexpr Multiplier kTensTsu[] = {{U"じゅっ", 10}, {U"じっ", 10}};

struct Unit {
  Piece reading;
  const char* text;
};

constexpr Unit kUnits[] = {
    {U"ねん", "年"},     {U"がつ", "月"},       {U"にち", "日"},      {U"じ", "時"},
    {U"ふん", "分"},     {U"ぷん", "分"},       {U"ぶん", "分"},      {U"びょう", "秒"},
    {U"ほん", "本"},     {U"ぼん", "本"},       {U"ぽん", "本"},      {U"こ", "個"},
    {U"にん", "人"},     {U"かい", "回"},       {U"えん", "円"},      {U"さい", "歳"},
    {U"ど", "度"},       {U"ばん", "番"},       {U"まい", "枚"},      {U"だい", "台"},
    {U"ひき", "匹"},     {U"びき", "匹"},       {U"ぴき", "匹"},      {U"けん", "件"},
    {U"はい", "杯"},     {U"ぱい", "杯"},       {U"ばい", "倍"},      {U"さつ", "冊"},
    {U"てん", "点"},     {U"わり", "割"},       {U"しゅうかん", "週間"}, {U"かげつ", "か月"},
    {U"じかん", "時間"}, {U"にちかん", "日間"}, {U"ばんめ", "番目"},  {U"かいめ", "回目"},
    {U"にんまえ", "人前"}, {U"ぱーせんと", "%"},
};

struct DayWord {
  Piece reading;
  int day;
  bool context_only;  // also an everyday word: taken only after 月 or じゅう
};

constexpr DayWord kDayWords[] = {
    {U"ついたち", 1, false}, {U"ふつか", 2, false}, {U"みっか", 3, false},  {U"よっか", 4, false},
    {U"いつか", 5, true},    {U"むいか", 6, true},  {U"なのか", 7, true},    {U"ようか", 8, true},
    {U"ここのか", 9, true},  {U"とおか", 10, false}, {U"はつか", 20, false},
};

// A number reading: where it ends, its value, and how many parts it has (each
// digit and each multiplier is one). A single part (one digit, or one じゅう)
// is taken only in the narrow cases in SinglePartNumber below.
struct Cand {
  size_t end;
  uint64_t value;
  int parts;
};

struct Match {
  size_t end;
  std::string value;
};

Text Decode(std::string_view s) {
  Text out;
  for (size_t i = 0; i < s.size();) {
    const unsigned char c = static_cast<unsigned char>(s[i]);
    const size_t len = c < 0x80 ? 1 : c >= 0xF0 ? 4 : c >= 0xE0 ? 3 : c >= 0xC0 ? 2 : 1;
    if (len == 1 || i + len > s.size()) {
      out.push_back(c < 0x80 ? c : 0xFFFD);
      ++i;
      continue;
    }
    char32_t cp = c & (0xFF >> (len + 1));
    for (size_t k = 1; k < len; ++k) cp = (cp << 6) | (static_cast<unsigned char>(s[i + k]) & 0x3F);
    out.push_back(cp);
    i += len;
  }
  return out;
}

bool At(const Text& t, size_t pos, Piece p) {
  return pos <= t.size() && t.compare(pos, p.size(), p) == 0;
}

std::vector<const Digit*> DigitsAt(const Text& t, size_t pos) {
  std::vector<const Digit*> out;
  for (const Digit& d : kDigits) {
    if (At(t, pos, d.reading)) out.push_back(&d);
  }
  return out;
}

// Readings below 10000 starting at |start|: thousands, hundreds, tens, ones in
// that order, each optional. |stage| is the next part allowed; 4 means done.
void GroupGen(const Text& t, size_t start, size_t pos, int stage, uint64_t val, int parts,
              std::vector<Cand>& out) {
  if (pos > start) out.push_back({pos, val, parts});
  if (stage >= 4 || pos >= t.size()) return;
  const std::vector<const Digit*> digits = DigitsAt(t, pos);
  auto with_multiplier = [&](const Multiplier& m, int next, bool allow_tsu) {
    if (At(t, pos, m.reading)) {
      GroupGen(t, start, pos + m.reading.size(), next, val + m.value, parts + 1, out);
    }
    for (const Digit* d : digits) {
      if (d->value == 0 || (d->tsu && !allow_tsu)) continue;
      const size_t at = pos + d->reading.size();
      if (At(t, at, m.reading)) {
        GroupGen(t, start, at + m.reading.size(), next, val + d->value * m.value, parts + 2, out);
      }
    }
  };
  if (stage <= 0) {
    for (const Multiplier& m : kThousands) with_multiplier(m, 1, true);
  }
  if (stage <= 1) {
    for (const Multiplier& m : kHundreds) with_multiplier(m, 2, true);
  }
  if (stage <= 2) {
    for (const Multiplier& m : kTens) with_multiplier(m, 3, false);
    for (const Multiplier& m : kTensTsu) with_multiplier(m, 4, false);
  }
  if (stage <= 3) {
    for (const Digit* d : digits) {
      if (d->value != 0) GroupGen(t, start, pos + d->reading.size(), 4, val + d->value, parts + 1, out);
    }
  }
}

std::vector<Cand> Groups(const Text& t, size_t pos) {
  std::vector<Cand> out;
  GroupGen(t, pos, pos, 0, 0, 0, out);
  return out;
}

// [groups]おく [groups]まん [groups]; おく and まん need digits before them.
void NumGen(const Text& t, size_t pos, int level, uint64_t val, int parts,
            std::vector<Cand>& out) {
  if (level < 2) {
    constexpr Piece kSuffix[] = {U"おく", U"まん"};
    constexpr uint64_t kScale[] = {100000000, 10000};
    for (const Cand& g : Groups(t, pos)) {
      if (!At(t, g.end, kSuffix[level])) continue;
      const size_t next = g.end + kSuffix[level].size();
      const uint64_t v = val + g.value * kScale[level];
      out.push_back({next, v, parts + g.parts + 1});
      NumGen(t, next, level + 1, v, parts + g.parts + 1, out);
    }
    NumGen(t, pos, level + 1, val, parts, out);
    return;
  }
  for (const Cand& g : Groups(t, pos)) out.push_back({g.end, val + g.value, parts + g.parts});
}

// Plain digits read one by one; only a long run with ぜろ/れい in it, such as
// "にぜろにろく" (2026). Shorter runs ("さんに", "にいち") are ordinary words.
void PositionalGen(const Text& t, size_t pos, uint64_t val, size_t count, bool zero,
                   std::vector<Cand>& out) {
  if (count >= 4 && zero) out.push_back({pos, val, static_cast<int>(count)});
  if (count >= 18) return;
  for (const Digit* d : DigitsAt(t, pos)) {
    if (d->tsu || (count == 0 && d->value == 0)) continue;
    PositionalGen(t, pos + d->reading.size(), val * 10 + d->value, count + 1,
                  zero || d->value == 0, out);
  }
}

std::vector<Cand> Numbers(const Text& t, size_t pos) {
  std::vector<Cand> out;
  NumGen(t, pos, 0, 0, 0, out);
  PositionalGen(t, pos, 0, 0, false, out);
  return out;
}

std::string Join(uint64_t n, const char* unit) { return std::to_string(n) + unit; }

// The longest day reading at |pos| ("ふつか", "にじゅうよっか", "さんにち").
// |after_month| (right after "がつ") also allows the everyday-looking words
// and a number plus にち.
std::optional<std::pair<size_t, int>> DayAt(const Text& t, size_t pos, bool after_month) {
  std::optional<std::pair<size_t, int>> best;
  auto take = [&](size_t end, int day) {
    if (!best || end > best->first) best = std::make_pair(end, day);
  };
  for (const DayWord& w : kDayWords) {
    if ((after_month || !w.context_only) && At(t, pos, w.reading)) {
      take(pos + w.reading.size(), w.day);
    }
  }
  const std::pair<Piece, int> tens[] = {{U"じゅう", 10}, {U"にじゅう", 20}, {U"さんじゅう", 30}};
  for (const auto& [ten, value] : tens) {
    if (!At(t, pos, ten)) continue;
    for (const DayWord& w : kDayWords) {
      if (w.day < 2 || w.day > 9 || value + w.day > 31 || !At(t, pos + ten.size(), w.reading)) {
        continue;
      }
      take(pos + ten.size() + w.reading.size(), value + w.day);
    }
  }
  if (after_month) {
    for (const Cand& c : Numbers(t, pos)) {
      if (At(t, c.end, U"にち") && c.value >= 1 && c.value <= 31) {
        take(c.end + 2, static_cast<int>(c.value));
      }
    }
  }
  return best;
}

std::optional<Match> MatchAt(const Text& t, size_t i);

// What may follow a span: the end, 句読点・閉じ括弧, a particle or です,
// ごぜん/ごご, or another span.
bool BoundaryOk(const Text& t, size_t end) {
  if (end >= t.size()) return true;
  switch (t[end]) {
    case U'、': case U'。': case U'，': case U'．': case U'！': case U'？':
    case U'」': case U'』': case U'）': case U'】': case U'・':
    case U' ': case U'　': case U'\n':
      return true;
  }
  constexpr Piece kParticles[] = {U"は", U"が", U"を", U"に", U"で",   U"と",   U"の",
                                  U"も", U"へ", U"や", U"から", U"まで", U"より", U"って", U"です"};
  for (Piece p : kParticles) {
    if (At(t, end, p)) return true;
  }
  return At(t, end, U"ごぜん") || At(t, end, U"ごご") || MatchAt(t, end).has_value();
}

// Keeps the longest candidate whose right boundary is fine; false if refused.
bool Offer(const Text& t, std::optional<Match>& best, size_t end, std::string value) {
  if (!BoundaryOk(t, end)) return false;
  if (!best || end > best->end) best = Match{end, std::move(value)};
  return true;
}

// ごぜん/ごご + hour + じ ("ごぜんくじ" -> 午前9時).
void OfferClock(const Text& t, size_t i, std::optional<Match>& best) {
  const std::pair<Piece, const char*> prefixes[] = {{U"ごぜん", "午前"}, {U"ごご", "午後"}};
  for (const auto& [reading, label] : prefixes) {
    if (!At(t, i, reading)) continue;
    for (const Cand& c : Numbers(t, i + reading.size())) {
      if (c.value < 1 || c.value > 12 || !At(t, c.end, U"じ")) continue;
      Offer(t, best, c.end + 1, std::string(label) + Join(c.value, "時"));
    }
  }
}

// 一つの部分だけの数でも、単位が続けば数として取るのは、じゅう（10）と
// 促音の いっ・ろっ・はっ（1・6・8）だけ。ふつうの1けた（に、さん、ろく ...）は
// にほん（日本）、くじ（籤）、いちにち（一日）、いちど（一度）と紛れ、ひゃく・せん は
// 百姓・千葉・仙台・先輩と紛れるので取らない。にひゃく・さんぜん のような複数の
// 部分からなる数は、この限りでない。
bool SinglePartNumber(const Text& t, size_t begin, size_t end) {
  static constexpr Piece kAllowed[] = {
      U"じゅう", U"じゅっ", U"じっ", U"いっ", U"ろっ", U"はっ",
  };
  for (Piece p : kAllowed) {
    if (end - begin == p.size() && At(t, begin, p)) return true;
  }
  return false;
}

// 数の形をした普通の言葉。単位まで含めた読みがこれに当たるときは数字にしない。
bool IsOrdinaryNumberWord(const Text& t, size_t begin, size_t end) {
  static constexpr Piece kWords[] = {
      U"じゅうぶん",  // 十分
      U"いってん",    // 一転
      U"じっけん",    // 実験
      U"じっさい",    // 実際
      U"はってん",    // 発展
      U"はっけん",    // 発見
      U"いっけん",    // 一見
  };
  for (Piece w : kWords) {
    if (end - begin == w.size() && At(t, begin, w)) return true;
  }
  return false;
}

void OfferNumbers(const Text& t, size_t i, std::optional<Match>& best) {
  for (const Cand& c : Numbers(t, i)) {
    for (const Unit& u : kUnits) {
      if (!At(t, c.end, u.reading)) continue;
      const size_t end = c.end + u.reading.size();
      if (std::string_view(u.text) == "月") {
        if (c.value < 1 || c.value > 12) continue;
        if (auto day = DayAt(t, end, true)) {
          if (Offer(t, best, day->first, Join(c.value, "月") + Join(day->second, "日"))) continue;
        }
      }
      if (IsOrdinaryNumberWord(t, i, end)) continue;
      if (c.parts >= 2 || SinglePartNumber(t, i, c.end)) {
        Offer(t, best, end, Join(c.value, u.text));
      }
    }
  }
}

// Digits read one by one as a code, kept as written (090, 213): right after
// ばんごう (and は/が/を/の/も), two or more; elsewhere three or more starting
// with ぜろ (an area or mobile code). にい and ごお are 2 and 5 drawn out.
void OfferDigitString(const Text& t, size_t i, std::optional<Match>& best) {
  static constexpr std::pair<Piece, char> kCode[] = {
      {U"ぜろ", '0'}, {U"れい", '0'}, {U"いち", '1'}, {U"にい", '2'}, {U"に", '2'}, {U"さん", '3'},
      {U"よん", '4'}, {U"ごお", '5'}, {U"ご", '5'}, {U"ろく", '6'}, {U"なな", '7'}, {U"はち", '8'},
      {U"きゅう", '9'}};
  bool after_bangou = false;
  for (Piece p : {Piece(U"ばんごう"), Piece(U"ばんごうは"), Piece(U"ばんごうが"), Piece(U"ばんごうを"),
                  Piece(U"ばんごうの"), Piece(U"ばんごうも")}) {
    after_bangou = after_bangou || (i >= p.size() && At(t, i - p.size(), p));
  }
  const bool zero_first = At(t, i, U"ぜろ");
  if (!after_bangou && !zero_first) return;
  // Every way to read a run of code digits from |pos|.
  std::vector<std::pair<size_t, std::string>> runs;
  const auto walk = [&](auto&& self, size_t pos, std::string digits) -> void {
    if (digits.size() >= (after_bangou ? 2u : 3u)) runs.emplace_back(pos, digits);
    if (digits.size() >= 15) return;
    for (const auto& [reading, digit] : kCode) {
      if (At(t, pos, reading)) self(self, pos + reading.size(), digits + digit);
    }
  };
  walk(walk, i, "");
  for (const auto& [end, digits] : runs) Offer(t, best, end, digits);
}

// 「ここにじゅうにん」の に は助詞で、数の一部（にじゅう = 20）ではない。
// 直前に助詞（は・が・を・に・で・と・も・へ・や・の）か区切りがなければ、に から始めない。
// ただし「きょうにじゅうにん」の に のように、時の言葉のすぐあとは助詞ではなく
// 数の一部（にじゅう = 20）として取る。
bool ParticleNi(const Text& t, size_t i) {
  if (!At(t, i, U"に") || i == 0) return false;
  switch (t[i - 1]) {
    case U'は': case U'が': case U'を': case U'に': case U'で': case U'と':
    case U'も': case U'へ': case U'や': case U'の':
    case U'、': case U'。': case U'，': case U'．': case U'！': case U'？':
    case U'「': case U'」': case U'『': case U'』': case U'（': case U'）':
    case U' ': case U'　': case U'\n':
      return false;
  }
  static constexpr Piece kTimeWords[] = {
      U"きょう", U"きのう", U"あした", U"あさって", U"おととい",
      U"けさ", U"こんばん", U"ゆうべ", U"いま",
      U"ことし", U"きょねん", U"らいねん",
      U"こんげつ", U"せんげつ", U"らいげつ",
      U"こんしゅう", U"せんしゅう", U"らいしゅう",
      U"まいにち", U"まいあさ", U"まいばん",
  };
  for (Piece w : kTimeWords) {
    if (i >= w.size() && At(t, i - w.size(), w)) return false;
  }
  return true;
}

std::optional<Match> MatchAt(const Text& t, size_t i) {
  if (ParticleNi(t, i)) return std::nullopt;
  std::optional<Match> best;
  OfferDigitString(t, i, best);
  OfferClock(t, i, best);
  // 和語の日の言葉（ふつか、ついたち ...）は漢字のまま。日の言葉に数が付く
  // にじゅうよっか（24日）だけは数として取る。
  if (At(t, i, U"じゅう") || At(t, i, U"にじゅう") || At(t, i, U"さんじゅう")) {
    if (auto day = DayAt(t, i, false)) Offer(t, best, day->first, Join(day->second, "日"));
  }
  OfferNumbers(t, i, best);
  return best;
}

}  // namespace

std::vector<NumberSpan> FindNumbers(std::string_view kana) {
  const Text t = Decode(kana);
  std::vector<NumberSpan> spans;
  for (size_t i = 0; i < t.size();) {
    std::optional<Match> m = MatchAt(t, i);
    if (!m) {
      ++i;
      continue;
    }
    const size_t end = m->end;
    spans.push_back({i, end, std::move(m->value)});
    i = end;
  }
  return spans;
}

}  // namespace jaen
