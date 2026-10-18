"""latency_report.py <結果のフォルダー> [ファイルの頭 (既定 latency-)]

tools/latency_convert.sh が書いた <名前>.profile.tsv（段ごとの時間）と <名前>.wall（空白キーの1回ごとの時間）を
集計して、変換1回の時間の中央値と90%点、段ごとの割合、評価の回数と1回の時間を出す。
記録の形は tools/apply_latency_profile.py の説明を参照。時間はミリ秒で出す。

段の分け方（変換 conv の1回について）:
  Mozc の変換: mozc_us
  人工知能側の変換エンジンの呼び出し: dll_us（回数 dll_n）
    うち all_zenzai: allz_us（うち llama.cpp の評価 allz_dec_us、回数 allz_dec_n）
    うち contextPriorWinner（前後の文を使った候補の並べ替え）: ctx_us（うち評価 ctx_dec_us、回数 ctx_dec_n）
    うち 打ち間違いの補正: typo_us
    うち 辞書の格子・候補作り・受け渡しなど（残り）
  選び手: sel_cpp_us（うち人工知能の採点 sel_us）
  その他: total_us から上の3つを引いた残り（Mozc の後処理・書き換え・先回りの待ちなど）
各変換の最初の 5 回（模型の読み込みなどで遅い）は除く。
"""
import glob
import os
import sys
from collections import defaultdict

SKIP_FIRST = 5


def pct(values, q):
    if not values:
        return 0.0
    s = sorted(values)
    return s[min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))]


