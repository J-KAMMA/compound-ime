#!/bin/bash
# learn_respect_convert.sh <session_handler_main> <engine dir> <model.gguf> <inputs.tsv> <out prefix> [並列数]
# 履歴の学習の試験（組 l）。1行1語の表（tests/conversion/learn-respect.tsv）を、次の順で流す。
#   1. 人工知能なしとありの両方で、履歴のない候補の窓（candidate_window）を1回ずつ調べる。窓の順で
#      先頭と違い、両方にある書き方を、その読みの選ぶ書き方にする（窓は下位の候補を展開しないので、
#      利用者が見る2番目と、all_candidate_words の2番目が違うときも正しく選べる）。
#   2. 同じ会話（1つの処理・1つのプロファイル）の中で、その書き方を4回、値で選んで確定する。
#   3. 同じ読みを変換し、先頭に来た候補を書く（ローマ字<TAB>選んだ書き方<TAB>先頭）。
# 1 の候補は <out prefix>-targets.tsv、2〜3 の結果は人工知能ありを -on.tsv、なし（重みなし）を -off.tsv に書く。
# 表の語のうち、先頭と違う共通の候補がない語は、比べられないので理由を出して除く（結果の行は捨てない）。
#
# 前後の文がある複数文節の表（tests/conversion/learn-respect-context.tsv、列: 文のローマ字<TAB>文節の読み<TAB>前の文）も、
# 同じ手順で流す。こちらは履歴のないときに文脈の手がかりが別の書き方を先頭にしている文だけを使い、その文節の元の先頭
# （人工知能なしの1語の変換の先頭）を4回選んでから、同じ文を変換する。人工知能ありの候補にもその書き方があることを
# 確かめてから流す。結果は -context-on.tsv / -context-off.tsv。
# 選ぶ命令は tools/apply_jaen_integration.py が試験の道具に足す SELECT_CANDIDATE_VALUE（値で候補を選ぶ）。
set -e
EXE=$1; ENGINE=$2; MODEL=$3; IN=$4; PREFIX=$5; P=${6:-2}
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
NO_MODEL="$TMP/no-model.gguf"
CONTEXT_TABLE="$(dirname "$IN")/learn-respect-context.tsv"
grep -v '^#' "$IN" | cut -f1 | awk 'NF' | awk '!seen[$0]++' > "$TMP/readings.txt"

probe() {  # <重み> <文節ごとの人工知能 0/1> <入力> <出力>
  local model=$1 calls=$2 input=$3 output=$4
  MYIME_CANDIDATE_WINDOW=1 MYIME_CONTEXT_SEGMENT_CALLS=$calls \
    bash "$(dirname "$0")/candidates_convert.sh" \
    "$EXE" "$ENGINE" "$model" "$input" "$output" "$P"
}

# 1. 人工知能なし・ありの候補を調べ、両方にあって先頭と違う書き方を選ぶ。
probe "$NO_MODEL" 0 "$TMP/readings.txt" "$TMP/probe-off.tsv"
probe "$MODEL" 1 "$TMP/readings.txt" "$TMP/probe-on.tsv"
python3 - "$TMP/readings.txt" "$TMP/probe-off.tsv" "$TMP/probe-on.tsv" "$TMP/targets.tsv" <<'PY'
import sys
from pathlib import Path

readings_path, off_path, on_path, out_path = sys.argv[1:5]

def load(path):
    rows = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        fields = line.split("\t")
        if len(fields) >= 2:
            rows[fields[0]] = [v for v in fields[1:] if v]
    return rows

off = load(off_path)
on = load(on_path)
readings = [line.strip() for line in Path(readings_path).read_text(encoding="utf-8").splitlines()
            if line.strip()]
