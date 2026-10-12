"""Lists Japanese place names typed in English-style Hepburn without long vowels.

  python tools/build_hepburn_names.py --mozc <mozc/src> --out <hepburn-names.tsv> [--max-cost N]

From data/dictionary_oss place-name entries (名詞,固有名詞,地域,*) whose reading
has a long vowel (おう, おお, うう), writes "spelling<TAB>surface<TAB>normal"
lines such as "tokyo<TAB>東京<TAB>toukyou": the reading romanized with the long
vowel dropped, and as normally typed. Spellings in --exclude (one per line;
those that turned ordinary Japanese romaji into English) are left out. Only spellings that differ from how the reading is normally
typed (toukyou) are kept, and only the most common surface per spelling.
User decision 2026-10-11: such spellings stay as typed ASCII, the kanji is the
second candidate.
"""
import argparse
import re
from pathlib import Path

ROMAJI = {}
for row in """あ a い i う u え e お o か ka き ki く ku け ke こ ko さ sa し shi す su せ se そ so
た ta ち chi つ tsu て te と to な na に ni ぬ nu ね ne の no は ha ひ hi ふ fu へ he ほ ho
ま ma み mi む mu め me も mo や ya ゆ yu よ yo ら ra り ri る ru れ re ろ ro わ wa を o
が ga ぎ gi ぐ gu げ ge ご go ざ za じ ji ず zu ぜ ze ぞ zo だ da ぢ ji づ zu で de ど do
ば ba び bi ぶ bu べ be ぼ bo ぱ pa ぴ pi ぷ pu ぺ pe ぽ po""".split("\n"):
    items = row.split()
    for k, r in zip(items[::2], items[1::2]):
        ROMAJI[k] = r
YOON = {"ゃ": "a", "ゅ": "u", "ょ": "o"}
O_ROW = set("おこそとのほもよろごぞどぼぽ")
U_ROW = set("うくすつぬふむゆるぐずづぶぷ")


def drop_long(reading):
    out = []
    for ch in reading:
        prev = out[-1] if out else ""
        last = prev[-1] if prev else ""
        if last and ch == "う" and (last in O_ROW or last in U_ROW or last in "ょゅ"):
            continue
        if last and ch == "お" and (last in O_ROW or last == "ょ"):
            continue
        out.append(ch)
    return "".join(out)


def hepburn(kana):
    out, i = [], 0
    while i < len(kana):
        ch = kana[i]
        if ch == "っ":
            nxt = hepburn(kana[i + 1:i + 2])[:1] if i + 1 < len(kana) else ""
            out.append("t" if nxt == "c" else nxt)
            i += 1
            continue
        if ch == "ん":
            out.append("n")
            i += 1
            continue
        if ch not in ROMAJI:
            return None
        r = ROMAJI[ch]
        if i + 1 < len(kana) and kana[i + 1] in YOON:
            base = r[:-1]
            r = (base if base in ("sh", "ch", "j") else base + "y") + YOON[kana[i + 1]]
            i += 1
        out.append(r)
        i += 1
    return "".join(out)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mozc", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-cost", type=int, default=5000)
    parser.add_argument("--exclude", type=Path)
    parser.add_argument("--top", type=int, default=150)
    parser.add_argument("--min-length", type=int, default=5)
    args = parser.parse_args()
    data = args.mozc / "data/dictionary_oss"
    place_ids = set()
    for line in (data / "id.def").read_text(encoding="utf-8").splitlines():
        number, _, pos = line.partition(" ")
        if pos.startswith("名詞,固有名詞,地域,"):
            place_ids.add(number)
    best = {}
    for path in sorted(data.glob("dictionary0*.txt")):
        for line in path.read_text(encoding="utf-8").splitlines():
            reading, lid, _, cost, surface = line.split("\t")[:5]
            cost = int(cost)
            if (lid not in place_ids or cost > args.max_cost or not re.fullmatch(r"[ぁ-ゖ]+", reading) or
                    not re.search(r"[一-鿿]", surface)):
                continue
            short = drop_long(reading)
            if short == reading:
                continue
            spelling = hepburn(short)
            if not spelling or len(spelling) < 4 or spelling == hepburn(reading):
                continue
            if spelling not in best or cost < best[spelling][0]:
                best[spelling] = (cost, surface, hepburn(reading))
    excluded = {w for w in args.exclude.read_text(encoding="utf-8").split() if not w.startswith("#")} if args.exclude else set()
    ranked = [(s, v) for s, v in sorted(best.items(), key=lambda x: x[1][0]) if s not in excluded]
    # Adopted 2026-10-11: the --top most common, at least --min-length letters,
    # no numerals (十二 juni): no ordinary Japanese turned into English in any
    # test set; wider lists caught お先に (osaki), 本郷 (hongo), コナン (konan).
    kept = [(s, v) for s, v in ranked[:args.top]
            if len(s) >= args.min_length and not re.search(r"[一二三四五六七八九十]", v[1])]
    with args.out.open("w", encoding="utf-8", newline="\n") as out:
        for spelling, (cost, surface, normal) in kept:
            out.write(f"{spelling}\t{surface}\t{normal}\n")
    print("names", len(best), "kept", len(kept))


if __name__ == "__main__":
    main()
