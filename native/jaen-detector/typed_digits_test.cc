#include <cstddef>
#include <iostream>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "typed_digits.inc"

namespace {

int g_total = 0;
int g_failed = 0;

void CheckKeep(const std::string& key, const std::string& candidate, bool expected) {
  ++g_total;
  const bool got = typed_digits::KeepsTypedDigits(key, candidate);
  if (got != expected) {
    ++g_failed;
    std::cout << "FAIL keep key=" << key << " candidate=" << candidate
              << " expected " << expected << " got " << got << "\n";
  }
}

void CheckReplace(const std::string& key, const std::string& candidate,
                  const std::string& expected) {
  ++g_total;
  std::string got;
  const bool changed = typed_digits::ReplaceWithTypedDigits(key, candidate, &got);
  if (!changed || got != expected) {
    ++g_failed;
    std::cout << "FAIL replace key=" << key << " candidate=" << candidate
              << " expected [" << expected << "] got [" << got << "] changed=" << changed << "\n";
  }
}

void CheckNoReplace(const std::string& key, const std::string& candidate) {
  ++g_total;
  std::string got;
  if (typed_digits::ReplaceWithTypedDigits(key, candidate, &got)) {
    ++g_failed;
    std::cout << "FAIL no-replace key=" << key << " candidate=" << candidate
              << " got [" << got << "]\n";
  }
}

}  // namespace

int main() {
  // Typed digits already there.
  CheckKeep("980", "980円", true);
  CheckKeep("4.1", "4.1点", true);
  CheckKeep("4.1", "４．１点", false);
  CheckKeep("４．１", "４．１点", true);
  CheckKeep("1,000", "1,000円", true);
  CheckKeep("10.0.0.1", "10.0.0.1に", true);
  // A kanji spelling of the typed number is replaced.
  CheckKeep("980", "九百八十円", false);
  CheckKeep("10", "十度", false);
  CheckKeep("4.1", "4.一", false);
  CheckKeep("100", "百", false);
  CheckKeep("1", "一", false);
  CheckKeep("10.0.0.1", "10.0.0.一", false);
  CheckKeep("1,000", "千円", false);
  CheckReplace("980", "九百八十円", "980円");
  CheckReplace("10", "十度", "10度");
  CheckReplace("4.1", "4.一点", "4.1点");
  CheckReplace("4.1", "４．一点", "4.1点");
  CheckReplace("4.1", "４．１点", "4.1点");
  CheckReplace("４．１", "4.1点", "４．１点");
  CheckReplace("10.0.0.1", "10.0.0.一", "10.0.0.1");
  CheckReplace("100", "百", "100");
  CheckReplace("1", "一", "1");
  CheckReplace("1,000", "千円", "1,000円");
  CheckReplace("12345", "一万二千三百四十五円", "12345円");
  CheckReplace("2026", "二〇二六年", "2026年");
  CheckReplace("3.14", "三点一四", "3.14");
  // Kana words and no-digit keys are never touched.
  CheckKeep("ひとつ", "一つ", true);
  CheckKeep("いちばん", "一番", true);
  CheckKeep("じゅうぶん", "十分", true);
  CheckNoReplace("ひとつ", "一つ");
  CheckNoReplace("いちばん", "一番");
  CheckNoReplace("じゅうぶん", "十分");
  // Different counts are left alone rather than guessed.
  CheckNoReplace("980", "九百八十円と二円");
  CheckReplace("10.5", "十点五度", "10.5度");
  if (g_failed != 0) {
    std::cout << g_failed << "/" << g_total << " failed\n";
    return 1;
  }
  std::cout << "typed_digits: " << g_total << "/" << g_total << " ok\n";
  return 0;
}
