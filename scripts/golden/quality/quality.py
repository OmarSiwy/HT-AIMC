#!/usr/bin/env python3
"""Model-quality harness: SmolLM2-135M perplexity under an injectable analog-IMC
error model at every linear layer (Q, K, V, O, gate, up, down, LM head).

    from quality import Err, evaluate
    evaluate({"all": Err(w_fmt="int4", w_gran="group", w_group=128,
                         a_fmt="int8", rows=128, w_slice_bits=4, x_slice_bits=4,
                         adc_bits=8, noise=0.01)})
    -> {ppl, ppl_ref, delta_pct, delta_pct_se, top1_agree, n_tokens, seconds}

Every number this file produces is MEASURED (numpy emulation on the real
weights and real text). Field meanings are in README.md.

The emulated linear y = x W^T, per layer type, in order:
  1. co-design transforms (digital, exact in FP): SmoothQuant x/s, W*s;
     randomized block-Hadamard x R, W R  (R R^T = I, so FP output unchanged)
  2. weight / activation quantization to integer codes C with V ~ C * scale
     (int, fp8/6/4, log, MX = group-32 power-of-two scale)
  3. analog column (only if any analog field is set): codes split into
     sign-magnitude slices (weights: bits per cell; acts: bits per input
     pulse), K split into row tiles; per (w-slice, x-slice, row-tile) partial:
       P' = P*(1+gain_col) + offset_col*FS + noise*FS*N(0,1)
       ADC: P^ = clip(round(P'/LSB)) * LSB, LSB = FS / 2^(adc_bits-1)
     FS = rows*dmax_w*dmax_x ("max", worst-case swing: pure LSB truncation)
       or adc_fs*std(P) (statistical +-k sigma clip, 27h6 / law:bout),
     frozen from a calibration window disjoint from the eval text.
  4. digital shift-add recombination, per-channel/group/token scales.
"""
import argparse
import dataclasses
import hashlib
import json
import math
import os
import re
import sys
import time
from dataclasses import dataclass

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from compiler.gguf_reader import GGUF          # noqa: E402
from compiler.formats import FORMATS           # noqa: E402

MODEL = os.path.join(ROOT, "scripts", "models", "smollm2-135m-q8_0.gguf")
TEXT = os.path.join(HERE, "data", "wikitext2_test_head.txt")
OUT = os.path.join(HERE, "out")
SEQ = 512                       # tokens per window (= ARCH_METRIC prompt length)
N_WIN = 4                       # eval windows -> 4*511 = 2044 scored tokens
KINDS = ("q", "k", "v", "o", "gate", "up", "down", "head")
GGUF_NAME = {"q": "attn_q", "k": "attn_k", "v": "attn_v", "o": "attn_output",
             "gate": "ffn_gate", "up": "ffn_up", "down": "ffn_down"}
HEAD = -1                       # layer index used for the LM head
_MX = {"mxfp8": "fp8_e4m3", "mxfp8_e5m2": "fp8_e5m2", "mxfp6": "fp6_e2m3",
       "mxfp4": "fp4_e2m1", "mxint8": "int8", "mxint4": "int4"}


@dataclass(frozen=True)
class Err:
    """Error model of one linear-layer type. Defaults = exact (no error)."""
    # quantization
    w_fmt: str = None           # int2..int8 | fp8_e4m3 | fp8_e5m2 | fp6_e2m3 | fp6_e3m2 | fp4 | log3..log8 | mxfp8 | mxfp6 | mxfp4 | mxint8
    w_gran: str = "channel"     # channel (per output row) | group | tensor
    w_group: int = 128          # group size along K (w_gran=group)
    w_pow2: bool = False        # power-of-two shared scale (MX E8M0)
    w_clip: float = 1.0         # scale = w_clip*absmax / fmt max
    a_fmt: str = None           # same formats as w_fmt
    a_gran: str = "token"       # token (dynamic per token) | tensor (static, calibrated) | group (dynamic per token-group)
    a_group: int = 32
    a_pow2: bool = False
    a_clip: float = 1.0         # input clipping: saturate at a_clip*absmax
    # analog column
    rows: int = None            # rows summed per conversion (None = all K)
    w_slice_bits: int = None    # magnitude bits per weight cell (None = whole code in one column)
    x_slice_bits: int = None    # magnitude bits per input pulse (1 = bit-serial, 4 = PWM nibble, None = full DAC)
    adc_bits: int = None        # per-partial ADC resolution (None = ideal)
    adc_fs: object = 4.0        # float k: FS = k*std(partial) ; "max": worst-case physical swing
    noise: float = 0.0          # additive Gaussian sigma / FS, fresh per conversion
    gain: float = 0.0           # static per-column gain error sigma (relative)
    offset: float = 0.0         # static per-column offset sigma / FS
    # co-design levers
    hadamard: bool = False      # randomized block-Hadamard rotation of K
    smooth: float = None        # SmoothQuant alpha (None = off)
    seed: int = 0

    def norm(self):
        e = self
        if e.w_fmt in _MX:
            e = dataclasses.replace(e, w_fmt=_MX[e.w_fmt], w_gran="group", w_group=32, w_pow2=True)
        if e.a_fmt in _MX:
            e = dataclasses.replace(e, a_fmt=_MX[e.a_fmt], a_gran="group", a_group=32, a_pow2=True)
        return e

    def analog(self):
        return bool(self.rows or self.w_slice_bits or self.x_slice_bits or self.adc_bits
                    or self.noise or self.gain or self.offset)


