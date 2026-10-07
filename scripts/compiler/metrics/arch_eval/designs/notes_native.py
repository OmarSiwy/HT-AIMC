"""notes_native: the notes/paper-native architecture (architect panel, 2026-10-06).

    python3 notes_native.py              # score designs/notes_native.json + baselines -> notes_native.score.json
    python3 notes_native.py --quality    # KV-format quality on the SmolLM2 proxy  -> notes_native.quality.json
    python3 notes_native.py --entropy    # weight-code entropy on the SmolLM2 proxy -> notes_native.quality.json
    python3 notes_native.py --selfcheck  # asserts on the cost-model patch (PASS/FAIL)

Write-up: docs/src/content/Project/ArchResearch/architects/notes_native.md.

The search's winner sits on a system ceiling (B <= KV capacity, decode on HBM). This design moves
the ceiling with two memory-side number formats the search grid cannot express, then re-tunes the
tile for the regime that results (prefill becomes tile-compute-bound, so tile density counts again):

  1. KV "4/8 sink+recent" (paper sec_attention.tex, 27l10, feng2026selective): K and V rotated by a
     per-head randomized Hadamard (QuaRot), stored as a 4 b per-token-per-head code; the m sink and
     r most recent tokens also keep a 4 b residual plane (= 8 b). When a token leaves the recent
     window its residual plane is dropped: no requantization (Fixed-Point Format Narrowing).
  2. Entropy-coded weight stream (optional, measured): the INT8 weight codes are Huffman-coded in
     HBM in independent chunks and decoded at the HBM PHY before the tile write path.

Cost-model hooks the nodes lack (implemented here, applied identically to the systolic baseline,
because KV width and weight compression are symmetric levers, N8 fairness rule):
  kv bytes/token   = kv_elems x b_eff / 8, b_eff = b_lo + 16/dh_scale + (b_hi - b_lo) min(m+r, ctx)/ctx
                     (ctx = mean decode context, the conservative end; capacity uses the same b_eff)
  stored weights   x w_stream_bits / wbits (HBM bytes and HBM capacity)
  entropy decoder  area dec_mm2, energy dec_pJ_per_B on every HBM byte (projected, see DEC)
  rail lanes       area x (1 + f_hi (A8/A4 - 1)): the sink+recent share needs 8 b K/V lanes
"""
import argparse
import heapq
import json
import math
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))                     # scripts/compiler/metrics
from arch_eval import ROOT, baseline_systolic, design, metric, model, search  # noqa: E402

DESIGN = HERE / "notes_native.json"
QOUT = HERE / "notes_native.quality.json"
SOUT = HERE / "notes_native.score.json"

# projected decoder constants (literature/law, not measured): a table-driven canonical-Huffman lane
# (<= 12 b codes, 2-level 4 KB LUT + 32 b barrel shifter) ~ 1,500 um2 and ~1 pJ per decoded byte at
# 0.7 V in 7 nm; 819 GB/s at 1 GHz needs ~820 byte-lanes -> ~1.2 mm2, plus chunk index/FIFO 0.3 mm2.
DEC = dict(dec_mm2=1.5, dec_pJ_per_B=1.0)


# ---------------------------------------------------------------------------------------------
# cost-model patch (one place; the IMC design and the baseline both route through model.Ctx)
# ---------------------------------------------------------------------------------------------
def kv_eff_bits(p, wl):
    lo, hi = float(p.get("kv_lo_bits", 4)), float(p.get("kv_hi_bits", 8))
    keep = int(p.get("kv_sink", 8)) + int(p.get("kv_recent", 120))
    ctx = wl["ctx_decode_sum"] / wl["gen"]
    return lo + 16.0 / int(p.get("kv_scale_group", wl["dh"])) + (hi - lo) * min(keep, ctx) / ctx


_BaseCtx = model.Ctx


class Ctx(_BaseCtx):
    """model.Ctx + the notes_native memory formats, active only when params carry nn_kv / nn_wstream."""

    def __init__(self, d, knobs=None):
        super().__init__(d, knobs)
        p, wl = self.p, self.wl
        self.nn = {}
        if p.get("nn_kv"):
            b = kv_eff_bits(p, wl)
            wl["kv_bytes_per_token"] = 2 * wl["model"]["layers"] * wl["model"]["hkv"] * wl["dh"] * b / 8
            self.nn["kv_eff_bits"] = b
        if p.get("nn_wstream"):
            wb = float(p["w_stream_bits"]) / float(p.get("w_code_bits", 8))
            wl["stored_weights"] = wl["stored_weights"] * wb
            self.nn["w_stream_ratio"] = wb
        if self.nn:
            self.mods["n7_dataflow"] = _rail_wrap(self.mods["n7_dataflow"], p, wl)


