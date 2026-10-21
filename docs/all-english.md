# 打った英字の並びが英単語として読めるなら英語にする（2026-10-21）

利用者の希望: 「英語の単語は、途中がローマ字として日本語に読めても、全部英語になるようにしてほしい」。

## 仕組み（`native/jaen-detector/jaen_detector.cc`）

英語の切り分け（`SplitEnglish`）は2段になりました。

1. **最初の段（今までどおり）**: 打ち方に日本語にない形（`l` `x` `v` `c` の小さいかな、母音のない並び）がある語、5文字以上の厳選した語、かなが辞書にない・自然な読みでない語を英語にします。
2. **文脈の段（新しい）**: 最初の段で日本語のままになった部分ごとに、次の2つの費用を Mozc の辞書と接続の費用で比べます。
   - (a) その部分を全部日本語の語で読む一番安い費用
   - (b) 一覧の英単語（または英単語のつながり）を入れてよい分け方での一番安い費用
   (b) が (a) より十分安いときだけ、英語にします。助詞・活用が続いて自然に読める部分は (a) が安く、日本語のままです。

英語の費用の付け方（`ContextCosts`、既定の値は `DefaultContextCosts()`）:

| 項目 | 値 | 意味 |
|---|---|---|
| 英単語1語 | 2500 + 300 × 文字数 | 辞書の語の費用と同じ尺度 |
| よく使う語・厳選した語 | −800 | SCOWL 水準20以下、厳選した語 |
| 一覧の大きい段の語 | +3000 | SCOWL 水準36〜70（既にある `signal-words.txt`）。人名・地名が多いので高くする |
| 1〜2文字の語 | +1000（1文字はさらに +3000） | a、i、to、be |
| 助詞の綴りの語（ha ga wo ni no de to mo he ya ka wa ne yo） | +2000 | 日本語の助詞のほうを取る |
| 日本語から英語へ変わる | +2000 | 英語が続く間は払わない |
| 英語にするために安くなければならない差 | 2000（英単語1語だけで英語の隣でもないときは 3500） | 日本語としても読める1語は決め手が弱いので厳しくする |

走り（英語が続く部分）は、打った文字の区切りから区切りまでを、一覧の語で隙間なく埋められる部分です。語の境は区切りの途中でもかまいません（`issome` の `s`）。走りの最初や最後が助詞の綴りや `a` のときは、日本語の助詞を英語に取り込んだ形なので使いません。1〜2文字だけの走りも使いません。

## 決め方の表

| 場面 | 例（打った形） | 決め方 | 結果 |
|---|---|---|---|
| 助詞・活用が続き、日本語として自然に読める | `takewotabeta`（竹を食べた）、`homemasu`（褒めます）、`kyouhagojimadehatarakimasu` | (a) が安い | 日本語 |
| 日本語の文の中に英単語1語だけ（日本語としても読める） | `konotakewotsukau`、`kyouhasame` | 差が 3500 に届かない（日本語としても読めるので決め手がない） | 日本語（従来どおり） |
| 日本語の語の一部になる | `onegai`（お願い）、`nodedekimasen`（のできません）、`demoikimasu` | (a) が安い | 日本語 |
| 英単語のつながり（日本語として読むと不自然） | `kyouhamakesureshimasu`、`sametimeni`、`takecareshitekudasai` | (b) が安い | 英語（`make sure`、`same time`、`take care`） |
| 英語として確かな語の隣 | `samegoogledeshita`、`takescreenshot` | 英語が続くので切り替えの費用がない | 英語 |
| 英語だけの文 | `pleasemakesureyoucomehome` | 日本語の読みは不自然 | 英語（語の境は空白で表示） |
| 助詞の綴りの語が英語の間にある | `wantnoserverwotsukau` | 助詞の綴りの語は費用が高く、走りの端にも置けない | `want` `server` は英語、`no` は日本語 |
| 英語と同じ綴りのカタカナ語 | `penwokaimashita`、`bananagasukidesu` | 日本語の辞書のカタカナ語（かなそのもののカタカナ）として自然に読める | 日本語 |
| 文頭の短い英単語（`you`、`i`） | `youmustrenamethefile` | 先頭でも日本語から英語への切り替えの費用を払うので、日本語の語（よう、い）と競り合う | `must rename the file` は英語、`you` は日本語のまま（取りこぼし） |

## 止める方法

環境変数 `MYIME_ALL_ENGLISH=off` で文脈の段を止めます（前後の比べ用。変換エンジンを再起動する）。

## 手元の確かめ

`native/jaen-detector/jaen_trial.cc` に Mozc の辞書（`<mozc>/src/data/dictionary_oss`）を渡すと、Mozc なしで文脈の段まで動きます（`JAEN_DICT=<dir> CONTEXT=1 jaen_trial <作業の場所> <一覧の場所>`、`CTX=名前=値,...` で費用を替えられる）。費用の計算は Mozc の `ReadingCost` と同じで、だて 6213、いであ 7064 など `apply_jaen_integration.py` の注に書いてある値と一致します。本物の変換とは、利用者の辞書・英語の別名・打ち間違いの直しがない点で違います。

## 試験

- `tests/conversion/allenglish-mixed.tsv`（英語にしたい文）と `allenglish-ja.tsv`（日本語だけの文）。`tools/make_allenglish_tests.py` で作る（語の一覧は中に書いてある）。採点は `tools/score_allenglish.py`。
- GitHub の組 `m`（`tools/run_tests.sh m`）が、既定の版と止めた版（`MYIME_ALL_ENGLISH=off`）の両方で流し、差を出す。
