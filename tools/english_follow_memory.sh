#!/bin/bash
# english_follow_memory.sh <session_handler_main> <engine dir> <model.gguf> <表.tsv> <out.tsv> [並列数]
# session が「さっき確定した文字」を覚える仕組み（docs/english-follow.md）の確かめ。前の文は渡さない。
# 表の列: ローマ字<TAB>期待<TAB>前に打って確定する語<TAB>場面。各行で、前の語を打って変換・確定したあと、場面の操作をして、
# 次の語（1列目）を打って変換・確定する。場面（確定のあとの操作）:
#   nospace      何も打たず、確定のすぐあとに次の語（履歴の道の切り分け用。cause の表）
#   space        空白（変換を通らずアプリへ返る）。SEND_KEY で
#   testkey      同じ空白を、TEST_SEND_KEY だけで（Windows では、アプリが処理するキーは session に TestSendKey だけが届く）
#   same-field   入力欄の印（revision）を 1 にして、空白（同じ入力欄のまま）
#   bs-in        空白、Backspace、空白（覚えた分の中で戻る）
#   bs-beyond    空白のあと、覚えた分より前まで Backspace を打つ
#   arrow        空白、左矢印、空白（カーソルを動かした）
#   reset        空白、RESET_CONTEXT（会話の作り直し・位置変更の知らせ）、空白
#   field        revision 1 で空白、revision 2 に替えて空白（入力欄が変わった）
#   ime-off      空白、IME を切って入れ直す（切っている間のキーは session に届かない）、空白
#   wait         空白、3.5 秒待つ、空白（MYIME_ENGLISH_FOLLOW_TTL_MS=3000 で流す。docs の「覚える時間」）
#   nowait       空白、待たずに空白（wait の対照。同じく TTL 3000）
# 出力: ローマ字<TAB>文節|…<TAB>確定（次の語を確定した結果）。環境変数 MYIME_ENGLISH_FOLLOW=off で記憶ごと止められる。
set -e
EXE=$1; ENGINE=$2; MODEL=$3; IN=$4; OUT=$5; P=${6:-4}
w=$(mktemp -d); grep -v '^#' "$IN" > $w/all.tsv
split -l $(( ($(wc -l < $w/all.tsv) + P - 1) / P )) $w/all.tsv $w/part.
ops() {  # ops <場面> <前の語>
  case "$1" in
    nospace) ;;
    space) printf 'SEND_KEY\tSpace\n' ;;
    testkey) printf 'TEST_SEND_KEY\tSpace\n' ;;
    same-field) printf 'SET_REVISION\t1\nSEND_KEY\tSpace\n' ;;
    bs-in) printf 'SEND_KEY\tSpace\nSEND_KEY\tBackspace\nSEND_KEY\tSpace\n' ;;
    bs-beyond) printf 'SEND_KEY\tSpace\n'; for _ in $(seq 1 $(( ${#2} + 4 ))); do printf 'SEND_KEY\tBackspace\n'; done; printf 'SEND_KEY\tSpace\n' ;;
    arrow) printf 'SEND_KEY\tSpace\nSEND_KEY\tLeft\nSEND_KEY\tSpace\n' ;;
    reset) printf 'SEND_KEY\tSpace\nRESET_CONTEXT\nSEND_KEY\tSpace\n' ;;
    field) printf 'SET_REVISION\t1\nSEND_KEY\tSpace\nSET_REVISION\t2\nSEND_KEY\tSpace\n' ;;
    ime-off) printf 'SEND_KEY\tSpace\nSEND_KEY\tOFF\nSEND_KEY\tON\nSEND_KEY\tSpace\n' ;;
    wait) printf 'SEND_KEY\tSpace\nSLEEP\t3500\nSEND_KEY\tSpace\n' ;;
    nowait) printf 'SEND_KEY\tSpace\nSEND_KEY\tSpace\n' ;;
    *) echo "知らない場面: $1" >&2; exit 2 ;;
  esac
}
for f in $w/part.*; do
  ( cut -f1 $f > $f.inputs
    { printf 'SEND_KEY\tON\n'
      while IFS=$'\t' read -r raw _ before scenario; do
        # 場面が revision を使うとき、前の語を打つところから同じ入力欄の印を付ける
        case "$scenario" in same-field|field) printf 'SET_REVISION\t1\n' ;; esac
        printf 'SEND_KEYS\t%s\nSEND_KEY\tSpace\nSEND_KEY\tEnter\n' "$before"
        ops "$scenario" "$before"
        printf 'SEND_KEYS\t%s\nSEND_KEY\tSpace\nSHOW_OUTPUT\nSEND_KEY\tEnter\nSHOW_OUTPUT\nCLEAR_ALL\nRESET_CONTEXT\nSET_PRECEDING_TEXT\nSET_REVISION\nSEND_KEY\tON\n' "$raw"
      done < $f; } > $f.cmd
    MYIME_ZENZAI_TIME_LIMIT_MS="${MYIME_ZENZAI_TIME_LIMIT_MS:-0}" MYIME_ZENZAI_STATS_FILE="$OUT.zstats" MYIME_AI_BUDGET_MS=0 MYIME_HERMETIC_TEST=1 MYIME_AZOOKEY_DLL_DIR="$ENGINE" MYIME_AZOOKEY_ZENZAI_WEIGHT="$MODEL" \
      MYIME_AZOOKEY_ZENZAI_GPU=0 TEST_TMPDIR=$f.prof "$EXE" --input $f.cmd --profile $f.prof --dictionary oss > $f.out 2> $f.err
    awk -v inputs=$f.inputs 'BEGIN{while((getline l < inputs)>0) in_[++n]=l}
      /^preedit \{/{p=1; s=""} p&&/^    value:/{v=$0; sub(/.*value: "/,"",v); sub(/"$/,"",v); s=s v "|"} p&&/^}/{p=0; segs=s}
      /^result \{/{r=1} r&&/^  value:/{v=$0; sub(/.*value: "/,"",v); sub(/"$/,"",v); i++; printf "%s\t%s\t%s\n", in_[i], substr(segs,1,length(segs)-1), v; r=0}' $f.out > $f.res ) &
done; wait
cat $w/part.*.res > "$OUT"
rm -r "$w"
