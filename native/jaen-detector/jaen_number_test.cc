#include <iostream>
#include <string>
#include <vector>

#include "jaen_number.h"

namespace {

int g_total = 0;
int g_failed = 0;

std::string Describe(const std::vector<jaen::NumberSpan>& spans) {
  std::string out;
  for (const jaen::NumberSpan& s : spans) {
    if (!out.empty()) out += "|";
    out += s.value;
  }
  return out;
}

// |expected| is the values joined by "|"; empty means nothing is found.
void Check(const std::string& kana, const std::string& expected) {
  ++g_total;
  const std::string got = Describe(jaen::FindNumbers(kana));
  if (got != expected) {
    ++g_failed;
    std::cout << "FAIL " << kana << " expected [" << expected << "] got [" << got << "]\n";
  }
}

void CheckSpan(const std::string& kana, size_t begin, size_t end, const std::string& value) {
  ++g_total;
  const std::vector<jaen::NumberSpan> spans = jaen::FindNumbers(kana);
  if (spans.size() != 1 || spans[0].begin != begin || spans[0].end != end ||
      spans[0].value != value) {
    ++g_failed;
    std::cout << "FAIL span " << kana << " expected " << begin << "-" << end << " " << value
              << " got " << Describe(spans) << "\n";
  }
}

}  // namespace

int main() {
  // Taken.
  Check("にじゅうよっか", "24日");
  Check("じゅうよっか", "14日");
  Check("さんじゅうにち", "30日");
  Check("にせんにじゅうろくねん", "2026年");
  Check("にぜろにろくねん", "2026年");
  Check("ろくじゅうぱーせんと", "60%");
  Check("じゅっぷん", "10分");
  Check("じっぷん", "10分");
  Check("さんびゃくえん", "300円");
  Check("ろっぴゃくえん", "600円");
  Check("はっぴゃくえん", "800円");
  Check("さんぜんえん", "3000円");
  Check("はっせんえん", "8000円");
  Check("ひゃくにん", "100人");
  Check("しちがつはつか", "7月20日");
  Check("ごがつむいか", "5月6日");
  Check("ごがつさんにち", "5月3日");
  Check("ごぜんくじ", "午前9時");
  Check("ごごじゅうにじ", "午後12時");
  Check("じゅうにがつ", "12月");
  Check("ついたち", "1日");
  Check("ふつか", "2日");
  Check("みっか", "3日");
  Check("よっか", "4日");
  Check("とおか", "10日");
  Check("はつか", "20日");
  Check("にじゅうここのか", "29日");
  Check("じゅうにちかん", "10日間");
  Check("にじゅうしゅうかん", "20週間");
  Check("じゅうにかげつ", "12か月");
  Check("じゅうにじかん", "12時間");
  Check("じゅうごばんめ", "15番目");
  Check("じゅっかいめ", "10回目");
  Check("にじゅうにんまえ", "20人前");
  Check("じゅうにほん", "12本");
  Check("じゅうごさい", "15歳");
  Check("ひゃくまんえん", "1000000円");
  Check("ごじゅうびょう", "50秒");
  Check("きゅうじゅうきゅうけん", "99件");
  // Several spans, and positions in characters.
  Check("きょうはごがつむいかで、じゅうにん", "5月6日|10人");
  CheckSpan("あさじゅうじ", 2, 6, "10時");
  CheckSpan("ごじゅうぱーせんと", 0, 9, "50%");
  // Everyday-looking day words: only after 月 or じゅう.
  Check("ごがついつか", "5月5日");
  Check("ごがつむいか", "5月6日");
  Check("しちがつなのか", "7月7日");
  Check("ごがつようか", "5月8日");
  Check("じゅうにがつここのか", "12月9日");
  Check("じゅういつか", "15日");
  Check("じゅうむいか", "16日");
  Check("にじゅうなのか", "27日");
  Check("じゅうようか", "18日");
  Check("いつか", "");
  Check("むいか", "");
  Check("なのか", "");
  Check("ようか", "");
  Check("ここのか", "");
  Check("いつかくる", "");
  Check("そうなのか", "");
  Check("いこうようか", "");
  Check("ここのかぎ", "");
  Check("いつかきてね", "");
  // Right boundary.
  Check("にじゅうよっかまでに", "24日");
  Check("にせんにじゅうろくねんの", "2026年");
  Check("さんびゃくえんから", "300円");
  Check("ひゃくにんより", "100人");
  Check("じゅうにんって", "10人");
  Check("ひゃくえんと", "100円");
  Check("ひゃくえんが", "100円");
  Check("ひゃくえんをもらう", "100円");
  Check("ひゃくえんへ", "100円");
  Check("ひゃくえんや", "100円");
  Check("じゅっぷんもかかる", "10分");
  Check("ひゃくにん、にひゃくにん", "100人|200人");
  Check("じゅうにんにじゅうにん", "10人|20人");
  Check("じゅうにんごぜんくじ", "10人|午前9時");
  Check("じゅうこく", "");
  Check("さんびゃくえんけい", "");
  Check("ひゃくえんだま", "");
  Check("じゅうにんしゅ", "");
  // Longer counters before shorter ones.
  Check("じゅうじかん", "10時間");
  Check("さんじゅうしゅうかん", "30週間");
  Check("じゅうにちかん", "10日間");
  Check("じゅうごかいめ", "15回目");
  Check("じゅうごばんめ", "15番目");
  Check("じゅうにんまえ", "10人前");
  Check("じゅうにかげつ", "12か月");
  // Left alone.
  Check("にほん", "");
  Check("いちにち", "");
  Check("くじびき", "");
  Check("じゅうたく", "");
  Check("ごがつ", "");
  Check("きょうは", "");
  Check("にんじん", "");
  Check("さんぽ", "");
  Check("いっしょ", "");
  Check("じゅうぶん", "");
  Check("ひとり", "");
  Check("ふたり", "");
  Check("ぐんじん", "");
  Check("ごご", "");
  Check("", "");
  std::cout << "SUMMARY " << g_failed << " (" << g_total << " checks)\n";
  return g_failed == 0 ? 0 : 1;
}
