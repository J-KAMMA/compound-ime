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
constexpr Multiplier kHundreds[] = {{U"ひゃく", 100}, {U"びゃく", 100}, {U"ぴゃく", 100}};
constexpr Multiplier kTens[] = {{U"じゅう", 10}};
constexpr Multiplier kTensTsu[] = {{U"じゅっ", 10}, {U"じっ", 10}};

struct Unit {
  Piece reading;
  const char* text;
};

constexpr Unit kUnits[] = {
    {U"ねん", "年"},     {U"がつ", "月"},       {U"にち", "日"},      {U"じ", "時"},
    {U"ふん", "分"},     {U"ぷん", "分"},       {U"びょう", "秒"},    {U"ほん", "本"},
    {U"ぼん", "本"},     {U"ぽん", "本"},       {U"こ", "個"},        {U"にん", "人"},
    {U"かい", "回"},     {U"えん", "円"},       {U"さい", "歳"},      {U"ど", "度"},
    {U"ばん", "番"},     {U"まい", "枚"},       {U"だい", "台"},      {U"ひき", "匹"},
    {U"びき", "匹"},     {U"ぴき", "匹"},       {U"けん", "件"},      {U"しゅうかん", "週間"},
    {U"かげつ", "か月"}, {U"じかん", "時間"},   {U"にちかん", "日間"}, {U"ばんめ", "番目"},
    {U"かいめ", "回目"}, {U"にんまえ", "人前"}, {U"ぱーせんと", "%"},
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
// digit and each multiplier is one). One part alone (a digit, or a bare じゅう,
// ひゃく, せん) is too often an ordinary word to be taken.
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

// What may follow a span: the end, 、, a particle, ごぜん/ごご, or another span.
bool BoundaryOk(const Text& t, size_t end) {
  if (end >= t.size() || t[end] == U'、') return true;
  constexpr Piece kParticles[] = {U"は", U"が", U"を", U"に", U"で",   U"と",   U"の",
                                  U"も", U"へ", U"や", U"から", U"まで", U"より", U"って"};
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
      if (c.parts >= 2) Offer(t, best, end, Join(c.value, u.text));
    }
  }
}

std::optional<Match> MatchAt(const Text& t, size_t i) {
  std::optional<Match> best;
  OfferClock(t, i, best);
  if (auto day = DayAt(t, i, false)) Offer(t, best, day->first, Join(day->second, "日"));
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
