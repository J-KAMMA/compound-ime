#!/bin/bash
# run_tests.sh <group> <engine dir> <model.gguf> <this repository> <results dir>
# 変換の試験を、組（a1、a2、b、c）に分けて流す。GitHub の試験（.github/workflows/linux-test.yml）が
# 組ごとに別の計算機で同時に呼ぶ。<engine dir> には session_handler_main と変換エンジン一式がある。
#   a1, a2: 1,298文（inputs）の前半と後半
#   b: 日本語だけの400文、予測変換、速さ、候補の並び、利用者が見つけた失敗
#   c: 英単語まじりの267文と200文、打ち間違いの150文2組
#   d1, d2: 打ち方の揺れ（tests/conversion/variants.tsv の前半と後半。tools/romaji_variants.py）
#   h: 話し言葉の文をローマ字で打ち込む（tests/conversion/colloquial.tsv。tools/colloquial_text.py）
#   f: 前後の文がある試験（tests/conversion/context.tsv を前の文あり・なしで。tools/context_convert.sh）
#   e1, e2: ウィキペディアの文をローマ字で打ち込む（前半と後半）（tests/conversion/wiki-typing.tsv。tools/wiki_typing_test.py）
#   g: プログラミングと仮想通貨の文をローマ字で打ち込む（tests/conversion/domain-prog.tsv、domain-crypto.tsv。tools/domain_typing_test.py）
#   i: 人工知能の時間の上限の試験（わざと遅くする。tools/slow_compare.py、tools/zenzai_stats.py）
#   j: 落ちないかの試験（標準エラーなし、前後の文と実験の印つきでキーを1つずつ送り続ける）
set -eo pipefail
GROUP=$1; E=$2; MODEL=$3; REPO=$4; OUT=$5
T=$REPO/tests/conversion
BATCH="bash $REPO/tools/batch_convert.sh $E/session_handler_main $E $MODEL"
W=$(mktemp -d); mkdir -p "$OUT"
# 選び手の段階3: 採点し直した文節の判断を組ごとに記録する（読み、文節、門、確からしさ、選んだ候補）
export MYIME_SELECTOR_LOG=$(cd "$OUT" && pwd)/selector-log-$GROUP.txt
# 変換エンジンの部品（libggml-cpu.so など）は一式の中から探す。組み立てた計算機の
# llama.cpp の組み立て先は、ここにはない。
export LD_LIBRARY_PATH="$E${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
romaji() { python3 -c "import json,sys; print('\n'.join(i['romaji'] for i in json.load(open(sys.argv[1]))['items']))" "$1"; }
run_one() {  # one input through the server; prints the output protocol text
  MYIME_HERMETIC_TEST=1 MYIME_AZOOKEY_DLL_DIR=$E MYIME_AZOOKEY_ZENZAI_WEIGHT=$MODEL TEST_TMPDIR=$W/p \
    $E/session_handler_main --input "$1" --profile $W/p --dictionary oss < /dev/null 2>/dev/null
}

