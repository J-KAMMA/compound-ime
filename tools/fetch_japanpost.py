"""日本郵便の郵便番号データ（住所の郵便番号）から、都道府県・市区町村・町域の表記と読みを取る。
tools/build_ja_dictionary.py の元。

  python tools/fetch_japanpost.py --out <dir>            # 取って、<dir>/postal-raw.tsv を書く
  python tools/fetch_japanpost.py --parse <ken_all.csv> --out <dir>   # 取ったファイルから（試験用）

GitHub Actions の中で流す（.github/workflows/dict-update.yml）。手元で流す必要はない。

出典は日本郵便の公式のページだけ:
  https://www.post.japanpost.jp/zipcode/dl/utf/zip/utf_ken_all.zip   （UTF-8、1レコード1行、読みは全角カタカナ）
  取れないときは https://www.post.japanpost.jp/zipcode/dl/kogaki/zip/ken_all.zip （Shift_JIS、読みは半角カタカナ）
使用条件: 「日本郵便株式会社は郵便番号データに限っては著作権を主張しません。自由に配布していただいて結構です。」
（https://www.post.japanpost.jp/zipcode/dl/readme.html、utf-readme.html）

出力の1行: 表記<TAB>読み（ひらがな）<TAB>段（pref、city、town）。同じ（表記、読み）は1行。
町域は次を取らない・直す:
- 「以下に掲載がない場合」「〜の次に番地がくる場合」「〜一円」（町域の名前ではない決まり文句）
- 括弧（（…））の中は除く（「（１〜１９丁目）」「（次のビルを除く）」「（地階・階層不明）」など）。括弧の中に
  「階」があるもの（大きなビルの階ごとの番号）は、ビルの名前なので行ごと除く
- 複数の行に分かれた町域（括弧が閉じない行。古い ken_all.csv の形）はつないでから
- 読みが、かな以外（数字・記号）を含むもの（「第１地割」など）は除く
- 先頭の「大字」「字」は除く（読みの側にあれば読みも）
"""
import argparse
import csv
import io
import re
import sys
import time
import unicodedata
import urllib.request
import zipfile
from pathlib import Path

UA = "compound-ime-dictionary/1.0 (https://github.com/J-KAMMA/compound-ime)"
URLS = [
    ("https://www.post.japanpost.jp/zipcode/dl/utf/zip/utf_ken_all.zip", "utf-8"),
    ("https://www.post.japanpost.jp/zipcode/dl/kogaki/zip/ken_all.zip", "cp932"),
]
SKIP_TOWN = re.compile(r"以下に掲載がない場合|次に番地がくる場合|一円$|^一円")
HIRAGANA = re.compile(r"[ぁ-ゖー]+")
MAX_BYTES = 64 * 1024 * 1024


def hiragana(text):
    out = []
    for ch in unicodedata.normalize("NFKC", text):
        if "ァ" <= ch <= "ヶ":
            out.append(chr(ord(ch) - 0x60))
        elif ch == "ヴ":
            out.append("ゔ")
        else:
            out.append(ch)
    return "".join(out)


def strip_parens(text):
    """全角・半角の括弧の中を除く（閉じていない括弧は、そこから後ろを除く）。"""
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"\([^()]*\)", "", text)
    return text.split("(", 1)[0].strip()


def records(lines):
    """ken_all.csv の行（列のリスト）。複数の行に分かれた町域（括弧が閉じない）はつなぐ。"""
    pending = None
    for row in lines:
        if len(row) < 9:
            continue
        if pending is not None:
            if row[2] == pending[2]:
                pending[8] += row[8]
                pending[5] += row[5]
                if pending[8].count("（") <= pending[8].count("）"):
                    yield pending
                    pending = None
                continue
            yield pending
            pending = None
        if row[8].count("（") > row[8].count("）"):
            pending = list(row)
            continue
        yield row
    if pending is not None:
        yield pending


