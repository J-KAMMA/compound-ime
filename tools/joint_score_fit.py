"""合わせた物差し（辞書の点数と人工知能の確からしさを一つにして文を選ぶ）の見込みを、書き出した材料で測る。

  python tools/joint_score_fit.py <results dir> [--export 重み.json]

<results dir> は組 e8 の成果物（joint-wiki.txt と wiki-typing-dump.tsv、確かめ用の joint-holdout.txt ほか）。
材料の1行（MYIME_JOINT_DUMP、tools/apply_jaen_integration.py の DumpJointFeatures）:
  J<TAB>読み<TAB>前後の文の有無<TAB>文節の数<TAB>Mozc の1位の文<TAB>その費用の和<TAB>その対数確率<TAB>候補…
候補は「表記、対数確率、当てはめ、Mozc の順位の和、替えた文節の数、費用の差、消える固有名・カタカナ語、増えるカタカナ、字数」
を U+0002 で区切ったもの。当てはめ: M（文節の候補で書ける）、U（書けるが固有名をかなにする）、V（使えない）、
R（組み直しで書ける）、F<番号>（組み直しを断る）、F<番号>L（断る決まりを外せば組み直せる）、X（試さない）。

今の選び方（人工知能の順に、M か、1位だけ R なら採る。1位がかなだけなら Mozc のまま）を材料から再現し、
実際の出力と合うかを確かめてから、合わせた物差し（Mozc のまま＝0点、候補 i は w・特徴）で選んだときに
何文良く・悪くなるかを数える。重みは条件付きロジット（候補の中から正しい文を選ぶ確率）で学ぶ。
ウィキペディアの文は前半・後半（組 e1・e2）で交差に確かめ、最後に学習に使わない表で下がらないかを見る。
"""
import argparse
import json
import math
import random
import re
import sys
from pathlib import Path

import numpy as np

# ---- ローマ字 → かな（Mozc の既定の表のうち、試験の文に出る範囲） ----
_V = "aiueo"
_ROWS = {
    "": "あいうえお", "k": "かきくけこ", "g": "がぎぐげご", "s": "さしすせそ", "z": "ざじずぜぞ",
    "t": "たちつてと", "d": "だぢづでど", "n": "なにぬねの", "h": "はひふへほ", "b": "ばびぶべぼ",
    "p": "ぱぴぷぺぽ", "m": "まみむめも", "r": "らりるれろ", "l": "ぁぃぅぇぉ", "x": "ぁぃぅぇぉ",
}
TABLE = {}
for c, kana in _ROWS.items():
    for v, k in zip(_V, kana):
        TABLE[c + v] = k
TABLE.update({"ya": "や", "yu": "ゆ", "yo": "よ", "ye": "いぇ", "wa": "わ", "wo": "を", "wi": "うぃ", "we": "うぇ",
              "shi": "し", "chi": "ち", "tsu": "つ", "fu": "ふ", "ji": "じ", "si": "し", "ti": "ち", "tu": "つ",
              "hu": "ふ", "zi": "じ", "di": "ぢ", "du": "づ", "nn": "ん", "n'": "ん", "xn": "ん",
              "fa": "ふぁ", "fi": "ふぃ", "fe": "ふぇ", "fo": "ふぉ", "va": "ゔぁ", "vi": "ゔぃ", "vu": "ゔ",
              "ve": "ゔぇ", "vo": "ゔぉ", "ja": "じゃ", "ju": "じゅ", "jo": "じょ", "je": "じぇ",
              "sha": "しゃ", "shu": "しゅ", "sho": "しょ", "she": "しぇ", "cha": "ちゃ", "chu": "ちゅ",
              "cho": "ちょ", "che": "ちぇ", "tsa": "つぁ", "thi": "てぃ", "dhi": "でぃ", "twu": "とぅ",
              "dwu": "どぅ", "thu": "てゅ", "dhu": "でゅ", "wha": "うぁ", "whi": "うぃ", "whe": "うぇ", "who": "うぉ",
              "ltu": "っ", "xtu": "っ", "lya": "ゃ", "lyu": "ゅ", "lyo": "ょ", "xya": "ゃ", "xyu": "ゅ", "xyo": "ょ",
              "kwa": "くぁ", "gwa": "ぐぁ", "tsi": "つぃ", "tse": "つぇ", "tso": "つぉ", "-": "ー",
              ",": "、", ".": "。", "!": "！", "?": "？", "~": "〜", "[": "「", "]": "」", "/": "・"})
