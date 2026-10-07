"""N8 compiler co-design & the quality gate (researched 2026-10-05, revised after two critics;
doc: ArchResearch/nodes/N8.md).

THE GATE (option "g43_lossless"; DEFAULT "bundle_lead" = that gate + the lead co-design levers):
  G1 format: lossless tier, W8A8-class (Llama-3-8B literature <= +3 % PPL: SmoothQuant W8A8
     +2.3 %, FP8 ~0; LIT_QUALITY.md 1). W4 weights fail on the proxy even with GPTQ (repo F20).
  G2 analog increment: <= +1.0 % PPL (KL <= 0.01 nats, the quantity actually measured) on
     SmolLM2-135M over the same format run digitally, with a 1 dB cushion (P) for the p10 die and
     calibration drift over temperature (unscored terms, see N8.md).
  G3 (reported, not gating; the user sets the bar): top-1 agreement vs the same-format digital run.
     DEPTH_BUDGET measures 96.6 % at 46 dB, 93.8 % at 43.3 dB (M), so >= 97 % needs ~47 dB (D).

The SNR -> perplexity law (derived: power law fitted to measured runs):
      dPPL_analog[%] = A * 10^(-SNR_dB / 10),   A = 2.0e4  (band 1.0e4 .. 3.8e4)
  SNR = per-MVM-output compute SNR (27g3), every linear layer perturbed, full depth (30 layers).
  Central A from the low-variance estimator, DEPTH_BUDGET KL (30 layers): 40 dB KL 0.0223 +-0.0008,
  46 dB 0.0054 -> A 2.1-2.2e4 (M). Band ends: quality.py design-matched W8A8 4b-slice R128 rows
  (A 0.9-1.0e4, but single-run se ~3 % PPL) and DEPTH_BUDGET PPL ratios (2.7-3.8e4, one passage).
  => +1 % needs 43.0 dB (band 40.0 .. 45.8). Depth: errors add in power over layers (slope 0.966,
  M), so target += 9.66 log10(L / 30): +0.27 dB at Llama-3-8B (32), +4.11 dB at 70B (80).

Error classes (gate weights, dB added to the n5 part before combining; + = gentler):
  fresh additive (thermal, settle, coupling, injection, cap_nl, ref_droop, clip)   0      (the law's class)
  quantization (adc)                       +3.0  D: quant-only row A 0.6e4 = +5.4 dB, one run -> half
  per-cell static weight error (mismatch)   0.0  bracket -3.6 .. +7.0 (DEPTH_BUDGET 5a vs 5b), unmeasured
  column-coherent static residual (row_gain) -3.6  M: frozen per-channel error 2.30x KL (DEPTH_BUDGET 5a)
  The old gate charged 5a's -3.6 dB to n5 'mismatch', a per-cell (5b-class) term: wrong class.

ADC range (measured, scripts/golden/quality/out/sweep.md, W8A8 4b slices R128, per-layer static FS
on per-token-scaled operands): +-4 sigma collapses the model at any resolution (adc 8..10 b:
+356..+361 %); +-16 sigma ~+3 % from clipping; +-32 sigma clip-free. Gate: n5 k_sigma >=
q_clip_sigma, unless the readout declares relative precision (p['adc_float'], an N6 float /
companding / overflow-fallback readout), in which case range is N6's job. The mapping of these
per-layer sigmas to n5's block-scaled k_sigma is unmeasured.

Units: dB, sigma (of the calibrated partial), GPU-hours (one-time), fractions of weight MACs.
Labels: M = measured here (quality.py / repo runs), D = derived, P = projected (literature).
"""
import math

A_PPL = 2.0e4                 # D: dPPL% = A 10^(-SNR/10), central (KL fit, DEPTH_BUDGET)
A_BAND = (1.0e4, 3.8e4)       # D: design-matched quality.py rows .. DEPTH_BUDGET PPL ratios
DEPTH_SLOPE = 0.966           # M: KL vs layers perturbed, power addition (DEPTH_BUDGET 3)
PROXY_LAYERS = 30
CLASS_DB = dict(adc=3.0, mismatch=0.0, row_gain=-3.6)   # see docstring; everything else 0
MISMATCH_BRACKET_DB = (-3.6, 7.0)
CLIP_MIN_SIGMA = 4.0          # the +-4 sigma range the frozen n5 ADC term assumes
GPU_W = 300.0                 # V100 board power for one-time energy (P)


def snr_for_dppl(pct, a=A_PPL):
    """Per-MVM compute SNR (dB) that costs `pct` % PPL on the 30-layer proxy (D)."""
    return 10 * math.log10(a / pct)


