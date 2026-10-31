"""正しく打った文で、推測（打ち間違いの直し・英語の見分け）が壊した数と直した数を数える。

  python3 tools/score_guess_harm.py tests/conversion/clean-typing.tsv <既定の出力.tsv> <推測を止めた出力.tsv>

出力の tsv は「ローマ字<TAB>文節|…<TAB>確定」（tools/batch_convert.sh）。期待する文は | 区切りで別の正解を持てる。
壊した: 止めると正しいのに、既定では違う。直した: 既定で正しいのに、止めると違う。
"""
import sys
from collections import defaultdict


def load_out(path):
    got = {}
    for line in open(path, encoding="utf-8"):
        p = line.rstrip("\n").split("\t")
        if len(p) >= 3:
            got[p[0]] = p[2]
    return got


def main():
    cases = []
    for line in open(sys.argv[1], encoding="utf-8"):
        if line.startswith("#") or not line.strip():
            continue
        raw, expected, kind = line.rstrip("\n").split("\t")[:3]
        cases.append((raw, set(expected.split("|")), kind))
    on, off = load_out(sys.argv[2]), load_out(sys.argv[3])
    count = defaultdict(lambda: [0, 0, 0, 0, 0])  # 文、既定で正解、止めて正解、壊した、直した
    lines = []
    for raw, answers, kind in cases:
        a, b = on.get(raw, ""), off.get(raw, "")
        ok_a, ok_b = a in answers, b in answers
        for k in (kind, "全体"):
            c = count[k]
            c[0] += 1; c[1] += ok_a; c[2] += ok_b; c[3] += ok_b and not ok_a; c[4] += ok_a and not ok_b
        if ok_a != ok_b or (a != b and not ok_a):
            mark = "壊した" if ok_b else "直した" if ok_a else "どちらも違う"
            lines.append(f"  {mark} [{kind}] {raw} → 既定 {a} / 止めて {b}（期待 {'|'.join(sorted(answers))}）")
    c = count["全体"]
    print(f"正しく打った文: 既定で正解 {c[1]}/{c[0]}、推測を止めて正解 {c[2]}/{c[0]}（推測が壊した {c[3]}、直した {c[4]}）")
    for k, c in sorted(count.items()):
        if k != "全体":
            print(f"  {k}: 既定 {c[1]}/{c[0]}、止めて {c[2]}/{c[0]}、壊した {c[3]}、直した {c[4]}")
    print("既定と止めたときで違う文:")
    print("\n".join(lines) if lines else "  なし")
    print("既定で間違えた文:")
    for raw, answers, kind in cases:
        if on.get(raw, "") not in answers:
            print(f"  [{kind}] {raw} → {on.get(raw, '')}（期待 {'|'.join(sorted(answers))}）")


if __name__ == "__main__":
    main()
