"""Format-universal registry + BFP lowering law (A5b).

THE THEOREM (one law, no per-format hacks): any weight format lowers to
  W[j,i] ~ w_scale[j] * 2^exp[j,rt] * M[j,i]
with M an integer mantissa of effective width b_eff = min(source information
width, target precision), shared exponent per 16-input block aligned to
row-tiles ((j, rt) blocks), and M split into S = ceil((b_eff-1)/4) slices of
4-bit differential cap codes (sign is FREE on the differential pair, so a
slice carries 4 magnitude bits; slice s has significance 16^s applied in the
digital shift-add). Exponents NEVER enter the analog core: exp-e_min is a
per-column shift on the tile partial in the accumulator, 2^e_min * w_scale
folds into the per-channel requant scale — the paper's BFP law.

Activations: any format -> per-tensor scale + INT-b_x mantissa, driven as
N_x = ceil((b_x-1)/4) PWM nibbles; the hardware pass pairs two nibbles at
duration ratio 1:16, so b_x <= 8 is a native single pass.

PASS-COUNT LAW (derived from the existing case: INT4 weights = 1 slice,
INT8 acts = 2 nibbles = 1 pass, which this law reproduces as identity):
  passes_per_tile(b_w_eff, b_x) = ceil((b_w_eff-1)/4) * ceil(ceil((b_x-1)/4)/2)

Source information width (BFP full-capture): int-b -> b; float with p
significand bits (man_bits+1, implicit leading 1) and emax_eff finite
exponent levels -> 1 (sign) + p + (emax_eff-1): the block-aligned integer
mantissa width that represents every finite value of the format exactly
(subnormals land on the LSB). Per-ELEMENT precision is sig_bits = p+1; the
CSNR ceiling ~ B_y=8 makes > 8 bits of per-element mantissa physically
unredeemable — lowering allows it but flags it (see FORMATS.md).

Identity guarantees (regression-tested in test_formats.py):
  lower_tensor(W, "int4")  == golden.quant_w_int4(W) bit-identically
  lower_acts(X, "int8")    == golden.quant_x_int8(X) bit-identically
"""

import numpy as np

# ---------------------------------------------------------------------------
# FormatSpec registry
# ---------------------------------------------------------------------------


