"""AnalogIOC-mini executable design math — single source of derived specs.

Every schedule constant, sizing point and reference span used by the
components/testbenches is a FUNCTION of the active PDKConfig
(pdk_specs.py process parameters + gmid.py gm-ID lookups).
Swap the PDK -> the whole chain re-derives.

Per-PDK MEASURED calibration factors (charge-transfer efficiency, OTA
self-load) live in _CAL — they are physical-tile measurements a formula
cannot predict (ponytail: the calibration knob stays).

Paper-law references per function: law:esnr (C_int noise/swing law),
law:adc (ratiometric packet conversion + cadence), law:bout (B_y
statistical converter sizing), eq:cascade (nibble/slice significance),
eq:E_conv (early-termination energy).

Per-PDK DESIGN values (layout-floor caps, delay-chain config) live in _DESIGN —
design choices, not process facts (those are pdk_specs.py). gm/ID lookups come from
gmid.py (GmIDVisualizer tables).

Self-check (asserts the active PDK reproduces the falsifier-validated
values):  python3 analog/docs/specs.py
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pdk_specs import get_pdk  # noqa: E402
import gmid as lookup  # noqa: E402

# ---------------------------------------------------------------------------
# design knobs (architecture constants, PDK-independent)
# ---------------------------------------------------------------------------
B_Y = 8                  # converter output bits (law:bout)
CODE_MAX = 120           # +-4 sigma nominal ceiling (law:bout)
VCM_FRAC = 0.5           # virtual ground at VDD/2
N_ROWS = 16
N_COLS = 17              # 16 data + ABFT checksum
TQ_SIM = 10e-9           # simulation PWM grid (tq_chain, tb_async_ctrl)
K_SETTLE = 2.0           # coarse decision cadence = K_SETTLE * tau_absorb
                         # (item S1: 3 tau was proven, 2 tau is the squeeze;
                         # falsifier tb_integrator_conv +-1 LSB)
MAC_MAX = 185            # OTA compression ceiling in code units (measured)
V_SWING = 0.25           # usable single-sided integrator swing (V)
RC_KICK = 0.44e-9        # coarse anti-kick filter RC (kick charge scales
                         # with this product — hold it while re-scaling C)
C_FILT_MIN = 60e-15      # floor: match the CDAC-side 8k/60f network
KB_T = 1.380649e-23 * 300.15

# OTA gm/ID coordinates (vault recipe, sizing/SIZING.md): (gm/ID, L in units of the
# PDK's Lmin, device). On sky130 (Lmin 0.15) these are AnalogIOC's 0.3 / 0.5 um.
OTA_COORDS = {
    "ota_in":    (12.0, 2.0, "nfet"),
    "ota_ncasc": (10.0, 2.0, "nfet"),
    "ota_pcasc": (10.0, 10 / 3, "pfet"),
    "ota_pmirr": (10.0, 10 / 3, "pfet"),
    "ota_tail":  (18.0, 10 / 3, "nfet"),
}


# Chip-2 softmax / attention path — shared by ptat_bias, rescale, wta, translinear_softmax,
# softmax_combine (one source; each block used to carry its own copy).
I_B = 500e-9             # A, softmax tail design current at 27 C (AnalogIOC I_B_NOM; band 0.1-1 uA)
TL_FRAC = 25 / 27.35     # AnalogIOC's translinear coordinate: gm/ID 25 at sky130's L = 1 um
                         # weak-inversion ceiling 27.35, kept as a fraction of the ceiling
L_SOFTMAX = 1.0          # um, ABSOLUTE long-channel length (matching, low gds): a design
                         # choice, not Lmin-scaled (6.7 Lmin on sky130, 3.6 on gf180)
SCORE_SPAN = 0.25        # V, score window width (CHIP2_SPEC 2.4: 0.6-0.85 V on sky130)
VOS_SOFTMAX = 5e-3       # V, 3-sigma offset budget of score-path blocks (rescale, wta)


def gmid_softmax(pdk=None):
    """THE softmax-path gm/ID (bank tail/branch, ptat_bias, wta, rescale): one number for
    every block, so the exponential slope beta ~ gm/ID agrees end to end. TL_FRAC of the
    nfet weak-inversion ceiling at L_SOFTMAX on the active PDK (sky130: 25.0)."""
    pdk = pdk or get_pdk()
    return TL_FRAC * float(lookup.load_table("nfet", L_SOFTMAX)["gm_ID"].max())


def ota_L(dev, pdk=None):
    """Drawn L [um] of an OTA device on the active PDK (snapped to 10 nm)."""
    pdk = pdk or get_pdk()
    return round(OTA_COORDS[dev][1] * pdk.min_l, 2)
# Item S1/3 re-bias: loop gain measured 330 vs 200 needed -> constant-J
# width scaling to I_SIDE (same VGS operating points, same BIAS voltages,
# gain preserved, gm and SR scale with I). 10 uA/side was the A1 point.
I_SIDE = 6e-6            # A per input-pair side (item S1/3 re-bias; was
                         # 10e-6 — loop gain 330 vs 200 needed, constant-J
                         # scaling keeps every operating point and the gain,
                         # trades gm (settle) for 40% static power)

# ---------------------------------------------------------------------------
# per-PDK measured calibration (the knobs formulas cannot see)
# ---------------------------------------------------------------------------
_CAL = {
    "sky130": {
        "k_cal": 267.45e-18 / (0.15e-15 * 1.8),  # A7 measured Q_UNIT/C_U*VDD
        "beta_int": 0.22,       # integrator feedback factor (measured A2)
        "c_ota_self": 311e-15,  # OTA self/output load at I_SIDE=10uA sizing,
                                # back-solved from measured tau_absorb=26ns:
                                # tau*beta*gm - c_filt - c_int_ser; scales
                                # with device width (constant-J scaling)
        "i_side_ref": 10e-6,    # sizing point of c_ota_self
        "c_par_vg": 700e-15,    # virtual-ground parasitic (C_RAIL + banks)
        "fine_ref_trim": 0.80,  # FINE SAR full-scale trim (diag_fine15): the
                                # 6uA OTA (O1 re-bias 10->6uA) droops the
                                # residue ~0.80x under the CDAC acq load, so
                                # the fine reference span shrinks to match and
                                # the drooped residue crosses the right fine
                                # thresholds. FINE ONLY (thr/coarse untouched);
                                # fine=0 codes (incl. mac32 A7 anchor) unmoved.
    },
}


# ---------------------------------------------------------------------------
# per-PDK design values (moved out of AnalogIOC's PDKConfig.caps / .delay)
# ---------------------------------------------------------------------------
_DESIGN_DEFAULT = {
        "c_unit": 50e-15,         # unit cap (DAC + crossbar)
        "c_int": 500e-15,         # integration cap
        "c_hold": 200e-15,        # sample-hold
        "c_load_delay": 220e-15,  # delay chain load
        "c_int_col": 200e-15,     # column integrator load (incl. parasitics)
        "c_store": 30e-15,        # gain-cell storage MOM cap
        "n_rst_stages": 10,       # ~5ns reset phase
        "n_settle_stages": 20,    # ~10ns settle phase
        "cload": "220f",
        # t_q grid: 2 min-size inv/stage, 550f per inverter -> 10ns nominal per stage
        # at TT (measured 10.0 ns by tb_async_ctrl; first stage ~7.6 ns from a
        # buffered edge)
        "tq_n_taps": 4,
        "tq_cload": "550f",
}
# Per-PDK overrides of the design defaults (AnalogIOC's per-PDK choices).
_DESIGN = {
    "ihp-sg13g2": {
        "c_unit": 30e-15, "c_int": 300e-15, "c_hold": 150e-15, "c_load_delay": 150e-15,
        "n_rst_stages": 10, "n_settle_stages": 18, "cload": "150f",
    },
    # projections: layout floor only; kT/C binds (c_int re-derives to ~52 fF)
    "asap7_proj": {"c_int_col": 50e-15},
    "tsmc_n4_proj": {"c_int_col": 40e-15},
}


def design(pdk=None):
    """Design values for this PDK: AnalogIOC's sky130 choices, overridden per PDK."""
    pdk = pdk or get_pdk()
    return {**_DESIGN_DEFAULT, **_DESIGN.get(pdk.name, {})}


