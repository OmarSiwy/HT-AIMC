"""N10 wildcards: architecture ideas N1-N9 do not own, as tile rewrites the evaluator can score.

`apply(p, tile)` rewrites the composed tile dict for the option in p["wildcard"]; the
default "none" is the identity. CANDIDATES are whole designs (best settings found by
`study()`, 2026-10-05) for search.py. Self-speculative decoding is system-level and does
not fit `apply`; `spec_decode()` scores it with a side model (core hook requested).
Doc: docs/src/content/Project/ArchResearch/nodes/N10.md.

Labels: every output is PROJECTED (the tile it rewrites is projected). Inputs marked
[M] are measured in this repo (sky130), [P] are paper/literature/law.

Options and their laws (per pass = one input vector through one tile):
  ensemble_avg     27c9 (Yousuf 2024): beta = 1+res_tiles independent copies averaged digitally:
                   every random SNR part + 10 log10 beta (1/2 log2 beta bits); cost x beta like below.
  residual_tiles   27c9 (Li 2025): W = sum_n gamma^n W(n), gamma = 1/n_states. Each extra tile
                   adds log2(n_states) bits to the STATIC (programming/mismatch) error only.
                   Cost: phys cols, conversions, area, write bits x (1+N). Digital gamma shift.
  pedestal_sub     27e3: pedestal fraction of full scale = 1/(1+TMR); bits lost log2(1+1/TMR).
                   A signed differential charge column has no pedestal (ped_frac = 0): no-op.
  analog_psum      27l3: K row-tiles share charge before one conversion. Averaging K columns
                   shrinks the converter range Vc' = eta Vc / sqrt(K), so the 27h1 thermal term
                   per conversion grows K/eta^2 while conversions per pass fall 1/K:
                   E_conv/pass = E_th/eta^2 + E_sw/K. eta = 0.84 [M] (CASCADE multibank),
                   gain residual sigma_g = 0.30 % [M] (EG_SERVO) -> SNR part -20log10(sigma_g sqrt K).
                   t_conv/pass /K; ADC area /K.
  bilinear         paper sec_strassen, law:bilinear: passes x r_t = R/8 per level, storage x r_s = R/4
                   (Strassen 7/8, 7/4; DPS rank-48 on 4x4: 48/64, 48/16; DPS-48 (x) Strassen
                   0.656, 5.25). Per stored tile the vectors seen fall r_t/r_s, so e_pass, t_pass
                   x r_t/r_s and cols / r_s (tiles needed x r_s). Weight combos formed on-die from
                   streamed source blocks (HBM bytes unchanged).
                   Operand growth (derived from the exact decompositions: compiler/dps48.py U, V, W
                   for DPS-48; Strassen M1..M7): B-side combo of b_src inputs adds bil_bx planes
                   (RMS growth 1/2 log2 b_src under the high-bit-skip plane schedule n4 uses:
                   DPS-48 1.12, Strassen 0.36; worst case ceil log2: 2.33, 0.71) -> t_word and
                   array energy x (planes+bx)/planes. A-side combo of a_src sources needs bil_ax
                   extra stored bits (mean ceil log2: DPS-48 3.0, Strassen 0.71).
                   Cell (bil_cell): "analog" = continuous charge cell that writes wbits+ax bits
                   exactly (needs >= 7 b write/storage precision, an N3 property; tax = algorithm
                   only); "int4_round" = combos rounded into one INT4 slice by a per-product shift
                   (tax + bil_cell_tax_db: F8 measured sky130 +4.7..10.9 dB, median 7.5, DPS-48).
                   SNR tax = bil_tax_db (paper Table net random: DPS-48 0.13, Strassen 3.0,
                   DPS-48 (x) Strassen 9.2) + bil_cell_tax_db. The S1 bias path (18.1 dB DPS-48)
                   is assumed policed by a servo/ABFT (not in this tile).
                   Digital adds on the rail (e_elem): A-side (a_src-1) per stored element per load
                   plus a_src source reads from a block buffer (e_buf), folded into the per-bit
                   write energy (charged under streaming; resident forms them once); B-side
                   (b_src-1) x rows per input vector, shared by the 5605/cols output tiles; C-side
                   c_terms x cols per pass. Buffer area (16 source blocks, ~0.1 mm2) not modelled.
  unary_pwm        27h9, REPO-A falsified: unary/duration inputs take 2^abits slots instead of
                   the binary-plane schedule: t_word x 2^abits/planes, array energy x 14.112/2.449
                   [M] (code-weighted transfers, IMC_ARCHITECTURE_SEARCH). Stochastic bitstreams
                   are strictly worse (same time plus Bernoulli noise) and are not modeled.
  stack3d          27l8, VERTICAL_3D: L array tiers share one converter tier (hybrid bonding;
                   ASAP7 has no BEOL compute device). Silicon-honest: every tier's area counts
                   toward the iso-area die, so per tile ADC area / L, conversion rounds x L,
                   plus one bond per phys col per tile (bond_um2 = pitch^2, 3 um [P]).
                   Counting footprint instead of silicon is the 27l8 overclaim (x L area).
  residue_imc      24a2 / 28h1 / E-method: coarse pass, in-array subtract, amplify, fine pass.
                   2 passes (t, array x 2); converter energy unchanged: the residue amplifier
                   must hold the full-B-bit noise floor (28m3: 12 kT 4^B), plus an OTA per ADC
                   (static, 79.1 pJ sky130 integrator chain [M] ported VDD^2 is the bound).
  karatsuba        DD notes (three-multiplication product): only when weights AND inputs split
                   into separate sub-MVMs; this core accumulates input planes in charge before
                   one conversion, so with slices < 2 it is a no-op; with W8 (2 slices) it saves
                   1/4 of slice columns; the middle product (a_h+a_l)(b_h+b_l) grows both
                   operands by one bit: -12 dB at a fixed cell full scale.
  factorized       27c9/27c1 (Xu 2025): M = M_A M_B, inner dim r = n: storage x2, passes x2.
  moe_experts, cam_topk_kv, iterative_refinement: infeasible for the ARCH_METRIC workload or
                   scope (dense Llama-3-8B; attention on the digital rail; inference has no
                   fixed-point iteration). apply() fails the quality gate so they score 0.
"""
import math