def dppl_for_snr(snr_db, a=A_PPL):
    return a * 10 ** (-snr_db / 10)


def depth_db(layers):
    """Extra SNR (dB) a model of `layers` needs over the 30-layer proxy (D, power addition)."""
    return 10 * DEPTH_SLOPE * math.log10(layers / PROXY_LAYERS)


def _o(prov, target_pct=1.0, clip=32.0, credit=0.0, wmin=8, amin=8, die=1.0, rail=0.0,
       gpu_h=0.0, requires=None, tier="lossless", target_db=None, mm_credit=0.0, split=None,
       rescale=False):
    return dict(params=dict(q_snr_target_db=round(target_db or snr_for_dppl(target_pct), 2),
                            q_clip_sigma=clip, q_credit_db=credit, q_mismatch_credit_db=mm_credit,
                            q_min_wbits=wmin, q_min_abits=amin, q_die_margin_db=die,
                            q_rail_macs_frac=rail, q_gpu_h=gpu_h, q_tier=tier,
                            q_dppl_budget_pct=target_pct, q_layers=32),
                provenance=prov, requires=requires or {}, split=split, rescale=rescale)


# Every option = one gate policy, or the lead gate plus one co-design lever (or a bundle).
# `requires` = params the best design must carry (format/geometry the lever implies); used by
# best() below, not by the core model. q_rail_macs_frac = weight MACs moved to the digital rail
# (the core model cannot charge them; best() does, see evaluate()). `split` = per-tensor-class
# targets [(MAC fraction, dB vs the uniform target)] scored as two designs (best()). `rescale` =
# per-tile ADC full scale: one rail multiply per column partial (2 slices / R of the MACs).
FWHT = 0.0025   # D: H_28 (x) H_512 on the 14336-wide down_proj input, 5.3e5 ops vs 2.18e8 MACs/layer
OPTIONS = {
    # ---- gate policies ----------------------------------------------------------------------
    "snr28_w4a8": dict(params=dict(q_snr_target_db=28.0, q_clip_sigma=4.0, q_credit_db=0.0,
                                   q_mismatch_credit_db=0.0, q_min_wbits=4, q_min_abits=8,
                                   q_die_margin_db=0.0, q_rail_macs_frac=0.0, q_gpu_h=0.0,
                                   q_tier="legacy", q_dppl_budget_pct=32.0, q_layers=30),
                       provenance="shipped default, UNIFORM 28 dB on every MVM (specs.SNR_T_ATTN_DB). "
                                  "FALSIFIED as a quality gate: +32 % PPL (D), +65 % at depth (M, "
                                  "DEPTH_BUDGET); +-4 sigma ADC collapses the proxy (M, sweep.md)",
                       requires={}, split=None, rescale=False),
    "g_paper_28_38": _o("the paper's per-class gate (PAPER.md N8): 28 dB attention / 38 dB FFN. By the "
                        "law with Llama-3-8B MAC shares (attention 24 %, FFN 76 %): +10.0 % (D). Scored "
                        "as its uniform equivalent 33.0 dB; outside every quality tier", target_pct=10.0,
                        requires=dict(wbits=8), tier="rejected"),
    "g43_lossless": _o("LEAD gate: G1 W8A8 lossless tier (P, LIT_QUALITY) + G2 <= +1 % PPL proxy "
                       "(43.0 dB, band 40.0-45.8, D from M fits) + depth (+0.27 dB at 32 layers, D) + "
                       "clip-free range 32 sigma (M, sweep.md) + 1 dB p10/drift cushion (P)",
                       requires=dict(wbits=8)),
    "g40_lossless_lowA": _o("G2 at the gentle end of the A band (1e4: design-matched quality.py rows, "
                            "single-run se ~3 %) -> 40.0 dB (D). Sensitivity row, not a policy",
                            target_db=40.0, requires=dict(wbits=8)),
    "g46_lossless_highA": _o("G2 at the strict end of the A band (3.8e4: DEPTH_BUDGET 46 dB PPL ratio) "
                             "-> 45.8 dB (D). Sensitivity row", target_db=45.8, requires=dict(wbits=8)),
    "g47_top1_97": _o("G2 + a G3 bound top-1 >= 97 % vs digital (D: DEPTH_BUDGET 96.6 % at 46 dB, "
                      "flip rate ~ noise rms) -> 47 dB. Only if the user wants token-identical output",
                      target_db=47.0, requires=dict(wbits=8)),
    "g38_3pct": _o("relaxed G2 <= +3 % PPL (38.2 dB, D); INT8 W8A8 '1-3 %' class (P, Kurtic 2025)",
                   target_pct=3.0, requires=dict(wbits=8)),
    "g33_10pct": _o("G2 <= +10 % PPL from analog alone (33.0 dB, D): exceeds every published "
                    "lossless/acceptable tier once the format loss is added (P)", target_pct=10.0,
                    requires=dict(wbits=8), tier="rejected"),
    "g43_w4_acceptable": _o("acceptable tier: W4A8 + GPTQ + learned rotation (SpinQuant +6.6 %, QServe "
                            "+9.1 % at 8B, P) + G2 +1 %; proxy cannot certify W4 (M: +83 % g128 RTN, "
                            "GPTQ W4 fails F20)", wmin=4, credit=0.0, gpu_h=10.0,
                            requires=dict(wbits=4, rot=True), tier="acceptable"),
    # ---- levers on top of the lead gate -----------------------------------------------------
    "lv_affine_cal": _o("per-column gain/offset folded into dequant scale (27d6 class 1, 27k6 "
                        "measure-once half; held-out fit, CSNR_HOLDOUT F2): removes static column "
                        "gain; n5 row_gain is its residual (cal_res), charged -3.6 dB -> 0 credit (D)",
                        requires=dict(wbits=8)),
    "lv_tile_range": _o("per-row-tile x slice-pair static ADC full scale (instead of per layer): "
                        "clip 32 -> 16 sigma (P; unmeasured; the only measured rotation x static-range "
                        "row goes the wrong way). One rail rescale per column partial charged",
                        clip=16.0, requires=dict(wbits=8), rescale=True),
    "lv_dynamic_fs": _o("per-token, per-block ADC full scale from the rail's block amax x per-column "
                        "weight scale: follows the token-to-token partial sigma that a static range "
                        "cannot. clip 32 -> 8 sigma (P); ~R adds per R x C block = 1/C rail ops (0.4 % "
                        "at C 256, D); reference-DAC settle per token unpriced in n6", clip=8.0,
                        rail=1 / 256, requires=dict(wbits=8), rescale=True),
    "lv_interleave": _o("compile-time row permutation spreading outlier channels across tiles "
                        "(SAGE-style; M: ffn_down 44.3 -> 51.1 dB SQNR, IMC_MAPPING_EXPERIMENT); "
                        "credit +3 dB whole-model (P, half the one-tensor number), clip 32 -> 16 (P)",
                        clip=16.0, credit=3.0, requires=dict(wbits=8)),
    "lv_hadamard": _o("random block-Hadamard (QuaRot-style; online H_28 x H_512 on the down_proj input, "
                      "~0.25 % rail ops, D): rho 0.037 -> n5 block rho (M 0.12-0.17 proxy); tolerance "
                      "credit 4.5 dB (D: 5.7 dB measured on W4 g128 at 28 dB, 1 seed, 1-sigma band "
                      "3-8.5 dB; scored at the low-middle); clip stays 32 sigma (rotation x static "
                      "range measured WORSE at 4 sigma)", credit=4.5, rail=FWHT,
                      requires=dict(wbits=8, rot=True)),
    "lv_smooth": _o("SmoothQuant alpha 0.5 folded offline: +4.3 dB (M, sweep.md int4g128 noise0.01); "
                    "repo IMC_SMOOTH_RADIX passes only 2/4 (M) -> credit 3 dB; rho 0.06 (P)", credit=3.0,
                    requires=dict(wbits=8, rho=0.06)),
    "lv_gptq": _o("GPTQ re-quantization (format lever only; W8 RTN already lossless-tier): 0 dB analog "
                  "credit; grouped GPTQ W4-W7 fail the proxy (M, F20)", gpu_h=2.0,
                  requires=dict(wbits=8)),
    "lv_group32_scales": _o("keep Q8_0 group-32 scales (rows per conversion = 32): removes the +3.1 % "
                            "per-channel requant floor (M: KL 0.00046, WEIGHT_REPRESENTATION); 4x "
                            "conversions vs R128", requires=dict(wbits=8, rows=32)),
    "lv_outlier_1pct": _o("outlier input rows to digital (1 row/128 = 0.85 % MACs): +0.5..1.1 dB (M, "
                          "IMC_OUTLIER_PLANES) -> 1 dB; clip 32 -> 8 sigma (P)", clip=8.0, credit=1.0,
                          rail=0.0085, requires=dict(wbits=8, rho=0.05)),
    "lv_outlier_3pct": _o("outlier rows to digital (4 rows/128 = 3.4 % MACs): +2.4..3.4 dB (M) -> 2.9 "
                          "dB; clip 32 -> 6 sigma (P)", clip=6.0, credit=2.9, rail=0.034,
                          requires=dict(wbits=8, rho=0.07)),
    "lv_protect_tensor": _o("one massive-activation FFN-down tensor digital (proxy blk.11: 0.83 % "
                            "MACs, KL /5-8, M IMC_PRECISION_EXPERIMENT; 6.6 dB relief for the other 29 "
                            "layers, M DEPTH_BUDGET, unrotated; Llama-3-8B: layer-1 down_proj, 0.78 % "
                            "MACs, P) -> 6 dB on raw operands", credit=6.0, rail=0.0078,
                            requires=dict(wbits=8)),
    "lv_water_fill": _o("per-tensor-class SNR allocation (27n7; DEPTH_BUDGET 4: ffn_down 89.7 % of the "
                        "KL on 27 % of 8B MACs). Optimum with energy ~ 10^(SNR/10): SNR_i = 5 log10(s_i/m_i) "
                        "+ c -> ffn_down +1.45 dB, the other six classes -5.41 dB vs uniform (D); per-layer "
                        "ADC bits / rows at runtime. Shares measured unrotated", requires=dict(wbits=8),
                        split=[(0.27, 1.45), (0.73, -5.41)]),
    "lv_head_digital": _o("LM head (7.0 % of 8B weight MACs) on the digital rail: small tolerance gain "
                          "(M: adc8 run 356 -> 330 %; Lammie 2026 P) -> 1 dB", credit=1.0, rail=0.070,
                          requires=dict(wbits=8)),
    "lv_cell_predistort": _o("per-cell write predistortion: measure each physical cell once, fold its "
                             "error into the die's own copy of the weights (HBM; no tile SRAM). The "
                             "correction quantizes to 1 LSB of the 8-bit weight: residual 1/12 LSB^2 vs "
                             "the uncorrected 0.10 LSB^2 at 42.9 dB -> +0.8 dB on mismatch (D)",
                             mm_credit=0.8, requires=dict(wbits=8)),
    "lv_noise_inject_ft": _o("noise-injection fine-tune alone (27k1 CNN recipe): insufficient for LLMs "
                             "(27k5, Buchel 2025) -> 1.5 dB (P), ~1B tokens", credit=1.5, gpu_h=500.0,
                             requires=dict(wbits=8)),
    "lv_hwa_distill": _o("hardware-aware distillation (Analog Foundation Models, 20B tokens; 27k5, 27n3): "
                         "noise loss 8-10 % -> 3.8-4.6 % (P) -> ~4 dB (P, weight-noise class mostly); 2.2e4 V100-h at 3.8B -> "
                         "~4.6e4 at 8B (P). Also strengthens the digital baseline (27k5)", credit=4.0,
                         gpu_h=4.6e4, requires=dict(wbits=8)),
    "lv_lora_digital": _o("digital low-rank adapter on the rail (HaLoRA, 0.15 % params; 27k5): ~3 dB "
                          "(P, swept noise, no chip); ~0.3 % rail MACs. Rank-1 correction falsified "
                          "for mismatch (F24)", credit=3.0, rail=0.003, gpu_h=200.0,
                          requires=dict(wbits=8)),
    "lv_kv8": _o("KV cache INT8 on the digital rail (outside analog budget; KV8 ~lossless, KV4 = "
                 "QServe acceptable tier, P). Symmetric: the baseline is scored with KV8 too",
                 requires=dict(wbits=8, kv_bits=8)),
    "lv_lsb_truncation": _o("skip low slice-pair conversions (28m8): the only real slicing saving; "
                            "quality unmeasured, energy delta lives in N4/N6 -> scored = lead",
                            requires=dict(wbits=8)),
    "lv_resistive_ir": _o("IR-drop-aware placement / droop precompensation / LRS-fraction code "
                          "(27f2, 27f5, 27f7): resistive domains only; N/A to the charge default",
                          requires=dict(_na=1)),
    "lv_nvm_program": _o("closed-loop program-under-load, factorized fault routing, learning-to-learn "
                         "(27k6, 27k4, 27j4): program-once NVM only; weights here stream as exact "
                         "digital codes -> N/A (the per-cell measure-once half is lv_cell_predistort)",
                         requires=dict(_na=1)),
    # ---- bundles -----------------------------------------------------------------------------
    "bundle_lead": _o("LEAD design path: affine cal + interleave + protect tensor + Hadamard + KV8. "
                      "Credit = the Hadamard credit only (4.5 dB): the protect-tensor relief was "
                      "measured unrotated and the FWHT flattens that very tensor, so their overlap is "
                      "unmeasured; interleave's +3 dB is P. Clip 32 sigma (16 is contradicted)",
                      clip=32.0, credit=4.5, rail=0.0078 + FWHT, gpu_h=1.0,
                      requires=dict(wbits=8, kv_bits=8, rot=True)),
    "bundle_raw": _o("no rotation: affine cal + protect tensor (6 dB, M unrotated) + dynamic per-block "
                     "FS (clip 8 sigma, P) + KV8", clip=8.0, credit=6.0, rail=0.0078 + 1 / 256,
                     gpu_h=1.0, requires=dict(wbits=8, kv_bits=8), rescale=True),
    "bundle_rot_dfs": _o("bundle_lead + dynamic per-block FS (clip 32 -> 8 sigma, P: rotated partials are "
                         "near-Gaussian, but no rotation x dynamic-range row is measured). Attacks the "
                         "ADC term that binds the rotated stack at 32 sigma", clip=8.0, credit=4.5,
                         rail=0.0078 + FWHT + 1 / 256, gpu_h=1.0,
                         requires=dict(wbits=8, kv_bits=8, rot=True), rescale=True),
    "bundle_lead_lowA": _o("bundle_lead scored at the gentle end of the A band (40.0 dB). Sensitivity row",
                           target_db=40.0, clip=32.0, credit=4.5, rail=0.0078 + FWHT, gpu_h=1.0,
                           requires=dict(wbits=8, kv_bits=8, rot=True)),
    "bundle_hwa": _o("bundle_lead + HWA distillation, its 4 dB applied to the per-cell mismatch term "
                     "only (weight-noise class, P)", clip=32.0, credit=4.5, mm_credit=4.0,
                     rail=0.0078 + FWHT, gpu_h=4.6e4, requires=dict(wbits=8, kv_bits=8, rot=True)),
}
DEFAULT = "bundle_lead"   # the g43 gate + the counted lead levers (n5 default rho already presumes the rotation)
SWEEP = dict(q_dppl_budget_pct=[1.0, 3.0, 10.0])   # informational; the target comes from the option


