"""Builds dictionary14.txt: proper nouns written in English as candidates of their kana reading.

  python tools/build_proper_noun_dictionary.py --mozc <mozc/src> --names tools/data/proper-nouns.tsv \
      [--names tools/data/proper-noun-extra.tsv] [--wasei tools/data/wasei.tsv] --out dictionary14.txt [--install]

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
A (reading, spelling) pair Mozc already has is skipped. Readings of 2 kana are used only from the
first of several --names files and only when Mozc already has a word for the reading (the checked
tools/data/proper-noun-extra.tsv: メタ, then Meta); the generated proper-nouns.tsv and a single
--names keep the old 3-kana rule (the acronym table is what adds あい → AI).

An optional 7th column of --names (after the number of Wikipedia language editions) holds other
official spellings separated by | (DRAGON BALL for Dragon Ball, NIKE for Nike, adidas for Adidas).
They are candidates of the same reading, just after the main spelling, and never before the
Japanese word either. --names may be given more than once: rows of the earlier files come first
when two files name the same reading (tools/data/proper-noun-extra.tsv is passed before
proper-nouns.tsv, so the checked official spelling comes first).

Only the long-vowel variant pairs in reading_variants.ALLOWED (でんそー / でんそう / でんそ,
あいでぃる / あいでぃーる) are added.  A variant that merely drops the long vowel is not added
even when Mozc has a word for the variant reading: it can be an unrelated Japanese word (おおさか
-> おさか / 大阪, あたーる -> あたる / 当たる). --wasei drops a name that is what a wasei word
merely looks like (マンション -> mansion), nor one part of a wasei compound
(オフィスレディー -> オフィス -> office).  A work's English spelling goes after the Japanese
title even when the reading's katakana form is a cheaper Mozc entry (ドラゴンボールZ before
Dragon Ball Z).

--acronyms tools/data/acronyms.tsv: the acronyms that read as Japanese words (type b: ai → あい, ui → うい) are
the exception to the 3-kana rule. Each becomes a candidate of its reading at the rank the list gives (1 to 3): rank
1 costs less than every Mozc entry of the reading, so it is the first candidate (AI for あい; 愛 follows); rank 2 or
3 lies between the (rank - 1)th and the rank-th cheapest entries, with the part of speech of the cheapest entry, so
it never wins a sentence over that entry. A reading no word has gets --default-cost. (The reading あい of AI in
proper-nouns.tsv is skipped by the 3-kana rule; this is what makes AI a candidate of あい.)
"""
import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import reading_variants  # noqa: E402

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
WORK_KINDS = {"film", "filmseries", "tvseries", "tvprogram", "videogame", "videogameseries",
              "album", "band", "novel", "lightnovel", "manga", "anime", "comic", "character", "work"}


def katakana(reading):
    return "".join(KATAKANA_OF.get(c, c) for c in reading)


def within_first_page(reading, cost, surface_costs):
    """The cost itself when it leaves the name among the first 10, otherwise the
    largest cost that keeps at most 9 words at or below it (one page is 9
    candidates, 10 checked).  Ties count: many words can share a cost, and the
    name must still be in the first page.  Never go down to the cheapest cost,
    so the English spelling is not the first candidate."""
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


def japanese_title(surface, reading, work=False):
    """A Japanese work title among the surfaces of a reading: mixed kana and
    something else (ドラゴンボールZ, ゲゲゲの鬼太郎, 東京リベンジャーズ).  A
    surface of only kana is the reading's own spelling.  A surface of only kanji
    is another language's name (羅馬 for ローマ), not the work's title, unless
    the reading is a work's (人魚姫 for The Little Mermaid)."""
    if surface.isascii() or surface == katakana(reading):
        return False
    kana = other = False
    for ch in surface:
        if "ぁ" <= ch <= "ゖ" or "ァ" <= ch <= "ヺ" or ch in "ー・":
            kana = True
        elif "㐀" <= ch <= "䶿" or "一" <= ch <= "鿿" or ch.isalnum() or ch in "!?&+-'.":
            other = True
    return other and (kana or work)


