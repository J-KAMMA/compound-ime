"""判定専用の模型（Jev のような仕組み）の設計: 上限と、今の zenz で採点だけしたときの正しさを数える。

  python tools/jev_ceiling.py jobs   <材料> <tests/conversion> <本線の結果> <jobs.tsv> [<bench の出力先>]
  python tools/jev_ceiling.py report <材料> <tests/conversion> <本線の結果> [<採点の出力のフォルダ>]

材料は tools/jev_collect.sh の出力（人工知能なしの変換の、文節ごとの候補の上位16、そのコスト、
AzooKey の辞書の文全体の候補）。本線の結果は linux-results（人工知能 v5 の出力。run 39196977336）。

候補の集まり:
  文節K   今の Mozc の文節の切り方のまま、文節ごとの候補の上位K（K=4、8、16）から1つずつ選んで組む
  組N     同じ候補を、Mozc のコストの和の小さい順に並べた文全体の上位N（N=8、32）
  辞書N   AzooKey の辞書の変換（生成なし）の、読み全体を使い切る文全体の候補の上位N（N=8、32）
上限: 正解の文がその集まりから組めるか（完全に選べたら何文正解か）。
生成でしか出ない: 本線（v5）は正解なのに、どの集まり（文節16 ∪ 組32 ∪ 辞書32）からも正解を組めない文。

jobs: 採点の材料（tools/jev_score.cpp の入力）を書く。1文1行で、候補は 辞書32 ∪ 組32 ∪ 本線の出力 ∪ 正解。
report: 上限の表と、採点の出力があれば (a)（今の zenz の対数確率の最大を選ぶ）の正しさを出す。
"""
import heapq
import json
import re
import sys
from pathlib import Path

TAG_INPUT, TAG_OUTPUT, TAG_LEFT, TAG_RIGHT = "", "", "", ""
CONTROL_RE = re.compile("[-]")
CONTEXT_MAX = 40
TO_KATA = {c: c + 0x60 for c in range(ord("ぁ"), ord("ゖ") + 1)}


def model_text(text):
    return text.replace(" ", "　").replace("\n", "")


def build_prompt(reading, left=""):
    left = CONTROL_RE.sub("", left.split("\n")[-1])[-CONTEXT_MAX:]
    prompt = (TAG_LEFT + left) if left else ""
    return model_text(prompt + TAG_INPUT + reading.translate(TO_KATA) + TAG_OUTPUT)


# ---- 試験と正解 ----
def rows(path):
    return [l.rstrip("\n").split("\t") for l in open(path, encoding="utf-8") if l.strip() and not l.startswith("#")]


def tests(tdir):
    """名前 → [(ローマ字, 正解の一覧, 前の文, 大文字小文字を区別しないか)]（jev_collect.sh の番号の順）"""
    t = Path(tdir)
    out = {}
    for name in ("ja400", "jaen200b", "typo150", "typo150b", "reported", "jaen270"):
        items = json.loads((t / f"{name}.json").read_text(encoding="utf-8"))["items"]
        out[name] = [(i["romaji"], [i["intended"], *i.get("alternatives", [])], "", True) for i in items]
    wiki = rows(t / "wiki-typing.tsv")
    for k in range(1, 5):
        out[f"wikiw{k}"] = [(r[0], [r[1]], "", False) for n, r in enumerate(wiki) if n % 4 == k - 1]
    ctx = rows(t / "context.tsv")
    out["ctxw"] = [(r[0], [r[1]], r[2] if len(r) > 2 else "", False) for r in ctx]
    out["ctxo"] = [(r[0], [r[1]], "", False) for r in ctx]
    out["coll"] = [(r[0], [r[1]], "", False) for r in rows(t / "colloquial.tsv")]
    out["prog"] = [(r[0], [r[1]], "", False) for r in rows(t / "domain-prog.tsv")]
    out["crypto"] = [(r[0], [r[1]], "", False) for r in rows(t / "domain-crypto.tsv")]
    return out


