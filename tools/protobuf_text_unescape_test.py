"""Tests tools/protobuf_text_unescape.py (Macy's and other apostrophes)."""
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import protobuf_text_unescape as ptu  # noqa: E402


def main():
    failures = []
    cases = {
        r"Macy\'s": "Macy's",
        r"macy\'s": "macy's",
        r"MACY\'S": "MACY'S",
        r"say \"hi\"": 'say "hi"',
        r"a\\b": "a\\b",
        "plain": "plain",
    }
    for got, want in cases.items():
        value = ptu.unescape(got)
        if value != want:
            failures.append(f"{got!r} -> {value!r}（{want!r} のはず）")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "result.tsv"
        path.write_text("meishi-zu\tMacy\\'s\tmacy\\'s\n", encoding="utf-8")
        ptu.rewrite(path)
        if path.read_text(encoding="utf-8") != "meishi-zu\tMacy's\tmacy's\n":
            failures.append("TSV の引用符を戻していない")
    print("\n".join(failures) if failures else "OK 引用符を戻す試験")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