def hiragana(katakana_text):
    out = []
    for ch in katakana_text:
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
    parser.add_argument("--names", type=Path, action="append", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--wasei", type=Path, help="tools/data/wasei.tsv: never add these names")
    parser.add_argument("--penalty", type=int, default=1)
    parser.add_argument("--margin", type=int, default=100)
    parser.add_argument("--default-cost", type=int, default=15000)
    parser.add_argument("--titles", type=Path, help="tools/data/japanese-titles.tsv: Japanese titles before the name")
    parser.add_argument("--acronyms", type=Path, help="tools/data/acronyms.tsv (type b rows: reading and rank)")
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()

    data = args.mozc / "data/dictionary_oss"
    ids = {}
    for line in (data / "id.def").read_text(encoding="utf-8").splitlines():
        number, _, pos = line.partition(" ")
        ids.setdefault(pos, number)
    title_pos = int(ids[POS["other"]])  # 名詞,固有名詞,一般: an all-kanji work title's part of speech
    acronyms = []  # (shown, reading, rank) of the acronyms that read as Japanese words
    if args.acronyms:
        for line in args.acronyms.read_text(encoding="utf-8").splitlines():
            f = line.split("\t")
            if line.startswith("#") or len(f) < 6 or f[2] != "b":
                continue
            if not HIRAGANA.fullmatch(f[3]) or f[5] not in ("1", "2", "3"):
                raise SystemExit(f"bad acronym row: {line}")
            acronyms.append((f[1], f[3], int(f[5])))
    wasei = set()  # (reading variant, English word) that a wasei word merely looks like
    if args.wasei:
        for line in args.wasei.read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or "\t" not in line:
                continue
            katakana_text, english = line.split("\t")[:2]
            for reading in reading_variants.variants(hiragana(katakana_text)):
                wasei.add((reading, english.lower()))
                # A wasei compound (オフィスレディー -> office) must not put the
                # English word of one part (オフィス -> office) either.
                for n in range(2, len(reading)):
                    wasei.add((reading[:n], english.lower()))
    short_readings = len(args.names) > 1  # only the first (checked extra) file may use 2-kana readings
    # Readings that name a work: an all-kanji title (人魚姫 for The Little
    # Mermaid) counts as the Japanese title there, while a place name's kanji
    # (羅馬 for ローマ) must not move the English spelling.
    work_readings = set()
    for file_order, path in enumerate(args.names):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or not line.strip():
                continue
            f = line.split("\t")
            if len(f) < 5 or f[4] not in WORK_KINDS:
                continue
            for reading in f[3].split("|"):
                if not HIRAGANA.fullmatch(reading):
                    continue
                if len(reading) < (2 if short_readings and file_order == 0 else 3):
                    continue
                work_readings.add(reading)
                for variant in reading_variants.variants(reading):
                    if variant == reading or reading_variants.allowed(reading, variant):
                        work_readings.add(variant)
    wanted = {reading for _, reading, _ in acronyms}
    reading_entries = defaultdict(list)  # reading -> [(cost, lid, rid)] of Mozc's own entries, for the acronyms
    existing = set()
    katakana_entries = {}  # (reading, katakana) -> (lid, rid, cost)
    max_cost, min_cost = {}, {}
    name_max = {}  # reading -> cost of the dearest Japanese work title (mixed kana and kanji/letters)
    surface_costs = defaultdict(dict)  # reading -> surface -> cheapest cost
    for path in sorted(data.glob("dictionary*.txt")):
        if path.name == "dictionary14.txt":
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            f = line.split("\t")
            if len(f) < 5:
                continue
            reading, lid, rid, cost, surface = f[0], int(f[1]), int(f[2]), int(f[3]), f[4]
            existing.add((reading, surface))
            if reading in wanted:
                reading_entries[reading].append((cost, lid, rid))
            max_cost[reading] = max(max_cost.get(reading, 0), cost)
            min_cost[reading] = min(min_cost.get(reading, 1 << 30), cost)
            # A work's Japanese title (ドラゴンボールZ, 東京リベンジャーズ,
            # ゲゲゲの鬼太郎) must stay before the English spelling even when the
            # katakana reading of the name is a cheaper Mozc entry.  Do not
            # count a kana-only alternate spelling (アヴァター) or a kanji-only
            # name (羅馬 for ローマ): they would push the English spelling behind
            # all of them and move a place or brand name out of the first page.
            # An all-kanji title (人魚姫) counts when the reading names a work and
            # the surface is a general proper noun, not a person or place name.
            work = reading in work_readings and lid == title_pos
            if japanese_title(surface, reading, work):
                name_max[reading] = max(name_max.get(reading, 0), cost)
            surfaces = surface_costs[reading]
            surfaces[surface] = min(surfaces.get(surface, 1 << 30), cost)
            if surface == katakana(reading):  # the reading written in katakana, as the name is usually written
                old = katakana_entries.get((reading, surface))
                if old is None or cost < old[2]:
                    katakana_entries[(reading, surface)] = (lid, rid, cost)

    # (reading, spelling) -> (file order, row order, variant order, kind, is an old main spelling).
    # The first file given wins for the order of an identical spelling; variants of a spelling are
    # kept with it. A spelling that proper-nouns.tsv already had as a main spelling is "old": its
    # cost stays exactly what it was, so the first candidate of an existing reading does not move.
    wanted_names = {}
    file_order = 0
    for path in args.names:
        for row_order, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
            if line.startswith("#") or not line.strip():
                continue
            f = line.split("\t")
            if len(f) < 5:
                continue
            shown, readings, kind = f[0], f[3], f[4]
            variants = f[6].split("|") if len(f) > 6 and f[6] else []
            for reading in readings.split("|"):
                if not HIRAGANA.fullmatch(reading):
                    continue
                # Long vowels are typed in more than one way (でんそー / でんそう /
                # でんそ, あいでぃる / あいでぃーる).  Only the explicit ALLOWED pairs
                # are added: dropping a long vowel can hit an unrelated Japanese
                # word (おおさか -> おさか, あたーる -> あたる).
                expanded = [reading]
                for variant in sorted(reading_variants.variants(reading)):
                    if variant == reading or variant not in max_cost:
                        continue
                    if reading_variants.allowed(reading, variant):
                        expanded.append(variant)
                for expanded_reading in expanded:
                    if len(expanded_reading) < (2 if short_readings and file_order == 0 else 3):
                        continue
                    for variant_order, spelling in enumerate([shown] + variants):
                        spelling = spelling.strip()
                        if (not spelling or (expanded_reading, spelling) in existing
                                or (expanded_reading, spelling.lower()) in wasei):
                            continue
                        key = (expanded_reading, spelling)
                        order = (file_order, row_order, variant_order)
                        # A checked row (the first file, proper-noun-extra.tsv) may replace the cost of
                        # the generated row: it is the spelling to put right after the katakana word.
                        is_old = file_order > 0 and variant_order == 0 and expanded_reading == reading
                        if key not in wanted_names:
                            wanted_names[key] = order + (kind, is_old, file_order == 0)
                        else:
                            current = wanted_names[key]
                            wanted_names[key] = (min(order, current[:3]) + (kind, current[4] or is_old,
                                                                          current[5] or file_order == 0))
        file_order += 1

    # Old main spellings keep their cost (all old names of a reading had the same cost). A new
    # spelling goes after them, and the other official spellings (variants) after the main one.
    by_reading = defaultdict(list)
    for (reading, spelling), info in wanted_names.items():
        by_reading[reading].append((info[:3], spelling, info[4], info[5]))
    entries = {}
    for reading, spellings in by_reading.items():
        kata = katakana_entries.get((reading, katakana(reading)))
        if kata and kata[2] <= min_cost[reading]:  # the katakana word is Mozc's first choice for the reading
            base = kata[2] + args.penalty
        elif kata:  # also a Japanese word (たいら: 平, Tyla is タイラ): the name stays behind all of them
            base = max_cost[reading] + args.margin
        else:
            if reading not in max_cost and len(reading) < 4:
                continue  # a short reading no word has: the name could win over kana of other words
            base = max_cost[reading] + args.margin if reading in max_cost else args.default_cost
        has_old = any(old for _, _, old, _ in spellings)
        # A new spelling goes right after the katakana word when Mozc has one, even when another
        # Japanese word is cheaper (ないき: 無い気, ない気, ナイキ, Nike). An old spelling keeps the
        # cost it had when that is already within the first 10; only an old spelling outside it
        # (Nike) moves. This keeps the old candidates where they were.
        new_base = kata[2] + args.penalty if kata else base
        old_rank = sum(1 for cost in surface_costs.get(reading, {}).values() if cost < base)
        move_old = old_rank > 9 and any(old and checked for _, _, old, checked in spellings)
        main_base = new_base if move_old else base
        main_base = within_first_page(reading, main_base, surface_costs)
        is_work = any(wanted_names[(reading, spelling)][3] in WORK_KINDS
                      for _, spelling, _, _ in spellings)
        if is_work and reading in name_max:  # the Japanese title stays first
            main_base = max(main_base, name_max[reading] + args.penalty)
        new_index = 1 if has_old else 0
        for _, spelling, old, _ in sorted(spellings):
            if old:
                cost = main_base
            else:
                cost = main_base + new_index
                new_index += 1
            if kata:
                lid, rid = kata[0], kata[1]
            else:
                kind = wanted_names[(reading, spelling)][3]
                lid = rid = int(ids[POS[KIND_POS.get(kind, "other")]])
            entries[(reading, spelling)] = (lid, rid, cost)

    # The Japanese title of a name whose reading Mozc does not have as one word
    # (ゲゲゲの鬼太郎): Mozc writes it from smaller words, which lose to the
    # name's one entry. It goes just before the cheapest spelling of the reading.
    if args.titles:
        for line in args.titles.read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or "\t" not in line:
                continue
            reading, title = line.split("\t")[:2]
            costs = [cost for (r, _), (_, _, cost) in entries.items() if r == reading]
            if costs and (reading, title) not in existing:
                entries[(reading, title)] = (title_pos, title_pos, max(0, min(costs) - 1))

    for shown, reading, rank in acronyms:
        if (reading, shown) in existing:
            continue
        found = sorted(reading_entries.get(reading, []))
        if not found:
            pos = int(ids[POS["other"]])
            entries[(reading, shown)] = (pos, pos, args.default_cost)
            continue
        costs = [c for c, _, _ in found]
        if rank == 1:  # cheaper than every Mozc entry of the reading: the first candidate
            cost = max(0, costs[0] - 1)
        elif len(costs) >= rank:  # between the (rank - 1)th and the rank-th cheapest
            lo, hi = costs[rank - 2], costs[rank - 1]
            cost = lo + (hi - lo) // 2 if hi - lo >= 2 else hi
        else:
            cost = costs[-1] + 100
        entries[(reading, shown)] = (found[0][1], found[0][2], cost)

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
