"""追加の辞書（mozcdic-ut-*）を、版と SHA256 を固定して取り出す。

  python tools/fetch_ut_dictionaries.py --out <dir> sudachidict neologd ...

tools/data/ut-dictionaries.tsv に書いたコミットから取り、SHA256 が合わなければ止める。
<dir>/mozcdic-ut-<名前>.txt（bz2 を開いたもの）を作る。辞書の材料そのものはリポジトリに入れない。
"""
import argparse
import bz2
import hashlib
import urllib.request
from pathlib import Path

TABLE = Path(__file__).with_name("data") / "ut-dictionaries.tsv"
LOCAL = {"domain"}  # tools/data/domain-words.tsv（tools/build_domain_words.py の出力）
URL ="https://raw.githubusercontent.com/utuhiro78/mozcdic-ut-{n}/{c}/mozcdic-ut-{n}.txt.bz2"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("names", nargs="+")
    args = parser.parse_args()
    pins = {}
    for line in TABLE.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            name, commit, sha256 = line.split("\t")[:3]
            pins[name] = (commit, sha256)
    args.out.mkdir(parents=True, exist_ok=True)
    for name in args.names:
        if name in LOCAL:  # リポジトリの中にある自作の辞書。取り出さない
            continue
        if name not in pins:
            raise SystemExit(f"{name}: tools/data/ut-dictionaries.tsv にない")
        commit, want = pins[name]
        request = urllib.request.Request(URL.format(n=name, c=commit), headers={"User-Agent": "compound-ime-build"})
        data = urllib.request.urlopen(request, timeout=300).read()
        got = hashlib.sha256(data).hexdigest()
        if got != want:
            raise SystemExit(f"{name}: SHA256 が合わない（{got}）")
        (args.out / f"mozcdic-ut-{name}.txt").write_bytes(bz2.decompress(data))
        print("取得", name, commit[:7], want[:12])


if __name__ == "__main__":
    main()
