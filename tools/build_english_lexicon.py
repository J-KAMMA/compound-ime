"""Build the English lexicon for Japanese/English romaji detection.

Downloads the pinned SCOWL release (permissive license, notice kept beside the
output), verifies its SHA-256, and writes one lowercase word per line:
SCOWL english/american words up to --level plus tools/data/jaen-extra-words.txt
and tools/data/jaen-brand-words.txt. signal-words.txt holds the rarer words and
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
    signal = set()
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        root = "scowl-2020.12.07/"
        copyright_text = tar.extractfile(root + "Copyright").read()
        for member in tar.getmembers():
            name = member.name.removeprefix(root + "final/")
            kind, _, level = name.rpartition(".")
            if kind in ("english-words", "american-words") and level.isdigit() and int(level) <= args.level:
                text = tar.extractfile(member).read().decode("iso-8859-1")
                words.update(w for w in text.split() if WORD.fullmatch(w))
            if (kind.startswith(("english-", "american-")) and kind.endswith(("-words", "-upper", "-proper-names"))
                    and level.isdigit() and int(level) <= args.signal_level):
                text = tar.extractfile(member).read().decode("iso-8859-1")
                signal.update(w.lower() for w in text.split() if len(w) >= 3 and WORD.fullmatch(w.lower()))
    curated = set()
    for name in ("jaen-extra-words.txt", "jaen-brand-words.txt"):
        extra = Path(__file__).with_name("data") / name
        lines = (line.strip() for line in extra.read_text(encoding="utf-8").splitlines())
        curated |= {w for w in lines if WORD.fullmatch(w)}
    words |= curated

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "english-lexicon.txt").write_text("".join(w + "\n" for w in sorted(words)), encoding="ascii")
    (args.out / "curated-words.txt").write_text("".join(w + "\n" for w in sorted(curated)), encoding="ascii")
    signal -= words
    (args.out / "signal-words.txt").write_text("".join(w + "\n" for w in sorted(signal)), encoding="ascii")
    (args.out / "SCOWL-Copyright.txt").write_bytes(copyright_text)
    print(f"words\t{len(words)}\tlevel\t{args.level}\tsignal\t{len(signal)}\tlevel\t{args.signal_level}")


if __name__ == "__main__":
    main()
