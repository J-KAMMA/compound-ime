"""latency_report.py <結果のフォルダー> [ファイルの頭 (既定 latency-)]

tools/latency_convert.sh が書いた <名前>.profile.tsv（段ごとの時間）、<名前>.wall（空白キーの1回ごとの時間、ミリ秒）、
<名前>.keyus（空白キーの始まりと終わりの時計の値、マイクロ秒）を集計して、変換1回の時間の中央値と90%点、
段ごとの割合、評価の回数と1回の時間を出す。記録の形は tools/apply_latency_profile.py の説明を参照。
時間はミリ秒で出す。

段の分け方（変換 conv の1回について）:
  空白キーを押してから結果が返るまで（wall、keyus がなければ入り口の全体）
    入り口より前（Mozc とセッションの前処理）、入り口より後（書き換え・候補一覧の作成など）: keyus があるとき
    入り口の全体: total_us
      Mozc の変換: mozc_us
      人工知能側の変換エンジンの呼び出し: dll_us（回数 dll_n）
        all_zenzai（格子の構築と全文の評価）: allz_us（うち llama.cpp の評価 allz_dec_us、回数 allz_dec_n）
        候補作り（processResult から並べ替えを除く）: proc_us - ctx_us
        contextPriorWinner（前後の文を使った候補の並べ替え）: ctx_us（うち評価 ctx_dec_us、回数 ctx_dec_n）
        打ち間違いの補正: typo_us
        Swift の残り（候補の JSON 作りなど）: call_us - sel_us - allz_us - proc_us - typo_us
        受け渡し（C++ と Swift の間、鍵待ちなど）: dll_us - (call_us - sel_us)
      選び手: sel_cpp_us（うち人工知能の採点 sel_us）
      その他: total_us から上の3つを引いた残り
各変換の最初の 5 回（模型の読み込みなどで遅い）は除く。
"""
import glob
import os
import sys

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
    allz, ctx, typo, proc = g(row, "allz_us"), g(row, "ctx_us"), g(row, "typo_us"), g(row, "proc_us")
    dll, call, sel_ai = g(row, "dll_us"), g(row, "call_us"), g(row, "sel_us")
    sel_cpp = g(row, "sel_cpp_us")
    mozc = g(row, "mozc_us")
    total = g(row, "total_us")
    swift_call = max(0, call - sel_ai)  # 選び手の入り口を除いた、変換の呼び出しの Swift 側の時間
    return {
        "total": total,
        "mozc": mozc,
        "dll": dll,
        "allz": allz,
        "allz_dec": g(row, "allz_dec_us"),
        "proc_rest": max(0, proc - ctx),
        "ctx": ctx,
        "ctx_dec": g(row, "ctx_dec_us"),
        "typo": typo,
        "swift_rest": max(0, swift_call - allz - proc - typo),
        "boundary": max(0, dll - swift_call),
        "sel": sel_cpp,
        "sel_ai": sel_ai,
        "other": max(0, total - mozc - dll - sel_cpp),
    }


ROWS = [
    ("入り口の全体", "total", 0),
    ("Mozc の変換", "mozc", 1),
    ("人工知能側の変換エンジンの呼び出し（合計）", "dll", 1),
    ("all_zenzai（格子の構築と全文の評価）", "allz", 2),
    ("うち llama.cpp の評価", "allz_dec", 3),
    ("候補作り（並べ替えを除く）", "proc_rest", 2),
    ("contextPriorWinner（前後の文での並べ替え）", "ctx", 2),
    ("うち llama.cpp の評価", "ctx_dec", 3),
    ("打ち間違いの補正", "typo", 2),
    ("Swift の残り（候補の JSON 作りなど）", "swift_rest", 2),
    ("受け渡し（C++ と Swift の間）", "boundary", 2),
    ("選び手（C++ の処理と採点の合計）", "sel", 1),
    ("うち人工知能の採点", "sel_ai", 2),
    ("その他（先回りの待ちなど）", "other", 1),
]


def fit_cost(conv):
    """評価1回の固定費 a と語片1つあたり b を、変換ごとの (回数, 新しい語片, 時間) から最小二乗で求める。"""
    xs = []
    for r in conv:
        n = sum(g(r, p + "_dec_n") for p in ("allz", "ctx", "sel", "typo", "other"))
        new = sum(g(r, p + "_new") for p in ("allz", "ctx", "sel", "typo", "other"))
        us = sum(g(r, p + "_dec_us") for p in ("allz", "ctx", "sel", "typo", "other"))
        if n:
            xs.append((n, new, us / 1000))
    if len(xs) < 20:
        return None
    sxx = sum(n * n for n, _, _ in xs)
    sxy = sum(n * m for n, m, _ in xs)
    syy = sum(m * m for _, m, _ in xs)
    sxt = sum(n * t for n, _, t in xs)
    syt = sum(m * t for _, m, t in xs)
    det = sxx * syy - sxy * sxy
    if abs(det) < 1e-9:
        return None
    a = (sxt * syy - syt * sxy) / det
    b = (syt * sxx - sxt * sxy) / det
    return a, b


