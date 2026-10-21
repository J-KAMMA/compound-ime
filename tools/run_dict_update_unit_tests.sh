#!/bin/bash
# 辞書の更新の単体試験を、Mozc なしで流す（native/dict_update。g++ と python の cryptography が要る）。
#   bash tools/run_dict_update_unit_tests.sh <python（cryptography が入ったもの）> [作業の場所]
# 通信は 127.0.0.1 だけ（端から端までの試験が、手元の簡単な配布ページから取る）。
set -eo pipefail
PY=${1:-python3}
R=$(cd "$(dirname "$0")/.." && pwd)
W=${2:-$(mktemp -d)}
mkdir -p "$W"
SRC="$R/native/dict_update/crypto.cc $R/native/dict_update/data.cc $R/native/dict_update/manifest.cc $R/native/dict_update/updater.cc $R/native/dict_update/fetcher.cc $R/native/dict_update/service.cc"
echo "== 暗号の部品（python の cryptography・hashlib と照らし合わせ）"
g++ -std=c++20 -O2 -Wall -Wextra -pthread -I "$R/native" "$R/native/dict_update/crypto.cc" "$R/native/dict_update/crypto_check.cc" -o "$W/crypto_check"
$PY "$R/tools/dict_update_crypto_check.py" "$W/crypto_check"
echo "== 本体の部品の単体試験（address と undefined の検査つき）"
$PY "$R/tools/dict_update_fixtures.py" "$W/fixtures"
g++ -std=c++20 -O1 -g -fsanitize=address,undefined -fno-sanitize-recover=undefined -Wall -Wextra -pthread -I "$R/native" $SRC "$R/native/dict_update/dict_update_test.cc" -o "$W/dict_update_test"
"$W/dict_update_test" "$W/fixtures"
echo "== 端から端まで（本物の取得の部品で、127.0.0.1 の配布ページから）"
g++ -std=c++20 -O1 -g -Wall -Wextra -pthread -I "$R/native" $SRC "$R/native/dict_update/dict_update_tool.cc" -o "$W/dict_update_tool"
$PY "$R/tools/dict_update_scenarios.py" tool "$W/dict_update_tool"
echo "== 配布物を作る道具（make_dict_release.py）の確かめ"
$PY "$R/tools/test_make_dict_release.py"
echo "== 月1回の自動更新の候補を入れる環境変数（tools/dict_candidate_env.sh。run_tests.sh の DICT_CANDIDATE_DIR と同じ）"
$PY - "$R" "$W" "$W/dict_update_tool" <<'PYEOF'
import os, subprocess, sys
from pathlib import Path
R, W, tool = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
sys.path.insert(0, str(R / "tools"))
import dict_update_fixtures as fx
import make_dict_release as mdr
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
key = Ed25519PrivateKey.generate()
# 本体の道具（dict_update_tool info）が焼いている品詞の表の値と同じにする
info = subprocess.run([tool, "info"], capture_output=True, text=True).stdout.split()
sha = info[1].split("=")[1]
cand = W / "candidate"
os.makedirs(cand, exist_ok=True)
base = "https://github.com/J-KAMMA/compound-ime/releases/download/dict-20261101"
for kind, name, text in (("supplement", "supplement.tsv", "ぬぬぬぬぬぬ\t1851\t1851\t2500\tCandidateProbe\n"), ("english", "english-extra.tsv", "named\tcandidatetool\n")):
    (cand / name).write_text(text, encoding="utf-8")
files = [(k, n, (cand / n).read_bytes(), f"{base}/{n}") for k, n in (("supplement", "supplement.tsv"), ("english", "english-extra.tsv"))]
manifest = mdr.build_manifest("20261101", sha, files, "2026-11-01").encode()
(cand / "manifest.txt").write_bytes(manifest)
(cand / "manifest.txt.sig").write_text(key.sign(manifest).hex() + "\n")
script = f'. "{R}/tools/dict_candidate_env.sh"; dict_candidate_env "{cand}" "{R}" "{W}/cand-state"; MYIME_HERMETIC_TEST=1 "{tool}" update ぬぬぬぬぬぬ'
env = dict(os.environ, DICT_CANDIDATE_PUBKEY=fx.pub_hex(key))
out = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True).stdout
print(out.strip())
assert "status=installed" in out and "CandidateProbe" in out, "候補の辞書を、手元のファイルから署名つきで入れられない"
print("candidate install ok")
PYEOF
