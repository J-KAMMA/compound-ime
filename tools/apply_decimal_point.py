"""数字の間の「.」「,」を小数点・桁区切りにする（4.1、3.14、192.168.0.1、1,000）。

  python tools/apply_decimal_point.py <mozc/src>

tools/apply_jaen_integration.py の直後に、1回だけ動かす（その script が作る
Converter::MarkEnglishSpans に手を入れるため）。

原因（調べた結果。docs/decimal-point.md）:
  1. ローマ字表（data/preedit/romanji-hiragana.tsv）は「.」を「。」、「,」を「、」にする。
  2. Composer::TransformCharactersForNumbers は、直前が英数字の「。」「、」を、次の文字を見ずに
     「．」「，」にする。幅は character_form_rules の ".,"（既定は全角）で決まり、数字の幅
     （"0"）とは別。数字を半角にしても点は全角のまま（4．1）。
  3. 英単語を含む文では Converter::MarkEnglishSpans が日本語の部分をローマ字の打鍵から読み直し、
     Mozc の数字の変換（TransformCharactersForNumbers）を通さないので、「。」のまま変換にまわる
     （Windowsの10。5、meetingを4。1に送る）。

直し方:
  - TransformCharactersForNumbers: 前が数字で次も数字なら小数点（半角の数字は「.」、全角は「．」。
    数字の幅に合わせる）。前が数字で次が英字（3.x）も同じ。前が数字で次が数字・英字以外
    （文末、日本語、閉じかっこ）なら「。」「、」のまま（合計は4。、4。では）。前が英字のときは
    次が数字なら小数点、ほかは従来どおり。
  - MarkEnglishSpans: 作った日本語の部分の鍵を、全体をつないだ文字列で同じ関数に通し直す。
  - Mozc 自身の試験のうち、この決めと食い違う期待値を直す。
決め方の本体は native/jaen-detector/composer_decimal.inc（tools/decimal_transform_test.py が、
直した composer.cc から取り出して手元で動かす）。
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
src = Path(sys.argv[1])


def edit(path, old, new, count=1):
    # 改行の記号（LF か CRLF）は、ファイルによって違う。LF で探し、見つからなければ CRLF で探す
    p = src / path
    text = p.read_bytes().decode("utf-8")
    for newline in ("\n", "\r\n"):
        o, n = old.replace("\n", newline), new.replace("\n", newline)
        if text.count(o) == count:
            p.write_bytes(text.replace(o, n).encode("utf-8"))
            return
    raise SystemExit(f"{path}: expected {count} match(es) for {old[:70]!r}, found {text.count(old)}")


decimal_inc = (REPO / "native/jaen-detector/composer_decimal.inc").read_text(encoding="utf-8")

C = "composer/composer.cc"
edit(C, """bool IsAlphabetOrNumber(const Script script) {
  return (script == ALPHABET) || (script == NUMBER);
}
}  // namespace
""", """bool IsAlphabetOrNumber(const Script script) {
  return (script == ALPHABET) || (script == NUMBER);
}

""" + decimal_inc + """}  // namespace
""")

edit(C, """// 。 (U+3002) is transformed to ． (U+FF0E) if:
//   * the previous character and the next character are both alphanumerics.
""", """// 。 (U+3002) is transformed to ． (U+FF0E) if:
//   * the previous character and the next character are both alphanumerics.
//
// Compound IME changes the rules of 、 and 。 (see DecideNumberPunctuation):
//   * between digits (or a digit and a letter after it) they become "," / "."
//     at the width of the digit ("4.1", "１．５", "3.x", "1,000"),
//   * after a digit and before anything else (the end, Japanese text, a
//     closing bracket) they stay "、" / "。" ("合計は4。", "4。では"),
//   * after a letter, they follow the old rule unless a digit comes next.
""")

edit(C, """  char_scripts.reserve(chars_len);
""", """  char_scripts.reserve(chars_len);
  std::vector<char32_t> chars;  // the characters themselves, as char_scripts
  chars.reserve(chars_len);
