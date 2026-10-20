"""Writes romaji lines of Japanese-only text, to check that new English words do not turn Japanese
into English (tools/build_proper_nouns.py --corpus).

  python tools/make_japanese_romaji_corpus.py --table <romanji-hiragana.tsv> --dictionary-dir <dictionary_oss> \
      --out corpus.txt [--generated 300000]

The lines: the romaji of every Japanese-only test sentence in tests/conversion (ja400, wiki-typing,
colloquial, variants in other typing styles), and strings of 2 to 4 readings of Mozc dictionary
words (kana only) written in the Hepburn style and in the Kunrei style.
"""
import argparse
import json
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import romaji_variants as rv  # noqa: E402

HIRA = re.compile(r"[ぁ-ゖー]+")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", type=Path, required=True)
    ap.add_argument("--dictionary-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--generated", type=int, default=300000)
    ap.add_argument("--english-words", type=Path,
                    help="a list of English words (common-words.txt of tools/build_english_lexicon.py): "
                         "writes strings of 2 to 5 pieces, Japanese readings and English words, instead")
    ap.add_argument("--seed", type=int, default=20261021)
    args = ap.parse_args()
    tests = HERE.parent / "tests" / "conversion"
    lines = []
    for item in json.loads((tests / "ja400.json").read_text(encoding="utf-8"))["items"]:
        lines.append(item["romaji"])
    for name in ("wiki-typing.tsv", "colloquial.tsv"):
        for line in (tests / name).read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#"):
                f = line.split("\t")
                if len(f) >= 2 and not re.search(r"[A-Za-zＡ-Ｚａ-ｚ]", f[1]):
                    lines.append(f[0])
    for line in (tests / "variants.tsv").read_text(encoding="utf-8").splitlines():
        f = line.split("\t")
        if len(f) >= 4 and not re.search(r"[A-Za-z]", f[3]):
            lines.append(f[2])
    table = rv.load_table(args.table)
    rev = rv.reverse_table(table)
    readings = []
    for path in sorted(args.dictionary_dir.glob("dictionary0*.txt")):
        for line in path.read_text(encoding="utf-8").splitlines():
            f = line.split("\t")
            if len(f) == 5 and HIRA.fullmatch(f[0]) and 2 <= len(f[0]) <= 8:
                readings.append(f[0])
    rng = random.Random(args.seed)
    if args.english_words:
        english = [w for w in args.english_words.read_text().split() if 3 <= len(w) <= 10 and w.isalpha()]
        mixed = []
        while len(mixed) < args.generated:
            pieces = []
            for _ in range(rng.randint(2, 5)):
                if rng.random() < 0.4:
                    pieces.append(rng.choice(english))
                else:
                    kana = rng.choice(readings)
                    written = rv.write(kana, "base", rev)
                    if written and rv.to_kana(written, table) == kana:
                        pieces.append(written)
            if any(p.isalpha() and p in english for p in pieces):
                mixed.append("".join(pieces))
        args.out.write_text("\n".join(mixed) + "\n", encoding="utf-8")
        print("mixed lines", len(mixed))
        return
    made = 0
    while made < args.generated:
        kana = "".join(rng.choice(readings) for _ in range(rng.randint(2, 4)))
        style = "base" if rng.random() < 0.7 else "kunrei"
        written = rv.write(kana, style, rev)
        if written and rv.to_kana(written, table) == kana:
            lines.append(written)
            made += 1
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("lines", len(lines))


if __name__ == "__main__":
    main()
