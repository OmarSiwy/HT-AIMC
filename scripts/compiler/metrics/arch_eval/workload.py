"""Llama-3 shapes (8B default; 70B for the Sohu conditions) and per-request op/byte counts
(ARCH_METRIC 'Workload', 'Request').

Dims are reused from imc_architecture_search.MODELS["8B-class"] (Llama 3 Table 3).
That table rounds the vocabulary to 128,000 (7,503,609,856 weight MACs/token);
ARCH_METRIC names the real 128,256 (7,504,658,432, +0.014 %). Scoring uses the
ARCH_METRIC value; `llama3_8b(vocab=128000)` reproduces the search script's count.
"""
from . import ROOT  # noqa: F401  (sets sys.path)
from imc_architecture_search import MODELS, shapes

PROMPT, GEN = 512, 128


def llama3(model="8B-class", vocab=128256, prompt=PROMPT, gen=GEN, kv_bits=16):
    m = dict(MODELS[model], vocab=vocab)
    L, d, hq, hkv = m["layers"], m["d"], m["hq"], m["hkv"]
    dh = d // hq
    mats = [(a, b, L) for a, b in shapes(m)] + [(d, m["vocab"], 1)]  # + LM head
    w_macs = sum(a * b * r for a, b, r in mats)
    att_per_ctx = 2 * L * hq * dh            # QK^T + A.V MACs per token per context position
    kv_elems = 2 * L * hkv * dh               # K and V elements stored per token
    ctx_prefill = sum(range(1, prompt + 1))   # causal: token t attends to t positions
    ctx_decode = sum(range(prompt + 1, prompt + gen + 1))
    return dict(
        model=m, dh=dh, matrices=mats, prompt=prompt, gen=gen, tokens=prompt + gen,
        stages=4 * L + 1,                       # serial weight stages per token (QKV, O, gate/up, down; + head)
        weight_macs_per_token=w_macs,
        stored_weights=w_macs,                  # embedding table lives in DRAM (one row read per token)
        att_macs_per_ctx=att_per_ctx,
        att_macs_prefill=att_per_ctx * ctx_prefill,   # per request
        att_macs_decode=att_per_ctx * ctx_decode,
        softmax_exps_prefill=L * hq * ctx_prefill, softmax_exps_decode=L * hq * ctx_decode,
        kv_bits=kv_bits, kv_bytes_per_token=kv_elems * kv_bits / 8,
        ctx_prefill_sum=ctx_prefill, ctx_decode_sum=ctx_decode,
        act_bytes_per_token=2 * m["d"],         # 16-bit residual stream crossing a die boundary
        # RMSNorm x2, RoPE, residual adds, requant ~10 ops/elem of d; SwiGLU ~3 ops/elem of f
        elem_ops_per_token=L * (10 * d + 3 * m["f"]),
        embed_bytes=m["vocab"] * d * 2,
    )


def llama3_8b(**kw):
    return llama3("8B-class", **kw)


def tiles(wl, rows, cols):
    """Tile count for one copy of every weight matrix (ceil tiling per matrix)."""
    return sum(-(-a // rows) * -(-b // cols) * r for a, b, r in wl["matrices"])


if __name__ == "__main__":
    w = llama3_8b()
    print({k: v for k, v in w.items() if k not in ("model", "matrices")})
