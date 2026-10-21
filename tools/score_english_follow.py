"""英語の語のあとの変換の試験（組 n）の採点（2026-10-21）。

  python tools/score_english_follow.py <word|history|memory|cause|ja|control|bare> <試験の表> <既定の版の結果> [<止めた版の結果>]

表は tests/conversion/english-follow-*.tsv（tools/make_english_follow_tests.py）。結果は tools/context_convert.sh
（history は tools/english_follow_history.sh）の出力（ローマ字<TAB>文節<TAB>確定した文）で、表と同じ順に並ぶ。
止めた版は MYIME_ENGLISH_FOLLOW=off で流したもの（同じ前の文）。
  word, history: 確定した文が打った1語そのまま（英語）か。止めた版と並べ、増えた数と減った数を出す
  ja           : 英字が1文字でも混じったら、日本語の文が英語に化けた。化けた文は全部並べる（止めた版でも化けたものは分ける）
  control      : 止めた版と確定した文が同じか（前の文が日本語なので同じはず）。違いは全部並べる
  cause        : memory と同じ表の形で、場面ごとに英語の1語になった数と止めた版からの増え方だけを出す（合否にしない。履歴の道の切り分け）
  bare         : 英単語と綴りが同じ日本語の語を1語で打ったとき英語になった数。合否にしない（寄せの代償の目安）
  memory       : 表の4列目（場面。tools/english_follow_memory.sh）ごとに、記憶が残るべき場面（KEEP）は英語になった数と止めた版からの増え方、
                 記憶が捨てられるべき場面（DROP）は止めた版と結果が同じか（違えば記憶が残ってしまっている）。expire の表も同じ採点
"""
import re
import sys

LETTER = re.compile(r"[A-Za-zＡ-Ｚａ-ｚ]")


def load_table(path):
    rows = []
    for line in open(path, encoding="utf-8"):
        if line.startswith("#") or not line.strip():
            continue
        rows.append(line.rstrip("\n").split("\t"))
    return rows


def load_output(path):
    out = []
    for line in open(path, encoding="utf-8"):
        p = line.rstrip("\n").split("\t")
        if len(p) >= 3:
            out.append(p[2])
    return out


def main():
    kind, table, with_path = sys.argv[1:4]
    off_path = sys.argv[4] if len(sys.argv) > 4 else None
    rows = load_table(table)
    got = load_output(with_path)
    off = load_output(off_path) if off_path else None
    if len(got) != len(rows) or (off is not None and len(off) != len(rows)):
        print(f"行の数が合わない: 表 {len(rows)} 既定 {len(got)}" + (f" 止めた版 {len(off)}" if off is not None else ""))
        sys.exit(1)
    n = len(rows)
    if kind in ("word", "history", "bare"):
        hit = [g == r[0] for g, r in zip(got, rows)]
        line = f"{kind}: {n} 行  英語の1語になった: {sum(hit)}"
        if off is not None:
            was = [g == r[0] for g, r in zip(off, rows)]
            line += f"  （止めた版 {sum(was)}、増えた {sum(h and not w for h, w in zip(hit, was))}、減った {sum(w and not h for h, w in zip(hit, was))}）"
        print(line)
        if kind != "bare":
            miss = {}
            for h, r in zip(hit, rows):
                if not h:
                    miss.setdefault(r[0], 0)
                    miss[r[0]] += 1
            for word, count in list(miss.items())[:60]:
                print(f"  英語にならなかった {word}: {count} 行")
    elif kind == "cause":
        if off is None:
            print("cause には止めた版の結果が要る")
            sys.exit(1)
        order = []
        for r in rows:
            if r[3] not in order:
                order.append(r[3])
        print(f"cause: {n} 行（session の記憶は止めてある）")
        for sc in order:
            idx = [i for i, r in enumerate(rows) if r[3] == sc]
            hit = sum(got[i] == rows[i][0] for i in idx)
            was = sum(off[i] == rows[i][0] for i in idx)
            gained = sum(got[i] == rows[i][0] and off[i] != rows[i][0] for i in idx)
            print(f"  {sc:<8} {len(idx)} 行  英語の1語になった: {hit}  （止めた版 {was}、増えた {gained}）")
    elif kind == "memory":
        if off is None:
            print("memory には止めた版の結果が要る")
            sys.exit(1)
        keep = {"space", "testkey", "same-field", "bs-in", "nowait"}
        drop = {"bs-beyond", "arrow", "reset", "field", "ime-off", "wait"}
        order = []
        for r in rows:
            if r[3] not in order:
                order.append(r[3])
        print(f"memory: {n} 行")
        for sc in order:
            idx = [i for i, r in enumerate(rows) if r[3] == sc]
            hit = sum(got[i] == rows[i][0] for i in idx)
            was = sum(off[i] == rows[i][0] for i in idx)
            if sc in keep:
                gained = sum(got[i] == rows[i][0] and off[i] != rows[i][0] for i in idx)
                print(f"  残る場面 {sc:<10} {len(idx)} 行  英語の1語になった: {hit}  （止めた版 {was}、増えた {gained}）")
            elif sc in drop:
                same = sum(got[i] == off[i] for i in idx)
                print(f"  捨てる場面 {sc:<10} {len(idx)} 行  止めた版と同じ: {same}  （違う {len(idx) - same}。違う行は記憶が残って英語に寄った）")
                for i in idx:
                    if got[i] != off[i]:
                        print(f"    違う {rows[i][0]} 前={rows[i][2]!r}: {off[i]} → {got[i]}")
            else:
                print(f"  知らない場面 {sc}: {len(idx)} 行")
    elif kind == "ja":
        bad = [bool(LETTER.search(g)) for g in got]
        was = [bool(LETTER.search(g)) for g in off] if off is not None else [False] * n
        new = [b and not w for b, w in zip(bad, was)]
        print(f"ja: {n} 行  英字が混じった（日本語が英語に化けた）: {sum(bad)}" +
              (f"  （止めた版 {sum(was)}、新しく化けた {sum(new)}）" if off is not None else ""))
        for r, g, w, b in zip(rows, got, was, bad):
            if b:
                print(f"  {'もとから' if w else '化けた'} {r[0]} ({r[1]}) 前={r[2]!r} → {g}")
    elif kind == "control":
        if off is None:
            print("control には止めた版の結果が要る")
            sys.exit(1)
        diff = [(r, g, w) for r, g, w in zip(rows, got, off) if g != w]
        print(f"control: {n} 行  止めた版と結果が違う: {len(diff)}")
        for r, g, w in diff:
            print(f"  違う {r[0]} 前={r[2]!r}: {w} → {g}")
    else:
        sys.exit("kind: word history memory cause ja control bare")


if __name__ == "__main__":
    main()
