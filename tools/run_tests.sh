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
#   p: 変換1回の時間を段ごとに測る（1つの計算機で、処理を1つだけ。tools/latency_convert.sh、tools/latency_report.py）
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
    MYIME_RESEG_SYMBOL=0 MYIME_AI_DUMP=$OUT/ai-old.txt MYIME_RESEGMENT_LOG=$OUT/reseg-old.txt $BATCH $W/colloquial.txt $OUT/old.tsv 4
    MYIME_AI_DUMP=$OUT/ai-new.txt MYIME_RESEGMENT_LOG=$OUT/reseg-new.txt $BATCH $W/colloquial.txt $OUT/new.tsv 4
  fi
  ;;
f)
  # 前の文を入力欄の前の文として渡したときと渡さないときの正解の数を比べる
  if [ -f $T/context.tsv ]; then
    CTX="bash $REPO/tools/context_convert.sh $E/session_handler_main $E $MODEL $T/context.tsv"
    t0=$(date +%s.%N)
    MYIME_CTX_LOG=$OUT/ctx-gate-log.txt $CTX $OUT/context-with.tsv with 4
    t1=$(date +%s.%N)
    $CTX $OUT/context-without.tsv without 4
    python3 $REPO/tools/score_context.py $T/context.tsv $OUT/context-with.tsv $OUT/context-without.tsv | tee $OUT/context-score.txt | head -30
    # 前後の文での並べ替えを「迷うときだけ」にする値の比べ（tools/apply_context_gate.py、tools/clause_gate_test.py）。
    # 文は句読点を含み並べ替えが働かないので、文の最初の句だけを前の文つきで変換し、候補を絞る個数（TOPK）と
    # 先頭と次の候補の点の差の上限（GAP）を変えて、正解の数・基準との違い・全体の時間（4並列）を比べる
    python3 $REPO/tools/clause_gate_test.py make $T/context.tsv > $W/clause.tsv
    echo "句の試験: $(wc -l < $W/clause.tsv) 句" | tee $OUT/context-gate.txt
    CLAUSE="bash $REPO/tools/context_convert.sh $E/session_handler_main $E $MODEL $W/clause.tsv"
    for variant in ref:MYIME_CTX_TOPK=0,MYIME_CTX_GAP=0 new: off:MYIME_CTX_GAP=0.000001 g8:MYIME_CTX_TOPK=0,MYIME_CTX_GAP=8 k2g8:MYIME_CTX_TOPK=2,MYIME_CTX_GAP=8 k3g16:MYIME_CTX_TOPK=3,MYIME_CTX_GAP=16; do
      name=${variant%%:*}; assign=${variant#*:}
      t0=$(date +%s.%N)
      env ${assign//,/ } MYIME_CTX_LOG=$OUT/ctx-gate-log-$name.txt $CLAUSE $OUT/clause-$name.tsv with 4
      t1=$(date +%s.%N)
      { echo "== $name（${assign:-既定}）: $(python3 -c "import sys; print(round(float(sys.argv[2])-float(sys.argv[1]), 1))" $t0 $t1) 秒、並べ替えの呼び出し $(cat $OUT/ctx-gate-log-$name.txt 2> /dev/null | wc -l) 回、先頭を替えた $(grep -vc 'winner=0\|winner=nil' $OUT/ctx-gate-log-$name.txt 2> /dev/null || true) 回"
        python3 $REPO/tools/clause_gate_test.py score $W/clause.tsv $OUT/clause-ref.tsv $OUT/clause-$name.tsv $name
      } | tee -a $OUT/context-gate.txt
    done
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
p)
  # 変換1回の時間を段ごとに測る。ほかの処理と同時に流さない（変換の処理は1つだけ。この組の計算機でも、ほかの作業はない）。
  # 記録は MYIME_PROFILE（tools/apply_latency_profile.py）。人工知能の時間の上限・待ちの上限・打っている間の先回りは
  # 外して（上限に打ち切られない本当の時間を測るため）、次の組を流す。
  #   ja400: 日本語だけの400文（前の文なし）
  #   wiki: ウィキペディアの文のローマ字入力（長めの文）から約150文
  #   ctx-with, ctx-without: 前後の文がある試験から約170文を、前の文あり・なしで
  #   clause-with, clause-without: 同じ試験の文の最初の句（読点の前まで。読みに句読点がないので、前後の文での並べ替えが働く）を、前の文あり・なしで
  # そのあと利用者の PC と同じ既定の設定（上限 1000 ミリ秒、待ちの上限 700 ミリ秒、先回り 120 ミリ秒）で、
  #   real-nopace: 日本語だけの先頭100文を、続けて速く打つ
  #   real-paced: 先頭40文を、1文字150ミリ秒ずつ打つ（先回りが働く打ち方に近い）
  #   real-fast: 先頭40文を、1文字90ミリ秒ずつ打つ（先回りの待ち 120 ミリ秒より速いので働かない）
  { echo "nproc=$(nproc)"; grep -m1 'model name' /proc/cpuinfo | sed 's/^[^:]*: *//'; } > $OUT/latency-env.txt
  LAT="bash $REPO/tools/latency_convert.sh $E/session_handler_main $E $MODEL"
  romaji $T/ja400.json | awk '{print $0 "\t"}' > $W/lat-ja400.tsv
  grep -v '^#' $T/wiki-typing.tsv | cut -f1 | awk 'NR%20==1 {print $0 "\t"}' > $W/lat-wiki.tsv
  grep -v '^#' $T/context.tsv | awk -F'\t' 'NR%6==1 {print $1 "\t" $3}' > $W/lat-ctx-with.tsv
  grep -v '^#' $T/context.tsv | awk -F'\t' 'NR%6==1 {print $1 "\t"}' > $W/lat-ctx-without.tsv
  grep -v '^#' $T/context.tsv | awk -F'\t' 'NR%4==1 {n=split($1,a,/[,.]/); if (length(a[1])>=8 && c<150) {print a[1] "\t" $3; c++}}' > $W/lat-clause-with.tsv
  cut -f1 $W/lat-clause-with.tsv | awk '{print $0 "\t"}' > $W/lat-clause-without.tsv
  for name in ja400 wiki ctx-with ctx-without clause-with clause-without; do
    $LAT $W/lat-$name.tsv $OUT/latency-$name
  done
  head -100 $W/lat-ja400.tsv > $W/lat-h100.tsv
  head -40 $W/lat-ja400.tsv > $W/lat-h40.tsv
  LAT_REAL=1 $LAT $W/lat-h100.tsv $OUT/latency-real-nopace
  LAT_REAL=1 $LAT $W/lat-h40.tsv $OUT/latency-real-paced 150
  LAT_REAL=1 $LAT $W/lat-h40.tsv $OUT/latency-real-fast 90
  # llama.cpp のスレッド数を変えて比べる（日本語だけの先頭60文。上限なしの設定で）。計算機は4つ（既定は3スレッド）
  head -60 $W/lat-ja400.tsv > $W/lat-h60.tsv
  for n in 1 2 3 4; do
    MYIME_PROFILE_THREADS=$n $LAT $W/lat-h60.tsv $OUT/latency-threads$n
  done
  python3 $REPO/tools/latency_report.py $OUT | tee $OUT/latency-report.txt
  # 空白キーの処理のうち、入り口の外の前の時間（report の「（入り口の外）前」）の正体を、関数ごとの時間で調べる。
  # どれも入れられなければ飛ばす（失敗しても組は失敗にしない）。前の文のない最初の句50文を流す。
  (
    set +e
    cut -f1 $W/lat-clause-without.tsv | awk 'NR<=50 {print $0 "\t"}' > $W/lat-perf.tsv
    sudo apt-get install -y -qq linux-tools-common linux-tools-$(uname -r) > /dev/null 2>&1       || sudo apt-get install -y -qq linux-tools-generic > /dev/null 2>&1
    PERF=$( { find /usr/lib/linux-tools /usr/lib/linux-tools-* /usr/bin -maxdepth 2 -name perf -type f 2> /dev/null || true; } | sort | tail -n 1 )
    if [ -n "$PERF" ]; then
      sudo sysctl -w kernel.perf_event_paranoid=-1 > /dev/null 2>&1
      "$PERF" record -F 499 -o $W/perf.data -- $LAT $W/lat-perf.tsv $W/perf-run > $OUT/perf-record.log 2>&1
      "$PERF" report -i $W/perf.data --stdio --no-children --sort dso,symbol --percent-limit 0.3 > $OUT/perf-flat.txt 2>&1
      "$PERF" report -i $W/perf.data --stdio --no-children --sort comm,dso --percent-limit 0.5 > $OUT/perf-dso.txt 2>&1
    else
      echo "perf を入れられなかった" > $OUT/perf-flat.txt
    fi
    # gdb で変換の処理の呼び出しの列を一定の間隔で取り、どの関数の中にいる時間が長いかを数える
    sudo apt-get install -y -qq gdb > /dev/null 2>&1
    if command -v gdb > /dev/null; then
      $LAT $W/lat-perf.tsv $W/gdb-run > /dev/null 2>&1 &
      LPID=$!
      sleep 6
      : > $OUT/gdb-samples.txt
      n=0
      while kill -0 $LPID 2> /dev/null && [ $n -lt 500 ]; do
        P=$(pgrep -n -f "session_handler_main --input")
        if [ -n "$P" ]; then
          sudo timeout 20 gdb -p $P -batch -ex 'set pagination off' -ex 'thread 1' -ex 'bt 16' 2> /dev/null | grep -E '^#' | cut -c1-170 >> $OUT/gdb-samples.txt
          echo "====" >> $OUT/gdb-samples.txt
        fi
        n=$((n + 1))
      done
      kill $LPID 2> /dev/null
      python3 - $OUT/gdb-samples.txt > $OUT/gdb-summary.txt <<'PY'
import re, sys, collections
samples, cur = [], []
for line in open(sys.argv[1], encoding="utf-8", errors="replace"):
    if line.startswith("===="):
        if cur: samples.append(cur)
        cur = []
    else:
        m = re.search(r" in ([^ (]+)", line)
        cur.append(m.group(1) if m else line.split()[-1])
print("標本", len(samples))
top = collections.Counter(s[0] for s in samples if s)
incl = collections.Counter(f for s in samples for f in set(s))
print("--- いちばん上の関数");  [print(f"{c:5d} {f}") for f, c in top.most_common(25)]
print("--- 呼び出しの列のどこかにある関数");  [print(f"{c:5d} {f}") for f, c in incl.most_common(60)]
PY
    fi
  ) || true
  ;;
*)
  echo "組は a1、a2、b、c、d1、d2、e1、e2、f、g、h、i、j、p、x のどれか" >&2; exit 2 ;;
esac
