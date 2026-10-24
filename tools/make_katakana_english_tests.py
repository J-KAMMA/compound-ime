"""Builds the katakana-to-English tests (カタカナ語・作品名・企業名の英字の試験).

  python tools/make_katakana_english_tests.py --out-dir tests/conversion \
      [--pairs tools/data/katakana-english.tsv] [--wasei tools/data/wasei.tsv] \
      [--names tools/data/proper-nouns.tsv --extra tools/data/proper-noun-extra.tsv] \
      [--loanwords 500] [--works 320] [--brands 320] [--seed 20261024] [--mozc <mozc/src>]

Four files, each line ローマ字<TAB>期待する候補<TAB>種類<TAB>由来:

katakana-english.tsv  A katakana loanword's reading typed in kana (こーひー): the English word
                      (coffee) is expected among the first 10 candidates, after the katakana word.
katakana-wasei.tsv    A wasei word's reading (まんしょん): the English word it looks like (mansion)
                      must NOT be among the first 10 candidates (和製英語には付けない).
work-names.tsv        A work's kana reading (どらごんぼーる): the official English spelling
                      (Dragon Ball) is expected among the first 10, and official variants
                      (DRAGON BALL) too when the checked table gives them.
brand-names.tsv       A company or brand's kana reading (ないき): the official spelling (Nike),
                      its official variants (NIKE), and alternate readings (ないきー) are tested.

The rows come from the same tables the dictionary is built from: tools/data/katakana-english.tsv,
tools/data/proper-nouns.tsv and the checked tools/data/proper-noun-extra.tsv. The sample is
deterministic (--seed). A reading that cannot be written in the base romaji style is left out.
With --mozc, a reading whose cheapest Mozc entry is already English is left out too: in the test
the Japanese candidate has to be first (the English word comes after it).
"""
import argparse
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import romaji_variants as rv  # noqa: E402

WORK_KINDS = {"film", "filmseries", "tvseries", "tvprogram", "videogame", "videogameseries",
              "album", "band", "novel", "lightnovel", "manga", "anime", "comic", "character", "work"}
BRAND_KINDS = {"business", "brand", "company"}
KATAKANA = re.compile(r"[ァ-ヺー・=＝ヽヾ 　]+")
EXAMPLES = ["コンピューター", "スマートフォン", "アップデート", "データベース", "コーヒー", "カフェ",
            "インターネット", "システム", "サービス", "プロジェクト"]


def hira(katakana):
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


def write_reading(reading, table, rev):
    if not re.fullmatch(r"[ぁ-ゖー]{2,}", reading):
        return None
    raw = rv.write(reading, "base", rev)
    if raw and rv.to_kana(raw, table) == reading:
        return raw
    return None


