"""判定の門を組み込んだ IME の試験（.github/workflows/linux-test.yml の jev_gate_configs）の結果をまとめる。

  python tools/jev_gate_report.py --tests tests/conversion --acc 設定名=結果のフォルダ … [--time 設定名=フォルダ …]
      [--same 設定名=フォルダ 設定名=フォルダ] [--out report.md]

  --acc  正解の数（試験ごとと合計）、門の判断の記録（jevgate-log-*.txt）から生成した割合と各段の平均の時間。
         フォルダには各組の結果（ja400.tsv、context-with.tsv、wiki-typing-1.tsv など）がそろっている。
         正解の数え方は tools/jev_ceiling.py と同じ（大文字小文字を区別しない試験もある）。6,985 文。
  --time 時間の試験（組 kp）の結果。フォルダに lat-<設定>-r<回>.keyus と .gatelog がある。変換1回の時間の
         中央値・90%点を回ごとに出し、設定ごとに回をまとめる（回ごとの中央値の最小〜最大）。各回の最初の5変換は除く。
  --same 2つのフォルダの結果のファイル（*.tsv）が1行も違わないかを確かめる（門なしの出力が今と同じか）。
"""
import argparse
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jev_ceiling as jc  # noqa: E402


def merge_wiki(d):
    """wiki-typing-1.tsv と -2.tsv をつなぐ（results ジョブと同じ）。つないだ行の一覧を返す"""
    out = []
    for n in ("1", "2"):
        p = Path(d) / f"wiki-typing-{n}.tsv"
        if p.exists():
            out += open(p, encoding="utf-8").read().splitlines()
    return out


def load_set(d, name):
    """設定のフォルダから試験 name の出力（入力 → 確定）"""
    if name.startswith("wikiw"):
        got = {}
        for line in merge_wiki(d):
            p = line.split("\t")
            if len(p) >= 3:
                got[p[0]] = p[2]
        return got
    return jc.load_out(Path(d) / jc.BASE_FILE[name])


def accuracy(tests_dir, folder):
    T = jc.tests(tests_dir)
    rows = {}
    for label, names in jc.GROUPS:
        ok = n = missing = 0
        for name in names:
            got = load_set(folder, name)
            for romaji, answers, _left, fold in T[name]:
                n += 1
                out = got.get(romaji)
                if out is None:
                    missing += 1
                ok += int(jc.correct(jc.norm(out) if out else out, [jc.norm(a) for a in answers], fold))
        rows[label] = (ok, n, missing)
    return rows


def parse_log(path):
    fields = {}
    for line in open(path, encoding="utf-8", errors="replace"):
        if not line.startswith("gate\t"):
            continue
        row = {}
        for part in line.rstrip("\n").split("\t")[1:]:
            if "=" in part:
                k, v = part.split("=", 1)
                row[k] = v
        yield row


def log_stats(folder, pattern):
    decisions, sums, counts = {}, {}, {}
    chosen = {}
    unreal = 0
    for p in sorted(Path(folder).glob(pattern)):
        for row in parse_log(p):
            d = row.get("decision", "?")
            decisions[d] = decisions.get(d, 0) + 1
            for k in ("noai_ms", "predict_ms", "score_ms", "total_ms"):
                if k in row:
                    try:
                        sums[(d, k)] = sums.get((d, k), 0.0) + float(row[k])
                        counts[(d, k)] = counts.get((d, k), 0) + 1
                    except ValueError:
                        pass
            if d == "skip":
                chosen[row.get("chosen", "?")] = chosen.get(row.get("chosen", "?"), 0) + 1
                unreal += row.get("best_unrealizable") == "1"
    return decisions, sums, counts, chosen, unreal


GEN_DECISIONS = ("generate", "generate_nogate", "fallback_score", "fallback_score_count", "fallback_realize", "error_predict")


def fmt_stats(decisions, sums, counts, chosen, unreal):
    total = sum(decisions.values())
    gen = sum(v for k, v in decisions.items() if k in GEN_DECISIONS)
    lines = [f"門に来た変換 {total}、生成した {gen}（{100.0 * gen / total:.1f}%）、生成を省いた {decisions.get('skip', 0)}" if total else "門の記録なし"]
    lines.append("判断の内訳: " + "、".join(f"{k} {v}" for k, v in sorted(decisions.items())))
    for d in ("skip", "generate"):
        parts = []
        for k in ("noai_ms", "predict_ms", "score_ms", "total_ms"):
            if counts.get((d, k)):
                parts.append(f"{k} {sums[(d, k)] / counts[(d, k)]:.1f}")
        if parts:
            lines.append(f"{d} の平均（ミリ秒）: " + "、".join(parts))
    if chosen:
        lines.append("省いたときに選んだ候補の出どころ: " + "、".join(f"{k} {v}" for k, v in sorted(chosen.items())) +
                     f"（最大の点の候補を実現できなかった {unreal}）")
    return lines


def pct(values, q):
    s = sorted(values)
    return s[min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))] if s else float("nan")