""")
edit(C, """    const char32_t one_char = iter.Get();
    switch (one_char) {
      case 0x30FC:  // "ー"
""", """    const char32_t one_char = iter.Get();
    chars.push_back(one_char);
    switch (one_char) {
      case 0x30FC:  // "ー"
""")
edit(C, """        // JA_COMMA should be transformed to COMMA.
        if (lhs_check) {
          CharacterFormManager::GetCharacterFormManager()->ConvertPreeditString(
              "，", &append_char);
          DCHECK(!append_char.empty());
        }
""", """        // JA_COMMA should be transformed to COMMA.
        if (lhs_check) {
          switch (DecideNumberPunctuation(
              chars[i - 1], i + 1 < chars.size() ? chars[i + 1] : 0)) {
            case NumberPunctuation::kKeep:
              break;
            case NumberPunctuation::kHalfWidth:
              append_char = ",";
              break;
            case NumberPunctuation::kFullWidth:
              append_char = "，";
              break;
            case NumberPunctuation::kLegacy:
              CharacterFormManager::GetCharacterFormManager()
                  ->ConvertPreeditString("，", &append_char);
              DCHECK(!append_char.empty());
              break;
          }
        }
""")
edit(C, """        // JA_PERIOD should be transformed to PERIOD.
        if (lhs_check) {
          CharacterFormManager::GetCharacterFormManager()->ConvertPreeditString(
              "．", &append_char);
          DCHECK(!append_char.empty());
        }
""", """        // JA_PERIOD should be transformed to PERIOD.
        if (lhs_check) {
          switch (DecideNumberPunctuation(
              chars[i - 1], i + 1 < chars.size() ? chars[i + 1] : 0)) {
            case NumberPunctuation::kKeep:
              break;
            case NumberPunctuation::kHalfWidth:
              append_char = ".";
              break;
            case NumberPunctuation::kFullWidth:
              append_char = "．";
              break;
            case NumberPunctuation::kLegacy:
              CharacterFormManager::GetCharacterFormManager()
                  ->ConvertPreeditString("．", &append_char);
              DCHECK(!append_char.empty());
              break;
          }
        }
""")

# Mozc 自身の試験: 期待値を新しい決めに合わせる
T = "composer/composer_test.cc"
edit(T, """  query = "およそ、３。１４１５９。";
  EXPECT_TRUE(Composer::TransformCharactersForNumbers(&query));
  EXPECT_EQ(query, "およそ、３．１４１５９．");

  query = "１００、";
  EXPECT_TRUE(Composer::TransformCharactersForNumbers(&query));
  EXPECT_EQ(query, "１００，");

  query = "１００。";
  EXPECT_TRUE(Composer::TransformCharactersForNumbers(&query));
  EXPECT_EQ(query, "１００．");
}
""", """  // Compound IME: the last 。 ends the sentence, so it stays.
  query = "およそ、３。１４１５９。";
  EXPECT_TRUE(Composer::TransformCharactersForNumbers(&query));
  EXPECT_EQ(query, "およそ、３．１４１５９。");

  query = "１００、";
  EXPECT_FALSE(Composer::TransformCharactersForNumbers(&query));
  EXPECT_EQ(query, "１００、");

  query = "１００。";
  EXPECT_FALSE(Composer::TransformCharactersForNumbers(&query));
  EXPECT_EQ(query, "１００。");
}

