"""Scores the katakana-to-English tests (tools/make_katakana_english_tests.py).

  python tools/score_katakana_english.py --tests tests/conversion --results results \
      [--min-rate 0.98] [--max-wasei 0]

The four test files are matched to the same names in the results directory (the output of
tools/candidates_convert.sh: ローマ字<TAB>候補<TAB>候補 ...). A positive test is a hit when the
expected spelling is among the first 10 candidates and not the first one (the Japanese candidate
stays first); a spelling at the very first place is counted as a failure. A wasei test is wrong
when the English word it looks like is among the first 10.
Prints the hits by kind and origin and the first misses. Exits 1 when the overall positive rate
is below --min-rate, when more wasei tests than --max-wasei find an English word, or when a
result file is missing.
"""
import argparse
import sys
from collections import defaultdict
from pathlib import Path

FILES = {
    "katakana-english.tsv": ("カタカナ語", True),
    "katakana-wasei.tsv": ("和製英語", False),
    "work-names.tsv": ("作品名", True),
    "brand-names.tsv": ("企業・ブランド", True),
}


def read_tsv(path):
    return [line.rstrip("\n").split("\t") for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tests", type=Path, required=True)
    ap.add_argument("--results", type=Path, required=True)
    ap.add_argument("--min-rate", type=float, default=0.98)
    ap.add_argument("--max-wasei", type=int, default=0)
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    missing, total, hits, first, wrong = False, 0, 0, 0, 0
    for name, (label, positive) in FILES.items():
        test_path = args.tests / name
        result_path = args.results / name
        if not test_path.exists():
            print(f"{name}: 試験がない")
            missing = True
            continue
        tests = read_tsv(test_path)
        if not result_path.exists():
            print(f"{label}: 結果がない（{result_path}）")
            missing = True
            continue
        results = read_tsv(result_path)
        if len(results) != len(tests):
            print(f"注意: {label} の結果が {len(results)} 行、試験が {len(tests)} 行")
        results += [[]] * (len(tests) - len(results))
        groups = defaultdict(lambda: [0, 0, 0])  # hit10, first, all
        misses = []
        for test, got in zip(tests, results):
            raw, expected = test[0], test[1]
            rank = None
            if len(got) > 1:
                try:
                    rank = got[1:31].index(expected)
                except ValueError:
                    rank = None
            key = f"由来 {test[3]}" if len(test) > 3 else "全部"
            for k in ("全部", key):
                g = groups[k]
                g[2] += 1
                if positive:
                    g[0] += rank is not None and 0 < rank < 10
                    g[1] += rank == 0
                else:
                    g[0] += rank is not None and rank < 10  # a wasei word that got the English word
            if positive:
                total += 1
                hit = rank is not None and 0 < rank < 10
                hits += hit
                first += rank == 0
                if not hit:
                    why = "先頭に出た" if rank == 0 else "上位10個以内にない"
                    misses.append(f"  {raw} → {' / '.join(got[1:7])}（期待: {expected}、{why}）")
            else:
                bad = rank is not None and rank < 10
                wrong += bad
                if bad:
                    misses.append(f"  {raw} → {' / '.join(got[1:7])}（出てはいけない: {expected}）")
        g = groups["全部"]
        if positive:
            print(f"{label}: 上位10個以内 {g[0]}/{g[2]}、先頭 {g[1]} 件（英字が先頭になった数）")
        else:
            print(f"{label}: 英字が出た {g[0]}/{g[2]}（0 が正しい）")
        for k in sorted(groups):
            if k != "全部":
                gg = groups[k]
                print(f"  {k}: {gg[0]}/{gg[2]}")
        if misses:
            print(f"{label} の外れ（先頭 40 件）:")
            print("\n".join(misses[:40]))

    rate = hits / total if total else 0.0
    print(f"合計: 上位10個以内 {hits}/{total}（{rate:.1%}）、英字が先頭になった {first} 件")
    ok = not missing and rate >= args.min_rate and wrong <= args.max_wasei and first == 0
    if wrong > args.max_wasei:
        print(f"和製英語に英字が付いた: {wrong} 件（上限 {args.max_wasei}）")
    if missing or rate < args.min_rate:
        print(f"試験に足りない（下限 {args.min_rate:.0%}）")
    if first:
        print(f"英字が先頭になった: {first} 件（1番目にはしないので失敗）")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