def _combine(parts_db):
    return -10 * math.log10(sum(10 ** (-v / 10) for v in parts_db.values()))


def target_db(p):
    return (p["q_snr_target_db"] + depth_db(p.get("q_layers", 32)) - p["q_credit_db"]
            + p["q_die_margin_db"])


def gate(p, acc, fmt):
    """Pass iff (1) the format is admissible, (2) the converter range is clip-free
    (n5 k_sigma >= q_clip_sigma, or the readout declares relative precision: p['adc_float']), and
    (3) the class-weighted per-MVM SNR clears target_db(p) (law + depth - credit + cushion).
    Class weights CLASS_DB; q_mismatch_credit_db adds to the per-cell mismatch term only.
    If the params carry no k_sigma (old n5), n5 assumed +-4 sigma and the ADC part is derated
    by 20 log10(q_clip_sigma / 4) instead."""
    parts = dict(acc.get("parts_db") or {})
    k_used = p.get("k_sigma")
    derate = 0.0 if k_used is not None else max(0.0, 20 * math.log10(p["q_clip_sigma"] / CLIP_MIN_SIGMA))
    clip_ok = bool(p.get("adc_float")) or k_used is None or k_used >= p["q_clip_sigma"] - 1e-9
    for n, w in CLASS_DB.items():
        if n in parts:
            parts[n] += w
    if "mismatch" in parts:
        parts["mismatch"] += p.get("q_mismatch_credit_db", 0.0)
    if "adc" in parts:
        parts["adc"] -= derate
    if parts:
        snr = _combine(parts)
    else:
        snr = acc["snr_db"] - derate if math.isfinite(acc["snr_db"]) else acc["snr_db"]
    target = target_db(p)
    margin = snr - target
    fmt_ok = fmt["wbits"] >= p["q_min_wbits"] and fmt["abits"] >= p["q_min_abits"]
    eff = snr + p["q_credit_db"] - p["q_die_margin_db"] - depth_db(p.get("q_layers", 32))
    return dict(passed=bool(margin >= 0 and fmt_ok and clip_ok), target_db=target, margin_db=margin,
                snr_eff_db=snr, adc_derate_db=derate, fmt_ok=fmt_ok, clip_ok=clip_ok,
                dppl_pred_pct=dppl_for_snr(eff) if math.isfinite(eff) else 0.0,
                dppl_band_pct=tuple(dppl_for_snr(eff, a) for a in A_BAND) if math.isfinite(eff) else (0.0, 0.0),
                rail_macs_frac=p["q_rail_macs_frac"], one_time_gpu_h=p["q_gpu_h"], tier=p["q_tier"])


