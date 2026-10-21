"""英語の語のあとに打つ次の変換の試験を作る（2026-10-21）。

IME ではスペースで変換するので、英語の文を1語ずつ（make →変換→確定→空白→ sure →変換）打つ人がいる。
直前に確定した文字が英字の語で終わっているとき、次の変換の英語の判定を英語寄りにする（docs/english-follow.md）。
その試験の表を3つ作る。列は tools/context_convert.sh と同じ（ローマ字<TAB>期待する文<TAB>前の文）。
  tests/conversion/english-follow-word.tsv     英語の1語（日本語にも読める語が中心）を、英語の前の文のあとで打つ。英語になるべき
  tests/conversion/english-follow-ja.tsv       英語の語のあとに日本語の文を打つ（Slack で連絡します ...）。日本語のままであるべき
  tests/conversion/english-follow-control.tsv  日本語のあとに英単語1語を打つ。今までどおり（前の文なしと同じ結果）であるべき
  tests/conversion/english-follow-bare.tsv     英語の語のあとに、英単語と綴りが同じ日本語の語（竹、酒、ペン）だけを1語で打つ。
                                               英語か日本語か決められない（打った人にしか分からない）ので、合否にせず数だけ出す（寄せの代償の目安）
語の一覧と前の文はこのファイルに手で書いてある（決まった順番で作るので、何度流しても同じ表ができる。実装を見て決めていない）。  tests/conversion/english-follow-history.tsv  word と同じ語を、前の文を入力欄の前の文として渡さず、前の語をキーで打って確定してから打つ
                                               （server →変換→確定→空白→次の語）。変換の履歴から直前を取る道の確かめ。tools/english_follow_history.sh
前の文は、末尾に空白があるもの（「make 」）とないもの（変換の履歴から取るときの形）の両方。
  python tools/make_english_follow_tests.py          # tests/conversion/ に書く
  python tools/make_english_follow_tests.py --stats  # 数だけ出す
採点は tools/score_english_follow.py。
"""
import argparse
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "tests" / "conversion"

# 英語の文を1語ずつ打つ人の、直前の確定（英字の語で終わる）
ENGLISH_BEFORE = [
    "I want to ", "Please ", "make ", "Could you", "We should ", "This is the ", "Let me",
    "今日は meeting ", "Thank you for the ", "I think we can ",
]
# 英語の語のあとに日本語を打つ場面の、直前の確定
ENGLISH_BEFORE_JA = ["Slack ", "I want to ", "make ", "今日は meeting ", "Google", "iPhone ", "Please", "Notion "]
JAPANESE_BEFORE = ["今日は", "これは", "資料を", "明日の会議で", "お疲れさまです。"]

# 英語の1語（打つ形）。日本語にも読める語（make: まけ、take: たけ ...）が中心。最後の数語は読めない語（その場で英語になる）
WORDS = """make take same name home game one time some note mode data date base site size tone zone house mouse region
session token theme image domain engine menu page use see share shake wake wipe hide join raise rename reuse erase resume
manage measure define ensure assume mention operate human icon info future vision reason route media memo demo node code
server project button folder update""".split()
MIXED_TAIL = 5  # WORDS の最後の何語が「読めない語」か（記録用）

# 英単語と綴りが同じ日本語の語（1語だけで打つと、英語にも日本語にも読める）
BARE_WORDS = """take sake same hate son min bin mine mare hone ago numa tuna tuba iso saga bingo kohaku dote shake dome hobo sonata
pen banana memo mini domino mania panda home make mate hare tame some name bake kane hon men ken sen ban san ten jin hen kin
kare dare tango kimono karate mama piano demo tomato papa zero nano panama pino""".split()

# 日本語の文の始まり: 助詞・語尾から始まる（英語の語のあとに続く形）と、英単語に重なる日本語の語から始まるもの
PARTICLES = [
    ("de", "で", [("renrakushimasu", "連絡します"), ("kakuninshimasu", "確認します"), ("tsukaimasu", "使います"), ("shirabeta", "調べた")]),
    ("wo", "を", [("tsukau", "使う"), ("kaeta", "変えた"), ("shirabeta", "調べた"), ("okurimasu", "送ります"), ("kakuninshite", "確認して")]),
    ("ga", "が", [("dekimasu", "できます"), ("arimasu", "あります"), ("hitsuyoudesu", "必要です"), ("sukidesu", "好きです")]),
    ("ni", "に", [("okurimasu", "送ります"), ("tsuite", "ついて"), ("shimashita", "しました"), ("kimemashita", "決めました")]),
    ("ha", "は", [("dokodesuka", "どこですか"), ("tsukaemasen", "使えません"), ("benridesu", "便利です"), ("onajidesu", "同じです")]),
    ("to", "と", [("renrakushimasu", "連絡します"), ("hanashimashita", "話しました"), ("kuraberu", "比べる")]),
    ("no", "の", [("hougaii", "ほうがいい"), ("hanashidesu", "話です"), ("kotowokangaeru", "ことを考える")]),
    ("mo", "も", [("tsukaemasu", "使えます"), ("onegaishimasu", "お願いします"), ("kakuninshimasu", "確認します")]),
    ("kara", "から", [("hajimeyou", "始めよう"), ("okutta", "送った"), ("kimasu", "来ます")]),
    ("nitsuite", "について", [("shirabeta", "調べた"), ("hanashimasu", "話します")]),
]


