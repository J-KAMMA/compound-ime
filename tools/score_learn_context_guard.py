#!/usr/bin/env python3
"""学習が文脈を壊さないかの試験（組 l）の採点。

  python tools/score_learn_context_guard.py <人工知能あり.tsv> <人工知能なし.tsv>

各行は「文のローマ字<TAB>覚えさせた書き方<TAB>正しい書き方<TAB>学習の前の確定<TAB>学習のあとの確定<TAB>1語の確定」。
学習の前に正しい書き方が入っていた文のうち、学習のあとも入っている文を数える。
いまは記録だけで、失敗にはしない（直す前の今の状態を測るため）。
"""
import sys
from pathlib import Path


def score(label, path):
    rows = [line.split("\t") for line in Path(path).read_text(encoding="utf-8").splitlines()]
    rows = [r for r in rows if len(r) >= 5]
    usable = [r for r in rows if r[2] in r[3]]
    kept = [r for r in usable if r[2] in r[4]]
    broken = [r for r in usable if r[2] not in r[4]]
    learned = [r for r in usable if len(r) >= 6 and r[5] == r[1]]
    print(f"  {label}: 学習の前に正しかった文 {len(usable)}/{len(rows)}、学習のあとも正しい {len(kept)}/{len(usable)}"
          f"（1語では覚えた書き方が先頭 {len(learned)}/{len(usable)}）")
    for r in broken[:10]:
        print(f"    壊れた: {r[1]} を覚えたあと {r[3]} → {r[4]}")


def main():
    on_path, off_path = sys.argv[1:3]
    print("学習が文脈を壊さないか:")
    score("人工知能あり", on_path)
    score("人工知能なし", off_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
