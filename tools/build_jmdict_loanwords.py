"""Builds katakana loanword -> original English pairs from JMdict (EDRDG, CC BY-SA 4.0).

  python tools/build_jmdict_loanwords.py --jmdict JMdict_e.gz --out jmdict-loanwords.tsv \
      [--wasei-out jmdict-wasei.tsv] [--wasei-list tools/data/wasei.tsv]

JMdict is the Japanese-Multi-Lingual Dictionary of the Electronic Dictionary Research and
Development Group (EDRDG): https://www.edrdg.org/jmdict/j_jmdict.html . The file JMdict_e.gz is
the English version, updated daily at https://ftp.edrdg.org/pub/Nihongo/JMdict_e.gz . It is
licensed under CC BY-SA 4.0; docs/credits_en.html carries the notice.

An entry is used when its headword is katakana and it has an English loanword source
(lsource with xml:lang="eng") that is not marked wasei (Japanese-made; the meaning differs, so
マンション is not mansion). The lsource text is the original spelling (coffee, smartphone). When
there is no lsource but an English gloss of one or two plain words (computer), the gloss is used,
but only for a katakana headword that JMdict does not mark as an ordinary Japanese word (a
hiragana/kanji headword or a common-word priority such as gai1/ichi1). This keeps Japanese
katakana words such as アイウエオ and established entries without a source out of the pairs.
Wasei entries go to --wasei-out (katakana<TAB>lsource, for checking), not to the pairs. The
checked list tools/data/wasei.tsv is also left out even when an older entry lost its wasei mark
(マンション).

Output: katakana<TAB>English<TAB>lsource|gloss, one line per pair, sorted. It is meant for
build_katakana_english.py --jmdict.
"""
import argparse
import gzip
import html
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

KATAKANA = re.compile(r"[ァ-ヺー・]+")
HERE = Path(__file__).resolve().parent
ENGLISH = re.compile(r"[A-Za-z][A-Za-z0-9 .'&+\-]*")
XLANG = "{http://www.w3.org/XML/1998/namespace}lang"


def open_text(path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open(encoding="utf-8")


def text_of(element):
    return unicodedata.normalize("NFC", "".join(element.itertext())).strip()


def clean_english(value):
    value = unicodedata.normalize("NFC", html.unescape(value)).strip()
    value = re.sub(r"\s+", " ", value)
    if not value or len(value) > 40 or not ENGLISH.fullmatch(value):
        return None
    if len(value) < 4 or sum(c.isalpha() for c in value) < 4:
        return None
    return value


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--jmdict", type=Path, required=True, help="JMdict_e.gz (or the uncompressed XML)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--wasei-out", type=Path)
    ap.add_argument("--wasei-list", type=Path, default=HERE / "data" / "wasei.tsv",
                    help="checked katakana of wasei words to leave out (default tools/data/wasei.tsv)")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    manual_wasei = set()
    if args.wasei_list and args.wasei_list.exists():
        for line in args.wasei_list.read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#") and "\t" in line:
                manual_wasei.add(line.split("\t", 1)[0])

    pairs, wasei = {}, {}
    for event, element in ET.iterparse(open_text(args.jmdict), events=("end",)):
        if element.tag != "entry":
            continue
        headwords = [text_of(e) for e in element.findall("./k_ele/keb")]
        headwords += [text_of(e) for e in element.findall("./r_ele/reb")]
        katakana = next((h for h in headwords if KATAKANA.fullmatch(h) and len(h) >= 2), None)
        if katakana:
            sources, made = [], []
            for sense in element.findall("./sense"):
                for source in sense.findall("./lsource"):
                    raw = text_of(source)
                    language = (source.get(XLANG) or "").lower()
                    if source.get("ls_wasei") == "y" or source.get("ls_type") == "wasei":
                        made.append(raw or "?")
                    elif language in ("eng", "en"):
                        value = clean_english(raw)
                        if value:
                            sources.append(value)
            if made:
                for value in made:
                    wasei.setdefault(katakana, [])
                    if value not in wasei[katakana]:
                        wasei[katakana].append(value)
            elif not sources:
                # No loanword source: an English gloss of one or two plain words may be the word
                # itself (アイアニング -> ironing), but a long explanation is not a spelling. The
                # fallback is only for a katakana-only entry with no common-word priority: a
                # hiragana/kanji headword (アイウエオ / あいうえお) or a gai/ichi entry (アイアン)
                # is an ordinary Japanese word, not evidence of an imported spelling.
                priorities = [text_of(e) for e in element.findall("./r_ele/re_pri")]
                katakana_only = all(KATAKANA.fullmatch(h) for h in headwords)
                if katakana_only and not priorities:
                    for gloss in element.findall("./sense/gloss"):
                        if (gloss.get(XLANG) or "eng").lower() not in ("eng", "en"):
                            continue
                        value = clean_english(text_of(gloss))
                        if value and len(value.split()) <= 2 and value.lower() == value:
                            sources.append(("gloss", value))
                            break
            for value in sources:
                if isinstance(value, str):
                    value = ("lsource", value)
                origin, spelling = value
                pairs.setdefault(katakana, [])
                if all(other != spelling for _, other in pairs[katakana]):
                    pairs[katakana].append((origin, spelling))
            if katakana in manual_wasei:
                pairs.pop(katakana, None)
        element.clear()

    with args.out.open("w", encoding="utf-8", newline="\n") as out:
        out.write("# katakana<TAB>English<TAB>lsource|gloss (tools/build_jmdict_loanwords.py; JMdict, EDRDG, CC BY-SA 4.0)\n")
        for katakana in sorted(pairs):
            for origin, value in pairs[katakana]:
                out.write(f"{katakana}\t{value}\t{origin}\n")
    if args.wasei_out:
        with args.wasei_out.open("w", encoding="utf-8", newline="\n") as out:
            out.write("# 和製英語（JMdict の lsource に ls_wasei=\"y\" がある語）。英単語の候補にしない。\n")
            for katakana in sorted(wasei):
                out.write(f"{katakana}\t{'|'.join(wasei[katakana])}\n")
    print("katakana", len(pairs), "pairs", sum(len(v) for v in pairs.values()),
          "wasei", len(wasei))


if __name__ == "__main__":
    main()
