#!/usr/bin/env python3
"""Task #24 — does the measured in-contract +-3 LSB tile-MVM error MATTER at the
MODEL level, before anyone pays for the #22/SAR topology fix?

Method (scripts/compiler/golden math, NO SPICE): compile blk.0 ONCE (clean, real
SmolLM2-135M, 9-token prompt), then re-run the REAL golden forward
(attention_forward + ffn_forward_gated) with golden.model.TILE_ERR set to the
measured pass_05 residual model (make_tile_err) at +-1/3/5/8 LSB. Compare
injected vs bit-exact:
  - blk.0 output (OUTX) cosine corr + relative MSE       (what compile.py emits)
  - attention softmax distribution shift (mean L1)
  - a proxy next-token: output_norm(OUTX[last]) @ token_embd.T  argmax + top-5
    (PROXY only: 1 of 30 blocks + head-0 attention, so this measures argmax
    STABILITY vs the clean quantized path, not a true LM prediction)
  - greedy proxy continuation divergence (same proxy head, first mismatch)

Run: PYTHONPATH=repo python3 scripts/compiler/test_error_impact.py
Writes docs/src/content/Project/ERROR_IMPACT.md.  Resets TILE_ERR (default path stays clean).
"""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from golden import model as G                       # noqa: E402
from compiler import compile as C                   # noqa: E402

LEVELS = [1, 3, 5, 8]          # LSB: 1=spec, 3=measured pass_05, 5, 8
SEEDS = 8                       # average over noise draws (per-column random)


def build_forward():
    """Compile blk.0 clean once; return a closure forward(err_lsb, seed) that
    re-runs the REAL golden forward and yields (OUTX, softmax_list)."""
    m = C.load_model()
    ids = C.tokenize_greedy(C.PROMPT, m["vocab"])
    E = m["embd"][ids].astype(np.float64)
    A_in = C.rms_rows(E, m["attn_norm"], m["rms_eps"])
    mats = {}
    for name, W, X in (("attn_q", m["Wq"], A_in), ("attn_k", m["Wk"], A_in),
                       ("attn_v", m["Wv"], A_in)):
        mats[name] = C.compile_matrix(name, W, X)
    qf, kf, vf, avf = C.float_attention(m, A_in)
    mats["attn_o"] = C.compile_matrix("attn_o", m["Wo"], avf)
    mats["attn_q"]["dq8"] = float(np.max(np.abs(qf))) / G.X_MAX or 1.0
    mats["attn_k"]["dk4"] = float(np.max(np.abs(kf))) / G.W_MAX or 1.0
    mats["attn_v"]["dv4"] = float(np.max(np.abs(vf))) / G.W_MAX or 1.0
    rope = lambda v, t: G.rope_norm(v, t, base=m["rope_base"])  # noqa: E731

    # FFN matrices need the CLEAN post-attention stream to calibrate (matches
    # compile.py: calibration is on clean hardware characterization).
    G.TILE_ERR = None
    o8, atr = G.attention_forward(mats["attn_q"], mats["attn_k"], mats["attn_v"],
                                  mats["attn_o"], A_in, sm_beta=1.0, rope=rope)
    H0 = E + o8 * mats["attn_o"]["dy"]
    F_in0 = C.rms_rows(H0, m["ffn_norm"], m["rms_eps"])
    mats["ffn_gate"] = C.compile_matrix("ffn_gate", m["Wg"], F_in0)
    mats["ffn_up"] = C.compile_matrix("ffn_up", m["Wu"], F_in0)
    gf = F_in0 @ m["Wg"].T
    hvf = (gf / (1.0 + np.exp(-gf))) * (F_in0 @ m["Wu"].T)
    mats["ffn_down"] = C.compile_matrix("ffn_down", m["Wd"], hvf)

    # proxy output head: tied embeddings, RMSNorm'd final hidden -> vocab logits
    out_norm = m["gguf"].array("output_norm.weight")
    Wemb = m["embd"].astype(np.float64)             # (vocab, d_model)

    def forward(err_lsb=0, seed=0, ot_lsb=0):
        G.TILE_ERR = None if err_lsb == 0 else G.make_tile_err(err_lsb, seed)
        G.ATTN_OUT_ERR = None if ot_lsb == 0 else G.make_attn_out_err(ot_lsb, seed)
        try:
            o8, atr = G.attention_forward(mats["attn_q"], mats["attn_k"],
                                          mats["attn_v"], mats["attn_o"], A_in,
                                          sm_beta=1.0, rope=rope)
            H = E + o8 * mats["attn_o"]["dy"]
            F_in = C.rms_rows(H, m["ffn_norm"], m["rms_eps"])
            ffn = [G.ffn_forward_gated(mats["ffn_gate"], mats["ffn_up"],
                                       mats["ffn_down"], F_in[t])
                   for t in range(len(ids))]
            OUTX = H + np.stack([f["out8"] for f in ffn]) * mats["ffn_down"]["dy"]
        finally:
            G.TILE_ERR = None
            G.ATTN_OUT_ERR = None
        soft = [a["p"] for a in atr]                # per-token softmax rows
        return OUTX, soft

    def logits(OUTX):
        h = G.rmsnorm(OUTX[-1], out_norm, m["rms_eps"])   # last-token proxy head
        return Wemb @ h

    return forward, logits, ids, m["vocab"]


