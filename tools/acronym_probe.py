"""略語の英語判定を、Mozc なしで前後比べする（native/jaen-detector/jaen_trial.cc を使う）。

  python tools/acronym_probe.py --before cc2ef50          # 今の作業の木と、その版（before）を比べる
  python tools/acronym_probe.py --classify                # tools/data/acronyms.tsv の型（a、b）が、読み方と合っているか
  python tools/acronym_probe.py --before cc2ef50 --show 40 # 前後で変わった文を40件まで書く

何を測るか: tests/conversion/acronyms.tsv（略語が入った文）と acronyms-ja.tsv（日本語の語が重なる文）の打った形を
jaen_trial に通し、英語の語として切り出される部分を見る。
  acronyms.tsv: 期待する略語（打った形）が英語の語として切り出されれば合い
  acronyms-ja.tsv: 型 b の略語（ai、ui ...）が英語として切り出されなければ合い（切り出されたら、日本語の文が壊れた）
前後の差は、その版の jaen_detector.cc と tools/data の語の一覧の差（jaen_trial.cc と試験の文は作業の木のものを両方に使う）。

本物との違い（ここでの数字は目安。最後は GitHub の試験の組 r で確かめる）:
  - ローマ字表は tools/make_test_romaji_table.py の写し（Mozc の表ではない）
  - 英語の語の一覧は tools/data の自作の語（略語・製品名）だけ。SCOWL の一般の英単語は入っていない
  - 日本語の読みの辞書がない。既定（辞書なし）は、日本語の語の途中の略語を止める仕組み（crosses_reading）が働かない最悪の場合。
    --readings を付けると、試験の文に出る日本語の語の読み（tests/conversion/acronyms-readings.txt）を辞書の代わりにする
    （辞書があるときの動きの目安。ほかの英語の判定が辞書つきの経路に入るので、略語以外の英語は数えない）
"""
import argparse
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "tools/data"
TESTS = REPO / "tests/conversion"
DETECTOR_FILES = ["jaen_detector.cc", "jaen_detector.h", "jaen_trial.cc"]


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, text=True, capture_output=True, **kw)


def build(rev, workdir, name):
    """rev が None なら作業の木、そうでなければその版の jaen_detector.* で jaen_trial を作る"""
    src = workdir / name
    src.mkdir()
    for f in DETECTOR_FILES:
        text = (REPO / "native/jaen-detector" / f).read_text(encoding="utf-8") if rev is None else \
            run(["git", "-C", str(REPO), "show", f"{rev}:native/jaen-detector/{f}"]).stdout
        (src / f).write_text(text, encoding="utf-8")
    # jaen_trial.cc は作業の木のもので統一する（版による違いは検出器だけにする）
    (src / "jaen_trial.cc").write_text((REPO / "native/jaen-detector/jaen_trial.cc").read_text(encoding="utf-8"), encoding="utf-8")
    exe = workdir / f"trial-{name}"
    run(["g++", "-std=c++20", "-O2", "-I", str(src), str(src / "jaen_trial.cc"), str(src / "jaen_detector.cc"), "-o", str(exe)])
    return exe


def data_text(name, rev):
    if rev is None:
        return (DATA / name).read_text(encoding="utf-8")
    return run(["git", "-C", str(REPO), "show", f"{rev}:tools/data/{name}"]).stdout


def make_lexicon(workdir, rev=None, label="lex"):
    """英語の語の一覧（tools/data の自作の語）。rev を付けると、その版の一覧で作る（前後の語の差も測る）"""
    lex = workdir / label
    lex.mkdir()

    def lines(name):
        return [l.strip() for l in data_text(name, rev).splitlines() if l.strip() and not l.startswith("#")]

    curated = sorted({w for n in ("jaen-extra-words.txt", "jaen-brand-words.txt", "jaen-domain-words.txt") for w in lines(n)
                      if re.fullmatch(r"[a-z]+", w)})
    named = sorted({l.split("\t")[0] for l in lines("jaen-modern-words.tsv") if "\t" in l and re.fullmatch(r"[a-z]+", l.split("\t")[0])})
    (lex / "curated-words.txt").write_text("\n".join(curated) + "\n", encoding="utf-8")
    (lex / "english-lexicon.txt").write_text("\n".join(curated) + "\n", encoding="utf-8")
    (lex / "signal-words.txt").write_text("\n".join(named) + "\n", encoding="utf-8")
    (lex / "common-words.txt").write_text("", encoding="utf-8")
    (lex / "joined.txt").write_text("\n".join(lines("english-joined.txt")) + "\n", encoding="utf-8")
    (lex / "phrases.txt").write_text("\n".join(lines("english-phrases.txt")) + "\n", encoding="utf-8")
    (lex / "places.tsv").write_text("\n".join(lines("hepburn-places.tsv")) + "\n", encoding="utf-8")
    return lex


def make_work(workdir, readings):
    work = workdir / "work"
    work.mkdir()
    table = run([sys.executable, str(REPO / "tools/make_test_romaji_table.py")]).stdout
    (work / "romaji.tsv").write_text(table, encoding="utf-8")
    if readings:
        (work / "readings.txt").write_text((TESTS / "acronyms-readings.txt").read_text(encoding="utf-8"), encoding="utf-8")
    return work


def pieces(exe, work, lex, lines, readings, dump=False):
    env = {"PATH": "/usr/bin:/bin"}
    if not readings:
        env["NO_READING"] = "1"
    if dump:
        env["DUMP_CHUNKS"] = "1"
    out = run([str(exe), str(work), str(lex)], input="".join(l + "\n" for l in lines), env=env).stdout.split("\n")
    if dump:
        return out
    result = []
    for line in out:
        if "\t" in line:
            result.append([p for p in line.split("\t", 1)[1].split(",") if p])
    return result


