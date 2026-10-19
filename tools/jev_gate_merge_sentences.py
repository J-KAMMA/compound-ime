"""判定の門の学習用の文を、ウィキペディアの分割ごとに作ったものから1つにまとめる。

  python tools/jev_gate_merge_sentences.py --out <train.tsv> --count 1000000 --seed 20261020 <分割1.tsv> <分割2.tsv> ...

各ファイルは tools/jev_gate_sentences.py の出力。ローマ字か元の文が同じ行は1つだけ残し、
seed で並べ替えてから先頭の --count 行を取る（分割ごとの偏りを組へ持ち込まないため）。
足りなければ失敗にする。出力の先頭の # の行は説明（分割ごとの件数つき）。
"""
import argparse
import random
import sys
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--count", type=int, required=True)
    ap.add_argument("--seed", type=int, default=20261020)
    args = ap.parse_args()
    rows, seen_raw, seen_surface = [], set(), set()
    notes = []
    for path in args.inputs:
        kept = dup = total = 0
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if not line or line.startswith("#"):
                continue
            total += 1
            cols = line.split("\t")
            if len(cols) != 3:
                continue
            if cols[0] in seen_raw or cols[1] in seen_surface:
                dup += 1
                continue
            seen_raw.add(cols[0])
            seen_surface.add(cols[1])
            rows.append(line)
            kept += 1
        notes.append(f"{Path(path).name}: {total} 文、重なりを除いて {kept}（除いた {dup}）")
        print(notes[-1])
    if len(rows) < args.count:
        sys.exit(f"文が足りません: {len(rows)} < {args.count}")
    random.Random(args.seed).shuffle(rows)
    rows = rows[: args.count]
    header = ("# ウィキペディア日本語版（CC BY-SA 4.0、https://ja.wikipedia.org/）の文を、SudachiPy の読みから"
              "ローマ字にしたもの。tools/jev_gate_sentences.py と tools/jev_gate_merge_sentences.py で作成。"
              "ローマ字<TAB>元の文<TAB>前の文\n")
    header += "".join(f"# {n}\n" for n in notes)
    Path(args.out).write_text(header + "\n".join(rows) + "\n", encoding="utf-8", newline="\n")
    with_prev = sum(1 for r in rows if r.split("\t")[2])
    print(f"{len(rows)} 文（前の文つき {with_prev}）")


if __name__ == "__main__":
    main()
