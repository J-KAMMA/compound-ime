"""選び手の段階1: Zenz の尤度でそのまま選べるか（学習なし）。

  python tools/selector_stage1.py <score.txt> <results.tsv> <tests.json>

score.txt は MYIME_SELECTOR_SCORE の記録。1行が1文節で、タブ区切り:
  読み, 今の先頭候補を U+0001 でつないだもの, 文節の番号, Zenz が選んだ候補の番号
  （0 は今の出力、-1 は採点できず）, 採点にかかった時間(ミリ秒), 候補, 点, 候補, 点, ...
点は、その文節だけ候補に替えた文全体を Zenz が出す確率の対数（大きいほどよい）。
results.tsv の出力と先頭候補をつないだ文が一致する行だけを、その文の記録とする。

数えるもの:
  - 直せる文節: 今の出力が間違いで、候補の上位8つに正解がある文節。
    Zenz の最高点が正解である割合（直せた率）。
  - 正しい文の文節: 今の出力が正しい文で、Zenz が今の候補から別の候補に替えてしまう割合（壊す率）。
  - 全部の文節に Zenz の選びを当てた文全体の結果（間違い→正解、正解→間違い）。
"""
import json
import statistics
import sys
from pathlib import Path


def solve(firsts, scored, answers):
    """答え（大文字小文字を無視）になる候補の選び方を探す。{文節番号: 正解の表記} か None。"""
    wanted = [a.lower() for a in answers]

    def go(i, at, chosen, answer):
        if i == len(firsts):
            return chosen if at == len(answer) else None
        options = [c for c, _ in scored[i]] if i in scored else [firsts[i]]
        for c in options:
            if c and answer.startswith(c.lower(), at):
                got = go(i + 1, at + len(c), chosen + [c], answer)
                if got is not None:
                    return got
        return None

    for a in wanted:
        got = go(0, 0, [], a)
        if got is not None:
            return {i: got[i] for i in scored}
    return None