# Llama-3-8B: sum(K*N)/sum(K) over q,k,v,o,gate,up,down = 4096*53248/38912 = 5605 outputs per
# input element, so one B-side combo vector feeds 5605/cols output tiles (derived, exact dims).
LLAMA_KN_OVER_K = 4096 * 53248 / 38912

# Bilinear decompositions. r_t, r_s: law:bilinear. a_src, b_src, c_terms: mean nonzeros per
# product in U, V and per product output in W (DPS-48 counted from compiler/dps48.py: 448, 288,
# 336 nnz over 48 products; Strassen 12, 12, 12 over 7). bx: RMS B-side planes (1/2 log2 b_src,
# mean); ax: mean ceil(log2 a_src) stored bits. DPS-48 (x) Strassen: products of the two.
def _bil(rt, rs, tax, a_src, b_src, c_terms, bx, ax):
    return dict(wildcard="bilinear", bil_rt=rt, bil_rs=rs, bil_tax_db=tax, bil_a_src=a_src, bil_b_src=b_src,
                bil_c_terms=c_terms, bil_bx=bx, bil_ax=ax, bil_cell="analog", bil_cell_tax_db=0.0)


_D = (48 / 64, 48 / 16, 0.13, 448 / 48, 288 / 48, 336 / 48, 1.12, 3.0)
_S = (7 / 8, 7 / 4, 3.0, 12 / 7, 12 / 7, 12 / 7, 0.5 * 5 / 7, 5 / 7)
BIL = dict(dps48=_bil(*_D), strassen=_bil(*_S),
           dps48_strassen=_bil(_D[0] * _S[0], _D[1] * _S[1], 9.2, *(d * s for d, s in zip(_D[3:6], _S[3:6])),
                               _D[6] + _S[6], _D[7] + _S[7]))

