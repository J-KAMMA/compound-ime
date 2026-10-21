// Typed Arabic digits stay Arabic in the first candidate. Mozc's number
// rewriter (and the whole-sentence AI) can put a kanji spelling of the same
// number first ("980" -> 九百八十, "10" -> 十). Only a key with a typed digit
// is touched, so a word read in kana (hitotsu -> 一つ, ichibann -> 一番,
// juubunn -> 十分) keeps its kanji.
//
// The comparison only asks whether every typed number token in the key is
// present, as typed, in the candidate. Kanji numerals added by the candidate
// are not part of that test: "3億" already holds the typed "3", and the 億
// comes from the kana "おく"; likewise the 一 of "2人一緒" comes from "いっしょ"
// and must not hide the typed 2. When the candidate spells the typed number in
// kanji, only that number is replaced ("九百八十円" -> "980円"), while a kanji
// unit after a typed digit stays ("三億" -> "3億").
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

inline bool TokenHasDigit(std::string_view text, const Token& token) {
  size_t i = token.begin;
  while (i < token.end) {
    const size_t len = Utf8Length(static_cast<unsigned char>(text[i]));
    const size_t end = i + len <= token.end ? i + len : token.end;
    if (IsDigit(Decode(text.data() + i, end - i))) return true;
    i = end;
  }
  return false;
}

// True when |token| holds at least one typed digit.
inline bool HasTypedDigit(std::string_view key) {
  for (const Token& token : NumberTokens(key)) {
    if (TokenHasDigit(key, token)) return true;
  }
  return false;
}

// The character just before |pos|. False at the start of the text.
inline bool PreviousChar(std::string_view text, size_t pos, char32_t* out) {
  if (pos == 0) return false;
  size_t start = pos - 1;
  while (start > 0 && (static_cast<unsigned char>(text[start]) & 0xC0) == 0x80) {
    --start;
  }
  *out = Decode(text.data() + start, pos - start);
  return true;
}

inline bool NextChar(std::string_view text, size_t pos, char32_t* out) {
  if (pos >= text.size()) return false;
  const size_t len = Utf8Length(static_cast<unsigned char>(text[pos]));
  const size_t end = pos + len <= text.size() ? pos + len : text.size();
  *out = Decode(text.data() + pos, end - pos);
  return true;
}

// A typed token must stand on its own: not inside a longer digit run and not
// next to a number mark. A kanji numeral after it is allowed because it may be
// the unit of the number (3億, 5百円).
inline bool MatchesAt(std::string_view text, size_t pos, size_t length) {
  char32_t c;
  if (PreviousChar(text, pos, &c) &&
      (IsDigit(c) || IsKanjiNumeral(c) || IsNumberMark(c))) {
    return false;
  }
  if (NextChar(text, pos + length, &c) && (IsDigit(c) || IsNumberMark(c))) {
    return false;
  }
  return true;
}

inline bool KeepsTypedDigits(std::string_view key, std::string_view candidate) {
  if (!HasTypedDigit(key)) return true;
  // Every typed number token in the key must appear as written, in order.
  // Extra kanji numerals (the unit 万, or the 一 of 一緒 added from kana) do
  // not take part in the test.
  size_t from = 0;
  for (const Token& token : NumberTokens(key)) {
    if (!TokenHasDigit(key, token)) continue;
    const std::string_view typed =
        key.substr(token.begin, token.end - token.begin);
    size_t pos = candidate.find(typed, from);
    bool found = false;
    while (pos != std::string_view::npos) {
      if (MatchesAt(candidate, pos, typed.size())) {
        found = true;
        break;
      }
      pos = candidate.find(typed, pos + 1);
    }
    if (!found) return false;
    from = pos + typed.size();
  }
  return true;
}

inline bool IsUnitChar(char32_t c) {
  switch (c) {
    case 0x5341:  // 十
    case 0x767E:  // 百
    case 0x5343:  // 千
    case 0x4E07:  // 万
    case 0x5104:  // 億
    case 0x5146:  // 兆
      return true;
    default:
      return false;
  }
}