def main():
    score_path, results_path, tests_path = sys.argv[1:4]
    records = {}  # 出力文 -> {文節番号: [(候補, 点)]}, 先頭候補, 番号->Zenzの選び
    times = []
    cand_counts = []
    if Path(score_path).exists():
        for line in Path(score_path).read_text(encoding="utf-8", errors="replace").splitlines():
            p = line.split("\t")
            if len(p) < 7:
                continue
            firsts = p[1].split("\x01")
            seg, pick, ms = int(p[2]), int(p[3]), int(p[4])
            pairs = [(p[k], float(p[k + 1])) for k in range(5, len(p) - 1, 2)]
            rec = records.setdefault("".join(firsts), {"firsts": firsts, "segs": {}, "pick": {}, "ms": {}})
            rec["segs"][seg] = pairs
            rec["pick"][seg] = pick
            rec["ms"][seg] = ms
    got = {}
    for line in Path(results_path).read_text(encoding="utf-8").splitlines():
        p = line.split("\t")
        if len(p) >= 3:
            got[p[0]] = p[2]
    items = json.loads(Path(tests_path).read_text(encoding="utf-8"))["items"]

    fixable = fixed = 0           # 直せる文節
    right_segs = broken = 0       # 正しい文の文節
    s_wrong_fixed = s_wrong_total = s_right_broken = s_right_total = 0
    no_record = 0
    fix_examples, break_examples, miss_examples = [], [], []
    by_cat = {}

    def pick_surface(pairs, pick):
        return pairs[pick][0] if 0 <= pick < len(pairs) else pairs[0][0]

    for it in items:
        out = got.get(it["romaji"])
        if out is None:
            continue
        answers = [it["intended"]] + it.get("alternatives", [])
        correct = out.lower() in [a.lower() for a in answers]
        rec = records.get(out)
        if rec is None:
            no_record += 1
            continue
        for seg, ms in rec["ms"].items():
            times.append((ms, len(rec["segs"][seg])))
        cat = it.get("category", "")
        stat = by_cat.setdefault(cat, [0, 0, 0, 0])
        # 全部の文節に Zenz の選びを当てた文
        chosen = list(rec["firsts"])
        for seg, pairs in rec["segs"].items():
            chosen[seg] = pick_surface(pairs, rec["pick"][seg])
        new_out = "".join(chosen)
        new_correct = new_out.lower() in [a.lower() for a in answers]
        if correct:
            s_right_total += 1
            if not new_correct:
                s_right_broken += 1
            for seg, pairs in rec["segs"].items():
                right_segs += 1
                stat[2] += 1
                if rec["pick"][seg] > 0:
                    broken += 1
                    stat[3] += 1
                    if len(break_examples) < 25:
                        top = pick_surface(pairs, rec["pick"][seg])
                        break_examples.append(f"  [{cat}] {out} → 文節{seg}を {pairs[0][0]} から {top} に（点 {pairs[0][1]:.2f} → {max(s for _, s in pairs):.2f}）")
        else:
            s_wrong_total += 1
            if new_correct:
                s_wrong_fixed += 1
            need = solve(rec["firsts"], rec["segs"], answers)
            if need is None:
                continue
            for seg, pairs in rec["segs"].items():
                if need[seg].lower() == rec["firsts"][seg].lower():
                    continue
                fixable += 1
                stat[0] += 1
                top = pick_surface(pairs, rec["pick"][seg])
                ok = rec["pick"][seg] >= 0 and top.lower() == need[seg].lower()
                if ok:
                    fixed += 1
                    stat[1] += 1
                if len(fix_examples) < 25 and ok:
                    fix_examples.append(f"  [{cat}] {out} → 文節{seg}を {rec['firsts'][seg]} から {need[seg]} に")
                if len(miss_examples) < 25 and not ok:
                    ranked = sorted(pairs, key=lambda x: -x[1])
                    miss_examples.append(f"  [{cat}] {out}: 正解 {need[seg]}、Zenz は {top}（"
                                         + "、".join(f"{c} {s:.1f}" for c, s in ranked[:3]) + "）")

    def rate(a, b):
        return f"{a}/{b} ({100 * a / b:.1f}%)" if b else f"{a}/{b}"

    print(f"Zenz の尤度だけで選ぶ（学習なし）: 直せた率 {rate(fixed, fixable)}、壊す率 {rate(broken, right_segs)}")
    print(f"  直せる文節（間違いの文で、正解が上位8つにある文節）のうち、Zenz の最高点が正解: {rate(fixed, fixable)}")
    print(f"  正しい文の文節のうち、Zenz が別の候補に替える: {rate(broken, right_segs)}")
    print(f"  文全体で全文節に当てると: 間違い→正解 {rate(s_wrong_fixed, s_wrong_total)}、正解→間違い {rate(s_right_broken, s_right_total)}")
    print(f"  記録が見つからない文: {no_record}")
    if times:
        ms_all = [t for t, _ in times]
        per_cand = [t / max(n, 1) for t, n in times]
        print(f"  時間: 採点した文節 {len(times)} 個、1文節あたり 平均 {statistics.mean(ms_all):.0f} ミリ秒"
              f"（中央値 {statistics.median(ms_all):.0f}、最大 {max(ms_all)}）、候補1つあたり 平均 {statistics.mean(per_cand):.0f} ミリ秒")
    print("  分類ごと（直せた/直せる、壊す/正しい文節）:")
    for cat, (a, b, c, d) in sorted(by_cat.items()):
        print(f"    {cat}: {b}/{a}、{d}/{c}")
    print("直せた例:")
    print("\n".join(fix_examples[:15]))
    print("直せなかった例:")
    print("\n".join(miss_examples[:15]))
    print("壊した例:")
    print("\n".join(break_examples[:15]))


if __name__ == "__main__":
    main()
