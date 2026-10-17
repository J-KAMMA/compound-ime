"""分野（プログラミング、仮想通貨）の文書から、英字の語の一覧と大文字小文字の対を作る。

  python tools/build_domain_words.py --sentences out/sentences.jsonl \
      --out-words tools/data/jaen-domain-words.txt --out-casing tools/data/domain-casing.tsv

--sentences は tools/zenz-finetune/domain_text.py の出力（sentences.jsonl）。
練習用（split が "train"）の文だけを読む。試験用の文書の文は読まない（試験への漏れを防ぐ）。
domain_sources.json で分野が prog か crypto の出典だけを使う（話し言葉の出典は使わない）。

作るもの:
  1. 英語として残す語の一覧（jaen-domain-words.txt）。tools/build_english_lexicon.py が英単語の一覧に足す
     （4文字以下は厳選の語として、api、dao のように、かなが自然な日本語に読めないときに英語にする）。
     文書の英字だけの語（API、etcd、DeFi）のうち、一覧（SCOWL 水準35以下と、すでに厳選した語）にない
     3文字以上の語で、文書の数と回数が次の下限以上のもの。かなに読めてしまう一般的な英単語（region）や、
     日本語の読みと同じつづりになる語は、ここでは足さない（日本語の文を英語にしてしまうため）。
     日本語だけの文のローマ字で誤って英語になった語は --exclude の一覧で外す（手元の確認で決めたもの）。
  2. 大文字小文字の対（domain-casing.tsv）。小文字で打った語を、文書で多い書き方（Pod、React、PEP、
     MediaStream）で先に出す。割合と回数の下限を満たし、一般の英語でよく使う語（SCOWL 水準20以下。
     service、date、can、go）は除く。ただし厳選した製品名（react）は、割合が高ければ水準によらず入れる。
     すでに brand-casing.tsv、digit-words.tsv、jaen-modern-words.tsv にある語は変えない。
"""
import argparse
import collections
import hashlib
import io
import json
import re
import sys
import tarfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_english_lexicon as bel  # noqa: E402

TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+#/'-]*")
ALPHA = re.compile(r"[A-Za-z]+")
MIN_DOCS = 2          # 語を入れる文書の数の下限
MIN_COUNT = 3         # 語を入れる回数の下限
MIN_LEN_NEW = 3       # 一覧にない語の長さの下限
CASE_COUNT = 8        # 大文字小文字の対の回数の下限（あまり一般的でない英単語）
CASE_SHARE = 0.8      # 一番多い書き方の割合の下限（同上）
CASE_COUNT_NEW = 3    # 英単語の一覧にない語（識別子、略語）の下限
CASE_SHARE_NEW = 0.7
CASE_MAX_LEVEL = 20   # SCOWL の水準がこれ以下の語は、大文字小文字の対にしない
SIMPLE_SHARE = 0.9    # 先頭だけ大文字の書き方（Pod、Cache）の割合の下限
ORDINARY_LEVEL = 60   # SCOWL の水準がこれ以下の語は普通の英単語（cache、web、gallery）
STRONG_COUNT = 500    # 普通の英単語でも、これだけ多く、ほぼ全部がその書き方なら入れる（Pod）
STRONG_SHARE = 0.99
PARTICLES = ("no", "ha", "wo", "ga", "ni", "de", "to", "mo", "he", "ya", "ka", "yo", "ne", "wa")
BRAND_SHARE = 0.95    # 厳選した製品名の割合の下限
BRAND_COUNT = 50


def read_lines(path):
    return [line.rstrip("\n") for line in Path(path).read_text(encoding="utf-8").splitlines()]


def scowl_levels(archive):
    """SCOWL の英単語と水準（小さいほど一般的）。build_english_lexicon.py と同じ版を確かめて読む。"""
    data = Path(archive).read_bytes() if archive else urllib.request.urlopen(bel.URL, timeout=60).read()
    if hashlib.sha256(data).hexdigest() != bel.SHA256:
        raise SystemExit("SCOWL archive SHA-256 mismatch")
    levels = {}
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        root = "scowl-2020.12.07/"
        for member in tar.getmembers():
            name = member.name.removeprefix(root + "final/")
            kind, _, level = name.rpartition(".")
            if kind in ("english-words", "american-words") and level.isdigit():
                text = tar.extractfile(member).read().decode("iso-8859-1")
                for word in text.split():
                    if bel.WORD.fullmatch(word):
                        levels[word] = min(levels.get(word, 99), int(level))
    return levels


