"""英単語と重なるローマ字の試験の文を作る（2026-10-21）。

ローマ字として日本語に読める英単語（make: まけ、take: たけ、same: さめ、one: おね ...）を中心に、
  tests/conversion/allenglish-mixed.tsv  英語にしたい文（日本語の文の中の英語、英語だけの文）
  tests/conversion/allenglish-ja.tsv     日本語のままにしたい文（英単語と同じ綴りのローマ字の語を含む）
を作る。語の一覧と文の型はこのファイルに直接書いてある（外の一覧に頼らない。決まった順番で作るので、
何度流しても同じ文ができる）。打ち方（ローマ字）はすべて手で書いた語のつなぎ合わせで、実装を見て
決めていない。

  python tools/make_allenglish_tests.py            # tests/conversion/ に書く
  python tools/make_allenglish_tests.py --stats    # 数だけ出す

列（mixed）: ローマ字<TAB>期待する文<TAB>区分<TAB>英語の部分（コンマ区切り。空白は語の間）<TAB>連番
列（ja）   : ローマ字<TAB>期待する文<TAB>区分<TAB>重なる英単語<TAB>連番
区分（mixed）:
  phrase   英語の2語・3語のつながりを日本語の文にはさむ（文頭・文中・文末）
  rare     一覧の大きい段（SCOWL の水準36〜70）の英単語1語（patina、montage ...）を日本語の文にはさむ
  paired   ローマ字として読める語が、ローマ字として読めない英単語（server、project ...）の隣にある
  sentence 英語だけの文（日本語の助詞なし）
  alone    日本語の助詞のあいだに英単語1語だけ（日本語の語としても読めるので、決め手がない。記録用）
区分（ja）:
  noun     名詞 + 助詞（竹を、金が、本は）
  verb     動詞・形容詞の活用（褒めます、負けた、晴れて）
  particle まで・ため・おねがい など、語の一部や助詞になる重なり
  loan     英語と同じ綴りのカタカナ語（ペン、バナナ、ラジオ）
採点は tools/score_allenglish.py。
"""
import argparse
import random
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "tests" / "conversion"

# ---- 英語にしたい文 ----
# 日本語の前後（名詞のつながり用）: (ローマ字の前, 前, ローマ字の後, 後)
NP_WRAPS = [
    ("kono", "この", "wotsukau", "を使う"),
    ("", "", "gaarimasu", "があります"),
    ("ashitano", "明日の", "wokakuninshite", "を確認して"),
    ("", "", "dehanaku", "ではなく"),
    ("kyouha", "今日は", "nitsuitekangaeru", "について考える"),
    ("sono", "その", "wosagashiteiru", "を探している"),
    ("", "", "nohougaii", "のほうがいい"),
    ("watashino", "私の", "hadokodesuka", "はどこですか"),
    ("kondo", "今度", "woshiraberu", "を調べる"),
    ("", "", "karahajimeyou", "から始めよう"),
    ("konoapurino", "このアプリの", "wokaeta", "を変えた"),
    ("sorehaonaji", "それは同じ", "desu", "です"),
]
# 動詞のつながり用
VP_WRAPS = [
    ("", "", "shitekudasai", "してください"),
    ("tabun", "たぶん", "shimasu", "します"),
    ("kyouha", "今日は", "surutsumorida", "するつもりだ"),
    ("", "", "surukotoga","することが"),
    ("kanarazu", "必ず", "shimasu", "します"),
    ("", "", "shinaito", "しないと"),
]

