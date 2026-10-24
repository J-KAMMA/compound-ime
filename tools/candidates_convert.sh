#!/bin/bash
# candidates_convert.sh <session_handler_main> <engine dir> <model.gguf> <inputs.txt> <out.tsv> [並列数]
# 1行に1つのローマ字を、空白で変換して、候補を先頭から最大30個、「入力<TAB>候補<TAB>候補…」と書く。
# （変換の後は Enter で確定して次の入力へ。tools/batch_convert.sh と同じ進め方。人工知能の待ち時間は無制限）
# 環境変数 MYIME_CANDIDATE_WINDOW=1 のときは、候補の窓（candidate_window）に出る順と値を使う
# （all_candidate_words は下位の候補を展開するので、窓の2番目と違うことがある）。
set -e
EXE=$1; ENGINE=$2; MODEL=$3; IN=$4; OUT=$5; P=${6:-4}
WINDOW=${MYIME_CANDIDATE_WINDOW:-0}
w=$(mktemp -d); split -l $(( ($(wc -l < "$IN") + P - 1) / P )) "$IN" $w/part.
for f in $w/part.*; do
  ( { printf 'SEND_KEY\tON\n'; while IFS= read -r r; do printf 'SEND_KEYS\t%s\nSEND_KEY\tSpace\nSHOW_OUTPUT\nSEND_KEY\tEnter\nSHOW_OUTPUT\nCLEAR_ALL\nRESET_CONTEXT\nSEND_KEY\tON\n' "$r"; done < $f; } > $f.tsv
    MYIME_ZENZAI_TIME_LIMIT_MS="${MYIME_ZENZAI_TIME_LIMIT_MS:-0}" MYIME_ZENZAI_STATS_FILE="$OUT.zstats" MYIME_AI_BUDGET_MS=0 MYIME_HERMETIC_TEST=1 MYIME_AZOOKEY_DLL_DIR="$ENGINE" MYIME_AZOOKEY_ZENZAI_WEIGHT="$MODEL" \
      MYIME_AZOOKEY_ZENZAI_GPU=0 TEST_TMPDIR=$f.prof "$EXE" --input $f.tsv --profile $f.prof --dictionary oss > $f.out 2> $f.err
    # 候補の窓（MYIME_CANDIDATE_WINDOW=1 のとき）または all_candidate_words の value: だけを取る。
    awk -v inputs=$f -v window=$WINDOW 'BEGIN{while((getline l < inputs)>0) in_[++n]=l}
      window&&/^candidate_window \{/{wc=1; wn=0; delete wid; delete wval}
      window&&wc&&/^  candidate \{/{++wn; wid[wn]=""; wval[wn]=""}
      window&&wc&&/^    id:/{v=$0; sub(/.*id: /,"",v); wid[wn]=v}
      window&&wc&&/^    value:/{v=$0; sub(/.*value: "/,"",v); sub(/"$/,"",v); wval[wn]=v}
      window&&wc&&/^\}/{wc=0}
      window&&/^all_candidate_words \{/{ac=1; delete aid}
      window&&ac&&/^    id:/{v=$0; sub(/.*id: /,"",v); curid=v}
      window&&ac&&/^    value:/{v=$0; sub(/.*value: "/,"",v); sub(/"$/,"",v); if (curid!="") aid[curid]=v}
      window&&ac&&/^\}/{ac=0}
      window&&/^result \{/{r=1}
      window&&r&&/^  value:/{list=""; for(j=1;j<=wn&&j<=30;j++){v=(wid[j] in aid)?aid[wid[j]]:wval[j]; list=list "\t" v}; i++; printf "%s%s\n", in_[i], list; r=0}
      !window&&/^all_candidate_words \{/{c=1; list=""; k=0}
      !window&&c&&/^    value:/{v=$0; sub(/.*value: "/,"",v); sub(/"$/,"",v); if (k<30) {list=list "\t" v; k++}}
      !window&&c&&/^\}/{c=0}
      !window&&/^result \{/{r=1}
      !window&&r&&/^  value:/{i++; printf "%s%s\n", in_[i], list; list=""; k=0; r=0}' $f.out > $f.res ) &
done; wait
cat $w/part.*.res > "$OUT"
# 形の確かめ用に、最初の部分の生の出力の先頭を残す
head -c 60000 $(ls $w/part.*.out | head -1) > "$OUT.raw" 2> /dev/null || true
if grep -l -i "failed to load\|dlopen error\|unavailable" $w/*.err; then grep -h -i "dlopen\|failed to load" $w/*.err | head -3; echo "変換エンジンを読めませんでした"; exit 1; fi
rm -rf $w
