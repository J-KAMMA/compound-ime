// 数の読み＋単位をかなから見つけ、算用数字と単位の漢字にする
// （にじゅうよっか -> 24日、さんびゃくえん -> 300円、じゅうにん -> 10人）。
// 二つ以上の部分からなる数（にひゃく、さんぜん、にせんにじゅうろく）はすべて取る。
// 一つの部分だけの数は、じゅう（10）と促音の いっ・ろっ・はっ・じゅっ・じっ だけ取る:
// ふつうの1けた＋単位（にほん、くじ、いちにち）は普通の言葉と紛れるため取らない。
// ひゃく・せん だけの数（ひゃくえん）も、百姓・千葉・仙台・先輩と紛れるため取らない。
// 和語の日の言葉（ふつか、ついたち）は単独では取らず、月のあと（ごがつむいか）と
// 十の付く日（にじゅうよっか）だけ数字にする。数の形の普通の言葉（十分、実験、実際、
// 発展、一見、一転、従妹、重大、重度、重版、充填、重点）は取らない。
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
// |kana| is UTF-8 hiragana (ー allowed). Taken: a number plus a counter, with
// the exceptions above; the tens day readings ("にじゅうよっか" -> "24日",
// "じゅうよっか" -> "14日"); "月" followed by a day ("ごがつむいか" ->
// "5月6日"); ごぜん/ごご plus an hour ("ごぜんくじ" -> "午前9時"). 回 and 階
// both read かい and are written 回. ばい is written 倍 and はい/ぱい 杯.
std::vector<NumberSpan> FindNumbers(std::string_view kana);

}  // namespace jaen

#endif  // JAEN_NUMBER_H_
