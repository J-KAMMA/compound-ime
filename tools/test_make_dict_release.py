"""tools/make_dict_release.py（配布物を作る・確かめる道具）の確かめ。 python tools/test_make_dict_release.py"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_dict_release as mdr  # noqa: E402

TOOL = Path(__file__).resolve().parent / "make_dict_release.py"
failures = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        failures.append(what)


def run(*args, env=None):
    e = dict(os.environ)
    e.update(env or {})
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True, env=e)


def main():
    keygen = run("keygen")
    lines = keygen.stdout.splitlines()
    secret, public = lines[0].split(": ")[1], lines[1].split(": ")[1]
    check(len(secret) == 64 and len(public) == 64, "keygen: 秘密鍵と公開鍵が16進64文字")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "id.def").write_text("0 BOS/EOS,*,*,*,*,*,*\n1 名詞,一般,*,*,*,*,*\n", encoding="utf-8")
        sha, count = run("pos-info", str(tmp / "id.def")).stdout.split()
        check(count == "2" and len(sha) == 64, "pos-info: 行数と SHA-256")
        (tmp / "s.tsv").write_text("# 注釈\nぬぬ\t1\t1\t3000\tNunu\n", encoding="utf-8")
        (tmp / "e.tsv").write_text("named\tfoo\ncasing\tfoo\tFoo\nphrase\tsee you\n", encoding="utf-8")
        base = ["build", "--supplement", str(tmp / "s.tsv"), "--english", str(tmp / "e.tsv"), "--version", "20261101",
                "--pos-table-sha", sha, "--pos-count", count, "--url-base", "https://example.test/dict-20261101/", "--out", str(tmp / "r")]
        r = run(*base, env={"DICT_SIGNING_KEY": secret})
        check(r.returncode == 0 and public in r.stdout, "build: 署名つきの配布物ができる")
        manifest = (tmp / "r/manifest.txt").read_text(encoding="utf-8")
        check(manifest.startswith("compound-ime-dict-manifest\t1\nversion\t20261101\n"), "目録の形（先頭の行と版）")
        check("https://example.test/dict-20261101/supplement.tsv" in manifest, "ファイルの URL は url-base の下")
        r = run("verify", str(tmp / "r"), "--public-key", public, "--pos-table-sha", sha, "--pos-count", count)
        check(r.returncode == 0 and "ok version 20261101" in r.stdout, "verify: 正しい配布物は通る")
        r = run("verify", str(tmp / "r"), "--public-key", "00" * 32, "--pos-table-sha", sha)
        check(r.returncode != 0, "verify: 別の公開鍵では通らない")
        r = run("verify", str(tmp / "r"), "--public-key", public, "--pos-table-sha", "1" * 64)
        check(r.returncode != 0, "verify: 品詞の表が違えば通らない")
        (tmp / "r/supplement.tsv").write_text("ぬぬ\t1\t1\t3000\tChanged\n", encoding="utf-8")
        r = run("verify", str(tmp / "r"), "--public-key", public)
        check(r.returncode != 0, "verify: ファイルを書き換えると通らない")
        # 作る前の確かめ
        (tmp / "bad.tsv").write_text("ぬぬ\t99\t1\t3000\tNunu\n", encoding="utf-8")
        bad = base.copy()
        bad[2] = str(tmp / "bad.tsv")
        r = run(*bad, env={"DICT_SIGNING_KEY": secret})
        check(r.returncode != 0 and "bad part-of-speech" in (r.stderr + r.stdout), "build: 品詞番号が範囲の外の辞書は作らない")
        r = run(*base, env={"DICT_SIGNING_KEY": ""})
        check(r.returncode != 0 and "DICT_SIGNING_KEY" in (r.stderr + r.stdout), "build: 秘密鍵がなければ、作り方を示して止まる")
        (tmp / "pub.txt").write_text("# c\n" + public + "\n", encoding="utf-8")
        r = run("check-key", "--public-key-file", str(tmp / "pub.txt"), env={"DICT_SIGNING_KEY": secret})
        check(r.returncode == 0, "check-key: secret の鍵と焼き込む公開鍵が合えば通る")
        (tmp / "unset.txt").write_text("UNSET\n", encoding="utf-8")
        r = run("check-key", "--public-key-file", str(tmp / "unset.txt"), env={"DICT_SIGNING_KEY": secret})
        check(r.returncode != 0 and "UNSET" in (r.stderr + r.stdout), "check-key: 公開鍵が UNSET なら止まる")
        (tmp / "other.txt").write_text("00" * 32 + "\n", encoding="utf-8")
        r = run("check-key", "--public-key-file", str(tmp / "other.txt"), env={"DICT_SIGNING_KEY": secret})
        check(r.returncode != 0, "check-key: 公開鍵が違えば止まる")
    check(mdr.validate_english("named\tFoo\n") != [] and mdr.validate_english("phrase\tone\n") != [], "英語の一覧: 大文字や1語の言い回しは受け付けない")
    check(mdr.validate_supplement("あ\t1\t1\t40000\tX\n", 10) != [], "追加の辞書: 費用の上限")
    print("failed" if failures else "all ok", len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
