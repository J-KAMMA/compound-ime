// What a Japanese period (。) or comma (、) typed right after an alphanumeric
// becomes. Mozc turned every such mark into a full-width one at the width of
// the "., " character-form rule ("4。1" -> "4．1", "1、000" -> "1，000"), whether
// or not a digit followed, and never looked at the digits' own width.
//
//   next is a digit:  decimal point / thousands separator (4.1, 1,000, v1.2),
//                     at the width of the neighbouring digit
//   next is a letter: 3.x, 2.x ... the same when a digit comes before
//   otherwise:        a digit before it ends the clause, so the mark stays
//                     Japanese (合計は4。, 4。では); after a letter the old rule
//
// This file is included inside the anonymous namespace of composer.cc by
// tools/apply_decimal_point.py and, for tests, by tools/decimal_transform_test.py.
enum class NumberPunctuation {
  kKeep,       // leave the Japanese mark as it is
  kLegacy,     // Mozc's old rule (the width of the "., " character-form rule)
  kHalfWidth,  // "." or ","
  kFullWidth,  // "．" or "，"
};

bool IsHalfWidthDigitChar(const char32_t c) { return c >= U'0' && c <= U'9'; }
bool IsFullWidthDigitChar(const char32_t c) { return c >= 0xFF10 && c <= 0xFF19; }
bool IsDigitChar(const char32_t c) {
  return IsHalfWidthDigitChar(c) || IsFullWidthDigitChar(c);
}
bool IsLetterChar(const char32_t c) {
  return (c >= U'a' && c <= U'z') || (c >= U'A' && c <= U'Z') ||
         (c >= 0xFF21 && c <= 0xFF3A) || (c >= 0xFF41 && c <= 0xFF5A);
}

// |prev| is the (alphanumeric) character before the mark and |next| the one
// after it, or 0 when the mark is last.
NumberPunctuation DecideNumberPunctuation(const char32_t prev, const char32_t next) {
  if (IsDigitChar(next) || (IsLetterChar(next) && IsDigitChar(prev))) {
    const char32_t width_of = IsDigitChar(prev) ? prev : next;
    return IsFullWidthDigitChar(width_of) ? NumberPunctuation::kFullWidth
                                          : NumberPunctuation::kHalfWidth;
  }
  return IsDigitChar(prev) ? NumberPunctuation::kKeep : NumberPunctuation::kLegacy;
}