# ---------------------------------------------------------------------------------------------
# Scoring helpers (not used by the core model): best reachable design with an option fixed.
# ---------------------------------------------------------------------------------------------
def _ctx(d, knobs, stack):
    """model.Ctx; stack="frozen" swaps every node except n8 for its shipped copy in
    nodes/default/ (the reference stack whose cu/bits trade is monotone), params re-merged."""
    from arch_eval import model
    if stack == "live":
        return model.Ctx(d, knobs)
    import sys
    ctx = model.Ctx(dict(d, nodes={}, params={}), knobs)
    me = sys.modules[__name__]
    ctx.mods = {nid: (me if nid == "n8_quality" else m) for nid, m in ctx.defaults.items()}
    p = {}
    for nid, m in ctx.mods.items():
        opt = d["nodes"].get(nid, m.DEFAULT)
        ctx.options[nid] = opt
        p.update(ctx.defaults[nid].OPTIONS[ctx.defaults[nid].DEFAULT]["params"])
        p.update(m.OPTIONS[opt]["params"])
    p.update(d["params"])
    ctx.p, ctx.design = p, d
    return ctx


def evaluate(d, rail_frac=0.0, knobs=None, stack="live"):
    """model.evaluate with `rail_frac` of the weight MACs moved to the digital rail (side paths,
    protected tensors, rescales): rail time and energy are charged, the tiles' MAC load drops by
    the same amount, so the useful MAC count is unchanged (neutral, not conservative)."""
    from arch_eval import metric, model
    ctx = _ctx(d, knobs, stack)
    if rail_frac:
        wl = ctx.wl
        extra = rail_frac * wl["weight_macs_per_token"]
        # side MACs per token -> prefill (per request), each decode step, and the latency chain
        wl["att_macs_prefill"] += extra * wl["prompt"]
        wl["att_macs_decode"] += extra * wl["gen"]
        wl["att_macs_per_ctx"] += extra / (wl["ctx_decode_sum"] / wl["gen"])
        wl["weight_macs_per_token"] -= extra       # useful MACs unchanged (moved, not added)
    pts, dies = model.operating_points(ctx)
    s = metric.score(pts, ctx.knobs)
    s["errors"] = ctx.errors
    if s["peak"]:
        s["tile"], s["die"], s["plan"] = dies[(s["peak"]["vdd"], s["peak"]["clk_frac"])]
    s["max_snr_db"] = max((t["quality"]["snr_eff_db"] for t, _, _ in dies.values()), default=float("nan"))
    s["kind"] = next(iter(dies.values()))[0]["arr"].get("kind", "charge") if dies else "charge"
    return s