def resolve(error_model):
    """{"all": Err, "head": Err|None, "q": ...} | Err | None -> {kind: Err|None}."""
    if error_model is None or isinstance(error_model, Err):
        error_model = {"all": error_model}
    bad = set(error_model) - set(KINDS) - {"all"}
    assert not bad, f"unknown layer kinds {bad}; use {KINDS} or 'all'"
    em = {k: error_model.get(k, error_model.get("all")) for k in KINDS}
    return {k: (e.norm() if e is not None else None) for k, e in em.items()}


# ---------------------------------------------------------------------------
# tokenizer: byte-level BPE with the GGUF merges (llama.cpp pre-type "smollm":
# isolated digits, then the GPT-2 split regex). \p{L}/\p{N} approximated with
# stdlib re classes; ids checked identical to the HF tokenizer on the data file.
# ---------------------------------------------------------------------------
_SPLIT = re.compile(r"""'s|'t|'re|'ve|'m|'ll|'d| ?[^\W\d_]+| ?\d+| ?(?:[^\s\w]|_)+|\s+(?!\S)|\s+""")


def _byte_map():
    bs = list(range(33, 127)) + list(range(161, 173)) + list(range(174, 256))
    cs, n = bs[:], 0
    for b in range(256):
        if b not in bs:
            bs.append(b)
            cs.append(256 + n)
            n += 1
    return {b: chr(c) for b, c in zip(bs, cs)}


def tokenize(text, tokens, merges):
    b2u = _byte_map()
    vocab = {t: i for i, t in enumerate(tokens)}
    ranks = {tuple(m.split(" ", 1)): r for r, m in enumerate(merges)}
    cache, ids = {}, []
    for seg in re.split(r"(\d)", text):
        for w in _SPLIT.findall(seg):
            if w not in cache:
                parts = [b2u[b] for b in w.encode("utf-8")]
                while len(parts) > 1:
                    r, i = min((ranks.get(p, math.inf), i)
                               for i, p in enumerate(zip(parts, parts[1:])))
                    if r == math.inf:
                        break
                    parts[i:i + 2] = [parts[i] + parts[i + 1]]
                cache[w] = [vocab[p] for p in parts]
            ids += cache[w]
    return ids


