"""Builds tools/data/proper-nouns.tsv: proper nouns written with capital letters (Google,
GitHub, New York, Elon Musk, iPhone ...) from Wikidata (CC0), with how they are typed and read.

  python tools/fetch_wikidata_names.py --out wikidata        # about an hour, once
  python tools/build_proper_nouns.py --wikidata wikidata --mozc-dictionaries <mozc/src>/data/dictionary_oss \
      --ut mozcdic-ut-sudachidict.txt --table <mozc/src>/data/preedit/romanji-hiragana.tsv \
      --lexicon <english lexicon dir> --trial jaen_trial --corpus <romaji lines of Japanese-only text> \
      --out tools/data/proper-nouns.tsv

--trial is native/jaen-detector/jaen_trial.cc built as that file says (it runs the real detector with
a lexicon directory: english-lexicon.txt curated-words.txt signal-words.txt common-words.txt joined.txt
phrases.txt places.tsv, plus readings.txt and romaji.tsv in the working directory --trial-work).

What the output line holds (shown<TAB>typed<TAB>flags<TAB>readings<TAB>kind<TAB>sitelinks):
- shown: the official spelling.
- typed: how it is typed in romaji with no capitals ("github", "new york" for two words), when the
  English-word detector takes it as English on its own after the name is added to its word list
  (so a name read as plain Japanese romaji, such as amazon or nintendo, has none). Empty if not.
- flags: "s" when the typed form is also a common English word (china, target, shell): the word
  as typed stays first and the name comes second.
- readings: kana readings (| separated) from the Japanese label or alias in katakana, or from the
  Japanese label's reading in Mozc's dictionary, or from the spelling typed as plain romaji when that
  kana is a reading in Mozc's dictionary (amazon: あまぞん).
  Used for the candidates of a reading (ぐーぐる -> Google).

A name goes in only when its spelling has a capital letter (a word list cannot say that "iPhone"
has one) and every word either starts with a capital or has one inside.
"""
import argparse
import re
import subprocess
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import romaji_variants as rv  # noqa: E402

DATA = HERE / "data"
CONNECTORS = {"of", "the", "and", "de", "la", "le", "von", "van", "der", "for", "in", "on", "at", "to", "by",
              "a", "an", "du", "des", "del", "di", "da", "el", "al", "bin", "ibn", "y", "e", "los", "las", "do", "dos"}
SUFFIX = re.compile(r"\s+(Inc\.?|Incorporated|Corporation|Corp\.?|Company|Co\.|Ltd\.?|Limited|LLC|L\.L\.C\.|PLC|plc|"
                    r"GmbH|AG|S\.A\.|SA|N\.V\.|NV|AB|ASA|Oyj|Group|Holdings?|Technologies|Enterprises)$")
BAD_CHARS = re.compile(r"[():/,;\"@#|\[\]{}<>*?_=~%$^\\`]")
GOOD = re.compile(r"[A-Za-z0-9À-ɏ][A-Za-z0-9À-ɏ .'&+\-!]*")
KATA = re.compile(r"[ァ-ヺー・=＝ヽヾ 　]+")
HIRA = re.compile(r"[ぁ-ゖー]+")
PEOPLE = {"people"}
# The company suffixes of SUFFIX as they are read in katakana (サムスングループ).
KANA_SUFFIXES = ["ぐるーぷ", "こーぽれーしょん", "こーぽれいてっど", "かんぱにー", "ほーるでぃんぐす", "てくのろじーず",
                 "いんこーぽれいてっど", "いんく", "りみてっど", "えるえるしー"]
# How well known a thing must be (Wikipedia language editions) when its English spelling is a common word.
COMMON_WORD_MIN_SITELINKS = 60
PLACE_KINDS = {"country", "usstate", "city", "island", "mountain", "river", "lake"}
PLACE_COMMON_WORD_MIN_SITELINKS = 150  # a town named Most or Oral is not what is meant by most or oral
# Not names of things people write about: parts of Wikipedia, competitions by year and the like.
JUNK = re.compile(r"Wikipedia|Olympics|Paralympics|Template|Module|Category|Wikimedia|WikiProject|Championship|"
                  r"\bSeason\b|\bat the\b|\bin the\b")
# 1 reading of the spelling typed as plain romaji is added only for these (not people: tayloあ is no name).
ALIAS_KINDS = {"business", "brand", "software", "app", "website", "videogame", "carmodel", "tvnetwork", "newspaper",
               "airline", "sportsteam", "country", "usstate", "city", "region", "island", "mountain", "river",
               "lake", "band", "film", "tvseries", "album", "novel", "character", "proglang", "os", "university",
               "museum"}
# Hand-added readings: short capital words people type as plain romaji (ai -> あい -> AI).
EXTRA_READINGS = {"AI": ["あい"]}