rows, missing, no_alt, replaced = [], [], [], []
for reading in readings:
    left, right = off.get(reading), on.get(reading)
    if not left or not right:
        missing.append(reading)
        continue
    common = [v for v in left if v in set(right)]
    choices = [v for v in common if v != left[0]]
    if not choices:
        no_alt.append(reading)
        continue
    # 人工知能ありで既に先頭の候補は、学習が効いたかを試せないので、別の共通候補があれば避ける。
    stronger = [v for v in choices if v != right[0]]
    if stronger:
        choices = stronger
    target = choices[0]
    if len(left) > 1 and target != left[1]:
        replaced.append((reading, left[1], target))
    rows.append((reading, target))
if missing:
    print("履歴なしの候補がない読み: " + ", ".join(missing), file=sys.stderr)
    sys.exit(1)
if not rows:
    print("先頭と違う共通の候補がある読みがありませんでした", file=sys.stderr)
    sys.exit(1)
if no_alt:
    print(f"先頭と違う共通の候補がないため比べない読み {len(no_alt)} 語: "
          + ", ".join(no_alt), file=sys.stderr)
if replaced:
    print(f"人工知能なしの2番目ではなく別の共通候補にした読み {len(replaced)} 語:",
          file=sys.stderr)
    for reading, second, target in replaced[:10]:
        print(f"  {reading}: {second} -> {target}", file=sys.stderr)
