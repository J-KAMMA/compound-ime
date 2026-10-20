"""jev_gate.cc（IME に組み込む推論の入り口）の入力の作り方と出力を、torch の出力と比べるための見本を書く。

  python tools/jev-gate/jev_gate_cases.py --ckpt final.pt --records test-records.jsonl.gz --out cases.tsv [--n 200]
  g++ -O3 -std=c++17 -mavx2 -mfma -pthread tools/jev-gate/jev_gate_check.cc tools/jev-gate/jev_gate.cc -o jev_gate_check
  ./jev_gate_check <jevgate.bin> cases.tsv

見本の 1 行: 前の文<TAB>読み<TAB>候補1<TAB>出どころ1<TAB>…<TAB>#<TAB>need need_k need_top1 harm_k<TAB>点…
前の文の改行は \n、バックスラッシュは \\ と書く。候補は先頭の k 個（生成なしで作れるもの）。
"""
import argparse
import sys
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jevgate as jg  # noqa: E402


def esc(s):
    return s.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", " ")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--records", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=200)
    a = ap.parse_args()
    model, vocab = jg.load_model(a.ckpt)
    model.eval()
    cfg = model.cfg
    k = model.k
    lines = []
    for rec in jg.iter_records(a.records, a.n * 3):
        if len(lines) >= a.n:
            break
        cands = rec["cands"][:k]
        if not cands:
            continue
        s = jg.featurize(rec, vocab, cfg)
        b = jg.collate([s], k, with_v5=False)
        with torch.no_grad():
            o = model(b)
        gate = torch.sigmoid(o["gate"][0]).tolist()
        sc = o["score"][0][b["cvalid"][0]].tolist()
        fields = [esc(jg.last_line_tail(rec["prev"], 100000)), esc(rec["reading"])]
        for c in cands:
            src = jg.SRC_ID.get(c[2][:1], 3) if c[2] else 3
            fields += [esc(c[0]), str(src)]
        fields += ["#", " ".join(f"{x:.6f}" for x in gate), " ".join(f"{x:.6f}" for x in sc)]
        lines.append("\t".join(fields))
    Path(a.out).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("書きました:", a.out, len(lines))


if __name__ == "__main__":
    main()
