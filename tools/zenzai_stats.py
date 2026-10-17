"""zenzai_stats.py <結果のフォルダー> [--glob 名前の型] [--exclude 除く名前の頭] [--label 名前]

試験の各処理が書いた「人工知能の上限」の集計（*.zstats.<処理番号>）を足し合わせて、1行で出す。
各ファイルは1つの処理の最後の状態（変換のたびに上書き）:
  conversions=変換の数 hits=上限に当たった変換の数 aborts=計算の途中で打ち切った数
  skips=評価に入る前に見送った数 total_ms=変換にかかった時間の合計 max_ms=1回の最長
（tools/apply_zenzai_deadline.py が足す MYIME_ZENZAI_STATS_FILE）
"""
import re
import sys
from pathlib import Path


def collect(folder, pattern="*.zstats.*", exclude=None):
    total = dict(conversions=0, hits=0, aborts=0, skips=0, total_ms=0, max_ms=0)
    files = 0
    for path in sorted(Path(folder).glob(pattern)):
        if exclude and path.name.startswith(exclude):
            continue
        fields = dict(re.findall(r"(\w+)=(\d+)", path.read_text(encoding="utf-8", errors="replace")))
        if "conversions" not in fields:
            continue
        files += 1
        for key in ("conversions", "hits", "aborts", "skips", "total_ms"):
            total[key] += int(fields.get(key, 0))
        total["max_ms"] = max(total["max_ms"], int(fields.get("max_ms", 0)))
    return files, total


def describe(files, t, label=""):
    if not files:
        return f"{label}人工知能の上限: 集計なし"
    mean = t["total_ms"] / t["conversions"] if t["conversions"] else 0
    rate = 100 * t["hits"] / t["conversions"] if t["conversions"] else 0
    return (f"{label}人工知能の上限: 変換 {t['conversions']} 回のうち、上限に当たったのは {t['hits']} 回（{rate:.2f}%）、"
            f"計算の途中で打ち切り {t['aborts']} 回、評価の前に見送り {t['skips']} 回、"
            f"1回の平均 {mean:.0f} ミリ秒、最長 {t['max_ms']} ミリ秒（処理 {files} 個）")


if __name__ == "__main__":
    folder = sys.argv[1]
    label = sys.argv[sys.argv.index("--label") + 1] + ": " if "--label" in sys.argv else ""
    pattern = sys.argv[sys.argv.index("--glob") + 1] if "--glob" in sys.argv else "*.zstats.*"
    exclude = sys.argv[sys.argv.index("--exclude") + 1] if "--exclude" in sys.argv else None
    print(describe(*collect(folder, pattern, exclude), label=label))
