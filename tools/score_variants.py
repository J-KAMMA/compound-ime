"""Scores the typing-style test (打ち方の揺れの試験).

  python tools/score_variants.py variants.tsv results.tsv

variants.tsv: tools/romaji_variants.py output. results.tsv: input<TAB>segments<TAB>committed.
For each style: how many lines give another result than the base style of the
same sentence (should be 0), and how many give the answer (when there is one).
The lines that differ from base are listed.
"""
import sys
from collections import defaultdict


def main():
    variants = [l.rstrip("\n").split("\t") for l in open(sys.argv[1], encoding="utf-8") if l.strip()]
    got = {}
    for l in open(sys.argv[2], encoding="utf-8"):
        p = l.rstrip("\n").split("\t")
        if len(p) >= 3:
            got[p[0]] = p[2]
    base = {v[0]: got.get(v[2]) for v in variants if v[1] == "base"}
    total, differ, correct, answered = defaultdict(int), defaultdict(int), defaultdict(int), defaultdict(int)
    listed = []
    for v in variants:
        sid, style, raw, intended = v[0], v[1], v[2], v[3]
        alts = v[4].split("|") if len(v) > 4 and v[4] else []
        out = got.get(raw)
        if out is None:
            continue
        total[style] += 1
        if intended:
            answered[style] += 1
            correct[style] += out == intended or out in alts
        if style != "base" and base.get(sid) is not None and out != base[sid]:
            differ[style] += 1
            listed.append(f"  {sid} {style}: {raw} → {out}（base: {base[sid]}）")
    all_differ = sum(differ.values())
    print(f"打ち方の揺れ: base と違う結果 {all_differ}/{sum(total[s] for s in total if s != 'base')}")
    for style in sorted(total, key=lambda s: (s != "base", s)):
        ans = f"、正解 {correct[style]}/{answered[style]}" if answered[style] else ""
        print(f"  {style}: {total[style]} 行、base と違う {differ[style]}{ans}")
    if listed:
        print("base と違ったもの:")
        print("\n".join(listed[:200]))


if __name__ == "__main__":
    main()
