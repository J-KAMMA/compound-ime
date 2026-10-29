"""tools/misconversions_to_tests.py の試験（Mozc なし）。"""
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import misconversions_to_tests as m  # noqa: E402

LOG = (
    "# 時刻\t種類\tローマ字\t読み\t出た変換\t選んでいた文節\t直前の文\n"
    "2026-10-29T10:00:00\tcommit\tkisyanokisya\tきしゃのきしゃ\t記者の記者\t\t昨日\n"
    "2026-10-29T10:01:00\tconvert\tkisyanokisya\tきしゃのきしゃ\t記者の記者\t記者\t\n"  # 同じもの
    "2026-10-29T10:02:00\tconvert\tkousei\tこうせい\t構成\t構成\t文の\n"
    "2026-10-29T10:03:00\tcommit\t\tかな\t仮名\t\t\n"  # かな入力（ローマ字なし）
    "2026-10-29T10:04:00\tcommit\tx\tx\t\t\t\n"  # 出た変換なし
    "\n"
    "壊れた行\n"
)


def main():
    failures = []
    rows = m.to_rows(m.read_records(LOG.splitlines(keepends=True)))
    want = ["kisyanokisya\t\t記者の記者", "kousei\t\t構成", "かな\t\t仮名"]
    if rows != want:
        failures.append(f"rows: {rows!r}（{want!r} のはず）")
    rows = m.to_rows(m.read_records(LOG.splitlines(keepends=True)), with_context=True)
    if rows[0] != "kisyanokisya\t\t記者の記者\t昨日":
        failures.append(f"context: {rows[0]!r}")
    with tempfile.TemporaryDirectory() as tmp:
        src, out = Path(tmp) / "misconversions.tsv", Path(tmp) / "draft.tsv"
        src.write_text(LOG, encoding="utf-8", newline="\n")
        if m.main([str(src), "-o", str(out)]) != 0:
            failures.append("main が失敗した")
        lines = out.read_text(encoding="utf-8").splitlines()
        data = [l for l in lines if not l.startswith("#")]
        if data != want:
            failures.append(f"file: {data!r}")
        if m.main([str(Path(tmp) / "none.tsv")]) != 1:
            failures.append("ないファイルで 1 を返さない")
    for f in failures:
        print("FAIL", f)
    print(f"misconversions_to_tests: {'ok' if not failures else 'ng'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
