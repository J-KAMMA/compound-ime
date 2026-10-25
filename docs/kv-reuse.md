# 打鍵をまたいだ KV キャッシュの使い回し

長い文の変換で、打つたびに人工知能（Zenzai、llama.cpp）へ同じ問いの前半を読み直さないようにする。
問いの並べ方は変えない（変えると出力が変わりうるため）。

## いまの持ち方と、消えている単位

- 変換エンジン（Swift）の `ZenzContext` は、プロセスで1つの模型と文脈を共有する（`Zenz.swift` の `SharedZenzCache`）。
  文脈の中の KV は列（`evalSeqId` = 0、入力予測 = 1、一括採点 = 2〜17）ごとに持ち、
  `prevInputBySeq` に「その列に入れた語片」を覚えている。
- `ZenzContext.getLogits` は、呼ばれるたびに今回の語片と `prevInputBySeq` の共通の前半を数え、
  `llama_kv_cache_seq_rm` で違う後ろを消して、そこから `llama_decode` する。
  つまり使い回しの単位は「列」で、同じ列に最後に入れた問い＋候補の後ろだけが次の材料になる。
- 1回の変換の中では、列 0 にいろいろな形の問いが順に入る。全文の候補の評価（`ZenzCandidateEvaluator`）、
  前後の文での並べ替え（`contextPriorWinner` は前の文ありの問いと、前の文を外した問いの2つ）、
  選び手の採点、候補をまとめた一括採点（`tools/apply_batch_score.py`。列 0 を共通の前半まで切り、
  候補の列へ写し、最後に列 0 を「問い＋先頭の候補」に置き直す）である。
- そのため、打鍵の境目で列 0 に残っている問いは、最後に走った段のものになる。前の文を外した問いや
  一括採点の問いが最後だと、次の打鍵の「前の文あり・読みが1字伸びた」問いとは先頭（BOS）しか
  共通にならず、前回の読みの KV は捨てられる。変換の中の使い回しが 55〜65% でも、
  打鍵をまたぐ使い回しにはなっていない。
- 問いの形は `ZenzPromptBuilder.candidateEvaluationPrompt` の
  「条件・左の文脈・右の文脈・読みの印・読み・出力の印」である。読みは出力の印より前に伸びるので、
  打鍵の前後で共通の前半は「前回の読みの終わりまで」になる。並べ方を変える必要はない。

## 足したもの

`tools/apply_kv_reuse.py`（`tools/apply_batch_score.py` のあと、`tools/apply_latency_profile.py` の前）:

1. 問いの前半だけを入れる列（`promptPrefixSeqId` = 18）を足す。評価のたびに、この列と今回の語片の
   共通の前半を列 0 へ写し、違う後ろだけを評価する。候補の表記はこの列に入れないので、読みが伸びても
   前回の読みの KV が残る。
2. `evaluationLogits` に問いの語片の数を渡す。`jointLogProbability`、選び手の `suffixLogProbabilities`、
   `ZenzCandidateEvaluator` が渡すので、問いと候補の境目が分かる。
3. `MYIME_KV_REUSE=0` で止められる（既定は有効）。止めたときは列も問いの記憶も触らないので、
   出力は変更前と同じになる。

## 確かめ方（本物の Mozc で流す）

この作業環境では Mozc・Swift・llama.cpp を組み立てられないため、下の試験はまだ流していない。
同じ計算機で、同じ変換エンジン・同じ模型を使い、環境変数だけを変えて2回流す。

### 出力が1文字も変わらないこと

組 `a1 a2 b c f h k m r s t` を、結果フォルダーを分けて2回流す。

```
for g in a1 a2 b c f h k m r s t; do
  MYIME_KV_REUSE=0 bash tools/run_tests.sh $g <engine> <model.gguf> <repo> <out>/off-$g
  MYIME_KV_REUSE=1 bash tools/run_tests.sh $g <engine> <model.gguf> <repo> <out>/on-$g
  python3 tools/compare_kv_reuse.py <out>/off-$g <out>/on-$g
done
```

`compare_kv_reuse.py` は変換の結果（`.tsv`、`.json`、`.txt`）を行数と1行ずつ比べ、
時間・記録・環境のファイルは飛ばす。違いが1件でもあれば終了の番号 1 を返す。
`MYIME_KV_REUSE=0` は変更前と同じ道を通るので、この比較は「変更前」と「変更後（有効）」の比較になる。
組 `j`（落ちないか）も、同じ2通りで流す。

### 速さ

組 `w`（長さ別、`LAT_N` で文の数）を、`MYIME_KV_REUSE=0` と `=1` で3回以上ずつ流す。

```
MYIME_KV_REUSE=0 bash tools/run_tests.sh w <engine> <model.gguf> <repo> <out>/off-w
MYIME_KV_REUSE=1 bash tools/run_tests.sh w <engine> <model.gguf> <repo> <out>/on-w
```

`long-latency-report.txt` の中央値・幅と、`<段>_tok`（渡した語片）と `<段>_new`（新しく計算した語片）から、
使い回しの割合（1 − new/tok）を出す。読みが1字伸びたときに、前回の読みまでが `reuse` として残ることを
`MYIME_CTX_LOG` の一括採点の行でも確かめる。

## 打っている間の先回り（検討だけ）

読みの prefill だけを裏で進める案は、採らなかった。打っている途中の予測変換がすでに今の読みで人工知能を
呼び、この変更後はその結果が問いの前半として残る。別の処理を足すと CPU を奪い合い、打鍵が遅れる危険のほうが
大きい。既存の先回り（`MYIME_PREFETCH_DELAY`）はそのまま。
