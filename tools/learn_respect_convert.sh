#!/bin/bash
# learn_respect_convert.sh <session_handler_main> <engine dir> <model.gguf> <inputs.tsv> <out prefix> [並列数]
# 履歴の学習の試験（組 l）。1行1語の表（tests/conversion/learn-respect.tsv）を、次の順で流す。
#   1. 人工知能なし（Mozc だけ）で1回ずつ変換し、先頭と違う2番目の候補を、その読みの選ぶ書き方にする。
#   2. 同じ会話（1つの処理・1つのプロファイル）の中で、その書き方を4回、値で選んで確定する。
#   3. 同じ読みを変換し、先頭に来た候補を書く（ローマ字<TAB>選んだ書き方<TAB>先頭）。
# 1 の候補は <out prefix>-targets.tsv、2〜3 の結果は人工知能ありを -on.tsv、なし（重みなし）を -off.tsv に書く。
#
# 前後の文がある複数文節の表（tests/conversion/learn-respect-context.tsv、列: 文のローマ字<TAB>文節の読み<TAB>前の文）も、
# 同じ手順で流す。こちらは履歴のないときに文脈の手がかりが別の書き方を先頭にしている文だけを使い、その文節の元の先頭
# （人工知能なしの1語の変換の先頭）を4回選んでから、同じ文を変換する。結果は -context-on.tsv / -context-off.tsv。
# 選ぶ命令は tools/apply_jaen_integration.py が試験の道具に足す SELECT_CANDIDATE_VALUE（値で候補を選ぶ）。
set -e
EXE=$1; ENGINE=$2; MODEL=$3; IN=$4; PREFIX=$5; P=${6:-2}
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
NO_MODEL="$TMP/no-model.gguf"
CONTEXT_TABLE="$(dirname "$IN")/learn-respect-context.tsv"
grep -v '^#' "$IN" | cut -f1 | awk 'NF' | awk '!seen[$0]++' > "$TMP/readings.txt"

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

