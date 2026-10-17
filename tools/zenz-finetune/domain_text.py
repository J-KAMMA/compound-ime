#!/usr/bin/env python3
"""プログラミングと仮想通貨の文書から、日本語の文を取り出す。

  python domain_text.py --config domain_sources.json --src-root src --out out [--seed 20261015]

材料（domain_sources.json に版を固定して書いてある文書の集まり）を --src-root/<名前>/ に
取り出してあるものとして、文書ごとに次を行う。

  1. 書式を除く: md の前置き（front matter）、コードの囲み、表、HTML、リンクの書式、
     マクロ（MDN の {{ }}、Kubernetes の {{< >}}、mdbook の {{#include}}）、見出し。
     po（Python 文書の日本語訳）は訳文（msgstr）だけを使い、未訳・fuzzy・原文のままは除く。
  2. 句点（。！？）で文に分ける。
  3. 文を選ぶ: 日本語の割合が低い文、短すぎる/長すぎる文、使えない記号を含む文、
     重複した文を除く。英字の言葉（git、npm、Python など）は文の中に残す。
  4. 文書の単位で「試験用」と「練習用」に分ける（同じ文書の文が両方に入らない。
     試験用の文書にある文は、ほかの文書にあっても練習用に入れない）。

できるもの（--out の中）:
  sentences.jsonl  1行1文: {"source", "doc", "split": "test" か "train", "text", "prev"}
                   prev は同じ段落の前の文（選ばれたものだけ）
  counts.json      出典ごとの文書の数・文の数・除いた理由ごとの数
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import unicodedata
from pathlib import Path

SENTINEL = ""  # 使えない書式が残った印。この文字を含む文は捨てる

JA_CHARS = "ぁ-ゖァ-ヺー一-鿿々〆ヶ、。「」・！？"
JA_LETTERS = "ぁ-ゖァ-ヺー一-鿿々〆ヶ"
EN_WORD = r"[A-Za-z0-9][A-Za-z0-9._+#/'-]*"
EN_TOKEN = rf"{EN_WORD}(?: {EN_WORD})*"
PIECE_RE = re.compile(rf"(?P<ja>[{JA_CHARS}]+)|(?P<en>{EN_TOKEN})")
JA_RE = re.compile(rf"[{JA_CHARS}]")
JA_LETTER_RE = re.compile(rf"[{JA_LETTERS}]")
SIMPLE_EN = re.compile(rf"{EN_TOKEN}")
SENTENCE_RE = re.compile(r"[^。！？]*[。！？]+[」』]?")
ASCII_PAREN = re.compile(r"\s*\([A-Za-z0-9 .,_/+#:'\"-]*\)")


# ---------------------------------------------------------------- 文の形

def normalize_text(text: str) -> str:
    """NFKC にそろえ、日本語の隣の空白を消す。ASCII の ! ? は全角に戻す。"""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("!", "！").replace("?", "？")
    text = ASCII_PAREN.sub("", text)
    text = re.sub(rf"\s+(?=[{JA_CHARS}])", "", text)
    text = re.sub(rf"(?<=[{JA_CHARS}])\s+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def pieces_of(sentence: str):
    """文を [("ja", 日本語の部分) か ("en", 英字の部分), ...] に分ける。分けられない文は None。"""
    out, pos = [], 0
    for m in PIECE_RE.finditer(sentence):
        if m.start() != pos:
            return None
        out.append(("ja", m.group("ja")) if m.group("ja") else ("en", m.group("en")))
        pos = m.end()
    if pos != len(sentence) or not out:
        return None
    return out


def sentence_reject_reason(sentence: str, min_len: int, max_len: int, min_ja_ratio: float, max_english: int):
    """使えない理由（使えるなら None）。"""
    if SENTINEL in sentence:
        return "format_left"
    if not (min_len <= len(sentence) <= max_len):
        return "length"
    if sentence[0] in "、。・」』！？" or not re.search(r"[ぁ-ゖ]", sentence):
        return "shape"
    if sentence.count("「") != sentence.count("」") or sentence.count("『") != sentence.count("』"):
        return "quote"
    pieces = pieces_of(sentence)
    if pieces is None:
        return "symbols"
    if sum(1 for kind, _ in pieces if kind == "en") > max_english:
        return "too_many_english"
    letters = len(JA_LETTER_RE.findall(sentence))
    if letters / max(1, len(sentence.replace(" ", ""))) < min_ja_ratio:
        return "ja_ratio"
    return None


# ---------------------------------------------------------------- 書式を除く（共通）

def plain_term(text: str) -> str:
    """コードや用語の中身。英字の言葉か日本語の言葉ならそのまま、そうでなければ印を返す。"""
    text = text.strip().lstrip("~!.")
    if text.endswith("()"):
        text = text[:-2]
    if not text or len(text) > 40:
        return SENTINEL
    if SIMPLE_EN.fullmatch(text) and re.search(r"[A-Za-z]", text):
        return text
    if re.fullmatch(rf"[{JA_LETTERS}]+", text):
        return text
    return SENTINEL


def inline_code(text: str) -> str:
    def repl(m):
        return plain_term(m.group(1) if m.group(1) is not None else m.group(2))
    return re.sub(r"``(.+?)``|`([^`\n]+)`", repl, text)


def strip_front_matter(text: str) -> str:
    for mark in ("---", "+++"):
        if text.startswith(mark):
            m = re.match(rf"{re.escape(mark)}[ \t]*\n.*?\n{re.escape(mark)}[ \t]*(?:\n|$)", text, re.S)
            if m:
                return text[m.end():]
    return text


def remove_fences(lines):
    """コードの囲み（``` と ~~~）の中身を空行にする。"""
    out, marker = [], None
    for line in lines:
        s = line.strip()
        if marker is None:
            m = re.match(r"(`{3,}|~{3,})", s)
            if m:
                marker = m.group(1)
                out.append("")
                continue
            out.append(line)
        else:
            if re.fullmatch(re.escape(marker[0]) + "{" + str(len(marker)) + r",}", s):
                marker = None
            out.append("")
    return out


