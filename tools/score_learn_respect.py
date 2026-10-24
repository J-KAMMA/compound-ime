#!/usr/bin/env python3
"""履歴の学習の試験（組 l）の採点。

  python tools/score_learn_respect.py <対象の表> <人工知能あり.tsv> <人工知能なし.tsv> [最低数]

対象の表は learn_respect_convert.sh が書く -targets.tsv（先頭<TAB>選んだ書き方[<TAB>前の文]）。
結果は「キー<TAB>選んだ書き方<TAB>学習のあとに先頭に来た候補」。
人工知能なし（重みなし）で、選んだ書き方が先頭に来たことを必ず確かめる。来なければ、
人工知能ありでも先頭なら合格にせず、試験の失敗にする。人工知能ありだけが先頭を別の書き方に
した件（打ち消し）も失敗にする。結果の行がない・空の行は捨てずに失敗にする。
最低数（省略すると50）より比べられた語が少ないときも失敗にする。
"""
import sys
from pathlib import Path


def load(path):
    rows, broken = {}, []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        fields = line.split("\t")
        if len(fields) < 3 or not fields[1] or not fields[2]:
            broken.append((number, line))
            continue
        rows[fields[0]] = (fields[1], fields[2])
    return rows, broken


def main():
    table, on_path, off_path = sys.argv[1:4]
    minimum = int(sys.argv[4]) if len(sys.argv) > 4 else 50
    keys = [line.split("\t")[0] for line in Path(table).read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")]
    on, on_broken = load(on_path)
    off, off_broken = load(off_path)
    missing_on = [k for k in keys if k not in on]
    missing_off = [k for k in keys if k not in off]
    common = [k for k in keys if k in on and k in off]
    ok_on = [k for k in common if on[k][1] == on[k][0]]
    ok_off = [k for k in common if off[k][1] == off[k][0]]
    not_learned = [k for k in common if off[k][1] != off[k][0]]
    override = [k for k in common if off[k][1] == off[k][0] and on[k][1] != on[k][0]]
    wrong_target = [k for k in common if on[k][0] != off[k][0]]

    print(f"履歴の学習: {len(common)} 語（先頭と違う共通の候補があった語）")
    print(f"  人工知能あり: 選んだ書き方が先頭 {len(ok_on)}/{len(common)}")
    print(f"  人工知能なし: 選んだ書き方が先頭 {len(ok_off)}/{len(common)}")
    print(f"  人工知能が打ち消した語: {len(override)}")
    for k in override[:10]:
        print(f"    {k}: 選んだ {off[k][0]}、なし {off[k][1]}、あり {on[k][1]}")
    if not_learned:
        print(f"  学習が効かなかった語（人工知能なしで先頭でない）: {len(not_learned)}")
        for k in not_learned[:10]:
            print(f"    {k}: 選んだ {off[k][0]}、なし {off[k][1]}")
    if wrong_target:
        print(f"  選んだ書き方があり・なしで違う語: {len(wrong_target)}")
    if missing_on or missing_off:
        print(f"  結果のない語: あり {len(missing_on)}、なし {len(missing_off)}")
        for k in (missing_on + [k for k in missing_off if k not in missing_on])[:10]:
            print(f"    {k}")
    if on_broken or off_broken:
        print(f"  結果の行が壊れている: あり {len(on_broken)}、なし {len(off_broken)}")
        for number, line in (on_broken + off_broken)[:5]:
            print(f"    {number}: {line}")
    if len(common) < minimum:
        print(f"比べられた語が{minimum}未満（{len(common)}）", file=sys.stderr)
        return 1
    if missing_on or missing_off or on_broken or off_broken or not_learned or override or wrong_target:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
