// Loanword katakana for readings Mozc has no word for (エンマータール typed
// えんまーたーる came out as 閻魔ータール; ヘーメルシェンブルク as
// ヘ|ー|メ|ルシェン|ブル...). Mozc's dictionary has no node for an unknown
// loanword, so its best path cuts the reading into short words, and a long
// vowel mark or a foreign small vowel (しぇ, つぃ, ねー) is left at the start
// of a node, cut from the kana it belongs to. Japanese words never leave such
// a cut: ー and しぇ live inside a word (ルーツ, シェア) or after a word that
// ends in the same vowel (ねぇ, すごーい).
//
// FindSpans looks at the best path once. For each node that starts with a cut
// sound, it proposes katakana spans from the node just before it to one of
// the next three nodes, and ImmutableConverter puts them in the lattice as
// general nouns and runs Viterbi again. A span is never proposed when
//   - it would hold anything but kana (kanji, digits, symbols) in the key,
//   - it would end on the cut sound itself (ほんとー, だめー stay as they are),
//   - a node after the cut sound is a particle or an auxiliary in hiragana
//     (は, の, より...) or a verb or adjective: the loanword ends before them,
//   - it would take in more than one kanji node, or a kanji node of two or
//     more characters, after the cut sound (大陸, 地方, 結婚 stay words).
// The span still has to beat Mozc's own path in Viterbi: its cost is
// kBaseCost + kCostPerChar per character.
//
// Measured with a Viterbi over dictionary_oss and the connection matrix
// (2026-10-29): tests/conversion/wiki-typing.tsv 12 sentences changed (10
// closer to the expectation, 0 farther), 6000 other Wikipedia sentences 24
// changed (23 closer, 0 farther), colloquial.tsv and context.tsv unchanged.
//
// This file is included in converter/immutable_converter.cc (inside an
// anonymous namespace) and by native/jaen-detector/loanword_katakana_test.cc.
namespace loanword_katakana {

inline constexpr int kBaseCost = 5000;
inline constexpr int kCostPerChar = 500;
inline constexpr size_t kMaxRightNodes = 3;
inline constexpr size_t kMinChars = 3;
inline constexpr size_t kMaxChars = 16;

// One node of the best path. begin and end are byte offsets in the lattice key.
struct PathNode {
  size_t begin = 0;
  size_t end = 0;
  std::string value;
  // A verb or adjective (PosMatcher::IsContentWordWithConjugation).
  bool conjugating = false;
  // A particle, auxiliary or other function word (PosMatcher::IsFunctional or
  // IsSuffixWord).
  bool functional = false;
};

struct Span {
  size_t begin = 0;
  size_t end = 0;
  std::string value;  // katakana
  int cost = 0;
};

// Decodes UTF-8 (the key and values are valid UTF-8; a broken byte becomes 0).
inline std::u32string ToChars(std::string_view text) {
  std::u32string out;
  for (size_t i = 0; i < text.size();) {
    const unsigned char b0 = static_cast<unsigned char>(text[i]);
    size_t length = b0 < 0x80 ? 1 : b0 >= 0xF0 ? 4 : b0 >= 0xE0 ? 3 : b0 >= 0xC0 ? 2 : 1;
    if (i + length > text.size()) length = 1;
    char32_t c = length == 1 ? (b0 < 0x80 ? b0 : 0)
                 : length == 2 ? (b0 & 0x1F)
                 : length == 3 ? (b0 & 0x0F)
                               : (b0 & 0x07);
    for (size_t k = 1; k < length; ++k) c = (c << 6) | (static_cast<unsigned char>(text[i + k]) & 0x3F);
    out.push_back(c);
    i += length;
  }
  return out;
}

inline void AppendUtf8(char32_t c, std::string* out) {
  if (c < 0x80) {
    out->push_back(static_cast<char>(c));
  } else if (c < 0x800) {
    out->push_back(static_cast<char>(0xC0 | (c >> 6)));
    out->push_back(static_cast<char>(0x80 | (c & 0x3F)));
  } else if (c < 0x10000) {
    out->push_back(static_cast<char>(0xE0 | (c >> 12)));
    out->push_back(static_cast<char>(0x80 | ((c >> 6) & 0x3F)));
    out->push_back(static_cast<char>(0x80 | (c & 0x3F)));
  } else {
    out->push_back(static_cast<char>(0xF0 | (c >> 18)));
    out->push_back(static_cast<char>(0x80 | ((c >> 12) & 0x3F)));
    out->push_back(static_cast<char>(0x80 | ((c >> 6) & 0x3F)));
    out->push_back(static_cast<char>(0x80 | (c & 0x3F)));
  }
}

inline constexpr char32_t kLongVowel = 0x30FC;  // ー

inline bool IsHiragana(char32_t c) { return c >= 0x3041 && c <= 0x3096; }
inline bool IsKana(char32_t c) { return IsHiragana(c) || c == kLongVowel; }
inline bool IsKanji(char32_t c) { return (c >= 0x4E00 && c <= 0x9FAF) || c == 0x3005; }

// The vowel of a hiragana (0 for ん and the rest).
inline char Vowel(char32_t c) {
  static constexpr std::u32string_view kRows[] = {
      U"あかさたなはまやらわがざだばぱぁゃゎ", U"いきしちにひみりぎじぢびぴぃ",
      U"うくすつぬふむゆるぐずづぶぷぅゅゔっ", U"えけせてねへめれげぜでべぺぇ",
      U"おこそとのほもよろをごぞどぼぽぉょ"};
  static constexpr char kVowels[] = {'a', 'i', 'u', 'e', 'o'};
  for (size_t row = 0; row < 5; ++row) {
    if (kRows[row].find(c) != std::u32string_view::npos) return kVowels[row];
  }
  return 0;
}

// The vowel of a small vowel kana ぁぃぅぇぉ (0 for anything else).
inline char SmallVowel(char32_t c) {
  switch (c) {
    case U'ぁ': return 'a';
    case U'ぃ': return 'i';
    case U'ぅ': return 'u';
    case U'ぇ': return 'e';
    case U'ぉ': return 'o';
    default: return 0;
  }
}

// `c` starts a node right after the kana `prev` and belongs to it: a long
// vowel mark, or a small vowel that does not repeat prev's vowel (しぇ, つぃ,
// ふぁ; not ねぇ or わぁ).
inline bool StartsCutSound(char32_t prev, char32_t c) {
  if (!IsKana(prev) || prev == kLongVowel) return false;
  if (c == kLongVowel) return true;
  const char small = SmallVowel(c);
  const char vowel = Vowel(prev);
  return small != 0 && vowel != 0 && vowel != small;
}

// The loanword ends before this node: a verb or adjective, or a particle or
// auxiliary written in hiragana (a fragment such as ぇ or ぃ is not one).
inline bool EndsLoanword(const PathNode& node) {
  if (node.conjugating) return true;
  const std::u32string value = ToChars(node.value);
  if (value.empty() || SmallVowel(value[0]) != 0) return false;
  for (const char32_t c : value) {
    if (!IsHiragana(c)) return false;
  }
  static constexpr std::u32string_view kParticles[] = {
      U"は", U"が", U"を", U"に", U"で", U"と", U"も", U"へ", U"や", U"の", U"か", U"ね", U"よ",
      U"より", U"から", U"まで", U"など", U"って"};
  for (const auto particle : kParticles) {
    if (value == particle) return true;
  }
  return node.functional;
}

inline std::string ToKatakana(std::u32string_view kana) {
  std::string out;
  for (const char32_t c : kana) AppendUtf8(IsHiragana(c) ? c + 0x60 : c, &out);
  return out;
}

// Katakana spans to add to the lattice for the best path `path` (BOS and EOS
// left out) over `key`. Only nodes at or after `conversion_begin` (the end of
// the history segments) are looked at.
inline std::vector<Span> FindSpans(std::string_view key, size_t conversion_begin,
                                   const std::vector<PathNode>& path) {
  std::vector<Span> spans;
  for (size_t n = 1; n < path.size(); ++n) {
    const PathNode& left = path[n - 1];
    const PathNode& cut = path[n];
    if (left.begin < conversion_begin || left.end != cut.begin || cut.begin > key.size() ||
        cut.end > key.size() || left.begin >= cut.begin || cut.begin >= cut.end) {
      continue;
    }
    const std::u32string before = ToChars(key.substr(left.begin, cut.begin - left.begin));
    const std::u32string first = ToChars(key.substr(cut.begin, cut.end - cut.begin));
    if (before.empty() || first.empty() || !StartsCutSound(before.back(), first[0])) continue;
    int kanji_nodes = 0;
    bool long_kanji = false;
    for (size_t j = n + 1; j < path.size() && j <= n + kMaxRightNodes; ++j) {
      const PathNode& right = path[j];
      if (right.begin != path[j - 1].end || right.end > key.size() || right.begin >= right.end) break;
      // Same order of checks for every j: a node that ends the loanword ends
      // every longer span too.
      if (EndsLoanword(right)) break;
      const std::u32string right_value = ToChars(right.value);
      bool has_kanji = false;
      for (const char32_t c : right_value) has_kanji = has_kanji || IsKanji(c);
      if (has_kanji) {
        ++kanji_nodes;
        if (right_value.size() > 1) long_kanji = true;
      }
      if (kanji_nodes > 1 || long_kanji) break;
      const std::u32string kana = ToChars(key.substr(left.begin, right.end - left.begin));
      bool all_kana = true;
      for (const char32_t c : kana) all_kana = all_kana && IsKana(c);
      if (!all_kana) break;
      static constexpr std::u32string_view kNoStart = U"ーっんゃゅょぁぃぅぇぉ";
      if (kNoStart.find(kana[0]) != std::u32string_view::npos) break;
      if (kana.size() < kMinChars) continue;
      if (kana.size() > kMaxChars) break;
      bool seen = false;
      for (const Span& s : spans) seen = seen || (s.begin == left.begin && s.end == right.end);
      if (seen) continue;
      spans.push_back(Span{left.begin, right.end, ToKatakana(kana),
                           kBaseCost + kCostPerChar * static_cast<int>(kana.size())});
    }
  }
  return spans;
}

}  // namespace loanword_katakana
