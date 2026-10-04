#!/usr/bin/env python3
"""AnalogIOC-mini compiler: REAL SmolLM2-135M blk.0 (head-0 slice + SwiGLU FFN)
-> 16x16 differential cap tiles + PWM schedules + digital-rail config +
golden expected values at every observation point (real-model mandate).

Pipeline per matrix: SmoothQuant (alpha=0.5) -> INT4 per-output-channel
weights -> differential cap codes (+ random-sign ABFT checksum column) ->
per-tensor converter LSB D from +-4sigma of REAL per-pass MAC samples ->
per-channel A4 requant fields. Activations: INT8 -> 1:16 PWM nibbles.

Forward-of-record runs through scripts/golden/model.py (bit-true, the same
functions every testbench trusts); this file adds a vectorized per-pass
pipeline (proven bit-identical in test_compile.py) for ABFT budgets,
early-termination statistics and representative-pass selection.

Outputs (scripts/compiler/out/): manifest.json, digital_config.json,
passes.json, golden_trace.npz, programming/<matrix>.npz, acts/<matrix>.npz,
passes/pass_NN_<tag>/{caps,params,pwm_lo,pwm_hi}.spice + expected.json.

Run: PYTHONPATH=scripts python3 scripts/compiler/compile.py
"""

import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compiler.gguf_reader import GGUF, tokenize_greedy          # noqa: E402
from compiler import emit_spice                                 # noqa: E402
from compiler import formats as F                               # noqa: E402
from golden import model as G                                   # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "scripts/models/smollm2-135m-q8_0.gguf"
OUT = Path(__file__).resolve().parent / "out"
PROMPT = "The quick brown fox jumps over the lazy dog"
HEAD = 0            # compiled head slice
SEED = 7
TILE = 16

EXPECT_META = {
    "general.architecture": "llama",
    "llama.block_count": 30,
    "llama.embedding_length": 576,
    "llama.attention.head_count": 9,
    "llama.attention.head_count_kv": 3,
    "llama.feed_forward_length": 1536,
    "llama.vocab_size": 49152,
}


# ---------------------------------------------------------------------------
# model loading
# ---------------------------------------------------------------------------

def load_model(path=MODEL):
    g = GGUF(str(path))
    for k, v in EXPECT_META.items():
        assert g.meta[k] == v, f"{k}: {g.meta[k]} != {v}"
    dm = g.meta["llama.embedding_length"]
    nh = g.meta["llama.attention.head_count"]
    nkv = g.meta["llama.attention.head_count_kv"]
    dh = dm // nh                                   # 64
    kv = HEAD // (nh // nkv)                        # GQA: q-head -> kv-head
    m = {
        "gguf": g,
        "d_model": dm, "d_head": dh, "rope_base": float(g.meta["llama.rope.freq_base"]),
        "rms_eps": float(g.meta["llama.attention.layer_norm_rms_epsilon"]),
        "vocab": g.meta["tokenizer.ggml.tokens"],
        "embd": g.array("token_embd.weight"),
        "attn_norm": g.array("blk.0.attn_norm.weight"),
        "ffn_norm": g.array("blk.0.ffn_norm.weight"),
        # head-0 slices: (out, in) numpy layout from the reader
        "Wq": g.array("blk.0.attn_q.weight")[HEAD * dh:(HEAD + 1) * dh],
        "Wk": g.array("blk.0.attn_k.weight")[kv * dh:(kv + 1) * dh],
        "Wv": g.array("blk.0.attn_v.weight")[kv * dh:(kv + 1) * dh],
        "Wo": g.array("blk.0.attn_output.weight")[:, HEAD * dh:(HEAD + 1) * dh],
        "Wg": g.array("blk.0.ffn_gate.weight"),
        "Wu": g.array("blk.0.ffn_up.weight"),
        "Wd": g.array("blk.0.ffn_down.weight"),
    }
    for n in ("Wq", "Wk", "Wv", "Wo", "Wg", "Wu", "Wd"):
        assert np.isfinite(m[n]).all()
    return m


def rms_rows(X, w, eps):
    return np.stack([G.rmsnorm(x, w, eps) for x in np.atleast_2d(X)])


# ---------------------------------------------------------------------------
# per-matrix compilation
# ---------------------------------------------------------------------------

