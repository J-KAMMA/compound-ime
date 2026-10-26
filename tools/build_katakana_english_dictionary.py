"""Builds dictionary12.txt: the English word of a katakana loanword as a candidate right after it.

  python tools/build_katakana_english_dictionary.py --mozc <mozc/src> --pairs tools/data/katakana-english.tsv
      --out dictionary12.txt [--wasei tools/data/wasei.tsv] [--install]

For each pair (katakana<TAB>english) whose katakana is a word in Mozc's dictionary, the English
word gets the katakana word's reading, part of speech and cost plus --penalty, so it comes right
after the katakana word: コーヒー, then coffee. Only the katakana word's reading is used: the
reading of the English spelling typed as romaji is often a Japanese word ("site" reads して),
and words typed in English spelling are kept as English by the English-word detector.

The reading's long-vowel variants (でんそー / でんそう / でんそ) get the same English word only
when the same katakana word has the variant reading in Mozc, or for the pairs in
reading_variants.ALLOWED (でんそ, あいでぃーる), so the Japanese candidate stays first and an
unrelated Japanese word (あき for アキー) gets no English candidate. --wasei never adds the
English word a wasei word merely looks like (マンション -> mansion), and neither does one part of a wasei compound
(オフィスレディー -> オフィス -> office).
"""
import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import reading_variants  # noqa: E402

KATAKANA = re.compile(r"[ァ-ヺー]+")
HIRAGANA = re.compile(r"[ぁ-ゖー]+")


def within_first_page(reading, cost, surface_costs):
    """The cost itself when it leaves the word among the first 10, otherwise the
    largest cost that keeps at most 9 words at or below it (one page is 9
    candidates, 10 checked).  Ties count: many words can share a cost, and the
    word must still be in the first page.  Never go down to the cheapest cost,
    so the English word is not the first candidate."""
    costs = sorted(surface_costs.get(reading, {}).values())
    if not costs or sum(1 for c in costs if c <= cost) <= 9:
        return cost
    for target in sorted(set(costs), reverse=True):
        if target >= cost or target <= costs[0]:
            continue
        if sum(1 for c in costs if c <= target) <= 9:
            return target
    # Every other word has the same cost: go just above the cheapest word so
    # the English word is in the first page and never first.
    if costs[0] + 1 < cost:
        return costs[0] + 1
    return cost


def hiragana(katakana):
    out = []
    for ch in katakana:
        if ch in "・=＝ 　":
            continue
        if ch == "ヴ":
            out.append("ゔ")
        elif "ァ" <= ch <= "ヶ":
            out.append(chr(ord(ch) - 0x60))
        else:
            out.append(ch)
    return "".join(out)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mozc", type=Path, required=True)
    parser.add_argument("--pairs", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--wasei", type=Path, help="tools/data/wasei.tsv: never add these pairs")
    parser.add_argument("--penalty", type=int, default=1)
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()

    data = args.mozc / "data/dictionary_oss"
    katakana_entries = {}  # katakana -> (reading, lid, rid, cost), the cheapest
    max_cost = {}
    surface_costs = {}  # reading -> {surface: cheapest cost}
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
            max_cost[reading] = max(max_cost.get(reading, 0), cost)
            costs = surface_costs.setdefault(reading, {})
            costs[surface] = min(costs.get(surface, 1 << 30), cost)
            if KATAKANA.fullmatch(surface) and HIRAGANA.fullmatch(reading) and not 1921 <= lid <= 1929:
                old = katakana_entries.get(surface)
                if old is None or cost < old[3]:
                    katakana_entries[surface] = (reading, lid, rid, cost)

    wasei = set()  # (reading variant, English word) that a wasei word merely looks like
    if args.wasei:
        for line in args.wasei.read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or "\t" not in line:
                continue
            katakana, english = line.split("\t")[:2]
            for reading in reading_variants.variants(hiragana(katakana)):
                wasei.add((reading, english.lower()))
                # A wasei compound (オフィスレディー -> office) must not put the
                # English word of one part (オフィス -> office) either.
                for n in range(2, len(reading)):
                    wasei.add((reading[:n], english.lower()))

    entries = {}  # (reading, surface) -> (lid, rid, cost)

    def add(reading, surface, lid, rid, cost):
        if not HIRAGANA.fullmatch(reading) or (reading, surface) in existing:
            return
        if (reading, surface.lower()) in wasei:
            return
        old = entries.get((reading, surface))
        if old is None or cost < old[2]:
            entries[(reading, surface)] = (lid, rid, cost)

    for line in args.pairs.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or "\t" not in line:
            continue
        katakana, english = line.split("\t")[:2]
        if katakana not in katakana_entries:
            continue
        reading, lid, rid, cost = katakana_entries[katakana]
        add(reading, english, lid, rid, within_first_page(reading, cost + args.penalty, surface_costs))
        # Long vowels are typed in more than one way (でんそー / でんそう / でんそ).
        # Add the English word under a variant only when the same katakana word
        # has that reading in Mozc, or the pair is in ALLOWED.  Otherwise the
        # variant can be an unrelated Japanese word (アキー -> あき / 秋).
        for variant in sorted(reading_variants.variants(reading)):
            if variant == reading or variant not in max_cost:
                continue
            if (variant, katakana) not in existing and not reading_variants.allowed(reading, variant):
                continue
            add(variant, english, lid, rid,
                within_first_page(variant, max_cost[variant] + args.penalty, surface_costs))

    with args.out.open("w", encoding="utf-8", newline="\n") as out:
        for (reading, surface), (lid, rid, cost) in sorted(entries.items()):
            out.write(f"{reading}\t{lid}\t{rid}\t{cost}\t{surface}\n")
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