def read_tests(name):
    return [l.split("\t") for l in (TESTS / name).read_text(encoding="utf-8").splitlines() if l and not l.startswith("#")]


def acronym_tables():
    typed_of, kind_b = {}, set()
    for l in (DATA / "acronyms.tsv").read_text(encoding="utf-8").splitlines():
        if l and not l.startswith("#"):
            f = l.split("\t")
            typed_of[f[1]] = f[0]
            if f[2] == "b":
                kind_b.add(f[0])
    return typed_of, kind_b


def classify(exe, work, lex):
    rows = [l.split("\t") for l in (DATA / "acronyms.tsv").read_text(encoding="utf-8").splitlines() if l and not l.startswith("#")]
    words = [r[0] for r in rows]
    curated = set((lex / "curated-words.txt").read_text(encoding="utf-8").split())
    dump = pieces(exe, work, lex, words, False, dump=True)
    bad, via_dictionary = [], []
    n_a = n_b = 0
    for k, r in enumerate(rows):
        chunks = re.findall(r"\[([^|]*)\|([^|]*)\|([^\]]*)\]", dump[2 * k])
        # 印: 英字が残る（強い）、x?・l?・v?・q? の小さいかなや子音+w+母音（弱い）
        strong = any(re.search("[A-Za-z]", c + p) and not (c == "" and p == "n") for _, c, p in chunks)
        weak = any(raw[:1] in "xlvq" or (len(raw) == 3 and raw[1] == "w") for raw, c, _ in chunks if c)
        if r[2] == "a":
            n_a += 1
            if not (strong or weak):
                if r[0] in curated and len(r[0]) >= 3:
                    via_dictionary.append(r[0])  # 全部かなに読めるが、読みが辞書にない語として取る（厳選の語。辞書があるとき）
                else:
                    bad.append(f"型 a なのに全部かなに読める（型 b にする。厳選の語でもない）: {r[0]}")
        else:
            n_b += 1
            if strong or weak:
                bad.append(f"型 b なのに英字か弱い印が残る（型 a にする）: {r[0]}")
    print(f"型 a {n_a} 語、型 b {n_b} 語")
    if via_dictionary:
        print("型 a のうち、全部かなに読めるが、厳選の語（3文字以上）として、読みが辞書にないときに取る語:", " ".join(via_dictionary))
    print("\n".join(bad) if bad else "どれも、読み方と型が合っている")
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--before", help="比べる前の版（git の版。例 cc2ef50）")
    ap.add_argument("--classify", action="store_true")
    ap.add_argument("--readings", action="store_true", help="日本語の読みの代わりの一覧を使う（辞書があるときの目安）")
    ap.add_argument("--show", type=int, default=25)
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        lex = make_lexicon(workdir)
        lex_before = make_lexicon(workdir, args.before, "lex-before") if args.before else None
        work = make_work(workdir, args.readings)
        after = build(None, workdir, "after")
        if args.classify:
            return classify(after, work, lex)
        before = build(args.before, workdir, "before") if args.before else None
        typed_of, kind_b = acronym_tables()

        def verdicts(exe, name, expect_acronym, lexicon):
            tests = read_tests(name)
            got = pieces(exe, work, lexicon, [t[0] for t in tests], args.readings)
            out = []
            for t, g in zip(tests, got):
                if expect_acronym:
                    want = typed_of.get(t[3], t[3].lower())
                    out.append(want in g)
                else:
                    out.append(not any(p in kind_b for p in g))
            return tests, out, got

        for name, expect, label in (("acronyms.tsv", True, "略語が入った文（期待: 略語が英語の語として切り出される）"),
                                    ("acronyms-ja.tsv", False, "日本語の語が重なる文（期待: 略語が切り出されない）")):
            tests, now, got = verdicts(after, name, expect, lex)
            old = verdicts(before, name, expect, lex_before)[1] if before else None
            print(f"== {name}: {label}")
            by = defaultdict(lambda: [0, 0, 0])  # 前、後、数
            for k, t in enumerate(tests):
                by[t[4]][2] += 1
                by[t[4]][1] += now[k]
                by[t[4]][0] += old[k] if old else 0
                by["全部"][2] += 1
                by["全部"][1] += now[k]
                by["全部"][0] += old[k] if old else 0
            for origin in sorted(by, key=lambda o: (o != "全部", o)):
                b, a, n = by[origin]
                print(f"  {origin}: " + (f"前 {b}/{n} → " if old else "") + f"後 {a}/{n}")
            if old:
                changed = [(k, t) for k, t in enumerate(tests) if old[k] != now[k]]
                better = [x for x in changed if now[x[0]]]
                worse = [x for x in changed if not now[x[0]]]
                print(f"  変わった文: 良くなった {len(better)}、悪くなった {len(worse)}")
                for k, t in worse[:args.show]:
                    print(f"    悪化 {t[0]} → {','.join(got[k]) or '-'}（{t[1]}）")
                for k, t in better[: min(args.show, 8)]:
                    print(f"    改善 {t[0]} → {','.join(got[k]) or '-'}（{t[1]}）")
            misses = [(k, t) for k, t in enumerate(tests) if not now[k]]
            print(f"  合わなかった文: {len(misses)}")
            by_origin = defaultdict(list)
            for k, t in misses:
                by_origin[t[4]].append((k, t))
            for origin, items in sorted(by_origin.items()):
                for k, t in items[:args.show if origin in ('ja-hard', 'ja-plain', 'ja-inside', 'b-cue', 'b-plain') else 3]:
                    print(f"    [{origin}] {t[0]} → {','.join(got[k]) or '-'}（期待: {t[1]}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