# 英語のつながり（名詞）: ローマ字として読める語を含む
NP_PHRASES = """
same time|same name|same size|same page|same site|same mode|same data|same base|same house
home page|home mode|home site|home region|home image|home media|home menu
game mode|game name|game time|game menu|game media|game data|game base
time zone|time name|time mode|time data|time base|time region|time session
name tag|name page|name data|name mode|name base|name space
note name|note data|note page|note mode|note menu
base name|base mode|base data|base image|base region|base page
one more|one time|one more time|one name|one note|one page|one mode|one zone|one game
some time|some more|some data|some name|some notes
data base|data name|data mode|data page|data region|data session
date time|date mode|date name|date zone
code name|code base|code mode|code page|code data
node name|node mode|node data|node zone
tone mode|tone zone|tone data
zone name|zone mode|zone data|zone region
house name|house mode|mouse mode|mouse name|mouse zone
site name|site mode|site data|site menu|site page
size name|size mode|size data|size zone
nation name|nation mode|region name|region mode|region zone|region data
session name|session mode|session data|session time|session zone
token name|token data|token mode|theme name|theme mode|theme data
image name|image data|image mode|image base|image region
menu name|menu mode|menu data|menu page|menu zone
media name|media mode|media data|media zone|media base
memo name|memo data|memo page|demo mode|demo name|demo data|demo page|demo zone
domain name|domain data|domain mode|domain zone
engine mode|engine name|engine data|human name|human mode|human data|human zone
icon name|icon mode|icon data|info page|info mode|info data|info zone
future mode|future name|future data|future zone|future time
vision mode|vision data|reason name|reason data|reason mode|route name|route data|route mode
page name|page mode|page data|page zone|page base|page region
""".strip().split("\n")
NP_PHRASES = [p.strip() for line in NP_PHRASES for p in line.split("|") if p.strip()]

VP_PHRASES = """
make sure|take care|take note|take time|make time|take more time|make some time|take some time
use some|see more|see some|see one|see same|use one|use same|make one|take one|make same
make name|make note|take name|take home|take some|take data|make data|use data|make mode
use more|make more|take more|raise more|use name|use time|use mode|see time|see name
make a note|take a note|use the same|make the same|take the same|see the same
rename one|resume some|erase some|erase one|erase same|erase data|erase name
reuse some|reuse data|reuse one|reuse name|define name|define mode|define zone|define one
ensure some|ensure same|ensure one|assume some|assume same|assume one|assume mode
imagine one|imagine some|measure time|measure size|measure some|measure data|manage data|manage time|manage name|manage some
mention name|mention time|mention some|mention one|operate mode|operate some
""".strip().split("\n")
VP_PHRASES = [p.strip() for line in VP_PHRASES for p in line.split("|") if p.strip()]

# ローマ字として読めない英単語（その場で英語になる語）と、ローマ字として読める語の組
PAIRED_AMB = """make take same name home game one time some note mode data date base site size tone zone house mouse region
session token theme image domain engine menu page""".split()
PAIRED_DEF = """project screenshot server file button window bookmark update download folder setting upload backup branch account
password chrome python github google network browser select login program library android windows database keyboard screen""".split()

NP_WRAPS_PAIRED = [
    ("kono", "この", "wokaeru", "を変える"),
    ("", "", "gaaru", "がある"),
    ("sono", "その", "nitsuite", "について"),
    ("ashitano", "明日の", "wokakunin", "を確認"),
]

# 一覧の大きい段（SCOWL の水準36〜70）にある英単語で、ローマ字として日本語に読めるもの（rare 区分）
RARE_WORDS = """thereto intone patina retake onside montage moraine entente pinafore dotage begonia settee attune antedate
geode rupee pupate sanguine effete derriere terrazzo serrano bazooka angora manatee reggae foodie tonsure""".split()

