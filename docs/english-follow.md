# 直前に確定した文字が英語なら、次の変換を英語寄りにする（2026-10-21）

利用者の様子: 英語の文を1語ずつ打つ（`make` →変換→確定→空白→ `sure` →変換）。英語の判定（`SplitEnglish`、[all-english.md](all-english.md)）は1回の変換の中の打った並びだけを見るので、`make`（まけ）・`take`（たけ）・`same`（さめ）のように日本語にも読める語が1語だけだと日本語になっていた。

## 直前の確定をどこから取るか

`converter/converter.cc` の `Converter::MarkEnglishSpans`（空白で変換するとき英語の部分を決める所）が、次の順で、取れたものだけを見る（`native/jaen-detector/converter_reading_check.inc` の `PreviousEndsInEnglish`）。

1. 入力欄の前の文: `request.GetSurroundingContext()` の左側（クライアントが `preceding_text` で渡す。`apply_jaen_integration.py` が前後の文の並べ替えに既に使っているのと同じもの）。空でなければこれだけを見る。
2. session が覚えている「さっき確定した文字」: `request.context().recent_committed_text`。前の文がないとき（1 が空）だけ、session が詰める。仕組みは下の「session の記憶」。
3. 変換の履歴: `Segments` の履歴の最後の文節の先頭の候補（直前に確定した語）。ただし下の理由で、空白を打ったあとはほぼ空。2 が入ってからは、2 が取れない（捨てた・期限切れ）ときの最後の手段。

空白を除いた最後の文字が英字（A〜Z、a〜z）なら「直前は英語」とする（`jaen::EndsWithEnglishWord`）。`make`、`make `、`I want to `、`今日は Slack `、`iPhone` は英語。`今日は`、`Hello, `、`2024 `、空は英語でない（記号・数のあとは寄せない）。

## 履歴の道（3）が効かなかった理由（2026-10-21 調べ）

最初の版（`187f2a0`）の GitHub の組 n（実行 39563261171）では、履歴から取る道の試験（`english-follow-history.tsv`、183 行）が、止めた版（`MYIME_ENGLISH_FOLLOW=off`）と**1行も違わなかった**（結果の3列が 183 行とも同じ。英語の1語 111 / 111）。前の文を渡す表（word、660 行）は 460 行が違い、英語の1語が 420 → 620 に増えている。つまり寄せの規則そのものは働いていて、履歴の道だけが、何も入らないまま（`PreviousEndsInEnglish` が偽）だった。

原因は Mozc の作り（`mozc/src` を読んで確かめた。履歴を消す呼び出しの経路）:

- 試験の手順（`tools/english_follow_history.sh`）は、前の語を打つ→空白で変換→Enter で確定→**空白**→次の語、の順。
- 確定した文節は、`EngineConverter` が `Converter::FinishConversion` で `Segments` の履歴に入れる。ここまでは残る。
- 確定のあと session は「未入力」（PRECOMPOSITION）の状態になる。ここで空白を打つと、`Session::SendKeyPrecompositionState` →（`INSERT_SPACE`）`InsertSpaceHalfWidth` が「空白だけのキー」をアプリへそのまま返す（`EchoBackAndClearUndoContext`）。その `Session::EchoBack` が `EngineConverter::Reset()` を呼び、`Converter::ResetConversion` が `segments->Clear()` する。**履歴ごと消える**。（`EngineConverter::Reset()` のコメントにも、履歴を消すために構成中でも ResetConversion を呼ぶ、と書いてある）
- 同じことは `Session::TestSendKey` の中でも起きる（未入力のとき、空白だけのキーは `EchoBackAndClearUndoContext`）。Windows の画面側（`win32/tip`）は、`ImeProcessKey` で `TestSendKey` を呼び、「食べない」と返ってきたキーは `SendKey` を呼ばない。確定のあとの空白は、Windows でも session には TestSendKey だけが届き、そこで履歴が消える。
- 空白を打たない場合は、確定したあと最初の文字で組み立てが始まるとき（`OnStartComposition`）、前の文がなく、revision も変わらなければ履歴は残る（`has_preceding_text()` が偽のとき `revision_changed` のときだけ消す）。つまり「空白を打つと消える」のであって、履歴の作り自体が壊れているのではない。

