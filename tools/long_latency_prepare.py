"""長い文の変換の時間を測る入力と、句読点で分けた入力を作る。

  python tools/long_latency_prepare.py tests/conversion/long-latency.tsv <出力のフォルダー>

tests/conversion/long-latency.tsv（組<TAB>ローマ字<TAB>前の文<TAB>元の文）から、組ごとに
  long-<組>.tsv            前の文なしの入力（ローマ字<TAB>）
  long-<組>-ctx.tsv        前の文ありの入力（ローマ字<TAB>前の文）
  long-<組>-split.tsv      句読点（. と ,）で分けた句を1行ずつにした入力
  long-<組>-split-map.tsv  元の文ごとの句の数（番号<TAB>句の数。split の時間を文ごとに足すのに使う）
を作る。split は句点を落とすので、正解ではなく時間だけを比べる。
"""
import re
import sys
from pathlib import Path


def read_tests(path):
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) >= 4:
            rows.append((int(fields[0]), fields[1], fields[2], fields[3]))
    return rows


def clauses(romaji):
    parts = [p.strip() for p in re.split(r"[,.]", romaji)]
    return [p for p in parts if p]


def main():
    if len(sys.argv) < 3:
        raise SystemExit("使い方: python tools/long_latency_prepare.py <long-latency.tsv> <出力のフォルダー>")
    tests = read_tests(sys.argv[1])
    out = Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    buckets = sorted({row[0] for row in tests})
    for bucket in buckets:
        rows = [row for row in tests if row[0] == bucket]
        (out / f"long-{bucket}.tsv").write_text(
            "".join(f"{romaji}\t\n" for _, romaji, _, _ in rows), encoding="utf-8", newline="\n")
        (out / f"long-{bucket}-ctx.tsv").write_text(
            "".join(f"{romaji}\t{before}\n" for _, romaji, before, _ in rows), encoding="utf-8", newline="\n")
        split, mapping = [], []
        for index, (_, romaji, _, _) in enumerate(rows):
            parts = clauses(romaji)
            if not parts:
                parts = [romaji]
            mapping.append(f"{index}\t{len(parts)}")
            split.extend(f"{part}\t" for part in parts)
        (out / f"long-{bucket}-split.tsv").write_text(
            "\n".join(split) + "\n", encoding="utf-8", newline="\n")
        (out / f"long-{bucket}-split-map.tsv").write_text(
            "\n".join(mapping) + "\n", encoding="utf-8", newline="\n")
        print(f"組 {bucket}: {len(rows)} 文、句 {len(split)} 個")
    print(f"{out} に入力を作りました（組 {', '.join(map(str, buckets))}）")


if __name__ == "__main__":
    main()