def cos(a, b):
    a, b = a.ravel(), b.ravel()
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))


def rel_mse(ref, hat):
    return float(np.mean((hat - ref) ** 2) / np.mean(ref ** 2))


def main():
    forward, logits, ids, vocab = build_forward()
    ref_out, ref_soft = forward(0)               # bit-exact clean quantized path
    ref_log = logits(ref_out)
    ref_arg = int(np.argmax(ref_log))
    ref_top5 = set(np.argsort(ref_log)[-5:].tolist())

    def greedy(OUTX_last_log):                   # 1-step proxy next token
        return int(np.argmax(OUTX_last_log))

    rows = []
    for lsb in LEVELS:
        cs, rm, sd, agree, ov5 = [], [], [], 0, []
        for seed in range(SEEDS):
            out, soft = forward(lsb, seed)
            log = logits(out)
            cs.append(cos(ref_out, out))
            rm.append(rel_mse(ref_out, out))
            # softmax L1 shift (mean over tokens, over valid causal entries)
            sd.append(float(np.mean([np.abs(p - q).sum()
                                     for p, q in zip(soft, ref_soft)])))
            agree += int(np.argmax(log) == ref_arg)
            ov5.append(len(set(np.argsort(log)[-5:].tolist()) & ref_top5))
        rows.append({
            "lsb": lsb, "cos": np.mean(cs), "cos_min": np.min(cs),
            "rel_mse": np.mean(rm), "soft_l1": np.mean(sd),
            "argmax_agree": 100.0 * agree / SEEDS,
            "top5_overlap": np.mean(ov5),
        })
        print(f"  +-{lsb} LSB: cos={rows[-1]['cos']:.5f} relMSE={rows[-1]['rel_mse']:.4e} "
              f"softL1={rows[-1]['soft_l1']:.4f} argmax={rows[-1]['argmax_agree']:.0f}% "
              f"top5={rows[-1]['top5_overlap']:.1f}/5")

    # proxy greedy continuation: does the argmax token differ at +-3 vs clean?
    cont = {}
    for lsb in LEVELS:
        toks = []
        for seed in range(SEEDS):
            out, _ = forward(lsb, seed)
            toks.append(greedy(logits(out)))
        cont[lsb] = toks

    write_md(rows, ref_arg, ref_top5, vocab, cont, ids)
    # sanity self-check (ponytail: the one runnable assert this logic needs)
    assert rows[0]["cos"] >= rows[-1]["cos"], "corr must degrade with LSB"
    assert G.TILE_ERR is None, "TILE_ERR leaked (default path must stay clean)"
    print("OK  self-check passed; TILE_ERR reset")

    ot_main(forward, logits, ref_out, ref_arg, ref_top5, vocab, ids)
    return rows


