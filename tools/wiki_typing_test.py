"""Builds the Wikipedia typing test (ウィキペディアの打ち込み試験): Japanese
sentences from Wikipedia written in romaji, to type into the IME and compare
with the original text.

  python tools/wiki_typing_test.py --wiki <ja parquet> --table <romanji-hiragana.tsv> \
      --out tests/conversion/wiki-typing.tsv [--count 3000] [--seed 20261015]

Sentences of 10 to 40 characters with only kanji, kana, ー and 、。 (no digits
or letters) are read with SudachiPy (tools/zenz-finetune/build_dataset.py) and
written in the base romaji style (tools/romaji_variants.py); a sentence whose
romaji does not read back to the same kana is left out, and so is any test
sentence of tests/conversion (TestExclusion). Output: romaji<TAB>original.
The sentences are from Wikipedia (CC BY-SA 4.0); see the header lines.
"""
import argparse
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "zenz-finetune"))
sys.path.insert(0, str(HERE))
import build_dataset as bd  # noqa: E402
import romaji_variants as rv  # noqa: E402

SURFACE = re.compile(r"[一-龯々〆ヵヶぁ-ゖァ-ヺー、。]+")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wiki", nargs="+", required=True)
    ap.add_argument("--table", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--count", type=int, default=3000)
    ap.add_argument("--seed", type=int, default=20261015)
    ap.add_argument("--repo", default=str(HERE.parent))
    args = ap.parse_args()
    table = rv.load_table(args.table)
    rev = rv.reverse_table(table)
    reader = bd.SudachiReader("core")
    exclusion = bd.TestExclusion(Path(args.repo) / "tests/conversion", bd.load_romaji_table(Path(args.table)))
    rng = random.Random(args.seed)
    lines, seen = [], set()
    for _, text in bd.iter_wiki_articles(args.wiki, rng):
        for paragraph in bd.split_paragraphs(text):
            for sentence in paragraph:
                if not (10 <= len(sentence) <= 40) or not SURFACE.fullmatch(sentence) or sentence in seen:
                    continue
                if not re.search(r"[ぁ-ゖ]", sentence) or sentence[0] in "、。":
                    continue
                tokens = reader.analyze(sentence)
                if not tokens:
                    continue
                kana = bd.to_hiragana("".join(t.reading for t in tokens))
                if exclusion.blocked(sentence, [kana]):
                    continue
                raw = rv.write(kana, "base", rev)
                if not raw or rv.to_kana(raw, table) != kana:
                    continue
                seen.add(sentence)
                lines.append(f"{raw}\t{sentence}")
                break  # one sentence per paragraph: more articles
            if len(lines) >= args.count:
                break
        if len(lines) >= args.count:
            break
    header = ("# ウィキペディア日本語版（CC BY-SA 4.0、https://ja.wikipedia.org/）の文を、"
              "SudachiPy の読みからローマ字にしたもの。tools/wiki_typing_test.py で作成。\n")
    Path(args.out).write_text(header + "\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"{len(lines)} sentences")


if __name__ == "__main__":
    main()