for c, base in (("ky", "き"), ("gy", "ぎ"), ("sy", "し"), ("zy", "じ"), ("ty", "ち"), ("dy", "ぢ"), ("ny", "に"),
                ("hy", "ひ"), ("by", "び"), ("py", "ぴ"), ("my", "み"), ("ry", "り"), ("jy", "じ"), ("cy", "ち")):
    for v, small in (("a", "ゃ"), ("u", "ゅ"), ("o", "ょ"), ("i", "ぃ"), ("e", "ぇ")):
        TABLE[c + v] = base + small
_LONGEST = max(map(len, TABLE))


def to_kana(raw):
    out, i = [], 0
    while i < len(raw):
        ch = raw[i]
        if ch == "n" and (i + 1 == len(raw) or raw[i + 1] not in "aiueoyn'"):
            out.append("ん"); i += 1; continue
        if i + 1 < len(raw) and ch == raw[i + 1] and ch.isalpha() and ch not in "aiueon":
            out.append("っ"); i += 1; continue
        for size in range(min(_LONGEST, len(raw) - i), 0, -1):
            if raw[i:i + size] in TABLE:
                out.append(TABLE[raw[i:i + size]]); i += size; break
        else:
            out.append(ch); i += 1
    return "".join(out)


def norm_key(text):
    import unicodedata
    return unicodedata.normalize("NFKC", text).replace("、", ",").replace("。", ".")


# ---- 材料の読み込み ----
def read_dump(path):
    records = {}
    for line in open(path, encoding="utf-8", errors="replace"):
        cols = line.rstrip("\n").split("\t")
        if len(cols) < 7 or cols[0] != "J":
            continue
        rec = {"key": cols[1], "ctx": cols[2], "segs": int(cols[3]), "mozc": cols[4],
               "mozc_cost": int(cols[5]), "mozc_lp": float(cols[6]), "cands": []}
        for rank, item in enumerate(cols[7:]):
            f = item.split("\x02")
            if len(f) != 9:
                continue
            rec["cands"].append({"rank": rank, "value": f[0], "lp": float(f[1]), "fit": f[2],
                                 "rank_sum": int(f[3]), "changed": int(f[4]), "cost_delta": int(f[5]),
                                 "lost": int(f[6]), "extra": int(f[7]), "chars": int(f[8])})
        records[norm_key(rec["key"])] = rec  # 同じ読みが何度も来たら最後のもの
    return records


def read_cases(path):
    """試験の表: ローマ字 → 正しい文の集まり（tsv は2列目、json は intended と alternatives）"""
    cases = {}
    if str(path).endswith(".json"):
        for item in json.load(open(path, encoding="utf-8"))["items"]:
            cases[item["romaji"]] = {item["intended"], *item.get("alternatives", [])}
    else:
        for line in open(path, encoding="utf-8"):
            if line.startswith("#") or not line.strip():
                continue
            p = line.rstrip("\n").split("\t")
            cases[p[0]] = {p[1]}
    return cases


def read_out(path):
    got = {}
    for line in open(path, encoding="utf-8"):
        p = line.rstrip("\n").split("\t")
        if len(p) >= 3:
            got[p[0]] = p[2]
    return got


def kana_only(value):
    """今の選び方で人工知能の文を採らない、かなだけの文（engine.cc の katakana_with_symbols と同じ）"""
    hira = kata = 0
    for ch in value:
        c = ord(ch)
        if 0x30A1 <= c <= 0x30FA or c == 0x30FC:
            kata += 1; continue
        if (0x3400 <= c <= 0x4DBF or 0x4E00 <= c <= 0x9FFF or 0xF900 <= c <= 0xFAFF or c == 0x3005 or
                ch.isascii() and ch.isalnum() or 0xFF10 <= c <= 0xFF19 or 0xFF21 <= c <= 0xFF3A or 0xFF41 <= c <= 0xFF5A):
            return False
        hira += 0x3041 <= c <= 0x309F
    return hira == 0 if kata else hira >= 20


def current_choice(rec):
    """今の選び方: 選んだ文（Mozc のままなら None）"""
    for c in rec["cands"]:
        if kana_only(c["value"]):
            if c["rank"] == 0:
                return None
            continue
        if c["fit"] == "M" or (c["rank"] == 0 and c["fit"] == "R"):
            return c
    return None


# ---- 合わせた物差し ----
APPLICABLE = {"strict": lambda f: f in ("M", "R"),
              "lenient": lambda f: f in ("M", "R", "U") or (f.startswith("F") and f.endswith("L"))}