def _rail_wrap(n7, p, wl):
    def rail(pp, vdd, op, knobs):
        r = n7.rail(pp, vdd, op, knobs)
        r = dict(r, area_mm2=dict(r["area_mm2"]))
        if pp.get("nn_kv") and "a_fix_um2" in pp:              # lane mix: f_hi of the context on 8 b lanes
            keep = int(pp.get("kv_sink", 8)) + int(pp.get("kv_recent", 120))
            f_hi = min(1.0, keep / (wl["ctx_decode_sum"] / wl["gen"]))
            lane = lambda kb: pp["a_fix_um2"] + pp["a_mul_um2"] * (pp["q_bits"] + pp.get("pv_bits", pp["q_bits"])) * kb / 128  # noqa: E731
            r["area_mm2"]["rail"] *= 1 + f_hi * (lane(pp.get("kv_hi_bits", 8)) / lane(r["kv_bits"]) - 1)
        if pp.get("nn_wstream"):
            r["area_mm2"]["entropy_dec"] = pp.get("dec_mm2", DEC["dec_mm2"])
            r["phy_J_per_bit"] += pp.get("dec_pJ_per_B", DEC["dec_pJ_per_B"]) * 1e-12 / 8
        return r
    return types.SimpleNamespace(rail=rail, OPTIONS=n7.OPTIONS, DEFAULT=n7.DEFAULT,
                                 SWEEP=getattr(n7, "SWEEP", {}), **{k: getattr(n7, k) for k in ("schedule",) if hasattr(n7, k)})


def patched(fn, *a, **kw):
    model.Ctx = Ctx
    try:
        return fn(*a, **kw)
    finally:
        model.Ctx = _BaseCtx


def baseline(wbits, lit, extra, knobs=None):
    """Systolic baseline with the same memory formats (extra params ride the default design)."""
    orig_ppa, orig_make = baseline_systolic.ppa, baseline_systolic.design.make
    if lit:
        baseline_systolic.ppa = lambda: (dict(baseline_systolic.LIT), dict.fromkeys(baseline_systolic.LIT, "projected"))
    baseline_systolic.design.make = lambda nodes=None, params=None, name="design": orig_make(nodes, dict(params or {}, **extra), name)
    try:
        return patched(baseline_systolic.evaluate, wbits, knobs)
    finally:
        baseline_systolic.ppa, baseline_systolic.design.make = orig_ppa, orig_make


def summ(s):
    pk = s.get("peak") or {}
    return dict(tok_s_die=round(s["tok_s_die"], 1), tops_w=round(s["tops_w"], 3), tok_w=round(s["tok_w"], 1),
                tok_j=round(s["tok_j"], 1), B=pk.get("B"), b_max=pk.get("b_max"), vdd=pk.get("vdd"),
                die_W=round(pk.get("die_power_W", 0), 1), per_stream=round(pk.get("per_stream_tok_s", 0), 1),
                binding=s.get("binding"), margin_db=round(s.get("margin_db", 0), 2) if "margin_db" in s else None)


def score_design(d, knobs=None):
    return patched(search.evaluate, d, knobs, "joint")


def reopt(seed, frozen, passes=2, knobs=None):
    """Coordinate descent on the search's own moves, under the patched Ctx; the KV guard is lifted
    (kv_min=0) because the KV format's quality is measured here, every other guard stays."""
    sc = search.Scorer(knobs=knobs, frame="joint", kv_min=0)
    model.Ctx = Ctx
    try:
        return search.descend(sc, seed, frozen=frozen, passes=passes)
    finally:
        model.Ctx = _BaseCtx


