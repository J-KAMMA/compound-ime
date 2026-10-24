"""Fetches names of well-known things from Wikidata (CC0) for tools/build_proper_nouns.py.

  python tools/fetch_wikidata_names.py --out <dir>

For each kind of thing below (companies, brands, software, places, people, works ...),
the items that have an English label and at least the given number of Wikipedia language
editions ("sitelinks", a measure of how well known it is). One line per item:

  Qid<TAB>English label<TAB>Japanese label (empty if none)<TAB>sitelinks<TAB>Japanese aliases (| separated)

The Japanese aliases are fetched in a second pass, only for items whose Japanese label is not
already in katakana (Google's label is "Google"; its alias is グーグル).

People are not listed by class (the query service times out on all human beings): the titles in the
monthly lists of the most viewed articles of the English and Japanese Wikipedia over the last five years
(pageviews API, CC0) are turned into Wikidata items (MediaWiki API), and those that are human
beings with enough sitelinks are kept.

Wikidata's data is CC0 (public domain): https://www.wikidata.org/wiki/Wikidata:Licensing
The query service allows about one query at a time and 60 seconds each, so this takes
about an hour. Files already in <dir> are kept (delete one to fetch it again).
"""
import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

UA = "compound-ime-dictionary/1.0 (https://github.com/J-KAMMA/compound-ime)"
ENDPOINT = "https://query.wikidata.org/sparql"

# (file name, Wikidata class, minimum sitelinks, include subclasses)
CLASSES = [
    ("business", "Q4830453", 12, True), ("brand", "Q431289", 10, True), ("software", "Q7397", 10, True),
    ("proglang", "Q9143", 5, True), ("os", "Q9135", 5, True), ("app", "Q166142", 8, True),
    ("website", "Q35127", 15, True), ("videogame", "Q7889", 25, True), ("carmodel", "Q3231690", 25, True),
    ("tvnetwork", "Q141683", 12, True), ("newspaper", "Q11032", 25, True), ("university", "Q3918", 40, True),
    ("airline", "Q46970", 8, True), ("museum", "Q33506", 35, True), ("sportsteam", "Q12973014", 25, True),
    ("country", "Q6256", 1, False), ("usstate", "Q35657", 1, False), ("city", "Q515", 45, True),
    ("island", "Q23442", 40, False), ("mountain", "Q8502", 50, False), ("river", "Q4022", 50, False),
    ("lake", "Q23397", 40, False),
    ("band", "Q215380", 25, False), ("film", "Q11424", 40, False), ("tvseries", "Q5398426", 30, False),
    ("tvprogram", "Q15416", 25, True), ("filmseries", "Q24856", 25, True),
    ("album", "Q482994", 30, False), ("novel", "Q7725634", 60, True), ("lightnovel", "Q747381", 20, True),
    ("manga", "Q8274", 20, True), ("anime", "Q1107", 20, True), ("comic", "Q1004", 20, True),
    ("videogameseries", "Q14204246", 25, True), ("character", "Q95074", 45, True),
]
PEOPLE_MIN_SITELINKS = 40
PEOPLE_MONTHS = 60
KATAKANA = re.compile(r"[ァ-ヺー・=＝ヽヾ 　]+")