// Compound IME: 4。1 is a decimal point at the width of the digits; 。 after a
// digit and before anything but a digit or a letter ends the clause.
TEST_F(ComposerTest, DecimalPointFollowsDigits) {
  const struct {
    const char* query;
    const char* expected;  // the same as query when nothing changes
  } kCases[] = {
      {"4。1", "4.1"},
      {"3。14", "3.14"},
      {"１。２。３", "１．２．３"},
      {"192。168。0。1", "192.168.0.1"},
      {"v1。2", "v1.2"},
      {"1。5ばい", "1.5ばい"},
      {"0。5%", "0.5%"},
      {"3。x", "3.x"},
      {"1、000", "1,000"},
      {"１、０００", "１，０００"},
      {"1、000、000", "1,000,000"},
      {"No。5", "No.5"},
      {"合計は4。", "合計は4。"},
      {"4。では", "4。では"},
      {"4。", "4。"},
      {"4。」", "4。」"},
      {"りんご3、みかん2", "りんご3、みかん2"},
      {"3、ひとつ", "3、ひとつ"},
      {"1。2。3。", "1.2.3。"},
      {"ほんとう、4。1です。", "ほんとう、4.1です。"},
  };
  for (const auto& test_case : kCases) {
    SCOPED_TRACE(test_case.query);
    std::string query = test_case.query;
    const bool changed = Composer::TransformCharactersForNumbers(&query);
    EXPECT_EQ(query, test_case.expected);
    EXPECT_EQ(changed, query != test_case.query);
  }
}
""")
edit(T, """    manager->AddPreeditRule("1", Config::FULL_WIDTH);
    manager->AddPreeditRule(".,", Config::HALF_WIDTH);
    composer_->InsertCharacter("3.14");
    EXPECT_EQ(composer_->GetStringForPreedit(), "３.１４");
""", """    manager->AddPreeditRule("1", Config::FULL_WIDTH);
    manager->AddPreeditRule(".,", Config::HALF_WIDTH);
    composer_->InsertCharacter("3.14");
    // Compound IME: the decimal point follows the digits, not ".,".
    EXPECT_EQ(composer_->GetStringForPreedit(), "３．１４");
""")
edit(T, """    manager->AddPreeditRule("1", Config::HALF_WIDTH);
    manager->AddPreeditRule(".,", Config::FULL_WIDTH);
    composer_->InsertCharacter("3.14");
    EXPECT_EQ(composer_->GetStringForPreedit(), "3．14");
""", """    manager->AddPreeditRule("1", Config::HALF_WIDTH);
    manager->AddPreeditRule(".,", Config::FULL_WIDTH);
    composer_->InsertCharacter("3.14");
    // Compound IME: the decimal point follows the digits, not ".,".
    EXPECT_EQ(composer_->GetStringForPreedit(), "3.14");
""")
edit("session/session_test.cc", """EXPECT_SINGLE_SEGMENT_AND_KEY("１２３．", "１２３．", command);""",
     """EXPECT_SINGLE_SEGMENT_AND_KEY("１２３。", "１２３。", command);""", count=2)

# 英単語を含む文: 日本語の部分の鍵も、数字の間の「。」「、」を直す。全体をつないだ文字列で
# 通すのは、英語の部分や前後の数字が前後関係になるため（v|1。2）。直すのは「。」「、」だけで、
# 英語の部分（FIXED_VALUE）の鍵は変えない（後で鍵で探すため）。
edit("converter/converter.cc", """      s->set_key(kana.substr(at[pos]));
      s->set_segment_type(Segment::FREE);
    }
  }
  return typed;
}
""", """      s->set_key(kana.substr(at[pos]));
      s->set_segment_type(Segment::FREE);
    }
  }
  // The pieces were read again from the typed keys, which skips Mozc's
  // number rules for 。 and 、 ("Python 3。9"). Apply them to the whole key,
  // so that neighbouring pieces count, and take over only those two marks.
  {
    std::string whole;
    for (const Segment& segment : segments->conversion_segments()) {
      whole.append(segment.key());
    }
    std::string moved = whole;
    if (composer::Composer::TransformCharactersForNumbers(&moved)) {
      const std::u32string before = Util::Utf8ToUtf32(whole);
      const std::u32string after = Util::Utf8ToUtf32(moved);
      if (before.size() == after.size()) {
        size_t offset = 0;
        for (Segment& segment : segments->conversion_segments()) {
          std::u32string key = Util::Utf8ToUtf32(segment.key());
          bool changed = false;
          if (segment.segment_type() == Segment::FREE) {
            for (size_t i = 0; i < key.size(); ++i) {
              const char32_t was = before[offset + i];
              if ((was == 0x3001 || was == 0x3002) && after[offset + i] != was) {
                key[i] = after[offset + i];
                changed = true;
              }
            }
          }
          if (changed) segment.set_key(Util::Utf32ToUtf8(key));
          offset += key.size();
        }
      }
    }
  }
  return typed;
}
""")
