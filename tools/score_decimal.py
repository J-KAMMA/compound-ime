"""数字の間の点と文末の句点の試験（tests/conversion/decimal.tsv、decimal-ja.tsv）の採点。

  python tools/score_decimal.py <試験の tsv> <結果の tsv> [ラベル] [--halfwidth] [--soft]

結果の tsv は tools/batch_convert.sh の出力（打った文字列<TAB>変換前の表示<TAB>確定した文）。

見るのは、数字と「. , 。 、 %」の並び、および算用数字のすぐあとに付く漢字の単位（十百千万億兆）
だけ（漢字・かなの選び方は見ない）。単位を見るのは、打った数字を戻すときに「3億」の億を
消していないか（3 にしていないか）を確かめるため。全角の数字・「．」「，」「％」は
半角と同じとして比べる（数字の設定が全角の既定でも通る）。
  --halfwidth  数字の設定が半角のときの試験。出力に全角の数字・「．」「，」があれば違いとする
               （「4．1」のように、数字は半角で点だけ全角になるのもここで見つかる）
  --soft       違いがあっても終了コードを 0 にする（比べるだけのとき）
違いが1つでもあれば、終了コード 1。違いは全部出す（区分ごとの数も出す）。
"""
import sys

FULL = str.maketrans("０１２３４５６７８９．，％", "0123456789.,%")
KEEP = set("0123456789.,。、%")
FULL_FORMS = set("０１２３４５６７８９．，")  # ％ は対象外（「%」の幅はこの直しの外）
DIGITS = set("0123456789")
UNITS = set("十百千万億兆")


def skeleton(text):
    return "".join(c for c in text.translate(FULL) if c in KEEP)


def unit_skeleton(text):
    """算用数字のすぐあとに続く漢字の単位だけを取り出す（3億 → 3億、百円 → 空）。"""
    out = []
    previous_digit = False
    for c in text.translate(FULL):
        if c in DIGITS:
            out.append(c)
            previous_digit = True
        elif c in UNITS and previous_digit:
            out.append(c)
            previous_digit = False
        else:
            previous_digit = False
    return "".join(out)


KANJI_DIGITS = set("〇零一二三四五六七八九十百千万億兆")


def lead_skeleton(text):
    """算用数字のすぐ前にある漢数字だけを取り出す（二十20 → 二十、3億 → 空）。
    かなで打った漢数字の語が、打った数字のとなりで消えていないかを見る。"""
    out = []
    run = []
    for c in text.translate(FULL):
        if c in KANJI_DIGITS:
            run.append(c)
        else:
            if c in DIGITS and run:
                out.append("".join(run))
            run = []
    return "|".join(out)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    tests = []
    for line in open(args[0], encoding="utf-8"):
        if line.startswith("#") or not line.strip():
            continue
        p = line.rstrip("\n").split("\t")
        tests.append((p[0], p[1], p[2] if len(p) > 2 else ""))
    got = {}
    for line in open(args[1], encoding="utf-8"):
        p = line.rstrip("\n").split("\t")
        if len(p) >= 3:
            got[p[0]] = p[2]
    label = args[2] if len(args) > 2 else "数字の間の点"
    total = same = exact = 0
    missing = 0
    groups = {}
    bad = []
    for raw, want, category in tests:
        out = got.get(raw)
        if out is None:
            missing += 1
            continue
        total += 1
        ok = skeleton(out) == skeleton(want)
        if "--preedit" not in flags:  # 入力中の表示は変換しないので、単位とかなの漢数字は見ない
            ok = ok and unit_skeleton(out) == unit_skeleton(want) and lead_skeleton(out) == lead_skeleton(want)
        if ok and "--halfwidth" in flags and any(c in FULL_FORMS for c in out):
            ok = False
        same += ok
        exact += out == want
        counts = groups.setdefault(category, [0, 0])
        counts[0] += ok
        counts[1] += 1
        if not ok:
            bad.append(f"  [{category}] {raw} → {out}（期待 {want}）")
    print(f"{label}: 数字・点・単位の並びが合う {same}/{total}、文字まで同じ {exact}/{total}"
          + (f"、結果がない {missing}" if missing else ""))
    for category in sorted(groups):
        print(f"  {category}: {groups[category][0]}/{groups[category][1]}")
    if bad:
        print(f"違い {len(bad)} 件:")
        print("\n".join(bad))
    if (bad or missing) and "--soft" not in flags:
        sys.exit(1)


main()
