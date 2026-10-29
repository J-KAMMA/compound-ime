"""tools/build_ja_dictionary.py と tools/fetch_japanpost.py（読み取りの部分）の確かめ。通信しない。

  python tools/test_build_ja_dictionary.py
"""
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fetch_japanpost  # noqa: E402
import fetch_wikidata_ja  # noqa: E402

failures = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        failures.append(what)


# 日本郵便の ken_all.csv の形（列: 地方公共団体コード, 旧郵便番号, 郵便番号, 都道府県の読み, 市区町村の読み, 町域の読み,
# 都道府県, 市区町村, 町域, 6つの印）。半角カタカナの読み（古い形）と全角（UTF-8 の形）を混ぜる
CSV = """\
01101,"060  ","0600000","ﾎｯｶｲﾄﾞｳ","ｻｯﾎﾟﾛｼﾁｭｳｵｳｸ","ｲｶﾆｹｲｻｲｶﾞﾅｲﾊﾞｱｲ","北海道","札幌市中央区","以下に掲載がない場合",0,0,0,0,0,0
01102,"001  ","0010000","ﾎｯｶｲﾄﾞｳ","ｻｯﾎﾟﾛｼｷﾀｸ","ｲｶﾆｹｲｻｲｶﾞﾅｲﾊﾞｱｲ","北海道","札幌市北区","以下に掲載がない場合",0,0,0,0,0,0
01103,"065  ","0650000","ﾎｯｶｲﾄﾞｳ","ｻｯﾎﾟﾛｼﾋｶﾞｼｸ","ｷﾀ(1-10ﾁｮｳﾒ)","北海道","札幌市東区","北（１～１０丁目）",0,0,0,0,0,0
01303,"06102","0610200","ﾎｯｶｲﾄﾞｳ","ｲｼｶﾘｸﾞﾝﾄｳﾍﾞﾂﾁｮｳ","ﾄｳﾍﾞﾂﾁｮｳﾉﾂｷﾞﾆﾊﾞﾝﾁｶﾞｸﾙﾊﾞｱｲ","北海道","石狩郡当別町","当別町の次に番地がくる場合",0,0,0,0,0,0
32203,"69901","6990101","シマネケン","イズモシ","ウップルイチョウ","島根県","出雲市","十六島町",0,0,0,0,0,0
13104,"160  ","1636090","ﾄｳｷｮｳﾄ","ｼﾝｼﾞｭｸｸ","ﾆｼｼﾝｼﾞｭｸｼﾝｼﾞｭｸﾉｰｽﾋﾞﾙ(ﾁｶｲ･ｶｲｿｳﾌﾒｲ)","東京都","新宿区","西新宿新宿ノースビル（地階・階層不明）",0,0,0,0,0,0
03366,"02955","0295500","ｲﾜﾃｹﾝ","ﾜｶﾞｸﾞﾝﾆｼﾜｶﾞﾏﾁ","ｱﾅｱｹ22ﾁﾜﾘ","岩手県","和賀郡西和賀町","穴明２２地割",0,0,0,0,0,0
06365,"99953","9995300","ﾔﾏｶﾞﾀｹﾝ","ﾓｶﾞﾐｸﾞﾝﾏﾑﾛｶﾞﾜﾏﾁ","ｵｵｱｻﾞﾉｿﾞｷ","山形県","最上郡真室川町","大字及位",0,0,0,0,0,0
26100,"604  ","6040000","ｷｮｳﾄﾌ","ｷｮｳﾄｼﾅｶｷﾞｮｳｸ","ｱｲｵｲﾁｮｳ(ｶﾗｽﾏﾄﾞｵﾘｺﾞｼﾞｮｳ","京都府","京都市中京区","相生町（烏丸通御池上る、",0,0,0,0,0,0
26100,"604  ","6040000","ｷｮｳﾄﾌ","ｷｮｳﾄｼﾅｶｷﾞｮｳｸ","ｱｶﾞﾙ)","京都府","京都市中京区","烏丸通姉小路下る）",0,0,0,0,0,0
"""


