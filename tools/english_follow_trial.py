"""英語の語のあとの判定の試験を、Mozc なしで jaen_trial で流して採点する（2026-10-21）。

  g++ -std=c++20 -O2 -I native/jaen-detector native/jaen-detector/jaen_trial.cc native/jaen-detector/jaen_detector.cc -o jaen_trial
  JAEN_DICT=<mozc>/src/data/dictionary_oss python tools/english_follow_trial.py <jaen_trial> <作業の場所> <一覧の場所> [CTX=...]

tests/conversion/english-follow-{word,ja,control}.tsv（tools/make_english_follow_tests.py）の各行を、
  前の文あり（既定）と前の文なし（FOLLOW_OFF=1。今までの動き）で流し、
  word    : 打った1語がまるごと英語になったか
  ja      : 英語が1つも出ないか（出たら日本語の文が英語に化けた）
  control : 前の文ありとなしで結果が同じか
  bare    : 英単語と綴りが同じ日本語の語を1語だけ打ったとき英語になる数（合否にしない。寄せの代償の目安）
を数える。化けた文・取りこぼした語は並べる。CTX=... は費用の替え（例 CTX=follow_margin=1000）。
本物の変換とは、利用者の辞書・打ち間違いの直しなどが違う（native/jaen-detector/jaen_trial.cc の注）。
"""
import os
import subprocess
import sys
from pathlib import Path

LIMIT = 25  # 化けた文を並べる数の上限（VERBOSE=1 で全部）
TESTS = Path(__file__).resolve().parent.parent / "tests" / "conversion"


def load(name):
    rows = []
    for line in (TESTS / name).read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        rows.append(line.split("\t"))
    return rows


def run(binary, work, lex, rows, follow, ctx):
    env = dict(os.environ, CONTEXT="1")
    if ctx:
        env["CTX"] = ctx
    if not follow:
        env["FOLLOW_OFF"] = "1"
    text = "".join(f"{r[0]}\t{r[2]}\n" for r in rows)
    p = subprocess.run([binary, work, lex], input=text, capture_output=True, text=True, env=env, check=True)
    out = []
    for line in p.stdout.split("\n"):
        if line:
            out.append(line.partition("\t")[2])
    assert len(out) == len(rows), (len(out), len(rows))
    return out


def main():
    binary, work, lex = sys.argv[1:4]
    ctx = sys.argv[4][4:] if len(sys.argv) > 4 and sys.argv[4].startswith("CTX=") else ""
    results = {}
    for name in ("word", "ja", "control", "bare"):
        rows = load(f"english-follow-{name}.tsv")
        before = run(binary, work, lex, rows, False, ctx)
        after = run(binary, work, lex, rows, True, ctx)
        results[name] = (rows, before, after)
    rows, before, after = results["word"]
    ok = lambda got, r: got == r[0]
    b = sum(ok(g, r) for g, r in zip(before, rows))
    a = sum(ok(g, r) for g, r in zip(after, rows))
    print(f"英語の1語（前の確定が英語）: {len(rows)} 行  英語になった: 前の文なし {b} → あり {a}")
    miss = {}
    for g, r in zip(after, rows):
        if not ok(g, r):
            miss.setdefault(r[0], []).append(r[2])
    for w, bs in miss.items():
        print(f"  取りこぼし {w}: {len(bs)} 行 例 {bs[0]!r}")
    rows, before, after = results["ja"]
    b = sum(1 for g in before if g)
    a = sum(1 for g in after if g)
    print(f"英語の語のあとの日本語の文: {len(rows)} 行  英語に化けた: 前の文なし {b} → あり {a}")
    shown = 0
    for r, g0, g1 in zip(rows, before, after):
        if g1 and not g0 and (shown < LIMIT or os.environ.get("VERBOSE")):
            print(f"  化けた {r[0]} ({r[1]}) 前={r[2]!r} → {g1}")
            shown += 1
        elif g1 and g0 and os.environ.get("VERBOSE"):
            print(f"  もとから {r[0]} ({r[1]}) 前={r[2]!r} → {g1}")
    rows, before, after = results["control"]
    diff = [(r, g0, g1) for r, g0, g1 in zip(rows, before, after) if g0 != g1]
    print(f"日本語のあとの英単語1語: {len(rows)} 行  結果が変わった: {len(diff)}")
    for r, g0, g1 in diff[:20]:
        print(f"  変わった {r[0]} 前={r[2]!r}: {g0!r} → {g1!r}")
    rows, before, after = results["bare"]
    print(f"日本語の語を1語だけ打つ（合否にしない）: {len(rows)} 行  英語になった: 前の文なし {sum(1 for g in before if g)} → あり {sum(1 for g in after if g)}")


if __name__ == "__main__":
    main()