OPTIONS = {
    "none": dict(params=dict(wildcard="none"), provenance="identity"),
    "residual_tiles": dict(params=dict(wildcard="residual_tiles", res_tiles=1, n_states=16),
                           provenance="27c9 (Li 2025 multi-tile residual); projected"),
    "ensemble_avg": dict(params=dict(wildcard="ensemble_avg", res_tiles=15),
                         provenance="27c9 (Yousuf 2024 layer-ensemble averaging): 1/2 log2(beta) bits; projected"),
    "pedestal_sub": dict(params=dict(wildcard="pedestal_sub", ped_frac=0.0),
                         provenance="27e3 pedestal law; signed differential charge column has none"),
    "analog_psum": dict(params=dict(wildcard="analog_psum", psum_K=4, bus_eff=0.84, eg_pct=0.30),
                        provenance="27l3 cascade law (+1 share slot per word); eta 0.84 and servo 0.30 % measured sky130 (CASCADE, EG_SERVO)"),
    "dps48": dict(params=BIL["dps48"],
                  provenance="paper sec_strassen DPS rank-48, analog >= 7 b cell; tax 0.13 dB algorithm (paper "
                             "Table, projected; repo-measured algorithm tax -0.02 dB); operand growth derived "
                             "from compiler/dps48.py"),
    "dps48_int4": dict(params=dict(BIL["dps48"], bil_cell="int4_round", bil_cell_tax_db=7.5),
                       provenance="DPS-48 on an INT4-slice cell: F8 measured sky130 tax median 7.5 dB "
                                  "(range 4.7..10.9)"),
    "strassen": dict(params=BIL["strassen"],
                     provenance="paper sec_strassen law:bilinear, analog cell; tax 3.0 dB net random (projected)"),
    "strassen_int4": dict(params=dict(BIL["strassen"], bil_cell="int4_round", bil_cell_tax_db=1.8),
                          provenance="Strassen on an INT4-slice cell: 3.0 + 1.8 dB (F8 median scaled by "
                                     "0.71/3 shift bits; projected, unmeasured)"),
    "dps48_strassen": dict(params=BIL["dps48_strassen"],
                           provenance="paper sec_strassen: DPS-48 (x) Strassen, x0.656 passes, ~9.2 dB net (projected)"),
    "dps48_strassen_orbit": dict(params=dict(BIL["dps48_strassen"], bil_tax_db=6.2),
                                 provenance="DPS-48 (x) Strassen with the paper's >= 3 dB post-hoc orbit recovery "
                                            "(untested on this decomposition; projected)"),
    "unary_pwm": dict(params=dict(wildcard="unary_pwm", unary_e_ratio=14.112 / 2.449),
                      provenance="27h9; transfer ratio measured (IMC_ARCHITECTURE_SEARCH), falsified there"),
    "stack3d": dict(params=dict(wildcard="stack3d", stack_L=4, bond_um2=9.0),
                    provenance="27l8 + VERTICAL_3D (F19); hybrid-bond pitch projected"),
    "residue_imc": dict(params=dict(wildcard="residue_imc", res_ota_pJ=79.12),
                        provenance="24a2/28h1/28m3; OTA cost from measured sky130 chain (METRICS.md) ported"),
    "karatsuba": dict(params=dict(wildcard="karatsuba"), provenance="DD three-multiplication product; projected"),
    "factorized": dict(params=dict(wildcard="factorized"), provenance="27c9 (Xu 2025 M=M_A M_B); projected"),
    "moe_experts": dict(params=dict(wildcard="infeasible", why="MoE (27l6): Llama-3-8B is dense; P_act = P_tot"),
                        provenance="27l6, MOE_MAPPING.md: not the workload"),
    "cam_topk_kv": dict(params=dict(wildcard="infeasible",
                                    why="analog CAM top-k (27l9): attention is on the digital rail (AGENTS scope); "
                                        "K cache 21 M elements/stream cannot live on the die"),
                        provenance="27l9 (UniCAIM d=4 only, simulation)"),
    "iterative_refinement": dict(params=dict(wildcard="infeasible",
                                             why="28h1/28h4: inference MVMs are used once; no contraction to iterate"),
                                 provenance="28h1, 28h4, 28h5, 28m7"),
}
DEFAULT = "none"
SWEEP = {}   # option-specific params live in CANDIDATES/study(); a sweep under "none" would be a no-op

# Merged or forwarded (not scored here; reason, owner). N10.md lists them in full.
RECORDED = {
    "self_speculative_decode": "system-level; scored by spec_decode() side model; needs a core hook",
    "contextual_sparsity_gather": "union over B >= 64 streams of 10 % active neurons is 1-(0.9)^B ~ 1: no load skipped",
    "noise_as_sampling / thermodynamic / Ising / p-bit": "28j2, 28j4, 28m6: inference is deterministic; sampling O(vocab)/token",
    "photonic_mvm_tile": "28p4: ~5 b ceiling, not ASAP7",
    "low_rank_structured_weights": "28e3: changes the model; Llama-3-8B fixed",
    "event_driven / zero-skip / seeded SAR / Booth skip": "N6; F6 (0.2 %) and F17 (p^N ~ 0) falsified",
    "under-settled column + calibrated gain": "N2 settle_tau knob (5i, 17r1)",
    "nonlinear ADC folding SiLU (27l3 Yang)": "elementwise is 0.02 % of token energy: nothing to fold",
    "charge recycling / resonant drive": "array delivery is ~0.4 % of pass energy (converters ~96 %)",
    "RNS channels, quarter-square, Gilbert, triode cells": "N2/N3 cell options; no note quantifies a win",
    "digital-rail LUT/ROM/CORDIC/interleave": "N7",
    "PTAT recal, PUF, CDS, security gating": "no metric effect (infrastructure)",
    "cryogenic operation": "infeasible for a 100 mm2 inference die (1m4)",
    "ping-pong / overlapped sampling phases (~2.5x usable settle)": "N2: targets t_word of the word-bound tile",
    "incremental delta-sigma on outlier layers, noise-shaped accumulation": "N6 (would re-open analog_psum, residue_imc)",
    "per-group analog VGA / amplified column range before the ADC": "N6: the lever that flips analog_psum and residue_imc",
    "fixed-residual eta-decomposition (sec_strassen)": "no decomposition exists (open computation); bilinear once found",
    "3D-stacked DRAM/SRAM over the die": "bandwidth lever; helps the systolic baseline equally, not an analog advantage",
}