TEXT_MACROS = {"jsxref", "domxref", "htmlelement", "cssxref", "glossary", "httpheader", "httpmethod",
               "httpstatus", "svgelement", "svgattr", "htmlattrxref", "event", "webextapi", "webextmanifest"}
HUGO_BLOCKS = {"note", "caution", "warning", "tabs", "tab", "alert", "feature-state", "heading", "details"}


def replace_macro(m) -> str:
    body = m.group(1).strip()
    if body[:1] in "<%":  # Hugo のショートコード {{< ... >}}、{{% ... %}}
        inner = body.strip("<>%").strip()
        name = inner.lstrip("/").split(None, 1)[0].lower() if inner.lstrip("/") else ""
        if name == "glossary_tooltip":
            t = re.search(r'text="([^"]*)"', inner)
            return plain_term(t.group(1)) if t else SENTINEL
        return "\n\n" if name in HUGO_BLOCKS else SENTINEL
    parsed = re.fullmatch(r"([\w:.-]+)\s*(?:\((.*)\))?", body, re.S)
    if not parsed:
        return SENTINEL
    name, args = parsed.group(1).lower(), parsed.group(2)
    if args is None:
        return ""  # {{optional_inline}} など
    if name in TEXT_MACROS:
        strings = re.findall(r'"([^"]*)"|\'([^\']*)\'', args)
        strings = [a or b for a, b in strings]
        if strings:
            return plain_term(strings[1] if len(strings) > 1 and strings[1] else strings[0])
    return SENTINEL


def drop_macro_lines(text: str) -> str:
    return re.sub(r"^[ \t]*\{\{(?:(?!\}\}).)*\}\}[ \t]*$", "", text, flags=re.M | re.S)


def clean_inline(text: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    for _ in range(3):
        text = re.sub(r"\[([^\[\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\[\]]+)\]\[[^\]]*\]", r"\1", text)
    text = re.sub(r"\[\^[^\]]+\]", "", text)
    text = re.sub(r"\{[#.:][^}]*\}", "", text)
    text = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m.group(1) or m.group(2), text)
    text = re.sub(r"(?<![\w*])\*([^*\s][^*]*?)\*(?![\w*])", r"\1", text)
    text = re.sub(r"~~(.+?)~~", r"\1", text)
    return text


LIST_RE = re.compile(r"\s*(?:[-*+]|\d+[.)])\s+")


def assemble_blocks(lines):
    """行を段落（箇条書きの1項目は1段落）にまとめる。"""
    blocks, cur = [], []

    def flush():
        if cur:
            blocks.append(" ".join(cur))
        cur.clear()

    for line in lines:
        s = line.rstrip()
        if not s.strip():
            flush()
            continue
        s = re.sub(r"^\s*(?:>\s?)+", "", s)
        s = re.sub(r"^\[![A-Za-z]+\]\s*", "", s.strip())
        if not s.strip():
            flush()
            continue
        m = LIST_RE.match(s)
        if m or re.match(r"\s*:\s", s):
            flush()
            s = s[m.end():] if m else re.sub(r"^\s*:\s+", "", s)
            s = re.sub(r"^:\s+", "", s)
        cur.append(s.strip())
    flush()
    return blocks


