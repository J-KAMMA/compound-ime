"""build_proper_noun_dictionary.py --acronyms の試験（Mozc なし。作り物の辞書で）。

  python tools/acronym_dictionary_test.py

あい に 愛・哀・藍・相・合い がある作り物の辞書で、AI が先頭（愛より安い）に入り、一番安い語（愛）の品詞を使い、
語が2つしかない うい では最後に、読みを持つ語がない うあえ には既定の費用で入ることを確かめる。
"""
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def main():
    with tempfile.TemporaryDirectory() as tmp:
        mozc = Path(tmp) / "mozc"
        data = mozc / "data/dictionary_oss"
        data.mkdir(parents=True)
        (data / "id.def").write_text("\n".join(f"{i} {p}" for i, p in enumerate([
            "名詞,一般,*,*,*,*,*", "名詞,固有名詞,組織,*,*,*,*", "名詞,固有名詞,人名,一般,*,*,*",
            "名詞,固有名詞,地域,一般,*,*,*", "名詞,固有名詞,一般,*,*,*,*"])) + "\n", encoding="utf-8")
        (data / "dictionary00.txt").write_text(
            "あい\t0\t0\t3000\t愛\nあい\t0\t0\t3600\t哀\nあい\t0\t0\t4200\t藍\nあい\t0\t0\t4300\t相\nあい\t0\t0\t5000\t合い\n"
            "うい\t0\t0\t4000\t憂い\nうい\t0\t0\t4000\t初\nういん\t0\t0\t3000\tウイン\n", encoding="utf-8")
        names = Path(tmp) / "names.tsv"
        names.write_text("Google\tgoogle\t\tぐーぐる\tcompany\t100\nAI\t\t\tえーあい|あい\tother\t0\n", encoding="utf-8")
        out = Path(tmp) / "out.txt"
        subprocess.run([sys.executable, str(REPO / "tools/build_proper_noun_dictionary.py"), "--mozc", str(mozc),
                        "--names", str(names), "--acronyms", str(REPO / "tools/data/acronyms.tsv"), "--out", str(out)],
                       check=True, stdout=subprocess.DEVNULL)
        rows = {tuple(l.split("\t")[0:1] + l.split("\t")[4:5]): l.split("\t")[1:4] for l in out.read_text(encoding="utf-8").splitlines()}
        failures = []

        def check(ok, message):
            if not ok:
                failures.append(message)

        ai = rows.get(("あい", "AI"))
        check(ai is not None, "あい → AI が出ていない")
        if ai:
            lid, rid, cost = int(ai[0]), int(ai[1]), int(ai[2])
            check(cost == 2999, f"AI は一番安い愛（3000）より1安く、先頭のはず: {cost}")
            check((lid, rid) == (0, 0), f"AI は愛と同じ品詞のはず: {lid} {rid}")
        check(rows.get(("あい", "AI")) is not None and ("えーあい", "AI") in rows, "えーあい → AI（3かなの読み）が出ていない")
        ui = rows.get(("うい", "UI"))
        check(ui is not None and int(ui[2]) == 4100, f"うい → UI: 語が2つしかないので、3番目は2つめの費用 + 100: {ui}")
        check(("うあえ", "UAE") in rows and int(rows[("うあえ", "UAE")][2]) == 15000, "うあえ → UAE: 読みを持つ語がないので既定の費用")
        check(("ぐーぐる", "Google") in rows, "従来の固有名詞が出ていない")
        # --acronyms なしでは、あい は2かななので出ない（今までの動き）
        out2 = Path(tmp) / "out2.txt"
        subprocess.run([sys.executable, str(REPO / "tools/build_proper_noun_dictionary.py"), "--mozc", str(mozc),
                        "--names", str(names), "--out", str(out2)], check=True, stdout=subprocess.DEVNULL)
        check("あい\t" not in "".join(l[:3] for l in out2.read_text(encoding="utf-8").splitlines()), "--acronyms なしで あい が出ている")
    print("\n".join(failures) if failures else "OK 作り物の辞書の試験")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
