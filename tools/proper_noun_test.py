"""Builds the proper noun tests (大文字で始まる英字の固有名詞の試験).

  python tools/proper_noun_test.py --table <romanji-hiragana.tsv> --out-dir tests/conversion \
      [--names tools/data/proper-nouns.tsv] [--sample 300] [--seed 20261021]

Needs SudachiPy (sudachipy==0.6.11, sudachidict-core==20260428) to read the Japanese parts of the
sentences. Writes two files:

proper-nouns.tsv, sentences: ローマ字<TAB>期待する文<TAB>分野<TAB>名前<TAB>由来
  A short Japanese sentence with one name in it. The name is typed in lower case with no spaces
  (githubwo, newyorkni), as it is typed, and the sentence is expected as written with the name in its
  official spelling. 由来: hand = tools/data/proper-noun-test-names.tsv (written by hand, without
  looking at Wikidata), hand-ambiguous = such a name that is also a common English word (queen, steam:
  the word as typed is meant to stay first, so these are expected to miss in the sentences),
  sample = a random sample of tools/data/proper-nouns.tsv (names the data claims).

proper-nouns-cand.tsv, candidates: ローマ字<TAB>期待する候補<TAB>方式<TAB>分野<TAB>由来
  One word typed and converted with the space key; the official spelling is expected among the
  candidates. 方式: typed = the name typed in English letters (github), kana = its Japanese reading
  (ぎっとはぶ is not what is typed: the katakana reading of the name, in hiragana, as romaji),
  kana-kunrei = the same reading in kunrei style (si, ti, tu, hu), kana-small-x = small kana typed
  with x (fuxa for ふぁ). info-capital, info-allcaps and info-hyphen (Github, GITHUB, coca-cola) show
  how the typing varies and are not in the totals.

The sentences' kanji and kana are what Sudachi reads; a sentence may come out different from the
expected one in kanji or kana alone, so the score counts both the sentences that are exactly as
expected and the sentences that have the name right (tools/score_proper_nouns.py).
"""
import argparse
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "zenz-finetune"))
import build_dataset as bd  # noqa: E402
import romaji_variants as rv  # noqa: E402

# (before the name, after the name). kinds: which kinds of name it suits.
ANY = ("company", "product", "software", "work", "person", "place")
TEMPLATES = [
    ("今日は", "について調べました。", ("company", "product", "software", "work", "person", "place")),
    ("昨日、", "のニュースを見ました。", ("company", "product", "software", "work", "person", "place")),
    ("友達が", "を使っています。", ("product", "software")),
    ("私は", "が好きです。", ("company", "product", "software", "work", "person", "place")),
    ("", "は世界中で知られています。", ("company", "product", "software", "work", "person", "place")),
    ("先週、", "の話をしました。", ("company", "product", "software", "work", "person", "place")),
    ("あの人は", "で働いています。", ("company",)),
    ("毎日", "を使って仕事をしています。", ("product", "software")),
    ("", "の公式サイトを確認してください。", ("company", "product", "software", "work")),
    ("妹は", "のファンです。", ("company", "product", "work", "person")),
    ("彼は", "に詳しいです。", ("company", "product", "software", "work", "person", "place")),
    ("新しい", "の機能を試しました。", ("product", "software")),
    ("来月", "に行く予定です。", ("place",)),
    ("週末は", "で過ごしました。", ("place",)),
    ("この本は", "について書かれています。", ("company", "product", "software", "work", "person", "place")),
    ("子供のころから", "に憧れていました。", ("company", "work", "person", "place")),
    ("駅で", "の広告を見つけました。", ("company", "product", "work")),
    ("会議で", "の事例を紹介しました。", ("company", "product", "software")),
    ("", "のことを考えると楽しくなります。", ("company", "product", "software", "work", "person", "place")),
    ("私の兄は", "を勉強しています。", ("software",)),
]
# Kinds of tools/fetch_wikidata_names.py files, as the hand-written kinds above.
KIND_OF = {"business": "company", "brand": "company", "airline": "company", "tvnetwork": "company",
           "newspaper": "company", "university": "company", "sportsteam": "company", "museum": "company",
           "software": "software", "app": "software", "proglang": "software", "os": "software",
           "website": "product", "videogame": "work", "carmodel": "product", "film": "work",
           "tvseries": "work", "album": "work", "band": "work", "novel": "work", "character": "work",
           "country": "place", "usstate": "place", "city": "place", "island": "place", "mountain": "place",
           "river": "place", "lake": "place", "people": "person"}


