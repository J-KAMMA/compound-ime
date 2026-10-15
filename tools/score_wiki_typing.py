"""Scores the Wikipedia typing test (ウィキペディアの打ち込み試験).

  python tools/score_wiki_typing.py tests/conversion/wiki-typing.tsv results.tsv

How many sentences come out exactly as written in Wikipedia (many differ only
in kanji or kana choice, so this is for comparing versions, not a pass mark),
and the sentences that came out with English letters although none were
typed for English (a Japanese reading taken as an English word, as kite in
okiteiru): these should be none and are all listed.
"""
import re
import sys


def main():
    cases = []
    for line in open(sys.argv[1], encoding="utf-8"):
        if line.startswith("#") or not line.strip():
            continue
        raw, original = line.rstrip("\n").split("\t")[:2]
        cases.append((raw, original))
    got = {}
    for line in open(sys.argv[2], encoding="utf-8"):
        p = line.rstrip("\n").split("\t")
        if len(p) >= 3:
            got[p[0]] = p[2]
    total = exact = 0
    letters = []
    for raw, original in cases:
        out = got.get(raw)
        if out is None:
            continue
        total += 1
        exact += out == original
        if re.search(r"[A-Za-zＡ-Ｚａ-ｚ]", out):
            letters.append(f"  {raw} → {out}（元: {original}）")
    print(f"ウィキペディアの打ち込み: 元の文と同じ {exact}/{total}、英字が混じった {len(letters)}")
    if letters:
        print("英字が混じったもの:")
        print("\n".join(letters[:200]))


if __name__ == "__main__":
    main()
