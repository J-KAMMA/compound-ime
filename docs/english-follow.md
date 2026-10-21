# 直前に確定した文字が英語なら、次の変換を英語寄りにする（2026-10-21）

利用者の様子: 英語の文を1語ずつ打つ（`make` →変換→確定→空白→ `sure` →変換）。英語の判定（`SplitEnglish`、[all-english.md](all-english.md)）は1回の変換の中の打った並びだけを見るので、`make`（まけ）・`take`（たけ）・`same`（さめ）のように日本語にも読める語が1語だけだと日本語になっていた。

## 直前の確定をどこから取るか

`converter/converter.cc` の `Converter::MarkEnglishSpans`（空白で変換するとき英語の部分を決める所）が、次の順で取る（`native/jaen-detector/converter_reading_check.inc` の `PreviousEndsInEnglish`）。

1. 入力欄の前の文: `request.GetSurroundingContext()` の左側（クライアントが `preceding_text` で渡す。`apply_jaen_integration.py` が前後の文の並べ替えに既に使っているのと同じもの）。空でなければこれだけを見る。
2. 空なら変換の履歴: `Segments` の履歴の最後の文節の先頭の候補（直前に確定した語）。

空白を除いた最後の文字が英字（A〜Z、a〜z）なら「直前は英語」とする（`jaen::EndsWithEnglishWord`）。`make`、`make `、`I want to `、`今日は Slack `、`iPhone` は英語。`今日は`、`Hello, `、`2024 `、空は英語でない（記号・数のあとは寄せない）。

## 寄せ方の規則

`SplitEnglish` の最後の引数 `previous_english`（`ContextCosts::follow_margin`）。文脈の段で日本語のまま残った最初の部分について、次の**全部**が当てはまるときだけ働く。

- 直前が英語
- 入力の最初から終わりまでが、まるごと一覧の英単語**1語**（`makesure` のような2語以上、`makewotabeta` のように日本語が残る並びは対象外）
- その語を英語の隣として比べる: 日本語から英語への切り替えの費用（run_start 2000）を払わず、最初を名詞とつなぐ。英語にするための差は `follow_margin` = 2000（1語だけの決め手の弱さ alone_margin 3500 は使わない）

当てはまらない（助詞・活用が続く、入力の途中の語、直前が日本語）ときは、今までの計算をそのまま使う。`follow_margin` が 0 以下なら働かない。

この規則で、次の打つ並びが日本語の文として自然（`takewotabeta`、`samegaarimasu`、`sakekarahajimeyou`）なら日本語のまま。語のあとに日本語が続けば、その部分が残るので対象外になる、という構造で守っている（費用の比べ方で守っているのではない）。

### 値をどう決めたか

手元の試験（下の表）で `follow_margin` を替えて数えた（英語の1語の取れた数 / 英単語と綴りが同じ日本語の語を1語だけ打って英語になった数）。値が大きいほど弱い。

| follow_margin | 1語が英語になった（660） | 日本語の1語が英語になった（63、合否にしない） |
|---|---|---|
| 止める（0 以下） | 420 | 1 |
| 4000 | 450 | 1 |
| 3000 | 530 | 17 |
| 2000（既定） | 630 | 37 |
| 1000 | 650 | 49 |
| 1 | 660 | 55 |

英語の1語と、日本語の1語（竹・酒・ペン）は、1語だけでは費用の差で分けられない（同じ尺度の両端）。2000 は、既に「英語の隣」に使っている差（`margin`）と同じ値で、新しい調整値を足さないために選んだ。1語だけの並びは、前が英語なら英語を取る、という割り切り。

## 止める方法

環境変数 `MYIME_ENGLISH_FOLLOW=off`（変換エンジンを再起動する）。既定は有効。`MYIME_ALL_ENGLISH=off`（文脈の段そのもの）で止めたときも働かない。

## 試験