case $GROUP in
a1|a2)
  # 1,298文を前半と後半に分ける（まとめの段で inputs.tsv にする）
  half=$(( ($(wc -l < $T/inputs.txt) + 1) / 2 ))
  if [ "$GROUP" = a1 ]; then head -n $half $T/inputs.txt > $W/inputs.txt; else tail -n +$((half + 1)) $T/inputs.txt > $W/inputs.txt; fi
  $BATCH $W/inputs.txt $OUT/inputs-${GROUP#a}.tsv 4
  ;;
b)
  # 日本語だけの400文（同音異義語、活用、敬語、数、固有名、カタカナ語、話し言葉、長文、助詞、慣用句）
  romaji $T/ja400.json > $W/ja400.txt
  # 選び手の段階3の確かめ: 判断の記録（selector-log）と、選び手を当てる前の候補とコスト（features）
  MYIME_SELECTOR_LOG=$OUT/selector-log-ja400.txt MYIME_SELECTOR_FEATURES=$OUT/features-ja400.txt \
    MYIME_SELECTOR_SCORE=$OUT/score-ja400.txt MYIME_SELECTOR_DUMP=$OUT/dump-ja400.txt $BATCH $W/ja400.txt $OUT/ja400.tsv 4
  python3 $REPO/tools/score_categories.py $OUT/ja400.tsv $T/ja400.json | head -12
  # 予測変換: 最初の100文を最後まで打ち、変換キーを押す前の候補の上位3つに正解が出るか
  python3 -c "import json,sys; [print(i['romaji']+'\t'+'\t'.join([i['intended']]+i.get('alternatives',[]))) for i in json.load(open(sys.argv[1]))['items'][:100]]" $T/ja400.json > $W/pred-items.tsv
  hit=0; total=0
  while IFS=$'\t' read -r r answers; do
    printf 'SEND_KEY\tON\nSEND_KEYS\t%s\nSHOW_OUTPUT\n' "$r" > $W/pred.tsv
    top=$(run_one $W/pred.tsv | awk '/^ *candidates \{/{c=1} c&&/^ *value:/{v=$0; sub(/.*value: "/,"",v); sub(/"$/,"",v); print v; n++} n>=3{exit}')
    total=$((total+1))
    if printf '%s\n' "$top" | grep -qxF -f <(printf '%s\n' $answers); then hit=$((hit+1)); fi
  done < $W/pred-items.tsv
  echo "予測変換: 上位3つに正解 $hit/$total" | tee $OUT/prediction.txt
  # 速さの目安: 最初の100文を1つの処理で変換した時間（GitHub の計算機、画像処理用の計算機なし）
  head -100 $W/ja400.txt > $W/speed.txt
  t0=$(date +%s.%N)
  $BATCH $W/speed.txt $W/speed.tsv 1
  t1=$(date +%s.%N)
  python3 -c "import sys; t=float(sys.argv[2])-float(sys.argv[1]); print(f'速さ: 100文 {t:.1f} 秒、1文あたり {t*10:.0f} ミリ秒（起動を含む）')" $t0 $t1 | tee $OUT/speed.txt
  # 候補の先頭8つ: カタカナ語の次の英単語、日付・時刻（きょう、いま）、絵文字（ねこ）、話し言葉
  for r in konpyu-ta- ko-hi- kafe cafe idea yoga mi-thinngu sukeju-ru ribinngu kyou ima ashita neko hare ikokka; do
    printf 'SEND_KEY\tON\nSEND_KEYS\t%s\nSEND_KEY\tSpace\nSHOW_OUTPUT\n' "$r" > $W/cand.tsv
    run_one $W/cand.tsv | awk '/^ *candidates \{/{c=1} c&&/^ *value:/{v=$0; sub(/.*value: "/,"",v); sub(/"$/,"",v); out=out v " / "; n++} n>=8{exit} END{print out}' | sed "s|^|$r: |" || true
  done | tee $OUT/candidates.txt
  # 利用者が見つけた失敗（毎回確かめる）
  romaji $T/reported.json > $W/reported.txt
  $BATCH $W/reported.txt $OUT/reported.tsv 1
  python3 $REPO/tools/score_categories.py $OUT/reported.tsv $T/reported.json
  ;;
c)
  MYIME_SELECTOR_DUMP=$OUT/dump-jaen270.txt $BATCH $T/jaen270.txt $OUT/jaen270.tsv 4
  romaji $T/jaen200b.json > $W/jaen200b.txt
  MYIME_SELECTOR_SCORE=$OUT/score-jaen200b.txt MYIME_SELECTOR_DUMP=$OUT/dump-jaen200b.txt $BATCH $W/jaen200b.txt $OUT/jaen200b.tsv 4
  romaji $T/typo150.json > $W/typo150.txt
  $BATCH $W/typo150.txt $OUT/typo150.tsv 4
  # 打ち間違いの直しを見ずに作った別の150文: 直しなし（off）と既定の両方
  romaji $T/typo150b.json > $W/typo150b.txt
  MYIME_TYPO_MARGIN=off $BATCH $W/typo150b.txt $OUT/typo150b-off.tsv 4
  $BATCH $W/typo150b.txt $OUT/typo150b.tsv 4
  ;;
