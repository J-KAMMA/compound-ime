#!/bin/bash
# candidates_convert.sh <session_handler_main> <engine dir> <model.gguf> <inputs.txt> <out.tsv> [並列数]
# 1行に1つのローマ字を、空白で変換して、候補を先頭から最大12個、「入力<TAB>候補<TAB>候補…」と書く。
# （変換の後は Enter で確定して次の入力へ。tools/batch_convert.sh と同じ進め方。人工知能の待ち時間は無制限）
set -e
EXE=$1; ENGINE=$2; MODEL=$3; IN=$4; OUT=$5; P=${6:-4}
w=$(mktemp -d); split -l $(( ($(wc -l < "$IN") + P - 1) / P )) "$IN" $w/part.
for f in $w/part.*; do
  ( { printf 'SEND_KEY\tON\n'; while IFS= read -r r; do printf 'SEND_KEYS\t%s\nSEND_KEY\tSpace\nSHOW_OUTPUT\nSEND_KEY\tEnter\nSHOW_OUTPUT\nCLEAR_ALL\nRESET_CONTEXT\nSEND_KEY\tON\n' "$r"; done < $f; } > $f.tsv
    MYIME_ZENZAI_TIME_LIMIT_MS="${MYIME_ZENZAI_TIME_LIMIT_MS:-0}" MYIME_ZENZAI_STATS_FILE="$OUT.zstats" MYIME_AI_BUDGET_MS=0 MYIME_HERMETIC_TEST=1 MYIME_AZOOKEY_DLL_DIR="$ENGINE" MYIME_AZOOKEY_ZENZAI_WEIGHT="$MODEL" \
      MYIME_AZOOKEY_ZENZAI_GPU=0 TEST_TMPDIR=$f.prof "$EXE" --input $f.tsv --profile $f.prof --dictionary oss > $f.out 2> $f.err
    # 候補の窓（all_candidate_words { candidates { value: … } … }）の value: だけを取る。次の result { … } が来たら1行書く。
    awk -v inputs=$f 'BEGIN{while((getline l < inputs)>0) in_[++n]=l}
      /^all_candidate_words \{/{c=1; list=""; k=0}
      c&&/^    value:/{v=$0; sub(/.*value: "/,"",v); sub(/"$/,"",v); if (k<12) {list=list "\t" v; k++}}
      c&&/^\}/{c=0}
      /^result \{/{r=1}
      r&&/^  value:/{i++; printf "%s%s\n", in_[i], list; list=""; k=0; r=0}' $f.out > $f.res ) &
done; wait
cat $w/part.*.res > "$OUT"
# 形の確かめ用に、最初の部分の生の出力の先頭を残す
head -c 60000 $(ls $w/part.*.out | head -1) > "$OUT.raw" 2> /dev/null || true
if grep -l -i "failed to load\|dlopen error\|unavailable" $w/*.err; then grep -h -i "dlopen\|failed to load" $w/*.err | head -3; echo "変換エンジンを読めませんでした"; exit 1; fi
rm -rf $w
