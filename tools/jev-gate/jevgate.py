"""判定の門の模型: 「この変換で人工知能の生成（all_zenzai）が要るか」を決める、文字単位の小さな符号化器。

入力  前の文の終わり（24字まで）、読み（ひらがな）、生成なしの候補の上位 k 個（人工知能なしの出力、辞書の文全体、
      Mozc の組の順）。1本の並びにつなぎ、候補どうしは見えないようにする（Jev と同じ形。各候補は
      「前の文・読み」と自分だけを見る）。
出力  gate   4つの確率（生成が要る度合い）
              0 need      生成なしの候補の zenz の最大が v5 の出力と違う（全部の候補から。教師の答え）
              1 need_k    入力の上位 k 個の中の zenz の最大が v5 の出力と違う
              2 need_top1 人工知能なしの出力が v5 の出力と違う
              3 harm_k    v5 は正解で、上位 k 個の中の zenz の最大は不正解（生成を省くと損をする）
      score  候補ごとの点（zenz の点の蒸留。最大の候補との差を 10 で割って -3 から 0 に切ったもの）
      item   答えを選ぶ頭 (b)  候補 k 個と v5 の出力（最後の枠）の、それぞれが正解である度合い（ロジット）
      pair   答えを選ぶ頭 (a)  v5 の出力と、生成なしの候補の一番（cands[0]）の、どちらが正しいか（v5 が正しいほうのロジット）
      v5 の出力の枠は、前置きにも候補にも見えない（他の枠から見えない）ので、枠を付けても付けなくても
      門・score の出力は変わらない。item・pair だけが v5 の出力を使う（生成のあとにしか使えない）。
学習データの記録は tools/jev_gate_build.py の書式。使い方は tools/jev-gate/train.ipynb と docs/jev-gate.md。

  python tools/jev-gate/jevgate.py train   --records train.jsonl.gz --out run1 [--k 4 --epochs 8 ...]
  python tools/jev-gate/jevgate.py predict --ckpt run1/final.pt --records test.jsonl.gz --out pred.tsv
  python tools/jev-gate/jevgate.py export  --ckpt run1/final.pt --out run1/jevgate.bin
  python tools/jev-gate/jevgate.py count   --k 4 --d 256 --layers 4
"""
import argparse
import gzip
import hashlib
import json
import math
import os
import pickle
import random
import struct
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

PAD, UNK, CLS, SEP, EOC = 0, 1, 2, 3, 4
N_SPECIAL = 5
SRC_ID = {"n": 1, "w": 2, "c": 3}
TYPE_SPECIAL, TYPE_PREV, TYPE_READ, TYPE_CAND = 0, 1, 2, 3
MAX_PREFIX_POS = 128
MAX_CAND_POS = 64
MAX_RANK = 16
V5_SRC = 4  # v5 の出力の枠の src 番号（0 空き、1〜3 候補の由来）
FEATURE_TAG = "sel1"  # 特徴の一時ファイルの版（教師を足したときに上げる）
GATE_NAMES = ["need", "need_k", "need_top1", "harm_k"]
# 教師 need（全部の候補から決めた「生成が要る」）は、生成なしの候補の先頭のこの数だけで決め直す。
# 材料の新しい記録は採点の時点で16個までだが、古い記録（最大24個）と同じ定義にそろえるため
NEED_AVAIL = 16
GATE_WEIGHTS = [1.0, 1.0, 0.5, 0.5]
MAGIC = b"JEVG"
VERSION = 2

DEFAULT_CFG = dict(d=256, layers=4, heads=4, ffn=1024, dropout=0.1, max_vocab=4096, k=4,
                   prev_chars=24, read_chars=64, cand_chars=40, gate_hidden=256)


# ---------------------------------------------------------------- 記録と語彙
def open_text(path):
    path = str(path)
    return gzip.open(path, "rt", encoding="utf-8") if path.endswith(".gz") else open(path, encoding="utf-8")


def iter_records(paths, limit=None):
    n = 0
    for p in ([paths] if isinstance(paths, (str, Path)) else paths):
        with open_text(p) as f:
            for line in f:
                if line.strip():
                    yield json.loads(line)
                    n += 1
                    if limit and n >= limit:
                        return


def last_line_tail(text, n):
    return text.split("\n")[-1][-n:] if n > 0 else ""


class Vocab:
    def __init__(self, chars):
        self.chars = list(chars)
        self.index = {c: i + N_SPECIAL for i, c in enumerate(self.chars)}

    def __len__(self):
        return N_SPECIAL + len(self.chars)

    def encode(self, text):
        return [self.index.get(c, UNK) for c in text]


def build_vocab(paths, cfg, limit=200000):
    count = {}
    for rec in iter_records(paths, limit):
        texts = [last_line_tail(rec["prev"], cfg["prev_chars"]), rec["reading"][:cfg["read_chars"]]]
        texts += [c[0][:cfg["cand_chars"]] for c in rec["cands"][:max(cfg["k"], 4)]]
        for t in texts:
            for ch in t:
                count[ch] = count.get(ch, 0) + 1
    chars = [c for c, n in sorted(count.items(), key=lambda x: (-x[1], x[0])) if n >= 2]
    return Vocab(chars[:cfg["max_vocab"] - N_SPECIAL])


def is_ok(text, answers, fold):
    if fold:
        return text.lower() in [a.lower() for a in answers]
    return text in answers


class Sample:
    """1文ぶんの入力と教師。配列はすべて短い整数の列"""
    __slots__ = ("id", "prefix", "ptype", "cands", "csrc", "gap", "best", "labels", "cand_ok", "v5_ok", "nc",
                 "v5tok", "same", "pair_y", "pair_m", "v5gap")


