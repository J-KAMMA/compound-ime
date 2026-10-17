"""分野の文書の文から、Mozc の辞書で変換できない言葉を拾って、小さな追加辞書を作る。

  python tools/build_domain_words.py --sentences sentences.jsonl --mozc <mozc/src> \
      [--extra-dict dictionary10.txt ...] --out tools/data/domain-words.tsv [--min-count 5]

材料: tools/zenz-finetune/domain_text.py が作る sentences.jsonl（流れ「Domain data」の成果物）のうち、
split が train の文だけを使う。試験用（split が test）の文と tests/conversion/ の文は使わない
（試験への漏れを防ぐため。--exclude で試験の tsv を渡すと、同じ文もはずす）。

手順:
  1. SudachiPy（分割の単位 C）で文を区切り、カタカナだけの名詞を数える（漢字まじりは読みの当てずっぽうが混ざるので除く。
     ASCII を含む言葉も除く。英単語は別の仕組み）。
  2. 読みは SudachiDict の読み（かなに直す）。未登録語（OOV）で漢字を含むものは読みが当てにならないので除く。
  3. Mozc の辞書（dictionary00〜09 と --extra-dict）に (読み, 表記) の組があるものは除く。残りが
     「今の辞書にない言葉」（--compose で、組の連なりで作れるものも除く）。
  4. 出る回数が --min-count 以上のものを、出る回数の多い順に書き出す。

出力は mozcdic-ut と同じ形（読み<TAB>0000<TAB>0000<TAB>費用<TAB>表記）。費用は出る回数で段にする
（多いほど安い）。build_ut_dictionary.py の --local-source domain=<このファイル> で足せる。
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ASCII = re.compile(r"[\x00-\x7f]")
HAS_KANJI = re.compile(r"[一-鿿々〆ヶ]")
KATA = re.compile(r"[ァ-ヺー]+")


def to_hiragana(text):
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in text)


def cost_for(count):
    if count >= 30:
        return 8000
    if count >= 12:
        return 8250
    return 8500


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sentences", type=Path, required=True)
    parser.add_argument("--mozc", type=Path, required=True)
    parser.add_argument("--extra-dict", type=Path, action="append", default=[])
    parser.add_argument("--exclude", type=Path, action="append", default=[],
                        help="試験の tsv（1列目が文）。同じ文は使わない")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--min-count", type=int, default=5)
    parser.add_argument("--min-docs", type=int, default=2, help="この数以上の文書に出る言葉だけ")
    parser.add_argument("--report", type=Path, help="拾った言葉の出る回数つきの一覧")
    parser.add_argument("--compose", action="store_true", help="辞書の組の連なりで作れる言葉は除く（既定は組の有無だけで除く。連なりは1文字の組でも作れてしまい、ほとんど除かれるため）")
    args = parser.parse_args()

    from sudachipy import dictionary, tokenizer
    tok = dictionary.Dictionary().create()
    mode = tokenizer.Tokenizer.SplitMode.C

    banned = set()
    for path in args.exclude:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#"):
                banned.add(line.split("\t")[0])

    counts, docs, pos_of = Counter(), {}, {}
    used = 0
    with args.sentences.open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            if row["split"] != "train" or row["text"] in banned:
                continue
            used += 1
            for m in tok.tokenize(row["text"], mode):
                pos = m.part_of_speech()
                surface = m.surface()
                if pos[0] != "名詞" or ASCII.search(surface) or len(surface) < 2:
                    continue
                if pos[1] in ("数詞", "代名詞") or pos[2] in ("人名", "地名") or pos[1] == "固有名詞" and pos[2] in ("人名", "地名"):
                    continue
                if not KATA.fullmatch(surface):  # カタカナの言葉だけ。漢字まじりは読みの当てずっぽうが混ざる
                    continue
                if m.is_oov() and HAS_KANJI.search(surface):
                    continue
                reading = to_hiragana(m.reading_form())
                if not re.fullmatch(r"[ぁ-ゖー]+", reading) or len(reading) < 3:
                    continue
                key = (reading, surface)
                counts[key] += 1
                docs.setdefault(key, set()).add(row["doc"])
                pos_of[key] = pos
    print("使った文", used, "言葉の種類", len(counts), file=sys.stderr)

    data = args.mozc / "data/dictionary_oss"
    pairs = set()
    paths = sorted(data.glob("dictionary0*.txt")) + args.extra_dict
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            fields = line.split("\t")
            if len(fields) >= 5:
                pairs.add((fields[0], fields[4]))
    print("辞書の組", len(pairs), file=sys.stderr)

    cache = {}

    def composable(reading, surface):
        """表記の全体を辞書の (読み, 表記) の連なりで作れるか。"""
        if not reading:
            return not surface
        if not surface:
            return False
        key = (reading, surface)
        if key in cache:
            return cache[key]
        ok = False
        for i in range(1, len(reading) + 1):
            for j in range(1, len(surface) + 1):
                if (reading[:i], surface[:j]) in pairs and composable(reading[i:], surface[j:]):
                    ok = True
                    break
            if ok:
                break
        cache[key] = ok
        return ok

    picked = []
    for (reading, surface), n in counts.most_common():
        if n < args.min_count or len(docs[(reading, surface)]) < args.min_docs:
            continue
        if (reading, surface) in pairs or (args.compose and composable(reading, surface)):
            continue
        picked.append((reading, surface, n, len(docs[(reading, surface)])))
    print("拾った言葉", len(picked), file=sys.stderr)
    with args.out.open("w", encoding="utf-8", newline="\n") as out:
        for reading, surface, n, _ in sorted(picked):
            out.write(f"{reading}\t0000\t0000\t{cost_for(n)}\t{surface}\n")
    if args.report:
        with args.report.open("w", encoding="utf-8", newline="\n") as out:
            for reading, surface, n, d in picked:
                out.write(f"{n}\t{d}\t{reading}\t{surface}\t{','.join(pos_of[(reading, surface)][:3])}\n")


if __name__ == "__main__":
    main()