_warned = set()


def cal(pdk=None):
    """Measured tile calibration (_CAL); projection PDKs carry theirs as pdk.cal_proj.
    A PDK with neither falls back to sky130's measurements — loudly: those numbers are
    physical-tile measurements (tb_weight_tile, tb_integrator_conv, diag_fine15) to
    re-measure on the new PDK and add to _CAL."""
    pdk = pdk or get_pdk()
    if pdk.name in _CAL:
        return _CAL[pdk.name]
    if pdk.cal_proj:
        return pdk.cal_proj
    if pdk.name not in _warned:
        _warned.add(pdk.name)
        print(f"specs: UNCALIBRATED {pdk.name} — using sky130 tile calibration "
              f"(k_cal, c_ota_self, c_par_vg, fine_ref_trim); measure and add to _CAL",
              file=sys.stderr)
    return _CAL["sky130"]


def beta_int(pdk=None):
    """Integrator feedback factor, DERIVED from the identity
    beta = C_int/(C_int + C_par_vg) rather than stored per PDK.

    It was stored, and the stored value went stale: tsmc_n4_proj wrote
    `beta_int = 40e-15/(40e-15 + c_par_vg)` = 0.3333 and documented it as
    exactly this identity — but 40 fF is that PDK's LAYOUT FLOOR, while
    c_int() returns 52.14 fF there because the kT/C noise law binds once the
    caps shrink. The constant contradicted its own docstring and understated
    beta by 18%, which inflated tau_absorb by 16% and cost ~19% of the
    projected N4 tok/s. Deriving it kills that class of bug for every
    projection PDK at once. sky130's measured 0.22 (A2) is reproduced to
    within 1% by the identity — asserted in _selfcheck."""
    pdk = pdk or get_pdk()
    c = c_int(pdk)
    return c / (c + cal(pdk)["c_par_vg"])


# ---------------------------------------------------------------------------
# unit charge / caps (law:esnr)
# ---------------------------------------------------------------------------
def c_u(pdk=None):
    """Crosspoint unit cap: swing law — worst |mac| on C_int inside the
    telescopic swing. C_u = C_int*V_swing/(MAC_MAX*VDD), snapped to the
    1 aF layout grid (tile and packet must share the EXACT value).
    (law:esnr)"""
    pdk = pdk or get_pdk()
    c = c_int(pdk) * V_SWING / (MAC_MAX * pdk.vdd)
    return round(c * 1e18 / 10) * 10e-18


def c_int(pdk=None):
    """Integration cap: max(kT/C noise law at B_y, layout floor).
    kT/C: C >= 12*kT*4^B_y/V_swing^2 (law:esnr); at B_y=8/0.25V this is
    ~5 fF — swing, not noise, binds; floor = pdk c_int_col."""
    pdk = pdk or get_pdk()
    c_noise = 12.0 * KB_T * 4.0 ** B_Y / V_SWING ** 2
    return max(c_noise, design(pdk)["c_int_col"])


def k_cal(pdk=None):
    """Measured tile charge-transfer efficiency (A7, tb_weight_tile
    single-crosspoint method). All reference spans sit on the ACTUAL
    charge unit, not the ideal one. (law:adc, ratiometric)"""
    return cal(pdk)["k_cal"]


