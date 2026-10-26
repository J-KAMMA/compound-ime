"""Variants of a kana reading that Japanese readers type for the same word.

  import reading_variants

  reading_variants.variants("でんそ")  # でんそ, でんそー, でんそう
  reading_variants.variants("あいでぃる")  # あいでぃる, あいでぃーる

Long vowels are written with ー, with the vowel (おう, うう, えい) or not at all
(でんそー / でんそう / でんそ).  The dictionary builders add the English word or
the official spelling under these readings only when the same katakana word has
the variant reading in Mozc, or when the pair is in ALLOWED, so the Japanese
candidate stays first and an unrelated Japanese word (あき / アキー) gets no
English candidate.  The set is small and stable.
"""
O_ROW = set("おこそとのほもよろごぞどぼぽょ")
U_ROW = set("うくすつふむゆぐずづぶぷゅ")
E_ROW = set("えけせてねへめれげぜでべぺ")
SMALL = "ぃぇぅぉ"
LONG_VOWELS = ("おう", "おお", "うう", "えい", "ええ", "いい")
LIMIT = 16

# (reading, variant) pairs that are added even when Mozc has no word for the
# variant reading.  Only words whose reading is commonly typed both ways and
# whose English word or official spelling is known belong here; every other
# variant is added only when the same katakana word has the variant reading in
# Mozc (so アキー does not put ackee on あき / 秋).
ALLOWED = {
    ("でんそ", "でんそう"),
    ("でんそー", "でんそう"),
    ("でんそ", "でんそー"),
    ("でんそー", "でんそ"),
    ("あいでぃる", "あいでぃーる"),
}


def allowed(reading, variant):
    return (reading, variant) in ALLOWED


def _add(out, value):
    if value and len(out) < LIMIT:
        out.add(value)


def variants(reading):
    """The reading and its long-vowel variants (at most LIMIT)."""
    if not reading:
        return {reading}
    out = {reading}

    # Each ー may be written as a vowel or left out.
    stack = [reading]
    while stack:
        text = stack.pop()
        at = text.find("ー")
        if at < 0:
            continue
        choices = ["", "う"]
        if at > 0 and text[at - 1] in O_ROW:
            choices.append("お")
        if at > 0 and text[at - 1] in E_ROW:
            choices.append("い")
        for replacement in choices:
            variant = text[:at] + replacement + text[at + 1:]
            if variant not in out and len(out) < LIMIT:
                out.add(variant)
                stack.append(variant)

    # A word ending in a long vowel can be typed with ー or the vowel.  This is
    # done on the original reading only (でんそ -> でんそー, でんそう), not on
    # every variant already made from ー.
    last = reading[-1]
    if last in O_ROW or last in U_ROW:
        _add(out, reading + "ー")
        _add(out, reading + "う")
    elif last in E_ROW:
        _add(out, reading + "ー")
        _add(out, reading + "い")
    # あいでぃる -> あいでぃーる
    for small in SMALL:
        at = reading.rfind(small)
        if at == len(reading) - 2 and not reading.endswith("ー"):
            _add(out, reading[:at + 1] + "ー" + reading[at + 1:])

    # Long vowels written with two vowels (おう, えい ...) and without the second.
    for pair in LONG_VOWELS:
        at = reading.find(pair)
        while at >= 0:
            _add(out, reading[:at] + pair[0] + "ー" + reading[at + 2:])
            _add(out, reading[:at] + pair[0] + reading[at + 2:])
            at = reading.find(pair, at + 1)
    return out
