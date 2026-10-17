"""マック版・リナックス版の組み立てで、中の番号（3.34.6239.N）を version.bzl に書く。

  python tools/apply_version_number.py <mozc/src> 3.34.6239.N
ウィンドウズ版は windows.yml が同じ事を直接している。ここは同じ考えをマック・リナックス用にしたもの。
設定の画面や「このソフトについて」に出す版の名前（コンパウンドIME 1.N）は、この N から作る。

- version.bzl の BUILD_OSS と REVISION を入力の番号にする。
- 開発版の枝は REVISION が 100 に決まってしまうので、version.bzl の値を使うようにする。
- 土台は REVISION の最後の1桁を、マックは 1、リナックスは 2 に置き換えるので、そのまま使うようにする。
"""
import re
import sys
from pathlib import Path

src = Path(sys.argv[1])
version = sys.argv[2]
m = re.fullmatch(r"3\.34\.6239\.([0-9]+)", version)
assert m, f"版の番号は 3.34.6239.<番号> の形: {version}"
build, revision = "6239", m.group(1)


def edit(path, old, new, count=1):
    p = src / path
    t = p.read_text(encoding="utf-8")
    assert t.count(old) == count, (path, old[:70], t.count(old))
    p.write_text(t.replace(old, new), encoding="utf-8", newline="")


p = src / "version.bzl"
t = p.read_text(encoding="utf-8")
t, n1 = re.subn(r"(?m)^BUILD_OSS = .*$", f"BUILD_OSS = {build}", t)
t, n2 = re.subn(r"(?m)^REVISION = .*$", f"REVISION = {revision}", t)
assert n1 == 1 and n2 == 1, (n1, n2)
p.write_text(t, encoding="utf-8", newline="")

V = "build_tools/mozc_version.py"
edit(V, "    revision = '100'\n", "    revision = template_dict.get('REVISION', None)\n")
edit(V, "    'Mac': '1',\n", "    'Mac': '',\n")
edit(V, "    'Linux': '2',\n", "    'Linux': '',\n")
print("version number applied:", version)
