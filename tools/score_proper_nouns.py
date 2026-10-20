"""Scores the proper noun tests (tools/proper_noun_test.py).

  python tools/score_proper_nouns.py sentences tests/conversion/proper-nouns.tsv results.tsv [label]
  python tools/score_proper_nouns.py candidates tests/conversion/proper-nouns-cand.tsv results.tsv [label]

sentences: results.tsv is the output of tools/batch_convert.sh (ローマ字<TAB>文節|…<TAB>確定). Counts the
  sentences that are exactly as expected and the sentences that have the name in its official spelling
  (the rest of the sentence may differ in kanji or kana), by kind of name and by origin.
candidates: results.tsv is the output of tools/candidates_convert.sh (ローマ字<TAB>候補<TAB>候補 ...).
  Counts the tests whose expected spelling is the first candidate, among the first 3, and among the first 9 (one page), and among all
  the candidates listed (at most 30), by way of typing.
Both list the first 60 misses. The results are matched to the tests by order (same number of lines).
"""
import sys
from collections import defaultdict


def read_tests(path):
    return [line.rstrip("\n").split("\t") for line in open(path, encoding="utf-8")
            if line.strip() and not line.startswith("#")]


def read_results(path):
    return [line.rstrip("\n").split("\t") for line in open(path, encoding="utf-8") if line.strip()]


def sentences(tests, results, label):
    groups = defaultdict(lambda: [0, 0, 0])  # exact, name right, all
    misses = []
    results = results + [[]] * (len(tests) - len(results))  # a test without a result is a miss
    for test, got in zip(tests, results):
        raw, expected, kind, name, origin = test[:5]
        out = got[2] if len(got) >= 3 else ""
        exact, named = out == expected, name in out
        for key in ("全部", f"分野 {kind}", f"由来 {origin}"):
            g = groups[key]
            g[0] += exact
            g[1] += named
            g[2] += 1
        if not named:
            misses.append(f"  {raw} → {out}（期待: {expected}）")
    total = groups["全部"]
    print(f"{label}: 名前が合う {total[1]}/{total[2]}、文が全部同じ {total[0]}/{total[2]}")
    for key in sorted(groups):
        if key != "全部":
            g = groups[key]
            print(f"  {key}: 名前が合う {g[1]}/{g[2]}、全部同じ {g[0]}/{g[2]}")
    if len(results) != len(tests):
        print(f"注意: 結果が {len(results)} 行、試験が {len(tests)} 行")
    if misses:
        print("名前が合わなかったもの（先頭 60 件）:")
        print("\n".join(misses[:60]))


def candidates(tests, results, label):
    groups = defaultdict(lambda: [0, 0, 0, 0, 0])  # first, first 3, first 9 (one page), any, all
    misses = []
    results = results + [[]] * (len(tests) - len(results))
    for test, got in zip(tests, results):
        raw, expected, mode, kind, origin = test[:5]
        cands = got[1:]
        rank = cands.index(expected) if expected in cands else None
        keys = [f"方式 {mode}", f"方式 {mode} / 由来 {origin}"]
        if not mode.startswith("info-"):  # info-… (how the typing varies) is not in the totals
            keys += ["全部", f"分野 {kind}", f"由来 {origin}"]
        for key in keys:
            g = groups[key]
            g[0] += rank == 0
            g[1] += rank is not None and rank < 3
            g[2] += rank is not None and rank < 9
            g[3] += rank is not None
            g[4] += 1
        if rank is None:
            misses.append(f"  {raw}（{mode}）→ {' / '.join(cands[:6])}（期待: {expected}）")
    total = groups["全部"]
    print(f"{label}: 先頭 {total[0]}/{total[4]}、上位3つ {total[1]}/{total[4]}、1ページ目（9つ） {total[2]}/{total[4]}、候補の中 {total[3]}/{total[4]}")
    for key in sorted(groups):
        if key != "全部":
            g = groups[key]
            print(f"  {key}: 先頭 {g[0]}/{g[4]}、上位3つ {g[1]}/{g[4]}、1ページ目 {g[2]}/{g[4]}、候補の中 {g[3]}/{g[4]}")
    if len(results) != len(tests):
        print(f"注意: 結果が {len(results)} 行、試験が {len(tests)} 行")
    if misses:
        print("候補になかったもの（先頭 60 件）:")
        print("\n".join(misses[:60]))


def main():
    kind, test_path, result_path = sys.argv[1:4]
    label = sys.argv[4] if len(sys.argv) > 4 else {"sentences": "固有名詞の文", "candidates": "固有名詞の候補"}[kind]
    tests, results = read_tests(test_path), read_results(result_path)
    for test, got in zip(tests, results):
        if got and test[0] != got[0]:
            sys.exit(f"order differs: {test[0]} / {got[0]}")
    (sentences if kind == "sentences" else candidates)(tests, results, label)


if __name__ == "__main__":
    main()
