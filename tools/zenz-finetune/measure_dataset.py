#!/usr/bin/env python3
"""練習問題の部品を数字にして、1問あたりの字数・ファイルの大きさ・数字にする速さを測る（Colab の見積りの根拠）。

  python measure_dataset.py --data dataset/ --tokenizer tokenizer/ [--end-id 3] [--limit 0]

--data に manifest.json か、部品（train-*.jsonl.gz）が入っている。--tokenizer は vocab.json などの入ったフォルダ
（zenz-v3.1-small のもの）。結果を表示して、--data/measure.json に書く。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import zenz_tune as z  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True)
    ap.add_argument("--tokenizer", required=True)
    ap.add_argument("--end-id", type=int, default=3)
    ap.add_argument("--limit", type=int, default=0, help="この数の部品ファイルだけ（0 は全部）")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(args.tokenizer)
    data = Path(args.data)
    parts = sorted(data.glob("train*.jsonl*"))
    if args.limit:
        parts = parts[:args.limit]
    started = time.time()
    ex, dropped = z.load_examples(parts, tok, args.end_id)
    seconds = time.time() - started
    npz = data / "measure-train.npz"
    ex.save(npz)
    n, tokens = len(ex), int(ex.length.sum())
    file_bytes = sum(p.stat().st_size for p in parts)
    result = {
        "parts": [p.name for p in parts], "examples": n, "dropped_too_long": dropped, "tokens": tokens,
        "tokens_per_example": round(tokens / n, 2), "tokenize_seconds": round(seconds, 1),
        "examples_per_second": round(n / seconds), "jsonl_bytes": file_bytes,
        "jsonl_bytes_per_example": round(file_bytes / n, 1), "npz_bytes": npz.stat().st_size,
        "npz_bytes_per_token": round(npz.stat().st_size / tokens, 3), "id_dtype": str(ex.ids.dtype),
        "by_kind_tokens": {name: round(float(ex.length[ex.kinds == k].mean()), 1) for k, name in enumerate(ex.kind_names)},
    }
    npz.unlink()
    (data / "measure.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
