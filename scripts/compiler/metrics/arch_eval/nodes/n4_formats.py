"""N4 number formats & operand encoding (researched 2026-10-05, revised after review; doc ArchResearch/nodes/N4.md).

A format reaches the four ARCH_METRIC numbers through these terms, each a law with its source:

  1. HBM bytes/weight = storage bits / 8 (streaming: decode tok/s <= HBM_Bps / model bytes).
  2. Weight slices    S = ceil((b_w - 1) / b_cell), b_cell = 4 magnitude bits (sign on the
                      differential pair, formats.n_slices). Slice magnitudes MSB first: W8 = [3, 4],
                      INT5 = [4], INT4 = [3]; a slice of m bits holds 2^m - 1 binary units per side.
                      n3 prices 2^(min(4,b)-1) - 1 = 7 units per slice, so `tile_effects` rescales
                      cap, area and array energy to the true unit count (W8 x 22/14, INT5 x 15/7).
  3. ADC bits         B = ceil((SQNR_req - 10.79 dB + 20 log10 k) / 6.02) + 1      [derived]
                      mid-tread B-bit quantizer, half-span FS = k sigma(partial). Same as n5's ADC
                      part (4.77 + 6.02 B - 20 log10 k). Statistical sizing depends on SQNR and k
                      only, not on the cell width, so an 8-b single cell needs the MSB slice's B
                      (the 28m8 faithful +4 b is not paid; review fix). Faithful bound (27h6):
                      ceil(log2(1 + N (2^bw - 1)(2^bx - 1))).
  4. Slice noise      output y = 16 y_H + y_L. With per-slice SNR equal (each ADC spans its own
                      slice's +-k sigma), the output SNR equals the slice SNR. Dropping d bits on the
                      LSB slice multiplies the output quantization noise by
                      (256 + 4^d g) / (256 + g),  g = (sigma_L / sigma_H)^2 = 4.11^2 (measured R32)
                      -> d = 1: -0.74 dB, d = 2: -2.9 dB, d = 4: -12.3 dB (T5 measured fail).
  5. Input word time  radix: n2's planes x slot (with N2's hybrid, the top k_dig planes go digital);
                      PWM 2^(bx-1) t_q (27h9); split nibble 32 t_q; amplitude C-DAC 1 slot;
                      bit-serial = planes x slot AND (planes - k_dig) conversions.
  6. Scale blocks     a weight or activation scale block g along K shorter than the rows per
                      conversion R forces R/g conversions (27l4: Delta-e = 0 inside one analog sum).
  7. Operand rho      rho = std(sum_R x w)/sqrt(R), codes normalized to their max (n5's thermal,
                      ADC-range and coupling statistic). MEASURED here per format at the live R = 32
                      (p10 over 43 proxy linears; scratchpad n4/rho_measure32.py). `score` passes it to
                      n5 with rho_mode="fixed", so the format's rho is what the gate sees.
  8. Amplitude DAC    per row segment of row_seg phys columns: one analog buffer (an amplitude
                      cannot be restored by a digital repeater), I = max(gm law, slew law):
                      gm = (B+1) ln2 C_seg / (2/3 t_slot), I_gm = gm / (gm/Id = 15); I_slew = 3 C_seg V_exc / t_slot.

Thermal-limited conversions cost E ~ k2 (VDD / V_c)^2 4^B (27h1); equal-bits bit-serial pays
B_x/3 x the radix thermal energy and B_x x the switching and time (law 8 in N4.md).

The core consumes only wbits/abits/slices/input_planes/kv_bits. Everything else rides in fmt
extra keys and is applied by `tile_effects` (an n10-style tile transform used by `score`), which
re-runs n2 -> n5 -> n8 on the corrected cell and re-gates. N4.md asks the core to adopt it.
Labels: every tok/s etc. is projected; rho and the proxy PPL rows are measured on SmolLM2-135M.
"""
import math

from compiler.formats import n_slices

TIERS = ("lossless", "acceptable", "rejected")   # LIT_QUALITY G1: <=3 %, <=10 %, worse

# ---- measured operand statistics (p10, median) --------------------------------------------------
# Per-token activations: rho does not depend on R (normalization is per token; measured int8ch
# 0.0229 at both R128 and R32). key = (weight class, weight scale group, Hadamard, outlier lane)
RHO_TOK = {(8, 0, 0, 0): (0.0122, 0.0229), (4, 128, 0, 0): (0.0149, 0.0286), (8, 0, 1, 0): (0.0529, 0.0803),
           (4, 128, 1, 0): (0.0631, 0.0978), (4, 128, 0, 1): (0.0405, 0.0578)}
# Activations with one scale per (token, R-row block), measured at R = 32. key = (class, group, Hadamard)
RHO_BLK32 = {(8, 0, 0): (0.0795, 0.1047), (8, 0, 1): (0.1270, 0.1374), (8, 32, 0): (0.1264, 0.1550),
             (8, 32, 1): (0.1884, 0.1982), (4, 128, 0): (0.1027, 0.1273), (4, 128, 1): (0.1580, 0.1642),
             (4, 32, 0): (0.1271, 0.1558), (5, 128, 1): (0.1571, 0.1633), (6, 128, 1): (0.1569, 0.1631),
             (6, 32, 0): (0.1264, 0.1550)}
# Earlier R = 128 table (medians, kept for the doc's comparison; not used for scoring at R = 32)
RHO_MEAS_R128 = {(4, 0, 0, 0): 0.0286, (8, 0, 0, 0): 0.0229, (4, 0, 1, 0): 0.0747, (8, 0, 1, 0): 0.0586,
                 (4, 1, 0, 0): 0.0978, (8, 1, 0, 0): 0.0803, (4, 1, 1, 0): 0.1316, (8, 1, 1, 0): 0.1067}
