#!/usr/bin/env python3
"""RealPersonaChat（日本語の雑談対話）の発話から、日本語の文を取り出す。練習問題の材料。

  python persona_text.py --src-root src --out out [--seed 20261015]

材料は nu-dialogue/real-persona-chat（CC BY-SA 4.0）の対話の JSON。fetch_domain_sources.py が、
domain_sources.json の persona の版（commit）を固定して、--src-root/persona/ に取り出す。

使うのは各発話の本文（utterances[].text）だけ。話者ID・ペルソナ・性格特性・属性・時刻は読まず、
出力にも残さない（作者の注意: 個人を特定しようとしない、なりすましに使わない、話者の属性や性格の推定に
使わない）。発話は句点（。！？）で文に分け、前の文（同じ対話の直前の文。話者は区別しない）を prev に入れる。

文を選ぶ（domain_text.py と同じ検査）: NFKC にそろえ、日本語の割合が低い文、短すぎる/長すぎる文、
使えない記号（絵文字・顔文字・括弧書きなど）を含む文、笑いの「w」だけの英字を含む文、重複した文を除く。

できるもの（--out の中）:
  persona-train.jsonl   1行1文: {"source": "persona", "doc": "dialogue-00001", "split": "train", "text", "prev"}
                        対話の単位で、割合 test_doc_fraction（domain_sources.json）を「試験の枠」に取り分け、
                        その対話の文は練習の材料に入れない（将来の試験用。文は書かない）
  persona-counts.json   件数と除いた理由ごとの数
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import domain_text as dt  # noqa: E402

LAUGH_ONLY = re.compile(r"^[wWｗＷ]+$")


def utterance_sentences(text: str):
    """発話を文に分ける。句点などで終わらない最後の部分も1文として返す。"""
    text = dt.normalize_text(text)
    out, pos = [], 0
    for m in dt.SENTENCE_RE.finditer(text):
        out.append(m.group(0).strip())
        pos = m.end()
    rest = text[pos:].strip()
    if rest:
        out.append(rest)
    return [s for s in out if s]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(HERE / "domain_sources.json"))
    ap.add_argument("--src-root", required=True, help="材料を取り出した場所（persona/ の下に対話の JSON）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=20261015)
    ap.add_argument("--min-len", type=int, default=5)
    ap.add_argument("--max-len", type=int, default=80)
    ap.add_argument("--min-ja-ratio", type=float, default=0.6)
    ap.add_argument("--max-english", type=int, default=3)
    ap.add_argument("--max-docs", type=int, default=0, help="対話の上限（試し用、0 は上限なし）")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    source = next(s for s in json.loads(Path(args.config).read_text(encoding="utf-8"))["sources"] if s["name"] == "persona")
    root = Path(args.src_root) / "persona" / source["root"]
    files = sorted(root.glob(source["glob"]))
    if args.max_docs:
        files = files[:args.max_docs]
    if not files:
        raise SystemExit(f"{root} に対話の JSON がありません（fetch_domain_sources.py --only persona を先に）")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stat = {"dialogues": len(files), "dialogues_test": 0, "utterances": 0, "raw_sentences": 0, "kept": 0,
            "kept_train": 0, "duplicate": 0, "reject": {}}
    seen = set()
    with open(out / "persona-train.jsonl", "w", encoding="utf-8", newline="\n") as handle:
        for path in files:
            data = json.loads(path.read_text(encoding="utf-8"))
            doc = f"dialogue-{int(data['dialogue_id']):05d}"
            is_test = dt.stable_unit(args.seed, f"persona:{doc}") < source["test_doc_fraction"]
            stat["dialogues_test"] += is_test
            previous = ""
            for utterance in data["utterances"]:   # 本文だけを読む（話者ID・時刻は見ない）
                stat["utterances"] += 1
                for sentence in utterance_sentences(utterance["text"]):
                    stat["raw_sentences"] += 1
                    why = dt.sentence_reject_reason(sentence, args.min_len, args.max_len, args.min_ja_ratio,
                                                    args.max_english)
                    if not why:
                        pieces = dt.pieces_of(sentence) or []
                        if any(kind == "en" and LAUGH_ONLY.match(text) for kind, text in pieces):
                            why = "laugh_w"
                    if why:
                        stat["reject"][why] = stat["reject"].get(why, 0) + 1
                        previous = ""
                        continue
                    key = dt.sentence_key(sentence)
                    if key in seen:
                        stat["duplicate"] += 1
                        previous = ""
                        continue
                    seen.add(key)
                    stat["kept"] += 1
                    if not is_test:
                        stat["kept_train"] += 1
                        handle.write(json.dumps({"source": "persona", "doc": doc, "split": "train", "text": sentence,
                                                 "prev": previous}, ensure_ascii=False) + "\n")
                    previous = sentence
    counts = {"settings": {"seed": args.seed, "min_len": args.min_len, "max_len": args.max_len,
                           "min_ja_ratio": args.min_ja_ratio, "max_english": args.max_english},
              "commit": source["commit"], **stat}
    (out / "persona-counts.json").write_text(json.dumps(counts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(counts, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
