"""slow_compare.py <正解.json> 名前=結果.tsv ...

人工知能の時間の上限の試験（試験の組 h）の比べ。結果.tsv は batch_convert.sh の出力
（入力<TAB>文節<TAB>確定）。名前は次の決まった言葉を使う:
  unlimited  上限なし（人工知能あり）
  noai       人工知能なし
  t10, t1    わざと小さくした上限（10 ミリ秒、1 ミリ秒）
  load1000    計算機を忙しくして、既定の上限（1000 ミリ秒）
  loadfree   計算機を忙しくして、上限なし

上限に当たった変換は、人工知能が確かめ終わった結果（unlimited と同じ）か、確かめる前の結果
（noai と同じ）のどちらかになるはず。どちらとも違う文があれば数えて出す。
"""
import json
import sys


def load(path):
    out = {}
    for line in open(path, encoding="utf-8"):
        f = line.rstrip("\n").split("\t")
        if len(f) >= 3:
            out[f[0]] = f[2]
    return out


def correct(item, got):
    if got is None:
        return False
    return any(got.lower() == a.lower() for a in [item["intended"], *item.get("alternatives", [])])


def main():
    items = json.load(open(sys.argv[1], encoding="utf-8"))["items"]
    runs = {}
    for arg in sys.argv[2:]:
        name, path = arg.split("=", 1)
        runs[name] = load(path)
    base = runs.get("noai") or next(iter(runs.values()))
    scope = [it for it in items if it["romaji"] in base]
    print(f"対象 {len(scope)} 文")
    labels = {"unlimited": "上限なし", "noai": "人工知能なし", "t10": "上限 10 ミリ秒", "t1": "上限 1 ミリ秒",
              "load1000": "忙しい計算機で 1000 ミリ秒", "loadfree": "忙しい計算機で上限なし",
              "idle300": "空いた計算機で 300 ミリ秒", "idle500": "空いた計算機で 500 ミリ秒",
              "idle1000": "空いた計算機で 1000 ミリ秒", "idlefree": "空いた計算機で上限なし"}
    for name, got in runs.items():
        right = sum(correct(it, got.get(it["romaji"])) for it in scope)
        done = sum(it["romaji"] in got for it in scope)
        print(f"{labels.get(name, name):24} 正解 {right}/{len(scope)}、変換を終えた文 {done}/{len(scope)}")
    full, none = runs.get("unlimited"), runs.get("noai")
    if full is None or none is None:
        return
    for name in ("t10", "t1", "load1000"):
        got = runs.get(name)
        if got is None:
            continue
        same_full = same_none = both = other = 0
        for it in scope:
            g, f, n = got.get(it["romaji"]), full.get(it["romaji"]), none.get(it["romaji"])
            if g == f and g == n:
                both += 1
            elif g == f:
                same_full += 1
            elif g == n:
                same_none += 1
            else:
                other += 1
        print(f"{labels[name]}: 人工知能の有無によらず同じ {both} 文、上限なしの結果と同じ {same_full} 文、"
              f"人工知能なしの結果と同じ {same_none} 文、どちらとも違う {other} 文")


if __name__ == "__main__":
    main()
