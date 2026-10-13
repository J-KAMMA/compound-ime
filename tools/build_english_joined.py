"""Builds tools/data/english-joined.txt: English words that are two shorter lexicon words joined.

  python tools/build_english_joined.py <lexicon dir, level 35> <lexicon dir, level 60> > tools/data/english-joined.txt

Both directories are outputs of tools/build_english_lexicon.py (--level 35, --level 60).
A word of the larger list that is not in the smaller one and splits into two
words of the smaller one (each of 2+ letters) is listed: download, backup,
smartphone, online. Two such typed words then stay one word ("download"),
while other adjacent English words are shown with a space ("weekly report").
A few common computing words missing from SCOWL are added by hand.
"""
import sys
from pathlib import Path

EXTRA = ["backend", "frontend", "login", "logout", "signin", "signup", "username", "website",
         "webpage", "smartwatch", "touchpad", "timestamp", "checkbox", "dropdown", "popup",
         "codebase", "dataset", "database", "filename", "workflow", "keyword",
         "powerpoint", "github", "gitlab", "facebook", "youtube", "iphone", "playstation", "onedrive",
         "dropbox", "wordpress", "javascript", "typescript"]


def words(path):
    return {w.strip().lower() for w in (Path(path) / "english-lexicon.txt").read_text(encoding="ascii").split()}


base, big = words(sys.argv[1]), words(sys.argv[2])
joined = set(EXTRA)
for w in big - base:
    if w.isalpha() and any(w[:i] in base and w[i:] in base for i in range(2, len(w) - 1)):
        joined.add(w)
sys.stdout.write("".join(w + "\n" for w in sorted(joined)))