def _combine_db(*parts):
    """Noise-power sum of SNR parts in dB."""
    return -10 * math.log10(sum(10 ** (-x / 10) for x in parts))


def _resnr(t, f):
    """Apply an SNR map f(dB) -> dB to the tile and to the n8 gate's effective SNR, keeping
    whatever else the gate checked (format floor, derates, credits)."""
    q = dict(t["quality"])
    old = q.get("snr_eff_db", t["snr_db"])
    new = f(old)
    t["snr_db"] = f(t["snr_db"])
    m0 = q.get("margin_db", 0.0)
    # every non-SNR condition n8 checked survives (clip_ok=False must stay failed). A gate that
    # reports no flags but failed with margin >= 0 failed on something else: keep that.
    other_ok = q.get("fmt_ok", True) and q.get("clip_ok", True) and (q.get("passed", True) or m0 < 0)
    q["margin_db"] = m0 + new - old
    q["snr_eff_db"] = new
    q["passed"] = bool(q["margin_db"] >= 0 and other_ok)
    q.pop("dppl_pred_pct", None)    # stale after the change; n8 owns that law
    t["quality"] = q


def _pass(t):
    """Re-sum pass energy and time after parts changed (model.tile's own rules)."""
    t["e_pass_J"] = sum(t["e_pass_J_parts"].values())
    t["area_um2"] = sum(t["area_um2_parts"].values())
    tw, tc = t["t_word_ns"], t["t_conv_ns"]
    t["t_pass_s"] = (max(tw, tc) if t["rail"]["pingpong"] else tw + tc) * 1e-9