SIG_LH = 4.11   # sigma(LSB slice partial) / sigma(MSB slice partial) in slice code units, INT8 + Hadamard,
                # block activations, R32 (15 x 0.2582 / (7 x 0.1346), measured)
X_RMS = dict(block=0.42, rot=0.26, raw=0.10)   # n5's row-coupling statistic per operand family (n5 values)
T_HOT_DB = 10 * math.log10(378 / 300)          # thermal SNR at 105 C vs n5's 300 K: -1.0 dB (derived)

_BASE = dict(wbits=4, abits=8, kv_bits=16, f_enc="radix", f_store_bits=None, f_cell_bits=4,
             f_block=128, f_rot=False, f_crest=32.0, f_sqnr_db=44.0, f_lsb_drop=0,
             f_side_frac=0.0, f_tier="acceptable", f_mixed_w8=0.0, f_tq_ps=150.0,
             f_skip=2, f_array_e=1.0, f_needs="", f_ablock=0, f_outl=0, f_cu_lsb=1.0, f_merge=False)


def _o(prov, **kw):
    return dict(params=dict(_BASE, **kw), provenance=prov)


W8 = dict(wbits=8, f_block=0, f_tier="lossless")                      # INT8 per output channel
Q80 = dict(wbits=8, f_block=32, f_tier="lossless", f_store_bits=8.5)  # GGUF Q8_0: fp16 scale per 32
OPTIONS = {
    # ---------------- weight formats (A8 radix planes, per-token activations, KV16) ----------------
    "w4a8_g128": _o("INT4 g128 + GPTQ/rotation, 1 slice; 8B +6.6..9.1 % (SpinQuant/QServe, projected); "
                    "proxy RTN +84 % (measured)", wbits=4),
    "w4a8_g128_had": _o("INT4 g128 + Hadamard (QuaRot-class); tier acceptable (projected 8B)", wbits=4, f_rot=True),
    "w5a8_sign_routed": _o("INT5 g128 = sign + 4 magnitude bits, one -15..15 slice (REPO-A); 15 units/side "
                           "(n3 prices 7: rescaled)", wbits=5, f_store_bits=5),
    "w8a8_2slice": _o("INT8 per-channel, two slices (magnitudes 3 + 4), the only weight format that passed on "
                      "the repo proxy (REPO-A); 8B +2.3 % SmoothQuant (projected)", **W8),
    "w8a8_q8_0_g32": _o("GGUF Q8_0: INT8 with one fp16 scale per 32 weights along K (block = live R = 32: no "
                        "extra conversions, law 6); proxy digital with per-token A8 +2.89 % (D5): the +3.1 % "
                        "floor is an activation floor, g32 weights do not remove it", **Q80),
    "w8a8_q8_0_g32_had": _o("Q8_0 g32 + Hadamard (re-quantized after rotation)", **Q80, f_rot=True),
    "w8a8_1cell8b": _o("INT8 in one 7-magnitude-bit cell (127 units/side): 1 conversion per weight at the MSB "
                       "slice's bits (law 3), unit cap sized from the noise need", **W8, f_cell_bits=7),
    "w6a8_1cell": _o("INT6 g128 in one 5-magnitude-bit cell (31 units/side): 1 conversion; FP6/INT6 weights "
                     "'preserve quality' (FP6-LLM, ZeroQuant(4+2); LIT_QUALITY 1); per-token act, no rotation: "
                     "proxy INT6 g32 +6.27 % (measured D9) -> acceptable", wbits=6, f_cell_bits=5),
    "w7a8_1cell": _o("INT7 per-channel in one 6-magnitude-bit cell (63 units/side); quality unmeasured",
                     wbits=7, f_block=0, f_cell_bits=6, f_store_bits=7),
    "w8_2b_slices": _o("INT8 as 2-b slices (ISAAC, 27b7/27c4): 4 conversions", **W8, f_cell_bits=2),
    "w6a8_fp6": _o("FP6/INT6 weights -> 5-b block mantissa, 4-b cell = 2 slices; proxy W6A8 per-channel "
                   "+11.2 % (measured; the +8.5 % row is MXFP6 W6A6) -> acceptable", wbits=6),
    "w8a8_fp8_bfp5": _o("FP8 E4M3 weights lowered to a 5-b block mantissa, 1 slice; proxy +5.4 % (measured)",
                        wbits=5, f_store_bits=8, f_tier="acceptable"),
    "mxint4_g32": _o("MXINT4 g32 weights at A8 (OCP MX scale per 32): block = live R, no extra conversions; "
                     "finer groups than g128 (acceptable tier)", wbits=4, f_block=32),
    "nvfp4_g16": _o("NVFP4 weights (E2M1 x2 = integers 0..12 fit the 15-unit cell; g16, E4M3 scale): 2x "
                    "conversions at R = 32 (law 6)", wbits=4, f_block=16, f_store_bits=4.5),
    "mx_g128_pow2": _o("MX-style power-of-two scale, block g128 >= R: dequant is an exponent add, free "
                       "(DD Floating-Point Specialization); merges with w4a8_g128", wbits=4),
    "fp8_per_element_analog": _o("per-element FP exponents inside the analog sum: 4^Delta-e energy (27l4)",
                                 wbits=8, f_tier="rejected"),
    "lns4_linear_tile": _o("LNS4 weights stored log, decoded to ~7-b linear at write (2 slices); proxy log4 "
                           "+126 % vs INT4 g128 +84 % on the same proxy", wbits=7, f_store_bits=4),
    "lns6_linear_tile": _o("LNS6 (2 fractional bits) decoded to linear: proxy +13 % (measured)",
                           wbits=8, f_block=0, f_store_bits=6),
    "posit8": _o("posit8: regime = variable exponent -> same BFP lowering as FP8 at 8-b mantissa", **W8),
    "ternary_bitnet": _o("ternary (BitNet b1.58): needs a QAT model; no Llama-3-8B PTQ within 10 %", wbits=2,
                         f_store_bits=1.6, f_tier="rejected"),
    "binary": _o("binary weights: G1 rejected for LLMs", wbits=1, f_store_bits=1, f_tier="rejected"),
    "w3a8": _o("INT3 g128: 8B GPTQ +34 % (Huang et al.)", wbits=3, f_store_bits=3, f_tier="rejected"),
    "w2a8": _o("INT2: proxy +3e9 % (measured)", wbits=2, f_store_bits=2, f_tier="rejected"),
    "csd_weights": _o("CSD/NAF weight recoding: real INT4 codes -0.3 % digit density, +16 % charge (FORMATS.md)",
                      wbits=4, f_array_e=1.16),
    "offset_binary_w": _o("offset-binary weights + zero-point correction: pedestal ~1 b of range (27e3)",
                          wbits=4, f_crest=64.0),
    "mixed_w4_w8_sensitive": _o("W4 bulk + sensitive tensors W8 (1/120 of MACs; KL /5-8 on the proxy)",
                                wbits=4, f_mixed_w8=1 / 120),
    # ---------------- input encoding (W4 g128 base) ----------------
    "a8_bitserial": _o("bit-serial planes, one conversion per analog plane (ISAAC, 27h5)", wbits=4,
                       f_enc="bitserial", f_skip=0),
    "a8_booth4": _o("radix-4 Booth digits {-2..2} in charge: 4 planes, 5-level drive (DD Booth)", wbits=4,
                    f_enc="booth4", f_array_e=2.5, f_skip=1),
    "a8_amplitude_dac": _o("8-b amplitude C-DAC row drive, one slot; pure charge N2 (k_dig 0); a buffer per "
                           "row segment", wbits=4, f_enc="amp"),
    "a8_nibble_amp": _o("4-b amplitude DAC x 2 nibble planes, 1:16 charge radix", wbits=4, f_enc="nib_amp"),
    "a8_pwm": _o("PWM 2^7 t_q, one conversion (27h9); needs a time/current-integrating N2 cell", wbits=4,
                 f_enc="pwm", f_needs="n2_time"),
    "a8_pwm_split_nibble": _o("split-nibble PWM: 2 x 16 t_q, 2 conversions; needs a time N2 cell", wbits=4,
                              f_enc="pwm_nib", f_needs="n2_time"),
    "a8_thermometer": _o("thermometer input: 127 row lines per input at A8 (20m2)", wbits=4, f_enc="thermo"),
    "a8_csd_input": _o("CSD/NAF input digits: only array energy moves", wbits=4, f_skip=1, f_array_e=0.7),
    "a8_log_input": _o("log activations into a linear tile: every slot still runs", wbits=4, f_array_e=0.3),
    "a10_common_scale": _o("A10 common scale per 1024 rows (REPO-B): +2 planes", wbits=4, abits=10),
    "a6": _o("A6: 8B W6A6 SmoothQuant +26 %", wbits=4, abits=6, f_tier="rejected"),
    "a4_rotated": _o("A4 + rotation: 8B W4A4 QuaRot +19..34 %", wbits=4, abits=4, f_tier="rejected"),
    # ---------------- outliers / scale granularity ----------------
    "outlier_digital_lane": _o("1 input/128 rows on the digital rail; rho 0.029 -> 0.058 (measured)", wbits=4,
                               f_side_frac=1 / 128, f_outl=1),
    "smoothquant_fold": _o("SmoothQuant alpha 0.5 folded into weights (free; compiler default)", wbits=4),
    "w8a8_bfp_act": _o("INT8 per channel + one activation scale per (token, R-row block): BFP/MX activations "
                       "whose block equals the analog sum (27l4 holds)", **W8, f_ablock=32),
    "w4a8_had_bfp": _o("INT4 g128 + Hadamard + block activations", wbits=4, f_rot=True, f_ablock=32),
    "outlier_lane_bfp": _o("INT4 g128 + block activations + 1 outlier input/128 rows on the rail", wbits=4,
                           f_ablock=32, f_outl=1, f_side_frac=1 / 128),
    # ---------------- KV (digital rail; symmetric lever) ----------------
    "w4a8_kv8": _o("INT4 g128, KV8 (near-lossless, projected)", wbits=4, kv_bits=8),
    "w4a8_kv4": _o("INT4 g128, KV4 (QServe W4A8KV4 +9.1 % on 8B, projected)", wbits=4, kv_bits=4),
}
# ---- lead stacks: INT8 per channel + Hadamard + block-32 activations + 32 sigma (N8 clip rule) + radix
# planes on N2's hybrid (k_dig swept by score); the lead adds slice merge + asymmetric LSB caps.
# Proxy digital floors (measured, qsweep3/4): INT8 ch + A8 per 32 block -0.01 % (D10), + Hadamard +0.18 % (D7),
# INT8 ch A8 per token +3.12 % (D8): the floor is activation quantization, removed by the block scale alone.
STACK_W8 = dict(W8, f_rot=True, f_ablock=32, f_crest=32.0)
STACK_W4 = dict(wbits=4, f_rot=True, f_ablock=32, f_crest=32.0)
_ML = dict(f_merge=True, f_cu_lsb=0.25)
_L = {
    "w8a8_lead": ("LEAD: INT8 per channel (2 slices, LSB unit 0.25x) + Hadamard (online for down_proj / o_proj "
                  "inputs) + block-32 activations + 32 sigma + slice merge (one conversion per weight) + radix "
                  "planes on N2 hybrid MSB-digital; proxy digital +0.18 % (D7), ADC range T12", _ML),
    "w8a8_lead_norot": ("lead without Hadamard; proxy digital -0.01 % (D10); ADC range measured only with "
                        "rotation (T11/T12) or per layer (R3)", dict(_ML, f_rot=False)),
    "w8a8_lead_plain": ("lead stack without merge and without asymmetric caps", {}),
    "w8a8_lead_merge": ("lead stack + slice merge only (1:16 charge combine, 27h6/27h1/27h5)", dict(f_merge=True)),
    "w8a8_lead_asym": ("lead stack + LSB unit cap 0.25x only (its noise reaches y /16 in amplitude)",
                       dict(f_cu_lsb=0.25)),
    "w8a8_lead_q80": ("lead with GGUF Q8_0 g32 weights (8.5 b in HBM) instead of per channel",
                      dict(_ML, f_block=32, f_store_bits=8.5)),
    "w8a8_lead_1cell": ("lead stack in one 127-unit cell (1 conversion, no merge needed)", dict(f_cell_bits=7)),
    "w8a8_lead_lsb1": ("lead stack (no merge) + LSB slice ADC 1 b coarser (law 4: -0.74 dB; T13)",
                       dict(f_lsb_drop=1, f_cu_lsb=0.25)),
    "w8a8_lead_lsb4": ("lead stack (no merge) + LSB slice ADC 4 b coarser (law 4: -12.3 dB; T5 fail)",
                       dict(f_lsb_drop=4, f_cu_lsb=0.25)),
    "w8a8_lead_k24": ("lead at +-24 sigma per tile (T11 +0.45 %, passes at R128; lv_tile_range)",
                      dict(_ML, f_crest=24.0)),
    "w8a8_lead_k16": ("lead at +-16 sigma per tile (T10: clipping floor fails G2) -> rejected",
                      dict(_ML, f_crest=16.0, f_tier="rejected")),
    "w8a8_lead_amp": ("lead encoding swapped for the 8-b amplitude C-DAC (pure-charge N2, k_dig 0)",
                      dict(_ML, f_enc="amp")),
    "w8a8_lead_bitserial": ("lead encoding swapped for bit-serial planes", dict(_ML, f_enc="bitserial", f_skip=0)),
    "w8a8_lead_tokact": ("lead with per-token activations (no block scale)", dict(_ML, f_ablock=0)),
}
for _n, (_prov, _kw) in _L.items():
    OPTIONS[_n] = _o(_prov, **dict(STACK_W8, **_kw))
