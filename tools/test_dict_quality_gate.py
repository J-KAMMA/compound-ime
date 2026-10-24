"""tools/dict_quality_gate.py（止める基準）の確かめ。 python tools/test_dict_quality_gate.py"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
GATE = HERE / "dict_quality_gate.py"
failures = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        failures.append(what)


# 採点の道具が出す1行目の形（score_proper_nouns.py、score_allenglish.py、score_wiki_typing.py、score_colloquial.py、score_categories.py）
def sample(proper=100, cand_first=80, cand_any=95, mixed=70, ja=198, ja400=380, wiki=900, letters=3, colloquial=150, acr=60):
    return {
        "proper-nouns-score.txt": f"固有名詞の文: 名前が合う {proper}/120、文が全部同じ 90/120\n",
        "proper-nouns-cand-score.txt": f"固有名詞の候補: 先頭 {cand_first}/110、上位3つ 95/110、1ページ目（9つ） 100/110、候補の中 {cand_any}/110\n",
        "acronyms-score.txt": f"略語の文: 名前が合う {acr}/70、文が全部同じ 50/70\n",
        "acronyms-cand-score.txt": "略語の候補: 先頭 40/50、上位3つ 48/50、1ページ目（9つ） 49/50、候補の中 50/50\n",
        "acronyms-ja-score.txt": "略語と重なる日本語の文（日本語のまま出るのが正解）: 名前が合う 30/30、文が全部同じ 30/30\n",
        "domain-tools-cand-score.txt": "開発の道具の候補: 先頭 20/25、上位3つ 22/25、1ページ目（9つ） 24/25、候補の中 25/25\n",
        "allenglish-mixed-score.txt": f"英単語と重なるローマ字: 英語で出た {mixed}/100（alone は数えない）\n",
        "allenglish-ja-score.txt": f"英単語と重なるローマ字: 日本語のまま {ja}/200、英字が混じった {200 - ja}\n",
        "ja400-score.txt": f"colloquial     20/20\n合計            {ja400}/400\n",
        "wiki-typing-score.txt": f"ウィキペディアの文: 元の文と同じ {wiki}/1000、英字が混じった {letters}\n",
        "domain-prog-score.txt": "分野の打ち込み（プログラミング）: 元の文と同じ 250/300、英字が混じった 1\n",
        "katakana-english-score.txt": "カタカナ語: 上位10個以内 500/500、先頭 0 件（英字が先頭になった数）\n"
                                      "作品名: 上位10個以内 320/320、先頭 0 件（英字が先頭になった数）\n"
                                      "企業・ブランド: 上位10個以内 320/320、先頭 0 件（英字が先頭になった数）\n"
                                      "和製英語: 英字が出た 0/44（0 が正しい）\n"
                                      "合計: 上位10個以内 1140/1140（100.0%）、英字が先頭になった 0 件\n",
        "colloquial-score.txt": f"話し言葉の打ち込み: 厳しい {colloquial}/200、記号ゆれ込み 170/200、緩い 180/200\n",
        "inputs.tsv": "a\tx\tA\nb\ty\tB\n",
    }


def write(d: Path, files):
    d.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (d / name).write_text(text, encoding="utf-8")


def run(*args):
    return subprocess.run([sys.executable, str(GATE), *args], capture_output=True, text=True)


def scores(tmp, cand_files, base_files=None, name="x"):
    write(tmp / (name + "-base"), base_files or sample())
    write(tmp / (name + "-cand"), cand_files)
    return run("scores", "--base", str(tmp / (name + "-base")), "--cand", str(tmp / (name + "-cand")), "--json", str(tmp / (name + ".json")))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        r = scores(tmp, sample(), name="same")
        check(r.returncode == 0 and "通ってよい" in r.stdout, "同じ結果は通る")
        r = scores(tmp, sample(proper=105, cand_first=85, mixed=75), name="better")
        check(r.returncode == 0, "よくなった結果は通る")
        r = scores(tmp, sample(proper=99), name="p99")
        check(r.returncode == 0, "固有名詞の文が1件下がるのは、許す範囲（総数×0.5%の切り上げ=1件）")
        r = scores(tmp, sample(proper=97), name="p97")
        check(r.returncode == 1 and "固有名詞の文: 名前が合う" in r.stdout, "固有名詞の文が3件下がったら止まる")
        r = scores(tmp, sample(cand_any=90), name="cand")
        check(r.returncode == 1 and "候補の中" in r.stdout, "固有名詞の候補が減ったら止まる")
        r = scores(tmp, sample(ja400=377), name="ja400")
        check(r.returncode == 1, "日本語の400文が3件下がったら止まる（許すのは2件）")
        r = scores(tmp, sample(ja400=378), name="ja400ok")
        check(r.returncode == 0, "日本語の400文が2件下がるのは許す")
        r = scores(tmp, sample(letters=9), name="letters")
        check(r.returncode == 1 and "英字が混じった" in r.stdout, "英字が混じった文が6件増えたら止まる（件数が少ないほうがよい項目）")
        r = scores(tmp, sample(ja=190), name="ja")
        check(r.returncode == 1, "日本語だけの文が英字になったら止まる")
        broken = sample()
        del broken["proper-nouns-score.txt"]
        r = scores(tmp, broken, name="missing")
        check(r.returncode == 1 and "試験が流れなかった" in r.stdout, "候補の採点がなければ止まる")
        cand = sample()
        cand["inputs.tsv"] = "a\tx\tChanged\nb\ty\tB\n"
        r = scores(tmp, cand, name="changed")
        check(r.returncode == 0 and "1 / 2" in r.stdout, "変わった文の数を報告する（止める基準にはしない）")
        out = json.loads((tmp / "p97.json").read_text(encoding="utf-8"))
        check(out["passed"] is False and out["failures"], "json に止める理由が入る")
        # 取り直した一覧の行数
        old, new = tmp / "old", tmp / "new"
        old.mkdir()
        new.mkdir()
        for name, rows_old, rows_new in (("proper-nouns.tsv", 10000, 10500), ("supplement.tsv", 24000, 24100), ("english-extra.tsv", 60000, 60500)):
            (old / name).write_text("# c\n" + "x\n" * rows_old, encoding="utf-8")
            (new / name).write_text("# c\n" + "x\n" * rows_new, encoding="utf-8")
        r = run("data", "--old-dir", str(old), "--new-dir", str(new))
        check(r.returncode == 0, "行数が近い一覧は通る")
        (new / "proper-nouns.tsv").write_text("# c\n" + "x\n" * 7000, encoding="utf-8")
        r = run("data", "--old-dir", str(old), "--new-dir", str(new))
        check(r.returncode == 1 and "いまの一覧との比" in r.stdout, "行数が3割減った一覧は止まる")
        (new / "proper-nouns.tsv").write_text("# c\n" + "x\n" * 100, encoding="utf-8")
        (old / "proper-nouns.tsv").write_text("# c\n" + "x\n" * 100, encoding="utf-8")
        r = run("data", "--old-dir", str(old), "--new-dir", str(new))
        check(r.returncode == 1 and "下限" in r.stdout, "行数が下限より少ない一覧は止まる")
    # 採点の道具の出力の言葉が変わっていないか（変わったら、基準の正規表現も直す）
    rules = json.loads((HERE / "data/dict-gate.json").read_text(encoding="utf-8"))
    sources = {"proper": "score_proper_nouns.py", "cand": "score_proper_nouns.py", "acronyms": "score_proper_nouns.py", "domain-tools-cand": "score_proper_nouns.py",
               "allenglish": "score_allenglish.py", "ja400": "score_categories.py", "wiki": "score_wiki_typing.py", "domain": "score_wiki_typing.py",
               "colloquial": "score_colloquial.py", "katakana-english": "score_katakana_english.py"}
    for metric in rules["metrics"]:
        key = next(k for k in sources if metric["file"].startswith(k))
        literal = [w for w in __import__("re").findall(r"[ぁ-んァ-ヶ一-龠]+|\d?[ぁ-んァ-ヶ一-龠]+", metric["pattern"]) if w]
        text = (HERE / sources[key]).read_text(encoding="utf-8")
        check(all(w in text for w in literal), f"採点の道具に基準の言葉がある: {metric['name']}（{'、'.join(literal)}）")
    print("failed" if failures else "all ok", len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
