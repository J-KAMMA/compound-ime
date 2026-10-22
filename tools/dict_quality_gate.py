"""辞書の月1回の自動更新で、「悪くならなかったか」を決める（止める基準）。基準の値は tools/data/dict-gate.json。

  python tools/dict_quality_gate.py data   --old-dir <いまの一覧のある所> --new-dir <取り直した一覧のある所> [--summary out.md]
  python tools/dict_quality_gate.py scores --base <基準の結果の所> --cand <新しい辞書の結果の所> [--summary out.md] [--json out.json] [--identical]

data:   取り直した一覧（proper-nouns.tsv、supplement.tsv、english-extra.tsv）の行数が、いまの一覧と比べて決めた幅の中か。
        外れたら、試験を流す前に止める（Wikidata の取得の失敗や出典の変更を早く見つけるため）。
scores: 同じ変換エンジンで、いまの辞書（基準）と新しい辞書（候補）を流した試験の採点（*-score.txt）を比べる。
        正解を数える項目が、許す下がり（件数）より多く下がったら止める。許す下がりは max(min_items, 総数×percent%) の切り上げ。
        候補に採点の結果がない（試験が流れなかった）ときも止める。変わった文の数（inputs.tsv）は報告だけ。
        --identical: 新しい辞書の中身がいまの辞書と同じはずのとき（Wikidata を取り直さない流し方）。両方の結果の
        *.tsv が1行も違わないことを求める。違えば、差のある文を数えて止める（同じ中身なら結果は変わらないはず）。
終了の値: 0 通ってよい、1 止める。
"""
import argparse
import json
import math
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RULES = HERE / "data" / "dict-gate.json"


