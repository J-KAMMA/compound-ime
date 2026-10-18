#!/bin/bash
# latency_convert.sh <session_handler_main> <engine dir> <model.gguf> <入力.tsv> <出力の名前> [打つ間隔ミリ秒]
# 変換1回の時間を段ごとに測る（tools/apply_latency_profile.py を当てた変換エンジンで）。
# 入力.tsv は「ローマ字<TAB>前の文」（前の文は空でもよい）。1行ずつ、前の文を入力欄の前の文として渡し、
# ローマ字を打って、空白キーの変換にかかった時間（TIMED_KEY）を測り、Enter で確定する。
# 処理は1つだけ（ほかの処理と同時に流さない）。出力:
#   <出力の名前>.profile.tsv  段ごとの時間（MYIME_PROFILE。tools/latency_report.py で集計）
#   <出力の名前>.wall         空白キーの1回ごとの時間（ミリ秒、整数）
# 環境変数:
#   LAT_REAL=1  利用者の PC と同じ既定の設定で流す（人工知能の時間の上限 1000 ミリ秒、待ちの上限 700 ミリ秒、
#               打っている間の先回り 120 ミリ秒）。なければ上限なし・先回りなしで、段ごとの本当の時間を測る
#   打つ間隔を渡すと、1文字ずつその間隔（ミリ秒）で打つ（先回りが働く実際の打ち方に近い）
set -e
EXE=$1; ENGINE=$2; MODEL=$3; IN=$4; OUT=$5; PACE=${6:-0}
w=$(mktemp -d)
rm -f "$OUT.profile.tsv" "$OUT.wall"
{ printf 'SEND_KEY\tON\n'
  while IFS=$'\t' read -r raw before; do
    [ -n "$before" ] && printf 'SET_PRECEDING_TEXT\t%s\n' "$before"
    if [ "$PACE" -gt 0 ]; then printf 'SEND_KEYS_PACED\t%s\t%s\n' "$raw" "$PACE"; else printf 'SEND_KEYS\t%s\n' "$raw"; fi
    printf 'TIMED_KEY\tSpace\nSEND_KEY\tEnter\nCLEAR_ALL\nRESET_CONTEXT\nSET_PRECEDING_TEXT\nSEND_KEY\tON\n'
  done < "$IN"; } > $w/cmd.tsv
if [ "${LAT_REAL:-0}" = 1 ]; then
  LIMITS=""
else
  LIMITS="MYIME_ZENZAI_TIME_LIMIT_MS=0 MYIME_AI_BUDGET_MS=0 MYIME_PREFETCH_DELAY=0"
fi
env $LIMITS MYIME_PROFILE="$OUT.profile.tsv" MYIME_HERMETIC_TEST=1 MYIME_AZOOKEY_DLL_DIR="$ENGINE" MYIME_AZOOKEY_ZENZAI_WEIGHT="$MODEL" \
  MYIME_AZOOKEY_ZENZAI_GPU=0 TEST_TMPDIR=$w/prof "$EXE" --input $w/cmd.tsv --profile $w/prof --dictionary oss > $w/out.txt 2> $w/err.txt
grep '^ELAPSED ' $w/out.txt | cut -d' ' -f2 > "$OUT.wall"
if grep -l -i "failed to load\|dlopen error\|unavailable" $w/err.txt; then head -3 $w/err.txt; echo "変換エンジンを読めませんでした"; exit 1; fi
rm -rf $w
