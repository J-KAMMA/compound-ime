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
GATE_NAMES = ["need", "need_k", "need_top1", "harm_k"]
GATE_WEIGHTS = [1.0, 1.0, 0.5, 0.5]
MAGIC = b"JEVG"
VERSION = 1

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
    __slots__ = ("id", "prefix", "ptype", "cands", "csrc", "gap", "best", "labels", "cand_ok", "v5_ok", "nc")


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
    sel_ok = int(is_ok(sel, answers, fold))
    s.v5_ok = v5_ok
    s.labels = np.array([rec["need"], int(sel != rec["v5"]), rec["need_top1"], int(v5_ok and not sel_ok)],
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
def collate(batch, k, device="cpu"):
    """並びの形: [前置き（先頭、前の文、区切り、読み、区切り）][候補1の枠][候補2の枠]…。枠の長さは束の中の最長にそろえる"""
    B = len(batch)
    Lp = max(len(s.prefix) for s in batch)
    Lc = max([len(c) for s in batch for c in s.cands] + [1])
    T = Lp + k * Lc
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
    ok = np.zeros((B, k), dtype=np.int64)
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
        gap[b, :s.nc] = s.gap
        ok[b, :s.nc] = s.cand_ok
        best[b] = s.best
    labels = np.stack([s.labels for s in batch])
    v5_ok = np.array([s.v5_ok for s in batch], dtype=np.int64)
    t = lambda x: torch.from_numpy(x).to(device)  # noqa: E731
    return dict(tok=t(tok), typ=t(typ), pos=t(pos), rank=t(rank), src=t(src), seg=t(seg), valid=t(valid),
                cvalid=t(cvalid), gap=t(gap), best=t(best), labels=t(labels), cand_ok=t(ok), v5_ok=t(v5_ok),
                Lp=Lp, Lc=Lc)


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
        self.src = nn.Embedding(4, d)
        self.blocks = nn.ModuleList([Block(d, cfg["heads"], cfg["ffn"], cfg["dropout"]) for _ in range(cfg["layers"])])
        self.ln_f = nn.LayerNorm(d)
        self.s1 = nn.Linear(d, d // 2)
        self.s2 = nn.Linear(d // 2, 1)
        self.g1 = nn.Linear(3 * d + 3, cfg["gate_hidden"])
        self.g2 = nn.Linear(cfg["gate_hidden"], len(GATE_NAMES))
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
            return dict(gate=self.g2(F.gelu(self.g1(g_in), approximate="tanh")), score=None, best=None)
        hc = h[:, Lp:].reshape(B, k, Lc, d)
        vc = valid[:, Lp:].reshape(B, k, Lc).unsqueeze(-1).to(h.dtype)
        pooled = (hc * vc).sum(2) / vc.sum(2).clamp(min=1)
        score = self.s2(F.gelu(self.s1(pooled), approximate="tanh")).squeeze(-1)
        cv = b["cvalid"]
        masked = score.masked_fill(~cv, -1e4)
        best = masked.argmax(-1)
        ar = torch.arange(B, device=h.device)
        c_best = pooled[ar, best]
        c0 = pooled[:, 0]
        top2 = masked.topk(min(2, k), dim=-1).values
        margin = (top2[:, 0] - top2[:, 1]) if k >= 2 else torch.zeros_like(top2[:, 0])
        margin = torch.where(cv.sum(-1) >= 2, margin, torch.ones_like(margin))
        length = vc.squeeze(-1).sum(2)[ar, best] / 20.0
        g_in = torch.cat([cls, c_best, c0, torch.stack([masked[ar, best], margin, length], dim=-1).to(h.dtype)], dim=-1)
        return dict(gate=self.g2(F.gelu(self.g1(g_in), approximate="tanh")), score=score, best=best)


def count_params(model):
    return sum(p.numel() for p in model.parameters())


def loss_fn(out, b):
    gate = out["gate"].float()
    w = torch.tensor(GATE_WEIGHTS, device=gate.device)
    l_gate = (F.binary_cross_entropy_with_logits(gate, b["labels"], reduction="none") * w).sum(-1).mean()
    if out["score"] is None:
        return l_gate, dict(gate=l_gate.item(), reg=0.0, rank=0.0)
    score, cv = out["score"].float(), b["cvalid"]
    reg = (F.huber_loss(score, b["gap"], reduction="none", delta=0.5) * cv).sum() / cv.sum().clamp(min=1)
    has = (b["best"] >= 0)
    ce = F.cross_entropy(score.masked_fill(~cv, -1e4)[has], b["best"][has]) if has.any() else score.sum() * 0
    return l_gate + reg + 0.5 * ce, dict(gate=l_gate.item(), reg=reg.item(), rank=ce.item())


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
    model.eval()
    k = model.k
    probs, bests, scores = [], [], []
    order = sorted(range(len(samples)), key=lambda i: len(samples[i].prefix) + sum(len(c) for c in samples[i].cands))
    for a in range(0, len(order), batch_size):
        idx = order[a:a + batch_size]
        b = collate([samples[i] for i in idx], k, device)
        with torch.autocast(device_type=device.type, dtype=autocast, enabled=autocast is not None):
            out = model(b)
        probs.append(torch.sigmoid(out["gate"].float()).cpu().numpy())
        bests.append(out["best"].cpu().numpy() if out["best"] is not None else np.zeros(len(idx), dtype=np.int64))
        scores.append(out["score"].float().cpu().numpy() if out["score"] is not None else np.zeros((len(idx), 0)))
    inv = np.empty(len(order), dtype=np.int64)
    inv[np.array(order)] = np.arange(len(order))
    return np.concatenate(probs)[inv], np.concatenate(bests)[inv], np.concatenate(scores)[inv]


def evaluate(model, samples, device, autocast=None):
    """確かめ用の成績: 各頭の AUC と、生成に回す割合ごとの正解数（模型の選んだ候補で）"""
    probs, bests, _ = run_model(model, samples, device, autocast=autocast)
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
    for th in (0.5, 0.35, 0.25, 0.15, 0.1, 0.05):
        gen = probs[:, 1] >= th
        ok = np.where(gen, v5_ok, stud_ok).sum()
        rows.append({"threshold": th, "gen_share": float(gen.mean()), "correct": int(ok)})
    res["gate_k"] = rows
    return res


def print_eval(res):
    print(f"確かめ用 {res['n']} 文: v5 の正解 {res['v5_ok']}、模型の選んだ候補を全部使うと {res['student_ok_all']}")
    print("  AUC: " + "、".join(f"{k} {v:.3f}" for k, v in res["auc"].items()))
    for r in res["gate_k"]:
        print(f"  need_k >= {r['threshold']:.2f} で生成: 生成の割合 {100 * r['gen_share']:.1f}%、正解 {r['correct']}")


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
          checkpoint_minutes=10, device=None, log_every=100, valid_share=0.02, max_steps=None):
    """学習する。out の中に ckpt-<歩>.pt（最新の2つ）、final.pt、vocab.json、log.txt を置く。途中から再開できる"""
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
    cache = out / f"features-k{cfg['k']}.pkl"
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

    def save(name):
        save_atomic({"model": model.state_dict(), "opt": opt.state_dict(), "step": step, "cfg": cfg,
                     "vocab": vocab.chars, "total": total}, out / name)

    while step < total:
        epoch = step // steps_per_epoch
        batches = make_batches(train_s, batch_size, seed, epoch)
        for bi in range(step - epoch * steps_per_epoch, len(batches)):
            if step >= total:
                break
            for g in opt.param_groups:
                g["lr"] = lr_at(step, total, min(500, total // 10), lr)
            b = collate([train_s[i] for i in batches[bi]], model.k, device)
            with torch.autocast(device_type=device.type, dtype=autocast, enabled=autocast is not None):
                outp = model(b)
            loss, parts = loss_fn(outp, b)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            step += 1
            if step % log_every == 0:
                el = time.time() - t0
                rate = (step - done0) / el
                msg = (f"歩 {step}/{total} 損失 {loss.item():.4f} 門 {parts['gate']:.4f} 点 {parts['reg']:.4f} "
                       f"順位 {parts['rank']:.4f} lr {opt.param_groups[0]['lr']:.2e} 残り約 {(total - step) / rate / 60:.1f} 分")
                print(msg, flush=True)
                logf.write(msg + "\n")
                logf.flush()
            if time.time() - t_save > checkpoint_minutes * 60:
                save(f"ckpt-{step}.pt")
                for old in sorted(out.glob("ckpt-*.pt"), key=lambda p: int(p.stem.split("-")[1]))[:-2]:
                    old.unlink()
                t_save = time.time()
        res = evaluate(model, valid_s, device, autocast)
        model.train()
        print(f"--- 周 {epoch + 1} 終わり（歩 {step}）")
        print_eval(res)
        logf.write(json.dumps({"step": step, "eval": res}, ensure_ascii=False) + "\n")
        logf.flush()
        save(f"ckpt-{step}.pt")
        for old in sorted(out.glob("ckpt-*.pt"), key=lambda p: int(p.stem.split("-")[1]))[:-2]:
            old.unlink()
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
    """記録ごとの出力を書く: id<TAB>need<TAB>need_k<TAB>need_top1<TAB>harm_k<TAB>選んだ候補の番号<TAB>候補ごとの点…"""
    device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
    model, vocab = load_model(ckpt, device)
    samples = featurize_all(records, vocab, model.cfg, limit, log=False)
    probs, bests, scores = run_model(model, samples, device)
    with open(out_tsv, "w", encoding="utf-8", newline="\n") as f:
        for i, s in enumerate(samples):
            row = [s.id] + [f"{x:.5f}" for x in probs[i]] + [str(int(bests[i]))] + [f"{x:.4f}" for x in scores[i][:s.nc]]
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
    for n in ("ln_f", "s1", "s2", "g1", "g2"):
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
            f.write(f"{len(b['tok'][0][b['valid'][0]])}\n" + "\n".join(toks) + f"\n{gate}\n{sc}\n")
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
              max_steps=a.max_steps)
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