def q_unit(pdk=None):
    pdk = pdk or get_pdk()
    return k_cal(pdk) * c_u(pdk) * pdk.vdd


def u1(pdk=None):
    """Ideal integrator volts per MAC code unit."""
    pdk = pdk or get_pdk()
    return c_u(pdk) * pdk.vdd / c_int(pdk)


def u_cal(pdk=None):
    """Calibrated volts/unit for every reference span (thr/sar ladders)."""
    return k_cal(pdk) * u1(pdk)


def fine_ref_trim(pdk=None):
    """FINE SAR full-scale trim: the fine-phase acq loads the CDAC onto the
    OTA output and the O1 6uA OTA droops the sampled residue ~0.80x (measured
    diag_fine15). The fine reference span (sar_p/sar_n only, NOT the coarse
    thr sign ladder) shrinks by this factor so the drooped residue reads the
    true fine code. fine=0 codes are untouched (mac32 A7 anchor safe).
    (law:adc, ratiometric — same discipline as u_cal.)"""
    return cal(pdk)["fine_ref_trim"]


def c_pkt(pdk=None, D=1):
    """Coarse reference packet: C_pkt*VDD = 16*D*Q_unit exactly —
    1 packet = 16 code units, ratiometric to the tile (law:adc)."""
    pdk = pdk or get_pdk()
    return 16 * D * c_u(pdk) * k_cal(pdk)


# multi-bank charge-transfer efficiency (A9; measured diag_multibank).
# K_CAL (A7) is the SINGLE-crosspoint (1-bank) anchor -> eff(1) = 1.0. A
# real column dumps n_banks mixed-sign SC banks (units = sum Cp+Cn) onto the
# shared rail + 500 fF C_RAIL each phi2; finite OTA gain/settle delivers only
# ~eff of ideal charge to C_int.
#
# HONEST LIMITATION (measured diag_multibank raw-eff probe): efficiency is
# NOT a clean function of n_banks. At ~19-23 units, real columns measure
# 0.835 / 0.878 / 0.899 (pass_00 cols 3/8/1) vs pass_05's 0.840 — a ~+-3%
# per-column scatter set by the exact cell/weight PATTERN, not bank count.
# The formula below is a FIRST-ORDER model (fit to the pass_05 anchor); it
# corrects the bulk of the -12..-19 LSB deficit (mid codes go exact) but
# leaves a residual: (a) the per-column eff scatter it cannot see, plus
# (b) a positive high-code coarse-loop INL (a column whose eff MATCHES the
# fit, pass_00 col3 mac111 eff0.835, still reads +4 LSB high) — so the
# scalar reference scale is NOT a complete +-1 LSB correction at large
# |code|. The PRODUCTION fix is a per-column MEASURED gain (a known-input
# calibration pass, or the ABFT-checksum servo test_gain_servo), passed to
# the converter in place of this formula; the INL residual then bounds the
# achievable accuracy at ~+3/+4 LSB for |code| >~ 110. (ponytail: the
# hardware needs a per-column calibration knob a bank-count model can't see.)
MB_EFF_FLOOR = 0.84      # busy-column plateau (pass_05 anchor)
MB_EFF_TAU = 3.5         # units-scale of the 1.0 -> floor rolloff


def multibank_efficiency(n_banks):
    """FIRST-ORDER per-column tile charge-transfer efficiency vs n_banks
    (= units = sum(Cp)+sum(Cn)). eff(1) = 1.0 (A7 single-crosspoint anchor);
    saturating-exp rolloff to MB_EFF_FLOOR. See the module comment above for
    the measured LIMITATION (per-column eff scatter + high-code INL) — this
    is a bulk correction, not a +-1 LSB one at large |code|; production wants
    a per-column MEASURED eff here. n_banks<=1 (or 0) -> 1.0 exactly."""
    nb = max(1, int(n_banks))
    if nb == 1:
        return 1.0
    return MB_EFF_FLOOR + (1.0 - MB_EFF_FLOOR) * math.exp(-(nb - 1) / MB_EFF_TAU)


# ---------------------------------------------------------------------------
# OTA sizing chain (vault recipe: gm = wu*CL -> ID -> W via tables)
# ---------------------------------------------------------------------------
def ota(pdk=None, i_side=I_SIDE):
    """Telescopic OTA sizing at drain current i_side per side.

    gm_in = i_side * (gm/ID)_in ; W = ID / J_D(gm/ID, L) per device.
    Loop-gain need: > 200 for 0.5% transfer (SIZING.md); measured 330 at
    the A1 point — constant-J re-bias keeps gain, trades gm for power."""
    pdk = pdk or get_pdk()
    out = {"i_side": i_side, "i_tail": 2 * i_side}
    for dev, (gmid, _, typ) in OTA_COORDS.items():
        L = ota_L(dev, pdk)
        i_d = 2 * i_side if dev == "ota_tail" else i_side
        out[dev] = (round(float(i_d / lookup.J_D(gmid, L, typ)), 2), L)
    out["gm_in"] = i_side * OTA_COORDS["ota_in"][0]
    out["sr"] = 2 * i_side / c_int(pdk)          # V/s into C_int
    out["tau_cl"] = c_int(pdk) / out["gm_in"]    # unloaded closed-loop tau
    return out


# ---------------------------------------------------------------------------
# integrator absorb / coarse cadence (law:adc)
# ---------------------------------------------------------------------------
def kick_filter(pdk=None):
    """Coarse comparator anti-kick R-C. RC held at RC_KICK (kick charge
    scales with RC); C sized so tau_absorb keeps the 2-tau cadence on the
    chop grid — C shrinks with the re-biased gm, floored at the CDAC-side
    match. Returns (R, C)."""
    pdk = pdk or get_pdk()
    o = ota(pdk)
    ca = cal(pdk)
    beta = beta_int(pdk)
    c_self = ca["c_ota_self"] * o["i_side"] / ca["i_side_ref"]
    c_ser = (c_int(pdk) * ca["c_par_vg"] /
             (c_int(pdk) + ca["c_par_vg"]))
    # budget: tau_absorb <= 3 sim-grid cycles (cadence 6 cycles at 2 tau)
    tau_budget = 3 * TQ_SIM
    c = min(220e-15, beta * o["gm_in"] * tau_budget - c_self - c_ser)
    c = max(C_FILT_MIN, c)
    return RC_KICK / c, c