def hira(text):
    out = []
    for ch in text:
        if ch in "・=＝ 　":
            continue
        if ch == "ヴ":
            out.append("ゔ")
        elif "ァ" <= ch <= "ヶ":
            out.append(chr(ord(ch) - 0x60))
        elif ch in "ヽヾ":
            return None
        else:
            out.append(ch)
    text = "".join(out)
    return text if HIRA.fullmatch(text) and len(text) >= 3 else None


def clean_english(en):
    """The official spelling to show, or None."""
    en = unicodedata.normalize("NFC", en).strip()
    if BAD_CHARS.search(en) or not GOOD.fullmatch(en):
        return None
    while True:
        stripped = SUFFIX.sub("", en)
        if stripped == en or not stripped:
            break
        en = stripped
    en = en.strip(" .-")
    words = en.split(" ")
    if not (1 <= len(words) <= 4) or len(en) > 30 or not any(c.isupper() for c in en) or JUNK.search(en):
        return None
    for i, w in enumerate(words):
        if not w or not any(c.isalnum() for c in w):
            return None
        if i > 0 and w in CONNECTORS:
            continue
        if not (w[0].isupper() or w[0].isdigit() or any(c.isupper() for c in w[1:])):
            return None
    if any(w.isdigit() for w in words):
        return None
    return en


def typed_form(shown):
    """The tokens typed in romaji, or None (not typable in ASCII)."""
    if not shown.isascii():
        return None
    tokens = []
    for word in shown.split(" "):
        token = re.sub(r"[^a-z0-9]", "", word.lower())
        if token:
            tokens.append(token)
    if not tokens or len(tokens) > 3 or any(t.isdigit() for t in tokens) or len("".join(tokens)) > 28:
        return None
    if len(tokens) == 1 and len(tokens[0]) < 3:
        return None
    return tokens


def load_readings(dictionary_dir, ut_path):
    """Kanji (or any non-ASCII) surface -> its cheapest hiragana reading."""
    best = {}
    files = sorted(dictionary_dir.glob("dictionary0*.txt"))
    for path in files + ([ut_path] if ut_path else []):
        for line in path.read_text(encoding="utf-8").splitlines():
            f = line.split("\t")
            if len(f) != 5 or f[4].isascii() or not HIRA.fullmatch(f[0]):
                continue
            cost = int(f[3]) if f[1] != "0000" else 9000
            if f[4] not in best or cost < best[f[4]][0]:
                best[f[4]] = (cost, f[0])
    return {s: r for s, (c, r) in best.items()}


def load_ut_latin(ut_path):
    """mozcdic-ut-sudachidict entries written in Latin letters with a capital: normalized spelling ->
    {spelling: [readings]}. build_ut_dictionary.py leaves them out of Mozc's dictionary (transliteration
    and the English-word detector were meant to give them), so Mozc has no candidate for their reading."""
    table = defaultdict(lambda: defaultdict(list))
    for line in ut_path.read_text(encoding="utf-8").splitlines():
        f = line.split("\t")
        if len(f) != 5 or not f[4].isascii() or f[4] == f[4].lower() or not HIRA.fullmatch(f[0]) or len(f[0]) < 3:
            continue
        key = re.sub(r"[^a-z0-9]", "", f[4].lower())
        if f[0] not in table[key][f[4]]:
            table[key][f[4]].append(f[0])
    return table


