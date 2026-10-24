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
  // 数＋単位: 二つ以上の部分からなる数（にひゃっぷん、さんぜんえん ...）。
  Check("にじゅうよっか", "24日");
  Check("じゅうよっか", "14日");
  Check("さんじゅうにち", "30日");
  Check("にせんにじゅうろくねん", "2026年");
  Check("にぜろにろくねん", "2026年");
  Check("ろくじゅうぱーせんと", "60%");
  Check("にひゃっぷん", "200分");
  Check("にじゅっぷん", "20分");
  Check("さんじっぷん", "30分");
  Check("じゅうごふん", "15分");
  Check("にじゅうごふん", "25分");
  Check("さんびゃくえん", "300円");
  Check("ろっぴゃくえん", "600円");
  Check("はっぴゃくえん", "800円");
  Check("さんぜんえん", "3000円");
  Check("はっせんえん", "8000円");
  Check("ごせんえん", "5000円");
  Check("にひゃくにん", "200人");
  Check("さんじゅうにん", "30人");
  Check("さんぜんにん", "3000人");
  Check("にせんにん", "2000人");
  Check("しちがつはつか", "7月20日");
  Check("ごがつむいか", "5月6日");
  Check("ごがつさんにち", "5月3日");
  Check("ごぜんくじ", "午前9時");
  Check("ごごじゅうにじ", "午後12時");
  Check("じゅうがつ", "10月");
  Check("じゅういちがつ", "11月");
  Check("じゅうにがつ", "12月");
  Check("じゅうにち", "10日");
  Check("にじゅうにち", "20日");
  Check("にじゅうにちかん", "20日間");
  Check("じゅうびょう", "10秒");
  Check("にじゅうびょう", "20秒");
  Check("にひゃくびょう", "200秒");
  Check("じゅうねん", "10年");
  Check("にじゅうねん", "20年");
  Check("ごひゃくねん", "500年");
  Check("にひゃくねん", "200年");
  Check("じゅうえん", "10円");
  Check("にじゅうえん", "20円");
  Check("じゅうけん", "10件");
  Check("にじゅうけん", "20件");
  Check("じゅうさつ", "10冊");
  Check("にじゅうさつ", "20冊");
  Check("にじゅうまい", "20枚");
  Check("にじゅうだい", "20台");
  Check("にじゅうど", "20度");
  Check("にじゅうばん", "20番");
  Check("じゅうばい", "10倍");
  Check("にじゅうばい", "20倍");
  Check("にひゃくばい", "200倍");
  Check("じゅうわり", "10割");
  Check("にじゅうわり", "20割");
  Check("じゅってん", "10点");
  Check("にじゅってん", "20点");
  Check("にひゃくてん", "200点");
  Check("じゅうてん", "10点");
  Check("にじゅうてん", "20点");
  Check("じゅうじ", "10時");
  Check("じゅうまい", "10枚");
  Check("じゅうだい", "10台");
  Check("じゅうど", "10度");
  Check("じゅうばん", "10番");
  Check("じゅうじから", "10時");
  Check("じゅうまいを", "10枚");
  Check("じゅうだいの", "10台");
  Check("じゅうばんの", "10番");
  Check("じゅうてんを", "10点");
  Check("じゅうどの", "10度");
  Check("にじゅうてんを", "20点");
  Check("じゅうにじ", "12時");
  Check("にじゅうじ", "20時");
  Check("じゅうにんまえ", "10人前");
  Check("じゅうじかん", "10時間");
  Check("じゅうにちかん", "10日間");

  // 一つの部分でも単位が続けば数: じゅう（10）と促音の いっ・ろっ・はっ・じゅっ・じっ。
  Check("じゅうにん", "10人");
  // 助詞の に のあとの数（ここに 10人 / きょうは 20人）。
  Check("ここにじゅうにんがいます", "10人");
  Check("きょうはにじゅうにんがいます", "20人");
  Check("がっこうににじゅうにんがいます", "20人");
  Check("ここにひゃくえんがあります", "");
  Check("ここにじゅうぶんがあります", "");
  // 時の言葉のあとの に は助詞ではなく数の一部（きょう20人）。
  Check("きょうにじゅうにん", "20人");
  Check("きのうにじゅうにん", "20人");
  Check("あしたにじゅうにん", "20人");
  Check("きょうにじゅうにん。", "20人");
  Check("！にじゅうにん", "20人");
  Check("「にじゅうにん」", "20人");
  // 文末・句読点・閉じ括弧のあとも右の境界として取る。
  Check("にひゃっぷん。", "200分");
  Check("にじゅうにん。", "20人");
  Check("さんぜんえん。", "3000円");
  Check("にせんにじゅうろくねん。", "2026年");
  Check("にひゃっぷん、", "200分");
  Check("にひゃっぷん！", "200分");
  Check("にひゃっぷん？", "200分");
  Check("にひゃっぷん!", "200分");
  Check("にひゃっぷん?", "200分");
  Check("にひゃっぷん!", "200分");
  Check("[にひゃっぷん]", "200分");
  Check("「にひゃっぷん」", "200分");
  Check("にじゅうねんごにまたあいましょう", "20年");
  Check("よんじゅっぷんまちました", "40分");
  Check("にじゅうにんご", "20人");
  Check("（にひゃっぷん）", "200分");
  Check("じゅっぷん", "10分");
  Check("じっぷん", "10分");
  Check("じゅっぴき", "10匹");
  Check("じゅっこ", "10個");
  Check("じゅっぽん", "10本");
  Check("じゅっかい", "10回");
  Check("じゅっさい", "10歳");
  Check("じゅっぱい", "10杯");
  Check("ななじゅっさい", "70歳");
  Check("にじゅっさい", "20歳");
  Check("にひゃくさい", "200歳");
  Check("いっぷん", "1分");
  Check("いっぴき", "1匹");
  Check("いっこ", "1個");
  Check("いっぽん", "1本");
  Check("いっかい", "1回");
  Check("いっさつ", "1冊");
  Check("ろっぷん", "6分");
  Check("ろっぴき", "6匹");
  Check("ろっこ", "6個");
  Check("ろっぽん", "6本");
  Check("ろっかい", "6回");
  Check("はっぷん", "8分");
  Check("はっぴき", "8匹");
  Check("はっこ", "8個");
  Check("はっぽん", "8本");
  Check("はっかい", "8回");
  Check("はっさい", "8歳");
  Check("はっさつ", "8冊");
  Check("はっぱい", "8杯");
  Check("ろっぴゃくにん", "600人");
  Check("はっぴゃくにん", "800人");

  // 和語の数の言葉は漢字のまま（数字にしない）。
  Check("ついたち", "");
  Check("ふつか", "");
  Check("みっか", "");
  Check("よっか", "");
  Check("とおか", "");
  Check("はつか", "");
  Check("ここのか", "");
  Check("いつか", "");
  Check("むいか", "");
  Check("なのか", "");
  Check("ようか", "");
  Check("ふつかかん", "");
  Check("みっかかんも", "");
  Check("よっかかんで", "");
  Check("むいかかん", "");
  Check("とおかかんは", "");
  Check("はつかかん", "");
  Check("ここのかかんの", "");
  Check("ついたちかん", "");
  Check("ひとつ", "");
  Check("ふたり", "");
  Check("みっつ", "");
  Check("はたち", "");

  // 数の形をした普通の言葉は漢字のまま。
  Check("じゅうぶんです", "");
  Check("いっしょにいく", "");
  Check("いっぱい", "");
  Check("いっぱいのむ", "");
  Check("いっさい", "");
  Check("いっさいがっさい", "");
  Check("いっかい", "1回");  // 一回・一階 はどちらも数の意味
  Check("はっかい", "8回");  // 発会 はまれなので数のまま
  Check("いちどだけ", "");
  Check("いちばんすき", "");
  Check("いちぶのかいしゃ", "");
  Check("いっぱんてき", "");
  Check("いちおうかくにん", "");
  Check("みっかぼうず", "");
  Check("ひゃくしょう", "");
  Check("ちばけん", "");
  Check("まんいち", "");
  Check("やおや", "");
  Check("しき", "");
  Check("いちにち", "");
  Check("にほん", "");
  Check("くじ", "");
  Check("にじ", "");
  Check("ごじ", "");
  Check("さんじ", "");
  Check("いちじ", "");
  Check("さんにん", "");
  Check("ろくじ", "");
  Check("ひゃくえん", "");
  Check("さんびき", "");
  Check("せんえん", "");
  Check("まんえん", "");

  // 音の変わる読みと紛れる普通の言葉（数字にしない）。
  Check("じっけん", "");
  Check("じっさい", "");
  Check("はってん", "");
  Check("はっけん", "");
  Check("いっけん", "");
  Check("いってん", "");

  // Several spans, and positions in characters.
  Check("きょうはごがつむいかで、にじゅうにん", "5月6日|20人");
  CheckSpan("あさじゅうにじ", 2, 7, "12時");
  CheckSpan("ごじゅうぱーせんと", 0, 9, "50%");
  CheckSpan("きょうはじゅうにん", 4, 9, "10人");

  // Everyday-looking day words: only after 月 or with a tens number.
  Check("ごがついつか", "5月5日");
  Check("ごがつむいか", "5月6日");
  Check("しちがつなのか", "7月7日");
  Check("ごがつようか", "5月8日");
  Check("じゅうにがつここのか", "12月9日");
  Check("じゅういつか", "15日");
  Check("じゅうむいか", "16日");
  Check("にじゅうなのか", "27日");
  Check("じゅうようか", "18日");

  // Codes read digit by digit.
  Check("でんわばんごうはぜろきゅうぜろからはじまる", "090");
  Check("ないせんばんごうはにいちさんです", "213");
  Check("ぜろさんのしがいきょくばん", "");  // two digits only: no code
  Check("ぜろからやりなおす", "");
  Check("ばんごうはにばんです", "");  // one digit and a unit stays a word
  Check("おにいさんです", "");
  Check("さんじゅうにんです", "30人");
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
  Check("にひゃくにんより", "200人");
  Check("にじゅうにんって", "20人");
  Check("さんびゃくえんと", "300円");
  Check("さんびゃくえんが", "300円");
  Check("さんびゃくえんをもらう", "300円");
  Check("さんびゃくえんへ", "300円");
  Check("さんびゃくえんや", "300円");
  Check("にじゅっぷんもかかる", "20分");
  Check("さんびゃくにん、にひゃくにん", "300人|200人");
  Check("にじゅうにんさんじゅうにん", "20人|30人");
  Check("にじゅうにんごぜんくじ", "20人|午前9時");
  Check("じゅうこく", "");
  Check("さんびゃくえんけい", "");
  Check("ひゃくえんだま", "");
  Check("じゅうにんしゅ", "");

  // Longer counters before shorter ones.
  Check("にじゅうじかん", "20時間");
  Check("さんじゅうしゅうかん", "30週間");
  Check("にじゅうにちかん", "20日間");
  Check("じゅうごかいめ", "15回目");
  Check("じゅうごばんめ", "15番目");
  Check("にじゅうにんまえ", "20人前");
  Check("じゅうにかげつ", "12か月");

  // Left alone.
  Check("せんだい", "");
  Check("しゅぜんじ", "");
  Check("たなかさんにほん", "");
  Check("ににいちど", "");
  Check("さんに", "");
  Check("にいち", "");
  Check("にほん", "");
  Check("いちにち", "");
  Check("くじびき", "");
  Check("じゅうたく", "");
  Check("ごがつ", "");
  Check("きょうは", "");
  Check("にんじん", "");
  Check("さんぽ", "");
  Check("いっしょ", "");
  Check("ひとり", "");
  Check("ふたり", "");
  Check("ぐんじん", "");
  Check("ごご", "");
  Check("", "");

  std::cout << "SUMMARY " << g_failed << " (" << g_total << " checks)\n";
  return g_failed == 0 ? 0 : 1;
}
