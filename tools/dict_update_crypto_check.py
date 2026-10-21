"""本体の暗号の部品（native/dict_update/crypto.cc の Ed25519 の確かめと SHA-256）を、python の cryptography・hashlib と照らし合わせる。

  python tools/dict_update_crypto_check.py <crypto_check の実行ファイル>

正しい署名は受け付け、文・署名・公開鍵のどれかを変えたもの、署名の後ろ半分に群の位数を足した（作り変えた）ものは受け付けないことを、
乱数で作った 300 組ほどで確かめる。RFC 8032 の試験 1 も含む。
"""
import hashlib
import os
import random
import subprocess
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

L = 2**252 + 27742317777372353535851937790883648493


def raw_pub(key):
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def main():
    lines, expect = [], []
    sk = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"))
    assert raw_pub(sk).hex() == "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
    lines.append(f"v {sk.sign(b'').hex()} {raw_pub(sk).hex()} ")
    expect.append("1")
    rnd = random.Random(20261021)
    for _ in range(60):
        sk = Ed25519PrivateKey.generate()
        pub = raw_pub(sk)
        msg = os.urandom(rnd.choice([0, 1, 5, 64, 200, 1000, 5000]))
        sig = sk.sign(msg)
        lines.append(f"v {sig.hex()} {pub.hex()} {msg.hex()}")
        expect.append("1")
        changed = bytearray(msg or b"x")
        changed[0] ^= 1
        lines.append(f"v {sig.hex()} {pub.hex()} {bytes(changed).hex()}")
        expect.append("0")
        bad = bytearray(sig)
        bad[rnd.randrange(64)] ^= 1 << rnd.randrange(8)
        lines.append(f"v {bytes(bad).hex()} {pub.hex()} {msg.hex()}")
        expect.append("0")
        lines.append(f"v {sig.hex()} {raw_pub(Ed25519PrivateKey.generate()).hex()} {msg.hex()}")
        expect.append("0")
        s_plus_l = int.from_bytes(sig[32:], "little") + L
        if s_plus_l < 2**256:
            lines.append(f"v {(sig[:32] + s_plus_l.to_bytes(32, 'little')).hex()} {pub.hex()} {msg.hex()}")
            expect.append("0")
    for data in (b"", b"abc", b"a" * 55, b"a" * 56, b"a" * 64, os.urandom(1000), os.urandom(100000)):
        lines.append("sha " + data.hex())
        expect.append(hashlib.sha256(data).hexdigest())
    out = subprocess.run([sys.argv[1]], input="\n".join(lines) + "\n", capture_output=True, text=True).stdout.split("\n")
    bad = [i for i, e in enumerate(expect) if out[i] != e]
    print(f"cases {len(expect)}, mismatches {len(bad)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