def featurize(rec, vocab, cfg):
    k = cfg["k"]
    prev = vocab.encode(last_line_tail(rec["prev"], cfg["prev_chars"]))
    read = vocab.encode(rec["reading"][:cfg["read_chars"]])
    s = Sample()
    s.id = rec["id"]
    s.prefix = np.array([CLS] + prev + [SEP] + read + [SEP], dtype=np.int16)
    s.ptype = np.array([TYPE_SPECIAL] + [TYPE_PREV] * len(prev) + [TYPE_SPECIAL] + [TYPE_READ] * len(read)
                       + [TYPE_SPECIAL], dtype=np.int8)
    cands = rec["cands"][:k]
    s.nc = len(cands)
    s.cands = [np.array(vocab.encode(c[0][:cfg["cand_chars"]]) + [EOC], dtype=np.int16) for c in cands]
    s.csrc = [SRC_ID.get(c[2][:1], 3) if c[2] else 3 for c in cands]
    answers, fold = rec["answers"], rec.get("fold", False)
    s.cand_ok = np.array([int(is_ok(c[0], answers, fold)) for c in cands], dtype=np.int8)
    scores = np.array([c[1] for c in cands], dtype=np.float32)
    if len(cands):
        s.best = int(np.argmax(scores))
        s.gap = np.clip((scores - scores.max()) / 10.0, -3.0, 0.0).astype(np.float32)
        sel = cands[s.best][0]
    else:
        s.best = -1
        s.gap = np.zeros(0, dtype=np.float32)
        sel = rec["noai"]
    v5_ok = int(is_ok(rec["v5"], answers, fold))
    # v5 の出力の枠（候補と同じ形。生成のあとにしか入力できない）と、答えを選ぶ頭の教師
    s.v5tok = np.array(vocab.encode(rec["v5"][:cfg["cand_chars"]]) + [EOC], dtype=np.int16)
    s.same = np.array([int(np.array_equal(c, s.v5tok)) for c in s.cands], dtype=np.float32)
    # v5 の出力の zenz の点も、候補と同じ向きで蒸留する（候補の最大との差を 10 で割る。v5 のほうが高ければ正になる）
    v5s = rec.get("v5s")
    cs_max = float(max((c[1] for c in cands), default=0.0))
    s.v5gap = float(np.clip((v5s - cs_max) / 10.0, -3.0, 3.0)) if (isinstance(v5s, (int, float)) and cands) else float("nan")
    s.pair_y = v5_ok
    s.pair_m = int(s.nc > 0 and v5_ok != int(s.cand_ok[0]))  # 片方だけ正解のときだけ教師にする
    sel_ok = int(is_ok(sel, answers, fold))
    s.v5_ok = v5_ok
    need = rec["need"]
    avail = [c for c in rec["cands"] if set(c[2]) & set("nwc")][:NEED_AVAIL]
    if avail:
        need = int(max(avail, key=lambda c: c[1])[0] != rec["v5"])
    s.labels = np.array([need, int(sel != rec["v5"]), rec["need_top1"], int(v5_ok and not sel_ok)],
                        dtype=np.float32)
    return s


def featurize_all(paths, vocab, cfg, limit=None, log=True):
    out = []
    t0 = time.time()
    for i, rec in enumerate(iter_records(paths, limit)):
        out.append(featurize(rec, vocab, cfg))
        if log and (i + 1) % 50000 == 0:
            print(f"  {i + 1} 文 ({time.time() - t0:.0f} 秒)", flush=True)
    return out


