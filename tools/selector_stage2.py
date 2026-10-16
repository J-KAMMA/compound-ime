"""選び手の段階2: 学習した小さな選び手で、候補の上位8つから選び直せるかを机上で確かめる。

  python tools/selector_stage2.py --material <材料のフォルダ> --repo <このリポジトリ> \
      --table <romanji-hiragana.tsv> [--model lr|tree|gbdt] [--out 結果.txt] [--weights 重み.json]

材料（.github/workflows/selector-data.yml の成果物 selector-material）は、組ごとに
<組>.tsv（ローマ字<TAB>文節<TAB>確定）、features-<組>.txt（候補とコスト）、score-<組>.txt（Zenz の尤度）。
組 t<番号> は学習用（train.tsv が正解）、ja400、jaen（jaen270 と jaen200b）、w<番号>（wiki-typing）、
x<番号>（前後の文がある試験）は試験で、学習には使わない。

文節ごとに「1位の候補を、別の表記の候補 c に替えるか」を二択で学ぶ。正例は、正解を候補から組めて、
1位が正解の道に乗らず c が乗る文節。負例は 1位が正解の道に乗る文節の別の候補（正しく1位だった
箇所を壊さないため）と、どちらも乗らない候補。変換するときは、各文節で替える確からしさが最も高い
候補がしきい値を超えたら替える（ほかの文節は1位のまま、と同じ前提で全文節に当てる）。
数えるのは文の単位で、直る（間違い→正解）と壊れる（正解→間違い）。
"""
import argparse
import json
import math
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import romaji_variants as rv  # noqa: E402

HIRA = re.compile(r"[ぁ-ゖ]")
KATA = re.compile(r"[ァ-ヺー]")
KANJI = re.compile(r"[一-龯々〆ヵヶ]")
LATIN = re.compile(r"[A-Za-zＡ-Ｚａ-ｚ]")
DIGIT = re.compile(r"[0-9０-９〇一二三四五六七八九十百千万億]")
# 候補の属性（Mozc の attribute.h）のうち特徴に使うもの
ATTRS = [("best", 0), ("reranked", 1), ("context", 4), ("spelling", 5), ("realtime", 8),
         ("user_dict", 9), ("typing_corr", 12), ("suffix", 15), ("english", 22), ("number", 23),
         ("single_kanji", 24)]


# ---- 読み込み ----

def read_answers(repo, material):
    """組の頭文字ごとに、ローマ字 → 正解の一覧。"""
    t = Path(repo) / "tests/conversion"
    answers = {"ja400": {}, "jaen": {}, "w": {}, "x": {}, "t": {}}
    for it in json.loads((t / "ja400.json").read_text(encoding="utf-8"))["items"]:
        answers["ja400"][it["romaji"]] = [it["intended"]] + it.get("alternatives", [])
    for name in ("jaen270.json", "jaen200b.json"):
        for it in json.loads((t / name).read_text(encoding="utf-8"))["items"]:
            answers["jaen"][it["romaji"]] = [it["intended"]] + it.get("alternatives", [])
    for key, path in (("w", t / "wiki-typing.tsv"), ("x", t / "context.tsv"), ("t", Path(material) / "train.tsv")):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or "\t" not in line:
                continue
            p = line.split("\t")
            answers[key][p[0]] = [p[1]]
    return answers


def parse_features(path):
    """読み（文節の読みをつないだもの）→ 文節の一覧 [(読み, [候補の辞書…])]。同じ読みは最後の行。"""
    out = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        segs = []
        for s in line.split("\x01"):
            parts = s.split("\t")
            cands = []
            for c in parts[1:]:
                f = c.split("\x02")
                if len(f) < 8:
                    break
                try:
                    cands.append({"value": f[0], "cost": int(f[1]), "wcost": int(f[2]), "scost": int(f[3]),
                                  "lid": int(f[4]), "rid": int(f[5]), "attr": int(f[6]), "content": f[7]})
                except ValueError:
                    break
            segs.append((parts[0], cands))
        out["".join(k for k, _ in segs)] = segs
    return out


def parse_scores(path):
    """(読み, 1位をつないだもの, 文節の番号) → {表記: Zenz の尤度}。"""
    out = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        p = line.split("\t")
        if len(p) < 7:
            continue
        scores = {}
        for i in range(5, len(p) - 1, 2):
            try:
                v = float(p[i + 1])
            except ValueError:
                continue
            if math.isfinite(v):
                scores[p[i]] = v
        out[(p[0], p[1], int(p[2]))] = scores
    return out


