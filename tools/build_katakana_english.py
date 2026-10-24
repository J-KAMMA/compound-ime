"""Builds tools/data/katakana-english.tsv: katakana loanwords and the English words they come from.

  python tools/build_katakana_english.py --pairs pairs.tsv --level lex10 --level lex20 --level lex35
      [--checked tools/data/loanwords.tsv] [--jmdict jmdict-loanwords.tsv] \
      [--wasei tools/data/wasei.tsv] --out tools/data/katakana-english.tsv

--pairs is the output of tools/build_loanword_pairs.py --all-words (english, katakana,
distance per sound). Each --level is an output directory of tools/build_english_lexicon.py,
most common first. A katakana word gets the English word of the most common level; when
another word of the same level is nearly as close (living / leaving), both are listed:
katakana cannot tell l from r or b from v, and the user picks among the candidates.
--checked pairs (english<TAB>katakana, checked by hand) come first and are kept as they are.
--jmdict is the output of tools/build_jmdict_loanwords.py (JMdict's lsource, wasei already left
out). Those pairs are kept as they are, after --checked, and before the pairs guessed from sound.
--wasei lists katakana of wasei (Japanese-made) words whose meaning differs from the English word;
those katakana words get no English candidate (マンション, パソコン, サラリーマン ...).

Kept from --pairs only: katakana of 4+ characters, English of 4+ letters, distance per sound
at most --threshold, no past forms (-ed) unless the katakana ends in ド or ト, no plural (-s)
unless it ends in ス or ズ, and -ing words only for katakana ending in ング (and back).
"""
import argparse
import re
from pathlib import Path

KATAKANA = re.compile(r"[ァ-ヺー]+")


def hiragana(katakana):
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in katakana)


def plausible(english, katakana):
    if english.endswith("ed"):
        return False  # past forms are rarely loanwords (snowballed for スノーボード)
    # A small ッ comes from a doubled or hard consonant in the spelling (セッション: session).
    if "ッ" in katakana and not any(a == b and a not in "aeiou" for a, b in zip(english, english[1:])) \
            and not any(s in english for s in ("ck", "tch", "x", "dg", "pt", "ct", "tt")):
        return False
    if english.endswith("s") and not english.endswith("ss") and not katakana.endswith(("ス", "ズ")):
        return False
    return english.endswith("ing") == katakana.endswith("ング")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pairs", type=Path, required=True)
    parser.add_argument("--level", type=Path, action="append", required=True)
    parser.add_argument("--checked", type=Path, action="append", default=[])
    parser.add_argument("--jmdict", type=Path, action="append", default=[],
                        help="katakana<TAB>English pairs from JMdict (tools/build_jmdict_loanwords.py)")
    parser.add_argument("--mozc", type=Path, help="Mozc src: katakana words whose reading is also a "
                        "hiragana or kanji word (ピッタリ: ぴったり) are Japanese, not loanwords")
    parser.add_argument("--wasei", type=Path, action="append", default=[],
                        help="katakana<TAB>original English of wasei words that get no English candidate")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--threshold", type=float, default=0.06)
    parser.add_argument("--margin", type=float, default=0.03)
    args = parser.parse_args()

    level = {}
    for rank, directory in enumerate(args.level):
        for word in (directory / "english-lexicon.txt").read_text(encoding="ascii").split():
            level.setdefault(word, rank)

    wasei = set()
    for path in args.wasei:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or "\t" not in line:
                continue
            wasei.add(line.split("\t", 1)[0])

    result = {}
    for checked in args.checked:
        for line in checked.read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or "\t" not in line:
                continue
            a, b = line.split("\t")[:2]
            katakana, english = (a, b) if KATAKANA.fullmatch(a) else (b, a)
            if english not in result.get(katakana, []):
                result.setdefault(katakana, []).append(english)

    for path in args.jmdict:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or "\t" not in line:
                continue
            f = line.split("\t")
            katakana, english = f[0], f[1]
            if (not KATAKANA.fullmatch(katakana) or len(katakana) < 3 or len(english) < 2
                    or katakana in wasei):
                continue
            result.setdefault(katakana, [])
            if english not in result[katakana] and len(result[katakana]) < 2:
                result[katakana].append(english)

    for katakana in list(result):
        if katakana in wasei:  # also in a checked list: the meaning differs, so no English candidate
            del result[katakana]

    japanese = set()  # readings of hiragana or kanji words
    if args.mozc:
        for path in sorted((args.mozc / "data/dictionary_oss").glob("dictionary0*.txt")):
            for line in path.read_text(encoding="utf-8").splitlines():
                f = line.split("\t")
                if len(f) >= 5 and not KATAKANA.fullmatch(f[4]) and not f[4].isascii():
                    japanese.add(f[0])

    by_katakana = {}
    for line in args.pairs.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        english, katakana, distance = line.split("\t")[:3]
        distance = float(distance)
        if (distance > args.threshold or len(katakana) < 4 or len(english) < 4 or english not in level
                or not plausible(english, katakana) or hiragana(katakana) in japanese):
            continue
        by_katakana.setdefault(katakana, []).append((level[english], distance, english))

    for katakana, options in by_katakana.items():
        if katakana in result or katakana in wasei:
            continue
        options.sort()
        best = options[0]
        rivals = [o for o in options[1:] if o[0] == best[0] and o[1] - best[1] < args.margin]
        result[katakana] = [best[2]] + [o[2] for o in rivals[:1]]

    with args.out.open("w", encoding="utf-8", newline="\n") as out:
        out.write("# katakana<TAB>english (tools/build_katakana_english.py; CMU Pronouncing Dictionary"
                  " BSD, SCOWL, tools/data/loanwords.tsv; wasei words in tools/data/wasei.tsv are left out)\n")
        for katakana in sorted(result):
            for english in result[katakana]:
                out.write(f"{katakana}\t{english}\n")
    print("katakana", len(result), "pairs", sum(len(v) for v in result.values()))


if __name__ == "__main__":
    main()
