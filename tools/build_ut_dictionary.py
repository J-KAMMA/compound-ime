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
    "edict2": "名詞,一般,*,*,*,*,*",
    "sudachidict": "名詞,一般,*,*,*,*,*",
    "domain": "名詞,一般,*,*,*,*,*",
}
# カタカナだけの表記も残す材料（分野の言葉。tools/build_domain_words.py の出力）
KEEP_KANA = {"domain"}
READING = re.compile(r"[ぁ-ゖー]+")
KANA_OR_ASCII = re.compile(r"[ぁ-ゖァ-ヺー・ｦ-ﾟ\x20-\x7e　-〿＀-￯]+")
MARGIN = 100


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mozc", type=Path, required=True)
    parser.add_argument("--ut", type=Path, required=True)
    parser.add_argument("--sources", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--local-source", action="append", default=[], metavar="名前=ファイル",
                        help="--ut の中でなく、この名前のファイルから読む（例 domain=tools/data/domain-words.tsv）")
    parser.add_argument("--max-cost", action="append", default=[], metavar="名前=費用",
                        help="この名前の辞書から、元の費用がこの値以下の言葉だけを足す（例 neologd=8300）")
    parser.add_argument("--skip-composable", default="", metavar="名前,名前",
                        help="この名前の辞書から、Mozc の2つの項目の連なりで作れる言葉と、--max-reading より長い読みの言葉（長い句）は足さない")
    parser.add_argument("--max-reading", type=int, default=99, help="--skip-composable で絞る辞書の、読みの長さの上限")
    parser.add_argument("--first-wins", action="store_true",
                        help="同じ (読み, 表記) が複数の辞書にあるとき、--sources で先に書いた辞書の品詞と費用を残す"
                             "（既定は費用の低いほう。後の辞書の品詞が先の辞書の語を上書きしないため）")
    parser.add_argument("--min-reading", type=int, default=3)
    parser.add_argument("--install", action="store_true",
                        help="also copy to data/dictionary_oss/dictionary10.txt and list it in BUILD.bazel")
    args = parser.parse_args()
    args.skip_composable = set(args.skip_composable.split(","))

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

    locals_ = {}
    for item in args.local_source:
        name, _, file = item.partition("=")
        locals_[name] = Path(file)
    cost_limits = {}
    for item in args.max_cost:
        name, _, limit = item.partition("=")
        cost_limits[name] = int(limit)
    entries, counts = {}, {}
    for tier, source in enumerate(args.sources.split(",")):
        pos_id = ids[POS[source]]
        kept = 0
        source_path = locals_.get(source, args.ut / f"mozcdic-ut-{source}.txt")
        for line in source_path.read_text(encoding="utf-8").splitlines():
            fields = line.split("\t")
            if len(fields) != 5:
                continue
            reading, _, _, cost, surface = fields
            if (not READING.fullmatch(reading) or len(reading) < args.min_reading or
                    (KANA_OR_ASCII.fullmatch(surface) and source not in KEEP_KANA) or
                    (reading, surface) in pairs or
                    "\t" in surface or not surface.strip()):
                continue
            cost = int(cost)
            if cost > cost_limits.get(source, 1 << 30):  # 出る回数の少ない（費用の高い）言葉は足さない
                continue
            if source in args.skip_composable and (len(reading) > args.max_reading or
                                                   composed(reading, surface) is not None):
                continue
            if reading in max_cost:
                cost = max(cost, max_cost[reading] + MARGIN)
            key = (reading, surface)
            if key not in entries or (cost < entries[key][1] and not args.first_wins):
                entries[key] = (pos_id, cost, tier)
                kept += 1
        counts[source] = kept
    groups = {}
    for (reading, surface), value in entries.items():
        groups.setdefault(reading, []).append((surface, value))

    def arrange(reading, group, pos_id=None, floor=None):
        """同じ読みの言葉を並べ直す。品詞は1つにそろえる（でないと接続の費用でまた順番が入れ替わる）。"""
        def rank_key(entry):
            c = composed(reading, entry[0])
            return (c is None, c or 0, entry[1][1], entry[0])
        ranked = sorted(group, key=rank_key)
        if pos_id is None:
            pos_id = ranked[0][1][0]
        if floor is None:
            floor = min(value[1] for _, value in group)
        return [(s, (pos_id, floor + rank * 50, value[2])) for rank, (s, value) in enumerate(ranked)]

    with args.out.open("w", encoding="utf-8", newline="\n") as out:
        for reading in sorted(groups):
            group = groups[reading]
            if args.first_wins:
                # 先に書いた辞書の言葉は、後の辞書を足さないときと同じにする。後の辞書の言葉は、その後ろに足す。
                tiers = {}
                for item in group:
                    tiers.setdefault(item[1][2], []).append(item)
                group, pos_id, top = [], None, 0
                for tier in sorted(tiers):
                    if pos_id is None:
                        part = arrange(reading, tiers[tier]) if len(tiers[tier]) > 1 else tiers[tier]
                        pos_id = part[0][1][0]
                        part = [(s, (pos_id, v[1], v[2])) for s, v in part]
                    else:
                        part = arrange(reading, tiers[tier], pos_id, top + 50)
                    top = max(v[1] for _, v in part)
                    group += part
            elif len(group) > 1:
                group = arrange(reading, group)
            for surface, (pos_id, cost, _) in sorted(group):
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