def load_group(material, group, answers, table):
    """組の文を読み、1文ごとに辞書を返す。"""
    m = Path(material)
    res = m / f"{group}.tsv"
    if not res.exists():
        return []
    feats = parse_features(m / f"features-{group}.txt")
    scores = parse_scores(m / f"score-{group}.txt")
    ans = answers["t" if group.startswith("t") else "w" if group.startswith("w")
                  else "x" if group.startswith("x") else group]
    items = []
    for line in res.read_text(encoding="utf-8").splitlines():
        p = line.split("\t")
        if len(p) < 3 or p[0] not in ans:
            continue
        raw, out = p[0], p[2]
        segs = feats.get(rv.to_kana(raw, table))
        item = {"group": group, "raw": raw, "out": out, "answers": ans[raw], "segs": None}
        if segs and all(c for _, c in segs):
            firsts = [c[0]["value"] for _, c in segs]
            # 書き出しの後で表記が変わった文（後処理）は、選び手を当てない
            if "".join(firsts) == out:
                reading = "".join(k for k, _ in segs)
                joined = "\x01".join(firsts)
                item["segs"] = segs
                item["zenz"] = [scores.get((reading, joined, i)) for i in range(len(segs))]
        items.append(item)
    return items


def is_right(text, answers):
    return text in answers or text.lower() == answers[0].lower()


def good_sets(segs, answers):
    """文節ごとに、正解の道に乗る候補の番号の集合。正解を組めなければ None。"""
    goods = None
    for a in answers:
        n = len(segs)
        # 前から: 各文節の前で届く位置
        fwd = [set() for _ in range(n + 1)]
        fwd[0] = {0}
        for i, (_, cands) in enumerate(segs):
            for at in fwd[i]:
                for c in cands:
                    v = c["value"]
                    if v and a.startswith(v, at):
                        fwd[i + 1].add(at + len(v))
        if len(a) not in fwd[n]:
            continue
        # 後ろから: 各文節の後ろの位置から終わりまで届くか
        bwd = [set() for _ in range(n + 1)]
        bwd[n] = {len(a)}
        for i in range(n - 1, -1, -1):
            for at in fwd[i]:
                for c in segs[i][1]:
                    v = c["value"]
                    if v and a.startswith(v, at) and at + len(v) in bwd[i + 1]:
                        bwd[i].add(at)
        g = [set() for _ in range(n)]
        for i in range(n):
            for at in fwd[i] & bwd[i]:
                for j, c in enumerate(segs[i][1]):
                    v = c["value"]
                    if v and a.startswith(v, at) and at + len(v) in bwd[i + 1]:
                        g[i].add(j)
        goods = g if goods is None else [x | y for x, y in zip(goods, g)]
    return goods


# ---- 特徴 ----

def char_stats(s):
    n = max(1, len(s))
    return [len(HIRA.findall(s)) / n, len(KATA.findall(s)) / n, len(KANJI.findall(s)) / n,
            1.0 if LATIN.search(s) else 0.0, 1.0 if DIGIT.search(s) else 0.0]


def kind(ch):
    if not ch:
        return 0
    if HIRA.match(ch):
        return 1
    if KATA.match(ch):
        return 2
    if KANJI.match(ch):
        return 3
    if LATIN.match(ch):
        return 4
    return 5


FEATURE_NAMES = (
    ["rank", "rank1", "cost_d", "wcost_d", "scost_d", "top_cost", "top_wcost", "top_scost",
     "z_have", "z_d", "z_d_best", "z_is_best", "z_top_is_best", "len_d", "keylen", "nsegs",
     "first", "last", "same_content", "same_lid", "same_rid", "c_all_hira", "t_all_hira",
     "c_all_kata", "t_all_kata", "prev_kanji", "next_hira", "c_end_eq_t_end"]
    + [f"c_{x}" for x in ("hira", "kata", "kanji", "latin", "digit")]
    + [f"t_{x}" for x in ("hira", "kata", "kanji", "latin", "digit")]
    + [f"d_{x}" for x in ("hira", "kata", "kanji")]
    + [f"c_attr_{n}" for n, _ in ATTRS] + [f"t_attr_{n}" for n, _ in ATTRS])