d1|d2)
  # 同じ文を別の打ち方（訓令式、l や x の小さいかな、ltu、xn、n'）で打っても結果が同じか
  cut -f3 $T/variants.tsv > $W/variants.txt
  half=$(( ($(wc -l < $W/variants.txt) + 1) / 2 ))
  if [ "$GROUP" = d1 ]; then head -n $half $W/variants.txt > $W/v.txt; else tail -n +$((half + 1)) $W/variants.txt > $W/v.txt; fi
  $BATCH $W/v.txt $OUT/variants-${GROUP#d}.tsv 4
  ;;
e1|e2)
  # ウィキペディアの文をローマ字で打つ（前半と後半。採点はまとめの段で）
  if [ -f $T/wiki-typing.tsv ]; then
    grep -v '^#' $T/wiki-typing.tsv | cut -f1 > $W/wiki.txt
    half=$(( ($(wc -l < $W/wiki.txt) + 1) / 2 ))
    if [ "$GROUP" = e1 ]; then head -n $half $W/wiki.txt > $W/w.txt; else tail -n +$((half + 1)) $W/wiki.txt > $W/w.txt; fi
    $BATCH $W/w.txt $OUT/wiki-typing-${GROUP#e}.tsv 4
  fi
  ;;
g)
  # 分野の文（プログラミング 300、仮想通貨 200 ほど）をローマ字で打つ。英字の言葉（git、npm、Python、DeFi、NFT など）は
  # 打ったまま元の文どおり出ることを期待する。採点はまとめの段で（tools/score_wiki_typing.py）
  for field in prog crypto; do
    if [ -f $T/domain-$field.tsv ]; then
      grep -v '^#' $T/domain-$field.tsv | cut -f1 > $W/domain-$field.txt
      $BATCH $W/domain-$field.txt $OUT/domain-$field.tsv 4
    fi
  done
  ;;
h)
  # 話し言葉の文（終助詞・縮約・くだけた言い方・疑問・感嘆、300 文ほど）をローマ字で打つ。! と ? は半角で打つ。
  # 採点はまとめの段で（tools/score_colloquial.py。厳しい採点と、記号・かな漢字の揺れを許す緩い採点）
  if [ -f $T/colloquial.tsv ]; then
    grep -v '^#' $T/colloquial.tsv | cut -f1 > $W/colloquial.txt
    $BATCH $W/colloquial.txt $OUT/colloquial.tsv 4
  fi
  ;;
x)
  # 診断（原因調べの間だけ）: 話し言葉の文を、仕組みを一つずつ切って流し、候補の書き出し付きで残す
  if [ -f $T/colloquial.tsv ]; then
    grep -v '^#' $T/colloquial.tsv | cut -f1 > $W/colloquial.txt
    MYIME_SELECTOR_DUMP=$OUT/dump-base.txt MYIME_AI_DUMP=$OUT/ai-base.txt $BATCH $W/colloquial.txt $OUT/base.tsv 4
    SOLO="bash $REPO/tools/batch_convert.sh $E/session_handler_main $E"
    MYIME_SELECTOR_DUMP=$OUT/dump-noai.txt $SOLO /nonexistent.gguf $W/colloquial.txt $OUT/noai.tsv 4 || true
    MYIME_AI_RESEGMENT=0 MYIME_SELECTOR_DUMP=$OUT/dump-nores.txt $BATCH $W/colloquial.txt $OUT/nores.tsv 4
    MYIME_HOMOPHONE_CUES=0 MYIME_SELECTOR_DUMP=$OUT/dump-nocues.txt $BATCH $W/colloquial.txt $OUT/nocues.tsv 4
    MYIME_ENGLISH_CONTEXT=0 MYIME_SELECTOR_DUMP=$OUT/dump-noenctx.txt $BATCH $W/colloquial.txt $OUT/noenctx.tsv 4
  fi
  ;;
y)
  # 診断（原因調べの間だけ）: 文末の記号の組み直し。従来の動き（MYIME_RESEG_SYMBOL=0）と新しい動きを、人工知能の候補と組み直しの記録付きで流す
  if [ -f $T/colloquial.tsv ]; then
    grep -v '^#' $T/colloquial.tsv | cut -f1 > $W/colloquial.txt
    MYIME_RESEG_SYMBOL=0 MYIME_RESEG_SYNTH=0 MYIME_AI_DUMP=$OUT/ai-old.txt MYIME_RESEGMENT_LOG=$OUT/reseg-old.txt $BATCH $W/colloquial.txt $OUT/old.tsv 4
    MYIME_RESEG_SYNTH=0 MYIME_RESEGMENT_LOG=$OUT/reseg-sym.txt $BATCH $W/colloquial.txt $OUT/sym.tsv 4
    MYIME_AI_DUMP=$OUT/ai-new.txt MYIME_RESEGMENT_LOG=$OUT/reseg-new.txt $BATCH $W/colloquial.txt $OUT/new.tsv 4
  fi
  ;;