動作での確かめは、次の GitHub の組 n の `english-follow-cause.tsv` で行う（記憶だけを `MYIME_ENGLISH_FOLLOW_MEMORY=off` で止め、確定のすぐあと（nospace）と空白のあと（space）を比べる。上の読みが正しければ、nospace は英語が増え、space は増えない）。この版を作った時点では、動かして確かめていない（本物の Mozc を手元でビルドできなかった）。読んだ範囲と、過去の組 n の記録（上の 183/183 一致）が、理由の根拠。

## session の記憶

履歴が空白で消えるので、IME が自分で覚える。`native/jaen-detector/recent_commit.h` の `jaen::RecentCommit` を、`Session`（入力欄ごとの会話。作り直されれば一緒に消える）が1つ持つ（`apply_jaen_integration.py` が `session/recent_commit.h` として置き、`session.h`・`session.cc` に足す）。

**足すもの**（`Session::NoteRecentAfter`。`SendKey`・`TestSendKey`・`SendCommand` のどの戻り方でも、呼び出しの終わりに見る）

- 確定した文字: `Output` の `result`（`type` が STRING）。変換・サジェスト・`COMMIT_RAW_TEXT`・`SUBMIT` など、どの確定の経路でも同じ。
- 変換を通らずアプリへ返したキー（`consumed` が偽）: 空白、`key_code` が印字できる文字（Shift つきの大文字も）、`TEXT_INPUT` の `key_string`。変換の組み立て中のキーは足さない（確定のときに result で足す）。
- 覚えるのは最後の 64 字（文字単位、UTF-8 の途中で切らない）。

**使うとき**: 組み立ての最初のキー（`SendKeyPrecompositionState` が入力欄の前後の文を session に控える所）で、`client_context.recent_committed_text` に詰める。前の文（`preceding_text`）が空でないときは詰めない。クライアントが自分でこの欄を入れてきても、その場で消す（`commands.proto` に足した欄 101。クライアントが使う欄ではない）。期限は、この詰める瞬間に見る（変換が始まるのが詰めたあとの数秒でも、そのまま）。

**捨てるとき**

| 場面 | 見るもの |
|---|---|
| 入力欄が変わった | 入力の `context.revision` が前と違う（Windows の画面側は、入力欄の焦点が替わるたびに増やす。`OnSetFocus`）。キーを処理する前に見る |
| 会話が作り直された | `Session` ごと消える |
| 位置変更・取り消しの知らせ | `RESET_CONTEXT`、`MOVE_CURSOR`、`SWITCH_INPUT_FIELD_TYPE`、`UNDO`、`UNDO_OR_REWIND`、`REVERT`、`CONVERT_REVERSE` |
| アプリの文字を消した | `Output` の `deletion_range`（取り消しなど）、確定の `cursor_offset` が 0 でない |
| カーソルを動かすキー | 矢印・Home・End・PageUp/Down・Enter（改行）・Tab・Delete・Insert・Escape・ファンクションキー、Ctrl/Alt つきのキー（貼り付けなど） |
| 覚えた分より前に戻った | Backspace で最後の 1 字ずつ消し、空になったら（それ以上は何が前か分からない）。空のまま Backspace しても空 |
| IME を切った | 切った瞬間（DIRECT になったとき）に捨てる。切っている間のキーは Windows の画面側が session に送らない（`HandleKey`）ので、覚えが古くなりうるため。この項目は依頼の「捨てる条件」に足した |
| 時間 | 最後に足してから 60 秒。足すたびに数え直す（打っている間は残る）。試験のためだけに `MYIME_ENGLISH_FOLLOW_TTL_MS` で替えられる |

字を足さない・何もしないもの: 修飾キーだけ、キーを離した知らせ、ON・OFF・変換・無変換・かな・英数・半角/全角・漢字・カタカナ・CapsLock（方式を替えるだけで字もカーソルも動かない）。