def describe(label, rows, wall, keyus):
    conv_all = [r for r in rows if r.get("kind") == "conv"]
    conv = conv_all[SKIP_FIRST:]
    out = [f"## {label}"]
    if not conv:
        return out + ["変換の記録なし", ""]
    parts = [breakdown(r) for r in conv]
    totals = [p["total"] / 1000 for p in parts]
    over = sum(1 for t in totals if t > 1000)
    out.append(f"変換 {len(conv)} 回。入り口の全体の時間: 中央値 {pct(totals, .5):.0f} ミリ秒、90%点 {pct(totals, .9):.0f}、"
               f"平均 {sum(totals) / len(totals):.0f}、最長 {max(totals):.0f}。1000 ミリ秒を超えた変換 {over} 回（{100 * over / len(totals):.1f}%）")
    if wall:
        w = wall[SKIP_FIRST:] or wall
        out.append(f"空白キーを押してから返るまで（TIMED_KEY）: 中央値 {pct(w, .5):.0f} ミリ秒、90%点 {pct(w, .9):.0f}、平均 {sum(w) / len(w):.0f}")
    pre, post = [], []
    if keyus and len(keyus) == len(conv_all):
        for r, (k0, k1) in zip(conv_all, keyus):
            pre.append((g(r, "t0_us") - k0) / 1000)
            post.append((k1 - g(r, "t1_us")) / 1000)
        pre, post = pre[SKIP_FIRST:], post[SKIP_FIRST:]
        out.append(f"空白キーの処理のうち入り口の外: 前 中央値 {pct(pre, .5):.1f}（90%点 {pct(pre, .9):.1f}）、"
                   f"後 中央値 {pct(post, .5):.1f}（90%点 {pct(post, .9):.1f}）ミリ秒")
    elif keyus:
        out.append(f"（keyus {len(keyus)} 行と変換 {len(conv_all)} 回が合わないので、入り口の外の前後は出さない）")
    grand = sum(p["total"] for p in parts) or 1
    out.append("")
    out.append("| 段（入り口の全体に対する割合） | 平均 ミリ秒 | 割合 | 中央値 | 90%点 |")
    out.append("|---|---:|---:|---:|---:|")
    for name, key, depth in ROWS:
        values = [p[key] / 1000 for p in parts]
        share = 100 * sum(p[key] for p in parts) / grand
        out.append(f"| {'　' * depth}{name} | {sum(values) / len(values):.1f} | {share:.1f}% | {pct(values, .5):.1f} | {pct(values, .9):.1f} |")
    if pre:
        out.append(f"| （入り口の外）前 | {sum(pre) / len(pre):.1f} | - | {pct(pre, .5):.1f} | {pct(pre, .9):.1f} |")
        out.append(f"| （入り口の外）後 | {sum(post) / len(post):.1f} | - | {pct(post, .5):.1f} | {pct(post, .9):.1f} |")
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
        entered = sum(1 for r in conv if g(r, prefix + "_n") > 0)
        if n == 0:
            out.append(f"| {name} | 0 | 0 | 0 | - | - | - | - |")
            continue
        out.append(f"| {name}（段に入った変換 {100 * entered / len(conv):.0f}%） | {n / len(conv):.1f} | {pct(counts, .5):.0f} | {pct(counts, .9):.0f} | "
                   f"{us / n / 1000:.1f} | {new / n:.0f} | {tok / n:.0f} | {100 * (1 - new / max(1, tok)):.0f}% |")
    out.append(f"人工知能側の変換エンジンの呼び出し: 1変換あたり {sum(g(r, 'dll_n') for r in conv) / len(conv):.2f} 回")
    cost = fit_cost(conv)
    if cost:
        out.append(f"評価の時間の当てはめ（全部の段）: 1回ごとの固定費 {cost[0]:.1f} ミリ秒 + 新しく計算する語片1つあたり {cost[1] * 1000:.0f} マイクロ秒")
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
        out.append(f"打っている間の予測（pred）: {len(pred)} 回、1回の平均 {sum(pt) / len(pt):.1f} ミリ秒、90%点 {pct(pt, .9):.1f}、"
                   f"人工知能側の呼び出しは1回あたり平均 {sum(g(r, 'dll_n') for r in pred) / len(pred):.2f} 回")
    if other:
        ot = [g(r, "total_us") / 1000 for r in other]
        out.append(f"そのほかの入り口（other）: {len(other)} 回、1回の平均 {sum(ot) / len(ot):.1f} ミリ秒、"
                   f"人工知能側の呼び出しは1回あたり平均 {sum(g(r, 'dll_n') for r in other) / len(other):.2f} 回")
    if between:
        bt = sum(g(r, "call_us") for r in between) / 1000
        bd = sum(g(r, "allz_dec_n") + g(r, "ctx_dec_n") + g(r, "sel_dec_n") for r in between)
        out.append(f"入り口の外の裏の仕事（打っている間の先回り・確定時の学習など）: {len(between)} 回、変換エンジンの時間の合計 {bt:.0f} ミリ秒"
                   f"（変換1回あたり {bt / len(conv_all):.0f} ミリ秒）、評価 {bd} 回（変換1回あたり {bd / len(conv_all):.1f} 回）")
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
        keyus = []
        if os.path.exists(base + ".keyus"):
            for line in open(base + ".keyus"):
                a = line.split()
                if len(a) == 2 and a[0].isdigit() and a[1].isdigit():
                    keyus.append((int(a[0]), int(a[1])))
        text += describe(label, read_profile(path), wall, keyus)
    print("\n".join(text))
