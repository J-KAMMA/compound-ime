"""判定の門の机上の評価: しきい値ごとの「正解数」「生成に回る割合」「速さの見込み」を出す。

  python tools/jev-gate/gate_eval.py <試験の記録.jsonl.gz> [--pred 模型の出力.tsv] [--head need_k] [--select student|zenz|top1|model2|model2a]
        [--gate-ms 6] [--cand-ms 10] [--thresholds 0.5,0.35,0.25,0.15,0.1,0.05] [--by-set]

試験の記録は tools/jev_gate_build.py test が作る（run 39249431055 の候補と zenz の点、本線 v5 の出力、正解）。
模型の出力は tools/jev-gate/jevgate.py predict が書く。なければ基準の門だけを出す。

比べる門:
  zenz   今の zenz の最高点を1字あたりにした値が低いと生成に戻す（docs/jev-design.md の机上の見込み。再現の確認用。門自体が重い）
  oracle 答えを知っている門（生成が要る文だけを生成に回す。上限）
  模型   --head の確率が しきい値以上なら生成（v5 の出力）、未満なら生成なしの答え
生成なしの答えの選び方（--select）:
  student 模型の候補の点の最大（入力の上位 k 個から。IME で実際に使える形）
  zenz    zenz の点の最大（全部の候補から。模型の選び方の上限。IME では重くて使えない）
  top1    人工知能なしの出力
  model2  （答えを選ぶ頭 b。jevgate.py v4sel 以降の出力が要る）生成したあと、v5 の出力と候補 k 個の枠から、頭 b の度合いが最大のものを答えにする。
          生成しなかった文は student と同じ。生成のあとにもう一度、v5 の出力の枠を足して通す（docs/jev-gate.md の「答えを選ぶ頭」）
  model2a （頭 a）生成したあと、v5 の出力と候補の一番（人工知能なしの出力）の2つだけから頭 a で選ぶ。生成しなかった文は student と同じ
どの --select でも、頭 b・a の出力があれば「選び方の比べ」の表（同じ門のしきい値で、zenz・student・model2・model2a を並べる）を出す。
速さの見込み（1変換あたり）= 門 + 候補作り + 生成に回る割合 × 生成（all_zenzai）の平均時間。
生成の時間は docs/jev-design.md の GitHub 3スレッドの値（ja400 85.5、ウィキペディア 234.8、前の文なし 253.5、
前の文あり 334.6 ミリ秒）。門と候補作りの時間は引数（既定 門 6、候補作り 10）で、実測ではなく仮の値。
注意: 模型のしきい値は学習用の文（確かめ用）で決めてから使う。ここで試験の文を見て決めると本番より良く見える。
"""
import argparse
import gzip
import json
import sys
from pathlib import Path

GEN_MS = {"ja400": 85.5, "ctxw": 334.6, "ctxo": 253.5}
GEN_MS_DEFAULT = 234.8
GROUPS = [("ja400", ["ja400"]), ("jaen270", ["jaen270"]), ("jaen200b", ["jaen200b"]), ("typo150", ["typo150"]),
          ("typo150b", ["typo150b"]), ("reported", ["reported"]),
          ("wiki-typing", ["wikiw1", "wikiw2", "wikiw3", "wikiw4"]), ("context 前の文あり", ["ctxw"]),
          ("context 前の文なし", ["ctxo"]), ("colloquial", ["coll"]), ("domain", ["prog", "crypto"])]
GATES = ["need", "need_k", "need_top1", "harm_k"]


