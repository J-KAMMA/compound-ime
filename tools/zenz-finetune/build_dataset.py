#!/usr/bin/env python3
"""zenz（かな漢字変換の小さな言語モデル）を追加学習するための練習問題を作る。

  python build_dataset.py --out data --romaji-table romanji-hiragana.tsv \
      --wiki train-00007-of-00015.parquet [--size 400000] [--seed 20261015]

できるもの（--out の中）:
  train.jsonl     学習用。1行1問: {"kind": 種類, "prompt": 問い, "output": 正解}
  valid.jsonl     確かめ用（学習に使わない）。記事・見出し語の単位で学習用と分ける
  manifest.json   出どころ・利用条件・ファイルの SHA256・件数・除いた件数・設定
  excluded.txt    試験の文と重なったために除いた文（先頭 200 件、見直し用）

問いの形は、コンパウンドIMEが変換時に zenz-v3.2 へ渡す形と同じにする
（AzooKeyKanaKanjiConverter の ZenzPromptBuilder.candidateEvaluationPrompt）:
  [U+EE02 左の文脈][U+EE07 右の文脈]U+EE00 読み（カタカナ）U+EE01
正解はその後に続く表記。文の終わりの記号は学習の側（finetune.ipynb）で付ける。
文脈は改行で切った1行の、左は末尾40文字・右は先頭40文字。半角の空白は全角の空白
（U+3000）に置き換える（ZenzContext.preprocessText と同じ）。

英単語まじりの文: 英単語は確定済みの文節になり、人工知能には渡らない。英単語で
区切られた日本語の部分ごとに、英単語とほかの部分を左右の文脈として問い合わせる
（tools/apply_jaen_integration.py の PreferWholePhraseRuns）。この形の問題を作る。

試験の文は学習に入れない: tests/conversion/ の全ファイル（ja400.json、jaen270.json、
jaen200b.json、typo150*.json、reported.json、inputs.txt、variants.tsv、wiki-typing.tsv、
expected-windows-139.tsv）の文と、表記または読みが同じか、それを含む文は、
問題にする前に捨てる（TestExclusion）。文脈に使う前後の文も同じ検査を通ったものだけ。

読みの付け方: ウィキペディアの文は SudachiPy（Apache-2.0）と SudachiDict
（Apache-2.0）で読みを付ける。自作の一覧（tools/data/）は一覧にある読みを使う。

出典の混ぜ方（--mix）: 学習用の問題の数 --size を、出典ごとの割合で分ける。
  --mix wiki=0.55,tatoeba=0.1,persona=0.15,domain=0.12,synthetic=0.08
  wiki       ウィキペディア（--wiki に複数の parquet を渡せる）
  synthetic  自作の一覧（話し言葉・略語・英語の言い回し。tools/data/）
  domain     プログラミングと仮想通貨の文書（tools/zenz-finetune/domain_text.py の sentences.jsonl）
  tatoeba    Tatoeba の話し言葉（tools/colloquial_text.py の colloquial-train.jsonl）
  persona    RealPersonaChat の雑談（tools/zenz-finetune/persona_text.py の persona-train.jsonl）
  domain・tatoeba・persona は、まとめた文の一覧（--domain-text。cat で連結してよい）の source を、
  domain_sources.json の mix の欄で振り分ける。英字の言葉（git、npm、Python など）は確定済みの文節として
  左右の文脈に入れ、日本語の部分を問う。
  --max-passes で、出典ごとに「同じ文から作る問題の形の数」の上限を決める。材料が足りないときだけ、
  この回数まで同じ文を別の形（文全体・前の文つき・文の一部）で使い回す。それでも足りない分は、予定より
  少ないまま manifest.json の mix_result に出る（既定では、ウィキペディアの文全体の問題で埋める。--no-fill-wiki で止める）。
  --mix を付けないと昔の指定（--domain-share: 分野の割合、残りは wiki と synthetic）。
  --kind-weights で出典の中の種類の割合を上書きできる（synthetic は casual・modern_words・english_phrases・business・counter）。
  --ortho-share で、文のその割合について表記を新聞・公用文にそろえる（tools/data/orthography.tsv。0 なら元の表記）。

部品に分けて作る（切れても続けられる。数百万問向け）:
  --only-source domain tatoeba persona synthetic --part text   ← まず文の一覧からの出典
  --only-source wiki --slice 0/2 --part wiki0                   ← 次にウィキペディア（足りなかった分を埋める）
  --only-source wiki --slice 1/2 --part wiki1                   ← 別の工程で並べて動かせる
  --merge-parts                                                 ← 最後に valid.jsonl と manifest.json を作る
  できるもの: train-<部品>.jsonl.gz、valid-<部品>.jsonl、part-<部品>.json（目録）。学習用は部品のまま使う
  （並びは学習の側で混ぜる）。新しい試験のファイルは --extra-test で指定すると、その文も除く。
  出どころ・版・利用条件・件数は manifest.json の domain と sources に残る。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path

TAG_INPUT = ""
TAG_OUTPUT = ""
TAG_LEFT = ""
TAG_RIGHT = ""
CONTROL_RE = re.compile("[-]")
CONTEXT_MAX = 40          # ZenzPromptBuilder / conversionContext の既定
READING_MAX = 100         # 実行時は 128 文字を超える読みでは人工知能を使わない

DEFAULT_WEIGHTS = {
    "wiki_whole": 0.32,      # 文全体（文脈なし）: 試験と同じ「文を打って変換」
    "wiki_context": 0.14,    # 文全体＋前の文（入力欄にすでにある文章）
    "wiki_span": 0.12,       # 文の一部＋左右の文脈（文節ごとの問い合わせ）
    "homophone": 0.12,       # 同音異義語の候補を含む文（tools/data/homophone-cues.tsv）
    "mixed_english": 0.16,   # カタカナ語を英単語にした文（英単語は文脈側）
    "casual": 0.08,          # 話し言葉（tools/data/colloquial.tsv）
    "modern_words": 0.04,    # 略語・サービス名を文脈に含む文（jaen-modern-words.tsv）
    "english_phrases": 0.02, # 英語の決まった言い回しを文脈に含む文（english-phrases.txt）
    "business": 0.06,        # ビジネス文（貴社・拝啓・お取引など。business-phrases.tsv の文を型に入れる）
    "counter": 0.06,         # 数＋助数詞（一杯・二羽・三日間など。counters.tsv の読みを型に入れる）
}
SYNTHETIC_KINDS = ("casual", "modern_words", "english_phrases", "business", "counter")
# 分野の文書（プログラミング・仮想通貨。tools/zenz-finetune/domain_text.py で取り出した文）の問題。
# --domain-text を付けたときだけ作り、全体の --domain-share（既定 0.5）をこの4種類で分ける。
DOMAIN_WEIGHTS = {
    "domain_whole": 0.30,    # 文全体（文脈なし）
    "domain_context": 0.15,  # 文全体＋前の文
    "domain_span": 0.20,     # 文の一部＋左右の文脈
    "domain_english": 0.35,  # 英字の言葉（git、npm、Python など）を含む文の、日本語の部分。英字は文脈側
}
DOMAIN_KINDS = tuple(DOMAIN_WEIGHTS)
WIKI_KINDS = ("wiki_whole", "wiki_context", "wiki_span", "homophone", "mixed_english")

# ---- 出典の混ぜ方（--mix wiki=0.55,tatoeba=0.2,... の名前）
# 文の一覧（sentences.jsonl）から作る出典: 問題の形（whole 文全体、context 前の文つき、span 文の一部、
# english 英字の言葉を含む文の日本語の部分）と、出典の中での割合。形の名前は <出典>_<形>。
TEXT_SHAPES = {
    "domain": DOMAIN_WEIGHTS,
    "tatoeba": {"tatoeba_whole": 0.55, "tatoeba_span": 0.45},   # 1文ずつの短い文で、前の文も英字もない
    "persona": {"persona_whole": 0.30, "persona_context": 0.40, "persona_span": 0.25, "persona_english": 0.05},
}
SOURCE_KINDS = {
    "wiki": {k: DEFAULT_WEIGHTS[k] for k in WIKI_KINDS},
    "synthetic": {k: DEFAULT_WEIGHTS[k] for k in SYNTHETIC_KINDS},   # 自作の一覧（話し言葉・略語・言い回し）
    **TEXT_SHAPES,
}
TEXT_SOURCES = tuple(TEXT_SHAPES)
KIND_SOURCE = {kind: source for source, kinds in SOURCE_KINDS.items() for kind in kinds}
# 出典ごとの「同じ文から作る問題の形の数」の上限（材料が足りないときだけ、この回数まで文を使い回す）
DEFAULT_MAX_PASSES = {"wiki": 2, "synthetic": 1, "domain": 3, "tatoeba": 3, "persona": 3}
# --mix を付けないときの出典の割合（昔の指定: 分野の文があれば --domain-share を分野に、残りを wiki と synthetic に）
LEGACY_BASE_MIX = {"wiki": 0.86, "synthetic": 0.14}


def parse_mix(text: str, args) -> dict:
    """出典ごとの割合（合計 1 にそろえる）。割合 0 の出典は作らない。"""
    if text:
        mix = {}
        for item in text.split(","):
            name, value = item.strip().split("=")
            if name.strip() not in SOURCE_KINDS:
                raise SystemExit(f"--mix の出典が不明: {name}（使えるのは {', '.join(SOURCE_KINDS)}）")
            mix[name.strip()] = float(value)
    elif args.domain_text:
        share = args.domain_share
        mix = {name: (1 - share) * value for name, value in LEGACY_BASE_MIX.items()}
        mix["domain"] = share
    else:
        mix = dict(LEGACY_BASE_MIX)
    total = sum(mix.values())
    if total <= 0:
        raise SystemExit("--mix の割合の合計が 0 です")
    return {name: value / total for name, value in mix.items() if value > 0}


def parse_slice(text: str) -> tuple:
    """"i/n"（0 始まり）を (i, n) にする。"""
    if not text:
        return 0, 1
    index, count = (int(x) for x in text.split("/"))
    if not 0 <= index < count:
        raise SystemExit(f"--slice は i/n（0 <= i < n）で指定してください: {text}")
    return index, count


def parse_passes(text: str) -> dict:
    passes = dict(DEFAULT_MAX_PASSES)
    for item in (text.split(",") if text else []):
        name, value = item.strip().split("=")
        if name.strip() not in passes:
            raise SystemExit(f"--max-passes の出典が不明: {name}（使えるのは {', '.join(passes)}）")
        passes[name.strip()] = max(1, int(value))
    return passes

# ---------------------------------------------------------------- 文字の処理

HIRA = "".join(chr(c) for c in range(0x3041, 0x3097))
KATA = "".join(chr(c) for c in range(0x30A1, 0x30F7))
TO_KATA = str.maketrans(HIRA, KATA)
TO_HIRA = str.maketrans(KATA, HIRA)
PUNCT_KEEP = "、。「」・！？"
SURFACE_OK = re.compile(r"^[ぁ-ゖァ-ヺー一-鿿々〆ヶ、。「」・！？]+$")
READING_OK = re.compile(r"^[ァ-ヺー、。「」・！？]+$")
NORM_DROP = re.compile(r"[\s　、。，．,.!！?？「」『』（）()\[\]【】・…‥〜~\"'“”‘’:：;；]")


def to_katakana(text: str) -> str:
    return text.translate(TO_KATA)


def to_hiragana(text: str) -> str:
    return text.translate(TO_HIRA)


def model_text(text: str) -> str:
    """ZenzContext.preprocessText: 空白は全角の空白、改行は消す。"""
    return text.replace(" ", "　").replace("\n", "")


def build_prompt(reading_katakana: str, left: str = "", right: str = "") -> str:
    left = CONTROL_RE.sub("", left.split("\n")[-1])[-CONTEXT_MAX:]
    right = CONTROL_RE.sub("", right.split("\n")[0])[:CONTEXT_MAX]
    prompt = ""
    if left:
        prompt += TAG_LEFT + left
    if right:
        prompt += TAG_RIGHT + right
    return model_text(prompt + TAG_INPUT + reading_katakana + TAG_OUTPUT)


def norm_surface(text: str) -> str:
    return NORM_DROP.sub("", unicodedata.normalize("NFKC", text).lower())


def norm_reading(text: str) -> str:
    return NORM_DROP.sub("", to_hiragana(unicodedata.normalize("NFKC", text).lower()))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_unit(seed: int, key: str) -> float:
    """seed と key だけで決まる 0 以上 1 未満の数（学習用と確かめ用の振り分け）。"""
    value = hashlib.sha256(f"{seed}\t{key}".encode("utf-8")).digest()
    return int.from_bytes(value[:8], "big") / 2**64

# ---------------------------------------------------------------- 試験の文を除く


def load_romaji_table(path: Path) -> dict:
    table = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        cols = line.split("\t")
        if len(cols) >= 2 and cols[0]:
            table[cols[0]] = (cols[1], cols[2] if len(cols) > 2 else "")
    return table


def romaji_to_kana(raw: str, table: dict) -> str:
    """Mozc のローマ字表で読む（tools/romaji_variants.py の to_kana と同じ読み方）。"""
    longest = max(len(k) for k in table)
    out, rest = [], raw
    while rest:
        for size in range(min(longest, len(rest)), 0, -1):
            key = rest[:size]
            if key not in table:
                continue
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


class SubstringIndex:
    """多数の短い文字列のどれかを含むかを速く調べる（先頭2文字で引く）。"""

    def __init__(self, keys):
        self.by_head: dict[str, list[str]] = {}
        for key in set(keys):
            if len(key) >= 2:
                self.by_head.setdefault(key[:2], []).append(key)

    def find(self, text: str):
        for i in range(len(text) - 1):
            for key in self.by_head.get(text[i:i + 2], ()):
                if text.startswith(key, i):
                    return key
        return None


class TestExclusion:
    """tests/conversion/ の文と表記・読みが同じか、それを含む文を見つける。

    表記: 正解（intended）と別解（alternatives）、variants.tsv の正解、
          expected-windows-139.tsv の変換結果（念のため）。
    読み: 各文のローマ字（romaji、correct_romaji、inputs.txt）を Mozc の
          ローマ字表でかなにしたもの。英単語の入った文（english の欄がある文）は、
          英単語を打ったまま残し、ほかをかなにしたもの（あしたのmeetingは…）。
    比べる前に NFKC・小文字・ひらがなにそろえ、空白と句読点・括弧を除く。
    短すぎる文字列で「含む」を調べると普通の文が大量に消えるため、表記は
    SURFACE_MIN 文字以上、読みは READING_MIN 文字以上のときだけ「含む」も調べ、
    それより短いものは「同じ」だけを調べる。
    """

    SURFACE_MIN = 4
    READING_MIN = 6

    def __init__(self, test_dir: Path, romaji_table: dict, english_to_katakana=None, ignore=(), extra_files=(),
                 ascii_containment=True):
        english_to_katakana = english_to_katakana or {}
        self.files = []
        surfaces, readings = set(), set()

        def add_surface(text: str):
            """試験の文の表記。句点で区切れる複数の文なら、1文ずつも足す
            （片方だけの文を練習に使うと、試験の文の半分を覚えさせることになるため）。"""
            surfaces.add(norm_surface(text))
            pieces = re.split(r"[。！？!?\n]", text)
            if len(pieces) > 1:
                surfaces.update(key for key in map(norm_surface, pieces) if len(key) >= self.SURFACE_MIN)

        def add_reading(romaji: str, english=()):
            romaji = unicodedata.normalize("NFKC", romaji).lower()
            pieces, used, rest = [], [], romaji
            for word in english:
                word = word.lower().replace(" ", "")
                at = rest.find(word)
                if at < 0:
                    continue
                pieces.append(rest[:at])
                used.append(word)
                rest = rest[at + len(word):]
            pieces.append(rest)
            # 英単語は打ったまま（小文字・空白なし）で読みの中に残す。学習の側の
            # 英単語まじりの文も同じ形（日本語の部分の読み＋英単語）で比べる。
            # 英単語をカタカナ語に戻した読みも足す（明日のmeeting… に対して 明日のミーティング… も除く）
            key, katakana_key = "", ""
            for i, piece in enumerate(pieces):
                kana = romaji_to_kana(piece, romaji_table) if piece else ""
                key += kana
                katakana_key += kana
                if i < len(used):
                    key += used[i]
                    katakana_key += english_to_katakana.get(used[i], used[i])
            for text in (key, katakana_key):
                text = norm_reading(text)
                if text:
                    readings.add(text)

        for path in sorted(test_dir.rglob("*.json")):  # holdout/ などの下のフォルダも
            data = json.loads(path.read_text(encoding="utf-8"))
            items = data["items"] if isinstance(data, dict) else data
            for item in items:
                for text in [item.get("intended", "")] + list(item.get("alternatives", []) or []):
                    if text:
                        add_surface(text)
                english = item.get("english", []) or []
                for key in ("romaji", "correct_romaji"):
                    if item.get(key):
                        add_reading(item[key], english)
            self.files.append(path)
        inputs = test_dir / "inputs.txt"
        if inputs.exists():
            for line in inputs.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    add_reading(line.strip())
            self.files.append(inputs)
        tsv_files = [(test_dir / name, column) for name, column in
                     (("variants.tsv", 3), ("expected-windows-139.tsv", 2), ("wiki-typing.tsv", 1),
                      ("domain-prog.tsv", 1), ("domain-crypto.tsv", 1), ("colloquial.tsv", 1),
                      ("toku.tsv", 1), ("naru.tsv", 1)) if name not in ignore]
        extra = [Path(p) for p in extra_files]
        tsv_files += [(p, 1) for p in extra]  #これから足す試験（分野の試験を作った直後など）
        for path, column in tsv_files:
            if not path.exists():
                continue
            typing_test = path.name in ("wiki-typing.tsv", "domain-prog.tsv", "domain-crypto.tsv", "colloquial.tsv",
                                        "toku.tsv", "naru.tsv") or path in extra
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.startswith("#"):
                    continue
                cols = line.split("\t")
                if typing_test and cols[0]:
                    add_reading(cols[0])  # 打ち込み試験: ローマ字と元の文の両方で除く
                if len(cols) > column and cols[column]:
                    add_surface(cols[column])
                if path.name == "variants.tsv" and len(cols) > 4 and cols[4]:
                    for alt in cols[4].split("|"):
                        add_surface(alt)
            self.files.append(path)
        known = {p.name for p in self.files} | set(ignore)
        self.unhandled = []  # 中身を読めなかった（形が分からない）ファイル。manifest に出す
        japanese_text = re.compile(r"[ぁ-ゖァ-ヺ一-鿿]")
        for path in sorted(test_dir.rglob("*")):
            if not path.is_file() or path.name in known or path.name.startswith("."):
                continue
            if path.suffix not in (".txt", ".tsv", ".csv", ".jsonl"):
                self.unhandled.append(path.name)
                continue
            # 新しく足された試験のファイル、context.tsv（ローマ字・元の文・前の文）なども、全部の列を調べる:
            # ローマ字の形の列は読みとして、日本語を含む列は表記（前の文を含む）として、試験の文に数える
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.startswith("#"):
                    continue
                if path.suffix == ".jsonl":  # 1行 1 つの JSON: 日本語を含む文字列の値を全部、表記として数える
                    for m in re.findall(r'"([^"]*[ぁ-ゖァ-ヺ一-鿿][^"]*)"', line):
                        add_surface(m)
                    continue
                for col in line.split("," if path.suffix == ".csv" else "\t"):
                    col = col.strip()
                    if len(col) < 2:
                        continue
                    if re.fullmatch(r"[a-z0-9\-',.?!~]+", col):
                        add_reading(col)
                    elif japanese_text.search(col):
                        add_surface(col)
            self.files.append(path)
        surfaces.discard("")
        readings.discard("")
        self.surface_exact = surfaces
        self.reading_exact = readings
        # 英字だけの試験の語（github、python など）を含む文まで消すと、分野の文書の文が大量に消える。
        # ascii_containment=False では、英字だけの語は「同じ」だけを調べ、「含む」は調べない
        # （日本語を含む試験の文は、今までどおり「含む」も調べる）
        japanese = re.compile(r"[ぁ-ゖァ-ヺ一-鿿]")

        def contains_checked(key: str, minimum: int) -> bool:
            return len(key) >= minimum and (ascii_containment or bool(japanese.search(key)))

        self.surface_index = SubstringIndex(s for s in surfaces if contains_checked(s, self.SURFACE_MIN))
        self.reading_index = SubstringIndex(r for r in readings if contains_checked(r, self.READING_MIN))
        self.stats = {
            "files_unhandled": self.unhandled,
            "surface_keys": len(surfaces),
            "surface_keys_checked_by_containment": sum(contains_checked(s, self.SURFACE_MIN) for s in surfaces),
            "reading_keys": len(readings),
            "reading_keys_checked_by_containment": sum(contains_checked(r, self.READING_MIN) for r in readings),
        }

    def blocked(self, surface: str, readings=()) -> str | None:
        s = norm_surface(surface)
        if s in self.surface_exact:
            return f"表記が同じ: {s}"
        hit = self.surface_index.find(s)
        if hit:
            return f"表記を含む: {hit}"
        for reading in readings:
            r = norm_reading(reading)
            if not r:
                continue
            if r in self.reading_exact:
                return f"読みが同じ: {r}"
            hit = self.reading_index.find(r)
            if hit:
                return f"読みを含む: {hit}"
        return None

# ---------------------------------------------------------------- 自作の一覧


def data_lines(path: Path):
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            yield line.rstrip("\n")


def load_colloquial(path: Path):
    entries = []
    for line in data_lines(path):
        cols = line.split("\t")
        if len(cols) >= 3 and cols[0] and cols[1]:
            entries.append((cols[0], cols[1], cols[2]))
    return entries


def load_katakana_english(path: Path):
    mapping = {}
    for line in data_lines(path):
        cols = line.split("\t")
        if len(cols) >= 2 and cols[0] and cols[1] and cols[0] not in mapping:
            mapping[cols[0]] = cols[1]
    return mapping


def load_modern_words(path: Path):
    words = []
    for line in data_lines(path):
        cols = line.split("\t")
        if len(cols) >= 2 and cols[1]:
            words.append(cols[1])
    return words


def load_phrases(path: Path):
    return [line.strip() for line in data_lines(path)]


def load_homophone_groups(path: Path):
    groups = []
    for line in data_lines(path):
        cols = line.split("\t")
        group = []
        for i in range(0, len(cols) - 1, 2):
            if cols[i]:
                group.append((cols[i], [c for c in cols[i + 1].split(",") if c]))
        if len(group) >= 2:
            groups.append(group)
    return groups


def homophone_hit(sentence: str, groups) -> bool:
    for group in groups:
        for stem, cues in group:
            if stem not in sentence:
                continue
            # 1文字の語幹（載・乗など）はありふれているので、手がかりの語も要る
            if len(stem) >= 2 or any(cue in sentence for cue in cues):
                return True
    return False

def load_business(path: Path):
    """ビジネス文・決まった文の一覧（読み<TAB>表記）。読みに「あす」、表記に「明日」があれば「あした」の行も足す。"""
    pairs = []
    for line in data_lines(path):
        cols = line.split("\t")
        if len(cols) >= 2 and cols[0] and cols[1]:
            pairs.append((cols[0], cols[1]))
            if "明日" in cols[1] and "あす" in cols[0]:
                pairs.append((cols[0].replace("あす", "あした"), cols[1]))
    return pairs


def load_counters(path: Path):
    """数＋助数詞の型。[(助数詞, [(数の表記, [読み…])], [(前の表記, 前の読み, 後の表記, 後の読み)…])]。"""
    out = []
    for line in data_lines(path):
        cols = line.split("\t")
        if len(cols) < 3:
            continue
        numbers = []
        for item in cols[1].split(","):
            number, readings = item.split(":")
            numbers.append((number, [r for r in readings.split("/") if r]))
        frames = [tuple(part.split("|")) for part in cols[2].split(";") if part]
        frames = [f for f in frames if len(f) == 4]
        out.append((cols[0], numbers, frames))
    return out


def load_orthography(path: Path) -> dict:
    """表記をそろえる規則。{直す前: [(直した後, 品詞, 品詞の細分)…]}。"""
    rules = {}
    for line in data_lines(path):
        cols = line.split("\t")
        if len(cols) >= 2 and cols[0] and cols[1]:
            rules.setdefault(cols[0], []).append((cols[1], cols[2] if len(cols) > 2 else "",
                                                  cols[3] if len(cols) > 3 else ""))
    return rules


# 業務の連絡文の前置き（文の前に付ける）。読みはひらがな
BUSINESS_PREFIXES = [("", ""), ("", ""), ("", ""), ("拝啓、", "はいけい、"),
                     ("お世話になっております。", "おせわになっております。"),
                     ("いつもありがとうございます。", "いつもありがとうございます。"),
                     ("お疲れ様です。", "おつかれさまです。"),
                     ("お忙しいところ恐れ入ります。", "おいそがしいところおそれいります。")]

# 数の前に付ける言葉（数＋助数詞の問題の型）
COUNTER_ADVERBS = [("約", "やく"), ("およそ", "およそ"), ("合計で", "ごうけいで"), ("たった", "たった"),
                   ("ちょうど", "ちょうど"), ("全部で", "ぜんぶで")]

# 結び（文の後ろに付ける）。何も付けない形を多めに
BUSINESS_SUFFIXES = [("", ""), ("", ""), ("", ""),
                     ("よろしくお願いいたします。", "よろしくおねがいいたします。"),
                     ("ご確認をお願いいたします。", "ごかくにんをおねがいいたします。"),
                     ("どうぞよろしくお願い申し上げます。", "どうぞよろしくおねがいもうしあげます。")]

# ---------------------------------------------------------------- 読み（Sudachi）


@dataclass
class Token:
    surface: str
    reading: str
    pos0: str
    pos1: str


# 辞書が改まった読みを選びやすい語を、打つときの読みに直す（よく打つ読みが1つの語だけ）
READING_OVERRIDE = {
    "今日": "キョウ", "昨日": "キノウ", "一昨日": "オトトイ",
    "明後日": "アサッテ", "今年": "コトシ", "去年": "キョネン", "一人": "ヒトリ", "二人": "フタリ",
    "大人": "オトナ", "上手": "ジョウズ", "下手": "ヘタ", "眼鏡": "メガネ", "果物": "クダモノ",
    "時計": "トケイ", "今朝": "ケサ", "今夜": "コンヤ",
}


# 打つ読みが2通りある語。文ごとに、決まった割合で片方の読みを選ぶ（同じ文なら同じ読み）。
# 明日は「あした」だけにすると「あす」と打ったときの変換が崩れる（v4 の反省）ので、「あす」も残す。
# 日本は「にほん」を主にして、「にっぽん」も残す。割合は新聞・放送の読みと打ち方の実感による目安。
READING_VARIANTS = {
    "明日": (("アシタ", 0.65), ("アス", 0.35)),
    "日本": (("ニホン", 0.85), ("ニッポン", 0.15)),
}


class SudachiReader:
    def __init__(self, dict_name: str, seed: int = 0):
        from sudachipy import Dictionary, SplitMode
        self.dict_name = dict_name
        self.seed = seed
        self.tokenizer = Dictionary(dict=dict_name).create(SplitMode.C)

    def versions(self) -> dict:
        from importlib import metadata
        out = {}
        for name in ("sudachipy", f"sudachidict_{self.dict_name}"):
            try:
                out[name] = metadata.version(name)
            except Exception:
                out[name] = "unknown"
        return out

    def analyze(self, text: str):
        tokens = []
        for number, m in enumerate(self.tokenizer.tokenize(text)):
            pos = m.part_of_speech()
            surface = m.surface()
            if pos[0] in ("補助記号", "空白"):
                reading = surface
            elif surface in READING_VARIANTS:
                roll, reading = stable_unit(self.seed, f"reading:{text}|{number}"), None
                for candidate, share in READING_VARIANTS[surface]:
                    reading = candidate
                    roll -= share
                    if roll < 0:
                        break
            else:
                reading = READING_OVERRIDE.get(surface) or to_katakana(m.reading_form())
            if not reading or not READING_OK.match(reading):
                return None
            tokens.append(Token(surface, reading, pos[0], pos[1]))
        return tokens


def normalize_orthography(tokens, rules, share, seed, key, stats):
    """表記をそろえる。文のうち share の割合（key で決まる）で、規則に当たる語の表記を直す。
    読みは変えない。直した語の数を stats["<前>→<後>"] に足す。"""
    if not tokens or not rules or share <= 0 or stable_unit(seed, f"ortho:{key}") >= share:
        return tokens
    out = []
    for token in tokens:
        new = token
        for after, pos0, pos1 in rules.get(token.surface, ()):
            if (not pos0 or pos0 == token.pos0) and (not pos1 or pos1 == token.pos1):
                new = Token(after, token.reading, token.pos0, token.pos1)
                stats[f"{token.surface}→{after}"] = stats.get(f"{token.surface}→{after}", 0) + 1
                break
        out.append(new)
    return out


CONTENT_POS = {"名詞", "代名詞", "動詞", "形容詞", "形状詞", "副詞", "連体詞", "接続詞", "感動詞", "接頭辞"}


def bunsetsu_starts(tokens) -> list[int]:
    """文節（Mozc の区切りに近いもの）の始まりの位置。おおよそでよい。"""
    starts = [0]
    for i in range(1, len(tokens)):
        tok, prev = tokens[i], tokens[i - 1]
        if tok.pos0 not in CONTENT_POS or prev.pos0 == "接頭辞":
            continue
        if tok.pos0 == "名詞" and prev.pos0 in ("名詞", "接頭辞"):
            continue  # 会議室、午前中などの複合語
        if tok.pos0 == "動詞" and prev.pos0 == "名詞" and tok.surface in ("し", "する", "さ", "せ", "す", "でき"):
            continue  # 提出した
        if tok.pos1 == "非自立可能" and prev.surface in ("て", "で"):
            continue  # 食べている
        if prev.pos0 == "補助記号" and prev.surface in ("「", "・"):
            continue
        starts.append(i)
    return starts

# ---------------------------------------------------------------- ウィキペディア


def iter_wiki_articles(paths, seed_key: str, part: tuple = (0, 1)):
    """(題名, 本文) を、seed_key で決まる順に返す（ファイルごとに順番を決める）。
    part=(i, n) なら、並べ替えたあとの i 番目、i+n 番目… の記事だけ（n 個の工程で分けるとき）。
    parquet（wikimedia/wikipedia）か、文章ファイル（空行で記事を区切る。1行目を題名とする）。"""
    index, count = part
    for path in paths:
        path = Path(path)
        rng = random.Random(f"{seed_key}:{path.name}")
        if path.suffix == ".parquet":
            import pyarrow.parquet as pq
            table = pq.read_table(path, columns=["title", "text"])
            titles = table.column("title").to_pylist()
            texts = table.column("text").to_pylist()
            del table
            order = list(range(len(titles)))
            rng.shuffle(order)
            for i in order[index::count]:
                yield titles[i], texts[i]
        else:
            blocks = [b for b in re.split(r"\n\s*\n", path.read_text(encoding="utf-8")) if b.strip()]
            order = list(range(len(blocks)))
            rng.shuffle(order)
            for i in order[index::count]:
                lines = blocks[i].strip().split("\n")
                yield f"{path.name}:{lines[0]}", "\n".join(lines[1:]) if len(lines) > 1 else lines[0]


SENTENCE_RE = re.compile(r"[^。！？]*[。！？]")


def split_paragraphs(text: str):
    for paragraph in text.split("\n"):
        sentences = [s.strip() for s in SENTENCE_RE.findall(paragraph.strip())]
        sentences = [s for s in sentences if s]
        if sentences:
            yield sentences


def sentence_ok(sentence: str) -> bool:
    if not (8 <= len(sentence) <= 60) or not SURFACE_OK.match(sentence):
        return False
    if not re.search(r"[ぁ-ゖ]", sentence) or sentence[0] in "、。・":
        return False
    return sentence.count("「") == sentence.count("」")

# ---------------------------------------------------------------- 問題の形


def example(kind: str, reading: str, output: str, left: str = "", right: str = "") -> dict:
    return {"kind": kind, "prompt": build_prompt(to_katakana(reading), left, right), "output": model_text(output)}


def span_example(kind, tokens, start, end, before="", after=""):
    left = before + "".join(t.surface for t in tokens[:start])
    right = "".join(t.surface for t in tokens[end:]) + after
    reading = "".join(t.reading for t in tokens[start:end])
    surface = "".join(t.surface for t in tokens[start:end])
    if not re.search(r"[ぁ-ゖァ-ヺ一-鿿]", surface):
        return None
    return example(kind, reading, surface, left, right)


def random_span(tokens, rng):
    starts = bunsetsu_starts(tokens)
    bounds = starts + [len(tokens)]
    if len(starts) < 2:
        return 0, len(tokens)
    first = rng.randrange(len(starts))
    count = rng.choice((1, 1, 2, 2, 3))
    last = min(len(starts), first + count)
    if first == 0 and last == len(starts):
        last -= 1
    return bounds[first], bounds[last]


def mixed_english_example(tokens, kata_map, rng, before=""):
    """カタカナ語を英単語に置き換え、英単語で区切られた日本語の部分の1つを問題にする。"""
    spots = [i for i, t in enumerate(tokens) if t.pos0 == "名詞" and t.surface in kata_map]
    if not spots:
        return None, (None, None)
    chosen = set(rng.sample(spots, min(len(spots), rng.choice((1, 1, 2)))))
    pieces = []  # (表記, 読み or None=英単語)
    for i, t in enumerate(tokens):
        pieces.append((kata_map[t.surface], None) if i in chosen else (t.surface, t.reading))
    runs, current = [], []
    for index, (surface, reading) in enumerate(pieces):
        if reading is None:
            if current:
                runs.append(current)
            current = []
        else:
            current.append(index)
    if current:
        runs.append(current)
    runs = [r for r in runs if any(re.search(r"[ぁ-ゖァ-ヺ一-鿿]", pieces[i][0]) for i in r)]
    if not runs:
        return None, (None, None)
    run = rng.choice(runs)
    left = before + "".join(pieces[i][0] for i in range(run[0]))
    right = "".join(pieces[i][0] for i in range(run[-1] + 1, len(pieces)))
    surface = "".join(pieces[i][0] for i in run)
    reading = "".join(pieces[i][1] for i in run)
    whole = "".join(p[0] for p in pieces)
    whole_reading = "".join(p[1] if p[1] is not None else p[0] for p in pieces)
    return example("mixed_english", reading, surface, left, right), (whole, whole_reading)

# ---------------------------------------------------------------- 自作の一覧からの問題
# 型: (前の表記, 前の読み, 後の表記, 後の読み)。読みはひらがな。一般的な言い回しとして
# この台本で書いたもので、試験の文は見ていない（重なれば TestExclusion が捨てる）。

CASUAL_FRAMES = {
    "verb_end": [("", "", "", ""), ("そろそろ", "そろそろ", "", ""), ("じゃあ", "じゃあ", "", ""),
                 ("今日は", "きょうは", "", ""), ("週末は", "しゅうまつは", "", ""), ("とりあえず", "とりあえず", "", ""),
                 ("もう", "もう", "", ""), ("帰りに", "かえりに", "", ""), ("", "", "笑", "わら"),
                 ("", "", "ね", "ね"), ("", "", "よ", "よ"), ("", "", "！", "！")],
    "noun": [("", "", "", ""), ("", "", "笑", "わら"), ("", "", "だね", "だね"), ("", "", "じゃん", "じゃん"),
             ("", "", "すぎる", "すぎる")],
    "interj": [("", "", "", ""), ("", "", "！", "！"), ("", "", "笑", "わら")],
    "adj": [("", "", "", ""), ("めっちゃ", "めっちゃ", "", ""), ("マジで", "まじで", "", ""),
            ("これ", "これ", "", ""), ("", "", "笑", "わら"), ("ほんとに", "ほんとに", "", "")],
}

# 英語（略語・サービス名・言い回し）を挟む型。英語は確定済みの文節なので文脈側に入る。
WORD_FRAMES = [
    ("", "", "のアカウントを作った", "のあかうんとをつくった"),
    ("昨日", "きのう", "を入れ直した", "をいれなおした"),
    ("", "", "で資料を共有します", "でしりょうをきょうゆうします"),
    ("", "", "の使い方を教えてほしい", "のつかいかたをおしえてほしい"),
    ("", "", "が使えなくて困っている", "がつかえなくてこまっている"),
    ("", "", "について調べてみた", "についてしらべてみた"),
    ("新しい", "あたらしい", "が発表された", "がはっぴょうされた"),
    ("", "", "の設定を変更した", "のせっていをへんこうした"),
    ("会社で", "かいしゃで", "を使っています", "をつかっています"),
    ("", "", "の画面が開かない", "のがめんがひらかない"),
    ("念のため", "ねんのため", "も確認してください", "もかくにんしてください"),
    ("", "", "に登録しておいた", "にとうろくしておいた"),
    ("最近", "さいきん", "を始めました", "をはじめました"),
    ("", "", "の料金が上がるらしい", "のりょうきんがあがるらしい"),
    ("詳しくは", "くわしくは", "を見てください", "をみてください"),
    ("", "", "と連携できるか試した", "とれんけいできるかためした"),
]

PHRASE_FRAMES = [
    ("", "", "って言われた", "っていわれた"),
    ("最後に", "さいごに", "と書いておいた", "とかいておいた"),
    ("", "", "と返事をした", "とへんじをした"),
    ("みんなに", "みんなに", "と伝えた", "とつたえた"),
    ("", "", "の意味が分からない", "のいみがわからない"),
    ("先生が", "せんせいが", "と言っていた", "といっていた"),
    ("", "", "という言葉が好きです", "ということばがすきです"),
    ("カードに", "かーどに", "と書いて渡した", "とかいてわたした"),
]


def framed_examples(kind, middle_surface, middle_reading, frame, middle_is_english):
    """型に語を入れた文から問題を作る。英語の語なら前後の日本語の部分のどちらか。"""
    pre_s, pre_r, post_s, post_r = frame
    whole = pre_s + middle_surface + post_s
    if not middle_is_english:
        return [(example(kind, pre_r + middle_reading + post_r, whole), whole, [pre_r + middle_reading + post_r])]
    out = []
    key = [pre_r + middle_surface + post_r]
    if pre_s:
        out.append((example(kind, pre_r, pre_s, "", middle_surface + post_s), whole, key))
    if post_s:
        out.append((example(kind, post_r, post_s, pre_s + middle_surface, ""), whole, key))
    return out

# ---------------------------------------------------------------- 本体


class Builder:
    def __init__(self, args):
        self.args = args
        self.rng = random.Random(args.seed)
        self.repo = Path(args.repo)
        self.data_dir = self.repo / "tools" / "data"
        english_to_katakana = {}
        for name in ("katakana-english-common.tsv", "katakana-english.tsv"):
            for katakana, english in load_katakana_english(self.data_dir / name).items():
                english_to_katakana.setdefault(english.lower().replace(" ", ""), katakana)
        self.exclusion = TestExclusion(self.repo / "tests" / "conversion",
                                       load_romaji_table(Path(args.romaji_table)), english_to_katakana,
                                       extra_files=args.extra_test,
                                       ascii_containment=not (args.domain_text or args.english_only_exact))
        # 種類ごとの割合（出典の中での割合）。--kind-weights で上書きできる
        self.kind_weights = {source: dict(kinds) for source, kinds in SOURCE_KINDS.items()}
        for item in (args.kind_weights.split(",") if args.kind_weights else []):
            name, value = item.split("=")
            if name not in KIND_SOURCE:
                raise SystemExit(f"--kind-weights の種類が不明: {name}")
            self.kind_weights[KIND_SOURCE[name]][name] = float(value)
        self.mix = parse_mix(args.mix, args)
        self.max_passes = parse_passes(args.max_passes)
        if args.domain_passes is not None and "domain=" not in (args.max_passes or ""):
            self.max_passes["domain"] = max(1, args.domain_passes)
        self.part = parse_slice(args.slice)
        wanted = list(args.only_source) if args.only_source else list(self.mix)
        for name in wanted:
            if name not in self.mix:
                raise SystemExit(f"--only-source の出典 {name} が --mix にありません（割合 0 か、書かれていない）")
        self.run_sources = [name for name in SOURCE_KINDS if name in wanted]
        if self.part[1] > 1 and self.run_sources != ["wiki"]:
            raise SystemExit("--slice を使えるのは --only-source wiki のときだけです")
        self.text_groups = [name for name in self.run_sources if name in TEXT_SOURCES]
        if self.text_groups and not args.domain_text:
            raise SystemExit(f"{', '.join(self.text_groups)} の問題を作るには --domain-text（文の一覧）が要ります")
        # 予定の数（全体）と、この実行が受け持つ数
        self.planned = {}
        for source, share in self.mix.items():
            weights = self.kind_weights[source]
            total = sum(weights.values())
            size = int(round(args.size * share))
            for kind, weight in weights.items():
                self.planned[kind] = int(round(size * weight / total))
        index, count = self.part
        self.quota = {k: (v // count + (1 if index < v % count else 0) if KIND_SOURCE[k] == "wiki" else v)
                      for k, v in self.planned.items() if KIND_SOURCE[k] in self.run_sources}
        self.valid_cap = -(-args.valid_per_kind // count)
        self.train = {k: [] for k in self.quota}
        self.valid = {k: [] for k in self.quota}
        self.valid_fraction = {k: (args.domain_valid_fraction if KIND_SOURCE[k] in TEXT_SOURCES else args.valid_fraction)
                               for k in self.quota}
        self.text_per_source = {}   # 文の一覧の出典ごとの練習問題・確かめ問題の数
        self.text_items = {}
        self.text_rejected = {}
        self.text_passes_used = {}
        self.shortfall = {}         # 出典ごとの、予定より足りなかった数
        self.fill_added = 0
        self.pass_no = 1
        self.seen = set()
        self.excluded = []
        self.excluded_count = 0
        # 表記をそろえる規則（--ortho-share の割合の文に使う。0 なら使わない）
        self.ortho_share = args.ortho_share
        self.ortho_rules = load_orthography(self.data_dir / "orthography.tsv") if self.ortho_share > 0 else {}
        self.ortho_stats = {"sentences_seen": 0, "sentences_changed": 0, "words": {}}
        self.rejected ={"wiki_sentence_shape": 0, "wiki_reading": 0}
        self.wiki_stats = None
        self.reader_versions = None
        self._reader = None

    def reader(self):
        if self._reader is None:
            self._reader = SudachiReader(self.args.sudachi_dict, self.args.seed)
            self.reader_versions = self._reader.versions()
        return self._reader

    # 学習用か確かめ用かは、記事・見出し語（group）で決める
    def is_valid(self, group: str, kind: str | None = None) -> bool:
        fraction = self.valid_fraction[kind] if kind else self.args.valid_fraction
        return stable_unit(self.args.seed, group) < fraction

    def add(self, kind, record, group):
        """入れたら "train" か "valid"、入れなかったら False を返す。"""
        if record is None:
            return False
        key = hashlib.sha1((record["prompt"] + "\t" + record["output"]).encode("utf-8")).digest()
        if key in self.seen:
            return False
        if self.is_valid(group, kind):
            if len(self.valid[kind]) >= self.valid_cap:
                return False
            self.seen.add(key)
            self.valid[kind].append(record)
            return "valid"
        if len(self.train[kind]) >= self.quota[kind]:
            return False
        self.seen.add(key)
        self.train[kind].append(record)
        return "train"

    def apply_orthography(self, tokens, text):
        """表記をそろえた形態素と、その表記の文を返す（規則に当たらなければそのまま）。"""
        if not self.ortho_rules:
            return tokens, text
        self.ortho_stats["sentences_seen"] += 1
        new = normalize_orthography(tokens, self.ortho_rules, self.ortho_share, self.args.seed, text,
                                    self.ortho_stats["words"])
        if new is tokens:
            return tokens, text
        joined = "".join(t.surface for t in new)
        if joined != text:
            self.ortho_stats["sentences_changed"] += 1
        return new, joined

    def check(self, surface, readings) -> bool:
        reason = self.exclusion.blocked(surface, readings)
        if reason:
            self.excluded_count += 1
            if len(self.excluded) < 200:
                self.excluded.append(f"{surface}\t{reason}")
            return False
        return True

    def full(self, kind) -> bool:
        return len(self.train[kind]) >= self.quota[kind] and (
            len(self.valid[kind]) >= self.valid_cap or self.valid_fraction[kind] == 0)

    def is_open(self, kind) -> bool:
        """まだ問題を足せる種類か。2周目からは練習用だけ見る（確かめ用は1周目で集める）。"""
        if len(self.train[kind]) < self.quota[kind]:
            return True
        return self.pass_no == 1 and self.valid_fraction[kind] > 0 and len(self.valid[kind]) < self.valid_cap

    def note_shortfall(self, source):
        self.shortfall[source] = sum(max(0, self.quota[k] - len(self.train[k])) for k in SOURCE_KINDS[source]
                                     if k in self.quota)

    # ---- 自作の一覧
    def build_synthetic(self):
        colloquial = load_colloquial(self.data_dir / "colloquial.tsv")
        modern = load_modern_words(self.data_dir / "jaen-modern-words.tsv")
        phrases = load_phrases(self.data_dir / "english-phrases.txt")
        jobs = []
        for reading, surface, kind in colloquial:
            for frame in CASUAL_FRAMES.get(kind, CASUAL_FRAMES["noun"]):
                # 「ー」「っ」「！」などで終わる語の後ろには何も付けない（会いたいーね を作らない）
                if frame[2] and surface[-1] in "ー〜っッ！？笑":
                    continue
                jobs.append(("casual", f"casual:{reading}:{surface}", surface, reading, frame, False))
        for word in modern:
            for frame in self.rng.sample(WORD_FRAMES, 3):
                jobs.append(("modern_words", f"modern:{word}", word, "", frame, True))
        for phrase in phrases:
            for frame in PHRASE_FRAMES:
                jobs.append(("english_phrases", f"phrase:{phrase}", phrase, "", frame, True))
        self.rng.shuffle(jobs)
        for kind, group, surface, reading, frame, english in jobs:
            if self.full(kind):
                continue
            options = framed_examples(kind, surface, reading, frame, english)
            if options and self.check(options[0][1], options[0][2]):
                self.add(kind, self.rng.choice(options)[0], group)
        self.build_notation_sentences()
        self.note_shortfall("synthetic")

    def build_notation_sentences(self):
        """ビジネス文（business）と数＋助数詞（counter）。読みは一覧にあるものを使う。
        文の前置きや前後は、文全体に含める形と、左右の文脈にする形をまぜる。"""
        rng = self.rng
        jobs = []   # (種類, 振り分けの単位, 問題, 文全体の表記, 文全体の読み)
        for reading, surface in load_business(self.data_dir / "business-phrases.tsv"):
            for pre_s, pre_r in BUSINESS_PREFIXES:
                for post_s, post_r in rng.sample(BUSINESS_SUFFIXES, 2):
                    # 前置き・結びを、文に含める形と、左右の文脈にする形をまぜる
                    left, right = (pre_s, post_s) if rng.random() < 0.5 else ("", "")
                    if left or right:
                        record = example("business", reading, surface, left, right)
                    else:
                        record = example("business", pre_r + reading + post_r, pre_s + surface + post_s)
                    jobs.append(("business", f"business:{surface}", record, pre_s + surface + post_s,
                                 pre_r + reading + post_r))
        for counter, numbers, frames in load_counters(self.data_dir / "counters.tsv"):
            for number, readings in numbers:
                for number_reading in readings:
                    for pre_s, pre_r, post_s, post_r in frames:
                        # 数の前に付ける言葉（何も付けない形を含めて3つ。型の最後がすでに「約」なら付けない）
                        adverbs = [("", "")] + (rng.sample(COUNTER_ADVERBS, 2) if not pre_s.endswith("約") else [])
                        for adverb_s, adverb_r in adverbs:
                            phrase, phrase_reading = adverb_s + number + counter, adverb_r + number_reading
                            whole, whole_reading = pre_s + phrase + post_s, pre_r + phrase_reading + post_r
                            group = f"counter:{counter}:{number}:{pre_s}{post_s}"
                            # 文全体と、数＋助数詞の部分だけ（左右は文脈）の2つの形を作る
                            jobs.append(("counter", group, example("counter", whole_reading, whole), whole,
                                         whole_reading))
                            if pre_s or post_s:
                                jobs.append(("counter", group,
                                             example("counter", phrase_reading, phrase, pre_s, post_s),
                                             whole, whole_reading))
        for reading, surface in load_business(self.data_dir / "counter-phrases.tsv"):
            jobs.append(("counter", f"counter-phrase:{surface}", example("counter", reading, surface), surface, reading))
        rng.shuffle(jobs)
        for kind, group, record, whole, whole_reading in jobs:
            if self.full(kind):
                continue
            if self.check(whole, [whole_reading]):
                self.add(kind, record, group)

    # ---- ウィキペディア
    def shortfall_from_parts(self) -> int:
        """この実行で作っていないほかの出典の、足りなかった数（先に作った部品の目録から読む）。"""
        total, seen = 0, set(self.shortfall)
        for path in sorted(Path(self.args.out).glob("part-*.json")):
            fragment = json.loads(path.read_text(encoding="utf-8"))
            for source, number in (fragment.get("shortfall") or {}).items():
                if source != "wiki" and source not in seen:
                    total += number
                    seen.add(source)
        return total

    def apply_fill(self):
        """ほかの出典で足りなかった分を、ウィキペディアの文全体の問題で埋める（--no-fill-wiki で止める）。"""
        self.fill_added = 0
        if self.args.no_fill_wiki:
            return
        short = sum(n for s, n in self.shortfall.items() if s != "wiki") + self.shortfall_from_parts()
        index, count = self.part
        self.fill_added = short // count + (1 if index < short % count else 0)
        self.quota["wiki_whole"] += self.fill_added

    def build_wiki(self):
        args = self.args
        if not args.wiki:
            return
        reader = self.reader()
        kata_map = load_katakana_english(self.data_dir / "katakana-english-common.tsv")
        groups = load_homophone_groups(self.data_dir / "homophone-cues.tsv")
        self.apply_fill()
        started, articles, sentences, passes_used = time.time(), 0, 0, 0
        for pass_no in range(1, self.max_passes["wiki"] + 1):
            if all(self.full(k) for k in WIKI_KINDS):
                break
            passes_used = pass_no
            self.pass_no = pass_no
            for title, text in iter_wiki_articles(args.wiki, f"{args.seed}:wiki:{pass_no}", self.part):
                if all(self.full(k) for k in WIKI_KINDS):
                    break
                if args.max_articles and articles >= args.max_articles:
                    break
                articles += 1
                group = f"wiki:{title}"
                for paragraph in split_paragraphs(text or ""):
                    previous = ""  # 同じ段落の前の文（検査を通ったものだけ）
                    for sentence in paragraph:
                        if not sentence_ok(sentence):
                            self.rejected["wiki_sentence_shape"] += 1
                            previous = ""
                            continue
                        tokens = reader.analyze(sentence)
                        if not tokens:
                            self.rejected["wiki_reading"] += 1
                            previous = ""
                            continue
                        tokens, sentence = self.apply_orthography(tokens, sentence)
                        reading = "".join(t.reading for t in tokens)
                        if len(reading) > READING_MAX or not self.check(sentence, [reading]):
                            previous = ""
                            continue
                        if previous and self.exclusion.blocked(previous + sentence):
                            previous = ""   # 前の文とつなげると試験の文になる（句点を含む複数の文の試験）
                        sentences += 1
                        self.wiki_sentence(group, sentence, tokens, reading, previous, kata_map, groups)
                        previous = sentence
                if args.progress and articles % args.progress == 0:
                    counts = {k: len(v) for k, v in self.train.items()}
                    print(f"  記事 {articles}  文 {sentences}  {time.time() - started:.0f}秒  {counts}", flush=True)
        self.wiki_stats = {"articles": articles, "sentences_used": sentences, "passes_used": passes_used,
                           "passes_max": self.max_passes["wiki"], "seconds": round(time.time() - started),
                           "fill_added": self.fill_added, "slice": list(self.part)}
        self.note_shortfall("wiki")

    def wiki_sentence(self, group, sentence, tokens, reading, previous, kata_map, groups):
        rng = self.rng
        if not self.full("homophone") and homophone_hit(sentence, groups):
            roll = rng.random()
            if roll < 0.6:
                record = example("homophone", reading, sentence)
            elif roll < 0.8 and previous:
                record = example("homophone", reading, sentence, previous)
            else:
                start, end = random_span(tokens, rng)
                record = span_example("homophone", tokens, start, end, previous)
            if self.add("homophone", record, group):
                return
        if not self.full("mixed_english") and rng.random() < 0.6:
            record, (whole, whole_reading) = mixed_english_example(tokens, kata_map, rng, previous)
            if record and self.check(whole, [whole_reading]) and self.add("mixed_english", record, group):
                return
        open_kinds = [k for k in ("wiki_whole", "wiki_context", "wiki_span") if not self.full(k)]
        if not open_kinds:
            return
        need = [max(1, self.quota[k] - len(self.train[k])) for k in open_kinds]
        kind = rng.choices(open_kinds, weights=need)[0]
        if kind == "wiki_whole":
            self.add(kind, example(kind, reading, sentence), group)
        elif kind == "wiki_context":
            if not previous:
                self.add("wiki_whole", example("wiki_whole", reading, sentence), group)
                return
            self.add(kind, example(kind, reading, sentence, previous), group)
        else:
            start, end = random_span(tokens, rng)
            self.add(kind, span_example(kind, tokens, start, end, previous if rng.random() < 0.5 else ""), group)

    # ---- 文の一覧（分野・Tatoeba・RealPersonaChat。domain_text.py などが作る sentences.jsonl と同じ形）
    def load_text_items(self):
        """練習用の文を、日本語の部分の読みを付けた形にする。試験の文と重なるものは捨てる。
        メモリを抑えるため、形態素は持たない（文の一部の問題を作るときに、もう一度解析する）。"""
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from domain_text import pieces_of
        reader = self.reader()
        config = json.loads(Path(self.args.domain_config).read_text(encoding="utf-8"))
        group_of = {s["name"]: s.get("mix", "domain") for s in config["sources"]}
        wanted = set(self.text_groups)
        items, rejected = [], {"not_train": 0, "other_source": 0, "pieces": 0, "reading": 0, "test_overlap": 0}
        started = time.time()
        for number, line in enumerate(open(self.args.domain_text, encoding="utf-8"), 1):
            row = json.loads(line)
            if row["split"] != "train":
                rejected["not_train"] += 1
                continue
            group = group_of.get(row["source"], "domain")
            if group not in wanted:
                rejected["other_source"] += 1
                continue
            pieces = pieces_of(row["text"])
            if not pieces:
                rejected["pieces"] += 1
                continue
            units, key = [], ""
            for kind, text in pieces:
                if kind == "en":
                    units.append({"en": True, "text": text, "reading": ""})
                    key += text
                    continue
                tokens = reader.analyze(text)
                if not tokens:
                    units = None
                    break
                tokens, text = self.apply_orthography(tokens, text)
                reading = "".join(t.reading for t in tokens)
                units.append({"en": False, "text": text, "reading": reading})
                key += reading
            if units is None:
                rejected["reading"] += 1
                continue
            rewritten = "".join(u["text"] for u in units)
            if not self.check(row["text"], [key]) or (rewritten != row["text"] and not self.check(rewritten, [key])):
                rejected["test_overlap"] += 1
                continue
            prev = row.get("prev", "")
            if prev:
                prev_pieces = pieces_of(prev)
                if (not prev_pieces or not self.check(prev, [""])
                        or self.exclusion.blocked(prev + row["text"])):  # つなげると試験の文になる場合も
                    prev = ""
            items.append({"group": group, "source": row["source"], "doc": row["doc"], "text": row["text"],
                          "prev": prev, "units": units, "has_english": any(u["en"] for u in units)})
            if self.args.progress and number % (self.args.progress * 20) == 0:
                print(f"  文の読み付け {number} 行  使える {len(items)}  {time.time() - started:.0f}秒", flush=True)
        self.text_rejected = rejected
        return items

    def text_run_example(self, kind, item, index, span, use_prev):
        """日本語の部分（units[index]）を問う問題。ほかの部分（英字を含む）は左右の文脈に入れる。"""
        units = item["units"]
        unit = units[index]
        before = (item["prev"] if use_prev else "") + "".join(u["text"] for u in units[:index])
        after = "".join(u["text"] for u in units[index + 1:])
        if span:
            tokens = self.reader().analyze(unit["text"])
            if not tokens:
                return None
            start, end = random_span(tokens, self.rng)
            left = before + "".join(t.surface for t in tokens[:start])
            right = "".join(t.surface for t in tokens[end:]) + after
            reading = "".join(t.reading for t in tokens[start:end])
            surface = "".join(t.surface for t in tokens[start:end])
        else:
            left, right, reading, surface = before, after, unit["reading"], unit["text"]
        if not reading or len(reading) > READING_MAX or not re.search(r"[ぁ-ゖァ-ヺ一-鿿]", surface):
            return None
        return example(kind, reading, surface, left, right)

    def text_sentence(self, item):
        rng = self.rng
        group = item["group"]
        units = item["units"]
        english = f"{group}_english"
        open_kinds = [k for k in SOURCE_KINDS[group] if self.is_open(k)]
        if not open_kinds:
            return
        runs = [i for i, u in enumerate(units) if not u["en"] and re.search(r"[ぁ-ゖァ-ヺ一-鿿]", u["text"])]
        if not runs:
            return
        used = item.setdefault("used", set())
        if item["has_english"]:
            if english not in open_kinds:
                return
            kind = english
            record = self.text_run_example(kind, item, rng.choice(runs), rng.random() < 0.3,
                                           bool(item["prev"]) and rng.random() < 0.3)
        else:
            # 文全体・前の文つきの問題は、同じ文から2つ作っても同じ問題になるので1回だけ。文の一部は毎回違う所を選ぶ
            kinds = [k for k in open_kinds if k != english and not (k in used and not k.endswith("_span"))]
            if not kinds:
                return
            need = [max(1, self.quota[k] - len(self.train[k])) for k in kinds]
            kind = rng.choices(kinds, weights=need)[0]
            if kind.endswith("_context") and not item["prev"]:
                kind = f"{group}_whole"
                if kind not in kinds:
                    return
            record = self.text_run_example(kind, item, runs[0], kind.endswith("_span"), kind.endswith("_context"))
        if record is not None:
            used.add(kind)
        where = self.add(kind, record, f"{group}:{item['source']}:{item['doc']}")
        if where:
            counts = self.text_per_source.setdefault(item["source"], {"train": 0, "valid": 0})
            counts[where] += 1

    def group_open(self, group) -> bool:
        return any(self.is_open(k) for k in SOURCE_KINDS[group])

    def build_text(self):
        if not self.text_groups:
            return
        started = time.time()
        items = self.load_text_items()
        self.text_items = {g: sum(1 for it in items if it["group"] == g) for g in self.text_groups}
        print(f"文の一覧から使える練習用の文 {self.text_items}（読み付けと試験の文の検査に {time.time() - started:.0f} 秒）",
              flush=True)
        self.text_passes_used = {g: 0 for g in self.text_groups}
        for pass_no in range(1, max(self.max_passes[g] for g in self.text_groups) + 1):
            self.pass_no = pass_no
            active = [g for g in self.text_groups if pass_no <= self.max_passes[g] and self.group_open(g)]
            if not active:
                break
            for g in active:
                self.text_passes_used[g] = pass_no
            order = list(range(len(items)))
            self.rng.shuffle(order)
            for i in order:
                if items[i]["group"] in active:
                    self.text_sentence(items[i])
            print(f"  {pass_no} 周目が終わりました: " +
                  str({g: sum(len(self.train[k]) for k in SOURCE_KINDS[g]) for g in self.text_groups}), flush=True)
        for g in self.text_groups:
            self.note_shortfall(g)

    def run(self):
        if "synthetic" in self.run_sources:
            self.build_synthetic()
        self.build_text()
        if "wiki" in self.run_sources:
            self.build_wiki()

    # ---- 書き出し
    def write_files(self, name):
        """name が None なら train.jsonl・valid.jsonl（昔の形）、あるなら部品 train-<name>.jsonl.gz など。"""
        out = Path(self.args.out)
        out.mkdir(parents=True, exist_ok=True)
        train = [r for kind in self.train for r in self.train[kind]]
        valid = [r for kind in self.valid for r in self.valid[kind]]
        self.rng.shuffle(train)
        suffix = "" if name is None else f"-{name}"
        train_file = write_jsonl(out / ("train.jsonl" if name is None else f"train{suffix}.jsonl.gz"), train)
        valid_file = write_jsonl(out / f"valid{suffix}.jsonl", valid)
        (out / f"excluded{suffix}.txt").write_text("\n".join(self.excluded) + "\n", encoding="utf-8")
        fragment = self.fragment(name or "all", train_file, valid_file)
        if name is not None:
            (out / f"part-{name}.json").write_text(json.dumps(fragment, ensure_ascii=False, indent=2) + "\n",
                                                   encoding="utf-8")
        return fragment

    def fragment(self, name, train_file, valid_file):
        """この実行で分かったこと（部品の目録）。assemble_manifest が集めて manifest.json にする。"""
        args = self.args
        own = "このリポジトリ（compound-ime）で作成した一覧。MIT ライセンス（リポジトリの LICENSE）。"
        sources = [
            {"name": "tools/data/colloquial.tsv", "use": "話し言葉の語と読み", "license": own},
            {"name": "tools/data/katakana-english-common.tsv", "use": "カタカナ語を英単語に置き換える対応", "license": own},
            {"name": "tools/data/jaen-modern-words.tsv", "use": "文脈に入れる略語・サービス名（表示の形）", "license": own},
            {"name": "tools/data/english-phrases.txt", "use": "文脈に入れる英語の言い回し", "license": own},
            {"name": "tools/data/homophone-cues.tsv", "use": "同音異義語を含む文を多めに選ぶ目印", "license": own},
            {"name": "tools/data/business-phrases.tsv", "use": "ビジネス文（business）の文", "license": own},
            {"name": "tools/data/counters.tsv", "use": "数＋助数詞（counter）の読みと文の型", "license": own},
            {"name": "tools/data/counter-phrases.tsv", "use": "数＋助数詞・いっぱいの書き分けの決まった文（counter）", "license": own},
        ]
        if self.ortho_share > 0:
            sources.append({"name": "tools/data/orthography.tsv", "use": "表記をそろえる規則（新聞・公用文の表記）", "license": own})
        for source in sources:
            source["sha256"] = sha256_file(self.repo / source["name"])
        for path in (args.wiki if "wiki" in self.run_sources else []):
            sources.append({
                "name": Path(path).name, "sha256": sha256_file(Path(path)),
                "use": "文と前後の文（読みは SudachiPy で付ける）",
                "license": "ウィキペディア日本語版の本文。CC BY-SA（記事の著者に帰属）。"
                           "wikimedia/wikipedia のデータセットは CC BY-SA 3.0 と GFDL と表示。"
                           "学習した模型を配る場合は出典（ウィキペディア）を示し、同じ条件で配る。",
            })
        domain = None
        if self.text_groups:
            config_path = Path(args.domain_config)
            config = json.loads(config_path.read_text(encoding="utf-8"))
            sentences_path = Path(args.domain_text)
            counts_path = sentences_path.with_name("counts.json")
            extraction = json.loads(counts_path.read_text(encoding="utf-8")) if counts_path.exists() else {}
            text_sources = []
            for source in config["sources"]:
                group = source.get("mix", "domain")
                if group not in self.text_groups:
                    continue
                per = self.text_per_source.get(source["name"], {"train": 0, "valid": 0})
                found = (extraction.get("sources") or {}).get(source["name"])
                if source.get("counts_file") and (sentences_path.with_name(source["counts_file"])).exists():
                    found = json.loads(sentences_path.with_name(source["counts_file"]).read_text(encoding="utf-8"))
                entry = {
                    "name": f"{source['title']}（{source['repo']}）", "id": source["name"], "mix": group,
                    "domain": source.get("domain"), "commit": source["commit"], "license": source["license"],
                    "license_url": source["license_url"], "attribution": source["attribution"],
                    "terms": source.get("terms"),
                    "use": source.get("use", "文書から取り出した日本語の文（読みは SudachiPy で付ける）。試験用の文書と別の文書だけ"),
                    "extraction": found, "train_examples": per["train"], "valid_examples": per["valid"],
                }
                text_sources.append(entry)
                sources.append({k: entry[k] for k in ("name", "commit", "license", "license_url", "use")})
            domain = {
                "sentences_file": {"name": sentences_path.name, "sha256": sha256_file(sentences_path)},
                "config": {"name": config_path.name, "sha256": sha256_file(config_path)},
                "domain_text_sha256": sha256_file(Path(__file__).resolve().with_name("domain_text.py")),
                "valid_fraction": args.domain_valid_fraction,
                "groups": list(self.text_groups),
                "kind_weights": {g: self.kind_weights[g] for g in self.text_groups},
                "quota": {k: self.quota[k] for g in self.text_groups for k in SOURCE_KINDS[g]},
                "passes_used": self.text_passes_used,
                "passes_max": {g: self.max_passes[g] for g in self.text_groups},
                "train_sentences_usable": self.text_items,
                "rejected": self.text_rejected,
                "extra_test_files": [{"name": str(p), "sha256": sha256_file(Path(p))}
                                     for p in args.extra_test if Path(p).exists()],
                "sources": text_sources,
            }
        sources.append({"name": Path(args.romaji_table).name, "sha256": sha256_file(Path(args.romaji_table)),
                        "use": "試験の文のローマ字をかなにする（除外の検査だけに使う）",
                        "license": "Mozc の romanji-hiragana.tsv（BSD-3-Clause）"})
        return {
            "name": name, "sources_run": list(self.run_sources), "slice": list(self.part),
            "made_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "settings": {"size": args.size, "seed": args.seed, "valid_fraction": args.valid_fraction,
                         "valid_per_kind": args.valid_per_kind, "mix": {k: round(v, 6) for k, v in self.mix.items()},
                         "kind_weights": self.kind_weights, "max_passes": self.max_passes,
                         "fill_wiki": not args.no_fill_wiki, "sudachi_dict": args.sudachi_dict,
                         "max_articles": args.max_articles, "ortho_share": args.ortho_share},
            "planned": self.planned, "quota_final": self.quota,
            "train_by_kind": {k: len(v) for k, v in self.train.items()},
            "valid_by_kind": {k: len(v) for k, v in self.valid.items()},
            "shortfall": self.shortfall, "fill_added": self.fill_added,
            "wiki": self.wiki_stats, "domain": domain, "rejected": self.rejected,
            "orthography": {"share": self.ortho_share, **self.ortho_stats} if self.ortho_rules else None,
            "excluded_sentences": self.excluded_count, "reader": self.reader_versions,
            "exclusion": {"files": [{"name": p.name, "sha256": sha256_file(p)} for p in self.exclusion.files],
                          "keys": self.exclusion.stats},
            "sources": sources, "files": {"train": train_file, "valid": valid_file},
        }


# ---------------------------------------------------------------- 書き出しの部品と、部品の集め方


def write_jsonl(path: Path, records) -> dict:
    """1行1問で書く（.gz なら同じ中身から同じバイト列ができるよう、時刻を 0 にして圧縮する）。"""
    path = Path(path)
    count = 0
    if path.suffix == ".gz":
        import gzip
        import io
        with open(path, "wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=6) as packed:
                with io.TextIOWrapper(packed, encoding="utf-8", newline="\n") as handle:
                    for record in records:
                        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                        count += 1
    else:
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                count += 1
    return {"name": path.name, "lines": count, "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def add_counts(total: dict, part: dict):
    for key, value in (part or {}).items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            total[key] = total.get(key, 0) + value
        elif isinstance(value, dict):
            add_counts(total.setdefault(key, {}), value)
    return total


def assemble_manifest(fragments: list, repo: Path, script: Path) -> dict:
    """部品の目録（1つ以上）から manifest.json の中身を作る。"""
    commit = None
    try:
        import subprocess
        commit = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True,
                                text=True, check=True).stdout.strip()
    except Exception:
        pass
    first = fragments[0]
    train_by_kind, valid_by_kind, planned, rejected = {}, {}, {}, {}
    wiki, domain, sources, ortho = None, None, {}, None
    for fragment in fragments:
        if fragment.get("orthography"):
            ortho = add_counts(ortho or {}, {k: v for k, v in fragment["orthography"].items() if k != "share"})
            ortho["share"] = fragment["orthography"]["share"]
        add_counts(train_by_kind, fragment["train_by_kind"])
        add_counts(valid_by_kind, fragment["valid_by_kind"])
        planned.update(fragment["planned"])
        add_counts(rejected, fragment["rejected"])
        if fragment.get("wiki"):
            wiki = add_counts(wiki or {}, {k: v for k, v in fragment["wiki"].items() if k != "slice"})
            wiki.setdefault("slices", []).append(fragment["wiki"]["slice"])
            wiki["passes_used"] = max(wiki.get("passes_used", 0), fragment["wiki"]["passes_used"])
            wiki["passes_max"] = fragment["wiki"]["passes_max"]
        if fragment.get("domain"):
            if domain is None:
                domain = fragment["domain"]
            else:
                domain["sources"] += fragment["domain"]["sources"]
        for source in fragment["sources"]:
            sources.setdefault(source["name"], source)
    n_train, n_valid = sum(train_by_kind.values()), sum(valid_by_kind.values())
    fill = sum(f.get("fill_added", 0) for f in fragments)
    shortfall = {}
    for fragment in fragments:
        for source, number in fragment["shortfall"].items():
            shortfall[source] = shortfall.get(source, 0) + number
    mix_result = {}
    for source, share in first["settings"]["mix"].items():
        want = sum(planned.get(k, 0) for k in SOURCE_KINDS[source])
        got = sum(train_by_kind.get(k, 0) for k in SOURCE_KINDS[source])
        mix_result[source] = {
            "share_planned": share, "train_planned": want, "train": got,
            "share_actual": round(got / n_train, 4) if n_train else 0,
            "short": shortfall.get(source, 0) if source != "wiki" else max(0, want + fill - got),
            "fill_added": fill if source == "wiki" else 0,
            "built": any(source in f["sources_run"] for f in fragments),
        }
    return {
        "made_by": "tools/zenz-finetune/build_dataset.py",
        "script_sha256": sha256_file(script),
        "repo_commit": commit,
        "made_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "settings": first["settings"],
        "format": {"prompt": "[U+EE02 左の文脈][U+EE07 右の文脈]U+EE00 読み(カタカナ) U+EE01",
                   "output": "表記（空白は U+3000）。文の終わりの記号は学習の側で付ける",
                   "context_max": CONTEXT_MAX, "reading_max": READING_MAX},
        "reader": first["reader"] or next((f["reader"] for f in fragments if f["reader"]), None),
        "counts": {"train": n_train, "valid": n_valid, "train_by_kind": train_by_kind, "valid_by_kind": valid_by_kind},
        "mix_result": mix_result,
        "train_files": [f["files"]["train"] for f in fragments],
        "valid_files": [f["files"]["valid"] for f in fragments],
        "wiki": wiki,
        "domain": domain,
        "orthography": ortho,
        "rejected": rejected,
        "test_exclusion": {
            "rule": "tests/conversion/ の文と、表記または読みが同じか、それを含む文は使わない"
                    f"（含むの検査は表記{TestExclusion.SURFACE_MIN}文字以上・読み{TestExclusion.READING_MIN}文字以上の文）",
            "files": first["exclusion"]["files"],
            "keys": first["exclusion"]["keys"],
            "excluded_sentences": sum(f["excluded_sentences"] for f in fragments),
        },
        "sources": list(sources.values()),
    }


def merge_parts(out: Path, repo: Path, script: Path) -> dict:
    """部品（part-*.json）を集めて、valid.jsonl・excluded.txt・manifest.json を作る。学習用は部品のまま使う。"""
    fragments = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(out.glob("part-*.json"))]
    if not fragments:
        raise SystemExit(f"{out} に part-*.json がありません")
    seen = {}
    for fragment in fragments:
        for source in fragment["sources_run"]:
            if source in seen and source != "wiki":
                raise SystemExit(f"出典 {source} が部品 {seen[source]} と {fragment['name']} の両方にあります")
            seen.setdefault(source, fragment["name"])
    with open(out / "valid.jsonl", "w", encoding="utf-8", newline="\n") as handle:
        for fragment in fragments:
            handle.write((out / fragment["files"]["valid"]["name"]).read_text(encoding="utf-8"))
    with open(out / "excluded.txt", "w", encoding="utf-8", newline="\n") as handle:
        for fragment in fragments:
            path = out / f"excluded-{fragment['name']}.txt"
            if path.exists():
                handle.write(path.read_text(encoding="utf-8"))
    manifest = assemble_manifest(fragments, repo, script)
    manifest["valid_merged"] = {"name": "valid.jsonl", "sha256": sha256_file(out / "valid.jsonl")}
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def print_summary(manifest: dict):
    counts = manifest["counts"]
    print(f"学習用 {counts['train']} 問、確かめ用 {counts['valid']} 問、試験と重なり除いた文 "
          f"{manifest['test_exclusion']['excluded_sentences']}")
    print("種類ごと（学習用）:", counts["train_by_kind"])
    for source, row in manifest["mix_result"].items():
        print(f"  {source}: 予定 {row['share_planned']:.1%}（{row['train_planned']} 問）→ 実際 {row['share_actual']:.1%}"
              f"（{row['train']} 問）、足りない {row['short']}" + (f"、ほかの出典の不足を {row['fill_added']} 問足した" if row["fill_added"] else ""))
    if manifest.get("orthography"):
        ortho = manifest["orthography"]
        print(f"表記をそろえた文: {ortho.get('sentences_changed', 0)} / 見た文 {ortho.get('sentences_seen', 0)}"
              f"（割合 {ortho['share']}）  直した語:", ortho.get("words", {}))
    if manifest.get("domain"):
        print("文の一覧の出典ごと（練習用・確かめ用）:",
              {s["id"]: (s["train_examples"], s["valid_examples"]) for s in manifest["domain"]["sources"]})
        print("使える練習用の文:", manifest["domain"]["train_sentences_usable"],
              " 使った周回:", manifest["domain"]["passes_used"])


def main(argv=None):
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", required=True, help="出力先のフォルダ")
    parser.add_argument("--repo", default=str(here.parent.parent), help="compound-ime のリポジトリ（tools/data と tests/conversion を読む）")
    parser.add_argument("--romaji-table", default="", help="Mozc の src/data/preedit/romanji-hiragana.tsv（--merge-parts 以外では必要）")
    parser.add_argument("--wiki", nargs="*", default=[], help="wikimedia/wikipedia の parquet（複数でよい）か文章ファイル")
    parser.add_argument("--size", type=int, default=400000, help="学習用の問題の数（全部の出典の合計）")
    parser.add_argument("--seed", type=int, default=20261015)
    parser.add_argument("--mix", default="",
                        help="出典ごとの割合 例: wiki=0.55,tatoeba=0.1,persona=0.15,domain=0.12,synthetic=0.08"
                             f"（出典は {', '.join(SOURCE_KINDS)}。合計は自動で 1 にそろえる）。付けないと昔の指定（--domain-share）")
    parser.add_argument("--max-passes", default="",
                        help="出典ごとに、同じ文から作る問題の形の数の上限 例: wiki=2,tatoeba=3,persona=3,domain=3"
                             f"（既定 {DEFAULT_MAX_PASSES}）。材料が足りないときだけ、この回数まで文を使い回す")
    parser.add_argument("--kind-weights", default="", help="出典の中の種類ごとの割合の上書き 例: wiki_whole=0.4,casual=0.05")
    parser.add_argument("--ortho-share", type=float, default=0.0,
                        help="表記を新聞・公用文にそろえる文の割合（0 はそろえない。規則は tools/data/orthography.tsv、方針は README）。"
                             "ウィキペディアと文の一覧（雑談・分野・Tatoeba）の文に使う")
    parser.add_argument("--only-source", nargs="*", default=[], help="この出典だけ作る（部品ごとに作るとき）")
    parser.add_argument("--part", default="", help="部品の名前。付けると train-<名前>.jsonl.gz などに分けて書く（切れても続けられる）")
    parser.add_argument("--slice", default="", help="ウィキペディアを n 個の工程で分けるときの i/n（0 始まり。例 0/2 と 1/2）。--only-source wiki だけ")
    parser.add_argument("--merge-parts", action="store_true", help="--out の部品を集めて valid.jsonl と manifest.json を作る")
    parser.add_argument("--no-fill-wiki", action="store_true", help="ほかの出典で足りなかった分を、ウィキペディアで埋めない")
    parser.add_argument("--valid-fraction", type=float, default=0.02, help="確かめ用に回す記事・見出し語の割合")
    parser.add_argument("--valid-per-kind", type=int, default=500, help="確かめ用の種類ごとの上限")
    parser.add_argument("--sudachi-dict", default="core", help="SudachiDict の種類（core / small / full）")
    parser.add_argument("--max-articles", type=int, default=0, help="読む記事の上限（0 は上限なし）")
    parser.add_argument("--progress", type=int, default=2000, help="何記事ごとに進み具合を出すか（0 は出さない）")
    parser.add_argument("--show", type=int, default=0, help="終わりに各種類の例をいくつ表示するか")
    parser.add_argument("--english-only-exact", action="store_true",
                        help="英字だけの試験の語（github など）は「同じ」だけ調べ、「含む」は調べない（--domain-text を付けたときと同じ。"
                             "文の一覧を渡さないウィキペディアの部品を、ほかの部品と同じ規則にするため）")
    parser.add_argument("--domain-text", default="", help="文の一覧 sentences.jsonl（分野・Tatoeba・RealPersonaChat の文。出典は domain_sources.json の mix で振り分ける）")
    parser.add_argument("--domain-share", type=float, default=0.5, help="（--mix なしのとき）--size のうち分野の問題にする割合（残りはウィキペディアなど）")
    parser.add_argument("--domain-valid-fraction", type=float, default=0.05, help="確かめ用に回す文の一覧の文書の割合")
    parser.add_argument("--domain-passes", type=int, default=None, help="（古い指定）--max-passes domain=N と同じ")
    parser.add_argument("--domain-config", default=str(here / "domain_sources.json"), help="文の出どころ（版・利用条件）の一覧")
    parser.add_argument("--extra-test", nargs="*", default=[],
                        help="リポジトリの tests/conversion にまだない試験のファイル（作った直後の domain-*.tsv など）。その文も除く")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    script = Path(__file__).resolve()

    if args.merge_parts:
        manifest = merge_parts(Path(args.out), Path(args.repo), script)
        print_summary(manifest)
        return 0
    if not args.romaji_table:
        raise SystemExit("--romaji-table が要ります")
    builder = Builder(args)
    print("試験の文の目印:", builder.exclusion.stats, flush=True)
    print("出典の割合:", {k: round(v, 4) for k, v in builder.mix.items()}, " 作る出典:", builder.run_sources,
          " 周回の上限:", {k: v for k, v in builder.max_passes.items() if k in builder.run_sources}, flush=True)
    started = time.time()
    builder.run()
    fragment = builder.write_files(args.part or None)
    print(f"作るのにかかった時間 {time.time() - started:.0f} 秒")
    if not args.part:
        manifest = assemble_manifest([fragment], Path(args.repo), script)
        (Path(args.out) / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                                       encoding="utf-8")
        print_summary(manifest)
    else:
        print(f"部品 {args.part}: 学習用 {fragment['files']['train']['lines']} 問、確かめ用 {fragment['files']['valid']['lines']} 問、"
              f"足りない {fragment['shortfall']}")
        print("全部の部品がそろったら --merge-parts で集めてください")
    short = {k: q - len(builder.train[k]) for k, q in builder.quota.items() if len(builder.train[k]) < q}
    if short:
        print("予定より少ない種類（材料が足りない）:", short)
    if args.show:
        for kind, records in builder.train.items():
            for record in records[:args.show]:
                print(kind, json.dumps(record, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
