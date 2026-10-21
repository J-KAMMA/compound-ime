"""直した Composer::TransformCharactersForNumbers を、Mozc を組み立てずに手元で試す。

  python tools/decimal_transform_test.py <mozc/src>

<mozc/src> は tools/apply_decimal_point.py を当てた後の木。composer/composer.cc から、
文字の種類の表（enum Script）から TransformCharactersForNumbers の終わりまでを
そのまま取り出し、Mozc の部品（Util、文字の幅の管理）の代わりの小さな部品を付けて
g++ で組み立てて動かす。確かめるのは次の2つ:
  - この script の中の表（打った文字列 → 期待）
  - composer_test.cc の TransformCharactersForNumbers の試験と、DecimalPointFollowsDigits の
    表（Mozc 自身の試験として GitHub で流れるものと、取り出した関数の動きが食い違わないか）
文字の幅の管理は、既定（「．」「，」は全角、「−」はそのまま）の代わりだけを置く。
さらに converter/converter.cc の MarkEnglishSpans の終わりに足した、英単語を含む文の
日本語の部分の鍵を直す塊（「Pythonの3。9を」）も、取り出して小さな Segment の代わりで動かす。
Mozc 本体（打鍵から変換まで）を通る試験ではない。
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

src = Path(sys.argv[1])
composer = (src / "composer/composer.cc").read_text(encoding="utf-8")
start = composer.index("namespace {\nenum Script {")
end_marker = "  *query = std::move(transformed_query);\n  return true;\n}\n"
end = composer.index(end_marker, start) + len(end_marker)
body = composer[start:end]
converter = (src / "converter/converter.cc").read_text(encoding="utf-8")
block_start = converter.index("  // The pieces were read again from the typed keys")
block_end = converter.index("  return typed;\n}\n", block_start)
block = converter[block_start:block_end]

SHIM = r'''
#include <cstdio>
#include <cstdlib>
#include <iostream>
#include <string>
#include <vector>
#include <utility>

#define DCHECK(x) do { if (!(x)) { std::fprintf(stderr, "DCHECK failed: %s\n", #x); std::abort(); } } while (0)
#define DCHECK_EQ(a, b) DCHECK((a) == (b))
#define MOZC_VLOG(n) if (false) std::cerr
struct NullLog { template <class T> NullLog& operator<<(const T&) { return *this; } };
#define LOG(x) NullLog()

namespace mozc {
struct Util {
  enum ScriptType { UNKNOWN_SCRIPT, KANJI, HIRAGANA, KATAKANA, ALPHABET, NUMBER };
  static std::u32string ToU32(const std::string& s) {
    std::u32string out;
    for (size_t i = 0; i < s.size();) {
      const unsigned char b = s[i];
      const int len = b < 0x80 ? 1 : b < 0xE0 ? 2 : b < 0xF0 ? 3 : 4;
      char32_t c = len == 1 ? b : b & (0xFF >> (len + 1));
      for (int k = 1; k < len; ++k) c = (c << 6) | (s[i + k] & 0x3F);
      out.push_back(c);
      i += len;
    }
    return out;
  }
  static size_t CharsLen(const std::string& s) { return ToU32(s).size(); }
  static ScriptType GetScriptType(char32_t c) {
    if ((c >= '0' && c <= '9') || (c >= 0xFF10 && c <= 0xFF19)) return NUMBER;
    if ((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= 0xFF21 && c <= 0xFF3A) ||
        (c >= 0xFF41 && c <= 0xFF5A)) return ALPHABET;
    if (c >= 0x3040 && c <= 0x309F) return HIRAGANA;
    if (c >= 0x30A0 && c <= 0x30FF) return KATAKANA;
    return UNKNOWN_SCRIPT;
  }
  static std::u32string Utf8ToUtf32(const std::string& s) { return ToU32(s); }
  static std::string Utf32ToUtf8(const std::u32string& s) {
    std::string out;
    for (const char32_t c : s) CodepointToUtf8Append(c, &out);
    return out;
  }
  static void CodepointToUtf8Append(char32_t c, std::string* out) {
    if (c < 0x80) out->push_back(c);
    else if (c < 0x800) { out->push_back(0xC0 | (c >> 6)); out->push_back(0x80 | (c & 0x3F)); }
    else if (c < 0x10000) { out->push_back(0xE0 | (c >> 12)); out->push_back(0x80 | ((c >> 6) & 0x3F)); out->push_back(0x80 | (c & 0x3F)); }
    else { out->push_back(0xF0 | (c >> 18)); out->push_back(0x80 | ((c >> 12) & 0x3F)); out->push_back(0x80 | ((c >> 6) & 0x3F)); out->push_back(0x80 | (c & 0x3F)); }
  }
};
struct Segment {
  enum SegmentType { FREE, FIXED_VALUE };
  const std::string& key() const { return key_; }
  void set_key(const std::string& key) { key_ = key; }
  SegmentType segment_type() const { return type_; }
  std::string key_;
  SegmentType type_ = FREE;
};
struct Segments {
  std::vector<Segment>& conversion_segments() { return list_; }
  std::vector<Segment> list_;
};
class ConstChar32Iterator {
 public:
  explicit ConstChar32Iterator(const std::string& s) : chars_(Util::ToU32(s)) {}
  bool Done() const { return pos_ >= chars_.size(); }
  char32_t Get() const { return chars_[pos_]; }
  void Next() { ++pos_; }
 private:
  std::u32string chars_;
  size_t pos_ = 0;
};
namespace config {
struct CharacterFormManager {
  static CharacterFormManager* GetCharacterFormManager() { static CharacterFormManager m; return &m; }
  // The default rule: full width for 「．」「，」, the other marks as they are.
  void ConvertPreeditString(const std::string& in, std::string* out) const { *out = in; }
};
}  // namespace config
namespace composer {
using config::CharacterFormManager;
class Composer { public: static bool TransformCharactersForNumbers(std::string* query); };
'''

MAIN_HEAD = r'''
}  // namespace composer

// converter.cc の MarkEnglishSpans の終わりの塊（Mozc の Segments の代わりで）
static void FixPieces(Segments* segments) {
'''

MAIN_TAIL = r'''
}
}  // namespace mozc

int main() {
  std::string line;
  while (std::getline(std::cin, line)) {
    if (line.rfind("S\t", 0) == 0) {  // S<TAB>鍵|#英語の鍵|鍵 : # は FIXED_VALUE の部分
      mozc::Segments segments;
      std::string rest = line.substr(2);
      size_t at = 0;
      while (at <= rest.size()) {
        size_t bar = rest.find('|', at);
        if (bar == std::string::npos) bar = rest.size();
        std::string part = rest.substr(at, bar - at);
        mozc::Segment segment;
        if (!part.empty() && part[0] == '#') { segment.type_ = mozc::Segment::FIXED_VALUE; part = part.substr(1); }
        segment.key_ = part;
        segments.list_.push_back(segment);
        at = bar + 1;
      }
      mozc::FixPieces(&segments);
      std::string out;
      for (const auto& segment : segments.list_) {
        if (!out.empty()) out += "|";
        out += (segment.type_ == mozc::Segment::FIXED_VALUE ? "#" : "") + segment.key_;
      }
      std::cout << "S\t" << out << "\n";
      continue;
    }
    std::string query = line;
    const bool changed = mozc::composer::Composer::TransformCharactersForNumbers(&query);
    std::cout << (changed ? "1" : "0") << "\t" << query << "\n";
  }
}
'''


PIECES = [  # (鍵の並び: # は英語の部分, 期待)
    ("#Python|の3。9を", "#Python|の3.9を"), ("#Windows|の10。5", "#Windows|の10.5"),
    ("#meeting|を4。1に", "#meeting|を4.1に"), ("#v|1。2", "#v|1.2"), ("#Python|3。|#x", "#Python|3.|#x"),
    ("#Python|の3。", "#Python|の3。"), ("#Python|は4。では", "#Python|は4。では"),
    ("今日は|#Google|で1、000円", "今日は|#Google|で1,000円"), ("#Google|は、2026。10。21", "#Google|は、2026.10.21"),
    ("#a。1|b", "#a。1|b"), ("#Python|です。", "#Python|です。"), ("#Python|と3ー", "#Python|と3ー"),
]

CASES = [  # (打った文字列, 期待。同じなら変わらない)
    ("4。1", "4.1"), ("3。14", "3.14"), ("１。２。３", "１．２．３"), ("192。168。0。1", "192.168.0.1"),
    ("v1。2", "v1.2"), ("1。5ばい", "1.5ばい"), ("0。5%", "0.5%"), ("3。x", "3.x"), ("3。14e10", "3.14e10"),
    ("1、000", "1,000"), ("１、０００", "１，０００"), ("1、000、000円", "1,000,000円"), ("No。5", "No.5"),
    ("Windowsの10。5", "Windowsの10.5"), ("Pythonの3。9を", "Pythonの3.9を"),
    ("合計は4。", "合計は4。"), ("4。では", "4。では"), ("4。", "4。"), ("4。」", "4。」"), ("（4。）", "（4。）"),
    ("りんご3、みかん2", "りんご3、みかん2"), ("3、ひとつ", "3、ひとつ"), ("1。2。3。", "1.2.3。"),
    ("ほんとう、4。1です。", "ほんとう、4.1です。"), ("今日は晴れ。", "今日は晴れ。"), ("はい、そうです。", "はい、そうです。"),
    ("Ａ。Ｂ", "Ａ．Ｂ"), ("ABC。", "ABC．"), ("4。1。", "4.1。"), ("2026。10。21", "2026.10.21"),
    ("。1", "。1"), ("1。。2", "1。。2"), ("１２３。", "１２３。"), ("０。５", "０．５"),
]


def parse_gtest_cases(test_source):
    cases = []
    m = re.search(r"TEST_F\(ComposerTest, TransformCharactersForNumbers\) \{(.*?)\nTEST_F", test_source, re.S)
    if m:
        for q, kind, _, e in re.findall(
                r'query = "([^"]*)";\s*EXPECT_(TRUE|FALSE)\(Composer::TransformCharactersForNumbers\(&query\)\);'
                r'(\s*EXPECT_EQ\(query, "([^"]*)"\);)?', m.group(1)):
            cases.append((q, e if kind == "TRUE" and e else q, kind == "TRUE"))
    m = re.search(r"TEST_F\(ComposerTest, DecimalPointFollowsDigits\) \{(.*?)\nTEST_F", test_source, re.S)
    if m:
        for q, e in re.findall(r'\{"([^"]*)", "([^"]*)"\}', m.group(1)):
            cases.append((q, e, q != e))
    return cases


with tempfile.TemporaryDirectory() as tmp:
    cc = Path(tmp) / "t.cc"
    cc.write_text(SHIM + body + MAIN_HEAD + block + MAIN_TAIL, encoding="utf-8")
    exe = Path(tmp) / "t"
    build = subprocess.run(["g++", "-std=c++20", "-Wall", "-Wextra", "-Werror", "-O1", str(cc), "-o", str(exe)],
                           capture_output=True, text=True)
    if build.returncode:
        print(build.stderr[:4000])
        sys.exit("組み立てに失敗")
    gtest = parse_gtest_cases((src / "composer/composer_test.cc").read_text(encoding="utf-8"))
    cases = [(q, e, q != e) for q, e in CASES] + gtest
    inputs = [q for q, _, _ in cases] + ["S\t" + q for q, _ in PIECES]
    run = subprocess.run([str(exe)], input="\n".join(inputs) + "\n", capture_output=True,
                         text=True, encoding="utf-8")
    if run.returncode:
        sys.exit("動かして失敗: " + run.stderr[:2000])
    lines = run.stdout.split("\n")
    results = [line.split("\t", 1) for line in lines[:len(cases)]]
    bad = 0
    for (q, e), line in zip(PIECES, lines[len(cases):]):
        if line != "S\t" + e:
            bad += 1
            print(f"違い（英語まじりの鍵）: {q} → {line[2:]}、期待 {e}")
    for (q, e, changed), (flag, got) in zip(cases, results):
        if got != e or (flag == "1") != changed:
            bad += 1
            print(f"違い: {q} → {got}（flag {flag}）、期待 {e}（変化 {changed}）")
    total = len(cases) + len(PIECES)
    print(f"数字の間の点・点の変換: {total - bad}/{total} 一致（うち composer_test.cc から {len(gtest)}、英語まじりの鍵 {len(PIECES)}）")
    sys.exit(1 if bad else 0)
