"""Builds dictionary14.txt: proper nouns written in English as candidates of their kana reading.

  python tools/build_proper_noun_dictionary.py --mozc <mozc/src> --names tools/data/proper-nouns.tsv \
      --out dictionary14.txt [--install]

For each line of tools/data/proper-nouns.tsv (shown<TAB>typed<TAB>flags<TAB>readings<TAB>...), the
spelling (Google, New York, Elon Musk) becomes a candidate of each reading (ぐーぐる, にゅーよーく).
It never takes the first place from what Mozc already has:
- the same katakana word is in Mozc's dictionary with that reading and is the cheapest entry of the
  reading: the name takes its part of speech and cost plus --penalty, so it comes right after the
  katakana word (グーグル, then Google). When another word is cheaper (たいら: 平), the name costs --margin
  more than every entry of the reading (it never beat the Japanese words in a sentence: Tyla);
- the reading is in Mozc's dictionary otherwise: the name costs --margin more than every entry of that
  reading;
- a reading Mozc does not have (4 kana or more): a proper-noun entry at --default-cost, high enough that
  the name never wins in a sentence over Mozc's own words (an earlier 8200 turned たいら into Tyla and
  カップヌードル into Cup Noodles) and is only a candidate of its reading.
A (reading, spelling) pair Mozc already has is skipped. Readings shorter than 3 kana are not used.
"""
import argparse
import re
from pathlib import Path

HIRAGANA = re.compile(r"[ぁ-ゖー]+")
KATAKANA_OF = {chr(c): chr(c + 0x60) for c in range(0x3041, 0x3097)}
KATAKANA_OF["ゔ"] = "ヴ"
POS = {  # lines of data/dictionary_oss/id.def
    "company": "名詞,固有名詞,組織,*,*,*,*",
    "person": "名詞,固有名詞,人名,一般,*,*,*",
    "place": "名詞,固有名詞,地域,一般,*,*,*",
    "other": "名詞,固有名詞,一般,*,*,*,*",
}
KIND_POS = {"business": "company", "brand": "company", "airline": "company", "tvnetwork": "company",
            "newspaper": "company", "university": "company", "sportsteam": "company", "museum": "company",
            "band": "company", "people": "person",
            "country": "place", "usstate": "place", "city": "place", "region": "place", "island": "place",
            "mountain": "place", "river": "place", "lake": "place"}


def katakana(reading):
    return "".join(KATAKANA_OF.get(c, c) for c in reading)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mozc", type=Path, required=True)
    parser.add_argument("--names", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--penalty", type=int, default=10)
    parser.add_argument("--margin", type=int, default=2000)
    parser.add_argument("--default-cost", type=int, default=15000)
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()

    data = args.mozc / "data/dictionary_oss"
    ids = {}
    for line in (data / "id.def").read_text(encoding="utf-8").splitlines():
        number, _, pos = line.partition(" ")
        ids.setdefault(pos, number)
    existing = set()
    katakana_entries = {}  # (reading, katakana) -> (lid, rid, cost)
    max_cost, min_cost = {}, {}
    for path in sorted(data.glob("dictionary*.txt")):
        if path.name == "dictionary14.txt":
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            f = line.split("\t")
            if len(f) < 5:
                continue
            reading, lid, rid, cost, surface = f[0], int(f[1]), int(f[2]), int(f[3]), f[4]
            existing.add((reading, surface))
            max_cost[reading] = max(max_cost.get(reading, 0), cost)
            min_cost[reading] = min(min_cost.get(reading, 1 << 30), cost)
            if surface == katakana(reading):  # the reading written in katakana, as the name is usually written
                old = katakana_entries.get((reading, surface))
                if old is None or cost < old[2]:
                    katakana_entries[(reading, surface)] = (lid, rid, cost)

    entries = {}
    for line in args.names.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        f = line.split("\t")
        shown, readings, kind = f[0], f[3], f[4]
        for reading in readings.split("|"):
            if not HIRAGANA.fullmatch(reading) or len(reading) < 3 or (reading, shown) in existing:
                continue
            kata = katakana_entries.get((reading, katakana(reading)))
            if kata and kata[2] <= min_cost[reading]:  # the katakana word is Mozc's first choice for the reading
                lid, rid, cost = kata[0], kata[1], kata[2] + args.penalty
            elif kata:  # also a Japanese word (たいら: 平, Tyla is タイラ): the name stays behind all of them
                lid, rid, cost = kata[0], kata[1], max_cost[reading] + args.margin
            else:
                if reading not in max_cost and len(reading) < 4:
                    continue  # a short reading no word has: the name could win over kana of other words
                pos = ids[POS[KIND_POS.get(kind, "other")]]
                lid = rid = int(pos)
                cost = max_cost[reading] + args.margin if reading in max_cost else args.default_cost
            key = (reading, shown)
            if key not in entries or cost < entries[key][2]:
                entries[key] = (lid, rid, cost)

    with args.out.open("w", encoding="utf-8", newline="\n") as out:
        for (reading, shown), (lid, rid, cost) in sorted(entries.items()):
            out.write(f"{reading}\t{lid}\t{rid}\t{cost}\t{shown}\n")
    print("entries", len(entries))
    if args.install:
        (data / "dictionary14.txt").write_bytes(args.out.read_bytes())
        build = data / "BUILD.bazel"
        text = build.read_text(encoding="utf-8")
        if '"dictionary14.txt"' not in text:
            anchor = '        "dictionary13.txt",\n'
            assert text.count(anchor) == 1
            build.write_text(text.replace(anchor, anchor + '        "dictionary14.txt",\n'), encoding="utf-8", newline="")


if __name__ == "__main__":
    main()
