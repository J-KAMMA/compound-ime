"""Builds dictionary13.txt: spoken and online forms (行こっか, まあいっか, 笑, ウケる).

  python tools/build_colloquial_dictionary.py --mozc <mozc/src> --words tools/data/colloquial.tsv
      --out dictionary13.txt [--install]

--words lines are "reading<TAB>surface<TAB>kind" (noun, interj, verb_end, adj). The part of
speech comes from the kind: noun is a common noun, interj and verb_end are interjections (a
whole phrase that ends a sentence), adj is an adjective in its plain form. A reading Mozc does
not have gets --cost; a reading Mozc already has (わら: 藁) gets its cheapest cost plus
--behind, so the new form comes after the usual word unless the context prefers it.
"""
import argparse
import re
from pathlib import Path

HIRAGANA = re.compile(r"[ぁ-ゖー]+")
I_ROW = set("いきしちにひみりぎじぢびぴ")
POS = {"noun": 1851, "interj": 2591, "verb_end": 2591}
ADJ_AUO = 2425  # 形容詞,自立,*,*,形容詞・アウオ段,基本形
ADJ_I = 2467    # 形容詞,自立,*,*,形容詞・イ段,基本形


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mozc", type=Path, required=True)
    parser.add_argument("--words", type=Path, required=True)
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
    for line in args.words.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or line.count("\t") < 2:
            continue
        reading, surface, kind = line.split("\t")[:3]
        if not HIRAGANA.fullmatch(reading) or (reading, surface) in existing:
            continue
        if kind == "adj":
            pos = ADJ_I if len(reading) >= 2 and reading.endswith("い") and reading[-2] in I_ROW else ADJ_AUO
        elif kind in POS:
            pos = POS[kind]
        else:
            continue
        cost = cheapest[reading] + args.behind if reading in cheapest else args.cost
        entries[(reading, surface)] = (pos, cost)

    with args.out.open("w", encoding="utf-8", newline="\n") as out:
        for (reading, surface), (pos, cost) in sorted(entries.items()):
            out.write(f"{reading}\t{pos}\t{pos}\t{cost}\t{surface}\n")
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