**打った文字を残さない**: 記憶は `RecentCommit` の文字列だけ。ログ・ファイルには書かない（`LOG`・`DLOG` なし）。`recent_committed_text` は session の内側の入力（`client_context`）にあるだけで、出力（`Output`）には出さない。

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

環境変数 `MYIME_ENGLISH_FOLLOW=off`（変換エンジンを再起動する）。既定は有効。寄せの規則と、session の記憶（足すのも、詰めるのも）が一緒に止まる。`MYIME_ALL_ENGLISH=off`（文脈の段そのもの）で止めたときも働かない。

試験・切り分けのための環境変数（普段は使わない）: `MYIME_ENGLISH_FOLLOW_MEMORY=off` は session の記憶だけを止める（前の文・履歴の道は残る）。`MYIME_ENGLISH_FOLLOW_TTL_MS=<ミリ秒>` は、覚えておく時間（既定 60000）を替える。

## 試験

表は `tools/make_english_follow_tests.py` で作る（語の一覧と前の文は中に書いてある）。

| 表（tests/conversion/） | 行 | 内容 | 期待 |
|---|---|---|---|
| `english-follow-word.tsv` | 660 | 前の文 `I want to ` / `make ` / `Could you` ... を渡して、英語の1語（make、take、same ...）を打つ | 英語になる |
| `english-follow-history.tsv` | 183 | 同じ1語を、前の文を渡さず、前の語（server など）をキーで打って確定してから打つ | 英語になる |
| `english-follow-memory.tsv` | 216 | 前の文を渡さず、確定のあとの操作（場面）を9通りに替える。残るはずの場面: 空白・TEST_SEND_KEY だけの空白・同じ入力欄（revision 固定）・空白→Backspace→空白。捨てるはずの場面: 覚えた分より前までの Backspace・左矢印・RESET_CONTEXT・入力欄の変更（revision 1→2）・IME を切って入れ直す | 残る場面は英語になる、捨てる場面は止めた版と同じ |
| `english-follow-expire.tsv` | 24 | 同じ形で、覚える時間を 3 秒に縮め、空白のあと待たない（nowait）／3.5 秒待つ（wait） | nowait は英語、wait は止めた版と同じ |
| `english-follow-cause.tsv` | 24 | 履歴の道の切り分け。記憶だけを止めて、確定のすぐあと（nospace）と空白のあと（space）を比べる | 合否にしない（nospace は増え、space は増えない見込み） |
| `english-follow-ja.tsv` | 948 | 英語の語のあとに日本語の文（`Slack` ＋ `derenrakushimasu`、竹を、酒から ...）。組 m の日本語の文と助詞から始まる文 | 日本語のまま |
| `english-follow-control.tsv` | 183 | 日本語のあとに英単語1語 | 前の文を見ない版と同じ |
| `english-follow-bare.tsv` | 63 | 英語の語のあとに、英単語と綴りが同じ日本語の語（take、酒の sake）を1語だけ | 決められない（数だけ） |

手元（Mozc なし）: `native/jaen-detector/jaen_trial.cc`（入力の行を「ローマ字<TAB>直前に確定した文字」にできる。`FOLLOW_OFF=1` で直前を無視）を `tools/english_follow_trial.py` で流す。

```
g++ -std=c++20 -O2 -I native/jaen-detector native/jaen-detector/jaen_trial.cc native/jaen-detector/jaen_detector.cc -o jaen_trial
JAEN_DICT=<mozc>/src/data/dictionary_oss python tools/english_follow_trial.py ./jaen_trial <作業の場所> <一覧の場所> [CTX=follow_margin=1000]
```

単体試験は `native/jaen-detector/jaen_detector_test.cc`（`EndsWithEnglishWord`、`previous_english` の動き、`follow_margin` の効き）と、記憶だけの `native/jaen-detector/recent_commit_test.cc`（空白・英字を足す、Backspace、カーソルのキー、revision、60 秒、64 字、方式のキー）。