BASE_FILE = {"ja400": "ja400.tsv", "jaen200b": "jaen200b.tsv", "typo150": "typo150.tsv", "typo150b": "typo150b.tsv",
             "reported": "reported.tsv", "jaen270": "jaen270.tsv", "ctxw": "context-with.tsv",
             "ctxo": "context-without.tsv", "coll": "colloquial.tsv", "prog": "domain-prog.tsv",
             "crypto": "domain-crypto.tsv", **{f"wikiw{k}": "wiki-typing.tsv" for k in range(1, 5)}}
# 表に出す試験のまとまり
GROUPS = [("ja400", ["ja400"]), ("jaen270", ["jaen270"]), ("jaen200b", ["jaen200b"]), ("typo150", ["typo150"]),
          ("typo150b", ["typo150b"]), ("reported", ["reported"]),
          ("wiki-typing", ["wikiw1", "wikiw2", "wikiw3", "wikiw4"]), ("context 前の文あり", ["ctxw"]),
          ("context 前の文なし", ["ctxo"]), ("colloquial", ["coll"]), ("domain", ["prog", "crypto"])]


def load_out(path):
    got = {}
    if Path(path).exists():
        for line in open(path, encoding="utf-8"):
            p = line.rstrip("\n").split("\t")
            if len(p) >= 3:
                got[p[0]] = p[2]
    return got


def correct(out, answers, fold):
    if out is None:
        return False
    if fold:
        return any(out.lower() == a.lower() for a in answers)
    return out in answers


# ---- 材料 ----
def blocks(path):
    """印（U+0004 名前:番号）で区切った行の塊。番号 → 行の一覧"""
    out, cur = {}, None
    if not Path(path).exists():
        return out
    for line in open(path, encoding="utf-8", errors="replace"):
        line = line.rstrip("\n")
        if line.startswith("\x04"):
            mark = line[1:]
            cur = int(mark.split(":")[1]) if ":" in mark else None
            if cur is not None:
                out[cur] = []
        elif cur is not None and line:
            out[cur].append(line)
    return out


def parse_dump(line):
    return [s.split("\t") for s in line.split("\x01")]


def parse_features(line):
    line = line.split("\x03")[0]
    segs = []
    for s in line.split("\x01"):
        parts = s.split("\t")
        cands = []
        for c in parts[1:]:
            f = c.split("\x02")
            try:
                cands.append((f[0], int(f[1])))
            except (IndexError, ValueError):
                cands.append((f[0], 0))
        segs.append((parts[0], cands))
    return segs


def kbest(segs, n, k=16):
    """文節ごとの上位k候補のコストの和の小さい順に、違う表記の文を n 個"""
    lists = [sorted(c[:k], key=lambda x: x[1]) for _, c in segs]
    if not lists or any(not l for l in lists):
        return []
    start = tuple(0 for _ in lists)
    heap = [(sum(l[0][1] for l in lists), start)]
    seen_idx, out, seen_text = {start}, [], set()
    while heap and len(out) < n and len(seen_idx) < 20000:
        cost, idx = heapq.heappop(heap)
        text = "".join(lists[i][j][0] for i, j in enumerate(idx))
        if text not in seen_text:
            seen_text.add(text)
            out.append(text)
        for i in range(len(idx)):
            if idx[i] + 1 < len(lists[i]):
                nxt = idx[:i] + (idx[i] + 1,) + idx[i + 1:]
                if nxt not in seen_idx:
                    seen_idx.add(nxt)
                    heapq.heappush(heap, (cost - lists[i][idx[i]][1] + lists[i][idx[i] + 1][1], nxt))
    return out


def whole_list(line):
    reading, _, js = line.partition("\t")
    try:
        arr = json.loads(js)
    except json.JSONDecodeError:
        return reading, []
    n = len(reading)
    out = []
    for c in arr:
        text = c.get("text", "")
        if text and c.get("correspondingCount") == n and text not in out:
            out.append(text)
    return reading, out