# live n3 MOS-cap options overwrite cu_fF from mos_fins (critic finding); MOM options read cu_fF: sweep both
GRID = dict(cu_fF=[1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0, 128.0, 256.0], adc_bits=[8, 9, 10, 11, 12, 13, 14],
            rows=[32, 64, 128, 256], adc_share=[4, 8, 16])
GRID_LIVE = dict(GRID, cu_fF=[1.0, 4.0, 16.0, 64.0], mos_fins=[8, 32, 128])   # n3 may be MOS (fins) or MOM (cu)
N4_BY_WBITS = {8: ("w8a8_2slice", "w8a8"), 4: ("w4a8_g128", "w4a8")}   # first that exists
RHO_RAW = dict(rho=0.037, x_rms=0.10)    # M: as-quantized SmolLM2 operands (n5 docstring)
RHO_ROT = dict(rho=0.10, x_rms=0.26)     # M 0.12-0.17 on the proxy after rotation; P 0.10 at 8B
ZERO = dict(tok_s_die=0.0, tops_w=0.0, tok_w=0.0, tok_j=0.0)


def _best1(opt, conditions, grid, stack, dt=0.0):
    """Lexicographic-best design with n8=opt and the target shifted by dt dB."""
    from arch_eval import design, metric, workload
    o = OPTIONS[opt]
    req = dict(o.get("requires", {}))
    knobs = metric.knobs_for(conditions)
    pp = o["params"]
    layers = workload.llama3(knobs.get("model", "8B-class"))["model"]["layers"]
    ctx = _ctx(design.make(), knobs, stack)
    m4 = ctx.mods["n4_formats"]
    wb = req.pop("wbits", 4)
    n4_def = m4.DEFAULT if int(m4.OPTIONS[m4.DEFAULT]["params"].get("wbits", 0)) == wb else None
    n4 = n4_def or next(n for n in N4_BY_WBITS[wb] if n in m4.OPTIONS)
    rows_set = [req.pop("rows")] if "rows" in req else grid["rows"]
    rot, rho_req = req.pop("rot", False), req.pop("rho", None)
    if stack == "live":     # live n5 default = rotated, block-scaled operands (rho_mode "block")
        rho = {} if rot else dict(RHO_RAW, rho_mode="fixed", **({"rho": rho_req} if rho_req else {}))
    else:
        rho = RHO_ROT if rot else dict(RHO_RAW, **({"rho": rho_req} if rho_req else {}))
    rng = (dict(k_sigma=pp["q_clip_sigma"]) if stack == "live"
           else dict(k2_aJ=(CLIP_MIN_SIGMA / pp["q_clip_sigma"]) ** 2))
    qd = dict(q_layers=layers, q_snr_target_db=pp["q_snr_target_db"] + dt)
    top, top_d, snr_max, skipped = None, None, float("-inf"), 0
    n1s = [n for n, o1 in ctx.mods["n1_system"].OPTIONS.items()   # ARCH_METRIC: weights stream (user)
           if o1["params"].get("mode") != "resident"]
    for n1 in n1s:
        for rows in rows_set:
            rail = pp["q_rail_macs_frac"] + (2.0 / rows if o.get("rescale") else 0.0)
            for share in grid["adc_share"]:
                for cu in grid["cu_fF"]:
                    for fins in grid.get("mos_fins", [None]):
                        for b in grid["adc_bits"]:
                            par = dict(req, **rho, **rng, **qd, rows=rows, adc_share=share, cu_fF=cu, adc_bits=b,
                                       **({"mos_fins": fins} if fins else {}))
                            d = design.make(dict(n1_system=n1, n4_formats=n4, n8_quality=opt), par,
                                            name=f"{opt}:{n1}:r{rows}:s{share}:cu{cu}:f{fins}:b{b}")
                            try:
                                s = evaluate(d, rail, knobs, stack)
                            except (ValueError, ZeroDivisionError, OverflowError):
                                continue            # another node's law out of its domain here
                            if s["kind"] == "digital":   # all planes digital: digital CIM, out of scope
                                skipped += 1
                                continue
                            snr_max = max(snr_max, s["max_snr_db"])
                            if top is None or metric.better(s, top):
                                top, top_d = s, d
    if top is None:
        top = dict(ZERO, infeasible=True)
    top["max_snr_db"] = snr_max
    top["target_db"] = target_db(dict(pp, **qd))
    top["digital_skipped"] = skipped
    return top_d, top