```
g++ -std=c++20 -O2 -I native/jaen-detector native/jaen-detector/recent_commit_test.cc native/jaen-detector/jaen_detector.cc -o recent_commit_test && ./recent_commit_test   # 最後の行 SUMMARY 0
```

Mozc を通す試験は GitHub の組 `n`（`tools/run_tests.sh n`）。前の文を渡す形は `tools/context_convert.sh`、前の語を打って確定する形（history）は `tools/english_follow_history.sh`、場面を替える形（memory・expire・cause）は `tools/english_follow_memory.sh`。既定の版と `MYIME_ENGLISH_FOLLOW=off` の版を流し、`tools/score_english_follow.py`（memory・cause は表の4列目の場面ごと）が並べる。history の表は、確定のあとの空白が session の記憶に入る形になっているので、この版からは記憶の効き目を測る（前は履歴の道だけを測っていた）。

組 `n` のあとの見方: `english-follow-history-score.txt`（この版の目的の数: 英語の1語 111/183 から増えるか、減りがないか）、`english-follow-memory-score.txt`（残る場面が増え、捨てる場面が止めた版と同じ）、`english-follow-expire-score.txt`、`english-follow-cause-score.txt`（履歴の道の切り分け）、`english-follow-ja` と `control`（日本語の文・日本語のあとの語が変わらないか）。memory・expire の表の手順は、試験用の道具 `session_handler_main` の新しい命令 `SET_REVISION`（入力欄の印を付ける。`apply_jaen_integration.py` が足す）を使う。

## 結果（手元の試し。2026-10-21）

### session の記憶（この版）の手元の確かめ（2026-10-21）

- `recent_commit_test.cc`: 全部通った（SUMMARY 0）。
- `jaen_trial`（Mozc なし。手元で組んだ設定は、下の表の数字を再現できなかった: 同じ表で止めた版 420 のところ 630 など。相対の目安だけ）: history の表 183 行を、前の文なしで流すと英語の1語が 174、session が `server ` のような直前の確定を渡せたとして流すと 183。**Mozc を通した確かめではない**。
- `session.cc`・`session.h`・`commands.proto` への足し込みは、`apply_jaen_integration.py` の差し替えの位置（見つける文字列が1つだけか）を、手元にある古い版の Mozc の作業の木に当てて確かめた。**Mozc 本体としてはビルドしていない**（手元にビルドの場所がない）。型・関数の名前は同じ木の `session.cc` などで確かめて書いたが、コンパイルは GitHub の組が最初。

組 n の前（止めた版との差）: 最初の版では history 183 行が 111 → 111（増えた 0。止めた版と1行も違わない）。この版の後の数字は、まだない（GitHub で流してから）。

### 最初の版（履歴の道だけ）の手元の試し

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
- 履歴が空白で消える理由は、Mozc のソースを読んだ結果と、過去の組 n の記録（history が止めた版と全行一致）による。動かして確かめるのは組 n の cause の表。
- **確かめていないこと（Windows の画面側）**: 確定のあとの空白が session に届くかは、`win32/tip` のソースを読んだだけで、実機では確かめていない。読んだ範囲では、半角の空白は `TestSendKey`（食べないと返るキー）か、`TestKey` を呼ばないアプリでは `SendKey` で届き、どちらでも記憶に入る。ただし、(1) 入力方式がひらがなで、空白の入力が「入力方式に従う」（既定）だと、空白は全角になって変換の入力に入る（`InsertSpaceFullWidth`）ので、この仕組みは働かない（試験の手順は半角になる設定）、(2) アプリが同じキーに `TestKey` と `Key` の両方を呼ぶと二重に足す、(3) IME を切っている間のキー、アプリ側の貼り付け・マウスでの位置変更・文字の削除は session に届かない（`context.revision` の変化、`RESET_CONTEXT` などの知らせがあれば捨てるが、画面側がマウスでの位置変更を session に知らせているかは確かめていない）、(4) 期限は 60 秒なので、その間に位置を変えると、古い語で寄せることがある。
- 前の文を渡さないアプリでだけ働く。前の文が渡せるときは、記憶は見ない（渡された文が優先）。
