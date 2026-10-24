"""長い文の変換の時間（読みの長さ別・段別）を集計する。

  python tools/long_latency_report.py <結果のフォルダー>

tools/run_tests.sh の組 w が書いた long-<組>-<条件>-r<回>.profile.tsv / .wall / .keyus /
.zstats.* を読む。組は読みの長さ（10・20・40・60・80・120 字ほど）、条件は
  plain       人工知能の時間の上限なし・打っている間の先回りなし（前の文なし）
  plain-ctx   同じ（前の文あり）
  split       句読点（. と ,）で分けた句を別々に変換（時間だけ。正解は見ない）
  real-pf     利用者の PC と同じ既定（上限 1000 ミリ秒・先回り 120 ミリ秒）で、1字 125 ミリ秒ずつ打つ
  real-nopf   同じで、先回りだけ止める（MYIME_PREFETCH_DELAY=0）
各回の最初の 5 変換は模型の読み込みとして捨てる。3 回以上の中央値と、回ごとのばらつきを出す。
段の分け方は tools/latency_report.py と同じで、一括採点（batch）は前後の文の並べ替えか選び手の
内側の時間を別に数える。prefill は「2語片以上をまとめて計算した評価」、decode は「1語片だけを
計算した評価」を指す（llama.cpp の評価の回数で分けたもの）。
案 (a)(b)(c) の見込みは、測った数字からの計算で、作ったものではない。
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from latency_report import SKIP_FIRST, breakdown, g, pct, read_profile  # noqa: E402
import zenzai_stats  # noqa: E402

BUCKETS = [10, 20, 40, 60, 80, 120]
MODES = {
    "plain": "上限なし・先回りなし（前の文なし）",
    "plain-ctx": "上限なし・先回りなし（前の文あり）",
    "split": "句読点で分けた句（時間だけ）",
    "real-pf": "既定・先回りあり（1字 125 ミリ秒）",
    "real-nopf": "既定・先回りなし（1字 125 ミリ秒）",
}


def read_ints(path):
    try:
        return [int(x) for x in open(path, encoding="utf-8").read().split() if x.lstrip("-").isdigit()]
    except FileNotFoundError:
        return []


def read_map(path):
    counts = []
    try:
        for line in open(path, encoding="utf-8"):
            fields = line.split()
            if len(fields) == 2 and fields[1].isdigit():
                counts.append(int(fields[1]))
    except FileNotFoundError:
        pass
    return counts


def stats_for(base):
    folder = os.path.dirname(base) or "."
    files, total = zenzai_stats.collect(folder, os.path.basename(base) + ".zstats.*")
    return total if files else None


def load_runs(folder, bucket, mode):
    runs = []
    for rep in range(1, 13):
        base = str(Path(folder) / f"long-{bucket}-{mode}-r{rep}")
        path = base + ".profile.tsv"
        if not os.path.exists(path):
            continue
        rows = read_profile(path)
        conv_all = [r for r in rows if r.get("kind") == "conv"]
        conv = conv_all[SKIP_FIRST:]
        if not conv:
            continue
        wall = read_ints(base + ".wall")
        wall = wall[SKIP_FIRST:] if len(wall) >= len(conv_all) else []
        runs.append({
            "base": base,
            "parts": [breakdown(r) for r in conv],
            "rows": conv,
            "wall": wall,
            "stats": stats_for(base),
        })
    return runs


def med(values):
    return pct(values, .5)


def ms(values):
    return f"{values:.0f}" if values == values else "-"


def pool(runs, key):
    return [p[key] / 1000 for r in runs for p in r["parts"]]


def per_run_medians(runs, key):
    return [med([p[key] / 1000 for p in r["parts"]]) for r in runs]


def wall_values(run):
    return run["wall"] if run["wall"] else [p["total"] / 1000 for p in run["parts"]]


def wall_med(runs):
    return med([w for r in runs for w in wall_values(r)])


def wall_run_medians(runs):
    return [med(wall_values(r)) for r in runs]


def spread(values):
    if not values:
        return "-"
    return f"{min(values):.0f}〜{max(values):.0f}"


def deadline(runs):
    """上限に当たった割合。分母は、空白キーの変換のうち最初の5回を除いた数（profile の conv 行）。"""
    hits = conv = 0
    rates = []
    for run in runs:
        s = run["stats"]
        if not s:
            continue
        profile_conv = len(run["parts"])
        if not profile_conv:
            continue
        if s.get("key_filter"):
            # 新しい記録: 空白キーの変換の間だけ数えた当たり数。分母は時間の表と同じ変換の数
            run_hits = s.get("key_hits", 0)
            run_conv = profile_conv
        else:
            # 古い記録: 上限の当たり数は全体。分母だけは時間の表と合わせる
            run_hits = s.get("hits", 0)
            run_conv = profile_conv
        hits += run_hits
        conv += run_conv
        if run_conv:
            rates.append(100 * run_hits / run_conv)
    rate = 100 * hits / conv if conv else None
    return conv, hits, rate, rates


def table_breakdown(folder):
    out = ["## 1. 段ごとの時間（前の文なし・上限なし・先回りなし）", ""]
    out.append("| 組 | 実際の読み字数 | 文数×回 | 空白キー 中央値 | 入り口 中央値 | Mozc | 全文 prefill | 全文 decode | 一括採点 | 選び手（一括採点を除く） | 前後の文（一括採点を除く） | その他 |")
    out.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for bucket in BUCKETS:
        runs = load_runs(folder, bucket, "plain")
        if not runs:
            continue
        chars = [g(r, "key_chars") for run in runs for r in run["rows"]]
        n = sum(len(run["parts"]) for run in runs)
        out.append(
            f"| {bucket} | {med(chars):.0f} | {n // len(runs)}×{len(runs)} | "
            f"{ms(wall_med(runs))} | {ms(med(pool(runs, 'total')))} | {ms(med(pool(runs, 'mozc')))} | "
            f"{ms(med(pool(runs, 'allz_pre')))} | {ms(med(pool(runs, 'allz_step')))} | "
            f"{ms(med(pool(runs, 'batch')))} | {ms(med(pool(runs, 'sel_no_batch')))} | "
            f"{ms(med(pool(runs, 'ctx_no_batch')))} | {ms(med(pool(runs, 'other')))} |")
    out.append("")
    out.append("一括採点は、前後の文の並べ替え（ctx）か選び手（sel）の内側で動く。その時間を別の列にして、ctx と sel から引いた。"
               "prefill/decode は全文の評価（all_zenzai）の内訳。")
    out.append("")
    out.append("同じ組の、評価（llama_decode）の内訳:")
    out.append("")
    out.append("| 組 | まとめて n / ms | 1語片 n / ms | 渡した語片 | 新しく計算 | 使い回せた割合 |")
    out.append("|---|---:|---:|---:|---:|---:|")
    for bucket in BUCKETS:
        runs = load_runs(folder, bucket, "plain")
        if not runs:
            continue
        n = sum(len(run["parts"]) for run in runs) or 1
        tok = sum(g(r, "allz_tok") for run in runs for r in run["rows"])
        new = sum(g(r, "allz_new") for run in runs for r in run["rows"])
        pre_n = sum(g(r, "allz_pre_n") for run in runs for r in run["rows"])
        pre_us = sum(g(r, "allz_pre_us") for run in runs for r in run["rows"])
        step_n = sum(g(r, "allz_step_n") for run in runs for r in run["rows"])
        step_us = sum(g(r, "allz_step_us") for run in runs for r in run["rows"])
        out.append(f"| {bucket} | {pre_n / n:.1f} / {pre_us / 1000 / n:.1f} | {step_n / n:.1f} / {step_us / 1000 / n:.1f} | "
                   f"{tok / n:.0f} | {new / n:.0f} | {100 * (1 - new / max(1, tok)):.0f}% |")
    out.append("")
    out.append("prefill は2語片以上をまとめた評価、decode は1語片だけの評価。")
    out.append("")
    return out


def table_context(folder):
    out = ["## 1b. 前の文あり・なし（文脈の門）", ""]
    out.append("| 組 | 前の文なし 中央値 | 前の文あり 中央値 | 差（あり−なし） | Mozc（あり） | 全文 prefill（あり） | 全文 decode（あり） | 一括採点（あり） | 選び手（あり） | 前後の文の並べ替え（あり） | その他（あり） |")
    out.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for bucket in BUCKETS:
        plain = load_runs(folder, bucket, "plain")
        ctx = load_runs(folder, bucket, "plain-ctx")
        if not plain or not ctx:
            continue
        wp, wc = wall_med(plain), wall_med(ctx)
        out.append(
            f"| {bucket} | {wp:.0f} | {wc:.0f} | {wc - wp:+.0f} | "
            f"{ms(med(pool(ctx, 'mozc')))} | {ms(med(pool(ctx, 'allz_pre')))} | "
            f"{ms(med(pool(ctx, 'allz_step')))} | {ms(med(pool(ctx, 'batch')))} | "
            f"{ms(med(pool(ctx, 'sel_no_batch')))} | {ms(med(pool(ctx, 'ctx_no_batch')))} | "
            f"{ms(med(pool(ctx, 'other')))} |")
    out.append("")
    if any(load_runs(folder, bucket, "plain-ctx") for bucket in BUCKETS):
        out.append("「前後の文の並べ替え」は、前の文を渡したときの文脈の門（contextPriorWinner）の段。"
                   "前の文なしの表1では、この段はほぼ 0 になる。")
    else:
        out.append("前の文あり（plain-ctx）の記録がありません。")
    out.append("")
    return out


def table_prefetch(folder):
    out = ["## 2. 先回りと1秒の上限", ""]
    out.append("| 組 | 先回りあり 中央値 | 先回りなし 中央値 | 差（なし−あり） | 減り方 | 上限に当たった割合（あり） | （なし） |")
    out.append("|---|---:|---:|---:|---:|---:|---:|")
    reductions = []
    for bucket in BUCKETS:
        on = load_runs(folder, bucket, "real-pf")
        off = load_runs(folder, bucket, "real-nopf")
        if not on or not off:
            continue
        won, woff = wall_med(on), wall_med(off)
        diff = woff - won
        reduction = 100 * diff / woff if woff else 0
        reductions.append(reduction)
        conv_on, hit_on, rate_on, _ = deadline(on)
        conv_off, hit_off, rate_off, _ = deadline(off)
        out.append(f"| {bucket} | {won:.0f} | {woff:.0f} | {diff:.0f} | {reduction:+.1f}% | "
                   f"{rate_on:.1f}%（{hit_on}/{conv_on}） | {rate_off:.1f}%（{hit_off}/{conv_off}） |" if rate_on is not None and rate_off is not None
                   else f"| {bucket} | {won:.0f} | {woff:.0f} | {diff:.0f} | {reduction:+.1f}% | 記録なし | 記録なし |")
    out.append("")
    if reductions:
        out.append(f"先回りありの減り方: 組ごとの {min(reductions):+.1f}%〜{max(reductions):+.1f}%（正なら先回りが速い）。")
    else:
        out.append("先回りの比較の記録がありません（組 w を流すと出ます）。")
    out.append("")
    return out


def split_reduction(folder, bucket):
    """句読点で分けたときの、1文あたりの時間の比（分けた側−そのまま）。"""
    whole = load_runs(folder, bucket, "plain")
    split = load_runs(folder, bucket, "split")
    if not whole or not split:
        return None
    meds = []
    map_path = Path(folder) / f"long-{bucket}-split-map.tsv"
    if not map_path.exists():
        map_path = Path(folder) / "long" / f"long-{bucket}-split-map.tsv"
    for run in split:
        counts = read_map(map_path)
        walls = read_ints(run["base"] + ".wall")
        if not counts or len(walls) < sum(counts):
            continue
        sums, pos = [], 0
        for count in counts:
            sums.append(sum(walls[pos:pos + count]))
            pos += count
        sums = sums[SKIP_FIRST:]
        if sums:
            meds.append(med(sums))
    if not meds:
        return None
    split_ms = med(meds)
    whole_ms = wall_med(whole)
    return whole_ms, split_ms, meds, wall_run_medians(whole)


def table_split(folder):
    out = ["## 3. 句読点で分けたときの見込み（時間だけ）", ""]
    out.append("| 組 | そのまま 中央値 | 句に分けて足す 中央値 | 減り方 |")
    out.append("|---|---:|---:|---:|")
    reductions = []
    for bucket in BUCKETS:
        got = split_reduction(folder, bucket)
        if not got:
            continue
        whole, split, _, _ = got
        reduction = 100 * (whole - split) / whole if whole else 0
        reductions.append(reduction)
        out.append(f"| {bucket} | {whole:.0f} | {split:.0f} | {reduction:+.1f}% |")
    out.append("")
    if reductions:
        out.append(f"組ごとの {min(reductions):+.1f}%〜{max(reductions):+.1f}%（正なら分けたほうが速い）。"
                   "句点を落とすので、変換の正しさは別に測る必要がある。")
    else:
        out.append("句に分けた比較の記録がありません。")
    out.append("")
    return out


def table_repeats(folder):
    out = ["## 4. 同じ機械での3回のばらつき", ""]
    out.append("| 組 | 条件 | 各回の中央値 | 幅 | ばらつき（幅÷中央値） |")
    out.append("|---|---|---|---:|---:|")
    for mode in ("plain", "plain-ctx", "real-pf", "real-nopf"):
        for bucket in BUCKETS:
            runs = load_runs(folder, bucket, mode)
            if len(runs) < 2:
                continue
            meds = wall_run_medians(runs)
            value = med(meds)
            spread_pct = 100 * (max(meds) - min(meds)) / value if value else 0
            out.append(f"| {bucket} | {mode} | {' / '.join(f'{x:.0f}' for x in meds)} | {spread(meds)} | {spread_pct:.1f}% |")
    out.append("")
    return out


def proposals(folder):
    out = ["## 5. 案の見込み（測った数字からの計算。作ってはいない）", ""]

    # (a) 先回りを長い文にも広げる
    out.append("### (a) 打っている間に先に作っておく（先回りを長い文にも広げる）")
    out.append("")
    lines = []
    for bucket in BUCKETS:
        on = load_runs(folder, bucket, "real-pf")
        off = load_runs(folder, bucket, "real-nopf")
        if not on or not off:
            continue
        won, woff = wall_med(on), wall_med(off)
        reduction = 100 * (woff - won) / woff if woff else 0
        _, hit_on, rate_on, _ = deadline(on)
        _, hit_off, rate_off, _ = deadline(off)
        lines.append((bucket, reduction, rate_on, rate_off))
    if lines:
        for bucket, reduction, rate_on, rate_off in lines:
            extra = ""
            if rate_on is not None and rate_off is not None:
                extra = f"、上限に当たった割合 {rate_off:.1f}%→{rate_on:.1f}%"
            out.append(f"- {bucket} 字: 空白キー {reduction:+.1f}%{extra}。")
        values = [x[1] for x in lines]
        out.append(f"- まとめ: 組ごと {min(values):+.1f}%〜{max(values):+.1f}%。"
                   "先回りは、打ち終わりまでに前の計算が終わる場合だけ効く。この測定は1字 125 ミリ秒で打っている。")
    else:
        out.append("- 比較の記録がありません。")
    out.append("")

    # (b) KV キャッシュの使い回し
    out.append("### (b) 前回の計算の KV キャッシュを使い回し、変わった後ろだけ作り直す")
    out.append("")
    out.append("いまの変換の中でも、同じ問いの共通の前半は使い回されている。全文の評価で渡した語片のうち、"
               "新しく計算した割合から、前回の変換をまたいで使い回せた場合の上限を見積もる。"
               "「読みが1字だけ変わった」と仮定し、新しい語片を読み1字あたりの語片数とする。")
    out.append("")
    out.append("| 組 | いまの使い回し | 1字あたりの語片 | 1変換の新しい語片 | 評価の語片の減り方（上限） | 全体の時間の減り方（上限） |")
    out.append("|---|---:|---:|---:|---:|---:|")
    savings = []
    for bucket in BUCKETS:
        runs = load_runs(folder, bucket, "plain")
        if not runs:
            continue
        n = sum(len(run["parts"]) for run in runs) or 1
        rows = [r for run in runs for r in run["rows"]]
        tok = sum(g(r, "allz_tok") for r in rows)
        new = sum(g(r, "allz_new") for r in rows)
        chars = sum(g(r, "key_chars") for r in rows)
        total_us = sum(g(r, "total_us") for r in rows)
        dec_us = sum(g(r, "allz_dec_us") for r in rows)
        if not tok or not new or not chars:
            continue
        per_char = tok / chars
        reuse = 100 * (1 - new / tok)
        tail = max(1.0, per_char)
        token_reduction = max(0.0, 1 - tail / new)
        saved = dec_us * token_reduction
        share = 100 * saved / total_us if total_us else 0
        savings.append(share)
        out.append(f"| {bucket} | {reuse:.0f}% | {per_char:.1f} | {new / n:.0f} | {100 * token_reduction:.0f}% | {share:.1f}% |")
    out.append("")
    if savings:
        out.append(f"まとめ: 全体で {min(savings):.1f}%〜{max(savings):.1f}% の見込み。"
                   "前回の変換の KV がそのまま使えるという仮定の上限で、変換の質は見ていない。")
    else:
        out.append("記録がありません。")
    out.append("")

    # (c) 句読点で区切る
    out.append("### (c) 句読点で区切って短く作る")
    out.append("")
    out.append("上の「3. 句読点で分けたときの見込み」がそのまま案 (c) の時間の見込み。"
               "句ごとに変換の入り口が増えるので、短い組では、かえって遅くなることがある。"
               "文脈が句の境目で切れるため、変換の正しさはこの測定に含まれない。")
    out.append("")
    return out


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else "."
    text = ["# 長い文の変換の時間（読みの長さ別・段別）", ""]
    env = os.path.join(folder, "long-latency-env.txt")
    if os.path.exists(env):
        text += ["計算機: " + open(env, encoding="utf-8").read().strip().replace("\n", " / "), ""]
    text += table_breakdown(folder)
    text += table_context(folder)
    text += table_prefetch(folder)
    text += table_split(folder)
    text += table_repeats(folder)
    text += proposals(folder)
    text += ["## 6. 本物の Mozc で流すとき", "",
             "GitHub の Linux test を手動で流し、試験の組に `[\"w\"]` を入れる（ほかの組は流さない）。"
             "組 w は1つの計算機で、処理を1つだけにして、上の条件を3回ずつ流す。結果は linux-results に入る。",
             "```",
             "groups: [\"w\"]",
             "```",
             ""]
    print("\n".join(text))


if __name__ == "__main__":
    main()