OPTIONS["w5a8_lead"] = _o("INT5 g128 one 15-unit slice + Hadamard + block act + 32 sigma; proxy digital +13.1 % "
                          "(measured D1): acceptable tier", **dict(STACK_W4, wbits=5, f_store_bits=5))
OPTIONS["w6a8_lead_1cell"] = _o("INT6 g128 one 31-unit cell + Hadamard + block act + 32 sigma; proxy digital "
                                "+2.43 % (measured D3): lossless tier on the proxy",
                                **dict(STACK_W4, wbits=6, f_cell_bits=5, f_tier="lossless", f_store_bits=6))
OPTIONS["w7a8_lead_1cell"] = _o("INT7 per channel one 63-unit cell + Hadamard + block act + 32 sigma",
                                **dict(STACK_W8, wbits=7, f_cell_bits=6, f_store_bits=7))
OPTIONS["w4a8_lead"] = _o("W4 variant: INT4 g128 + Hadamard + block act + 32 sigma + radix/hybrid "
                          "(acceptable tier: N8 g43_w4_acceptable)", **STACK_W4)
OPTIONS["w4a8_lead_amp"] = _o("W4 lead with the amplitude DAC (pure charge N2)", **dict(STACK_W4, f_enc="amp"))
# Shipped names, kept as aliases (n8_quality.best and older designs reference them).
OPTIONS["w4a8"] = dict(OPTIONS["w4a8_g128"], provenance="alias of w4a8_g128 (shipped contract INT4xINT8)")
OPTIONS["w8a8"] = dict(OPTIONS["w8a8_2slice"], provenance="alias of w8a8_2slice")
OPTIONS["w4a4"] = dict(OPTIONS["a4_rotated"], provenance="alias of a4_rotated (rejected)")
# Default = the N4 lead. KV stays 16 b: baseline_systolic reads kv_bits from this default (symmetric lever).
DEFAULT = "w8a8_lead"
SWEEP = dict(wbits=[4, 5, 8], abits=[8], kv_bits=[4, 8, 16], f_crest=[16.0, 24.0, 32.0])


