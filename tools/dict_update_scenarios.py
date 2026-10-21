"""辞書の更新の端から端までの試験。本物の取得の部品を通し、手元の簡単な配布ページ（127.0.0.1）から取る。

  python tools/dict_update_scenarios.py tool <dict_update_tool>                          # Mozc なし（native/dict_update）
  python tools/dict_update_scenarios.py session <session_handler_main> [--env K=V ...]   # 本体の変換エンジン（組 u）

確かめること:
  1. 取った辞書を読み直して候補が変わる（取る前は出ない → 取る → 同じ処理の中ですぐ出る → 再起動しても出る）
  2. 新しい版が出たら入れ替わり、古い目録（巻き戻し）は無視する
  3. 悪い配布物（署名違い、ハッシュ違い、読めない行、品詞の表の違い、許していない URL、大きさの超過）は入れない（前の辞書のまま）
  4. 読み直しに失敗したら前の辞書に戻る（MYIME_DICT_UPDATE_FAIL_APPLY。試験のときだけ効く）
  5. 止める設定（MYIME_DICT_UPDATE=0）では、配布ページに1回も取りに行かない。入っている辞書は使い続ける
  6. 配布ページにつながらないときは、辞書は変わらない
署名は試験用の鍵（この中で作る）。本体は、試験のときだけ MYIME_DICT_UPDATE_PUBKEY でその公開鍵を受け取る。
"""
import argparse
import functools
import http.server
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dict_update_fixtures as fx  # noqa: E402

# 読みは、Mozc の辞書にその語も分け方もない並び（辞書の語に割れずに、追加の辞書の1語が一番安い道になる）
R1, R1_ROMAJI = "ぬぬぬぬぬぬ", "nu" * 6
R2, R2_ROMAJI = "ねねねねねねねね", "ne" * 8
READINGS = [(R1, R1_ROMAJI), (R2, R2_ROMAJI)]


class Site:
    """手元の配布ページ。アクセスの数を数える。"""

    def __init__(self, root: Path):
        self.root = root
        (root / "rel").mkdir(parents=True, exist_ok=True)
        self.requests = []
        site = self

        class Handler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, fmt, *args):
                site.requests.append(self.path)

        handler = functools.partial(Handler, directory=str(root))
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def base(self):
        return f"http://127.0.0.1:{self.port}/rel"

    def publish(self, release_dir: Path):
        rel = self.root / "rel"
        shutil.rmtree(rel, ignore_errors=True)
        shutil.copytree(release_dir, rel)

    def close(self):
        self.server.shutdown()


class Runner:
    def __init__(self, mode, binary, extra_env):
        self.mode, self.binary = mode, binary
        self.extra_env = dict(kv.split("=", 1) for kv in extra_env)

    def run(self, state_dir: Path, base: str, pubkey: str, *, update: bool, env=None, profile: Path = None):
        e = dict(os.environ)
        e.update(self.extra_env)
        e.update({"MYIME_HERMETIC_TEST": "1", "MYIME_DICT_UPDATE_DIR": str(state_dir), "MYIME_DICT_UPDATE_BASE": base,
                  "MYIME_DICT_UPDATE_PUBKEY": pubkey})
        e.update(env or {})
        if self.mode == "tool":
            cmd = [self.binary, "update" if update else "load"] + [r for r, _ in READINGS]
            out = subprocess.run(cmd, env=e, capture_output=True, text=True, timeout=300).stdout
        else:
            lines = ["DICT_UPDATE"] if update else []
            for _, romaji in READINGS:
                lines += ["SEND_KEY\tON", f"SEND_KEYS\t{romaji}", "SEND_KEY\tSpace", "SHOW_OUTPUT", "SEND_KEY\tEscape", "SEND_KEY\tEscape"]
            with tempfile.TemporaryDirectory() as tmp:
                script = Path(tmp) / "input.tsv"
                script.write_text("\n".join(lines) + "\n", encoding="utf-8")
                prof = profile or Path(tmp) / "profile"
                prof.mkdir(exist_ok=True)
                cmd = [self.binary, "--input", str(script), "--profile", str(prof), "--dictionary", "oss"]
                out = subprocess.run(cmd, env=e, capture_output=True, text=True, timeout=600, stdin=subprocess.DEVNULL).stdout
        return self.parse(out)

    def parse(self, out):
        status = None
        m = re.search(r"DICT_UPDATE: status=(\S+) version=(\d+)(?: detail=(.*))?", out)
        if m:
            status = {"status": m.group(1), "version": int(m.group(2)), "detail": m.group(3) or ""}
        values = {}
        if self.mode == "tool":
            for r, _ in READINGS:
                m = re.search(rf"^candidates {re.escape(r)}:(.*)$", out, re.M)
                values[r] = [v for v in (m.group(1).split("\t") if m else []) if v]
        else:
            # SHOW_OUTPUT は読みごとに1回。value: "…" の並びを、読みの順に分ける
            all_values = re.findall(r'value: "((?:[^"\\]|\\.)*)"', out)
            for r, _ in READINGS:
                values[r] = all_values  # 本体の出力は読みごとの区切りが読みにくいので、全部を持つ（含むかどうかで確かめる）
        return status, values

    def info(self):
        if self.mode == "tool":
            out = subprocess.run([self.binary, "info"], capture_output=True, text=True).stdout
        else:
            with tempfile.TemporaryDirectory() as tmp:
                script = Path(tmp) / "input.tsv"
                script.write_text("DICT_UPDATE_INFO\n", encoding="utf-8")
                e = dict(os.environ)
                e.update(self.extra_env)
                e["MYIME_HERMETIC_TEST"] = "1"
                out = subprocess.run([self.binary, "--input", str(script), "--profile", tmp, "--dictionary", "oss"],
                                     env=e, capture_output=True, text=True, stdin=subprocess.DEVNULL).stdout
        m = re.search(r"DICT_UPDATE_INFO: pos_table_sha256=([0-9a-f]{64}) pos_count=(\d+) noun_id=(\d+)", out)
        if not m:
            raise SystemExit("DICT_UPDATE_INFO が読めません:\n" + out[-500:])
        return m.group(1), int(m.group(2)), int(m.group(3))