def tau_absorb(pdk=None):
    """Integrator packet-absorb time constant: the OTA loop re-settling
    V_out after a packet dump. tau = C_out_eff/(beta*gm_in) with
    C_out_eff = C_kickfilter + C_self(width-scaled) + C_int series C_par.
    Anchored to the measured 26 ns at the A1 sizing point."""
    pdk = pdk or get_pdk()
    o = ota(pdk)
    ca = cal(pdk)
    _, c_filt = kick_filter(pdk)
    c_self = ca["c_ota_self"] * o["i_side"] / ca["i_side_ref"]
    c_ser = c_int(pdk) * ca["c_par_vg"] / (c_int(pdk) + ca["c_par_vg"])
    return (c_filt + c_self + c_ser) / (beta_int(pdk) * o["gm_in"])


def coarse_cadence(pdk=None):
    """Coarse decision cadence = K_SETTLE * tau_absorb, snapped UP to the
    chop grid (packet fires must land in the chop all-off gap — off-grid
    envelopes give partial transfers). Was 3 tau = 80 ns (A2); squeeze
    point 2 tau. (law:adc; falsifier tb_integrator_conv)"""
    pdk = pdk or get_pdk()
    return math.ceil(K_SETTLE * tau_absorb(pdk) / TQ_SIM - 1e-9) * TQ_SIM


# ---------------------------------------------------------------------------
# reference ladder (item S2: static power + tap stiffness)
# ---------------------------------------------------------------------------
P_LADDER_BUDGET = 5.5e-6     # W per string, worst full-band config
V_TAP_TOL = 0.5e-3           # tap disturbance tolerance (~u_cal/3)
C_KICK_CDAC = 96e-15         # CDAC-equivalent sample load
V_KICK = 75e-3               # worst sample precharge error (tb_rstring
                             # slams 0.85 V onto the 0.923 V mid tap)


def r_seg(pdk=None):
    """Ladder segment R from the static-power budget:
    P = band^2/(15*R) <= P_LADDER_BUDGET at the worst rail-to-rail band
    (0.8 V converter test band). 200 ohm (A2) burned 213 uW/string."""
    pdk = pdk or get_pdk()
    band = 0.8
    r = band ** 2 / (15 * P_LADDER_BUDGET)
    return round(r / 1e3) * 1e3          # snap to 1k


def c_tap(pdk=None):
    """Per-tap decap sized to HOLD the CDAC sample kick: charge-sharing
    droop C_KICK*V_KICK/C_tap <= V_TAP_TOL/2 (2x margin: the settled
    droop must sit well inside the band or the slow string recovery —
    tau = 15R/4 * C_tap — keeps the tap hovering at the band edge;
    measured tb_rstring). Recovery through the string Thevenin is slow
    at high R_SEG BY DESIGN; the decap makes it unnecessary."""
    c = C_KICK_CDAC * V_KICK / (V_TAP_TOL / 2)
    return math.ceil(c * 1e12) * 1e-12   # snap UP to 1 pF


def ladder_area_um2(pdk=None):
    """Decap area check: 16 taps * c_tap on MiM."""
    pdk = pdk or get_pdk()
    return 16 * c_tap(pdk) * 1e15 / pdk.cap_density_mim


# ---------------------------------------------------------------------------
# t_q floor (real-silicon grid)
# ---------------------------------------------------------------------------
def t_q_floor(pdk=None):
    """max(row wire transit, jitter budget). Row RC: 16 crosspoints of
    bank bottom cap on a pitch-scaled met wire. (paper sec_circuits)"""
    pdk = pdk or get_pdk()
    row_len = N_COLS * 15 * pdk.wire_pitch          # um, generous route
    r_row = pdk.r_sq_wire * row_len / pdk.wire_pitch
    c_row = 16 * (15 * c_u(pdk)) + row_len * 0.2e-15  # banks + 0.2 fF/um
    return max(5 * r_row * c_row, pdk.jitter_budget_s)


# ---------------------------------------------------------------------------
# conversion / pass timing model (sim grid)
# ---------------------------------------------------------------------------
T_ACQ = 40e-9        # SAR acquisition (OTA settles the CDAC load)
T_TRIAL = 35e-9      # SAR resampling trial cycle
N_TRIALS = 4
T_SAR_TAIL = 55e-9   # readout margin after last trial


def sar_time(pdk=None):
    return T_ACQ + 5e-9 + N_TRIALS * T_TRIAL + T_SAR_TAIL