class FormatSpec:
    """One numeric format. kind 'int': symmetric signed integers in
    [-(2^(b-1)-1), 2^(b-1)-1] (matches the vault's int4 [-7,7] convention);
    decode = identity on the signed codes, encode = round-half-even + clip.

    kind 'float': s | e (exp_bits) | m (man_bits), value:
      e == 0          : (-1)^s * (m / 2^man) * 2^(1-bias)      (subnormal; 0 at m=0)
      0 < e < emax'   : (-1)^s * (1 + m/2^man) * 2^(e-bias)
      e == emax       : inf/nan only where the format defines them (see below)
    Special-value policy:
      has_inf : e=emax, m=0 -> +-inf (fp16/bf16/fp32/fp8_e5m2)
      nan_all : e=emax, m!=0 -> NaN  (fp16/bf16/fp32/fp8_e5m2)
      e4m3    : OCP: NO inf; only s.1111.111 is NaN; s.1111.110 = 448 is a
                normal number (nan_top_code=True)
      tiny formats (fp2/fp3/fp4/fp6): no inf, no nan (all codes finite, OCP MX)
    encode() is SATURATING: |x| > max_finite -> max_finite code (never emits
    inf), NaN -> 0 code (weights/acts have no use for NaN), ties round to
    even mantissa for the wide formats (IEEE casts) and toward -inf (the
    lower value) for the table-based (<= 8 bit) formats — representable
    values round-trip exactly either way (tested).
    """

    def __init__(self, name, kind, bits, exp_bits=0, man_bits=0, bias=0,
                 has_inf=False, nan_all=False, nan_top_code=False, doc=""):
        self.name, self.kind, self.bits = name, kind, bits
        self.exp_bits, self.man_bits, self.bias = exp_bits, man_bits, bias
        self.has_inf, self.nan_all, self.nan_top_code = has_inf, nan_all, nan_top_code
        self.doc = doc
        if kind == "int":
            self.sig_bits = bits                     # signed integer width
            self.info_bits = bits
            self.max_finite = float(2 ** (bits - 1) - 1)
        else:
            p = man_bits + 1                         # significand (implicit 1)
            emax_eff = (1 << exp_bits) - 1 - (1 if (has_inf or nan_all) else 0)
            self.sig_bits = p + 1                    # per-element precision+sign
            # BFP full-capture width: block-aligned integer mantissa that
            # represents EVERY finite value exactly = sign + p + exponent span
            self.info_bits = self.sig_bits + max(emax_eff - 1, 0)
            self.max_finite = self._max_finite()
        if kind == "float" and bits <= 8:
            self._table = self._decode(np.arange(1 << bits, dtype=np.uint64))

    # -- float bit fields ---------------------------------------------------
    def _fields(self, codes):
        c = np.asarray(codes, dtype=np.uint64)
        m = c & np.uint64((1 << self.man_bits) - 1)
        e = (c >> np.uint64(self.man_bits)) & np.uint64((1 << self.exp_bits) - 1)
        s = c >> np.uint64(self.man_bits + self.exp_bits)
        return s.astype(np.int64), e.astype(np.int64), m.astype(np.int64)

    def _max_finite(self):
        emax = (1 << self.exp_bits) - 1
        mmax = (1 << self.man_bits) - 1
        if self.has_inf or self.nan_all:
            emax -= 1                                # top exponent = specials
        elif self.nan_top_code:
            mmax -= 1                                # only top code is NaN
        if emax == 0:                                # all-subnormal (fp2 e1m0)
            return (mmax / 2 ** self.man_bits) * 2.0 ** (1 - self.bias) \
                if self.man_bits else 0.0
        return (1 + mmax / 2 ** self.man_bits) * 2.0 ** (emax - self.bias)

    def _decode(self, codes):
        s, e, m = self._fields(codes)
        sign = np.where(s == 1, -1.0, 1.0)
        sub = m / 2.0 ** self.man_bits * 2.0 ** (1 - self.bias)
        nrm = (1 + m / 2.0 ** self.man_bits) * np.power(2.0, e - self.bias)
        v = sign * np.where(e == 0, sub, nrm)
        emax = (1 << self.exp_bits) - 1
        if self.has_inf:
            v = np.where((e == emax) & (m == 0), sign * np.inf, v)
        if self.nan_all:
            v = np.where((e == emax) & (m != 0), np.nan, v)
        if self.nan_top_code:                        # e4m3: s.1111.111 only
            v = np.where((e == emax) & (m == (1 << self.man_bits) - 1), np.nan, v)
        return v

    # -- public API ---------------------------------------------------------
    def decode(self, codes):
        """codes (uint bit patterns for floats / signed ints for kind=int)
        -> float64 values."""
        if self.kind == "int":
            c = np.asarray(codes, dtype=np.int64)
            assert np.all(np.abs(c) <= self.max_finite), f"{self.name} code range"
            return c.astype(np.float64)
        return self._decode(codes)

    def encode(self, values):
        """float64 -> codes, saturating (see class docstring)."""
        v = np.asarray(values, dtype=np.float64)
        if self.kind == "int":
            return np.clip(np.rint(np.nan_to_num(v, nan=0.0)),
                           -self.max_finite, self.max_finite).astype(np.int64)
        if self.bits <= 8:                           # table nearest-lookup
            tab = self._table
            order = np.argsort(tab, kind="stable")   # finite+specials sorted
            fin = order[np.isfinite(tab[order])]
            vals = tab[fin]
            vc = np.clip(np.nan_to_num(v, nan=0.0), -self.max_finite,
                         self.max_finite)
            idx = np.searchsorted(vals, vc)
            lo = np.clip(idx - 1, 0, len(vals) - 1)
            hi = np.clip(idx, 0, len(vals) - 1)
            pick = np.where(np.abs(vals[hi] - vc) < np.abs(vc - vals[lo]), hi, lo)
            return fin[pick].astype(np.uint64)
        # wide formats: IEEE round-to-nearest-even via numpy casts
        vc = np.clip(np.nan_to_num(v, nan=0.0), -self.max_finite, self.max_finite)
        if self.name == "fp16":
            return np.float16(vc).view(np.uint16).astype(np.uint64)
        if self.name == "fp32":
            return np.float32(vc).view(np.uint32).astype(np.uint64)
        if self.name == "bf16":                      # RNE truncation of f32
            u = np.float32(vc).view(np.uint32).astype(np.uint64)
            r = (u + 0x7FFF + ((u >> np.uint64(16)) & np.uint64(1))) >> np.uint64(16)
            return r.astype(np.uint64)
        raise ValueError(self.name)

    def snap(self, values):
        """decode(encode(v)): nearest representable value, saturating."""
        return self.decode(self.encode(values))


