"""Build the English lexicon for Japanese/English romaji detection.

Downloads the pinned SCOWL release (permissive license, notice kept beside the
output), verifies its SHA-256, and writes one lowercase word per line:
SCOWL english/american words up to --level plus tools/data/jaen-extra-words.txt
and tools/data/jaen-brand-words.txt, plus tools/data/jaen-domain-words.txt (from
tools/build_domain_words.py; only its words of 4 letters or fewer are curated).
signal-words.txt holds the rarer words and
names up to --signal-level (english/american words, upper-case words and proper
names, lowercased) that are not in the main list; the detector takes them only
when what was typed is no plain Japanese romaji (london: lo is ぉ).

  python tools/build_english_lexicon.py --out <dir> [--level 35] [--signal-level 70]
"""
import argparse
import hashlib
import io
import re
import tarfile
import urllib.request
from pathlib import Path

URL = "https://downloads.sourceforge.net/project/wordlist/SCOWL/2020.12.07/scowl-2020.12.07.tar.gz"
SHA256 = "5587667caa20c4891390c2d42dbb4d5c4c3f41bee77af1457ece3ba23fb859cc"
LEVELS = (10, 20, 35, 40, 50, 55, 60, 70, 80, 95)
WORD = re.compile(r"[a-z][a-z']{0,31}")
# 日本語のローマ字として切れ目なく読める綴り（子音＋母音、母音、ん、っ の重ね）。
PLAIN_ROMAJI = re.compile(r"(?:(?:ky|gy|sh|ch|ts|ny|hy|by|py|my|ry|dy|ty|j|f|[kgsztdnhbpmyrwv])?[aiueo]"
                          r"|n(?![aiueoy])|([kgsztdhbpmrjfc])(?=\1))+")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--level", type=int, choices=LEVELS, default=35)
    parser.add_argument("--signal-level", type=int, choices=LEVELS, default=70)
    parser.add_argument("--archive", type=Path, help="already downloaded archive")
    args = parser.parse_args()

    data = args.archive.read_bytes() if args.archive else urllib.request.urlopen(URL, timeout=60).read()
    if hashlib.sha256(data).hexdigest() != SHA256:
        raise SystemExit("SCOWL archive SHA-256 mismatch")
    words = set()
    common = set()  # level 20 or less: the common words (hero, safe, idea; not omen, redo)
    level_of = {}
    signal = set()
    cased = {}  # 大文字を含む名前（Madrid、NASA）: 小文字の形 -> 書き方
    plain = set()  # 段階 --signal-level までに小文字で載る語（serrano は唐辛子でもある）
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        root = "scowl-2020.12.07/"
        copyright_text = tar.extractfile(root + "Copyright").read()
        for member in tar.getmembers():
            name = member.name.removeprefix(root + "final/")
            kind, _, level = name.rpartition(".")
            if kind in ("english-words", "american-words") and level.isdigit() and int(level) <= args.level:
                text = tar.extractfile(member).read().decode("iso-8859-1")
                found = [w for w in text.split() if WORD.fullmatch(w)]
                words.update(found)
                for w in found:
                    level_of[w] = min(level_of.get(w, 99), int(level))
                if int(level) <= 20:
                    common.update(found)
            if kind.startswith(("english-", "american-")) and kind.endswith("-words") and level.isdigit() and int(level) <= args.signal_level:
                plain.update(w for w in tar.extractfile(member).read().decode("iso-8859-1").split() if WORD.fullmatch(w))
            if (kind.startswith(("english-", "american-")) and kind.endswith(("-words", "-upper", "-proper-names"))
                    and level.isdigit() and int(level) <= args.signal_level):
                text = tar.extractfile(member).read().decode("iso-8859-1")
                for w in text.split():
                    if len(w) >= 3 and WORD.fullmatch(w.lower()):
                        signal.add(w.lower())
                        if w != w.lower():
                            cased.setdefault(w.lower(), set()).add(w)
    curated = set()
    for name in ("jaen-extra-words.txt", "jaen-brand-words.txt"):
        extra = Path(__file__).with_name("data") / name
        lines = (line.strip() for line in extra.read_text(encoding="utf-8").splitlines())
        curated |= {w for w in lines if WORD.fullmatch(w)}
    words |= curated
    # 分野の文書に出る英字の語（tools/build_domain_words.py）。英単語の一覧に足す。4文字以下の語だけ
    # 厳選の語（api、dao）として足し、5文字以上は普通の語にする（かなが日本語の読みになる語を
    # 厳選にすると、日本語の文を英語にしてしまう）。
    # ローマ字としてそのまま読める語（todo とど、dai だい、uri うり、gen げん）は厳選にしない。文書に出ただけの語で、
    # 日本語のつもりで打った かな を英語にしてしまう（2026-10-30、todo を日本語で打つと英字になった）。
    domain_path = Path(__file__).with_name("data") / "jaen-domain-words.txt"
    if domain_path.exists():
        for line in domain_path.read_text(encoding="utf-8").splitlines():
            word = line.strip()
            if WORD.fullmatch(word):
                words.add(word)
                if len(word) <= 4 and not PLAIN_ROMAJI.fullmatch(word):
                    curated.add(word)

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "english-lexicon.txt").write_text("".join(w + "\n" for w in sorted(words)), encoding="ascii")
    (args.out / "curated-words.txt").write_text("".join(w + "\n" for w in sorted(curated)), encoding="ascii")
    signal -= words
    (args.out / "signal-words.txt").write_text("".join(w + "\n" for w in sorted(signal)), encoding="ascii")
    # 大文字を含む書き方が1つだけで、小文字の形がどこにも語として載らない5文字以上の名前（madrid -> Madrid）。
    # 短い名前（kay、stu、nam）は打ち間違いの日本語を英語にしてしまうので入れない。
    names = sorted(f"{w}\t{next(iter(forms))}\n" for w, forms in cased.items()
                   if len(forms) == 1 and w in signal and w not in plain and len(w) >= 5)
    (args.out / "cased-names.tsv").write_text("".join(names), encoding="ascii")
    (args.out / "common-words.txt").write_text("".join(w + "\n" for w in sorted(common)), encoding="ascii")
    (args.out / "SCOWL-Copyright.txt").write_bytes(copyright_text)
    probe = "hero safe idea radio menu area zone dune mute share kiwi bike issue omen redo name home note token kite base".split()
    print("levels", " ".join(f"{w}:{level_of.get(w, '-')}" for w in probe))
    print(f"words\t{len(words)}\tlevel\t{args.level}\tsignal\t{len(signal)}\tlevel\t{args.signal_level}")


if __name__ == "__main__":
    main()
