"""辞書の更新で配る「英語の一覧」（english-extra.tsv）を、tools/data の一覧から作る。

  python tools/build_english_extra.py --out english-extra.tsv [--data tools/data] [--proper-nouns <新しい proper-nouns.tsv>]

組み立て時に本体へ焼き込む一覧（tools/apply_jaen_integration.py）と同じ決まりで、同じ元の一覧から作る。
行は「種類<TAB>語[<TAB>表示の形]」（native/dict_update/data.h）:
  curated  厳選の英単語   jaen-extra-words.txt、jaen-brand-words.txt、jaen-domain-words.txt の語と、digit-words.tsv の打った形
  named    手で挙げた名前   jaen-modern-words.tsv の打った形（略語・IT・サービス名）
  signal   強い印のときだけ英語に取る語   proper-nouns.tsv の「打つ形」が1語のもの
  phrase   2語以上の言い回し   english-phrases.txt と、proper-nouns.tsv の「打つ形」が2語以上のもの
  casing   小文字で打った語の表示の形   brand-casing.tsv、digit-words.tsv、jaen-modern-words.tsv、domain-casing.tsv、
           proper-nouns.tsv（印が s でないもの）の順で、同じ打った形は先のものだけ
  casing2  普通の英単語でもある名前の表示の形   proper-nouns.tsv の印が s のもの
本体に焼き込んだ表の語や表示の形は、本体が優先する（取った一覧は足すだけ）。本体の決まりに合わない行は、数えて外す。
--proper-nouns に月1回取り直した proper-nouns.tsv を渡すと、それで作る。
"""
import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import make_dict_release as mdr  # noqa: E402

WORD = re.compile(r"[a-z0-9']{1,40}\Z")
LOWER = re.compile(r"[a-z0-9']{1,24}\Z")



def rows(path, minimum=1):
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            f = line.split("\t")
            if len(f) >= minimum:
                out.append(f)
    return out


def words(path):
    return [l.strip() for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--data", type=Path, default=HERE / "data")
    ap.add_argument("--proper-nouns", type=Path)
    args = ap.parse_args()
    data = args.data
    proper = rows(args.proper_nouns or data / "proper-nouns.tsv", 3)

    skipped = 0
    out = {"curated": set(), "named": set(), "signal": set(), "phrase": set()}
    casing, casing2 = {}, {}

    def add_word(kind, w):
        nonlocal skipped
        if WORD.match(w):
            out[kind].add(w)
        else:
            skipped += 1

    for name in ("jaen-extra-words.txt", "jaen-brand-words.txt"):
        for w in words(data / name):
            add_word("curated", w)
    # 分野の語は、本体の組み立て（tools/build_english_lexicon.py）と同じく 4文字以下だけ厳選にする。
    # 5文字以上（inode、kohaku、amazon）は普通の語として焼き込み済みで、厳選にすると日本語の文
    # （「暑いので」の「いの」→ inode）を英語にしてしまう。
    for w in words(data / "jaen-domain-words.txt"):
        if len(w) <= 4:
            add_word("curated", w)
    for f in rows(data / "digit-words.tsv", 2):
        add_word("curated", f[0])
    for f in rows(data / "jaen-modern-words.tsv", 2):
        add_word("named", f[0])
    for phrase in words(data / "english-phrases.txt"):
        if all(LOWER.match(w) for w in phrase.split(" ")) and " " in phrase and len(phrase) <= 80:
            out["phrase"].add(phrase)
        else:
            skipped += 1

    cased = set()  # 表示の形を決めた、打った形（本体の組み立てと同じく、先の表のものを優先する）

    def add_casing(table, typed, shown):
        nonlocal skipped
        if mdr.CASING_KEY.match(typed) and len(typed) <= 80 and mdr.shown_ok(shown):
            table[typed] = shown
            cased.add(typed)
        else:
            skipped += 1

    for name in ("brand-casing.tsv", "digit-words.tsv"):
        for f in rows(data / name, 2):
            if f[0] not in cased:
                add_casing(casing, f[0], f[1])
    for name in ("jaen-modern-words.tsv", "domain-casing.tsv"):
        for f in rows(data / name, 2):
            if f[0] not in cased and f[1] != f[0]:
                add_casing(casing, f[0], f[1])
    for f in proper:
        shown, typed = f[0], f[1]
        if not typed:
            continue
        flag = f[2] if len(f) > 2 else ""
        if typed not in cased:
            add_casing(casing2 if flag == "s" else casing, typed, shown)
        if " " in typed:
            if all(LOWER.match(w) for w in typed.split(" ")) and len(typed) <= 80:
                out["phrase"].add(typed)
            else:
                skipped += 1
        else:
            add_word("signal", typed)

    lines = ["# 辞書の更新で配る英語の一覧。tools/build_english_extra.py で作る（手で足さない）。"]
    for kind in ("curated", "named", "signal", "phrase"):
        lines += [f"{kind}\t{w}" for w in sorted(out[kind])]
    lines += [f"casing\t{t}\t{s}" for t, s in sorted(casing.items())]
    lines += [f"casing2\t{t}\t{s}" for t, s in sorted(casing2.items())]
    text = "\n".join(lines) + "\n"
    errors = mdr.validate_english(text)
    if errors:
        raise SystemExit("作った一覧が決まりに合いません: " + "; ".join(errors))
    args.out.write_text(text, encoding="utf-8", newline="\n")
    print(f"rows {len(lines) - 1} (curated {len(out['curated'])}, named {len(out['named'])}, signal {len(out['signal'])}, "
          f"phrase {len(out['phrase'])}, casing {len(casing)}, casing2 {len(casing2)}), skipped {skipped}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
