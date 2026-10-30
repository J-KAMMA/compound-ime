"""日本語の表記の名前（Wikidata、CC0）と住所（日本郵便の郵便番号データ）を、追加の辞書の行にする。

  python tools/build_ja_dictionary.py --mozc <mozc/src> \
      [--wikidata <dir>/ja-wikidata-raw.tsv] [--postal <dir>/postal-raw.tsv] \
      --out-wikidata ja-wikidata.tsv --out-postal ja-postal.tsv [--report report.md]

元は tools/fetch_wikidata_ja.py と tools/fetch_japanpost.py の出力。出力は Mozc の辞書の元データと同じ形
（読み<TAB>左品詞<TAB>右品詞<TAB>費用<TAB>表記）で、月1回の追加の辞書（supplement.tsv）に足す
（.github/workflows/dict-update.yml。docs/dict-update.md の「日本語の名前と住所」）。

件数より「普通の変換を悪くしない」ことを先にする。決まり:

取らないもの
- 読みがかなでない、読みが3かなより短い、表記が2文字より短いか24文字より長い、表記に漢字がない（かなだけの
  表記は Mozc が読みから作れる）、表記に英字・数字・記号がある（英字の名前は proper-nouns.tsv の係）。
- 表記の中のかなが、読みの中に同じ順で出ない（ラベルと読みが別の物を指している）。
- 読みが表記を覆わない: 表記のかなの部分はそのまま、漢字の並び n 字は n〜5n かな（4字以上は n + (n-2)//2 から）
  に当てはまらない（ブルサ県 を ぶるさ、鎮西大社諏訪神社 を すわじんじゃ、電気電子工学 を でんしこうがく）。
- 読みが外来語の形（ー がある）で、表記が漢字だけ（視覚芸術 を びじゅあるあーと）。
- Wikidata だけ: 読みを、Mozc の辞書にある部分の読み（1〜6字。連濁・促音も）でたどれない（別名・通称。
  憲宗 を りじゅん）。辞書でたどれなくてよい漢字は --free-kanji-per 字（既定3）ごとに1字（2字の表記は0字）。
  住所は日本郵便の公式の読みなので、この確かめはしない（十六島 うっぷるい のような読みを残す）。
- Mozc の辞書（焼き込みの dictionary14.txt まで全部）に同じ（読み、表記）がある。
- よく使う語の別の読み: 表記が Mozc に費用 --common-cost 未満であり、その読みが Mozc のその表記の読みにない
  （「日本」を やまと で、のような珍しい読み。普通の語の表記を、知らない読みで出してしまう）。
- Mozc にない読みで4かなより短いもの（その読みの1語が、ほかの語のかなに勝ってしまう）。

費用（小さいほど先に出る。Mozc の費用と同じ尺度）
- 読みが Mozc にある（一般語と同じ読み）: max(その読みの一番高い語 + --margin, 一番安い語 + --gap)。
  同じ読みの語の全部より後ろで、一番安い語からも大きく離す（品詞の接続の違いで文の中で勝たないように）。
  候補の一覧の後ろには出る。
- 読みが Mozc にない（4かな以上）: --new-cost（既定 15000。英字の固有名詞 dictionary14.txt と同じ値。
  これより安くすると、文の中で Mozc の語の並びに勝つ。たいら → Tyla の失敗が元）。名前だけを打てば候補に出る。
- 同じ読みに新しい表記が複数あるときは、Wikidata は sitelinks の多い順、住所は 都道府県 → 市区町村 → 町域 の順に
  1ずつ足す。Wikidata と住所に同じ（読み、表記）があれば Wikidata の行だけ。

品詞: 人 → 名詞,固有名詞,人名,一般、場所・住所 → 名詞,固有名詞,地域,一般、組織 → 名詞,固有名詞,組織、
それ以外 → 名詞,固有名詞,一般。
"""
import argparse
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

HIRAGANA = re.compile(r"[ぁ-ゖー]+")
POS = {
    "person": "名詞,固有名詞,人名,一般,*,*,*",
    "place": "名詞,固有名詞,地域,一般,*,*,*",
    "org": "名詞,固有名詞,組織,*,*,*,*",
    "other": "名詞,固有名詞,一般,*,*,*,*",
}
KIND_POS = {"person": "person", "place": "place", "pref": "place", "city": "place", "town": "place",
            "org": "org", "work": "other", "other": "other"}
