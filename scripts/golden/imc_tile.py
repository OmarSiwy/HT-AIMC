"""Bit-true golden of the chosen IMC tile path (ARCH_CHOSEN.md), with an optional analog-error model.

Contract (shared by analog/imc_tile/va/*.va, digital/imc_driver/src/*.v and every testbench):

  weights   INT8, sign-magnitude: w in [-127, 127] (-128 clips to -127, counted). Two slices of
            the magnitude: hi = |w| >> 4 (3 b, n_msb = 7 units of cu_msb) and lo = |w| & 15
            (4 b, n_lsb = 15 units of cu_lsb). Differential: both columns of a pair hold |w|
            units; the weight sign picks which row rail each column's units follow.
  acts      INT8, sign-magnitude on the rows: |x| in 0..127 (7 b; -128 clips to -127, counted).
            Two rails per row, rp and rn; sgn(x) picks the rail that carries the level, the
            other stays at 0, so each column swings 0..VDD (full rail, not 0..VDD/2).
  drive     bitserial (BS6H, the pick): 7 slots of 6 ticks (0.849 ns), slot s carries bit s of |x|
            as level 0 / VDD. The rail error at the share edge is the measured droop table of the
            grid-driven rails on a tile PDN of R_PDN = 0.4 ohm (DRIVE_ALT E3, ASAP7 ESPice, M);
            cc = constant-charge dummies (fallback BS6H-cc). ml2 (replaced, selectable): 4 slots,
            slot s carries digit (2|x| >> 2s) & 3 as level d/3 * VDD (level-net law).
  column    per slot: top plate reset, rails driven, top plate shares with the accumulation
            cap C_acc = C_col * r_acc (r_acc = 1/3 ml2, 1 bitserial), so after the last slot
            V_acc = V/128 * sum_j units_j * |x_j| / C_col (LSB-first significance accumulation).
  merge     V_m = (V_acc,msb + rho V_acc,lsb) / (1 + rho), rho sized so the LSB slice weighs
            1/16 of the MSB slice: V_m,diff = k * S, S = sum_j w_j x_j, k = VDD cu_msb /
            (2048 C_msb (1 + rho)).
  SAR       code = clip(floor(V_m / LSB + 1/2), -2^(B-1), 2^(B-1) - 1), LSB = vref / 2^B, found by a
            bipolar search: the first decision at mid-scale, then est += d * step (d = +-1), code =
            est - [d_last < 0]. E-trim (the pick, COMPARATOR_ALT): steps 1024 .. 32, 32, 16 .. 1
            (one redundant 32-LSB step), 6 fast double-tail decisions then 7 quiet tail-starved
            double-tail x2 decisions, 13-tick rounds; dt_x2 (fallback D) is binary with every
            decision quiet. Noise-free, both give the ideal code exactly.
            vref (differential peak-to-peak) = 2^B * lsb_mac * k: one code = lsb_mac MAC units,
            the ideal code is floor((S + lsb_mac/2) / lsb_mac) exactly. lsb_mac 64: vref 1.411 V
            (+-0.705 V), the hard range |S| <= 8*127*127 never clips. lsb_mac 32: vref 0.7055 V,
            ARCH's LSB 172 uV, clips beyond half the hard range (its +-32 sigma rule).
  pooling   pool_k K-adjacent tiles charge-averaged before one conversion: one code =
            64 pool_k MAC units (pool_k = 1 is the T2 per-tile chain the RTL implements).
  cal (B6)  c = (g * code + o + 2^(F-1)) >> F, g unsigned 16 b (Q2.14), o signed 20 b, F = 14.
  chain     acc = sum over the K-chunks of c, 24 b signed (asserted, no wrap in spec).
  block8    (the operand format the accuracy target needs) every 8-row block of x (per token) and
            of w (per column) is rescaled to full-scale INT8 by a scale byte: e = code >> 5 (0..7),
            sig = 32 + (code & 31), value = sig / 64 * 2^-e of the tensor base (5-b mantissa: 0.11 dB
            below exact scales, E4M3's 3 b costs 0.45 dB; architecture.md section 4). The dequant
            multiply per conversion: acc += (c * sig_x * sig_w) << (14 - e_x - e_w), 52 b; the real
            sum is acc * base_x * base_w[n] / 2^20 (MAC units of the block integers).
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


# measured plate error at the share edge (fraction of V) of 8 grid-driven 0/V rows on one tile supply,
# by (corner, R_PDN ohm) -> slot ticks -> (rows on V, error): DRIVE_ALT E1/E3 (sp_rail.py, ASAP7 BSIM-CMG
# ESPice, 0.7 V, M). It replaces the linear level-net law on the V rail, which understates the 8-row
# error 14x at 1.3 ohm (the tile supply sags and the inverters weaken with it).
E_TAB = {
    ("tt", 0.3): {4: ((1, 4, 8), (0.007489, 0.01479, 0.02897)), 5: ((1, 4, 8), (0.00041, 0.001166, 0.003305)),
                  6: ((1, 4, 8), (2.3e-05, 9.2e-05, 0.000373)), 7: ((1, 4, 8), (2e-06, 8e-06, 4.2e-05)),
                  8: ((1, 4, 8), (1e-06, 1e-06, 5e-06))},
    ("tt", 0.4): {4: ((1, 4, 8), (0.008161, 0.01899, 0.04102)), 5: ((1, 4, 8), (0.000467, 0.001715, 0.005694)),
                  6: ((1, 4, 8), (2.7e-05, 0.000154, 0.00078)), 7: ((1, 4, 8), (2e-06, 1.4e-05, 0.000107)),
                  8: ((1, 4, 8), (1e-06, 2e-06, 1.5e-05))},
    ("tt", 0.5): {4: ((1, 4, 8), (0.008868, 0.02375, 0.05481)), 5: ((1, 4, 8), (0.000531, 0.002427, 0.008978)),
                  6: ((1, 4, 8), (3.2e-05, 0.000246, 0.001446)), 7: ((1, 4, 8), (2e-06, 2.5e-05, 0.000233)),
                  8: ((1, 4, 8), (1e-06, 3e-06, 3.8e-05))},
    ("ss", 0.3): {4: ((1, 4, 8), (0.0228, 0.03566, 0.05652)), 5: ((1, 4, 8), (0.002164, 0.004343, 0.008981)),
                  6: ((1, 4, 8), (0.000203, 0.000521, 0.001396)), 7: ((1, 4, 8), (1.9e-05, 6.3e-05, 0.000216)),
                  8: ((1, 4, 8), (2e-06, 8e-06, 3.4e-05))},
    ("ss", 0.4): {4: ((1, 4, 8), (0.0241, 0.04222, 0.07232)), 5: ((1, 4, 8), (0.002358, 0.005663, 0.01331)),
                  6: ((1, 4, 8), (0.000228, 0.000746, 0.002384)), 7: ((1, 4, 8), (2.2e-05, 9.8e-05, 0.000425)),
                  8: ((1, 4, 8), (3e-06, 1.3e-05, 7.6e-05))},
    ("ss", 0.5): {4: ((1, 4, 8), (0.02543, 0.04923, 0.08921)), 5: ((1, 4, 8), (0.002564, 0.007217, 0.01863)),
                  6: ((1, 4, 8), (0.000256, 0.001037, 0.003775)), 7: ((1, 4, 8), (2.6e-05, 0.000149, 0.000761)),
                  8: ((1, 4, 8), (3e-06, 2.2e-05, 0.000153))},
    ("tt", 1.3): {T: ((1, 2, 2.6667, 4, 5.3333, 8), e) for T, e in (
        (4, (0.01586, 0.03198, 0.04559, 0.07822, 0.1151, 0.1924)), (5, (0.0013, 0.003865, 0.006733, 0.01577, 0.02916, 0.06657)),
        (6, (0.000107, 0.000463, 0.00098, 0.003114, 0.007201, 0.02233)), (7, (1e-05, 5.6e-05, 0.000143, 0.000613, 0.001768, 0.007423)),
        (8, (2e-06, 8e-06, 2.2e-05, 0.000121, 0.000434, 0.00246)))},
}
# comparator classes, input-referred sigma per decision (V) by corner: ASAP7 .trannoise (COMPARATOR_ALT
# section 5, M; FF fast = TT x sqrt(T), D). dt_x2_trim: the x2 class built as three switchable
# slices, all three on at SS (0.585 mV, D from the measured x4 SS point by the kappa law)
CMP_SIG = {"dt_fast": dict(tt=1.82e-3, ff=1.99e-3, ss=3.35e-3),
           "dt_x2": dict(tt=0.654e-3, ff=0.747e-3, ss=1.06e-3),
           "dt_x2_trim": dict(tt=0.654e-3, ff=0.747e-3, ss=0.585e-3),
           "strongarm": dict(tt=4.05e-3, ff=4.05e-3, ss=4.05e-3),     # M at TT (N9_r2); corners not run
           "budget": dict(tt=86e-6, ff=86e-6, ss=86e-6)}             # P (ARCH B4)
# SAR options: (redundant step after n_fast decisions, fast class, quiet class, t_conv s, e_conv J)
SAR_OPT = {"etrim": (32, 6, "dt_fast", "dt_x2_trim", 1.61e-9, 276.8e-15),     # the pick (D on M)
           "dt_x2": (0, 0, "dt_x2_trim", "dt_x2_trim", 1.62e-9, 303.7e-15),   # fallback D
           "strongarm": (0, 0, "strongarm", "strongarm", 1.44e-9, 205e-15),   # replaced (fails G2)
           "budget": (0, 0, "budget", "budget", 1.3e-9, 253.5e-15)}           # ARCH round-1 booking


@dataclass
class P:
    rows: int = 8                  # P  R8
    cols: int = 256                # P  C256 differential columns
    mode: str = "bitserial"        # BS6H (DRIVE_ALT); "ml2" = round-1 pick, replaced (fails settling)
    vdd: float = 0.7               # P  VDD_A
    temp: float = 300.0
    corner: str = "tt"             # tt / ss / ff: comparator sigmas and the drive table
    cu_msb: float = 1.0e-15        # P  MOM6 unit, MSB slice
    cu_lsb: float = 0.25e-15       # P  f_cu_lsb
    n_msb: int = 7                 # P  3 magnitude bits (7 fF per side, C_col 56 fF)
    n_lsb: int = 15                # P  4 bits
    c_par: float = 0.0             # top-plate parasitic beyond the units
    adc_bits: int = 12             # P
    lsb_mac: int = 64              # MAC units per code (power of 2): sets vref
    vref: float = None             # derived in __post_init__
    pool_k: int = 1                # P ARCH says 4; 1 = T2 chain as built
    adc_share: int = 3             # columns per converter: 3 rounds of 13 ticks hide under the 42-tick
                                   # drive (5.94 ns); 4 makes the ADC bind (7.36 ns). Chosen by arch_eval
                                   # (tok/s +8.6 to +16 %, imc_tile/docs/architecture.md section 1)
    # timing: the RTL phase generator counts ticks of a DLL timebase
    t_tick: float = 1.132 / 8      # ns; P ml2 slot 1.132 ns = 8 ticks
    slot_ticks_ml2: int = 8        # P 1.132 ns
    slot_ticks_bs: int = 6         # D BS6H 0.849 ns: 0.566 ns of rail time to the share edge (DRIVE_ALT)
    rst_ticks: int = 1             # top-plate + rail reset at the start of each slot
    sh_ticks: int = 3              # share, ending one tick before the slot end (rails still driven)
    merge_ticks: int = 8           # weight-write window, only on weight-change passes (one row per tick)
    merge_hidden: bool = True      # BS6H: the slice merge overlaps the next pass on the other bank
    round_ticks: int = 13          # 1.84 ns per SAR round (E-trim t_conv 1.61 ns + margin)
    # drive (B2): level nets are Thevenin sources r_lvl (ohm, full 256-col tile) behind the rows
    c_row: float = 7.47e-12        # P per row, full tile
    r_lvl_mid: float = 2.54        # M-fit: class-AB SSF settles 59.8 pF to 0.136 mV in 1.132 ns (N9_r2 2.3)
    r_lvl_top: float = 0.4         # P spec: R_PDN <= 0.4 ohm per tile, no slow local decap (DRIVE_ALT)
    drive_law: str = "meas"        # "meas": E_TAB on the V rail (M); "law": the linear level-net law (D)
    c_dec_mid: float = 0.0
    c_dec_top: float = 0.0
    tau_row: float = 16.1e-12      # M-fit row segment (N2_r2 lead)
    inl13: float = 0.0             # static level errors (trimmed)
    inl23: float = 0.0
    cc: bool = False               # constant-charge dummies (BS6H-cc fallback, N2_r2)
    eps_cc: float = 0.03           # P dummy tracking: residual code-dependent fraction of the droop
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
    comparator: str = "etrim"      # SAR_OPT key
    sig_cmp: float = None          # override: one sigma for every decision (sensitivity rows)
    sig_dac_u: float = 0.0245      # D unit-cap sigma that gives the 193 uV C-DAC budget
    # B5 reference: Thevenin r_ref behind decap c_ref, shared by every converter of a tile; each SAR
    # step draws the C-DAC switching charge (imc_sar.va), each decision reads the drooped node
    c_dac: float = 60e-15          # P C-DAC total per converter
    r_ref: float = 0.5             # P class-A buffer output resistance
    c_ref: float = 200e-12         # D B5 area 5,798 um2 x ~35 fF/um2 thin-oxide MOS decap
    t_conv: float = None           # SAR conversion window (NDEC + 1 steps); None = the comparator's
    e_conv: float = None           # J per conversion; None = the comparator's
    ref_cols: int = 256            # the reference serves a 256-column tile: a narrower bench scales the load
    noise: bool = True             # kT/C on
    terms: tuple = None            # None = all error terms on; else the set that is on

    def __post_init__(self):
        if self.vref is None:
            self.vref = (2 ** self.adc_bits) * self.lsb_mac * self.k()
        o = SAR_OPT[self.comparator]
        if self.t_conv is None:
            self.t_conv = o[4]
        if self.e_conv is None:
            self.e_conv = o[5]

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

    def sar_sched(self):
        """(steps [n_dec - 1] in LSB, comparator sigma per decision [n_dec] in V) of the bipolar search."""
        red, nf, cf, cq, _, _ = SAR_OPT[self.comparator]
        steps = [2 ** b for b in range(self.adc_bits - 2, -1, -1)]
        if red:
            steps.insert(nf, red)
        sig = [CMP_SIG[cf][self.corner]] * nf + [CMP_SIG[cq][self.corner]] * (len(steps) + 1 - nf)
        if self.sig_cmp is not None:
            sig = [self.sig_cmp] * len(sig)
        return np.array(steps, float), np.array(sig)


TERMS = ("ktc", "mismatch", "drive", "share", "merge", "racc", "cmp", "dac", "ref")
ADC_CLASS = ("quant", "cmp", "dac")          # N8 class weight +3 dB (CLASS_DB adc)
# ARCH_CHOSEN section 2 terms these models do not simulate (no top-plate parasitic, injection or
# coupling paths, no column hold leakage, row gain after calibration): booked at their budget (P)
# as fixed error powers relative to the signal power, so the total is not flattered by omission.
BOOKED_DB = {"hold": 60.7, "coupling": 63.0, "injection": 73.9, "row_coupling": 74.8, "row_gain": 76.9}
# V2 rule: every term within 0.5 dB of its ARCH section 2 budget (adc = quant + cmp + dac, unweighted).
# adc: the E-trim converter's design point (COMPARATOR_ALT, D); round 1's 43.30 assumed an 86 uV comparator
BUDGET_DB = {"ktc": 43.31, "mismatch": 46.02, "adc": 41.50, "ref": 53.98, "drive": 54.81}


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
        nconv = -(-C // p.adc_share)
        steps, _ = p.sar_sched()
        h = 2.0 ** (p.adc_bits - 1)
        sd = p.sig_dac_u if p.on("dac") else 0.0
        # the C-DAC as the bipolar search sees it: mid-scale threshold and one cap per step, each
        # with sigma sig_dac_u * sqrt(units) (frozen) [LSB]
        self.dmid = h + rng.standard_normal(nconv) * sd * np.sqrt(h)
        self.dstep = steps + rng.standard_normal((nconv, len(steps))) * sd * np.sqrt(steps)
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
            nlev = len(lv)
            err = np.zeros_like(L)
            for code in range(1, nlev):
                top = code == nlev - 1
                n = np.sum(d == code, axis=1, keepdims=True).astype(float)   # popcount [T,1,S]
                e = level_err(p, n, top)
                if p.cc:            # dummies hold the charge at 8 rows: a static gain + a residual
                    e8 = level_err(p, np.full_like(n, float(p.rows)), top)
                    e = e8 + p.eps_cc * (e - e8)
                err = np.where(d == code, e, err)
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
            j = cols // p.adc_share
            code[:, cols], d = sar_convert(vdiff[:, cols], p, self.dmid[j], self.dstep[j],
                                           self.rng if p.on("cmp") else None,
                                           mult=p.ref_cols / p.cols, d0=d)
            d = d * math.exp(-max(gap, 0.0) / (p.r_ref * p.c_ref))
        return code

    def codes(self, W, X):
        return self.convert(self.merged(W, X))


def sar_convert(v, p, dmid, dstep, rng=None, mult=1.0, d0=0.0, trace=None):
    """Simultaneous conversions v [T, n] (one round, n converters on one reference) -> (codes, droop).

    Same steps as imc_sar.va: NDEC + 1 steps of t_conv / (NDEC + 1). Step 0 switches the C-DAC to
    mid-scale; decision i (at the end of step i) compares x = v / LSB_now + 2^(B-1) + 1/2 (+ noise
    sig_i / LSB_now) with the threshold est_i (dmid + sum of +-dstep: the DAC's real caps) and moves
    est by d_i * step_i; the last step switches to the final code est - [d < 0]. Each step draws its
    C-DAC switching charge from the reference (r_ref, c_ref; mult scales the load), and LSB_now reads
    the drooped reference. The charge law (D, ideal caps): the DAC node sits at (u - T) LSB for trial
    T (u = input in LSB, offset binary), and a step from T_p to T_n keeps A = T_n - step units on
    vref, A = T_n on the last step: q = c_dac / 2^B (T_n (vref - vx_n) - A (vref - vx_p)). With
    binary steps this is the offset-binary search exactly. The ref term off = ideal reference.
    dmid [n], dstep [n, n_dec - 1] in LSB. Returns codes [T, n] and the droop [T, 1]."""
    B, h, s2 = p.adc_bits, 2 ** (p.adc_bits - 1), 2.0 ** p.adc_bits
    steps, sig = p.sar_sched()
    nd = len(sig)
    vr = p.vref
    lsb = vr / s2
    u = v / lsb + h
    t_bit = p.t_conv / (nd + 1)
    tau = p.r_ref * p.c_ref
    e = math.exp(-t_bit / tau)
    ref = p.on("ref")
    d = np.zeros((v.shape[0], 1)) + d0

    def step(tn, a, tp_, d_):
        q = p.c_dac / s2 * (tn * (vr - (u - tn) * lsb) - a * (vr - (u - tp_) * lsb))
        i = mult * np.sum(q, axis=1, keepdims=True) / t_bit
        return d_ * e + i * p.r_ref * (1 - e) if ref else d_

    est = np.full(v.shape, float(h))
    est_a = np.broadcast_to(np.asarray(dmid, float)[None, :], v.shape).copy()
    d = step(est, 0.0, est, d)
    for i in range(nd):
        lsbn = (vr - d) / s2
        nz = rng.standard_normal(v.shape) * (sig[i] / lsbn) if rng is not None else 0.0
        dd = np.where(v / lsbn + h + 0.5 + nz >= est_a, 1.0, -1.0)
        if trace is not None:
            trace.append(d.copy())
        tp = est
        if i < nd - 1:
            est = est + dd * steps[i]
            est_a = est_a + dd * np.asarray(dstep, float)[None, :, i]
            d = step(est, est - steps[i], tp, d)
        else:
            est = est - (dd < 0)
            d = step(est, est, tp, d)
    return np.clip(est, 0, s2 - 1).astype(np.int64) - h, d


def ideal_dac(p, n):
    """Mismatch-free (dmid, dstep) for n converters."""
    steps, _ = p.sar_sched()
    return np.full(n, 2.0 ** (p.adc_bits - 1)), np.tile(steps, (n, 1))


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


def gemm(X, W, p, tiles=None, cal=None, cx=None, cw=None, acc_w=ACC_W):
    """Full path: K-chunks of R rows on tiles, N-blocks of C columns.

    tiles: None = ideal (bit-true integer), else a list of Tile used round-robin over the
    K-chunks (chunk k on tiles[k % len(tiles)]). cal: per-tile (g, o) list, None = identity.
    cx [M, chunks], cw [chunks, N]: block8 scale codes (block_codes); the dequant multiply is
    applied per conversion and the chain is acc_w (48) bits.
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
        if cal is not None:
            g, o = cal[kg % len(cal)]
            cg = cal_apply(cg, np.tile(g, Np // C), np.tile(o, Np // C))
        if cx is not None:
            cwp = np.zeros(Np, np.int64)
            cwp[:W.shape[1]] = cw[kg]
            cg = dequant(cg, cx[:, kg][:, None], cwp[None, :])
        acc += cg
    assert np.all(np.abs(acc) < 2 ** (acc_w - 1)), f"{acc_w}-b chain overflow"
    return acc[:, :W.shape[1]], codes


def requant(acc, p, scale, shift, offset):
    """golden.model.requant_int8 on the MAC-domain sum, with the RTL's 6-b shift (0..63, which the
    block8 chain needs); identical to requant_int8 for shift <= 24 (test_imc_tile)."""
    a = np.asarray(acc, np.int64) * p.lsb_mac * p.pool_k * np.asarray(scale, np.int64)
    sh = np.asarray(shift, np.int64)
    half = np.where(sh > 0, np.left_shift(1, np.maximum(sh, 1) - 1), 0)
    return np.clip(((a + half) >> sh) + np.asarray(offset, np.int64), -128, 127).astype(np.int64)


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


SCALE_V = np.array([(32 + (c & 31)) / 64 * 2.0 ** -(c >> 5) for c in range(256)])   # code -> value / base


def dequant(c, cx, cw):
    """Block-scale dequant of calibrated codes: (c * sig_x * sig_w) << (14 - e_x - e_w) (RTL imc_chain)."""
    cx, cw = np.asarray(cx, np.int64), np.asarray(cw, np.int64)
    return np.asarray(c, np.int64) * (32 + (cx & 31)) * (32 + (cw & 31)) * (1 << (14 - (cx >> 5) - (cw >> 5)))


def block_codes(X, W, R):
    """Format block8 with integer scale codes (the RTL contract): per-tensor x base and per-column w
    base; every R-row block's scale is the smallest code value >= its absmax / 127 (no clipping).
    Returns (Xb, Wb, cx [M, K/R], cw [K/R, N], base_x, base_w [N]); real sum ~ acc * bx * bw / 2^20."""
    X, W = np.asarray(X, float), np.asarray(W, float)
    M, K = X.shape
    nk = -(-K // R)
    Xp = np.zeros((M, nk * R)); Xp[:, :K] = X
    Wp = np.zeros((nk * R, W.shape[1])); Wp[:K] = W
    ax = np.abs(Xp).reshape(M, nk, R).max(2) / 127                  # [M, nk]
    aw = np.abs(Wp).reshape(nk, R, -1).max(1) / 127                 # [nk, N]
    bx = max(float(ax.max()), 1e-30) / SCALE_V.max()
    bw = np.maximum(aw.max(0), 1e-30) / SCALE_V.max()

    def code(r):
        ok = SCALE_V[None, :] >= r.reshape(-1, 1) * (1 - 1e-12)
        v = np.where(ok, SCALE_V[None, :], np.inf)
        c = np.argmin(v, 1)
        c = np.where(ok.any(1), c, int(np.argmax(SCALE_V)))
        return c.reshape(r.shape)
    cx, cw = code(ax / bx), code(aw / bw[None, :])
    sx = np.repeat(SCALE_V[cx] * bx, R, 1)
    sw = np.repeat(SCALE_V[cw] * bw[None, :], R, 0)
    Xb = np.clip(np.rint(Xp / sx), -127, 127).astype(np.int64)[:, :K]
    Wb = np.clip(np.rint(Wp / sw), -127, 127).astype(np.int64)[:K]
    return Xb, Wb, cx, cw, bx, bw


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
    """Pass timing (ns) of the RTL phase plan. Drive: the slots (the slice merge runs on the other bank
    under the next pass when merge_hidden; a weight-change pass adds the merge_ticks write window).
    Conversion: adc_share rounds back to back. t_pass = the longer of the two (ping-pong banks)."""
    t_word = (p.n_slots() * p.slot_ticks() + (0 if p.merge_hidden else p.merge_ticks)) * p.t_tick
    t_conv = p.adc_share * p.round_ticks * p.t_tick
    t_pass = t_word + t_conv if p.merge_on_top else max(t_word, t_conv)
    return dict(t_word=t_word, t_word_wchange=t_word + (p.merge_ticks * p.t_tick if p.merge_hidden else 0),
                t_conv=t_conv, t_pass=t_pass, t_settle=p.t_settle(), t_share=p.t_share())


def level_err(p, n, top=True):
    """Relative rail error at the share edge with n rows on one level net: the measured table on the V
    rail (drive_law "meas", log-interpolated in n, linear to 0 below the first point), else the
    linear level-net law (n rails, r_sw c_row = tau_row each, through r_lvl + c_dec; D)."""
    n = np.asarray(n, float)
    if top and p.drive_law == "meas":
        ns, es = E_TAB[(p.corner if p.corner != "ff" else "tt", p.r_lvl_top)][p.slot_ticks()]
        nn = np.clip(n, 1e-9, ns[-1])
        return np.where(nn < ns[0], es[0] * nn / ns[0], np.exp(np.interp(nn, ns, np.log(es))))
    r, cdec = (p.r_lvl_top, p.c_dec_top) if top else (p.r_lvl_mid, p.c_dec_mid)
    t = p.t_settle() * 1e-9
    tau = p.tau_row + r * (cdec + n * p.c_row)
    f = np.minimum((n * p.c_row + cdec * p.tau_row / tau) / np.maximum(cdec + n * p.c_row, 1e-30), 1.0)
    return f * np.exp(-t / tau)


def drive_settle_err(p, n):
    """Relative rail error at the share edge with n rows on one level, per level net."""
    out = {"top": float(level_err(p, n, True))}
    if p.mode == "ml2":
        out["mid"] = float(level_err(p, n, False))
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
    # every SAR schedule finds floor(x) noise-free over the whole range (redundant steps included)
    for cmp_ in SAR_OPT:
        q = replace(p, comparator=cmp_)
        v = (np.arange(-2100, 2100, 0.37) * q.lsb())[None, :]
        c, _ = sar_convert(v, q, *ideal_dac(q, v.shape[1]))
        ci = np.clip(np.floor(v / q.lsb() + 0.5), -2048, 2047)
        assert np.all((c == ci) | (np.abs(v / q.lsb() % 1 - 0.5) < 1e-9)), cmp_
    # block8: codes reproduce the block scale within its 4-b significand, no clipping, and the
    # dequantized chain sum tracks the float GEMM
    Xf = rng.standard_normal((6, 64)) * np.exp(rng.standard_normal((6, 64)))
    Wf = rng.standard_normal((64, 24))
    Xb, Wb, cx, cw, bx, bw = block_codes(Xf, Wf, 8)
    assert np.max(np.abs(Xb)) <= 127 and np.max(np.abs(Wb)) <= 127 and np.max(np.abs(Xb)) >= 64
    acc, _ = gemm(Xb, Wb, replace(p, cols=8), cx=cx, cw=cw, acc_w=52)
    yf = Xf @ Wf
    rel = np.sqrt(np.mean((acc * bx * bw[None, :] / 2 ** 20 - yf) ** 2)) / np.sqrt(np.mean(yf ** 2))
    assert rel < 0.05, rel
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
