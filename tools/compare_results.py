"""compare_results.py <基準.tsv> <新.tsv> [<正解.json>]
2つの一括試験の結果（入力<TAB>文節<TAB>確定）を比べ、変わった文を一覧する。正解があれば採点もする。"""
import json
import sys


def load(path):
    return {l.split("\t")[0]: l.rstrip("\n").split("\t")[2] for l in open(path, encoding="utf-8")}


base, new = load(sys.argv[1]), load(sys.argv[2])
changed = [k for k in new if base.get(k) != new[k]]
print(f"{len(new)} 文のうち {len(changed)} 文が変わった")
want = {}
if len(sys.argv) > 3:
    items = json.load(open(sys.argv[3], encoding="utf-8"))["items"]
    want = {i["romaji"]: i for i in items}

    def score(got):
        exact = kept = 0
        for i in items:
            v = got.get(i["romaji"], "").lower()
            exact += v == i["intended"].lower()
            pos, ok = 0, True
            for w in i["english"]:
                at = v.find(w.lower(), pos)
                if at < 0:
                    ok = False
                    break
                pos = at + len(w)
            kept += ok
        return exact, kept
    print("全文一致（大文字小文字は無視）・英単語保持: 基準 %d・%d → 新 %d・%d" % (*score(base), *score(new)))
for k in changed:
    mark = ""
    if k in want:
        w = want[k]["intended"].lower()
        mark = "○ " if new[k].lower() == w else "× " if base.get(k, "").lower() == w else "・ "
    print(f"{mark}{base.get(k)} → {new[k]}")
