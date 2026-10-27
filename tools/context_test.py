"""Builds the context test (前後の文がある試験): a Wikipedia sentence typed in
romaji with the sentence before it as the text already in the input field.

  python tools/context_test.py --wiki <ja parquet> --table <romanji-hiragana.tsv> \
      --out tests/conversion/context.tsv [--count 1000] [--seed 20261016]

Targets are sentences of 10 to 40 characters with only kanji, kana, ー and
、。, preferring ones with a word of tools/data/homophone-cues.tsv (where the
context matters); the sentence before it in the same paragraph (up to 80
characters) is the context. Test sentences of tests/conversion are left out.
Output: target romaji<TAB>target<TAB>context. Sentences are from Wikipedia
(CC BY-SA 4.0).

--long adds two wider contexts for the same rows (the text on the screen when
typing into a long document): the paragraph so far (up to 400 characters) and
the article so far with its title (up to 1500 characters, line breaks as a
space). The rows picked do not change.
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
    ap.add_argument("--count", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=20261016)
    ap.add_argument("--long", action="store_true")
    args = ap.parse_args()
    table = rv.load_table(args.table)
    rev = rv.reverse_table(table)
    reader = bd.SudachiReader("core")
    repo = HERE.parent
    exclusion = bd.TestExclusion(repo / "tests/conversion", bd.load_romaji_table(Path(args.table)))
    groups = bd.load_homophone_groups(repo / "tools/data/homophone-cues.tsv")
    rng = random.Random(args.seed)
    picked, others = [], []
    for title, text in bd.iter_wiki_articles(args.wiki, rng):
        earlier = [title]
        for paragraph in bd.split_paragraphs(text):
            earlier.append("".join(paragraph))
            for i in range(1, len(paragraph)):
                before, sentence = paragraph[i - 1], paragraph[i]
                if len(before) > 80 or not (10 <= len(sentence) <= 40) or not SURFACE.fullmatch(sentence):
                    continue
                if not re.search(r"[ぁ-ゖ]", sentence) or exclusion.blocked(sentence):
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
                row = f"{raw}\t{sentence}\t{before}"
                if args.long:
                    so_far = "".join(paragraph[:i])
                    page = " ".join(earlier[:-1] + [so_far])
                    row += f"\t{so_far[-400:]}\t{page[-1500:]}"
                (picked if bd.homophone_hit(sentence, groups) else others).append(row)
                break  # one pair per paragraph
            if len(picked) >= args.count:
                break
        if len(picked) >= args.count:
            break
    rows = picked[: args.count]
    rows += others[: max(0, args.count - len(rows))]
    header = ("# ウィキペディア日本語版（CC BY-SA 4.0、https://ja.wikipedia.org/）の文。"
              "変換する文のローマ字<TAB>元の文<TAB>前の文" + ("<TAB>段落の前の文全部<TAB>記事の頭から" if args.long else "")
              + "。tools/context_test.py で作成。\n")
    Path(args.out).write_text(header + "\n".join(rows) + "\n", encoding="utf-8", newline="\n")
    print(f"{len(rows)} pairs ({len(picked)} with a homophone)")


if __name__ == "__main__":
    main()
