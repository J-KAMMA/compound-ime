"""finetune.ipynb から呼ぶ部品。Colab でも手元の計算機（GPU なし）でも動く。

- GPU に合わせた設定と、時間・コンピューティング ユニットの見積り（gpu_profile, estimate）
- 配布されている GGUF（量子化済み）を、学習できる形（transformers の GPT-2）に戻す
  （gguf_to_hf）。zenz-v3.2-small は GGUF でしか配られていないため
- 練習問題の読み込みと並べ方（load_examples, epoch_batches）
- 途中から続けられる学習（train）。チェックポイントは Google ドライブに置く
- 確かめ用の問題での成績（evaluate）、文の終わりの記号の確認（choose_end_token）
- GGUF の中身の比較（gguf_summary, compare_summaries）と SHA256
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import sys
import time
from pathlib import Path

import numpy as np

PAD_ID = 1

# 1 時間あたりのコンピューティング ユニット（2026-10 時点の目安。Colab の表示が正）。
# tok_s は学習の速さの仮の値（1 秒あたりの文字数）。実際の値は学習を始めてから測って出し直す。
PROFILES = {
    "A100": {"precision": "bf16", "micro": 128, "tok_s": 110_000, "units_per_hour": 11.77},
    "L4": {"precision": "bf16", "micro": 64, "tok_s": 45_000, "units_per_hour": 4.82},
    "T4": {"precision": "fp16", "micro": 16, "tok_s": 12_300, "units_per_hour": 1.76},  # tok_s は実測（40万問・2周で約85分）。micro は 64 では長い問題の束で記憶が足りなくなった（2026-10-15、400歩目）
}


def sha256_file(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def gpu_profile(effective_batch: int = 128) -> dict:
    """使える GPU に合わせて、計算の精度と一度に流す数を決める。"""
    import torch
    if not torch.cuda.is_available():
        return {"name": "CPU", "kind": "CPU", "precision": "fp32", "micro": 8,
                "accum": max(1, effective_batch // 8), "tok_s": 500, "units_per_hour": None}
    name = torch.cuda.get_device_name(0)
    kind = next((k for k in PROFILES if k in name), None)
    if kind:
        profile = dict(PROFILES[kind])
    else:
        memory = torch.cuda.get_device_properties(0).total_memory / 2**30
        profile = {"precision": "bf16" if torch.cuda.is_bf16_supported() else "fp16",
                   "micro": 128 if memory >= 20 else 64, "tok_s": 20_000, "units_per_hour": None}
        kind = "その他"
    profile["micro"] = min(profile["micro"], effective_batch)
    profile["accum"] = max(1, effective_batch // profile["micro"])
    profile.update({"name": name, "kind": kind})
    return profile


AVG_TOKENS = 71.5          # 1問の平均の字数（300万問の試運転の実測: 71.49。ウィキペディアだけの割合なら 78）。⑧で実際の平均に直す
BUILD_PROBLEMS_PER_MIN = 60_000   # 問題作り（CPU 1 つ分）の速さ。GitHub Actions の実測は約 20万〜60万問/分で、Colab はその 1/3 ほどと見込む
BUILD_PROCESSES = 2


def estimate(profile: dict, n_train: int, epochs: int, avg_tokens: float = AVG_TOKENS,
             data_built: bool = False, tok_s: float | None = None, run_minutes: float | None = None) -> dict:
    """全体の時間（分）とコンピューティング ユニットの見積り。
    run_minutes を渡すと、1回の接続で学習できる時間をそれだけと見て、何回に分かれるかも返す。"""
    speed = tok_s or profile["tok_s"]
    train_minutes = n_train * epochs * avg_tokens / speed / 60
    # 問題作り（CPU。GPU は使わないので CPU のランタイムで先に作ると、GPU の枠を使わない）
    build_minutes = 0 if data_built else n_train / (BUILD_PROBLEMS_PER_MIN * BUILD_PROCESSES)
    # 準備（道具・材料・元の模型）10分、評価 10分、GGUF 化 10分
    fixed = 10 + 10 + 10
    total = train_minutes + build_minutes + fixed
    gpu_minutes = train_minutes + fixed          # 問題作りを CPU のランタイムでやる場合に GPU をつなぐ時間
    rate = profile.get("units_per_hour")
    return {"train_minutes": train_minutes, "build_minutes": build_minutes, "total_minutes": total,
            "units": None if rate is None else total / 60 * rate,
            "units_gpu_only": None if rate is None else gpu_minutes / 60 * rate,
            "runs": None if not run_minutes else math.ceil(train_minutes / run_minutes)}


# ------------------------------------------------------------------ Google ドライブの容量の見積り

CHECKPOINT_GB = 1.1        # 模型（fp32）と最適化の状態。実測（README: 約1.1GB ずつ）
MODEL_GB = 0.37            # 学習できる形の模型（fp32、約9100万個の重み）
GGUF_GB = 0.075
JSONL_GZ_BYTES = 76        # 1問あたりの jsonl.gz のバイト数（300万問の試運転の実測: 75.8）
NPZ_BYTES_PER_TOKEN = 0.98  # 数字にした練習問題（npz、圧縮）の 1字あたりのバイト数（300万問の試運転の実測: 0.98）


def drive_plan(n_train: int, keep: int = 1, avg_tokens: float = AVG_TOKENS, data_on_drive: bool = True) -> dict:
    """Google ドライブに置くものの大きさ（GB）の見積り。keep は残すチェックポイントの数。
    チェックポイントは、新しいものを書き終えてから古いものを消すので、保存の最中は keep+1 個分になる。"""
    gb = 1e9
    rows = [
        ("材料の控え（元の GGUF・分かち方・ローマ字表・取り出した文）", 0.12),
        ("学習できる形の元の模型（base）", MODEL_GB),
        ("学習後の模型（final）", MODEL_GB),
        ("できた GGUF 2 つと説明書き（result）", 2 * GGUF_GB + 0.01),
    ]
    if data_on_drive:
        rows += [("練習問題（jsonl.gz の部品）", n_train * JSONL_GZ_BYTES / gb),
                 ("数字にした練習問題（npz）", n_train * avg_tokens * NPZ_BYTES_PER_TOKEN / gb)]
    steady = sum(v for _, v in rows) + keep * CHECKPOINT_GB
    peak = steady + CHECKPOINT_GB
    return {"rows": rows + [(f"チェックポイント（最新の {keep} 個。保存の最中は {keep + 1} 個分）", keep * CHECKPOINT_GB)],
            "steady_gb": steady, "peak_gb": peak}

# ------------------------------------------------------------------ GGUF


def import_gguf(llama_dir):
    """llama.cpp に同梱の gguf-py（変換スクリプトと同じ版）を読み込む。"""
    path = str(Path(llama_dir) / "gguf-py")
    if path not in sys.path:
        sys.path.insert(0, path)
    import gguf
    return gguf


def _field(reader, key):
    field = reader.fields.get(key)
    return None if field is None else field.contents()


BLOCK_NAMES = {"attn_norm": "ln_1", "attn_qkv": "attn.c_attn", "attn_output": "attn.c_proj",
               "ffn_norm": "ln_2", "ffn_up": "mlp.c_fc", "ffn_down": "mlp.c_proj"}
TRANSPOSED = {"attn_qkv", "attn_output", "ffn_up", "ffn_down"}
TOP_NAMES = {"token_embd.weight": "transformer.wte.weight", "position_embd.weight": "transformer.wpe.weight",
             "output_norm.weight": "transformer.ln_f.weight", "output_norm.bias": "transformer.ln_f.bias"}
PRECISION_RANK = {"F32": 100, "F16": 90, "BF16": 90, "Q8_0": 80, "Q6_K": 60, "Q5_K": 50, "Q5_0": 45,
                  "Q5_1": 46, "Q4_K": 40, "Q4_0": 35, "Q4_1": 36, "Q3_K": 30, "Q2_K": 20}


def gguf_to_hf(gguf_path, tokenizer_dir, out_dir, llama_dir) -> dict:
    """GPT-2 の GGUF を transformers の形に戻す（量子化をほどいて float32 にする）。

    llama.cpp の convert_hf_to_gguf.py（GPT2Model）がしていることの逆:
    c_attn・c_proj・c_fc の重みは転置して入っているので、転置して戻す。
    出力の重み（output.weight）は入力の重み（token_embd）と元は同じもの。
    精度の高い方の型で量子化されている方を使う。
    """
    import torch
    from transformers import GPT2Config, GPT2LMHeadModel
    gguf = import_gguf(llama_dir)
    reader = gguf.GGUFReader(str(gguf_path))
    if _field(reader, "general.architecture") != "gpt2":
        raise ValueError("GPT-2 の GGUF ではありません")
    tokens = _field(reader, "tokenizer.ggml.tokens")
    vocab = json.loads((Path(tokenizer_dir) / "vocab.json").read_text(encoding="utf-8"))
    by_id = sorted(vocab.items(), key=lambda kv: kv[1])
    if [k for k, _ in by_id] != list(tokens):
        raise ValueError("GGUF の語彙と vocab.json の語彙が違います（分かち方の部品が合っていない）")

    n_embd = int(_field(reader, "gpt2.embedding_length"))
    n_ff = int(_field(reader, "gpt2.feed_forward_length"))
    config = GPT2Config(
        vocab_size=len(tokens),
        n_positions=int(_field(reader, "gpt2.context_length")),
        n_embd=n_embd,
        n_layer=int(_field(reader, "gpt2.block_count")),
        n_head=int(_field(reader, "gpt2.attention.head_count")),
        n_inner=None if n_ff == 4 * n_embd else n_ff,
        layer_norm_epsilon=float(_field(reader, "gpt2.attention.layer_norm_epsilon")),
        activation_function="gelu_new",
        bos_token_id=int(_field(reader, "tokenizer.ggml.bos_token_id")),
        eos_token_id=int(_field(reader, "tokenizer.ggml.eos_token_id")),
        pad_token_id=int(_field(reader, "tokenizer.ggml.padding_token_id") or PAD_ID),
        tie_word_embeddings=True,
    )
    config.n_ctx = config.n_positions

    arrays, types = {}, {}
    for tensor in reader.tensors:
        data = gguf.quants.dequantize(tensor.data, tensor.tensor_type)
        shape = tuple(int(x) for x in reversed([int(v) for v in tensor.shape]))
        arrays[tensor.name] = np.asarray(data, dtype=np.float32).reshape(shape)
        types[tensor.name] = tensor.tensor_type.name

    state = {}
    embed_source = "token_embd.weight"
    if "output.weight" in arrays and PRECISION_RANK.get(types["output.weight"], 0) > \
            PRECISION_RANK.get(types["token_embd.weight"], 0):
        embed_source = "output.weight"
    for name, array in arrays.items():
        if name == "output.weight":
            continue
        if name == "token_embd.weight":
            array = arrays[embed_source]
        if name in TOP_NAMES:
            state[TOP_NAMES[name]] = array
            continue
        _, block, part, kind = name.split(".")
        hf = f"transformer.h.{block}.{BLOCK_NAMES[part]}.{kind}"
        state[hf] = array.T.copy() if (part in TRANSPOSED and kind == "weight") else array

    model = GPT2LMHeadModel(config)
    params = {n for n, _ in model.named_parameters()}
    missing = params - set(state) - {"lm_head.weight"}
    extra = set(state) - params
    if missing or extra:
        raise ValueError(f"重みの対応が合いません: 足りない {sorted(missing)[:5]} 余分 {sorted(extra)[:5]}")
    with torch.no_grad():
        for name, param in model.named_parameters():
            if name in state:
                if tuple(param.shape) != state[name].shape:
                    raise ValueError(f"{name} の形が違います {tuple(param.shape)} {state[name].shape}")
                param.copy_(torch.from_numpy(state[name]))
    model.tie_weights()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(out, safe_serialization=True)
    for name in ("vocab.json", "merges.txt", "tokenizer_config.json", "special_tokens_map.json"):
        shutil.copy(Path(tokenizer_dir) / name, out / name)
    info = {"tensor_types": types, "embedding_from": embed_source,
            "config": {k: getattr(config, k) for k in ("vocab_size", "n_positions", "n_embd", "n_layer", "n_head",
                                                       "bos_token_id", "eos_token_id", "pad_token_id")}}
    (out / "from_gguf.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    return info


def prepare_for_convert(model_dir, end_id: int | None = None):
    """convert_hf_to_gguf.py（固定版）は config.json の n_ctx を読むので、無ければ足す。
    文の終わりの記号などの番号は元の GGUF と同じ（bos 1、eos 2、pad 1）のままにする。"""
    path = Path(model_dir) / "config.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    config.setdefault("n_ctx", config.get("n_positions", 1024))
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return config


def gguf_summary(path, llama_dir) -> dict:
    gguf = import_gguf(llama_dir)
    reader = gguf.GGUFReader(str(path))
    meta = {}
    for key in reader.fields:
        if key.startswith("GGUF.") or key.startswith("general."):
            continue
        value = _field(reader, key)
        if isinstance(value, list) and len(value) > 50:
            value = hashlib.sha256(json.dumps(value, ensure_ascii=False).encode("utf-8")).hexdigest()
        meta[key] = value
    tensors = {t.name: ([int(v) for v in t.shape], t.tensor_type.name) for t in reader.tensors}
    general = {k: _field(reader, k) for k in reader.fields if k.startswith("general.")}
    return {"meta": meta, "tensors": tensors, "general": general}


def compare_summaries(original: dict, candidate: dict) -> list[str]:
    """元の GGUF と作った GGUF の違い（general.* の名前などは見ない）。"""
    problems = []
    for key in sorted(set(original["meta"]) | set(candidate["meta"])):
        if original["meta"].get(key) != candidate["meta"].get(key):
            problems.append(f"設定 {key}: 元 {original['meta'].get(key)!r} / 新 {candidate['meta'].get(key)!r}")
    for name in sorted(set(original["tensors"]) | set(candidate["tensors"])):
        if original["tensors"].get(name) != candidate["tensors"].get(name):
            problems.append(f"重み {name}: 元 {original['tensors'].get(name)} / 新 {candidate['tensors'].get(name)}")
    return problems

# ------------------------------------------------------------------ 練習問題


class Examples:
    """問題を数字の列にしたもの。ids はつないだ1本の列、starts・prompt_len・length で切り出す。"""

    def __init__(self, ids, starts, prompt_len, length, kinds, kind_names):
        self.ids, self.starts, self.prompt_len, self.length = ids, starts, prompt_len, length
        self.kinds, self.kind_names = kinds, kind_names

    def __len__(self):
        return len(self.starts)

    def get(self, i):
        s = int(self.starts[i])
        return self.ids[s:s + int(self.length[i])], int(self.prompt_len[i])

    def save(self, path):
        # 圧縮して書く（数百万問でもドライブに置ける大きさにする）。読むときは np.load が自動で戻す
        np.savez_compressed(path, ids=self.ids, starts=self.starts, prompt_len=self.prompt_len, length=self.length,
                 kinds=self.kinds, kind_names=np.array(self.kind_names))

    @classmethod
    def load(cls, path):
        d = np.load(path)
        return cls(d["ids"], d["starts"], d["prompt_len"], d["length"], d["kinds"], [str(x) for x in d["kind_names"]])

    def subset(self, indices):
        indices = np.asarray(indices)
        return Examples(self.ids, self.starts[indices], self.prompt_len[indices], self.length[indices],
                        self.kinds[indices], self.kind_names)


def read_jsonl(path):
    """1行1問の jsonl（.gz も可）を1問ずつ返す。"""
    import gzip
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def load_examples(jsonl_paths, tokenizer, end_id: int, max_len: int = 256, chunk: int = 50_000,
                  progress: int = 500_000) -> tuple[Examples, int]:
    """問いと正解を数字にする。正解の後ろに文の終わりの記号を付ける。
    実行時と同じく、問いの前に始まりの記号は付けない（GGUF の add_bos_token は False）。
    jsonl_paths は1つのパスか、パスの並び（数百万問を部品に分けたもの。.gz も可）。chunk 問ずつ数字にして、
    メモリを抑える（300万問でも 1GB ほど）。字の番号は 65536 未満なら 2 バイトで持つ。"""
    if isinstance(jsonl_paths, (str, os.PathLike)):
        jsonl_paths = [jsonl_paths]
    id_dtype = np.uint16 if len(tokenizer) < 65536 else np.int32
    kind_index, kind_names = {}, []
    id_parts, prompt_len, length, kinds = [], [], [], []
    state = {"dropped": 0, "pos": 0, "seen": 0}
    starts = []

    def flush(records):
        if not records:
            return
        prompts = tokenizer([r["prompt"] for r in records], add_special_tokens=False)["input_ids"]
        outputs = tokenizer([r["output"] for r in records], add_special_tokens=False)["input_ids"]
        ids = []
        for record, p, o in zip(records, prompts, outputs):
            seq = list(p) + list(o) + [end_id]
            if len(seq) > max_len or not o:
                state["dropped"] += 1
                continue
            if record["kind"] not in kind_index:
                kind_index[record["kind"]] = len(kind_names)
                kind_names.append(record["kind"])
            starts.append(state["pos"])
            prompt_len.append(len(p))
            length.append(len(seq))
            kinds.append(kind_index[record["kind"]])
            ids.extend(seq)
            state["pos"] += len(seq)
        id_parts.append(np.array(ids, dtype=id_dtype))

    batch = []
    for path in jsonl_paths:
        for record in read_jsonl(path):
            batch.append(record)
            state["seen"] += 1
            if len(batch) >= chunk:
                flush(batch)
                batch = []
                if progress and state["seen"] % progress < chunk:
                    print(f"  数字にした問題 {state['seen']:,}", flush=True)
    flush(batch)
    ex = Examples(np.concatenate(id_parts) if id_parts else np.zeros(0, dtype=id_dtype),
                  np.array(starts, dtype=np.int64), np.array(prompt_len, dtype=np.int32),
                  np.array(length, dtype=np.int32), np.array(kinds, dtype=np.int16), kind_names)
    return ex, state["dropped"]


def collate(examples: Examples, indices, device):
    import torch
    seqs = [examples.get(i) for i in indices]
    width = max(len(s) for s, _ in seqs)
    input_ids = torch.full((len(seqs), width), PAD_ID, dtype=torch.long)
    labels = torch.full((len(seqs), width), -100, dtype=torch.long)
    mask = torch.zeros((len(seqs), width), dtype=torch.long)
    for row, (seq, plen) in enumerate(seqs):
        t = torch.from_numpy(np.asarray(seq, dtype=np.int64))
        input_ids[row, :len(seq)] = t
        mask[row, :len(seq)] = 1
        labels[row, plen:len(seq)] = t[plen:]
    return input_ids.to(device), mask.to(device), labels.to(device)


def epoch_batches(lengths, micro: int, seed: int, epoch: int):
    """seed と回数だけで決まる並び。長さの近い問題を同じ束にして詰め物を減らす。"""
    rng = np.random.default_rng(seed * 1000 + epoch)
    order = rng.permutation(len(lengths))
    chunk = micro * 50
    batches = []
    for s in range(0, len(order), chunk):
        part = order[s:s + chunk]
        part = part[np.argsort(lengths[part], kind="stable")]
        batches.extend(part[i:i + micro] for i in range(0, len(part), micro))
    return [batches[i] for i in rng.permutation(len(batches))]

# ------------------------------------------------------------------ 学習


def autocast_context(precision: str, device):
    import contextlib
    import torch
    if device.type != "cuda" or precision == "fp32":
        return contextlib.nullcontext()
    return torch.autocast("cuda", dtype=torch.bfloat16 if precision == "bf16" else torch.float16)


def _schedule(step, total, warmup, floor=0.1):
    if step < warmup:
        return (step + 1) / warmup
    progress = min(1.0, (step - warmup) / max(1, total - warmup))
    return floor + (1 - floor) * 0.5 * (1 + math.cos(math.pi * progress))


def _latest_checkpoint(root: Path):
    marks = sorted(p for p in root.glob("step-*") if (p / "state.json").exists())
    return marks[-1] if marks else None


def train(base_dir, train_ex: Examples, valid_ex: Examples, ckpt_root, final_dir, *, epochs: int, lr: float,
          profile: dict, seed: int, checkpoint_minutes: float = 20, warmup_ratio: float = 0.03,
          weight_decay: float = 0.01, keep: int = 1, gradient_checkpointing: bool = False,
          max_steps: int | None = None, log_every: int = 50, stop_after_seconds: float | None = None):
    """途中で切れても、ckpt_root の最新のチェックポイントから続ける。終われば final_dir に保存。
    チェックポイントは最新の keep 個だけ残す（既定 1。Google ドライブの空きが少ないため）。
    stop_after_seconds を渡すと、その時間で止めて保存し、None を返す（もう一度呼ぶと続きから）。"""
    import torch
    from transformers import GPT2LMHeadModel
    ckpt_root, final_dir = Path(ckpt_root), Path(final_dir)
    ckpt_root.mkdir(parents=True, exist_ok=True)
    for stale in ckpt_root.glob("tmp-*"):   # 保存の途中で切れた書きかけ（約1.1GB）。残すとドライブを圧迫する
        shutil.rmtree(stale, ignore_errors=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if device.type == "cuda":
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True
    micro, accum, precision = profile["micro"], profile["accum"], profile["precision"]
    batches_per_epoch = len(epoch_batches(train_ex.length, micro, seed, 0))
    steps_per_epoch = math.ceil(batches_per_epoch / accum)
    total_steps = max_steps or steps_per_epoch * epochs
    warmup = max(1, int(total_steps * warmup_ratio))

    latest = _latest_checkpoint(ckpt_root)
    source = latest or Path(base_dir)
    model = GPT2LMHeadModel.from_pretrained(source).float().to(device)
    if gradient_checkpointing:
        model.gradient_checkpointing_enable()
    model.train()
    no_decay = [p for n, p in model.named_parameters() if p.ndim < 2]
    decay = [p for n, p in model.named_parameters() if p.ndim >= 2]
    optimizer = torch.optim.AdamW([{"params": decay, "weight_decay": weight_decay},
                                   {"params": no_decay, "weight_decay": 0.0}], lr=lr, betas=(0.9, 0.98), eps=1e-6)
    scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lambda s: _schedule(s, total_steps, warmup))
    scaler = torch.amp.GradScaler("cuda", enabled=(precision == "fp16" and device.type == "cuda"))
    state = {"epoch": 0, "batch": 0, "step": 0, "tokens": 0, "seconds": 0.0, "history": []}
    torch.manual_seed(seed)
    if latest:
        extra = torch.load(latest / "optimizer.pt", map_location=device, weights_only=False)
        optimizer.load_state_dict(extra["optimizer"])
        scheduler.load_state_dict(extra["scheduler"])
        scaler.load_state_dict(extra["scaler"])
        torch.set_rng_state(extra["rng_cpu"])
        if device.type == "cuda" and extra.get("rng_cuda") is not None:
            torch.cuda.set_rng_state(extra["rng_cuda"])
        state = json.loads((latest / "state.json").read_text(encoding="utf-8"))
        print(f"続きから始めます: {latest.name}（{state['step']}/{total_steps} 歩、{state['epoch'] + 1} 回目の途中）")
    else:
        print(f"最初から始めます: 全部で {total_steps} 歩（1回 {steps_per_epoch} 歩 × {epochs} 回）")

    def save_checkpoint():
        tmp = ckpt_root / f"tmp-{state['step']:07d}"
        if tmp.exists():
            shutil.rmtree(tmp)
        model.save_pretrained(tmp, safe_serialization=True)
        torch.save({"optimizer": optimizer.state_dict(), "scheduler": scheduler.state_dict(),
                    "scaler": scaler.state_dict(), "rng_cpu": torch.get_rng_state(),
                    "rng_cuda": torch.cuda.get_rng_state() if device.type == "cuda" else None}, tmp / "optimizer.pt")
        (tmp / "state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        final = ckpt_root / f"step-{state['step']:07d}"
        if final.exists():
            shutil.rmtree(final)
        os.replace(tmp, final)
        for old in sorted(p for p in ckpt_root.glob("step-*"))[:-keep]:
            shutil.rmtree(old, ignore_errors=True)
        print(f"  チェックポイントを保存: {final.name}", flush=True)

    started = time.time()
    last_save = time.time()
    window_tokens, window_time = 0, time.time()
    rate = profile.get("units_per_hour")
    done = state["step"] >= total_steps
    while not done and state["epoch"] < epochs:
        batches = epoch_batches(train_ex.length, micro, seed, state["epoch"])
        while state["batch"] < len(batches):
            group = batches[state["batch"]:state["batch"] + accum]
            optimizer.zero_grad(set_to_none=True)
            loss_sum = 0.0
            for indices in group:
                input_ids, mask, labels = collate(train_ex, indices, device)
                with autocast_context(precision, device):
                    loss = model(input_ids=input_ids, attention_mask=mask, labels=labels).loss / len(group)
                scaler.scale(loss).backward()
                loss_sum += float(loss)
                n_tok = int(mask.sum())
                state["tokens"] += n_tok
                window_tokens += n_tok
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(optimizer)
            scaler.update()
            scheduler.step()
            state["batch"] += len(group)
            state["step"] += 1
            if state["step"] % log_every == 0:
                now = time.time()
                speed = window_tokens / max(1e-6, now - window_time)
                left_steps = total_steps - state["step"]
                tokens_per_step = window_tokens / log_every
                eta = left_steps * tokens_per_step / max(1.0, speed) / 60
                units = "" if rate is None else f"、残りのユニット 約{eta / 60 * rate:.1f}"
                print(f"  {state['step']}/{total_steps} 歩  損失 {loss_sum:.4f}  速さ {speed:,.0f} 字/秒  "
                      f"残り 約{eta:.0f} 分{units}", flush=True)
                state["history"].append([state["step"], round(loss_sum, 5)])
                window_tokens, window_time = 0, now
            if time.time() - last_save > checkpoint_minutes * 60:
                state["seconds"] += time.time() - started
                started = time.time()
                save_checkpoint()
                last_save = time.time()
            if state["step"] >= total_steps:
                done = True
                break
            if stop_after_seconds and time.time() - started > stop_after_seconds:
                state["seconds"] += time.time() - started
                save_checkpoint()
                print("  時間の上限で止めました（もう一度このセルを押すと続きから）")
                return None
        if state["batch"] >= len(batches):
            state["epoch"] += 1
            state["batch"] = 0
        model.eval()
        val = evaluate_loss(model, valid_ex, device, precision, profile["micro"])
        model.train()
        state["history"].append(["valid", state["epoch"], round(val, 5)])
        print(f"  {state['epoch']} 回目が終わりました。確かめ用の損失 {val:.4f}", flush=True)
        state["seconds"] += time.time() - started
        started = time.time()
        save_checkpoint()
        last_save = time.time()
    final_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(final_dir, safe_serialization=True)
    (final_dir / "train_state.json").write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    for name in ("vocab.json", "merges.txt", "tokenizer_config.json", "special_tokens_map.json"):
        shutil.copy(Path(base_dir) / name, final_dir / name)
    print(f"学習が終わりました: {final_dir}")
    return state

# ------------------------------------------------------------------ 評価


def evaluate_loss(model, examples: Examples, device, precision: str, batch: int = 64) -> float:
    import torch
    total, count = 0.0, 0
    with torch.no_grad():
        for s in range(0, len(examples), batch):
            indices = list(range(s, min(len(examples), s + batch)))
            input_ids, mask, labels = collate(examples, indices, device)
            with autocast_context(precision, device):
                logits = model(input_ids=input_ids, attention_mask=mask).logits.float()
            shift = logits[:, :-1].reshape(-1, logits.size(-1))
            target = labels[:, 1:].reshape(-1)
            loss = torch.nn.functional.cross_entropy(shift, target, ignore_index=-100, reduction="sum")
            total += float(loss)
            count += int((target != -100).sum())
    return total / max(1, count)


def greedy(model, prompts, end_ids, device, precision: str, max_new: int = 64, batch: int = 64):
    """問いだけを与えて、一番確かな字を順に選ぶ（左に詰め物をして束で計算）。"""
    import torch
    outputs = []
    for s in range(0, len(prompts), batch):
        part = prompts[s:s + batch]
        width = max(len(p) for p in part)
        ids = torch.full((len(part), width), PAD_ID, dtype=torch.long)
        mask = torch.zeros((len(part), width), dtype=torch.long)
        for row, p in enumerate(part):
            ids[row, width - len(p):] = torch.tensor(p, dtype=torch.long)
            mask[row, width - len(p):] = 1
        ids, mask = ids.to(device), mask.to(device)
        result = [[] for _ in part]
        finished = [False] * len(part)
        with torch.no_grad():
            for _ in range(max_new):
                positions = (mask.cumsum(-1) - 1).clamp(min=0)
                with autocast_context(precision, device):
                    logits = model(input_ids=ids, attention_mask=mask, position_ids=positions).logits[:, -1].float()
                nxt = logits.argmax(-1)
                for row, token in enumerate(nxt.tolist()):
                    if not finished[row]:
                        if token in end_ids:
                            finished[row] = True
                        else:
                            result[row].append(token)
                if all(finished):
                    break
                ids = torch.cat([ids, nxt[:, None]], dim=1)
                mask = torch.cat([mask, torch.ones_like(nxt[:, None])], dim=1)
        outputs.extend(result)
    return outputs


def evaluate(model, examples: Examples, tokenizer, end_id: int, device, precision: str,
             per_kind: int = 300, seed: int = 0, samples: int = 3) -> dict:
    """種類ごとの損失と、一番確かな答えが正解と完全に同じだった割合。"""
    rng = np.random.default_rng(seed)
    model.eval()
    report = {}
    for k, name in enumerate(examples.kind_names):
        idx = np.flatnonzero(examples.kinds == k)
        if len(idx) == 0:
            continue
        idx = np.sort(rng.permutation(idx)[:per_kind])
        sub = examples.subset(idx)
        loss = evaluate_loss(model, sub, device, precision)
        prompts, answers = [], []
        for i in range(len(sub)):
            seq, plen = sub.get(i)
            prompts.append([int(x) for x in seq[:plen]])
            answers.append([int(x) for x in seq[plen:-1]])
        got = greedy(model, prompts, {end_id}, device, precision,
                     max_new=min(96, max(len(a) for a in answers) + 4))
        exact = sum(g == a for g, a in zip(got, answers))
        report[name] = {"n": len(sub), "loss": loss, "exact": exact / len(sub),
                        "examples": [{"prompt": tokenizer.decode(prompts[i]), "answer": tokenizer.decode(answers[i]),
                                      "got": tokenizer.decode(got[i])} for i in range(min(samples, len(sub)))]}
    return report


def choose_end_token(model, examples: Examples, device, precision: str, candidates=(2, 3), n: int = 200) -> dict:
    """正解を書き終えた直後に、元の模型がどの終わりの記号を出すかを数える。"""
    import torch
    votes = {c: 0 for c in candidates}
    with torch.no_grad():
        for i in range(min(n, len(examples))):
            seq, _ = examples.get(i)
            ids = torch.tensor([[int(x) for x in seq[:-1]]], device=device)
            with autocast_context(precision, device):
                logits = model(input_ids=ids).logits[0, -1].float()
            best = max(candidates, key=lambda c: float(logits[c]))
            votes[best] += 1
    winner = max(votes, key=votes.get)
    return {"end_id": winner, "votes": votes}


def print_report(base: dict, tuned: dict | None = None):
    names = sorted(base)
    print(f"{'種類':<16} {'元の損失':>8} {'元の正解率':>10}" + ("" if tuned is None else f" {'新の損失':>8} {'新の正解率':>10} {'差':>7}"))
    for name in names:
        b = base[name]
        line = f"{name:<16} {b['loss']:8.4f} {b['exact'] * 100:9.1f}%"
        if tuned and name in tuned:
            t = tuned[name]
            line += f" {t['loss']:8.4f} {t['exact'] * 100:9.1f}% {(t['exact'] - b['exact']) * 100:+6.1f}"
        print(line)

# ------------------------------------------------------------------ 取得と llama.cpp の道具


def part_done(data_dir, name: str) -> bool:
    """練習問題の部品 name（text、wiki0of2 …）が作り終わっているか（目録 part-<name>.json は最後に書かれる）。"""
    return (Path(data_dir) / f"part-{name}.json").exists()


def data_ready(data_dir) -> bool:
    """練習問題が（集め終わって）そろっているか。昔の形（train.jsonl だけ）も読む。"""
    manifest = Path(data_dir) / "manifest.json"
    if not manifest.exists():
        return False
    try:
        info = json.loads(manifest.read_text(encoding="utf-8"))
    except ValueError:
        return False
    names = [f["name"] for f in info.get("train_files") or [{"name": "train.jsonl"}]] + ["valid.jsonl"]
    return all((Path(data_dir) / n).exists() for n in names)


def download(url: str, path, sha256: str | None = None) -> Path:
    """取ってきて SHA256 を確かめる。すでに正しいものがあれば取り直さない。"""
    import urllib.request
    path = Path(path)
    if path.exists() and (sha256 is None or sha256_file(path) == sha256):
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    urllib.request.urlretrieve(url, tmp)
    got = sha256_file(tmp)
    if sha256 and got != sha256:
        tmp.unlink()
        raise ValueError(f"SHA256 が合いません: {url}\n  期待 {sha256}\n  実際 {got}")
    os.replace(tmp, path)
    return path


def llama_tokenize_ids(binary, model_path, text: str) -> list[int]:
    import ast
    import subprocess
    out = subprocess.run([str(binary), "-m", str(model_path), "-p", text, "--ids", "--no-bos", "--log-disable"],
                         capture_output=True, check=True).stdout.decode("utf-8", "replace")
    line = [l for l in out.splitlines() if l.strip().startswith("[")][-1]
    return list(ast.literal_eval(line.strip()))


def llama_simple_answer(binary, model_path, prompt: str, n_predict: int = 48) -> str:
    """llama.cpp の llama-simple（一番確かな字を順に選ぶ）で答えを出し、問いの後ろだけを返す。"""
    import subprocess
    out = subprocess.run([str(binary), "-m", str(model_path), "-n", str(n_predict), prompt],
                         capture_output=True).stdout.decode("utf-8", "replace")
    tail = out.split("", 1)[1] if "" in out else out
    for stop in ("</s>", "<s>", "\n", "[PAD]"):
        tail = tail.split(stop, 1)[0]
    return tail


def materials_text(manifest: dict) -> str:
    """manifest.json の出典から、MODEL_CARD.md の「学習の材料」の行を作る（出典・版・利用条件・表示）。"""
    lines, attribution = [], {}
    for source in (manifest.get("domain") or {}).get("sources", []):
        attribution[source["name"]] = source.get("attribution")
    for source in manifest.get("sources", []):
        name = source["name"]
        if name.startswith("tools/data/") or name.endswith(".tsv") and "romanji" in name:
            continue
        line = f"  - {name}: {source.get('license', '')}"
        if source.get("commit"):
            line += f"（版 {source['commit']}）"
        if attribution.get(name):
            line += f"。表示: {attribution[name]}"
        lines.append(line)
    return "\n".join(lines)


MODEL_CARD = """# {name}

コンパウンドIME の試験用に、zenz-v3.2-small を追加学習したかな漢字変換の模型です（試作品）。

- 元の模型: Miwa-Keita/zenz-v3.2-small-gguf（{base_url}）。zenz は ku-nlp/gpt2-small-japanese-char
  （CC BY-SA 4.0）をもとに Miwa Keita さん（azooKey の作者）が学習した模型です。
- 学習の材料（出典の表示。試験の文 tests/conversion/ は学習に入れていません。詳しくは manifest.json）:
{materials}
  読みは SudachiPy・SudachiDict（Apache-2.0）で付けました。コンパウンドIME のリポジトリの一覧は MIT です。
- 利用条件: CC BY-SA 4.0（https://creativecommons.org/licenses/by-sa/4.0/deed.ja）。配るときは、
  この説明（出典の表示）を付け、同じ条件で配ってください。元の模型の配布ページは Apache-2.0 と表示していますが、
  もとになった模型と材料が CC BY-SA のため、こちらは CC BY-SA 4.0 として扱います。
- 変更点: 元の GGUF の量子化をほどき、{epochs} 回・学習率 {lr} で追加学習し、Q5_K_M に量子化し直しました。

SHA256: {sha256}
"""