def features(rec, c, use_lp):
    lp_d = c["lp"] - rec["mozc_lp"] if use_lp else 0.0
    if not math.isfinite(lp_d):
        lp_d = 0.0
    fit = c["fit"]
    f = [
        1.0,                                   # 切片（Mozc のままより候補を採る気持ち）
        lp_d / 10.0,                           # 人工知能の対数確率の差（Mozc の1位の文と比べて）
        lp_d / max(c["chars"], 1),             # 1字あたりの差
        1.0 if c["rank"] == 0 else 0.0,        # 人工知能の1位
        math.log1p(c["rank"]),                 # 人工知能の順位
        1.0 if fit == "R" else 0.0,            # 組み直しで書ける
        1.0 if fit.endswith("L") else 0.0,     # 断る決まりを外して書ける
        1.0 if fit == "U" else 0.0,            # 固有名をかなにする
        min(c["rank_sum"], 20) / 10.0,         # Mozc の順位の和
        min(c["changed"], 10) / 5.0,           # 替えた文節の数
        max(min(c["cost_delta"], 20000), -20000) / 5000.0,  # Mozc の費用の差
        min(c["lost"], 3),                     # 消える固有名・カタカナ語
        min(max(c["extra"], 0), 10) / 5.0,     # 増えるカタカナ
        1.0 if kana_only(c["value"]) else 0.0, # かなだけ
    ]
    if not use_lp:
        f[1] = f[2] = 0.0
    return f


NAMES = ["切片", "対数確率の差/10", "1字あたりの差", "人工知能の1位", "log(1+順位)", "組み直し", "決まりを外す",
         "固有名をかな", "Mozc 順位の和/10", "替えた文節/5", "費用の差/5000", "消える名前", "増えるカタカナ/5", "かなだけ"]


def options(rec, mode, use_lp, top=20):
    """選べる候補（Mozc の1位と同じ文は除く）と特徴"""
    out = []
    seen = {rec["mozc"]}
    for c in rec["cands"][:top]:
        if c["value"] in seen or not APPLICABLE[mode](c["fit"]):
            continue
        seen.add(c["value"])
        out.append((c, features(rec, c, use_lp)))
    return out


def fit_weights(train, mode, use_lp, l2=0.3, iters=600):
    """条件付きロジット: 正しい文が候補か Mozc のままにあるときだけ学ぶ"""
    data = []
    for rec, answers in train:
        opts = options(rec, mode, use_lp)
        if not opts:
            continue
        label = 0 if rec["mozc"] in answers else None
        for i, (c, _) in enumerate(opts):
            if c["value"] in answers and label is None:
                label = i + 1
        if label is None:
            continue
        x = np.array([[0.0] * len(NAMES)] + [f for _, f in opts])
        data.append((x, label))
    w = np.zeros(len(NAMES))
    if not data:
        return w
    lr = 0.5
    for _ in range(iters):
        g = l2 * w
        for x, label in data:
            s = x @ w
            s -= s.max()
            p = np.exp(s); p /= p.sum()
            g += (x.T @ p - x[label]) / len(data)
        w -= lr * g
    return w


def choose(rec, w, mode, use_lp, margin=0.0):
    best, best_s = None, margin
    for c, f in options(rec, mode, use_lp):
        s = float(np.dot(w, f))
        if s > best_s:
            best, best_s = c, s
    return best


def evaluate(items, w, mode, use_lp, margin=0.0, show=0):
    """items: (rec または None, 正解の集まり, 実際の出力)。今と新しい選び方の正解数"""
    cur = new = better = worse = changed = unsure = 0
    examples = []
    for rec, answers, out in items:
        ok_now = out in answers
        cur += ok_now
        if rec is None:
            new += ok_now; continue
        now = current_choice(rec)
        pick = choose(rec, w, mode, use_lp, margin)
        now_v = now["value"] if now else rec["mozc"]
        pick_v = pick["value"] if pick else rec["mozc"]
        if pick_v == now_v:
            new += ok_now; continue
        changed += 1
        unsure += out != now_v  # 後の段で出力が変わっていた文（見込みは選んだ文のままとみなす）
        ok_new = pick_v in answers
        new += ok_new
        better += ok_new and not ok_now
        worse += ok_now and not ok_new
        if (ok_new != ok_now) and len(examples) < show:
            examples.append(f"  {'良' if ok_new else '悪'} {out} → {pick_v}")
    return {"cur": cur, "new": new, "better": better, "worse": worse, "changed": changed, "unsure": unsure,
            "examples": examples}


