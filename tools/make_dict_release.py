"""辞書の配布物（目録と署名つき）を作る・確かめる。月1回の流れ（.github/workflows/dict-update.yml）と、
試験の組み立て（tools/dict_update_fixtures.py）が使う。本体側の読み取りは native/dict_update/。

  python tools/make_dict_release.py keygen                      # 署名の鍵の組を作る（秘密鍵は一度だけ表示）
  python tools/make_dict_release.py pos-info <id.def>           # 品詞の表の SHA-256 と行数
  python tools/make_dict_release.py build --supplement supplement.tsv --english english-extra.tsv \
      --version 20261101 --pos-table-sha <sha> --url-base https://github.com/J-KAMMA/compound-ime/releases/download/dict-20261101 \
      --out release/ [--key-env DICT_SIGNING_KEY | --key-file key.hex]
  python tools/make_dict_release.py verify release/ --public-key <hex> --pos-table-sha <sha> [--pos-count N]
  python tools/make_dict_release.py check-key --public-key-file tools/dict-update/public-key.txt [--key-env DICT_SIGNING_KEY]

署名は Ed25519。秘密鍵は 16進 64 文字（32バイト）で、GitHub の secret（DICT_SIGNING_KEY）に置く。
公開鍵は tools/dict-update/public-key.txt に書き、本体に焼き込む（tools/apply_dict_update.py）。
中身の決まり（行の形・品詞番号・費用の範囲）は native/dict_update/data.cc と同じで、作る側でも先に確かめる。
"""
import argparse
import hashlib
import os
import re
import sys
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

MANIFEST_NAME = "manifest.txt"
SIG_NAME = "manifest.txt.sig"
FILES = (("supplement", "supplement.tsv"), ("english", "english-extra.tsv"))
LOWER_WORD = re.compile(r"[a-z0-9']{1,40}\Z")
CASING_KEY = re.compile(r"[a-z0-9']+( [a-z0-9']+)*\Z")


def shown_ok(s):
    return 0 < len(s.encode("utf-8")) <= 64 and clean_utf8(s) and '"' not in s and "\\" not in s


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pos_info(id_def: Path):
    data = id_def.read_bytes()
    return sha256_hex(data), len(data.decode("utf-8").splitlines())


def clean_utf8(s: str) -> bool:
    return bool(s) and all(ord(c) >= 0x20 and ord(c) != 0x7F for c in s)


def validate_supplement(text: str, pos_count: int, max_entries: int = 400000):
    """行の形（読み、左右の品詞番号、費用、表記）の誤りを返す（なければ空）。"""
    errors = []
    count = 0
    for number, line in enumerate(text.splitlines(), 1):
        if not line or line.startswith("#"):
            continue
        f = line.split("\t")
        count += 1
        if len(f) != 5:
            errors.append(f"line {number}: 5 columns expected")
        elif not (f[1].isdigit() and f[2].isdigit() and int(f[1]) < pos_count and int(f[2]) < pos_count):
            errors.append(f"line {number}: bad part-of-speech id")
        elif not (f[3].isdigit() and int(f[3]) <= 32767):
            errors.append(f"line {number}: bad cost")
        elif not clean_utf8(f[0]) or len(f[0].encode()) > 192 or not clean_utf8(f[4]) or len(f[4].encode()) > 256:
            errors.append(f"line {number}: bad reading or surface")
        if len(errors) >= 5:
            break
    if count > max_entries:
        errors.append("too many entries")
    return errors


def validate_english(text: str):
    errors = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line or line.startswith("#"):
            continue
        f = line.split("\t")
        kind = f[0]
        ok = False
        if kind in ("curated", "named", "signal"):
            ok = len(f) == 2 and bool(LOWER_WORD.match(f[1]))
        elif kind == "phrase":
            words = f[1].split(" ") if len(f) == 2 else []
            ok = len(words) >= 2 and all(LOWER_WORD.match(w) for w in words) and len(f[1]) <= 80
        elif kind in ("casing", "casing2"):
            ok = len(f) == 3 and bool(CASING_KEY.match(f[1])) and len(f[1]) <= 80 and shown_ok(f[2])
        if not ok:
            errors.append(f"line {number}: bad row")
        if len(errors) >= 5:
            break
    return errors


def load_private_key(args) -> Ed25519PrivateKey:
    if args.key_file:
        hexkey = Path(args.key_file).read_text().strip()
    else:
        hexkey = os.environ.get(args.key_env or "DICT_SIGNING_KEY", "").strip()
    if not re.fullmatch(r"[0-9a-fA-F]{64}", hexkey):
        raise SystemExit("署名の秘密鍵がありません（16進64文字。GitHub の secret DICT_SIGNING_KEY か --key-file）。"
                         "鍵は `python tools/make_dict_release.py keygen` で作れます。")
    return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(hexkey))


def public_hex(key) -> str:
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()


def build_manifest(version, pos_sha, files, created):
    lines = ["compound-ime-dict-manifest\t1", f"version\t{version}", f"created\t{created}", f"pos_table\t{pos_sha}"]
    for kind, name, data, url in files:
        lines.append(f"file\t{kind}\t{name}\t{len(data)}\t{sha256_hex(data)}\t{url}")
    return "\n".join(lines) + "\n"