# Coarse-loop slot budget. The old 17/19 defaults provisioned the full 8-bit
# `mag` range, but `mag` is never observed above 7 bits: golden.model
# eventrate_convert assembles code = sign*min(16*count + fine, 127) with the
# 4b fine SAR saturating at 15, so count >= 8 is UNREACHABLE — the 127 clamp
# eats it. Truncating the coarse loop at 7 crossings is therefore BIT-IDENTICAL:
#   q >= 112 -> mag' = 112 + min(q-112, 15) = min(q, 127) == the untruncated code
#   q <  112 -> count = q>>4 <= 6, the cap never engages
# Verified exhaustively over q = 0..4095 at D = 1/3/7: cap 7 gives
# max|delta code| = 0, cap 6 loses 16 LSB. So 7 is the exact lossless cap, and
# 6 of the 17 slots were provably dead. (scripts/compiler/metrics/coarse_earlyexit.py)
COARSE_CAP = 7           # lossless ceiling on observable coarse crossings
COARSE_MARGIN = 2        # MEASURED (tb_integrator_conv.py margin): done_v
                         # latches in cadence slot count+1.10 at every test
                         # point (the 0.10 is ~6 ns comparator+logic delay), so
                         # the loop consumes count+2 strobe slots: slot 0
                         # latches sign, slots 1..count fire packets, slot
                         # count+1 is the no-cross that latches done. Margins
                         # 1/2/3/4 are bit-identical; margin 0 is the control
                         # and breaks catastrophically (-13, +15 LSB), so the
                         # falsifier has power. 2 rather than 1 because at
                         # margin 1 done lands 6 ns PAST the coarse budget
                         # conv_time buys - it reads correctly only thanks to a
                         # +15 ns t_sar pad, and it breaks the "SAR starts
                         # after done" invariant that the async controller and
                         # the done-gated OTA park both rely on.
N_COARSE = COARSE_CAP + COARSE_MARGIN    # 9 (was 17 per-nibble / 19 merged)


def conv_time(pdk=None, n_coarse=N_COARSE):
    """One conversion: n_coarse decision slots + SAR. (eq:E_conv)"""
    return n_coarse * coarse_cadence(pdk) + sar_time(pdk)


def window_time(pdk=None, window="lo", t_q=None):
    t_q = TQ_SIM if t_q is None else t_q
    n_cyc = 16 if window == "lo" else 8
    t_chop = t_q if window == "lo" else 16 * t_q
    return n_cyc * t_chop


def pass_time(pdk=None, n_coarse=N_COARSE, t_q=None):
    """Both nibble windows + both conversions (+ settle-in 8 t_q each)."""
    t_q = TQ_SIM if t_q is None else t_q
    pdk = pdk or get_pdk()
    return (window_time(pdk, "lo", t_q) + window_time(pdk, "hi", t_q)
            + 2 * (8 * t_q + conv_time(pdk, n_coarse)))


def merged_pass_time(pdk=None, n_coarse=N_COARSE, t_q=None):
    """Item S5 (law:bout): ONE 128-cycle t_q window + ONE conversion."""
    t_q = TQ_SIM if t_q is None else t_q
    pdk = pdk or get_pdk()
    return 128 * t_q + 8 * t_q + conv_time(pdk, n_coarse)


def pingpong_pass_time(pdk=None, n_coarse=N_COARSE, t_q=None):
    """Item S6: window(n+1) overlaps conversion(n) on the second
    converter path — pass rate = max(window, conversion) + swap gap."""
    t_q = TQ_SIM if t_q is None else t_q
    pdk = pdk or get_pdk()
    return max(128 * t_q + 8 * t_q,
               conv_time(pdk, n_coarse)) + 4 * TQ_SIM


# ---------------------------------------------------------------------------
# K* super-tile conversion cascade (law:cascade, paper sec:supertile)
# ---------------------------------------------------------------------------
# Mini-chip realization (one physical tile, time-multiplexed): K successive
# PWM windows accumulate in charge on the SAME column C_int with the
# converter parked (tphi/run_c gating discipline, A7/A8), then ONE
# conversion whose packet charge and ladder spans are scaled by K
# (C_pkt' = K*C_pkt, coarser Delta_c) so the 8b code space covers the
# K-window sum. The Kx coarser code LSB IS the law's SNR cost.
# Falsifier: analog/testbenches/tb_cascade.py.
SNR_S_DB = 34.0          # per-stage SNR, measured-class (paper sec:supertile)
SNR_T_ATTN_DB = 28.0     # attention-class end-to-end target
EG_SERVO = 0.003         # servoed per-stage gain error (test_gain_servo)
EPS_TOT = 0.02           # cumulative gain-error bound ln(1+eps)/eg


def cascade_window_chain_time(K, pdk=None, window="lo", n_coarse=N_COARSE,
                              t_q=None):
    """ONE cascade chain: K windows + settle-in + ONE conversion
    (vs K*(window + conversion) today). This is the schedule
    tb_cascade realizes and asserts."""
    pdk = pdk or get_pdk()
    t_q = TQ_SIM if t_q is None else t_q
    return (K * window_time(pdk, window, t_q) + 8 * t_q
            + conv_time(pdk, n_coarse))


def cascade_pass_time(K, pdk=None, n_coarse=N_COARSE, t_q=None):
    """Per-pass time with both nibble windows cascaded K deep: the two
    conversions amortize over K passes. K=1 == pass_time() exactly
    (regression anchor)."""
    pdk = pdk or get_pdk()
    t_q = TQ_SIM if t_q is None else t_q
    return (window_time(pdk, "lo", t_q) + window_time(pdk, "hi", t_q)
            + 2 * (8 * t_q + conv_time(pdk, n_coarse)) / K)


def conversions_per_token(K, passes_per_token=10944):
    """2 conversions/pass (lo+hi) today; cascade divides by K."""
    return 2 * passes_per_token / K


def cascade_pass_energy_pj(K, pdk=None, duty_ota=1.0, n_coarse=N_COARSE,
                           e_tile_dyn=120e-12, e_conv_dyn=180e-12):
    """Amortized pass energy: statics burn for cascade_pass_time(K),
    tile dynamic stays per pass, conversion dynamic divides by K.
    K=1 == pass_energy_pj() exactly."""
    pdk = pdk or get_pdk()
    return pass_energy_pj(pdk, duty_ota, n_coarse, e_tile_dyn,
                          e_conv_dyn / K,
                          t=cascade_pass_time(K, pdk, n_coarse))