def best(opt, conditions="arch", grid=None, stack="live"):
    """Lexicographic-best design reachable with n8=opt, other nodes at their DEFAULT options
    (n1: every streaming option; resident is excluded by the user's streaming decision), swept over
    the params the gate pushes on: unit cap (frozen) or MOS fins (live), ADC bits, rows, sharing;
    operand rho raw or rotated per the option. Designs n2 marks kind='digital' are skipped.
    live: converter range = n5 k_sigma set to q_clip_sigma (n5/n6 price it).
    frozen: shipped n5 assumes +-4 sigma; the gate derates the ADC term and n6's 27h1 thermal
    energy is rescaled to the wider range, k2 x (4/clip)^2 (= Vc x clip/4).
    split options: one search per tensor class at its shifted target, combined harmonically by
    MAC fraction (D: per-layer runtime reconfiguration of ADC bits / rows)."""
    o = OPTIONS[opt]
    grid = grid or (GRID_LIVE if stack == "live" else GRID)
    if o.get("requires", {}).get("_na"):
        return None, dict(ZERO, infeasible=True, max_snr_db=float("nan"),
                          note="not applicable to this design family")
    if not o.get("split"):
        return _best1(opt, conditions, grid, stack)
    parts = [(f, _best1(opt, conditions, grid, stack, dt)) for f, dt in o["split"]]
    out = dict(parts[-1][1][1])
    for m in ZERO:
        vals = [s[m] for _, (_, s) in parts]
        out[m] = 0.0 if min(vals) <= 0 else 1 / sum(f / v for (f, _), v in zip(parts, vals))
    out["split"] = [dict(frac=f, d=d and d["name"], **{m: s[m] for m in ZERO}) for f, (d, s) in parts]
    out["max_snr_db"] = min(s["max_snr_db"] for _, (_, s) in parts)
    return parts[0][1][0], out


