"""数字を半角にする設定（利用者の設定: 数字は半角）の config1.db を作る。

  python tools/make_decimal_config.py <出力ファイル>

Mozc の設定（Config）を直接組み立てる。中身は character_form_rules の1つだけ:
グループ "0"（数字）を、入力中の表示も確定後も半角（HALF_WIDTH）。ほかの規則は Mozc の既定のまま
（「.,」は入力中の表示が全角）。組 s（tools/run_tests.sh）が、プロファイルに置いて使う
（tools/batch_convert.sh の MYIME_TEST_CONFIG_DB）。
"""
import sys


def varint(n):
    out = b""
    while True:
        low = n & 0x7F
        n >>= 7
        if n:
            out += bytes([low | 0x80])
        else:
            return out + bytes([low])


def rule(group, preedit, conversion):
    g = group.encode()
    message = b"\x0a" + varint(len(g)) + g + b"\x10" + varint(preedit) + b"\x18" + varint(conversion)
    return varint(54 << 3 | 2) + varint(len(message)) + message  # Config.character_form_rules = 54


HALF_WIDTH = 0
open(sys.argv[1], "wb").write(rule("0", HALF_WIDTH, HALF_WIDTH))
