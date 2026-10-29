#!/bin/bash
# learn_sticky_convert.sh <session_handler_main> <engine dir> <model.gguf> <inputs.tsv> <out prefix>
# 選び直しが次の変換に効くかの試験（組 l）。表（tests/conversion/learn-sticky.tsv、列: 種類<TAB>選ぶ入力のローマ字<TAB>
# 選ぶ書き方<TAB>確かめる入力のローマ字<TAB>先頭に来てほしい書き方）の各行を、履歴を消してから次の順で流す。
#   0. 確かめる入力を変換して確定する（学習の前。すでに望みの書き方なら、その行は数えない）。履歴を消す。
#   1〜2. 選ぶ入力を変換し、最初の文節で選ぶ書き方を選んで確定する（2回）。選ぶ書き方が「KEY:F10」の形なら、
#      1回目は候補から選ぶ代わりにそのキーを送り（F キーで英字を大文字にする場合）、2回目は押さずに確定する。
#   3. 確かめる入力を変換して、先頭のまま確定する。
# 文節の区切りは決めず、確定した文に望みの書き方が入っているかで見る。
# 前の文の扱いを2通り流す: ctx は変換のたびに違う前の文を渡す（ふつうのアプリと同じ。前の文は確定のたびに変わる）、
# plain は前の文を渡さない。人工知能あり（-on.tsv）となし（-off.tsv）の両方。
# 結果は「前の文の扱い<TAB>種類<TAB>選ぶ入力<TAB>選ぶ書き方<TAB>確かめる入力<TAB>望み<TAB>学習の前<TAB>1回目<TAB>2回目<TAB>学習のあと」。
set -e
EXE=$1; ENGINE=$2; MODEL=$3; IN=$4; PREFIX=$5
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
NO_MODEL="$TMP/no-model.gguf"
grep -v '^#' "$IN" | awk -F'\t' 'NF >= 5' > "$TMP/rows.tsv"
# 変換のたびに違う前の文（同じ前の文が二度と来ない、ふつうの書き方をまねる）。
CONTEXTS=("きのうの記録を見直した。" "次の段落に移る。" "ここから別の話になる。" "メモの続きを書く。")

convert() {  # <前の文の番号|空> <ローマ字> <選ぶ書き方|空>
  printf 'RESET_CONTEXT\nSEND_KEY\tON\n'
  if [ -n "$1" ]; then printf 'SET_PRECEDING_TEXT\t%s\n' "${CONTEXTS[$1]}"; fi
  printf 'SEND_KEYS\t%s\nSEND_KEY\tSpace\n' "$2"
  case "$3" in
    "") ;;
    KEY:*) for key in ${3#KEY:}; do printf 'SEND_KEY\t%s\n' "$key"; done ;;
    *) printf 'SELECT_CANDIDATE_VALUE\t%s\n' "$3" ;;
  esac
  printf 'SEND_KEY\tEnter\nSHOW_OUTPUT\n'
}

run_mode() {  # <前の文の扱い ctx|plain> <重み> <出力>
  local mode=$1 model=$2 out=$3 c0="" c1="" c2="" c3=""
  if [ "$mode" = ctx ]; then c0=0; c1=1; c2=2; c3=3; fi
  { printf 'SEND_KEY\tON\n'
    while IFS=$'\t' read -r kind pick value check expected; do
      printf 'CLEAR_ALL\n'
      convert "$c0" "$check" ""
      printf 'CLEAR_ALL\n'
      convert "$c1" "$pick" "$value"
      # F キーは押すたびに次の形へ回るので、2回目は押さずに先頭のまま確定する（1回目で覚えていれば望みの形）。
      case "$value" in KEY:*) convert "$c2" "$pick" "" ;; *) convert "$c2" "$pick" "$value" ;; esac
      convert "$c3" "$check" ""
    done < "$TMP/rows.tsv"; } > "$TMP/$mode.cmd"
  MYIME_HISTORY_TRACE=1 MYIME_ZENZAI_TIME_LIMIT_MS=0 MYIME_AI_BUDGET_MS=0 \
    MYIME_HERMETIC_TEST=1 MYIME_AZOOKEY_DLL_DIR="$ENGINE" MYIME_AZOOKEY_ZENZAI_WEIGHT="$model" \
    MYIME_AZOOKEY_ZENZAI_GPU=0 TEST_TMPDIR="$TMP/$mode.prof" \
    "$EXE" --input "$TMP/$mode.cmd" --profile "$TMP/$mode.prof" --dictionary oss > "$TMP/$mode.out" 2> "$TMP/$mode.err" || true
  awk -v rows="$TMP/rows.tsv" -v mode="$mode" '
    BEGIN { while ((getline line < rows) > 0) row[++n] = line }
    /^result \{/ { r = 1 }
    r && /^  value:/ {
      v = $0; sub(/.*value: "/, "", v); sub(/"$/, "", v); r = 0
      got[++k % 4] = v
      if (k % 4 == 0) printf "%s\t%s\t%s\t%s\t%s\t%s\n", mode, row[k / 4], got[1], got[2], got[3], got[0]
    }
  ' "$TMP/$mode.out" >> "$out"
  # 学習と並べ替えの判断（MYIME_HISTORY_TRACE）を、調べられるように結果の横に残す。
  grep -a "^history " "$TMP/$mode.err" > "${out%.tsv}-$mode-trace.txt" || true
  grep -h "^candidate not found: " "$TMP/$mode.err" 2> /dev/null | sed 's/^candidate not found: //' | sort -u \
    | sed "s/^/選べなかった書き方（$mode）: /" >&2 || true
}

for side in on off; do
  model=$MODEL; [ $side = off ] && model=$NO_MODEL
  : > "$PREFIX-$side.tsv"
  run_mode ctx "$model" "$PREFIX-$side.tsv"
  run_mode plain "$model" "$PREFIX-$side.tsv"
done
