"""判定の門の学習用の文を作る（試験に使っていないウィキペディアの分割から）。

  python tools/jev_gate_sentences.py --wiki <ja parquet か文章ファイル> --table <romanji-hiragana.tsv> \
      --out <train.tsv> [--count 100000] [--seed 20261019] [--prev-share 0.6]

tools/wiki_typing_test.py と同じ条件（10〜40字、漢字・かな・ー・、。だけ、SudachiPy の読みからローマ字を作り、
かなに戻して同じになるものだけ）で、段落ごとに1文を選ぶ。選んだ文の1つ前の文（同じ段落、80字まで）があれば
前の文として付ける（付ける割合は --prev-share。残りは前の文なし）。試験の文（tests/conversion）と
表記・読みが同じか含む文は除く。ローマ字が同じ文は1つだけ残す（変換の結果をローマ字で引くため）。
出力（先頭の # の行は説明）: ローマ字<TAB>元の文<TAB>前の文
ウィキペディア日本語版（CC BY-SA 4.0）の文。出力はリポジトリに入れない（成果物にだけ置く）。
"""
import argparse
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "zenz-finetune"))
sys.path.insert(0, str(HERE))
import build_dataset as bd  # noqa: E402
import romaji_variants as rv  # noqa: E402

SURFACE = re.compile(r"[一-龯々〆ヵヶぁ-ゖァ-ヺー、。]+")
PREV_MAX = 80


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wiki", nargs="+", required=True)
    ap.add_argument("--table", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--count", type=int, default=100000)
    ap.add_argument("--seed", type=int, default=20261019)
    ap.add_argument("--prev-share", type=float, default=0.6)
    ap.add_argument("--repo", default=str(HERE.parent))
    args = ap.parse_args()
    table = rv.load_table(args.table)
    rev = rv.reverse_table(table)
    reader = bd.SudachiReader("core")
    exclusion = bd.TestExclusion(Path(args.repo) / "tests/conversion", bd.load_romaji_table(Path(args.table)))
    rng = random.Random(args.seed)
    lines, seen_surface, seen_raw = [], set(), set()
    excluded = 0
    for _, text in bd.iter_wiki_articles(args.wiki, rng):
        for paragraph in bd.split_paragraphs(text):
            # 段落の中の候補を並べ替え、最初に条件に合った1文を選ぶ（前の文がある文を先に試す）
            order = list(range(len(paragraph)))
            rng.shuffle(order)
            order.sort(key=lambda i: 0 if i > 0 else 1)
            for i in order:
                sentence = paragraph[i]
                if not (10 <= len(sentence) <= 40) or not SURFACE.fullmatch(sentence) or sentence in seen_surface:
                    continue
                if not re.search(r"[ぁ-ゖ]", sentence) or sentence[0] in "、。":
                    continue
                tokens = reader.analyze(sentence)
                if not tokens:
                    continue
                kana = bd.to_hiragana("".join(t.reading for t in tokens))
                if exclusion.blocked(sentence, [kana]):
                    excluded += 1
                    continue
                raw = rv.write(kana, "base", rev)
                if not raw or rv.to_kana(raw, table) != kana or raw in seen_raw:
                    continue
                prev = paragraph[i - 1] if i > 0 else ""
                if len(prev) > PREV_MAX or "\t" in prev or rng.random() >= args.prev_share:
                    prev = ""
                seen_surface.add(sentence)
                seen_raw.add(raw)
                lines.append(f"{raw}\t{sentence}\t{prev}")
                break
            if len(lines) >= args.count:
                break
        if len(lines) >= args.count:
            break
    header = ("# ウィキペディア日本語版（CC BY-SA 4.0、https://ja.wikipedia.org/）の文を、SudachiPy の読みから"
              "ローマ字にしたもの。tools/jev_gate_sentences.py で作成。ローマ字<TAB>元の文<TAB>前の文\n")
    Path(args.out).write_text(header + "\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    with_prev = sum(1 for l in lines if l.split("\t")[2])
    print(f"{len(lines)} 文（前の文つき {with_prev}）、試験と重なって除いた {excluded}")


if __name__ == "__main__":
    main()
