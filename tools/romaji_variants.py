"""Writes the same sentences typed in other romaji styles, to check that the
way of typing does not change the conversion (打ち方の揺れの試験).

  python tools/romaji_variants.py --table <mozc/src>/data/preedit/romanji-hiragana.tsv \
      --tests tests/conversion/ja400.json [more.json ...] --out variants.tsv

Each sentence's romaji is read into kana with Mozc's romaji table, and the
kana is written again in these styles (a style that changes nothing is left
out). Every written line is read back with the same table and must give the
same kana.

  base     ヘボン式（shi, chi, tsu, fu, ji, sha）、ん は nn、っ は子音を重ねる
  kunrei   訓令式（si, ti, tu, hu, zi, sya）
  small_l  小さいかなを l で（ふぁ fula、うぉ ulo、きゃ kilya、てぃ teli）
  small_x  小さいかなを x で（fuxa、uxo、kixya）
  tsu_l    っ を ltu で（kaltuta）
  n_x      ん を xn で
  n_apos   ん を n' で

Output: id<TAB>style<TAB>romaji<TAB>intended<TAB>alternatives (| separated).
"""
import argparse
import json
from pathlib import Path

SMALL = set("ぁぃぅぇぉゃゅょゎ")
SMALL_KEY = {"ぁ": "a", "ぃ": "i", "ぅ": "u", "ぇ": "e", "ぉ": "o", "ゃ": "ya", "ゅ": "yu", "ょ": "yo", "ゎ": "wa"}
# The style of each kana when several romaji give it (shi, not si or ci).
HEPBURN = {"し": "shi", "ち": "chi", "つ": "tsu", "ふ": "fu", "じ": "ji", "ぢ": "di", "づ": "du", "を": "wo",
           "しゃ": "sha", "しゅ": "shu", "しぇ": "she", "しょ": "sho", "ちゃ": "cha", "ちゅ": "chu", "ちぇ": "che",
           "ちょ": "cho", "じゃ": "ja", "じゅ": "ju", "じぇ": "je", "じょ": "jo"}
KUNREI = {"し": "si", "ち": "ti", "つ": "tu", "ふ": "hu", "じ": "zi", "しゃ": "sya", "しゅ": "syu", "しょ": "syo",
          "ちゃ": "tya", "ちゅ": "tyu", "ちょ": "tyo", "じゃ": "zya", "じゅ": "zyu", "じょ": "zyo"}
STYLES = ["base", "kunrei", "small_l", "small_x", "tsu_l", "n_x", "n_apos"]


def load_table(path):
    table = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        cols = line.split("\t")
        if len(cols) >= 2 and cols[0]:
            table[cols[0]] = (cols[1], cols[2] if len(cols) > 2 else "")
    return table


def to_kana(raw, table):
    """Reads romaji the way Mozc's composer does (longest key; pending keys go back in)."""
    longest = max(len(k) for k in table)
    out, rest = [], raw
    while rest:
        for size in range(min(longest, len(rest)), 0, -1):
            key = rest[:size]
            if key not in table:
                continue
            # "n" alone waits for the next key: ん before a consonant or at the end.
            if key == "n" and len(rest) > 1 and rest[1] in "aiueoyn'":
                continue
            kana, pending = table[key]
            out.append(kana)
            rest = pending + rest[size:]
            break
        else:
            out.append(rest[0])
            rest = rest[1:]
    return "".join(out)


def units(kana):
    """Kana split into what one romaji key group types (き, きゃ, っ, ん, ー)."""
    out = []
    for ch in kana:
        if ch in SMALL and out and out[-1] not in ("っ", "ん") and len(out[-1]) == 1 and out[-1] not in SMALL:
            out[-1] += ch
        else:
            out.append(ch)
    return out


def reverse_table(table):
    rev = {}
    for key, (kana, pending) in table.items():
        if pending or not key.isascii() or not key.isalpha() or not key.islower():
            continue
        rev.setdefault(kana, []).append(key)
    for keys in rev.values():
        keys.sort(key=lambda k: (any(c in "clxq" for c in k), len(k), k))
    return rev


def write(kana, style, rev):
    """kana written in |style|; None when a unit cannot be written."""
    us = units(kana)
    parts = []
    for i, u in enumerate(us):
        if u == "っ":
            parts.append("っ")  # filled in below from the next unit
            continue
        if u == "ん":
            nxt = us[i + 1][0] if i + 1 < len(us) else ""
            parts.append({"n_x": "xn", "n_apos": "n'"}.get(style, "nn") if nxt or style != "base" else "nn")
            continue
        if u == "ー":
            parts.append("-")
            continue
        if u == "、":
            parts.append(",")
            continue
        if u == "。":
            parts.append(".")
            continue
        if len(u) == 2 and style in ("small_l", "small_x"):
            first = HEPBURN.get(u[0]) or (rev.get(u[0]) or [None])[0]
            if first is None:
                return None
            parts.append(first + ("l" if style == "small_l" else "x") + SMALL_KEY[u[1]])
            continue
        if style == "kunrei" and u in KUNREI:
            parts.append(KUNREI[u])
            continue
        key = HEPBURN.get(u) or (rev.get(u) or [None])[0]
        if key is None:
            if u.isascii():
                parts.append(u)
                continue
            if len(u) == 2:  # no key for the pair: the kana and its small kana apart
                a = HEPBURN.get(u[0]) or (rev.get(u[0]) or [None])[0]
                if a is None:
                    return None
                parts.append(a + "x" + SMALL_KEY[u[1]])
                continue
            return None
        parts.append(key)
    out = []
    for i, p in enumerate(parts):
        if p == "っ":
            nxt = parts[i + 1] if i + 1 < len(parts) else ""
            if style == "tsu_l" or not nxt or not nxt[0].isalpha() or nxt[0] in "aiueon":
                out.append("ltu")
            else:
                out.append("t" if nxt.startswith("ch") else nxt[0])
        else:
            out.append(p)
    return "".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", required=True)
    ap.add_argument("--tests", nargs="*", default=[])
    ap.add_argument("--lines", nargs="*", default=[],
                    help="romaji one per line, no answer (only the same result as base is checked)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    table = load_table(args.table)
    rev = reverse_table(table)
    items = []
    for path in args.tests:
        items += json.loads(Path(path).read_text(encoding="utf-8"))["items"]
    for path in args.lines:
        for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
            if line.strip():
                items.append({"id": f"{Path(path).stem}{n}", "romaji": line.strip(), "intended": ""})
    lines, skipped = [], 0
    for item in items:
        kana = to_kana(item["romaji"], table)
        if any(c.isascii() and c.isalpha() for c in kana):
            skipped += 1  # English typed as is: no kana to write again
            continue
        seen = set()
        for style in STYLES:
            raw = write(kana, style, rev)
            if raw is None or raw in seen or to_kana(raw, table) != kana:
                continue
            seen.add(raw)
            alts = "|".join(item.get("alternatives", []))
            lines.append(f"{item['id']}\t{style}\t{raw}\t{item['intended']}\t{alts}")
    Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(lines)} lines, {skipped} sentences with English skipped")


if __name__ == "__main__":
    main()