run_mode() {  # <名前> <重み> <出力> <対象の表> [行ごとに履歴を消す]
  local name=$1 model=$2 out=$3 targets=$4 isolate=${5:-} w="$TMP/$1"
  # 人工知能ありのときだけ、前の文がある複数文節でも文節ごとの人工知能を呼ぶ（既定は全文生成に任せる）。
  # なしのときは重みがないので呼ばない。
  local segment_calls=0
  if [ -n "$model" ] && [ "$model" != "$NO_MODEL" ]; then segment_calls=1; fi
  mkdir -p "$w"
  split -l $(( ($(wc -l < "$targets") + P - 1) / P )) "$targets" "$w/part."
  for f in "$w"/part.*; do
    ( { printf 'SEND_KEY\tON\n'
        while IFS=$'\t' read -r reading target preceding; do
          if [ -n "$isolate" ]; then printf 'CLEAR_ALL\nRESET_CONTEXT\n'; fi
          if [ -n "${preceding:-}" ]; then printf 'SET_PRECEDING_TEXT\t%s\n' "$preceding"; fi
          # 同じ書き方を4回選んで確定する。履歴を消す命令（CLEAR_ALL）ははさまない。
          for _ in 1 2 3 4; do
            printf 'SEND_KEYS\t%s\nSEND_KEY\tSpace\nSELECT_CANDIDATE_VALUE\t%s\nSEND_KEY\tEnter\n' \
              "$reading" "$target"
          done
          # 5回目は選ばずに、先頭の候補を記録する。
          if [ -n "${preceding:-}" ]; then printf 'SET_PRECEDING_TEXT\t%s\n' "$preceding"; fi
          printf 'SEND_KEYS\t%s\nSEND_KEY\tSpace\nSHOW_OUTPUT\nSEND_KEY\tEnter\n' "$reading"
        done < "$f"; } > "$f.cmd"
      MYIME_CONTEXT_SEGMENT_CALLS=$segment_calls MYIME_ZENZAI_TIME_LIMIT_MS=0 MYIME_ZENZAI_STATS_FILE="$out.zstats" MYIME_AI_BUDGET_MS=0 \
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
  # 人工知能ありの変換では、なしの2番目が候補の一覧に出ないことがある。その書き方は選べないので、
  # その行を結果から外し（採点はあり・なし両方にある語だけを比べる）、外した書き方を記録する。
  grep -h "^candidate not found: " "$w"/*.err 2> /dev/null | sed 's/^candidate not found: //' | sort -u > "$out.missing" || true
  if [ -s "$out.missing" ]; then
    echo "選ぶ候補が変換の候補になく外した書き方（$name）: $(wc -l < "$out.missing") 件: $(head -20 "$out.missing" | tr '\n' ' ')" >&2
    awk -F'\t' -v m="$out.missing" 'BEGIN { while ((getline l < m) > 0) skip[l] = 1 } !($2 in skip)' \
      "$out" > "$out.kept" && mv "$out.kept" "$out"
  fi
}

# 前後の文がある複数文節の文: 履歴のないときの候補（人工知能なし）と、1語の変換の先頭を並べ、
# 文脈が別の書き方を先頭にしている文だけを対象にする。対象は文節の元の先頭（2番目になっている書き方）。
context_probe() {  # 前の文あり・履歴なしの候補を $TMP/context-probe.tsv に書く（キー<TAB>候補…）
  local w="$TMP/cprobe"; mkdir -p "$w"
  split -l $(( ($(wc -l < "$TMP/context.tsv") + P - 1) / P )) "$TMP/context.tsv" "$w/part."
  for f in "$w"/part.*; do
    ( cut -f1,3 "$f" > "$f.inputs"
      { printf 'SEND_KEY\tON\n'
        while IFS=$'\t' read -r reading _ preceding; do
          printf 'SET_PRECEDING_TEXT\t%s\nSEND_KEYS\t%s\nSEND_KEY\tSpace\nSHOW_OUTPUT\nSEND_KEY\tEnter\nCLEAR_ALL\nRESET_CONTEXT\nSET_PRECEDING_TEXT\nSEND_KEY\tON\n' \
            "$preceding" "$reading"
        done < "$f"; } > "$f.cmd"
      MYIME_ZENZAI_TIME_LIMIT_MS=0 MYIME_ZENZAI_STATS_FILE="$PREFIX-context.zstats" MYIME_AI_BUDGET_MS=0 \
        MYIME_HERMETIC_TEST=1 MYIME_AZOOKEY_DLL_DIR="$ENGINE" MYIME_AZOOKEY_ZENZAI_WEIGHT="$NO_MODEL" \
        MYIME_AZOOKEY_ZENZAI_GPU=0 TEST_TMPDIR="$f.prof" \
        "$EXE" --input "$f.cmd" --profile "$f.prof" --dictionary oss > "$f.out" 2> "$f.err" || true
      awk -v inputs="$f.inputs" '
        BEGIN { while ((getline line < inputs) > 0) { split(line, a, "\t"); k[++n] = a[1] } }
        /^all_candidate_words \{/ { block = 1; list = ""; first = "" }
        block && /^    value:/ {
          v = $0; sub(/.*value: "/, "", v); sub(/"$/, "", v)
          if (first == "") first = v
          list = list "\t" v
        }
        block && /^\}/{ block = 0; if (first != "") { ++i; printf "%s%s\n", k[i], list } }
      ' "$f.out" > "$f.res"
    ) &
  done
  wait
  cat "$w"/part.*.res > "$TMP/context-probe.tsv"
}

make_context_targets() {
  cut -f2 "$TMP/context.tsv" | awk 'NF' | awk '!seen[$0]++' > "$TMP/context-readings.txt"
  bash "$(dirname "$0")/candidates_convert.sh" "$EXE" "$ENGINE" "$NO_MODEL" \
    "$TMP/context-readings.txt" "$TMP/context-first.tsv" "$P"
  context_probe
  python3 - "$TMP/context.tsv" "$TMP/context-first.tsv" "$TMP/context-probe.tsv" "$TMP/context-targets.tsv" <<'PY'
import sys
from pathlib import Path

table, first_path, probe_path, out_path = sys.argv[1:5]
first = {}
for line in Path(first_path).read_text(encoding="utf-8").splitlines():
    fields = line.split("\t")
    if len(fields) >= 2:
        first[fields[0]] = fields[1]
probe = {}
for line in Path(probe_path).read_text(encoding="utf-8").splitlines():
    fields = line.split("\t")
    if len(fields) >= 2:
        probe[fields[0]] = fields[1:]
rows = []
for line in Path(table).read_text(encoding="utf-8").splitlines():
    if not line or line.startswith("#"):
        continue
    fields = line.split("\t")
    if len(fields) < 3:
        continue
    key, reading, preceding = fields[0], fields[1], fields[2]
    target = first.get(reading)
    candidates = probe.get(key, [])
    # 文の中の文節は「記者の」のように助詞まで含むことがあるので、書き方＋ひらがなの候補をその文節の書き方にする。
    if target and target not in candidates:
        target = next((c for c in candidates if c.startswith(target)
                       and all("ぁ" <= ch <= "ゖ" for ch in c[len(target):])), target)
    if not target or target not in candidates:
        print(f"履歴なしの変換に、選ぶ書き方がありません: {key} ({reading} -> {target})", file=sys.stderr)
        sys.exit(1)
    if candidates[0] == target:
        print(f"履歴なしで既に先頭です（人工知能の段を試せません）: {key} -> {target}", file=sys.stderr)
        sys.exit(1)
    rows.append((key, target, preceding))
Path(out_path).write_text("".join("\t".join(row) + "\n" for row in rows), encoding="utf-8")
PY
}

run_mode on "$MODEL" "$PREFIX-on.tsv" "$TMP/targets.tsv"
run_mode off "$NO_MODEL" "$PREFIX-off.tsv" "$TMP/targets.tsv"

if [ -f "$CONTEXT_TABLE" ]; then
  grep -v '^#' "$CONTEXT_TABLE" | awk -F'\t' 'NF >= 3' > "$TMP/context.tsv"
  if [ -s "$TMP/context.tsv" ]; then
    make_context_targets
    cp "$TMP/context-targets.tsv" "$PREFIX-context-targets.tsv"
    run_mode context-on "$MODEL" "$PREFIX-context-on.tsv" "$TMP/context-targets.tsv" isolate
    run_mode context-off "$NO_MODEL" "$PREFIX-context-off.tsv" "$TMP/context-targets.tsv" isolate
  fi
fi
