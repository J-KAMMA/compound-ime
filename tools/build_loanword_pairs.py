"""Pairs English words that read as romaji with the katakana word they mean.

  python tools/build_loanword_pairs.py --mozc <mozc/src> --cmudict cmudict.dict
      --lexicon english-lexicon.txt --out tools/data/loanwords.tsv

Only words whose spelling Mozc reads entirely as kana are paired ("agenda" is
read あげんだ, "menu" めぬ): other words are already kept as English. The
katakana side must be a common-noun word in Mozc's dictionary (names and
places excluded). A pair is kept when the word's pronunciation (CMU
Pronouncing Dictionary, BSD license, cmusphinx/cmudict) aligns closely with
the katakana and no other katakana word aligns nearly as well.
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from build_romaji_alias_dictionary import Romaji, BASE, SPECIAL, YOON  # noqa: E402

KATAKANA = re.compile(r"[ァ-ヺー]{2,}")
HIRAGANA = re.compile(r"[ぁ-ゖ]+")
VOWELS = set("aeiou")
EXTRA = {"ふぁ": "fa", "ふぃ": "fi", "ふぇ": "fe", "ふぉ": "fo", "てぃ": "ti", "でぃ": "di",
         "うぃ": "wi", "うぇ": "we", "うぉ": "wo", "しぇ": "she", "ちぇ": "che", "じぇ": "je",
         "とぅ": "tu", "どぅ": "du", "ゔぁ": "va", "ゔぃ": "vi", "ゔぇ": "ve", "ゔぉ": "vo", "ゔ": "vu",
         "つぁ": "tsa", "ふゅ": "fyu", "てゅ": "tyu", "でゅ": "dyu", "いぇ": "ye", "くぁ": "kwa", "ぐぁ": "gwa"}
PHONEMES = {
    "AA": "a", "AE": "a", "AH": "a", "AO": "o", "AW": "au", "AY": "ai", "EH": "e", "ER": "ar",
    "EY": "eI", "IH": "i", "IY": "i", "OW": "oU", "OY": "oi", "UH": "u", "UW": "u",
    "B": "b", "CH": "C", "D": "d", "DH": "z", "F": "f", "G": "g", "HH": "h", "JH": "J", "K": "k",
    "L": "r", "M": "m", "N": "n", "NG": "ng", "P": "p", "R": "r", "S": "s", "SH": "S", "T": "t",
    "TH": "s", "V": "b", "W": "u", "Y": "y", "Z": "z", "ZH": "J",
}
VOWELS = set("aeiou")
SIMILAR = {frozenset(p) for p in ("tC", "dJ", "zJ", "sS", "zs", "td", "bp", "gk", "fh", "ub", "JS", "CS", "ts")}


def kata_romaji(katakana):
    kana = "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in katakana)
    out, i = [], 0
    while i < len(kana):
        two = kana[i:i + 2]
        if two in EXTRA:
            out.append(EXTRA[two]); i += 2
        elif two in SPECIAL:
            out.append(SPECIAL[two]); i += 2
        elif len(two) == 2 and two[1] in YOON and BASE.get(two[0], "").endswith("i") and len(BASE[two[0]]) == 2:
            out.append(BASE[two[0]][0] + "y" + YOON[two[1]]); i += 2
        elif kana[i] in EXTRA:
            out.append(EXTRA[kana[i]]); i += 1
        elif kana[i] == "っ":
            out.append("@"); i += 1
        elif kana[i] == "ん":
            out.append("n"); i += 1
        elif kana[i] == "ー":
            i += 1
        elif kana[i] in BASE:
            out.append(BASE[kana[i]]); i += 1
        else:
            return None
    s = "".join(out)
    s = s.replace("sh", "S").replace("ch", "C").replace("j", "J").replace("tsu", "tu").replace("v", "b")
    s = re.sub(r"@([a-zA-Z])", lambda m: m.group(1) * 2, s)
    return None if "@" in s else s


def phoneme_romaji(phones):
    return "".join(PHONEMES[re.sub(r"\d", "", p)] for p in phones.split())


def distance(source, kata):
    """Edit distance from a pronunciation to a katakana's romaji."""
    n, m = len(source), len(kata)
    inf = float("inf")
    d = [[inf] * (m + 1) for _ in range(n + 1)]
    d[0][0] = 0.0
    for i in range(n + 1):
        for j in range(m + 1):
            v = d[i][j]
            if v == inf:
                continue
            if i < n and j < m:
                a, b = source[i], kata[j]
                cost = (0 if a == b or (a, b) in (("I", "i"), ("U", "u")) else
                        0.4 if a.lower() in VOWELS and b in VOWELS else
                        0.3 if frozenset((a, b)) in SIMILAR else 1.5)
                d[i + 1][j + 1] = min(d[i + 1][j + 1], v + cost)
            if i < n:  # sound the katakana leaves out (r after a vowel: ER -> ー)
                a = source[i]
                prev = source[i - 1] if i else ""
                cost = 0.05 if a in "IU" else 0.1 if a == "r" and prev in VOWELS else 0.3 if a in "yh" else 0.5 if a in VOWELS else 1.0
                d[i + 1][j] = min(d[i + 1][j], v + cost)
            if j < m:  # sound the katakana adds: a vowel after a consonant, a doubled consonant
                b = kata[j]
                prev = kata[j - 1] if j else ""
                cost = (0.15 if b in "uoi" and prev and prev not in VOWELS else 0.1 if b == prev else
                        0.4 if b in VOWELS else 0.3 if b == "y" else 1.0)
                d[i][j + 1] = min(d[i][j + 1], v + cost)
    return d[n][m]