FORMATS = {}
for _b in range(2, 9):
    FORMATS[f"int{_b}"] = FormatSpec(f"int{_b}", "int", _b,
                                     doc=f"symmetric signed, +-{2**(_b-1)-1}")
FORMATS.update({
    # FP2 (s+e1m0, bias 1): e=0 -> 0, e=1 -> +-1. Value set {-1, 0, +1}
    # (ternary, BitNet-style; the per-channel scale carries all magnitude).
    # NOTE the set {0,+-0.5,+-1,+-2} sometimes quoted for "FP2" has 7 values
    # and cannot fit 2 bits — it is exactly fp3_e2m0 below.
    "fp2": FormatSpec("fp2", "float", 2, 1, 0, 1, doc="{0,+-1} ternary"),
    "fp3_e1m1": FormatSpec("fp3_e1m1", "float", 3, 1, 1, 1,
                           doc="{0,+-0.5,+-1,+-1.5}"),
    "fp3_e2m0": FormatSpec("fp3_e2m0", "float", 3, 2, 0, 2,
                           doc="{0,+-0.5,+-1,+-2}"),
    "fp4_e2m1": FormatSpec("fp4_e2m1", "float", 4, 2, 1, 1,
                           doc="MXFP4 {0,.5,1,1.5,2,3,4,6}"),
    "fp6_e2m3": FormatSpec("fp6_e2m3", "float", 6, 2, 3, 1, doc="OCP MX, max 7.5"),
    "fp6_e3m2": FormatSpec("fp6_e3m2", "float", 6, 3, 2, 3, doc="OCP MX, max 28"),
    "fp8_e4m3": FormatSpec("fp8_e4m3", "float", 8, 4, 3, 7, nan_top_code=True,
                           doc="OCP: no inf, s.1111.111=NaN, max 448"),
    "fp8_e5m2": FormatSpec("fp8_e5m2", "float", 8, 5, 2, 15, has_inf=True,
                           nan_all=True, doc="OCP: IEEE-style inf/nan, max 57344"),
    "bf16": FormatSpec("bf16", "float", 16, 8, 7, 127, has_inf=True, nan_all=True),
    "fp16": FormatSpec("fp16", "float", 16, 5, 10, 15, has_inf=True, nan_all=True),
    "fp32": FormatSpec("fp32", "float", 32, 8, 23, 127, has_inf=True, nan_all=True),
})
FORMATS["fp4"] = FORMATS["fp4_e2m1"]                 # common alias (MXFP4)
FORMATS["fp3"] = FORMATS["fp3_e2m0"]

TILE = 16
BY_CEIL_BITS = 8            # B_y=8 output: >8 effective mantissa bits are
                            # physically unredeemable (CSNR ceiling)


