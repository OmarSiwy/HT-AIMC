"""The systolic reference's jobs (digital/sysreference/test/run_tests.py), reused unchanged,
plus the Hadamard-rotated variant of its SmolLM2 GEMM that the IMC format (ARCH_CHOSEN B7) runs."""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "digital/sysreference/test"))
import run_tests as SR          # noqa: E402  rand_job, sparse, real_job
import sched as SS              # noqa: E402  golden(X, W, scale, shift, offset)


def hadamard(K, seed=1234):
    """Block-diagonal randomized Hadamard (block = largest power of 2 dividing K), orthonormal."""
    b = K & -K
    H = np.ones((1, 1))
    while H.shape[0] < b:
        H = np.block([[H, H], [H, -H]])
    s = np.random.default_rng(seed + K).choice([-1.0, 1.0], b)
    Hb = s[:, None] * H / np.sqrt(b)
    return np.kron(np.eye(K // b), Hb)


def real_rot_job(n_out=None):
    """SmolLM2 blk.0 attn_q with x -> x H, W -> H^T W (exact in float), then INT8 per-tensor x
    and per-output-channel W, as SR.real_job does. n_out keeps the first n_out outputs."""
    from compiler import compile as CC
    from compiler.gguf_reader import tokenize_greedy
    from golden import model as G
    m = CC.load_model(CC.MODEL)
    ids = tokenize_greedy(CC.PROMPT, m["vocab"])
    A = CC.rms_rows(m["embd"][ids].astype(np.float64), m["attn_norm"], m["rms_eps"])
    Wf = m["gguf"].array("blk.0.attn_q.weight").astype(np.float64)     # (out, in)
    if n_out:
        Wf = Wf[:n_out]
    H = hadamard(A.shape[1])
    Ar, Wr = A @ H, Wf @ H                                              # (A H)(W H)^T = A W^T
    dw = np.max(np.abs(Wr), axis=1) / 127.0
    Wq = np.clip(np.rint(Wr / dw[:, None]), -127, 127).astype(np.int64)
    Xq, dx = G.quant_x_int8(Ar)
    dy = np.max(np.abs(A @ Wf.T)) / 127.0
    scale, shift = G.make_requant(dx * dw / dy)
    return dict(X=Xq, W=Wq.T, scale=scale, shift=shift, offset=np.zeros(Wq.shape[0], np.int64),
                yf=A @ Wf.T, dy=dy)


def systolic_jobs(rng):
    """Random GEMM/GEMV incl. extremes, as the systolic reference's regression draws them."""
    return [
        ("gemv_m1", SR.rand_job(rng, 1, 64, 48)),
        ("gemm_m16", SR.rand_job(rng, 16, 80, 32)),
        ("gemm_m37_pad", SR.rand_job(rng, 37, 50, 40)),
        ("sparse_x", SR.sparse(rng, SR.rand_job(rng, 16, 64, 32), 0.5)),
        ("extremes", dict(X=rng.choice([-128, 127, 0], (20, 256)), W=rng.choice([-128, 127], (256, 32)),
                          scale=np.full(32, 255), shift=rng.integers(0, 25, 32),
                          offset=rng.integers(-128, 128, 32))),
        ("edge_mixed", dict(X=rng.choice([-128, -1, 0, 1, 127], (8, 64)),
                            W=rng.choice([-128, -1, 0, 1, 127], (64, 16)),
                            scale=np.full(16, 1), shift=rng.integers(0, 25, 16),
                            offset=rng.integers(-128, 128, 16))),
    ]