表は `tools/make_english_follow_tests.py` で作る（語の一覧と前の文は中に書いてある）。

| 表（tests/conversion/） | 行 | 内容 | 期待 |
|---|---|---|---|
| `english-follow-word.tsv` | 660 | 前の文 `I want to ` / `make ` / `Could you` ... を渡して、英語の1語（make、take、same ...）を打つ | 英語になる |
| `english-follow-history.tsv` | 183 | 同じ1語を、前の文を渡さず、前の語（server など）をキーで打って確定してから打つ | 英語になる |
| `english-follow-ja.tsv` | 948 | 英語の語のあとに日本語の文（`Slack` ＋ `derenrakushimasu`、竹を、酒から ...）。組 m の日本語の文と助詞から始まる文 | 日本語のまま |
| `english-follow-control.tsv` | 183 | 日本語のあとに英単語1語 | 前の文を見ない版と同じ |
| `english-follow-bare.tsv` | 63 | 英語の語のあとに、英単語と綴りが同じ日本語の語（take、酒の sake）を1語だけ | 決められない（数だけ） |

手元（Mozc なし）: `native/jaen-detector/jaen_trial.cc`（入力の行を「ローマ字<TAB>直前に確定した文字」にできる。`FOLLOW_OFF=1` で直前を無視）を `tools/english_follow_trial.py` で流す。

```
g++ -std=c++20 -O2 -I native/jaen-detector native/jaen-detector/jaen_trial.cc native/jaen-detector/jaen_detector.cc -o jaen_trial
JAEN_DICT=<mozc>/src/data/dictionary_oss python tools/english_follow_trial.py ./jaen_trial <作業の場所> <一覧の場所> [CTX=follow_margin=1000]
```

単体試験は `native/jaen-detector/jaen_detector_test.cc`（`EndsWithEnglishWord`、`previous_english` の動き、`follow_margin` の効き）。

Mozc を通す試験は GitHub の組 `n`（`tools/run_tests.sh n`）。前の文を渡す形は `tools/context_convert.sh`、履歴の形は `tools/english_follow_history.sh`。既定の版と `MYIME_ENGLISH_FOLLOW=off` の版を流し、`tools/score_english_follow.py` が並べる。

## 結果（手元の試し。2026-10-21）

| 場面 | 前（止めた版） | 後（既定） |
|---|---|---|
| 英語の1語（前の確定が英語）660 行 | 英語 420 | 英語 630 |
| 英語の語のあとの日本語の文 948 行 | 英字に化けた 6（峰があります・峰を買いました・東京まで行きます が各2行。この変更の前から） | 6（同じ行。増えなかった） |
| 日本語のあとの英単語1語 183 行 | — | 結果が変わった 0 |
| 日本語の語を1語だけ打つ 63 行（合否にしない） | 英語 1 | 英語 37 |

取れなかった語: `note`、`site`、`demo`（どの前の文でも 10 行ずつ。理由は調べていない）。

## 分かっていること・分からないこと

- 前の文が `.` `,` `)` や数で終わるときは寄せない（新しい文の頭と見なす）。
- 英語の語のあとに、日本語の語を1語だけ打つと、英単語と綴りが同じもの（take、sake、pen、banana ...）は英語になる（上の最後の行。63 語のうち 37）。これは規則の代償で、日本語の文の形（助詞が続く）なら起きない。「日本語の文」の表（948 行）は、どの行も1語のあとに日本語が続くので、この代償は測れない。測るのは最後の表。
- `to`、`a`、`I` のような1〜2文字の語は、文脈の段が 1〜2 文字の走りを使わないので、寄せの対象外（今までどおり日本語の助詞・読みが優先）。
- Mozc 本体（`GetSurroundingContext`、`history_segment` の使い方、履歴が確定のあとに残るか、空白の入力が履歴を消さないか）は、手元で組み立てて確かめていない。GitHub の組 `n` で確かめる。
