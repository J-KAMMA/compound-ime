// 単体試験（recent_commit.h だけで動く）:
//   g++ -std=c++20 -O2 recent_commit_test.cc -o recent_commit_test && ./recent_commit_test
// 最後の行が「SUMMARY<TAB>0」なら全部通っている。
#include "recent_commit.h"

#include <iostream>
#include <string>

#include "jaen_detector.h"

namespace {
int failures = 0;
void Expect(bool ok, const char* name) {
  if (!ok) {
    ++failures;
    std::cout << "FAIL\t" << name << '\n';
  }
}
using jaen::EchoedKey;
using jaen::RecentCommit;

EchoedKey Space() { return EchoedKey{jaen::kKeySpace, 0, 0, {}}; }
EchoedKey Backspace() { return EchoedKey{jaen::kKeyBackspace, 0, 0, {}}; }
EchoedKey Char(char c, uint32_t modifiers = 0) { return EchoedKey{0, static_cast<uint32_t>(c), modifiers, {}}; }
EchoedKey Special(int key) { return EchoedKey{key, 0, 0, {}}; }
bool English(const RecentCommit& r, RecentCommit::Millis now) { return jaen::EndsWithEnglishWord(r.Text(now)); }
}  // namespace

int main() {
  // 確定のあとの空白（変換を通らない）をつなぐ。
  {
    RecentCommit r;
    r.Append("make", 100);
    r.NoteEchoedKey(Space(), 200);
    Expect(r.Text(300) == "make ", "確定のあとに空白をつなぐ");
    Expect(English(r, 300), "空白のあとも英語の語で終わる");
  }
  // 変換を通らずに打った英字（直接入力）もつなぐ。Shift つきの大文字も。
  {
    RecentCommit r;
    r.Append("今日は ", 0);
    r.NoteEchoedKey(Char('S', 4), 10);
    r.NoteEchoedKey(Char('l'), 20);
    r.NoteEchoedKey(Char('a'), 30);
    Expect(r.Text(40) == "今日は Sla" && English(r, 40), "直接入力の英字をつなぐ");
    r.NoteEchoedKey(Char('1'), 50);
    Expect(!English(r, 60), "数で終わったら英語でない");
  }
  // 日本語の確定のあとは英語でない。
  {
    RecentCommit r;
    r.Append("今日は", 0);
    r.NoteEchoedKey(Space(), 1);
    Expect(!English(r, 2), "日本語のあとの空白は英語でない");
  }
  // Backspace: 覚えた分の中なら1字消す。覚えた分より前に戻ったら捨てる（空になる）。
  {
    RecentCommit r;
    r.Append("make", 0);
    r.NoteEchoedKey(Space(), 1);
    r.NoteEchoedKey(Backspace(), 2);
    Expect(r.Text(3) == "make", "Backspace で空白を消す");
    r.NoteEchoedKey(Backspace(), 4);
    Expect(r.Text(5) == "mak", "Backspace で1字消す");
    r.NoteEchoedKey(Backspace(), 6);
    r.NoteEchoedKey(Backspace(), 7);
    r.NoteEchoedKey(Backspace(), 8);
    Expect(r.empty() && r.Text(9).empty(), "覚えた分より前に戻ったら空");
    r.NoteEchoedKey(Backspace(), 10);
    r.NoteEchoedKey(Space(), 11);
    Expect(r.Text(12) == " " && !English(r, 12), "空のあとに空白だけ足しても英語にならない");
  }
  {
    RecentCommit r;
    r.Append("日本語", 0);
    r.NoteEchoedKey(Backspace(), 1);
    Expect(r.Text(2) == "日本", "Backspace は文字（UTF-8 の1字）単位で消す");
  }
  // カーソルを動かすキーは捨てる。字の方式を替えるだけのキーは何もしない。
  for (const int key : {6, 7, 8, 9, 16, 17, 5, 18, 11, 33, 31, 32, 10}) {  // 矢印・Home・End・Enter・Tab・Delete など
    RecentCommit r;
    r.Append("make ", 0);
    r.NoteEchoedKey(Special(key), 1);
    Expect(r.empty(), ("カーソル・改行のキーで捨てる " + std::to_string(key)).c_str());
  }
  for (const int key : {jaen::kKeyOn, jaen::kKeyOff, jaen::kKeyHenkan, jaen::kKeyMuhenkan, jaen::kKeyKana, jaen::kKeyEisu,
                        jaen::kKeyHankaku, jaen::kKeyKanji, jaen::kKeyKatakana, jaen::kKeyCapsLock}) {
    RecentCommit r;
    r.Append("make ", 0);
    r.NoteEchoedKey(Special(key), 1);
    Expect(r.Text(2) == "make ", ("方式を替えるだけのキーは何もしない " + std::to_string(key)).c_str());
  }
  // Ctrl・Alt つき（貼り付けなど）は捨てる。修飾キーだけ・離したときの知らせは何もしない。
  {
    RecentCommit r;
    r.Append("make ", 0);
    r.NoteEchoedKey(Char('v', 1), 1);
    Expect(r.empty(), "Ctrl+V で捨てる");
    r.Append("make ", 2);
    r.NoteEchoedKey(EchoedKey{0, 0, 4, {}}, 3);
    r.NoteEchoedKey(EchoedKey{0, static_cast<uint32_t>('a'), 16, {}}, 4);
    Expect(r.Text(5) == "make ", "修飾キーだけ・キーを離した知らせは何もしない");
  }
  // 入力欄が変わる（revision が変わる）と捨てる。最初に見た値は捨てない。
  {
    RecentCommit r;
    r.Append("make ", 0);
    r.NoteRevision(7);
    Expect(r.Text(1) == "make ", "最初に見た revision では捨てない");
    r.NoteRevision(7);
    Expect(r.Text(2) == "make ", "同じ revision では捨てない");
    r.NoteRevision(8);
    Expect(r.empty(), "revision が変わったら捨てる");
    r.Append("a", 3);
    r.NoteRevision(8);
    Expect(r.Text(4) == "a", "捨てたあとに足した字は残る");
  }
  // 時間: 最後に足してから 60 秒たつと使えない（足したあとに数える）。
  {
    RecentCommit r;
    r.Append("make", 1000);
    Expect(r.Text(1000 + 60000) == "make", "ちょうど 60 秒は残る");
    Expect(r.Text(1000 + 60001).empty(), "60 秒を過ぎたら空");
    r.NoteEchoedKey(Space(), 1000 + 30000);
    Expect(r.Text(1000 + 89000) == "make ", "空白を足すと、そこから 60 秒数え直す");
    r.NoteEchoedKey(Char('x'), 1000 + 200000);
    Expect(r.Text(1000 + 200001) == "x", "期限が切れたあとに足すと、古い字は捨てて新しい字だけ");
  }
  {
    RecentCommit r(500);
    r.Append("make", 0);
    Expect(r.Text(500) == "make" && r.Text(501).empty(), "覚える時間は替えられる（試験用）");
  }
  // 長さ: 最後の 64 字だけ（文字単位）。
  {
    RecentCommit r;
    std::string many;
    for (int i = 0; i < 100; ++i) many += (i % 2 ? "あ" : "b");
    r.Append(many, 0);
    const std::string text = r.Text(1);
    size_t chars = 0;
    for (const char c : text) chars += (static_cast<unsigned char>(c) & 0xC0) != 0x80;
    Expect(chars == 64, "最後の 64 字だけ覚える");
    Expect(text == many.substr(many.size() - text.size()), "覚えるのは後ろのほう");
    Expect(text.size() == 32 * 3 + 32, "切れ目が UTF-8 の字の途中にならない");
    for (int i = 0; i < 64; ++i) r.NoteEchoedKey(Backspace(), 2 + i);
    Expect(r.empty(), "64 字より前へ戻ったら空");
  }
  // 方式が分からない字（制御文字・空）の key_string は、何が入ったか分からないので捨てる。
  {
    RecentCommit r;
    r.Append("make ", 0);
    r.NoteEchoedKey(EchoedKey{jaen::kKeyTextInput, 0, 0, "é"}, 1);
    Expect(r.Text(2) == "make é" && !English(r, 2), "文字の入力は key_string をつなぐ");
    r.NoteEchoedKey(EchoedKey{jaen::kKeyTextInput, 0, 0, {}}, 3);
    Expect(r.empty(), "中身が分からない入力は捨てる");
  }
  std::cout << "SUMMARY\t" << failures << '\n';
  return failures ? 1 : 0;
}
