#!/usr/bin/env python3
"""履歴の学習の試験（組 l）の採点。

  python tools/score_learn_respect.py <読みの表> <人工知能あり.tsv> <人工知能なし.tsv>

表の各行は1語のローマ字。あり・なしの結果は
「ローマ字<TAB>選んだ書き方<TAB>学習のあとに先頭に来た候補」。
同じ書き方を4回選んだあと、先頭がその書き方になるかを数える。
人工知能ありだけが先頭を別の書き方にした件（打ち消し）があれば失敗にする。
"""
import sys
from pathlib import Path


def load(path):
    rows = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        fields = line.split("\t")
        if len(fields) >= 3:
            rows[fields[0]] = (fields[1], fields[2])
    return rows


def main():
    table, on_path, off_path = sys.argv[1:4]
    readings = [line.split("\t")[0] for line in Path(table).read_text(encoding="utf-8").splitlines()
                if line and not line.startswith("#")]
    on, off = load(on_path), load(off_path)
    common = [r for r in readings if r in on and r in off and on[r][0] and off[r][0]]
    ok_on = [r for r in common if on[r][1] == on[r][0]]
    ok_off = [r for r in common if off[r][1] == off[r][0]]
    override = [r for r in common if off[r][1] == off[r][0] and on[r][1] != on[r][0]]
    wrong_target = [r for r in common if on[r][0] != off[r][0]]
    print(f"履歴の学習: {len(common)} 語（人工知能なしで2番目の候補があった語）")
    print(f"  人工知能あり: 選んだ書き方が先頭 {len(ok_on)}/{len(common)}")
    print(f"  人工知能なし: 選んだ書き方が先頭 {len(ok_off)}/{len(common)}")
    print(f"  人工知能が打ち消した語: {len(override)}")
    if override:
        for r in override[:10]:
            print(f"    {r}: 選んだ {off[r][0]}、なし {off[r][1]}、あり {on[r][1]}")
    if wrong_target:
        print(f"  選んだ書き方があり・なしで違う語: {len(wrong_target)}")
    # 少なくとも50語を実際に比べる（この組の目的の数）。
    if len(common) < 50:
        print(f"比べられた語が50未満（{len(common)}）", file=sys.stderr)
        return 1
    if override or wrong_target:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
