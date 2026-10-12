"""Builds dictionary11.txt: readings that a romaji spelling produces in Mozc
when it is not written the Japanese-input way.

  python tools/build_romaji_alias_dictionary.py --mozc <mozc/src> --out dictionary11.txt
      [--names] [--loanwords data/loanwords.tsv] [--install]

--names: person and place names in Mozc's dictionary, spelled the passport
  way (Hepburn without long vowels or apostrophes): "sato" is read さと, not
  さとう, so さと gets 佐藤; "shinichi" is read しにち, so しにち gets 新一.
--loanwords: lines "english<TAB>katakana": "agenda" is read あげんだ, so
  あげんだ gets アジェンダ.

The alias keeps the word's part of speech and the word's cost plus a penalty:
--name-penalty, or --name-collision when Mozc already has the alias reading
(さと is also 里: the name then needs context such as a following さん to win);
--loan-penalty for loanwords, which cost more than every existing entry of a
reading Mozc already has (でも stays でも; デモ is already a candidate).
"""
import argparse
import re
from pathlib import Path

NAME_POS = range(1921, 1930)  # 名詞,固有名詞,人名/地域 in id.def
BASE = dict(zip(
    "あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをがぎぐげござじずぜぞだぢづでどばびぶべぼぱぴぷぺぽ",
    "a i u e o ka ki ku ke ko sa shi su se so ta chi tsu te to na ni nu ne no ha hi fu he ho ma mi mu me mo ya yu yo "
    "ra ri ru re ro wa o ga gi gu ge go za ji zu ze zo da ji zu de do ba bi bu be bo pa pi pu pe po".split()))
SPECIAL = {"しゃ": "sha", "しゅ": "shu", "しょ": "sho", "ちゃ": "cha", "ちゅ": "chu", "ちょ": "cho",
           "じゃ": "ja", "じゅ": "ju", "じょ": "jo", "ぢゃ": "ja", "ぢゅ": "ju", "ぢょ": "jo"}
YOON = {"ゃ": "a", "ゅ": "u", "ょ": "o"}
HIRAGANA = re.compile(r"[ぁ-ゖー]+")


O_ROW = set("おこそとのほもよろごぞどぼぽょ")
U_ROW = set("うくすつぬふむゆるぐずづぶぷゅ")


def hepburn(kana):
    """Passport-style romaji: no long vowels, n before vowels without an apostrophe."""
    # Long vowels (おう, おお, うう) lose their second vowel. の+う is left alone:
    # it is usually a word boundary (波の上 なみのうえ, 野上 のうえ).
    shortened = []
    for c in kana:
        prev = shortened[-1] if shortened else ""
        if (c == "う" and (prev in O_ROW or prev in U_ROW) and prev != "の") or (c == "お" and prev in O_ROW and prev != "の"):
            continue
        shortened.append(c)
    kana = "".join(shortened)
    out, i = [], 0
    while i < len(kana):
        two = kana[i:i + 2]
        if two in SPECIAL:
            out.append(SPECIAL[two]); i += 2
        elif len(two) == 2 and two[1] in YOON and BASE.get(two[0], "").endswith("i") and len(BASE[two[0]]) == 2:
            out.append(BASE[two[0]][0] + "y" + YOON[two[1]]); i += 2
        elif kana[i] == "っ":
            out.append("@"); i += 1
        elif kana[i] == "ん":
            out.append("n"); i += 1
        elif kana[i] in BASE:
            out.append(BASE[kana[i]]); i += 1
        else:
            return None
    s = "".join(out)
    s = re.sub(r"@(ch)", r"t\1", s)
    s = re.sub(r"@([a-z])", lambda m: m.group(1) * 2, s)
    if "@" in s:
        return None
    return s


