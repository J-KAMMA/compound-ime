#!/bin/bash
# selector_collect.sh <組> <engine dir> <model.gguf> <this repository> <results dir> [学習用の文.tsv] [組の数]
# 選び手の段階2の材料集め（.github/workflows/selector-data.yml が組ごとに別の計算機で呼ぶ）。
# 文を変換エンジンに通し、候補の書き出し（MYIME_SELECTOR_DUMP）、候補ごとのコスト
# （MYIME_SELECTOR_FEATURES）、Zenz の尤度（MYIME_SELECTOR_SCORE）を取る。出力は変えない。
#   t<番号>: 学習用の文（tools/wiki_typing_test.py で train-00011 から作ったもの）の <番号> 番目の組
#   ja400, jaen: 試験の文（日本語だけの400文、英単語まじりの270文と200文）
#   w<番号>: ウィキペディアの打ち込み試験（tests/conversion/wiki-typing.tsv）を6つに分けた <番号> 番目
#   x<番号>: 前後の文がある試験（tests/conversion/context.tsv、前の文あり）を2つに分けた <番号> 番目
# 書き出すもの: <組>.tsv（ローマ字<TAB>文節<TAB>確定）、dump-<組>.txt、features-<組>.txt、score-<組>.txt
set -eo pipefail
GROUP=$1; E=$2; MODEL=$3; REPO=$4; OUT=$5; TRAIN=$6; SHARDS=${7:-16}
T=$REPO/tests/conversion
BATCH="bash $REPO/tools/batch_convert.sh $E/session_handler_main $E $MODEL"
W=$(mktemp -d); mkdir -p "$OUT"; OUT=$(cd "$OUT" && pwd)
export LD_LIBRARY_PATH="$E${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export MYIME_SELECTOR_DUMP=$OUT/dump-$GROUP.txt
export MYIME_SELECTOR_FEATURES=$OUT/features-$GROUP.txt
# Zenz で採点し直す尤度（段階1、重い）は SELECTOR_SCORE=1 のときだけ。段階2b の Zenzai の計算済みの
# 分布の記録は features-<組>.txt の行の終わりに入る（推論は増えない）。
if [ "${SELECTOR_SCORE:-0}" = 1 ]; then export MYIME_SELECTOR_SCORE=$OUT/score-$GROUP.txt; else unset MYIME_SELECTOR_SCORE; fi
romaji() { python3 -c "import json,sys; print('\n'.join(i['romaji'] for i in json.load(open(sys.argv[1]))['items']))" "$1"; }
# shard <ファイル> <組の数> <番号>: 行を組の数に分けた <番号> 番目（1から）
shard() { awk -v n="$2" -v k="$3" '(NR - 1) % n == k - 1' "$1"; }

case $GROUP in
t*)
  grep -v '^#' "$TRAIN" | cut -f1 > $W/all.txt
  shard $W/all.txt "$SHARDS" "${GROUP#t}" > $W/in.txt
  $BATCH $W/in.txt $OUT/$GROUP.tsv 4
  ;;
ja400)
  romaji $T/ja400.json > $W/in.txt
  $BATCH $W/in.txt $OUT/$GROUP.tsv 4
  ;;
jaen)
  cp $T/jaen270.txt $W/in.txt
  romaji $T/jaen200b.json >> $W/in.txt
  $BATCH $W/in.txt $OUT/$GROUP.tsv 4
  ;;
w*)
  grep -v '^#' $T/wiki-typing.tsv | cut -f1 > $W/all.txt
  shard $W/all.txt 6 "${GROUP#w}" > $W/in.txt
  $BATCH $W/in.txt $OUT/$GROUP.tsv 4
  ;;
x*)
  grep -v '^#' $T/context.tsv > $W/all.tsv
  { echo '#'; shard $W/all.tsv 2 "${GROUP#x}"; } > $W/in.tsv
  bash $REPO/tools/context_convert.sh $E/session_handler_main $E $MODEL $W/in.tsv $OUT/$GROUP.tsv with 4
  ;;
*)
  echo "組は t<番号>、ja400、jaen、w<番号>、x<番号> のどれか" >&2; exit 2 ;;
esac
echo "$GROUP: $(wc -l < $OUT/$GROUP.tsv) 文、書き出し $(wc -l < $MYIME_SELECTOR_DUMP) 行、分布の記録つき $(grep -c $'\x03' $MYIME_SELECTOR_FEATURES || true) 行"
