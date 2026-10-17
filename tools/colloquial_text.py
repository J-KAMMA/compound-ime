"""話し言葉の打ち込み試験（tests/conversion/colloquial.tsv）と、学習の材料の候補（colloquial-train.jsonl）を作る。

  python tools/colloquial_text.py --tatoeba jpn_sentences.tsv.bz2 --table <romanji-hiragana.tsv> \
      --out-dir out [--count 300] [--seed 20261017] [--dump-sha256 …] [--dump-date 2026-10-10]

材料は Tatoeba の日本語の文（CC BY 2.0 FR。表記は Tatoeba の投稿者）。1行は「番号<TAB>jpn<TAB>文」。
手順:
  1. 文の番号の SHA-256 で、全体の 10% を「試験の枠」に取り分ける（練習には絶対に使わない）。
  2. 文を選ぶ: 6〜40 字、漢字・かな・ー・、。だけ（末尾に限って ！ ？ を 2 つまで）、ていねいな言い方
     （です・ます など）は除く。話し言葉のしるしで 5 つの区分に分ける
       終助詞（よ・ね・じゃん・っしょ・かな …）、縮約（ちゃう・てる・とく・んだ …）、
       くだけた言い方、疑問（？）、感嘆（！）。
  3. 試験: 試験の枠の文から、区分ごとの枠で count 文（既定 300）。固有名（トム・メアリー …）の文は 15% まで。
     読みは SudachiPy（tools/wiki_typing_test.py と同じ）で付け、ローマ字（ヘボン式）に戻して
     かなに読み戻せない文は除く。tests/conversion の既存の試験と重なる文も除く（TestExclusion）。
     ！ ？ は半角の ! ? で打つ（Mozc の全角記号の変換）。
  4. 練習の材料: 試験の枠に入らなかった、話し言葉のしるしがある文（--train-all で全部）を、
     tools/zenz-finetune/domain_text.py の sentences.jsonl と同じ形（source・doc・split・text・prev）で書く。
     試験の文と重なるものは除く。

できるもの（--out-dir）:
  tests/colloquial.tsv         ローマ字<TAB>元の文<TAB>区分<TAB>Tatoeba の番号（先頭の # 行に出典・版・利用条件）
  colloquial-train.jsonl       練習の材料の候補
  colloquial-counts.json       件数
"""
import argparse
import bz2
import hashlib
import json
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "zenz-finetune"))
sys.path.insert(0, str(HERE))
import build_dataset as bd  # noqa: E402
import romaji_variants as rv  # noqa: E402

BODY = re.compile(r"[一-龯々〆ヵヶぁ-ゖァ-ヺー、。]+")
TAIL = re.compile(r"([！？]{1,2})$")
POLITE = re.compile(r"です|ます|でした|ました|ません|ください|ござい|でしょう|ましょう|いたし|おり[まま]|いただ|くださ|ませ|"
                    r"であっ|である|ざるを|であろ|において|べさ|だっぺ|ちまう|ちまっ|ンだ|だべ")
NAME = re.compile(r"トム|メアリー|ボブ|ジョン|ジャック|ケン|アリス|ベス|リサ|ジム")

# 区分ごとの、話し言葉のしるし（先に当てはまった区分に入れる）
CATEGORIES = [
    ("終助詞", re.compile(r"(?:よ|ね|ねえ|ねぇ|な|ぞ|ぜ|(?<=[ぁ-ん])わ|わよ|わね|かな|かなあ|かしら|のよ|んだよ|だよ|だね|だよね|"
                          r"じゃん|じゃんか|っしょ|だろ|でしょ|もん|っけ|のね|のよね)[。！？]*$")),
    ("縮約", re.compile(r"ちゃ[うっいえ]|ちゃって|じゃった|じゃう|(?:[いきしちにびみりぎじっ]|[一-龯])(?:て(?:る|た|ない|ね|よ)|で(?:る|た))|"
                        r"なきゃ|なくちゃ|なくっちゃ|とく|といた|といて|とこう|ってば|ってこと|"
                        r"(?<=[たるいうくすつぬむぶぐ])んだ|んじゃ|じゃない|じゃなくて|じゃん|やっぱ(?!り)|めっちゃ|すっご|ちっちゃ|でっか|"
                        r"っぽい|もん[。！？]|っての|っけ")),
    ("くだけた言い方", re.compile(r"やばい|ヤバい|まじで|まじか|マジ|すげ[えぇー]|うそ[！？。]|嘘[！？]|えっ|えー|ええ[、！]|うん[、。！]|あっ[、！]|"
                                 r"おい[、！]|おいおい|ねえ|ねぇ|ほら[、！]|なんか|だめ[だよ]|ダメ|いいじゃ|ごめん|ありがと[！。]|"
                                 r"どうしよう|おっ|わあ|やったー|やったぁ|やった！|そっか|へえ|ふうん|いやだ|嫌だ|しんどい|だるい|むかつく|うざい|きもい|"
                                 r"あのさ|ていうか|けどさ|めちゃ|おなか|だよな|だな[。！]")),
    ("疑問", re.compile(r"^")),   # 末尾が ？ のもの（下で確かめる）
    ("感嘆", re.compile(r"^")),   # 末尾が ！ のもの
]
QUOTA_SHARE = {"終助詞": 0.28, "縮約": 0.27, "くだけた言い方": 0.17, "疑問": 0.15, "感嘆": 0.13}


