"""Bit-true golden of the chosen IMC tile path (ARCH_CHOSEN.md), with an optional analog-error model.

Contract (shared by analog/imc_tile/va/*.va, digital/imc_driver/src/*.v and every testbench):

  weights   INT8, sign-magnitude: w in [-127, 127] (-128 clips to -127, counted). Two slices of
            the magnitude: hi = |w| >> 4 (3 b, n_msb = 7 units of cu_msb) and lo = |w| & 15
            (4 b, n_lsb = 15 units of cu_lsb). Differential: both columns of a pair hold |w|
            units; the weight sign picks which row rail each column's units follow.
  acts      INT8, sign-magnitude on the rows: |x| in 0..127 (7 b; -128 clips to -127, counted).
            Two rails per row, rp and rn; sgn(x) picks the rail that carries the level, the
            other stays at 0, so each column swings 0..VDD (full rail, not 0..VDD/2).
  drive     ml2: 4 slots, slot s carries digit (2|x| >> 2s) & 3 as level d/3 * VDD.
            bitserial: 7 slots, slot s carries bit s of |x| as level 0 / VDD.
  column    per slot: top plate reset, rails driven, top plate shares with the accumulation
            cap C_acc = C_col * r_acc (r_acc = 1/3 ml2, 1 bitserial), so after the last slot
            V_acc = V/128 * sum_j units_j * |x_j| / C_col (LSB-first significance accumulation).
  merge     V_m = (V_acc,msb + rho V_acc,lsb) / (1 + rho), rho sized so the LSB slice weighs
            1/16 of the MSB slice: V_m,diff = k * S, S = sum_j w_j x_j, k = VDD cu_msb /
            (2048 C_msb (1 + rho)).
  SAR       code = clip(floor(V_m / LSB + 1/2), -2^(B-1), 2^(B-1) - 1), LSB = vref / 2^B.
            vref (differential peak-to-peak) = 2^B * lsb_mac * k: one code = lsb_mac MAC units,
            the ideal code is floor((S + lsb_mac/2) / lsb_mac) exactly. lsb_mac 64: vref 1.411 V
            (+-0.705 V), the hard range |S| <= 8*127*127 never clips. lsb_mac 32: vref 0.7055 V,
            ARCH's LSB 172 uV, clips beyond half the hard range (its +-32 sigma rule).
  pooling   pool_k K-adjacent tiles charge-averaged before one conversion: one code =
            64 pool_k MAC units (pool_k = 1 is the T2 per-tile chain the RTL implements).
  cal (B6)  c = (g * code + o + 2^(F-1)) >> F, g unsigned 16 b (Q2.14), o signed 20 b, F = 14.
  chain     acc = sum over the K-chunks of c, 24 b signed (asserted, no wrap in spec).
  requant   y8 = golden.model.requant_int8(acc * lsb_mac * pool_k, scale, shift, offset), the
            systolic reference's requant (sysreference) applied to the code-domain sum.

Labels on defaults: M measured (ASAP7 ESPice, round 2), D derived, P projected (ARCH_CHOSEN).
"""
import math
from dataclasses import dataclass, field, replace

import numpy as np

KB = 1.380649e-23
CAL_F = 14
ACC_W = 24