def existing_casing():
    keys = {}
    for name in ("brand-casing.tsv", "domain-casing.tsv", "digit-words.tsv", "jaen-modern-words.tsv"):
        for line in (DATA / name).read_text(encoding="utf-8").splitlines():
            f = line.split("\t")
            if len(f) >= 2 and not line.startswith("#"):
                keys.setdefault(f[0], f[1])
    return keys


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wikidata", type=Path, required=True)
    ap.add_argument("--mozc-dictionaries", type=Path, required=True)
    ap.add_argument("--ut", type=Path, help="mozcdic-ut-sudachidict.txt (readings of kanji names, and of names in Latin letters)")
    ap.add_argument("--table", type=Path, required=True)
    ap.add_argument("--lexicon", type=Path, required=True)
    ap.add_argument("--trial", type=Path, required=True)
    ap.add_argument("--trial-work", type=Path, required=True, help="folder with romaji.tsv and readings.txt")
    ap.add_argument("--corpus", type=Path, nargs="*",
                    help="romaji lines of Japanese text, with or without English words "
                         "(tools/make_japanese_romaji_corpus.py), to find new words that change what is taken as English")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--work", type=Path, required=True, help="scratch folder")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    table = rv.load_table(args.table)
    ordinary = set((args.lexicon / "english-lexicon.txt").read_text().split())
    common = set((args.lexicon / "common-words.txt").read_text().split())
    cased = existing_casing()
    kanji_reading = load_readings(args.mozc_dictionaries, args.ut)
    known_readings = set((args.trial_work / "readings.txt").read_text(encoding="utf-8").split())

    # 1. Candidates. One per official spelling, the best known first.
    found = {}
    for path in sorted(args.wikidata.glob("*.tsv")):
        kind = path.stem
        for line in path.read_text(encoding="utf-8").splitlines():
            f = line.split("\t")
            if len(f) < 4:
                continue
            shown = clean_english(f[1])
            if shown is None:
                continue
            sitelinks = int(f[3])
            ja = f[2]
            aliases = f[4].split("|") if len(f) > 4 and f[4] else []
            readings = []
            if ja and KATA.fullmatch(ja):
                readings.append(hira(ja))
            readings += [hira(a) for a in aliases]
            # the English spelling lost its company suffix (Samsung Group -> Samsung); so does the reading
            for r in list(readings):
                for suffix in KANA_SUFFIXES:
                    if r and r.endswith(suffix) and len(r) - len(suffix) >= 3:
                        readings.append(r[: -len(suffix)])
            if not [r for r in readings if r] and ja and kind not in PEOPLE and not ja.isascii():
                r = kanji_reading.get(ja)
                if r and len(r) >= 3:
                    readings.append(r)
            entry = found.get(shown)
            if entry is None:
                found[shown] = entry = {"kind": kind, "sl": sitelinks, "readings": []}
            elif sitelinks > entry["sl"]:
                entry["kind"], entry["sl"] = kind, sitelinks
            for r in readings:
                if r and r not in entry["readings"]:
                    entry["readings"].append(r)
    # Readings of the names in Latin letters that Sudachi has (Python: ぱいそん), for the spellings Wikidata
    # has no katakana label for, and for the official spellings of the tables the detector already has
    # (brand-casing.tsv ...), which are names Japanese users type.
    if args.ut:
        ut_latin = load_ut_latin(args.ut)
        for official in sorted(set(cased.values())):
            if official not in found and re.sub(r"[^a-z0-9]", "", official.lower()) in ut_latin:
                found[official] = {"kind": "other", "sl": 0, "readings": []}
        for shown, entry in found.items():
            for readings in ut_latin.get(re.sub(r"[^a-z0-9]", "", shown.lower()), {}).get(shown, []):
                if readings not in entry["readings"]:
                    entry["readings"].append(readings)
    print("spellings", len(found))

    # 2. How it is typed, and whether the typed form is a common English word.
    rows = []
    for shown, e in found.items():
        tokens = typed_form(shown)
        key = " ".join(tokens) if tokens else ""
        joined = "".join(tokens) if tokens else ""
        flags = ""
        if tokens and len(tokens) == 1 and (joined in common or joined in ordinary):
            if e["sl"] < (PLACE_COMMON_WORD_MIN_SITELINKS if e["kind"] in PLACE_KINDS else COMMON_WORD_MIN_SITELINKS):
                continue  # an ordinary word that happens to be a name: left alone
            flags = "s"
        elif not e["readings"] and not tokens:
            continue
        # a spelling typed as plain romaji reads as kana: its reading, for the candidates of that kana
        if joined and e["kind"] in ALIAS_KINDS and joined.isalpha():
            kana = rv.to_kana(joined, table)
            # only a reading Mozc has as a word (あまぞん), not what x, l, q or v would make (ぁ, ぃ)
            if kana in known_readings and len(kana) >= 3 and kana not in e["readings"]:
                e["readings"].append(kana)
        for kana in EXTRA_READINGS.get(shown, []):
            if kana not in e["readings"]:
                e["readings"].append(kana)
        rows.append({"shown": shown, "tokens": tokens, "key": key, "joined": joined, "flags": flags,
                     "kind": e["kind"], "sl": e["sl"], "readings": e["readings"][:3]})
    # one name per typed form: the best known
    by_key = defaultdict(list)
    for r in rows:
        if r["tokens"]:
            by_key[r["key"]].append(r)
    for key, group in by_key.items():
        group.sort(key=lambda r: -r["sl"])
        for r in group[1:]:
            r["tokens"], r["key"], r["flags"] = None, "", ""
    for r in rows:
        if r["tokens"] and r["key"] in cased or (r["tokens"] and r["joined"] in cased):
            r["tokens"], r["key"], r["flags"] = None, "", ""
    # Two words or more read entirely as kana (hiroshisato: ひろしさと) are Japanese typed in romaji,
    # not a name in English letters: the detector must not take them (a set phrase needs no foreign sign).
    for r in rows:
        if r["tokens"] and len(r["tokens"]) > 1 and HIRA.fullmatch(rv.to_kana(r["joined"], table)):
            r["tokens"], r["key"], r["flags"] = None, "", ""
    # A new word of 4 letters or fewer (kde, ica) is too likely to be part of other words (ok|desu).
    known = ordinary | set((args.lexicon / "signal-words.txt").read_text().split())
    for r in rows:
        if r["tokens"] and len(r["tokens"]) == 1 and len(r["joined"]) <= 4 and r["joined"] not in known:
            r["tokens"], r["key"], r["flags"] = None, "", ""
    typed_rows = [r for r in rows if r["tokens"]]
    print("rows", len(rows), "typable", len(typed_rows))

    # 3. Add the typable names to the detector's word lists and see which are taken as English whole.
    lex = args.work / "lex"
    lex.mkdir(parents=True, exist_ok=True)
    for name in ("english-lexicon.txt", "curated-words.txt", "common-words.txt", "joined.txt", "phrases.txt", "places.tsv"):
        source = args.lexicon / name
        if source.exists():
            (lex / name).write_bytes(source.read_bytes())
    signal = (args.lexicon / "signal-words.txt").read_text().splitlines()
    phrases = (lex / "phrases.txt").read_text(encoding="utf-8").splitlines()
    singles = [r["joined"] for r in typed_rows if len(r["tokens"]) == 1]
    multis = [r["key"] for r in typed_rows if len(r["tokens"]) > 1]
    (lex / "signal-words.txt").write_text("\n".join(signal + singles) + "\n")
    (lex / "phrases.txt").write_text("\n".join(phrases + multis) + "\n", encoding="utf-8")

    def run_trial(lexicon_dir, lines):
        proc = subprocess.run([str(args.trial), str(args.trial_work), str(lexicon_dir)], input="\n".join(lines) + "\n",
                              capture_output=True, text=True, encoding="utf-8", check=True)
        return [l.split("\t")[1] if "\t" in l else "" for l in proc.stdout.splitlines()]

    out = run_trial(lex, [r["joined"] for r in typed_rows])
    for r, got in zip(typed_rows, out):
        if got.replace(" ", "") != r["joined"] or "," in got:
            r["tokens"], r["key"], r["flags"] = None, "", ""
        else:
            if len(r["tokens"]) > 1:
                r["key"] = got  # where the detector puts the spaces
    print("taken as English whole", sum(1 for r in typed_rows if r["tokens"]))

    # 4. Names that change what is taken as English in the corpus (a Japanese word read as a name, a
    #    name cutting into an English word next to it) are dropped.
    if args.corpus:
        base = args.work / "lex-base"
        base.mkdir(exist_ok=True)
        for p in lex.iterdir():
            (base / p.name).write_bytes(p.read_bytes())
        (base / "signal-words.txt").write_text("\n".join(signal) + "\n")
        (base / "phrases.txt").write_text("\n".join(phrases) + "\n", encoding="utf-8")
        lines = [l for path in args.corpus for l in path.read_text(encoding="utf-8").splitlines() if l]
        before = run_trial(base, lines)
        for round_ in range(3):
            after = run_trial(lex, lines)
            bad = set()
            for l, b, a in zip(lines, before, after):
                if a != b:
                    for piece in a.split(","):
                        if piece not in b.split(","):  # an English piece that was not there before
                            bad.add(piece)
            print("round", round_, "corpus lines changed", sum(1 for b, a in zip(before, after) if a != b),
                  "words dropped", len(bad), sorted(bad)[:40])
            if not bad:
                break
            drop = {p.replace(" ", "") for p in bad} | {w for p in bad for w in p.split(" ")}
            for r in typed_rows:
                if r["tokens"] and r["joined"] in drop:
                    r["tokens"], r["key"], r["flags"] = None, "", ""
            singles = [r["joined"] for r in typed_rows if r["tokens"] and len(r["tokens"]) == 1]
            multis = [r["key"] for r in typed_rows if r["tokens"] and len(r["tokens"]) > 1]
            (lex / "signal-words.txt").write_text("\n".join(signal + singles) + "\n")
            (lex / "phrases.txt").write_text("\n".join(phrases + multis) + "\n", encoding="utf-8")

    with args.out.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write("# 大文字を含む英字の固有名詞。tools/build_proper_nouns.py で作る（手で足さない）。出典は Wikidata（CC0）。\n")
        fh.write("# 列: 表示<TAB>打つ形（小文字、2語以上は空白で区切る。英語として取れない名前は空）<TAB>印（s: 普通の英単語でもある。"
                 "打った形を先に、固有名詞を2番目に）<TAB>かなの読み（| 区切り）<TAB>分野<TAB>ウィキペディアの言語版の数\n")
        for r in sorted(rows, key=lambda r: (r["kind"], -r["sl"], r["shown"])):
            if not r["key"] and not r["readings"]:
                continue
            fh.write("\t".join([r["shown"], r["key"], r["flags"], "|".join(r["readings"]), r["kind"], str(r["sl"])]) + "\n")
    print("written", args.out)


if __name__ == "__main__":
    main()
