// miss_report.h の単体試験（g++ -std=c++20 -I native/jaen-detector miss_report_test.cc）。
#include "miss_report.h"

#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>

namespace {

int g_total = 0;
int g_failed = 0;

void Check(bool ok, const std::string& what) {
  ++g_total;
  if (!ok) {
    ++g_failed;
    std::cout << "FAIL " << what << "\n";
  }
}

void CheckEq(const std::string& got, const std::string& want, const std::string& what) {
  Check(got == want, what + ": got [" + got + "] want [" + want + "]");
}

std::string ReadAll(const std::filesystem::path& p) {
  std::ifstream in(p, std::ios::binary);
  std::stringstream s;
  s << in.rdbuf();
  return s.str();
}

}  // namespace

int main() {
  using namespace jaen;
  // キー: Ctrl+Shift+F12 だけ。左右の印だけでもよい。Alt つき・離したとき・F11 は違う
  Check(IsMissReportKey(30, 1 | 4), "ctrl+shift+f12");
  Check(IsMissReportKey(30, 32 | 1024 | 8), "left ctrl + right shift + key down");
  Check(IsMissReportKey(30, 1 | 4 | 2048), "with caps lock");
  Check(!IsMissReportKey(30, 1), "ctrl+f12 (ATOK の設定画面)");
  Check(!IsMissReportKey(30, 4), "shift+f12");
  Check(!IsMissReportKey(30, 1 | 4 | 2), "ctrl+shift+alt+f12");
  Check(!IsMissReportKey(30, 1 | 4 | 16), "key up");
  Check(!IsMissReportKey(29, 1 | 4), "ctrl+shift+f11");
  Check(!IsMissReportKey(0, 1 | 4), "no special key");

  // 欄: タブ・改行は空白、長いものは文字の途中で切らない
  CheckEq(MissField("a\tb\nc\rd"), "a b c d", "field controls");
  CheckEq(MissField("あいう", 4), "あ", "field cut inside char");
  CheckEq(MissField("あいう", 6), "あい", "field cut at boundary");
  CheckEq(MissField("abc", 10), "abc", "field short");
  CheckEq(MissTail("今日はいい天気", 3), "い天気", "tail");
  CheckEq(MissTail("ab", 5), "ab", "tail short");
  CheckEq(MissTail("", 5), "", "tail empty");
  CheckEq(MissTail("あいう", 0), "", "tail zero");

  MissEntry e{"commit", "kisyanokisya", "きしゃのきしゃ", "記者の記者", "", "昨日"};
  CheckEq(FormatMissLine("2026-10-29T10:00:00", e),
          "2026-10-29T10:00:00\tcommit\tkisyanokisya\tきしゃのきしゃ\t記者の記者\t\t昨日\n", "line");
  Check(MissStamp().size() == 19, "stamp length");

  // 直前の確定: 時間内に1回だけ。入力欄が変われば捨てる
  LastCommit last(1000);
  Check(!last.Ready(0), "empty not ready");
  last.Set(e, 100);
  Check(last.Ready(100) && last.Ready(1100), "ready within lifetime");
  Check(!last.Ready(1101), "expired");
  Check(!last.Ready(50), "clock went back");
  last.MarkReported();
  Check(!last.Ready(200), "reported once");
  last.Set(e, 300);
  Check(last.Ready(300), "new commit ready again");
  last.NoteRevision(5);
  Check(last.Ready(300), "first revision only remembered");
  last.NoteRevision(5);
  Check(last.Ready(300), "same revision keeps");
  last.NoteRevision(6);
  Check(!last.Ready(300), "other field clears");

  // ファイル: 見出しを1回だけ書き、上限を超えたら新しい半分と見出しを残す
  const std::filesystem::path dir = std::filesystem::temp_directory_path() / "miss_report_test";
  std::filesystem::remove_all(dir);
  std::filesystem::create_directories(dir);
  const std::filesystem::path file = dir / kMissReportFileName;
  Check(AppendMissLine(file, "1\n"), "append 1");
  Check(AppendMissLine(file, "2\n"), "append 2");
  CheckEq(ReadAll(file), std::string(kMissReportHeader) + "1\n2\n", "header once");
  for (int i = 3; i <= 10; ++i) AppendMissLine(file, std::to_string(i) + "\n", 40);
  const std::string after = ReadAll(file);
  Check(after.rfind(std::string(kMissReportHeader), 0) == 0, "header kept after trim");
  Check(after.find("\n1\n") == std::string::npos, "old lines dropped");
  Check(after.size() >= 3 && after.substr(after.size() - 3) == "10\n", "newest kept");
  size_t headers = 0;
  for (size_t p = after.find("# "); p != std::string::npos; p = after.find("# ", p + 1)) ++headers;
  Check(headers == 1, "one header");
  std::filesystem::remove_all(dir);

  if (g_failed != 0) {
    std::cout << g_failed << "/" << g_total << " failed\n";
    return 1;
  }
  std::cout << "miss_report: " << g_total << "/" << g_total << " ok\n";
  return 0;
}
