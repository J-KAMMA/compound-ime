"""Scores the context test (前後の文がある試験).

  python tools/score_context.py tests/conversion/context.tsv with.tsv without.tsv

How many sentences come out exactly as written with the sentence before them
given as context, and without it, and the sentences where the two differ.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lenient_match import lenient_match  # noqa: E402


def load(path):
    out = {}
    for line in open(path, encoding="utf-8"):
        p = line.rstrip("\n").split("\t")
        if len(p) >= 3:
            out[p[0]] = p[2]
    return out


def main():
    cases = [l.rstrip("\n").split("\t") for l in open(sys.argv[1], encoding="utf-8")
             if l.strip() and not l.startswith("#")]
    with_, without = load(sys.argv[2]), load(sys.argv[3])
    a = b = la = lb = 0
    better, worse = [], []
    for raw, original, _before in cases:
        x, y = with_.get(raw), without.get(raw)
        a += x == original
        b += y == original
        la += x is not None and lenient_match(x, original)
        lb += y is not None and lenient_match(y, original)
        if x != y:
            (better if x == original else worse if y == original else []).append(f"  {y} → {x}（元: {original}）")
    print(f"前後の文がある試験: 前の文あり {a}/{len(cases)}、なし {b}/{len(cases)}"
          f"（前の文で正解になった {len(better)}、間違いになった {len(worse)}）")
    print(f"ゆるい一致（表記ゆれは同じとみなす）: 前の文あり {la}/{len(cases)}、なし {lb}/{len(cases)}")
    if better:
        print("前の文で正解になった:\n" + "\n".join(better[:40]))
    if worse:
        print("前の文で間違いになった:\n" + "\n".join(worse[:40]))


if __name__ == "__main__":
    main()