def reachable(segs, answer, k):
    ends = {0}
    for cands in segs:
        nxt = set()
        for at in ends:
            for c in cands[:k]:
                if c and answer.startswith(c, at):
                    nxt.add(at + len(c))
        if not nxt:
            return False
        ends = nxt
    return len(answer) in ends


def material(mdir, tdir, bdir):
    """文ごとの記録: dict(name, i, romaji, answers, fold, left, base, noai, segs, combos, whole, reading)"""
    T = tests(tdir)
    recs = []
    for name, items in T.items():
        base = load_out(Path(bdir) / BASE_FILE[name])
        noai = load_out(Path(mdir) / f"{name}.tsv")
        dump = blocks(Path(mdir) / f"dump-{name}.txt")
        feat = blocks(Path(mdir) / f"features-{name}.txt")
        whole = blocks(Path(mdir) / f"whole-{name}.txt")
        for i, (romaji, answers, left, fold) in enumerate(items, 1):
            segs = parse_dump(dump[i][-1]) if dump.get(i) else None
            reading = "".join(s[0] for s in segs) if segs else ""
            fsegs = parse_features(feat[i][-1]) if feat.get(i) else None
            w = []
            for line in reversed(whole.get(i, [])):
                r, lst = whole_list(line)
                if r == reading:
                    w = lst
                    break
            recs.append(dict(name=name, i=i, romaji=romaji, answers=answers, fold=fold, left=left,
                             base=base.get(romaji), noai=noai.get(romaji),
                             segs=[s[1:] for s in segs] if segs else None, reading=reading,
                             combos=kbest(fsegs, 32) if fsegs else [], whole=w))
    return recs


def norm(text):
    """変換の後の決まった直し（半角の ? ! を全角にする）を、候補の側にも当てる"""
    return text.replace("?", "？").replace("!", "！") if text else text


def in_list(lst, answers, fold):
    ans = [norm(a) for a in answers]
    return any(correct(norm(x), ans, fold) for x in lst)


def ceilings(r):
    # どの集まりにも、人工知能なしの出力（生成なしの変換の結果）を入れる
    a, f = [norm(x) for x in r["answers"]], r["fold"]
    noai = in_list([r["noai"]], a, f)
    segs = [[norm(c) for c in s] for s in r["segs"]] if r["segs"] else None
    seg = {k: noai or (bool(segs) and any(
        reachable(segs, x, k) or (f and reachable([[c.lower() for c in s] for s in segs], x.lower(), k)) for x in a))
        for k in (4, 8, 16)}
    return {"seg4": seg[4], "seg8": seg[8], "seg16": seg[16],
            "combo8": noai or in_list(r["combos"][:8], a, f), "combo32": noai or in_list(r["combos"][:32], a, f),
            "dict8": noai or in_list(r["whole"][:8], a, f), "dict32": noai or in_list(r["whole"][:32], a, f)}


COLS = ["seg4", "seg8", "seg16", "combo8", "combo32", "dict8", "dict32"]


def candidates(r):
    out = []
    for x in [r["noai"]] + r["whole"][:32] + r["combos"][:32] + [r["base"]] + r["answers"][:1]:
        x = norm(x)
        if x and x not in out:
            out.append(x)
    return out[:64]


def cmd_jobs(mdir, tdir, bdir, out, bench_dir=None):
    recs = material(mdir, tdir, bdir)
    n = 0
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        for r in recs:
            if not r["reading"]:
                continue
            cands = candidates(r)
            f.write("\t".join([f"{r['name']}:{r['i']}", build_prompt(r["reading"], r["left"])]
                              + [model_text(c) for c in cands]) + "\n")
            n += 1
    print(f"採点の材料: {n} 文")
    if bench_dir:
        # 時間の比べ: 日本語だけの400文の先頭150文とウィキペディアの文150文で、候補 K 個（辞書の順、足りなければ組）
        Path(bench_dir).mkdir(parents=True, exist_ok=True)
        pick = [r for r in recs if r["name"] == "ja400" and r["reading"]][:150] + \
               [r for r in recs if r["name"] == "wikiw1" and r["reading"]][:150]
        for k in (1, 2, 4, 8, 16, 32):
            with open(Path(bench_dir) / f"bench-{k}.tsv", "w", encoding="utf-8", newline="\n") as f:
                m = 0
                for r in pick:
                    cands = []
                    for x in [norm(y) for y in r["whole"] + r["combos"]]:
                        if x not in cands:
                            cands.append(x)
                    if len(cands) < k:
                        continue
                    f.write("\t".join([f"{r['name']}:{r['i']}", build_prompt(r["reading"], r["left"])]
                                      + [model_text(c) for c in cands[:k]]) + "\n")
                    m += 1
            print(f"時間の比べ K={k}: {m} 文")


