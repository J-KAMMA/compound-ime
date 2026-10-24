#!/bin/bash
# learn_respect_convert.sh <session_handler_main> <engine dir> <model.gguf> <inputs.tsv> <out prefix> [並列数]
# 履歴の学習の試験（組 l）。1行1語の表（tests/conversion/learn-respect.tsv）を、次の順で流す。
#   1. 人工知能なし（Mozc だけ）で1回ずつ変換し、先頭と違う2番目の候補を、その読みの選ぶ書き方にする。
#   2. 同じ会話（1つの処理・1つのプロファイル）の中で、その書き方を4回、値で選んで確定する。
#   3. 同じ読みを変換し、先頭に来た候補を書く（ローマ字<TAB>選んだ書き方<TAB>先頭）。
# 1 の候補は <out prefix>-targets.tsv、2〜3 の結果は人工知能ありを -on.tsv、なし（重みなし）を -off.tsv に書く。
# 選ぶ命令は tools/apply_jaen_integration.py が試験の道具に足す SELECT_CANDIDATE_VALUE（値で候補を選ぶ）。
set -e
EXE=$1; ENGINE=$2; MODEL=$3; IN=$4; PREFIX=$5; P=${6:-2}
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
grep -v '^#' "$IN" | cut -f1 | awk 'NF' | awk '!seen[$0]++' > "$TMP/readings.txt"
NO_MODEL="$TMP/no-model.gguf"

# 1. 人工知能なしの候補から、先頭と違う最初の候補（2番目）を選ぶ。
bash "$(dirname "$0")/candidates_convert.sh" "$EXE" "$ENGINE" "$NO_MODEL" \
  "$TMP/readings.txt" "$TMP/probe.tsv" "$P"
awk -F'\t' 'NF >= 3 && $3 != $2 { print $1 "\t" $3 }' \
  "$TMP/probe.tsv" > "$TMP/targets.tsv"
cp "$TMP/targets.tsv" "$PREFIX-targets.tsv"
if [ ! -s "$TMP/targets.tsv" ]; then
  echo "2番目の候補がある読みがありませんでした" >&2
  exit 1
fi

run_mode() {  # <名前> <重み> <出力>
  local name=$1 model=$2 out=$3 w="$TMP/$1"
  mkdir -p "$w"
  split -l $(( ($(wc -l < "$TMP/targets.tsv") + P - 1) / P )) "$TMP/targets.tsv" "$w/part."
  for f in "$w"/part.*; do
    ( { printf 'SEND_KEY\tON\n'
        while IFS=$'\t' read -r reading target; do
          # 同じ書き方を4回選んで確定する。履歴を消す命令（CLEAR_ALL）ははさまない。
          for _ in 1 2 3 4; do
            printf 'SEND_KEYS\t%s\nSEND_KEY\tSpace\nSELECT_CANDIDATE_VALUE\t%s\nSEND_KEY\tEnter\n' \
              "$reading" "$target"
          done
          # 5回目は選ばずに、先頭の候補を記録する。
          printf 'SEND_KEYS\t%s\nSEND_KEY\tSpace\nSHOW_OUTPUT\nSEND_KEY\tEnter\n' "$reading"
        done < "$f"; } > "$f.cmd"
      MYIME_ZENZAI_TIME_LIMIT_MS=0 MYIME_ZENZAI_STATS_FILE="$out.zstats" MYIME_AI_BUDGET_MS=0 \
        MYIME_HERMETIC_TEST=1 MYIME_AZOOKEY_DLL_DIR="$ENGINE" MYIME_AZOOKEY_ZENZAI_WEIGHT="$model" \
        MYIME_AZOOKEY_ZENZAI_GPU=0 TEST_TMPDIR="$f.prof" \
        "$EXE" --input "$f.cmd" --profile "$f.prof" --dictionary oss > "$f.out" 2> "$f.err" || true
      awk -v targets="$f" '
        BEGIN { while ((getline line < targets) > 0) { split(line, a, "\t"); r[++n] = a[1]; t[n] = a[2] } }
        /^all_candidate_words \{/ { block = 1; first = "" }
        block && /^    value:/ {
          v = $0; sub(/.*value: "/, "", v); sub(/"$/, "", v)
          if (first == "") first = v
        }
        block && /^\}/{ block = 0; if (first != "") { ++i; printf "%s\t%s\t%s\n", r[i], t[i], first } }
      ' "$f.out" > "$f.res"
    ) &
  done
  wait
  cat "$w"/part.*.res > "$out"
  if grep -q "candidate not found" "$w"/*.out "$w"/*.err 2> /dev/null; then
    grep -h "candidate not found" "$w"/*.out "$w"/*.err | head -3 >&2
    echo "選ぶ候補が変換の候補にありませんでした（$name）" >&2
    exit 1
  fi
}

run_mode on "$MODEL" "$PREFIX-on.tsv"
run_mode off "$NO_MODEL" "$PREFIX-off.tsv"
