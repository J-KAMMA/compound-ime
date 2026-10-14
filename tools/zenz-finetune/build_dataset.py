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
jaen200b.json、typo150*.json、reported.json、inputs.txt、variants.tsv、
expected-windows-139.tsv）の文と、表記または読みが同じか、それを含む文は、
問題にする前に捨てる（TestExclusion）。文脈に使う前後の文も同じ検査を通ったものだけ。

読みの付け方: ウィキペディアの文は SudachiPy（Apache-2.0）と SudachiDict
（Apache-2.0）で読みを付ける。自作の一覧（tools/data/）は一覧にある読みを使う。
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
}
SYNTHETIC_KINDS = ("casual", "modern_words", "english_phrases")
WIKI_KINDS = ("wiki_whole", "wiki_context", "wiki_span", "homophone", "mixed_english")

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

    def __init__(self, test_dir: Path, romaji_table: dict, english_to_katakana=None):
        english_to_katakana = english_to_katakana or {}
        self.files = []
        surfaces, readings = set(), set()

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

        for path in sorted(test_dir.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            items = data["items"] if isinstance(data, dict) else data
            for item in items:
                for text in [item.get("intended", "")] + list(item.get("alternatives", []) or []):
                    if text:
                        surfaces.add(norm_surface(text))
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
        for name, column in (("variants.tsv", 3), ("expected-windows-139.tsv", 2)):
            path = test_dir / name
            if not path.exists():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                cols = line.split("\t")
                if len(cols) > column and cols[column]:
                    surfaces.add(norm_surface(cols[column]))
                if name == "variants.tsv" and len(cols) > 4 and cols[4]:
                    for alt in cols[4].split("|"):
                        surfaces.add(norm_surface(alt))
            self.files.append(path)
        known = {p.name for p in self.files}
        for path in sorted(test_dir.iterdir()):
            if path.is_file() and path.name not in known and path.suffix in (".txt", ".tsv"):
                # 新しく足された試験のファイルも、1行目の列をローマ字として扱う
                for line in path.read_text(encoding="utf-8").splitlines():
                    first = line.split("\t")[0].strip()
                    if re.fullmatch(r"[a-z\-']+", first or ""):
                        add_reading(first)
                self.files.append(path)
        surfaces.discard("")
        readings.discard("")
        self.surface_exact = surfaces
        self.reading_exact = readings
        self.surface_index = SubstringIndex(s for s in surfaces if len(s) >= self.SURFACE_MIN)
        self.reading_index = SubstringIndex(r for r in readings if len(r) >= self.READING_MIN)
        self.stats = {
            "surface_keys": len(surfaces),
            "surface_keys_checked_by_containment": sum(len(s) >= self.SURFACE_MIN for s in surfaces),
            "reading_keys": len(readings),
            "reading_keys_checked_by_containment": sum(len(r) >= self.READING_MIN for r in readings),
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

# ---------------------------------------------------------------- 読み（Sudachi）


@dataclass
class Token:
    surface: str
    reading: str
    pos0: str
    pos1: str


# 辞書が改まった読みを選びやすい語を、打つときの読みに直す（よく打つ読みが1つの語だけ）
READING_OVERRIDE = {
    "明日": "アシタ", "日本": "ニホン", "今日": "キョウ", "昨日": "キノウ", "一昨日": "オトトイ",
    "明後日": "アサッテ", "今年": "コトシ", "去年": "キョネン", "一人": "ヒトリ", "二人": "フタリ",
    "大人": "オトナ", "上手": "ジョウズ", "下手": "ヘタ", "眼鏡": "メガネ", "果物": "クダモノ",
    "時計": "トケイ", "今朝": "ケサ", "今夜": "コンヤ",
}


class SudachiReader:
    def __init__(self, dict_name: str):
        from sudachipy import Dictionary, SplitMode
        self.dict_name = dict_name
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
        for m in self.tokenizer.tokenize(text):
            pos = m.part_of_speech()
            surface = m.surface()
            if pos[0] in ("補助記号", "空白"):
                reading = surface
            else:
                reading = READING_OVERRIDE.get(surface) or to_katakana(m.reading_form())
            if not reading or not READING_OK.match(reading):
                return None
            tokens.append(Token(surface, reading, pos[0], pos[1]))
        return tokens


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


def iter_wiki_articles(paths, rng: random.Random):
    """(題名, 本文) を、seed で決まる順に返す。parquet（wikimedia/wikipedia）か、
    文章ファイル（空行で記事を区切る。1行目を題名とする）。"""
    for path in paths:
        path = Path(path)
        if path.suffix == ".parquet":
            import pyarrow.parquet as pq
            table = pq.read_table(path, columns=["title", "text"])
            titles = table.column("title").to_pylist()
            texts = table.column("text").to_pylist()
            order = list(range(len(titles)))
            rng.shuffle(order)
            for i in order:
                yield titles[i], texts[i]
        else:
            blocks = [b for b in re.split(r"\n\s*\n", path.read_text(encoding="utf-8")) if b.strip()]
            order = list(range(len(blocks)))
            rng.shuffle(order)
            for i in order:
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
                                       load_romaji_table(Path(args.romaji_table)), english_to_katakana)
        self.weights = dict(DEFAULT_WEIGHTS)
        for item in (args.mix.split(",") if args.mix else []):
            name, value = item.split("=")
            if name not in self.weights:
                raise SystemExit(f"--mix の種類が不明: {name}")
            self.weights[name] = float(value)
        total = sum(self.weights.values())
        self.quota = {k: int(round(args.size * v / total)) for k, v in self.weights.items()}
        self.train = {k: [] for k in self.weights}
        self.valid = {k: [] for k in self.weights}
        self.seen = set()
        self.excluded = []
        self.excluded_count = 0
        self.rejected = {"wiki_sentence_shape": 0, "wiki_reading": 0}

    # 学習用か確かめ用かは、記事・見出し語（group）で決める
    def is_valid(self, group: str) -> bool:
        return stable_unit(self.args.seed, group) < self.args.valid_fraction

    def add(self, kind, record, group):
        if record is None:
            return False
        key = hashlib.sha1((record["prompt"] + "\t" + record["output"]).encode("utf-8")).digest()
        if key in self.seen:
            return False
        if self.is_valid(group):
            if len(self.valid[kind]) >= self.args.valid_per_kind:
                return False
            self.seen.add(key)
            self.valid[kind].append(record)
            return True
        if len(self.train[kind]) >= self.quota[kind]:
            return False
        self.seen.add(key)
        self.train[kind].append(record)
        return True

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
            len(self.valid[kind]) >= self.args.valid_per_kind or self.args.valid_fraction == 0)

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

    # ---- ウィキペディア
    def build_wiki(self):
        args = self.args
        if not args.wiki:
            return
        reader = SudachiReader(args.sudachi_dict)
        self.reader_versions = reader.versions()
        kata_map = load_katakana_english(self.data_dir / "katakana-english-common.tsv")
        groups = load_homophone_groups(self.data_dir / "homophone-cues.tsv")
        # 自作の一覧で埋まらなかった分は文全体の問題で埋める
        for kind in SYNTHETIC_KINDS:
            self.quota["wiki_whole"] += max(0, self.quota[kind] - len(self.train[kind]))
            self.quota[kind] = len(self.train[kind])
        started, articles, sentences = time.time(), 0, 0
        for title, text in iter_wiki_articles(args.wiki, self.rng):
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
                    reading = "".join(t.reading for t in tokens)
                    if len(reading) > READING_MAX or not self.check(sentence, [reading]):
                        previous = ""
                        continue
                    sentences += 1
                    self.wiki_sentence(group, sentence, tokens, reading, previous, kata_map, groups)
                    previous = sentence
            if args.progress and articles % args.progress == 0:
                counts = {k: len(v) for k, v in self.train.items()}
                print(f"  記事 {articles}  文 {sentences}  {time.time() - started:.0f}秒  {counts}", flush=True)
        self.wiki_stats = {"articles": articles, "sentences_used": sentences}

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

    def write(self):
        out = Path(self.args.out)
        out.mkdir(parents=True, exist_ok=True)
        train = [r for kind in self.train for r in self.train[kind]]
        valid = [r for kind in self.valid for r in self.valid[kind]]
        self.rng.shuffle(train)
        for name, records in (("train.jsonl", train), ("valid.jsonl", valid)):
            with open(out / name, "w", encoding="utf-8", newline="\n") as handle:
                for record in records:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        (out / "excluded.txt").write_text("\n".join(self.excluded) + "\n", encoding="utf-8")
        self.write_manifest(out, len(train), len(valid))
        return train, valid

    def write_manifest(self, out, n_train, n_valid):
        args = self.args
        script = Path(__file__).resolve()
        commit = None
        try:
            import subprocess
            commit = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD"], capture_output=True,
                                    text=True, check=True).stdout.strip()
        except Exception:
            pass
        own = "このリポジトリ（compound-ime）で作成した一覧。MIT ライセンス（リポジトリの LICENSE）。"
        sources = [
            {"name": "tools/data/colloquial.tsv", "use": "話し言葉の語と読み", "license": own},
            {"name": "tools/data/katakana-english-common.tsv", "use": "カタカナ語を英単語に置き換える対応", "license": own},
            {"name": "tools/data/jaen-modern-words.tsv", "use": "文脈に入れる略語・サービス名（表示の形）", "license": own},
            {"name": "tools/data/english-phrases.txt", "use": "文脈に入れる英語の言い回し", "license": own},
            {"name": "tools/data/homophone-cues.tsv", "use": "同音異義語を含む文を多めに選ぶ目印", "license": own},
        ]
        for source in sources:
            path = self.repo / source["name"]
            source["sha256"] = sha256_file(path)
        for path in args.wiki or []:
            sources.append({
                "name": str(path), "sha256": sha256_file(Path(path)),
                "use": "文と前後の文（読みは SudachiPy で付ける）",
                "license": "ウィキペディア日本語版の本文。CC BY-SA（記事の著者に帰属）。"
                           "wikimedia/wikipedia のデータセットは CC BY-SA 3.0 と GFDL と表示。"
                           "学習した模型を配る場合は出典（ウィキペディア）を示し、同じ条件で配る。",
            })
        sources.append({"name": args.romaji_table, "sha256": sha256_file(Path(args.romaji_table)),
                        "use": "試験の文のローマ字をかなにする（除外の検査だけに使う）",
                        "license": "Mozc の romanji-hiragana.tsv（BSD-3-Clause）"})
        manifest = {
            "made_by": "tools/zenz-finetune/build_dataset.py",
            "script_sha256": sha256_file(script),
            "repo_commit": commit,
            "made_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "settings": {"size": args.size, "seed": args.seed, "valid_fraction": args.valid_fraction,
                         "valid_per_kind": args.valid_per_kind, "weights": self.weights, "quota": self.quota,
                         "sudachi_dict": args.sudachi_dict, "max_articles": args.max_articles},
            "format": {"prompt": "[U+EE02 左の文脈][U+EE07 右の文脈]U+EE00 読み(カタカナ) U+EE01",
                       "output": "表記（空白は U+3000）。文の終わりの記号は学習の側で付ける",
                       "context_max": CONTEXT_MAX, "reading_max": READING_MAX},
            "reader": getattr(self, "reader_versions", None),
            "counts": {"train": n_train, "valid": n_valid,
                       "train_by_kind": {k: len(v) for k, v in self.train.items()},
                       "valid_by_kind": {k: len(v) for k, v in self.valid.items()}},
            "wiki": getattr(self, "wiki_stats", None),
            "rejected": self.rejected,
            "test_exclusion": {
                "rule": "tests/conversion/ の文と、表記または読みが同じか、それを含む文は使わない"
                        f"（含むの検査は表記{TestExclusion.SURFACE_MIN}文字以上・読み{TestExclusion.READING_MIN}文字以上の文）",
                "files": [{"name": p.name, "sha256": sha256_file(p)} for p in self.exclusion.files],
                "keys": self.exclusion.stats,
                "excluded_sentences": self.excluded_count,
            },
            "sources": sources,
        }
        (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv=None):
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", required=True, help="出力先のフォルダ")
    parser.add_argument("--repo", default=str(here.parent.parent), help="compound-ime のリポジトリ（tools/data と tests/conversion を読む）")
    parser.add_argument("--romaji-table", required=True, help="Mozc の src/data/preedit/romanji-hiragana.tsv")
    parser.add_argument("--wiki", nargs="*", default=[], help="wikimedia/wikipedia の parquet か文章ファイル")
    parser.add_argument("--size", type=int, default=400000, help="学習用の問題の数")
    parser.add_argument("--seed", type=int, default=20261015)
    parser.add_argument("--mix", default="", help="種類ごとの割合の上書き 例: wiki_whole=0.4,casual=0.05")
    parser.add_argument("--valid-fraction", type=float, default=0.02, help="確かめ用に回す記事・見出し語の割合")
    parser.add_argument("--valid-per-kind", type=int, default=500, help="確かめ用の種類ごとの上限")
    parser.add_argument("--sudachi-dict", default="core", help="SudachiDict の種類（core / small / full）")
    parser.add_argument("--max-articles", type=int, default=0, help="読む記事の上限（0 は上限なし）")
    parser.add_argument("--progress", type=int, default=2000, help="何記事ごとに進み具合を出すか（0 は出さない）")
    parser.add_argument("--show", type=int, default=0, help="終わりに各種類の例をいくつ表示するか")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    builder = Builder(args)
    print("試験の文の目印:", builder.exclusion.stats, flush=True)
    builder.build_synthetic()
    builder.build_wiki()
    train, valid = builder.write()
    print(f"学習用 {len(train)} 問、確かめ用 {len(valid)} 問、試験と重なり除いた文 {builder.excluded_count}")
    print("種類ごと（学習用）:", {k: len(v) for k, v in builder.train.items()})
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
