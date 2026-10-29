#!/usr/bin/env python3
"""選び直しが次の変換に効くかの試験（組 l）の採点。

  python tools/score_learn_sticky.py <人工知能あり.tsv> <人工知能なし.tsv>

各行は tools/learn_sticky_convert.sh の出力（前の文の扱い、種類、選ぶ入力、選ぶ書き方、確かめる入力、望み、
学習の前、1回目、2回目、学習のあと）。学習の前に望みの書き方が入っておらず、2回とも選べた行（F キーの行は1回目）（数える行）のうち、
学習のあとの確定に望みの書き方が入っていない行があれば失敗にする。
"""
import sys
from collections import defaultdict
from pathlib import Path


def score(label, path):
    rows = [line.split("\t") for line in Path(path).read_text(encoding="utf-8").splitlines()]
    rows = [r for r in rows if len(r) >= 10]
    print(f"  {label}:")
    failed = 0
    groups = defaultdict(lambda: [0, 0, 0])  # 数える行、効いた行、数えない行
    for mode, kind, pick, value, check, want, before, first, second, after in (r[:10] for r in rows):
        g = groups[(mode, kind)]
        # F キーの行は2回目を押さずに確定するので、2回目は学習の結果（数える条件にしない）。
        picked_twice = value.startswith("KEY:") or want in second
        if want in before or want not in first or not picked_twice:
            g[2] += 1
            print(f"    数えない（{mode} {kind}）: {pick} → {value}: 学習の前 {before}、選んだ確定 {first} / {second}")
            continue
        g[0] += 1
        if want in after:
            g[1] += 1
        else:
            failed += 1
            print(f"    効かない（{mode} {kind}）: {pick} で {value} を2回選んだあと {check} → {after}（望み {want}）")
    for (mode, kind), (usable, kept, skipped) in sorted(groups.items()):
        print(f"    {mode} {kind}: 効いた {kept}/{usable}（数えない {skipped}）")
    return failed


def main():
    on_path, off_path = sys.argv[1:3]
    print("選び直しが次の変換に効くか（前の文が毎回違う ctx / 前の文なし plain）:")
    failed = score("人工知能あり", on_path) + score("人工知能なし", off_path)
    if failed:
        print(f"選び直しが効かない行が {failed} 件")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