# ---------------------------------------------------------------------------
# model (fp32 dequantized Q8_0 weights; the GGUF IS the "unperturbed" model)
# ---------------------------------------------------------------------------
class Model:
    def __init__(self, path=MODEL):
        g = GGUF(path)
        m = g.meta
        self.NL, self.D = m["llama.block_count"], m["llama.embedding_length"]
        self.NH, self.NKV = m["llama.attention.head_count"], m["llama.attention.head_count_kv"]
        self.DH = self.D // self.NH
        self.eps = float(m["llama.attention.layer_norm_rms_epsilon"])
        self.base = float(m["llama.rope.freq_base"])
        self.tokens, self.merges = m["tokenizer.ggml.tokens"], m["tokenizer.ggml.merges"]
        self.E = np.ascontiguousarray(g.array("token_embd.weight"), dtype=np.float32)
        self.W = {(HEAD, "head"): self.E}                     # tied LM head
        self.norm = {"out": g.array("output_norm.weight").astype(np.float32)}
        for li in range(self.NL):
            for k, n in GGUF_NAME.items():
                self.W[li, k] = g.array(f"blk.{li}.{n}.weight").astype(np.float32)
            self.norm[li, "attn"] = g.array(f"blk.{li}.attn_norm.weight").astype(np.float32)
            self.norm[li, "ffn"] = g.array(f"blk.{li}.ffn_norm.weight").astype(np.float32)
        self.WT = {k: np.ascontiguousarray(w.T) for k, w in self.W.items()}

    def _rms(self, x, w):
        return x / np.sqrt((x * x).mean(-1, keepdims=True) + self.eps) * w

    def _rope(self, x):                                   # x (B, T, H, DH), NORM style
        T, d = x.shape[1], x.shape[-1]
        th = np.arange(T)[:, None] * np.power(self.base, -np.arange(0, d, 2) / d)[None]
        c, s = np.cos(th).astype(np.float32)[:, None], np.sin(th).astype(np.float32)[:, None]
        a, b = x[..., 0::2], x[..., 1::2]
        y = np.empty_like(x)
        y[..., 0::2], y[..., 1::2] = a * c - b * s, a * s + b * c
        return y

    def forward(self, ids, lin):
        """ids (B, T) -> logits (B*T, V). lin(li, kind, x2d) -> y2d."""
        B, T = ids.shape
        x = self.E[ids].reshape(B * T, self.D)
        mask = np.triu(np.full((T, T), -np.inf, np.float32), 1)
        rep = self.NH // self.NKV
        for li in range(self.NL):
            a = self._rms(x, self.norm[li, "attn"])
            q = self._rope(lin(li, "q", a).reshape(B, T, self.NH, self.DH))
            k = self._rope(lin(li, "k", a).reshape(B, T, self.NKV, self.DH))
            v = lin(li, "v", a).reshape(B, T, self.NKV, self.DH)
            k, v = np.repeat(k, rep, 2), np.repeat(v, rep, 2)
            s = q.transpose(0, 2, 1, 3) @ k.transpose(0, 2, 3, 1) / np.float32(math.sqrt(self.DH)) + mask
            p = np.exp(s - s.max(-1, keepdims=True))
            p /= p.sum(-1, keepdims=True)
            o = (p @ v.transpose(0, 2, 1, 3)).transpose(0, 2, 1, 3).reshape(B * T, self.D)
            x = x + lin(li, "o", o)
            f = self._rms(x, self.norm[li, "ffn"])
            g, u = lin(li, "gate", f), lin(li, "up", f)
            x = x + lin(li, "down", g / (1.0 + np.exp(-g)) * u)
        return lin(HEAD, "head", self._rms(x, self.norm["out"]))


# ---------------------------------------------------------------------------
# quantizers
# ---------------------------------------------------------------------------
def fmt_table(fmt):
    """Sorted non-negative magnitudes of a format (all integer multiples of t[1])."""
    if fmt.startswith("int"):
        return np.arange(2 ** (int(fmt[3:]) - 1), dtype=np.float64)
    if fmt.startswith("log"):              # sign + (b-1) bits: 0 and 2^-k, k=0..2^(b-1)-2
        kmax = 2 ** (int(fmt[3:]) - 1) - 2
        return np.concatenate([[0.0], 2.0 ** np.arange(-kmax, 1)])
    t = FORMATS[fmt]._table
    return np.unique(np.abs(t[np.isfinite(t)]))


def quantize(V, fmt, gran, group, pow2, clip, amax=None):
    """V (N, K) -> (codes (N,K) integer-valued float32, scale (N|1, G), g) with
    V ~ codes * expand(scale). G = 1 (g = K) unless gran == 'group'.
    amax: static absmax (a_gran=tensor) overriding the data."""
    N, K = V.shape
    t = fmt_table(fmt)
    ulp, top = t[1], t[-1]
    if gran == "group":
        g = group
        Vp = np.pad(V, ((0, 0), (0, -K % g))).reshape(N, -1, g)
        am = np.abs(Vp).max(-1)                               # (N, G)
    else:
        g = K
        am = (np.abs(V).max(-1, keepdims=True) if gran in ("channel", "token")
              else np.full((1, 1), np.abs(V).max() if amax is None else amax))
    am = np.where(am > 0, am, 1.0).astype(np.float64)
    s = 2.0 ** (np.floor(np.log2(am)) - np.floor(np.log2(top))) if pow2 else clip * am / top
    u = (Vp if gran == "group" else V[:, None, :]) / s[..., None]
    if fmt.startswith("int"):
        c = np.clip(np.rint(u), -top, top)
    else:
        mids = (t[1:] + t[:-1]) / 2
        c = np.sign(u) * t[np.searchsorted(mids, np.abs(u))] / ulp
    c = c.reshape(N, -1)[:, :K].astype(np.float32)
    return c, (s * ulp).astype(np.float32), g


