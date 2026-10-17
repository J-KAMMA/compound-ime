#!/usr/bin/env python3
"""練習問題が、試験の文を含まず、出典・版・利用条件・件数が目録（manifest.json）に出ているかを確かめる。

  python check_dataset.py probe  --out probe/ [--repo .]
      試験の文（tests/conversion/）を、わざと各出典の材料に混ぜるための入れ物を作る:
        probe/probe-wiki.txt        ウィキペディアの記事の形（build_dataset.py --wiki に足す）
        probe/probe-sentences.jsonl 文の一覧の形（domain・tatoeba・persona の3つの出典の名前で。cat で足す）
      混ぜた文が1つも練習問題に残らなければ、試験の文との重なりの除外が全部の出典に効いている。

  python check_dataset.py verify --data dataset/ --repo . --romaji-table romanji-hiragana.tsv \
      [--probe probe/] [--expect-sources wiki,tatoeba,persona,domain,synthetic]
      dataset/ の train（部品でも可）と valid の全部の問題について、問いから左右の文脈と正解をつなぎ直した文が、
      試験の文と同じか含むかを調べる（文全体を問う種類は0件でなければならない）。--probe があれば、混ぜた試験の文
      が残っていないことと、出典ごとに混ぜた数のうち何文が除かれたかを表示する。manifest.json に出典・版・利用条件・
      件数があることも確かめる。問題があれば終了コード 1。
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_dataset as bd  # noqa: E402

JAPANESE = re.compile(r"[ぁ-ゖァ-ヺ一-鿿]")
SENT_SHAPE = re.compile(r"^[ぁ-ゖァ-ヺー一-鿿々〆ヶ、。「」・！？]+$")


def test_sentences(repo: Path):
    """tests/conversion/ の、日本語の文（表記）を集める。出所の名前つき。"""
    out = []
    test_dir = repo / "tests" / "conversion"
    for path in sorted(test_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for item in (data["items"] if isinstance(data, dict) else data):
            if item.get("intended"):
                out.append((path.name, item["intended"]))
    for name, column in (("context.tsv", 1), ("colloquial.tsv", 1), ("wiki-typing.tsv", 1), ("domain-prog.tsv", 1),
                         ("domain-crypto.tsv", 1), ("expected-windows-139.tsv", 2), ("variants.tsv", 3)):
        path = test_dir / name
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                cols = line.split("\t")
                if not line.startswith("#") and len(cols) > column and cols[column]:
                    out.append((name, cols[column]))
    return out


def make_probe(repo: Path, out: Path, per_file: int = 60):
    out.mkdir(parents=True, exist_ok=True)
    sentences, counts = [], {}
    for name, text in test_sentences(repo):
        text = text.strip()
        if not (6 <= len(text) <= 50) or not JAPANESE.search(text):
            continue
        if not SENT_SHAPE.match(re.sub(r"[。！？]+$", "", text) + "。"):
            continue
        counts[name] = counts.get(name, 0) + 1
        if counts[name] > per_file:
            continue
        sentences.append((name, re.sub(r"[。！？]+$", "", text) + "。"))
    # ウィキペディアの記事の形: 5文ずつ
    articles = []
    for i in range(0, len(sentences), 5):
        chunk = sentences[i:i + 5]
        articles.append(f"試験の文{i // 5}\n" + "".join(t for _, t in chunk))
    (out / "probe-wiki.txt").write_text("\n\n".join(articles) + "\n", encoding="utf-8", newline="\n")
    rows = []
    for i, (name, text) in enumerate(sentences):
        for source in ("mdn", "tatoeba", "persona"):
            rows.append({"source": source, "doc": f"probe:{source}:{i}", "split": "train", "text": text,
                         "prev": sentences[i - 1][1] if i and source == "persona" else ""})
    with open(out / "probe-sentences.jsonl", "w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    (out / "probe.json").write_text(json.dumps({"sentences": len(sentences), "by_file": counts,
                                                  "texts": [t for _, t in sentences]}, ensure_ascii=False) + "\n",
                                    encoding="utf-8")
    print(f"probe: 試験の文 {len(sentences)} 文（ファイル別 {counts}）を、wiki 記事 {len(articles)} と文の一覧 {len(rows)} 行にしました")


def read_records(path: Path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def rebuild(record: dict) -> str:
    """問いの左の文脈・正解・右の文脈をつなぎ直した文（文脈は前後40文字までの切り取り）。"""
    head = record["prompt"].split(bd.TAG_INPUT, 1)[0]
    left_part, right = head.split(bd.TAG_RIGHT, 1) if bd.TAG_RIGHT in head else (head, "")
    left = left_part.split(bd.TAG_LEFT, 1)[1] if bd.TAG_LEFT in left_part else ""
    return left + record["output"] + right



def verify(args) -> int:
    repo, data = Path(args.repo), Path(args.data)
    manifest = json.loads((data / "manifest.json").read_text(encoding="utf-8"))
    problems = []
    exclusion = bd.TestExclusion(repo / "tests" / "conversion", bd.load_romaji_table(Path(args.romaji_table)),
                                 extra_files=args.extra_test, ascii_containment=False)
    probe_index, probe_total = None, 0
    if args.probe:
        probe = json.loads((Path(args.probe) / "probe.json").read_text(encoding="utf-8"))
        probe_total = len(probe["texts"])
        probe_index = bd.SubstringIndex(bd.norm_surface(t) for t in probe["texts"] if len(bd.norm_surface(t)) >= 4)
        probe_exact = {bd.norm_surface(t) for t in probe["texts"]}
    files = [data / f["name"] for f in manifest["train_files"]] + [data / "valid.jsonl"]
    whole_kinds = ("_whole", "_context")   # homophone・mixed_english は文の一部の問題も含むので除く
    total = hits_whole = hits_other = probe_hits = 0
    examples = []
    per_kind = {}
    for path in files:
        for record in read_records(path):
            total += 1
            per_kind[record["kind"]] = per_kind.get(record["kind"], 0) + 1
            text = rebuild(record)
            whole = record["kind"].endswith(whole_kinds)
            if probe_index is not None:
                norm = bd.norm_surface(text)
                if norm in probe_exact or probe_index.find(norm):
                    probe_hits += 1
                    if len(examples) < 5:
                        examples.append(("probe", record["kind"], text))
            reason = exclusion.blocked(record["output"] if whole else text, [])
            if reason:
                if whole:
                    hits_whole += 1
                    if len(examples) < 10:
                        examples.append((reason, record["kind"], text))
                else:
                    hits_other += 1
    print(f"確かめた問題 {total}（部品 {len(files) - 1} 個＋確かめ用）")
    print(f"文全体を問う種類で試験の文と重なった問題: {hits_whole}（0 でなければならない）")
    print(f"文の一部を問う種類で、つなぎ直した文が試験の文と重なった問題: {hits_other}（短い文の切り取りが偶然同じになったもの。参考）")
    if args.probe:
        print(f"混ぜた試験の文 {probe_total} 文のうち、練習問題に残ったもの: {probe_hits}（0 でなければならない）")
        print("除かれた文の数（manifest）:", manifest["test_exclusion"]["excluded_sentences"])
    for item in examples:
        print("  例:", item)
    if hits_whole:
        problems.append("文全体を問う種類に、試験の文と重なる問題が残っている")
    if probe_hits:
        problems.append("混ぜた試験の文が練習問題に残っている")
    # 目録の確認
    expect = [s for s in args.expect_sources.split(",") if s]
    for source in expect:
        row = manifest["mix_result"].get(source)
        if not row or row["train"] <= 0:
            problems.append(f"出典 {source} の問題が作れていない")
        else:
            print(f"  出典 {source}: 予定 {row['share_planned']:.1%} → 実際 {row['share_actual']:.1%}（{row['train']} 問）、足りない {row['short']}")
    ids = {s["id"] for s in (manifest.get("domain") or {}).get("sources", [])}
    for source in manifest.get("domain", {}).get("sources", []):
        for field in ("commit", "license", "license_url", "attribution"):
            if not source.get(field):
                problems.append(f"manifest の {source['id']} に {field} がない")
    for needed in ("tatoeba", "persona"):
        if needed in expect and needed not in ids:
            problems.append(f"manifest の domain.sources に {needed} がない")
    for field in ("counts", "mix_result", "test_exclusion", "sources", "train_files", "settings"):
        if field not in manifest:
            problems.append(f"manifest に {field} がない")
    if not manifest["test_exclusion"]["files"]:
        problems.append("manifest に試験のファイルの一覧がない")
    print("manifest の試験のファイル:", [f["name"] for f in manifest["test_exclusion"]["files"]],
          " 読めなかったファイル:", manifest["test_exclusion"]["keys"].get("files_unhandled"))
    for problem in problems:
        print("問題:", problem)
    print("確認: よし" if not problems else "確認: 問題があります")
    return 1 if problems else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("probe")
    p.add_argument("--out", required=True)
    p.add_argument("--repo", default=str(Path(__file__).resolve().parent.parent.parent))
    v = sub.add_parser("verify")
    v.add_argument("--data", required=True)
    v.add_argument("--repo", default=str(Path(__file__).resolve().parent.parent.parent))
    v.add_argument("--romaji-table", required=True)
    v.add_argument("--probe", default="")
    v.add_argument("--expect-sources", default="")
    v.add_argument("--extra-test", nargs="*", default=[])
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if args.command == "probe":
        make_probe(Path(args.repo), Path(args.out))
        return 0
    return verify(args)


if __name__ == "__main__":
    sys.exit(main())
