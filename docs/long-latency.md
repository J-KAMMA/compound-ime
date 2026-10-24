# 長い文の変換の時間（測るだけ）

空白キー1回の時間を、読みの長さごと・段ごとに測る。変換を速くする変更はしない。
測る仕組みは `MYIME_PROFILE` があるときだけ動き、普段の変換の結果は変えない。

## 試験の文

`tests/conversion/long-latency.tsv`（`tools/make_long_latency_tests.py` で作る）。
`tests/conversion/wiki-typing.tsv` と `tests/conversion/context.tsv` の文から、
目標の字数が 10・20・40・60・80・120 字ほどの組を各 36 文ずつ作る（40 字までは1文、
それより長い組は句点でつないだ複数の文）。各回の最初の5変換は模型の読み込みとして捨てるので、
組ごとに30文以上が残る。列は「組・ローマ字・前の文・元の文」。

```
python tools/make_long_latency_tests.py --out tests/conversion/long-latency.tsv
python tools/long_latency_prepare.py tests/conversion/long-latency.tsv <作業フォルダー>
```

`long_latency_prepare.py` は、前の文なし（`long-<組>.tsv`）、前の文あり（`-ctx.tsv`）、
句読点（`.` と `,`）で分けた句（`-split.tsv` と `-split-map.tsv`）を作る。
組 `w` は、`-split-map.tsv` を結果のフォルダーにも写す（`long_latency_report.py` がそこを読む）。

## 流し方

GitHub の Linux test を手動で流し、試験の組に `["w"]` を入れる（ほかの組は流さない）。

```
groups: ["w"]
```

組 `w` は1つの計算機で、変換の処理を1つだけにして、次の5条件を同じ条件で3回ずつ流す
（合計 5 × 6組 × 36文 × 3回）。1字 125 ミリ秒で打つ2条件があるので、2〜3時間ほどかかる。
結果は成果物 `linux-results` の `long-latency-report.txt` に入る。手元に組み立てた一式があれば、
同じことを `bash tools/run_tests.sh w <engine のフォルダー> <model.gguf> <このリポジトリ> <結果のフォルダー>`
で流せる。`test` の制限時間は 330 分にしてある。

- `plain`: 人工知能の上限なし・先回りなし（前の文なし）
- `plain-ctx`: 同じ（前の文あり）
- `split`: 句読点で分けた句を別々に変換（時間だけ。正解は見ない）
- `real-pf`: 利用者の PC と同じ既定（上限 1000 ミリ秒、先回り 120 ミリ秒）で1字 125 ミリ秒ずつ打ち、
  打ち終わってから空白キーまで 300 ミリ秒待つ（利用者が考える間。先回りが働ける時間）
- `real-nopf`: 同じで、先回りだけ止める（`MYIME_PREFETCH_DELAY=0`）

## 段の分け方

`tools/apply_latency_profile.py` の記録を `tools/long_latency_report.py` が集計する。
空白キーの1回を、Mozc の変換、人工知能側の呼び出し、全文の評価（all_zenzai）、
前後の文での並べ替え、一括採点、選び手、その他に分ける。一括採点は前後の文の並べ替えか
選び手の内側で動くので、その時間を別の段として記録し、内側の段からは引いて表に出す。

llama.cpp の評価は、2語片以上をまとめて計算した回を **prefill（読み込み）相当**、
1語片だけを計算した回を **decode（1文字ずつの生成）相当** として数える
（`<段>_pre_n/_pre_us`、`<段>_step_n/_step_us`。従来の `_dec_n/_dec_us` は全部の評価）。

## 結果の表

`long-latency-report.txt` は次を出す。

1. 読みの長さ別の段ごとの時間（中央値、prefill/decode の内訳、語片の使い回し）
1b. 前の文あり・なしの時間（前の文ありの文脈の門を含む）
2. 先回りあり・なしの時間と、1秒の上限に当たった割合（分母は空白キーの変換のうち最初の5回を除いた数）
3. 句読点で分けたときの時間
4. 同じ機械での3回の中央値と、幅（ばらつき）
5. 案 (a)(b)(c) の見込み

## 案の見込みの計算

- (a) 先回りを長い文にも広げる: 同じ打つ速さ（1字 125 ミリ秒）と、打ち終わりから空白キーまでの
  300 ミリ秒の待ちでの `real-pf` と `real-nopf` の空白キーの中央値の差。上限に当たった割合の変化も並べる。
  上限の集計は、空白キーの変換（`kind=conv`）の間だけ数え、最初の5回を除く
  （先回り・予測・選び手の呼び出しは数えない）。
- (b) KV キャッシュを前回の変換から使う: 全文の評価で渡した語片と新しく計算した語片から、
  いまの使い回しの割合を出す。「読みが1字だけ変わった」と仮定し、新しい語片を読み1字あたりの
  語片数としたときの、評価の語片と全体の時間の減り方（上限）。
- (c) 句読点で区切る: `split` の各句の時間を文ごとに足した中央値と、`plain` の文の中央値の比。

いずれも測った数字からの計算で、案を作ったものではない。変換の正しさ（文脈が切れること）は
測っていない。

## この環境で確かめたこと

- `tools/make_long_latency_tests.py` で `tests/conversion/long-latency.tsv`（各組36文）を作れた。
- `tools/long_latency_prepare.py` で各組の入力と句分けを作れた。
- 作り物の記録を入れたフォルダーで `tools/long_latency_report.py` が最後まで動き、表を出せた。
- 本物の Mozc と人工知能の重みは、この環境では組み立てられない（通信なし、Bazel の控えなし）。
  そのため、本物の時間の数字はまだ無い。上の組 `w` を GitHub で流すと出る。