# ------------------------------------------------------------------------- laws
def adc_bits_needed(sqnr_db, crest):
    """Mid-tread quantizer, half-span FS = crest x sigma: SQNR = 10.79 + 6.02 (B-1) - 20 log10 crest."""
    return max(1, math.ceil((sqnr_db - 10.79 + 20 * math.log10(crest)) / 6.02) + 1)


def faithful_bits(rows, bw_mag, bx_mag):
    """27h6 exact count for magnitudes of bw/bx bits (sign on the differential pair: +1)."""
    return math.ceil(math.log2(1 + rows * (2 ** bw_mag - 1) * (2 ** bx_mag - 1))) + 1


def slices(wbits, cell_bits=4):
    return n_slices(wbits) if cell_bits == 4 else max(1, -(-(wbits - 1) // cell_bits))


def slice_mags(wbits, cell_bits=4):
    """Magnitude bits per slice, MSB first (sign on the differential pair)."""
    m, S = max(1, wbits - 1), slices(wbits, cell_bits)
    return [m - cell_bits * (S - 1)] + [cell_bits] * (S - 1) if S > 1 else [m]


def n3_units(wbits, S):
    """Units per side n3 prices (n3_cell.cell: slice bits min(4, wb - 4 i), 2^(b-1) - 1 units)."""
    sb = [min(4, wbits - 4 * i) if wbits > 4 else wbits for i in range(S)]
    return [2 ** (max(1, b) - 1) - 1 or 1 for b in sb]


def slice_noise_db(drop, g=SIG_LH ** 2):
    """Law 4: output quantization SNR change when the LSB slice converts `drop` bits coarser."""
    return -10 * math.log10((256 + 4 ** drop * g) / (256 + g))


def rho_of(wbits, group, rot, ablock, outl, R=32):
    """Measured (p10, median) operand rho for the format at R rows; unmeasured combinations take the
    nearest measured one (listed fallbacks)."""
    wc = 8 if wbits >= 7 else (wbits if wbits in (5, 6) else 4)
    g = group if group else (0 if wc == 8 else 128)
    r = int(bool(rot))
    if ablock:
        for key in ((wc, g, r), (wc, 128, r), (4, g, r), (4, 128, r), (8, 0, r)):
            if key in RHO_BLK32:
                return RHO_BLK32[key]   # block fixed at 32: rho is a per-element statistic for any R <= 32
    for key in ((wc, g, r, outl), (wc, g, r, 0), (8 if wc == 8 else 4, 0 if wc == 8 else 128, r, outl),
                (8 if wc == 8 else 4, 0 if wc == 8 else 128, r, 0), (8, 0, r, 0)):
        if key in RHO_TOK:
            return RHO_TOK[key]
    return RHO_TOK[(8, 0, 0, 0)]


def fmt(p):
    wb, ab = int(p["wbits"]), int(p["abits"])
    enc = p.get("f_enc", "radix")
    cb = int(p.get("f_cell_bits", 4))
    S = slices(wb, cb)
    skip = int(p.get("f_skip", 2)) if ab >= 6 else 0      # measured sky130 MSB skipping: 6 planes/A8 word
    planes = dict(radix=ab - skip, bitserial=ab - skip, booth4=-(-ab // 2) - skip, amp=1, nib_amp=2,
                  pwm=1, pwm_nib=1, thermo=1).get(enc, ab - skip)
    planes = p.get("input_planes") or max(1, planes)
    kd = int(p.get("k_dig") or 0)
    conv = dict(bitserial=max(1, planes - kd), pwm_nib=2).get(enc, 1)   # conversions per word per slice
    B = adc_bits_needed(p.get("f_sqnr_db", 44.0), p.get("f_crest", 32.0))
    if enc == "bitserial":
        B = max(1, B - 1)      # law 8: each plane's LSB may be sqrt(3) larger (~0.8 b), not 3 b
    rho, rho_med = rho_of(wb, int(p.get("f_block", 0)), p.get("f_rot"), int(p.get("f_ablock", 0)),
                          int(p.get("f_outl", 0)), int(p.get("rows", 32)))
    return dict(wbits=wb, abits=ab, slices=S, input_planes=planes, kv_bits=int(p.get("kv_bits", 16)),
                bits_product=wb * ab, enc=enc, conv_per_word=conv, adc_bits_needed=B,
                lsb_slice_drop=int(p.get("f_lsb_drop", 0)), crest=p.get("f_crest", 32.0),
                storage_bits=p.get("f_store_bits") or wb, block=int(p.get("f_block", 0)),
                tier=p.get("f_tier", "acceptable"), side_frac=p.get("f_side_frac", 0.0),
                mixed_w8=p.get("f_mixed_w8", 0.0), array_e=p.get("f_array_e", 1.0), cell_bits=cb,
                mags=slice_mags(wb, cb), tq_ps=p.get("f_tq_ps", 150.0), rot=bool(p.get("f_rot")),
                needs=p.get("f_needs", ""), ablock=int(p.get("f_ablock", 0)), rho=rho, rho_median=rho_med,
                cu_lsb=float(p.get("f_cu_lsb", 1.0)), merge=bool(p.get("f_merge")) and S == 2)


# ------------------------------------------------------------------------- tile transform
D_MODEL = 4096        # Llama-3-8B d (ARCH_METRIC)
# Online rotation ops per input element, MAC-weighted (QuaRot, arXiv:2404.00456): down_proj input
# (58.7M of 218.1M MACs/layer = 0.269) needs an online Hadamard of 2048 (largest power of 2 dividing
# 14336; the 7-factor is a Kronecker block), and o_proj input a cross-head Hadamard of 32 heads
# (16.8M/218.1M = 0.077). Everything else folds into W offline.
HAD_OPS_PER_ELEM = 0.269 * math.log2(2048) + 0.077 * math.log2(32)
BUF_GMID, BUF_UM2 = 15.0, 25.0   # DAC buffer gm/Id (1/V) and area (um2, n2 ota_area_um2 class; projected)


def _fail(q, why):
    q.update(passed=False, why=why)


def tile_effects(ctx, t):
    """Apply the format terms the core does not model to a model.tile dict, re-run n2 -> n5 -> n8
    on the corrected cell (true unit count), re-price conversions, word time, DAC buffers and the
    input-side digital work, and re-gate."""
    p, f = ctx.p, t["fmt"]
    if "enc" not in f:                      # fmt fell back to the default module
        return t
    vdd, clk = t["op"]["vdd"], t["op"]["clk_frac"]
    geo = ctx.call("n5_array", "geometry")
    S, R = f["slices"], geo["rows"]
    cell, arr = t["cell"], t["arr"]
    # true units per side (law 2) vs n3's price; LSB slices may use a smaller unit (f_cu_lsb)
    u_true = [2 ** m - 1 for m in f["mags"]]
    u_n3 = n3_units(f["wbits"], S)
    r_msb = u_true[0] / u_n3[0]
    r_all = (u_true[0] + f["cu_lsb"] * sum(u_true[1:])) / sum(u_n3)
    if abs(r_msb - 1) > 1e-9:               # MSB column cap changes: column settling, thermal, range
        arr = ctx.call("n2_domain", "array", vdd, f, dict(cell, c_weight_fF=cell["c_weight_fF"] * r_msb), R)
    vfs = ctx.call("n5_array", "v_range", geo, arr)
    B = int(p["adc_bits"])

    def adc(bits):
        old = p["adc_bits"]
        p["adc_bits"] = max(1, bits)
        try:
            return ctx.call("n6_readout", "adc", vdd, vfs)
        finally:
            p["adc_bits"] = old

    a0 = adc(B)
    convs = 1 if f["merge"] else S         # conversions per weight column group
    per_col = [a0] + ([] if f["merge"] else [adc(B - f["lsb_slice_drop"]) for _ in range(S - 1)])
    acc = ctx.call("n5_array", "accuracy", vdd, geo, arr, a0, f)
    parts = dict(acc["parts_db"])
    parts["thermal"] = parts.get("thermal", 300.0) - T_HOT_DB
    if abs(r_msb - 1) > 1e-9 and "mismatch" in parts:   # static error scales with total cap per weight
        parts["mismatch"] += 10 * math.log10(r_msb)
    if S > 1 and not f["merge"] and "adc" in parts:
        parts["adc"] += slice_noise_db(f["lsb_slice_drop"])
    cols = t["phys_cols"] // max(1, S)                    # physical columns of one slice
    rounds = f["conv_per_word"]
    for g in (f["block"], f["ablock"]):                   # law 6: scale blocks shorter than R
        if g and g < R:
            rounds *= R // g
    mix = 1 + f["mixed_w8"]
    e = dict(t["e_pass_J_parts"])
    e["converters"] = cols * sum(a["e_conv_fJ"] for a in per_col) * rounds * mix * 1e-15
    e["digital_recombination"] = cols * sum(a["e_digital_fJ"] for a in per_col) * rounds * mix * 1e-15
    e["array"] *= f["array_e"] * mix * r_all
    e["format_side"] = t["macs_per_pass"] * f["side_frac"] * t["rail"]["e_att_mac_J"]
    # input-side digital work, once per input block, shared by the D_MODEL / C output tiles of the layer
    share = max(1, D_MODEL // t["cols"])
    if f["ablock"]:   # per-block max + LZC on the rail: ~1 compare per input element (DD Priority Encoder)
        e["format_side"] += R * t["rail"]["e_elem_J"] / share
    if f["rot"]:
        e["format_side"] += HAD_OPS_PER_ELEM * R * t["rail"]["e_elem_J"] / share
    area = dict(t["area_um2_parts"])
    fs, fe, be = cell.get("feol_store_um2"), cell.get("feol_um2"), cell.get("beol_um2")
    if fs is not None and fe is not None and be is not None and max(fe, be) > 0:
        area["weights"] *= max(fs + (fe - fs) * r_all, be * r_all) / max(fe, be)
    else:
        area["weights"] *= r_all
    area["weights"] *= mix
    area["adcs"] = area.get("adcs", 0.0) * convs / S
    from arch_eval import asap7 as k
    slot = arr.get("slot_ns", arr["t_word_ns"] / max(1, f["input_planes"]))
    if f["enc"] in ("amp", "nib_amp"):      # C-DAC per row + one analog buffer per row segment (law 8)
        nb = 8 if f["enc"] == "amp" else 4
        seg = min(t["phys_cols"], int(p.get("row_seg", 32)))
        n_seg = -(-t["phys_cols"] // seg)
        pitch = math.sqrt(max(cell["area_um2_per_weight"] / max(1, S), 1e-3))
        c_seg = seg * arr["c_col_fF"] / R * 1e-15 + seg * pitch * k.get("wire_c_fF_per_um") * 1e-15
        ts = slot * 1e-9
        i_buf = max((nb + 1) * math.log(2) * c_seg / (2 * ts / 3) / BUF_GMID, 3 * c_seg * arr["v_exc_V"] / ts)
        cdac = 2 ** (nb - 1) * k.get("unit_cap_min_fF")
        area["dac"] = R * (cdac / k.get("mom_cap_density_fF_per_um2") + n_seg * BUF_UM2)
        e["format_side"] += R * f["input_planes"] * (cdac * 1e-15 * vdd ** 2 * 0.5 + n_seg * i_buf * vdd * ts)
        t["n4_dac"] = dict(n_seg=n_seg, c_seg_fF=c_seg * 1e15, i_buf_uA=i_buf * 1e6)
    if f["enc"] == "thermo":                # one driver + wire track per level per row (2^(b-1)-1 levels)
        area["dac"] = R * (2 ** (f["abits"] - 1) - 1) * 4 * k.get("dff_area_um2")
    t_word = dict(pwm=(2 ** (f["abits"] - 1)) * f["tq_ps"] * 1e-3,
                  pwm_nib=2 * 16 * f["tq_ps"] * 1e-3).get(f["enc"], arr["t_word_ns"])
    if f["merge"]:
        t_word += slot                      # the 1:16 merge share
    t_word /= clk
    n_conv = cols * len(per_col) * rounds * mix
    t_conv = -(-n_conv // t["n_adc"]) * per_col[-1]["t_conv_ns"] / clk
    t_pass = max(t_word, t_conv) if t["rail"]["pingpong"] else t_word + t_conv
    # re-gate on the corrected parts
    acc = dict(acc, parts_db=parts, snr_db=-10 * math.log10(sum(10 ** (-v / 10) for v in parts.values())))
    q = dict(ctx.call("n8_quality", "gate", acc, f))
    kd = int(p.get("k_dig") or 0)
    if f["tier"] == "rejected":
        _fail(q, "N4: format rejected by the G1 quality tier (LIT_QUALITY)")
    if kd and kd >= f["input_planes"]:
        _fail(q, "N4: N2 hybrid k_dig >= input planes (MSB-digital needs radix bit planes)")
    if f["needs"] == "n2_time" and p.get("domain_kind") not in ("time", "current"):
        _fail(q, "N4: PWM inputs need a time/current-integrating N2 cell")
    if f["enc"] in ("amp", "nib_amp") and p.get("cap") == "mos_binary":
        _fail(q, "N4: amplitude levels on MOS-gate caps: C(V) INL unmodelled (27i1 caveat), needs the ASAP7 sim")
    if min(e.values()) < 0:
        _fail(q, "N4: negative energy part (inconsistent node combination)")
    need = adc_bits_needed(p.get("f_sqnr_db", 44.0) - 6.02 * kd, f["crest"])   # N2's hybrid relaxes the analog part
    if p.get("q_tier") == "legacy" and a0["bits"] < need:   # the 28 dB screen only
        _fail(q, "N4 screen: ADC effective bits below the format's law-3 requirement")
    t.update(e_pass_J_parts=e, e_pass_J=sum(e.values()), area_um2_parts=area, area_um2=sum(area.values()),
             t_word_ns=t_word, t_conv_ns=t_conv, t_pass_s=t_pass * 1e-9, wbits=f["storage_bits"], quality=q,
             snr_db=acc["snr_db"], snr_parts_db=parts, arr=arr,
             n4_adc_bits=[round(a["bits"], 2) for a in per_col], n4_rounds=rounds,
             n4_units=dict(r_msb=round(r_msb, 3), r_all=round(r_all, 3)))
    return t


def _evaluate(d, conditions, effects=True):
    import types
    from arch_eval import metric, model
    ctx = model.Ctx(d, metric.knobs_for(conditions))
    if effects:
        n10 = ctx.mods["n10_wildcards"]
        ctx.mods["n10_wildcards"] = types.SimpleNamespace(
            apply=lambda p, t: n10.apply(p, tile_effects(ctx, t)), SWEEP=getattr(n10, "SWEEP", {}))
    pts, dies = model.operating_points(ctx)
    s = metric.score(pts, ctx.knobs)
    s["errors"] = ctx.errors
    if s["peak"]:
        s["tile"], s["die"], s["plan"] = dies[(s["peak"]["vdd"], s["peak"]["clk_frac"])]
        s["binding"] = s["peak"]["binding"]
    return s


GATE_FOR_TIER = dict(lossless="g43_lossless", acceptable="g43_w4_acceptable", rejected="g43_lossless")
SCREEN = "snr28_w4a8"   # N8's legacy 28 dB gate: FALSIFIED as a quality gate; equal-SNR screen only
# Frames: gate = N8's option for the tier as shipped; n2 = + N2's hybrid credit 6.02 k_dig dB (N2's
# derived claim, not yet in N8); refit = n2 + G2 target 38.7 dB (N4's a + b N fit of R2/R3);
# screen = 28 dB with the ADC held at the format's law-3 bits.
FRAMES = dict(gate={}, n2=dict(credit=True), refit=dict(credit=True, target=38.7), screen=dict(gate=SCREEN))
CELLS = tuple(dict(cu_fF=c) for c in (0.5, 2.0, 8.0)) + (dict(mos_fins=128),) + tuple(
    dict(n3_cell="sram6t_binary_caps", cu_fF=c) for c in (0.2, 0.5, 2.0, 8.0, 16.0, 32.0))   # n3 default cell + SRAM caps
GRID = dict(cell=CELLS, adc_bits=(8, 9, 10, 11, 12, 13, 14), k_dig=(0, 4))   # N2.md: k_dig 4 is its 43 dB point


def score(option, conditions="arch", frame="gate", gate=None, nodes=None, params=None, grid=GRID, effects=True):
    """Best design reachable with n4=option, other nodes at their DEFAULT options, swept over the
    cell (n3 gain cell mos_fins / SRAM-cap unit), ADC bits and N2's k_dig (radix-like encodings on
    a hybrid N2 only; other encodings run k_dig 0 = pure charge). The format sets n5's operand
    statistics (measured rho, rho_mode fixed) and range k_sigma. -> (design, score)."""
    import itertools
    from arch_eval import design, metric
    from arch_eval.nodes import n2_domain as n2, n8_quality as n8
    P = {**_BASE, **OPTIONS[option]["params"], **(params or {})}
    f = fmt(P)
    fr = FRAMES[frame]
    g = gate or fr.get("gate") or GATE_FOR_TIER[f["tier"]]
    if f["crest"] < 32 and g == "g43_lossless" and not gate:
        g = "lv_tile_range"                 # 16-24 sigma is only admissible under N8's per-tile range lever
    if g == "g43_lossless" and f["wbits"] < 8 and not gate:
        g = "g43_w4_acceptable"             # same G2 target; N8's lossless gate hard-codes wbits >= 8 (G1 by width)
    gp = n8.OPTIONS[g]["params"]
    fam = "block" if f["ablock"] else ("rot" if f["rot"] else "raw")
    base = dict(k_sigma=f["crest"], rho_mode="fixed", rho=f["rho"], x_rms=X_RMS[fam])
    nd = dict(dict(n8_quality=g), **(nodes or {}), n4_formats=option)
    n2opt = nd.get("n2_domain", n2.DEFAULT)
    hyb = n2.OPTIONS.get(n2opt, {}).get("params", {}).get("k_dig", 0) > 0
    kds = grid["k_dig"] if (hyb and f["enc"] in ("radix", "bitserial")) else ((0,) if hyb else (None,))
    top = top_d = None
    for cell, b, kd in itertools.product(grid["cell"], grid["adc_bits"], kds):
        if kd is not None and f["input_planes"] <= kd:
            continue
        nodes_i = dict(nd, **({"n3_cell": cell["n3_cell"]} if "n3_cell" in cell else {}))
        par = dict(base, **{k: v for k, v in cell.items() if k != "n3_cell"}, adc_bits=b, **(params or {}))
        if kd is not None:
            par["k_dig"] = kd
            if fr.get("credit"):
                par["q_credit_db"] = gp["q_credit_db"] + 6.02 * kd
        if fr.get("target"):
            par["q_snr_target_db"] = fr["target"]
        d = design.make(nodes_i, par, name=f"{option}:{g}:{frame}:{cell}:b{b}:kd{kd}")
        try:
            s = _evaluate(d, conditions, effects)
        except Exception as e:  # noqa: BLE001  (another node's model raising at this grid point)
            s = dict(tok_s_die=0.0, tops_w=0.0, tok_w=0.0, tok_j=0.0, peak=None, errors=[repr(e)])
        if top is None or metric.better(s, top):
            top, top_d = s, d
    return top_d, top


def row(option, conditions="arch", frame="gate"):
    d, s = score(option, conditions, frame)
    t = s.get("tile") or {}
    pr = d["params"]
    return dict(tok_s_die=round(s["tok_s_die"]), tops_w=round(s["tops_w"], 2), tok_w=round(s["tok_w"], 1),
                tok_j=round(s["tok_j"], 1), gate=d["nodes"]["n8_quality"], n3=d["nodes"].get("n3_cell", "gaincell"),
                cu=pr.get("cu_fF"), mos_fins=pr.get("mos_fins"), adc_bits=pr["adc_bits"], k_dig=pr.get("k_dig"),
                conv_bits=t.get("n4_adc_bits"), binding=s.get("binding"),
                fj_mac=round(t["e_pass_J"] / t["macs_per_pass"] * 1e15, 1) if t else 0.0,
                snr=round(t["quality"]["snr_eff_db"], 1) if t else None, errors=s["errors"][:2])


def table(options=None, conditions="arch", frames=("gate", "n2", "screen"), out=None):
    """Score options in each frame; one row each. out: optional JSON path (rewritten per row)."""
    import json
    rows = {}
    for name in options or OPTIONS:
        for fr in frames:
            rows[f"{name}|{fr}"] = r = row(name, conditions, fr)
            print(f"{name:<24} {fr:<6} {r['gate']:<18} tok/s/die {r['tok_s_die']:>8}  TOPS/W {r['tops_w']:>6}  "
                  f"tok/W {r['tok_w']:>7}  tok/J {r['tok_j']:>7}  {r['n3']} cu={r['cu']} fins={r['mos_fins']} "
                  f"B={r['adc_bits']} kd={r['k_dig']} {r['conv_bits']} {r['fj_mac']} fJ/MAC snr={r['snr']} "
                  f"{r['binding']}", flush=True)
            if out:
                json.dump(rows, open(out, "w"), indent=1, default=str)
    return rows


def _live_check():
    """One live tile through tile_effects: no negative energy part, and the format's rho moves n5."""
    import types
    from arch_eval import design, metric, model
    th = []
    for rho in (0.05, 0.2):
        d = design.make(dict(n4_formats=DEFAULT), dict(k_sigma=32.0, rho_mode="fixed", rho=rho, adc_bits=12, k_dig=4))
        ctx = model.Ctx(d, metric.knobs_for("arch"))
        ctx.mods["n10_wildcards"] = types.SimpleNamespace(apply=lambda p, t, c=ctx: tile_effects(c, t), SWEEP={})
        t = model.tile(ctx, 0.7, 1.0)
        assert min(t["e_pass_J_parts"].values()) >= 0, t["e_pass_J_parts"]
        th.append(t["snr_parts_db"]["thermal"])
    assert abs(th[1] - th[0] - 20 * math.log10(4)) < 0.1, th      # thermal ~ rho^2
    d = design.make(dict(n4_formats="w8a8_lead_amp"), dict(k_sigma=32.0, adc_bits=12, k_dig=2))
    ctx = model.Ctx(d, metric.knobs_for("arch"))
    assert not tile_effects(ctx, model.tile(ctx, 0.7, 1.0))["quality"]["passed"]   # amp + hybrid guard


if __name__ == "__main__":   # self-check: laws reproduce their sources, live tile sane
    import sys
    assert faithful_bits(128, 4, 1) - 1 == 11 and faithful_bits(256, 4, 3) - 1 == 15   # 27h6 checks
    assert adc_bits_needed(28.8, 16) == 8 and adc_bits_needed(34.0, 32) == 10         # sweep.md rows
    assert slices(4) == 1 and slices(5) == 1 and slices(8) == 2 and slices(8, 2) == 4 and slices(8, 7) == 1
    assert slice_mags(8) == [3, 4] and slice_mags(5) == [4] and slice_mags(8, 7) == [7]
    assert abs(slice_noise_db(0)) < 1e-9 and -0.8 < slice_noise_db(1) < -0.7 and slice_noise_db(4) < -12
    for name in OPTIONS:
        f = fmt(dict(_BASE, **OPTIONS[name]["params"]))
        assert f["slices"] >= 1 and f["input_planes"] >= 1 and f["tier"] in TIERS and 0 < f["rho"] < 0.3, name
    _live_check()
    print("n4_formats self-check PASS")
    if "--table" in sys.argv:
        outs = [a[6:] for a in sys.argv if a.startswith("--out=")]
        table([a for a in sys.argv[1:] if not a.startswith("--")] or None,
              "sohu" if "--sohu" in sys.argv else "arch", out=outs[0] if outs else None)
