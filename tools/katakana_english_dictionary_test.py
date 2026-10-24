"""Tests the dictionary builders for katakana English and official spellings (Mozc なし。作り物の辞書で).

  python tools/katakana_english_dictionary_test.py

確かめること:
- カタカナ語の英単語は、カタカナ語と同じ読み・品詞で、費用だけ --penalty だけ後ろ（先頭を変えない）。
- 作品名・企業名の公式表記と別表記（Dragon Ball と DRAGON BALL、Nike と NIKE）は、同じ読みの
  カタカナ語より後ろで、公式表記が別表記より先。カタカナ語が先頭のまま。
- 既にある (読み, 表記) は重ねて足さない。
"""
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        mozc = tmp / "mozc"
        data = mozc / "data/dictionary_oss"
        data.mkdir(parents=True)
        pos = ["名詞,一般,*,*,*,*,*", "名詞,固有名詞,組織,*,*,*,*", "名詞,固有名詞,人名,一般,*,*,*",
               "名詞,固有名詞,地域,一般,*,*,*", "名詞,固有名詞,一般,*,*,*,*"]
        (data / "id.def").write_text("\n".join(f"{i} {p}" for i, p in enumerate(pos)) + "\n", encoding="utf-8")
        (data / "dictionary00.txt").write_text(
            "こーひー\t0\t0\t3000\tコーヒー\n"
            "どらごんぼーる\t0\t0\t3000\tドラゴンボール\n"
            "ないき\t0\t0\t3000\tナイキ\n"
            "まんしょん\t0\t0\t3000\tマンション\n"
            "めた\t0\t0\t3000\tメタ\n"
            + "".join(f"ないき\t0\t0\t{3100 + i}\t内規{i}\n" for i in range(10)), encoding="utf-8")

        # 0. カタカナ語と英単語の組（和製英語を外し、JMdict の組を足す）
        lex = tmp / "lex"
        lex.mkdir()
        (lex / "english-lexicon.txt").write_text("coffee mansion smartphone\n", encoding="ascii")
        pairs_in = tmp / "pairs-in.tsv"
        pairs_in.write_text("coffee\tコーヒー\t0.01\nmansion\tマンション\t0.01\n", encoding="utf-8")
        jmdict = tmp / "jmdict.tsv"
        jmdict.write_text("スマートフォン\tsmartphone\tlsource\n", encoding="utf-8")
        wasei_file = tmp / "wasei.tsv"
        wasei_file.write_text("マンション\tmansion\n", encoding="utf-8")
        checked = tmp / "checked.tsv"
        checked.write_text("マンション\tmansion\n", encoding="utf-8")  # a checked list must not bring wasei back
        pairs_out = tmp / "pairs-out.tsv"
        subprocess.run([sys.executable, str(REPO / "tools/build_katakana_english.py"), "--pairs", str(pairs_in),
                        "--level", str(lex), "--checked", str(checked), "--jmdict", str(jmdict),
                        "--wasei", str(wasei_file), "--out", str(pairs_out)], check=True, stdout=subprocess.DEVNULL)
        made = {l.split("\t")[0]: l.split("\t")[1] for l in pairs_out.read_text(encoding="utf-8").splitlines()
                if l and not l.startswith("#")}
        failures = []

        def check(ok, message):
            if not ok:
                failures.append(message)

        check(made.get("コーヒー") == "coffee", "音の似た組（コーヒー → coffee）が出ていない")
        check(made.get("スマートフォン") == "smartphone", "JMdict の組（スマートフォン → smartphone）が出ていない")
        check("マンション" not in made, "和製英語（マンション）に英単語を付けている")

        # 1. カタカナ語の英単語
        pairs = tmp / "pairs.tsv"
        pairs.write_text("コーヒー\tcoffee\nマンション\tmansion\n", encoding="utf-8")
        out12 = tmp / "dictionary12.txt"
        subprocess.run([sys.executable, str(REPO / "tools/build_katakana_english_dictionary.py"),
                        "--mozc", str(mozc), "--pairs", str(pairs), "--out", str(out12)],
                       check=True, stdout=subprocess.DEVNULL)
        rows = [l.split("\t") for l in out12.read_text(encoding="utf-8").splitlines()]
        coffee = next((r for r in rows if r[4] == "coffee"), None)
        check(coffee is not None, "コーヒー → coffee が出ていない")
        if coffee:
            check(coffee[0] == "こーひー", f"読みがカタカナ語と同じでない: {coffee[0]}")
            check(int(coffee[3]) == 3010, f"費用はカタカナ語 + 10 のはず: {coffee[3]}")
            check(coffee[1:3] == ["0", "0"], f"品詞はカタカナ語と同じはず: {coffee[1:3]}")

        # 2. 公式表記と別表記
        extra = tmp / "extra.tsv"
        extra.write_text(
            "Dragon Ball\tdragonball\t\tどらごんぼーる\twork\t0\tDRAGON BALL\n"
            "Nike\tnike\t\tないき\tcompany\t0\tNIKE\n"
            "Coca-Cola\tcoca-cola\t\tこかこーら\tcompany\t0\tCOCA-COLA\n"
            "Meta\tmeta\t\tめた\tcompany\t0\tMETA\n", encoding="utf-8")
        base = tmp / "base.tsv"
        base.write_text("Adidas\tadidas\t\tあでぃだす\tcompany\t0\t\n"
                        "Nike\tnike\t\tないき\tbusiness\t0\t\n", encoding="utf-8")
        out14 = tmp / "dictionary14.txt"
        subprocess.run([sys.executable, str(REPO / "tools/build_proper_noun_dictionary.py"),
                        "--mozc", str(mozc), "--names", str(extra), "--names", str(base), "--out", str(out14)],
                       check=True, stdout=subprocess.DEVNULL)
        rows = {}
        for line in out14.read_text(encoding="utf-8").splitlines():
            f = line.split("\t")
            rows[(f[0], f[4])] = int(f[3])
        dragon = rows.get(("どらごんぼーる", "Dragon Ball"))
        dragon_caps = rows.get(("どらごんぼーる", "DRAGON BALL"))
        check(dragon is not None and dragon_caps is not None, "どらごんぼーる → Dragon Ball / DRAGON BALL が出ていない")
        if dragon is not None and dragon_caps is not None:
            check(dragon == 3010, f"Dragon Ball はカタカナ語 + 10 のはず: {dragon}")
            check(dragon_caps == 3011, f"DRAGON BALL は Dragon Ball の次のはず: {dragon_caps}")
        nike = rows.get(("ないき", "Nike"))
        nike_caps = rows.get(("ないき", "NIKE"))
        check(nike == 3010 and nike_caps == 3011,
              f"ないき → Nike, NIKE の順が違う（古い費用が上位10個の外なら、カタカナ語の次へ）: {nike} {nike_caps}")
        check(rows.get(("こかこーら", "Coca-Cola")) == 15000,
              f"読みを持つ語がないときは既定の費用: {rows.get(('こかこーら', 'Coca-Cola'))}")
        check(rows.get(("めた", "Meta")) == 3010 and rows.get(("めた", "META")) == 3011,
              f"2かなの読みでも、Mozc に語があればその後ろ: {rows.get(('めた', 'Meta'))} {rows.get(('めた', 'META'))}")
        # 既にある (読み, 表記) は足さない
        check(all(not (r[0] == "こーひー" and r[4] == "コーヒー") for r in rows), "Mozc にある表記を足している")

    print("\n".join(failures) if failures else "OK カタカナ語・公式表記の辞書の試験")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
