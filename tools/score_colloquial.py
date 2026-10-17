"""話し言葉の打ち込み試験（tests/conversion/colloquial.tsv）の採点。

  python tools/score_colloquial.py tests/conversion/colloquial.tsv results.tsv [label]

results.tsv は batch_convert.sh の出力（入力<TAB>文節<TAB>確定）。採点は 3 つ:
  厳しい: 元の文と、文字まで同じ。
  記号ゆれ込み: 、。！？ と空白の違い、ひらがな/カタカナの違いだけなら同じとみなす。
  緩い: 記号ゆれ込みに加えて、読みが同じで、漢字とかなの書き分けだけが違う場合（私/わたし、有難う/ありがとう、
        下さい/ください）も正解とみなす。別の漢字（同音異義語：橋/箸）は正解にしない。
        読みは SudachiPy で付ける（なければ緩い採点は出さない）。
間違いの型（記号・かなの文字種だけ・カタカナのまま・かな漢字の揺れ・同音の別の漢字・読みが違う・英字が混じった）に分けて数え、区分ごとの点数と
間違いの例も出す。
"""
import re
import sys
import unicodedata

LETTER = re.compile(r"[A-Za-zＡ-Ｚａ-ｚ]")
KATA = re.compile(r"[ァ-ヺ]")
KANJI = re.compile(r"[一-龯々〆]")
PUNCT = re.compile(r"[、。！？!?,.\s「」・…]")


def hira(text):
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in text)


def squash(text):
    return hira(PUNCT.sub("", unicodedata.normalize("NFKC", text)))


def make_reader():
    try:
        from sudachipy import Dictionary, SplitMode
    except ImportError:
        return None
    tokenizer = Dictionary(dict="core").create(SplitMode.C)

    def reading(text):
        out = []
        for m in tokenizer.tokenize(text):
            pos = m.part_of_speech()[0]
            out.append(m.surface() if pos in ("補助記号", "空白") else m.reading_form())
        return squash("".join(out))
    return reading


def classify_miss(original, out, reading):
    """間違いの型。"""
    if not LETTER.search(original) and LETTER.search(out):
        return "英字が混じった"
    if squash(original) == squash(out):
        return "記号・かなの文字種だけの違い" if original != out else "同じ"
    if len(KATA.findall(out)) - len(KATA.findall(original)) >= max(4, len(out) * 0.3):
        return "カタカナのまま（変換されなかった）"
    if reading is not None:
        if reading(original) == reading(out):
            ko, kp = set(KANJI.findall(original)), set(KANJI.findall(out))
            if kp <= ko or ko <= kp:
                return "かな漢字の書き分け"
            return "同音の別の漢字"
        return "読みが違う（別の語・区切り）"
    return "その他"


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    cases = []
    for line in open(sys.argv[1], encoding="utf-8"):
        if line.startswith("#") or not line.strip():
            continue
        p = line.rstrip("\n").split("\t")
        cases.append((p[0], p[1], p[2] if len(p) > 2 else "", p[3] if len(p) > 3 else ""))
    label = sys.argv[3] if len(sys.argv) > 3 else "話し言葉の打ち込み"
    got = {}
    for line in open(sys.argv[2], encoding="utf-8"):
        p = line.rstrip("\n").split("\t")
        if len(p) >= 3:
            got[p[0]] = p[2]
    reading = make_reader()
    total = strict = relaxed = loose = 0
    by_cat = {}
    types = {}
    misses = []
    for raw, original, category, sid in cases:
        out = got.get(raw)
        if out is None:
            continue
        total += 1
        s = out == original
        r = s or squash(out) == squash(original)
        kind = "同じ" if s else classify_miss(original, out, reading)
        l = r or kind == "かな漢字の書き分け"
        strict += s
        relaxed += r
        loose += l
        c = by_cat.setdefault(category or "-", [0, 0, 0, 0])
        c[0] += s
        c[1] += r
        c[2] += l
        c[3] += 1
        if not s:
            types[kind] = types.get(kind, 0) + 1
            misses.append((kind, f"  [{kind}] {raw} → {out}（元: {original}）"))
    print(f"{label}: 厳しい {strict}/{total}、記号ゆれ込み {relaxed}/{total}、"
          f"緩い {loose}/{total}" + ("" if reading else "（SudachiPy なし: 緩い = 記号ゆれ込み）"))
    for category in sorted(by_cat):
        a, b, c, n = by_cat[category]
        print(f"  {category}: 厳しい {a}/{n}、記号ゆれ込み {b}/{n}、緩い {c}/{n}")
    print("間違いの型（厳しい採点で違ったもの）: " + "、".join(f"{k} {v}" for k, v in sorted(types.items(), key=lambda x: -x[1])))
    letters = [m for k, m in misses if k == "英字が混じった"]
    if letters:
        print("英字が混じったもの:")
        print("\n".join(letters[:100]))
    shown = [m for k, m in misses if k != "英字が混じった"]
    if shown:
        print("元の文と違ったもの（先頭 200 件）:")
        print("\n".join(shown[:200]))


if __name__ == "__main__":
    main()