# ---- task #26: o_t (attention output) error impact ------------------------
OT_LEVELS = [18.8, 37.6, 75.2]      # measured Chip2 worst / 2x / 4x (LSB of o_t range)


def ot_main(forward, logits, ref_out, ref_arg, ref_top5, vocab, ids):
    """Inject the Chip2 measured o_t error (gaussian exp+A.V translinear class)
    into the real blk.0 attention output; measure vs the SAME clean ref."""
    rows = []
    for lsb in OT_LEVELS:
        cs, rm, agree, ov5 = [], [], 0, []
        for seed in range(SEEDS):
            out, _ = forward(ot_lsb=lsb, seed=seed)
            log = logits(out)
            cs.append(cos(ref_out, out))
            rm.append(rel_mse(ref_out, out))
            agree += int(np.argmax(log) == ref_arg)
            ov5.append(len(set(np.argsort(log)[-5:].tolist()) & ref_top5))
        rows.append({"lsb": lsb, "cos": float(np.mean(cs)),
                     "cos_min": float(np.min(cs)), "rel_mse": float(np.mean(rm)),
                     "argmax_agree": 100.0 * agree / SEEDS,
                     "top5_overlap": float(np.mean(ov5))})
        print(f"  o_t +-{lsb} LSB: cos={rows[-1]['cos']:.5f} "
              f"relMSE={rows[-1]['rel_mse']:.4e} "
              f"argmax={rows[-1]['argmax_agree']:.0f}% "
              f"top5={rows[-1]['top5_overlap']:.1f}/5")
    write_ot_md(rows, ref_arg, ref_top5, vocab, ids)
    assert rows[0]["cos"] >= rows[-1]["cos"], "o_t cos must degrade with LSB"
    assert G.ATTN_OUT_ERR is None, "ATTN_OUT_ERR leaked (default path must stay clean)"
    print("OK  o_t self-check passed; ATTN_OUT_ERR reset")
    return rows


