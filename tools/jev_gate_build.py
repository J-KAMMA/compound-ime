"""判定の門（「この変換で人工知能の生成が要るか」）の学習・評価の記録を作る。

  学習用の文（GitHub Actions の組ごと）:
    python tools/jev_gate_build.py jobs <材料> <文の一覧.tsv> <v5 の結果.tsv> <名前> <jobs.tsv> <pre.jsonl>
    （jev_score で jobs.tsv を採点してから）
    python tools/jev_gate_build.py records <pre.jsonl> <採点の出力.tsv> <records.jsonl>
  試験の組（run 39249431055 の材料。机上の評価用）:
    python tools/jev_gate_build.py test <材料> <tests/conversion> <本線の結果> <採点の出力のフォルダ> <records.jsonl>
  記録の生成なしの候補を先頭の n 個に絞って付け直す（採点のやり直しなし）:
    python tools/jev_gate_build.py cap <n> <入力.jsonl.gz> <出力.jsonl.gz>
  記録を結ぶ・数える:
    python tools/jev_gate_build.py stats <records.jsonl>…

材料は tools/jev_collect.sh（人工知能なしの候補の書き出し）の出力、v5 の結果は tools/context_convert.sh の出力
（ローマ字<TAB>文節|…<TAB>確定）。候補の集まりは tools/jev_ceiling.py と同じ
（人工知能なしの出力 ∪ AzooKey の辞書の文全体の候補（最大32）∪ Mozc の組（上位32）∪ v5 の出力 ∪ 正解）で、
tools/jev_score.cpp で今の zenz v5 が点を付ける。
学習用の文では、生成なしの候補を先頭の CAND_AVAIL（16、環境変数 JEV_GATE_AVAIL で変える）個までにしてから採点する
（1文 約36個 → 約18個。模型が使うのは上位 k=4 個だけ。need_k・need_top1・harm_k と蒸留の教師は変わらず、need だけが
 「上位16個の中の zenz 最大」で決まる）。試験の記録は従来どおり全部の候補（最大64）。

記録（1文1行の JSON）:
  id        名前:番号（学習用は <組>:<番号>、試験は jev_ceiling.py と同じ）
  reading   読み（ひらがな）。prev  前の文（なければ空）
  answers   正解（ゆれがあれば複数。変換の後の決まった直し＝半角の ? ! の全角化をそろえた形）、fold  大文字小文字を区別しないか
  v5        本線（生成あり）の出力。noai  人工知能なし（生成なし）の出力
  cands     [[表記, zenz の点, 出どころ], …]。生成なしで作れる候補だけ（出どころは n=人工知能なしの出力、w=辞書の文全体、c=組）。
            並びは 人工知能なしの出力、辞書、組の順（IME が生成なしで作れる順）。最大 CAND_KEEP 個
  v5s, golds  v5 の出力、正解の点（候補にないとき null。比べるためだけ）
  sel       生成なしの候補の zenz の最大の表記（ラベルの元）、sel_i はその cands の番号
  need      生成が要る（1）／要らない（0）= sel が v5 の出力と違う（1）か同じ（0）か
  need_top1 人工知能なしの出力が v5 の出力と違うか
  sel_ok, v5_ok, top1_ok  それぞれの出力が正解か（学習用は元の文と同じか）
"""
import gzip
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jev_ceiling as jc  # noqa: E402

CAND_KEEP = 24
CAND_AVAIL = 16  # 学習用の文で採点する「生成なしの候補」の数（模型が使うのは上位 k=4 個。試験の記録は従来どおり最大64）


def open_text(path, mode="r"):
    path = str(path)
    if path.endswith(".gz"):
        return gzip.open(path, mode + "t", encoding="utf-8", newline="\n" if "w" in mode else None)
    return open(path, mode, encoding="utf-8", newline="\n" if "w" in mode else None)


def read_list(path):
    rows = []
    for line in open(path, encoding="utf-8"):
        if line.startswith("#") or not line.strip():
            continue
        f = line.rstrip("\n").split("\t")
        f += [""] * (3 - len(f))
        rows.append(f[:3])
    return rows