def run_score():
    d = design.load(DESIGN)
    raw = json.loads(DESIGN.read_text())
    mem = {k: v for k, v in d["params"].items() if k.startswith(("nn_", "kv_"))}
    base_p = {k: v for k, v in d["params"].items() if k not in mem}
    wst = dict(nn_wstream=True, w_stream_bits=7.33, w_code_bits=8)   # measured proxy entropy, Hadamard codes
    tight = dict(kv_sink=4, kv_recent=28)                               # measured +0.30 % variant
    sd = search.design
    r01 = sd.load(ROOT / "docs/src/content/Project/ArchResearch/search/designs/r01.json")
    had = sd.load(ROOT / "docs/src/content/Project/ArchResearch/search/designs/cf_n8_quality__lv_hadamard.json")
    out = dict(label="projected (joint frame, search.evaluate + notes_native memory-format patch); "
                     "baseline PE: ppa.json = derived, LIT = projected", design=raw)
    out["notes_native"] = summ(score_design(d))
    out["notes_native_kv_sink4_recent28"] = summ(score_design(sd.make(d["nodes"], dict(d["params"], **tight))))
    out["notes_native_plus_wstream"] = summ(score_design(sd.make(d["nodes"], dict(d["params"], **wst))))
    out["notes_native_tile_at_kv8"] = summ(score_design(sd.make(d["nodes"], dict(base_p, kv_bits=8))))
    out["r01_asis"] = summ(score_design(r01))
    out["r01_with_kv48"] = summ(score_design(sd.make(r01["nodes"], dict(r01["params"], **mem))))
    out["hadamard_asis"] = summ(score_design(had))
    out["hadamard_with_kv48"] = summ(score_design(sd.make(had["nodes"], dict(had["params"], **mem))))
    for wb in (8, 4):
        for lit in (False, True):
            tag = f"baseline_W{wb}_{'LIT' if lit else 'ppa'}"
            out[tag + "_kv8"] = summ(baseline(wb, lit, dict(kv_bits=8)))
            out[tag + "_kv48"] = summ(baseline(wb, lit, dict(mem)))
            out[tag + "_kv48_sink4_recent28"] = summ(baseline(wb, lit, dict(mem, **tight)))
    # Sohu condition set: its FP8 KV is part of the conditions, so the KV format is NOT applied there
    sk = metric.knobs_for("sohu")
    out["sohu_notes_native_kv8"] = summ(score_design(sd.make(d["nodes"], dict(base_p, kv_bits=8)), sk))
    for lit in (False, True):
        out[f"sohu_baseline_FP8_{'LIT' if lit else 'ppa'}"] = summ(baseline(metric.SOHU_WBITS, lit, dict(kv_bits=8), sk))
    SOUT.write_text(json.dumps(out, indent=1, default=str))
    for k, v in out.items():
        if isinstance(v, dict) and "tok_s_die" in v:
            print(f"{k:<40} {v['tok_s_die']:>10,.0f} {v['tops_w']:>7.2f} {v['tok_w']:>8.1f} {v['tok_j']:>8.1f}  B {v['B']}  {v['binding']}")


# ---------------------------------------------------------------------------------------------
# measured: KV-format quality and weight-code entropy on the SmolLM2-135M proxy
# ---------------------------------------------------------------------------------------------
def _q():
    sys.path.insert(0, str(ROOT / "scripts/golden/quality"))
    import quality
    return quality


def kv_quant(x, bits):
    """x (B, T, H, dh): symmetric per-token-per-head INT quantizer (round to nearest)."""
    import numpy as np
    top = 2 ** (bits - 1) - 1
    s = np.abs(x).max(-1, keepdims=True) / top
    s = np.where(s > 0, s, 1.0)
    return (np.clip(np.rint(x / s), -top, top) * s).astype(np.float32)