def split_valid(samples, valid_share=0.02):
    """id の指紋で決まる確かめ用（同じ id はいつも同じ側）"""
    train, valid = [], []
    for s in samples:
        h = int(hashlib.md5(s.id.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
        (valid if h < valid_share else train).append(s)
    return train, valid


# ---------------------------------------------------------------- 束ねる
def collate(batch, k, device="cpu", with_v5=True):
    """並びの形: [前置き（先頭、前の文、区切り、読み、区切り）][候補1の枠]…[候補kの枠][v5 の出力の枠]。枠の長さは束の中の最長にそろえる。
    with_v5=False なら v5 の出力の枠を付けない（生成の前の門の入力。門・score の出力は付けても変わらない）"""
    B = len(batch)
    S = k + 1 if (k > 0 and with_v5) else k
    Lp = max(len(s.prefix) for s in batch)
    Lc = max([len(c) for s in batch for c in s.cands] + ([len(s.v5tok) for s in batch] if S > k else []) + [1])
    T = Lp + S * Lc
    tok = np.zeros((B, T), dtype=np.int64)
    typ = np.zeros((B, T), dtype=np.int64)
    pos = np.zeros((B, T), dtype=np.int64)
    rank = np.zeros((B, T), dtype=np.int64)
    src = np.zeros((B, T), dtype=np.int64)
    seg = np.zeros((B, T), dtype=np.int64)
    valid = np.zeros((B, T), dtype=bool)
    cvalid = np.zeros((B, k), dtype=bool)
    gap = np.zeros((B, k), dtype=np.float32)
    best = np.full(B, -1, dtype=np.int64)
    ok = np.zeros((B, S), dtype=np.int64)
    same = np.zeros((B, S), dtype=np.float32)
    pair_y = np.zeros(B, dtype=np.float32)
    pair_m = np.zeros(B, dtype=np.float32)
    v5gap = np.zeros(B, dtype=np.float32)
    v5gap_m = np.zeros(B, dtype=np.float32)
    for b, s in enumerate(batch):
        n = len(s.prefix)
        tok[b, :n] = s.prefix
        typ[b, :n] = s.ptype
        pos[b, :n] = np.minimum(np.arange(n), MAX_PREFIX_POS - 1)
        valid[b, :n] = True
        for j, c in enumerate(s.cands):
            a = Lp + j * Lc
            m = len(c)
            tok[b, a:a + m] = c
            typ[b, a:a + m] = TYPE_CAND
            pos[b, a:a + m] = np.minimum(np.arange(m), MAX_CAND_POS - 1)
            rank[b, a:a + m] = min(j, MAX_RANK - 1)
            src[b, a:a + m] = s.csrc[j]
            seg[b, a:a + Lc] = j + 1
            valid[b, a:a + m] = True
            cvalid[b, j] = True
        if S > k:
            a = Lp + k * Lc
            m = len(s.v5tok)
            tok[b, a:a + m] = s.v5tok
            typ[b, a:a + m] = TYPE_CAND
            pos[b, a:a + m] = np.minimum(np.arange(m), MAX_CAND_POS - 1)
            rank[b, a:a + m] = min(k, MAX_RANK - 1)
            src[b, a:a + m] = V5_SRC
            seg[b, a:a + Lc] = k + 1
            valid[b, a:a + m] = True
            ok[b, k] = s.v5_ok
            same[b, k] = 1.0
        gap[b, :s.nc] = s.gap
        ok[b, :s.nc] = s.cand_ok
        same[b, :s.nc] = s.same
        best[b] = s.best
        pair_y[b] = s.pair_y
        pair_m[b] = s.pair_m
        if s.v5gap == s.v5gap:  # nan でない
            v5gap[b], v5gap_m[b] = s.v5gap, 1.0
    labels = np.stack([s.labels for s in batch])
    v5_ok = np.array([s.v5_ok for s in batch], dtype=np.int64)
    ivalid = np.concatenate([cvalid, np.ones((B, 1), dtype=bool)], axis=1) if S > k else cvalid
    t = lambda x: torch.from_numpy(x).to(device)  # noqa: E731
    return dict(tok=t(tok), typ=t(typ), pos=t(pos), rank=t(rank), src=t(src), seg=t(seg), valid=t(valid),
                cvalid=t(cvalid), ivalid=t(ivalid), gap=t(gap), best=t(best), labels=t(labels), cand_ok=t(ok), v5_ok=t(v5_ok),
                same=t(same), pair_y=t(pair_y), pair_m=t(pair_m), v5gap=t(v5gap), v5gap_m=t(v5gap_m), Lp=Lp, Lc=Lc, S=S)


def to_device(b, device):
    return {k: (v.to(device, non_blocking=True) if torch.is_tensor(v) else v) for k, v in b.items()}


def prefetch(items, fn, depth=6):
    """束ねる仕事を別の流れで先に進める（GPU を待たせない）"""
    import queue
    import threading
    q = queue.Queue(depth)
    end = object()

    def work():
        for it in items:
            q.put(fn(it))
        q.put(end)

    threading.Thread(target=work, daemon=True).start()
    while True:
        x = q.get()
        if x is end:
            return
        yield x


def make_batches(samples, batch_size, seed, epoch):
    """長さの近い文を同じ束にする（束の順は seed と epoch で決まる）"""
    rng = random.Random(seed * 1000003 + epoch)
    idx = list(range(len(samples)))
    rng.shuffle(idx)
    chunk = batch_size * 50
    out = []
    for i in range(0, len(idx), chunk):
        part = sorted(idx[i:i + chunk], key=lambda j: len(samples[j].prefix) + sum(len(c) for c in samples[j].cands))
        out += [part[b:b + batch_size] for b in range(0, len(part), batch_size)]
    rng.shuffle(out)
    return [b for b in out if len(b) == batch_size or len(out) == 1] or out


# ---------------------------------------------------------------- 模型
class Block(nn.Module):
    def __init__(self, d, heads, ffn, drop):
        super().__init__()
        self.heads = heads
        self.ln1 = nn.LayerNorm(d)
        self.qkv = nn.Linear(d, 3 * d)
        self.proj = nn.Linear(d, d)
        self.ln2 = nn.LayerNorm(d)
        self.fc1 = nn.Linear(d, ffn)
        self.fc2 = nn.Linear(ffn, d)
        self.drop = nn.Dropout(drop)

    def forward(self, x, mask):
        B, T, D = x.shape
        q, k, v = self.qkv(self.ln1(x)).view(B, T, 3, self.heads, D // self.heads).permute(2, 0, 3, 1, 4)
        a = F.scaled_dot_product_attention(q, k, v, attn_mask=mask)
        x = x + self.drop(self.proj(a.transpose(1, 2).reshape(B, T, D)))
        return x + self.drop(self.fc2(F.gelu(self.fc1(self.ln2(x)), approximate="tanh")))


class JevGate(nn.Module):
    def __init__(self, vocab_size, cfg):
        super().__init__()
        self.cfg = dict(cfg)
        d, k = cfg["d"], cfg["k"]
        self.k = k
        self.tok = nn.Embedding(vocab_size, d)
        self.typ = nn.Embedding(4, d)
        self.pos_prefix = nn.Embedding(MAX_PREFIX_POS, d)
        self.pos_cand = nn.Embedding(MAX_CAND_POS, d)
        self.rank = nn.Embedding(MAX_RANK, d)
        self.src = nn.Embedding(5, d)
        self.blocks = nn.ModuleList([Block(d, cfg["heads"], cfg["ffn"], cfg["dropout"]) for _ in range(cfg["layers"])])
        self.ln_f = nn.LayerNorm(d)
        self.s1 = nn.Linear(d, d // 2)
        self.s2 = nn.Linear(d // 2, 1)
        self.g1 = nn.Linear(3 * d + 3, cfg["gate_hidden"])
        self.g2 = nn.Linear(cfg["gate_hidden"], len(GATE_NAMES))
        # 答えを選ぶ頭。i: 枠ごとの正解の度合い（入力 cls、その枠、v5 の枠、補助の数 7 個）、p: v5 と候補の一番の比べ（cls、v5 の枠、候補1の枠、補助 6 個）
        self.i1 = nn.Linear(3 * d + 7, cfg["gate_hidden"])
        self.i2 = nn.Linear(cfg["gate_hidden"], 1)
        self.p1 = nn.Linear(3 * d + 6, cfg["gate_hidden"])
        self.p2 = nn.Linear(cfg["gate_hidden"], 1)
        for m in self.modules():
            if isinstance(m, (nn.Linear, nn.Embedding)):
                nn.init.normal_(m.weight, std=0.02)
                if isinstance(m, nn.Linear):
                    nn.init.zeros_(m.bias)

    def forward(self, b):
        d, k = self.cfg["d"], self.k
        Lp, Lc = b["Lp"], b["Lc"]
        is_cand = (b["typ"] == TYPE_CAND)
        pos = torch.where(is_cand.unsqueeze(-1), self.pos_cand(b["pos"].clamp(max=MAX_CAND_POS - 1)), self.pos_prefix(b["pos"]))
        x = self.tok(b["tok"]) + self.typ(b["typ"]) + pos + self.rank(b["rank"]) * is_cand.unsqueeze(-1) \
            + self.src(b["src"])
        seg, valid = b["seg"], b["valid"]
        allowed = valid.unsqueeze(1) & ((seg.unsqueeze(1) == 0) | (seg.unsqueeze(1) == seg.unsqueeze(2)))
        mask = allowed.unsqueeze(1)
        for blk in self.blocks:
            x = blk(x, mask)
        h = self.ln_f(x)
        B = h.shape[0]
        cls = h[:, 0]
        if k == 0:
            zero = torch.zeros_like(cls)
            g_in = torch.cat([cls, zero, zero, torch.zeros(B, 3, device=h.device, dtype=h.dtype)], dim=-1)
            return dict(gate=self.g2(F.gelu(self.g1(g_in), approximate="tanh")), score=None, best=None, item=None, pair=None, score_v5=None)
        S = b["S"]
        hc = h[:, Lp:].reshape(B, S, Lc, d)
        vc = valid[:, Lp:].reshape(B, S, Lc).unsqueeze(-1).to(h.dtype)
        pooled_all = (hc * vc).sum(2) / vc.sum(2).clamp(min=1)
        pooled = pooled_all[:, :k]
        score_all = self.s2(F.gelu(self.s1(pooled_all), approximate="tanh")).squeeze(-1)
        score = score_all[:, :k]
        cv = b["cvalid"]
        masked = score.masked_fill(~cv, -1e4)
        best = masked.argmax(-1)
        ar = torch.arange(B, device=h.device)
        c_best = pooled[ar, best]
        c0 = pooled[:, 0]
        top2 = masked.topk(min(2, k), dim=-1).values
        margin = (top2[:, 0] - top2[:, 1]) if k >= 2 else torch.zeros_like(top2[:, 0])
        margin = torch.where(cv.sum(-1) >= 2, margin, torch.ones_like(margin))
        length_all = vc.squeeze(-1).sum(2) / 20.0
        length = length_all[ar, best]
        g_in = torch.cat([cls, c_best, c0, torch.stack([masked[ar, best], margin, length], dim=-1).to(h.dtype)], dim=-1)
        out = dict(gate=self.g2(F.gelu(self.g1(g_in), approximate="tanh")), score=score, best=best, item=None, pair=None, score_v5=None)
        if S > k:  # v5 の出力の枠がある（生成のあと）
            pv5 = pooled_all[:, k]
            sc_v5 = score_all[:, k]
            out["score_v5"] = sc_v5
            sc_all = torch.cat([score.masked_fill(~cv, 0.0), sc_v5.unsqueeze(1)], dim=1)
            sc_max = masked[ar, best].unsqueeze(1).expand(B, S)
            is_v5 = torch.zeros(B, S, device=h.device, dtype=h.dtype)
            is_v5[:, k] = 1.0
            same = b["same"].to(h.dtype)
            len_v5 = length_all[:, k].unsqueeze(1).expand(B, S)
            ex = torch.stack([sc_all, sc_max, sc_v5.unsqueeze(1).expand(B, S), length_all, len_v5, same, is_v5], dim=-1).to(h.dtype)
            i_in = torch.cat([cls.unsqueeze(1).expand(B, S, d), pooled_all, pv5.unsqueeze(1).expand(B, S, d), ex], dim=-1)
            item = self.i2(F.gelu(self.i1(i_in), approximate="tanh")).squeeze(-1)
            ex_p = torch.stack([masked[ar, 0].to(h.dtype), sc_v5.to(h.dtype), masked[ar, best].to(h.dtype), length_all[:, 0],
                                length_all[:, k], same[:, 0]], dim=-1)
            p_in = torch.cat([cls, pv5, c0, ex_p], dim=-1)
            out["item"] = item
            out["pair"] = self.p2(F.gelu(self.p1(p_in), approximate="tanh")).squeeze(-1)
        return out


def count_params(model):
    return sum(p.numel() for p in model.parameters())


def loss_fn(out, b, sel_weight=1.0):
    gate = out["gate"].float()
    w = torch.tensor(GATE_WEIGHTS, device=gate.device)
    l_gate = (F.binary_cross_entropy_with_logits(gate, b["labels"], reduction="none") * w).sum(-1).mean()
    if out["score"] is None:
        return l_gate, dict(gate=l_gate.item(), reg=0.0, rank=0.0, sel=0.0)
    score, cv = out["score"].float(), b["cvalid"]
    reg = (F.huber_loss(score, b["gap"], reduction="none", delta=0.5) * cv).sum() / cv.sum().clamp(min=1)
    has = (b["best"] >= 0)
    ce = F.cross_entropy(score.masked_fill(~cv, -1e4)[has], b["best"][has]) if has.any() else score.sum() * 0
    sel = score.sum() * 0
    if out["item"] is not None and sel_weight > 0:
        item, iv, ok = out["item"].float(), b["ivalid"], b["cand_ok"].float()
        bce = (F.binary_cross_entropy_with_logits(item, ok, reduction="none") * iv).sum() / iv.sum().clamp(min=1)
        t = ok * iv
        ts = t.sum(-1)
        hs = ts > 0
        logp = F.log_softmax(item.masked_fill(~iv, -1e4), dim=-1)
        lce = -((t / ts.clamp(min=1).unsqueeze(-1)) * logp).sum(-1)
        lce = lce[hs].mean() if hs.any() else item.sum() * 0
        pm = b["pair_m"]
        lp = (F.binary_cross_entropy_with_logits(out["pair"].float(), b["pair_y"], reduction="none") * pm).sum() / pm.sum().clamp(min=1)
        vm = b["v5gap_m"]
        lv = (F.huber_loss(out["score_v5"].float(), b["v5gap"], reduction="none", delta=0.5) * vm).sum() / vm.sum().clamp(min=1)
        sel = 0.5 * bce + 0.5 * lce + lp + lv
    return l_gate + reg + 0.5 * ce + sel_weight * sel, dict(gate=l_gate.item(), reg=reg.item(), rank=ce.item(), sel=sel.item())


# ---------------------------------------------------------------- 評価
def auc(y, p):
    y, p = np.asarray(y), np.asarray(p)
    pos, neg = (y == 1).sum(), (y == 0).sum()
    if pos == 0 or neg == 0:
        return float("nan")
    order = np.argsort(p, kind="mergesort")
    ranks = np.empty(len(p))
    ranks[order] = np.arange(1, len(p) + 1)
    return float((ranks[y == 1].sum() - pos * (pos + 1) / 2) / (pos * neg))


@torch.no_grad()
def run_model(model, samples, device, batch_size=256, autocast=None):
    """各文の出力（確率 4 つ、門の選んだ候補、候補の点、枠ごとの正解の度合い、v5 と候補の一番の比べ）を文の順で返す"""
    model.eval()
    k = model.k
    probs, bests, scores, items, pairs = [], [], [], [], []
    order = sorted(range(len(samples)), key=lambda i: len(samples[i].prefix) + sum(len(c) for c in samples[i].cands))
    for a in range(0, len(order), batch_size):
        idx = order[a:a + batch_size]
        b = collate([samples[i] for i in idx], k, device)
        with torch.autocast(device_type=device.type, dtype=autocast, enabled=autocast is not None):
            out = model(b)
        n = len(idx)
        probs.append(torch.sigmoid(out["gate"].float()).cpu().numpy())
        bests.append(out["best"].cpu().numpy() if out["best"] is not None else np.zeros(n, dtype=np.int64))
        scores.append(out["score"].float().cpu().numpy() if out["score"] is not None else np.zeros((n, 0)))
        items.append(out["item"].float().cpu().numpy() if out["item"] is not None else np.zeros((n, 0)))
        pairs.append(out["pair"].float().cpu().numpy() if out["pair"] is not None else np.zeros(n))
    inv = np.empty(len(order), dtype=np.int64)
    inv[np.array(order)] = np.arange(len(order))
    cat = lambda x: np.concatenate(x)[inv]  # noqa: E731
    return cat(probs), cat(bests), cat(scores), cat(items), cat(pairs)


def select_stats(samples, items, pairs):
    """答えを選ぶ頭の成績（確かめ用）。比べる相手: いつも v5、いつも候補の一番、当て推量（枠をでたらめに選ぶ期待値）、上限"""
    n = len(samples)
    v5 = np.array([s.v5_ok for s in samples])
    c0 = np.array([int(s.cand_ok[0]) if s.nc else 0 for s in samples])
    pick = np.zeros(n, dtype=int)
    rand = 0.0
    or_all = 0
    for i, s in enumerate(samples):
        ok = np.concatenate([s.cand_ok, [s.v5_ok]])
        pick[i] = ok[int(np.argmax(items[i][:len(ok)]))] if items.shape[1] else 0
        rand += ok.mean()
        or_all += int(ok.max())
    pair_pick = np.where(pairs > 0, v5, c0)
    m = np.array([s.pair_m for s in samples], dtype=bool)
    y = np.array([s.pair_y for s in samples])
    res = dict(pick_ok=int(pick.sum()), pick_random=float(rand), pick_oracle=int(or_all), always_v5=int(v5.sum()),
               always_c0=int(c0.sum()), pair_ok=int(pair_pick.sum()), pair_oracle=int(np.maximum(v5, c0).sum()),
               pair_random=float((v5 + c0).sum() / 2), pair_n=int(m.sum()),
               pair_auc=auc(y[m], pairs[m]) if m.any() else float("nan"),
               pair_acc=float(((pairs[m] > 0) == (y[m] == 1)).mean()) if m.any() else float("nan"),
               pair_major=float(max(y[m].mean(), 1 - y[m].mean())) if m.any() else float("nan"))
    return res


def evaluate(model, samples, device, autocast=None):
    """確かめ用の成績: 各頭の AUC と、生成に回す割合ごとの正解数（模型の選んだ候補で）、答えを選ぶ頭の成績"""
    probs, bests, _, items, pairs = run_model(model, samples, device, autocast=autocast)
    labels = np.stack([s.labels for s in samples])
    res = {"n": len(samples), "auc": {}}
    for j, name in enumerate(GATE_NAMES):
        res["auc"][name] = auc(labels[:, j], probs[:, j])
    v5_ok = np.array([s.v5_ok for s in samples])
    if model.k > 0:
        stud_ok = np.array([int(s.cand_ok[bests[i]]) if s.nc else 0 for i, s in enumerate(samples)])
    else:
        stud_ok = np.zeros(len(samples), dtype=int)
    res["v5_ok"], res["student_ok_all"] = int(v5_ok.sum()), int(stud_ok.sum())
    rows = []
    for th in (0.5, 0.35, 0.25, 0.2, 0.15, 0.1, 0.05):
        gen = probs[:, 1] >= th
        ok = np.where(gen, v5_ok, stud_ok).sum()
        rows.append({"threshold": th, "gen_share": float(gen.mean()), "correct": int(ok)})
    res["gate_k"] = rows
    if model.k > 0 and items.shape[1]:
        res["select"] = select_stats(samples, items, pairs)
        pa = res["select"]["pair_auc"]
        res["auc"]["pair"] = pa
        res["auc"]["need_k+pair"] = (res["auc"]["need_k"] + pa) / 2  # 早めに止める基準に使える（門と選ぶ頭の平均）
    return res


def print_eval(res):
    print(f"確かめ用 {res['n']} 文: v5 の正解 {res['v5_ok']}、模型の選んだ候補を全部使うと {res['student_ok_all']}")
    print("  AUC: " + "、".join(f"{k} {v:.3f}" for k, v in res["auc"].items()))
    for r in res["gate_k"]:
        print(f"  need_k >= {r['threshold']:.2f} で生成: 生成の割合 {100 * r['gen_share']:.1f}%、正解 {r['correct']}")
    if "select" in res:
        q = res["select"]
        print(f"  選ぶ頭 (b) 枠から選ぶ: 正解 {q['pick_ok']}（いつも v5 {q['always_v5']}、当て推量 {q['pick_random']:.0f}、上限 {q['pick_oracle']}）")
        print(f"  選ぶ頭 (a) v5 と候補の一番: 正解 {q['pair_ok']}（いつも v5 {q['always_v5']}、いつも一番 {q['always_c0']}、当て推量 {q['pair_random']:.0f}、"
              f"上限 {q['pair_oracle']}）。割れる文 {q['pair_n']} で AUC {q['pair_auc']:.3f}、正答率 {q['pair_acc']:.3f}（多いほうに決め打ち {q['pair_major']:.3f}）")


# ---------------------------------------------------------------- 学習
def lr_at(step, total, warmup, peak, floor=0.05):
    if step < warmup:
        return peak * (step + 1) / warmup
    p = (step - warmup) / max(1, total - warmup)
    return peak * (floor + (1 - floor) * 0.5 * (1 + math.cos(math.pi * min(1.0, p))))


def save_atomic(obj, path):
    tmp = str(path) + ".tmp"
    torch.save(obj, tmp)
    os.replace(tmp, path)


def latest_checkpoint(out):
    cks = sorted(Path(out).glob("ckpt-*.pt"), key=lambda p: int(p.stem.split("-")[1]))
    return cks[-1] if cks else None


def train(records, out, cfg=None, epochs=8, batch_size=128, lr=6e-4, seed=20261019, limit=None,
          checkpoint_minutes=10, device=None, log_every=100, valid_share=0.02, max_steps=None, cache_dir=None,
          eval_every=None, patience=None, metric="need_k", sel_weight=1.0):
    """学習する。out の中に ckpt-<歩>.pt（最新の2つ）、best.pt、final.pt、vocab.json、log.txt を置く。途中から再開できる。
    特徴の一時ファイルは cache_dir（既定は out。Colab では手元の高速な場所を渡す）。
    早めの止め方: eval_every 歩ごと（と周の終わり）に確かめ用の AUC（metric の頭）を測り、いちばん良い結果を best.pt に残す。
    patience 回つづけて良くならなければ止める。終わるとき（止めたときも、最後まで行ったときも）final.pt はいちばん良い結果"""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
    cfg = {**DEFAULT_CFG, **(cfg or {})}
    ckpt = latest_checkpoint(out)
    state = torch.load(ckpt, map_location="cpu", weights_only=False) if ckpt else None
    if state:
        cfg = state["cfg"]
        vocab = Vocab(state["vocab"])
        print("続きから始めます:", ckpt.name, "歩", state["step"])
    else:
        vocab = build_vocab(records, cfg, limit=limit or 200000)
    cache_root = Path(cache_dir) if cache_dir else out
    cache_root.mkdir(parents=True, exist_ok=True)
    cache = cache_root / f"features-{FEATURE_TAG}-k{cfg['k']}-a{NEED_AVAIL}-{limit or 'all'}.pkl"
    if cache.exists():
        samples = pickle.load(open(cache, "rb"))
        print("特徴を読みました:", len(samples))
    else:
        print("特徴を作ります…")
        samples = featurize_all(records, vocab, cfg, limit)
        pickle.dump(samples, open(cache, "wb"), protocol=4)
    train_s, valid_s = split_valid(samples, valid_share)
    print(f"学習 {len(train_s)} 文、確かめ {len(valid_s)} 文、語彙 {len(vocab)}、設定 {cfg}")
    model = JevGate(len(vocab), cfg).to(device)
    print(f"数 {count_params(model) / 1e6:.2f} 百万、{device}")
    decay = [p for n, p in model.named_parameters() if p.ndim >= 2]
    other = [p for n, p in model.named_parameters() if p.ndim < 2]
    opt = torch.optim.AdamW([{"params": decay, "weight_decay": 0.01}, {"params": other, "weight_decay": 0.0}],
                            lr=lr, betas=(0.9, 0.98))
    steps_per_epoch = len(make_batches(train_s, batch_size, seed, 0))
    total = steps_per_epoch * epochs
    if max_steps:
        total = min(total, max_steps)
    step = 0
    if state:
        model.load_state_dict(state["model"])
        opt.load_state_dict(state["opt"])
        step = state["step"]
    autocast = torch.bfloat16 if device.type == "cuda" and torch.cuda.is_bf16_supported() else None
    logf = open(out / "log.txt", "a", encoding="utf-8")
    t_save, t0 = time.time(), time.time()
    done0 = step
    model.train()

    best_auc = state.get("best_auc", -1.0) if state else -1.0
    best_step = state.get("best_step", 0) if state else 0
    bad = state.get("bad", 0) if state else 0
    stopped = False

    def save(name):
        save_atomic({"model": model.state_dict(), "opt": opt.state_dict(), "step": step, "cfg": cfg,
                     "vocab": vocab.chars, "total": total, "best_auc": best_auc, "best_step": best_step,
                     "bad": bad}, out / name)

    def check(tag):
        """確かめ用の成績を測って記録し、いちばん良ければ best.pt に残す。止めるなら True"""
        nonlocal best_auc, best_step, bad
        res = evaluate(model, valid_s, device, autocast)
        model.train()
        cur = res["auc"][metric]
        if cur > best_auc + 1e-4:
            best_auc, best_step, bad = cur, step, 0
            save_atomic({"model": model.state_dict(), "step": step, "cfg": cfg, "vocab": vocab.chars,
                         "total": total, "best_auc": best_auc, "best_step": best_step}, out / "best.pt")
            mark = "（最良を更新）"
        else:
            bad += 1
            mark = f"（最良は歩 {best_step} の {best_auc:.4f}、良くならない回数 {bad}" + (f"/{patience}）" if patience else "）")
        print(f"--- {tag}（歩 {step}）{metric} の AUC {cur:.4f} {mark}")
        print_eval(res)
        logf.write(json.dumps({"step": step, "eval": res, "best_auc": best_auc, "best_step": best_step},
                              ensure_ascii=False) + "\n")
        logf.flush()
        return bool(patience) and bad >= patience

    while step < total and not stopped:
        epoch = step // steps_per_epoch
        batches = make_batches(train_s, batch_size, seed, epoch)
        todo = batches[step - epoch * steps_per_epoch:]
        for b_cpu in prefetch(todo, lambda idx: collate([train_s[i] for i in idx], model.k, "cpu")):
            if step >= total:
                break
            for g in opt.param_groups:
                g["lr"] = lr_at(step, total, min(500, total // 10), lr)
            b = to_device(b_cpu, device)
            with torch.autocast(device_type=device.type, dtype=autocast, enabled=autocast is not None):
                outp = model(b)
            loss, parts = loss_fn(outp, b, sel_weight)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            step += 1
            if step % log_every == 0:
                el = time.time() - t0
                rate = (step - done0) / el
                msg = (f"歩 {step}/{total} 損失 {loss.item():.4f} 門 {parts['gate']:.4f} 点 {parts['reg']:.4f} "
                       f"順位 {parts['rank']:.4f} 選び {parts['sel']:.4f} lr {opt.param_groups[0]['lr']:.2e} 残り約 {(total - step) / rate / 60:.1f} 分")
                print(msg, flush=True)
                logf.write(msg + "\n")
                logf.flush()
            if time.time() - t_save > checkpoint_minutes * 60:
                save(f"ckpt-{step}.pt")
                for old in sorted(out.glob("ckpt-*.pt"), key=lambda p: int(p.stem.split("-")[1]))[:-2]:
                    old.unlink()
                t_save = time.time()
            if eval_every and step % eval_every == 0 and step < total and (step % steps_per_epoch):
                if check(f"周 {epoch + 1} の途中"):
                    stopped = True
                    break
                save(f"ckpt-{step}.pt")
                for old in sorted(out.glob("ckpt-*.pt"), key=lambda p: int(p.stem.split("-")[1]))[:-2]:
                    old.unlink()
                t_save = time.time()
        if not stopped:
            stopped = check(f"周 {epoch + 1} 終わり")
        if not stopped:
            save(f"ckpt-{step}.pt")
            for old in sorted(out.glob("ckpt-*.pt"), key=lambda p: int(p.stem.split("-")[1]))[:-2]:
                old.unlink()
    if stopped:
        print(f"早めに止めます: 歩 {best_step} から {patience} 回つづけて {metric} の AUC が良くなりませんでした")
    if best_step and (out / "best.pt").exists():
        best = torch.load(out / "best.pt", map_location="cpu", weights_only=False)
        model.load_state_dict(best["model"])
        step = best["step"]
        print(f"いちばん良い結果（歩 {step}、{metric} の AUC {best_auc:.4f}）を最終の結果にします")
    save("final.pt")
    json.dump({"chars": vocab.chars, "cfg": cfg}, open(out / "vocab.json", "w", encoding="utf-8"), ensure_ascii=False)
    print("学習が終わりました:", out / "final.pt")
    return model


def load_model(path, device="cpu"):
    state = torch.load(path, map_location="cpu", weights_only=False)
    vocab = Vocab(state["vocab"])
    model = JevGate(len(vocab), state["cfg"])
    model.load_state_dict(state["model"])
    return model.to(device).eval(), vocab


def predict(ckpt, records, out_tsv, device=None, limit=None):
    """記録ごとの出力を書く: id<TAB>need<TAB>need_k<TAB>need_top1<TAB>harm_k<TAB>選んだ候補の番号<TAB>候補ごとの点…
    答えを選ぶ頭があれば、続けて「|」、v5 が正しいほうの確率（頭 a。v5 と候補の一番）、枠ごとの正解の度合い（頭 b。候補…、最後に v5 の出力）"""
    device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
    model, vocab = load_model(ckpt, device)
    samples = featurize_all(records, vocab, model.cfg, limit, log=False)
    probs, bests, scores, items, pairs = run_model(model, samples, device)
    with open(out_tsv, "w", encoding="utf-8", newline="\n") as f:
        for i, s in enumerate(samples):
            row = [s.id] + [f"{x:.5f}" for x in probs[i]] + [str(int(bests[i]))] + [f"{x:.4f}" for x in scores[i][:s.nc]]
            if items.shape[1]:
                row += ["|", f"{1 / (1 + math.exp(-float(pairs[i]))):.5f}"] + [f"{x:.4f}" for x in items[i][:s.nc]] + [f"{items[i][model.k]:.4f}"]
            f.write("\t".join(row) + "\n")
    print(f"{len(samples)} 文の出力を書きました: {out_tsv}")


# ---------------------------------------------------------------- 書き出し（C++ の推論用の重みの表）
def tensor_order(model):
    """C++ と同じ順の (名前, 形) の一覧。重みはすべて [出力][入力] の並び（torch の Linear と同じ）"""
    cfg = model.cfg
    names = ["tok", "typ", "pos_prefix", "pos_cand", "rank", "src"]
    out = [(f"{n}.weight", getattr(model, n).weight) for n in names]
    for i, blk in enumerate(model.blocks):
        for n in ("ln1", "qkv", "proj", "ln2", "fc1", "fc2"):
            m = getattr(blk, n)
            out.append((f"b{i}.{n}.weight", m.weight))
            out.append((f"b{i}.{n}.bias", m.bias))
    for n in ("ln_f", "s1", "s2", "g1", "g2", "i1", "i2", "p1", "p2"):
        m = getattr(model, n)
        out.append((f"{n}.weight", m.weight))
        out.append((f"{n}.bias", m.bias))
    return out


def export(ckpt, out_path, fp16=False):
    """重みの表（JEVG 形式）を書く。先頭: 目印 4 バイト、版、設定の整数、語彙の数。続いて tensor_order の順に重みを並べる。
    fp16=True なら重みを半精度で持つ（約半分の大きさ。読み込むときに単精度へ戻す）"""
    model, vocab = load_model(ckpt)
    c = model.cfg
    head = [VERSION, int(fp16), len(vocab), c["d"], c["layers"], c["heads"], c["ffn"], c["k"], c["gate_hidden"],
            MAX_PREFIX_POS, MAX_CAND_POS, MAX_RANK, len(GATE_NAMES)]
    with open(out_path, "wb") as f:
        f.write(MAGIC)
        f.write(struct.pack(f"<{len(head)}i", *head))
        for name, t in tensor_order(model):
            a = t.detach().cpu().numpy().astype(np.float16 if fp16 else np.float32)
            f.write(a.tobytes(order="C"))
    json.dump({"chars": vocab.chars, "cfg": c, "special": {"pad": PAD, "unk": UNK, "cls": CLS, "sep": SEP, "eoc": EOC}},
              open(str(out_path) + ".vocab.json", "w", encoding="utf-8"), ensure_ascii=False)
    print(f"書きました: {out_path}（{os.path.getsize(out_path) / 1e6:.1f} MB、{count_params(model) / 1e6:.2f} 百万）")


def dump_case(ckpt, records, out_path, n=3):
    """C++ の推論と合わせるための、入力の並びと torch の出力の見本（テキスト）"""
    model, vocab = load_model(ckpt)
    samples = featurize_all(records, vocab, model.cfg, n, log=False)
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        for s in samples:
            b = collate([s], model.k)
            with torch.no_grad():
                o = model(b)
            Lp, Lc = b["Lp"], b["Lc"]
            toks = []
            for key in ("tok", "typ", "pos", "rank", "src", "seg"):
                toks.append(" ".join(str(int(x)) for x in b[key][0][b["valid"][0]]))
            gate = " ".join(f"{x:.6f}" for x in torch.sigmoid(o["gate"][0]).tolist())
            sc = " ".join(f"{x:.6f}" for x in o["score"][0][b["cvalid"][0]].tolist()) if o["score"] is not None else ""
            it = " ".join(f"{x:.6f}" for x in o["item"][0][b["ivalid"][0]].tolist()) if o["item"] is not None else ""
            pr = f"{o['pair'][0].item():.6f}" if o["pair"] is not None else ""
            f.write(f"{len(b['tok'][0][b['valid'][0]])}\n" + "\n".join(toks) + f"\n{gate}\n{sc}\n{it}\n{pr}\n")
    print("見本を書きました:", out_path)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("train")
    t.add_argument("--records", nargs="+", required=True)
    t.add_argument("--out", required=True)
    t.add_argument("--epochs", type=int, default=8)
    t.add_argument("--batch", type=int, default=128)
    t.add_argument("--lr", type=float, default=6e-4)
    t.add_argument("--limit", type=int, default=None)
    t.add_argument("--max-steps", type=int, default=None)
    t.add_argument("--seed", type=int, default=20261019)
    t.add_argument("--eval-every", type=int, default=None, help="確かめ用を測る歩の間隔（周の終わりにも測る）")
    t.add_argument("--patience", type=int, default=None, help="確かめ用の AUC がこの回数つづけて良くならなければ止める")
    t.add_argument("--metric", default="need_k", choices=GATE_NAMES + ["pair", "need_k+pair"])
    t.add_argument("--sel-weight", type=float, default=1.0, help="答えを選ぶ頭の損失の重み（0 なら選ぶ頭を学習しない）")
    for key in ("k", "d", "layers", "heads", "ffn", "max_vocab", "prev_chars", "read_chars", "cand_chars"):
        t.add_argument("--" + key.replace("_", "-"), type=int, default=None)
    p = sub.add_parser("predict")
    p.add_argument("--ckpt", required=True)
    p.add_argument("--records", nargs="+", required=True)
    p.add_argument("--out", required=True)
    e = sub.add_parser("export")
    e.add_argument("--ckpt", required=True)
    e.add_argument("--out", required=True)
    e.add_argument("--fp16", action="store_true")
    dc = sub.add_parser("dumpcase")
    dc.add_argument("--ckpt", required=True)
    dc.add_argument("--records", nargs="+", required=True)
    dc.add_argument("--out", required=True)
    c = sub.add_parser("count")
    for key in ("k", "d", "layers", "heads", "ffn", "max_vocab"):
        c.add_argument("--" + key.replace("_", "-"), type=int, default=None)
    a = ap.parse_args()
    if a.cmd == "train":
        cfg = {k: getattr(a, k) for k in ("k", "d", "layers", "heads", "ffn", "max_vocab", "prev_chars", "read_chars",
                                           "cand_chars") if getattr(a, k) is not None}
        train(a.records, a.out, cfg, epochs=a.epochs, batch_size=a.batch, lr=a.lr, seed=a.seed, limit=a.limit,
              max_steps=a.max_steps, eval_every=a.eval_every, patience=a.patience, metric=a.metric, sel_weight=a.sel_weight)
    elif a.cmd == "predict":
        predict(a.ckpt, a.records, a.out)
    elif a.cmd == "export":
        export(a.ckpt, a.out, a.fp16)
    elif a.cmd == "dumpcase":
        dump_case(a.ckpt, a.records, a.out)
    elif a.cmd == "count":
        cfg = {**DEFAULT_CFG, **{k: getattr(a, k) for k in ("k", "d", "layers", "heads", "ffn", "max_vocab")
                                 if getattr(a, k) is not None}}
        m = JevGate(cfg["max_vocab"], cfg)
        print(f"{count_params(m) / 1e6:.2f} 百万", cfg)


if __name__ == "__main__":
    main()
