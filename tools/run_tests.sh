#!/bin/bash
# run_tests.sh <group> <engine dir> <model.gguf> <this repository> <results dir>
# 変換の試験を、組（a1、a2、b、c）に分けて流す。GitHub の試験（.github/workflows/linux-test.yml）が
# 組ごとに別の計算機で同時に呼ぶ。<engine dir> には session_handler_main と変換エンジン一式がある。
#   a1, a2: 1,298文（inputs）の前半と後半
#   b: 日本語だけの400文、予測変換、速さ、候補の並び、利用者が見つけた失敗
#   c: 英単語まじりの267文と200文、打ち間違いの150文2組
#   d1, d2: 打ち方の揺れ（tests/conversion/variants.tsv の前半と後半。tools/romaji_variants.py）
#   f: 前後の文がある試験（tests/conversion/context.tsv を前の文あり・なしで。tools/context_convert.sh）
#   e1, e2: ウィキペディアの文をローマ字で打ち込む（前半と後半）（tests/conversion/wiki-typing.tsv。tools/wiki_typing_test.py）
set -eo pipefail
GROUP=$1; E=$2; MODEL=$3; REPO=$4; OUT=$5
T=$REPO/tests/conversion
BATCH="bash $REPO/tools/batch_convert.sh $E/session_handler_main $E $MODEL"
W=$(mktemp -d); mkdir -p "$OUT"
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
f)
  # 前の文を入力欄の前の文として渡したときと渡さないときの正解の数を比べる
  if [ -f $T/context.tsv ]; then
    CTX="bash $REPO/tools/context_convert.sh $E/session_handler_main $E $MODEL $T/context.tsv"
    $CTX $OUT/context-with.tsv with 4
    $CTX $OUT/context-without.tsv without 4
    python3 $REPO/tools/score_context.py $T/context.tsv $OUT/context-with.tsv $OUT/context-without.tsv | tee $OUT/context-score.txt | head -30
  fi
  ;;
*)
  echo "組は a1、a2、b、c、d1、d2、e1、e2、f のどれか" >&2; exit 2 ;;
esac