failures = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        failures.append(what)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["tool", "session"])
    ap.add_argument("binary")
    ap.add_argument("--env", action="append", default=[])
    args = ap.parse_args()
    runner = Runner(args.mode, args.binary, args.env)
    pos_sha, pos_count, noun = runner.info()
    key, other = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    pub = fx.pub_hex(key)

    def supplement(n_extra=0, bad=False):
        text = f"{R1}\t{noun}\t{noun}\t2500\tZzyzxProbe\n"
        if n_extra:
            text += f"{R1}\t{noun}\t{noun}\t2600\tZzyzxProbe Two\n{R2}\t{noun}\t{noun}\t2500\tPopopo Item\n"
        if bad:
            text += f"ぱぱぱ\t{pos_count + 5}\t{noun}\t2500\tOutOfRange\n"
        return text

    english = "named\tzzyzxtool\ncasing\tzzyzxtool\tZzyzxTool\n"

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        site = Site(tmp / "site")
        releases = tmp / "releases"

        def make(name, version, text, signer=key, sha=pos_sha, tamper=None, url_override=None, size_override=None):
            fx.make(releases, name, version, text, english, signer, sha, url_base=site.base, tamper=tamper,
                    url_override=url_override, size_override=size_override)
            return releases / name

        def serve(name):
            site.publish(releases / name)

        def run(state, *, update, base=None, env=None):
            return runner.run(state, base or site.base, pub, update=update, env=env, profile=tmp / "profile")

        make("v1", "20261101", supplement(), key)
        make("v2", "20261201", supplement(1), key)
        make("older", "20260901", supplement(), key)
        make("bad-sig", "20261210", supplement(1), other)  # 別の鍵の署名
        make("bad-hash", "20261215", supplement(1), tamper="supplement.tsv")
        make("bad-content", "20261220", supplement(1, bad=True))
        make("wrong-pos", "20261225", supplement(1), sha="0" * 64)
        make("bad-url", "20261226", supplement(1), url_override="https://evil.example/supplement.tsv")
        make("huge", "20261227", supplement(1), size_override=999999999)
        make("v3", "20270101", supplement(1) + f"{R1}\t{noun}\t{noun}\t2700\tZzyzxProbe Three\n")

        # 1. 取る前は出ない → 取るとすぐ出る → 再起動しても出る
        state = tmp / "state"
        serve("v1")
        status, values = run(state, update=False)
        check("ZzyzxProbe" not in values[R1], "取る前: ZzyzxProbe は候補にない")
        check(not site.requests, "更新を呼ばない起動では、配布ページに取りに行かない")
        status, values = run(state, update=True)
        check(status and status["status"] == "installed" and status["version"] == 20261101, f"取る: installed 20261101 ({status})")
        check("ZzyzxProbe" in values[R1], "取った辞書を読み直して、同じ処理の中ですぐ候補に出る")
        check(len(site.requests) == 4, f"取るのは目録・署名・辞書・英語の一覧の4つ（{len(site.requests)}）")
        status, values = run(state, update=False)
        check("ZzyzxProbe" in values[R1], "再起動しても、入れた辞書を読んで候補に出る")
        # 2. 同じ版では何も入れない。新しい版が入る。古い目録は無視する
        site.requests.clear()
        status, _ = run(state, update=True)
        check(status and status["status"] == "up-to-date", f"同じ版: up-to-date ({status})")
        check(len(site.requests) == 2, "同じ版のときは、目録と署名だけを見る")
        serve("v2")
        status, values = run(state, update=True)
        check(status and status["status"] == "installed" and status["version"] == 20261201, f"新しい版: installed 20261201 ({status})")
        check("Popopo Item" in values[R2] and "ZzyzxProbe Two" in values[R1], "新しい辞書の語が候補に出る")
        serve("older")
        status, values = run(state, update=True)
        check(status and status["status"] == "up-to-date", f"古い目録（巻き戻し）は無視する ({status})")
        check("Popopo Item" in values[R2], "巻き戻しのあとも新しい辞書のまま")
        # 3. 悪い配布物は入れない
        for name, expect in [("bad-sig", "verify-failed"), ("bad-hash", "verify-failed"), ("bad-content", "rejected"),
                             ("wrong-pos", "rejected"), ("bad-url", "rejected"), ("huge", "rejected")]:
            serve(name)
            status, values = run(state, update=True)
            check(status and status["status"] == expect, f"悪い配布物 {name}: {expect} ({status})")
            check("Popopo Item" in values[R2], f"{name} のあとも、前の辞書（20261201）のまま")
        # 4. 読み直しに失敗したら前に戻る
        serve("v3")
        status, values = run(state, update=True, env={"MYIME_DICT_UPDATE_FAIL_APPLY": "1"})
        check(status and status["status"] == "reload-failed", f"読み直しの失敗: reload-failed ({status})")
        status, values = run(state, update=False)
        check("Popopo Item" in values[R2] and "ZzyzxProbe Three" not in values[R1], "読み直しに失敗した版は入らず、前の辞書で起動する")
        # 4b. 入れた版が確かめられる前に続けて落ちたら、前の版に戻る（確かめた印は、30秒動いたときに付く）
        crash = tmp / "state-crash"
        no_confirm = {"MYIME_DICT_UPDATE_NO_CONFIRM": "1"}
        serve("v1")
        run(crash, update=True, env=no_confirm)
        serve("v2")
        status, _ = run(crash, update=True, env=no_confirm)
        check(status and status["status"] == "installed" and status["version"] == 20261201, f"確かめる前の版を入れる ({status})")
        _, values = run(crash, update=False, env=no_confirm)
        check("Popopo Item" in values[R2], "確かめる前の1回目の起動では、新しい辞書を使う")
        _, values = run(crash, update=False, env=no_confirm)
        check("Popopo Item" not in values[R2] and "ZzyzxProbe" in values[R1], "確かめる前に2回続けて起動したら、前の辞書（20261101）に戻る")
        # 5. 止める設定では、取りに行かない
        stopped = tmp / "state-stopped"
        serve("v1")
        site.requests.clear()
        status, values = run(stopped, update=True, env={"MYIME_DICT_UPDATE": "0"})
        check(status and status["status"] == "disabled", f"止める設定: disabled ({status})")
        check(not site.requests, f"止める設定では、配布ページに1回も取りに行かない（{len(site.requests)} 回）")
        check("ZzyzxProbe" not in values[R1], "止める設定では、辞書も入らない")
        # 止めた状態でも、すでに入っている辞書は使い続ける
        site.requests.clear()
        status, values = run(state, update=True, env={"MYIME_DICT_UPDATE": "0"})
        check(status and status["status"] == "disabled" and not site.requests, "入っている辞書がある状態で止めても、取りに行かない")
        check("Popopo Item" in values[R2], "止めても、入っている辞書は使い続ける")
        # 6. つながらない
        site.close()
        status, values = run(state, update=True)
        check(status and status["status"] == "fetch-failed", f"配布ページにつながらない: fetch-failed ({status})")
        check("Popopo Item" in values[R2], "つながらなくても、入っている辞書は使い続ける")
    print("failed" if failures else "all ok", len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
