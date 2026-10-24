"""長い文の変換の時間を測る試験の文を作る。

  python tools/make_long_latency_tests.py --out tests/conversion/long-latency.tsv [--count 36] [--check]

tests/conversion/wiki-typing.tsv（ウィキペディアの文）と tests/conversion/context.tsv（前の文つきの文）から、
読みの長さ（目標の文の字数）が 10・20・40・60・80・120 字ほどの組を作る。40 字までの組は1文、
それより長い組は句点でつないだ複数の文を使う。前の文は context.tsv から取る。
出力は「組<TAB>ローマ字<TAB>前の文<TAB>元の文」。組ごとに --count 文（既定 36 文。最初の 5 回は
模型の読み込みとして捨てるので、30 文以上が残る）。

文は tests/conversion の既存の試験と同じウィキペディア日本語版（CC BY-SA 4.0）から作る。
学習や語の一覧には使わない（時間を測る試験だけ）。
"""
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
WIKI = REPO / "tests/conversion/wiki-typing.tsv"
CONTEXT = REPO / "tests/conversion/context.tsv"

# 組の名前（目標の字数）と、受け入れる字数の範囲
BUCKETS = [
    (10, 8, 14),
    (20, 16, 26),
    (40, 32, 50),
    (60, 50, 72),
    (80, 68, 96),
    (120, 100, 150),
]


def read_tsv(path):
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) >= 2 and fields[0] and fields[1]:
            rows.append(fields)
    return rows


def needs_mark(text):
    return not text.endswith(("。", "、", "！", "？", ".", ",", "!", "?"))


def join_units(left, right):
    """文を句点でつなぐ。ローマ字は . 、日本語は 。 を補う。"""
    romaji, target = left
    r2, t2 = right
    if needs_mark(target):
        target += "。"
        romaji += "."
    return romaji + r2, target + t2


def build_units(wiki, context):
    units = []
    for fields in wiki:
        units.append((fields[0], fields[1]))
    for fields in context:
        if len(fields) >= 2:
            units.append((fields[0], fields[1]))
    return units


def pick_single(units, lo, hi, used, start):
    """1文で範囲に入るものを、start から順に探す。"""
    n = len(units)
    for k in range(n):
        romaji, target = units[(start + k) % n]
        if target in used:
            continue
        if lo <= len(target) <= hi:
            return romaji, target
    return None


def pick_joined(units, lo, hi, used, start):
    """2文以上をつないで範囲に入るものを探す。"""
    n = len(units)
    for k in range(n):
        idx = (start + k) % n
        romaji, target = units[idx]
        while len(target) < lo:
            nxt = units[(idx + 1 + (len(target) // 7)) % n]
            idx = (idx + 1 + (len(target) // 7)) % n
            romaji, target = join_units((romaji, target), nxt)
            if len(target) > hi:
                break
        if lo <= len(target) <= hi and target not in used:
            return romaji, target
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO / "tests/conversion/long-latency.tsv"))
    ap.add_argument("--count", type=int, default=36)
    ap.add_argument("--check", action="store_true", help="作らずに、組ごとの文の数だけを確かめる")
    args = ap.parse_args()

    wiki = read_tsv(WIKI)
    context = read_tsv(CONTEXT)
    if not wiki or not context:
        raise SystemExit(f"試験の文がありません: {WIKI} / {CONTEXT}")
    units = build_units(wiki, context)
    befores = [f[2] for f in context if len(f) >= 3 and f[2]]

    lines = []
    for bucket, lo, hi in BUCKETS:
        used = set()
        picked = []
        start = (bucket * 97 + 11) % len(units)
        # まず1文で範囲に入るもの、足りなければつないだ文で補う
        for i in range(args.count):
            row = None
            if bucket <= 40:
                row = pick_single(units, lo, hi, used, start + i * 13)
            if row is None:
                row = pick_joined(units, lo, hi, used, start + i * 29)
            if row is None:
                raise SystemExit(f"組 {bucket} の文を {args.count} 文そろえられませんでした（{len(picked)} 文）")
            used.add(row[1])
            picked.append(row)
        for i, (romaji, target) in enumerate(picked):
            before = befores[(bucket + i * 7) % len(befores)]
            lines.append(f"{bucket}\t{romaji}\t{before}\t{target}")
        print(f"組 {bucket}: {len(picked)} 文（字数 {min(len(t) for _, t in picked)}〜{max(len(t) for _, t in picked)}）")

    if args.check:
        return
    header = (
        "# 長い文の変換の時間を測るための文。ウィキペディア日本語版（CC BY-SA 4.0、https://ja.wikipedia.org/）の\n"
        "# tests/conversion/wiki-typing.tsv と context.tsv から tools/make_long_latency_tests.py で作った。\n"
        "# 組（目標の字数）<TAB>ローマ字<TAB>前の文<TAB>元の文。時間を測る試験だけに使い、学習や語の一覧には使わない。\n"
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(header + "\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"{out}: {len(lines)} 文")


if __name__ == "__main__":
    main()