@dataclass
class P:
    rows: int = 8                  # P  R8
    cols: int = 256                # P  C256 differential columns
    mode: str = "ml2"              # P  round-1 pick; "bitserial" = round-2 fallback
    vdd: float = 0.7               # P  VDD_A
    temp: float = 300.0
    cu_msb: float = 1.0e-15        # P  MOM6 unit, MSB slice
    cu_lsb: float = 0.25e-15       # P  f_cu_lsb
    n_msb: int = 7                 # P  3 magnitude bits (7 fF per side, C_col 56 fF)
    n_lsb: int = 15                # P  4 bits
    c_par: float = 0.0             # top-plate parasitic beyond the units
    adc_bits: int = 12             # P
    lsb_mac: int = 64              # MAC units per code (power of 2): sets vref
    vref: float = None             # derived in __post_init__
    pool_k: int = 1                # P ARCH says 4; 1 = T2 chain as built
    adc_share: int = 4             # columns per converter -> rounds per pass (D: 4 rounds = 6.30 ns)
    # timing: the RTL phase generator counts ticks of a DLL timebase
    t_tick: float = 1.132 / 8      # ns; P ml2 slot 1.132 ns = 8 ticks
    slot_ticks_ml2: int = 8        # P 1.132 ns
    slot_ticks_bs: int = 7         # D 0.99 ns (M lead slot 0.94 ns, N2_r2)
    rst_ticks: int = 1             # top-plate + rail reset at the start of each slot
    sh_ticks: int = 3              # share, ending one tick before the slot end (rails still driven)
    merge_ticks: int = 8           # merge slot (weight writes overlap it, one row per tick)
    round_ticks: int = 11          # 1.557 ns per SAR round (P: <= 1.576 ns)
    # drive (B2): level nets are Thevenin sources r_lvl (ohm, full 256-col tile) behind the rows
    c_row: float = 7.47e-12        # P per row, full tile
    r_lvl_mid: float = 2.54        # M-fit: class-AB SSF settles 59.8 pF to 0.136 mV in 1.132 ns (N9_r2 2.3)
    r_lvl_top: float = 1.30        # D R_PDN per tile for 0.1 % in one slot (N9_r2)
    c_dec_mid: float = 0.0
    c_dec_top: float = 0.0
    tau_row: float = 16.1e-12      # M-fit row segment (N2_r2 lead)
    inl13: float = 0.0             # static level errors (trimmed)
    inl23: float = 0.0
    cc: bool = False               # constant-charge dummies (N2_r2)
    # column (B3)
    tau_col: float = 39.2e-12      # M-fit bootstrapped share, sf32 (N2_r2)
    sig_racc: float = 1e-3         # P acc-cap ratio error (static, per column)
    sig_merge: float = 1e-3        # P merge ratio error <= 0.1 %
    merge_on_top: bool = False     # False: ping-pong acc banks, merge on C_acc only, drive of pass
                                   # p+1 overlaps conversion of p (ARCH t_pass). True: the column is
                                   # the sampler (merge on C_col + C_acc), no overlap.
    # weight store (B1)
    sig_cu_msb: float = 0.01       # P 1 % at 1 fF
    sig_cu_lsb: float = 0.02       # P 2 % at 0.25 fF
    t_ret: float = 2.08e-6         # M gc3t hold-high design retention (N3_r2)
    # converter (B4) / reference (B5)
    sig_cmp: float = 86e-6         # P budget (M: 4.05 mV at the IMC StrongARM size, N9_r2)
    sig_dac_u: float = 0.0245      # D unit-cap sigma that gives the 193 uV C-DAC budget
    # B5 reference: Thevenin r_ref behind decap c_ref, shared by every converter of a tile; each SAR
    # step draws the C-DAC switching charge (imc_sar.va), each decision reads the drooped node
    c_dac: float = 60e-15          # P C-DAC total per converter
    r_ref: float = 0.5             # P class-A buffer output resistance
    c_ref: float = 200e-12         # D B5 area 5,798 um2 x ~35 fF/um2 thin-oxide MOS decap
    t_conv: float = 1.3e-9         # P SAR conversion window (BITS + 1 steps)
    ref_cols: int = 256            # the reference serves a 256-column tile: a narrower bench scales the load
    noise: bool = True             # kT/C on
    terms: tuple = None            # None = all error terms on; else the set that is on

    def __post_init__(self):
        if self.vref is None:
            self.vref = (2 ** self.adc_bits) * self.lsb_mac * self.k()

    # ---- derived geometry
    def c_msb(self): return self.rows * self.n_msb * self.cu_msb + self.c_par
    def c_lsb(self): return self.rows * self.n_lsb * self.cu_lsb + self.c_par
    def r_acc(self): return 1 / 3 if self.mode == "ml2" else 1.0

    def rho(self):
        """Merge cap / MSB acc cap so the LSB slice weighs 1/16 per unit."""
        return (1 / 16) * (self.cu_msb / self.c_msb()) / (self.cu_lsb / self.c_lsb())

    def k(self):
        """Merged differential volts per MAC unit (ideal)."""
        return self.vdd * self.cu_msb / (2048 * self.c_msb() * (1 + self.rho()))

    def n_slots(self): return 4 if self.mode == "ml2" else 7
    def slot_ticks(self): return self.slot_ticks_ml2 if self.mode == "ml2" else self.slot_ticks_bs
    def slot(self): return self.slot_ticks() * self.t_tick
    def t_settle(self): return (self.slot_ticks() - self.rst_ticks - 1) * self.t_tick   # rails driven until share opens
    def t_share(self): return self.sh_ticks * self.t_tick
    def lsb(self): return self.vref / 2 ** self.adc_bits

    def on(self, t):
        return self.terms is None or t in self.terms