ENG_SUBJ = ["i", "we", "you", "they", "he", "she", "it"]
ENG_MODAL = ["must", "will", "can", "should", "would", "could", "may"]
ENG_SUBJ_PLURAL = ["i", "we", "you", "they"]
ENG_VERB = ["make", "take", "use", "see", "manage", "measure", "define", "ensure", "assume", "mention", "operate", "resume", "erase", "rename", "reuse", "raise", "join", "wake", "wipe", "hide", "share", "shake"]
ENG_DET = ["the", "a", "one", "some", "more", "same"]
ENG_NOUN = ["name", "game", "time", "home", "note", "mode", "node", "date", "data", "base", "site", "size", "tone", "zone", "house", "mouse", "page", "rain", "pipe", "tape", "token", "theme", "nature", "noise", "region", "session", "solution", "vision", "position", "reason", "route", "image", "menu", "media", "memo", "demo", "domain", "engine", "human", "icon", "info", "message", "minute", "mountain", "onion", "orange", "origin", "passage"]
ENG_TAIL = ["", "here", "there", "soon", "again", "more", "before", "inside", "outside", "within", "once"]

# 日本語の文（アルファベットなし）で英単語と同じ綴りになる語: (ローマ字, 漢字や表記)
JA_NOUNS = [  # 英単語の綴りと、その読みの日本語の語（Mozc の辞書で確かめた読み）
    ("take", "竹"), ("sake", "酒"), ("kane", "金"), ("same", "鮫"), ("hate", "果て"), ("hon", "本"), ("men", "麺"),
    ("ken", "県"), ("sen", "線"), ("son", "損"), ("ban", "番"), ("san", "三"), ("ten", "点"), ("jin", "人"),
    ("min", "民"), ("hen", "辺"), ("bin", "瓶"), ("kin", "金"), ("mine", "峰"), ("mare", "稀"), ("kare", "彼"),
    ("dare", "誰"), ("hone", "骨"), ("ago", "顎"), ("numa", "沼"), ("tuna", "綱"), ("tuba", "唾"), ("iso", "磯"),
    ("saga", "佐賀"), ("tango", "丹後"), ("bingo", "備後"), ("kimono", "着物"), ("karate", "空手"), ("kohaku", "琥珀"),
    ("dote", "土手"), ("shake", "鮭"), ("dome", "度目"), ("mama", "まま"), ("hobo", "ほぼ"), ("sonata", "そなた"),
]
JA_NOUN_FRAMES = [
    ("{X}gaarimasu", "{J}があります"),
    ("{X}wokaimashita", "{J}を買いました"),
    ("{X}nituiteshirabeta", "{J}について調べた"),
    ("{X}dehanaku", "{J}ではなく"),
    ("kyouha{X}nokotowokangaeteiru", "今日は{J}のことを考えている"),
    ("ashitamo{X}wotsukau", "明日も{J}を使う"),
    ("{X}karahajimeyou", "{J}から始めよう"),
    ("sorehaonaji{X}desu", "それは同じ{J}です"),
    ("watashiha{X}gasukidesu", "私は{J}が好きです"),
    ("kinouno{X}hadokodesuka", "昨日の{J}はどこですか"),
]
# 動詞の語幹（活用が続く）: (語幹のローマ字, 表記の語幹)。語幹 + 活用の形で打つ
JA_VERB_STEMS = [
    ("home", "褒め"), ("make", "負け"), ("same", "冷め"), ("take", "炊け"), ("more", "漏れ"), ("tore", "取れ"),
    ("tome", "止め"), ("maze", "混ぜ"), ("ate", "当て"), ("nose", "乗せ"), ("yoke", "避け"), ("sage", "下げ"),
    ("bake", "化け"), ("hoe", "吠え"), ("hue", "増え"), ("fume", "踏め"), ("mane", "真似"), ("name", "舐め"),
    ("some", "染め"), ("bore", "惚れ"), ("hike", "引け"), ("abi", "浴び"), ("tame", "貯め"), ("hate", "果て"),
    ("mate", "待て"), ("hare", "晴れ"), ("uri", "売り"), ("hose", "干せ"), ("fuse", "付せ"), ("oboe", "覚え"),
]
JA_VERB_FORMS = [
    ("masu", "ます"), ("masuka", "ますか"), ("ta", "た"), ("te", "て"), ("nai", "ない"), ("ru", "る"), ("rareru", "られる"), ("tai", "たい"),
]
JA_VERB_PRE = [("kyouha", "今日は"), ("", ""), ("kinou", "昨日"), ("kanarazu", "必ず")]
# まで・ため・おねがい など（語の一部や助詞が英単語に重なる）: 文をそのまま書く
JA_PARTICLE_SENTENCES = [
    ("gojimadehatarakimasu", "5時まで働きます"), ("tokyomadeikimasu", "東京まで行きます"),
    ("ashitamadenimatteite", "明日までに待っていて"), ("kyoumadedekitara", "今日までできたら"),
    ("kenkounotameniarukimasu", "健康のために歩きます"), ("kazokunotamenihatarakou", "家族のために働こう"),
    ("sonotameniikimasu", "そのために行きます"), ("gakumonnotameda", "学問のためだ"),
    ("madewomatsu", "までを待つ"), ("kurumadeiku", "車で行く"), ("denshamadeiku", "電車で行く"),
    ("amedanodeikimasen", "雨なので行きません"), ("kyouhayasumidanodekonai", "今日は休みなのでこない"),
    ("nodedekimasen", "のでできません"), ("tanoshiinodeaso", "楽しいので遊"), ("kaigigaarunode", "会議があるので"),
    ("kyoudemoii", "今日でもいい"), ("demoikimasu", "でも行きます"), ("ashitademomatsu", "明日でも待つ"),
    ("sonomamadeikimasu", "そのままで行きます"), ("mamadeiiyo", "ままでいいよ"), ("kinomamanihanasu", "気のままに話す"),
    ("mainichigotonikaeru", "毎日ごとに変える"), ("nanigotonimo", "何ごとにも"), ("kotogotoku", "ことごとく"),
    ("iyouda", "いようだ"), ("souiyounakoto", "そういうようなこと"), ("youdearu", "ようである"),
    ("wakegawakaranai", "わけがわからない"), ("sonowakeha", "そのわけは"), ("iwakeniha", "言い訳には"),
    ("soregasukida", "それが好きだ"), ("soreyorimotto", "それよりもっと"), ("mottotakusan", "もっとたくさん"),
    ("daregaikuka", "誰が行くか"), ("daremoinai", "誰もいない"), ("aregaarimasu", "あれがあります"),
    ("oregaikuyo", "俺が行くよ"), ("oretachino", "俺たちの"), ("arekoreshite", "あれこれして"),
    ("onegaishimasu", "お願いします"), ("onegaiganaru", "お願いがある"), ("mouonegaishimasen", "もうお願いしません"),
    ("minnadeonegaishimasu", "みんなでお願いします"), ("madadamedesu", "まだだめです"),
    ("sorehamadamadadesu", "それはまだまだです"), ("kanemochinohitoga", "金持ちの人が"),
    ("sakeonomu", "酒を飲む"), ("takenokowomitai", "竹の子を見たい"), ("takenoko", "竹の子"),
    ("kanedehanaku", "金ではなく"), ("sakenomise", "酒の店"), ("kanenohanashi", "金の話"),
    ("matenakattano", "待てなかったの"), ("sameganaiteiru", "鮫が泣いている"),
    ("hanahaharetekita", "花は晴れてきた"), ("ameganaharete", "雨が晴れて"), ("tamenitenarunara", "ためになるなら"),
    ("honnotameni", "本のために"), ("tamenoonegai", "ためのお願い"), ("toumorokoshimo", "とうもろこしも"),
    ("sonnamononodemo", "そんなものでも"), ("anatamoiku", "あなたも行く"), ("watashimoikitai", "私も行きたい"),
]
# 英語と同じ綴りのカタカナ語（日本語の文では英語にしない）
JA_LOAN = [  # 日本語を打つ人が、そのままのローマ字で打つカタカナ語（radio や menu は rajio、me-nyu- と打つので入れない）
    ("pen", "ペン"), ("banana", "バナナ"), ("piano", "ピアノ"), ("memo", "メモ"), ("demo", "デモ"), ("tomato", "トマト"),
    ("mini", "ミニ"), ("mama", "ママ"), ("papa", "パパ"), ("zero", "ゼロ"), ("domino", "ドミノ"), ("nano", "ナノ"),
    ("tuna", "ツナ"), ("mania", "マニア"), ("panda", "パンダ"), ("tango", "タンゴ"),
    ("bingo", "ビンゴ"), ("panama", "パナマ"), ("sonata", "ソナタ"), ("pino", "ピノ"),
]
JA_LOAN_FRAMES = [
    ("{X}wokaimashita", "{J}を買いました"),
    ("{X}gasukidesu", "{J}が好きです"),
    ("kyouha{X}nitsuiteshirabeta", "今日は{J}について調べた"),
    ("{X}hadokodesuka", "{J}はどこですか"),
]


