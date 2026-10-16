"""Scores the Wikipedia typing test (ウィキペディアの打ち込み試験) and the domain
typing tests (分野の打ち込み試験, tests/conversion/domain-prog.tsv and
domain-crypto.tsv, which have the source name as a third column).

  python tools/score_wiki_typing.py tests/conversion/wiki-typing.tsv results.tsv [label]

How many sentences come out exactly as written in the original (many differ only
in kanji or kana choice, so this is for comparing versions, not a pass mark),
and the sentences that came out with English letters although the original has
none (a Japanese reading taken as an English word, as kite in okiteiru): these
should be none and are all listed. For a test with a third column, the count is
also given for each source and for sentences with and without English words
(git, npm, Python ...) in the original.
"""
import re
import sys

LETTER = re.compile(r"[A-Za-zＡ-Ｚａ-ｚ]")


def main():
    cases = []
    for line in open(sys.argv[1], encoding="utf-8"):
        if line.startswith("#") or not line.strip():
            continue
        parts = line.rstrip("\n").split("\t")
        cases.append((parts[0], parts[1], parts[2] if len(parts) > 2 else ""))
    label = sys.argv[3] if len(sys.argv) > 3 else "ウィキペディアの打ち込み"
    got = {}
    for line in open(sys.argv[2], encoding="utf-8"):
        p = line.rstrip("\n").split("\t")
        if len(p) >= 3:
            got[p[0]] = p[2]
    total = exact = 0
    letters = []
    groups = {}  # 出典、英字入り、日本語だけ → [一致, 全部]
    misses = []
    for raw, original, source in cases:
        out = got.get(raw)
        if out is None:
            continue
        total += 1
        ok = out == original
        exact += ok
        keys = ([f"出典 {source}"] if source else []) + (
            ["英字入りの文" if LETTER.search(original) else "日本語だけの文"] if source else [])
        for key in keys:
            counts = groups.setdefault(key, [0, 0])
            counts[0] += ok
            counts[1] += 1
        if not ok and source:
            misses.append(f"  {raw} → {out}（元: {original}）")
        if not LETTER.search(original) and LETTER.search(out):
            letters.append(f"  {raw} → {out}（元: {original}）")
    print(f"{label}: 元の文と同じ {exact}/{total}、英字が混じった {len(letters)}")
    for key in sorted(groups):
        same, count = groups[key]
        print(f"  {key}: {same}/{count}")
    if letters:
        print("英字が混じったもの:")
        print("\n".join(letters[:200]))
    if misses:
        print("元の文と違ったもの（先頭 150 件）:")
        print("\n".join(misses[:150]))


if __name__ == "__main__":
    main()
