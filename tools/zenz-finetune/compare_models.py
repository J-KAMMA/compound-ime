#!/usr/bin/env python3
"""2つの人工知能（v5 と v6 など）で流した一括試験の結果（linux-test.yml の成果物 linux-results）を、同じ組の
試験ごとに比べる。

  gh run download <v5 の run> -n linux-results -D v5
  gh run download <v6 の run> -n linux-results -D v6
  python tools/zenz-finetune/compare_models.py v5 v6 [--tests tests/conversion] [--show 5]

結果の .tsv（入力<TAB>文節<TAB>確定）のうち、正解の表が分かるもの（tests/conversion/ の同じ名前の .json の
items＝romaji→intended・alternatives、または同じ名前の .tsv の 1列目＝ローマ字・2列目＝正解）を採点し、
正解の数・良くなった文・悪くなった文・変わった文の数を並べる。正解の表がない結果は、変わった文の数だけ。
確かめ用（holdout/）は「学習にも調整にも使わない」決まりなので、最後の確認として別の段に出す（ここを見て
設定を変え、もう一度比べることはしない）。完全一致で数える（表記ゆれを許す採点は、各組の *-score.txt を見る）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load_results(path: Path) -> dict:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        cols = line.split("\t")
        if len(cols) >= 3:
            out[cols[0]] = cols[2]
    return out


def load_answers(tests: Path, stem: str):
    for path in (tests / f"{stem}.json", tests / "holdout" / f"{stem}.json"):
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            items = data["items"] if isinstance(data, dict) else data
            return path, {i["romaji"]: [i["intended"]] + list(i.get("alternatives") or []) for i in items if i.get("romaji")}
    path = tests / f"{stem}.tsv"
    if path.exists():
        answers = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            cols = line.split("\t")
            if line.startswith("#") or len(cols) < 2 or not cols[0]:
                continue
            answers[cols[0]] = [cols[1]] + (cols[4].split("|") if stem == "variants" and len(cols) > 4 else [])
        return path, answers
    return None, None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("base")
    ap.add_argument("new")
    ap.add_argument("--tests", default=str(Path(__file__).resolve().parents[2] / "tests" / "conversion"))
    ap.add_argument("--show", type=int, default=5, help="良くなった・悪くなった文の例をいくつ出すか")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    base_dir, new_dir, tests = Path(args.base), Path(args.new), Path(args.tests)
    rows, holdout_rows, total = [], [], [0, 0]
    for path in sorted(new_dir.glob("*.tsv")):
        other = base_dir / path.name
        if not other.exists():
            continue
        base, new = load_results(other), load_results(path)
        keys = [k for k in new if k in base]
        changed = sum(1 for k in keys if base[k] != new[k])
        answer_file, answers = load_answers(tests, path.stem)
        if not answers:
            rows.append((path.stem, None, None, None, None, changed, len(keys), [], []))
            continue
        scored = [k for k in keys if k in answers]
        ok_base = {k for k in scored if base[k] in answers[k]}
        ok_new = {k for k in scored if new[k] in answers[k]}
        better = [(k, base[k], new[k]) for k in scored if k in ok_new and k not in ok_base]
        worse = [(k, base[k], new[k], answers[k][0]) for k in scored if k in ok_base and k not in ok_new]
        row = (path.stem, len(scored), len(ok_base), len(ok_new), len(ok_new) - len(ok_base), changed, len(keys),
               better, worse)
        (holdout_rows if "holdout" in answer_file.parts else rows).append(row)
        if "holdout" not in answer_file.parts:
            total[0] += len(ok_base)
            total[1] += len(ok_new)

    def show(title, items):
        print(f"\n== {title}")
        print(f"{'試験':<28}{'採点した文':>8}{'基準':>8}{'新':>8}{'差':>7}{'変わった文':>10}")
        for stem, n, a, b, d, changed, keys, better, worse in items:
            if n is None:
                print(f"{stem:<28}{'-':>8}{'-':>8}{'-':>8}{'-':>7}{changed:>10}（正解の表なし、{keys} 文）")
                continue
            print(f"{stem:<28}{n:>8}{a:>8}{b:>8}{d:>+7}{changed:>10}")
            for k, x, y in better[:args.show]:
                print(f"    良: {k}  {x} → {y}")
            for k, x, y, want in worse[:args.show]:
                print(f"    悪: {k}  {x} → {y}（正解 {want}）")

    show("試験の組（調整に使ってよい）", rows)
    print(f"\n合計（確かめ用を除く、正解の表がある試験）: 基準 {total[0]} → 新 {total[1]}（{total[1] - total[0]:+d}）")
    if holdout_rows:
        show("確かめ用 holdout（最後の確認だけ。これを見て設定を変えない）", holdout_rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