def expand(scale, g, K):
    return np.repeat(scale, g, axis=1)[:, :K] if scale.shape[1] > 1 else scale


def code_max(fmt):
    t = fmt_table(fmt)
    return int(round(t[-1] / t[1]))


def _hadamard(K, seed=1234):
    """Block-diagonal randomized Hadamard: block = largest power of 2 dividing K."""
    b = K & -K
    H = np.ones((1, 1))
    while H.shape[0] < b:
        H = np.block([[H, H], [H, -H]])
    sg = np.random.default_rng(seed + K).choice([-1.0, 1.0], b)
    return (sg[:, None] * H / math.sqrt(b)).astype(np.float32)


def rotate(x, Rb):
    b = Rb.shape[0]
    return (x.reshape(x.shape[0], -1, b) @ Rb).reshape(x.shape)


def digits(C, bits, cmax):
    """Sign-magnitude slices: sum_i sig_i * D_i == C exactly; sign rides every
    slice (differential cell / signed pulse). Returns [(sig, D int8|f32, dmax)]."""
    if not bits:
        return [(1.0, C, cmax)]
    a, s = np.abs(C).astype(np.int64), np.sign(C).astype(np.int64)
    n = max(1, math.ceil(math.log2(cmax + 1) / bits))
    m = 2 ** bits - 1
    return [(float(2 ** (bits * i)), (s * ((a >> (bits * i)) & m)).astype(np.int8),
             min(m, cmax >> (bits * i))) for i in range(n)]


# ---------------------------------------------------------------------------
# prepared weights (cached across evaluate() calls with the same weight fields)
# ---------------------------------------------------------------------------
_M, _REF, _PREP = None, None, {}
WFIELDS = ("w_fmt", "w_gran", "w_group", "w_pow2", "w_clip", "hadamard", "smooth",
           "rows", "w_slice_bits")


def model():
    global _M
    if _M is None:
        _M = Model()
    return _M