def forward_kv(m, ids, lin, kv):
    """quality.Model.forward with the KV path quantized: kv = dict(lo, hi, sink, recent, rot) or None.
    Scores of (query i, key j) use the 8 b copy iff j < sink or i - j < recent, else the 4 b code;
    this is exactly what a decode step sees for every query position (teacher-forced prefill)."""
    import numpy as np
    q_ = _q()
    B, T = ids.shape
    x = m.E[ids].reshape(B * T, m.D)
    causal = np.triu(np.full((T, T), -np.inf, np.float32), 1)
    rep = m.NH // m.NKV
    if kv:
        i, j = np.arange(T)[:, None], np.arange(T)[None]
        hi = ((j < kv["sink"]) | (i - j < kv["recent"])) & (j <= i)
        H = q_._hadamard(m.DH, seed=4321) if kv["rot"] else None
    for li in range(m.NL):
        a = m._rms(x, m.norm[li, "attn"])
        q = m._rope(lin(li, "q", a).reshape(B, T, m.NH, m.DH))
        k = m._rope(lin(li, "k", a).reshape(B, T, m.NKV, m.DH))
        v = lin(li, "v", a).reshape(B, T, m.NKV, m.DH)
        if kv:
            if H is not None:                     # q.k and o = p v H^T are invariant (H H^T = I)
                q, k, v = q @ H, k @ H, v @ H
            kl, vl = kv_quant(k, kv["lo"]), kv_quant(v, kv["lo"])
            kh, vh = (kv_quant(k, kv["hi"]), kv_quant(v, kv["hi"])) if kv["hi"] else (kl, vl)
            kl, vl, kh, vh = (np.repeat(t, rep, 2).transpose(0, 2, 1, 3) for t in (kl, vl, kh, vh))
            qt = q.transpose(0, 2, 1, 3)
            sc = np.where(hi, qt @ kh.transpose(0, 1, 3, 2), qt @ kl.transpose(0, 1, 3, 2))
            s = sc / np.float32(math.sqrt(m.DH)) + causal
            p = np.exp(s - s.max(-1, keepdims=True))
            p /= p.sum(-1, keepdims=True)
            ph = np.where(hi, p, 0).astype(np.float32)
            o = ph @ vh + (p - ph) @ vl
            if H is not None:
                o = o @ H.T
        else:
            k, v = np.repeat(k, rep, 2), np.repeat(v, rep, 2)
            s = q.transpose(0, 2, 1, 3) @ k.transpose(0, 2, 3, 1) / np.float32(math.sqrt(m.DH)) + causal
            p = np.exp(s - s.max(-1, keepdims=True))
            p /= p.sum(-1, keepdims=True)
            o = p @ v.transpose(0, 2, 1, 3)
        x = x + lin(li, "o", o.transpose(0, 2, 1, 3).reshape(B * T, m.D))
        f = m._rms(x, m.norm[li, "ffn"])
        g, u = lin(li, "gate", f), lin(li, "up", f)
        x = x + lin(li, "down", g / (1.0 + np.exp(-g)) * u)
    return lin(q_.HEAD, "head", m._rms(x, m.norm["out"]))


def q_eval(kv, err=None, n_win=4, seed=0):
    import time
    import numpy as np
    q_ = _q()
    t0 = time.time()
    ref, m = q_.reference(n_win), q_.model()
    em = q_.resolve(err)
    st = {}
    if any(e is not None and (e.analog() or e.a_gran == "tensor") for e in em.values()):
        m.forward(ref["cal"], q_.make_lin(em, st, ref["amax"], None))
    lin = q_.make_lin(em, st, ref["amax"], np.random.default_rng(seed))
    nll, arg = q_._score(forward_kv(m, ref["ev"], lin, kv), ref["ev"])
    d = nll - ref["nll"]
    ppl, pr = math.exp(nll.mean()), math.exp(ref["nll"].mean())
    return dict(ppl=ppl, ppl_ref=pr, delta_pct=100 * (ppl / pr - 1),
                delta_pct_se=float(100 * (ppl / pr) * d.std() / math.sqrt(len(d))),
                top1_agree=float((arg == ref["arg"]).mean()), n_tokens=int(len(nll)),
                seconds=round(time.time() - t0, 1), _nll=nll)


def run_quality():
    q_ = _q()
    res = json.loads(QOUT.read_text()) if QOUT.exists() else {}
    res.setdefault("label", "measured (SmolLM2-135M proxy, 4 windows x 512 = 2,044 scored tokens, seed 0, "
                            "notes_native.forward_kv on scripts/golden/quality)")
    runs = res.setdefault("kv", {})
    base = None
    cfgs = {
        "kv8 per-token-head": dict(lo=8, hi=0, sink=0, recent=0, rot=False),
        "kv4 per-token-head": dict(lo=4, hi=0, sink=0, recent=0, rot=False),
        "kv4 hadamard": dict(lo=4, hi=0, sink=0, recent=0, rot=True),
        "kv4/8 sink8+recent120 (no rot)": dict(lo=4, hi=8, sink=8, recent=120, rot=False),
        "kv4/8 sink8+recent120 hadamard": dict(lo=4, hi=8, sink=8, recent=120, rot=True),
        "kv3/8 sink8+recent120 hadamard": dict(lo=3, hi=8, sink=8, recent=120, rot=True),
        "kv4/8 sink4+recent28 hadamard": dict(lo=4, hi=8, sink=4, recent=28, rot=True),
    }
    for name, kv in cfgs.items():
        if name in runs:
            continue
        r = q_eval(kv)
        r.pop("_nll")
        runs[name] = dict(config=kv, **r)
        print(name, {k: round(v, 3) if isinstance(v, float) else v for k, v in r.items()}, flush=True)
        QOUT.write_text(json.dumps(res, indent=1))
    # combined with the tile's own error (the Hadamard spot-check config at 39.8 dB, quality_spotcheck.json)
    comb = res.setdefault("combined", {})
    snr = 39.8
    tile = q_.Err(w_fmt="int8", a_fmt="int8", rows=8, adc_fs=32.0, hadamard=True, noise=10 ** (-snr / 20) / 32)
    for name, kv in (("tile 39.8 dB + kv16", None),
                     ("tile 39.8 dB + kv4/8 sink8+recent120 hadamard", cfgs["kv4/8 sink8+recent120 hadamard"])):
        if name in comb:
            continue
        r = q_eval(kv, {"all": tile})
        r.pop("_nll")
        comb[name] = dict(config=kv, tile=f"w int8/ch, a int8/token, rows 8, FS 32 sigma, hadamard, noise {snr} dB", **r)
        print(name, {k: round(v, 3) if isinstance(v, float) else v for k, v in r.items()}, flush=True)
        QOUT.write_text(json.dumps(res, indent=1))
    del base