# ---------------------------------------------------------------- md / mdx

def markdown_blocks(text: str):
    text = strip_front_matter(text.replace("\r\n", "\n"))
    text = "\n".join(remove_fences(text.split("\n")))
    text = re.sub(r"<!--.*?-->", "\n\n", text, flags=re.S)
    text = re.sub(r"<(pre|script|style|table|svg|iframe|video|math)\b.*?</\1\s*>", "\n\n", text, flags=re.S | re.I)
    text = drop_macro_lines(text)
    text = re.sub(r"\{\{(.*?)\}\}", replace_macro, text, flags=re.S)
    text = re.sub(r"<code>(.*?)</code>", r"`\1`", text, flags=re.S | re.I)
    text = inline_code(text)
    text = re.sub(r"<[A-Za-z/!][^<>]*>", "", text, flags=re.S)
    text = html.unescape(text).replace("\xa0", " ")
    lines = []
    for line in text.split("\n"):
        s = line.strip()
        if (re.match(r"#{1,6}(\s|$)", s) or s.startswith("|") or re.fullmatch(r"[-*_=\s]{3,}", s)
                or re.match(r"\[[^\]]+\]:\s*\S+", s) or re.match(r"[-=]{2,}\s*$", s)):
            lines.append("")
            continue
        lines.append(clean_inline(line))
    return assemble_blocks(lines)


# ---------------------------------------------------------------- po

def parse_po(text: str):
    """訳された項目の訳文（msgstr）を返す。fuzzy・未訳・原文のままのものは返さない。"""
    entries = []

    def unquote(s):
        s = s.strip()
        if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
            try:
                return json.loads(s)
            except ValueError:
                return s[1:-1]
        return ""

    for chunk in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        flags, msgid, msgstr, field = "", [], [], None
        for line in chunk.split("\n"):
            if line.startswith("#,"):
                flags += line
            elif line.startswith("msgctxt"):
                field = "ctx"
            elif line.startswith("msgid "):
                msgid, field = [unquote(line[6:])], "id"
            elif line.startswith("msgstr "):
                msgstr, field = [unquote(line[7:])], "str"
            elif line.startswith('"') and field in ("id", "str"):
                (msgid if field == "id" else msgstr).append(unquote(line))
        a, b = "".join(msgid), "".join(msgstr)
        if a and b and "fuzzy" not in flags and a != b:
            entries.append(b)
    return entries


ROLE_RE = re.compile(r":(?:[a-z]+:)?([a-z]+):`([^`]+)`")


def rest_role(m) -> str:
    if m.group(1) in ("pep", "rfc", "issue", "gh", "cve", "bpo", "source"):
        return SENTINEL
    content = m.group(2)
    t = re.match(r"(.*?)\s*<(.+)>\s*$", content, re.S)
    title = (t.group(1) or t.group(2)) if t else content
    return plain_term(title)


def po_blocks(text: str):
    blocks = []
    for msgstr in parse_po(text):
        if re.match(r"\s*\.\. ", msgstr) or ">>>" in msgstr:
            continue
        s = msgstr.replace("\r", "")
        s = ROLE_RE.sub(rest_role, s)
        s = re.sub(r"`([^`<]+?)\s*<[^>]+>`_{1,2}", r"\1", s)
        s = inline_code(s)
        s = clean_inline(s)
        s = html.unescape(s)
        blocks.extend(assemble_blocks(s.split("\n")))
    return blocks


def blocks_of(text: str, fmt: str):
    return po_blocks(text) if fmt == "po" else markdown_blocks(text)


# ---------------------------------------------------------------- 抽出

def stable_unit(seed: int, key: str) -> float:
    value = hashlib.sha256(f"{seed}\t{key}".encode("utf-8")).digest()
    return int.from_bytes(value[:8], "big") / 2**64


