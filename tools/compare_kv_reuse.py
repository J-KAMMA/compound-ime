#!/usr/bin/env python3
"""打鍵をまたぐ KV の使い回しを止めた版と入れた版の出力を、1行ずつ比べる。

  python tools/compare_kv_reuse.py <止めた版の結果フォルダー> <入れた版の結果フォルダー>

tools/run_tests.sh の結果フォルダーをそのまま渡す。変換の結果（*.tsv、*.json、*.txt）を
1ファイルずつ読み、行数と1行ずつの文字が全部同じかを確かめる。時間・記録・環境のファイル
（名前に latency、speed、time、profile、log、stats、zstats、env、report、gdb、perf を含む）は
比べない（同じ条件でも機械の都合で変わるため）。違いが1つでもあれば、ファイル名と行番号を出して
終了の番号を 1 にする。

同じ組を同じ計算機で、MYIME_KV_REUSE=0 と =1 の2回流してから使う。
"""
from __future__ import annotations

import sys
from pathlib import Path

SKIP = ("latency", "speed", "time", "profile", "log", "stats", "zstats", "env", "report", "gdb", "perf")
SUFFIXES = (".tsv", ".json", ".txt")


def files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in SUFFIXES:
            continue
        name = path.name.lower()
        if any(word in name for word in SKIP):
            continue
        yield path.relative_to(root)


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    left, right = Path(sys.argv[1]), Path(sys.argv[2])
    left_files = set(files(left))
    right_files = set(files(right))
    differences = 0
    for name in sorted(left_files | right_files):
        if name not in left_files:
            print(f"片方にない: {name}（{right} にだけある）")
            differences += 1
            continue
        if name not in right_files:
            print(f"片方にない: {name}（{left} にだけある）")
            differences += 1
            continue
        a = (left / name).read_text(encoding="utf-8", errors="replace").splitlines()
        b = (right / name).read_text(encoding="utf-8", errors="replace").splitlines()
        if a == b:
            continue
        differences += 1
        if len(a) != len(b):
            print(f"行数が違う: {name}（{len(a)} 行 と {len(b)} 行）")
        for number, (x, y) in enumerate(zip(a, b), 1):
            if x != y:
                print(f"違う: {name}:{number}")
                print(f"  止めた版: {x}")
                print(f"  入れた版: {y}")
                break
    if differences:
        print(f"違い {differences} 件")
        return 1
    print("出力は全部同じ（比べたファイル " + str(len(left_files)) + " 個）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