def count_rows(path: Path) -> int:
    return sum(1 for l in path.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#"))


def gate_data(rules, old_dir: Path, new_dir: Path):
    rows, failures = [], []
    for name, rule in rules["data"].items():
        if name.startswith("_"):
            continue
        new = new_dir / name
        if not new.exists():
            rows.append((name, "-", "なし", "-", "NG 取り直した一覧がない"))
            failures.append(f"{name}: 取り直した一覧がない")
            continue
        n = count_rows(new)
        old_path = old_dir / name
        old = count_rows(old_path) if old_path.exists() else None
        problems = []
        if n < rule.get("min_rows", 0):
            problems.append(f"行数 {n} が下限 {rule['min_rows']} より少ない")
        ratio = None
        if old:
            ratio = n / old
            if ratio < rule["min_ratio"] or ratio > rule["max_ratio"]:
                problems.append(f"いまの一覧との比 {ratio:.2f} が {rule['min_ratio']}〜{rule['max_ratio']} の外")
        rows.append((name, old if old is not None else "-", n, f"{ratio:.2f}" if ratio is not None else "-",
                     "NG " + "、".join(problems) if problems else "OK"))
        failures += [f"{name}: {p}" for p in problems]
    return rows, failures


def search(text, pattern):
    m = re.search(pattern, text)
    if not m:
        return None
    total = None
    if m.lastindex and m.lastindex >= 2 and m.group(2):
        total = int(m.group(2))
    return int(m.group(1)), total


def read(dirpath: Path, name):
    p = dirpath / name
    return p.read_text(encoding="utf-8") if p.exists() else None


def metric_value(dirpath: Path, metric):
    text = read(dirpath, metric["file"])
    if text is None:
        return None
    found = search(text, metric["pattern"])
    if found is None:
        return None
    value, total = found
    if total is None and metric.get("total_from"):
        file, _, pattern = metric["total_from"].partition("|")
        other = read(dirpath, file)
        t = search(other, pattern) if other else None
        total = t[0] if t else None
    return value, total


def gate_scores(rules, base: Path, cand: Path):
    rows, failures, notes = [], [], []
    for metric in rules["metrics"]:
        b, c = metric_value(base, metric), metric_value(cand, metric)
        if b is None:
            notes.append(f"{metric['name']}: 基準の結果がないので比べない")
            continue
        if c is None:
            rows.append((metric["name"], b[0], "なし", "-", "-", "NG 候補の採点がない（試験が流れなかった）"))
            failures.append(f"{metric['name']}: 候補の採点がない")
            continue
        tol = rules["tolerance"][metric["group"]]
        total = b[1] or c[1] or 0
        allowed = max(tol["min_items"], math.ceil(total * tol["percent"] / 100))
        diff = c[0] - b[0]
        worse = -diff if metric["better"] == "higher" else diff
        verdict = "OK"
        if worse > allowed:
            verdict = f"NG {worse} 件悪くなった（許すのは {allowed} 件まで）"
            failures.append(f"{metric['name']}: {b[0]} → {c[0]}（{worse} 件悪くなった、許すのは {allowed} 件まで）")
        rows.append((metric["name"], b[0], c[0], f"{diff:+d}", allowed, verdict))
    changed = None
    spec = rules.get("changed_sentences")
    if spec:
        bt, ct = read(base, spec["file"]), read(cand, spec["file"])
        if bt and ct:
            def load(text):
                return {l.split("\t")[0]: l.rstrip("\n").split("\t")[2] for l in text.splitlines() if l.count("\t") >= 2}
            bm, cm = load(bt), load(ct)
            changed = (sum(1 for k, v in cm.items() if bm.get(k) != v), len(cm))
    return rows, failures, notes, changed


def gate_identical(base: Path, cand: Path):
    """同じ中身の辞書なら、結果の *.tsv は1行も違わない。違う行を数える。"""
    failures, details = [], []
    names = sorted(p.name for p in base.glob("*.tsv"))
    if not names:
        return ["基準の結果の *.tsv がない"], details
    for name in names:
        b = (base / name).read_text(encoding="utf-8").splitlines()
        cp = cand / name
        if not cp.exists():
            failures.append(f"{name}: 新しい辞書の結果がない")
            continue
        c = cp.read_text(encoding="utf-8").splitlines()
        diff = [i for i in range(max(len(b), len(c))) if (b[i] if i < len(b) else None) != (c[i] if i < len(c) else None)]
        if diff:
            failures.append(f"{name}: {len(diff)} 行が違う（行数 {len(b)} と {len(c)}）")
            for i in diff[:3]:
                details.append(f"{name} {i + 1} 行目: {(b[i] if i < len(b) else '')[:90]} → {(c[i] if i < len(c) else '')[:90]}")
    return failures, details


def table(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "|".join(["---"] * len(header)) + "|"]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("data")
    d.add_argument("--old-dir", type=Path, required=True)
    d.add_argument("--new-dir", type=Path, required=True)
    s = sub.add_parser("scores")
    s.add_argument("--base", type=Path, required=True)
    s.add_argument("--cand", type=Path, required=True)
    for p in (d, s):
        p.add_argument("--rules", type=Path, default=RULES)
        p.add_argument("--summary", type=Path)
        p.add_argument("--json", type=Path)
    s.add_argument("--identical", action="store_true")
    args = ap.parse_args()
    rules = json.loads(args.rules.read_text(encoding="utf-8"))
    if args.cmd == "data":
        rows, failures = gate_data(rules, args.old_dir, args.new_dir)
        text = "### 取り直した一覧の行数の確かめ\n\n" + table(["一覧", "いまの行数", "新しい行数", "比", "判定"], rows)
        notes, changed = [], None
    else:
        rows, failures, notes, changed = gate_scores(rules, args.base, args.cand)
        text = "### 試験の結果（いまの辞書 → 新しい辞書）\n\n" + table(["試験", "いまの辞書", "新しい辞書", "差", "許す下がり", "判定"], rows)
        if changed:
            text += f"\n\n変わった文: 1,298 文の入力のうち {changed[0]} / {changed[1]} 文で結果が変わった（報告だけ）。"
        if notes:
            text += "\n\n" + "\n".join(f"- {n}" for n in notes)
    if args.cmd == "scores" and args.identical:
        same, details = gate_identical(args.base, args.cand)
        text += "\n\n同じ中身の確かめ（結果の *.tsv が1行も違わないか）: " + ("全部一致" if not same else f"{len(same)} ファイルで違う")
        if same:
            text += "\n" + "\n".join(f"- {s}" for s in same) + "\n\n違いの例:\n" + "\n".join(f"- {d}" for d in details[:12])
        failures += [f"同じ中身なのに結果が違う: {s}" for s in same]
    verdict = "止める" if failures else "通ってよい"
    text += f"\n\n**判定: {verdict}**"
    if failures:
        text += "\n\n止める理由:\n" + "\n".join(f"- {f}" for f in failures)
    print(text)
    if args.summary:
        with args.summary.open("a", encoding="utf-8") as f:
            f.write(text + "\n\n")
    if args.json:
        args.json.write_text(json.dumps({"passed": not failures, "failures": failures}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 1 if failures else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