def classify(body: str, marks: str):
    """区分の名前、当てはまらなければ None。"""
    if POLITE.search(body):
        return None
    for name, pattern in CATEGORIES[:3]:
        if pattern.search(body + marks):
            return name
    if marks.endswith("？"):
        return "疑問"
    if marks.endswith("！"):
        return "感嘆"
    return None


def stable_unit(seed: int, key: str) -> float:
    value = hashlib.sha256(f"{seed}\t{key}".encode("utf-8")).digest()
    return int.from_bytes(value[:8], "big") / 2**64


def read_tatoeba(path: str):
    opener = bz2.open if path.endswith(".bz2") else open
    with opener(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            cols = line.rstrip("\n").split("\t")
            if len(cols) >= 3 and cols[1] == "jpn":
                yield cols[0], cols[2].strip()


def shape(text: str):
    """(本体, 末尾の ！？) か、形が合わない文なら None。"""
    if not (6 <= len(text) <= 40):
        return None
    m = TAIL.search(text)
    marks = m.group(1) if m else ""
    body = text[:len(text) - len(marks)]
    if not body or not BODY.fullmatch(body) or body[0] in "、。ー" or not re.search(r"[ぁ-ゖ]", body):
        return None
    return body, marks


def typing_line(body, marks, reader, table, rev):
    """(ローマ字, 読み) か、試験に使えない文なら None。"""
    tokens = reader.analyze(body)
    if not tokens:
        return None
    kana = bd.to_hiragana("".join(t.reading for t in tokens))
    raw = rv.write(kana, "base", rev)
    if not raw or rv.to_kana(raw, table) != kana:
        return None
    return raw + "".join("!" if c == "！" else "?" for c in marks), kana + marks


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tatoeba", required=True)
    ap.add_argument("--table", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--count", type=int, default=300)
    ap.add_argument("--seed", type=int, default=20261017)
    ap.add_argument("--pool-fraction", type=float, default=0.1, help="試験の枠に取り分ける割合")
    ap.add_argument("--name-share", type=float, default=0.15, help="固有名（トム など）の文の割合の上限")
    ap.add_argument("--train-all", action="store_true", help="練習の材料に、話し言葉のしるしがない文も入れる")
    ap.add_argument("--dump-sha256", default="")
    ap.add_argument("--dump-date", default="")
    ap.add_argument("--repo", default=str(HERE.parent))
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    table = rv.load_table(args.table)
    rev = rv.reverse_table(table)
    reader = bd.SudachiReader("core")
    exclusion = bd.TestExclusion(Path(args.repo) / "tests/conversion", bd.load_romaji_table(Path(args.table)),
                                 ignore=("colloquial.tsv",))
    rng = random.Random(args.seed)

    pool, train, seen = [], [], set()
    stats = {"total": 0, "shape": 0, "polite": 0, "duplicate": 0, "pool": 0, "train_candidates": 0}
    for sid, text in read_tatoeba(args.tatoeba):
        stats["total"] += 1
        parts = shape(text)
        if parts is None:
            stats["shape"] += 1
            continue
        body, marks = parts
        key = bd.norm_surface(text)
        if key in seen:
            stats["duplicate"] += 1
            continue
        seen.add(key)
        in_pool = stable_unit(args.seed, sid) < args.pool_fraction
        category = classify(body, marks)
        if category is None and POLITE.search(body):
            stats["polite"] += 1
        if in_pool:
            stats["pool"] += 1
            if category:
                pool.append((sid, text, body, marks, category))
        elif category or args.train_all:
            train.append((sid, text, body, marks, category or ""))

    # ---- 試験: 区分ごとの枠
    pool.sort(key=lambda r: stable_unit(args.seed + 1, r[0]))
    quota = {name: int(round(args.count * share)) for name, share in QUOTA_SHARE.items()}
    quota["終助詞"] += args.count - sum(quota.values())
    chosen, names = {name: [] for name in quota}, 0
    max_names = int(args.count * args.name_share)
    blocked_count = 0
    for sid, text, body, marks, category in pool:
        if len(chosen[category]) >= quota[category]:
            continue
        is_name = bool(NAME.search(text))
        if is_name and names >= max_names:
            continue
        made = typing_line(body, marks, reader, table, rev)
        if made is None:
            continue
        if exclusion.blocked(text, [made[1]]):
            blocked_count += 1
            continue
        chosen[category].append((made[0], text, category, sid))
        names += is_name
        if all(len(chosen[n]) >= quota[n] for n in quota):
            break
    lines = [row for rows in chosen.values() for row in rows]
    rng.shuffle(lines)

    out_dir = Path(args.out_dir)
    (out_dir / "tests").mkdir(parents=True, exist_ok=True)
    header = [
        "# 話し言葉の打ち込み試験。Tatoeba（https://tatoeba.org/）の日本語の文のうち、終助詞・縮約・くだけた言い方・疑問・感嘆の"
        "しるしがある文を、SudachiPy の読みからローマ字にしたもの。! と ? は半角で打ち、全角の ！ ？ で出ることを期待する。",
        "# 列: ローマ字<TAB>元の文<TAB>区分<TAB>Tatoeba の文の番号。tools/colloquial_text.py で作成。"
        "文の番号の SHA-256 で取り分けた試験の枠の文だけ（練習の材料には使わない）。",
        f"# 出典と利用条件: Tatoeba の文（クリエイティブ・コモンズ 表示 2.0 フランス = CC BY 2.0 FR、一部は CC0）。"
        f"表示: Tatoeba の投稿者（各文の番号 https://tatoeba.org/sentences/show/<番号>）。"
        f"版: https://downloads.tatoeba.org/exports/per_language/jpn/jpn_sentences.tsv.bz2 の {args.dump_date}"
        f" 版、SHA-256 {args.dump_sha256}。利用条件の根拠: https://tatoeba.org/en/terms_of_use",
    ]
    text_out = "\n".join(header) + "\n" + "\n".join("\t".join(map(str, row)) for row in lines) + "\n"
    test_path = out_dir / "tests" / "colloquial.tsv"
    test_path.write_text(text_out, encoding="utf-8", newline="\n")
    print(f"colloquial.tsv: {len(lines)} 文（" + "、".join(f"{n} {len(chosen[n])}" for n in quota) + f"）、固有名 {names}")

    # ---- 練習の材料: 試験の枠に入らなかった文。選んだ試験の文と重なるものも除く
    exclusion2 = bd.TestExclusion(Path(args.repo) / "tests/conversion", bd.load_romaji_table(Path(args.table)),
                                  ignore=("colloquial.tsv",), extra_files=[test_path])
    kept = overlap = 0
    with open(out_dir / "colloquial-train.jsonl", "w", encoding="utf-8", newline="\n") as handle:
        for sid, text, body, marks, category in train:
            tokens = reader.analyze(body)
            if not tokens:
                continue
            kana = bd.to_hiragana("".join(t.reading for t in tokens)) + marks
            if exclusion2.blocked(text, [kana]):
                overlap += 1
                continue
            handle.write(json.dumps({"source": "tatoeba", "doc": f"tatoeba:{sid}", "split": "train", "text": text,
                                     "prev": "", "category": category}, ensure_ascii=False) + "\n")
            kept += 1
    by_category = {}
    for row in train:
        by_category[row[4] or "なし"] = by_category.get(row[4] or "なし", 0) + 1
    counts = {"stats": stats, "test": {n: len(chosen[n]) for n in quota}, "test_blocked_by_existing_tests": blocked_count,
              "train_candidates_by_category": by_category, "train_written": kept, "train_overlap_with_tests": overlap,
              "dump_sha256": args.dump_sha256, "dump_date": args.dump_date}
    (out_dir / "colloquial-counts.json").write_text(json.dumps(counts, ensure_ascii=False, indent=2) + "\n",
                                                    encoding="utf-8", newline="\n")
    print(json.dumps(counts, ensure_ascii=False))


if __name__ == "__main__":
    main()
