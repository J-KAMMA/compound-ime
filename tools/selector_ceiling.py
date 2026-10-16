"""Selector stage 0 (選び手の段階0): how many wrong sentences could be made right
by picking among the first 8 candidates of each segment.

  python tools/selector_ceiling.py <dump.txt> <results.tsv> <tests.json> <romanji-hiragana.tsv>

dump.txt: MYIME_SELECTOR_DUMP lines (segments joined by U+0001, each
key<TAB>candidates...). A sentence's line is the last one whose joined keys
equal the sentence's reading (romaji read with Mozc's table; English pieces
stay as typed). Prints, for the sentences that came out wrong, how many have
the answer among the candidates (the ceiling), by category, and lists them.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import romaji_variants as rv  # noqa: E402


def reachable(segments, answer):
    """Whether answer is a concatenation of one candidate per segment, in order."""
    ends = {0}
    for cands in segments:
        nxt = set()
        for at in ends:
            for c in cands:
                if c and answer.startswith(c, at):
                    nxt.add(at + len(c))
        if not nxt:
            return False
        ends = nxt
    return len(answer) in ends


def main():
    dump_path, results_path, tests_path, table_path = sys.argv[1:5]
    table = rv.load_table(table_path)
    last = {}
    for line in Path(dump_path).read_text(encoding="utf-8", errors="replace").splitlines():
        segs = [s.split("\t") for s in line.split("\x01")]
        last["".join(s[0] for s in segs)] = [s[1:] for s in segs]
    got = {}
    for line in Path(results_path).read_text(encoding="utf-8").splitlines():
        p = line.split("\t")
        if len(p) >= 3:
            got[p[0]] = p[2]
    items = json.loads(Path(tests_path).read_text(encoding="utf-8"))["items"]
    wrong = reach = missing = 0
    by_cat = {}
    listed = []
    for it in items:
        out = got.get(it["romaji"])
        answers = [it["intended"]] + it.get("alternatives", [])
        if out is None or out in answers or out.lower() == it["intended"].lower():
            continue
        wrong += 1
        cat = it.get("category", "")
        stat = by_cat.setdefault(cat, [0, 0])
        stat[0] += 1
        segs = last.get(rv.to_kana(it["romaji"], table))
        if segs is None:
            missing += 1
            continue
        if any(reachable(segs, a) for a in answers):
            reach += 1
            stat[1] += 1
            listed.append(f"  {cat}: {out} → {it['intended']}")
    print(f"選び手で直せる上限: 間違い {wrong} 文のうち、候補の上位8つから正解を組める {reach} 文"
          f"（候補の記録が見つからない {missing} 文）")
    for cat, (w, r) in sorted(by_cat.items()):
        print(f"  {cat}: {r}/{w}")
    print("\n".join(listed[:80]))


if __name__ == "__main__":
    main()