def prep(li, kind, e, calib_amax):
    key = (li, kind) + tuple(getattr(e, f) for f in WFIELDS) + (e.analog(),)
    if key in _PREP:
        return _PREP[key]
    W = model().W[li, kind]
    O, K = W.shape
    p = {"s": None, "R": None}
    if e.smooth is not None:
        aw = np.abs(W).max(0)
        s = np.maximum(calib_amax[li, kind], 1e-5) ** e.smooth / np.maximum(aw, 1e-5) ** (1 - e.smooth)
        p["s"] = s.astype(np.float32)
        W = W * p["s"]
    if e.hadamard:
        p["R"] = _hadamard(K)
        W = rotate(W, p["R"])
    if e.w_fmt is None:
        p["WT"] = np.ascontiguousarray(W.T)
    else:
        C, sc, g = quantize(W, e.w_fmt, e.w_gran, e.w_group, e.w_pow2, e.w_clip)
        if e.analog():
            rows = e.rows or K
            if e.w_gran == "group":
                assert e.rows in (None, g), "analog path: per-group weight scale needs rows == w_group (scale applied per row tile)"
                rows = g
            R = -(-K // rows)
            Cp = np.pad(C, ((0, 0), (0, R * rows - K)))
            p.update(rows=rows, nt=R, ws=sc.T[:, None, :],                      # (G, 1, O)
                     wd=[(sig, D.reshape(O, R, rows).transpose(1, 2, 0).copy(), dm)
                         for sig, D, dm in digits(Cp, e.w_slice_bits, code_max(e.w_fmt))])
        else:
            p["WT"] = np.ascontiguousarray((C * expand(sc, g, K)).T)
    _PREP[key] = p
    return p


# ---------------------------------------------------------------------------
# the perturbed linear
# ---------------------------------------------------------------------------
def make_lin(em, st, calib_amax, rng):
    """st: calibration state; keys absent -> measured now and stored (calib
    pass), present -> frozen (eval pass)."""
    def lin(li, kind, x):
        e = em[kind]
        if e is None:
            return x @ model().WT[li, kind]
        p = prep(li, kind, e, calib_amax)
        if p["s"] is not None:
            x = x / p["s"]
        if p["R"] is not None:
            x = rotate(x, p["R"])
        if e.a_fmt is not None:
            amax = None
            if e.a_gran == "tensor":
                amax = st.setdefault(("amax", li, kind), float(np.abs(x).max()))
            xc, xs, xg = quantize(x, e.a_fmt, e.a_gran, e.a_group, e.a_pow2, e.a_clip, amax)
        if not e.analog():
            return (x if e.a_fmt is None else xc * expand(xs, xg, x.shape[1])) @ p["WT"]
        assert e.w_fmt and e.a_fmt, "analog fields need w_fmt and a_fmt (integer codes)"
        assert xs.shape[1] == 1, "analog path: activation scale must be per token or per tensor"
        return analog_mvm(li, kind, e, p, xc, st, rng) * xs
    return lin


_POOL = None


def _noise(rng, shape):
    """N(0,1) block of `shape`: a contiguous window at a random offset of a fixed
    2^26-sample pool. ponytail: fresh normals cost ~10 ns each (4x slower overall,
    >4 min per config); the pool reuses samples at random alignments, so every
    conversion is still N(0,1) and cross-conversion correlation is negligible.
    Swap for rng.standard_normal if a study needs strictly independent draws."""
    global _POOL
    if _POOL is None:
        _POOL = np.random.default_rng(987).standard_normal(1 << 26, dtype=np.float32)
    n = math.prod(shape)
    o = int(rng.integers(0, _POOL.size - n + 1))
    return _POOL[o:o + n].reshape(shape)


def analog_mvm(li, kind, e, p, xc, st, rng):
    T, K = xc.shape
    R, rows, O = p["nt"], p["rows"], p["ws"].shape[-1]
    xd = digits(np.pad(xc, ((0, 0), (0, R * rows - K))), e.x_slice_bits, code_max(e.a_fmt))
    y = np.zeros((T, O), np.float32)
    chunk = max(1, min(T, (1 << 25) // (R * O)))
    for si, (sw, Dw, dw) in enumerate(p["wd"]):
        Wf = Dw.astype(np.float32)                                          # (R, rows, O)
        crng = np.random.default_rng([e.seed, li + 1, KINDS.index(kind), si])
        gain = (1 + e.gain * crng.standard_normal((R, 1, O))).astype(np.float32) if e.gain else None
        offs = e.offset * crng.standard_normal((R, 1, O)).astype(np.float32) if e.offset else None
        for ti, (sx, Dx, dx) in enumerate(xd):
            key = (li, kind, si, ti)
            for c0 in range(0, T, chunk):
                Xc = Dx[c0:c0 + chunk].astype(np.float32)
                P = Xc.reshape(-1, R, rows).transpose(1, 0, 2) @ Wf           # (R, t, O)
                if key not in st:
                    st[key] = (rows * dw * dx if e.adc_fs == "max"
                               else float(e.adc_fs) * float(P.std()) or 1.0)
                fs = st[key]
                if gain is not None:
                    P *= gain
                if offs is not None:
                    P += offs * fs
                if e.noise and rng is not None:                              # rng None = calibration pass
                    P += (e.noise * fs) * _noise(rng, P.shape)
                if e.adc_bits:
                    lsb = fs / 2 ** (e.adc_bits - 1)
                    np.clip(np.rint(P / lsb), -2 ** (e.adc_bits - 1), 2 ** (e.adc_bits - 1) - 1, out=P)
                    P *= lsb
                y[c0:c0 + chunk] += (sw * sx) * (P * p["ws"]).sum(0)
    return y


# ---------------------------------------------------------------------------
# evaluation
# ---------------------------------------------------------------------------
def _windows(n_win):
    m = model()
    ids = tokenize(open(TEXT, encoding="utf-8").read(), m.tokens, m.merges)
    assert len(ids) >= (n_win + 1) * SEQ, f"data file holds {len(ids)} tokens"
    ev = np.array(ids[:n_win * SEQ]).reshape(n_win, SEQ)
    cal = np.array(ids[n_win * SEQ:(n_win + 1) * SEQ])[None]                # disjoint
    return ev, cal


def _score(logits, ids):
    """Per-token NLL of the next token and argmax, positions 0..T-2 per window."""
    B, T = ids.shape
    lg = logits.reshape(B, T, -1)[:, :-1].reshape(B * (T - 1), -1)
    tgt = ids[:, 1:].reshape(-1)
    nll = np.empty(len(tgt))
    for c in range(0, len(tgt), 512):
        z = lg[c:c + 512].astype(np.float64)
        z -= z.max(-1, keepdims=True)
        nll[c:c + 512] = np.log(np.exp(z).sum(-1)) - z[np.arange(len(z)), tgt[c:c + 512]]
    return nll, lg.argmax(-1)


def reference(n_win=N_WIN):
    """FP reference: cached on disk (out/) and in memory. Also records per-channel
    input absmax of every linear on the calibration window (for smoothing)."""
    global _REF
    if _REF is not None and _REF["n_win"] == n_win:
        return _REF
    h = hashlib.sha256(open(TEXT, "rb").read() + f"{os.path.getsize(MODEL)}|{SEQ}|{n_win}|v1".encode()).hexdigest()[:16]
    path = os.path.join(OUT, f"ref_{h}.npz")
    m = model()
    ev, cal = _windows(n_win)
    if os.path.exists(path):
        z = np.load(path, allow_pickle=True)
        _REF = {"nll": z["nll"], "arg": z["arg"], "amax": z["amax"].item()}
    else:
        amax = {}

        def rec(li, kind, x):
            amax[li, kind] = np.abs(x).max(0)
            return x @ m.WT[li, kind]
        m.forward(cal, rec)
        nll, arg = _score(m.forward(ev, lambda li, k, x: x @ m.WT[li, k]), ev)
        os.makedirs(OUT, exist_ok=True)
        np.savez(path, nll=nll, arg=arg, amax=np.array(amax, dtype=object))
        _REF = {"nll": nll, "arg": arg, "amax": amax}
    _REF.update(n_win=n_win, ev=ev, cal=cal)
    return _REF


def evaluate(error_model, n_win=N_WIN, seed=0):
    """error_model: Err | {"all"|kind: Err|None} | None -> quality dict (measured)."""
    t0 = time.time()
    em = resolve(error_model)
    ref, m = reference(n_win), model()
    rng = np.random.default_rng(seed)
    st = {}
    if any(e is not None and (e.analog() or e.a_gran == "tensor") for e in em.values()):
        m.forward(ref["cal"], make_lin(em, st, ref["amax"], None))          # calibration pass (noise off)
    nll, arg = _score(m.forward(ref["ev"], make_lin(em, st, ref["amax"], rng)), ref["ev"])
    d = nll - ref["nll"]
    ppl, ppl_ref = math.exp(nll.mean()), math.exp(ref["nll"].mean())
    return {"ppl": ppl, "ppl_ref": ppl_ref, "delta_pct": 100 * (ppl / ppl_ref - 1),
            "delta_pct_se": float(100 * (ppl / ppl_ref) * d.std() / math.sqrt(len(d))),
            "top1_agree": float((arg == ref["arg"]).mean()),
            "n_tokens": int(len(nll)), "seconds": round(time.time() - t0, 1)}


# ---------------------------------------------------------------------------
# CLI + first sweep
# ---------------------------------------------------------------------------
def _parse(sets):
    kw = {}
    types = {f.name: f.type for f in dataclasses.fields(Err)}
    for s in sets:
        k, v = s.split("=", 1)
        assert k in types, f"unknown field {k}"
        if v.lower() in ("none", ""):
            kw[k] = None
        elif types[k] is bool:
            kw[k] = v.lower() in ("1", "true", "yes")
        elif types[k] is object:
            kw[k] = v if v == "max" else float(v)
        else:
            kw[k] = types[k](v)
    return Err(**kw)


def sweep():
    """First sweep (README): INT8 / INT4-g128 / FP8 weights x INT8 per-token acts,
    rows=128, 4b cells, 4b PWM input nibbles, ADC +-4 sigma."""
    hw = dict(a_fmt="int8", rows=128, w_slice_bits=4, x_slice_bits=4)
    W = {"int8": dict(w_fmt="int8"), "int4g128": dict(w_fmt="int4", w_gran="group", w_group=128),
         "fp8_e4m3": dict(w_fmt="fp8_e4m3")}
    runs = []
    for wn, w in W.items():
        runs.append((wn, "quant only", Err(a_fmt="int8", **w)))
        for b in (4, 5, 6, 7, 8, 9, 10):
            runs.append((wn, f"adc{b}", Err(adc_bits=b, **hw, **w)))
        for n in (0.001, 0.003, 0.01, 0.03):
            runs.append((wn, f"noise{n:g}", Err(noise=n, **hw, **w)))
        runs.append((wn, "adc8+noise0.01", Err(adc_bits=8, noise=0.01, **hw, **w)))
    for b in (8, 10, 12):          # 27h6: LSB truncation at the worst-case range
        runs.append(("int8", f"adc{b} FS=max", Err(adc_bits=b, adc_fs="max", w_fmt="int8", **hw)))
    for k in (8.0, 16.0):          # wider statistical range: clipping vs LSB trade
        runs.append(("int8", f"adc8 FS={k:g}sigma", Err(adc_bits=8, adc_fs=k, w_fmt="int8", **hw)))
    for b, k in ((6, 16.0), (10, 16.0), (6, 32.0), (8, 32.0), (10, 32.0)):   # follow-up: ADC bits at a wide range
        runs.append(("int8", f"adc{b} FS={k:g}sigma", Err(adc_bits=b, adc_fs=k, w_fmt="int8", **hw)))
    runs.append(("int8", "adc8 FS=16sigma+noise0.003", Err(adc_bits=8, adc_fs=16.0, noise=0.003, w_fmt="int8", **hw)))
    runs.append(("int8", "adc8, LM head exact", {"all": Err(adc_bits=8, w_fmt="int8", **hw), "head": None}))
    for lev, kw in (("hadamard", dict(hadamard=True)), ("smooth0.5", dict(smooth=0.5))):
        runs.append(("int4g128", f"quant only +{lev}", Err(a_fmt="int8", **W["int4g128"], **kw)))
        runs.append(("int4g128", f"adc6 +{lev}", Err(adc_bits=6, **hw, **W["int4g128"], **kw)))
        runs.append(("int4g128", f"noise0.01 +{lev}", Err(noise=0.01, **hw, **W["int4g128"], **kw)))
    runs.append(("int4", "quant only (per-channel)", Err(w_fmt="int4", a_fmt="int8")))
    runs.append(("int8", "quant only, a per-tensor static", Err(w_fmt="int8", a_fmt="int8", a_gran="tensor")))
    # resumable: rows already in out/sweep.md are skipped, new rows appended as they finish
    path = os.path.join(OUT, "sweep.md")
    os.makedirs(OUT, exist_ok=True)
    if not os.path.exists(path):
        open(path, "w").write("| weights | config | PPL | dPPL % | +-se | top-1 agree | s |\n|---|---|---|---|---|---|---|\n")
    done = {tuple(c.strip() for c in l.split("|")[1:3]) for l in open(path) if l.startswith("| ")}
    for wn, cfg, e in runs:
        if (wn, cfg) in done:
            continue
        r = evaluate(e if isinstance(e, dict) else {"all": e})
        row = (f"| {wn} | {cfg} | {r['ppl']:.3f} | {r['delta_pct']:+.2f} | {r['delta_pct_se']:.2f} "
               f"| {100 * r['top1_agree']:.1f}% | {r['seconds']} |")
        print(row, flush=True)
        open(path, "a").write(row + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--set", action="append", default=[], metavar="FIELD=VAL",
                    help="Err field for every linear (repeatable), e.g. --set w_fmt=int4")
    ap.add_argument("--head", action="append", default=None, metavar="FIELD=VAL|fp",
                    help="separate Err for the LM head; '--head fp' keeps it exact")
    ap.add_argument("--only", default=None, help="comma list of kinds to perturb (others exact)")
    ap.add_argument("--windows", type=int, default=N_WIN)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--sweep", action="store_true", help="run the README first sweep")
    a = ap.parse_args()
    if a.sweep:
        return sweep()
    e = _parse(a.set)
    em = {"all": e} if a.only is None else {k: (e if k in a.only.split(",") else None) for k in KINDS}
    if a.head is not None:
        em["head"] = None if a.head == ["fp"] else _parse(a.head)
    print(json.dumps({"error_model": {k: (dataclasses.asdict(v) if v else None) for k, v in resolve(em).items()},
                      **evaluate(em, a.windows, a.seed)}, indent=1))


if __name__ == "__main__":
    main()