inline int KanjiDigitValue(char32_t c) {
  switch (c) {
    case 0x3007:  // 〇
    case 0x96F6:  // 零
      return 0;
    case 0x4E00:  // 一
    case 0x58F1:  // 壱
      return 1;
    case 0x4E8C:  // 二
    case 0x5F10:  // 弐
      return 2;
    case 0x4E09:  // 三
    case 0x53C2:  // 参
      return 3;
    case 0x56DB:  // 四
      return 4;
    case 0x4E94:  // 五
      return 5;
    case 0x516D:  // 六
      return 6;
    case 0x4E03:  // 七
      return 7;
    case 0x516B:  // 八
      return 8;
    case 0x4E5D:  // 九
      return 9;
    default:
      return -1;
  }
}

// Reads a number written with kanji numerals and/or typed digits (九百八十,
// 三億, 千, 3億, 1,000万). False on marks such as "." and "%".
inline int TypedDigitValue(char32_t c) {
  if (IsAsciiDigit(c)) return static_cast<int>(c - U'0');
  if (IsFullWidthDigit(c)) return static_cast<int>(c - 0xFF10);
  return -1;
}

inline bool ParseKanjiNumber(std::string_view text, long long* out) {
  long long total = 0;
  long long section = 0;
  long long number = 0;
  bool any = false;
  size_t i = 0;
  while (i < text.size()) {
    const size_t len = Utf8Length(static_cast<unsigned char>(text[i]));
    const size_t end = i + len <= text.size() ? i + len : text.size();
    const char32_t c = Decode(text.data() + i, end - i);
    if (c == U',' || c == 0xFF0C) {  // 桁区切り (1,000万)
      i = end;
      continue;
    }
    const int kanji_digit = KanjiDigitValue(c);
    const int digit = kanji_digit >= 0 ? kanji_digit : TypedDigitValue(c);
    if (digit >= 0) {
      number = digit;
      any = true;
    } else if (c == 0x5341 || c == 0x767E || c == 0x5343) {  // 十 百 千
      const long long unit = c == 0x5341 ? 10 : c == 0x767E ? 100 : 1000;
      section += (number == 0 ? 1 : number) * unit;
      number = 0;
      any = true;
    } else if (c == 0x4E07 || c == 0x5104 || c == 0x5146) {  // 万 億 兆
      const long long unit =
          c == 0x4E07 ? 10000LL : c == 0x5104 ? 100000000LL : 1000000000000LL;
      section += number;
      total += (section == 0 ? 1 : section) * unit;
      section = 0;
      number = 0;
      any = true;
    } else {
      return false;
    }
    i = end;
  }
  if (!any) return false;
  *out = total + section + number;
  return true;
}

inline bool ParseTypedInteger(std::string_view text, long long* out) {
  long long value = 0;
  bool any = false;
  for (size_t i = 0; i < text.size();) {
    const size_t len = Utf8Length(static_cast<unsigned char>(text[i]));
    const size_t end = i + len <= text.size() ? i + len : text.size();
    const char32_t c = Decode(text.data() + i, end - i);
    if (c == U',' || c == 0xFF0C) {  // 桁区切り (1,000万)
      i = end;
      continue;
    }
    const int digit = TypedDigitValue(c);
    if (digit < 0) return false;
    value = value * 10 + digit;
    any = true;
    i = end;
  }
  if (!any) return false;
  *out = value;
  return true;
}

// Writes the typed spelling of one candidate number token. A trailing kanji
// unit stays when the kanji before it has the same value as the typed number:
// 三億 -> 3億, 二千円 -> 2千円. A full kanji spelling is replaced whole:
// 九百八十円 -> 980円, 百円 -> 100円.
inline void ReplaceNumberToken(std::string_view typed, std::string_view kanji,
                               std::string* out) {
  out->assign(typed);
  long long typed_value;
  if (!ParseTypedInteger(typed, &typed_value)) return;
  std::vector<size_t> starts;
  for (size_t i = 0; i < kanji.size();) {
    starts.push_back(i);
    const size_t len = Utf8Length(static_cast<unsigned char>(kanji[i]));
    i += i + len <= kanji.size() ? len : kanji.size() - i;
  }
  // Try the longest trailing unit run first: the part before it must be the
  // typed number itself.
  for (size_t j = 1; j < starts.size(); ++j) {
    const std::string_view suffix = kanji.substr(starts[j]);
    bool units = !suffix.empty();
    for (size_t i = 0; i < suffix.size();) {
      const size_t len = Utf8Length(static_cast<unsigned char>(suffix[i]));
      const size_t end = i + len <= suffix.size() ? i + len : suffix.size();
      if (!IsUnitChar(Decode(suffix.data() + i, end - i))) units = false;
      i = end;
    }
    if (!units) continue;
    long long prefix_value;
    if (!ParseKanjiNumber(kanji.substr(0, starts[j]), &prefix_value)) continue;
    if (prefix_value != typed_value) continue;
    out->append(suffix);
    return;
  }
}

