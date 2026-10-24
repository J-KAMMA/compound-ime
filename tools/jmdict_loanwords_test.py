"""Tests tools/build_jmdict_loanwords.py with a small JMdict entry set (no network).

  python tools/jmdict_loanwords_test.py
"""
import gzip
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
XML = '''<?xml version="1.0" encoding="UTF-8"?>
<JMdict>
<entry><k_ele><keb>コーヒー</keb></k_ele><r_ele><reb>コーヒー</reb></r_ele>
 <sense><lsource xml:lang="eng">coffee</lsource><gloss>coffee</gloss></sense></entry>
<entry><k_ele><keb>スマートフォン</keb></k_ele><r_ele><reb>スマートフォン</reb></r_ele>
 <sense><lsource xml:lang="eng">smartphone</lsource><gloss>smartphone</gloss></sense></entry>
<entry><k_ele><keb>コンピューター</keb></k_ele><r_ele><reb>コンピューター</reb></r_ele>
 <sense><gloss>computer</gloss></sense></entry>
<entry><k_ele><keb>マンション</keb></k_ele><r_ele><reb>マンション</reb></r_ele>
 <sense><lsource xml:lang="eng" ls_wasei="y">mansion</lsource><gloss>condominium</gloss></sense></entry>
<entry><k_ele><keb>サラリーマン</keb></k_ele><r_ele><reb>サラリーマン</reb></r_ele>
 <sense><lsource xml:lang="eng" ls_wasei="y">salaryman</lsource><gloss>office worker</gloss></sense></entry>
<entry><r_ele><reb>アイアニング</reb></r_ele>
 <sense><gloss>ironing</gloss></sense></entry>
<entry><r_ele><reb>アイアン</reb><re_pri>gai2</re_pri></r_ele>
 <sense><gloss>iron</gloss></sense></entry>
<entry><r_ele><reb>アイウエオ</reb></r_ele><r_ele><reb>あいうえお</reb></r_ele>
 <sense><gloss>kana</gloss></sense></entry>
</JMdict>
'''


def main():
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        source = tmp / "JMdict_e.gz"
        with gzip.open(source, "wt", encoding="utf-8") as out:
            out.write(XML)
        out = tmp / "pairs.tsv"
        wasei = tmp / "wasei.tsv"
        subprocess.run([sys.executable, str(REPO / "tools/build_jmdict_loanwords.py"), "--jmdict", str(source),
                        "--out", str(out), "--wasei-out", str(wasei)], check=True, stdout=subprocess.DEVNULL)
        pairs = {l.split("\t")[0]: l.split("\t")[1] for l in out.read_text(encoding="utf-8").splitlines()
                 if l and not l.startswith("#")}
        bad = {l.split("\t")[0]: l.split("\t")[1] for l in wasei.read_text(encoding="utf-8").splitlines()
               if l and not l.startswith("#")}

        def check(ok, message):
            if not ok:
                failures.append(message)

        check(pairs.get("コーヒー") == "coffee", "コーヒー → coffee が出ていない")
        check(pairs.get("スマートフォン") == "smartphone", "スマートフォン → smartphone が出ていない")
        check(pairs.get("コンピューター") == "computer", "lsource のない語の英語の訳（computer）が出ていない")
        check(pairs.get("アイアニング") == "ironing", "外来語の英語の訳（アイアニング → ironing）が出ていない")
        check("アイアン" not in pairs and "アイウエオ" not in pairs,
              "外来語でないカタカナ語（アイアン・アイウエオ）に英単語を付けている")
        check("マンション" not in pairs and "サラリーマン" not in pairs, "和製英語（wasei）に英単語を付けている")
        check("マンション" in bad and "サラリーマン" in bad, "和製英語の一覧に出ていない")
    print("\n".join(failures) if failures else "OK JMdict の外来語の試験")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