def words_after_english():
    rows = []
    for i, word in enumerate(WORDS):
        for before in ENGLISH_BEFORE:
            rows.append((word, word, before))
    return rows


def japanese_after_english():
    rows = []
    n = 0
    # 英単語に重なる日本語の語から始まる文（組 m の日本語だけの文）
    ja = OUT / "allenglish-ja.tsv"
    if ja.exists():
        for line in ja.read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or not line.strip():
                continue
            p = line.split("\t")
            for k in range(2):
                rows.append((p[0], p[1], ENGLISH_BEFORE_JA[(n + k * 3) % len(ENGLISH_BEFORE_JA)]))
            n += 1
    # 助詞から始まる文（Slack で連絡します）
    for ro, ja_particle, predicates in PARTICLES:
        for pr, pj in predicates:
            for k in range(2):
                rows.append((ro + pr, ja_particle + pj, ENGLISH_BEFORE_JA[(n + k * 3) % len(ENGLISH_BEFORE_JA)]))
            n += 1
    return rows


# 履歴の試験で、キーで打って確定する前の語（その場で英語になる語）
HISTORY_BEFORE = ["server", "project", "button", "folder", "update", "download"]


def words_after_typed_english():
    rows = []
    for i, word in enumerate(WORDS[:-MIXED_TAIL]):
        for k in range(3):
            rows.append((word, word, HISTORY_BEFORE[(i + 2 * k) % len(HISTORY_BEFORE)]))
    return rows


def english_after_japanese():
    rows = []
    for i, word in enumerate(WORDS[:-MIXED_TAIL]):
        for k in range(3):
            rows.append((word, word, JAPANESE_BEFORE[(i + k) % len(JAPANESE_BEFORE)]))
    return rows


def bare_after_english():
    return [(w, w, ENGLISH_BEFORE_JA[i % len(ENGLISH_BEFORE_JA)]) for i, w in enumerate(BARE_WORDS)]


FILES = [
    ("english-follow-word.tsv", words_after_english,
     "# 英語の文を1語ずつ打つ場面（前の確定は英字の語で終わる）。打った1語が英語になることを期待する。tools/make_english_follow_tests.py で作成。列: ローマ字<TAB>期待<TAB>前の文"),
    ("english-follow-ja.tsv", japanese_after_english,
     "# 英語の語のあとに日本語の文を打つ場面。日本語のままであること（英字に化けない）を期待する。tools/make_english_follow_tests.py で作成。列: ローマ字<TAB>期待する文<TAB>前の文"),
    ("english-follow-control.tsv", english_after_japanese,
     "# 日本語のあとに英単語1語を打つ場面。前の文が日本語なので今までどおり（前の文なしと同じ結果）を期待する。tools/make_english_follow_tests.py で作成。列: ローマ字<TAB>語<TAB>前の文"),
    ("english-follow-history.tsv", words_after_typed_english,
     "# 前の語をキーで打って確定してから（変換の履歴が前の文になる）、次の1語を打つ場面。列: ローマ字<TAB>期待<TAB>前に打って確定する語。tools/english_follow_history.sh で流す"),
    ("english-follow-bare.tsv", bare_after_english,
     "# 英語の語のあとに、英単語と綴りが同じ日本語の語だけを1語で打つ場面（英語か日本語か決められない。合否にせず数だけ出す）。tools/make_english_follow_tests.py で作成。列: ローマ字<TAB>語<TAB>前の文"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()
    for name, make, header in FILES:
        rows = make()
        if args.stats:
            print(name, len(rows))
            continue
        text = header + "\n" + "".join(f"{r}\t{e}\t{b}\n" for r, e, b in rows)
        (OUT / name).write_text(text, encoding="utf-8", newline="\n")
        print("wrote", name, len(rows))


if __name__ == "__main__":
    main()
