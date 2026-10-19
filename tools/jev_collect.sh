#!/bin/bash
# jev_collect.sh <組> <engine dir> <this repository> <results dir>
# 判定専用の模型（Jev のような仕組み）の設計のための材料集め（.github/workflows/jev-data.yml が組ごとに呼ぶ）。
# 人工知能の重みを渡さずに（生成なし。Mozc と AzooKey の辞書の変換だけ）試験の文を変換し、
#   dump-<名前>.txt     文節ごとの候補の上位16（MYIME_SELECTOR_DUMP、MYIME_JEV_DUMP_K=16）
#   features-<名前>.txt 同じ候補の Mozc のコストなど（MYIME_SELECTOR_FEATURES）
#   whole-<名前>.txt    全文節の読みの AzooKey の変換の候補の JSON（MYIME_JEV_WHOLE、N_best=32）
#   <名前>.tsv          ローマ字<TAB>文節<TAB>確定（人工知能なしの出力）
# を書く。どのファイルも、文ごとに「U+0004 名前:番号」の印の行（命令 JEV_MARK）で区切る。
#   ja400、jaen（jaen270 と jaen200b）、typo（typo150 と typo150b）、reported、
#   w1〜w4（ウィキペディアの打ち込み3000文を4つに分けた番号目）、ctxw、ctxo（前後の文がある試験の前の文あり・なし）、
#   coll（話し言葉）、dom（分野: プログラミングと仮想通貨）
set -eo pipefail
GROUP=$1; E=$2; REPO=$3; OUT=$4
T=$REPO/tests/conversion
W=$(mktemp -d); mkdir -p "$OUT"; OUT=$(cd "$OUT" && pwd)
export LD_LIBRARY_PATH="$E${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
romaji() { python3 -c "import json,sys; print('\n'.join(i['romaji'] for i in json.load(open(sys.argv[1]))['items']))" "$1"; }

# run <名前> <ローマ字<TAB>前の文 の一覧> <with|without> [並列数]
run() {
  local name=$1 list=$2 mode=$3 p=${4:-4}
  local d=$W/$name; mkdir -p $d
  awk -F'\t' -v OFS='\t' '{print NR, $0}' "$list" > $d/all.tsv
  split -l $(( ($(wc -l < $d/all.tsv) + p - 1) / p )) $d/all.tsv $d/part.
  for f in $d/part.??; do
    ( { printf 'SEND_KEY\tON\n'
        while IFS=$'\t' read -r i raw before; do
          printf 'JEV_MARK\t%s:%s\n' "$name" "$i"
          [ "$mode" = with ] && printf 'SET_PRECEDING_TEXT\t%s\n' "$before"
          printf 'SEND_KEYS\t%s\nSEND_KEY\tSpace\nSHOW_OUTPUT\nSEND_KEY\tEnter\nSHOW_OUTPUT\nCLEAR_ALL\nRESET_CONTEXT\nSET_PRECEDING_TEXT\nSEND_KEY\tON\n' "$raw"
        done < $f
        printf 'JEV_MARK\tend\n'; } > $f.cmd
      cut -f2 $f > $f.inputs
      MYIME_SELECTOR_DUMP=$f.dump MYIME_SELECTOR_FEATURES=$f.features MYIME_JEV_WHOLE=$f.whole \
        MYIME_JEV_DUMP_K=16 MYIME_JEV_NBEST=32 MYIME_SELECTOR=0 MYIME_PREFETCH_DELAY=0 \
        MYIME_ZENZAI_TIME_LIMIT_MS=0 MYIME_AI_BUDGET_MS=0 MYIME_HERMETIC_TEST=1 MYIME_AZOOKEY_DLL_DIR="$E" \
        MYIME_AZOOKEY_ZENZAI_WEIGHT=$W/no-such-model.gguf MYIME_AZOOKEY_ZENZAI_GPU=0 TEST_TMPDIR=$f.prof \
        "$E/session_handler_main" --input $f.cmd --profile $f.prof --dictionary oss > $f.out 2> $f.err || true
      awk -v inputs=$f.inputs 'BEGIN{while((getline l < inputs)>0) in_[++n]=l}
        /^preedit \{/{p=1; s=""} p&&/^    value:/{v=$0; sub(/.*value: "/,"",v); sub(/"$/,"",v); s=s v "|"} p&&/^}/{p=0; segs=s}
        /^result \{/{r=1} r&&/^  value:/{v=$0; sub(/.*value: "/,"",v); sub(/"$/,"",v); i++; printf "%s\t%s\t%s\n", in_[i], substr(segs,1,length(segs)-1), v; r=0}' $f.out > $f.res ) &
  done; wait
  cat $d/part.??.res > $OUT/$name.tsv
  for k in dump features whole; do cat $d/part.??.$k > $OUT/$k-$name.txt 2> /dev/null || : > $OUT/$k-$name.txt; done
  head -c 2000 $d/part.aa.err > $OUT/err-$name.txt || true
  echo "$name: 入力 $(wc -l < $list) 文、確定 $(wc -l < $OUT/$name.tsv) 文、書き出し $(grep -c . $OUT/dump-$name.txt) 行、文全体 $(grep -c . $OUT/whole-$name.txt) 行"
}

json_list() { romaji "$1" | awk '{print $0 "\t"}'; }
case $GROUP in
ja400) json_list $T/ja400.json > $W/l.tsv; run ja400 $W/l.tsv without ;;
jaen)
  awk '{print $0 "\t"}' $T/jaen270.txt > $W/a.tsv; run jaen270 $W/a.tsv without
  json_list $T/jaen200b.json > $W/b.tsv; run jaen200b $W/b.tsv without ;;
typo)
  json_list $T/typo150.json > $W/a.tsv; run typo150 $W/a.tsv without
  json_list $T/typo150b.json > $W/b.tsv; run typo150b $W/b.tsv without ;;
reported) json_list $T/reported.json > $W/l.tsv; run reported $W/l.tsv without ;;
w*)
  grep -v '^#' $T/wiki-typing.tsv | cut -f1 | awk -v k="${GROUP#w}" '(NR - 1) % 4 == k - 1 {print $0 "\t"}' > $W/l.tsv
  run wiki$GROUP $W/l.tsv without ;;
ctxw) grep -v '^#' $T/context.tsv | awk -F'\t' -v OFS='\t' '{print $1, $3}' > $W/l.tsv; run ctxw $W/l.tsv with ;;
ctxo) grep -v '^#' $T/context.tsv | awk -F'\t' '{print $1 "\t"}' > $W/l.tsv; run ctxo $W/l.tsv without ;;
coll) grep -v '^#' $T/colloquial.tsv | awk -F'\t' '{print $1 "\t"}' > $W/l.tsv; run coll $W/l.tsv without ;;
dom)
  grep -v '^#' $T/domain-prog.tsv | awk -F'\t' '{print $1 "\t"}' > $W/a.tsv; run prog $W/a.tsv without
  grep -v '^#' $T/domain-crypto.tsv | awk -F'\t' '{print $1 "\t"}' > $W/b.tsv; run crypto $W/b.tsv without ;;
*) echo "組は ja400、jaen、typo、reported、w1〜w4、ctxw、ctxo、coll、dom のどれか" >&2; exit 2 ;;
esac
