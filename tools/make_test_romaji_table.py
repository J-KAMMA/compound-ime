"""手元の試し用（native/jaen-detector/jaen_trial.cc、tools/acronym_probe.py）のローマ字表を作る。

  python tools/make_test_romaji_table.py > romaji.tsv

Mozc の romanji-hiragana.tsv（入力<TAB>かな<TAB>あとに残るキー）の簡易な写し: 五十音、濁音、拗音、
小さいかな（x?・l?）、促音（子音の重ね）、ん（nn、n'、n+子音）、外来語の音（fa、ti、wi、we、va、th ...）。
本物の表とは細かく違う。本物は、GitHub の試験の中で取る（tools/run_tests.sh の組 r の手前、linux-test.yml）。
"""
BASE = {
    "a": "あ", "i": "い", "u": "う", "e": "え", "o": "お",
    "ka": "か", "ki": "き", "ku": "く", "ke": "け", "ko": "こ",
    "sa": "さ", "si": "し", "su": "す", "se": "せ", "so": "そ", "shi": "し",
    "ta": "た", "ti": "ち", "tu": "つ", "te": "て", "to": "と", "chi": "ち", "tsu": "つ",
    "na": "な", "ni": "に", "nu": "ぬ", "ne": "ね", "no": "の",
    "ha": "は", "hi": "ひ", "hu": "ふ", "he": "へ", "ho": "ほ", "fu": "ふ",
    "ma": "ま", "mi": "み", "mu": "む", "me": "め", "mo": "も",
    "ya": "や", "yu": "ゆ", "yo": "よ",
    "ra": "ら", "ri": "り", "ru": "る", "re": "れ", "ro": "ろ",
    "wa": "わ", "wi": "うぃ", "we": "うぇ", "wo": "を",
    "ga": "が", "gi": "ぎ", "gu": "ぐ", "ge": "げ", "go": "ご",
    "za": "ざ", "zi": "じ", "zu": "ず", "ze": "ぜ", "zo": "ぞ", "ji": "じ",
    "da": "だ", "di": "ぢ", "du": "づ", "de": "で", "do": "ど",
    "ba": "ば", "bi": "び", "bu": "ぶ", "be": "べ", "bo": "ぼ",
    "pa": "ぱ", "pi": "ぴ", "pu": "ぷ", "pe": "ぺ", "po": "ぽ",
    "fa": "ふぁ", "fi": "ふぃ", "fe": "ふぇ", "fo": "ふぉ",
    "va": "ゔぁ", "vi": "ゔぃ", "vu": "ゔ", "ve": "ゔぇ", "vo": "ゔぉ",
    "ja": "じゃ", "ju": "じゅ", "jo": "じょ", "je": "じぇ",
    "cha": "ちゃ", "chu": "ちゅ", "cho": "ちょ", "che": "ちぇ",
    "sha": "しゃ", "shu": "しゅ", "sho": "しょ", "she": "しぇ",
    "tsa": "つぁ", "tsi": "つぃ", "tse": "つぇ", "tso": "つぉ",
    "thi": "てぃ", "thu": "てゅ", "dhi": "でぃ", "dhu": "でゅ",
    "twu": "とぅ", "dwu": "どぅ", "kwa": "くぁ", "gwa": "ぐぁ", "gwo": "ぐぉ", "two": "とぉ",
    "la": "ぁ", "li": "ぃ", "lu": "ぅ", "le": "ぇ", "lo": "ぉ",
    "xa": "ぁ", "xi": "ぃ", "xu": "ぅ", "xe": "ぇ", "xo": "ぉ",
    "lya": "ゃ", "lyu": "ゅ", "lyo": "ょ", "xya": "ゃ", "xyu": "ゅ", "xyo": "ょ",
    "ltu": "っ", "xtu": "っ", "ltsu": "っ", "xtsu": "っ", "lwa": "ゎ", "xwa": "ゎ",
    "nn": "ん", "xn": "ん", "n'": "ん", "-": "ー", ",": "、", ".": "。", "!": "！", "?": "？",
}
for c, kana in (("k", "き"), ("g", "ぎ"), ("s", "し"), ("z", "じ"), ("t", "ち"), ("d", "ぢ"), ("n", "に"),
                ("h", "ひ"), ("b", "び"), ("p", "ぴ"), ("m", "み"), ("r", "り")):
    for v, small in (("a", "ゃ"), ("u", "ゅ"), ("o", "ょ"), ("e", "ぇ")):
        BASE[f"{c}y{v}"] = kana + small
CONSONANTS = "bcdfghjklmpqrstvwxyz"


def main():
    rows = [(k, v, "") for k, v in BASE.items()]
    for c in CONSONANTS:
        if c not in "n":
            rows.append((c + c, "っ", c))
    for c in CONSONANTS + "n":
        if c not in "ny":
            rows.append(("n" + c, "ん", c))
    for key, value, pending in sorted(rows):
        print(f"{key}\t{value}\t{pending}")


if __name__ == "__main__":
    main()
