"""Builds dictionary13.txt: spoken and online forms (行こっか, まあいっか, 笑, ウケる).

  python tools/build_colloquial_dictionary.py --mozc <mozc/src> --words tools/data/colloquial.tsv \
      tools/data/toku.tsv tools/data/naru.tsv --out dictionary13.txt [--install]

--words lines are "reading<TAB>surface<TAB>kind[<TAB>cost]" (noun, interj, verb_end, adj, or
one of the verb_toku_* / verb_doku_* / verb_naru_teru kinds). The part of speech comes from
the kind: noun is a common noun, interj and verb_end are interjections (a whole phrase that
ends a sentence), adj is an adjective in its plain form, and the contraction kinds are the
verb's 連用タ接続 or 連用形 plus Mozc's とく/どく (とく: 1296, どく: 1297), or なっ plus てる
(825/1097). A reading Mozc does not have gets --cost; a reading Mozc already has (わら: 藁)
gets its cheapest cost plus --behind. A fourth column replaces that cost (for a pair of
homophones where the default must be chosen in advance).
"""
import argparse
import re
from pathlib import Path

HIRAGANA = re.compile(r"[ぁ-ゖー]+")
I_ROW = set("いきしちにひみりぎじぢびぴ")
POS = {
    "noun": (1851, 1851),          # 名詞,一般
    "interj": (2591, 2591),        # 感動詞
    "verb_end": (2591, 2591),
    # 〜ておくの縮約は、前の動詞の連用タ接続（または連用形）＋ とく/どく の動詞。
    # 1296 is 動詞,非自立,*,*,五段・カ行イ音便,基本形,とく; 1297 is the same for どく.
    "verb_toku_godan": (841, 1296),    # 五段動詞,連用タ接続
    "verb_toku_ku": (726, 1296),       # 五段・カ行イ音便,連用タ接続
    "verb_toku_wa": (825, 1296),       # 五段・ワ行促音便,連用タ接続
    "verb_toku_ichidan": (701, 1296),  # 一段,連用形
    "verb_toku_suru": (842, 1296),     # 五段動詞,連用形（消す）
    "verb_doku_hatsuon": (841, 1297),  # 五段動詞,連用タ接続（読んで）
    "verb_doku_gu": (841, 1297),       # 五段動詞,連用タ接続（泳いで）
    "verb_naru_teru": (825, 1097),     # 五段・ワ行促音便,連用タ接続 + 一段,基本形,てる
}
ADJ_AUO = (2425, 2425)  # 形容詞,自立,*,*,形容詞・アウオ段,基本形
ADJ_I = (2467, 2467)    # 形容詞,自立,*,*,形容詞・イ段,基本形


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mozc", type=Path, required=True)
    parser.add_argument("--words", type=Path, nargs="+", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cost", type=int, default=5000)
    parser.add_argument("--behind", type=int, default=500)
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()

    data = args.mozc / "data/dictionary_oss"
    cheapest, existing = {}, set()
    for path in sorted(data.glob("dictionary*.txt")):
        if path.name == "dictionary13.txt":
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            f = line.split("\t")
            if len(f) < 5:
                continue
            cheapest[f[0]] = min(cheapest.get(f[0], 1 << 30), int(f[3]))
            existing.add((f[0], f[4]))

    entries = {}
    for path in args.words:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or line.count("\t") < 2:
                continue
            fields = line.split("\t")
            reading, surface, kind = fields[:3]
            if not HIRAGANA.fullmatch(reading) or (reading, surface) in existing:
                continue
            if kind == "adj":
                pos = ADJ_I if len(reading) >= 2 and reading.endswith("い") and reading[-2] in I_ROW else ADJ_AUO
            elif kind in POS:
                pos = POS[kind]
            else:
                continue
            if len(fields) > 3 and fields[3].strip():
                cost = int(fields[3])
            else:
                cost = cheapest[reading] + args.behind if reading in cheapest else args.cost
            entries[(reading, surface)] = (pos, cost)

    with args.out.open("w", encoding="utf-8", newline="\n") as out:
        for (reading, surface), (pos, cost) in sorted(entries.items()):
            out.write(f"{reading}\t{pos[0]}\t{pos[1]}\t{cost}\t{surface}\n")
    print("entries", len(entries))
    if args.install:
        (data / "dictionary13.txt").write_bytes(args.out.read_bytes())
        build = data / "BUILD.bazel"
        text = build.read_text(encoding="utf-8")
        if '"dictionary13.txt"' not in text:
            anchor = '        "dictionary12.txt",\n' if '"dictionary12.txt"' in text else '        "dictionary11.txt",\n'
            assert text.count(anchor) == 1
            build.write_text(text.replace(anchor, anchor + '        "dictionary13.txt",\n'), encoding="utf-8", newline="")


if __name__ == "__main__":
    main()