def n_slices(b_eff):
    """S = ceil((b_eff-1)/4): sign rides the differential pair for free,
    each slice carries 4 magnitude bits (identity: int4 -> 1 slice)."""
    return max(1, -(-(b_eff - 1) // 4))


def n_nibbles(b_x):
    """PWM nibble count = ceil((b_x-1)/4) (identity: int8 -> 2 nibbles)."""
    return max(1, -(-(b_x - 1) // 4))


def passes_per_tile(b_w_eff, b_x):
    """The pass-count law: slices x nibble-pair rounds (2 windows/pass)."""
    return n_slices(b_w_eff) * -(-n_nibbles(b_x) // 2)


_SCALE_GRID = np.exp2(np.linspace(0.0, -3.0, 13))   # max-anchor .. max/8


def _best_scale(V, fmt, axis):
    """Per-channel (axis=1) or per-tensor (axis=None) snapping scale d:
    argmin-MSE over a 13-point log grid anchored at max|V|/max_finite.

    Max-anchored scaling is exact-optimal for fine grids (fp16 &c) but
    catastrophic for coarse ones (fp2 ternary: everything below half-max
    snaps to 0) — the classic per-format scale trap, solved once here for
    every float format. int sources never come here (identity path).
    """
    a = np.max(np.abs(V), axis=axis) / fmt.max_finite
    a = np.where(a == 0, 1.0, a) if axis is not None else (a or 1.0)
    best_d, best_e = None, None
    for g in _SCALE_GRID:
        d = a * g
        dd = d[:, None] if axis is not None else d
        e = np.sum((V - fmt.snap(V / dd) * dd) ** 2, axis=axis)
        if best_e is None:
            best_d, best_e = d, e
        elif axis is None:
            if e < best_e:
                best_d, best_e = d, e
        else:
            take = e < best_e
            best_d = np.where(take, d, best_d)
            best_e = np.where(take, e, best_e)
    return best_d


def slice_digits(M, S):
    """Signed magnitude digits: D_s = sign(M) * ((|M| >> 4s) & 15),
    sum_s 16^s * D_s == M exactly. Each digit fits one differential 4b cap
    pair (|D_s| <= 15)."""
    M = np.asarray(M, dtype=np.int64)
    assert np.all(np.abs(M) < (1 << (4 * S))), "mantissa exceeds slice budget"
    sg = np.sign(M)
    return np.stack([sg * ((np.abs(M) >> (4 * s)) & 15) for s in range(S)])


# ---------------------------------------------------------------------------
# the lowering law
# ---------------------------------------------------------------------------

def lower_tensor(W, src_fmt, target_bits=BY_CEIL_BITS):
    """Lower a float weight matrix stored in src_fmt onto the substrate.

    Returns dict:
      fmt, b_eff, S, sig (list 16^s), over_by8 flag
      slices (S, O, I) int digits in [-15,15]
      M      (O, I) integer mantissa (= sum sig_s * slices_s)
      w_scale (O,) per-channel float scale
      exp    (O, Rt) per-(row, 16-input-block) shared exponents (<= 0),
             e_min  = int(exp.min())  (folds into requant; shift-add applies
             exp - e_min per column per row-tile)
      W_hat  float64 reconstruction, mse, sqnr_db vs the given W

    int sources (b_eff == fmt.bits): exp == 0 everywhere and the path IS the
    legacy per-channel quant (bit-identical to golden.quant_w_int4 for int4).
    float sources: per-channel scale to the format's full range, snap to the
    format grid, then per-block power-of-2 alignment so the block max uses
    all b_eff-1 magnitude bits (float64 ops on power-of-2 scaled values are
    exact — no double rounding).
    """
    fmt = FORMATS[src_fmt]
    W = np.asarray(W, dtype=np.float64)
    O, I = W.shape
    assert I % TILE == 0, "input dim must be 16-aligned (real-model dims are)"
    Rt = I // TILE
    b_eff = min(fmt.info_bits, target_bits)
    m_max = (1 << (b_eff - 1)) - 1
    S = n_slices(b_eff)

    if fmt.kind == "int" and b_eff == fmt.bits:
        # identity path: legacy symmetric per-channel int quant, exp = 0
        d = np.max(np.abs(W), axis=1) / fmt.max_finite
        d = np.where(d == 0, 1.0, d)
        M = fmt.encode(W / d[:, None])
        exp = np.zeros((O, Rt), dtype=np.int64)
        w_scale = d
    else:
        d = _best_scale(W, fmt, axis=1) if fmt.kind == "float" else \
            np.where(np.max(np.abs(W), axis=1) == 0, 1.0,
                     np.max(np.abs(W), axis=1) / fmt.max_finite)
        Vf = fmt.snap(W / d[:, None])                # values on the fmt grid
        Vb = Vf.reshape(O, Rt, TILE)
        a = np.max(np.abs(Vb), axis=2)               # block max
        # E = floor(log2 a) exactly via frexp (a = f * 2^E, f in [0.5,1))
        _, ex = np.frexp(a)
        exp = (ex - 1 - (b_eff - 2)).astype(np.int64)
        # all-zero blocks (M=0): park at the max exponent so they neither
        # drag e_min down nor widen the shift span (shift value is moot)
        fill = int(exp[a > 0].max()) if np.any(a > 0) else 0
        exp = np.where(a > 0, exp, fill)
        # normalize so fmt.max_finite maps to m_max at exp reference 0
        M = np.clip(np.rint(Vb * np.exp2(-exp)[:, :, None]),
                    -m_max, m_max).astype(np.int64).reshape(O, I)
        w_scale = d
    exp_e = np.repeat(exp, TILE, axis=1)
    W_hat = w_scale[:, None] * np.exp2(exp_e) * M
    err = W - W_hat
    mse = float(np.mean(err ** 2))
    p_sig = float(np.mean(W ** 2))
    sqnr = 10.0 * np.log10(p_sig / mse) if mse > 0 else np.inf
    return {
        "fmt": src_fmt, "b_eff": b_eff, "S": S,
        "sig": [16 ** s for s in range(S)],
        # >8b per-element precision (or an overridden >8b target) cannot be
        # redeemed through a B_y=8 readout — allowed, flagged (FORMATS.md)
        "over_by8": fmt.sig_bits > BY_CEIL_BITS or b_eff > BY_CEIL_BITS,
        "slices": slice_digits(M, S), "M": M, "w_scale": w_scale,
        "exp": exp, "e_min": int(exp.min()),
        "W_hat": W_hat, "mse": mse, "sqnr_db": float(sqnr),
    }


# ---------------------------------------------------------------------------
# CSD / NAF weight recoding (task A, compile.py --csd; default path untouched)
# ---------------------------------------------------------------------------

def csd_digits(M, n_pos=None):
    """Canonical-signed-digit (non-adjacent form) recode of an int array.

    Returns planes (n_pos, *M.shape) with digits in {-1,0,+1}, no two
    adjacent nonzeros, and sum_k planes[k] * 2^k == M exactly. NAF of an
    n-bit magnitude can CARRY into position n (7 -> +8-1), so n_pos
    defaults to bit_length(max|M|)+1; callers slicing digits into 4-bit
    cap groups must size for that extra position (FORMATS.md).
    """
    M = np.asarray(M, dtype=np.int64)
    if n_pos is None:
        n_pos = (int(np.max(np.abs(M))).bit_length() + 1) if M.size else 1
    n = M.copy()
    planes = np.zeros((n_pos,) + M.shape, dtype=np.int64)
    for k in range(n_pos):
        d = np.where(n & 1 == 1, 2 - (n & 3), 0)     # mod 4: 1 -> +1, 3 -> -1
        planes[k] = d
        n = (n - d) >> 1                             # exact: n - d is even
    assert np.all(n == 0), "n_pos too small for the NAF carry"
    return planes


def csd_caps(M):
    """CSD digit planes -> differential 4b cap codes per slice.

    Digit +1 at position k sets bit (k mod 4) of the C+ cap code of slice
    k//4; -1 sets it on C-; 0 programs nothing (both caps off). Returns
    dict(Cp, Cn) of shape (S_csd, *M.shape) with slice significance 16^s
    (same digital shift-add as slice_digits) and
      sum_s 16^s * (Cp[s] - Cn[s]) == M   exactly.
    S_csd = ceil(n_pos/4) can exceed the signed-magnitude slice count by
    one when the NAF carry crosses a slice boundary (b_eff = 4S+1 sources,
    e.g. slice digits of +-15 -> +16-1); |Wq| <= 7 stays single-slice.
    Each 4-digit group has |value| <= 10 (1010 pattern), so Cp, Cn <= 15
    always fit the 4b cap range and Cp & Cn share no bit.
    """
    planes = csd_digits(M)
    n_pos = planes.shape[0]
    S = -(-n_pos // 4)
    shp = (S,) + planes.shape[1:]
    Cp = np.zeros(shp, dtype=np.int64)
    Cn = np.zeros(shp, dtype=np.int64)
    for k in range(n_pos):
        b = 1 << (k % 4)
        Cp[k // 4] += b * (planes[k] > 0)
        Cn[k // 4] += b * (planes[k] < 0)
    return {"Cp": Cp, "Cn": Cn, "S_csd": S,
            "sig": [16 ** s for s in range(S)]}


def _popcount4(c):
    """Set bits of 0..15 codes (ON bit-caps of one 4b bank)."""
    c = np.asarray(c, dtype=np.int64)
    return (c & 1) + ((c >> 1) & 1) + ((c >> 2) & 1) + ((c >> 3) & 1)


def charge_cost(Cp, Cn, duty):
    """Column charge/current model: programmed cap units x activation duty.

    Cp, Cn: (O, I) 4b cap codes (single slice). duty: (I,) per-row mean
    activation duty (mean|xq| / 255 over the real stream: fraction of the
    full 255*t_q window the row envelope is high). Two unit conventions,
    both returned, because they disagree about CSD:
      cells : one unit per ON bit-cap = nonzero digit count. This is the
              bit-sliced / unit-cell array cost where the paper's 1/2->1/3
              CSD density claim lives (each nonzero digit = one unit cell
              switching on the rail), and the switch/driver count here too.
      value : binary-weighted cap units = Cp+Cn code value = the mini's
              actual C_u*VDD charge per chop cycle. One-sided signed
              magnitude already minimizes this (Cp+Cn = |W|), so CSD can
              only increase it -- reported to keep the trade honest.
    Also returns density = nonzero digits / total digit positions.
    """
    Cp = np.asarray(Cp, dtype=np.int64)
    Cn = np.asarray(Cn, dtype=np.int64)
    duty = np.asarray(duty, dtype=np.float64)
    ncells = _popcount4(Cp) + _popcount4(Cn)
    value = Cp + Cn
    return {
        "cells": float(np.sum(ncells * duty[None, :])),
        "value": float(np.sum(value * duty[None, :])),
        "density": float(np.mean(ncells) / 4.0),
        "cells_static": int(ncells.sum()),
        "value_static": int(value.sum()),
    }


def lower_acts(X, src_fmt, target_bits=BY_CEIL_BITS):
    """Any activation format -> per-tensor scale + INT-b_x mantissa.

    int sources: bit-identical to golden.quant_x_int8 for int8 (b_x = fmt
    bits). float sources: snap to the fmt grid at per-tensor scale, then
    carry on the substrate's native INT-8 mantissa (b_x = 8: the PWM pass is
    the same silicon either way, and B_y=8 caps what finer carriage could
    deliver). Returns dict(xq, dx, b_x, n_nib, sqnr_db).
    """
    fmt = FORMATS[src_fmt]
    X = np.asarray(X, dtype=np.float64)
    if fmt.kind == "int":
        b_x = min(fmt.bits, target_bits)
        x_max = (1 << (b_x - 1)) - 1
        dx = np.max(np.abs(X)) / x_max
        dx = 1.0 if dx == 0 else dx
        xq = np.clip(np.rint(X / dx), -x_max, x_max).astype(np.int64)
    else:
        b_x = target_bits
        x_max = (1 << (b_x - 1)) - 1
        da = float(_best_scale(X, fmt, axis=None))
        Xf = fmt.snap(X / da) * da                   # values on the fmt grid
        dx = np.max(np.abs(Xf)) / x_max
        dx = 1.0 if dx == 0 else dx
        xq = np.clip(np.rint(Xf / dx), -x_max, x_max).astype(np.int64)
    err = X - xq * dx
    mse = float(np.mean(err ** 2))
    p = float(np.mean(X ** 2))
    return {"xq": xq, "dx": float(dx), "b_x": b_x, "n_nib": n_nibbles(b_x),
            "sqnr_db": float(10 * np.log10(p / mse)) if mse > 0 else np.inf}