def tiles4(Wq):
    """(O, I) int matrix -> (Oc, 16, Rc, 16) tile view (dims must be /16)."""
    O, I = Wq.shape
    assert O % TILE == 0 and I % TILE == 0, "real-model dims are 16-multiples"
    return Wq.reshape(O // TILE, TILE, I // TILE, TILE).transpose(0, 1, 2, 3)


def nib16(xq):
    """Signed nibble drives reshaped to (Rc, 16)."""
    sg, hi, lo = G.pwm_nibbles(xq)
    return (sg * hi).reshape(-1, TILE), (sg * lo).reshape(-1, TILE)


def compile_matrix(name, W, X_cal, seed=SEED, csd=False):
    """Full compile of one real matrix against real calibration activations.

    csd=True (task A, --csd): program the C+/C- split from the canonical-
    signed-digit recode (formats.csd_caps) instead of one-sided signed
    magnitude. Cp - Cn == Wq either way, so every MAC/conversion/rail
    number below is bit-identical (golden.tile_mvm_caps); only the cap
    programming statistics change. |Wq| <= 7 keeps the NAF carry inside
    one slice (asserted).
    """
    X_cal = np.atleast_2d(np.asarray(X_cal, dtype=np.float64))
    Xs, Ws, s_sm = G.smooth(X_cal, W.astype(np.float64), alpha=0.5)
    Wq, dw = G.quant_w_int4(Ws)
    dx = float(np.max(np.abs(Xs))) / G.X_MAX or 1.0
    W4 = tiles4(Wq)
    # per-pass MAC samples over the calibration stream (both nibble windows)
    macs = []
    macs_m = []          # merged full-window macs (item S5, law:bout)
    for t in range(Xs.shape[0]):
        xq, _ = G.quant_x_int8(Xs[t], dx)
        sh, sl = nib16(xq)
        macs.append(np.einsum("ojri,ri->ojr", W4, sh))
        macs.append(np.einsum("ojri,ri->ojr", W4, sl))
        macs_m.append(np.einsum("ojri,ri->ojr", W4,
                                xq.reshape(-1, TILE)))
    D = G.conv_scale_D(np.concatenate([m.ravel() for m in macs]))
    D_merged = G.merged_scale_D(np.concatenate(
        [m.ravel() for m in macs_m]))
    dy = float(np.max(np.abs(Xs @ Ws.T))) / G.X_MAX or 1.0
    scale8, shift = G.make_requant(D * dw * dx / dy)
    scale_m, shift_m = G.make_requant(D_merged * dw * dx / dy)
    s16 = G.abft_signs(TILE, seed)
    exact = np.einsum("j,ojri->ori", s16, W4)
    chk = G._half_up_div(exact, 1 << G.CHK_SHIFT)
    assert np.all(np.abs(chk) <= G.CAP_MAX)
    e4 = exact - (chk << G.CHK_SHIFT)     # design-time-known rounding, |e|<=4
    if csd:
        cc = F.csd_caps(Wq)
        assert cc["S_csd"] == 1, "int4 CSD stays single-slice"
        Cp, Cn = cc["Cp"][0].astype(np.uint8), cc["Cn"][0].astype(np.uint8)
        assert np.array_equal(G.wq_from_caps(Cp, Cn), Wq)
    else:
        Cp, Cn = G.caps_from_wq(Wq)
    err = Ws - dw[:, None] * Wq           # int4 lowering error vs float64 Ws
    mse = float(np.mean(err ** 2))
    sqnr = float(10 * np.log10(np.mean(Ws ** 2) / mse)) if mse > 0 else np.inf
    return {
        "name": name, "Wq": Wq, "W4": W4, "Cp": Cp, "Cn": Cn,
        "smooth": s_sm, "dw": dw, "dx_in": dx, "D": D, "dy": dy,
        "D_merged": D_merged, "scale_m": scale_m, "shift_m": shift_m,
        "scale": scale8, "shift": shift, "offset": np.zeros(W.shape[0], dtype=np.int64),
        "s16": s16, "chk": chk, "e4": e4,  # chk caps + e per tile (Oc, Rc, 16)
        "zero_scale_ch": int(np.sum(scale8 == 0)),
        "sqnr_w_db": sqnr,
    }


def layer_passes(C, xq):
    """Every tile pass of one MVM, vectorized; bit-identical to G.mvm_layer
    (proven in test_compile.py). Returns per-pass observation arrays."""
    W4, D = C["W4"], C["D"]
    sh, sl = nib16(xq)
    mac_hi = np.einsum("ojri,ri->ojr", W4, sh)
    mac_lo = np.einsum("ojri,ri->ojr", W4, sl)
    ch, cl = G.eventrate_convert(mac_hi, D), G.eventrate_convert(mac_lo, D)
    y12 = G.nibble_combine(ch["code"], cl["code"])          # (Oc, 16, Rc)
    y14 = G.slice_combine(y12)
    acc = y14.sum(axis=2).reshape(-1)
    assert np.all(np.abs(acc) < 2 ** 19)
    out8 = G.requant_int8(acc, C["scale"], C["shift"], C["offset"])
    mch = np.einsum("ori,ri->or", C["chk"], sh)
    mcl = np.einsum("ori,ri->or", C["chk"], sl)
    kh, kl = G.eventrate_convert(mch, D), G.eventrate_convert(mcl, D)
    y12chk = G.nibble_combine(kh["code"], kl["code"])       # (Oc, Rc)
    corr = G._half_up_div(
        np.einsum("ori,ri->or", C["e4"], sh) * 16
        + np.einsum("ori,ri->or", C["e4"], sl), D)          # e.xq combined
    resid = np.abs(np.einsum("j,ojr->or", C["s16"], y12)
                   - (y12chk << G.CHK_SHIFT) - corr)
    n_eval = (ch["n_eval"] + cl["n_eval"]).sum(axis=1)      # (Oc, Rc) data cols
    return {"mac_hi": mac_hi, "mac_lo": mac_lo, "y12": y12, "y14": y14,
            "acc": acc, "out8": out8, "y12chk": y12chk, "resid": resid,
            "n_eval": n_eval,
            "n_eval_conv": np.concatenate([ch["n_eval"].ravel(),
                                           cl["n_eval"].ravel()]),
            "n_eval_chk": kh["n_eval"] + kl["n_eval"]}


# ---------------------------------------------------------------------------
# format-universal flow (A5b): any --wfmt/--afmt via the BFP lowering law
# ---------------------------------------------------------------------------

def compile_matrix_fmt(name, W, X_cal, wfmt, afmt, target=F.BY_CEIL_BITS):
    """Lower one real matrix + calibration stream in arbitrary formats.

    Same SmoothQuant pre-pass as compile_matrix, then compiler.formats
    lowering. D sizing generalizes the INT4 two-window rule: +-4sigma over
    every (slice, nibble-window) MAC of the calibration stream.
    """
    X_cal = np.atleast_2d(np.asarray(X_cal, dtype=np.float64))
    Xs, Ws, s_sm = G.smooth(X_cal, W.astype(np.float64), alpha=0.5)
    Lw = F.lower_tensor(Ws, wfmt, target)
    La = F.lower_acts(Xs, afmt, target)   # per-tensor scales over the stream
    S4 = np.stack([tiles4(s) for s in Lw["slices"]])
    macs = []
    for t in range(La["xq"].shape[0]):
        sg, rounds = G.pwm_nibble_rounds(La["xq"][t], La["n_nib"])
        for nl, nh in rounds:
            # hi window first: same float summation order as the legacy
            # compile_matrix D sizing -> bit-identical sigma on the identity
            for n in (nl,) if nh is None else (nh, nl):
                w = (sg * n).reshape(-1, TILE)
                macs.append(np.einsum("sojri,ri->sojr", S4, w).ravel())
    D = G.conv_scale_D(np.concatenate(macs))
    dy = float(np.max(np.abs(Xs @ Ws.T))) / G.X_MAX or 1.0
    unit = Lw["w_scale"] * np.exp2(Lw["e_min"])      # per-channel weight LSB
    scale8, shift = G.make_requant(D * unit * La["dx"] / dy)
    return {
        "name": name, "wfmt": wfmt, "afmt": afmt, "Ws": Ws, "Xs": Xs,
        "Lw": Lw, "La": La, "S4": S4, "smooth": s_sm, "D": D, "dy": dy,
        "scale": scale8, "shift": shift,
        "offset": np.zeros(W.shape[0], dtype=np.int64),
    }


def layer_passes_fmt(C, xq):
    """Vectorized general per-pass pipeline; bit-identical to
    golden.mvm_lowered (proven in test_formats.py). Returns per-column acc,
    out8 and comparator-strobe stats."""
    Lw, D = C["Lw"], C["D"]
    O, I = Lw["M"].shape
    Oc, Rc = O // TILE, I // TILE
    sg, rounds = G.pwm_nibble_rounds(xq, C["La"]["n_nib"])
    y = np.zeros((Oc, TILE, Rc), dtype=np.int64)
    nev = np.zeros(16, dtype=np.int64)
    for s, sig in enumerate(Lw["sig"]):
        y_sl = np.zeros_like(y)
        for p, (nl, nh) in enumerate(rounds):
            cl = G.eventrate_convert(
                np.einsum("ojri,ri->ojr", C["S4"][s], (sg * nl).reshape(Rc, TILE)), D)
            if nh is None:
                y12 = G.nibble_combine(0, cl["code"])
                nev += np.bincount(cl["n_eval"].ravel(), minlength=16)
            else:
                ch = G.eventrate_convert(
                    np.einsum("ojri,ri->ojr", C["S4"][s], (sg * nh).reshape(Rc, TILE)), D)
                y12 = G.nibble_combine(ch["code"], cl["code"])
                nev += np.bincount(cl["n_eval"].ravel(), minlength=16) \
                    + np.bincount(ch["n_eval"].ravel(), minlength=16)
            y_sl += (256 ** p) * y12
        y += sig * y_sl
    sh = (Lw["exp"] - Lw["e_min"]).reshape(Oc, TILE, Rc)
    acc = (y << sh).sum(axis=2).reshape(-1)
    out8 = G.requant_int8(acc, C["scale"], C["shift"], C["offset"])
    return {"acc": acc, "out8": out8, "n_eval_hist": nev}


def fmt_pass_counts(mats_f, T):
    per_tok = {}
    for n, C in mats_f.items():
        O, I = C["Lw"]["M"].shape
        per_tok[n] = count_passes((O, I)) * F.passes_per_tile(
            C["Lw"]["b_eff"], C["La"]["b_x"])
    total = sum(per_tok.values())
    return {"tile_passes_per_token": per_tok,
            "tile_passes_per_token_total": total,
            "prompt_tokens": T,
            "tile_passes_prompt_total": total * T,
            "pass_law": "passes/tile = ceil((b_w_eff-1)/4) [slices] * "
                        "ceil(ceil((b_x-1)/4)/2) [nibble-pair rounds]; "
                        "identity int4 x int8 = 1 (see formats.py)"}


def run_formats(wfmt, afmt, prompt=PROMPT, out=None, model_path=MODEL,
                target=F.BY_CEIL_BITS, quiet=False):
    """Format-exploration compile: lowering + fidelity + rail config + pass
    counts for any (wfmt, afmt). The full golden e2e trace / SPICE rep passes
    remain the default-format (int4 x int8) deliverable — this flow answers
    'what does format X cost and what fidelity does it buy' (manifest SQNR).
    """
    t0 = time.time()
    log = (lambda *a: None) if quiet else print
    out = Path(out) if out else OUT.parent / f"out_formats/{wfmt}__{afmt}"
    (out / "programming").mkdir(parents=True, exist_ok=True)
    (out / "acts").mkdir(exist_ok=True)
    m = load_model(model_path)
    ids = tokenize_greedy(prompt, m["vocab"])
    T = len(ids)
    E = m["embd"][ids].astype(np.float64)
    A_in = rms_rows(E, m["attn_norm"], m["rms_eps"])
    qf, kf, vf, avf = float_attention(m, A_in)
    H = E + avf @ m["Wo"].T
    F_in = rms_rows(H, m["ffn_norm"], m["rms_eps"])
    gf = F_in @ m["Wg"].T
    hvf = (gf / (1.0 + np.exp(-gf))) * (F_in @ m["Wu"].T)
    cal = {"attn_q": (m["Wq"], A_in), "attn_k": (m["Wk"], A_in),
           "attn_v": (m["Wv"], A_in), "attn_o": (m["Wo"], avf),
           "ffn_gate": (m["Wg"], F_in), "ffn_up": (m["Wu"], F_in),
           "ffn_down": (m["Wd"], hvf)}
    mats_f, fid = {}, {}
    for n, (W, X) in cal.items():
        C = compile_matrix_fmt(n, W, X, wfmt, afmt, target)
        mats_f[n] = C
        p = layer_passes_fmt(C, C["La"]["xq"][T - 1])
        y_ref = C["Ws"] @ C["Xs"][T - 1]
        y_hat = p["acc"] * C["D"] * C["Lw"]["w_scale"] \
            * np.exp2(C["Lw"]["e_min"]) * C["La"]["dx"]
        e = y_ref - y_hat
        mvm_sqnr = float(10 * np.log10(np.mean(y_ref ** 2) / np.mean(e ** 2))) \
            if np.any(e) else np.inf
        fid[n] = {"sqnr_w_db": round(C["Lw"]["sqnr_db"], 2),
                  "sqnr_x_db": round(C["La"]["sqnr_db"], 2),
                  "mvm_sqnr_db": round(mvm_sqnr, 2),
                  "over_by8": bool(C["Lw"]["over_by8"]),
                  "n_eval_hist_last_tok": p["n_eval_hist"].tolist()}
        Cp = np.maximum(C["Lw"]["slices"], 0).astype(np.uint8)
        Cn = np.maximum(-C["Lw"]["slices"], 0).astype(np.uint8)
        np.savez_compressed(out / "programming" / f"{n}.npz",
                            slices=C["Lw"]["slices"], Cp=Cp, Cn=Cn,
                            M=C["Lw"]["M"], w_scale=C["Lw"]["w_scale"],
                            exp=C["Lw"]["exp"], e_min=C["Lw"]["e_min"],
                            sig=np.array(C["Lw"]["sig"]), smooth=C["smooth"],
                            dx_in=C["La"]["dx"], D=C["D"], dy=C["dy"],
                            scale=C["scale"], shift=C["shift"], offset=C["offset"])
        np.savez_compressed(out / "acts" / f"{n}.npz", xq=C["La"]["xq"])
        log(f"[fmt] {n}: b_eff={C['Lw']['b_eff']} S={C['Lw']['S']} "
            f"D={C['D']} wSQNR={fid[n]['sqnr_w_db']} mvmSQNR={fid[n]['mvm_sqnr_db']} "
            f"({time.time() - t0:.1f}s)")

    def rounds_of(R):
        return [15] * (R // 15) + ([R % 15] if R % 15 else [])
    dig = {
        "note": "format-universal rail config (A5b). Slice/round shift-adds "
                "exceed A4's fixed sat14 x4 slice_combine when S>1 with 16^s "
                "significances: required widths below are the generalized-"
                "rail spec. Per-(row,row-tile) BFP exponents are applied as "
                "left-shifts on tile partials in the accumulator (exponents "
                "never enter the analog core).",
        "wfmt": wfmt, "afmt": afmt,
        "abft_note": "checksum column disabled for non-default formats: "
                     "slice digits span +-15 so the signed column sum "
                     "exceeds the 4b chk cap range at CHK_SHIFT=3 (needs "
                     "chk_shift=4 + rail change; upgrade path).",
        "matrices": {},
    }
    for n, C in mats_f.items():
        O, I = C["Lw"]["M"].shape
        S = C["Lw"]["S"]
        n_rounds = -(-C["La"]["n_nib"] // 2)
        span = int((C["Lw"]["exp"] - C["Lw"]["e_min"]).max())
        comb = 2047 * sum(C["Lw"]["sig"]) * sum(256 ** p for p in range(n_rounds))
        req_acc = int(np.ceil(np.log2(comb))) + 1 + span \
            + int(np.ceil(np.log2(max(I // TILE, 1)))) + 1
        dig["matrices"][n] = {
            "shape": [O, I], "col_tiles": O // TILE, "row_tiles": I // TILE,
            "acc_rounds": rounds_of(I // TILE), "D": C["D"], "relu_en": 0,
            "slices": S, "slice_sig": C["Lw"]["sig"],
            "b_eff": C["Lw"]["b_eff"], "b_x": C["La"]["b_x"],
            "nibble_rounds": n_rounds, "exp_shift_span": span,
            "required_acc_bits": req_acc,
            "requant": {"scale": C["scale"].tolist(),
                        "shift": C["shift"].tolist(),
                        "offset": C["offset"].tolist()},
            "abft": None,
        }
    (out / "digital_config.json").write_text(json.dumps(dig, indent=1))
    pt = fmt_pass_counts(mats_f, T)
    (out / "passes.json").write_text(json.dumps(pt, indent=1))
    manifest = {
        "model": str(model_path), "prompt": prompt, "token_ids": ids,
        "wfmt": wfmt, "afmt": afmt, "target_bits": target,
        "flow": "format-exploration (lowering + fidelity + config + pass "
                "counts); full golden e2e trace + SPICE rep passes are the "
                "default int4 x int8 deliverable in out/",
        "by8_note": "CSNR ceiling ~ B_y=8: sqnr entries flagged over_by8 "
                    "carry >8b per-element mantissa the readout cannot "
                    "redeem (FORMATS.md)",
        "matrices": {n: {
            "shape": list(mats_f[n]["Lw"]["M"].shape),
            "D": mats_f[n]["D"], "dx_in": mats_f[n]["La"]["dx"],
            "dy": mats_f[n]["dy"], "b_eff": mats_f[n]["Lw"]["b_eff"],
            "slices": mats_f[n]["Lw"]["S"],
            "passes_per_token": pt["tile_passes_per_token"][n],
            **fid[n],
        } for n in mats_f},
        "tile_passes_per_token_total": pt["tile_passes_per_token_total"],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    log(f"[fmt] wrote {out} ({time.time() - t0:.1f}s); "
        f"{pt['tile_passes_per_token_total']} tile passes/token")
    return {"mats": mats_f, "manifest": manifest, "fid": fid, "out_dir": out}


# ---------------------------------------------------------------------------
# float calibration reference (pre-quant; scales become static at compile)
# ---------------------------------------------------------------------------

def float_attention(m, A_in):
    T = A_in.shape[0]
    rope = lambda v, t: G.rope_norm(v, t, base=m["rope_base"])  # noqa: E731
    q = np.stack([rope(A_in[t] @ m["Wq"].T, t) for t in range(T)])
    k = np.stack([rope(A_in[t] @ m["Wk"].T, t) for t in range(T)])
    v = A_in @ m["Wv"].T
    av = np.zeros_like(v)
    for t in range(T):
        p = G.softmax_ref(k[:t + 1] @ q[t] / np.sqrt(q.shape[1]))
        av[t] = p @ v[:t + 1]
    return q, k, v, av


# ---------------------------------------------------------------------------
# pass accounting
# ---------------------------------------------------------------------------

def count_passes(shape):
    O, I = shape
    return -(-O // TILE) * -(-I // TILE)


def pass_table(mats, T):
    per_tok = {name: count_passes(C["Wq"].shape) for name, C in mats.items()}
    total = sum(per_tok.values())
    return {
        "tile_passes_per_token": per_tok,
        "tile_passes_per_token_total": total,
        "prompt_tokens": T,
        "tile_passes_prompt_total": total * T,
        # 8x8 gain-cell KV bank units at d_head=64 (8 array configurations)
        "kv_col_writes_per_token": 16,
        "qk_read_ops_token_t": "8*(t+1)",
        "av_read_ops_token_t": "8*(t+1)",
        "softmax_bank_evals_token_t": "ceil((t+1)/8)",
        "tok_per_s_formula":
            "1 / (tile_passes_per_token_total * t_pass_measured + attn_aux);"
            " one physical tile time-multiplexed (silicon reuse); t_pass from"
            " A2 SPICE (PWM windows + conversion done-time), attn_aux from"
            " A3 KV/softmax measured ops.",
    }


# ---------------------------------------------------------------------------
# representative pass selection + emission
# ---------------------------------------------------------------------------

def build_pass(C, ct, rt, xq, tag, budget, token_index):
    js = slice(ct * TILE, (ct + 1) * TILE)
    ks = slice(rt * TILE, (rt + 1) * TILE)
    Wt, xt, chk = C["Wq"][js, ks], xq[ks], C["chk"][ct, rt]
    e = C["e4"][ct, rt]
    t = G.tile_mvm(Wt, xt, C["D"], s=C["s16"], chk=chk, chk_e=e)
    sg, hi, lo = G.pwm_nibbles(xt)
    # stored codes, not re-derived: identical for the default one-sided
    # split; --csd rep passes then carry the CSD split into caps.spice
    cp, cn = C["Cp"][js, ks], C["Cn"][js, ks]
    return {
        "tag": tag, "matrix": C["name"], "ct": ct, "rt": rt,
        "token_index": token_index, "D": C["D"], "budget": budget,
        "s": C["s16"], "Wq": Wt, "Cp": cp, "Cn": cn, "chk": chk, "chk_e": e,
        "xq": xt,
        "pwm": {"sign": sg, "hi": hi, "lo": lo,
                "t_lo_s": (lo * G.TQ_SIM), "t_hi_s": (hi * 16.0 * G.TQ_SIM)},
        "expected": {
            "mac_hi": t["mac_hi"], "mac_lo": t["mac_lo"],
            "code_hi": t["conv_hi"]["code"], "code_lo": t["conv_lo"]["code"],
            "coarse_hi": t["conv_hi"]["coarse"], "fine_hi": t["conv_hi"]["fine"],
            "coarse_lo": t["conv_lo"]["coarse"], "fine_lo": t["conv_lo"]["fine"],
            "n_eval_hi": t["conv_hi"]["n_eval"], "n_eval_lo": t["conv_lo"]["n_eval"],
            "y12": t["y12"], "y14": t["y14"],
            "chk_code_hi": t["chk"]["conv_hi"]["code"],
            "chk_code_lo": t["chk"]["conv_lo"]["code"],
            "chk_y12": t["chk"]["y12"], "abft_residual": t["chk"]["residual"],
        },
    }


def select_passes(mats, last_xq, budgets, token_index):
    """>= 8 real passes: global worst-case code, sparsest, best/worst
    early-termination, max checksum residual, one typical per matrix."""
    P = {n: layer_passes(C, last_xq[n]) for n, C in mats.items()}
    picks = []  # (tag, matrix, ct, rt)

    def argmax2(a):
        i = int(np.argmax(a))
        return np.unravel_index(i, a.shape)

    # worst-case |y12| over all matrices
    n, (c, j, r) = max(((n, argmax2(np.abs(p["y12"]))) for n, p in P.items()),
                       key=lambda t: abs(P[t[0]]["y12"][t[1]]))
    picks.append(("worst_code", n, int(c), int(r)))
    # sparsest tile (zero weights + zero activations)
    def sparsity(C, n, c, r):
        return 0.5 * np.mean(C["W4"][c, :, r, :] == 0) + \
               0.5 * np.mean(last_xq[n][r * TILE:(r + 1) * TILE] == 0)
    best = max(((n, c, r) for n, C in mats.items()
                for c in range(C["W4"].shape[0]) for r in range(C["W4"].shape[2])),
               key=lambda t: sparsity(mats[t[0]], *t))
    picks.append(("sparse", best[0], best[1], best[2]))
    # early-termination extremes (per-pass mean strobes over data columns)
    n, p = min(P.items(), key=lambda kv: kv[1]["n_eval"].min())
    c, r = argmax2(-p["n_eval"])
    picks.append(("eterm_min", n, int(c), int(r)))
    n, p = max(P.items(), key=lambda kv: kv[1]["n_eval"].max())
    c, r = argmax2(p["n_eval"])
    picks.append(("eterm_max", n, int(c), int(r)))
    # max ABFT residual (clean-traffic stress for the budget)
    n, p = max(P.items(), key=lambda kv: kv[1]["resid"].max())
    c, r = argmax2(p["resid"])
    picks.append(("chk_max", n, int(c), int(r)))
    # one typical pass per matrix not already covered
    for n, p in P.items():
        c, j, r = argmax2(np.abs(p["y12"]))
        picks.append((f"typ_{n}", n, int(c), int(r)))
    seen, out = set(), []
    for tag, n, c, r in picks:
        if (n, c, r) in seen:
            continue
        seen.add((n, c, r))
        out.append(build_pass(mats[n], c, r, last_xq[n], tag, budgets[n],
                              token_index))
    assert len(out) >= 8, f"only {len(out)} unique representative passes"
    return out


# ---------------------------------------------------------------------------
# top-level compile + golden forward
# ---------------------------------------------------------------------------

def csd_report(mats, stream):
    """Measured CSD density/charge vs the one-sided baseline (task A).

    duty_i = mean|xq_i| / 255 over the real token stream (fraction of the
    255*t_q full window row i drives). Reported per matrix and pooled;
    'cells' is the nonzero-digit (unit-cell) cost the ~1/2 -> ~1/3 claim
    lives in, 'value' the binary-weighted C_u charge (see charge_cost).
    """
    rep, agg = {}, {"cells": [0.0, 0.0], "value": [0.0, 0.0],
                    "digits": [0, 0], "positions": 0}
    for n, C in mats.items():
        duty = np.mean(np.abs(np.stack(stream[n])), axis=0) / 255.0
        base = F.charge_cost(*G.caps_from_wq(C["Wq"]), duty)
        cc = F.csd_caps(C["Wq"])
        new = F.charge_cost(cc["Cp"][0], cc["Cn"][0], duty)
        rep[n] = {
            "density_binary": round(base["density"], 4),
            "density_csd": round(new["density"], 4),
            "digit_drop_pct": round(100 * (1 - new["cells_static"]
                                           / max(base["cells_static"], 1)), 2),
            "charge_cells_drop_pct": round(
                100 * (1 - new["cells"] / max(base["cells"], 1e-30)), 2),
            "charge_value_change_pct": round(
                100 * (new["value"] / max(base["value"], 1e-30) - 1), 2),
        }
        for k, b, c in (("cells", base["cells"], new["cells"]),
                        ("value", base["value"], new["value"])):
            agg[k][0] += b
            agg[k][1] += c
        agg["digits"][0] += base["cells_static"]
        agg["digits"][1] += new["cells_static"]
        agg["positions"] += 4 * C["Wq"].size
    return {
        "per_matrix": rep,
        "total": {
            "density_binary": round(agg["digits"][0] / agg["positions"], 4),
            "density_csd": round(agg["digits"][1] / agg["positions"], 4),
            "digit_drop_pct": round(
                100 * (1 - agg["digits"][1] / agg["digits"][0]), 2),
            "charge_cells_drop_pct": round(
                100 * (1 - agg["cells"][1] / agg["cells"][0]), 2),
            "charge_value_change_pct": round(
                100 * (agg["value"][1] / agg["value"][0] - 1), 2),
        },
        "note": "cells = ON bit-caps (nonzero signed digits) x duty -- the "
                "bit-sliced unit-cell cost CSD reduces; value = Cp+Cn code "
                "units x duty = actual C_u charge on the mini's binary-"
                "weighted banks, which one-sided coding already minimizes "
                "(CSD raises it). MAC output is bit-identical either way "
                "(golden.tile_mvm_caps). See FORMATS.md / csd section.",
    }


def run(prompt=PROMPT, out=OUT, model_path=MODEL, quiet=False, csd=False,
        score_temp=None):
    # score_temp: opt-in device temperature (Kelvin) for #18/#25 PTAT score
    # pre-scaling. None -> gain 1.0 -> default path byte-identical.
    score_gain = 1.0 if score_temp is None else G.ptat_score_gain(score_temp)
    t_start = time.time()
    log = (lambda *a: None) if quiet else print
    out = Path(out)
    (out / "programming").mkdir(parents=True, exist_ok=True)
    (out / "acts").mkdir(exist_ok=True)

    m = load_model(model_path)
    ids = tokenize_greedy(prompt, m["vocab"])
    assert ids, "tokenizer produced no tokens"
    pieces = [m["vocab"][i] for i in ids]
    T = len(ids)
    log(f"[compile] prompt {prompt!r} -> {T} tokens {ids} {pieces}")

    E = m["embd"][ids].astype(np.float64)                     # (T, 576)
    A_in = rms_rows(E, m["attn_norm"], m["rms_eps"])

    # --- attention matrices (calibration = real rmsnormed embeddings) ---
    mats = {}
    for name, W, X in (("attn_q", m["Wq"], A_in), ("attn_k", m["Wk"], A_in),
                       ("attn_v", m["Wv"], A_in)):
        mats[name] = compile_matrix(name, W, X, csd=csd)
    qf, kf, vf, avf = float_attention(m, A_in)
    mats["attn_o"] = compile_matrix("attn_o", m["Wo"], avf, csd=csd)
    # static gain-cell / requant scales for the analog attention chain
    dq8 = float(np.max(np.abs(qf))) / G.X_MAX or 1.0
    dk4 = float(np.max(np.abs(kf))) / G.W_MAX or 1.0
    dv4 = float(np.max(np.abs(vf))) / G.W_MAX or 1.0
    mats["attn_q"]["dq8"], mats["attn_k"]["dk4"], mats["attn_v"]["dv4"] = dq8, dk4, dv4

    # --- bit-true attention through the golden model ---
    rope = lambda v, t: G.rope_norm(v, t, base=m["rope_base"])  # noqa: E731
    o8, atr = G.attention_forward(mats["attn_q"], mats["attn_k"],
                                  mats["attn_v"], mats["attn_o"], A_in,
                                  sm_beta=1.0, rope=rope, score_gain=score_gain)
    attn_out = o8 * mats["attn_o"]["dy"]                      # head-0 contribution
    H = E + attn_out
    F_in = rms_rows(H, m["ffn_norm"], m["rms_eps"])
    log(f"[compile] attention done ({time.time() - t_start:.1f}s)")

    # --- FFN matrices (calibration = real post-attention stream) ---
    mats["ffn_gate"] = compile_matrix("ffn_gate", m["Wg"], F_in, csd=csd)
    mats["ffn_up"] = compile_matrix("ffn_up", m["Wu"], F_in, csd=csd)
    gf = F_in @ m["Wg"].T
    hvf = (gf / (1.0 + np.exp(-gf))) * (F_in @ m["Wu"].T)
    mats["ffn_down"] = compile_matrix("ffn_down", m["Wd"], hvf, csd=csd)

    ffn = [G.ffn_forward_gated(mats["ffn_gate"], mats["ffn_up"],
                               mats["ffn_down"], F_in[t]) for t in range(T)]
    ffn_out = np.stack([f["out8"] for f in ffn]) * mats["ffn_down"]["dy"]
    OUTX = H + ffn_out
    assert np.isfinite(OUTX).all() and np.max(np.abs(OUTX)) < 1e3, "insane output"
    log(f"[compile] FFN done ({time.time() - t_start:.1f}s)")

    # --- ABFT budgets + early-termination stats over the whole real stream ---
    stream = {  # bit-true INT8 input stream per matrix per token
        "attn_q": [G.quant_in(mats["attn_q"], A_in[t]) for t in range(T)],
        "attn_k": [G.quant_in(mats["attn_k"], A_in[t]) for t in range(T)],
        "attn_v": [G.quant_in(mats["attn_v"], A_in[t]) for t in range(T)],
        "attn_o": [atr[t]["av8"] for t in range(T)],
        "ffn_gate": [G.quant_in(mats["ffn_gate"], F_in[t]) for t in range(T)],
        "ffn_up": [G.quant_in(mats["ffn_up"], F_in[t]) for t in range(T)],
        "ffn_down": [G.quant_in(mats["ffn_down"], ffn[t]["h_raw"]) for t in range(T)],
    }
    budgets, nev_hist, resid_max = {}, {}, {}
    for n, C in mats.items():
        residuals, hist = [], np.zeros(16, dtype=np.int64)
        for t in range(T):
            p = layer_passes(C, stream[n][t])
            residuals.append(int(p["resid"].max()))
            hist += np.bincount(p["n_eval_conv"], minlength=16)
        resid_max[n] = max(residuals)
        budgets[n] = G.abft_budget(residuals)
        nev_hist[n] = hist
    log(f"[compile] budgets/stats done ({time.time() - t_start:.1f}s)")

    if csd:  # task A: measured density/charge report (flag-gated emission)
        (out / "csd_report.json").write_text(
            json.dumps(csd_report(mats, stream), indent=1))

    # --- representative passes for A2's SPICE testbenches ---
    last_xq = {n: stream[n][T - 1] for n in mats}
    reps = select_passes(mats, last_xq, budgets, T - 1)
    pass_dirs = []
    for i, p in enumerate(reps):
        d = out / "passes" / f"pass_{i:02d}_{p['tag']}"
        emit_spice.emit_pass_dir(d, p, G.TQ_SIM)
        pass_dirs.append({"dir": str(d.relative_to(out)), "tag": p["tag"],
                          "matrix": p["matrix"], "ct": p["ct"], "rt": p["rt"]})

    # --- programming vectors + activation streams (npz) ---
    for n, C in mats.items():
        np.savez_compressed(out / "programming" / f"{n}.npz",
                            Wq=C["Wq"], Cp=C["Cp"], Cn=C["Cn"], chk=C["chk"],
                            e4=C["e4"],
                            s16=C["s16"], smooth=C["smooth"], dw=C["dw"],
                            dx_in=C["dx_in"], D=C["D"], dy=C["dy"],
                            scale=C["scale"], shift=C["shift"], offset=C["offset"])
        np.savez_compressed(out / "acts" / f"{n}.npz",
                            xq=np.stack(stream[n]))

    # --- golden observation-point trace ---
    Tpad = np.zeros((T, T))
    for t in range(T):
        Tpad[t, :t + 1] = atr[t]["p"]
    np.savez_compressed(
        out / "golden_trace.npz",
        ids=np.array(ids), E=E, A_in=A_in,
        q8=np.stack([a["q8"] for a in atr]), q8p=np.stack([a["q8p"] for a in atr]),
        k4=np.stack([a["k4"] for a in atr]), v4=np.stack([a["v4"] for a in atr]),
        p=Tpad, av8=np.stack([a["av8"] for a in atr]), attn_out8=o8,
        H=H, F_in=F_in,
        g8=np.stack([f["g8"] for f in ffn]), u8=np.stack([f["u8"] for f in ffn]),
        ffn_out8=np.stack([f["out8"] for f in ffn]), out=OUTX)

    # --- digital-rail config (A4 port fields, exact widths) ---
    def rounds(R):
        return [15] * (R // 15) + ([R % 15] if R % 15 else [])
    dig = {
        "note": "fields match scripts/digital/INTERFACES.md; requant scale is "
                "unsigned 8b per channel, shift 0..24, offset signed 8b after "
                "shift; bacc tile_cnt is 4b so row-tiles accumulate in "
                "fabric-summed rounds (acc_rounds).",
        "abft_wiring": "rail abft_check computes a plain sum: feed "
                       "y_flat[j] = s16[j]*acc_j and y_chk_port = (acc_chk<<3)"
                       " + sum_over_passes(round_half_away(e_tile.xq_tile/D))."
                       " e_tile (programming/<m>.npz key e4) is the compile-"
                       "time checksum rounding; without the correction the "
                       "budget is traffic-dominated and hides cap faults. "
                       "Budget below is in y12/acc LSBs. Widen budget during "
                       "LoRA-active passes (sidecar bypasses the chk column).",
        "matrices": {n: {
            "shape": list(C["Wq"].shape),
            "col_tiles": C["Wq"].shape[0] // TILE,
            "row_tiles": C["Wq"].shape[1] // TILE,
            "acc_rounds": rounds(C["Wq"].shape[1] // TILE),
            "D": C["D"], "relu_en": 0,
            "wfmt": "int4", "afmt": "int8",             # A5b format fields:
            "slices": 1, "slice_sig": [1],              # identity case S=1,
            "b_eff": 4, "b_x": 8, "nibble_rounds": 1,   # 2 nibbles = 1 round
            "requant": {"scale": C["scale"].tolist(),
                        "shift": C["shift"].tolist(),
                        "offset": C["offset"].tolist()},
            "abft": {"s": C["s16"].tolist(), "chk_shift": G.CHK_SHIFT,
                     "budget": budgets[n], "max_clean_residual": resid_max[n]},
            # item S5 merged single conversion (law:bout): one 8b
            # statistical conversion of the full 255tq window; digital
            # runs nibble_combine in BYPASS (passthrough) mode, y unit =
            # D_merged (see golden.tile_mvm_merged + INTERFACES.md).
            "merged": {"D_merged": C["D_merged"], "nibble_bypass": 1,
                       "requant": {"scale": C["scale_m"].tolist(),
                                   "shift": C["shift_m"].tolist(),
                                   "offset": C["offset"].tolist()}},
        } for n, C in mats.items()},
        "relu_note": "relu_en=0 for all real-model matrices: outputs span "
                     "multiple row-tiles so a per-pass sign strobe is not the "
                     "final sign. Fixture-scale ReLU FFN (single row-tile) "
                     "sets relu_en=1 on the HI conversion, skips LO when HI "
                     "exits, asserts relu_en on LO only when code_hi==0, and "
                     "the fabric ReLU-clamps the recombined y12 to >=0 (see "
                     "golden tile_mvm docstring for the exactness bound).",
        "attention": {"dq8": dq8, "dk4": dk4, "dv4": dv4, "sm_beta": 1.0,
                      "rope_base": m["rope_base"], "rms_eps": m["rms_eps"],
                      # PTAT score pre-scale (#25); only emitted when opted in
                      # so the default path stays byte-identical.
                      **({"score_temp_k": score_temp, "score_gain": score_gain}
                         if score_temp is not None else {})},
    }
    (out / "digital_config.json").write_text(json.dumps(dig, indent=1))

    # --- pass counts + manifest ---
    pt = pass_table(mats, T)
    pt["n_eval_histogram_per_matrix"] = {n: h.tolist() for n, h in nev_hist.items()}
    pt["n_eval_mean_per_conversion"] = {
        n: float(np.sum(np.arange(16) * h) / max(h.sum(), 1))
        for n, h in nev_hist.items()}
    (out / "passes.json").write_text(json.dumps(pt, indent=1))

    manifest = {
        "model": str(model_path), "arch_meta": {k: int(v) if isinstance(v, (int, np.integer)) else v
                                                for k, v in EXPECT_META.items()},
        "head": HEAD, "prompt": prompt, "token_ids": ids, "token_pieces": pieces,
        "tokenizer": "greedy longest-match over GGUF vocab (ignores BPE merge "
                     "ranks; documented fidelity caveat in gguf_reader.py)",
        "t_q_sim_s": G.TQ_SIM, "t_q_target_s": 200e-12,
        "vdd": emit_spice.VDD, "seed": SEED,
        "wfmt": "int4", "afmt": "int8",
        "matrices": {n: {
            "shape": list(C["Wq"].shape), "D": C["D"], "dx_in": C["dx_in"],
            "dy": C["dy"], "passes_per_token": count_passes(C["Wq"].shape),
            "budget": budgets[n], "zero_scale_channels": C["zero_scale_ch"],
            "sqnr_w_db": round(C["sqnr_w_db"], 2),
        } for n, C in mats.items()},
        "tile_passes_per_token_total": pt["tile_passes_per_token_total"],
        "files": {"digital_config": "digital_config.json",
                  "passes": "passes.json", "trace": "golden_trace.npz",
                  "programming": "programming/<matrix>.npz",
                  "acts": "acts/<matrix>.npz", "rep_passes": pass_dirs},
        "formats": "see scripts/compiler/FORMATS.md",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    log(f"[compile] wrote {out} ({time.time() - t_start:.1f}s total); "
        f"{pt['tile_passes_per_token_total']} tile passes/token; "
        f"{len(reps)} representative passes")
    return {"mats": mats, "manifest": manifest, "trace": atr, "ffn": ffn,
            "out": OUTX, "stream": stream, "budgets": budgets, "ids": ids}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--wfmt", default="int4", choices=sorted(F.FORMATS),
                    help="weight source format (default int4 = frozen A5 path)")
    ap.add_argument("--afmt", default="int8", choices=sorted(F.FORMATS),
                    help="activation source format (default int8)")
    ap.add_argument("--target-bits", type=int, default=F.BY_CEIL_BITS,
                    help="requested effective mantissa precision cap")
    ap.add_argument("--csd", action="store_true",
                    help="canonical-signed-digit C+/C- cap split (task A); "
                         "MACs bit-identical, writes out_csd/ + csd_report")
    ap.add_argument("--dps48", action="store_true",
                    help="DPS rank-48 bilinear lowering (task B); writes "
                         "out_dps48/ (combo tiles + recombination schedule)")
    ap.add_argument("--lattice", action="store_true",
                    help="CSNR mid-lattice converter thresholds (task C); "
                         "writes out_lattice/ (per-tensor tap-code schedule "
                         "+ measured CSNR gain curve)")
    ap.add_argument("--prompt", default=PROMPT)
    ap.add_argument("--out", default=None)
    ap.add_argument("--score-temp", type=float, default=None,
                    help="device temp (Kelvin) for #18/#25 PTAT score "
                         "pre-scale (score spread x T/T0); unset = T0 = "
                         "byte-identical default path")
    a = ap.parse_args()
    if a.dps48:
        assert a.wfmt == "int4" and a.afmt == "int8" and not a.csd, \
            "--dps48 lowers the default int4 x int8 path"
        from compiler import dps48
        dps48.run_dps48(prompt=a.prompt, out=a.out)
    elif a.lattice:
        assert a.wfmt == "int4" and a.afmt == "int8" and not a.csd, \
            "--lattice applies to the default int4 x int8 path"
        from compiler import lattice
        lattice.run_lattice(prompt=a.prompt, out=a.out)
    elif a.wfmt == "int4" and a.afmt == "int8" and a.target_bits == F.BY_CEIL_BITS:
        out = Path(a.out) if a.out else (OUT.parent / "out_csd" if a.csd else OUT)
        run(prompt=a.prompt, out=out, csd=a.csd, score_temp=a.score_temp)
    else:
        assert not a.csd, "--csd applies to the default int4 path"
        run_formats(a.wfmt, a.afmt, prompt=a.prompt, target=a.target_bits,
                    out=a.out)
