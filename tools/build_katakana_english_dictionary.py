"""Builds dictionary12.txt: the English word of a katakana loanword as a candidate right after it.

  python tools/build_katakana_english_dictionary.py --mozc <mozc/src> --pairs tools/data/katakana-english.tsv
      --out dictionary12.txt [--install]

For each pair (katakana<TAB>english) whose katakana is a word in Mozc's dictionary, the English
word gets the katakana word's reading, part of speech and cost plus --penalty, so it comes right
after the katakana word: コーヒー, then coffee. Only the katakana word's reading is used: the
reading of the English spelling typed as romaji is often a Japanese word ("site" reads して),
and words typed in English spelling are kept as English by the English-word detector.
"""
import argparse
import re
import sys
from pathlib import Path


KATAKANA = re.compile(r"[ァ-ヺー]+")
HIRAGANA = re.compile(r"[ぁ-ゖー]+")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mozc", type=Path, required=True)
    parser.add_argument("--pairs", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--penalty", type=int, default=10)
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()

    data = args.mozc / "data/dictionary_oss"
    katakana_entries = {}  # katakana -> (reading, lid, rid, cost), the cheapest
    existing = set()
    for path in sorted(data.glob("dictionary*.txt")):
        if path.name == "dictionary12.txt":
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            f = line.split("\t")
            if len(f) < 5:
                continue
            reading, lid, rid, cost, surface = f[0], int(f[1]), int(f[2]), int(f[3]), f[4]
            existing.add((reading, surface))
            if KATAKANA.fullmatch(surface) and HIRAGANA.fullmatch(reading) and not 1921 <= lid <= 1929:
                old = katakana_entries.get(surface)
                if old is None or cost < old[3]:
                    katakana_entries[surface] = (reading, lid, rid, cost)

    entries = {}  # (reading, english) -> (lid, rid, cost)

    def add(reading, english, lid, rid, cost):
        if not HIRAGANA.fullmatch(reading) or (reading, english) in existing:
            return
        old = entries.get((reading, english))
        if old is None or cost < old[2]:
            entries[(reading, english)] = (lid, rid, cost)

    for line in args.pairs.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or "\t" not in line:
            continue
        katakana, english = line.split("\t")[:2]
        if katakana not in katakana_entries:
            continue
        reading, lid, rid, cost = katakana_entries[katakana]
        add(reading, english, lid, rid, cost + args.penalty)

    with args.out.open("w", encoding="utf-8", newline="\n") as out:
        for (reading, english), (lid, rid, cost) in sorted(entries.items()):
            out.write(f"{reading}\t{lid}\t{rid}\t{cost}\t{english}\n")
    print("entries", len(entries))
    if args.install:
        (data / "dictionary12.txt").write_bytes(args.out.read_bytes())
        build = data / "BUILD.bazel"
        text = build.read_text(encoding="utf-8")
        if '"dictionary12.txt"' not in text:
            old = '        "dictionary11.txt",\n'
            assert text.count(old) == 1
            build.write_text(text.replace(old, old + '        "dictionary12.txt",\n'), encoding="utf-8", newline="")


if __name__ == "__main__":
    main()
