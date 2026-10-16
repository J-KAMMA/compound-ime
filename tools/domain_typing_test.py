"""Builds the domain typing tests (分野の打ち込み試験): sentences of programming
and crypto documents written in romaji, to type into the IME and compare with
the original text.

  python tools/domain_typing_test.py --sentences out/sentences.jsonl --table <romanji-hiragana.tsv> \
      --out-dir out/tests [--prog 300] [--crypto 200] [--seed 20261015]

Input is sentences.jsonl of tools/zenz-finetune/domain_text.py; only sentences
of documents set aside for the test (split "test", never used for training)
are read. A sentence is used when it is 10 to 45 characters, ends with 。, and
is made only of kanji, kana, ー、。 and English words of letters (git, npm,
Python, DeFi, NFT ...; at most 3 words, no digits or symbols). Japanese parts
are read with SudachiPy and written in the base romaji style
(tools/romaji_variants.py); the English words are typed as they are, in lower
case, and expected as they are in the document. A sentence whose romaji does
not read back to the same kana is left out, and so is any test sentence of
tests/conversion (TestExclusion). Up to 3 sentences per document, about 40%
with English words. The quota of each source is in
tools/zenz-finetune/domain_sources.json (a source with too few sentences hands
its quota to the others of the same field).

Output (--out-dir): domain-prog.tsv and domain-crypto.tsv, each line
romaji<TAB>original<TAB>source name; the header lines (#) tell the sources,
versions and licenses.
"""
import argparse
import json
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "zenz-finetune"))
sys.path.insert(0, str(HERE))
import build_dataset as bd  # noqa: E402
import domain_text as dt  # noqa: E402
import romaji_variants as rv  # noqa: E402

JA_ONLY = re.compile(r"[一-龯々〆ヵヶぁ-ゖァ-ヺー、。]+")
EN_WORD = re.compile(r"[A-Za-z]{2,20}")
CAMEL = re.compile(r"[A-Z][a-z]+[A-Z][a-z]+")
FIELDS = {"prog": "プログラミング", "crypto": "仮想通貨"}


def english_ok(word: str, brands: set) -> bool:
    if not EN_WORD.fullmatch(word):
        return False
    return (word in (word.lower(), word.upper(), word.capitalize()) or word.lower() in brands
            or bool(CAMEL.fullmatch(word)))


def typing_line(text, reader, table, rev, brands):
    """(ローマ字, 読みの目印) か、試験に使えない文なら None。"""
    if not (10 <= len(text) <= 45) or not text.endswith("。"):
        return None
    pieces = dt.pieces_of(text)
    if not pieces or sum(1 for kind, _ in pieces if kind == "en") > 3:
        return None
    raw, key = "", ""
    for kind, part in pieces:
        if kind == "en":
            if not english_ok(part, brands):
                return None
            raw += part.lower()
            key += part.lower()
            continue
        if not JA_ONLY.fullmatch(part):
            return None
        tokens = reader.analyze(part)
        if not tokens:
            return None
        kana = bd.to_hiragana("".join(t.reading for t in tokens))
        written = rv.write(kana, "base", rev)
        if not written or rv.to_kana(written, table) != kana:
            return None
        raw += written
        key += kana
    return raw, key


