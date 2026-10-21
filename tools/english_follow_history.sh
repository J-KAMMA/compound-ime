#!/bin/bash
# english_follow_history.sh <session_handler_main> <engine dir> <model.gguf> <english-follow-history.tsv> <out.tsv> [並列数]
# 英語の文を1語ずつ打つ場面を、入力欄の前の文を渡さずに流す。前の語（3列目）をキーで打ち、変換して確定し、
# 空白を打ってから、次の語（1列目）を打って変換・確定する。空白は session が変換を通さずアプリへ返すキーで、Mozc はそこで変換の
# 履歴を消す（docs/english-follow.md「履歴の道が効かなかった理由」）。そのため、この表で英語が増えるのは session の記憶
# （直前の確定と空白を覚える）が働くとき。最初の版（記憶なし）では、止めた版と全行同じだった。
# 出力: ローマ字<TAB>文節|…<TAB>確定（次の語を確定した結果）。環境変数 MYIME_ENGLISH_FOLLOW=off で寄せを止められる。
set -e
EXE=$1; ENGINE=$2; MODEL=$3; IN=$4; OUT=$5; P=${6:-4}
w=$(mktemp -d); grep -v '^#' "$IN" > $w/all.tsv
split -l $(( ($(wc -l < $w/all.tsv) + P - 1) / P )) $w/all.tsv $w/part.
for f in $w/part.*; do
  ( cut -f1 $f > $f.inputs
    { printf 'SEND_KEY\tON\n'
      while IFS=$'\t' read -r raw _ before; do
        printf 'SEND_KEYS\t%s\nSEND_KEY\tSpace\nSEND_KEY\tEnter\nSEND_KEY\tSpace\n' "$before"
        printf 'SEND_KEYS\t%s\nSEND_KEY\tSpace\nSHOW_OUTPUT\nSEND_KEY\tEnter\nSHOW_OUTPUT\nCLEAR_ALL\nRESET_CONTEXT\nSET_PRECEDING_TEXT\nSEND_KEY\tON\n' "$raw"
      done < $f; } > $f.cmd
    MYIME_ZENZAI_TIME_LIMIT_MS="${MYIME_ZENZAI_TIME_LIMIT_MS:-0}" MYIME_ZENZAI_STATS_FILE="$OUT.zstats" MYIME_AI_BUDGET_MS=0 MYIME_HERMETIC_TEST=1 MYIME_AZOOKEY_DLL_DIR="$ENGINE" MYIME_AZOOKEY_ZENZAI_WEIGHT="$MODEL" \
      MYIME_AZOOKEY_ZENZAI_GPU=0 TEST_TMPDIR=$f.prof "$EXE" --input $f.cmd --profile $f.prof --dictionary oss > $f.out 2> $f.err
    awk -v inputs=$f.inputs 'BEGIN{while((getline l < inputs)>0) in_[++n]=l}
      /^preedit \{/{p=1; s=""} p&&/^    value:/{v=$0; sub(/.*value: "/,"",v); sub(/"$/,"",v); s=s v "|"} p&&/^}/{p=0; segs=s}
      /^result \{/{r=1} r&&/^  value:/{v=$0; sub(/.*value: "/,"",v); sub(/"$/,"",v); i++; printf "%s\t%s\t%s\n", in_[i], substr(segs,1,length(segs)-1), v; r=0}' $f.out > $f.res ) &
done; wait
cat $w/part.*.res > "$OUT"
rm -r "$w"