def pair_features(segs, zenz, i, j):
    key, cands = segs[i]
    t, c = cands[0], cands[j]
    z = zenz[i] if zenz else None
    zt = z.get(t["value"]) if z else None
    zc = z.get(c["value"]) if z else None
    have = zt is not None and zc is not None
    zbest = max(z.values()) if z else None
    tv, cv = t["value"], c["value"]
    prev = segs[i - 1][1][0]["value"] if i > 0 else ""
    nxt = segs[i + 1][1][0]["value"] if i + 1 < len(segs) else ""
    cs, ts = char_stats(cv), char_stats(tv)
    f = [j, 1.0 if j == 1 else 0.0,
         (c["cost"] - t["cost"]) / 1000.0, (c["wcost"] - t["wcost"]) / 1000.0, (c["scost"] - t["scost"]) / 1000.0,
         t["cost"] / 1000.0, t["wcost"] / 1000.0, t["scost"] / 1000.0,
         1.0 if have else 0.0,
         (zc - zt) if have else 0.0,
         (zc - zbest) if have else 0.0,
         1.0 if have and zc >= zbest else 0.0,
         1.0 if zt is not None and zbest is not None and zt >= zbest else 0.0,
         len(cv) - len(tv), len(key), len(segs),
         1.0 if i == 0 else 0.0, 1.0 if i + 1 == len(segs) else 0.0,
         1.0 if c["content"] == t["content"] else 0.0,
         1.0 if c["lid"] == t["lid"] else 0.0, 1.0 if c["rid"] == t["rid"] else 0.0,
         1.0 if cs[0] == 1.0 else 0.0, 1.0 if ts[0] == 1.0 else 0.0,
         1.0 if cs[1] == 1.0 else 0.0, 1.0 if ts[1] == 1.0 else 0.0,
         1.0 if kind(prev[-1:]) == 3 else 0.0, 1.0 if kind(nxt[:1]) == 1 else 0.0,
         1.0 if cv[-1:] == tv[-1:] else 0.0]
    f += cs + ts + [cs[k] - ts[k] for k in range(3)]
    f += [1.0 if c["attr"] >> b & 1 else 0.0 for _, b in ATTRS]
    f += [1.0 if t["attr"] >> b & 1 else 0.0 for _, b in ATTRS]
    return f


def alternatives(segs, i):
    """文節 i の、1位と違う表記の候補の番号（同じ表記は先のものだけ）。"""
    seen = {segs[i][1][0]["value"]}
    out = []
    for j, c in enumerate(segs[i][1]):
        if j == 0 or c["value"] in seen:
            continue
        seen.add(c["value"])
        out.append(j)
    return out


def examples(item):
    """学習の例: (特徴, ラベル) の一覧。正解を組めない間違いの文は使わない。"""
    segs = item["segs"]
    if segs is None:
        return []
    right = is_right(item["out"], item["answers"])
    goods = good_sets(segs, item["answers"])
    if goods is None:
        return []
    rows = []
    for i in range(len(segs)):
        top_good = 0 in goods[i]
        for j in alternatives(segs, i):
            label = 1 if (not right and not top_good and j in goods[i]) else 0
            rows.append((pair_features(segs, item["zenz"], i, j), label))
    return rows


# ---- 当てはめと数え ----

def apply_selector(item, prob, threshold):
    """選び手を当てた後の文。prob(特徴の一覧) → 確からしさの一覧。"""
    segs = item["segs"]
    if segs is None:
        return item["out"]
    out = []
    for i in range(len(segs)):
        alts = alternatives(segs, i)
        pick = 0
        if alts:
            ps = prob([pair_features(segs, item["zenz"], i, j) for j in alts])
            k = max(range(len(alts)), key=lambda x: ps[x])
            if ps[k] >= threshold:
                pick = alts[k]
        out.append(segs[i][1][pick]["value"])
    return "".join(out)


def zenz_only(item):
    """段階1と同じ: Zenz の尤度が最も高い表記を選ぶ（学習なし）。"""
    segs = item["segs"]
    if segs is None:
        return item["out"]
    out = []
    for i, (_, cands) in enumerate(segs):
        z = item["zenz"][i]
        v = cands[0]["value"]
        if z and v in z:
            best = max(z, key=lambda s: z[s])
            if z[best] > z[v]:
                v = best
        out.append(v)
    return "".join(out)


def count(items, choose):
    fixed = broken = wrong = right = reach = 0
    for it in items:
        before = is_right(it["out"], it["answers"])
        after = is_right(choose(it), it["answers"])
        right += before
        wrong += not before
        if not before and it["segs"] is not None and good_sets(it["segs"], it["answers"]) is not None:
            reach += 1
        fixed += (not before) and after
        broken += before and not after
    return {"fixed": fixed, "broken": broken, "wrong": wrong, "right": right, "reach": reach}


