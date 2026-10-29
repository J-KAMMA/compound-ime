"""二つの文が「表記ゆれだけの違い」かを判定する（標準ライブラリだけ）。

  from lenient_match import lenient_match
  lenient_match("殆ど同じ事", "ほとんど同じこと")  # True

両方の文を正規化して等しければ一致とみなす。正規化の中身:
  - 全角半角をそろえる（NFKC）、カタカナをひらがなに寄せる
  - 旧字・異体字を新字に
  - 形式語・副詞・接続詞の漢字表記をかなに（事→こと、様→よう、時→とき 等）。
    一字の語は、前後が漢字・数字・英字でないときだけ置き換える
    （時間・同時・5時・仕事・平等 のような熟語は壊さない）
  - 送り仮名の小さなゆれ（行なう→行う、表わす→表す）
迷うものは入れない。誤って正解を増やさないことを優先する。
"""
import re
import unicodedata

# 前後にあると「熟語の一部」とみなす文字（漢字・数字・英字・々）
_BLOCK = "0-9A-Za-z々〆㐀-䶿一-鿿豈-﫿"

# 一字の語: 前後が熟語でないときだけ置き換える
_SINGLE = {
    "事": "こと", "様": "よう", "時": "とき", "為": "ため", "又": "また",
    "程": "ほど", "尚": "なお",
}
# 「等」は等しい（ひとしい）を除く
_SPECIAL_SINGLE = [(r"(?<![%s])等(?![%s]|しい|しく)" % (_BLOCK, _BLOCK), "など")]

# 長い語: 前に漢字があってもよい（A及びB、A又はB）。後ろ側は語の一部として含める
_WORDS = [
    ("殆ど", "ほとんど"), ("及び", "および"), ("又は", "または"), ("但し", "ただし"),
    ("並びに", "ならびに"), ("若しくは", "もしくは"), ("或いは", "あるいは"),
    ("即ち", "すなわち"), ("勿論", "もちろん"), ("迄", "まで"), ("下さい", "ください"),
    ("於いて", "において"), ("於ける", "における"), ("宜しく", "よろしく"),
    ("致します", "いたします"), ("暫く", "しばらく"), ("概ね", "おおむね"),
    ("予め", "あらかじめ"), ("恐らく", "おそらく"), ("何故", "なぜ"),
]
# 前が漢字でないときだけ置き換える語
_WORDS_LEFT = [
    ("良く", "よく"), ("更に", "さらに"), ("既に", "すでに"), ("全て", "すべて"),
    ("頂く", "いただく"), ("頂き", "いただき"),
    ("出来る", "できる"), ("出来た", "できた"), ("出来ない", "できない"),
    ("出来ます", "できます"), ("出来て", "できて"), ("出来ず", "できず"),
]
# 達: 前がかなのとき、または代名詞のとき（友達・発達・配達 などは対象外）
_TACHI = [
    (r"(?<![%s])達(?![%s])" % (_BLOCK, _BLOCK), "たち"),
    (r"(私|僕|俺|君|貴方|子供|彼女|彼)達(?![%s])" % _BLOCK, r"\1たち"),
]
# 送り仮名のゆれ
_OKURI = [
    (r"行な(?=[うっいわえ])", "行"),
    (r"表わ(?=[すしさせ])", "表"),
]
_KAGETSU = (r"(?<=[0-9一二三四五六七八九十百])[ヶヵケカか箇個](?=[月所国年間])", "か")

# 旧字・異体字 → 新字
_OLD = dict(zip(
    "國學體總號區會對傳藝圖變廣實當濱澤齋邊驛營鐵戰數點觀關圓禮靈臺縣寶辯舊發壽讀讓"
    "應惡價擧經續與條眞惠假賣劍嚴兩內氣淺櫻屬彈狀殘﨑髙邉",
    "国学体総号区会対伝芸図変広実当浜沢斎辺駅営鉄戦数点観関円礼霊台県宝弁旧発寿読譲"
    "応悪価挙経続与条真恵仮売剣厳両内気浅桜属弾状残崎高辺"))
_OLD_TABLE = str.maketrans(_OLD)

_SINGLE_RES = [(re.compile(r"(?<![%s])%s(?![%s])" % (_BLOCK, k, _BLOCK)), v)
               for k, v in _SINGLE.items()]
_SPECIAL_RES = [(re.compile(p), r) for p, r in _SPECIAL_SINGLE]
_TACHI_RES = [(re.compile(p), r) for p, r in _TACHI]
_OKURI_RES = [(re.compile(p), r) for p, r in _OKURI]
_LEFT_RES = [(re.compile(r"(?<![%s])%s" % (_BLOCK, re.escape(k))), v) for k, v in _WORDS_LEFT]
_KAGETSU_RE = re.compile(_KAGETSU[0])


def _kata_to_hira(s):
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" or c in "ヽヾ" else c
                   for c in s)


def _fold(s):
    """かなの字種以外の正規化（長さは字種そろえの前後で変わらない）。"""
    s = unicodedata.normalize("NFKC", s).translate(_OLD_TABLE)
    s = _KAGETSU_RE.sub(_KAGETSU[1], s)
    for pat, rep in _OKURI_RES:
        s = pat.sub(rep, s)
    for old, new in _WORDS:
        s = s.replace(old, new)
    for pat, rep in _LEFT_RES:
        s = pat.sub(rep, s)
    for pat, rep in _SPECIAL_RES + _SINGLE_RES + _TACHI_RES:
        s = pat.sub(rep, s)
    return s


def normalize(s):
    return _kata_to_hira(_fold(s))


def lenient_match(a, b):
    """完全一致、または表記ゆれだけの違いなら True。"""
    if a == b:
        return True
    x, y = _fold(a), _fold(b)
    if _kata_to_hira(x) != _kata_to_hira(y):
        return False
    # 字種だけの違い（ひらがな⇔カタカナ）は、二字以上続くときだけ表記ゆれとみなす。
    # 一字だけ（助詞の「と」と「ト」、「に」と「ニ」など）は誤りの可能性が高い。
    run = 0
    for c, d in zip(x, y):
        if c != d:
            run += 1
        elif c in "ー・":
            continue
        else:
            if 0 < run < 2:
                return False
            run = 0
    return not 0 < run < 2
