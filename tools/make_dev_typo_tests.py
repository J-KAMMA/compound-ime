"""調整用の打ち間違いの表（tests/conversion/dev-typo.json）を ja400.json の文から作る。

  python3 tools/make_dev_typo_tests.py

打ち間違いの直しの境目や重みを決めるときは、この表で比べる。確かめ用の表（holdout）は最後の確認だけに使う。
打ち間違いの入れ方は tools/make_holdout_tests.py と同じ（5種類を順に、文ごとに決まった乱数で）。
"""
import json
import random
from pathlib import Path

from make_holdout_tests import add_typo

TESTS = Path(__file__).resolve().parent.parent / "tests/conversion"


def main():
    items = json.loads((TESTS / "ja400.json").read_text(encoding="utf-8"))["items"]
    kinds = ["doubled_vowel", "dropped", "swapped", "neighbor", "extra"]
    typos = []
    for item in items:
        typed = item["romaji"]
        if not typed.isascii() or not typed.isalpha() or len(typed) < 8:
            continue
        kind = kinds[len(typos) % len(kinds)]
        rng = random.Random(f"{item['id']}-{kind}")
        try:
            wrong = add_typo(typed, kind, rng)
        except IndexError:
            continue
        if wrong != typed:
            typos.append({"id": f"dt-{item['id']}", "category": kind, "romaji": wrong, "correct_romaji": typed,
                          "intended": item["intended"], "alternatives": item.get("alternatives", [])})
    (TESTS / "dev-typo.json").write_text(json.dumps({
        "description": f"調整用の打ち間違いの表 {len(typos)} 件（ja400.json の文に打ち間違いを1つ。"
                       "tools/make_dev_typo_tests.py）。種類: " + ", ".join(kinds),
        "items": typos}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"dev-typo: {len(typos)} items")


if __name__ == "__main__":
    main()