def build(args):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    key = load_private_key(args)
    if not re.fullmatch(r"\d{8}", args.version):
        raise SystemExit("--version は年月日の8桁（例 20261101）")
    pos_count = args.pos_count
    files = []
    for kind, default_name in FILES:
        src = getattr(args, kind)
        if not src:
            continue
        data = Path(src).read_bytes()
        text = data.decode("utf-8")
        errors = validate_supplement(text, pos_count) if kind == "supplement" else validate_english(text)
        if errors:
            raise SystemExit(f"{src}: " + "; ".join(errors))
        files.append((kind, default_name, data, f"{args.url_base.rstrip('/')}/{default_name}"))
    if not files:
        raise SystemExit("辞書のファイルがありません")
    for kind, name, data, url in files:
        (out / name).write_bytes(data)
    manifest = build_manifest(args.version, args.pos_table_sha, files, args.created or f"{args.version[:4]}-{args.version[4:6]}-{args.version[6:]}")
    manifest_bytes = manifest.encode("utf-8")
    (out / MANIFEST_NAME).write_bytes(manifest_bytes)
    (out / SIG_NAME).write_text(key.sign(manifest_bytes).hex() + "\n")
    print(f"built {out} version {args.version} public key {public_hex(key)}")


def verify(args):
    d = Path(args.dir)
    manifest = (d / MANIFEST_NAME).read_bytes()
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(args.public_key)).verify(
            bytes.fromhex((d / SIG_NAME).read_text().strip()), manifest)
    except (InvalidSignature, ValueError):
        raise SystemExit("署名が合いません")
    rows = [l.split("\t") for l in manifest.decode("utf-8").splitlines()]
    if rows[0] != ["compound-ime-dict-manifest", "1"]:
        raise SystemExit("目録の形式が違います")
    meta = {r[0]: r[1] for r in rows[1:] if len(r) == 2}
    if args.pos_table_sha and meta.get("pos_table") != args.pos_table_sha:
        raise SystemExit("品詞の表が合いません")
    seen = 0
    for r in rows[1:]:
        if r[0] != "file":
            continue
        _, kind, name, size, sha, url = r
        data = (d / name).read_bytes()
        if len(data) != int(size) or sha256_hex(data) != sha:
            raise SystemExit(f"{name}: 大きさかハッシュが目録と合いません")
        text = data.decode("utf-8")
        errors = validate_supplement(text, args.pos_count) if kind == "supplement" else validate_english(text)
        if errors:
            raise SystemExit(f"{name}: " + "; ".join(errors))
        seen += 1
    if not seen:
        raise SystemExit("目録にファイルがありません")
    print(f"ok version {meta.get('version')} files {seen}")


def check_key(args):
    """秘密鍵（secret）から作った公開鍵が、本体に焼き込む公開鍵（tools/dict-update/public-key.txt）と同じかを確かめる。
    違えば、署名した辞書を本体が受け付けないので、長い作業の前に止める。"""
    rows = [l.strip() for l in Path(args.public_key_file).read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
    baked = rows[0] if rows else "UNSET"
    if baked == "UNSET":
        raise SystemExit("tools/dict-update/public-key.txt がまだ UNSET です。鍵を作って（python tools/make_dict_release.py keygen）、"
                         "公開鍵をここに書いて本体を作り直してください。")
    derived = public_hex(load_private_key(args))
    if derived != baked:
        raise SystemExit(f"secret の鍵から作った公開鍵（{derived[:12]}…）が、本体に焼き込む公開鍵（{baked[:12]}…）と違います。")
    print("ok 鍵が合っています", baked[:12])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("keygen")
    p = sub.add_parser("pos-info")
    p.add_argument("id_def")
    p = sub.add_parser("build")
    p.add_argument("--supplement")
    p.add_argument("--english")
    p.add_argument("--version", required=True)
    p.add_argument("--pos-table-sha", required=True)
    p.add_argument("--pos-count", type=int, default=65536)
    p.add_argument("--url-base", required=True)
    p.add_argument("--created")
    p.add_argument("--out", required=True)
    p.add_argument("--key-env")
    p.add_argument("--key-file")
    p = sub.add_parser("check-key")
    p.add_argument("--public-key-file", required=True)
    p.add_argument("--key-env")
    p.add_argument("--key-file")
    p = sub.add_parser("verify")
    p.add_argument("dir")
    p.add_argument("--public-key", required=True)
    p.add_argument("--pos-table-sha")
    p.add_argument("--pos-count", type=int, default=65536)
    args = ap.parse_args()
    if args.cmd == "keygen":
        key = Ed25519PrivateKey.generate()
        seed = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
        print("秘密鍵（GitHub の secret DICT_SIGNING_KEY に置く。ほかには書かない）:", seed.hex())
        print("公開鍵（tools/dict-update/public-key.txt に書く）:", public_hex(key))
    elif args.cmd == "pos-info":
        sha, count = pos_info(Path(args.id_def))
        print(sha, count)
    elif args.cmd == "build":
        build(args)
    elif args.cmd == "check-key":
        check_key(args)
    else:
        verify(args)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