def read_profile(path):
    rows = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            fields = {}
            for part in line.rstrip("\n").split("\t"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    try:
                        fields[k] = int(v)
                    except ValueError:
                        fields[k] = v
            if fields:
                rows.append(fields)
    return rows


def g(row, key):
    value = row.get(key, 0)
    return value if isinstance(value, int) else 0


def breakdown(row):
    allz, ctx, typo = g(row, "allz_us"), g(row, "ctx_us"), g(row, "typo_us")
    dll = g(row, "dll_us")
    sel_cpp = g(row, "sel_cpp_us")
    mozc = g(row, "mozc_us")
    total = g(row, "total_us")
    return {
        "total": total,
        "mozc": mozc,
        "dll": dll,
        "allz": allz,
        "allz_dec": g(row, "allz_dec_us"),
        "ctx": ctx,
        "ctx_dec": g(row, "ctx_dec_us"),
        "typo": typo,
        "dll_rest": max(0, dll - allz - ctx - typo),
        "sel": sel_cpp,
        "sel_ai": g(row, "sel_us"),
        "other": max(0, total - mozc - dll - sel_cpp),
    }


ROWS = [
    ("全体", "total", 0),
    ("Mozc の変換", "mozc", 0),
    ("人工知能側の変換エンジンの呼び出し（合計）", "dll", 0),
    ("all_zenzai（全文の変換）", "allz", 1),
    ("llama.cpp の評価（all_zenzai の中）", "allz_dec", 2),
    ("contextPriorWinner（前後の文での並べ替え）", "ctx", 1),
    ("llama.cpp の評価（並べ替えの中）", "ctx_dec", 2),
    ("打ち間違いの補正", "typo", 1),
    ("辞書の格子・候補作り・受け渡しなど", "dll_rest", 1),
    ("選び手（C++ の処理と採点の合計）", "sel", 0),
    ("人工知能の採点（選び手の中）", "sel_ai", 2),
    ("その他（Mozc の後処理・先回りの待ちなど）", "other", 0),
]


def describe(label, rows, wall):
    conv = [r for r in rows if r.get("kind") == "conv"][SKIP_FIRST:]
    out = [f"## {label}"]
    if not conv:
        return out + ["変換の記録なし", ""]
    parts = [breakdown(r) for r in conv]
    totals = [p["total"] / 1000 for p in parts]
    out.append(f"変換 {len(conv)} 回。1回の時間（入り口の全体）: 中央値 {pct(totals, .5):.0f} ミリ秒、90%点 {pct(totals, .9):.0f}、"
               f"平均 {sum(totals) / len(totals):.0f}、最長 {max(totals):.0f}。1000 ミリ秒を超えた変換 "
               f"{sum(1 for t in totals if t > 1000)} 回（{100 * sum(1 for t in totals if t > 1000) / len(totals):.1f}%）")
    if wall:
        w = wall[SKIP_FIRST:] or wall
        out.append(f"空白キーを押してからの時間（TIMED_KEY、入り口の外の処理も含む）: 中央値 {pct(w, .5):.0f} ミリ秒、"
                   f"90%点 {pct(w, .9):.0f}、平均 {sum(w) / len(w):.0f}")
    grand = sum(p["total"] for p in parts) or 1
    out.append("")
    out.append("| 段 | 平均 ミリ秒 | 全体に対する割合 | 中央値 | 90%点 |")
    out.append("|---|---:|---:|---:|---:|")
    for name, key, depth in ROWS:
        values = [p[key] / 1000 for p in parts]
        share = 100 * sum(p[key] for p in parts) / grand
        out.append(f"| {'　' * depth}{name} | {sum(values) / len(values):.1f} | {share:.1f}% | {pct(values, .5):.1f} | {pct(values, .9):.1f} |")
    # 評価の回数と1回の時間
    out.append("")
    out.append("| 評価（llama_decode） | 1変換あたりの回数 平均 | 中央値 | 90%点 | 1回の平均 ミリ秒 | 1回に新しく計算した語片 | 渡した語片 | 使い回せた割合 |")
    out.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for name, prefix in (("all_zenzai", "allz"), ("contextPriorWinner", "ctx"), ("選び手", "sel"), ("打ち間違い", "typo")):
        counts = [g(r, prefix + "_dec_n") for r in conv]
        n = sum(counts)
        us = sum(g(r, prefix + "_dec_us") for r in conv)
        new = sum(g(r, prefix + "_new") for r in conv)
        tok = sum(g(r, prefix + "_tok") for r in conv)
        calls = sum(g(r, prefix + "_n") for r in conv)
        if n == 0:
            out.append(f"| {name} | 0 | 0 | 0 | - | - | - | - |")
            continue
        out.append(f"| {name}（段に入った回数 平均 {calls / len(conv):.1f}） | {n / len(conv):.1f} | {pct(counts, .5):.0f} | {pct(counts, .9):.0f} | "
                   f"{us / n / 1000:.1f} | {new / n:.0f} | {tok / n:.0f} | {100 * (1 - new / max(1, tok)):.0f}% |")
    out.append(f"人工知能側の変換エンジンの呼び出し: 1変換あたり {sum(g(r, 'dll_n') for r in conv) / len(conv):.1f} 回")
    # 読みの長さ別
    out.append("")
    out.append("読みの長さ別（字数）:")
    out.append("| 読みの字数 | 回数 | 中央値 ミリ秒 | 90%点 | all_zenzai の割合 | 並べ替えの割合 | 選び手の割合 | Mozc の割合 |")
    out.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    buckets = [("1〜4", 1, 4), ("5〜8", 5, 8), ("9〜16", 9, 16), ("17〜32", 17, 32), ("33〜", 33, 10 ** 9)]
    for name, lo, hi in buckets:
        idx = [i for i, r in enumerate(conv) if lo <= g(r, "key_chars") <= hi]
        if not idx:
            continue
        sub = [parts[i] for i in idx]
        t = sum(p["total"] for p in sub) or 1
        ts = [p["total"] / 1000 for p in sub]
        out.append(f"| {name} | {len(sub)} | {pct(ts, .5):.0f} | {pct(ts, .9):.0f} | {100 * sum(p['allz'] for p in sub) / t:.0f}% | "
                   f"{100 * sum(p['ctx'] for p in sub) / t:.0f}% | {100 * sum(p['sel'] for p in sub) / t:.0f}% | "
                   f"{100 * sum(p['mozc'] for p in sub) / t:.0f}% |")
    # 打っている間と裏の仕事
    pred = [r for r in rows if r.get("kind") == "pred"]
    between = [r for r in rows if r.get("kind") == "between"]
    other = [r for r in rows if r.get("kind") == "other"]
    out.append("")
    if pred:
        pt = [g(r, "total_us") / 1000 for r in pred]
        out.append(f"打っている間の予測（pred）: {len(pred)} 回、1回の平均 {sum(pt) / len(pt):.1f} ミリ秒、中央値 {pct(pt, .5):.1f}、"
                   f"90%点 {pct(pt, .9):.1f}、評価の回数は1回あたり平均 "
                   f"{sum(g(r, 'allz_dec_n') + g(r, 'ctx_dec_n') for r in pred) / len(pred):.2f}、"
                   f"人工知能側の呼び出しは平均 {sum(g(r, 'dll_n') for r in pred) / len(pred):.2f} 回")
    if other:
        ot = [g(r, "total_us") / 1000 for r in other]
        out.append(f"そのほかの入り口（other）: {len(other)} 回、1回の平均 {sum(ot) / len(ot):.1f} ミリ秒")
    if between:
        bt = sum(g(r, "call_us") for r in between) / 1000
        out.append(f"入り口の外の裏の仕事（先回り・確定時の学習など）: {len(between)} 回、変換エンジンの時間の合計 {bt:.0f} ミリ秒"
                   f"（変換1回あたり {bt / len(conv):.1f} ミリ秒）")
    out.append("")
    return out


if __name__ == "__main__":
    folder = sys.argv[1]
    head = sys.argv[2] if len(sys.argv) > 2 else "latency-"
    names = sorted(glob.glob(os.path.join(folder, head + "*.profile.tsv")))
    if not names:
        print("段ごとの時間の記録なし")
        sys.exit(0)
    text = ["# 変換1回の時間（段ごと）", ""]
    env = os.path.join(folder, head + "env.txt")
    if os.path.exists(env):
        text += ["計算機: " + open(env, encoding="utf-8").read().strip().replace("\n", " / "), ""]
    for path in names:
        base = path[: -len(".profile.tsv")]
        label = os.path.basename(base)[len(head):]
        wall = []
        if os.path.exists(base + ".wall"):
            wall = [int(x) for x in open(base + ".wall").read().split() if x.isdigit()]
        text += describe(label, read_profile(path), wall)
    print("\n".join(text))
