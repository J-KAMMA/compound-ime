"""Official spellings of brand and service names typed in lowercase.

  python tools/build_brand_casing.py --ut mozcdic-ut-sudachidict.txt
      --out tools/data/brand-casing.tsv

For each word of tools/data/jaen-brand-words.txt and jaen-extra-words.txt,
the SudachiDict surface (mozcdic-ut-sudachidict, Apache-2.0) that is the same
word with capitals (google -> Google, youtube -> YouTube, iphone -> iPhone).
When SudachiDict spells a word with several capitalizations, the cheapest one
wins. Words SudachiDict has only in lowercase stay as typed. Hand fixes in
tools/data/brand-casing-fixes.tsv override it ("-" keeps a word as typed).
"""
import argparse
import re
from pathlib import Path

DATA = Path(__file__).parent / "data"
ASCII_WORD = re.compile(r"[A-Za-z][A-Za-z0-9.+&'-]*")


def words(path):
    return [w for w in path.read_text(encoding="utf-8").splitlines() if w and not w.startswith("#")]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ut", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    wanted = {w.lower() for w in words(DATA / "jaen-brand-words.txt") + words(DATA / "jaen-extra-words.txt")}
    best = {}
    for line in args.ut.read_text(encoding="utf-8").splitlines():
        f = line.split("\t")
        if len(f) != 5 or not ASCII_WORD.fullmatch(f[4]) or f[4] == f[4].lower():
            continue
        lower = f[4].lower()
        if lower in wanted and (lower not in best or int(f[3]) < best[lower][0]):
            best[lower] = (int(f[3]), f[4])
    for line in words(DATA / "brand-casing-fixes.tsv"):
        lower, official = line.split("\t")
        if official == "-":
            best.pop(lower, None)
        else:
            best[lower] = (0, official)
    with args.out.open("w", encoding="utf-8", newline="\n") as out:
        out.write("# typed<TAB>official spelling (tools/build_brand_casing.py)\n")
        for lower in sorted(best):
            out.write(f"{lower}\t{best[lower][1]}\n")
    print("names", len(best), "of", len(wanted))


if __name__ == "__main__":
    main()
