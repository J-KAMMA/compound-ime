#!/usr/bin/env python3
"""打鍵をまたぐ KV の使い回しを止めた版と入れた版の出力を、1行ずつ比べる。

  python tools/compare_kv_reuse.py <止めた版の結果フォルダー> <入れた版の結果フォルダー>

tools/run_tests.sh の結果フォルダーをそのまま渡す。両方のフォルダーが存在し、
変換の結果として下の許可リストに合うファイルが1つ以上あることを要求する。
1ファイルずつ読み、行数と1行ずつの文字が全部同じかを確かめる。時間・記録・環境の
ファイルは許可リストに入れない（同じ条件でも機械の都合で変わるため）。違いが1つでも
あれば、ファイル名と行番号を出して終了の番号を 1 にする。フォルダーが無い・ファイルが
0個のときも、出力不変を証明できないので終了の番号を 1 にする。

同じ組を同じ計算機で、MYIME_KV_REUSE=0 と =1 の2回流してから使う。
"""
from __future__ import annotations

import fnmatch
import sys
from pathlib import Path

# 変換の結果として比べるファイル（名前の形を明示した許可リスト）。
# ここに無いものは、たとえ .tsv でも比べない（時間や記録のファイルを黙って飛ばさない）。
RESULT_PATTERNS = (
    "inputs-*.tsv",
    "ja400.tsv",
    "reported.tsv",
    "jaen*.tsv",
    "typo*.tsv",
    "variants-*.tsv",
    "wiki-typing-*.tsv",
    "domain-*.tsv",
    "proper-nouns*.tsv",
    "learn-respect*.tsv",
    "allenglish-*.tsv",
    "english-follow-*.tsv",
    "colloquial.tsv",
    "toku.tsv",
    "naru.tsv",
    "context-with*.tsv",
    "context-without.tsv",
    "clause-*.tsv",
    "decimal*.tsv",
    "kana-numbers*.tsv",
    "acronyms*.tsv",
    "katakana-*.tsv",
    "work-names.tsv",
    "brand-names.tsv",
    "long-*.tsv",
)


def is_result(name: str) -> bool:
    # 長い組の入力の対応表（-split-map.tsv）も、両側で同じなら比べてよい。
    # 時間の記録（*.profile.tsv）だけは明示して外す。
    if name.endswith(".profile.tsv"):
        return False
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in RESULT_PATTERNS)


def files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        name = path.name
        if is_result(name):
            yield path.relative_to(root)


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    left, right = Path(sys.argv[1]), Path(sys.argv[2])
    if not left.is_dir():
        print(f"結果フォルダーがありません: {left}", file=sys.stderr)
        return 1
    if not right.is_dir():
        print(f"結果フォルダーがありません: {right}", file=sys.stderr)
        return 1
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
    compared = len(left_files & right_files)
    if compared == 0:
        print("比べたファイルが0個。出力不変を証明できない", file=sys.stderr)
        return 1
    if differences:
        print(f"違い {differences} 件")
        return 1
    print(f"出力は全部同じ（比べたファイル {compared} 個）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