def make_candidates(noai, whole, combos, v5, gold, avail=None):
    """[(表記, 出どころ)]。出どころは n/w/c（生成なしで作れる）、b（v5 の出力）、g（正解）の文字の集まり。
    avail が数なら、生成なしで作れる候補（n/w/c）を並びの先頭からその数だけにしてから v5 の出力と正解を足す
    （採点の候補を減らす。ラベルの need はこの範囲での zenz 最大で決まる）"""
    out, index = [], {}
    for text, tag in [(noai, "n")] + [(x, "w") for x in whole[:32]] + [(x, "c") for x in combos[:32]]:
        text = jc.norm(text)
        if not text:
            continue
        if text in index:
            out[index[text]][1] += tag
        else:
            index[text] = len(out)
            out.append([text, tag])
    if avail:
        out = out[:avail]
        index = {c[0]: i for i, c in enumerate(out)}
    for text, tag in [(v5, "b"), (gold, "g")]:
        text = jc.norm(text)
        if not text:
            continue
        if text in index:
            out[index[text]][1] += tag
        else:
            index[text] = len(out)
            out.append([text, tag])
    return out[:64]


def pre_record(rid, reading, prev, answers, fold, v5, noai, whole, combos, avail=None):
    answers = [jc.norm(a) for a in answers]
    cands = make_candidates(noai, whole, combos, v5, answers[0], avail)
    return {"id": rid, "reading": reading, "prev": prev, "answers": answers, "fold": bool(fold),
            "v5": jc.norm(v5), "noai": jc.norm(noai), "cands": cands}


def job_row(pre):
    return "\t".join([pre["id"], jc.build_prompt(pre["reading"], pre["prev"])]
                     + [jc.model_text(c[0]) for c in pre["cands"]])


def finish(pre, scores):
    """採点を付け、ラベルを決めた記録にする。採点が候補の数と合わなければ None"""
    cands = pre["cands"]
    if len(scores) != len(cands) or any(s != s for s in scores):
        return None
    if not pre["v5"]:
        return None
    answers, fold = pre["answers"], pre["fold"]
    avail = [(i, c) for i, c in enumerate(cands) if set(c[1]) & set("nwc")]
    if not avail:
        return None
    best_i = max(avail, key=lambda x: scores[x[0]])[0]
    sel = cands[best_i][0]
    keep = [i for i, _ in avail[:CAND_KEEP]]
    if best_i not in keep:
        keep.append(best_i)
    kept = [[cands[i][0], round(scores[i], 4), "".join(sorted(set(cands[i][1]) & set("nwc")))] for i in keep]
    by_text = {c[0]: scores[i] for i, c in enumerate(cands)}

    def ok(out):
        return jc.correct(out, answers, fold)

    return {"id": pre["id"], "reading": pre["reading"], "prev": pre["prev"], "answers": answers, "fold": fold,
            "v5": pre["v5"], "noai": pre["noai"], "cands": kept,
            "v5s": by_text.get(pre["v5"]), "golds": by_text.get(answers[0]),
            "sel": sel, "sel_i": keep.index(best_i),
            "need": int(sel != pre["v5"]), "need_top1": int(pre["noai"] != pre["v5"]),
            "sel_ok": int(ok(sel)), "v5_ok": int(ok(pre["v5"])), "top1_ok": int(ok(pre["noai"]))}


def load_scores(path):
    scores = {}
    for line in open(path, encoding="utf-8"):
        f = line.rstrip("\n").split("\t")
        if len(f) >= 6 and f[1] == "trie":
            scores[f[0]] = [float(x) for x in f[5:]]
    return scores


def cmd_jobs(mdir, list_path, v5_path, name, jobs_path, pre_path):
    rows = read_list(list_path)
    noai = jc.load_out(Path(mdir) / f"{name}.tsv")
    v5 = jc.load_out(v5_path)
    dump = jc.blocks(Path(mdir) / f"dump-{name}.txt")
    feat = jc.blocks(Path(mdir) / f"features-{name}.txt")
    whole = jc.blocks(Path(mdir) / f"whole-{name}.txt")
    avail = int(os.environ.get("JEV_GATE_AVAIL") or CAND_AVAIL)
    n = skipped = 0
    with open(jobs_path, "w", encoding="utf-8", newline="\n") as jf, open(pre_path, "w", encoding="utf-8", newline="\n") as pf:
        for i, (romaji, orig, prev) in enumerate(rows, 1):
            segs = jc.parse_dump(dump[i][-1]) if dump.get(i) else None
            if not segs or romaji not in v5 or romaji not in noai:
                skipped += 1
                continue
            reading = "".join(s[0] for s in segs)
            fsegs = jc.parse_features(feat[i][-1]) if feat.get(i) else None
            w = []
            for line in reversed(whole.get(i, [])):
                r, lst = jc.whole_list(line)
                if r == reading:
                    w = lst
                    break
            pre = pre_record(f"{name}:{i}", reading, prev, [orig], False, v5[romaji], noai[romaji], w,
                             jc.kbest(fsegs, 32) if fsegs else [], avail)
            jf.write(job_row(pre) + "\n")
            pf.write(json.dumps(pre, ensure_ascii=False) + "\n")
            n += 1
    print(f"{name}: 文 {len(rows)}、採点の材料 {n}、記録が欠けて外した {skipped}")