f)
  # 前の文を入力欄の前の文として渡したときと渡さないときの正解の数を比べる
  if [ -f $T/context.tsv ]; then
    CTX="bash $REPO/tools/context_convert.sh $E/session_handler_main $E $MODEL $T/context.tsv"
    $CTX $OUT/context-with.tsv with 4
    $CTX $OUT/context-without.tsv without 4
    python3 $REPO/tools/score_context.py $T/context.tsv $OUT/context-with.tsv $OUT/context-without.tsv | tee $OUT/context-score.txt | head -30
  fi
  ;;
i)
  # 人工知能の時間の上限の試験（わざと遅くする）。日本語だけの400文の先頭100文を、
  #   unlimited: 上限なし（人工知能あり）、noai: 人工知能なし（重みのファイルがない）、
  #   t10, t1: 上限を 10, 1 ミリ秒にして（ほぼ必ず上限に当たる）、
  #   load300, loadfree: 計算機の全部のコアを空回しで忙しくして、既定の 1000 ミリ秒と上限なし
  # で変換する。上限に当たっても全部の文が変換され（固まらず）、結果が人工知能ありかなしの
  # どちらかになることを tools/slow_compare.py で確かめる。
  romaji $T/ja400.json > $W/ja400.txt
  head -100 $W/ja400.txt > $W/h100.txt
  MYIME_ZENZAI_TIME_LIMIT_MS=0 $BATCH $W/h100.txt $OUT/slow-unlimited.tsv 4
  bash $REPO/tools/batch_convert.sh $E/session_handler_main $E $W/no-such-model.gguf $W/h100.txt $OUT/slow-noai.tsv 4 || true
  t0=$(date +%s.%N)
  MYIME_ZENZAI_TIME_LIMIT_MS=10 $BATCH $W/h100.txt $OUT/slow-t10.tsv 4
  MYIME_ZENZAI_TIME_LIMIT_MS=1 $BATCH $W/h100.txt $OUT/slow-t1.tsv 4
  t1=$(date +%s.%N)
  python3 -c "import sys; print(f'上限を 10 ミリ秒と 1 ミリ秒にして 100 文ずつ変換: {float(sys.argv[2])-float(sys.argv[1]):.1f} 秒（固まらず終わった）')" $t0 $t1 | tee $OUT/slow-time.txt
  # 計算機を忙しくする（コアの数の2倍の空回し）
  for i in $(seq $(( $(nproc) * 2 ))); do ( timeout 900 bash -c 'while :; do :; done' ) & done
  sleep 2
  MYIME_ZENZAI_TIME_LIMIT_MS=1000 $BATCH $W/h100.txt $OUT/slow-load1000.tsv 4
  MYIME_ZENZAI_TIME_LIMIT_MS=0 $BATCH $W/h100.txt $OUT/slow-loadfree.tsv 4
  pkill -f 'while :; do :; done' || true
  # 計算機が空いているとき（変換の処理を1つだけ）に、上限を 300、500、1000 ミリ秒、なしにした場合
  for ms in 300 500 1000 0; do
    MYIME_ZENZAI_TIME_LIMIT_MS=$ms $BATCH $W/h100.txt $OUT/slow-idle$ms.tsv 1
  done
  # 前の文がある変換（人工知能を一番使う）60文を、空いた計算機で、上限 1000 ミリ秒と上限なしにした場合
  grep -v '^#' $T/context.tsv > $W/ctxall.tsv
  head -60 $W/ctxall.tsv > $W/ctx60.tsv
  for ms in 1000 0; do
    MYIME_ZENZAI_TIME_LIMIT_MS=$ms bash $REPO/tools/context_convert.sh $E/session_handler_main $E $MODEL $W/ctx60.tsv $OUT/slow-ctx$ms.tsv with 1
  done
  python3 -c "
import sys
gold = {l.split('\t')[0]: l.split('\t')[1] for l in open(sys.argv[1], encoding='utf-8') if l.strip()}
for ms in ('1000', '0'):
    got = [l.rstrip('\n').split('\t') for l in open(sys.argv[2] + '/slow-ctx' + ms + '.tsv', encoding='utf-8')]
    right = sum(len(f) >= 3 and gold.get(f[0]) == f[2] for f in got)
    print(f'前の文がある60文、空いた計算機、上限 {ms} ミリ秒（0 は上限なし）: 正解 {right}/{len(got)}')
