"""全部の絵文字の「〇〇えもじ」の試験の入力を作る（tools/run_tests.sh の組 b）。

  python3 tools/make_emoji_all_tests.py <mozc/src/data/emoji/emoji_data.tsv> tests/conversion/emoji-all.tsv

試験の計算機には Mozc のソースがないので、作った表を tests/conversion に置く（Mozc の版を上げたら作り直す）。

絵文字ごとに、読み（3列目）のうちいちばん長いひらがなの語を選び、その語と「えもじ」を続けて打つローマ字を作る。
列: ローマ字<TAB>絵文字<TAB>読み
"""
import sys
from pathlib import Path

# かな → ローマ字（tools/make_kana_number_tests.py と同じ表に、小さいかなを足す）
BASE = {
    "あ": "a", "い": "i", "う": "u", "え": "e", "お": "o",
    "か": "ka", "き": "ki", "く": "ku", "け": "ke", "こ": "ko",
    "さ": "sa", "し": "shi", "す": "su", "せ": "se", "そ": "so",
    "た": "ta", "ち": "chi", "つ": "tsu", "て": "te", "と": "to",
    "な": "na", "に": "ni", "ぬ": "nu", "ね": "ne", "の": "no",
    "は": "ha", "ひ": "hi", "ふ": "fu", "へ": "he", "ほ": "ho",
    "ま": "ma", "み": "mi", "む": "mu", "め": "me", "も": "mo",
    "や": "ya", "ゆ": "yu", "よ": "yo",
    "ら": "ra", "り": "ri", "る": "ru", "れ": "re", "ろ": "ro",
    "わ": "wa", "を": "wo", "ん": "nn",
    "が": "ga", "ぎ": "gi", "ぐ": "gu", "げ": "ge", "ご": "go",
    "ざ": "za", "じ": "ji", "ず": "zu", "ぜ": "ze", "ぞ": "zo",
    "だ": "da", "ぢ": "di", "づ": "du", "で": "de", "ど": "do",
    "ば": "ba", "び": "bi", "ぶ": "bu", "べ": "be", "ぼ": "bo",
    "ぱ": "pa", "ぴ": "pi", "ぷ": "pu", "ぺ": "pe", "ぽ": "po",
    "ー": "-", "、": ",", "。": ".",
}
SMALL = {"ぁ": "xa", "ぃ": "xi", "ぅ": "xu", "ぇ": "xe", "ぉ": "xo", "ゃ": "xya", "ゅ": "xyu", "ょ": "xyo",
         "ゎ": "xwa", "ゔ": "vu"}
YOON = {"ゃ": "ya", "ゅ": "yu", "ょ": "yo"}
YOON_BASE = {"き": "ky", "ぎ": "gy", "し": "sh", "じ": "j", "ち": "ch", "に": "ny", "ひ": "hy", "び": "by",
             "ぴ": "py", "み": "my", "り": "ry"}


def romaji(kana):
    out, i = [], 0
    while i < len(kana):
        c = kana[i]
        if c == "っ":
            nxt = romaji(kana[i + 1:i + 3])
            out.append(nxt[0] if nxt and nxt[0].isalpha() and nxt[0] not in "aiueon" else "xtsu")
            i += 1
            continue
        if i + 1 < len(kana) and kana[i + 1] in YOON and c in YOON_BASE:
            out.append(YOON_BASE[c] + YOON[kana[i + 1]][1:])
            i += 2
            continue
        out.append(SMALL.get(c) or BASE.get(c))
        if out[-1] is None:
            return None
        i += 1
    return "".join(out)


def main():
    rows = []
    for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        cols = line.split("\t")
        if len(cols) < 3 or not cols[1]:
            continue
        words = [w for w in cols[2].split() if all("ぁ" <= ch <= "ゖ" or ch == "ー" for ch in w)]
        if not words:
            continue
        reading = max(words, key=len)
        typed = romaji(reading)
        if typed:
            rows.append(f"{typed}emoji\t{cols[1]}\t{reading}")
    Path(sys.argv[2]).write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(f"emoji-all: {len(rows)} inputs")


if __name__ == "__main__":
    main()