def build_mixed(rng):
    rows = []

    def add(kind, romaji, text, eng):
        rows.append((romaji, text, kind, eng))

    # phrase: 名詞のつながり
    for k, phrase in enumerate(NP_PHRASES):
        compact = phrase.replace(" ", "")
        for w in rng.sample(range(len(NP_WRAPS)), 2):
            pre_r, pre_j, suf_r, suf_j = NP_WRAPS[w]
            add("phrase", f"{pre_r}{compact}{suf_r}", f"{pre_j}{phrase}{suf_j}", phrase)
    # phrase: 動詞のつながり
    for k, phrase in enumerate(VP_PHRASES):
        compact = phrase.replace(" ", "")
        for w in rng.sample(range(len(VP_WRAPS)), 2):
            pre_r, pre_j, suf_r, suf_j = VP_WRAPS[w]
            add("phrase", f"{pre_r}{compact}{suf_r}", f"{pre_j}{phrase}{suf_j}", phrase)
    # rare: 一覧の大きい段の語（名詞のつながりの中の1語）
    for word in RARE_WORDS:
        for w in rng.sample(range(len(NP_WRAPS)), 2):
            pre_r, pre_j, suf_r, suf_j = NP_WRAPS[w]
            add("rare", f"{pre_r}{word}{suf_r}", f"{pre_j}{word}{suf_j}", word)
    # paired: 読める語 + 読めない英単語（順番は両方）
    for k, first in enumerate(PAIRED_AMB):
        for step in (0, 11):
            second = PAIRED_DEF[(k * 7 + step) % len(PAIRED_DEF)]
            for a, b in ((first, second), (second, first)):
                w = rng.choice(NP_WRAPS_PAIRED)
                add("paired", f"{w[0]}{a}{b}{w[2]}", f"{w[1]}{a} {b}{w[3]}", f"{a} {b}")
    # sentence: 英語だけの文（文法の合う型だけ）
    seen = set()
    sentences = []
    while len(sentences) < 200:
        kind = rng.choice(("modal", "want", "please", "this", "here"))
        v, n, t = rng.choice(ENG_VERB), rng.choice(ENG_NOUN), rng.choice(ENG_TAIL)
        d = rng.choice(ENG_DET)
        if d == "a":
            d = "an" if n[0] in "aiueo" else "a"
        if kind == "modal":
            words = [rng.choice(ENG_SUBJ), rng.choice(ENG_MODAL), v, d, n]
        elif kind == "want":
            words = [rng.choice(ENG_SUBJ_PLURAL), rng.choice(("want", "need")), "to", v, d, n]
        elif kind == "please":
            words = ["please", v, d, n]
        elif kind == "this":
            words = [rng.choice(("this", "that")), "is", d, n]
        else:
            words = ["here", "is", d, n]
        if t and kind in ("modal", "want", "please"):
            words.append(t)
        key = tuple(words)
        if key in seen:
            continue
        seen.add(key)
        sentences.append(words)
    for words in sentences:
        add("sentence", "".join(words), " ".join(words), " ".join(words))
    # alone: 日本語の助詞のあいだに1語だけ（記録用）
    alone_words = ["name", "game", "time", "home", "note", "mode", "node", "date", "base", "site", "size", "tone", "zone",
                   "house", "mouse", "page", "pipe", "tape", "token", "theme", "region", "session", "route", "image", "menu",
                   "media", "memo", "demo", "domain", "engine", "human", "icon", "info", "make", "take", "use", "share", "hide"]
    for word in alone_words:
        w = rng.choice(NP_WRAPS)
        add("alone", f"{w[0]}{word}{w[2]}", f"{w[1]}{word}{w[3]}", word)
        w2 = rng.choice(NP_WRAPS)
        add("alone", f"{w2[0]}{word}{w2[2]}", f"{w2[1]}{word}{w2[3]}", word)
    return rows


