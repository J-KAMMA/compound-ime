"""日本語の表記の名前と、かなの読み（P1814）を Wikidata（CC0）から取る。tools/build_ja_dictionary.py の元。

  python tools/fetch_wikidata_ja.py --out <dir>

GitHub Actions の中で流す（.github/workflows/dict-update.yml）。手元で流す必要はない。

取るもの: 日本語のラベルと「かなの名前」P1814 の両方を持ち、ウィキペディアの言語版の数（sitelinks）が
MIN_SITELINKS 以上の項目（2026-10 の数え: P1814 を持つ項目は sitelinks 1 以上で約27万、2 以上で約10万、
5 以上で約4万。2 以上のうち人が約6万）。1行1項目:

  Qid<TAB>日本語のラベル<TAB>読み（P1814。| 区切り。かなのまま）<TAB>sitelinks<TAB>種類

種類は P31（何であるか）から決める: person（人。Q5）、place（地理的な場所・行政区画・地形）、org（組織）、
work（作品）、other（それ以外。専門語の項目もここ）。姓・名・曖昧さ回避・一覧・分類は取らない
（姓や名の項目は1語に珍しい読みが多く、普通の語を押しのけやすい）。

出典: Wikidata の問い合わせサービス https://query.wikidata.org/sparql だけ（公式）。データは CC0
（https://www.wikidata.org/wiki/Wikidata:Licensing）。問い合わせは1つずつ、60秒の上限があるので、
sitelinks の幅で分けて取る（fetch_wikidata_names.py と同じやり方）。<dir> にあるファイルは取り直さない。
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_wikidata_names import sparql  # noqa: E402  同じ取り方（User-Agent、やり直し）

MIN_SITELINKS = 2
# 取らない種類（P31 の値）
SKIP_CLASSES = {
    "Q101352",    # 姓
    "Q202444",    # 名
    "Q12308941",  # 男性の名
    "Q11879590",  # 女性の名
    "Q3409032",   # 男女の名
    "Q4167410",   # 曖昧さ回避
    "Q13406463",  # 一覧
    "Q4167836",   # 分類
    "Q11266439",  # テンプレート
    "Q17362920",  # 重複した項目
}
# 種類の根（P279* でたどる）。先にあるほうを採る
ROOTS = [
    ("place", ["Q2221906", "Q56061", "Q618123", "Q15642541"]),  # 地理的な場所、行政区画、地形、人の住む所
    ("org", ["Q43229"]),                                       # 組織
    ("work", ["Q17537576", "Q386724"]),                       # 作品、著作物
]


BANDS = [(1, 2), (2, 3), (3, 4), (4, 6), (6, 10), (10, 20), (20, 50), (50, 1000000)]


def band_query(low, high, suffix=None):
    # suffix: 項目の番号の末尾の数字で分ける（1つの sitelinks の幅でも多すぎて時間切れになるとき）
    cut = f'FILTER(STRENDS(STR(?item), "{suffix}"))' if suffix is not None else ""
    return f"""SELECT ?item ?ja (GROUP_CONCAT(DISTINCT ?kana; separator="|") AS ?kanas) ?sl
  (GROUP_CONCAT(DISTINCT STRAFTER(STR(?c), "entity/"); separator=" ") AS ?cs) WHERE {{
  ?item wdt:P1814 ?kana . {cut}
  ?item wikibase:sitelinks ?sl . FILTER(?sl >= {low} && ?sl < {high})
  ?item rdfs:label ?ja . FILTER(LANG(?ja) = "ja")
  OPTIONAL {{ ?item wdt:P31 ?c }}
}} GROUP BY ?item ?ja ?sl"""


def fetch_band(low, high, suffix=None):
    """[low, high) の項目。取れなければ、幅を2つに、それもできなければ番号の末尾の数字で10に分ける。"""
    rows = sparql(band_query(low, high, suffix))
    if rows is not None:
        time.sleep(3)
        return rows
    parts = []
    if high - low > 1:
        mid = (low + min(high, 2 * max(low, 50))) // 2
        if low < mid < high:
            parts = [(low, mid, suffix), (mid, high, suffix)]
    if not parts:
        if suffix is not None and len(suffix) >= 2:
            return None
        parts = [(low, high, f"{d}{suffix or ''}") for d in "0123456789"]
    out = []
    for part in parts:
        got = fetch_band(*part)
        if got is None:
            return None
        out += got
    return out


def classify_classes(classes):
    """クラスの番号 → 種類（place、org、work）。どの根の下でもないクラスは入らない。"""
    kinds = {}
    classes = sorted(classes)
    for kind, roots in ROOTS:
        root_values = " ".join(f"wd:{r}" for r in roots)
        for start in range(0, len(classes), 200):
            part = [c for c in classes[start:start + 200] if c not in kinds]
            if not part:
                continue
            values = " ".join(f"wd:{c}" for c in part)
            rows = sparql(f"""SELECT DISTINCT ?c WHERE {{ VALUES ?c {{ {values} }} VALUES ?root {{ {root_values} }}
              ?c wdt:P279* ?root . }}""")
            for b in rows or []:
                kinds.setdefault(b["c"]["value"].rsplit("/", 1)[-1], kind)
            time.sleep(2)
    return kinds


def kind_of(classes, kinds):
    if "Q5" in classes:
        return "person"
    found = {kinds[c] for c in classes if c in kinds}
    for kind, _ in ROOTS:
        if kind in found:
            return kind
    return "other"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--min-sitelinks", type=int, default=MIN_SITELINKS)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / "ja-wikidata-raw.tsv"
    if path.exists() and path.stat().st_size > 0:
        print("kept", path)
        return
    rows = []
    for low, high in BANDS:
        low = max(low, args.min_sitelinks)
        if low >= high:
            continue
        part = fetch_band(low, high)
        if part is None:
            sys.exit(f"FAILED: Wikidata の問い合わせが通らなかった（sitelinks {low}〜{high}）")
        print("band", low, high, len(part), flush=True)
        rows += part
    items = {}
    for b in rows:
        qid = b["item"]["value"].rsplit("/", 1)[-1]
        classes = set(b.get("cs", {}).get("value", "").split())
        if classes & SKIP_CLASSES:
            continue
        label = b["ja"]["value"]
        kanas = [k for k in b["kanas"]["value"].split("|") if k]
        old = items.get(qid)
        if old:  # 同じ項目が2行（ラベルが2つ）: 読みを足す
            old[1] = sorted(set(old[1]) | set(kanas))
            continue
        items[qid] = [label, kanas, int(b["sl"]["value"]), classes]
    all_classes = set().union(*(v[3] for v in items.values())) - {"Q5"} if items else set()
    kinds = classify_classes(all_classes)
    with path.open("w", encoding="utf-8", newline="\n") as out:
        for qid in sorted(items, key=lambda q: int(q[1:])):
            label, kanas, sl, classes = items[qid]
            clean = [k.replace("\t", " ").replace("|", " ") for k in kanas]
            out.write("\t".join([qid, label.replace("\t", " "), "|".join(clean), str(sl), kind_of(classes, kinds)]) + "\n")
    print("ja-wikidata", len(items), flush=True)


if __name__ == "__main__":
    main()