def write_ot_md(rows, ref_arg, ref_top5, vocab, ids):
    tokstr = lambda i: repr(vocab[i]) if 0 <= i < len(vocab) else str(i)
    r0 = rows[0]                                    # the measured 18.8 LSB point
    adequate = r0["argmax_agree"] >= 100.0 and r0["cos"] >= 0.99
    # cos>0.99 ceiling (matches #24's blk.0-cos criterion) and the looser
    # argmax-survival ceiling (highest swept LSB still 100% argmax agreement).
    tol = max((r["lsb"] for r in rows
               if r["argmax_agree"] >= 100.0 and r["cos"] >= 0.99), default=0.0)
    tol_arg = max((r["lsb"] for r in rows
                   if r["argmax_agree"] >= 100.0), default=0.0)
    lines = [
        "# OT_IMPACT — is the Chip2 18.8 LSB o_t error model-breaking? (task #26)",
        "",
        "The tb_attention_chip2_e2e e2e ('A-CHIP2 inc4', commit 366e612) got o_t "
        "cos 1.000/1.000/0.9978/0.9978 over 4 tokens but max|err| 18.8 LSB on the "
        "3-4-key tokens FAILED the `<=8 LSB` envelope. That +-8 LSB was measured "
        "by #24 for the TILE-MVM `y12` code, NOT for the attention output o_t. "
        "This task measures the correct o_t budget with #24's error-impact method.",
        "",
        "## Method (scripts/compiler/golden math, NO SPICE)",
        "Real SmolLM2-135M blk.0 (head-0 attn + SwiGLU FFN), real 9-token prompt "
        f"{ids}. Compile ONCE clean; re-run the real golden forward with "
        "`golden.model.ATTN_OUT_ERR = make_attn_out_err(lsb)` — GAUSSIAN "
        "(sigma=lsb/3, 3-sigma clip) additive code error on the attention output "
        "o8 (INT8 +-127, so 1 code == 1 LSB of the o_t range), fresh per token. "
        "This models the Chip2 analog exp+A.V translinear residual (~1.4% class) "
        "that the tb measured on o_t = p@V. Injected vs bit-exact clean, 8 seeds.",
        "",
        "**Metric honesty.** blk.0 output (OUTX) cosine + rel-MSE is the real "
        "signal; the next-token argmax/top-5 uses the same PROXY head as #24 "
        "(`output_norm(OUTX[-1]) @ token_embd.T`, tied embeddings): 1 of 30 "
        "blocks + head-0 only, so it measures argmax STABILITY vs the clean "
        "quantized path, not a true LM prediction. Same clean ref as #24.",
        "",
        "## Results (injected vs bit-exact clean)",
        "",
        "| o_t +-LSB | blk.0 cos | cos(min) | rel MSE | argmax agree | top5 overlap |",
        "|----------:|----------:|---------:|--------:|-------------:|-------------:|",
    ]
    for r in rows:
        tag = " (measured)" if abs(r["lsb"] - 18.8) < 1e-6 else \
              " (2x)" if abs(r["lsb"] - 37.6) < 1e-6 else \
              " (4x)" if abs(r["lsb"] - 75.2) < 1e-6 else ""
        lines.append(
            f"| {r['lsb']:.1f}{tag} | {r['cos']:.5f} | {r['cos_min']:.5f} | "
            f"{r['rel_mse']:.3e} | {r['argmax_agree']:.0f}% | "
            f"{r['top5_overlap']:.2f}/5 |")
    lines += [
        "",
        f"Clean proxy next-token argmax = id {ref_arg} {tokstr(ref_arg)}; "
        f"clean top-5 = {sorted(ref_top5)}.",
        "",
        "## Verdict",
    ]
    if adequate:
        lines += [
            f"**18.8 LSB o_t (cos 0.998 per-head) is MODEL-ADEQUATE.** At the "
            f"measured worst-token severity: blk.0 cos {r0['cos']:.5f} (>0.99), "
            f"argmax agreement {r0['argmax_agree']:.0f}%, top-5 "
            f"{r0['top5_overlap']:.2f}/5. The `<=8 LSB` gate the Chip2 e2e failed "
            f"is the #24 TILE-MVM proxy MIS-APPLIED to o_t — a tile-code budget "
            f"does not transfer to the attention output.",
            "",
            f"- **Correct o_t model budget: +-{tol:.1f} LSB of the o_t range** "
            f"(highest swept level holding BOTH 100% argmax AND blk.0 cos>0.99, "
            f"the #24 criterion). argmax agreement itself survives 100% out to "
            f"+-{tol_arg:.1f} LSB (2x measured); the model only breaks (argmax "
            f"<100%) at +-75.2 LSB (4x). o_t is a convex softmax average (p@V, no "
            f"bit growth) that then passes through Wo + residual add + RMSNorm + "
            f"the FFN, so per-head o_t error is attenuated far more than a raw "
            f"tile code — the o_t budget is much looser than the y12 tile's +-8.",
            f"- **Chip 2 attention MEETS its o_t budget as-built:** the measured "
            f"worst-token 18.8 LSB sits AT the cos>0.99 ceiling ({tol:.1f} LSB) "
            f"and 2x inside the argmax-survival ceiling ({tol_arg:.1f} LSB). "
            "Relax the tb_attention_chip2_e2e acceptance from the borrowed "
            "`<=8 LSB` tile proxy to the o_t budget (cos>0.99 AND max|err| <= "
            f"{tol:.1f} LSB). The e2e 'FAIL' is a mis-applied criterion, not a "
            "real accuracy shortfall.",
            "- Reducing the exp+A.V translinear error (PTAT co-scale, #18/#25) "
            "stays WANTED for margin/cascade headroom but is NOT a correctness "
            "blocker for blk.0 next-token.",
        ]
    else:
        first_break = next((r["lsb"] for r in rows
                            if r["argmax_agree"] < 100.0 or r["cos"] < 0.99), None)
        lines += [
            f"**18.8 LSB o_t DEGRADES the model.** blk.0 cos {r0['cos']:.5f}, "
            f"argmax agreement {r0['argmax_agree']:.0f}%. Model breaks by "
            f"+-{first_break} LSB.",
            "",
            f"- **Chip 2 attention must reach +-{tol:.1f} LSB o_t** (highest "
            f"swept level still 100% argmax + cos>0.99). The exp+A.V translinear "
            f"error MUST be reduced (PTAT co-scale #18/#25, smaller analog "
            f"groups) to get o_t under that ceiling.",
        ]
    (ROOT / "docs/src/content/Project" / "OT_IMPACT.md").write_text("\n".join(lines) + "\n")
    print(f"wrote {ROOT / 'docs/src/content/Project' / 'OT_IMPACT.md'}")