# ---- 主 ----

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--material", required=True)
    ap.add_argument("--repo", default=str(HERE.parent))
    ap.add_argument("--table", required=True)
    ap.add_argument("--model", default="lr", choices=["lr", "tree", "gbdt"])
    ap.add_argument("--out")
    ap.add_argument("--weights")
    ap.add_argument("--seed", type=int, default=20261017)
    args = ap.parse_args()
    import numpy as np
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.tree import DecisionTreeClassifier, export_text

    table = rv.load_table(args.table)
    answers = read_answers(args.repo, args.material)
    groups = sorted(p.stem for p in Path(args.material).glob("*.tsv")
                    if p.stem != "train" and not p.stem.startswith("romanji"))
    data = {g: load_group(args.material, g, answers, table) for g in groups}
    train_items = [it for g in groups if g.startswith("t") for it in data[g]]
    rng = random.Random(args.seed)
    rng.shuffle(train_items)
    cut = len(train_items) * 4 // 5
    fit_items, val_items = train_items[:cut], train_items[cut:]
    rows = [r for it in fit_items for r in examples(it)]
    X = np.array([r[0] for r in rows], dtype=float)
    y = np.array([r[1] for r in rows])
    lines = []
    say = lambda s="": (lines.append(s), print(s))  # noqa: E731
    have = sum(1 for it in train_items if it["segs"] is not None)
    say(f"学習用の文 {len(train_items)}（候補の記録あり {have}）、学習 {len(fit_items)} 文・確かめ {len(val_items)} 文")
    say(f"学習の例 {len(y)}（替えるのが正しい {int(y.sum())}）、特徴 {X.shape[1]} 個、選び手 {args.model}")

    if args.model == "lr":
        scaler = StandardScaler().fit(X)
        clf = LogisticRegression(C=0.3, max_iter=3000).fit(scaler.transform(X), y)

        def prob(feats):
            return clf.predict_proba(scaler.transform(np.array(feats, dtype=float)))[:, 1]
    elif args.model == "tree":
        clf = DecisionTreeClassifier(max_depth=5, min_samples_leaf=20, random_state=0).fit(X, y)

        def prob(feats):
            return clf.predict_proba(np.array(feats, dtype=float))[:, 1]
    else:
        clf = GradientBoostingClassifier(n_estimators=150, max_depth=3, learning_rate=0.1,
                                         subsample=0.8, random_state=0).fit(X, y)

        def prob(feats):
            return clf.predict_proba(np.array(feats, dtype=float))[:, 1]

    thresholds = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95]
    sets = [("確かめ（学習用の残り2割）", val_items),
            ("ja400", data.get("ja400", [])), ("jaen（270+200b）", data.get("jaen", [])),
            ("wiki-typing", [it for g in groups if g.startswith("w") for it in data[g]]),
            ("context（前の文あり）", [it for g in groups if g.startswith("x") for it in data[g]])]
    say("\n組ごと: 間違い（うち候補から組める）/ 正しい、Zenz だけ（段階1）の 直る/壊れる、しきい値ごとの 直る/壊れる")
    say("組\t間違い(組める)/正しい\tZenzだけ\t" + "\t".join(f"≥{t}" for t in thresholds))
    totals = {t: [0, 0] for t in thresholds}
    for name, items in sets:
        if not items:
            continue
        base = count(items, zenz_only)
        cells = []
        for t in thresholds:
            r = count(items, lambda it, t=t: apply_selector(it, prob, t))
            cells.append(f"{r['fixed']}/{r['broken']}")
            if not name.startswith("確かめ"):
                totals[t][0] += r["fixed"]
                totals[t][1] += r["broken"]
        say(f"{name}\t{base['wrong']}({base['reach']})/{base['right']}\t{base['fixed']}/{base['broken']}\t" + "\t".join(cells))
    say("試験の合計\t\t\t" + "\t".join(f"{a}/{b}" for a, b in totals.values()))

    if args.model == "lr":
        names = FEATURE_NAMES
        w = sorted(zip(names, clf.coef_[0]), key=lambda x: -abs(x[1]))
        say("\n重みの大きい特徴（標準化した後）: " + "、".join(f"{n} {v:+.2f}" for n, v in w[:12]))
        if args.weights:
            Path(args.weights).write_text(json.dumps({
                "features": names, "mean": scaler.mean_.round(6).tolist(), "scale": scaler.scale_.round(6).tolist(),
                "coef": clf.coef_[0].round(6).tolist(), "intercept": float(round(clf.intercept_[0], 6))},
                ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    elif args.model == "tree":
        say("\n" + export_text(clf, feature_names=FEATURE_NAMES, max_depth=5))
    else:
        imp = sorted(zip(FEATURE_NAMES, clf.feature_importances_), key=lambda x: -x[1])
        say("\n効いた特徴: " + "、".join(f"{n} {v:.3f}" for n, v in imp[:12]))
    if args.out:
        Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
