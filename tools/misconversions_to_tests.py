"""Ctrl+Shift+F12 の記録（misconversions.tsv、docs/miss-report.md）を、試験の表の下書きにする。

  python tools/misconversions_to_tests.py [misconversions.tsv] [-o 下書き.tsv] [--context]

出す列: ローマ字<TAB>期待<TAB>出た変換（--context で4列目に直前の文）。
「期待」は空のまま出すので、利用者が正しい変換を書き込む。書き込んだ行だけを試験に使う。
同じローマ字・同じ出た変換の行は1つにまとめる（最初のものを残す）。ローマ字が空なら読みを使う。
ファイルを指定しなければ、この PC の既定の場所を読む:
  ウィンドウズ: %USERPROFILE%\\AppData\\LocalLow\\CompoundIME\\misconversions.tsv
  マック:       ~/Library/Application Support/CompoundIME/misconversions.tsv
  Linux:        ~/.config/compound-ime/misconversions.tsv
"""
import argparse
import os
import sys
from pathlib import Path

# 記録の列（native/jaen-detector/miss_report.h の FormatMissLine と同じ順）
COLUMNS = ("time", "kind", "romaji", "reading", "shown", "selected", "context")
KIND_LABEL = {"commit": "確定のあと", "convert": "変換中", "compose": "入力中"}


def default_path():
    if sys.platform == "win32":
        return Path(os.environ.get("USERPROFILE", "~")) / "AppData/LocalLow/CompoundIME/misconversions.tsv"
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/CompoundIME/misconversions.tsv"
    return Path.home() / ".config/compound-ime/misconversions.tsv"


def read_records(lines):
    """記録の行を dict にする。# の行・空行・列の足りない行は読み飛ばす。"""
    for line in lines:
        line = line.rstrip("\r\n")
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) < len(COLUMNS):
            fields += [""] * (len(COLUMNS) - len(fields))
        record = dict(zip(COLUMNS, fields))
        if not record["shown"] or not (record["romaji"] or record["reading"]):
            continue
        yield record


def to_rows(records, with_context=False):
    """試験の表の行（タブ区切り）にする。同じローマ字と出た変換は1行。"""
    seen = set()
    rows = []
    for r in records:
        typed = r["romaji"] or r["reading"]
        key = (typed, r["shown"])
        if key in seen:
            continue
        seen.add(key)
        row = [typed, "", r["shown"]]
        if with_context:
            row.append(r["context"])
        rows.append("\t".join(row))
    return rows


def header(with_context):
    cols = "ローマ字<TAB>期待<TAB>出た変換" + ("<TAB>直前の文" if with_context else "")
    return [
        "# 利用者が Ctrl+Shift+F12 で記録した「違う変換」の下書き（tools/misconversions_to_tests.py）。",
        f"# 列: {cols}。期待の欄に正しい変換を書き込み、書いた行だけを試験に使う。",
        "# 打った文がそのまま入っている。公開の試験の表に入れる前に、個人の情報がないか見ること。",
    ]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", nargs="?", type=Path, help="misconversions.tsv（省略時はこの PC の既定の場所）")
    ap.add_argument("-o", "--output", type=Path, help="書き出す先（省略時は画面）")
    ap.add_argument("--context", action="store_true", help="4列目に直前の文を付ける")
    args = ap.parse_args(argv)
    path = args.input or default_path()
    if not path.exists():
        print(f"記録がない: {path}", file=sys.stderr)
        return 1
    with open(path, encoding="utf-8", errors="replace") as f:
        rows = to_rows(read_records(f), args.context)
    text = "\n".join(header(args.context) + rows) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8", newline="\n")
        print(f"{len(rows)} 行 → {args.output}", file=sys.stderr)
    else:
        sys.stdout.buffer.write(text.encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