TERMS = ("ktc", "mismatch", "drive", "share", "merge", "racc", "cmp", "dac", "ref")
ADC_CLASS = ("quant", "cmp", "dac")          # N8 class weight +3 dB (CLASS_DB adc)
# ARCH_CHOSEN section 2 terms these models do not simulate (no top-plate parasitic, injection or
# coupling paths, no column hold leakage, row gain after calibration): booked at their budget (P)
# as fixed error powers relative to the signal power, so the total is not flattered by omission.
BOOKED_DB = {"hold": 60.7, "coupling": 63.0, "injection": 73.9, "row_coupling": 74.8, "row_gain": 76.9}
# V2 rule: every term within 0.5 dB of its ARCH section 2 budget (adc = quant + cmp + dac, unweighted)
BUDGET_DB = {"ktc": 43.31, "mismatch": 46.02, "adc": 43.30, "ref": 53.98, "drive": 54.81}


# ----------------------------------------------------------------------------- formats
def slice_w(W):
    """W int -> (sign 0/1, hi 0..7, lo 0..15, n_clipped). -128 clips to -127."""
    W = np.asarray(W, np.int64)
    n_clip = int(np.sum(W < -127))
    Wc = np.clip(W, -127, 127)
    m = np.abs(Wc)
    return (Wc < 0).astype(np.int64), m >> 4, m & 15, n_clip


def digits(X, mode):
    """X int8 -> (sign 0/1, digits [..., n_slots] LSB first, the level code per slot)."""
    X = np.clip(np.asarray(X, np.int64), -127, 127)
    m = np.abs(X)
    if mode == "ml2":
        d = np.stack([((2 * m) >> (2 * s)) & 3 for s in range(4)], -1)
    else:
        d = np.stack([(m >> s) & 1 for s in range(7)], -1)
    return (X < 0).astype(np.int64), d