def load(path):
    op = gzip.open if str(path).endswith(".gz") else open
    with op(path, "rt", encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def load_pred(path):
    pred = {}
    for line in open(path, encoding="utf-8"):
        f = line.rstrip("\n").split("\t")
        tail = f[6:]
        sel = None
        if "|" in tail:  # 答えを選ぶ頭の出力: | 頭 a の確率, 頭 b の度合い（候補…、最後に v5 の出力）
            at = tail.index("|")
            vals = [float(x) for x in tail[at + 1:]]
            sel = (vals[0], vals[1:])
            tail = tail[:at]
        pred[f[0]] = ([float(x) for x in f[1:5]], int(f[5]), [float(x) for x in tail], sel)
    return pred


def ok(text, r):
    if r.get("fold"):
        return text.lower() in [a.lower() for a in r["answers"]]
    return text in r["answers"]


def prepare(recs, pred, head, select):
    """文ごとに (生成なしの答えが正解か, 生成したときの答えが正解か, 門の値, 生成の平均時間, 集合名) を作る。
    gen_ok は、生成したあとの答えの正解（select が model2 / model2a のときだけ v5 の出力と違うことがある）。
    ほかに比べ用に student_ok・gen_b_ok・gen_a_ok（選び方の比べの表で使う）を持つ"""
    rows = []
    hi = GATES.index(head) if head else None
    for r in recs:
        sel = r["sel"]
        p = pred.get(r["id"])
        k = len(p[2]) if p else 0
        if p and k:
            student = r["cands"][:k][p[1]][0]
        else:
            student = r["noai"]
        if select == "top1":
            alt = r["noai"]
        elif select in ("student", "model2", "model2a") and p:
            alt = student
        else:
            alt = sel
        v5_ok = int(ok(r["v5"], r))
        gen_b = gen_a = v5_ok
        if p and p[3] is not None and k:
            pair, items = p[3]
            texts = [c[0] for c in r["cands"][:k]] + [r["v5"]]
            gen_b = int(ok(texts[max(range(len(texts)), key=lambda i: items[i])], r))
            gen_a = int(ok(r["v5"] if pair >= 0.5 else r["cands"][0][0], r))
        elif select in ("model2", "model2a"):
            sys.exit("答えを選ぶ頭の出力がありません（--pred に v4sel 以降の模型の出力が要ります）")
        best = max(c[1] for c in r["cands"])
        pc = best / (len(sel) + 1)  # 1字あたり（文の終わりの記号を数に入れる。docs/jev-design.md の机上の値と合う）
        score = p[0][hi] if (head and p) else None
        name = r.get("set", r["id"].split(":")[0])
        gen_ok = {"model2": gen_b, "model2a": gen_a}.get(select, v5_ok)
        rows.append(dict(alt_ok=int(ok(alt, r)), sel_ok=int(ok(sel, r)), v5_ok=v5_ok, gen_ok=gen_ok, need=r["need"], pc=pc, gate=score,
                         ms=GEN_MS.get(name, GEN_MS_DEFAULT), set=name, student_ok=int(ok(student, r)), gen_b_ok=gen_b, gen_a_ok=gen_a,
                         has_sel=bool(p and p[3] is not None)))
    return rows


def run_gate(rows, gen_flags, gate_ms, cand_ms, alt="alt_ok", gen="gen_ok"):
    n = len(rows)
    correct = sum(r[gen] if g else r[alt] for r, g in zip(rows, gen_flags))
    share = sum(gen_flags) / n
    ms = sum(gate_ms + cand_ms + (r["ms"] if g else 0) for r, g in zip(rows, gen_flags)) / n
    return correct, share, ms


def by_share(rows, key, shares, gate_ms, cand_ms, descending, alt="alt_ok", gen="gen_ok"):
    """key の大きい（descending）か小さい順に、上位 share の割合を生成に回す"""
    order = sorted(range(len(rows)), key=lambda i: rows[i][key], reverse=descending)
    out = []
    for s in shares:
        flags = [False] * len(rows)
        for i in order[:int(round(s * len(rows)))]:
            flags[i] = True
        out.append(run_gate(rows, flags, gate_ms, cand_ms, alt, gen))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("records")
    ap.add_argument("--pred")
    ap.add_argument("--head", default="need_k", choices=GATES)
    ap.add_argument("--select", default="student", choices=["student", "zenz", "top1", "model2", "model2a"])
    ap.add_argument("--gate-ms", type=float, default=6.0)
    ap.add_argument("--cand-ms", type=float, default=10.0)
    ap.add_argument("--thresholds", default="0.6,0.5,0.4,0.3,0.25,0.2,0.15,0.1,0.07,0.05,0.03")
    ap.add_argument("--by-set", action="store_true")
    a = ap.parse_args()
    recs = load(a.records)
    pred = load_pred(a.pred) if a.pred else {}
    if a.pred and not any(r["id"] in pred for r in recs):
        sys.exit("模型の出力の id が記録と合いません")
    use_model = bool(pred)
    rows = prepare(recs, pred, a.head if use_model else None, a.select)
    n = len(rows)
    v5 = sum(r["v5_ok"] for r in rows)
    alt = sum(r["alt_ok"] for r in rows)
    always_ms = sum(r["ms"] for r in rows) / n
    print(f"## 机上の評価（{n} 文）。生成なしの答えの選び方: {a.select}、模型の頭: {a.head if use_model else '（なし）'}\n")
    print(f"- v5（いつも生成）: 正解 {v5}、1変換の平均 {always_ms:.1f} ms（生成だけ）")
    sel_all = sum(r["sel_ok"] for r in rows)
    print(f"- 生成なしの答えだけ（生成に戻さない）: 正解 {alt}（v5 との差 {alt - v5:+d}）。zenz の最大を選ぶと {sel_all}（{sel_all - v5:+d}）")
    print(f"- 門 {a.gate_ms} ms、候補作り {a.cand_ms} ms は仮の値。生成の時間は GitHub 3スレッドの測定値（ja400 85.5、ほか 234.8 など）\n")

    shares = [0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5]
    print("### 生成に回す割合を決めたときの正解数（門の優劣の比べ。同じ割合で、どれだけ正解が残るか）\n")
    header = "| 生成に回す割合 | 答えを知っている門（上限。zenz の最大を選ぶ） | zenz の1字あたりの点（zenz の最大を選ぶ） |"
    sep = "|---:|---:|---:|"
    cols = [by_share(rows, "need", shares, 0, a.cand_ms, True, "sel_ok", "v5_ok"),
            by_share(rows, "pc", shares, 0, a.cand_ms, False, "sel_ok", "v5_ok")]
    if use_model:
        header += f" 模型 {a.head} |"
        sep += "---:|"
        cols.append(by_share(rows, "gate", shares, a.gate_ms, a.cand_ms, True))
    print(header)
    print(sep)
    for i, s in enumerate(shares):
        print(f"| {100 * s:.0f}% | " + " | ".join(f"{c[i][0]}（{c[i][0] - v5:+d}）" for c in cols) + " |")

    print("\n### zenz の1字あたりの点の門（docs/jev-design.md の机上の見込みの再現。-0.1 で 4,823 正解・16%）\n")
    print("| しきい値（これ未満なら生成） | 正解 | v5 との差 | 生成の割合 |")
    print("|---:|---:|---:|---:|")
    for th in (-0.2, -0.15, -0.1, -0.075, -0.05, -0.03):
        flags = [r["pc"] < th for r in rows]
        c, sh, _ = run_gate(rows, flags, 0, a.cand_ms, "sel_ok", "v5_ok")
        print(f"| {th} | {c} | {c - v5:+d} | {100 * sh:.1f}% |")

    if use_model:
        print(f"\n### 模型 {a.head} のしきい値ごと（しきい値以上なら生成。答えの選び方 {a.select}）\n")
        print("| しきい値 | 正解 | v5 との差 | 生成の割合 | 速さの見込み（1変換 ms） | いつも生成との比 |")
        print("|---:|---:|---:|---:|---:|---:|")
        for th in [float(x) for x in a.thresholds.split(",")]:
            flags = [r["gate"] >= th for r in rows]
            c, sh, ms = run_gate(rows, flags, a.gate_ms, a.cand_ms)
            print(f"| {th} | {c} | {c - v5:+d} | {100 * sh:.1f}% | {ms:.1f} | {ms / always_ms:.2f} |")
        if all(r["has_sel"] for r in rows):
            print(f"\n### 選び方の比べ（門は模型 {a.head}、しきい値以上なら生成。生成したあとの答えの選び方を変える。生成しない文は、zenz は zenz の最大、ほかは student）\n")
            print("| しきい値 | 生成の割合 | v5 のまま | zenz の最大（上限・重い） | student（今） | model2 頭 b | model2a 頭 a |")
            print("|---:|---:|---:|---:|---:|---:|---:|")
            for th in [0.0] + [float(x) for x in a.thresholds.split(",")]:
                flags = [r["gate"] >= th for r in rows]
                cs = [run_gate(rows, flags, a.gate_ms, a.cand_ms, alt, g)[0] for alt, g in
                      (("student_ok", "v5_ok"), ("sel_ok", "v5_ok"), ("student_ok", "v5_ok"), ("student_ok", "gen_b_ok"), ("student_ok", "gen_a_ok"))]
                share = sum(flags) / n
                print(f"| {th} | {100 * share:.1f}% | " + " | ".join(f"{c}（{c - v5:+d}）" for c in cs) + " |")
            ub = sum(max(r["v5_ok"], r["student_ok"]) for r in rows)
            print(f"\n- 参考: 全部生成して選ぶと、頭 b で {sum(r['gen_b_ok'] for r in rows)}、頭 a で {sum(r['gen_a_ok'] for r in rows)}（v5 {v5}）。"
                  f"v5 か student のうち正しいほうを選べる上限は {ub}")
        if a.by_set:
            th = float(a.thresholds.split(",")[len(a.thresholds.split(",")) // 2])
            print(f"\n### 試験ごと（しきい値 {th}）\n")
            print("| 試験 | 文 | v5 正解 | 門の正解 | 差 | 生成の割合 |")
            print("|---|---:|---:|---:|---:|---:|")
            for label, names in GROUPS:
                rs = [r for r in rows if r["set"] in names]
                if not rs:
                    continue
                flags = [r["gate"] >= th for r in rs]
                c, sh, _ = run_gate(rs, flags, a.gate_ms, a.cand_ms)
                b = sum(r["v5_ok"] for r in rs)
                print(f"| {label} | {len(rs)} | {b} | {c} | {c - b:+d} | {100 * sh:.1f}% |")


if __name__ == "__main__":
    main()
