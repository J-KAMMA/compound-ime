"""日本語に読める略語（ai、ui ...）の表を、検出器（native/jaen-detector/jaen_detector.cc）に書く。

  python tools/build_acronym_table.py            # jaen_detector.cc の BEGIN/END GENERATED の間を書き直す
  python tools/build_acronym_table.py --check    # 書き直す必要がないか、一覧どうしが食い違わないかを確かめる（変更しない）

入力は tools/data/acronyms.tsv（略語の一覧）と tools/data/acronym-cues.tsv（技術の語の手がかり）。
--check は次も確かめる:
  - 型 a の語は、英語の検出器の語の一覧（jaen-modern-words.tsv、jaen-extra-words.txt、jaen-brand-words.txt、
    jaen-domain-words.txt）にあり、表示の形が（brand-casing.tsv、jaen-modern-words.tsv、domain-casing.tsv の）どれかと同じ
  - 型 b（方式 cue、plain）の語は、表示の形が同じ表にある（検出器が英語に取ったあと、表示の形を先頭に出すのに要る）
  （型 a は英字が残り、型 b は全部かなに読める、の分け方は tools/acronym_probe.py --classify が確かめる）
  - 手がかりはひらがな（と ー）だけ
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "tools/data"
DETECTOR = REPO / "native/jaen-detector/jaen_detector.cc"
BEGIN = "// BEGIN GENERATED acronyms (tools/build_acronym_table.py)\n"
END = "// END GENERATED acronyms\n"
HIRAGANA = re.compile(r"[ぁ-ゖー]+")


def read_rows(name):
    return [line.rstrip("\n").split("\t") for line in (DATA / name).read_text(encoding="utf-8").splitlines()
            if line and not line.startswith("#")]


def acronyms():
    rows = []
    for f in read_rows("acronyms.tsv"):
        f += [""] * (7 - len(f))
        typed, shown, kind, reading, mode, rank, extra = f[:7]
        rows.append({"typed": typed, "shown": shown, "kind": kind, "reading": reading, "mode": mode,
                     "rank": rank, "extra": [c for c in extra.split(",") if c]})
    return rows


def cues():
    return [f[0] for f in read_rows("acronym-cues.tsv")]


def table_text(rows, shared):
    sentence = [r for r in rows if r["kind"] == "b" and r["mode"] in ("cue", "plain")]
    out = ["constexpr ReadableAcronym kReadableAcronyms[] = {\n"]
    for r in sorted(sentence, key=lambda r: r["typed"]):
        out.append(f'    {{"{r["typed"]}", {"true" if r["mode"] == "plain" else "false"}, "{",".join(r["extra"])}"}},\n')
    out.append("};\n")
    out.append("constexpr std::string_view kAcronymCues =\n    \"" + ",".join(shared) + "\";\n")
    return "".join(out)


def problems(rows, shared):
    bad = []
    typed_seen = set()
    for r in rows:
        t = r["typed"]
        if not re.fullmatch(r"[a-z]+", t) or t in typed_seen:
            bad.append(f"打つ形が小文字の英字でないか重複: {t}")
        typed_seen.add(t)
        if r["kind"] not in ("a", "b"):
            bad.append(f"型が a でも b でもない: {t}")
        if r["kind"] == "b":
            if not HIRAGANA.fullmatch(r["reading"]) or r["mode"] not in ("cue", "plain", "rank") or r["rank"] not in ("1", "2", "3"):
                bad.append(f"型 b の列が正しくない: {t}")
            if len(t) > 4 and r["mode"] != "rank":
                bad.append(f"文の中の規則で使う語は4文字まで（kMaxAcronymLength）: {t}")
            if r["mode"] != "cue" and r["extra"]:
                bad.append(f"追加の手がかりは方式 cue だけ: {t}")
        for c in r["extra"] + shared:
            if not HIRAGANA.fullmatch(c):
                bad.append(f"手がかりがひらがなでない: {c}")
    return bad


def lexicon_problems(rows):
    words, shown = set(), {}
    for name in ("jaen-extra-words.txt", "jaen-brand-words.txt", "jaen-domain-words.txt"):
        words |= {l.strip() for l in (DATA / name).read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")}
    for name in ("brand-casing.tsv", "jaen-modern-words.tsv", "domain-casing.tsv", "digit-words.tsv"):
        for f in read_rows(name):
            if len(f) >= 2:
                shown.setdefault(f[0], set()).add(f[1])
                if name == "jaen-modern-words.tsv":
                    words.add(f[0])
    bad = []
    for r in rows:
        # 型 b は、検出器の語の一覧ではなく表（kReadableAcronyms）で取る。表示の形（ai → AI）だけは、型 a と同じ表から出る
        if r["kind"] == "b":
            if r["mode"] != "rank" and r["shown"] not in shown.get(r["typed"], set()):
                bad.append(f"型 b の語の表示の形が表にない・違う: {r['typed']} → {r['shown']}（jaen-modern-words.tsv に足す）")
            continue
        if r["typed"] not in words:
            bad.append(f"型 a の語が英語の検出器の一覧にない: {r['typed']}（jaen-modern-words.tsv に足す）")
        if r["shown"] not in shown.get(r["typed"], set()):
            bad.append(f"型 a の語の表示の形が表にない・違う: {r['typed']} → {r['shown']}（表: {sorted(shown.get(r['typed'], []))}）")
    return bad


def main():
    rows, shared = acronyms(), cues()
    bad = problems(rows, shared)
    text = DETECTOR.read_text(encoding="utf-8")
    start, stop = text.index(BEGIN) + len(BEGIN), text.index(END)
    new = table_text(rows, shared)
    if "--check" in sys.argv:
        bad += lexicon_problems(rows)
        if text[start:stop] != new:
            bad.append("jaen_detector.cc の表が一覧と違う（python tools/build_acronym_table.py で書き直す）")
        print("\n".join(bad) if bad else f"一覧と表は合っている（型 a {sum(r['kind'] == 'a' for r in rows)}、型 b {sum(r['kind'] == 'b' for r in rows)}、手がかり {len(shared)}）")
        sys.exit(1 if bad else 0)
    if bad:
        sys.exit("\n".join(bad))
    DETECTOR.write_text(text[:start] + new + text[stop:], encoding="utf-8", newline="\n")
    print("書いた:", DETECTOR)


if __name__ == "__main__":
    main()