def table_words(path):
    """タブ区切りの表の1列目（打った形）の集まり。"""
    out = {}
    for line in read_lines(path):
        if line and not line.startswith("#") and "\t" in line:
            out.setdefault(line.split("\t")[0], line.split("\t")[1])
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sentences", required=True)
    ap.add_argument("--config", default=str(HERE / "zenz-finetune" / "domain_sources.json"))
    ap.add_argument("--data", default=str(HERE / "data"))
    ap.add_argument("--out-words", required=True)
    ap.add_argument("--out-casing", required=True)
    ap.add_argument("--exclude", default=str(HERE / "data" / "jaen-domain-exclude.txt"))
    ap.add_argument("--archive", help="already downloaded SCOWL archive")
    ap.add_argument("--hold-out", type=int, default=0,
                    help="確かめ用: 文書の名前の hash を5で割った余りが 0 の文書を読まない（1 にする）")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    data = Path(args.data)
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    names = {s["name"] for s in config["sources"] if s.get("domain") in ("prog", "crypto")}
    count = collections.defaultdict(collections.Counter)
    docs = collections.defaultdict(set)
    sentences = 0
    with open(args.sentences, encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            if row["split"] != "train" or row["source"] not in names:
                continue
            if args.hold_out and int(hashlib.md5(row["doc"].encode()).hexdigest(), 16) % 5 == 0:
                continue
            sentences += 1
            for m in TOKEN.finditer(row["text"]):
                token = m.group(0)
                if ALPHA.fullmatch(token):
                    count[token.lower()][token] += 1
                    docs[token.lower()].add((row["source"], row["doc"]))

    levels = scowl_levels(args.archive)
    brand = {w.strip() for w in read_lines(data / "jaen-brand-words.txt") if w.strip() and not w.startswith("#")}
    extra = {w.strip() for w in read_lines(data / "jaen-extra-words.txt") if w.strip() and not w.startswith("#")}
    curated = brand | extra
    exclude = set()
    if Path(args.exclude).exists():
        exclude = {w.strip() for w in read_lines(args.exclude) if w.strip() and not w.startswith("#")}

    bel_level = 35  # build_english_lexicon.py の --level の既定。これ以下の語は英単語の一覧に入っている
    words = []
    for word, variants in sorted(count.items(), key=lambda kv: (-sum(kv[1].values()), kv[0])):
        total = sum(variants.values())
        if total < MIN_COUNT or len(docs[word]) < MIN_DOCS or word in curated or word in exclude:
            continue
        if levels.get(word, 99) > bel_level and len(word) >= MIN_LEN_NEW:
            # 助詞で終わり、残りが英単語の語（lineno: line + の）は、日本語の文を英語にしてしまう
            stem = next((word[:-len(p)] for p in PARTICLES if word.endswith(p) and len(word) - len(p) >= 3), None)
            if stem and (levels.get(stem, 99) <= bel_level or stem in count):
                continue
            words.append(word)
    header = [
        "# 分野（プログラミング、仮想通貨）の文書に出る英字の語。tools/build_domain_words.py で作る（手で足さない）。",
        f"# 読んだ文: 練習用の {sentences} 文（試験用の文書は読まない）。下限: 文書 {MIN_DOCS}、回数 {MIN_COUNT}。",
        "# 日本語だけの文のローマ字で誤って英語になった語は jaen-domain-exclude.txt で外してある。",
    ]
    Path(args.out_words).write_text("\n".join(header + words) + "\n", encoding="utf-8", newline="\n")

    existing = {}
    for name in ("brand-casing.tsv", "digit-words.tsv", "jaen-modern-words.tsv"):
        for key, shown in table_words(data / name).items():
            existing.setdefault(key, shown)
    keep = {k for k, v in table_words(data / "brand-casing-fixes.tsv").items() if v == "-"}
    pairs = []
    for word, variants in sorted(count.items()):
        total = sum(variants.values())
        top, top_count = max(variants.items(), key=lambda kv: (kv[1], kv[0]))
        if len(word) < 2 or top == word or word in existing or word in exclude or word in keep:
            continue
        share = top_count / total
        level = levels.get(word, 99)
        simple = top == word.capitalize()  # 先頭だけ大文字
        if level > bel_level:  # 英単語の一覧にない語（識別子、略語、製品名）
            ok = total >= CASE_COUNT_NEW and share >= CASE_SHARE_NEW
        elif level > CASE_MAX_LEVEL:  # あまり一般的でない英単語（pod、cargo）
            ok = total >= CASE_COUNT and share >= CASE_SHARE
        else:  # 一般の英単語は、厳選した製品名（react）だけ
            ok = word in brand and share >= BRAND_SHARE and total >= BRAND_COUNT
        if ok and simple:
            # 先頭だけ大文字の書き方は、普通の英単語（cache、web）や日常の語（app、crypto）で
            # 利用者が小文字で打つ語を変えてしまう。割合を高くし、普通の英単語はほぼ全部のときだけ。
            ok = share >= SIMPLE_SHARE and (level > ORDINARY_LEVEL or word in brand or
                                            (total >= STRONG_COUNT and share >= STRONG_SHARE))
        if ok:
            pairs.append((word, top))
    header = [
        "# 打った形（小文字）<TAB>文書で多い書き方。tools/build_domain_words.py で作る（手で足さない）。",
        f"# 読んだ文: 練習用の {sentences} 文。下限: 英単語の一覧にない語は回数 {CASE_COUNT_NEW}・割合 {CASE_SHARE_NEW}、"
        f"あまり一般的でない英単語は回数 {CASE_COUNT}・割合 {CASE_SHARE}。一般の英単語（SCOWL 水準 {CASE_MAX_LEVEL} 以下）は除く。",
    ]
    Path(args.out_casing).write_text("\n".join(header + [f"{a}\t{b}" for a, b in pairs]) + "\n",
                                     encoding="utf-8", newline="\n")
    print(f"文 {sentences}、語 {len(words)}、大文字小文字の対 {len(pairs)}")


if __name__ == "__main__":
    main()
