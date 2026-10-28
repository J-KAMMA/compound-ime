"""文の頭・途中・終わりに置いた英字の語が、英語のまま出るかの試験の文を作る。

  python tools/make_english_mid_tests.py > tests/conversion/english-mid.tsv

語は tools/data/jaen-modern-words.tsv（略語・製品名など）から決まった間隔で選ぶ。日本語の部分は
下の型で、語の前の助詞（を・は・が・に・で・と・も・の）と位置を変える。報告（arXiv の前が
「を」のとき英語にならなかった）を1件ずつ直すのでなく、同じ種類の外れをまとめて数えるためのもの。
形式: ローマ字<TAB>表示する形（英字の語）<TAB>型の名前
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", newline="\n")
WORDS = Path(__file__).resolve().parent / "data/jaen-modern-words.tsv"
TEMPLATES = [
    ("head", "{w}deshirabeta"),
    ("wo", "korewo{w}deshirabeta"),
    ("ha", "kinouha{w}wotsukatta"),
    ("ga", "korega{w}desu"),
    ("ni", "kaishani{w}gaaru"),
    ("de", "sorede{w}wotsukau"),
    ("to", "tomodachito{w}wotsukatta"),
    ("mo", "watashimo{w}wotsukau"),
    ("no", "honno{w}wosagasu"),
    ("tail", "tsukattanoha{w}"),
]

rows = [line.split("\t") for line in WORDS.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")]
rows = [(typed, shown) for typed, shown, *_ in rows if typed.isascii() and typed.isalpha() and len(typed) >= 3]
picked = rows[:: max(1, len(rows) // 150)][:150]
print("# 英字の語（tools/data/jaen-modern-words.tsv）を型に入れた文。tools/make_english_mid_tests.py で作成。"
      "ローマ字<TAB>表示する形<TAB>型")
for typed, shown in picked:
    for name, template in TEMPLATES:
        print(f"{template.format(w=typed)}\t{shown}\t{name}")