def apply(p, tile):
    w = p.get("wildcard", "none")
    if w == "none":
        return tile
    t = dict(tile, e_pass_J_parts=dict(tile["e_pass_J_parts"]), area_um2_parts=dict(tile["area_um2_parts"]),
             snr_parts_db=dict(tile["snr_parts_db"]))
    e, a = t["e_pass_J_parts"], t["area_um2_parts"]
    th = t["adc"].get("breakdown_fJ", {}).get("thermal", 0.0) * 1e-15 * t["phys_cols"]   # J per pass
    sw = e["converters"] - th

    if w == "infeasible":
        t["quality"] = dict(t["quality"], passed=False, why=p["why"])
        return t

    if w in ("residual_tiles", "ensemble_avg"):
        n = 1 + int(p["res_tiles"])
        for key in ("array", "converters", "digital_recombination"):
            e[key] *= n
        a["weights"] *= n
        a["adcs"] *= n
        t["write_bits_per_load"] *= n
        t["leak_W"] *= n
        t["phys_cols"] *= n
        mis = t["snr_parts_db"].get("mismatch")
        if w == "ensemble_avg":   # beta = n independent copies averaged: every random part + 10 log10 n
            _resnr(t, lambda x: x + 10 * math.log10(n))
        elif mis is not None:   # only the static part improves: log2(n_states) bits per extra tile
            better = mis + 20 * math.log10(p["n_states"]) * (n - 1)
            t["snr_parts_db"]["mismatch"] = better
            _resnr(t, lambda x: -10 * math.log10(max(1e-30, 10 ** (-x / 10) - 10 ** (-mis / 10)
                                                     + 10 ** (-better / 10))))

    elif w == "pedestal_sub":
        f = p["ped_frac"]   # converter range carrying no information; subtraction removes it
        e["converters"] = sw + th * (1 - f) ** 2

    elif w == "analog_psum":
        K, eta = int(p["psum_K"]), p["bus_eff"]
        e["converters"] = th / eta ** 2 + sw / K
        e["digital_recombination"] /= K
        a["adcs"] /= K
        t["t_conv_ns"] /= K
        t["t_word_ns"] *= 1 + p.get("psum_slots", 1) / t["fmt"]["input_planes"]   # bus share slot
        gain = -20 * math.log10(p["eg_pct"] / 100 * math.sqrt(K))
        t["snr_parts_db"]["psum_gain"] = gain
        _resnr(t, lambda x: _combine_db(x, gain))

    elif w == "bilinear":
        r = p["bil_rt"] / p["bil_rs"]          # vectors per stored tile, relative
        planes = t["fmt"]["input_planes"]
        pf = (planes + p["bil_bx"]) / planes   # B-side combos: extra input planes (word-bound tile)
        e["array"] *= pf
        t["t_word_ns"] *= pf
        for key in e:
            e[key] *= r
        e_add = t["rail"]["e_elem_J"]
        e["c_side_adds"] = p["bil_c_terms"] * t["cols"] * e_add * r
        share = max(1.0, LLAMA_KN_OVER_K / t["cols"])   # tiles along N reuse one input combo
        e["b_side_adds"] = (p["bil_b_src"] - 1) * t["rows"] * e_add * r / share
        t["cols"] = t["cols"] / p["bil_rs"]   # logical outputs per tile -> tiles needed x r_s
        t["t_word_ns"] *= r
        t["t_conv_ns"] *= r
        bits = t["wbits"] + (p["bil_ax"] if p["bil_cell"] == "analog" else 0)   # int4_round keeps 4 b
        t["write_bits_per_load"] *= bits / t["wbits"]
        # A-side combo forming per stored element: (a_src-1) adds + a_src source reads, per written bit
        t["e_write_J_per_bit"] += ((p["bil_a_src"] - 1) * e_add
                                   + p["bil_a_src"] * t["wbits"] / 8 * t["rail"]["e_buf_J_per_byte"]) / bits
        tax = p["bil_tax_db"] + p["bil_cell_tax_db"]
        t["snr_parts_db"]["bilinear_tax_db"] = -tax
        _resnr(t, lambda x: x - tax)

    elif w == "unary_pwm":
        planes = t["fmt"]["input_planes"]
        t["t_word_ns"] *= 2 ** t["fmt"]["abits"] / planes
        e["array"] *= p["unary_e_ratio"]

    elif w == "stack3d":
        L = int(p["stack_L"])
        a["adcs"] /= L
        a["bonds"] = t["phys_cols"] * p["bond_um2"]
        t["t_conv_ns"] *= L

    elif w == "residue_imc":
        e["array"] *= 2
        e["residue_ota"] = t["n_adc"] * p["res_ota_pJ"] * 1e-12 * (t["op"]["vdd"] / 1.8) ** 2
        t["t_word_ns"] *= 2

    elif w == "karatsuba":
        if t["slices"] >= 2:
            for key in ("array", "converters", "digital_recombination"):
                e[key] *= 0.75
            _resnr(t, lambda x: x - 12.04)   # both operands +1 bit

    elif w == "factorized":
        t["cols"] = t["cols"] / 2            # M_A and M_B: storage x2 for r = n -> passes x2

    else:
        raise ValueError(f"unknown wildcard {w!r}")
    _pass(t)
    return t


