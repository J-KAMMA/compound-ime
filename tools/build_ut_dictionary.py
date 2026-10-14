"""Builds an extra Mozc system dictionary file from mozcdic-ut-* word lists.

  python tools/build_ut_dictionary.py --mozc <mozc/src> --ut <dir> \
      --sources sudachidict --out dictionary10.txt [--install]

Adopted 2026-10-11: sudachidict only (proper nouns +11/+2/+2 on a 300-item set,
no regressions; adding jawiki, personal-names or place-names did not help).
Source file: mozcdic-ut-sudachidict.txt.bz2 (Apache-2.0, from SudachiDict),
SHA-256 d2cb4b2b16d513e257d26d1c33673ebda254a1d5aa0c3c0c9bc94f932619fbdc.

<dir> holds mozcdic-ut-<name>.txt files (github.com/utuhiro78/mozcdic-ut-<name>,
"reading 0000 0000 cost surface"). Entries are added only where they cannot
displace what Mozc already ranks:
- (reading, surface) pairs Mozc already has are skipped;
- readings shorter than --min-reading characters are skipped;
- surfaces made only of kana, ASCII or symbols are skipped (transliteration
  and English detection already produce those);
- an entry whose reading Mozc already has gets a cost above every existing
  entry of that reading, so it never becomes the first candidate on its own;
- entries sharing a reading (芥川龍之介 and 芥川竜之介) are ordered by how
  cheaply Mozc composes the surface from two of its own entries (芥川 +
  龍之介), so Mozc's preferred variant stays first;
- part of speech: person names 名詞,固有名詞,人名,一般; places 名詞,固有名詞,
  地域,一般; jawiki 名詞,固有名詞,一般; sudachidict 名詞,一般.
"""
import argparse
import re
from pathlib import Path

POS = {  # lines of data/dictionary_oss/id.def, resolved to ids below
    "personal-names": "名詞,固有名詞,人名,一般,*,*,*",
    "place-names": "名詞,固有名詞,地域,一般,*,*,*",
    "jawiki": "名詞,固有名詞,一般,*,*,*,*",
    "neologd": "名詞,固有名詞,一般,*,*,*,*",
    "sudachidict": "名詞,一般,*,*,*,*,*",
}
READING = re.compile(r"[ぁ-ゖー]+")
KANA_OR_ASCII = re.compile(r"[ぁ-ゖァ-ヺー・ｦ-ﾟ\x20-\x7e　-〿＀-￯]+")
MARGIN = 100


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mozc", type=Path, required=True)
    parser.add_argument("--ut", type=Path, required=True)
    parser.add_argument("--sources", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--min-reading", type=int, default=3)
    parser.add_argument("--install", action="store_true",
                        help="also copy to data/dictionary_oss/dictionary10.txt and list it in BUILD.bazel")
    args = parser.parse_args()

    data = args.mozc / "data/dictionary_oss"
    ids = {}
    for line in (data / "id.def").read_text(encoding="utf-8").splitlines():
        number, _, pos = line.partition(" ")
        ids.setdefault(pos, number)
    pairs, max_cost = {}, {}  # (reading, surface) -> lowest cost
    for path in sorted(data.glob("dictionary0*.txt")):
        for line in path.read_text(encoding="utf-8").splitlines():
            reading, _, _, cost, surface = line.split("\t")[:5]
            pairs[(reading, surface)] = min(pairs.get((reading, surface), 1 << 30), int(cost))
            max_cost[reading] = max(max_cost.get(reading, 0), int(cost))

    def composed(reading, surface):
        """Lowest cost of surface as two Mozc entries, or None."""
        best = None
        for i in range(1, len(reading)):
            for j in range(1, len(surface)):
                a = pairs.get((reading[:i], surface[:j]))
                b = pairs.get((reading[i:], surface[j:])) if a is not None else None
                if b is not None and (best is None or a + b < best):
                    best = a + b
        return best

    entries, counts = {}, {}
    for source in args.sources.split(","):
        pos_id = ids[POS[source]]
        kept = 0
        for line in (args.ut / f"mozcdic-ut-{source}.txt").read_text(encoding="utf-8").splitlines():
            fields = line.split("\t")
            if len(fields) != 5:
                continue
            reading, _, _, cost, surface = fields
            if (not READING.fullmatch(reading) or len(reading) < args.min_reading or
                    KANA_OR_ASCII.fullmatch(surface) or (reading, surface) in pairs or
                    "\t" in surface or not surface.strip()):
                continue
            cost = int(cost)
            if reading in max_cost:
                cost = max(cost, max_cost[reading] + MARGIN)
            key = (reading, surface)
            if key not in entries or cost < entries[key][1]:
                entries[key] = (pos_id, cost)
                kept += 1
        counts[source] = kept
    groups = {}
    for (reading, surface), value in entries.items():
        groups.setdefault(reading, []).append((surface, value))
    with args.out.open("w", encoding="utf-8", newline="\n") as out:
        for reading in sorted(groups):
            group = groups[reading]
            if len(group) > 1:
                def rank_key(entry):
                    c = composed(reading, entry[0])
                    return (c is None, c or 0, entry[1][1], entry[0])
                # One part of speech per reading, or connection costs would
                # reorder the variants again.
                floor = min(cost for _, (_, cost) in group)
                ranked = sorted(group, key=rank_key)
                pos_id = ranked[0][1][0]
                group = [(s, (pos_id, floor + rank * 50)) for rank, (s, _) in enumerate(ranked)]
            for surface, (pos_id, cost) in sorted(group):
                out.write(f"{reading}\t{pos_id}\t{pos_id}\t{cost}\t{surface}\n")
    print("entries", len(entries), counts)
    if args.install:
        target = data / "dictionary10.txt"
        target.write_bytes(args.out.read_bytes())
        build = data / "BUILD.bazel"
        text = build.read_text(encoding="utf-8")
        if '"dictionary10.txt"' not in text:
            old = '        "dictionary09.txt",\n        "//dictionary:zip_code_data",'
            if text.count(old) != 1:
                raise SystemExit("BUILD.bazel: dictionary list not found")
            build.write_text(text.replace(old, '        "dictionary09.txt",\n        "dictionary10.txt",\n'
                                          '        "//dictionary:zip_code_data",'), encoding="utf-8", newline="")
        print("installed", target)


if __name__ == "__main__":
    main()