def build_ja(rng):
    rows = []
    for romaji, jp in JA_NOUNS:
        frames = rng.sample(JA_NOUN_FRAMES, 5)
        for fr, fj in frames:
            rows.append((fr.replace("{X}", romaji), fj.replace("{J}", jp), "noun", romaji))
    for romaji, jp in JA_VERB_STEMS:
        forms = rng.sample(JA_VERB_FORMS, 4)
        for sr, sj in forms:
            pre_r, pre_j = rng.choice(JA_VERB_PRE)
            rows.append((f"{pre_r}{romaji}{sr}", f"{pre_j}{jp}{sj}", "verb", romaji))
    for romaji, jp in JA_PARTICLE_SENTENCES:
        rows.append((romaji, jp, "particle", ""))
    for romaji, jp in JA_LOAN:
        for fr, fj in rng.sample(JA_LOAN_FRAMES, 3):
            rows.append((fr.replace("{X}", romaji), fj.replace("{J}", jp), "loan", romaji))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()
    rng = random.Random(20261021)
    mixed = build_mixed(rng)
    ja = build_ja(rng)
    # 重複を除く
    def dedupe(rows):
        seen, out = set(), []
        for r in rows:
            if r[0] not in seen:
                seen.add(r[0])
                out.append(r)
        return out
    mixed, ja = dedupe(mixed), dedupe(ja)
    from collections import Counter
    print("mixed", len(mixed), dict(Counter(r[2] for r in mixed)))
    print("ja", len(ja), dict(Counter(r[2] for r in ja)))
    if args.stats:
        return
    head_m = ("# 英単語と重なるローマ字の試験（英語にしたい文）。tools/make_allenglish_tests.py で作成（手で書いた語のつなぎ合わせ、実装を見ない打ち方）。\n"
              "# 列: ローマ字<TAB>期待する文<TAB>区分<TAB>英語の部分（空白は語の間）<TAB>連番。区分: phrase paired rare sentence alone（alone は記録用で採点しない）\n")
    head_j = ("# 英単語と同じ綴りのローマ字を含む日本語だけの文（英語にしてはいけない文）。tools/make_allenglish_tests.py で作成。\n"
              "# 列: ローマ字<TAB>期待する文<TAB>区分<TAB>重なる英単語<TAB>連番。区分: noun verb particle loan\n")
    (OUT / "allenglish-mixed.tsv").write_text(
        head_m + "".join(f"{r}\t{t}\t{k}\t{e}\tm{i + 1:04d}\n" for i, (r, t, k, e) in enumerate(mixed)), encoding="utf-8")
    (OUT / "allenglish-ja.tsv").write_text(
        head_j + "".join(f"{r}\t{t}\t{k}\t{e}\tj{i + 1:04d}\n" for i, (r, t, k, e) in enumerate(ja)), encoding="utf-8")


if __name__ == "__main__":
    main()