def sentence_key(sentence: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", sentence)).lower()


def doc_sentences(text: str, fmt: str, args, reasons):
    """1つの文書から、選ばれた文を段落ごとに返す: [[文, ...], ...]。"""
    out = []
    for block in blocks_of(text, fmt):
        kept, previous = [], ""
        for raw in SENTENCE_RE.findall(normalize_text(block)):
            sentence = raw.strip()
            if not sentence:
                continue
            reasons["raw_sentences"] = reasons.get("raw_sentences", 0) + 1
            why = sentence_reject_reason(sentence, args.min_len, args.max_len, args.min_ja_ratio, args.max_english)
            if why:
                reasons[why] = reasons.get(why, 0) + 1
                previous = ""
                continue
            kept.append((sentence, previous))
            previous = sentence
        if kept:
            out.append(kept)
    return out


def main(argv=None):
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(here / "domain_sources.json"))
    ap.add_argument("--src-root", required=True, help="材料を取り出した場所（<名前>/ の下に文書）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=20261015)
    ap.add_argument("--min-len", type=int, default=10)
    ap.add_argument("--max-len", type=int, default=80)
    ap.add_argument("--min-ja-ratio", type=float, default=0.6, help="日本語の文字の割合の下限")
    ap.add_argument("--max-english", type=int, default=5, help="1文に入る英字の言葉の数の上限")
    ap.add_argument("--only", nargs="*", default=[], help="この名前の出典だけ（試し用）")
    ap.add_argument("--max-docs", type=int, default=0, help="出典ごとの文書の上限（試し用、0 は上限なし）")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    seen, test_keys = set(), set()
    records, counts = [], {}
    for source in config["sources"]:
        name = source["name"]
        if source.get("kind") == "external":
            continue  # git の文書ではない出典（Tatoeba など）。tools/colloquial_text.py が別に文を取り出す
        if args.only and name not in args.only:
            continue
        base = Path(args.src_root) / name
        root = base / source.get("root", "")
        fmt = source["format"]
        files = sorted(p for p in root.glob(source["glob"]) if p.is_file()
                       and not any(part in source.get("exclude", []) for part in p.relative_to(root).parts))
        if args.max_docs:
            files = files[:args.max_docs]
        stat = {"docs": len(files), "docs_test": 0, "docs_with_sentences": 0, "kept": 0, "kept_test": 0,
                "kept_train": 0, "kept_with_english": 0, "duplicate": 0, "leak_to_test": 0, "reject": {}}
        per_doc = []
        for path in files:
            doc = path.relative_to(root).as_posix()
            split = "test" if stable_unit(args.seed, f"{name}:{doc}") < source["test_doc_fraction"] else "train"
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                stat["reject"]["unreadable_doc"] = stat["reject"].get("unreadable_doc", 0) + 1
                continue
            stat["docs_test"] += split == "test"
            blocks = doc_sentences(text, fmt, args, stat["reject"])
            if blocks:
                stat["docs_with_sentences"] += 1
            per_doc.append((doc, split, blocks))
        # 試験用の文書の文を先に決め、練習用はそれと重ならないものだけにする
        for phase in ("test", "train"):
            for doc, split, blocks in per_doc:
                if split != phase:
                    continue
                for kept in blocks:
                    previous_ok = ""
                    for sentence, previous in kept:
                        key = sentence_key(sentence)
                        if key in seen:
                            stat["duplicate"] += 1
                            previous_ok = ""
                            continue
                        if phase == "train" and key in test_keys:
                            stat["leak_to_test"] += 1
                            previous_ok = ""
                            continue
                        seen.add(key)
                        if phase == "test":
                            test_keys.add(key)
                        stat["kept"] += 1
                        stat["kept_" + phase] += 1
                        stat["kept_with_english"] += any(k == "en" for k, _ in pieces_of(sentence))
                        records.append({"source": name, "doc": doc, "split": phase, "text": sentence,
                                        "prev": previous if previous and previous == previous_ok else ""})
                        previous_ok = sentence
        # 重複で前の文が落ちた場合に備え、prev は直前に採用した文のときだけ残す
        counts[name] = stat
        print(f"{name}: 文書 {stat['docs']}（試験用 {stat['docs_test']}）、採用 {stat['kept']}"
              f"（試験用 {stat['kept_test']}、練習用 {stat['kept_train']}、英字入り {stat['kept_with_english']}）", flush=True)
    with open(out / "sentences.jsonl", "w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    summary = {"settings": {"seed": args.seed, "min_len": args.min_len, "max_len": args.max_len,
                            "min_ja_ratio": args.min_ja_ratio, "max_english": args.max_english},
               "sources": counts, "total": len(records)}
    (out / "counts.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"合計 {len(records)} 文")
    return 0


if __name__ == "__main__":
    sys.exit(main())
