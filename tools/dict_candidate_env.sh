# 辞書の更新の候補（署名つきの配布物）を、本体の取り込みの道で入れるための環境変数を決める。source して使う。
#   . tools/dict_candidate_env.sh
#   dict_candidate_env <配布物の場所> <リポジトリ> <置き場所>
# 目録の中の URL（配布ページ）は変えずに、手元のファイルから取る（試験のときだけ効く MYIME_DICT_UPDATE_REWRITE）。
# 公開鍵は <リポジトリ>/tools/dict-update/public-key.txt（環境変数 DICT_CANDIDATE_PUBKEY があればそれ）。
dict_candidate_env() {
  local cand pub prefix
  cand=$(cd "$1" && pwd)
  pub=${DICT_CANDIDATE_PUBKEY:-$(grep -v '^#' "$2/tools/dict-update/public-key.txt" | grep -v '^$' | head -1)}
  prefix=$(awk -F'\t' '$1=="file"{print $6; exit}' "$cand/manifest.txt" | sed 's|[^/]*$||')
  export MYIME_DICT_UPDATE_DIR=$3 MYIME_DICT_UPDATE_BASE=file://$cand MYIME_DICT_UPDATE_PUBKEY=$pub \
    MYIME_DICT_UPDATE_URL_PREFIX=$prefix MYIME_DICT_UPDATE_REWRITE="$prefix=file://$cand/"
}
