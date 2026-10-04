"""AnalogIOC-mini golden model — bit-true reference of the analog+digital path.

Single source of truth for every testbench's expected values (CONTRACT.md).
Pure numpy. No SPICE. Every stage is a separate function whose docstring
states the contract equation it implements.

Code-domain conventions (these ARE the contract; A2/A3/A4 match these):
  weights   : INT4 symmetric per-output-channel, Wq in [-7,+7]
  cap codes : differential 4b, W = Cp - Cn, Cp,Cn in 0..15, zero = both equal
  acts      : INT8 symmetric per-tensor, xq in [-127,+127]
  PWM       : sign + two magnitude nibbles hi=|x|>>4 (0..7), lo=|x|&15 (0..15);
              lo window unit t_q, hi window unit 16*t_q (duration ratio 1:16)
  converter : per-nibble-window conversion, shared per-tensor LSB D sized so
              +-4*sigma maps to |code| = 120 (schedule point CODE_MAX; keeps
              y12 <= 2040 < sat12). Hardware mapping (A4 tile_fsm/event_ctrl,
              mirrored bit-true): evt count saturates at 15 (15th crossing
              terminates), 4b SAR residue, mag = 16*count + sar (0..255),
              col_code = clamp(+-mag, -127..+127), N_eval = min(count+1, 15)
              comparator strobes (early termination on first no-cross).
  rails     : (A4 INTERFACES.md, mirrored bit-true)
              y12 = sat12(16*c_hi + c_lo), sat12 = clip [-2048, 2047]
              y14 = sat14(4*p_hi + p_lo)  (2b weight slices; mini S=1: p_hi=0)
              acc = sum of tile partials, 20b signed (saturating in HW,
                    unreachable in-spec -> golden asserts instead)
              requant: sat8( ((acc*scale + half) >> shift) + offset ),
                    half = 2^(shift-1) if shift>0 else 0 (round-half-up),
                    scale unsigned 8b per channel, shift 0..24, offset signed
                    8b applied AFTER the shift, sat8 = clip [-128, 127]
"""

import numpy as np

VDD = 1.8
TQ_SIM = 10e-9          # t_q for simulation (real target 200 ps; scale linearly)
CODE_MAX = 120          # converter magnitude full-scale (+-4 sigma clip point)
W_MAX = 7               # INT4 symmetric
CAP_MAX = 15            # 4b cap code
X_MAX = 127             # INT8 symmetric
CHK_SHIFT = 3           # checksum column scale = 2^3 (|sum s*W| <= 112 -> +-14)


