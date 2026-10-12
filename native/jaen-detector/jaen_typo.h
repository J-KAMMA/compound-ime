// Fixes one mistyped key in romaji that the romaji table cannot read, e.g.
// "tokyp" (と + unread "kyp") -> "tokyo" (ときょ). Romaji that reads as kana is
// never touched: "kyouu" or "ka" for "ko" cannot be told from intent.
#ifndef JAEN_TYPO_H_
#define JAEN_TYPO_H_

#include <optional>
#include <span>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>

#include "jaen_detector.h"

namespace jaen {

struct KanaTrigram {
  const char* text;  // three kana; "^" and "$" mark reading edges
  int count;
};

// How Japanese-like a kana string is, from trigram counts of dictionary readings.
class KanaModel {
 public:
  explicit KanaModel(std::span<const KanaTrigram> trigrams);
  // Log-probability of |kana| (UTF-8 hiragana and ー) as a reading.
  double Score(std::string_view kana) const;

 private:
  std::unordered_map<std::string, int> trigrams_;
  std::unordered_map<std::string, int> contexts_;  // first two characters
};

// Keys the table left unread (ASCII letters in a chunk), apart from a final
// "n" that becomes ん.
int UnreadKeys(const std::vector<Chunk>& chunks);

// The typed keys |raw| with one edit (adjacent-key substitution, swapped
// neighbors, a dropped or doubled key, or a missing vowel) near the first
// unread key, after which every key is read as kana; the reading |model|
// scores highest wins. nullopt when |raw| already reads, is too long, no
// single edit fixes it, the best reading beats the runner-up (a different
// reading) by less than |margin| (natural log), or its average log-probability
// per kana (end mark included) is below |floor|. Only lowercase romaji typed in
// kana mode is considered.
std::optional<std::string> FixTypo(std::string_view raw, const RomajiParser& parse,
                                   const KanaModel& model, double margin = 3.0,
                                   double floor = -4.5);

}  // namespace jaen

#endif  // JAEN_TYPO_H_
