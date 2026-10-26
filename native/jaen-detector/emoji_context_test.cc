// emoji_context.h の単体試験（Mozc を組み立てずに g++ で動く。tools/run_tests.sh の組 b）。
#include <iostream>
#include <string>
#include <string_view>
#include <vector>

#include "emoji_context.h"

namespace {

constexpr jaen::EmojiKeyword kTable[] = {
    {"ありがとう", "🙏", 2}, {"ありがとう", "🫂", 2}, {"寝", "💤", 3}, {"寝", "😴", 3},
    {"猫", "🐱", 3},         {"猫", "🐾", 3},         {"足跡", "🐾", 1},
};

int g_total = 0;
int g_failed = 0;

void Check(std::string_view context, const std::vector<std::string_view>& expected) {
  ++g_total;
  const std::vector<std::string_view> got = jaen::ContextEmoji(context, kTable);
  if (got != expected) {
    ++g_failed;
    std::cout << "FAIL context=" << context << " got";
    for (std::string_view e : got) std::cout << " " << e;
    std::cout << "\n";
  }
}

}  // namespace

int main() {
  Check("", {});
  Check("今日は晴れ", {});
  Check("ありがとう", {"🙏", "🫂"});
  // 後ろで見つかった言葉が先（寝 が 猫 より後ろ）。同じ言葉の中は表の順
  Check("猫が寝てる", {"💤", "😴", "🐱", "🐾"});
  // 同じ位置で終わるなら長い言葉が先
  Check("猫の足跡", {"🐾", "🐱"});
  // 最後の kContextChars 字だけを見る（前の「ありがとう」は遠いので外れる）
  Check("ありがとう" + std::string(jaen::kContextChars, 'a'), {});
  Check(std::string(jaen::kContextChars - 2, 'a') + "猫", {"🐱", "🐾"});
  // 文字の途中で切らない
  if (jaen::LastChars("あいう", 2) != "いう") {
    ++g_failed;
    std::cout << "FAIL LastChars\n";
  }
  ++g_total;
  std::cout << "emoji_context: " << (g_total - g_failed) << "/" << g_total << "\n";
  return g_failed == 0 ? 0 : 1;
}
