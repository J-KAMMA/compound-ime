#!/bin/bash
# batch_convert.sh <session_handler_main> <engine dir> <model.gguf> <inputs.txt> <out.tsv> [並列数]
# 1行に1つのローマ字を、空白で変換・Enter で確定し、「入力<TAB>文節|…<TAB>確定」を書く（人工知能の待ち時間は無制限）。
set -e
EXE=$1; ENGINE=$2; MODEL=$3; IN=$4; OUT=$5; P=${6:-4}
w=$(mktemp -d); split -l $(( ($(wc -l < "$IN") + P - 1) / P )) "$IN" $w/part.
for f in $w/part.*; do
  ( { printf 'SEND_KEY\tON\n'; while IFS= read -r r; do printf 'SEND_KEYS\t%s\nSEND_KEY\tSpace\nSHOW_OUTPUT\nSEND_KEY\tEnter\nSHOW_OUTPUT\nCLEAR_ALL\nRESET_CONTEXT\nSEND_KEY\tON\n' "$r"; done < $f; } > $f.tsv
    MYIME_AI_BUDGET_MS=0 MYIME_HERMETIC_TEST=1 MYIME_AZOOKEY_DLL_DIR="$ENGINE" MYIME_AZOOKEY_ZENZAI_WEIGHT="$MODEL" \
      MYIME_AZOOKEY_ZENZAI_GPU=0 TEST_TMPDIR=$f.prof "$EXE" --input $f.tsv --profile $f.prof --dictionary oss > $f.out 2> $f.err
    awk -v inputs=$f 'BEGIN{while((getline l < inputs)>0) in_[++n]=l}
      /^preedit \{/{p=1; s=""} p&&/^    value:/{v=$0; sub(/.*value: "/,"",v); sub(/"$/,"",v); s=s v "|"} p&&/^}/{p=0; segs=s}
      /^result \{/{r=1} r&&/^  value:/{v=$0; sub(/.*value: "/,"",v); sub(/"$/,"",v); i++; printf "%s\t%s\t%s\n", in_[i], substr(segs,1,length(segs)-1), v; r=0}' $f.out > $f.res ) &
done; wait
cat $w/part.*.res > "$OUT"
if grep -l -i "failed to load\|dlopen error\|unavailable" $w/*.err; then grep -h -i "dlopen\|failed to load" $w/*.err | head -3; echo "変換エンジンを読めませんでした"; exit 1; fi
rm -rf $w
