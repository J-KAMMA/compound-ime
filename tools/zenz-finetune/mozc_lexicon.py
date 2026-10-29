#!/usr/bin/env python3
"""Mozc の辞書（src/data/dictionary_oss/dictionary0*.txt）から、v6 の練習問題を選ぶための語の一覧を作る。

  python mozc_lexicon.py --out lexicon.tsv dictionary00.txt … dictionary09.txt

できるもの（1行 1 語。先頭の # の行に、元のファイルの SHA256）:
  読み（ひらがな）<TAB>表記<TAB>費用（同じ読み・表記の中でいちばん小さい値）

漢字を含む表記だけを残す。使い道（build_dataset.py --lexicon）:
  - homophone_dict: 文の中の語の読みに、Mozc で別の漢字の表記もある語（同音語）。費用がほかの表記より
    大きい（＝ふつうは別の語が先に出る）語を「難しい同音語」として多めに選ぶ。
  - proper_noun: 固有名詞の読みと表記の組が Mozc にもあるか（SudachiPy の読みの誤りを避ける確かめ）。
Mozc の辞書は BSD-3-Clause 系（Mozc の LICENSE と dictionary_oss/README）。練習問題を選ぶのに使うだけで、配る物には入らない。
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

KANJI = re.compile(r"[一-鿿々〆ヶ]")
READING = re.compile(r"^[ぁ-ゖー]+$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def build(paths, out: Path) -> dict:
    best: dict[tuple[str, str], int] = {}
    for path in paths:
        for line in open(path, encoding="utf-8"):
            cols = line.rstrip("\n").split("\t")
            if len(cols) < 5 or not READING.match(cols[0]) or not KANJI.search(cols[4]):
                continue
            key = (cols[0], cols[4])
            cost = int(cols[3])
            if key not in best or cost < best[key]:
                best[key] = cost
    with open(out, "w", encoding="utf-8", newline="\n") as handle:
        for path in paths:
            handle.write(f"# {Path(path).name}\t{sha256_file(Path(path))}\n")
        for (reading, surface), cost in sorted(best.items()):
            handle.write(f"{reading}\t{surface}\t{cost}\n")
    readings = {}
    for reading, _ in best:
        readings[reading] = readings.get(reading, 0) + 1
    return {"entries": len(best), "readings": len(readings),
            "readings_with_homophones": sum(1 for n in readings.values() if n >= 2)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("paths", nargs="+")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    stats = build(sorted(args.paths), Path(args.out))
    print(f"語の一覧 {args.out}: {stats}  SHA256 {sha256_file(Path(args.out))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