def huffman_bits(counts):
    """Mean code length (bits/symbol) of an optimal Huffman code for these symbol counts."""
    c = [int(x) for x in counts if x > 0]
    if len(c) == 1:
        return 1.0
    h = list(c)
    heapq.heapify(h)
    tot = 0
    while len(h) > 1:
        a, b = heapq.heappop(h), heapq.heappop(h)
        tot += a + b
        heapq.heappush(h, a + b)
    return tot / sum(c)


def run_entropy():
    import numpy as np
    q_ = _q()
    m = q_.model()
    res = json.loads(QOUT.read_text()) if QOUT.exists() else {}
    acc = {k: [0.0, 0.0, 0] for k in ("ch_plain", "ch_hadamard")}
    for (li, kind), W in m.W.items():
        if kind == "head":
            continue
        for tag, Wx in (("ch_plain", W), ("ch_hadamard", q_.rotate(W, q_._hadamard(W.shape[1])))):
            s = np.abs(Wx).max(1, keepdims=True) / 127
            c = np.clip(np.rint(Wx / np.where(s > 0, s, 1)), -127, 127).astype(np.int64) + 127
            n = np.bincount(c.ravel(), minlength=255).astype(np.float64)
            pr = n[n > 0] / n.sum()
            acc[tag][0] += -(pr * np.log2(pr)).sum() * n.sum()
            acc[tag][1] += huffman_bits(n) * n.sum()
            acc[tag][2] += int(n.sum())
    res["weight_entropy"] = {k: dict(H0_bits=a / n, huffman_bits=b / n, n_weights=n) for k, (a, b, n) in acc.items()}
    res["weight_entropy_note"] = ("measured on SmolLM2-135M (dequantized Q8_0 -> INT8 per output channel, absmax), "
                                  "linears without the tied LM head; zero-order per-tensor Huffman, table overhead excluded "
                                  "(< 0.01 b/w at 4 KB chunks). Llama-3-8B is projected to differ.")
    QOUT.write_text(json.dumps(res, indent=1))
    print(json.dumps(res["weight_entropy"], indent=1))


def selfcheck():
    wl = model.workload.llama3()
    b = kv_eff_bits(dict(kv_lo_bits=4, kv_hi_bits=8, kv_sink=8, kv_recent=120), wl)
    assert abs(b - (4 + 0.125 + 4 * 128 / 576.5)) < 1e-9, b
    assert huffman_bits([1, 1]) == 1.0 and abs(huffman_bits([2, 1, 1]) - 1.5) < 1e-12
    d = design.load(DESIGN)
    s_on = score_design(d)
    s_off = score_design(design.make(d["nodes"], {k: v for k, v in d["params"].items() if not k.startswith("nn_")} | dict(kv_bits=8)))
    assert s_on["peak"]["b_max"] > 1.4 * s_off["peak"]["b_max"], (s_on["peak"]["b_max"], s_off["peak"]["b_max"])
    assert model.Ctx is _BaseCtx, "patch leaked"
    print("notes_native selfcheck PASS")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--quality", action="store_true")
    ap.add_argument("--entropy", action="store_true")
    ap.add_argument("--selfcheck", action="store_true")
    a = ap.parse_args()
    if a.quality:
        run_quality()
    elif a.entropy:
        run_entropy()
    elif a.selfcheck:
        selfcheck()
    else:
        run_score()