def test_postal():
    rows = fetch_japanpost.parse(CSV)
    got = {(s, r) for s, r, _ in rows}
    check(("十六島町", "うっぷるいちょう") in got, "町域（全角カタカナの読み）")
    check(("及位", "のぞき") in got, "大字を除く（読みの おおあざ も）")
    check(("北", "きた") in got, "括弧の中を除く")
    check(("相生町", "あいおいちょう") in got, "2行に分かれた町域をつなぐ")
    check(not any("以下に掲載" in s or "番地がくる" in s for s, _ in got), "決まり文句の町域は取らない")
    check(not any("ノースビル" in s for s, _ in got), "ビルの階の行は取らない")
    check(not any("地割" in s for s, _ in got), "読みに数字がある行は取らない")
    check(("当別町", "とうべつちょう") in got and ("石狩郡", "いしかりぐん") in got, "郡と町に分ける")
    check(("札幌市", "さっぽろし") in got and ("中央区", "ちゅうおうく") in got, "政令市の市と区に分ける（区が3つ以上）")
    check(("京都市", "きょうとし") not in got, "区が3つ未満の市は分けない")
    check(("島根県", "しまねけん") in got and ("出雲市", "いずもし") in got, "都道府県と市区町村")


def test_wikidata_kind():
    kinds = {"Q515": "place", "Q43229": "org"}
    check(fetch_wikidata_ja.kind_of({"Q5"}, kinds) == "person", "人")
    check(fetch_wikidata_ja.kind_of({"Q515", "Q43229"}, kinds) == "place", "場所が組織より先")
    check(fetch_wikidata_ja.kind_of({"Q999"}, kinds) == "other", "どれでもない")


MOZC_DICT = [
    # 読み, 左, 右, 費用, 表記
    ("にほん", 1, 1, 3000, "日本"),
    ("にっぽん", 1, 1, 3500, "日本"),
    ("かえる", 2, 2, 4000, "帰る"),
    ("かえる", 1, 1, 5000, "蛙"),
    ("きた", 1, 1, 3000, "北"),
    ("いずもし", 3, 3, 6000, "出雲市"),
    ("ひがし", 1, 1, 3000, "東"),
    # 字・部分の読み（Wikidata の読みを、辞書の読みでたどれるかの確かめに使う）
    ("おおくぼ", 4, 4, 6000, "大久保"), ("みち", 1, 1, 5000, "通"), ("おに", 1, 1, 5000, "鬼"), ("き", 1, 1, 7000, "鬼"),
    ("たろう", 4, 4, 6000, "太郎"), ("もり", 1, 1, 5000, "森"), ("がい", 1, 1, 6000, "外"),
    ("かえ", 1, 1, 7000, "替"), ("る", 1, 1, 7000, "流"),
    ("まきの", 4, 4, 6000, "牧野"), ("とみ", 1, 1, 6000, "富"), ("かわ", 1, 1, 5000, "川"), ("たに", 1, 1, 5000, "谷"),
    ("けん", 1, 1, 5000, "県"), ("けん", 1, 1, 5000, "憲"), ("そう", 1, 1, 5000, "宗"),
    ("しゃほう", 1, 1, 7000, "斜方"), ("にじゅう", 1, 1, 5000, "二十"), ("めんたい", 1, 1, 7000, "面体"),
    ("しかく", 1, 1, 5000, "視覚"), ("げいじゅつ", 1, 1, 5000, "芸術"),
    ("でんき", 1, 1, 5000, "電気"), ("でんし", 1, 1, 5000, "電子"), ("こうがく", 1, 1, 5000, "工学"),
    ("じんじゃ", 1, 1, 5000, "神社"), ("すわ", 3, 3, 6000, "諏訪"),
]
ID_DEF = """0 BOS/EOS,*,*,*,*,*,*
1 名詞,一般,*,*,*,*,*
2 動詞,自立,*,*,五段・ラ行,基本形,*
3 名詞,固有名詞,地域,一般,*,*,*
4 名詞,固有名詞,人名,一般,*,*,*
5 名詞,固有名詞,組織,*,*,*,*
6 名詞,固有名詞,一般,*,*,*,*
"""