def sparql(query, tries=3):
    url = ENDPOINT + "?" + urllib.parse.urlencode({"query": query, "format": "json"})
    for attempt in range(tries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/sparql-results+json"})
            return json.load(urllib.request.urlopen(request, timeout=150))["results"]["bindings"]
        except Exception as error:  # the service sometimes times out or throttles
            print("retry", attempt, error, file=sys.stderr, flush=True)
            time.sleep(20 * (attempt + 1))
    return None


def class_query(cls, low, high, transitive):
    path = "wdt:P31/wdt:P279*" if transitive else "wdt:P31"
    return f"""SELECT DISTINCT ?item ?en ?ja ?sl WHERE {{
  ?item {path} wd:{cls} .
  ?item wikibase:sitelinks ?sl . FILTER(?sl >= {low} && ?sl < {high})
  ?item rdfs:label ?en . FILTER(LANG(?en) = "en")
  OPTIONAL {{ ?item rdfs:label ?ja . FILTER(LANG(?ja) = "ja") }}
}}"""


def fetch_band(cls, low, high, transitive):
    """Rows of one class within [low, high) sitelinks; a band that fails (too big) is split in two."""
    rows = sparql(class_query(cls, low, high, transitive))
    if rows is not None:
        time.sleep(3)
        return rows
    top = min(high, 2000)
    mid = int((low * top) ** 0.5)
    if mid <= low or mid >= high:
        return None
    first = fetch_band(cls, low, mid, transitive)
    second = fetch_band(cls, mid, high, transitive) if first is not None else None
    return None if second is None else first + second


def get_json(url, tries=4):
    for attempt in range(tries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": UA})
            return json.load(urllib.request.urlopen(request, timeout=60))
        except Exception as error:
            print("retry", attempt, url[:100], error, file=sys.stderr, flush=True)
            time.sleep(5 * (attempt + 1))
    return None


def popular_titles(language):
    """Titles in the monthly lists of the most viewed articles, over the last PEOPLE_MONTHS months."""
    titles = set()
    year, month = time.gmtime().tm_year, time.gmtime().tm_mon
    for _ in range(PEOPLE_MONTHS + 1):
        month -= 1
        if month == 0:
            year, month = year - 1, 12
        data = get_json(f"https://wikimedia.org/api/rest_v1/metrics/pageviews/top/{language}.wikipedia/"
                        f"all-access/{year}/{month:02d}/all-days")
        for item in (data or {}).get("items", []):
            for article in item["articles"]:
                title = article["article"].replace("_", " ")
                if ":" not in title and title != "Main Page" and title != "メインページ":
                    titles.add(title)
    return titles


def items_of_titles(language, titles):
    ids = set()
    titles = sorted(titles)
    for start in range(0, len(titles), 50):
        query = urllib.parse.urlencode({"action": "query", "prop": "pageprops", "ppprop": "wikibase_item",
                                        "titles": "|".join(titles[start:start + 50]), "format": "json", "redirects": 1})
        data = get_json(f"https://{language}.wikipedia.org/w/api.php?{query}")
        for page in ((data or {}).get("query", {}).get("pages", {})).values():
            qid = page.get("pageprops", {}).get("wikibase_item")
            if qid:
                ids.add(qid)
    return ids


def fetch_people(path):
    ids = items_of_titles("en", popular_titles("en")) | items_of_titles("ja", popular_titles("ja"))
    print("popular items", len(ids), flush=True)
    rows = []
    ids = sorted(ids)
    for start in range(0, len(ids), 300):
        values = " ".join(f"wd:{q}" for q in ids[start:start + 300])
        part = sparql(f"""SELECT DISTINCT ?item ?en ?ja ?sl WHERE {{ VALUES ?item {{ {values} }}
          ?item wdt:P31 wd:Q5 . ?item wikibase:sitelinks ?sl . FILTER(?sl >= {PEOPLE_MIN_SITELINKS})
          ?item rdfs:label ?en . FILTER(LANG(?en) = "en")
          OPTIONAL {{ ?item rdfs:label ?ja . FILTER(LANG(?ja) = "ja") }} }}""")
        if part is None:
            return None
        rows += part
        time.sleep(2)
    return write_rows(path, rows)


def write_rows(path, rows):
    with path.open("w", encoding="utf-8", newline="\n") as out:
        seen = set()
        for b in rows:
            qid = b["item"]["value"].rsplit("/", 1)[-1]
            if qid in seen:
                continue
            seen.add(qid)
            out.write("\t".join([qid, b["en"]["value"], b.get("ja", {}).get("value", ""), b["sl"]["value"], ""]) + "\n")
    return len(seen)


def fetch_aliases(directory):
    """Second pass: Japanese aliases of the items whose Japanese label is not katakana."""
    for path in sorted(directory.glob("*.tsv")):
        lines = [line.rstrip("\n").split("\t") for line in path.read_text(encoding="utf-8").splitlines()]
        todo = [f[0] for f in lines if len(f) >= 5 and not f[4] and not KATAKANA.fullmatch(f[2] or "x") and f[0] != "done"]
        if not todo or (directory / (path.name + ".aliases")).exists():
            continue
        aliases = {}
        for start in range(0, len(todo), 300):
            values = " ".join(f"wd:{q}" for q in todo[start:start + 300])
            rows = sparql(f"""SELECT ?item ?alias WHERE {{ VALUES ?item {{ {values} }}
              ?item skos:altLabel ?alias . FILTER(LANG(?alias) = "ja") }}""")
            for b in rows or []:
                aliases.setdefault(b["item"]["value"].rsplit("/", 1)[-1], []).append(b["alias"]["value"])
            time.sleep(2)
        with path.open("w", encoding="utf-8", newline="\n") as out:
            for f in lines:
                f[4] = "|".join(a for a in aliases.get(f[0], []) if KATAKANA.fullmatch(a))
                out.write("\t".join(f) + "\n")
        (directory / (path.name + ".aliases")).write_text("done\n")
        print("aliases", path.name, len(aliases), flush=True)


def fetch_official(directory):
    """Third pass: official names (P1448) and titles (P1476) in English, for the spellings
    (DRAGON BALL, NIKE, adidas) that the labels alone do not give."""
    path = directory / "official.tsv"
    if path.exists() and path.stat().st_size > 0:
        return
    ids = set()
    for source in sorted(directory.glob("*.tsv")):
        if source.name == "official.tsv":
            continue
        for line in source.read_text(encoding="utf-8").splitlines():
            qid = line.split("\t", 1)[0]
            if qid.startswith("Q"):
                ids.add(qid)
    forms = {}
    ids = sorted(ids)
    for start in range(0, len(ids), 250):
        values = " ".join(f"wd:{q}" for q in ids[start:start + 250])
        rows = sparql(f"""SELECT ?item ?form WHERE {{ VALUES ?item {{ {values} }}
          {{ ?item wdt:P1448 ?form . FILTER(LANG(?form) = "en") }}
          UNION {{ ?item wdt:P1476 ?form . FILTER(LANG(?form) = "en") }} }}""")
        for b in rows or []:
            qid = b["item"]["value"].rsplit("/", 1)[-1]
            form = b["form"]["value"]
            forms.setdefault(qid, [])
            if form not in forms[qid]:
                forms[qid].append(form)
        time.sleep(2)
    with path.open("w", encoding="utf-8", newline="\n") as out:
        for qid in sorted(forms):
            out.write(qid + "\t" + "|".join(forms[qid]) + "\n")
    print("official", len(forms), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--only", nargs="*", help="file names to fetch (default: all)")
    parser.add_argument("--no-aliases", action="store_true")
    parser.add_argument("--no-official", action="store_true")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    jobs = [(name, cls, [(low, 1000000)], trans) for name, cls, low, trans in CLASSES]
    for name, cls, bands, trans in jobs:
        path = args.out / f"{name}.tsv"
        if (args.only and name not in args.only) or (path.exists() and path.stat().st_size > 0):
            continue
        rows = []
        for low, high in bands:
            part = fetch_band(cls, low, high, trans)
            if part is None:
                print("FAILED", name, flush=True)
                rows = None
                break
            rows += part
        if rows is not None:
            print(name, write_rows(path, rows), flush=True)
    people = args.out / "people.tsv"
    if (not args.only or "people" in args.only) and not (people.exists() and people.stat().st_size > 0):
        print("people", fetch_people(people), flush=True)
    if not args.no_aliases:
        fetch_aliases(args.out)
    if not args.no_official:
        fetch_official(args.out)


if __name__ == "__main__":
    main()