def cmd_records(pre_path, score_path, out_path):
    scores = load_scores(score_path)
    n = bad = 0
    with open(pre_path, encoding="utf-8") as pf, open_text(out_path, "w") as out:
        for line in pf:
            pre = json.loads(line)
            rec = finish(pre, scores.get(pre["id"], []))
            if rec is None:
                bad += 1
                continue
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
    print(f"記録 {n}、採点がなくて外した {bad}")


def cmd_test(mdir, tdir, bdir, sdir, out_path):
    recs = jc.material(mdir, tdir, bdir)
    scores = jc.load_scores(sdir)
    n = bad = 0
    with open_text(out_path, "w") as out:
        for r in recs:
            if not r["reading"] or not r["base"]:
                bad += 1
                continue
            rid = f"{r['name']}:{r['i']}"
            pre = pre_record(rid, r["reading"], r["left"], r["answers"], r["fold"], r["base"], r["noai"],
                             r["whole"], r["combos"])
            rec = finish(pre, scores.get(rid, []))
            if rec is None:
                bad += 1
                continue
            rec["set"] = r["name"]
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
    print(f"試験の記録 {n}、外した {bad}")


def cap_record(r, n):
    """記録の生成なしの候補を先頭の n 個までにし、sel／ラベルを付け直す（採点のやり直しなし）。v5s、golds はそのまま"""
    cands = [c for c in r["cands"] if set(c[2]) & set("nwc")][:n]
    if not cands:
        return None
    best = max(range(len(cands)), key=lambda i: cands[i][1])
    sel = cands[best][0]
    r = dict(r)
    r.update({"cands": cands, "sel": sel, "sel_i": best, "need": int(sel != r["v5"]),
              "sel_ok": int(jc.correct(sel, r["answers"], r["fold"]))})
    return r


def cmd_cap(n, in_path, out_path):
    n = int(n)
    k = bad = 0
    with open_text(out_path, "w") as out:
        for r in iter_records([in_path]):
            r = cap_record(r, n)
            if r is None:
                bad += 1
                continue
            out.write(json.dumps(r, ensure_ascii=False) + "\n")
            k += 1
    print(f"記録 {k}、候補がなくて外した {bad}")


def iter_records(paths):
    for p in paths:
        with open_text(p) as f:
            for line in f:
                if line.strip():
                    yield json.loads(line)


def cmd_stats(paths):
    n = need = top1 = sel_ok = v5_ok = top1_ok = harm = prev = 0
    for r in iter_records(paths):
        n += 1
        need += r["need"]
        top1 += r["need_top1"]
        sel_ok += r["sel_ok"]
        v5_ok += r["v5_ok"]
        top1_ok += r["top1_ok"]
        harm += int(r["v5_ok"] and not r["sel_ok"])
        prev += bool(r["prev"])
    if not n:
        print("記録なし")
        return
    pct = lambda x: f"{100 * x / n:.1f}%"  # noqa: E731
    print(f"記録 {n}（前の文つき {prev}）")
    print(f"生成が要る（生成なしの候補の zenz 最大 ≠ v5 の出力） {need}（{pct(need)}）、要らない {n - need}（{pct(n - need)}）")
    print(f"人工知能なしの出力 ≠ v5 の出力 {top1}（{pct(top1)}）")
    print(f"正解: v5 {v5_ok}（{pct(v5_ok)}）、zenz 最大 {sel_ok}（{pct(sel_ok)}）、人工知能なし {top1_ok}（{pct(top1_ok)}）")
    print(f"v5 だけが正解（生成を省くと損）{harm}（{pct(harm)}）")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    a = sys.argv[2:]
    if cmd == "jobs" and len(a) == 6:
        cmd_jobs(*a)
    elif cmd == "records" and len(a) == 3:
        cmd_records(*a)
    elif cmd == "test" and len(a) == 5:
        cmd_test(*a)
    elif cmd == "cap" and len(a) == 3:
        cmd_cap(*a)
    elif cmd == "stats" and a:
        cmd_stats(a)
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
