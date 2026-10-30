// Words of the text before the cursor (前の文) that the conversion may write the
// same way again: a name or a term written once (エドサル, 伴馬, 帰還) is likely
// meant again when its reading comes up in the next sentence.
#ifndef JAEN_CONTEXT_WORDS_H_
#define JAEN_CONTEXT_WORDS_H_

#include <cstddef>
#include <functional>
#include <string>
#include <string_view>
#include <vector>

namespace jaen {

// A word of the dictionary: how it is written and its reading (hiragana).
struct DictionaryWord {
  std::string value;
  std::string reading;
};
// The dictionary words whose reading is a prefix of the hiragana |key| (every
// way of writing each; Mozc's LookupPrefix).
using PrefixLookup = std::function<std::vector<DictionaryWord>(std::string_view key)>;

struct ContextMatch {
  std::string surface;    // as written before (エドサル, 伴馬)
  size_t bytes = 0;       // bytes of the key its reading takes
  bool katakana = false;  // a katakana word (read as written)
  bool composed = false;  // read with a single kanji of the dictionary (a name not in it: 伴馬)
};

class ContextWords {
 public:
  // The last |max_chars| characters of |preceding| count.
  explicit ContextWords(std::string_view preceding, size_t max_chars = 200);

  // The words of the text whose reading the hiragana |key| starts with at byte
  // |begin|, longest reading first (a dictionary word before a composed one):
  //  - a katakana run (2+ characters, read as written, 2+ kana);
  //  - a dictionary word of 2+ kanji inside a kanji run (3+ kana);
  //  - a whole kanji run read as dictionary words one after another, single
  //    kanji included (伴馬: 伴 + 馬, 蜀地方: 蜀 + 地方; 3+ kana).
  // Without |lookup| only katakana runs are matched.
  std::vector<ContextMatch> MatchAt(std::string_view key, size_t begin, const PrefixLookup* lookup) const;

  // Whether a katakana run reads |kana| (ヴァネッサ: ゔぁねっさ).
  bool HasKatakanaReading(std::string_view kana) const;

  bool empty() const { return katakana_.empty() && kanji_.empty(); }

  // Fewest kana of a reading: 2 for katakana (パン, リク), 3 for kanji (an
  // unrelated sentence's ほか or しよう is too common to follow).
  static constexpr size_t kMinKatakanaReading = 2;
  static constexpr size_t kMinKanjiReading = 3;

 private:
  struct Katakana {
    std::string surface;
    std::string reading;
  };
  std::vector<Katakana> katakana_;
  std::vector<std::string> kanji_;  // runs of 2+ kanji, each once
};

}  // namespace jaen

#endif  // JAEN_CONTEXT_WORDS_H_