def load_brands(repo: Path) -> set:
    path = repo / "tools" / "data" / "brand-casing.tsv"
    brands = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#") and "\t" in line:
                brands.add(line.split("\t")[0].lower())
    return brands


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sentences", required=True)
    ap.add_argument("--table", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--config", default=str(HERE / "zenz-finetune" / "domain_sources.json"))
    ap.add_argument("--prog", type=int, default=300)
    ap.add_argument("--crypto", type=int, default=200)
    ap.add_argument("--english-share", type=float, default=0.4, help="英字の言葉を含む文の割合のねらい")
    ap.add_argument("--per-doc", type=int, default=3, help="1つの文書から取る文の上限")
    ap.add_argument("--seed", type=int, default=20261015)
    ap.add_argument("--repo", default=str(HERE.parent))
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    sources = {s["name"]: s for s in config["sources"]}
    table = rv.load_table(args.table)
    rev = rv.reverse_table(table)
    reader = bd.SudachiReader("core")
    brands = load_brands(Path(args.repo))
    exclusion = bd.TestExclusion(Path(args.repo) / "tests/conversion", bd.load_romaji_table(Path(args.table)),
                                 ignore=("domain-prog.tsv", "domain-crypto.tsv"), ascii_containment=False)
    rng = random.Random(args.seed)

    # 出典ごとに、使える文を集める（英字入りと日本語だけに分けて、文書ごとの数を制限）
    pool = {name: {"eng": [], "ja": []} for name in sources}
    rows = [json.loads(line) for line in open(args.sentences, encoding="utf-8")]
    rows = [r for r in rows if r["split"] == "test" and r["source"] in sources]
    rng.shuffle(rows)
    seen_text = set()
    stats = {name: {"candidates": 0, "usable": 0} for name in sources}
    for row in rows:
        name = row["source"]
        stats[name]["candidates"] += 1
        if row["text"] in seen_text:
            continue
        made = typing_line(row["text"], reader, table, rev, brands)
        if made is None or exclusion.blocked(row["text"], [made[1]]):
            continue
        seen_text.add(row["text"])
        stats[name]["usable"] += 1
        has_english = bool(re.search(r"[A-Za-z]", row["text"]))
        pool[name]["eng" if has_english else "ja"].append((row["doc"], made[0], row["text"]))

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for field, total in (("prog", args.prog), ("crypto", args.crypto)):
        names = [n for n, s in sources.items() if s["domain"] == field]
        quota = {n: sources[n]["test_quota"] for n in names}
        scale = total / max(1, sum(quota.values()))
        quota = {n: int(round(q * scale)) for n, q in quota.items()}
        taken = {n: [] for n in names}

        def pick(name, want):
            """出典 name から want 文。英字入りを english_share ぐらい、文書ごとの上限つき。"""
            per_doc, got = {}, []

            def take(kind, upto):
                for doc, raw, text in pool[name][kind]:
                    if len(got) >= upto:
                        return
                    if per_doc.get(doc, 0) >= args.per_doc or any(g[2] == text for g in got):
                        continue
                    per_doc[doc] = per_doc.get(doc, 0) + 1
                    got.append((doc, raw, text, kind == "eng"))

            take("eng", int(round(want * args.english_share)))
            take("ja", want)
            take("eng", want)
            return got

        for name in names:
            taken[name] = pick(name, quota[name])
        # 足りない出典の分は、まだ余りのある同じ分野の出典で補う
        shortage = total - sum(len(v) for v in taken.values())
        for name in sorted(names, key=lambda n: -len(pool[n]["ja"]) - len(pool[n]["eng"])):
            if shortage <= 0:
                break
            more = pick(name, len(taken[name]) + shortage)
            shortage -= len(more) - len(taken[name])
            taken[name] = more
        lines = []
        for name in names:
            lines += [(raw, text, name) for _, raw, text, _ in taken[name]]
        rng.shuffle(lines)
        header = [f"# 分野の打ち込み試験（{FIELDS[field]}）。文書の文を、SudachiPy の読みからローマ字にしたもの。"
                  f"英字の言葉（git、npm、Python、DeFi、NFT など）は小文字で打ち、元の文の英字のとおりに出ることを期待する。",
                  "# 列: ローマ字<TAB>元の文<TAB>出典名。tools/zenz-finetune/domain_text.py と tools/domain_typing_test.py で作成。"
                  "試験用に分けた文書の文だけ（練習問題には使わない）。出典と利用条件:"]
        for name in (n for n in names if taken[n]):
            s = sources[name]
            header.append(f"# - {name}: {s['title']}（{s['repo']} コミット {s['commit']}）。{s['license']}。"
                          f"{s['attribution']}。{len(taken[name])} 文")
        text = "\n".join(header) + "\n" + "\n".join(f"{raw}\t{sentence}\t{name}" for raw, sentence, name in lines) + "\n"
        (out_dir / f"domain-{field}.tsv").write_text(text, encoding="utf-8", newline="\n")
        print(f"domain-{field}.tsv: {len(lines)} 文（" + "、".join(f"{n} {len(taken[n])}" for n in names) + "）")
    print("使える文:", json.dumps(stats, ensure_ascii=False))


if __name__ == "__main__":
    main()