def skeleton(text):
    text = text.replace("ng", "n").translate(str.maketrans("CJSzdgbpf", "tssstkbbh"))
    out = [c for c in text if c not in "aeiouyhwIU"]
    return "".join(c for i, c in enumerate(out) if i == 0 or c != out[i - 1])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mozc", type=Path, required=True)
    parser.add_argument("--cmudict", type=Path, required=True)
    parser.add_argument("--lexicon", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--threshold", type=float, default=0.15)
    parser.add_argument("--cost-weight", type=float, default=0.00005,
                        help="per unit of Mozc cost: common katakana words win close calls")
    parser.add_argument("--margin", type=float, default=0.05)
    parser.add_argument("--min-length", type=int, default=4)
    args = parser.parse_args()
    romaji = Romaji(args.mozc / "data/preedit/romanji-hiragana.tsv")
    katakana_cost = {}
    for path in sorted((args.mozc / "data/dictionary_oss").glob("dictionary0*.txt")):
        for line in path.read_text(encoding="utf-8").splitlines():
            f = line.split("\t")
            if KATAKANA.fullmatch(f[4]) and not 1921 <= int(f[1]) <= 1929:
                katakana_cost[f[4]] = min(katakana_cost.get(f[4], 1 << 30), int(f[3]))
    by_skeleton = {}
    for word in katakana_cost:
        r = kata_romaji(word)
        if r:
            by_skeleton.setdefault(skeleton(r), []).append((word, r))
    pronunciations = {}
    for line in args.cmudict.read_text(encoding="utf-8").splitlines():
        head, _, phones = line.partition(" ")
        word = re.sub(r"\(\d+\)$", "", head)
        pronunciations.setdefault(word, []).append(phoneme_romaji(phones.split("#")[0]))
    pairs = []
    for english in args.lexicon.read_text(encoding="utf-8").split():
        if (len(english) < args.min_length or not english.isalpha() or not english.islower() or
                english not in pronunciations or not HIRAGANA.fullmatch(romaji.read(english))):
            continue
        best = {}
        for source in pronunciations[english]:
            sk = skeleton(source)
            for key in {sk} | {sk[:i] + sk[i + 1:] for i in range(len(sk))}:
                for word, r in by_skeleton.get(key, []):
                    score = distance(source, r) / len(source)
                    if word not in best or score < best[word]:
                        best[word] = score
        if not best:
            continue
        ranked = sorted((score + args.cost_weight * katakana_cost[word], score, word)
                        for word, score in best.items())
        top = ranked[0]
        if top[1] <= args.threshold and all(s[0] - top[0] >= args.margin for s in ranked[1:]):
            pairs.append((english, top[2], top[1]))
    with args.out.open("w", encoding="utf-8", newline="\n") as out:
        out.write("# english<TAB>katakana<TAB>distance per sound (build_loanword_pairs.py)\n")
        for english, word, score in sorted(pairs):
            out.write(f"{english}\t{word}\t{score:.2f}\n")
    print("pairs", len(pairs))


if __name__ == "__main__":
    main()