def hira(katakana):
    return "".join("ゔ" if c == "ヴ" else chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in katakana)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--table", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--names", type=Path)
    ap.add_argument("--hand", type=Path, default=HERE / "data" / "proper-noun-test-names.tsv")
    ap.add_argument("--common-words", type=Path,
                    help="common-words.txt of tools/build_english_lexicon.py: a hand-written name that is also a "
                         "common English word (queen, steam) is marked hand-ambiguous")
    ap.add_argument("--sample", type=int, default=300)
    ap.add_argument("--seed", type=int, default=20261021)
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    rng = random.Random(args.seed)
    table = rv.load_table(args.table)
    rev = rv.reverse_table(table)
    reader = bd.SudachiReader("core")

    def japanese_romaji(text):
        if not text:
            return ""
        tokens = reader.analyze(text)
        if not tokens:
            raise SystemExit("cannot read " + text)
        kana = bd.to_hiragana("".join(t.reading for t in tokens))
        out = rv.write(kana, "base", rev)
        if out is None or rv.to_kana(out, table) != kana:
            raise SystemExit("cannot write " + text)
        return out

    reading_cache = {}

    def kana_typing(reading, style):
        key = (reading, style)
        if key not in reading_cache:
            out = rv.write(reading, style, rev)
            reading_cache[key] = out if out and rv.to_kana(out, table) == reading else None
        return reading_cache[key]

    # names: (shown, typed, katakana reading or "", kind, origin)
    names = []
    for line in args.hand.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            shown, kata, kind = line.split("\t")
            names.append((shown, re.sub(r"[^a-z0-9]", "", shown.lower()), hira(kata), kind, "hand"))
    if args.common_words:
        common = set(args.common_words.read_text().split())
        names = [(n[0], n[1], n[2], n[3], "hand-ambiguous" if n[1] in common else n[4]) for n in names]
    hand_shown = {n[0] for n in names}
    if args.names:
        pool = []
        for line in args.names.read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or not line:
                continue
            f = line.split("\t")
            shown, typed, readings, kind = f[0], f[1], f[3], KIND_OF.get(f[4])
            if shown in hand_shown or kind is None or int(f[5]) < 25:
                continue
            pool.append((shown, typed.replace(" ", ""), readings.split("|")[0], kind, "sample"))
        rng.shuffle(pool)
        by_kind = {}
        for item in pool:
            by_kind.setdefault(item[3], []).append(item)
        for kind, items in by_kind.items():
            names += items[: max(1, args.sample // len(by_kind))]

    sentences, cands = [], []
    for shown, typed, reading, kind, origin in names:
        # sentences: the name typed; hand names get 2 templates, sampled names 1
        if typed and shown.isascii():
            suited = [t for t in TEMPLATES if kind in t[2]]
            for before, after, _ in rng.sample(suited, 2 if origin.startswith("hand") else 1):
                raw = japanese_romaji(before) + typed + japanese_romaji(after)
                sentences.append((raw, before + shown + after, kind, shown, origin))
            cands.append((typed, shown, "typed", kind, origin))
            # how the typing varies (for information; not in the totals): a capital first letter (Github),
            # all capitals (GITHUB), and a hyphen kept where the name has one (coca-cola).
            if origin.startswith("hand"):
                cands.append((typed.capitalize(), shown, "info-capital", kind, origin))
                cands.append((typed.upper(), shown, "info-allcaps", kind, origin))
                if "-" in shown:
                    cands.append((re.sub(r"[^a-z0-9-]", "", shown.lower()), shown, "info-hyphen", kind, origin))
        if reading and re.fullmatch(r"[ぁ-ゖー]{3,}", reading):
            for style, mode in (("base", "kana"), ("kunrei", "kana-kunrei"), ("small_x", "kana-small-x")):
                raw = kana_typing(reading, style)
                if raw and (style == "base" or raw != kana_typing(reading, "base")):
                    cands.append((raw, shown, mode, kind, origin))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    with (args.out_dir / "proper-nouns.tsv").open("w", encoding="utf-8", newline="\n") as out:
        out.write("# 固有名詞の試験（文）。tools/proper_noun_test.py で作成。列: ローマ字<TAB>期待する文<TAB>分野<TAB>名前<TAB>由来（hand: 手で書いた名前、sample: tools/data/proper-nouns.tsv からの無作為の標本）\n")
        for row in sentences:
            out.write("\t".join(row) + "\n")
    with (args.out_dir / "proper-nouns-cand.tsv").open("w", encoding="utf-8", newline="\n") as out:
        out.write("# 固有名詞の試験（候補）。tools/proper_noun_test.py で作成。列: ローマ字<TAB>期待する候補<TAB>方式（typed: 英字で打つ、kana: 読みを打つ、kana-kunrei: 訓令式、kana-small-x: 小さいかなを x で）<TAB>分野<TAB>由来\n")
        for row in cands:
            out.write("\t".join(row) + "\n")
    print("sentences", len(sentences), "candidates", len(cands))


if __name__ == "__main__":
    main()
