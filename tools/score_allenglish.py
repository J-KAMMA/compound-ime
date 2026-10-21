"""英単語と重なるローマ字の試験（組 m。tests/conversion/allenglish-mixed.tsv、allenglish-ja.tsv）の採点。

  python tools/score_allenglish.py mixed tests/conversion/allenglish-mixed.tsv results/allenglish-mixed.tsv [label]
  python tools/score_allenglish.py ja    tests/conversion/allenglish-ja.tsv    results/allenglish-ja.tsv    [label]
  python tools/score_allenglish.py compare <mixed|ja> <試験の表> <結果A> <結果B>   # 2つの結果を並べる（A: 止めた版、B: 既定）

mixed: 変換結果の確定した文に、期待する英語（phrase、paired、rare、sentence は空白も含めてそのまま）が出ているか。
  alone は日本語の語としても読めるので、決め手がなく、数だけ出して合否にしない。
ja: 英字（A-Z、a-z）が1文字でも混じったら失敗（日本語の文が英字に化けた）。化けた文は全部並べる。
結果の形は tools/batch_convert.sh の出力（入力<TAB>文節<TAB>確定した文）。
"""
import re
import sys
from collections import OrderedDict

LETTER = re.compile(r"[A-Za-zＡ-Ｚａ-ｚ]")


def load_cases(path):
    cases = []
    for line in open(path, encoding="utf-8"):
        if line.startswith("#") or not line.strip():
            continue
        p = line.rstrip("\n").split("\t")
        cases.append({"raw": p[0], "text": p[1], "kind": p[2], "english": p[3] if len(p) > 3 else ""})
    return cases


def load_output(path):
    out = {}
    for line in open(path, encoding="utf-8"):
        p = line.rstrip("\n").split("\t")
        if len(p) >= 3:
            out[p[0]] = p[2]
    return out


def judge(mode, case, output):
    if mode == "mixed":
        return case["english"] in output
    return not LETTER.search(output)


def score(mode, cases, got):
    kinds = OrderedDict()
    failed = []
    for case in cases:
        output = got.get(case["raw"])
        if output is None:
            continue
        ok = judge(mode, case, output)
        entry = kinds.setdefault(case["kind"], [0, 0])
        entry[0] += ok
        entry[1] += 1
        if not ok:
            failed.append((case, output))
    return kinds, failed


def main():
    mode = sys.argv[1]
    if mode == "compare":
        sub, table, a_path, b_path = sys.argv[2:6]
        cases = load_cases(table)
        a, b = load_output(a_path), load_output(b_path)
        better = worse = 0
        for case in cases:
            if case["raw"] not in a or case["raw"] not in b:
                continue
            ok_a, ok_b = judge(sub, case, a[case["raw"]]), judge(sub, case, b[case["raw"]])
            if ok_b and not ok_a:
                better += 1
            elif ok_a and not ok_b:
                worse += 1
                print(f"  悪くなった: {case['raw']} → A: {a[case['raw']]} / B: {b[case['raw']]}")
        print(f"A→B: よくなった {better}、悪くなった {worse}")
        return
    cases = load_cases(sys.argv[2])
    got = load_output(sys.argv[3])
    label = sys.argv[4] if len(sys.argv) > 4 else ("英単語と重なるローマ字（英語にしたい文）" if mode == "mixed" else "英単語と重なるローマ字（日本語だけの文）")
    kinds, failed = score(mode, cases, got)
    if mode == "mixed":
        counted = [k for k in kinds if k != "alone"]
        ok = sum(kinds[k][0] for k in counted)
        total = sum(kinds[k][1] for k in counted)
        print(f"{label}: 英語で出た {ok}/{total}（alone は数えない）")
    else:
        ok = sum(v[0] for v in kinds.values())
        total = sum(v[1] for v in kinds.values())
        print(f"{label}: 日本語のまま {ok}/{total}、英字が混じった {total - ok}")
    for kind, (k_ok, k_total) in kinds.items():
        print(f"  {kind}: {k_ok}/{k_total}")
    if mode == "ja" and failed:
        print("英字が混じったもの:")
        for case, output in failed:
            print(f"  {case['raw']} → {output}（元: {case['text']}）")
    if mode == "mixed":
        print("英語で出なかったもの（先頭40、alone を除く）:")
        shown = 0
        for case, output in failed:
            if case["kind"] == "alone":
                continue
            print(f"  [{case['kind']}] {case['raw']} → {output}（期待: {case['english']}）")
            shown += 1
            if shown >= 40:
                break


if __name__ == "__main__":
    main()