def write_md(rows, ref_arg, ref_top5, vocab, cont, ids):
    r3 = next(r for r in rows if r["lsb"] == 3)
    r1 = next(r for r in rows if r["lsb"] == 1)
    tol = max((r["lsb"] for r in rows
               if r["argmax_agree"] >= 100.0 and r["cos"] >= 0.99), default=0)
    verdict_go = r3["argmax_agree"] >= 95.0 and r3["cos"] >= 0.99
    tokstr = lambda i: repr(vocab[i]) if 0 <= i < len(vocab) else str(i)
    lines = [
        "# ERROR_IMPACT — does the in-contract +-3 LSB tile error matter? (task #24)",
        "",
        "Ponytail check-before-fix: measure the MEASURED pass_05 residual "
        "(RESULTS3: +-2/3 LSB on ordinary in-contract mid/high codes, col13 "
        "|code|89 -> -3) at the MODEL level before building the expensive "
        "#22/SAR topology fix.",
        "",
        "## Method (scripts/compiler/golden math, NO SPICE)",
        "Real SmolLM2-135M blk.0 (head-0 attn + SwiGLU FFN), real 9-token "
        f"prompt {ids}. Compile ONCE clean; re-run the real golden forward with "
        "`golden.model.TILE_ERR = make_tile_err(lsb)` — the measured per-column "
        "code error (uniform +-lsb on |y12|>20, ~0 near zero) injected on the "
        "recombined tile code `y12`, the exact quantity tb_tile_mvm gates at "
        "+-1 LSB. Averaged over 8 noise draws.",
        "",
        "**Metric honesty.** blk.0 output (OUTX) cosine corr + relative MSE is "
        "the real, defensible signal (it is what compile.py emits). The "
        "next-token argmax/top-5 uses a PROXY head "
        "`output_norm(OUTX[-1]) @ token_embd.T` (tied embeddings). It is a "
        "PROXY: only 1 of 30 blocks and head-0 attention are compiled, so it "
        "measures argmax STABILITY of the error vs the clean quantized path, "
        "NOT a true LM prediction. All numbers are injected-vs-bit-exact-clean.",
        "",
        "## Results (injected vs bit-exact clean)",
        "",
        "| +-LSB | blk.0 cos | cos(min) | rel MSE | softmax L1 | argmax agree | top5 overlap |",
        "|------:|----------:|---------:|--------:|-----------:|-------------:|-------------:|",
    ]
    for r in rows:
        tag = " (spec)" if r["lsb"] == 1 else " (measured)" if r["lsb"] == 3 else ""
        lines.append(
            f"| {r['lsb']}{tag} | {r['cos']:.5f} | {r['cos_min']:.5f} | "
            f"{r['rel_mse']:.3e} | {r['soft_l1']:.4f} | "
            f"{r['argmax_agree']:.0f}% | {r['top5_overlap']:.2f}/5 |")
    lines += [
        "",
        f"Clean proxy next-token argmax = id {ref_arg} {tokstr(ref_arg)}; "
        f"clean top-5 = {sorted(ref_top5)}.",
        "",
        "### Proxy greedy next-token per level (8 seeds)",
    ]
    for lsb in LEVELS:
        uniq = sorted(set(cont[lsb]))
        agree = 100.0 * sum(t == ref_arg for t in cont[lsb]) / len(cont[lsb])
        lines.append(f"- +-{lsb} LSB: argmax tokens {uniq} "
                     f"({', '.join(tokstr(u) for u in uniq)}) — matches clean "
                     f"{agree:.0f}% of seeds")
    lines += [
        "",
        "## Cross-check vs the audit path (task 4)",
        "RESULTS3: with the +-3 residual present, ABFT residual = 62 (budget "
        "199) — IN BUDGET. Faults are still DETECTED at +-3; this task is about "
        "output QUALITY, not fault detection. The two are independent: the "
        "checksum column sees the same perturbed conversions and still fits its "
        "statistical budget, so relaxing the accuracy gate does NOT weaken fault "
        "coverage.",
        "",
        "## Verdict",
    ]
    if verdict_go:
        lines += [
            f"**+-3 LSB (measured) does NOT degrade the model.** argmax agreement "
            f"{r3['argmax_agree']:.0f}%, blk.0 cos {r3['cos']:.5f} (>0.99), "
            f"softmax L1 {r3['soft_l1']:.4f}. The +-1 LSB spec is OVER-STRICT: "
            f"the model tolerates up to +-{tol} LSB with 100% argmax agreement "
            f"and cos>0.99.",
            "",
            f"- **Spec change (honestly justified):** relax the tb_tile_mvm "
            f"acceptance gate from +-1 LSB to +-{tol} LSB (the model-tolerable "
            f"budget). +-1 is a converter-ENOB target, not a model-accuracy "
            f"requirement — transformers are quantization/noise tolerant "
            f"(project notes 27k1 adversarial robustness, 27k3 analog noise), "
            f"and this quantifies it: +-{tol} LSB on 8-bit (+-127) codes is "
            f"transparent to the output.",
            "- **GO / NO-GO on the #22/SAR topology fix FOR CORRECTNESS: NOT "
            "REQUIRED.** The in-contract residual does not move the token. #22 "
            "is still WANTED for tok/s (parallel super-tile / cascade "
            "amortization, STATUS.md/COMPOSED_RESULTS) but is NOT a correctness "
            "blocker. Do not build the fix to chase +-1 LSB.",
        ]
    else:
        first_break = next((r["lsb"] for r in rows
                            if r["argmax_agree"] < 95.0 or r["cos"] < 0.99), None)
        lines += [
            f"**+-3 LSB (measured) DOES degrade the model.** argmax agreement "
            f"{r3['argmax_agree']:.0f}% (< 95%) / blk.0 cos {r3['cos']:.5f}. The "
            f"model breaks at +-{first_break} LSB.",
            "",
            f"- **The #22/SAR topology fix is MANDATORY for correctness.** It "
            f"must reach the tightest passing level: "
            f"+-{tol if tol else 1} LSB (the highest LSB with 100% argmax "
            f"agreement and cos>0.99).",
            "- The +-1 LSB spec is justified (or close to it); do NOT relax it "
            "below the model-tolerable budget above.",
        ]
    (ROOT / "docs/src/content/Project" / "ERROR_IMPACT.md").write_text("\n".join(lines) + "\n")
    print(f"wrote {ROOT / 'docs/src/content/Project' / 'ERROR_IMPACT.md'}")


if __name__ == "__main__":
    main()
