#!/bin/bash
# context_convert.sh <session_handler_main> <engine dir> <model.gguf> <context.tsv> <out.tsv> <with|without|newline> [並列数]
# 前後の文がある試験: context.tsv（ローマ字<TAB>元の文<TAB>前の文）の各行を、with では前の文を
# 入力欄の前の文として渡して、without では渡さずに変換・確定し、「ローマ字<TAB>文節|…<TAB>確定」を書く。
set -e
EXE=$1; ENGINE=$2; MODEL=$3; IN=$4; OUT=$5; MODE=$6; P=${7:-4}
w=$(mktemp -d); grep -v '^#' "$IN" > $w/all.tsv
split -l $(( ($(wc -l < $w/all.tsv) + P - 1) / P )) $w/all.tsv $w/part.
for f in $w/part.*; do
  ( cut -f1 $f > $f.inputs
    { printf 'SEND_KEY\tON\n'
      while IFS=$'\t' read -r raw _ before; do
        [ "$MODE" = with ] && printf 'SET_PRECEDING_TEXT\t%s\n' "$before"
        # newline: 前の文のあとに改行がある（チャットやメモで Enter のあと）。改行は「\n」と書いて渡す
        [ "$MODE" = newline ] && printf 'SET_PRECEDING_TEXT\t%s%s\n' "$before" '\n'
        printf 'SEND_KEYS\t%s\nSEND_KEY\tSpace\nSHOW_OUTPUT\nSEND_KEY\tEnter\nSHOW_OUTPUT\nCLEAR_ALL\nRESET_CONTEXT\nSET_PRECEDING_TEXT\nSEND_KEY\tON\n' "$raw"
      done < $f; } > $f.cmd
    MYIME_ZENZAI_TIME_LIMIT_MS="${MYIME_ZENZAI_TIME_LIMIT_MS:-0}" MYIME_ZENZAI_STATS_FILE="$OUT.zstats" MYIME_AI_BUDGET_MS=0 MYIME_HERMETIC_TEST=1 MYIME_AZOOKEY_DLL_DIR="$ENGINE" MYIME_AZOOKEY_ZENZAI_WEIGHT="$MODEL" \
      MYIME_AZOOKEY_ZENZAI_GPU=0 TEST_TMPDIR=$f.prof "$EXE" --input $f.cmd --profile $f.prof --dictionary oss > $f.out 2> $f.err
    awk -v inputs=$f.inputs 'BEGIN{while((getline l < inputs)>0) in_[++n]=l}
      /^preedit \{/{p=1; s=""} p&&/^    value:/{v=$0; sub(/.*value: "/,"",v); sub(/"$/,"",v); s=s v "|"} p&&/^}/{p=0; segs=s}
      /^result \{/{r=1} r&&/^  value:/{v=$0; sub(/.*value: "/,"",v); sub(/"$/,"",v); i++; printf "%s\t%s\t%s\n", in_[i], substr(segs,1,length(segs)-1), v; r=0}' $f.out > $f.res ) &
done; wait
cat $w/part.*.res > "$OUT"
rm -rf $w
