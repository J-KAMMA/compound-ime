"""Decodes the C escapes of Mozc's text-format output in a TSV result file.

  python tools/protobuf_text_unescape.py <file.tsv> [<file.tsv> ...]

session_handler_main prints protobuf messages with Utf8Format, which escapes an
apostrophe as \\' (Macy's -> Macy\\'s), a double quote as \\" and a backslash as
\\\\.  The real input method shows the original text, so the tests must compare
the decoded text.  Only the escapes that text format writes are handled; a
backslash before any other character is kept as it is.

The file is rewritten in place (the tool is idempotent for decoded text).
"""
import sys
from pathlib import Path

ESCAPES = {"n": "\n", "r": "\r", "t": "\t", "\\": "\\", '"': '"', "'": "'",
           "a": "\a", "b": "\b", "f": "\f", "v": "\v", "?": "?"}


def unescape(value):
    out = []
    i = 0
    while i < len(value):
        c = value[i]
        if c != "\\" or i + 1 >= len(value):
            out.append(c)
            i += 1
            continue
        nxt = value[i + 1]
        if nxt in ESCAPES:
            out.append(ESCAPES[nxt])
            i += 2
            continue
        if nxt in "01234567":
            digits = value[i + 1:i + 4]
            end = 0
            while end < len(digits) and digits[end] in "01234567":
                end += 1
            out.append(chr(int(digits[:end], 8)))
            i += 1 + end
            continue
        if nxt == "x" and i + 3 < len(value):
            try:
                out.append(chr(int(value[i + 2:i + 4], 16)))
                i += 4
                continue
            except ValueError:
                pass
        out.append(c)
        i += 1
    return "".join(out)


def rewrite(path):
    text = Path(path).read_text(encoding="utf-8")
    lines = []
    for line in text.splitlines(keepends=True):
        body = line[:-1] if line.endswith("\n") else line
        lines.append("\t".join(unescape(field) for field in body.split("\t")) + ("\n" if line.endswith("\n") else ""))
    Path(path).write_text("".join(lines), encoding="utf-8", newline="")


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    for path in sys.argv[1:]:
        rewrite(path)


if __name__ == "__main__":
    main()
