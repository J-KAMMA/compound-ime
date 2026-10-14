"""Builds tools/data/katakana-english.tsv: katakana loanwords and the English words they come from.

  python tools/build_katakana_english.py --pairs pairs.tsv --level lex10 --level lex20 --level lex35
      [--checked tools/data/loanwords.tsv] --out tools/data/katakana-english.tsv

--pairs is the output of tools/build_loanword_pairs.py --all-words (english, katakana,
distance per sound). Each --level is an output directory of tools/build_english_lexicon.py,
most common first. A katakana word gets the English word of the most common level; when
another word of the same level is nearly as close (living / leaving), both are listed:
katakana cannot tell l from r or b from v, and the user picks among the candidates.
--checked pairs (english<TAB>katakana, checked by hand) come first and are kept as they are.

Kept from --pairs only: katakana of 4+ characters, English of 4+ letters, distance per sound
at most --threshold, no past forms (-ed) unless the katakana ends in ド or ト, no plural (-s)
unless it ends in ス or ズ, and -ing words only for katakana ending in ング (and back).
"""
import argparse
from pathlib import Path


def plausible(english, katakana):
    if english.endswith("ed") and not katakana.endswith(("ド", "ト")):
        return False
    if english.endswith("s") and not english.endswith("ss") and not katakana.endswith(("ス", "ズ")):
        return False
    return english.endswith("ing") == katakana.endswith("ング")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pairs", type=Path, required=True)
    parser.add_argument("--level", type=Path, action="append", required=True)
    parser.add_argument("--checked", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--threshold", type=float, default=0.06)
    parser.add_argument("--margin", type=float, default=0.03)
    args = parser.parse_args()

    level = {}
    for rank, directory in enumerate(args.level):
        for word in (directory / "english-lexicon.txt").read_text(encoding="ascii").split():
            level.setdefault(word, rank)

    result = {}
    if args.checked:
        for line in args.checked.read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or "\t" not in line:
                continue
            english, katakana = line.split("\t")[:2]
            result.setdefault(katakana, []).append(english)

    by_katakana = {}
    for line in args.pairs.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        english, katakana, distance = line.split("\t")[:3]
        distance = float(distance)
        if (distance > args.threshold or len(katakana) < 4 or len(english) < 4 or english not in level
                or not plausible(english, katakana)):
            continue
        by_katakana.setdefault(katakana, []).append((level[english], distance, english))

    for katakana, options in by_katakana.items():
        if katakana in result:
            continue
        options.sort()
        best = options[0]
        rivals = [o for o in options[1:] if o[0] == best[0] and o[1] - best[1] < args.margin]
        result[katakana] = [best[2]] + [o[2] for o in rivals[:1]]

    with args.out.open("w", encoding="utf-8", newline="\n") as out:
        out.write("# katakana<TAB>english (tools/build_katakana_english.py; CMU Pronouncing Dictionary"
                  " BSD, SCOWL, tools/data/loanwords.tsv)\n")
        for katakana in sorted(result):
            for english in result[katakana]:
                out.write(f"{katakana}\t{english}\n")
    print("katakana", len(result), "pairs", sum(len(v) for v in result.values()))


if __name__ == "__main__":
    main()