LEVEL_ORDER = {"pref": 0, "city": 1, "town": 2}
MAX_COST = 32767


def is_kanji(ch):
    return "一" <= ch <= "鿿" or "㐀" <= ch <= "䶿" or "豈" <= ch <= "﫿" or ch in "々〆" or "\U00020000" <= ch <= "\U0003134f"


def is_kana(ch):
    return "ぁ" <= ch <= "ゖ" or "ァ" <= ch <= "ヺ" or ch == "ー"


def to_hiragana(text):
    out = []
    for ch in unicodedata.normalize("NFKC", text):
        if ch in " 　・=＝、,":
            continue
        if ch == "ヴ":
            out.append("ゔ")
        elif "ァ" <= ch <= "ヶ":
            out.append(chr(ord(ch) - 0x60))
        else:
            out.append(ch)
    return "".join(out)


def surface_problem(surface):
    """表記を取らない理由か None。"""
    if not 2 <= len(surface) <= 24:
        return "表記の長さ"
    if not any(is_kanji(ch) for ch in surface):
        return "表記に漢字がない"
    for ch in surface:
        if not (is_kanji(ch) or is_kana(ch) or ch in "ヶヵ・"):
            return "表記に英字・数字・記号"
    return None


def reading_problem(surface, reading, min_reading):
    if not HIRAGANA.fullmatch(reading or ""):
        return "読みがかなでない"
    if len(reading) < min_reading:
        return "読みが短い"
    # 表記の中のかな（カタカナはひらがなに）が、読みの中に同じ順で出るか
    kana = [to_hiragana(ch) for ch in surface if is_kana(ch) and ch not in "ーヶヵ"]  # ヶ は が・け と読む
    pos = 0
    for k in kana:
        pos = reading.find(k, pos)
        if pos < 0:
            return "表記のかなが読みにない"
        pos += len(k)
    if "ー" in reading and not any(is_kana(ch) for ch in surface):
        return "読みが外来語の形（表記は漢字だけ）"
    if not re.fullmatch(structure_pattern(surface), reading):
        return "読みが表記を覆わない（かなと漢字の並び・字数）"
    return None