def load_scores(sdir):
    scores = {}
    for p in sorted(Path(sdir).glob("**/score-*.tsv")):
        for line in open(p, encoding="utf-8"):
            f = line.rstrip("\n").split("\t")
            if len(f) >= 6:
                scores[f[0]] = [float(x) for x in f[5:]]
    return scores


def cmd_report(mdir, tdir, bdir, sdir=None):
    recs = material(mdir, tdir, bdir)
    scores = load_scores(sdir) if sdir else {}
    by = {}
    for r in recs:
        by.setdefault(r["name"], []).append(r)
    print("## 上限（正解の文を、生成なしの候補だけから組めるか）\n")
    print("| 試験 | 文 | 本線 v5 正解 | 人工知能なし 正解 | 文節4 | 文節8 | 文節16 | 組8 | 組32 | 辞書8 | 辞書全部 | 全部の和 | 和∪本線 | 生成でしか出ない | 記録なし |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    tot = None
    gen_only_list = []
    for label, names in GROUPS:
        rs = [r for n in names for r in by.get(n, [])]
        if not rs:
            continue
        row = {"n": len(rs), "base": 0, "noai": 0, **{c: 0 for c in COLS}, "union": 0, "union_base": 0, "gen": 0, "miss": 0}
        for r in rs:
            a, f = r["answers"], r["fold"]
            b = correct(r["base"], a, f)
            row["base"] += b
            row["noai"] += correct(r["noai"], a, f)
            if not r["segs"]:
                row["miss"] += 1
            c = ceilings(r)
            for k in COLS:
                row[k] += c[k]
            u = c["seg16"] or c["combo32"] or c["dict32"]
            row["union"] += u
            row["union_base"] += u or b
            if b and not u:
                row["gen"] += 1
                gen_only_list.append(f"  {label}: {r['base']}（人工知能なし: {r['noai']}）")
        tot = row if tot is None else {k: tot[k] + row[k] for k in tot}
        print(f"| {label} | {row['n']} | {row['base']} | {row['noai']} | " + " | ".join(str(row[c]) for c in COLS)
              + f" | {row['union']} | {row['union_base']} | {row['gen']} | {row['miss']} |")
    print(f"| 合計 | {tot['n']} | {tot['base']} | {tot['noai']} | " + " | ".join(str(tot[c]) for c in COLS)
          + f" | {tot['union']} | {tot['union_base']} | {tot['gen']} | {tot['miss']} |")
    print("\n生成でしか出ない文（本線は正解、生成なしの候補のどれからも組めない）の例:")
    print("\n".join(gen_only_list[:40]))
    if not scores:
        return
    print("\n## (a) 今の zenz v5 で候補を採点し、対数確率の最大を選んだときの正解の数（机上）\n")
    sets = [("辞書8", lambda r: r["whole"][:8]), ("辞書全部", lambda r: r["whole"][:32]),
            ("組8", lambda r: r["combos"][:8]), ("組32", lambda r: r["combos"][:32]),
            ("辞書全部∪組32", lambda r: r["whole"][:32] + r["combos"][:32]),
            ("辞書全部∪組32∪本線", lambda r: r["whole"][:32] + r["combos"][:32] + ([r["base"]] if r["base"] else []))]
    print("| 試験 | 文 | 本線 v5 | " + " | ".join(f"{s}（上限）" for s, _ in sets) + " | 正解を足したとき正解が最高点 |")
    print("|---|---:|---:|" + "---:|" * len(sets) + "---:|")
    tot = None
    for label, names in GROUPS:
        rs = [r for n in names for r in by.get(n, []) if f"{r['name']}:{r['i']}" in scores]
        if not rs:
            continue
        row = {"n": len(rs), "base": 0, **{s: 0 for s, _ in sets}, **{s + "u": 0 for s, _ in sets}, "gold": 0}
        for r in rs:
            a, f = r["answers"], r["fold"]
            sc = dict(zip(candidates(r), scores[f"{r['name']}:{r['i']}"]))
            a = [norm(x) for x in a]
            row["base"] += correct(r["base"], a, f)
            for s, fn in sets:
                lst = [norm(x) for x in [r["noai"]] + fn(r) if norm(x) in sc]
                if lst:
                    best = max(lst, key=lambda x: sc[x])
                    row[s] += correct(best, a, f)
                    row[s + "u"] += in_list(lst, a, f)
            allc = list(sc)
            if allc and norm(r["answers"][0]) in sc:
                row["gold"] += correct(max(allc, key=lambda x: sc[x]), a, f)
        tot = row if tot is None else {k: tot[k] + row[k] for k in tot}
        print(f"| {label} | {row['n']} | {row['base']} | " + " | ".join(f"{row[s]}（{row[s + 'u']}）" for s, _ in sets)
              + f" | {row['gold']} |")
    print(f"| 合計 | {tot['n']} | {tot['base']} | " + " | ".join(f"{tot[s]}（{tot[s + 'u']}）" for s, _ in sets)
          + f" | {tot['gold']} |")


def cmd_bench(bdir, first=None):
    """tools/jev_score.cpp の bench-t<スレッド>-k<候補の数>.tsv から、方式ごとの時間の表（first: 先頭の文の数だけ）"""
    rows = {}
    for p in Path(bdir).glob("bench-t*-k*.tsv"):
        m = re.match(r"bench-t(\d+)-k(\d+)\.tsv", p.name)
        t, k = int(m.group(1)), int(m.group(2))
        ids = []
        for line in open(p, encoding="utf-8"):
            f = line.rstrip("\n").split("\t")
            if f[0] not in ids:
                ids.append(f[0])
            if first and len(ids) > int(first):
                break
            if len(f) >= 5 and int(f[3]) > 0:
                rows.setdefault((t, k, f[1]), []).append((float(f[4]), int(f[3]), int(f[2])))
    modes = ["trie", "flat", "seq", "full"]
    print("| スレッド | 候補 K | 文 | 問いの語片 平均 | " + " | ".join(f"{m} 平均 ms（中央値、90%点、評価した語片）" for m in modes) + " |")
    print("|---:|---:|---:|---:|" + "---|" * len(modes))
    for t, k in sorted({(t, k) for t, k, _ in rows}):
        cells = []
        n = p0 = 0
        for m in modes:
            v = sorted(rows.get((t, k, m), []))
            if not v:
                cells.append("-")
                continue
            ms = sorted(x[0] for x in v)
            n, p0 = len(v), sum(x[2] for x in v) / len(v)
            cells.append(f"{sum(ms) / len(ms):.1f}（{ms[len(ms) // 2]:.1f}、{ms[int(len(ms) * 0.9)]:.1f}、{sum(x[1] for x in v) / len(v):.0f}）")
        print(f"| {t} | {k} | {n} | {p0:.1f} | " + " | ".join(cells) + " |")


def main():
    cmd = sys.argv[1]
    if cmd == "bench":
        cmd_bench(sys.argv[2], *(sys.argv[3:4] or [None]))
    elif cmd == "jobs":
        cmd_jobs(*sys.argv[2:6], *(sys.argv[6:7] or [None]))
    elif cmd == "report":
        cmd_report(*sys.argv[2:5], *(sys.argv[5:6] or [None]))
    else:
        raise SystemExit("jobs か report")


if __name__ == "__main__":
    main()