def load_set(results, dump, cases_path, out_name):
    dump_path = results / dump
    if not dump_path.exists():
        return None
    recs = read_dump(dump_path)
    cases = read_cases(cases_path)
    got = read_out(results / out_name)
    items, matched = [], 0
    for raw, answers in cases.items():
        if raw not in got:
            continue
        rec = recs.get(norm_key(to_kana(raw)))
        matched += rec is not None
        items.append((rec, answers, got[raw]))
    return items, matched, len(recs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results", type=Path)
    ap.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent.parent)
    ap.add_argument("--export", type=Path)
    ap.add_argument("--show", type=int, default=0)
    args = ap.parse_args()
    T = args.repo / "tests/conversion"
    wiki = load_set(args.results, "joint-wiki.txt", T / "wiki-typing.tsv", "wiki-typing-dump.tsv")
    items, matched, nrec = wiki
    print(f"ウィキペディア: {len(items)} 文、材料と結び付いた {matched} 文（材料 {nrec} 行）")
    # 今の選び方の再現の確かめ
    agree = total = 0
    for rec, answers, out in items:
        if rec is None:
            continue
        now = current_choice(rec)
        total += 1
        agree += out == (now["value"] if now else rec["mozc"])
    print(f"今の選び方の再現: 実際の出力と同じ {agree}/{total}")
    # 正解がどこにあるか
    where = {}
    for rec, answers, out in items:
        if rec is None:
            continue
        if out in answers:
            k = "今が正解"
        elif rec["mozc"] in answers:
            k = "Mozc の1位が正解"
        else:
            hit = next((c for c in rec["cands"] if c["value"] in answers), None)
            k = f"人工知能の{'1位' if hit and hit['rank'] == 0 else '2位以下' if hit else '候補にない'}" + \
                (f"（{hit['fit'][:2] if hit['fit'].startswith('F') else hit['fit']}{'L' if hit['fit'].endswith('L') else ''}）" if hit else "")
        where[k] = where.get(k, 0) + 1
    for k, v in sorted(where.items(), key=lambda kv: -kv[1]):
        print(f"  {k}: {v}")

    half = len(items) // 2
    folds = [(items[:half], items[half:]), (items[half:], items[:half])]
    rnd = random.Random(1)
    shuffled = items[:]; rnd.shuffle(shuffled)
    folds += [(shuffled[:half], shuffled[half:]), (shuffled[half:], shuffled[:half])]
    results = {}
    for mode in ("strict", "lenient"):
        for use_lp in (False, True):
            tag = f"{mode}{'+対数確率' if use_lp else ''}"
            tot = {"cur": 0, "new": 0, "better": 0, "worse": 0, "changed": 0, "unsure": 0}
            for i, (tr, te) in enumerate(folds):
                w = fit_weights([(r, a) for r, a, _ in tr if r], mode, use_lp)
                e = evaluate(te, w, mode, use_lp)
                for k in tot:
                    tot[k] += e[k]
            # 4つの折り（前半/後半、混ぜた半分×2）の合計を2で割ると全体の1回分
            print(f"[{tag}] 交差（全体1回分）: 今 {tot['cur']/2:.0f} → 新 {tot['new']/2:.0f}（{(tot['new']-tot['cur'])/2:+.1f}、"
                  f"良 {tot['better']/2:.1f}・悪 {tot['worse']/2:.1f}、替えた {tot['changed']/2:.0f}、うち後段で変わる {tot['unsure']/2:.0f}）")
            results[tag] = (mode, use_lp)
    # 全部で学んだ重みと、学習に使わない表での確かめ
    for tag, (mode, use_lp) in results.items():
        w = fit_weights([(r, a) for r, a, _ in items if r], mode, use_lp)
        print(f"[{tag}] 重み: " + "、".join(f"{n} {x:+.2f}" for n, x in zip(NAMES, w)))
        for name, dump, cases, out in (("確かめ用", "joint-holdout.txt", T / "holdout/holdout.json", "holdout-dump.tsv"),
                                       ("日本語400", "joint-ja400.txt", T / "ja400.json", "ja400-dump.tsv"),
                                       ("話し言葉", "joint-colloquial.txt", T / "colloquial.tsv", "colloquial-dump.tsv"),
                                       ("分野・プログラミング", "joint-domain-prog.txt", T / "domain-prog.tsv", "domain-prog-dump.tsv"),
                                       ("分野・仮想通貨", "joint-domain-crypto.txt", T / "domain-crypto.tsv", "domain-crypto-dump.tsv")):
            s = load_set(args.results, dump, cases, out)
            if not s:
                continue
            e = evaluate(s[0], w, mode, use_lp, show=args.show)
            print(f"    {name}: {len(s[0])} 文（材料 {s[1]}）今 {e['cur']} → 新 {e['new']}（良 {e['better']}・悪 {e['worse']}、替えた {e['changed']}）")
            for line in e["examples"]:
                print(line)
        if args.export and tag == "lenient+対数確率":
            args.export.write_text(json.dumps({"names": NAMES, "weights": [round(float(x), 4) for x in w]},
                                              ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