def kanji_run_bounds(n):
    """漢字 n 字の並びの読みの長さの下限と上限。2字までは1字1かなまで（江戸 えど）、それより長い並びは
    平均1.5かな以上（電気電子工学 を でんしこうがく では覆わない）。上限は1字5かな（承 うけたまわ）。"""
    return (n if n <= 3 else n + (n - 2) // 2), 5 * n


def structure_pattern(surface):
    """表記の並び（かなの部分はそのまま、漢字の並びは字数に合う長さ）に読みが合うかの正規表現。
    ブルサ県 を ぶるさ（県 の読みがない）、鎮西大社諏訪神社 を すわじんじゃ（短すぎる）は合わない。"""
    parts, run = [], 0
    for ch in surface + "\0":
        if is_kanji(ch):
            run += 1
            continue
        if run:
            lo, hi = kanji_run_bounds(run)
            parts.append(f".{{{lo},{hi}}}")
            run = 0
        if ch == "\0" or ch == "・":
            continue
        if ch in "ヶヵ":
            parts.append("[がけかこ]")
        else:
            parts.append(re.escape(to_hiragana(ch)))
    return "".join(parts)


VOICED = dict(zip("かきくけこさしすせそたちつてとはひふへほ", "がぎぐげござじずぜぞだぢづでどばびぶべぼ"))
VOICED.update(zip("はひふへほ", "ばびぶべぼ"))
SEMI = dict(zip("はひふへほ", "ぱぴぷぺぽ"))


def reading_variants(r, first):
    """辞書の読み r の、語の中での形（連濁: かわ → がわ、促音: いち → いっ）。"""
    out = {r}
    if not first and r and r[0] in VOICED:
        out.add(VOICED[r[0]] + r[1:])
        if r[0] in SEMI:
            out.add(SEMI[r[0]] + r[1:])
    for v in list(out):
        if len(v) >= 2 and v[-1] in "つくちき":
            out.add(v[:-1] + "っ")
    return out


def coverage_penalty(surface, reading, surface_readings, allowed, max_seg=6):
    """表記を前から、Mozc の辞書にある部分の読み（1字〜max_seg 字。連濁・促音も）とかなでたどって、読みを
    覆えるか。辞書でたどれない漢字1字（1〜4かなを読む）ごとに1を数え、一番少ない数を返す（allowed を超えたら
    allowed + 1）。視覚芸術 を びじゅあるあーと、憲宗 を りじゅん のような別名・通称の読みを見つける。"""
    chars = [ch for ch in surface if ch != "・"]
    n, m = len(chars), len(reading)
    best = {(0, 0): 0}
    for i in range(n):
        states = sorted((j, p) for (ii, j), p in best.items() if ii == i)
        for j, p in states:
            def go(i2, j2, p2):
                if j2 <= m and p2 <= allowed and best.get((i2, j2), allowed + 1) > p2:
                    best[(i2, j2)] = p2
            ch = chars[i]
            if not is_kanji(ch):
                if ch in "ヶヵ":
                    for k in "がけかこ":
                        if reading.startswith(k, j):
                            go(i + 1, j + 1, p)
                else:
                    h = to_hiragana(ch)
                    if reading.startswith(h, j):
                        go(i + 1, j + len(h), p)
                continue
            for k in range(1, max_seg + 1):
                if i + k > n or not all(is_kanji(c) for c in chars[i:i + k]):
                    break
                for r in surface_readings.get("".join(chars[i:i + k]), ()):
                    for v in reading_variants(r, i == 0):
                        if reading.startswith(v, j):
                            go(i + k, j + len(v), p)
            cost = 0 if ch == "々" else 1  # 々 は前の字の読みを繰り返す
            for length in range(1, 5):
                go(i + 1, j + length, p + cost)
    return best.get((n, m), allowed + 1)


def load_mozc(data, skip=()):
    existing = set()
    max_cost, min_cost = {}, {}
    surface_min = {}  # 表記 → 一番安い費用
    surface_readings = defaultdict(set)
    for path in sorted(data.glob("dictionary*.txt")):
        if path.name in skip:
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            f = line.split("\t")
            if len(f) < 5:
                continue
            reading, cost, surface = f[0], int(f[3]), f[4]
            existing.add((reading, surface))
            max_cost[reading] = max(max_cost.get(reading, cost), cost)
            min_cost[reading] = min(min_cost.get(reading, cost), cost)
            surface_min[surface] = min(surface_min.get(surface, cost), cost)
            surface_readings[surface].add(reading)
    return existing, max_cost, min_cost, surface_min, surface_readings


def read_wikidata(path):
    """[(表記, 読み, 種類, 並べる値)]。"""
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        f = line.split("\t")
        if len(f) < 5 or not f[0].startswith("Q"):
            continue
        surface = unicodedata.normalize("NFC", f[1].strip())
        sitelinks = int(f[3]) if f[3].isdigit() else 0
        for kana in f[2].split("|")[:3]:
            rows.append((surface, to_hiragana(kana), f[4], -sitelinks))
    return rows


def read_postal(path):
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        f = line.split("\t")
        if len(f) < 3:
            continue
        rows.append((unicodedata.normalize("NFC", f[0].strip()), to_hiragana(f[1]), f[2], LEVEL_ORDER.get(f[2], 9)))
    return rows


class Builder:
    def __init__(self, mozc, args):
        data = mozc / "data/dictionary_oss"
        ids = {}
        for line in (data / "id.def").read_text(encoding="utf-8").splitlines():
            number, _, pos = line.partition(" ")
            ids.setdefault(pos, number)
        self.pos_id = {kind: int(ids[pos]) for kind, pos in POS.items() if pos in ids}
        if "other" not in self.pos_id:
            raise SystemExit("id.def に 名詞,固有名詞,一般 がない")
        (self.existing, self.max_cost, self.min_cost, self.surface_min,
         self.surface_readings) = load_mozc(data)
        self.args = args
        self.reasons = Counter()
        self.taken = set()  # 前の元（Wikidata）で入れた（読み、表記）
        self.collide = []   # 一般語と同じ読みに入れた語（報告用）

    def build(self, rows, source, check_coverage=False):
        """rows: [(表記, 読み, 種類, 並べる値)] → {(読み, 表記): (lid, rid, cost)}"""
        args = self.args
        picked = {}
        for surface, reading, kind, order in rows:
            why = surface_problem(surface) or reading_problem(surface, reading, args.min_reading)
            if why is None and ((reading, surface) in self.existing):
                why = "Mozc に同じ語がある"
            if why is None and (reading, surface) in self.taken:
                why = "Wikidata の行と同じ"
            if why is None and self.surface_min.get(surface, MAX_COST + 1) < args.common_cost \
                    and reading not in self.surface_readings.get(surface, ()):
                why = "よく使う語の別の読み"
            if why is None and reading not in self.max_cost and len(reading) < 4:
                why = "Mozc にない短い読み"
            if why is None and check_coverage:
                allowed = sum(1 for ch in surface if is_kanji(ch) and ch != "々") // args.free_kanji_per
                if coverage_penalty(surface, reading, self.surface_readings, allowed) > allowed:
                    why = "読みを辞書の字の読みでたどれない（別名・通称）"
            if why:
                self.reasons[f"{source}: {why}"] += 1
                continue
            key = (reading, surface)
            if key not in picked or (order, kind) < picked[key]:
                picked[key] = (order, kind)
        by_reading = defaultdict(list)
        for (reading, surface), (order, kind) in picked.items():
            by_reading[reading].append((order, surface, kind))
        out = {}
        for reading, items in by_reading.items():
            if reading in self.max_cost:
                base = max(self.max_cost[reading] + args.margin, self.min_cost[reading] + args.gap)
            else:
                base = args.new_cost
            for i, (_, surface, kind) in enumerate(sorted(items)):
                cost = base + i
                if cost > MAX_COST:
                    self.reasons[f"{source}: 費用が上限を超える"] += 1
                    continue
                pos = self.pos_id.get(KIND_POS.get(kind, "other"), self.pos_id["other"])
                out[(reading, surface)] = (pos, pos, cost)
                self.taken.add((reading, surface))
                if reading in self.max_cost:
                    self.collide.append((reading, surface, cost, self.min_cost[reading]))
        self.reasons[f"{source}: 入れた"] += len(out)
        return out


def write(path, entries):
    with path.open("w", encoding="utf-8", newline="\n") as out:
        for (reading, surface), (lid, rid, cost) in sorted(entries.items()):
            out.write(f"{reading}\t{lid}\t{rid}\t{cost}\t{surface}\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mozc", type=Path, required=True)
    parser.add_argument("--wikidata", type=Path)
    parser.add_argument("--postal", type=Path)
    parser.add_argument("--out-wikidata", type=Path, required=True)
    parser.add_argument("--out-postal", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--margin", type=int, default=100)
    parser.add_argument("--gap", type=int, default=3000)
    parser.add_argument("--new-cost", type=int, default=15000)
    parser.add_argument("--common-cost", type=int, default=5000)
    parser.add_argument("--min-reading", type=int, default=3)
    parser.add_argument("--free-kanji-per", type=int, default=3,
                        help="Wikidata の読みで、辞書でたどれなくてよい漢字は この字数ごとに1字（2字の表記は0字）")
    args = parser.parse_args()
    builder = Builder(args.mozc, args)
    wikidata = builder.build(read_wikidata(args.wikidata), "Wikidata", check_coverage=True) if args.wikidata else {}
    postal = builder.build(read_postal(args.postal), "住所") if args.postal else {}
    # 元を渡さなかった側は書かない（取れなかった回。門の その1 は、ない一覧を比べない）
    if args.wikidata:
        write(args.out_wikidata, wikidata)
    if args.postal:
        write(args.out_postal, postal)
    lines = ["## 日本語の名前と住所（tools/build_ja_dictionary.py）", "",
             f"- Wikidata: {len(wikidata)} 行、住所: {len(postal)} 行",
             f"- そのうち一般語と同じ読み（その読みの語の全部より後ろ）: {len(builder.collide)} 行、"
             f"Mozc にない読み（費用 {args.new_cost}）: {len(wikidata) + len(postal) - len(builder.collide)} 行", "",
             "| 理由 | 行 |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in sorted(builder.reasons.items())]
    lines += ["", "一般語と同じ読みに入れた語（一番安い語との差の小さい順、先頭 40）:", ""]
    for reading, surface, cost, low in sorted(builder.collide, key=lambda c: c[2] - c[3])[:40]:
        lines.append(f"- {reading} → {surface}（費用 {cost}、その読みの一番安い語 {low}）")
    text = "\n".join(lines) + "\n"
    if args.report:
        args.report.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
