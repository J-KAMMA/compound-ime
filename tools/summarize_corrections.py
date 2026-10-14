"""summarize_corrections.py [correction_log.tsv] [--top N]

Summarizes the local correction log (what the user chose instead of the first candidate) to
find what to improve next. The log is written only when it is turned on and stays on this PC;
this tool only reads it and prints to the screen.

Without a path, the log in the usual profile folder is read:
  Windows: %USERPROFILE%\\AppData\\LocalLow\\CompoundIME\\correction_log.tsv
  Linux:   ~/.config/compound-ime/correction_log.tsv
  Mac:     ~/Library/Application Support/CompoundIME/correction_log.tsv

Lines are "time<TAB>kind<TAB>key<TAB>first<TAB>chosen". Printed: the kinds of correction, then
the most frequent (first -> chosen) pairs with their readings.
"""
import argparse
import os
import sys
from collections import Counter
from pathlib import Path


def default_log():
    home = Path.home()
    for path in (home / "AppData/LocalLow/CompoundIME/correction_log.tsv",
                 home / ".config/compound-ime/correction_log.tsv",
                 home / "Library/Application Support/CompoundIME/correction_log.tsv"):
        if path.is_file():
            return path
    return None


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("log", nargs="?", type=Path)
    parser.add_argument("--top", type=int, default=40)
    args = parser.parse_args()
    log = args.log or default_log()
    if log is None or not log.is_file():
        print("誤変換の記録が見つかりません（記録を有効にしていないか、まだ記録がありません）。")
        return
    kinds, pairs = Counter(), Counter()
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        f = line.split("\t")
        if len(f) < 5:
            continue
        kinds[f[1]] += 1
        pairs[(f[2], f[3], f[4])] += 1
    print(f"記録 {sum(kinds.values())} 件（{log}）")
    for kind, n in kinds.most_common():
        print(f"  {kind}: {n}")
    print(f"\nよく直された変換（多い順に {args.top} 件）: 回数  読み  最初の候補 → 選んだもの")
    for (key, first, chosen), n in pairs.most_common(args.top):
        print(f"  {n:4}  {key}  {first} → {chosen}")


if __name__ == "__main__":
    main()
