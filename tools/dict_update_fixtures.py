"""辞書の更新の試験に使う配布物（署名つき）を、試験用の鍵で作る。

  python tools/dict_update_fixtures.py <出力の場所>

作るもの（<出力の場所>/）:
  key.hex            公開鍵（16進）。本体の試験はこれで署名を確かめる
  other-key.hex      別の鍵の公開鍵（署名が合わないことの確かめ用）
  pos.txt            品詞の表の SHA-256 と行数
  v1/ v2/ older/     正しい配布物（版 20261101、20261201、20260901）。v1 は ずずずぷろーぶ → ZzyzxProbe だけ
  bad-sig/           別の鍵で署名したもの（20261210）
  bad-hash/          署名は合うが、辞書のファイルが目録のハッシュと合わない（20261215）
  bad-content/       署名もハッシュも合うが、品詞番号が範囲の外の行がある（20261220）
  wrong-pos/         署名は合うが、品詞の表の SHA-256 が本体のものと違う（20261225）
  bad-url/           署名は合うが、ファイルの URL が許した場所の外（20261226）
  huge/              署名は合うが、大きさの宣言が上限を超える（20261227）
試験の URL は https://example.test/<名前>/<ファイル>。
"""
import hashlib
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_dict_release as mdr  # noqa: E402

POS_COUNT = 2000
NOUN = 1851 % POS_COUNT
BASE = "https://example.test"

SUPPLEMENT_V1 = f"ずずずぷろーぶ\t{NOUN}\t{NOUN}\t6000\tZzyzxProbe\n"
SUPPLEMENT_V2 = SUPPLEMENT_V1 + f"ずずずぷろーぶ\t{NOUN}\t{NOUN}\t6100\tZzyzxProbe Two\nぽぽぽあいてむ\t{NOUN}\t{NOUN}\t7000\tPopopo Item\n"
ENGLISH_V1 = "named\tzzyzxtool\nsignal\tzzyzxsignal\ncasing\tzzyzxtool\tZzyzxTool\ncasing2\tzzyzxsignal\tZzyzxSignal\nphrase\tzzyzx test phrase\ncurated\tzzyzxword\n"
ENGLISH_V2 = ENGLISH_V1 + "named\tpopopotool\ncasing\tpopopotool\tPopopoTool\n"


def pub_hex(key):
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()


def make(out, name, version, supplement, english, key, pos_sha, url_base=None, tamper=None, size_override=None, url_override=None):
    d = out / name
    d.mkdir(parents=True, exist_ok=True)
    url_base = url_base or f"{BASE}/{name}"
    files = []
    for kind, fname, text in (("supplement", "supplement.tsv", supplement), ("english", "english-extra.tsv", english)):
        data = text.encode("utf-8")
        url = url_override if (url_override and kind == "supplement") else f"{url_base}/{fname}"
        files.append((kind, fname, data, url))
        (d / fname).write_bytes(data)
    manifest = mdr.build_manifest(version, pos_sha, files, "2026-10-21")
    if size_override is not None:
        manifest = manifest.replace(f"\tsupplement.tsv\t{len(files[0][2])}\t", f"\tsupplement.tsv\t{size_override}\t")
    mb = manifest.encode("utf-8")
    (d / "manifest.txt").write_bytes(mb)
    (d / "manifest.txt.sig").write_text(key.sign(mb).hex() + "\n")
    if tamper:
        raw = bytearray((d / tamper).read_bytes())  # 大きさは変えずに、1文字だけ書き換える
        raw[0] = ord("Z") if raw[0] != ord("Z") else ord("Y")
        (d / tamper).write_bytes(bytes(raw))


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    key, other = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    pos_sha = hashlib.sha256(b"fixture id.def").hexdigest()
    (out / "key.hex").write_text(pub_hex(key) + "\n")
    (out / "other-key.hex").write_text(pub_hex(other) + "\n")
    (out / "pos.txt").write_text(f"{pos_sha} {POS_COUNT}\n")
    make(out, "v1", "20261101", SUPPLEMENT_V1, ENGLISH_V1, key, pos_sha)
    make(out, "v2", "20261201", SUPPLEMENT_V2, ENGLISH_V2, key, pos_sha)
    make(out, "older", "20260901", SUPPLEMENT_V1, ENGLISH_V1, key, pos_sha)
    make(out, "bad-sig", "20261210", SUPPLEMENT_V2, ENGLISH_V2, other, pos_sha)
    make(out, "bad-hash", "20261215", SUPPLEMENT_V2, ENGLISH_V2, key, pos_sha, tamper="supplement.tsv")
    bad_line = f"ぱぱぱ\t{POS_COUNT + 5}\t{NOUN}\t6000\tOutOfRange\n"
    make(out, "bad-content", "20261220", SUPPLEMENT_V2 + bad_line, ENGLISH_V2, key, pos_sha)
    make(out, "wrong-pos", "20261225", SUPPLEMENT_V2, ENGLISH_V2, key, hashlib.sha256(b"another id.def").hexdigest())
    make(out, "bad-url", "20261226", SUPPLEMENT_V2, ENGLISH_V2, key, pos_sha, url_override="https://evil.example/supplement.tsv")
    make(out, "huge", "20261227", SUPPLEMENT_V2, ENGLISH_V2, key, pos_sha, size_override=999999999)
    print("fixtures", out)


if __name__ == "__main__":
    main()