def cascade_snr_db(K, snr_s_db=SNR_S_DB, eg=EG_SERVO):
    """End-to-end SNR of a K-deep cascade: random errors add in power
    (sigma*sqrt(K)) and the systematic gain error compounds (1+eg)^K
    (worst-case correlated, so it enters as error amplitude)."""
    e_gain = (1.0 + eg) ** K - 1.0
    return -10.0 * math.log10(K * 10.0 ** (-snr_s_db / 10.0) + e_gain ** 2)


def k_star(snr_s_db=SNR_S_DB, snr_t_db=SNR_T_ATTN_DB, eg=EG_SERVO,
           eps_tot=EPS_TOT):
    """Eq. cascade: K* = min{10^((SNRs-SNRT)/10), ln(1+eps_tot)/eg}.
    Paper design point (34, 28, 0.3%): min{4.0, 6.6} -> K* = 4,
    binding on the random term."""
    return min(10.0 ** ((snr_s_db - snr_t_db) / 10.0),
               math.log(1.0 + eps_tot) / eg)


def cascade_k_swing(worst_window_mac=CODE_MAX, pdk=None):
    """Charge-headroom bind at FIXED C_int: the accumulated K-window sum
    must stay in the OTA linear range, K * worst|mac| <= MAC_MAX (both in
    D=1 code units — swing is a raw-charge limit, the conversion LSB does
    not move it). At the nominal 4-sigma window full-scale (CODE_MAX=120)
    this is K=1: worst-case-aligned cascades DO NOT FIT this C_int.
    Real traffic sums grow sqrt(K) (random signs) — tb_cascade selects
    codes under the running-sum guard; the silicon fix for guaranteed
    headroom is C_int' = K*C_int (the merged-mode c_int override in
    integrator_conv.generate — spans then stay at the K=1 voltages)."""
    return max(1, MAC_MAX // int(worst_window_mac))


def tokens_per_s_cascade(K, pdk=None, passes_per_token=10944, t_q=None):
    return 1.0 / (passes_per_token * cascade_pass_time(K, pdk, t_q=t_q))


def tokens_per_j_cascade(K, pdk=None, passes_per_token=10944,
                         duty_ota=1.0):
    return 1.0 / (passes_per_token
                  * cascade_pass_energy_pj(K, pdk, duty_ota) * 1e-12)


def cascade_pingpong_pass_time(K, pdk=None, n_coarse=N_COARSE, t_q=None):
    """Item S6 x cascade (task 2): double-buffered C_int — token b+1
    integrates on cap B while token b converts on cap A, so
    f_MVM = 1/max(T_in, T_conv/K) (+ swap gap, as pingpong_pass_time).
    Isolation falsifier: diag_pingpong.py (B reads code 0 EXACTLY while
    A's packets/SAR fire through B's window)."""
    pdk = pdk or get_pdk()
    t_q = TQ_SIM if t_q is None else t_q
    t_in = window_time(pdk, "lo", t_q) + window_time(pdk, "hi", t_q)
    t_conv = 2 * (8 * t_q + conv_time(pdk, n_coarse))
    return max(t_in, t_conv / K) + 4 * TQ_SIM


# ---------------------------------------------------------------------------
# PARALLEL charge-summing super-tile (law:cascade, paper sec:supertile) —
# ADDITIVE (task #22). The SERIES chain (cascade_snr_db above) re-applies the
# per-column gain error every window -> (1+eg)^K, capping FFN at K=7. The
# PARALLEL super-tile sums K partial charges and applies ONE gain to the SUM
# (or leaves partials as INT8 and sums them digitally): the gain error is
# applied ONCE, so it is K-INDEPENDENT. (1+eg)^K VANISHES; only the random
# sqrt(K) quantization term remains. Falsifier: analog/testbenches/tb_supertile.py.
def parallel_cascade_snr_db(K, snr_s_db=SNR_S_DB, eg=EG_SERVO):
    """K-deep PARALLEL super-tile SNR: the random term still adds in power
    (sigma*sqrt(K) across K partials / K-window sum) but the systematic gain
    error is applied ONCE to the summed charge -> a FIXED eg^2, NOT (1+eg)^K.
    This is the whole point of the parallel topology (SERVO_EG.md #21,
    test_gain_servo assert #4: parallel rel err flat 0.44% at K=1/4/13)."""
    return -10.0 * math.log10(K * 10.0 ** (-snr_s_db / 10.0) + eg ** 2)


def parallel_k_star(snr_s_db=SNR_S_DB, snr_t_db=SNR_T_ATTN_DB, eg=EG_SERVO):
    """Largest K whose PARALLEL cascade SNR still clears the target. Because
    the gain term is fixed (not compounding), the RANDOM sqrt(K) term binds:
    K <= 10^((SNRs-SNRT)/10) (as long as the fixed eg^2 stays under budget).
    At FFN SNRs=38, SNRT=28 -> K=10 (vs the series gain-capped K=7)."""
    k = 1
    while parallel_cascade_snr_db(k + 1, snr_s_db, eg) >= snr_t_db:
        k += 1
    return k


def tokens_per_s_parallel(K, pdk=None, passes_per_token=10944, t_q=None):
    """PARALLEL super-tile tok/s: same merged-window + ping-pong pass law as
    the series cascade (pass(K)=max(136*t_q, T_conv/K)+4*t_q); the parallel
    topology does NOT change the SCHEDULE (one conversion per K windows), it
    changes the ACHIEVABLE K (gain no longer caps it). So tok/s(K) is identical
    to the series law AT THE SAME K — the win is that K can go deeper."""
    pdk = pdk or get_pdk()
    t_q = TQ_SIM if t_q is None else t_q
    return 1.0 / (passes_per_token * cascade_pass_time(K, pdk, t_q=t_q))


# ---------------------------------------------------------------------------
# Task #17 adaptive coarse-RANGE model (27h2) — ADDITIVE, opt-in.
# ---------------------------------------------------------------------------
# Measured single-column coarse energy (out/tile_energy.json e_vs_code):
#   E_coarse(npkt) = E_COARSE_FLOOR + E_PKT * npkt   (npkt = coarse packets fired)
# code<16 fires 0 packets -> pure floor (measured code0 0.204 == code15 0.206),
# so EARLY TERMINATION already makes the coarse loop code-proportional and
# already zeroes the packet cost on every sub-16 column. Fine/SAR is FLAT
# (0.274 pJ, code-independent). Adaptive range shrinks Delta_c on a small
# column so a 2x-coarser packet fires HALF the packets for the same coarse
# resolution -- but the 4b SAR must then absorb 2x the residue span, costing
# +1 effective SAR bit (E_SAR_PER_BIT). 27h2: range adaptation at FIXED
# absolute accuracy buys NOTHING; the only saving is the packet count it
# removes, and that is what this function scores.
E_COARSE_FLOOR = 0.204e-12   # pJ, measured code-0 coarse (non-adaptable)
E_PKT = 0.559e-12            # pJ/coarse-packet, measured slope code16..127
E_SAR = 0.274e-12           # pJ, measured fine (flat, code-independent)
E_SAR_PER_BIT = 0.07 * E_SAR  # ~7%/bit extra SAR trial to absorb coarser Delta


def adaptive_range_saving(coarse_packets, r=2):
    """Incremental coarse-conversion energy of adaptive range vs early-term,
    for one column that fires `coarse_packets` under fixed full-scale.
    Returns (E_early_term, E_adaptive) in Joules. r = Delta_c coarsening
    factor (2 -> 5b SAR, 4 -> 6b SAR). r=1 is byte-identical to early-term.

    Honest ceiling (27h2 + measured): the packet count drops to ceil(P/r) but
    the SAR grows log2(r) bits, so on the real workload (mean ~1.1 pkt/col,
    52% cols already fire 0) the win is small and blocked below r-worth of
    packets. See tb_adaptive_range for the workload roll-up."""
    import math as _m
    P = int(coarse_packets)
    e_et = E_COARSE_FLOOR + E_PKT * P + E_SAR
    if r <= 1:
        return e_et, e_et
    P_adapt = _m.ceil(P / r)
    e_ad = (E_COARSE_FLOOR + E_PKT * P_adapt
            + E_SAR + E_SAR_PER_BIT * _m.log2(r))
    return e_et, min(e_et, e_ad)


# ---------------------------------------------------------------------------
# pass energy model (eq:E_conv; calibrated to tb_tile_mvm measurements)
# ---------------------------------------------------------------------------
def ota_static_w(pdk=None, n_cols=N_COLS):
    pdk = pdk or get_pdk()
    return n_cols * ota(pdk)["i_tail"] * pdk.vdd


def ladder_static_w(pdk=None, span=43.2e-3, n_ladders=4):
    """Converter-band ladder burn (span = 32*u_cal worst)."""
    pdk = pdk or get_pdk()
    return n_ladders * span ** 2 / (15 * r_seg(pdk))


def pass_energy_pj(pdk=None, duty_ota=1.0, n_coarse=N_COARSE,
                   e_tile_dyn=120e-12, e_conv_dyn=180e-12, t=None):
    """Pass energy: OTA static x on-time x duty (bias gating, item S4)
    + tile/converter dynamic (measured residuals) + ladder static.
    duty_ota < 1 models done-parking (mean n_eval/n_coarse).
    t: pass time override (O2 item 4) — pass merged_pass_time()/
    pingpong_pass_time() so S5/S6 schedules price correctly."""
    pdk = pdk or get_pdk()
    t = t if t is not None else pass_time(pdk, n_coarse)
    e = (ota_static_w(pdk) * t * duty_ota
         + ladder_static_w(pdk) * t
         + e_tile_dyn + e_conv_dyn)
    return e * 1e12


def tokens_per_s(pdk=None, passes_per_token=10944, t_q=None):
    t_q = TQ_SIM if t_q is None else t_q
    return 1.0 / (passes_per_token * pass_time(pdk, t_q=t_q))


def tokens_per_j(pdk=None, passes_per_token=10944, duty_ota=1.0):
    return 1.0 / (passes_per_token * pass_energy_pj(pdk, duty_ota) * 1e-12)


# ---------------------------------------------------------------------------
# self-check: sky130 must reproduce the falsifier-validated values
# ---------------------------------------------------------------------------
def _selfcheck():
    pdk = get_pdk()
    # sky130 is where AnalogIOC measured its falsifier points; other PDKs re-derive and
    # are checked only against the PDK-independent laws below.
    anchor = pdk.name == "sky130"
    o = ota(pdk)
    print(f"pdk {pdk.name}: i_side {o['i_side']*1e6:.1f} uA, "
          f"gm_in {o['gm_in']*1e6:.0f} uS")
    # AnalogIOC's sizing (its own ngspice gm/ID tables) — GmIDVisualizer tables must
    # land within 10% or the LUT, not the design, has moved.
    analogioc_w = {"ota_in": 0.54, "ota_ncasc": 0.37, "ota_pcasc": 2.63,
                 "ota_pmirr": 2.63, "ota_tail": 7.06}
    for dev in OTA_COORDS:
        w_spec, l_spec = o[dev]
        if pdk.name == "sky130":
            assert abs(analogioc_w[dev] - w_spec) / analogioc_w[dev] < 0.10, \
                f"{dev}: {w_spec} vs AnalogIOC {analogioc_w[dev]}"
        print(f"  {dev}: {w_spec}/{l_spec} um (AnalogIOC {analogioc_w[dev]})")
    if anchor:
        assert abs(c_u(pdk) - 0.15e-15) / 0.15e-15 < 0.11, c_u(pdk)
        assert abs(k_cal(pdk) - 0.9906) < 0.001
    # TASK A fine-SAR acq-droop trim: fine reference shrinks to the measured
    # ~0.80x OTA loop droop (diag_fine15); fine-only, so <1 and in-band.
    assert 0.70 < fine_ref_trim(pdk) < 1.0, fine_ref_trim(pdk)
    # A9 multi-bank efficiency: single-bank anchor EXACT, monotone rolloff to
    # the measured busy-column floor (real pass_05 ~0.84 at 11-21 units)
    assert multibank_efficiency(1) == 1.0
    assert multibank_efficiency(0) == 1.0
    assert 0.83 < multibank_efficiency(11) < 0.86, multibank_efficiency(11)
    assert 0.83 < multibank_efficiency(21) < 0.86, multibank_efficiency(21)
    assert (multibank_efficiency(4) > multibank_efficiency(11)
            > multibank_efficiency(21) >= MB_EFF_FLOOR)
    r, c = kick_filter(pdk)
    ta = tau_absorb(pdk)
    cad = coarse_cadence(pdk)
    print(f"  kick filter {r/1e3:.2f}k/{c*1e15:.0f}f, tau_absorb "
          f"{ta*1e9:.1f} ns, cadence {cad*1e9:.0f} ns")
    if anchor:
        assert abs(cad - 60e-9) < 1e-12, cad   # item 1 falsifier point
        assert ta <= 30.5e-9, ta
        assert r_seg(pdk) == 8e3               # item 2 falsifier point
        assert abs(c_tap(pdk) - 29e-12) < 1e-15
    print(f"  r_seg {r_seg(pdk)/1e3:.0f}k, c_tap {c_tap(pdk)*1e12:.0f} pF "
          f"(decap area {ladder_area_um2(pdk):.0f} um2/ladder)")
    print(f"  t_q floor {t_q_floor(pdk)*1e12:.0f} ps; pass_time "
          f"{pass_time(pdk)*1e6:.2f} us; OTA static "
          f"{ota_static_w(pdk)*1e6:.0f} uW; ladder static "
          f"{ladder_static_w(pdk)*1e6:.2f} uW")
    # cascade laws: K=1 must reproduce the current numbers EXACTLY
    assert cascade_pass_time(1, pdk) == pass_time(pdk)
    assert cascade_pass_energy_pj(1, pdk) == pass_energy_pj(pdk)
    assert tokens_per_s_cascade(1, pdk) == tokens_per_s(pdk)
    assert tokens_per_j_cascade(1, pdk) == tokens_per_j(pdk)
    assert conversions_per_token(1) == 2 * 10944
    # paper design point: K* = min{10^0.6, ln(1.02)/0.003} = min{4.0, 6.6}
    ks = k_star()
    assert abs(ks - 10.0 ** 0.6) < 1e-12 and round(ks) == 4, ks
    assert abs(k_star(34, 28, 0.001) - math.log(1.02) / 0.001) > 0  # sane
    # swing bind at fixed C_int: worst-case 4-sigma windows do NOT cascade
    if anchor:
        assert cascade_k_swing(CODE_MAX, pdk) == 1
        assert cascade_k_swing(46, pdk) == 4   # tb_cascade K=4 code guard
    print(f"  cascade: K*={ks:.2f} (paper point), SNR(K=4) "
          f"{cascade_snr_db(4):.1f} dB, k_swing(worst) "
          f"{cascade_k_swing()} on C_int {c_int(pdk)*1e15:.0f}f")
    # PARALLEL super-tile (task #22): gain applied once -> (1+eg)^K vanishes.
    # tok/s(K) identical to series at the same K (same schedule); the win is
    # that K goes deeper. FFN (SNRs=38): series gain-capped K=7, parallel
    # random-bound K=10.
    assert tokens_per_s_parallel(1, pdk) == tokens_per_s(pdk)
    assert tokens_per_s_parallel(4, pdk) == tokens_per_s_cascade(4, pdk)
    pk_ffn = parallel_k_star(38.0, 28.0)          # random-bound (gain vanished)
    sk_ffn = 1                                    # series gain-capped, recompute
    while cascade_snr_db(sk_ffn + 1, 38.0) >= 28.0:
        sk_ffn += 1
    # parallel FFN random-bound at K=9 (K=10 is marginal, SERVO_EG.md);
    # series gain-capped at K=7 -> parallel buys +2 K for free.
    assert pk_ffn == 9 and sk_ffn == 7, (pk_ffn, sk_ffn)
    # parallel SNR is FLAT in the gain term: eg contributes a fixed eg^2, so
    # parallel SNR(K) >= series SNR(K) for every K>1 (gain no longer compounds)
    assert parallel_cascade_snr_db(13) > cascade_snr_db(13)
    print(f"  parallel super-tile: FFN K series {sk_ffn} (gain-capped) -> "
          f"parallel {pk_ffn} (random-bound); SNR(K=13) series "
          f"{cascade_snr_db(13):.1f} dB -> parallel "
          f"{parallel_cascade_snr_db(13):.1f} dB")
    print("  K sweep (tok/s x, tok/J x vs K=1, mini passes/token):")
    t1, e1 = tokens_per_s_cascade(1, pdk), tokens_per_j_cascade(1, pdk)
    for K in (1, 2, 4, 8, 13, 16):
        print(f"    K={K:>2}: pass {cascade_pass_time(K, pdk)*1e6:.2f} us "
              f"({cascade_pass_energy_pj(K, pdk):.0f} pJ), tok/s "
              f"x{tokens_per_s_cascade(K, pdk)/t1:.2f}, tok/J "
              f"x{tokens_per_j_cascade(K, pdk)/e1:.2f}, pingpong pass "
              f"{cascade_pingpong_pass_time(K, pdk)*1e6:.2f} us")
    print("SPECS SELF-CHECK PASS")


if __name__ == "__main__":
    _selfcheck()
