// Typed Arabic digits stay Arabic in the first candidate. Mozc's number
// rewriter (and the whole-sentence AI) can put a kanji spelling of the same
// number first ("980" -> 九百八十, "10" -> 十). Only a key with a typed digit
// is touched, so a word read in kana (hitotsu -> 一つ, ichibann -> 一番,
// juubunn -> 十分) keeps its kanji.
//
// A number token is a run of digits (half or full width), kanji numerals and
// the marks between them (., %). The candidate's token is compared with the
// key's token after width normalization; when they differ, the key's token is
// put back while the surrounding text (円, 度, 点, ...) stays.
//
// This file is included in converter.cc (inside an anonymous namespace) and by
// native/jaen-detector/typed_digits_test.cc.
namespace {
namespace typed_digits {

inline bool IsAsciiDigit(char32_t c) { return c >= U'0' && c <= U'9'; }
inline bool IsFullWidthDigit(char32_t c) { return c >= 0xFF10 && c <= 0xFF19; }
inline bool IsDigit(char32_t c) { return IsAsciiDigit(c) || IsFullWidthDigit(c); }

inline bool IsKanjiNumeral(char32_t c) {
  switch (c) {
    case 0x3007:  // 〇
    case 0x96F6:  // 零
    case 0x4E00:  // 一
    case 0x4E8C:  // 二
    case 0x4E09:  // 三
    case 0x56DB:  // 四
    case 0x4E94:  // 五
    case 0x516D:  // 六
    case 0x4E03:  // 七
    case 0x516B:  // 八
    case 0x4E5D:  // 九
    case 0x5341:  // 十
    case 0x767E:  // 百
    case 0x5343:  // 千
    case 0x4E07:  // 万
    case 0x5104:  // 億
    case 0x5146:  // 兆
    case 0x58F1:  // 壱
    case 0x5F10:  // 弐
    case 0x53C2:  // 参
      return true;
    default:
      return false;
  }
}

// The marks that can sit inside a number token.
inline bool IsNumberMark(char32_t c) {
  return c == U'.' || c == 0xFF0E || c == U',' || c == 0xFF0C ||
         c == U'%' || c == 0xFF05;
}

inline bool IsTokenChar(char32_t c) {
  return IsDigit(c) || IsKanjiNumeral(c) || IsNumberMark(c);
}

inline size_t Utf8Length(unsigned char b) {
  return b < 0x80 ? 1 : b < 0xE0 ? 2 : b < 0xF0 ? 3 : 4;
}

inline char32_t Decode(const char* p, size_t len) {
  if (len == 1) return static_cast<unsigned char>(*p);
  char32_t c = static_cast<unsigned char>(p[0]) & (0xFF >> (len + 1));
  for (size_t i = 1; i < len; ++i) {
    c = (c << 6) | (static_cast<unsigned char>(p[i]) & 0x3F);
  }
  return c;
}

struct Token {
  size_t begin;
  size_t end;
};

// Maximal number tokens, left to right. A token must hold a digit or a kanji
// numeral (a bare "." or "%" is not a number).
inline std::vector<Token> NumberTokens(std::string_view text) {
  std::vector<Token> tokens;
  size_t i = 0;
  while (i < text.size()) {
    const size_t len = Utf8Length(static_cast<unsigned char>(text[i]));
    const size_t end = i + len <= text.size() ? i + len : text.size();
    if (!IsTokenChar(Decode(text.data() + i, end - i))) {
      i = end;
      continue;
    }
    const size_t begin = i;
    bool has_number = false;
    while (i < text.size()) {
      const size_t l = Utf8Length(static_cast<unsigned char>(text[i]));
      const size_t e = i + l <= text.size() ? i + l : text.size();
      const char32_t c = Decode(text.data() + i, e - i);
      if (!IsTokenChar(c)) break;
      has_number = has_number || IsDigit(c) || IsKanjiNumeral(c);
      i = e;
    }
    if (has_number) tokens.push_back({begin, i});
  }
  return tokens;
}

inline bool HasTypedDigit(std::string_view key) {
  for (size_t i = 0; i < key.size();) {
    const size_t len = Utf8Length(static_cast<unsigned char>(key[i]));
    const size_t end = i + len <= key.size() ? i + len : key.size();
    if (IsDigit(Decode(key.data() + i, end - i))) return true;
    i = end;
  }
  return false;
}

inline bool KeepsTypedDigits(std::string_view key, std::string_view candidate) {
  if (!HasTypedDigit(key)) return true;
  const std::vector<Token> key_tokens = NumberTokens(key);
  const std::vector<Token> candidate_tokens = NumberTokens(candidate);
  if (key_tokens.size() != candidate_tokens.size()) return false;
  // Compare the written tokens themselves, so the width follows the typed key
  // (980 for a half-width setting, ９８０ for a full-width one).
  for (size_t i = 0; i < key_tokens.size(); ++i) {
    if (key.substr(key_tokens[i].begin, key_tokens[i].end - key_tokens[i].begin) !=
        candidate.substr(candidate_tokens[i].begin,
                         candidate_tokens[i].end - candidate_tokens[i].begin)) {
      return false;
    }
  }
  return true;
}

// Puts the key's number tokens into candidate, leaving the other text alone.
// False when the two do not have the same number of tokens.
inline bool ReplaceWithTypedDigits(std::string_view key, std::string_view candidate,
                                   std::string* out) {
  if (out == nullptr || !HasTypedDigit(key)) return false;
  const std::vector<Token> key_tokens = NumberTokens(key);
  const std::vector<Token> candidate_tokens = NumberTokens(candidate);
  if (key_tokens.empty()) return false;
  if (key_tokens.size() == 1 && candidate_tokens.size() > 1) {
    // A decimal read with 点 between the digits (三点一四 for 3.14): the gap
    // must be only that mark, so 九百八十円と二 (a gap of 円と) is left alone.
    bool decimal_marks = true;
    for (size_t i = 1; i < candidate_tokens.size(); ++i) {
      const std::string_view gap(candidate.data() + candidate_tokens[i - 1].end,
                                 candidate_tokens[i].begin - candidate_tokens[i - 1].end);
      if (gap != "点" && gap != "．" && gap != ".") decimal_marks = false;
    }
    if (decimal_marks) {
      std::string result(candidate.substr(0, candidate_tokens.front().begin));
      result.append(key.substr(key_tokens[0].begin, key_tokens[0].end - key_tokens[0].begin));
      result.append(candidate.substr(candidate_tokens.back().end));
      *out = std::move(result);
      return true;
    }
  }
  if (key_tokens.size() != candidate_tokens.size()) return false;
  std::string result;
  size_t at = 0;
  for (size_t i = 0; i < key_tokens.size(); ++i) {
    result.append(candidate.data() + at, candidate_tokens[i].begin - at);
    result.append(key.data() + key_tokens[i].begin,
                  key_tokens[i].end - key_tokens[i].begin);
    at = candidate_tokens[i].end;
  }
  result.append(candidate.data() + at, candidate.size() - at);
  *out = std::move(result);
  return true;
}

}  // namespace typed_digits
}  // namespace