def clean_town(surface, reading):
    """(表記, 読み) か None。"""
    if not surface or SKIP_TOWN.search(surface):
        return None
    norm = unicodedata.normalize("NFKC", surface)
    inside = re.findall(r"\(([^()]*)\)?", norm)
    if any("階" in part for part in inside):
        return None
    surface, reading = strip_parens(surface), hiragana(strip_parens(reading))
    if surface.startswith("大字"):
        surface = surface[2:]
        if reading.startswith("おおあざ"):
            reading = reading[4:]
    elif surface.startswith("字"):
        surface = surface[1:]
        if reading.startswith("あざ"):
            reading = reading[2:]
    return (surface, reading) if surface and reading else None


def parse(text):
    """ken_all.csv の中身 → {(表記, 読み, 段)}。"""
    out = set()
    wards = {}  # 「〜市」→ その区の読みの一覧（政令市の区。市の読みの区切りを、区どうしの共通の頭で決める）
    for row in records(csv.reader(io.StringIO(text))):
        pref, city = row[6].strip(), row[7].strip()
        pref_r, city_r = hiragana(row[3]).strip(), hiragana(row[4]).strip()
        out.add((pref, pref_r, "pref"))
        out.add((city, city_r, "city"))
        # 「〜郡〜町」: 郡と町の名前にも分ける（表記の「郡」も読みの「ぐん」も1つだけのとき）
        if city.count("郡") == 1 and city_r.count("ぐん") == 1 and not city.endswith("郡"):
            head, tail = city.split("郡")
            hr, tr = city_r.split("ぐん")
            if head and tail and hr and tr:
                out.add((head + "郡", hr + "ぐん", "city"))
                out.add((tail, tr, "city"))
        m = re.fullmatch(r"(.+?市)(.+区)", city)
        if m:
            wards.setdefault(m.group(1), set()).add((m.group(2), city_r))
        town = clean_town(row[8].strip(), row[5].strip())
        if town:
            out.add(town + ("town",))
    for head, items in wards.items():
        if len(items) < 3:
            continue
        readings = [r for _, r in items]
        common = readings[0]
        for r in readings[1:]:
            while not r.startswith(common):
                common = common[:-1]
        cut = common.rfind("し")
        if cut <= 0:
            continue
        head_r = common[:cut + 1]
        out.add((head, head_r, "city"))
        for ward, r in items:
            if r.startswith(head_r) and len(r) > len(head_r):
                out.add((ward, r[len(head_r):], "city"))
    return {(s, r, k) for s, r, k in out if s and HIRAGANA.fullmatch(r)}


def download():
    for url, encoding in URLS:
        for attempt in range(3):
            try:
                request = urllib.request.Request(url, headers={"User-Agent": UA})
                data = urllib.request.urlopen(request, timeout=120).read(MAX_BYTES + 1)
                if len(data) > MAX_BYTES:
                    raise ValueError("大きすぎる")
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    names = [n for n in z.namelist() if n.lower().endswith(".csv")]
                    if len(names) != 1:
                        raise ValueError(f"CSV が1つでない: {names}")
                    print("got", url, len(data), names[0], flush=True)
                    return z.read(names[0]).decode(encoding)
            except Exception as error:
                print("retry", url, attempt, error, file=sys.stderr, flush=True)
                time.sleep(10 * (attempt + 1))
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--parse", type=Path, help="取ったあとの CSV（試験用。UTF-8 か Shift_JIS）")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / "postal-raw.tsv"
    if args.parse:
        raw = args.parse.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("cp932")
    else:
        if path.exists() and path.stat().st_size > 0:
            print("kept", path)
            return
        text = download()
        if text is None:
            sys.exit("FAILED: 日本郵便の郵便番号データが取れなかった")
    rows = parse(text)
    with path.open("w", encoding="utf-8", newline="\n") as out:
        for surface, reading, level in sorted(rows):
            out.write(f"{surface}\t{reading}\t{level}\n")
    counts = {k: sum(1 for r in rows if r[2] == k) for k in ("pref", "city", "town")}
    print("postal", len(rows), counts, flush=True)


if __name__ == "__main__":
    main()