def timing(folder):
    out = {}
    for p in sorted(Path(folder).glob("lat-*-r*.keyus")):
        stem = p.name[len("lat-"):-len(".keyus")]
        cfg, _, rep = stem.rpartition("-r")
        ms = []
        for line in open(p, encoding="utf-8"):
            f = line.split()
            if len(f) >= 2:
                ms.append((int(f[1]) - int(f[0])) / 1000.0)
        ms = ms[5:]
        if ms:
            out.setdefault(cfg, {})[int(rep)] = ms
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tests", required=True)
    ap.add_argument("--acc", nargs="*", default=[])
    ap.add_argument("--time", nargs="*", default=[])
    ap.add_argument("--same", nargs=2)
    ap.add_argument("--out")
    a = ap.parse_args()
    out = []
    if a.acc:
        cfgs = [x.split("=", 1) for x in a.acc]
        table = {name: accuracy(a.tests, folder) for name, folder in cfgs}
        labels = [l for l, _ in jc.GROUPS]
        out.append("## 正解の数\n")
        out.append("| 試験 | 文 | " + " | ".join(n for n, _ in cfgs) + " |")
        out.append("|---|---:|" + "---:|" * len(cfgs))
        for label in labels:
            n = table[cfgs[0][0]][label][1]
            out.append(f"| {label} | {n} | " + " | ".join(str(table[c][label][0]) for c, _ in cfgs) + " |")
        out.append("| **合計** | " + str(sum(table[cfgs[0][0]][l][1] for l in labels)) + " | " +
                   " | ".join(f"**{sum(table[c][l][0] for l in labels)}**" for c, _ in cfgs) + " |")
        miss = {c: sum(table[c][l][2] for l in labels) for c, _ in cfgs}
        if any(miss.values()):
            out.append("\n出力のなかった文: " + "、".join(f"{c} {m}" for c, m in miss.items()))
        out.append("\n## 門の判断（正解を数えた全部の組の合計）\n")
        for name, folder in cfgs:
            out.append(f"### {name}\n")
            out += ["- " + l for l in fmt_stats(*log_stats(folder, "jevgate-log-*.txt"))]
            out.append("")
    if a.time:
        out.append("## 変換1回の時間（ミリ秒。変換の入り口の全体、空白キーを押してから返るまで）\n")
        out.append("同じ計算機で、設定を入れ替えながら繰り返した。回ごとの中央値の最小〜最大を括弧に書く。\n")
        out.append("| 設定 | 回数 | 変換数/回 | 中央値（回の平均） | 中央値の幅 | 90%点（回の平均） | 90%点の幅 | 平均 |")
        out.append("|---|---:|---:|---:|---|---:|---|---:|")
        details = []
        for name, folder in (x.split("=", 1) for x in a.time):
            t = timing(folder)
            for cfg in sorted(t, key=lambda c: (c != "off", c)):
                reps = t[cfg]
                meds = [statistics.median(v) for v in reps.values()]
                p90 = [pct(v, 0.9) for v in reps.values()]
                means = [statistics.mean(v) for v in reps.values()]
                n = statistics.mean(len(v) for v in reps.values())
                out.append(f"| {cfg} | {len(reps)} | {n:.0f} | {statistics.mean(meds):.1f} | {min(meds):.1f}〜{max(meds):.1f} | "
                           f"{statistics.mean(p90):.1f} | {min(p90):.1f}〜{max(p90):.1f} | {statistics.mean(means):.1f} |")
                st = log_stats(folder, f"lat-{cfg}-r*.gatelog")
                details.append((cfg, st, sum(len(v) for v in reps.values()) + 5 * len(reps)))
        # 着工前の値付け（speed-claims）: 門なしでの全文の生成（all_zenzai）が変換1回の時間に占める割合と、その上限（Amdahl）
        for name, folder in (x.split("=", 1) for x in a.time):
            tot = allz = n = 0
            for p in sorted(Path(folder).glob("lat-off-r*.profile.tsv")):
                for line in open(p, encoding="utf-8", errors="replace"):
                    row = dict(kv.split("=", 1) for kv in line.rstrip("\n").split("\t") if "=" in kv)
                    if row.get("kind") != "conv":
                        continue
                    try:
                        tot += int(row.get("total_us", 0))
                        allz += int(row.get("allz_us", 0))
                        n += 1
                    except ValueError:
                        pass
            if tot:
                share = allz / tot
                out.append(f"\n門なし（off）の変換 {n} 回で、全文の生成（all_zenzai）が入り口の時間に占める割合 {100 * share:.1f}%。"
                           f"生成を全部なくせたとしても（Amdahl の上限）速さは最大 {1 / (1 - share):.2f} 倍。")
        out.append("\n### 時間の試験での門の判断\n")
        for cfg, st, total in details:
            out.append(f"#### {cfg}\n")
            decisions = st[0]
            gen = sum(v for k, v in decisions.items() if k in GEN_DECISIONS)
            out.append(f"- 全部の変換 {total} 回のうち、全文の生成が走ったのは {gen} 回（{100.0 * gen / total:.1f}%）")
            out += ["- " + l for l in fmt_stats(*st)]
            out.append("")
    if a.same:
        (n1, d1), (n2, d2) = (x.split("=", 1) for x in a.same)
        names = sorted({p.name for p in Path(d1).glob("*.tsv")} | {p.name for p in Path(d2).glob("*.tsv")})
        names = [n for n in names if not n.startswith(("lat-", "seqscore-"))]
        diff = []
        for n in names:
            p1, p2 = Path(d1) / n, Path(d2) / n
            if not (p1.exists() and p2.exists()):
                diff.append(f"{n}: 片方にしかない")
                continue
            l1, l2 = p1.read_text(encoding="utf-8").splitlines(), p2.read_text(encoding="utf-8").splitlines()
            # 並列の分け方で行の順は変わらないが、念のため順を無視して比べる
            if sorted(l1) != sorted(l2):
                d = sum(1 for x, y in zip(l1, l2) if x != y) if len(l1) == len(l2) else abs(len(l1) - len(l2))
                diff.append(f"{n}: 違う行 {d}（{len(l1)} 行と {len(l2)} 行）")
        out.append(f"## 出力が同じか（{n1} と {n2}）\n")
        out.append(f"比べたファイル {len(names)} 個。" + ("**全部 1 行も違わない。**" if not diff else "違い: " + "；".join(diff)))
    text = "\n".join(out) + "\n"
    print(text)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