" $W/ctx60.tsv $OUT | tee $OUT/slow-ctx.txt
  python3 $REPO/tools/slow_compare.py $T/ja400.json unlimited=$OUT/slow-unlimited.tsv noai=$OUT/slow-noai.tsv \
    t10=$OUT/slow-t10.tsv t1=$OUT/slow-t1.tsv load1000=$OUT/slow-load1000.tsv loadfree=$OUT/slow-loadfree.tsv \
    idle300=$OUT/slow-idle300.tsv idle500=$OUT/slow-idle500.tsv idle1000=$OUT/slow-idle1000.tsv idlefree=$OUT/slow-idle0.tsv \
    | tee $OUT/slow-compare.txt
  for s in unlimited noai t10 t1 load1000 loadfree idle300 idle500 idle1000 idle0 ctx1000 ctx0; do
    python3 $REPO/tools/zenzai_stats.py $OUT --glob "slow-$s.tsv.zstats.*" --label "$s" | tee -a $OUT/slow-stats.txt
  done
  ;;
j)
  # 落ちないかの試験。ウィンドウズの変換エンジン（mozc_server.exe、画面だけの処理）には標準エラーがない。
  # 1.144 では、人工知能の重みを読み込むときに標準エラーへ書こうとして変換エンジンが落ち、打っていた文が
  # 消えた（Swift の FileHandle.standardError.write は、書けないと中の try! で処理ごと止まる）。
  # ここでは標準エラーを書けない状態（読み取り専用で開く）にし、実際の打ち込みと同じく後ろの文と
  # 画面側が付ける実験の印（myime_async_conversion_v1）を付け、前の文は1文おきに付け、先回りの変換が
  # すぐ動くようにして（MYIME_PREFETCH_DELAY=1）、キーを1つずつ送り続ける。途中で1字消して打ち直す。
  # 上限は既定の 1000 ミリ秒、1 ミリ秒（計算の途中の打ち切りがほぼ毎回起きる）、それに裏の変換
  # （MYIME_ASYNC_CONVERSION=1）でも流す。処理が最後まで動き、全部の文が確定することを確かめる。
  # head に直接つなぐと、pipefail のもとで Python が書き込み先の切れた誤り（終了の番号 120）で止まる
  romaji $T/ja400.json > $W/stress-all.txt
  head -40 $W/stress-all.txt > $W/stress.txt
  expected=$(wc -l < $W/stress.txt)
  fail=0
  for variant in t1000 t1 async; do
    case $variant in
      t1000) limit=1000; async=0 ;;
      t1) limit=1; async=0 ;;
      async) limit=1000; async=1 ;;
    esac
    { printf 'SET_EXPERIMENTAL_FEATURE\tmyime_async_conversion_v1\nSET_FOLLOWING_TEXT\t。\nSEND_KEY\tON\n'
      n=0
      while IFS= read -r r; do
        n=$((n + 1))
        if [ $((n % 2)) = 0 ]; then printf 'SET_PRECEDING_TEXT\t今日は良い天気です。\n'; else printf 'SET_PRECEDING_TEXT\n'; fi
        printf 'SEND_KEYS\t%s\nSEND_KEY\tBackspace\nSEND_KEYS\t%s\nSEND_KEY\tSpace\nSEND_KEY\tEnter\nSHOW_OUTPUT\n' "$r" "${r: -1}"
      done < $W/stress.txt; } > $W/stress-$variant.cmd
    rc=0
    env MYIME_ZENZAI_TIME_LIMIT_MS=$limit MYIME_PREFETCH_DELAY=1 $([ $async = 1 ] && echo MYIME_ASYNC_CONVERSION=1) \
      MYIME_HERMETIC_TEST=1 MYIME_AZOOKEY_DLL_DIR=$E MYIME_AZOOKEY_ZENZAI_WEIGHT=$MODEL MYIME_AZOOKEY_ZENZAI_GPU=0 \
      TEST_TMPDIR=$W/p-$variant timeout 1800 $E/session_handler_main --input $W/stress-$variant.cmd \
      --profile $W/p-$variant --dictionary oss < /dev/null > $OUT/stress-$variant.out 2< /dev/null || rc=$?
    got=$(grep -c '^result {' $OUT/stress-$variant.out || true)
    if [ $rc != 0 ] || [ "$got" != "$expected" ]; then
      echo "落ちないかの試験 $variant: 失敗（終了の番号 $rc、確定 $got/$expected）" | tee -a $OUT/stress.txt
      fail=1
    else
      echo "落ちないかの試験 $variant: 最後まで動いた（確定 $got/$expected）" | tee -a $OUT/stress.txt
    fi
  done
  [ $fail = 0 ]
  ;;
*)
  echo "組は a1、a2、b、c、d1、d2、e1、e2、f、g、h、i、j、x のどれか" >&2; exit 2 ;;
esac
