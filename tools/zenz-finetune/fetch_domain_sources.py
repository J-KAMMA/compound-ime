#!/usr/bin/env python3
"""分野の文書（domain_sources.json）を、版（commit）を固定して取り出す。

  python fetch_domain_sources.py --out src [--config domain_sources.json] [--only mdn ...]

出典ごとに <out>/<名前>/ へ、git の sparse checkout（必要な場所だけ）で 1 つの版を取り出す。
取り出した版が設定の commit と同じことを確かめる。リポジトリには材料を入れない
（GitHub Actions の中で使う: .github/workflows/domain-data.yml）。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def run(*cmd, cwd=None) -> str:
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def fetch(source: dict, out: Path) -> None:
    target = out / source["name"]
    target.mkdir(parents=True, exist_ok=True)
    run("git", "init", "-q", cwd=target)
    run("git", "remote", "add", "origin", source["repo"] + ".git", cwd=target)
    if source["paths"]:
        run("git", "sparse-checkout", "set", "--no-cone", *[f"/{p.strip('/')}/" for p in source["paths"]], cwd=target)
    run("git", "fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", source["commit"], cwd=target)
    run("git", "checkout", "-q", "FETCH_HEAD", cwd=target)
    head = run("git", "rev-parse", "HEAD", cwd=target)
    if head != source["commit"]:
        raise SystemExit(f"{source['name']}: 取り出した版 {head} が設定の {source['commit']} と違う")
    root = target / source.get("root", "")
    count = sum(1 for p in root.glob(source["glob"]) if p.is_file())
    print(f"{source['name']}: {source['repo']} {head[:12]}、{source['glob']} が {count} ファイル", flush=True)
    if count == 0:
        raise SystemExit(f"{source['name']}: 文書が 1 つも見つからない（paths と root を確かめる）")


def main(argv=None):
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--config", default=str(here / "domain_sources.json"))
    ap.add_argument("--only", nargs="*", default=[])
    args = ap.parse_args(argv)
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    for source in config["sources"]:
        if source.get("kind") == "external":
            continue  # git の文書ではない出典（Tatoeba など）
        if not args.only or source["name"] in args.only:
            fetch(source, Path(args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