Path(out_path).write_text("".join("\t".join(row) + "\n" for row in rows), encoding="utf-8")
PY
cp "$TMP/targets.tsv" "$PREFIX-targets.tsv"

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
  local expected got
  expected=$(wc -l < "$targets")
  got=$(wc -l < "$out")
  if grep -q "candidate not found" "$w"/*.out "$w"/*.err 2> /dev/null; then
    grep -h "candidate not found" "$w"/*.out "$w"/*.err | head -3 >&2
    echo "選ぶ候補が変換の候補にありませんでした（$name）" >&2
    exit 1
  fi
  if grep -h -q '^ERROR:' "$w"/*.out "$w"/*.err 2> /dev/null; then
    grep -h '^ERROR:' "$w"/*.out "$w"/*.err | head -3 >&2
    echo "変換の試験の道具がエラーを返しました（$name）" >&2
    exit 1
  fi
  if [ "$got" -ne "$expected" ] || ! awk -F'\t' 'NF < 3 || $2 == "" || $3 == "" { bad = 1 } END { exit bad }' "$out"; then
    echo "結果の行が足りないか空です（$name）: $got / $expected 行" >&2
    exit 1
  fi
}

# 前後の文がある複数文節の文: 履歴のないときの候補（人工知能なし・あり）と、1語の変換の先頭を並べ、
# 文脈が別の書き方を先頭にしている文だけを対象にする。対象は文節の元の先頭（2番目になっている書き方）。
context_probe() {  # <重み> <文節ごとの人工知能 0/1> <出力>（キー<TAB>候補…）
  local model=$1 calls=$2 output=$3 w="$TMP/cprobe-$calls"; mkdir -p "$w"
  split -l $(( ($(wc -l < "$TMP/context.tsv") + P - 1) / P )) "$TMP/context.tsv" "$w/part."
  for f in "$w"/part.*; do
    ( cut -f1,3 "$f" > "$f.inputs"
      { printf 'SEND_KEY\tON\n'
        while IFS=$'\t' read -r reading _ preceding; do
          printf 'SET_PRECEDING_TEXT\t%s\nSEND_KEYS\t%s\nSEND_KEY\tSpace\nSHOW_OUTPUT\nSEND_KEY\tEnter\nCLEAR_ALL\nRESET_CONTEXT\nSET_PRECEDING_TEXT\nSEND_KEY\tON\n' \
            "$preceding" "$reading"
        done < "$f"; } > "$f.cmd"
      MYIME_CONTEXT_SEGMENT_CALLS=$calls MYIME_ZENZAI_TIME_LIMIT_MS=0 MYIME_ZENZAI_STATS_FILE="$PREFIX-context.zstats" MYIME_AI_BUDGET_MS=0 \
        MYIME_HERMETIC_TEST=1 MYIME_AZOOKEY_DLL_DIR="$ENGINE" MYIME_AZOOKEY_ZENZAI_WEIGHT="$model" \
        MYIME_AZOOKEY_ZENZAI_GPU=0 TEST_TMPDIR="$f.prof" \
        "$EXE" --input "$f.cmd" --profile "$f.prof" --dictionary oss > "$f.out" 2> "$f.err" || true
      awk -v inputs="$f.inputs" '
        BEGIN { while ((getline line < inputs) > 0) { split(line, a, "\t"); k[++n] = a[1] } }
        /^candidate_window \{/ { wc = 1; wn = 0; delete wid; delete wval }
        wc && /^  candidate \{/ { ++wn; wid[wn] = ""; wval[wn] = "" }
        wc && /^    id:/ { v = $0; sub(/.*id: /, "", v); wid[wn] = v }
        wc && /^    value:/ {
          v = $0; sub(/.*value: "/, "", v); sub(/"$/, "", v); wval[wn] = v
        }
        wc && /^\}/{ wc = 0 }
        /^all_candidate_words \{/ { ac = 1; delete aid }
        ac && /^    id:/ { v = $0; sub(/.*id: /, "", v); curid = v }
        ac && /^    value:/ {
          v = $0; sub(/.*value: "/, "", v); sub(/"$/, "", v)
          if (curid != "") aid[curid] = v
        }
        ac && /^\}/{ ac = 0 }
        /^result \{/ { result = 1 }
        result && /^  value:/ {
          list = ""
          for (j = 1; j <= wn; j++) {
            v = (wid[j] in aid) ? aid[wid[j]] : wval[j]
            list = list "\t" v
          }
          ++i; printf "%s%s\n", k[i], list; list = ""; result = 0
        }
      ' "$f.out" > "$f.res"
    ) &
  done
  wait
  cat "$w"/part.*.res > "$output"
}

make_context_targets() {
  cut -f2 "$TMP/context.tsv" | awk 'NF' | awk '!seen[$0]++' > "$TMP/context-readings.txt"
  bash "$(dirname "$0")/candidates_convert.sh" "$EXE" "$ENGINE" "$NO_MODEL" \
    "$TMP/context-readings.txt" "$TMP/context-first.tsv" "$P"
  context_probe "$NO_MODEL" 0 "$TMP/context-probe-off.tsv"
  context_probe "$MODEL" 1 "$TMP/context-probe-on.tsv"
  python3 - "$TMP/context.tsv" "$TMP/context-first.tsv" "$TMP/context-probe-off.tsv" "$TMP/context-probe-on.tsv" "$TMP/context-targets.tsv" <<'PY'
import sys
from pathlib import Path

table, first_path, off_path, on_path, out_path = sys.argv[1:6]

def load(path):
    rows = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        fields = line.split("\t")
        if len(fields) >= 2:
            rows[fields[0]] = [v for v in fields[1:] if v]
    return rows

first = {}
for line in Path(first_path).read_text(encoding="utf-8").splitlines():
    fields = line.split("\t")
    if len(fields) >= 2:
        first[fields[0]] = fields[1]
off = load(off_path)
on = load(on_path)
rows = []
for line in Path(table).read_text(encoding="utf-8").splitlines():
    if not line or line.startswith("#"):
        continue
    fields = line.split("\t")
    if len(fields) < 3:
        continue
    key, reading, preceding = fields[0], fields[1], fields[2]
    target = first.get(reading)
    candidates = off.get(key, [])
    if not target or target not in candidates:
        print(f"履歴なしの変換に、選ぶ書き方がありません: {key} ({reading} -> {target})", file=sys.stderr)
        sys.exit(1)
    if candidates[0] == target:
        print(f"履歴なしで既に先頭です（人工知能の段を試せません）: {key} -> {target}", file=sys.stderr)
        sys.exit(1)
    if target not in on.get(key, []):
        print(f"人工知能ありの履歴なし変換に、選ぶ書き方がありません: {key} ({reading} -> {target})",
              file=sys.stderr)
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
