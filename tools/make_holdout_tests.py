"""確かめ用の表（tests/conversion/holdout/holdout.tsv）から、試験の入力を作る。

  python3 tools/make_holdout_tests.py

  holdout.json: そのまま打つ（ja400.json と同じ形。tools/score_categories.py で区分ごとに採点できる）
  holdout-typo.json: 同じ文に打ち間違いを1つ入れる（typo150b.json と同じ形。correct_romaji つき）。
    種類は文ごとに順に替える: 母音の重ね打ち、1字抜け、隣どうしの入れ替え、隣のキー、余分な1字。
    英字を含む文（区分 mixed）と数字を含む文は、打ち間違いを入れない。

この表は学習にも調整にも使わない（tools/make_japanese_romaji_corpus.py などの材料に入れない）。
"""
import json
import random
from pathlib import Path

DIR = Path(__file__).resolve().parent.parent / "tests/conversion/holdout"

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
    "ー": "-", "、": ",", "。": ".", "？": "?", "！": "!",
}
YOON = {"ゃ": "ya", "ゅ": "yu", "ょ": "yo"}
YOON_BASE = {"き": "ky", "ぎ": "gy", "し": "sh", "じ": "j", "ち": "ch", "に": "ny", "ひ": "hy", "び": "by",
             "ぴ": "py", "み": "my", "り": "ry"}
SMALL_AFTER = {("ふ", "ぁ"): "fa", ("ふ", "ぃ"): "fi", ("ふ", "ぇ"): "fe", ("ふ", "ぉ"): "fo",
               ("て", "ぃ"): "thi", ("で", "ぃ"): "dhi", ("じ", "ぇ"): "je", ("し", "ぇ"): "she",
               ("ち", "ぇ"): "che", ("う", "ぃ"): "wi", ("う", "ぇ"): "we"}
# 隣のキー（JIS 配列の英字の段）
ROWS = ["qwertyuiop", "asdfghjkl", "zxcvbnm"]
NEIGHBOR = {}
for row in ROWS:
    for i, ch in enumerate(row):
        NEIGHBOR[ch] = (row[i - 1] if i > 0 else "") + (row[i + 1] if i + 1 < len(row) else "")


def romaji(kana):
    out, i = [], 0
    while i < len(kana):
        c = kana[i]
        if c == "っ":
            nxt = romaji(kana[i + 1:i + 3])
            out.append(nxt[0] if nxt and nxt[0] not in "aiueon-,.?!" else "xtu")
            i += 1
            continue
        if i + 1 < len(kana) and (c, kana[i + 1]) in SMALL_AFTER:
            out.append(SMALL_AFTER[(c, kana[i + 1])])
            i += 2
            continue
        if i + 1 < len(kana) and kana[i + 1] in YOON and c in YOON_BASE:
            out.append(YOON_BASE[c] + YOON[kana[i + 1]][1:])
            i += 2
            continue
        if c.isascii():
            out.append(c)
        elif c in BASE:
            out.append(BASE[c])
        else:
            raise SystemExit(f"no romaji for {c!r} in {kana}")
        i += 1
    return "".join(out)


def add_typo(text, kind, rng):
    letters = [i for i, ch in enumerate(text) if ch.isalpha()]
    vowels = [i for i in letters if text[i] in "aiueo"]
    inner = [i for i in letters if 2 <= i < len(text) - 2]
    if kind == "doubled_vowel":
        i = rng.choice([v for v in vowels if 2 <= v < len(text) - 2])
        return text[:i + 1] + text[i] + text[i + 1:]
    if kind == "dropped":
        i = rng.choice(inner)
        return text[:i] + text[i + 1:]
    if kind == "swapped":
        pairs = [i for i in inner if i + 1 < len(text) and text[i + 1].isalpha() and text[i] != text[i + 1]]
        i = rng.choice(pairs)
        return text[:i] + text[i + 1] + text[i] + text[i + 2:]
    if kind == "neighbor":
        i = rng.choice([j for j in inner if text[j] in NEIGHBOR])
        return text[:i] + rng.choice(NEIGHBOR[text[i]]) + text[i + 1:]
    if kind == "extra":
        i = rng.choice(inner)
        return text[:i] + rng.choice(NEIGHBOR.get(text[i], text[i]) or text[i]) + text[i:]
    raise ValueError(kind)


def main():
    rows = []
    for line in (DIR / "holdout.tsv").read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        cols = line.split("\t") + [""]
        category, intended, reading, alternatives = cols[:4]
        rows.append((category, intended, reading, [a for a in alternatives.split("|") if a]))
    counts = {}
    for category, *_ in rows:
        counts[category] = counts.get(category, 0) + 1
    items, typos = [], []
    kinds = ["doubled_vowel", "dropped", "swapped", "neighbor", "extra"]
    for n, (category, intended, reading, alternatives) in enumerate(rows, 1):
        typed = romaji(reading)
        item = {"id": f"h{n:03d}", "category": category, "romaji": typed, "intended": intended,
                "alternatives": alternatives}
        items.append(item)
        if category == "mixed" or any(ch.isdigit() for ch in reading):
            continue
        kind = kinds[len(typos) % len(kinds)]
        rng = random.Random(f"{n}-{kind}")
        wrong = add_typo(typed, kind, rng)
        if wrong != typed:
            typos.append({"id": f"ht{n:03d}", "category": kind, "romaji": wrong, "correct_romaji": typed,
                          "intended": intended, "alternatives": alternatives})
    summary = ", ".join(f"{k} {v}" for k, v in counts.items())
    (DIR / "holdout.json").write_text(json.dumps({
        "description": f"確かめ用の表 {len(items)} 件（holdout。学習にも調整にも使わない。2026-10-27 作成）。区分: {summary}",
        "items": items}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (DIR / "holdout-typo.json").write_text(json.dumps({
        "description": f"確かめ用の表の打ち間違い版 {len(typos)} 件（holdout.json の同じ文に打ち間違いを1つ。学習にも調整にも使わない）。"
                       "種類: " + ", ".join(kinds),
        "items": typos}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"holdout: {len(items)} items, {len(typos)} typo items")


if __name__ == "__main__":
    main()