def rows_of(path):
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            yield line.split("\t")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--pairs", type=Path, default=HERE / "data" / "katakana-english.tsv")
    ap.add_argument("--wasei", type=Path, default=HERE / "data" / "wasei.tsv")
    ap.add_argument("--names", type=Path, default=HERE / "data" / "proper-nouns.tsv")
    ap.add_argument("--extra", type=Path, default=HERE / "data" / "proper-noun-extra.tsv")
    ap.add_argument("--loanwords", type=int, default=500)
    ap.add_argument("--works", type=int, default=320)
    ap.add_argument("--brands", type=int, default=320)
    ap.add_argument("--seed", type=int, default=20261024)
    ap.add_argument("--table", type=Path, help="romanji-hiragana.tsv; the simple test table is used if not given")
    ap.add_argument("--mozc", type=Path, help="Mozc src: leave out readings whose cheapest entry is English")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if args.table:
        table = rv.load_table(args.table)
    else:
        import make_test_romaji_table as mtr
        table = dict((k, (v, pending)) for k, v, pending in mtr.rows())
    rev = rv.reverse_table(table)
    rng = random.Random(args.seed)

    japanese_first = None
    if args.mozc:
        japanese_first = {}  # reading -> True when Mozc's cheapest entry is not English letters
        for path in sorted((args.mozc / "data/dictionary_oss").glob("dictionary0*.txt")):
            for line in path.read_text(encoding="utf-8").splitlines():
                f = line.split("\t")
                if len(f) < 5:
                    continue
                cost, surface = int(f[3]), f[4]
                old = japanese_first.get(f[0])
                if old is None or cost < old[0]:
                    japanese_first[f[0]] = (cost, not surface.isascii())
        japanese_first = {reading: ok for reading, (_, ok) in japanese_first.items()}

    def usable(reading):
        return japanese_first is None or japanese_first.get(reading, False)

    # 1. Loanwords. The same katakana can have two English words (the pair table lists both).
    pairs = {}
    for f in rows_of(args.pairs):
        if len(f) >= 2:
            pairs.setdefault(f[0], [])
            if f[1] not in pairs[f[0]]:
                pairs[f[0]].append(f[1])
    wasei = {f[0]: f[1] for f in rows_of(args.wasei) if len(f) >= 2}
    loanwords = []
    seen = set()
    for katakana in EXAMPLES + sorted(pairs):
        if katakana in wasei or katakana in seen:
            continue
        raw = write_reading(hira(katakana), table, rev)
        if raw is None or not usable(hira(katakana)):
            continue
        for english in pairs[katakana]:
            if len(english) < 3:
                continue  # in, on: too short to be a useful loanword test
            loanwords.append((raw, english, "loanword", "example" if katakana in EXAMPLES else "data"))
            seen.add(katakana)
            break
        if len(loanwords) >= args.loanwords:
            break
    # a little shuffle, keeping the examples first
    head, tail = loanwords[:len(EXAMPLES)], loanwords[len(EXAMPLES):]
    rng.shuffle(tail)
    loanwords = head + tail[: max(0, args.loanwords - len(head))]

    wasei_rows = []
    for katakana, english in wasei.items():
        raw = write_reading(hira(katakana), table, rev)
        if raw:
            wasei_rows.append((raw, english, "wasei", "wasei"))
    wasei_rows.sort()

    # 2. Works and companies. The extra table's checked spellings come first, with their variants.
    names = []
    for origin, path in (("extra", args.extra), ("data", args.names)):
        for f in rows_of(path):
            if len(f) < 5:
                continue
            shown, readings, kind = f[0], f[3], f[4]
            variants = f[6].split("|") if len(f) > 6 and f[6] else []
            for reading in readings.split("|"):
                raw = write_reading(reading, table, rev)
                if raw and usable(reading):
                    names.append((raw, shown, kind, origin, reading))
                    for variant in variants:
                        if variant.strip():
                            names.append((raw, variant.strip(), kind, origin + "-variant", reading))

    def sample(kinds, count, label):
        # The checked extra table (the examples the job names) is always tested first. Of the
        # generated table, prefer readings that do not have many names, so the expected spelling
        # stays on one page.
        by_reading = {}
        for row in names:
            if row[2] in kinds and len(row[1]) >= 2 and re.fullmatch(r"[A-Za-z0-9À-ɏ .'&+\-!]+", row[1]):
                by_reading.setdefault(row[0], []).append(row)
        extra_rows, pool = [], []
        for reading, rows in by_reading.items():
            extra = [r for r in rows if r[3].startswith("extra")]
            data = [r for r in rows if r[3] == "data"]
            extra_rows.extend(extra)
            pool.extend(data[:2])
        rng.shuffle(pool)
        seen = set()
        out = []
        for row in extra_rows + pool:
            key = (row[0], row[1])
            if key in seen:
                continue
            seen.add(key)
            out.append(row)
            if len(out) >= count:
                break
        if len(out) < count:
            raise SystemExit(f"{label} の試験が {len(out)} 行しか作れません（{count} 行必要）")
        return out

    works = sample(WORK_KINDS, args.works, "作品")
    brands = sample(BRAND_KINDS, args.brands, "企業・ブランド")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "katakana-english.tsv": ("カタカナ語の英字（tools/make_katakana_english_tests.py。期待する候補が上位10個以内。"
                                 "列: ローマ字<TAB>期待する候補<TAB>種類<TAB>由来）", loanwords),
        "katakana-wasei.tsv": ("和製英語（期待する英単語が候補に出ないこと。列: ローマ字<TAB>出てはいけない候補<TAB>種類<TAB>由来）",
                               wasei_rows),
        "work-names.tsv": ("作品名の英字（期待する候補が上位10個以内。列: ローマ字<TAB>期待する候補<TAB>種類<TAB>由来）", works),
        "brand-names.tsv": ("企業・ブランド名の英字（期待する候補が上位10個以内。列: ローマ字<TAB>期待する候補<TAB>種類<TAB>由来）",
                            brands),
    }
    for name, (header, rows) in files.items():
        with (args.out_dir / name).open("w", encoding="utf-8", newline="\n") as out:
            out.write("# " + header + "\n")
            for row in rows:
                out.write("\t".join(row) + "\n")
        print(name, len(rows))


if __name__ == "__main__":
    main()