class Romaji:
    """Mozc's romaji table, applied the way the composer does."""

    def __init__(self, table):
        self.rules = {}
        for line in table.read_text(encoding="utf-8").splitlines():
            f = line.split("\t")
            if len(f) >= 2 and f[0]:
                self.rules[f[0]] = (f[1], f[2] if len(f) > 2 else "")
        self.prefixes = {k[:i] for k in self.rules for i in range(1, len(k))}

    def read(self, text):
        out, pending = [], ""
        for c in text:
            while True:
                s = pending + c
                if s in self.prefixes:
                    pending = s
                    break
                if s in self.rules:
                    o, pending = self.rules[s]
                    out.append(o)
                    break
                if pending in self.rules:
                    o, pending = self.rules[pending]
                    out.append(o)
                    continue
                out.append(pending)
                pending = ""
                if c in self.prefixes or c in self.rules:
                    continue
                out.append(c)
                break
        if pending:
            out.append(self.rules[pending][0] if pending in self.rules else
                       ("ん" if pending == "n" else pending))
        return "".join(out)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mozc", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--names", action="store_true")
    parser.add_argument("--loanwords", type=Path)
    parser.add_argument("--max-cost", type=int, default=8000, help="names costlier than this are skipped")
    parser.add_argument("--name-penalty", type=int, default=500)
    parser.add_argument("--name-collision", type=int, default=1500)
    parser.add_argument("--loan-penalty", type=int, default=0)
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()

    data = args.mozc / "data/dictionary_oss"
    romaji = Romaji(args.mozc / "data/preedit/romanji-hiragana.tsv")
    max_cost, words, pairs = {}, [], set()
    for path in sorted(data.glob("dictionary*.txt")):
        if path.name == "dictionary11.txt":
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            reading, lid, rid, cost, surface = line.split("\t")[:5]
            max_cost[reading] = max(max_cost.get(reading, 0), int(cost))
            pairs.add((reading, surface))
            words.append((reading, int(lid), int(rid), int(cost), surface))

    aliases = {}  # (alias reading, surface) -> (lid, rid, cost)

    def add(alias, lid, rid, cost, surface, loan=False):
        if not alias or not HIRAGANA.fullmatch(alias) or (alias, surface) in pairs:
            return
        if loan:
            cost += args.loan_penalty
            if alias in max_cost:
                cost = max(cost, max_cost[alias] + 100)
        else:
            cost += args.name_collision if alias in max_cost else args.name_penalty
        old = aliases.get((alias, surface))
        if old is None or cost < old[2]:
            aliases[(alias, surface)] = (lid, rid, cost)

    if args.names:
        for reading, lid, rid, cost, surface in words:
            if lid not in NAME_POS or cost > args.max_cost or not HIRAGANA.fullmatch(reading):
                continue
            spelled = hepburn(reading)
            if spelled:
                alias = romaji.read(spelled)
                if alias != reading:
                    add(alias, lid, rid, cost, surface)
    counted = len(aliases)
    if args.loanwords:
        by_surface = {}
        for reading, lid, rid, cost, surface in words:
            if (surface not in by_surface or cost < by_surface[surface][2]) and lid == rid:
                by_surface[surface] = (lid, rid, cost)
        for line in args.loanwords.read_text(encoding="utf-8").splitlines():
            if not line or line.startswith("#"):
                continue
            english, katakana = line.split("\t")[:2]
            if katakana not in by_surface:
                continue
            lid, rid, cost = by_surface[katakana]
            add(romaji.read(english.lower()), lid, rid, cost, katakana, loan=True)
    with args.out.open("w", encoding="utf-8", newline="\n") as out:
        for (alias, surface), (lid, rid, cost) in sorted(aliases.items()):
            out.write(f"{alias}\t{lid}\t{rid}\t{cost}\t{surface}\n")
    print("aliases", len(aliases), "names", counted, "loanwords", len(aliases) - counted)
    if args.install:
        (data / "dictionary11.txt").write_bytes(args.out.read_bytes())
        build = data / "BUILD.bazel"
        text = build.read_text(encoding="utf-8")
        if '"dictionary11.txt"' not in text:
            old = '        "dictionary10.txt",\n'
            assert text.count(old) == 1
            build.write_text(text.replace(old, old + '        "dictionary11.txt",\n'), encoding="utf-8", newline="")


if __name__ == "__main__":
    main()