def test_builder(tmp):
    data = tmp / "src/data/dictionary_oss"
    data.mkdir(parents=True)
    (data / "id.def").write_text(ID_DEF, encoding="utf-8")
    (data / "dictionary00.txt").write_text("".join(f"{r}\t{l}\t{rr}\t{c}\t{s}\n" for r, l, rr, c, s in MOZC_DICT),
                                           encoding="utf-8")
    wd = tmp / "ja-wikidata-raw.tsv"
    wd.write_text("\n".join([
        "Q1\t大久保利通\tオオクボ トシミチ\t40\tperson",          # 新しい読み → 15000
        "Q2\t日本\tヤマト\t200\tplace",                           # よく使う語の別の読み → 取らない
        "Q3\t日本\tニホン\t200\tplace",                           # Mozc にある → 取らない
        "Q4\t蛙\tカエル\t10\tother",                              # Mozc にある
        "Q5\t替流\tカエル\t5\torg",                               # 一般語と同じ読み → 後ろ
        "Q6\tゲゲゲの鬼太郎\tゲゲゲノキタロウ\t30\twork",         # かなと漢字
        "Q7\t鬼太郎\tオニタロウ|キタロウ\t30\twork",               # 読み2つ
        "Q8\tトヨタ\tトヨタ\t100\torg",                           # 漢字がない → 取らない
        "Q9\t東京スカイツリー\tトウキョウスカイ\t50\tplace",       # 表記のかながない読み → 取らない
        "Q10\t山田\tやまだ たろう\t3\tperson",                    # 2字で辞書にない読み → 取らない
        # 読みが表記を覆っていない（Wikidata の実例。run 40853954933 の報告から）
        "Q20\tブルサ県\tブルサ\t50\tplace",                         # 県 の読みがない
        "Q21\t鎮西大社諏訪神社\tスワジンジャ\t3\tplace",             # 8字に6かな
        "Q22\t電気電子工学\tデンシコウガク\t20\tother",               # 6字に7かな（下限8）
        "Q23\t視覚芸術\tビジュアルアート\t30\tother",                # 外来語の形の読み
        "Q24\t憲宗\tリジュン\t20\tperson",                           # 別の読み（辞書でたどれない）
        "Q25\t斜方二十面体\tダイシャホウロクメンタイ\t20\tother",      # 別の物の読み
        "Q26\t牧野富太郎\tマキノトミタロウ\t20\tperson",             # 辞書でたどれる → 入る
        "Q27\t谷川\tタニガワ\t5\tplace",                             # 連濁（かわ → がわ）でたどれる → 入る
        "Q28\t鬼々\tオニオニ\t5\tother",                             # 々 は前の字の繰り返し → 入る
        "Q11\t北\tキタ\t3\tplace",                                # 1文字 → 取らない
        "Q12\tAKB48劇場\tエーケービーフォーティーエイトゲキジョウ\t3\tplace",  # 英数字 → 取らない
        "Q13\t森鷗外\tモリ オウガイ\t60\tperson",
        "Q14\t森鴎外\tモリオウガイ\t60\tperson",
        "Q15\t堺\tサカイ\t5\tplace",                               # 1文字
        "Q16\t岩手\tイワ\t5\tplace",                               # 短い読み（3かな未満）
    ]) + "\n", encoding="utf-8")
    postal = tmp / "postal-raw.tsv"
    postal.write_text("\n".join([
        "十六島町\tうっぷるいちょう\ttown",
        "出雲市\tいずもし\tcity",              # Mozc にある
        "鬼太郎\tきたろう\ttown",              # Wikidata と同じ → 取らない
        "東町\tひがしまち\ttown",
        "北\tきた\ttown",
        "宮\tみや\ttown",
        "奥\tおく\ttown",
        "中ノ\tなかの\ttown",
        "上野\tこうずけ\ttown",
    ]) + "\n", encoding="utf-8")
    out_w, out_p, report = tmp / "w.tsv", tmp / "p.tsv", tmp / "r.md"
    subprocess.run([sys.executable, str(HERE / "build_ja_dictionary.py"), "--mozc", str(tmp / "src"),
                    "--wikidata", str(wd), "--postal", str(postal), "--out-wikidata", str(out_w),
                    "--out-postal", str(out_p), "--report", str(report)], check=True, capture_output=True)
    w = {(f[0], f[4]): (int(f[1]), int(f[3])) for f in (l.split("\t") for l in out_w.read_text(encoding="utf-8").splitlines())}
    p = {(f[0], f[4]): (int(f[1]), int(f[3])) for f in (l.split("\t") for l in out_p.read_text(encoding="utf-8").splitlines())}
    check(w.get(("おおくぼとしみち", "大久保利通")) == (4, 15000), "人の名前: 新しい読みは 15000、人名の品詞")
    check(("やまと", "日本") not in w, "よく使う語の別の読みは取らない")
    check(("にほん", "日本") not in w and ("かえる", "蛙") not in w, "Mozc にある語は取らない")
    for reading, surface in (("ぶるさ", "ブルサ県"), ("すわじんじゃ", "鎮西大社諏訪神社"), ("でんしこうがく", "電気電子工学"),
                             ("びじゅあるあーと", "視覚芸術"), ("りじゅん", "憲宗"), ("だいしゃほうろくめんたい", "斜方二十面体"),
                             ("やまだたろう", "山田")):
        check((reading, surface) not in w, f"読みが表記を覆わない組は取らない: {surface} / {reading}")
    check(("まきのとみたろう", "牧野富太郎") in w and ("たにがわ", "谷川") in w and ("おにおに", "鬼々") in w,
          "辞書の読み（連濁、々）でたどれる組は入る")
    got = w.get(("かえる", "替流"))
    check(got is not None and got[1] == max(5000 + 100, 4000 + 3000) and got[0] == 5,
          "一般語と同じ読み: その読みの全部より後ろ・一番安い語から gap 離す、組織の品詞")
    check(("げげげのきたろう", "ゲゲゲの鬼太郎") in w, "かなと漢字の作品名")
    check(("おにたろう", "鬼太郎") in w and ("きたろう", "鬼太郎") in w, "読みが2つ")
    check(not any(s in ("トヨタ", "東京スカイツリー", "北", "AKB48劇場", "堺", "岩手") for _, s in w),
          "漢字なし・読みが合わない・1文字・英数字・短い読みは取らない")
    check(("もりおうがい", "森鷗外") in w and ("もりおうがい", "森鴎外") in w, "同じ読みの2つの表記")
    costs = sorted(w[("もりおうがい", s)][1] for s in ("森鷗外", "森鴎外"))
    check(costs == [15000, 15001], "同じ読みの2つ目は1つ後ろ")
    check(p.get(("うっぷるいちょう", "十六島町")) == (3, 15000), "住所: 新しい読み、地域の品詞")
    check(("いずもし", "出雲市") not in p, "住所: Mozc にある市は取らない")
    check(("きたろう", "鬼太郎") not in p, "住所: Wikidata の行と同じものは住所に入れない")
    check(("ひがしまち", "東町") in p and p[("ひがしまち", "東町")][1] == 15000, "住所: Mozc にない4かなの読み")
    check(("みや", "宮") not in p and ("おく", "奥") not in p, "1文字の町域は取らない")
    check(("なかの", "中ノ") not in p, "Mozc にない3かなの読みは取らない")
    check(("こうずけ", "上野") in p, "Mozc にない表記の珍しい読みは、新しい読みとして入る（よく使う語でなければ）")
    text = report.read_text(encoding="utf-8")
    check("住所: 入れた" in text, "報告を書く")
    check("| Wikidata: 読みが表記を覆わない（かなと漢字の並び・字数） | 3 |" in text
          and "| Wikidata: 読みが外来語の形（表記は漢字だけ） | 1 |" in text
          and "| Wikidata: 読みを辞書の字の読みでたどれない（別名・通称） | 3 |" in text,
          "除いた数を理由ごとに報告に出す")


def main():
    test_postal()
    test_wikidata_kind()
    with tempfile.TemporaryDirectory() as tmp:
        test_builder(Path(tmp))
    if failures:
        print(f"{len(failures)} 件の失敗")
        sys.exit(1)
    print("全部通った")


if __name__ == "__main__":
    main()
