"""score_categories.py <結果.tsv> <正解.json> [<基準の結果.tsv>]

変換結果（batch_convert.sh の出力: 入力<TAB>文節<TAB>確定）を正解と比べ、カテゴリごとの
正解数を出す。正解は intended と alternatives（表記ゆれ）のどれかと一致すれば○。
基準の結果を渡すと、カテゴリごとの差と、変わった文（○×）も出す。
"""
import json
import sys
from collections import Counter


def load(path):
    out = {}
    for line in open(path, encoding="utf-8"):
        f = line.rstrip("\n").split("\t")
        if len(f) >= 3:
            out[f[0]] = f[2]
    return out


def ok(item, got):
    if got is None:
        return False
    answers = [item["intended"], *item.get("alternatives", [])]
    return any(got.lower() == a.lower() for a in answers)


def main():
    got = load(sys.argv[1])
    items = json.load(open(sys.argv[2], encoding="utf-8"))["items"]
    base = load(sys.argv[3]) if len(sys.argv) > 3 else None
    total, right, base_right = Counter(), Counter(), Counter()
    for it in items:
        c = it["category"]
        total[c] += 1
        right[c] += ok(it, got.get(it["romaji"]))
        if base is not None:
            base_right[c] += ok(it, base.get(it["romaji"]))
    for c in sorted(total):
        line = f"{c:14} {right[c]:4}/{total[c]}"
        if base is not None:
            line += f"  （基準 {base_right[c]}、差 {right[c] - base_right[c]:+d}）"
        print(line)
    line = f"{'合計':14} {sum(right.values()):4}/{sum(total.values())}"
    if base is not None:
        line += f"  （基準 {sum(base_right.values())}）"
    print(line)
    if base is not None:
        for it in items:
            a, b = base.get(it["romaji"]), got.get(it["romaji"])
            if a != b:
                mark = "○" if ok(it, b) else ("×" if ok(it, a) else "・")
                print(f"{mark} {it['category']:12} {a} → {b}（正解 {it['intended']}）")
    else:
        for it in items:
            if not ok(it, got.get(it["romaji"])):
                print(f"✗ {it['category']:12} {got.get(it['romaji'])}（正解 {it['intended']}）")


if __name__ == "__main__":
    main()