# ---------------------------------------------------------------- self-speculative decoding
def _decode_time(ctx, t, d, plan, vectors, w_frac, kv_frac, B, x_frac=1.0):
    """One decode step's binding time with `vectors` tile vectors, w_frac of the weight bytes,
    kv_frac of the KV read and x_frac of the pass time (an MSB-plane draft on a word-bound
    tile runs fewer input planes; 1 for the systolic tile). ponytail: mirrors model.system_point's decode resources;
    replace with a core `tokens_per_step` hook when model.py grows one."""
    k, wl, rail = ctx.knobs, ctx.wl, t["rail"]
    D, streaming = plan["dies"], plan["mode"] == "streaming"
    need = d["tiles_needed"]
    if streaming:
        loads = -(-need // d["n_tiles"])
        tp = x_frac * t["t_pass_s"]
        per = max(t["t_load_s"], vectors * tp) if ctx.p.get("double_buffer") else t["t_load_s"] + vectors * tp
        comp = loads * per
    else:
        comp = vectors * x_frac * t["t_pass_s"] / max(1, D * d["n_tiles"] // need)
    ctx_avg, kvb = wl["ctx_decode_sum"] / wl["gen"], wl["kv_bytes_per_token"]
    w_bytes = wl["stored_weights"] * t["wbits"] / 8 if streaming else 0
    hbm = (w_frac * w_bytes + kv_frac * B * ctx_avg * kvb + B * kvb) / (D * k["hbm_Bps"])
    att = vectors * wl["att_macs_per_ctx"] * ctx_avg / (D * rail["att_mac_per_s"])
    return max(comp, hbm, att), hbm * D * k["hbm_Bps"]


def spec_decode(s, ctx, k_draft=3, alpha=0.7, f_w=0.5, f_kv=0.5, f_x=None):
    """Self-speculative decode at a scored design's peak point (B, VDD and clock held).
    Draft = k_draft steps reading f_w of the weight bytes (MSB bit-planes, 28m8) and f_kv of
    the KV; verify = one step with B(k+1) vectors sharing one weight load and one KV read.
    Accepted tokens per stream per cycle tau = (1 - alpha^(k+1)) / (1 - alpha) (Leviathan 2023).
    alpha is unmeasured for an MSB-slice draft: sweep it. f_x: the draft's input-plane fraction
    (default f_w on an IMC tile, 1 on the systolic tile). Returns the four metrics."""
    pk, t, d, plan = s["peak"], s["tile"], s["die"], s["plan"]
    wl, B, G, P = ctx.wl, pk["B"], ctx.wl["gen"], ctx.wl["prompt"]
    tau = (1 - alpha ** (k_draft + 1)) / (1 - alpha)
    if f_x is None:
        f_x = f_w if "input_planes" in t["fmt"] else 1.0
    t_draft, by_draft = _decode_time(ctx, t, d, plan, B, f_w, f_kv, B, f_x)
    t_ver, by_ver = _decode_time(ctx, t, d, plan, B * (k_draft + 1), 1.0, 1.0, B)
    t_base, by_base = _decode_time(ctx, t, d, plan, B, 1.0, 1.0, B)
    cycle = k_draft * t_draft + t_ver
    T = pk["T_prefill_s"] + G / tau * cycle
    T0 = pk["T_wave_s"]
    ept = pk["energy_per_token_J"]
    toks = P + G
    pass_f = (P + G * (k_draft * f_x + k_draft + 1) / tau) / toks    # weight-pass energy factor
    load_f = (1 + G / tau * (k_draft * f_w + 1)) / (1 + G)              # streaming writes follow loads
    att_f = (wl["att_macs_prefill"] + wl["att_macs_decode"] * (2 * k_draft + 1) / tau) / (
        wl["att_macs_prefill"] + wl["att_macs_decode"])
    by_pre = 2 * B * P * wl["kv_bytes_per_token"] + (wl["stored_weights"] * t["wbits"] / 8
                                                     if plan["mode"] == "streaming" else 0)
    by_f = (by_pre + G / tau * (k_draft * by_draft + by_ver)) / (by_pre + G * by_base)
    die_e = (ept["weight_passes"] * pass_f + ept["attention"] * att_f + ept["elementwise"]
             + ept.get("weight_write", 0) * load_f + ept["d2d"] + ept["static"] * T / T0
             + ept["hbm_phy"] * by_f)
    ext_e = ept["external_memory"] * by_f
    tok_s = B * toks / T / pk["dies"]
    p_die = die_e * tok_s
    useful = pk["useful_macs_s_die"] * T0 / T
    return dict(tau=tau, per_stream_tok_s=tau / cycle, tok_s_die=tok_s, tops_w=2 * useful / p_die / 1e12,
                tok_w=1 / (die_e + ext_e), speedup=T0 / T, bytes_factor=by_f)


# ---------------------------------------------------------------- bilinear on the baseline
# Worst-case operand growth (a PE has no plane skip; bit-exact needs the full width).
BIL_MAX = dict(dps48=dict(ax=4, bx=4), strassen=dict(ax=1, bx=1))


def baseline_bilinear(alg, conditions="arch"):
    """baseline_systolic.evaluate with the same law:bilinear lowering (tax 0: exact integer).
    PE energy and area scale with operand width: x max(1, (wbits+ax)/8) x (8+bx)/8.
    ponytail: swaps baseline_systolic.tile inside the call only."""
    from arch_eval import baseline_systolic as bs, metric
    b, mx = BIL[alg], BIL_MAX[alg]
    wb = metric.SOHU_WBITS if conditions == "sohu" else 4
    orig = bs.tile

    def tile(*a, **k):
        t = orig(*a, **k)
        r = b["bil_rt"] / b["bil_rs"]
        wf = max(1.0, (wb + mx["ax"]) / 8) * (8 + mx["bx"]) / 8
        e, ea = t["e_pass_J_parts"], t["rail"]["e_elem_J"]
        e["pe_macs"] *= wf
        for key in e:
            e[key] *= r
        e["c_side_adds"] = b["bil_c_terms"] * t["cols"] * ea * r
        e["b_side_adds"] = (b["bil_b_src"] - 1) * t["rows"] * ea * r / max(1.0, LLAMA_KN_OVER_K / t["cols"])
        t["e_pass_J"] = sum(e.values())
        t["area_um2"] *= wf
        t["area_um2_parts"] = dict(pes=t["area_um2"])
        t["cols"] /= b["bil_rs"]
        t["t_pass_s"] *= r
        t["e_write_J_per_bit"] += ((b["bil_a_src"] - 1) * ea
                                   + b["bil_a_src"] * wb / 8 * t["rail"]["e_buf_J_per_byte"]) / 8
        return t
    bs.tile = tile
    try:
        return bs.evaluate(wb, metric.knobs_for(conditions))
    finally:
        bs.tile = orig


# ---------------------------------------------------------------- study (writes no files)
VARIANTS = {   # option -> list of option-param overrides the study tries
    "none": [{}], "pedestal_sub": [{}], "ensemble_avg": [{"res_tiles": 3}, {"res_tiles": 15}, {"res_tiles": 63}],
    "residual_tiles": [{"res_tiles": 1}, {"res_tiles": 2}],
    "analog_psum": [{"psum_K": 2}, {"psum_K": 4}, {"psum_K": 8}],
    "dps48": [{}], "dps48_int4": [{}], "strassen": [{}], "strassen_int4": [{}],
    "dps48_strassen": [{}], "dps48_strassen_orbit": [{}],
    "unary_pwm": [{}], "stack3d": [{"stack_L": 2}, {"stack_L": 4}], "residue_imc": [{}],
    "karatsuba": [{}, {"wbits": 8}], "factorized": [{}], "moe_experts": [{}], "cam_topk_kv": [{}],
    "iterative_refinement": [{}],
}
BASE_GRID = dict(wbits=[4, 8], adc_bits=[6, 7, 8, 10, 12], cu_fF=[1.0, 1.5, 2.0, 3.0, 4.0], rows=[128, 256])


class frozen:
    """Score against the frozen shipped defaults (nodes/default/) for N1-N9 instead of the live,
    concurrently edited modules, so relative effects are reproducible. Scoped to study().
    ponytail: patches model.importlib inside the block only."""
    def __enter__(self):
        import importlib
        from arch_eval import model
        self.m, self.orig = model, model.importlib

        class _Redirect:
            @staticmethod
            def import_module(name):
                if name.startswith("arch_eval.nodes.n") and not name.endswith("n10_wildcards"):
                    name = name.replace("arch_eval.nodes.", "arch_eval.nodes.default.")
                return importlib.import_module(name)
        model.importlib = _Redirect
        return self

    def __exit__(self, *exc):
        self.m.importlib = self.orig


def study(conditions="arch", nodes=None, verbose=True, options=None, params=None, n1s=None):
    """Best design per option over n1 options x BASE_GRID x VARIANTS (other nodes at their
    current defaults, or `nodes`, e.g. {"n8_quality": "snr28_w4a8"}). -> {option: (score, design)}.
    Wrap in `with frozen():` for the reproducible shipped-default base."""
    import itertools
    from arch_eval import design, metric, model
    n1 = model.Ctx(design.make()).mods["n1_system"]
    knobs = metric.knobs_for(conditions)
    out = {}
    for opt, variants in VARIANTS.items():
        if options and opt not in options:
            continue
        best = None
        for n1o, var in itertools.product(n1s or n1.OPTIONS, variants):
            for vals in itertools.product(*BASE_GRID.values()):
                prm = dict(params or {}, **dict(zip(BASE_GRID, vals), **var))
                dz = design.make(dict(nodes or {}, n1_system=n1o, n10_wildcards=opt), prm, name=f"n10:{opt}")
                try:
                    s = model.evaluate(dz, knobs)
                except Exception:  # noqa: BLE001  (a live N1-N9 module mid-edit; skip the point)
                    continue
                if best is None or metric.better(s, best[0]):
                    best = (s, dz)
        out[opt] = best
        if verbose and best:
            s, dz = best
            print(f"{opt:<22} tok/s/die {s['tok_s_die']:>9.5g}  TOPS/W {s['tops_w']:>6.3g}  tok/W {s['tok_w']:>7.4g}"
                  f"  tok/J {s['tok_j']:>7.4g}  {dz['nodes']['n1_system']} {dz['params']}")
    return out


# Best settings per option from study() on the frozen shipped-default base, streaming (ARCH_METRIC
# fixes the dataflow), 2026-10-05 21:30 (N10.md "Scores"); the gate is n8's. Param names belong
# to n1/n3/n5/n6. dps48 assumes an N3 analog cell with >= 7 b write precision.
_R7 = dict(rows=256, adc_bits=7)
_ST = {"n1_system": "streaming"}
CANDIDATES = {
    "n10_dps48": dict(nodes=dict(_ST, n10_wildcards="dps48"), params=dict(_R7)),
    "n10_strassen": dict(nodes=dict(_ST, n10_wildcards="strassen"), params=dict(rows=128, adc_bits=8, cu_fF=1.5)),
    "n10_analog_psum8": dict(nodes=dict(_ST, n10_wildcards="analog_psum"), params=dict(_R7, psum_K=8)),
    "n10_stack3d_L4": dict(nodes=dict(_ST, n10_wildcards="stack3d"), params=dict(_R7, stack_L=4)),
    "n10_residual_tiles": dict(nodes=dict(_ST, n10_wildcards="residual_tiles"), params=dict(_R7, res_tiles=1)),
    "n10_ensemble_avg4": dict(nodes=dict(_ST, n10_wildcards="ensemble_avg"), params=dict(rows=256, adc_bits=6, res_tiles=3)),
    "n10_residue_imc": dict(nodes=dict(_ST, n10_wildcards="residue_imc"), params=dict(_R7)),
    "n10_factorized": dict(nodes=dict(_ST, n10_wildcards="factorized"), params=dict(_R7)),
    "n10_unary_pwm": dict(nodes=dict(_ST, n10_wildcards="unary_pwm"), params=dict(_R7)),
}


def _selfcheck():
    """Frozen shipped-default base (reproducible) + a live smoke run (no n10 errors)."""
    from arch_eval import design, model
    for opt in OPTIONS:   # live nodes: whatever N1-N9 currently are, n10 must not raise
        s = model.evaluate(design.make({"n10_wildcards": opt}))
        assert not [x for x in s["errors"] if x.startswith("n10")], (opt, s["errors"])
    with frozen():
        base = model.evaluate(design.make())
        assert base["tok_s_die"] > 0, "frozen base infeasible"
        for opt in ("moe_experts", "cam_topk_kv", "iterative_refinement"):
            assert model.evaluate(design.make({"n10_wildcards": opt}))["tok_s_die"] == 0, opt
        same = model.evaluate(design.make({"n10_wildcards": "pedestal_sub"}))
        assert abs(same["tok_s_die"] - base["tok_s_die"]) < 1e-9 * base["tok_s_die"]
        one = apply({"wildcard": "residual_tiles", "res_tiles": 1, "n_states": 16}, base["tile"])
        assert one["area_um2_parts"]["weights"] == 2 * base["tile"]["area_um2_parts"]["weights"]
        # bilinear with zero tax: per-crosspoint work x 8/7 must raise tok/s (compute-bound prefill)
        z = model.evaluate(design.make({"n10_wildcards": "strassen"}, {"bil_tax_db": 0.0}))
        assert z["tok_s_die"] > base["tok_s_die"], (z["tok_s_die"], base["tok_s_die"])
        # B-side planes are charged: t_word grows by (planes + bx)/planes before the r_t/r_s scaling
        bt = apply(OPTIONS["dps48"]["params"], base["tile"])
        pl = base["tile"]["fmt"]["input_planes"]
        want = base["tile"]["t_word_ns"] * (pl + _D[6]) / pl * _D[0] / _D[1]
        assert abs(bt["t_word_ns"] - want) < 1e-9 * want
    # gate bypass guard: a tile n8 failed on clip range must stay failed after an SNR-raising option
    q = dict(base["tile"]["quality"], passed=False, clip_ok=False, margin_db=5.0)
    t = apply({"wildcard": "ensemble_avg", "res_tiles": 255}, dict(base["tile"], quality=q))
    assert not t["quality"]["passed"], "clip_ok=False tile passed after apply()"
    q = dict(base["tile"]["quality"], passed=False, margin_db=5.0)   # flagless gate failed on format
    q.pop("fmt_ok", None), q.pop("clip_ok", None)
    assert not apply({"wildcard": "ensemble_avg", "res_tiles": 3}, dict(base["tile"], quality=q))["quality"]["passed"]
    print("n10 selfcheck PASS")


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    _selfcheck()
    print("-- current gate (n8 default)")
    study()
    print("-- frozen shipped defaults (reproducible base)")
    with frozen():
        study()
