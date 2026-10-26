#!/bin/bash
# learn_context_guard.sh <session_handler_main> <engine dir> <model.gguf> <inputs.tsv> <out prefix> [並列数]
# 学習が文脈を壊さないかの試験（組 l）。表（tests/conversion/learn-context-guard.tsv、列: 1語のローマ字<TAB>覚えさせる書き方
# <TAB>文のローマ字<TAB>文の中で正しい書き方）の各行を、履歴を消してから次の順で流す。
#   1. 文を変換して確定する（学習の前）。
#   2. 1語を4回、覚えさせる書き方を値で選んで確定する。
#   3. 文脈を消して、同じ文を変換して確定する（学習のあと）。
#   4. 1語を変換して先頭のまま確定する（学習が効いているかの確かめ）。
# 結果は「文のローマ字<TAB>覚えさせた書き方<TAB>正しい書き方<TAB>前の確定<TAB>あとの確定<TAB>1語の確定」で、人工知能ありを -on.tsv、
# なし（重みなし）を -off.tsv に書く。覚えさせる書き方が1語の候補になかった行は外し、<出力>.missing に書く。
set -e
EXE=$1; ENGINE=$2; MODEL=$3; IN=$4; PREFIX=$5; P=${6:-2}
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
NO_MODEL="$TMP/no-model.gguf"
grep -v '^#' "$IN" | awk -F'\t' 'NF >= 4' > "$TMP/rows.tsv"

run_mode() {  # <名前> <重み> <出力>
  local name=$1 model=$2 out=$3 w="$TMP/$1"
  mkdir -p "$w"
  split -l $(( ($(wc -l < "$TMP/rows.tsv") + P - 1) / P )) "$TMP/rows.tsv" "$w/part."
  for f in "$w"/part.*; do
    ( { printf 'SEND_KEY\tON\n'
        while IFS=$'\t' read -r word learned sentence _; do
          printf 'CLEAR_ALL\nRESET_CONTEXT\nSEND_KEY\tON\n'
          printf 'SEND_KEYS\t%s\nSEND_KEY\tSpace\nSEND_KEY\tEnter\nSHOW_OUTPUT\n' "$sentence"
          for _ in 1 2 3 4; do
            printf 'SEND_KEYS\t%s\nSEND_KEY\tSpace\nSELECT_CANDIDATE_VALUE\t%s\nSEND_KEY\tEnter\n' "$word" "$learned"
          done
          printf 'RESET_CONTEXT\nSEND_KEY\tON\n'
          printf 'SEND_KEYS\t%s\nSEND_KEY\tSpace\nSEND_KEY\tEnter\nSHOW_OUTPUT\n' "$sentence"
          # 学習が効いているかの確かめ: 1語を変換して、先頭のまま確定する。
          printf 'RESET_CONTEXT\nSEND_KEY\tON\nSEND_KEYS\t%s\nSEND_KEY\tSpace\nSEND_KEY\tEnter\nSHOW_OUTPUT\n' "$word"
        done < "$f"; } > "$f.cmd"
      MYIME_ZENZAI_TIME_LIMIT_MS=0 MYIME_ZENZAI_STATS_FILE="$out.zstats" MYIME_AI_BUDGET_MS=0 \
        MYIME_HERMETIC_TEST=1 MYIME_AZOOKEY_DLL_DIR="$ENGINE" MYIME_AZOOKEY_ZENZAI_WEIGHT="$model" \
        MYIME_AZOOKEY_ZENZAI_GPU=0 TEST_TMPDIR="$f.prof" \
        "$EXE" --input "$f.cmd" --profile "$f.prof" --dictionary oss > "$f.out" 2> "$f.err" || true
      awk -F'\t' -v rows="$f" '
        BEGIN { while ((getline line < rows) > 0) { split(line, a, "\t"); s[++n] = a[3]; l[n] = a[2]; e[n] = a[4] } }
        /^result \{/ { r = 1 }
        r && /^  value:/ {
          v = $0; sub(/.*value: "/, "", v); sub(/"$/, "", v); r = 0
          ++k
          if (k % 3 == 1) before = v
          else if (k % 3 == 2) after = v
          else { i = k / 3; printf "%s\t%s\t%s\t%s\t%s\t%s\n", s[i], l[i], e[i], before, after, v }
        }
      ' "$f.out" > "$f.res"
    ) &
  done
  wait
  cat "$w"/part.*.res > "$out"
  grep -h "^candidate not found: " "$w"/*.err 2> /dev/null | sed 's/^candidate not found: //' | sort -u > "$out.missing" || true
  if [ -s "$out.missing" ]; then
    echo "覚えさせる書き方が1語の候補になく外した行（$name）: $(head -20 "$out.missing" | tr '\n' ' ')" >&2
    awk -F'\t' -v m="$out.missing" 'BEGIN { while ((getline x < m) > 0) skip[x] = 1 } !($2 in skip)' \
      "$out" > "$out.kept" && mv "$out.kept" "$out"
  fi
}

run_mode on "$MODEL" "$PREFIX-on.tsv"
run_mode off "$NO_MODEL" "$PREFIX-off.tsv"
