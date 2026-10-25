#!/bin/bash
# batch_convert.sh <session_handler_main> <engine dir> <model.gguf> <inputs.txt> <out.tsv> [並列数]
# 1行に1つのローマ字を、空白で変換・Enter で確定し、「入力<TAB>文節|…<TAB>確定」を書く（人工知能の待ち時間は無制限）。
# MYIME_TEST_CONFIG_DB に設定ファイル（config1.db）を渡すと、各処理のプロファイルに置いてから流す（数字を半角にする設定の試験。
# tools/make_decimal_config.py）。MYIME_BATCH_NO_CONVERT=1 なら、変換せず（空白を押さず）入力中の表示をそのまま確定する。
# 人工知能の時間の上限は、環境変数 MYIME_ZENZAI_TIME_LIMIT_MS で決める。決めなければ 0（上限なし）。4つの処理を同じ計算機で
# 同時に流すので、利用者の PC より何倍も遅く、上限を付けると（300 でも 5000 でも）計算機の混み具合を測ることになり、正解数が
# 下がる。上限の試験は組 h（tools/run_tests.sh）で、処理を1つだけにして行う。
set -e
EXE=$1; ENGINE=$2; MODEL=$3; IN=$4; OUT=$5; P=${6:-4}
if [ -n "$MYIME_BATCH_NO_CONVERT" ]; then CONVERT=''; else CONVERT='SEND_KEY\tSpace\n'; fi
w=$(mktemp -d); split -l $(( ($(wc -l < "$IN") + P - 1) / P )) "$IN" $w/part.
for f in $w/part.*; do
  if [ -n "$MYIME_TEST_CONFIG_DB" ]; then mkdir -p $f.prof; cp "$MYIME_TEST_CONFIG_DB" $f.prof/config1.db; fi
  ( { printf 'SEND_KEY\tON\n'; while IFS= read -r r; do printf 'SEND_KEYS\t%s\n'"$CONVERT"'SHOW_OUTPUT\nSEND_KEY\tEnter\nSHOW_OUTPUT\nCLEAR_ALL\nRESET_CONTEXT\nSEND_KEY\tON\n' "$r"; done < $f; } > $f.tsv
    MYIME_ZENZAI_TIME_LIMIT_MS="${MYIME_ZENZAI_TIME_LIMIT_MS:-0}" MYIME_ZENZAI_STATS_FILE="$OUT.zstats" MYIME_AI_BUDGET_MS=0 MYIME_HERMETIC_TEST=1 MYIME_AZOOKEY_DLL_DIR="$ENGINE" MYIME_AZOOKEY_ZENZAI_WEIGHT="$MODEL" \
      MYIME_AZOOKEY_ZENZAI_GPU=0 TEST_TMPDIR=$f.prof "$EXE" --input $f.tsv --profile $f.prof --dictionary oss > $f.out 2> $f.err
    awk -v inputs=$f 'BEGIN{while((getline l < inputs)>0) in_[++n]=l}
      /^preedit \{/{p=1; s=""} p&&/^    value:/{v=$0; sub(/.*value: "/,"",v); sub(/"$/,"",v); s=s v "|"} p&&/^}/{p=0; segs=s}
      /^result \{/{r=1} r&&/^  value:/{v=$0; sub(/.*value: "/,"",v); sub(/"$/,"",v); i++; printf "%s\t%s\t%s\n", in_[i], substr(segs,1,length(segs)-1), v; r=0}' $f.out > $f.res ) &
done; wait
cat $w/part.*.res > "$OUT"
# Mozc の試験用の出力は引用符を C の形で書く（Macy's → Macy\'s）。実際の入力欄と同じ文字に戻してから採点する。
python3 "$(cd "$(dirname "$0")" && pwd)/protobuf_text_unescape.py" "$OUT"
if grep -l -i "failed to load\|dlopen error\|unavailable" $w/*.err; then grep -h -i "dlopen\|failed to load" $w/*.err | head -3; echo "変換エンジンを読めませんでした"; exit 1; fi
rm -rf $w