def ideal_code(S, p):
    """Ideal SAR code of an exact column sum S (bit-true integer form)."""
    q = p.lsb_mac * p.pool_k
    c = np.floor_divide(np.asarray(S, np.int64) + q // 2, q)
    h = 2 ** (p.adc_bits - 1)
    return np.clip(c, -h, h - 1)


def cal_apply(code, g, o):
    return (np.asarray(code, np.int64) * g + o + (1 << (CAL_F - 1))) >> CAL_F


# ----------------------------------------------------------------------------- analog model
class Tile:
    """One tile's frozen static errors (unit caps, ratios, DAC weights) + the pass model."""

    def __init__(self, p, seed=0):
        self.p, R, C = p, p.rows, p.cols
        rng = np.random.default_rng(seed)
        mm = p.on("mismatch")
        # per-bit unit groups (bit b of a slice = 2^b units, sigma grows as sqrt(units))
        def grp(nb, sig):
            u = 2 ** np.arange(nb)
            e = rng.standard_normal((R, C, 2, nb)) * sig * np.sqrt(u) if mm else 0.0
            return np.broadcast_to(u + e, (R, C, 2, nb))   # [row, col, side(+/-), bit] in units
        self.hi_u = grp(3, p.sig_cu_msb)
        self.lo_u = grp(4, p.sig_cu_lsb)
        self.racc = p.r_acc() * (1 + rng.standard_normal((C, 2, 2)) * (p.sig_racc if p.on("racc") else 0))
        self.rho = p.rho() * (1 + rng.standard_normal((C, 2)) * (p.sig_merge if p.on("merge") else 0))
        nconv = C // p.adc_share
        B = p.adc_bits
        w = 2.0 ** np.arange(B)
        e = rng.standard_normal((nconv, B)) * np.sqrt(w) * (p.sig_dac_u if p.on("dac") else 0.0)
        self.dacw = w + e                   # [conv, bit] in LSB
        self.rng = np.random.default_rng(seed + 7919)

    def units(self, W):
        """Effective units per (row, col, side, slice) for weights W[R, C]."""
        s, hi, lo, _ = slice_w(W)
        bh = (hi[..., None] >> np.arange(3)) & 1
        bl = (lo[..., None] >> np.arange(4)) & 1
        uh = np.sum(self.hi_u * bh[:, :, None, :], -1)     # [R, C, 2]
        ul = np.sum(self.lo_u * bl[:, :, None, :], -1)
        return s, uh, ul

    def rail_levels(self, sx, d):
        """Rail voltages at share end, [T, R, 2(rp, rn), slots], with drive errors."""
        p = self.p
        V = p.vdd
        if p.mode == "ml2":
            lv = np.array([0, (1 + p.inl13) / 3, (1 + p.inl23) * 2 / 3, 1.0]) * V
        else:
            lv = np.array([0, 1.0]) * V
        L = lv[d]                                           # [T, R, S]
        if p.on("drive"):
            t = p.t_settle() * 1e-9
            nlev = len(lv)
            err = np.zeros_like(L)
            for code in range(1, nlev):
                top = code == nlev - 1
                r = (p.r_lvl_top if top else p.r_lvl_mid)
                cdec = (p.c_dec_top if top else p.c_dec_mid)
                n = np.sum(d == code, axis=1, keepdims=True).astype(float)   # popcount [T,1,S]
                if p.cc:
                    n = np.full_like(n, p.rows)
                crow = p.c_row
                # n rails (r_sw c_row = tau_row each) charging through one level net r (+ c_dec)
                tau = p.tau_row + r * (cdec + n * crow)
                f = (n * crow + cdec * p.tau_row / tau) / np.maximum(cdec + n * crow, 1e-30)
                err = np.where(d == code, np.minimum(f, 1.0) * np.exp(-t / tau), err)
            L = L * (1 - err)
        rails = np.zeros(L.shape[:2] + (2,) + L.shape[2:])
        rails[:, :, 0] = np.where(sx[..., None] == 0, L, 0)
        rails[:, :, 1] = np.where(sx[..., None] == 1, L, 0)
        return rails

    def merged(self, W, X):
        """Merged differential voltage per (token, column) for weights W[R,C], X[T,R]."""
        p = self.p
        kT = KB * p.temp
        sw, uh, ul = self.units(W)
        sx, d = digits(X, p.mode)
        rails = self.rail_levels(sx, d)                     # [T, R, 2, S]
        T, S = X.shape[0], d.shape[-1]
        # side + follows rp where w >= 0 and rn where w < 0; side - the other rail
        rp, rn = rails[:, :, 0], rails[:, :, 1]             # [T, R, S]
        swf = sw.astype(float)
        out = []
        for u, cu, ccol, sl in ((uh, p.cu_msb, p.c_msb(), 0), (ul, p.cu_lsb, p.c_lsb(), 1)):
            up, un = u[:, :, 0] * cu / ccol, u[:, :, 1] * cu / ccol
            vs = np.stack([np.einsum("jc,tjs->tcs", up * (1 - swf), rp) + np.einsum("jc,tjs->tcs", up * swf, rn),
                           np.einsum("jc,tjs->tcs", un * (1 - swf), rn) + np.einsum("jc,tjs->tcs", un * swf, rp)],
                          2)                                # [T, C, side, S]
            ra = self.racc[:, sl, :][None, :, :]           # [1, C, side]
            cacc = ccol * ra
            a = cacc / (ccol + cacc)                        # weight of the old acc
            settle = 1 - math.exp(-p.t_share() * 1e-9 / p.tau_col) if p.on("share") else 1.0
            vacc = np.zeros((T, p.cols, 2))
            for s in range(S):
                v_top = vs[..., s]
                if p.noise and p.on("ktc"):
                    v_top = v_top + self.rng.standard_normal(v_top.shape) * math.sqrt(kT / ccol)
                tgt = a * vacc + (1 - a) * v_top
                vacc = vacc + (tgt - vacc) * settle
                if p.noise and p.on("ktc"):
                    vacc = vacc + self.rng.standard_normal(vacc.shape) * np.sqrt(kT / (ccol + cacc))
            # binary/quaternary significance normalisation: the recursion weighs slot s by
            # (1-a) a^(S-1-s); ideal a gives digit weights 4^s/256 (ml2) or 2^s/256 (bs)
            out.append(vacc)
        vm, vl = out
        rho = self.rho[None]
        v = (vm + rho * vl) / (1 + rho)
        if p.noise and p.on("ktc"):
            cmg = p.c_msb() * (p.r_acc() + (1 if p.merge_on_top else 0)) * (1 + p.rho())
            v = v + self.rng.standard_normal(v.shape) * math.sqrt(kT / cmg)
        return v[..., 0] - v[..., 1]

    def convert(self, vdiff):
        """SAR codes [T, C] of differential voltages [T, C]; error terms per p. Column c is converted
        in round c % adc_share by converter c // adc_share; the converters of a round share the
        reference node (droop carried from round to round within a token)."""
        p = self.p
        code = np.zeros(vdiff.shape, np.int64)
        d = np.zeros((vdiff.shape[0], 1))
        gap = p.round_ticks * p.t_tick * 1e-9 - p.t_conv
        for r in range(p.adc_share):
            cols = np.arange(r, p.cols, p.adc_share)
            code[:, cols], d = sar_convert(vdiff[:, cols], p, self.dacw[cols // p.adc_share],
                                           self.rng if p.on("cmp") else None,
                                           mult=p.ref_cols / p.cols, d0=d)
            d = d * math.exp(-max(gap, 0.0) / (p.r_ref * p.c_ref))
        return code

    def codes(self, W, X):
        return self.convert(self.merged(W, X))


def sar_convert(v, p, dacw, rng=None, mult=1.0, d0=0.0, trace=None):
    """Simultaneous conversions v [T, n] (one round, n converters on one reference) -> (codes, droop).

    Same steps as imc_sar.va: BITS + 1 steps of t_conv / (BITS + 1); step i switches the C-DAC to
    its next trial and draws that charge from the reference (r_ref, c_ref; mult scales the load);
    the decision ending step i reads the drooped reference. The ref term off = ideal reference.
    dacw [n, B] in LSB. Returns codes [T, n] and the droop [T, 1] at the end of the round."""
    B, h, s2 = p.adc_bits, 2 ** (p.adc_bits - 1), 2.0 ** p.adc_bits
    vr = p.vref
    lsb = vr / s2
    u = v / lsb + h
    t_bit = p.t_conv / (B + 1)
    tau = p.r_ref * p.c_ref
    e = math.exp(-t_bit / tau)
    ref = p.on("ref")
    d = np.zeros((v.shape[0], 1)) + d0
    acc = np.zeros(v.shape)
    ia = np.zeros(v.shape)
    tp = np.zeros(v.shape)

    def step(tn, ia_, tp_, d_):
        q = p.c_dac / s2 * (tn * (vr - (u - tn) * lsb) - ia_ * (vr - (u - tp_) * lsb))
        i = mult * np.sum(q, axis=1, keepdims=True) / t_bit
        return d_ * e + i * p.r_ref * (1 - e) if ref else d_

    tn = np.full(v.shape, float(h))
    d = step(tn, ia, tp, d)
    tp = tn
    for k in range(B - 1, -1, -1):
        lsbn = (vr - d) / s2
        trial = acc + dacw[None, :, k]
        nz = rng.standard_normal(v.shape) * (p.sig_cmp / lsbn) if rng is not None else 0.0
        take = (v / lsbn + h + 0.5 + nz) >= trial
        acc = np.where(take, trial, acc)
        ia = ia + take * (1 << k)
        if trace is not None:
            trace.append(d.copy())
        tn = ia + (1 << (k - 1)) if k > 0 else ia
        d = step(tn, ia, tp, d)
        tp = tn
    return ia.astype(np.int64) - h, d


# ----------------------------------------------------------------------------- calibration
def calibrate(tile, n=256, seed=11):
    """Per-column affine fit code ~ a * S/64 + b on random Hadamard-like inputs -> (g, o)."""
    p = tile.p
    rng = np.random.default_rng(seed)
    W = rng.integers(-127, 128, (p.rows, p.cols))
    X = np.clip(np.rint(rng.standard_normal((n, p.rows)) * 40), -128, 127).astype(np.int64)
    S = X @ W
    c = tile.codes(W, X).astype(float)
    t = S / (p.lsb_mac * p.pool_k)
    g = np.zeros(p.cols, np.int64)
    o = np.zeros(p.cols, np.int64)
    for j in range(p.cols):
        a, b = np.polyfit(t[:, j], c[:, j], 1)
        g[j] = int(np.clip(round((1 << CAL_F) / a), 0, 65535))
        o[j] = int(np.clip(round(-b * (1 << CAL_F) / a), -(1 << 19), (1 << 19) - 1))
    return g, o


# ----------------------------------------------------------------------------- GEMM path
def pad(X, W, R, C):
    M, K = X.shape
    N = W.shape[1]
    Kp, Np = -(-K // R) * R, -(-N // C) * C
    Xp = np.zeros((M, Kp), np.int64); Xp[:, :K] = X
    Wp = np.zeros((Kp, Np), np.int64); Wp[:K, :N] = W
    return Xp, Wp


def gemm(X, W, p, tiles=None, cal=None):
    """Full path: K-chunks of R rows on tiles, N-blocks of C columns.

    tiles: None = ideal (bit-true integer), else a list of Tile used round-robin over the
    K-chunks (chunk k on tiles[k % len(tiles)]). cal: per-tile (g, o) list, None = identity.
    Returns (acc [M, N] code domain, codes [chunks, M, Np])."""
    R, C = p.rows, p.cols
    Xp, Wp = pad(X, W, R, C)
    M, Kp = Xp.shape
    Np = Wp.shape[1]
    nk = Kp // R
    assert nk % p.pool_k == 0 or p.pool_k == 1
    acc = np.zeros((M, Np), np.int64)
    codes = []
    for kg in range(0, nk, p.pool_k):
        ks = slice(kg * R, (kg + p.pool_k) * R)
        cg = np.zeros((M, Np), np.int64)
        for n0 in range(0, Np, C):
            Wb, Xb = Wp[ks, n0:n0 + C], Xp[:, ks]
            if tiles is None:
                cg[:, n0:n0 + C] = ideal_code(np.clip(Xb, -127, 127) @ np.clip(Wb, -127, 127), p)
            else:
                v = 0
                for q in range(p.pool_k):
                    t = tiles[(kg + q) % len(tiles)]
                    v = v + t.merged(Wb[q * R:(q + 1) * R], Xb[:, q * R:(q + 1) * R])
                t0 = tiles[kg % len(tiles)]
                cg[:, n0:n0 + C] = t0.convert(v / p.pool_k)
        codes.append(cg)
        if cal is None:
            acc += cg
        else:
            g, o = cal[kg % len(cal)]
            acc += cal_apply(cg, np.tile(g, Np // C), np.tile(o, Np // C))
    assert np.all(np.abs(acc) < 2 ** (ACC_W - 1)), "24-b chain overflow"
    return acc[:, :W.shape[1]], codes


def requant(acc, p, scale, shift, offset):
    from golden.model import requant_int8
    return requant_int8(acc * p.lsb_mac * p.pool_k, scale, shift, offset)


# ----------------------------------------------------------------------------- SNR
def snr_db(S, err):
    return 10 * math.log10(np.var(S) / max(np.mean(err ** 2), 1e-300))


def block_scale(X, W, R):
    """Format F2 (the n5 'block' rho the ARCH SNR budget assumes): every R-row block of x
    (per token) and of w (per column) rescaled to full-scale INT8. Returns int arrays."""
    def q(a, axis):
        m = np.max(np.abs(a), axis=axis, keepdims=True)
        return np.clip(np.rint(a * 127 / np.where(m == 0, 1, m)), -127, 127).astype(np.int64)
    Xb = np.concatenate([q(X[:, k:k + R].astype(float), 1) for k in range(0, X.shape[1], R)], 1)
    Wb = np.concatenate([q(W[k:k + R].astype(float), 0) for k in range(0, W.shape[0], R)], 0)
    return Xb, Wb


def pass_snr(p, W, X, seed=0, cal=True):
    """Per-pass column SNR: error of the calibrated code (x 64 pool) against S = X W (one tile)."""
    t = Tile(p, seed)
    S = np.clip(X, -127, 127) @ np.clip(W, -127, 127)
    c = t.codes(W, X)
    if cal:
        g, o = calibrate(t, seed=seed + 1)
        c = cal_apply(c, g, o)
    err = c * p.lsb_mac * p.pool_k - S
    return snr_db(S, err), S, err


def term_budget(p, W, X, seed=0):
    """Error power per term (MAC^2): quantization alone, then each term added alone."""
    base = replace(p, terms=(), noise=False)
    _, S, e0 = pass_snr(base, W, X, seed)
    pq = float(np.mean(e0 ** 2))
    parts = {"quant": pq}
    for t in TERMS:
        q = replace(p, terms=(t,), noise=(t == "ktc"))
        _, _, e = pass_snr(q, W, X, seed)
        parts[t] = max(float(np.mean(e ** 2)) - pq, 1e-30)
    _, _, eall = pass_snr(p, W, X, seed)
    ps = float(np.var(S))
    db = {k: 10 * math.log10(ps / v) for k, v in parts.items()}
    tot = 10 * math.log10(ps / float(np.mean(eall ** 2)))
    w = sum(v * (10 ** (-0.3) if k in ADC_CLASS else 1.0) for k, v in parts.items())
    return dict(parts_db=db, total_db=tot, sum_db=10 * math.log10(ps / sum(parts.values())),
                weighted_db=10 * math.log10(ps / w))


# ----------------------------------------------------------------------------- timing
def timing(p):
    """Pass timing (ns) of the RTL phase plan: drive slots + merge slot, SAR rounds."""
    t_word = (p.n_slots() * p.slot_ticks() + p.merge_ticks) * p.t_tick
    t_conv = p.adc_share * p.round_ticks * p.t_tick
    t_pass = t_word + t_conv if p.merge_on_top else max(t_word, t_conv)
    return dict(t_word=t_word, t_conv=t_conv, t_pass=t_pass, t_settle=p.t_settle(), t_share=p.t_share())


def drive_settle_err(p, n):
    """Relative rail error at share end with n rows on one level (level-net law, D)."""
    t = p.t_settle() * 1e-9
    out = {}
    for name, r, cdec in (("mid", p.r_lvl_mid, p.c_dec_mid), ("top", p.r_lvl_top, p.c_dec_top)):
        if name == "mid" and p.mode != "ml2":
            continue
        tau = p.tau_row + r * (cdec + n * p.c_row)
        f = min((n * p.c_row + cdec * p.tau_row / tau) / (cdec + n * p.c_row), 1.0)
        out[name] = f * math.exp(-t / tau)
    return out


# ----------------------------------------------------------------------------- self-check
def _selfcheck():
    rng = np.random.default_rng(3)
    p = P(noise=False, terms=())
    # contract constants
    assert abs(p.vref - 1.41102) < 1e-4, p.vref
    assert abs(p.c_msb() - 56e-15) < 1e-20
    # ideal analog model == bit-true integer quantizer (no error terms)
    W = rng.integers(-128, 128, (8, 256))
    X = rng.integers(-128, 128, (64, 8))
    for mode in ("ml2", "bitserial"):
        q = replace(p, mode=mode)
        t = Tile(q)
        c = t.codes(W, X)
        S = np.clip(X, -127, 127) @ np.clip(W, -127, 127)
        ci = ideal_code(S, q)
        # the analog model's float rounding may flip an exact half-LSB tie (S = 64k + 32)
        bad = (c != ci) & ((S + 32) % 64 != 0)
        assert not bad.any(), (mode, int(bad.sum()))
    # extremes fit the converter (sign-magnitude: |S| <= 8*127*127 < 2^17)
    assert np.all(ideal_code(np.array([8 * 127 * 127, -8 * 127 * 127]), p) == [2016, -2016])
    # chain + requant against the exact INT8 GEMM on a K=64 job
    X2 = rng.integers(-127, 128, (5, 64))
    W2 = rng.integers(-127, 128, (64, 40))
    q = replace(p, cols=16)
    acc, _ = gemm(X2, W2, q)
    exact = X2 @ W2
    err = acc * 64 - exact
    assert np.max(np.abs(err)) <= 8 * 32, np.max(np.abs(err))     # <= half a code per chunk
    # calibration of an ideal tile is identity within 1 code
    g, o = calibrate(Tile(replace(p, cols=16)))
    assert np.all(np.abs(g - (1 << CAL_F)) < 64) and np.all(np.abs(o) < (1 << CAL_F)), (g, o)
    print("PASS golden imc_tile self-check")


if __name__ == "__main__":
    _selfcheck()
