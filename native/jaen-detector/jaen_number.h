// Finds readings of a number plus a counter in kana ("にじゅうよっか",
// "さんびゃくえん") and writes them as half-width digits with the counter's
// kanji ("24日", "300円"). A bare digit with a counter ("にほん", "くじ") is
// left alone because it is far more often an ordinary word.
#ifndef JAEN_NUMBER_H_
#define JAEN_NUMBER_H_

#include <cstddef>
#include <string>
#include <string_view>
#include <vector>

namespace jaen {

struct NumberSpan {
  size_t begin;  // index of the first character (one UTF-8 character each)
  size_t end;    // one past the last character
  std::string value;
};

// Non-overlapping spans found left to right, the longest first at each start.
// |kana| is UTF-8 hiragana (ー allowed). Taken: a number of two or more digits
// or with じゅう/ひゃく/せん/まん/おく plus a counter; the special day readings
// (ついたち ... はつか); "月" followed by a day ("ごがつむいか" -> "5月6日");
// ごぜん/ごご plus an hour ("ごぜんくじ" -> "午前9時"). 回 and 階 both read かい
// and are written 回. "じゅうぶん" is left alone (10分 or 十分).
std::vector<NumberSpan> FindNumbers(std::string_view kana);

}  // namespace jaen

#endif  // JAEN_NUMBER_H_