inline bool CandidateIndices(size_t candidate_count, const std::vector<Token>& typed,
                             std::string_view key, std::vector<size_t>* out) {
  out->clear();
  if (typed.empty()) return false;
  if (typed.front().begin == 0) {
    if (candidate_count < typed.size()) return false;
    for (size_t i = 0; i < typed.size(); ++i) out->push_back(i);
    return true;
  }
  if (typed.back().end == key.size()) {
    if (candidate_count < typed.size()) return false;
    for (size_t i = candidate_count - typed.size(); i < candidate_count; ++i) {
      out->push_back(i);
    }
    return true;
  }
  if (candidate_count != typed.size()) return false;
  for (size_t i = 0; i < candidate_count; ++i) out->push_back(i);
  return true;
}

// Puts the key's typed number tokens into candidate, leaving the other text
// alone. False when the tokens cannot be placed without guessing.
inline bool ReplaceWithTypedDigits(std::string_view key, std::string_view candidate,
                                   std::string* out) {
  if (out == nullptr || !HasTypedDigit(key)) return false;
  std::vector<Token> typed;
  for (const Token& token : NumberTokens(key)) {
    if (TokenHasDigit(key, token)) typed.push_back(token);
  }
  if (typed.empty()) return false;
  const std::vector<Token> candidate_tokens = NumberTokens(candidate);

  // A decimal read with 点 or ・ between the digits (三点一四 for 3.14): the
  // gap must be only that mark, so 九百八十円と二 (a gap of 円と) is not taken.
  bool key_has_mark = false;
  for (size_t i = typed[0].begin; i < typed[0].end;) {
    const size_t len = Utf8Length(static_cast<unsigned char>(key[i]));
    const size_t end = i + len <= typed[0].end ? i + len : typed[0].end;
    if (IsNumberMark(Decode(key.data() + i, end - i))) key_has_mark = true;
    i = end;
  }
  if (key_has_mark && typed.size() == 1 && candidate_tokens.size() > 1) {
    bool decimal_marks = true;
    for (size_t i = 1; i < candidate_tokens.size(); ++i) {
      const std::string_view gap(
          candidate.data() + candidate_tokens[i - 1].end,
          candidate_tokens[i].begin - candidate_tokens[i - 1].end);
      if (gap != "点" && gap != "．" && gap != "." && gap != "・") {
        decimal_marks = false;
      }
    }
    if (decimal_marks) {
      std::string result(candidate.substr(0, candidate_tokens.front().begin));
      result.append(key.substr(typed[0].begin, typed[0].end - typed[0].begin));
      result.append(candidate.substr(candidate_tokens.back().end));
      *out = std::move(result);
      return true;
    }
  }

  std::vector<size_t> replace_at;
  if (!CandidateIndices(candidate_tokens.size(), typed, key, &replace_at)) {
    return false;
  }

  std::string result;
  size_t at = 0;
  size_t next = 0;
  for (size_t i = 0; i < candidate_tokens.size(); ++i) {
    const Token& token = candidate_tokens[i];
    result.append(candidate.data() + at, token.begin - at);
    const std::string_view value =
        candidate.substr(token.begin, token.end - token.begin);
    // |replace_at| is in increasing order, so a simple cursor is enough.
    const bool replace = next < replace_at.size() && replace_at[next] == i;
    if (replace) {
      const Token& key_token = typed[next];
      const std::string_view typed_value =
          key.substr(key_token.begin, key_token.end - key_token.begin);
      std::string replaced;
      ReplaceNumberToken(typed_value, value, &replaced);
      result.append(replaced);
      ++next;
    } else {
      result.append(value);
    }
    at = token.end;
  }
  if (next != typed.size()) return false;
  result.append(candidate.data() + at, candidate.size() - at);
  *out = std::move(result);
  return true;
}

}  // namespace typed_digits
}  // namespace