def _half_up_div(num, den):
    """Integer round-half-away-from-zero of num/den (num int array, den>0 int).

    Contract: the mid-tread quantizer of the converter — comparator threshold
    at Delta/2. Bit-exact integer form so A4's Verilog can match it.
    """
    num = np.asarray(num, dtype=np.int64)
    s = np.sign(num)
    return s * ((np.abs(num) * 2 + den) // (2 * den))


# ----------------------------------------------------------------------------
# 1. smoothing + quantization
# ----------------------------------------------------------------------------

def smooth(X, W, alpha=0.5):
    """SmoothQuant per-input-channel: s_i = max|X_i|^a / max|W_:,i|^(1-a).

    Contract: 'per-channel smoothing in the digital wrapper is a prerequisite'
    (paper sec_circuits data-specific boundary). X'(t,i)=X/s_i, W'(j,i)=W*s_i.
    Returns (X', W', s).
    """
    ax = np.max(np.abs(X), axis=0)
    aw = np.max(np.abs(W), axis=0)
    s = np.power(np.maximum(ax, 1e-8), alpha) / np.power(np.maximum(aw, 1e-8), 1.0 - alpha)
    s = np.where(ax == 0, 1.0, s)
    return X / s, W * s, s


def quant_w_int4(W):
    """INT4 symmetric per-output-channel: dw_j = max_i|W_ji|/7, Wq=clip(rint(W/dw)).

    Contract: 'INT4 symmetric per-channel weight quant'. Returns (Wq int, dw).
    """
    dw = np.max(np.abs(W), axis=1) / W_MAX
    dw = np.where(dw == 0, 1.0, dw)
    Wq = np.clip(np.rint(W / dw[:, None]), -W_MAX, W_MAX).astype(np.int64)
    return Wq, dw


def caps_from_wq(Wq):
    """Differential 4b cap codes: W = Cp - Cn, codes 0..15, zero = both equal (0,0).

    Contract: 'weight = 4-bit binary-weighted cap code, differential'.
    """
    assert np.all(np.abs(Wq) <= CAP_MAX)
    Cp = np.maximum(Wq, 0).astype(np.uint8)
    Cn = np.maximum(-Wq, 0).astype(np.uint8)
    return Cp, Cn


def wq_from_caps(Cp, Cn):
    """Inverse of caps_from_wq: Wq = Cp - Cn."""
    return Cp.astype(np.int64) - Cn.astype(np.int64)


def quant_x_int8(X, dx=None):
    """INT8 symmetric per-tensor: dx = max|X|/127; xq = clip(rint(X/dx), +-127).

    Contract: 'INT8 activation quant'. Returns (xq int, dx).
    """
    if dx is None:
        dx = np.max(np.abs(X)) / X_MAX
        dx = 1.0 if dx == 0 else dx
    xq = np.clip(np.rint(X / dx), -X_MAX, X_MAX).astype(np.int64)
    return xq, dx


# ----------------------------------------------------------------------------
# 2. PWM encoding
# ----------------------------------------------------------------------------

def pwm_nibbles(xq):
    """Split INT8 code into (sign, hi, lo): xq = sign*(16*hi + lo).

    Contract: 'two 4-bit nibbles of binary-amplitude PWM, duration ratio 1:16'.
    Row i pulses lo_i*t_q in the LO window and hi_i*(16 t_q) in the HI window,
    on the polarity rail selected by sign (negative rows drive the complement
    input). hi in 0..7 (|xq|<=127), lo in 0..15.
    """
    xq = np.asarray(xq, dtype=np.int64)
    sign = np.where(xq < 0, -1, 1)
    m = np.abs(xq)
    return sign, m >> 4, m & 15


def pwm_schedule(xq, t_q=TQ_SIM):
    """Per-row PWM pulse widths in seconds: (T_lo, T_hi) = (lo*t_q, hi*16*t_q).

    Sum contract: T_lo + T_hi = |xq| * t_q  (tested).
    """
    sign, hi, lo = pwm_nibbles(xq)
    return sign, lo * t_q, hi * 16.0 * t_q


# ----------------------------------------------------------------------------
# 3. ideal charge MAC (code arithmetic)
# ----------------------------------------------------------------------------

def mac_codes(Wq, xq):
    """Ideal charge MAC per nibble window, in code units.

    mac_hi[j] = sum_i Wq[j,i] * sign_i * hi_i ;  mac_lo likewise with lo_i.
    Physical charge of the HI window is 16x per unit (duration ratio), and its
    reference packet is 16x — the ratio cancels, so both windows convert with
    the same code-domain LSB D. Full product: 16*mac_hi + mac_lo = Wq @ xq.
    """
    sign, hi, lo = pwm_nibbles(xq)
    return Wq @ (sign * hi), Wq @ (sign * lo)


# ----------------------------------------------------------------------------
# 4. statistical converter scale + event-rate conversion
# ----------------------------------------------------------------------------

def conv_scale_D(mac_samples):
    """Per-tensor converter LSB: D = max(1, ceil(4*sigma / CODE_MAX)).

    Contract: 'B_y statistical sizing with +-4 sigma clipping' (law:bout).
    sigma is taken over calibration MAC values of both nibble windows; values
    beyond 4 sigma saturate at code +-120.
    """
    sig = float(np.std(np.asarray(mac_samples, dtype=np.float64)))
    return max(1, int(np.ceil(4.0 * sig / CODE_MAX)))


def eventrate_convert(mac, D):
    """Two-step extended-counting conversion, bit-true to A4's controllers.

    q      = round_half_away(|mac|/D)      (comparator mid-tread quantizer)
    count  = coarse event-packet count; saturates at 15, the 15th crossing
             terminates (event_ctrl "range exhausted")
    sar    = 4b SAR residue, saturates at 15
    mag    = 16*count + sar = min(q, 255)  (tile_fsm assembly)
    code   = sign * min(mag, 127)          (tile_fsm mag_sat clamp; the +-4sigma
             schedule keeps mag <= CODE_MAX=120 nominally, so the clamp is
             overrange protection for tail samples)
    n_eval = min(count+1, 15) comparator strobes (EARLY TERMINATION on first
             no-cross; paper eq. E_conv: N_eval = c(y)+1). Sign strobe not
             counted here.
    Returns dict(code, sign, coarse, fine, n_eval).
    """
    # float-safe half-away rounding: the comparator sees the ANALOG value, so
    # non-integral macs (in-charge LoRA add) must round, not truncate.
    mac_f = np.asarray(mac, dtype=np.float64)
    q = np.floor((2.0 * np.abs(mac_f) + D) / (2.0 * D)).astype(np.int64)
    sign = np.where(mac_f < 0, -1, 1).astype(np.int64)
    mag = np.minimum(q, 255)
    count = mag >> 4
    fine = mag & 15
    return {
        "code": sign * np.minimum(mag, 127),
        "sign": sign,
        "coarse": count,
        "fine": fine,
        "n_eval": np.minimum(count + 1, 15),
    }


# ----------------------------------------------------------------------------
# 5. digital rail: recombination + accumulate + requant  (A4 mirrors exactly)
# ----------------------------------------------------------------------------

def merged_scale_D(mac_full_samples):
    """Merged-window converter LSB (law:bout): the SAME +-4 sigma
    statistical law as conv_scale_D, applied to FULL-window macs
    (16*mac_hi + mac_lo = Wq @ xq) instead of per-nibble macs."""
    return conv_scale_D(mac_full_samples)


def tile_mvm_merged(Wq, xq, D_m, chk=None):
    """MERGED single conversion per pass (law:bout compliance, item S5).

    One PWM window of duration |xq|*t_q per row (the full 255 t_q
    envelope), ONE 8b statistical conversion of the full-window mac at
    LSB D_m — no per-nibble split, no 12b combine. Physically: C_int
    scales to D_m * C_int_base so the reference ladder VOLTAGE spans and
    packet dV are IDENTICAL to the D=1 per-nibble case (u' = u/D_m and
    every span is u'*D_m per code LSB — the ratio cancels, law:adc).

    GOLDEN GATE (measured, 11 real A5 passes): merged at D_m = 4sigma/128
    gives 40.8 dB MVM SQNR vs 28.3 dB for the per-nibble 12b combine —
    the per-window +-127 clamp on worst-code passes is what the merged
    law removes. Digital: nibble_combine runs in BYPASS (passthrough)
    mode, y = D_m * code8 (see INTERFACES.md).
    """
    Wq = np.asarray(Wq, dtype=np.int64)
    xq = np.asarray(xq, dtype=np.int64)
    mac = Wq @ xq
    cv = eventrate_convert(mac, D_m)
    out = {"mac": mac, "conv": cv, "code8": cv["code"],
           "y": D_m * cv["code"]}
    if chk is not None:
        cm = np.asarray(chk, dtype=np.int64) @ xq
        out["chk"] = {"mac": cm,
                      "conv": eventrate_convert(np.atleast_1d(cm), D_m)}
    return out


def nibble_combine(c_hi, c_lo):
    """y12 = sat12(16*c_hi + c_lo), sat12 = clip to [-2048, 2047].

    Mirrors A4 nibble_combine.v exactly. In-schedule |y12| <= 16*120+120 =
    2040 (exact); the saturation only engages on overrange tail codes.
    """
    y = 16 * np.asarray(c_hi, dtype=np.int64) + np.asarray(c_lo, dtype=np.int64)
    return np.clip(y, -2048, 2047)


def slice_combine(p_lo, p_hi=0):
    """y14 = sat14(4*p_hi + p_lo), sat14 = clip to [-8192, 8191].

    Mirrors A4 slice_combine.v: hi slice = weight bits [3:2] (x4 significance).
    AnalogIOC-mini programs 4b caps in a single slice (S=1): p_hi = 0 and this
    is a sign-extending pass-through kept so the 12b->14b rail is exercised.
    """
    y = 4 * np.asarray(p_hi, dtype=np.int64) + np.asarray(p_lo, dtype=np.int64)
    return np.clip(y, -8192, 8191)


def accumulate(parts14):
    """acc20 = sum of tile partials (row-tiles / cascade positions / tokens).

    b_acc = 20b signed (A4 bacc_accum W=20). A4's adds saturate at +-2^19;
    that is unreachable in-spec (96 partials * 2047 < 2^19-1), so the golden
    asserts instead of modelling order-dependent mid-stream saturation.
    NOTE A4's tile_cnt port is 4b (<=15 partials per done): matrices with
    more row-tiles accumulate in fabric-summed rounds of <=15 (bit-identical
    to one long sum while in-spec) — see compiler digital_config acc_rounds.
    """
    acc = np.sum(np.asarray(parts14, dtype=np.int64), axis=0)
    assert np.all(np.abs(acc) < 2 ** 19), "20b rail overflow"
    return acc


def make_requant(scale, max_shift=24):
    """Per-channel A4 requant fields: scale_j = rint(s_j * 2^shift_j) <= 255.

    For each channel pick the largest shift <= max_shift (A4: 0..24
    meaningful) whose 8b unsigned scale fits; scale in [128,255] whenever
    shift < max_shift, i.e. <=0.4% requant scale error. Channels with s_j too
    small even at shift=24 round to scale=0 (dead channel — the compiler
    reports them; it means the float channel scale is ~0 anyway).
    Returns (scale uint8-range int array, shift int array).
    """
    s = np.atleast_1d(np.asarray(scale, dtype=np.float64))
    assert np.all(s >= 0), "requant scale must be non-negative (A4 scale is unsigned)"
    scale8 = np.zeros(s.shape, dtype=np.int64)
    shift = np.zeros(s.shape, dtype=np.int64)
    for j, sj in enumerate(s):
        sh = max_shift
        m = int(np.rint(sj * (1 << sh)))
        while m > 255 and sh > 0:
            sh -= 1
            m = int(np.rint(sj * (1 << sh)))
        scale8[j] = min(m, 255)
        shift[j] = sh
    return scale8, shift


def requant_int8(acc, scale, shift, offset=0):
    """q = sat8( ((acc*scale + half) >> shift) + offset ), A4 requant.v exact.

    half = 2^(shift-1) if shift>0 else 0 (round-half-up toward +inf via
    arithmetic shift), offset (zero-point) added AFTER the shift, sat8 =
    clip to [-128, 127]. scale unsigned 8b, shift 0..24 — all per channel.
    """
    acc = np.asarray(acc, dtype=np.int64)
    scale = np.asarray(scale, dtype=np.int64)
    shift = np.asarray(shift, dtype=np.int64)
    assert np.all((scale >= 0) & (scale <= 255)), "scale is unsigned 8b"
    assert np.all((shift >= 0) & (shift <= 24)), "shift is 0..24"
    half = np.where(shift > 0, np.left_shift(1, np.maximum(shift, 1) - 1), 0)
    v = ((acc * scale + half) >> shift) + np.asarray(offset, dtype=np.int64)
    return np.clip(v, -128, 127).astype(np.int64)


# ----------------------------------------------------------------------------
# 6. ABFT random-sign checksum
# ----------------------------------------------------------------------------

def abft_signs(n, seed):
    """Random-sign vector s in {+1,-1}^n (paper: signed checksum sees common mode)."""
    return (np.random.default_rng(seed).integers(0, 2, n) * 2 - 1).astype(np.int64)


def abft_checksum_col(Wq, s):
    """Checksum column caps: chk_i = round_half_up( sum_j s_j Wq[j,i] / 2^3 ).

    Contract: extra differential column programmed with the random-sign
    combination, scaled into cap range (|sum| <= 112 -> +-14 <= 15).
    Returns (chk int in +-15, e) with e_i = sum_j s_j Wq[j,i] - 8*chk_i,
    |e_i| <= 4 (design-time-known rounding error).
    """
    exact = s @ Wq
    chk = _half_up_div(exact, 1 << CHK_SHIFT)
    assert np.all(np.abs(chk) <= CAP_MAX)
    return chk, exact - (chk << CHK_SHIFT)


def abft_checksum_row(Wq, s_row):
    """Checksum row caps: row_j = round_half_up( sum_i s_row_i Wq[j,i] / 2^3 ).

    Programming-audit digest (drive only this row -> read column digests);
    forward per-MVM check uses the checksum COLUMN. Emitted for tb_audit.
    """
    exact = Wq @ s_row
    row = _half_up_div(exact, 1 << CHK_SHIFT)
    return row, exact - (row << CHK_SHIFT)


def abft_residual(y12_cols, y12_chk, s, e=None, xq=None, D=1):
    """Per-MVM residual: R = | sum_j s_j y12_j - 2^3*y12_chk - corr |.

    Paper: 'every MVM yields a free residual |sum y_i - y_chk| compared
    against the statistical budget'. Exact identity before conversion:
    sum_j s_j mac_j = 8*mac_chk + e . xn per window, so recombined:
    sum_j s_j y12_j ~ (8*chk_combined + e.xq)/D. e is the DESIGN-TIME-KNOWN
    checksum-column rounding vector (|e_i| <= 4); without removing it the
    budget is traffic-dominated (~4*127*16/D) and hides single-cap faults.
    corr = round_half_away(e.xq / D) — computed by the fabric (it knows e
    from the compiler and xq from its own PWM schedule); what remains is
    conversion rounding only.
    A4's abft_check computes a PLAIN sum — the harness absorbs the
    conventions by wiring y_flat[j] = s_j * y_j (negation) and
    y_chk_port = (y_chk << CHK_SHIFT) + corr (see compiler FORMATS.md).
    """
    r = int(np.dot(s, y12_cols)) - (int(y12_chk) << CHK_SHIFT)
    if e is not None:
        r -= int(_half_up_div(int(np.dot(e, xq)), D))
    return abs(r)


def abft_budget(residuals_cal, margin=1.5, floor=8):
    """eps_bud = ceil(max(calibration residuals) * margin) + floor.

    ponytail: empirical budget from clean calibration traffic; the analytic
    bound (conversion rounding 16*8.5 + 8*8.5 plus e.xq term) is ~4x looser
    and would hide single-cap faults. Upgrade path: 4-sigma statistical bound
    on e.xq if calibration coverage becomes a concern.
    """
    mx = max([int(r) for r in residuals_cal], default=0)
    return int(np.ceil(mx * margin)) + floor


# ----------------------------------------------------------------------------
# 7. one full tile MVM (the pipeline every testbench observes)
# ----------------------------------------------------------------------------

def _mask_conv(cv, kill):
    """Zero a conversion where kill: code/coarse/fine 0, n_eval 0 (skipped)."""
    keep = ~kill
    return {k: cv[k] * keep for k in ("code", "coarse", "fine", "n_eval")} | \
           {"sign": cv["sign"]}


# Opt-in tile-MVM error injector (task #24: does in-contract +-N LSB matter?).
# Default None -> tile_mvm is byte-identical to the frozen path. When set to a
# callable f(y12) -> y12_err it perturbs the recombined per-column code (the
# exact quantity tb_tile_mvm accepts/rejects at +-1 LSB), so the measured
# analog residual flows through the whole real blk.0 forward unchanged. Only
# scripts/compiler/test_error_impact.py sets it; it is reset there in a finally.
TILE_ERR = None


def make_tile_err(lsb, seed=0, thresh=20):
    """Measured pass_05 residual model (RESULTS3): per-column additive code
    error, roughly uniform in [-lsb, +lsb] on in-contract mid/high codes
    (|y12| > thresh), ~0 near zero (col13 |code|89 -> -3; lo +2/-2). Returns a
    stateful f(y12) drawing fresh noise per tile pass (independent columns)."""
    rng = np.random.default_rng(seed)

    def f(y12):
        y12 = np.asarray(y12, dtype=np.int64)
        e = rng.integers(-lsb, lsb + 1, size=y12.shape)
        e = np.where(np.abs(y12) > thresh, e, 0)
        return np.clip(y12 + e, -2048, 2047)
    return f


def tile_mvm(Wq, xq, D, s=None, chk=None, chk_e=None, lora=None, relu=False):
    """One 16x16(+chk) tile pass, all observation points.

    Order per contract: PWM nibbles -> ideal charge MAC -> (in-charge LoRA
    add) -> event-rate conversion (the +-4sigma clip lives in D's sizing;
    hardware clamps at +-127) -> nibble combine (sat12) -> slice combine
    (sat14, S=1). Returns dict with mac_hi/lo, per-nibble conversions, y12,
    y14, and (if s,chk given) chk conversion + residual.

    lora = (A_q, B_q, rho): adds rho*B_q[j]*(A_q . x-nibble) to the column
    charge BEFORE conversion (contract: 'summed IN CHARGE onto the tile's
    column integrators' — costs no extra conversions). NOTE the checksum
    column has no sidecar, so the ABFT residual sees an active LoRA as
    common-mode error: widen/ignore the budget during training steps.

    relu=True (A4 sign_exit + fabric sequencing — valid only when the column
    output is single-pass, i.e. one row-tile):
      1. HI window converts first with relu_en=1: col_sign negative
         (mac_hi < 0) -> col_code 0, NO conversion activity (n_eval 0), LO
         skipped entirely. ENERGY PREDICTION, approximate: if the true
         recombined y12 would still be positive (needs c_lo > 16*|c_hi|,
         possible since |c_lo| <= 127) the column is wrongly zeroed —
         bounded by 127 y12 LSBs, rare on real streams; golden mirrors the
         hardware, so tb acceptance (+-1 LSB vs golden) is unaffected.
      2. Else LO converts, with relu_en only when code_hi == 0 (a negative
         LO then exits: exact, the final would be clamped anyway).
      3. Fabric applies the free digital ReLU clamp y12 = max(y12, 0)
         (exact; catches mac_hi >= 0 with very negative mac_lo).
    """
    mac_hi, mac_lo = mac_codes(Wq, xq)
    mac_hi = mac_hi.astype(np.float64)
    mac_lo = mac_lo.astype(np.float64)
    if lora is not None:
        A_q, B_q, rho = lora
        sign, hi, lo = pwm_nibbles(xq)
        mac_hi = mac_hi + rho * B_q * float(np.dot(A_q, sign * hi))
        mac_lo = mac_lo + rho * B_q * float(np.dot(A_q, sign * lo))
    cv_hi = eventrate_convert(mac_hi, D)
    cv_lo = eventrate_convert(mac_lo, D)
    exit_hi = np.zeros(mac_hi.shape, dtype=bool)
    if relu:
        exit_hi = mac_hi < 0
        cv_hi = _mask_conv(cv_hi, exit_hi)
        relu_lo = ~exit_hi & (cv_hi["code"] == 0)
        cv_lo = _mask_conv(cv_lo, exit_hi | (relu_lo & (mac_lo < 0)))
    y12 = nibble_combine(cv_hi["code"], cv_lo["code"])
    if relu:
        y12 = np.maximum(y12, 0)      # free digital ReLU clamp in the fabric
    if TILE_ERR is not None:          # task #24 opt-in analog-residual model
        y12 = TILE_ERR(y12)
    out = {
        "mac_hi": mac_hi, "mac_lo": mac_lo,
        "conv_hi": cv_hi, "conv_lo": cv_lo,
        "exit_hi": exit_hi,
        "y12": y12, "y14": slice_combine(y12),
    }
    if s is not None and chk is not None:
        if chk_e is None:
            chk_e = np.zeros_like(np.asarray(chk))
        mh, ml = mac_codes(chk[None, :], xq)
        ch, cl = eventrate_convert(mh, D), eventrate_convert(ml, D)
        y12c = nibble_combine(ch["code"], cl["code"])
        out["chk"] = {"conv_hi": ch, "conv_lo": cl, "y12": int(y12c[0]),
                      "residual": abft_residual(y12, int(y12c[0]), s,
                                                e=chk_e, xq=xq, D=D)}
    return out


def tile_mvm_caps(Cp, Cn, xq, D, **kw):
    """CSD-aware tile MVM (task A): one pass of a tile programmed from ANY
    differential cap recode (canonical-signed-digit included).

    The analog pass only sees the net differential cap per crosspoint --
    charge per chop cycle = (Cp - Cn) * x * C_u * VDD (weight_tile Q_j
    equation) -- so every recode with Cp - Cn == Wq converts bit-identically
    to tile_mvm(Wq, ...): CSD is a representation change on the C+/C- split,
    not on the MAC. Asserted vs the one-sided codes on the real Wq head-0
    slice in scripts/compiler/test_formats.py. What CSD changes is the programmed
    cap-unit statistics (compiler.formats.charge_cost).
    """
    assert np.all((np.asarray(Cp) >= 0) & (np.asarray(Cp) <= CAP_MAX))
    assert np.all((np.asarray(Cn) >= 0) & (np.asarray(Cn) <= CAP_MAX))
    return tile_mvm(wq_from_caps(np.asarray(Cp), np.asarray(Cn)), xq, D, **kw)


def iter_tile_passes(O, I, tile=16):
    """Yield (c, r, col_slice, row_slice) for every physical tile pass of an
    (O,I) matrix on 16x16 tiles. Pass count contract (exact, counted):
    n_passes = ceil(I/16) * ceil(O/16)."""
    for c in range(-(-O // tile)):
        for r in range(-(-I // tile)):
            yield c, r, slice(c * tile, min((c + 1) * tile, O)), \
                slice(r * tile, min((r + 1) * tile, I))


def mvm_layer(Wq, xq, D, tile=16, relu=False):
    """Row/col-tiled MVM of an arbitrary (O,I) int matrix on 16x16 tiles.

    Each (col-tile, row-tile) pair is one physical tile pass; row-tile
    partials accumulate on the 20b rail. relu (sign-early-exit) is only
    exact for single-row-tile matrices (asserted) — per-pass sign is not the
    final sign when partials accumulate, so the real-model FFN runs with
    relu_en=0. Returns (acc (O,), n_passes, info) with info counting
    comparator strobes (n_eval) and skipped conversions (exits).
    """
    O, I = Wq.shape
    assert not (relu and I > tile), "sign-early-exit needs single row-tile"
    acc = np.zeros(O, dtype=np.int64)
    passes = 0
    info = {"n_eval": 0, "exits": 0}
    for c in range(-(-O // tile)):
        js = slice(c * tile, min((c + 1) * tile, O))
        parts = []
        for r in range(-(-I // tile)):
            ks = slice(r * tile, min((r + 1) * tile, I))
            t = tile_mvm(Wq[js, ks], xq[ks], D, relu=relu)
            parts.append(t["y14"])
            passes += 1
            info["n_eval"] += int(np.sum(t["conv_hi"]["n_eval"]) +
                                  np.sum(t["conv_lo"]["n_eval"]))
            info["exits"] += int(np.sum(t["exit_hi"]))
        acc[js] = accumulate(parts)
    return acc, passes, info


# ----------------------------------------------------------------------------
# 7b. format-universal tiled MVM (A5b): S weight slices + multi-nibble rounds
# ----------------------------------------------------------------------------

def pwm_nibble_rounds(xq, n_nib=2):
    """General PWM split: |xq| -> n_nib 4b nibbles n_k = (|xq|>>4k)&15, driven
    as ceil(n_nib/2) hardware rounds of (lo, hi) window pairs with in-pass
    duration ratio 1:16; the 256^p between rounds is digital shift-add.
    Identity: n_nib=2 gives [(lo, hi)] == pwm_nibbles. Returns (sign, rounds)
    with rounds = list of (nib_lo, nib_hi|None) signed-magnitude arrays.
    """
    xq = np.asarray(xq, dtype=np.int64)
    assert np.all(np.abs(xq) < (1 << (4 * n_nib))), "xq exceeds nibble budget"
    sign = np.where(xq < 0, -1, 1)
    m = np.abs(xq)
    nibs = [(m >> (4 * k)) & 15 for k in range(n_nib)]
    rounds = [(nibs[2 * p], nibs[2 * p + 1] if 2 * p + 1 < n_nib else None)
              for p in range(-(-n_nib // 2))]
    return sign, rounds


def tile_mvm_general(slices_t, sigs, xq, D, n_nib=2):
    """One tile position, S slices x nibble rounds — the generalized rail.

    slices_t: (S, 16cols, 16rows) signed digit tiles (|digit| <= 15, one
    differential 4b cap pattern per slice); sigs: per-slice significances
    (16^s). Each (slice, round) is one physical tile pass = up to 2 PWM
    windows converted by the same event-rate+SAR converter (per-conversion
    clamp +-127) and recombined sat12 — identical rails to the S=1 case.
    Slice/round shift-adds are plain integer (fabric width = 12 + 4(S-1) +
    8(rounds-1) bits, reported by the compiler; A4's sat14 x4 slice_combine
    covers only the historic S<=2 2-bit case).
    Returns dict(y_tile, n_eval, conversions, passes).
    """
    sign, rounds = pwm_nibble_rounds(xq, n_nib)
    y_tile = np.zeros(slices_t.shape[1], dtype=np.int64)
    n_eval = 0
    convs = 0
    for s, (st, sig) in enumerate(zip(slices_t, sigs)):
        y_sl = np.zeros(st.shape[0], dtype=np.int64)
        for p, (nlo, nhi) in enumerate(rounds):
            cl = eventrate_convert(st @ (sign * nlo), D)
            if nhi is None:
                y12 = nibble_combine(0, cl["code"])
                n_eval += int(cl["n_eval"].sum())
                convs += 1
            else:
                ch = eventrate_convert(st @ (sign * nhi), D)
                y12 = nibble_combine(ch["code"], cl["code"])
                n_eval += int(cl["n_eval"].sum() + ch["n_eval"].sum())
                convs += 2
            y_sl += (256 ** p) * y12
        y_tile += sig * y_sl
    return {"y_tile": y_tile, "n_eval": n_eval, "conversions": convs,
            "passes": len(slices_t) * len(rounds)}


def mvm_lowered(slices, sigs, exp, e_min, xq, D, n_nib=2, tile=16):
    """Row/col-tiled MVM of a lowered tensor (compiler.formats.lower_tensor).

    slices (S, O, I) digit planes; exp (O, I//16) per-(row, row-tile) block
    exponents; per-tile partials are shifted left by (exp - e_min) in the
    accumulator (exponents NEVER enter the analog core — BFP law), then
    summed. Fast path: S=1, n_nib=2, exp==e_min everywhere is bit-identical
    to mvm_layer(Wq=slices[0]) (regression-tested). Returns (acc, passes,
    info); reconstruction: y ~ acc * D * 2^e_min * w_scale * dx.
    """
    S, O, I = slices.shape
    acc = np.zeros(O, dtype=np.int64)
    passes = 0
    info = {"n_eval": 0, "conversions": 0}
    for c in range(-(-O // tile)):
        js = slice(c * tile, min((c + 1) * tile, O))
        for r in range(-(-I // tile)):
            ks = slice(r * tile, min((r + 1) * tile, I))
            t = tile_mvm_general(slices[:, js, ks], sigs, xq[ks], D, n_nib)
            sh = exp[js, r] - e_min
            acc[js] += t["y_tile"] << sh
            passes += t["passes"]
            info["n_eval"] += t["n_eval"]
            info["conversions"] += t["conversions"]
    assert np.all(np.abs(acc) < 2 ** 62), "fabric accumulator width exceeded"
    return acc, passes, info


# ----------------------------------------------------------------------------
# 7c. DPS rank-48 bilinear MVM (task B): golden mirror of compiler.dps48
# ----------------------------------------------------------------------------

def mvm_dps48_group(Ahat, s_a, s_b, Vc, WT8, xq4, D, exact=False):
    """One 4-token group of an MVM through the DPS rank-48 schedule, bit-true.

    Ahat (Gi, Gk, 48, 16, 16): programmed A-side combo tiles, |.| <= 15
      (= round_half_away(sum_ab U[m,a,b] * Wq_tile[4gi+a, 4gk+b] / 2^s_a)).
    s_a (Gi, Gk, 48), s_b (Gk, 48): the per-product power-of-2
      renormalizations, returned exactly as left-shifts at recombination.
    Vc, WT8 (48, 4, 4): B-side {-1,0,+1} combo coefficients and 8x the
      transposed C-side coefficients (compiler.dps48.V / .WT8).
    xq4 (4, I): the token group's INT8 codes.

    Per product m of super-block (gi, gk): ONE physical tile pass --
    B-side digital pre-add b = sum_cd Vc[m,c,d] * xq4[d, block 4gk+c],
    shifted/clipped to the native +-255 two-nibble PWM range, standard
    hi/lo window conversion on the combo tile (same eventrate + sat12 +
    sat14 rails as tile_mvm), then C-side digital post-add
      acc[f, tile 4gi+e] += WT8[m,e,f] * (y14 << (s_a + s_b)).
    Returns (acc (4, O) with acc ~ 8 * Wq @ xq / D, passes, info).
    exact=True bypasses PWM/conversion (y = Ahat @ b_hat, no cap-range
    assert): the pure recombination-identity path used by test_dps.
    """
    Gi, Gk, R = Ahat.shape[:3]
    O = Gi * 4 * 16
    acc = np.zeros((4, Gi, 4, 16), dtype=np.int64)
    passes = 0
    info = {"n_eval": 0, "conversions": 0}
    if not exact:
        assert np.all(np.abs(Ahat) <= CAP_MAX), "combo tile exceeds cap range"
    for gk in range(Gk):
        xb = xq4[:, gk * 64:(gk + 1) * 64].reshape(4, 4, 16)   # [d, c, i]
        for m in range(R):
            b = np.einsum("cd,dci->i", Vc[m], xb)              # [c,d] coeffs
            bh = _half_up_div(b, 1 << int(s_b[gk, m]))
            if not exact:                    # PWM range; exact = identity path
                bh = np.clip(bh, -255, 255)
            A = Ahat[:, gk, m]                                 # (Gi, 16, 16)
            if exact:
                y = np.einsum("goi,i->go", A, bh)
            else:
                sg, hi, lo = pwm_nibbles(bh)
                ch = eventrate_convert(np.einsum("goi,i->go", A, sg * hi), D)
                cl = eventrate_convert(np.einsum("goi,i->go", A, sg * lo), D)
                y = slice_combine(nibble_combine(ch["code"], cl["code"]))
                info["n_eval"] += int(ch["n_eval"].sum() + cl["n_eval"].sum())
                info["conversions"] += 2 * Gi * 16
            passes += Gi
            contrib = y << (s_a[:, gk, m] + s_b[gk, m])[:, None]  # (Gi, 16)
            for e in range(4):
                for f in range(4):
                    w = WT8[m, e, f]
                    if w:
                        acc[f, :, e, :] += w * contrib
    acc = acc.reshape(4, O)
    assert np.all(np.abs(acc) < 2 ** 62), "fabric accumulator width exceeded"
    return acc, passes, info


# ----------------------------------------------------------------------------
# 7d. CSNR lattice-threshold converter (task C, law:csnr / paper L6)
# ----------------------------------------------------------------------------

def output_lattice(Wq_tile, xq_stream, tile=16):
    """Achievable pre-ADC MAC lattice for one column tile over a calibration
    activation stream (law:csnr: the ideal pre-ADC signal is a discrete
    (N+1)-point lattice, not a continuum).

    Wq_tile (16,) or (Ocols,16): fixed INT4 weights of a column (or column
    block); xq_stream (T,16): the real INT8 activation nibbles that drive it.
    Returns (values sorted unique achievable macs, pitch) where pitch is the
    lattice GCD step in code units (>=1 for integer operands; larger when the
    weights share a common factor). The pitch vs analog-noise sigma is what
    sets whether mid-lattice thresholds can delete noise.
    """
    W = np.atleast_2d(Wq_tile).astype(np.int64)
    X = np.atleast_2d(xq_stream).astype(np.int64)
    macs = np.unique((X @ W.T).ravel())
    if macs.size <= 1:
        return macs, 1
    pitch = int(np.gcd.reduce(np.abs(np.diff(macs))))
    return macs, max(pitch, 1)


def lattice_thresholds(macs, D):
    """Mid-lattice comparator thresholds for the achievable set `macs`
    (paper L6: thresholds co-designed to the lattice). Decision boundaries
    sit at the MIDPOINT between adjacent achievable values instead of at the
    uniform (k+0.5)*D grid; a noisy sample then snaps to the correct lattice
    point whenever |noise| < half the local pitch. Returns the sorted
    boundary array (length len(macs)-1) in code units. Falls back to the
    uniform grid resolution when the lattice is denser than D (pitch < D:
    the converter cannot resolve sub-D structure, boundaries collapse to the
    uniform quantizer — the regime where the gain dies)."""
    macs = np.asarray(macs, dtype=np.int64)
    if macs.size <= 1:
        return np.array([], dtype=np.float64)
    return (macs[:-1] + macs[1:]) / 2.0


def convert_lattice(mac_noisy, macs, thr):
    """Snap a noisy pre-ADC value to the nearest achievable lattice point via
    mid-lattice thresholds `thr` (searchsorted on the boundaries). Bit-exact
    analog of a comparator bank whose reference taps sit mid-lattice.
    Returns the decided lattice VALUE (code units), noise deleted below Δ/2."""
    idx = np.searchsorted(thr, np.asarray(mac_noisy, dtype=np.float64))
    return macs[np.clip(idx, 0, macs.size - 1)]


def convert_uniform(mac_noisy, D):
    """Baseline uniform converter: round the noisy analog value to the D grid
    (comparator thresholds at (k+0.5)*D). The reference the lattice beats."""
    return _half_up_div(np.rint(np.asarray(mac_noisy, dtype=np.float64)
                                ).astype(np.int64), 1) if D == 1 else \
        D * _half_up_div(np.rint(mac_noisy).astype(np.int64), D)


def csnr_db(y_ideal, y_hat):
    """Compute-SNR (law:csnr): Var(y_ideal)/E[(y_hat-y_ideal)^2], in dB.
    The correct accuracy metric for analog compute (NOT ENOB)."""
    y_ideal = np.asarray(y_ideal, dtype=np.float64)
    e = np.asarray(y_hat, dtype=np.float64) - y_ideal
    mse = float(np.mean(e ** 2))
    if mse == 0:
        return np.inf
    return 10 * np.log10(float(np.var(y_ideal)) / mse)


# ----------------------------------------------------------------------------
# 8. softmax reference (digital rail; attention is an application, not analog)
# ----------------------------------------------------------------------------

def softmax_ref(z, beta=1.0):
    """p_i = exp(beta*z_i)/sum_j exp(beta*z_j), max-subtracted. sum_i p_i = 1."""
    z = np.asarray(z, dtype=np.float64) * beta
    e = np.exp(z - np.max(z))
    return e / np.sum(e)


# ----------------------------------------------------------------------------
# 10. LoRA sidecar: quantization + one SGD outer-product step
# ----------------------------------------------------------------------------

def lora_quant(A, B, dw_cols):
    """Quantize rank-1 (A in R^I, B in R^O) to 4b gain-cell codes.

    Charge-domain contract: column j's sidecar adds rho*B_q[j]*(A_q . x)
    in weight-code units, so the real correction is
    dW[j,i] = rho * dw_j * B_q[j]*A_q[i], with rho = dA*dB0 a single global
    gain (A3's one knob) and dw_j the tile's per-channel weight LSB folded
    into B by the compiler. Returns (A_q, B_q, rho).
    """
    dA = np.max(np.abs(A)) / W_MAX
    dA = 1.0 if dA == 0 else dA
    Bn = B / dw_cols
    dB0 = np.max(np.abs(Bn)) / W_MAX
    dB0 = 1.0 if dB0 == 0 else dB0
    A_q = np.clip(np.rint(A / dA), -W_MAX, W_MAX).astype(np.int64)
    B_q = np.clip(np.rint(Bn / dB0), -W_MAX, W_MAX).astype(np.int64)
    return A_q, B_q, dA * dB0


def lora_sgd_step(A, B, x, y, target, lr):
    """One SGD step on L = 0.5*||y - t||^2 for the rank-1 sidecar y += B*(A.x).

    dL/dB = e*(A.x), dL/dA = (B.e)*x, e = y - t  (outer-product update:
    written to sidecar gain cells from digital). Returns (A', B').
    """
    e = y - target
    t = float(np.dot(A, x))
    return A - lr * float(np.dot(B, e)) * x, B - lr * e * t


# ----------------------------------------------------------------------------
# 11. fixture-model attention + FFN golden forward (unit-test scale)
# ----------------------------------------------------------------------------

def quant_in(C, x_raw):
    """Runtime input quantization for a compiled matrix: xq = quant8(x/s, dx_in).

    Smoothing divide happens in the digital wrapper; dx_in is the STATIC
    per-tensor scale fixed at compile time (bit-true reproducible).
    """
    xq, _ = quant_x_int8(np.asarray(x_raw, dtype=np.float64) / C["smooth"], C["dx_in"])
    return xq


def proj(C, xq, relu=False):
    """Tile MVM of compiled matrix C on INT8 codes + per-channel requant.

    out8 = requant(acc) with scale/shift folding D*dw_j*dx_in/dy, so
    out8 * dy ~ W_float @ x_raw. Returns dict(acc, out8, passes, info).
    """
    acc, n, info = mvm_layer(C["Wq"], xq, C["D"], relu=relu)
    return {"acc": acc,
            "out8": requant_int8(acc, C["scale"], C["shift"], C.get("offset", 0)),
            "passes": n, "info": info}


def attention_forward(Wq_c, Wk_c, Wv_c, Wo_c, X, sm_beta=1.0, rope=None):
    """Causal single-head attention, bit-true through the quantized path.

    The four projections are IMC tile MVMs; everything between them is
    digital. Per token: x -> smoothed INT8 -> tile MVMs q,k,v -> (optional
    RoPE on q,k) -> K,V cached as dequantized INT8 tile outputs -> scores,
    softmax (temperature sm_beta; 1/sqrt(d) folded in) and A.V on the digital
    rail -> INT8 -> Wo tile MVM. All scales static from the compiled dicts.
    Returns (out8 (T,O), trace).
    """
    T, d = X.shape
    K, V, trace, outs = [], [], [], []
    for t in range(T):
        # each matrix has its own smoothing + input scale -> per-matrix quant
        xq = quant_in(Wq_c, X[t])
        q8 = proj(Wq_c, xq)["out8"]
        k8 = proj(Wk_c, quant_in(Wk_c, X[t]))["out8"]
        v8 = proj(Wv_c, quant_in(Wv_c, X[t]))["out8"]
        qv, kv_ = q8 * Wq_c["dy"], k8 * Wk_c["dy"]
        if rope is not None:
            qv, kv_ = rope(qv, t), rope(kv_, t)
        K.append(kv_)
        V.append(v8 * Wv_c["dy"])
        z = np.stack(K) @ qv / np.sqrt(len(qv))
        p = softmax_ref(z, sm_beta)
        av = p @ np.stack(V)                         # real units, range of V
        av8 = quant_in(Wo_c, av)
        o8 = proj(Wo_c, av8)["out8"]
        outs.append(o8)
        trace.append({"xq": xq, "q8": q8, "k8": k8, "v8": v8,
                      "scores": z, "p": p, "av8": av8, "out8": o8})
    return np.stack(outs), trace


def ffn_forward(W1_c, W2_c, x_raw, act="relu"):
    """FFN: x -> W1 -> nonlinearity -> W2 (fixture scale, 16->16).

    relu: sign-early-exit ACTIVE in the W1 conversions (A4 sign_exit; exact
    at fixture scale because each output is a single tile pass) — negative
    columns cost 0 comparator strobes and read 0. The float ReLU after
    requant is then a no-op safeguard (exited codes are already 0/positive).
    silu = digital LUT on dequantized INT8 (no exit).
    """
    xq = quant_in(W1_c, x_raw)
    h = proj(W1_c, xq, relu=(act == "relu"))
    hv = h["out8"] * W1_c["dy"]
    hv = np.maximum(hv, 0.0) if act == "relu" else hv / (1.0 + np.exp(-hv))
    o = proj(W2_c, quant_in(W2_c, hv))
    return {"xq": xq, "h8": h["out8"], "out8": o["out8"],
            "sign_exit": h["info"]["exits"],
            "n_eval": h["info"]["n_eval"] + o["info"]["n_eval"],
            "passes": h["passes"] + o["passes"]}


def ffn_forward_gated(Wg_c, Wu_c, Wd_c, x_raw):
    """SwiGLU FFN of the real model: down( silu(gate(x)) * up(x) ).

    silu and the elementwise product run in the digital wrapper on
    dequantized INT8. relu_en = 0 here: gate outputs accumulate 36 row-tile
    partials, so a per-pass sign strobe is NOT the final sign and hardware
    sign-early-exit would corrupt the sum (documented in digital_config).
    sign_exit_opportunity counts negative gate outputs — the energy that a
    future output-side gating scheme could skip in the down matrix.
    """
    xg = quant_in(Wg_c, x_raw)
    xu = quant_in(Wu_c, x_raw)
    g = proj(Wg_c, xg)
    u = proj(Wu_c, xu)
    gv = g["out8"] * Wg_c["dy"]
    hv = (gv / (1.0 + np.exp(-gv))) * (u["out8"] * Wu_c["dy"])
    o = proj(Wd_c, quant_in(Wd_c, hv))
    return {"out8": o["out8"], "g8": g["out8"], "u8": u["out8"],
            "h_raw": hv,
            "sign_exit_opportunity": int(np.sum(g["out8"] < 0)),
            "n_eval": g["info"]["n_eval"] + u["info"]["n_eval"] + o["info"]["n_eval"],
            "passes": g["passes"] + u["passes"] + o["passes"]}


def rmsnorm(x, w, eps=1e-5):
    """RMSNorm (digital wrapper): x * w / sqrt(mean(x^2) + eps)."""
    return x * w / np.sqrt(np.mean(x * x) + eps)


def rope_norm(x, pos, base=10000.0):
    """llama-style NORM RoPE: interleaved pairs (2i,2i+1) rotated by
    pos*base^(-2i/d). Matches GGUF llama weights (convert_hf_to_gguf permutes
    attn_q/attn_k so NORM style applies). Digital-wrapper op."""
    d = x.shape[-1]
    th = pos * np.power(base, -np.arange(0, d, 2) / d)
    c, s = np.cos(th), np.sin(th)
    y = np.array(x, dtype=np.float64)
    y[0::2], y[1::2] = x[0::2] * c - x[1::2] * s, x[0::2] * s + x[1::2] * c
    return y
