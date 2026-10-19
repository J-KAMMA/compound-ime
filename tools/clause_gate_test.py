"""前後の文での並べ替え（contextPriorWinner）の門を比べるための、句ごとの試験。

  python tools/clause_gate_test.py make tests/conversion/context.tsv > clause.tsv
  python tools/clause_gate_test.py score clause.tsv 基準.tsv 比べる版.tsv 名前

前後の文がある試験（context.tsv）の文は句読点を含むので、読みがかなだけの条件を満たさず、並べ替えが働かない
（1000 文で 11 回）。そこで文の最初の句（読点・句点の前まで）だけを、前の文を渡して変換し、元の句と同じになるかを数える。
並べ替えは読みに句読点がない変換でだけ働くので、これが並べ替えの効きを見る試験になる。

make: ローマ字<TAB>元の句<TAB>前の文 を書き出す（句の読みが 6 字以上で、かなと漢字だけの句）。
score: 版ごとの正解の数と、基準との違い（基準で正解だったのに外れた句、外れていたのに正解になった句）。
"""
import re
import sys


def make(path):
    seen = set()
    for line in open(path, encoding="utf-8"):
        if line.startswith("#") or not line.strip():
            continue
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 3:
            continue
        raw, original, before = parts[:3]
        romaji = re.split(r"[,.]", raw, maxsplit=1)
        found = re.search(r"[、。]", original)
        if len(romaji) < 2 or not found:
            continue
        clause = original[: found.start()]
        if len(romaji[0]) < 6 or not clause or not re.fullmatch(r"[぀-ヿ一-鿿々]+", clause):
            continue
        if romaji[0] in seen:
            continue
        seen.add(romaji[0])
        print(f"{romaji[0]}\t{clause}\t{before}")


def load_result(path):
    out = {}
    for line in open(path, encoding="utf-8"):
        parts = line.rstrip("\n").split("\t")
        if len(parts) >= 3:
            out[parts[0]] = parts[2]
    return out


def score(clause_path, base_path, var_path, label):
    gold = {}
    for line in open(clause_path, encoding="utf-8"):
        parts = line.rstrip("\n").split("\t")
        if len(parts) >= 3:
            gold[parts[0]] = parts[1]
    base, var = load_result(base_path), load_result(var_path)
    right_base = sum(base.get(r) == g for r, g in gold.items())
    right_var = sum(var.get(r) == g for r, g in gold.items())
    changed = [r for r in gold if base.get(r) != var.get(r)]
    lost = [r for r in changed if base.get(r) == gold[r]]
    gained = [r for r in changed if var.get(r) == gold[r]]
    print(f"{label}: 正解 {right_var}/{len(gold)}（基準 {right_base}）、基準と違う句 {len(changed)}、"
          f"基準で正解だったのに外れた {len(lost)}、外れていたのに正解になった {len(gained)}")
    for r in lost[:15]:
        print(f"  失った: {base[r]} → {var.get(r)}（元: {gold[r]}）")
    for r in gained[:5]:
        print(f"  得た: {base.get(r)} → {var[r]}")


if __name__ == "__main__":
    if sys.argv[1] == "make":
        make(sys.argv[2])
    else:
        score(*sys.argv[2:6])