def baseline(wbits=8, kv_bits=8, conditions="arch"):
    """KV-matched systolic baseline (projected PE numbers): a candidate using KV8 is compared
    with a baseline using KV8 too."""
    from arch_eval import baseline_systolic, metric
    return baseline_systolic.evaluate(wbits, dict(metric.knobs_for(conditions), kv_bits=kv_bits))


def break_even_tokens(gpu_h, e_tok_without_J, e_tok_with_J):
    """One-time adaptation energy / per-token saving it enables (27n3). inf if no saving."""
    de = e_tok_without_J - e_tok_with_J
    return math.inf if de <= 0 else gpu_h * 3600 * GPU_W / de


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    # self-check (fails loudly if the law, the depth term or the class weights drift)
    assert abs(snr_for_dppl(1.0) - 43.01) < 0.01 and abs(dppl_for_snr(28.0) - 31.7) < 0.1
    assert abs(depth_db(32) - 0.271) < 0.01 and abs(depth_db(80) - 4.115) < 0.01
    assert abs(snr_for_dppl(1.0, A_BAND[0]) - 40.0) < 0.01 and abs(snr_for_dppl(1.0, A_BAND[1]) - 45.8) < 0.01
    acc = dict(snr_db=29.7, parts_db=dict(thermal=30.15, mismatch=46.0, adc=40.9))
    g = gate(dict(OPTIONS["g43_lossless"]["params"]), acc, dict(wbits=8, abits=8))
    assert not g["passed"] and abs(g["adc_derate_db"] - 18.06) < 0.01, g
    g = gate(dict(OPTIONS["snr28_w4a8"]["params"]), acc, dict(wbits=4, abits=8))
    assert g["passed"], g
    # class weights: per-cell mismatch neutral, quantization +3 dB, column-coherent residual -3.6 dB
    p0 = dict(OPTIONS["g43_lossless"]["params"], k_sigma=32.0)
    g = gate(p0, dict(snr_db=0, parts_db=dict(mismatch=50.0)), dict(wbits=8, abits=8))
    assert abs(g["snr_eff_db"] - 50.0) < 1e-9 and abs(g["target_db"] - 44.28) < 0.01, g
    g = gate(p0, dict(snr_db=0, parts_db=dict(adc=40.0, row_gain=50.0)), dict(wbits=8, abits=8))
    assert abs(g["snr_eff_db"] - _combine(dict(a=43.0, b=46.4))) < 1e-9, g
    assert not gate(dict(p0, k_sigma=16.0), dict(snr_db=0, parts_db=dict(adc=99.0)), dict(wbits=8, abits=8))["passed"]
    assert gate(dict(p0, k_sigma=16.0, adc_float=True), dict(snr_db=0, parts_db=dict(adc=99.0)),
                dict(wbits=8, abits=8))["passed"]
    assert abs(break_even_tokens(4.6e4, 2e-3, 1e-3) - 4.97e13) / 4.97e13 < 0.01
    print("PASS n8 self-check")
    if "--check" in sys.argv:
        sys.exit(0)
    out = {}
    names = [a for a in sys.argv[1:] if not a.startswith("--")] or list(OPTIONS)
    stack = "frozen" if "--frozen" in sys.argv else "live"
    cond = "sohu" if "--sohu" in sys.argv else "arch"
    for name in names:
        d, s = best(name, cond, stack=stack)
        t = s.get("tile") or {}
        out[name] = dict(design=d and dict(nodes=d["nodes"], params=d["params"]),
                         **{m: s[m] for m in ("tok_s_die", "tops_w", "tok_w", "tok_j")},
                         snr_db=t.get("snr_db"), parts=t.get("snr_parts_db"), max_snr_db=s["max_snr_db"],
                         target_db=s.get("target_db"), gate=t.get("quality"), split=s.get("split"),
                         errors=s.get("errors"))
        print(f"{name:<22} tok/s/die {s['tok_s_die']:>9.4g}  TOPS/W {s['tops_w']:>6.3g}  "
              f"tok/W {s['tok_w']:>7.4g}  tok/J {s['tok_j']:>7.4g}  maxSNR {s['max_snr_db']:5.1f} "
              f"target {s.get('target_db', float('nan')):5.1f}  {d and d['name']}", flush=True)
    for wb, kv in ((8, 8), (8, 16), (4, 8)):
        b = baseline(wb, kv, cond)
        print(f"baseline W{wb} KV{kv}: " + " ".join(f"{m} {b[m]:.4g}" for m in ZERO), flush=True)
    print(json.dumps(out, default=str))
