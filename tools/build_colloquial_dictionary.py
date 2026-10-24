"""Builds dictionary13.txt: spoken and online forms (行こっか, まあいっか, 笑, ウケる).

  python tools/build_colloquial_dictionary.py --mozc <mozc/src> --words tools/data/colloquial.tsv \
      tools/data/toku.tsv tools/data/naru.tsv --out dictionary13.txt [--install]

--words lines are "reading<TAB>surface<TAB>kind[<TAB>cost]" (noun, interj, verb_end, adj, or
one of the verb_toku_* / verb_doku_* / verb_naru_* kinds). The part of speech comes from
the kind: noun is a common noun, interj and verb_end are interjections (a whole phrase that
ends a sentence), adj is an adjective in its plain form, and the contraction kinds are the
verb's 連用タ接続 or 連用形 plus Mozc's とく/どく (とく: 1296, どく: 1297), or なっ plus
てる/てた/てます/ている/ちゃう and た/ます. A reading Mozc does not have gets --cost; a
reading Mozc already has (わら: 藁) gets its cheapest cost plus --behind. A fourth column
replaces that cost (for a pair of homophones where the default must be chosen in advance).

The 〜とく／〜どく forms are also made from every verb in Mozc's dictionary whose 辞書形
costs at most --verb-max-cost (default 3000), not only the verbs listed in --words. The new
form costs the verb's cost plus --verb-cost-offset. A reading that already has a
contraction (買っとく / 読んどく) is left alone; a reading with only another word (三徳 for
みとく) also gets the contraction.
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
    "verb_naru_teta": (825, 142),      # 〜てた（た: 助動詞,特殊・タ,基本形）
    "verb_naru_temasu": (825, 240),    # 〜てます（ます: 助動詞,特殊・マス,基本形）
    "verb_naru_teiru": (825, 1084),    # 〜ている（いる: 動詞,非自立,一段,基本形）
    "verb_naru_chau": (825, 1785),     # 〜ちゃう（ちゃう: 動詞,非自立,五段・ワ行促音便,基本形）
    "verb_naru_chatta": (825, 142),    # 〜ちゃった（た: 助動詞,特殊・タ,基本形）
}
ADJ_AUO = (2425, 2425)  # 形容詞,自立,*,*,形容詞・アウオ段,基本形
ADJ_I = (2467, 2467)    # 形容詞,自立,*,*,形容詞・イ段,基本形

# 〜ておくの縮約は、動詞の辞書形から作れる。動詞の種類（id.def の品詞）ごとに
# 連用形・連用タ接続の作り方が決まるので、Mozc の辞書にある動詞をまとめて
# 縮約の形にする（30 語の一覧に限らない）。
TOKU_FORMS = ("とく", "といて", "といた", "とこう", "とけば", "ときます", "ときました")
DOKU_FORMS = ("どく", "どいて", "どいた", "どこう", "どけば", "どきます", "どきました")
VERB_BASE_POS = {
    837: "godan",    # 五段動詞,基本形
    723: "godan",    # 五段・カ行イ音便,基本形（書く、履く）
    763: "godan",    # 五段・ラ行,基本形（ある、いる、なる、依る）
    764: "godan",
    765: "godan",
    766: "godan",
    813: "godan",    # 五段・ワ行促音便,基本形（買う、言う、行う）
    814: "godan",
    815: "godan",
    816: "godan",
    680: "ichidan",  # 一段,基本形
    681: "ichidan",
    682: "ichidan",
    683: "ichidan",
    684: "ichidan",
    685: "ichidan",
    686: "ichidan",
    713: "ichidan",  # 一段・クレル
    719: "ichidan",  # 一段・得ル
    621: "sahen",    # サ変,基本形
    633: "sahen",    # サ変・スル,基本形
    590: "kahen",    # カ変・クル,基本形
    591: "kahen",    # カ変・来ル,基本形
    609: "kahen",    # カ変・来ル,基本形（来る）
    610: "kahen",
}
# 「ある」「なる」などは縮約の前の動詞にしない（あっとく、なっとく が
# 会っとく、納得 とぶつかる）。
VERB_BASE_SKIP = {"ある", "いる", "なる", "おる", "くれる", "くださる", "ござる",
                  "いたす", "なさる", "いらっしゃる", "おっしゃる", "える", "うる",
                  "できる", "みえる", "きこえる", "おもえる", "いえる", "いただける",
                  "すぎる"}


def verb_stem(surface, reading, kind):
    """辞書形から、縮約の前の形（連用形・連用タ接続）と とく／どく を作る。"""
    if kind == "godan":
        if not surface or not reading or surface[-1] != reading[-1]:
            return None
        patterns = {
            "う": ("っ", "toku", 825),  # ワ行促音便
            "つ": ("っ", "toku", 841),
            "る": ("っ", "toku", 841),
            "く": ("い", "toku", 726),  # カ行イ音便
            "ぐ": ("い", "doku", 841),  # ガ行イ音便
            "す": ("し", "toku", 842),  # サ行
            "ぬ": ("ん", "doku", 841),  # 撥音便
            "ぶ": ("ん", "doku", 841),
            "む": ("ん", "doku", 841),
        }
        pattern = patterns.get(reading[-1])
        if pattern is None:
            return None
        add, voice, left = pattern
        return surface[:-1] + add, reading[:-1] + add, voice, left
    if kind == "ichidan":
        if not surface.endswith("る") or not reading.endswith("る"):
            return None
        return surface[:-1], reading[:-1], "toku", 701
    if kind == "sahen":
        if not surface.endswith("する") or not reading.endswith("する"):
            return None
        return surface[:-2] + "し", reading[:-2] + "し", "toku", 638
    if kind == "kahen":
        if not surface.endswith("来る") or not reading.endswith("くる"):
            return None
        return surface[:-1], reading[:-2] + "き", "toku", 597
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mozc", type=Path, required=True)
    parser.add_argument("--words", type=Path, nargs="+", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cost", type=int, default=5000)
    parser.add_argument("--behind", type=int, default=500)
    parser.add_argument("--verb-max-cost", type=int, default=3000,
                        help="この費用以下の辞書形の動詞から縮約を作る")
    parser.add_argument("--verb-cost-offset", type=int, default=1500,
                        help="縮約の費用は辞書形の費用にこれを足す")
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()

    data = args.mozc / "data/dictionary_oss"
    cheapest, existing, verb_bases = {}, set(), []
    contraction_readings = set()
    suffixes = TOKU_FORMS + DOKU_FORMS
    for path in sorted(data.glob("dictionary*.txt")):
        if path.name == "dictionary13.txt":
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            f = line.split("\t")
            if len(f) < 5:
                continue
            cost = int(f[3])
            cheapest[f[0]] = min(cheapest.get(f[0], 1 << 30), cost)
            existing.add((f[0], f[4]))
            if any(f[4].endswith(suffix) for suffix in suffixes):
                contraction_readings.add(f[0])
            base_kind = VERB_BASE_POS.get(int(f[1]))
            if base_kind is not None and cost <= args.verb_max_cost:
                verb_bases.append((f[4], f[0], base_kind, cost))

    entries, auto_entries = {}, set()
    # 辞書にある動詞から、〜とく／〜どく の縮約をまとめて作る。同じ読みに
    # すでに縮約の形（買っとく、読んどく など）があれば、その語を壊さない。
    # 三徳（みとく）のような別の語しかない読みには、縮約を足す。
    for surface, reading, kind, cost in verb_bases:
        if reading in VERB_BASE_SKIP or not HIRAGANA.fullmatch(reading):
            continue
        stem = verb_stem(surface, reading, kind)
        if stem is None:
            continue
        surface_stem, reading_stem, voice, left = stem
        forms = TOKU_FORMS if voice == "toku" else DOKU_FORMS
        pos = (left, 1296 if voice == "toku" else 1297)
        for form in forms:
            new_reading = reading_stem + form
            new_surface = surface_stem + form
            if new_reading in contraction_readings or (new_reading, new_surface) in existing:
                continue
            entries[(new_reading, new_surface)] = (pos, cost + args.verb_cost_offset)
            auto_entries.add((new_reading, new_surface))
    for path in args.words:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or line.count("\t") < 2:
                continue
            fields = line.split("\t")
            reading, surface, kind = fields[:3]
            if not HIRAGANA.fullmatch(reading) or (reading, surface) in existing:
                continue
            if (reading, surface) in auto_entries:
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
