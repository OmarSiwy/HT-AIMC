"""N9 circuits and operating point at ASAP7. Write-up: docs/src/content/Project/ArchResearch/nodes/N9.md.

Contract (model.py): op(p, vdd, clk_frac) -> e_scale, delay_scale, leak_scale, clk_GHz for the
digital logic (rail, buffer, the systolic baseline). Laws are the MEASURED ASAP7 tables below
(ESPice BSIM-CMG, TT 27 C, this node's runs; reproduce with `python3 n9_circuits.py --char`):
  e_scale(V)     = [E_f(V) + (lib-1) (V/0.7)^2 E_f(0.7)] / (lib E_rvt(0.7))   bare-device + cell-parasitic
                   blend, lib = inv_switch_energy_fJ_lib / inv_switch_energy_fJ = 5.4 (CHAR.md)
  delay_scale(V) = FO4_f(V) / FO4_rvt(0.7)
  leak_scale(V)  = V (Ioff_n,f(V) + Ioff_p,f(V)) / (0.7 (Ioff_n,rvt(0.7) + Ioff_p,rvt(0.7)))   (DIBL measured)
  f = the logic Vt flavour of the option (n9_logic_vt).

The circuit choices this node owns (row drivers and swing, column switches, references, amplifiers,
clocking, supply domains) change tile energy, time, area and accuracy, which the core contract
cannot carry today. `evaluate_full(design)` runs model.evaluate with three hooks:
  _arr_fix   on n2.array: column-switch Ron at the worst signal point, (B+1) ln2 settling, the
             driver's word time (planes x slot, or one DAC settle) and the driver's swing cap;
  _acc_fix   on n5.accuracy: hold-droop mismatch at 85 C and the row-DAC INL / kT/C / gain-mismatch
             terms, as extra parts_db that the n8 gate sees;
  plumb      on the composed tile: driver, reference, digital-periphery and clock energy and area,
             and (only when n9_margin_on) the clock margin. Scoring is at TT (ARCH_METRIC); margins
             are a sensitivity. Every term is labelled in-line.
The core change that would make this native is in N9.md "Open questions".
Round 2 (N9_r2.md): ml2_rails pays its level buffers' settling bias (ML2_ANCHOR, measured), the SAR loop
can take LVT/SLVT per comparator class (_sar_vt, measured ratios), and MOS decaps can sit in the FEOL slack
under the MOM array (n9_decap_under, projected).
"""
import math

import numpy as np

from arch_eval import asap7 as k

# ── measured here (ESPice, ASAP7 r1p7 BSIM-CMG, TT 27 C unless noted, no layout parasitics) ─────
_V4 = (0.45, 0.5, 0.6, 0.7)
FO4_PS = dict(rvt=(25.87, 18.84, 12.54, 9.88), lvt=(15.32, 12.54, 9.59, 8.15), slvt=(10.91, 9.54, 7.97, 7.15))
E_FJ = dict(rvt=(0.0407, 0.0530, 0.0833, 0.1209), lvt=(0.0449, 0.0580, 0.0900, 0.1303),
            slvt=(0.0501, 0.0642, 0.0991, 0.1436))                     # 1+1-fin inverter, per transition
IOFF_N = dict(rvt=(0.00979, 0.01079, 0.01328, 0.01638), lvt=(0.1086, 0.1132, 0.1232, 0.1342),
              slvt=(1.112, 1.153, 1.236, 1.323))                        # nA/fin, VGS=0, VDS=V
IOFF_P = dict(rvt=(0.01348, 0.01428, 0.01603, 0.01799), lvt=(0.1345, 0.1427, 0.1606, 0.1806),
              slvt=(1.395, 1.480, 1.665, 1.871))
IOFF85_N = dict(rvt=0.1003, lvt=0.866, slvt=6.20)   # nA/fin, VGS 0, VDS 0.35 V, 85 C (27 C: 0.0083/0.100/1.03)
_V5 = (0.45, 0.5, 0.55, 0.6, 0.7)
TG_RMAX = dict(rvt=(368133, 160524, 76699, 41048, 18325), lvt=(51864, 29404, 20462, 15038, 10238),
               slvt=(17099, 13310, 10853, 9387, 7549))                 # 1n+1p TG, worst Ron over 0..VDD
# NMOS 1 fin, VDS 5 mV, Ron vs VGS (= VG - VS). Measured over VS 0..0.45 at VG 0.45..0.7: BSIM-CMG shows
# no body effect, Ron depends on VGS only (e.g. VG 0.7/VS 0.2 = VG 0.5/VS 0 = 9044 ohm). A bootstrapped
# gate (VG = VS + 0.7) gives Ron(0.7) at every VS: signal-independent, measured flat to 5 digits.
_VGS = (0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70)
NMOS_R_VGS = dict(rvt=(408150, 84942, 29848, 16333, 11402, 9044, 7713, 6881, 6324, 5932),
                  lvt=(53336, 22113, 13378, 9867, 8082, 7035, 6365, 5907, 5580, 5337),
                  slvt=(18569, 11914, 9072, 7572, 6672, 6086, 5681, 5389, 5171, 5003))
_V3 = (0.5, 0.6, 0.7)
PREAMP = dict(gain=(43.3, 44.7, 40.9), span_V=(0.262, 0.312, 0.338), sndr3_dB=(51.8, 55.7, 62.0))
#   2n+2p RVT inverter at its trip point, DC: open-loop gain, output span where gain >= 0.7 peak.
# Row-DAC buffer, inverting unity-gain (2n+2p RVT, 10 Mohm in/feedback, DC sweep; a static-linearity
# proxy for the capacitive-feedback buffer, no settling dynamics), INL after a best-fit line, % of the
# output span, SS corner (TT is 10-20 % lower). 1 stage: A0 41; 3 stages: three inverters in the loop.
_SPAN = (0.10, 0.20, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60)
INL_PK_1ST = (0.0089, 0.0327, 0.0893, 0.145, 0.229, 0.388, 0.682, 1.247, 2.471)
INL_RMS_1ST = (0.0026, 0.0093, 0.0244, 0.038, 0.0579, 0.0926, 0.1546, 0.2728, 0.5483)
INL_PK_3ST = (0.0, 0.0, 0.0, 0.0, 0.0001, 0.0001, 0.0001, 0.001, 0.002)
GAIN_1ST = 0.951                          # closed-loop |gain| at TT (1/(beta A0) ~ 5 % static, calibrated)
FO4_SS_OVER_TT = 11.354 / 9.876          # measured, SS 0.7 V 27 C (asap7_constants fo4_delay_ps_ss)
FO4_SIGNOFF = 14.077 / 9.876             # measured, SS 0.63 V 100 C (the liberty SS point) = 1.425
DIG_SIGNOFF = 1162.9 / 715.4             # measured: sysreference ppa.json s8 fmax TT / SS (STA) = 1.626
# ── round 2 (A5, 2026-10-06; N9_r2.md), measured here, TT 27 C 0.7 V, intrinsic devices ───────────
# IMC-grade StrongARM (char.py topology: in 16, tail 8, latch 4/4, reset 2 fins, +2 fF on P/Q), 1 mV input,
# all devices of one flavour (scratchpad a5/cmp_fl.py). kappa = E x vn^2, vn derived (note 19p) from the
# measured Iss, C1 and the flavour's gm/ID table at the measured VGS of the input pair.
CMP_TDEC_PS = dict(rvt=32.65, lvt=22.85, slvt=18.35)
CMP_E_FJ = dict(rvt=2.936, lvt=3.081, slvt=3.257)
CMP_KAPPA_X = dict(rvt=1.00, lvt=1.73, slvt=1.95)   # per quiet decision at fixed noise, vs RVT. MEASURED (critic r2):
# ESPice .trannoise (BSIM-CMG noise), constant 3/6 mV input, 150-250 decisions per flavour, sigma = dv/Phi^-1(P):
# RVT 4.05, LVT 5.20, SLVT 5.38 mV (+-12 % each, binomial); kappa = (E_f/E_rvt)(sigma_f/sigma_rvt)^2 (scratchpad
# a5/cmp_tn.py). The round-2 closed form (note 19p) gave 1.61 / 2.59 and sigma 1.24 / 1.53 / 1.89 mV: it is 3.3x
# low in absolute sigma (n6's noise budget) and over-states the SLVT penalty.
CMP_SIGMA_MV_TN = dict(rvt=4.05, lvt=5.20, slvt=5.38)
SAR_FINS_PER_ADC = 2 * 13 * 24 + 2 * 40 + 50        # 2 DFF/decision x 24 fins, 2 comparator classes, misc (projected)
# Closed-loop class-AB row-level buffer: super source follower (NMOS follower M1 256 fins + PMOS shunt M2
# 8192 fins, I1 1 mA, I2 2 mA) holding V/3 = 0.2333 V while 8 rows x 7.47 pF (59.8 pF, precharged to 0)
# switch on through a 4096-fin switch (~2.6 ohm, the damping). Max |rail error| over 1.0-1.5 ns after the
# switch: 0.136 mV (spec 0.7 mV), P_q 2.8 mW (scratchpad a5/drv3b.py, measured). The plain follower
# (critic, crit/drv2.py) needs 16k fins / 32 mA = 22.4 mW for ~0.4 mV. A stiffer path (16k-fin switch) makes
# the SSF ring (3.6 mV): the rail's series R is part of the design. 2V/3 needs a PMOS-input SSF (an NMOS
# follower gate would sit above 0.7 V): priced at 1.5x the V/3 buffer (PMOS fT ~0.7x, projected).
ML2_ANCHOR = dict(c_fF=59.8e3, t_ns=1.132, err=1e-3, ssf_W=2.8e-3, follower_W=22.4e-3, ssf_um2=37.0,
                  follower_um2=70.0, pdn_W=0.0, pdn_um2=0.0, hi_x=dict(ssf=1.5, follower=1.0, pdn=0.0))
# "pdn" (critic r2, symmetric law): V/3 and 2V/3 are two more die-level supply nets (bumps + top-metal mesh +
# die-wide decap, an off-chip or die-level regulator) exactly as bit-serial's VDD/GND are. No tile-local bias;
# the regulator loss is the eta 0.5 delivery term already charged. Both drives then need the same PDN
# impedance, notes["pdn_r_req_ohm"] = t_slot / (R c_row ln(1/err)) (projected; no PDN extracted, sim S5).
# Per-plate row-drive devices (critic r2): bit-serial INV (2 T), ml2 INV + 2 TG (6 T). ASAP7 INVx1 footprint
# 3 CPP x 7.5 T = 0.162 x 0.27 um = 0.044 um2 per 2 T (liberty cell, derived). They go in FEOL slack first.
PLATE_DEV = dict(inv_bitserial=(2, 0.044), ml2_rails=(6, 0.132))
SAR_T_PER_ADC = 2 * 13 * 24 + 2 * 12 + 60           # transistors: 26 DFF x 24 T, 2 StrongARM, misc (projected)


def _i(xs, ys, v):
    return float(np.interp(v, xs, ys))


def _ron_vgs(fl, vgs):
    """Per-fin NMOS Ron at a gate overdrive point (log-interpolated, measured table)."""
    return float(np.exp(np.interp(vgs, _VGS, np.log(NMOS_R_VGS[fl]))))


# ── options: the lead bundle, then one dimension changed per option ───────────────────────────────
LEAD = dict(n9_rail="split", n9_vdd_analog=0.7, n9_logic_vt="rvt", n9_clock="dll_replica",
            n9_ref="buffered", n9_amp="n6", n9_driver="ml2_rails", n9_colsw="bootstrap",
            n9_switch_vt="rvt", n9_ref_eta=0.3, n9_ldo_eta=0.875, n9_cal_gates=80, clk_nom_GHz=1.0,
            n9_margin_on=False, n9_beta=0.5, n9_gmid_inv=30.0, n9_a0_sigma=0.10, n9_hot_C=85.0,
            n9_reservoir_x=32.0, n9_rail_err=0.001)
CLOCK = dict(  # (margin on every analog+digital time, clock-net factor, local gen fJ/cycle)
    sync_tree=(FO4_SIGNOFF * 1.08, 2.0, 0.0),   # liberty-SS sign-off (measured 1.425) x 8 % skew+jitter (projected)
    self_timed=(1.10, 0.3, 6.0),                # matched-delay/replica padded for local variation (projected)
    gals_local=(1.12, 1.0, 10.0),               # per-tile ring osc. tracks local PVT; sync. on hops
    dll_replica=(1.06, 1.5, 2.0),               # paper sec_sync: one DLL locked to a replica column
    tt_no_margin=(1.0, 0.0, 0.0),               # the ARCH_METRIC scoring convention (TT 25 C)
)
# Driver: (bits per plane k; None = abits, i.e. one plane; stages of the row buffer). Swing cap in swing_cap().
DRIVERS = dict(inv_bitserial=(1, 0), row_dac=(None, 1), row_dac_ms=(None, 3), nibble_dac=(4, 1),
               ml3_dac=(3, 1), ml2_rails=(2, 0), sf_dac=(None, 1), pwm=(None, 0))
_VAR = dict(
    lead={},
    # supply / operating point
    single_rail=dict(n9_rail="single"), ntv_rail_045=dict(n9_rail="single", n9_pin_vdd=0.45),
    analog_rail_09=dict(n9_vdd_analog=0.9),
    # logic Vt flavour (rail, buffer, baseline logic)
    vt_lvt_logic=dict(n9_logic_vt="lvt"), vt_slvt_logic=dict(n9_logic_vt="slvt"),
    vt_slvt_all=dict(n9_logic_vt="slvt", n9_switch_vt="slvt"),
    # column / share switch
    colsw_midrail_tg_rvt=dict(n9_colsw="midrail_tg"), colsw_midrail_tg_lvt=dict(n9_colsw="midrail_tg", n9_switch_vt="lvt"),
    colsw_midrail_nmos_rvt=dict(n9_colsw="midrail_nmos"), colsw_ground_nmos_rvt=dict(n9_colsw="ground_nmos"),
    colsw_ground_slvt=dict(n9_colsw="ground_nmos", n9_switch_vt="slvt"),
    colsw_ground_lvt=dict(n9_colsw="ground_nmos", n9_switch_vt="lvt"), colsw_bootstrap_lvt=dict(n9_switch_vt="lvt"),
    # clocking / timebase: margin applied (sensitivity; the score itself is at TT)
    **{f"clk_{c}": dict(n9_clock=c, n9_margin_on=True) for c in CLOCK},
    # references
    ref_ratiometric_decap=dict(n9_ref="ratiometric"), ref_reservoir=dict(n9_ref="reservoir"),
    ref_bandgap_ldo=dict(n9_ref="bandgap_ldo"),
    # amplifiers
    amp_none=dict(preamp=False), amp_ota_integrator=dict(n9_ota=True, int_bits_cap=6.0),
    amp_twostage_integrator=dict(n9_ota=True, int_bits_cap=round(math.log2(0.5 * 500) - 1, 2)),
    amp_telescopic=dict(n9_ota=True, int_bits_cap=round(math.log2(0.5 * 200) - 1, 2)),
    # row drivers / input DACs
    **{f"drv_{d}": dict(n9_driver=d) for d in DRIVERS if d != "ml2_rails"},
    # round 2 (A5): sizing for delay and area, paid in power (N9_r2.md)
    ml2_follower=dict(n9_ml2_buf="follower"),                       # the critic's plain follower, for reference
    sar_lvt=dict(n9_sar_vt_q="lvt", n9_sar_vt_l="lvt"),
    sar_slvt=dict(n9_sar_vt_q="slvt", n9_sar_vt_l="slvt"),
    sar_dual=dict(n9_sar_vt_l="slvt"),                              # quiet class RVT, logic/cheap class SLVT
    sar_lvt_q=dict(n9_sar_vt_q="lvt", n9_sar_vt_l="slvt"),
    decap_under=dict(n9_decap_under=True),
    fast_dual=dict(n9_sar_vt_l="slvt", n9_decap_under=True),
    fast_slvt=dict(n9_sar_vt_q="slvt", n9_sar_vt_l="slvt", n9_decap_under=True),
    bitserial_dual=dict(n9_driver="inv_bitserial", n9_sar_vt_l="slvt", n9_decap_under=True),
)
PROV = dict(
    lead="projected: split rail (analog 0.7 V, logic swept), RVT logic, 2-b-per-plane row drive switched "
         "between 4 rails (0, V/3, 2V/3, V; 4 planes for 8 b; V/3 and 2V/3 from two trimmed tile-shared "
         "class-AB buffers; round 2: their settling bias is charged, P_q from the measured super-source-follower anchor, N9_r2.md) at full swing (v_exc_frac 0.5), bootstrapped NMOS column share/reset switch (constant VGS, measured "
         "flat Ron), class-A buffered reference, N6 quiet comparator with a dynamic (capacitor-biased) preamp, "
         "DLL replica timebase; measured ASAP7 tables (this node); laws 27h1, 27h5, 19g1, 6i1, 11c2, 18k, 20x, 5c4",
)
OPTIONS = {n: dict(params=dict(LEAD, **v), provenance=PROV.get(n, f"projected: lead bundle with {v}; see N9.md"))
           for n, v in _VAR.items()}
DEFAULT = "lead"
# vdd / clk_frac: the operating-point grid model.py reads. The rest: N9_r2's own sizing sweep (r2_sweep()).
SWEEP = dict(vdd=[0.45, 0.5, 0.55, 0.6, 0.65, 0.7], clk_frac=[1.0, 0.5, 0.25],
             n9_sar_vt_q=["rvt", "lvt", "slvt"], n9_sar_vt_l=["rvt", "lvt", "slvt"], n9_decap_under=[False, True],
             n9_ml2_buf=["ssf", "follower"], share_fins=[8, 16, 32, 64], adc_share=[2, 4],
             rail_headroom=[2.0, 3.0, 4.0])
NOTES = {"drv_pwm": "PWM encodes in time; on a charge-domain cell the bottom plate settles to the row level "
                    "whatever the pulse width, so it is meaningless here. Scored with the corrected law as if "
                    "N2 were current-integrating (conditional)."}


# ── contract ─────────────────────────────────────────────────────────────────────────────────────
def analog_vdd(p, vdd):
    if p.get("n9_pin_vdd"):
        return p["n9_pin_vdd"]
    return p["n9_vdd_analog"] if p.get("n9_rail") == "split" else vdd


def op(p, vdd, clk_frac=1.0):
    f = p.get("n9_logic_vt", "rvt")
    lib = k.get("inv_switch_energy_fJ_lib") / k.get("inv_switch_energy_fJ")
    e_rvt = E_FJ["rvt"][-1]
    e = (_i(_V4, E_FJ[f], vdd) + (lib - 1) * (vdd / 0.7) ** 2 * E_FJ[f][-1]) / (lib * e_rvt)
    ds = _i(_V4, FO4_PS[f], vdd) / FO4_PS["rvt"][-1]
    leak = vdd * (_i(_V4, IOFF_N[f], vdd) + _i(_V4, IOFF_P[f], vdd)) / (0.7 * (IOFF_N["rvt"][-1] + IOFF_P["rvt"][-1]))
    return dict(vdd=vdd, clk_frac=clk_frac, e_scale=e, delay_scale=ds, leak_scale=leak,
                clk_GHz=p.get("clk_nom_GHz", 1.0) / ds * clk_frac, vdd_analog=analog_vdd(p, vdd), logic_vt=f)


# ── circuit laws ─────────────────────────────────────────────────────────────────────────────────
def _driver(p, fmt):
    """-> (name, bits per plane, planes, buffer stages)."""
    d = p.get("n9_driver", "inv_bitserial")
    kb, stages = DRIVERS[d]
    ab = int(fmt["abits"])
    if d == "inv_bitserial":
        return d, 1, int(fmt["input_planes"]), 0
    kb = kb or ab
    return d, kb, -(-ab // kb), stages


def swing_cap(p, va=0.7):
    """Largest v_exc_frac (row excitation +-frac x V_a, i.e. row span 2 frac V_a) the driver passes:
    rail-to-rail drivers 0.5; a buffered DAC the span where its measured SS INL <= 1/2 LSB of its
    plane bits (capped at the 0.6 V measured range); source follower V_a - V_GS (0.45 V measured)."""
    d, kb, _, stages = _driver(p, dict(abits=8, input_planes=8))
    if stages == 0:                                   # bit-serial, 2-b rails, PWM: levels are rails
        return 0.5
    if d == "sf_dac":
        return (va - 0.45) / (2 * va)
    half = 100 * 0.5 / 2 ** kb                        # % of span
    pk = INL_PK_3ST if stages > 1 else INL_PK_1ST
    span = _SPAN[-1] if pk[-1] <= half else float(np.interp(half, pk, _SPAN))
    return min(0.5, span / (2 * 0.7))                 # INL table is at 0.7 V; span scales with V_a to first order


def _column_switch_ohm(p, va, exc):
    """Per-fin R of the column share/reset switch at its worst signal point (measured tables).
    exc = per-side column excursion (V): +-k_sigma of the column signal (n5)."""
    sw, f = p.get("n9_colsw", "ground_nmos"), p.get("n9_switch_vt", "rvt")
    if sw == "ground_nmos":     # CM = exc (off switch never sees VGS > 0), worst node 2 exc (18y)
        return _ron_vgs(f, va - 2 * exc)
    if sw == "midrail_nmos":    # CM = V_a/2 (measured table at VS = V_a/2 + exc)
        return _ron_vgs(f, va / 2 - exc)
    if sw == "bootstrap":       # VG = VS + 0.7 V: Ron(0.7) at every VS (measured flat)
        return _ron_vgs(f, 0.7)
    return _i(_V5, TG_RMAX[f], va)                    # midrail_tg (1n+1p per fin pair), worst over the range


def _excursion(p, va, rows):
    try:
        from arch_eval.nodes import n5_array
        rho = n5_array.rho_of(p, rows)
    except Exception:  # noqa: BLE001
        rho = p.get("rho", 0.1)
    return p.get("k_sigma", 4.0) * va * p["v_exc_frac"] * rho / math.sqrt(rows)


def _arr_fix(p, va, arr, fmt, rows):
    """Column-switch settling and the driver's word time, applied to n2's array output."""
    arr = dict(arr)
    if p.get("domain_kind", "charge") != "charge" or "tau_ns" not in arr or p.get("k_dig"):
        return arr
    B = int(p.get("adc_bits", 8))
    exc = _excursion(p, va, rows)
    fins = p.get("share_fins", 8)
    tau_sw = _column_switch_ohm(p, va, exc) / fins * arr["c_col_fF"] * 1e-6       # ns
    n_tau = (B + 1) * math.log(2)                                                  # settle to 1/2 LSB (critic)
    fo4 = k.get("fo4_delay_ps", va) * 1e-3
    if p.get("timing") == "rc":       # n2's own law with N9's switch R (n_phase phases, n2 corner margin)
        slot = p["n_phase"] * n_tau * (tau_sw + arr["tau_ns"]["wire"]) * p.get("corner_margin", 1.0) + 4 * fo4
    else:                             # n2's ported sky130 slot, settle-limited by the real switch
        slot = max(61.0 * k.get("fo4_delay_ps", va) / k.get("sky130_fo4_delay_ps"), n_tau * tau_sw)
    d, kb, planes, stages = _driver(p, fmt)
    ratio = slot / max(arr["slot_ns"], 1e-12)
    if d == "inv_bitserial":
        t_word = arr["t_word_ns"] * ratio
    elif d == "pwm":                  # area-preserving RC: one edge pedestal + 2^b quanta of edge timing
        c_row = arr["c_row_fF"]
        t_q = 4 * k.get("fo4_delay_ps_lib") * k.get("fo4_delay_ps", va) / k.get("fo4_delay_ps") * 1e-3
        t_word = 2.3 * _ron_vgs("rvt", va) / 16 * c_row * 1e-6 + 2 ** int(fmt["abits"]) * t_q + slot
    else:                             # one buffered level per plane; an 8-b level needs a longer row settle
        t_word = planes * slot * (1.5 if kb > 4 else 1.0) * (1.33 if d == "sf_dac" else 1.0)
    arr.update(slot_ns=slot, t_word_ns=t_word, n9_tau_sw_ns=tau_sw, n9_exc_V=exc)
    return arr


def _row_c_fF(p, arr, cell, phys):
    return phys * cell["c_weight_fF"] + phys * math.sqrt(cell["area_um2_per_weight"]) * k.get("wire_c_fF_per_um")


def _c_dac_fF(p, kb, span):
    """Row C-DAC total cap: 2^k 0.2 fF units, or larger so its kT/C stays 50 dB under the row signal."""
    kT = k.get("kT_300K_J")
    return max(2 ** kb * 0.2, kT / (p.get("x_rms", 0.26) * span) ** 2 * 1e5 * 1e15)


def _db(x):
    return 10 * math.log10(max(x, 1e-30))


def _acc_fix(p, va, geo, arr, adc, fmt, acc):
    """Accuracy terms N9's circuits add (parts_db the n8 gate sees). All derived from measured tables
    plus the projected Avt (asap7_constants avt_mV_um) and A0 spread."""
    acc = dict(acc)
    parts = dict(acc.get("parts_db") or {})
    s2 = acc.get("v_signal_rms_V", 0.0) ** 2
    c_tot = acc.get("c_tot_fF", arr["c_col_fF"]) * 1e-15
    phys = (geo["cols"] + geo["checksum"]) * fmt["slices"]
    n_adc = -(-phys // geo["adc_share"])
    t_hold = -(-phys // n_adc) * adc["t_conv_ns"] * 1e-9                          # worst column waits all rounds
    # 1. hold droop of the off share/reset switch at the hot corner: mean is common mode (x rej_cm),
    #    the Ioff mismatch (lognormal, sigma_Vt / (n Ut)) is differential.
    f, fins = p.get("n9_switch_vt", "rvt"), p.get("share_fins", 8)
    n_dev = 2 if p.get("n9_colsw") == "midrail_tg" else 1
    i_off = n_dev * fins * IOFF85_N[f] * 1e-9
    mean = i_off * t_hold / c_tot
    a_fin = 0.071 * 0.021                                                          # um2 per fin (Weff x L)
    s_vt = k.get("avt_mV_um") * 1e-3 / math.sqrt(fins * a_fin)
    n_ut = 1.2 * 1.380649e-23 * (273.15 + p.get("n9_hot_C", 85.0)) / 1.602e-19
    s_rel = math.sqrt(math.exp((s_vt / n_ut) ** 2) - 1)
    diff = math.sqrt(2) * s_rel * mean
    cm = p.get("rej_cm", 0.03)
    parts["n9_droop"] = _db(s2 / max((diff ** 2 + (cm * mean) ** 2) / 3, 1e-40))
    # 2. row-DAC terms (buffered drivers only): INL residual, C-DAC kT/C, per-row closed-loop gain spread.
    d, kb, planes, stages = _driver(p, fmt)
    if stages:
        span = 2 * p["v_exc_frac"] * va
        x = p.get("x_rms", 0.26)
        if d == "sf_dac":
            inl = 0.01                                              # follower body/gm(V) bow ~1 % (2i3), projected
            g_mm = 0.02                                             # V_GS mismatch / span, projected
        else:
            inl = (_i(_SPAN, INL_RMS_1ST, span * 0.7 / va) if stages == 1 else 0.0) / 100
            g_mm = p.get("n9_a0_sigma", 0.1) / (p.get("n9_beta", 0.5) * 41.0 ** stages)
        kT = k.get("kT_300K_J")
        v_n = math.sqrt(kT / (_c_dac_fF(p, kb, span) * 1e-15))
        parts["n9_drv_inl"] = _db(x ** 2 / max(inl ** 2, 1e-30))
        parts["n9_drv_ktc"] = _db((x * span) ** 2 / v_n ** 2)
        parts["n9_drv_gain_mm"] = _db(1 / max(g_mm ** 2, 1e-30))
    if d == "ml2_rails":              # V/3, 2V/3 rail error after trim (projected 0.1 % FS) is a static level INL
        parts["n9_drv_inl"] = _db(p.get("x_rms", 0.26) ** 2 / p.get("n9_rail_err", 0.001) ** 2)
    if p["v_exc_frac"] > swing_cap(p, va) + 1e-9:
        parts["n9_swing_cap"] = 0.0                                 # beyond the driver's linear span
    total = -_db(sum(10 ** (-v / 10) for v in parts.values()))
    acc.update(parts_db=parts, snr_db=total, n9_droop_uV=mean * 1e6, n9_droop_diff_uV=diff * 1e6)
    return acc


def _feol_slack(p, a_weights, cell):
    """Usable FEOL area under the MOM weight array: footprint - FEOL per weight (critic r2 fix; the old
    1 - feol/beol read n3's stale beol_um2 on the hybrid tile), x n9_under_frac for M0/M1 access + shield."""
    return a_weights * max(0.0, 1 - cell.get("feol_um2", 0) / cell["area_um2_per_weight"]) * p.get("n9_under_frac", 0.5)


def plumb(p, t):
    """Apply N9's energy/area/reference/clock terms to a composed tile dict. Returns a new dict."""
    t = dict(t)
    o, arr, adc, fmt, cell = t["op"], t["arr"], t["adc"], t["fmt"], t["cell"]
    va, vd, cf = o["vdd_analog"], o["vdd"], o["clk_frac"]
    R, phys, n_adc, B = t["rows"], t["phys_cols"], t["n_adc"], int(p.get("adc_bits", 8))
    lib_fJ = k.get("inv_switch_energy_fJ_lib") * (vd / 0.7) ** 2      # one logic-cell toggle, derived
    parts, area, notes = dict(t["e_pass_J_parts"]), dict(t["area_um2_parts"]), {}
    margin, net, gen = CLOCK[p.get("n9_clock", "dll_replica")]
    if not p.get("n9_margin_on"):
        margin = 1.0                  # ARCH_METRIC scores at TT 25 C; margins are a sensitivity (N9.md 4.6)
    slot = arr.get("slot_ns", t["t_word_ns"])
    # 1. row drivers (n2's e_mac already holds delivery + switch gates + row wire per plane)
    bd = arr["breakdown_fJ"]
    planes0 = int(fmt["input_planes"])
    drive_fJ = (bd["switch_gates"] + bd["row_wire"]) * R * phys
    c_row = _row_c_fF(p, arr, cell, phys)
    d, kb, planes, stages = _driver(p, fmt)
    v_exc = arr["v_exc_V"]
    e_drv = static_drv = 0.0
    if d == "inv_bitserial":          # FO4-tapered chain adds 1/(f-1) = 1/3 of the load (logical effort, DD notes)
        e_drv = drive_fJ / 3 + R * planes0 * (k.get("dff_energy_fJ") + k.get("dff_clk_cap_fF") * vd ** 2)
    elif d == "pwm":                  # one full-rail pulse per word: its C_row V^2 is n2's delivery for one plane
        parts["array"] = t["e_pass_J_parts"]["array"] / planes0          # (critic fix: no 2 C V^2 double count)
        e_drv = drive_fJ / 3 / planes0 + R * k.get("dff_energy_fJ") * 2 ** int(fmt["abits"]) / 8   # taper + edge counter
    elif d == "ml2_rails":            # 2-b levels from 4 rails; V/3, 2V/3 from 2 tile-shared class-AB buffers (eta 0.5)
        parts["array"] = t["e_pass_J_parts"]["array"] * planes / planes0   # n2 delivery for these planes is kept
        deliv = bd["delivery"] * R * phys * planes / planes0
        e_drv = drive_fJ / 3 * planes / planes0 + 0.5 * deliv * (1 / 0.5 - 1) + R * planes * 4 * k.get("dff_energy_fJ")
        # Settling bias (critic gap, round 2): the level buffers must settle all R rows (R c_row) to n9_rail_err
        # inside one slot, so gm ~ C ln(1/err) / t_slot; P_q scales from the measured anchors (ML2_ANCHOR).
        buf, a = p.get("n9_ml2_buf", "ssf"), ML2_ANCHOR
        sc = (R * c_row / a["c_fF"]) * (a["t_ns"] / slot) * math.log(1 / p.get("n9_rail_err", 1e-3)) / math.log(1 / a["err"])
        static_drv = a[f"{buf}_W"] * sc * (1 + a["hi_x"][buf])
        area["n9_row_dac"] = R * 2.0 + a[f"{buf}_um2"] * max(sc, 0.25) * (1 + a["hi_x"][buf])
        notes["ml2_pq_mW"] = static_drv * 1e3
    else:                             # per-row C-DAC + class-AB buffer settling (k+1) ln2 tau (5c4, 20x)
        parts["array"] = t["e_pass_J_parts"]["array"] * planes / planes0
        span = 2 * v_exc
        c_dac = _c_dac_fF(p, kb, span)
        gmid = p.get("n9_gmid_inv", 30.0) / (3.0 if d == "sf_dac" else 1.0)          # follower: class A, one device
        e_buf = c_row * va * (kb + 1) * math.log(2) / (p.get("n9_beta", 0.5) * gmid)  # fJ: E = C V (k+1)ln2/(beta gm/ID)
        e_buf *= 2.5 if stages > 1 else 1.0                                           # compensated multistage (projected)
        e_drv = R * planes * (0.5 * c_dac * va ** 2 + e_buf)          # row charge itself = n2 delivery (kept)
        area["n9_row_dac"] = R * (c_dac / k.get("mom_cap_density_fF_per_um2") + 1.0 * max(1, stages))
        t_settle = t["t_word_ns"] / planes * (1 / 3 if kb > 4 else 0.5) * 1e-9
        notes["drv_iq_peak_uA"] = c_row * 1e-15 * (kb + 1) * math.log(2) / (p.get("n9_beta", 0.5) * t_settle) / gmid * 1e6
    # 2. amplifier: owned with N6 (preamp KAPPA_PRE vs KAPPA_SA; integrator int_bits_cap); nothing here.
    t_conv = t["t_conv_ns"]
    # 3. digital periphery: n6 prices its gates at the bare-device inverter energy; CHAR.md says use the cell
    lib_ratio = k.get("inv_switch_energy_fJ_lib") / k.get("inv_switch_energy_fJ")
    dig = t["e_pass_J_parts"]["digital_recombination"] * lib_ratio
    dig += phys * p.get("n9_cal_gates", 80) * 0.5 * lib_fJ * 1e-15                # per-column gain/offset correction
    parts["digital_recombination"] = dig
    # 4. reference. c_inj = the SAR's DAC charge per conversion / V (n6 breakdown), per ADC.
    ref, e_ref, static_W = p.get("n9_ref", "reservoir"), 0.0, 0.0
    c_inj = 2 * adc.get("breakdown_fJ", {}).get("dac", 0.5 * 2 ** B * 0.5 * va ** 2) / va ** 2   # fF
    rho_mos = 20.0                                                                 # fF/um2 (n6 RHO_MOS, derived)
    if ref == "ratiometric":          # decap-only: code-dependent bounce < 1/2 LSB needs 2^(B+1) C_dac (critic rule)
        area["n9_ref_decap"] = n_adc * 2 ** (B + 1) * c_inj / rho_mos
    elif ref == "reservoir":          # per-ADC reservoir ~32 C_dac, deterministic droop removed by redundancy + cal
        area["n9_ref_decap"] = n_adc * p.get("n9_reservoir_x", 32.0) * c_inj / rho_mos
        e_ref = n_adc * c_inj * va ** 2 / p.get("n9_reservoir_x", 32.0)            # refill loss ~ Q^2/(2 C_res) x2
    elif ref == "buffered":           # class-A buffer, efficiency eta, I_q slews the column step in slot/4 (20x)
        deliv = bd["delivery"] * R * phys + n_adc * c_inj * va ** 2
        e_ref = (1 / p["n9_ref_eta"] - 1) * deliv
        i_q = arr["c_col_fF"] * 1e-15 * v_exc / (0.25 * slot * 1e-9)
        static_W = i_q * va
        area["n9_ref_buffer"] = 20.0 + n_adc * 4 * c_inj / rho_mos
    elif ref == "bandgap_ldo":        # LDO on the analog rail: (1/eta - 1) of array + converters; BGR unverifiable
        e_ref = (1 / p["n9_ldo_eta"] - 1) * (parts["array"] + parts["converters"]) * 1e15
        area["n9_ref_decap"] = n_adc * 4 * c_inj / rho_mos
        notes["unverifiable"] = "ASAP7 has no BJT/R models (CHAR.md); bandgap cannot be signed off"
    parts["n9_reference"] = e_ref * 1e-15
    # 5. column share/reset switch gates (not priced by n2): fins Cgg V^2 per event, n_phase events per plane;
    #    TG doubles it; a bootstrap pumps ~3x the gate charge through its boost cap (Abo-Gray, projected) and
    #    adds a boost cap of 5x the gate load plus ~5 small devices per column (11c2, 18k).
    planes_clk = planes0 if d == "inv_bitserial" else planes
    sw = p.get("n9_colsw", "ground_nmos")
    fins, cgg = p.get("share_fins", 8), k.get("nfet_cgg_per_fin_aF") * 1e-3            # fF/fin
    events = planes_clk * (p.get("n_phase", 1) if p.get("timing") == "rc" else 1)
    mult = dict(midrail_tg=2.0, bootstrap=3.0).get(sw, 1.0)
    parts["n9_colsw"] = events * phys * mult * fins * cgg * va ** 2 * 1e-15
    if sw == "bootstrap":
        area["n9_bootstrap"] = phys * (5 * fins * cgg / rho_mos + 0.3)
    # 6. clock
    sinks = R * planes_clk + 32 * planes_clk + (n_adc * -(-phys // n_adc) * (B + 2) * 2 * B
                                                if p.get("n9_clock") == "sync_tree" else 0)
    e_clk = sinks * k.get("dff_clk_cap_fF") * vd ** 2 * net + gen * lib_fJ / k.get("inv_switch_energy_fJ_lib") * planes_clk
    parts["n9_drivers"] = e_drv * 1e-15
    parts["n9_clock"] = e_clk * 1e-15
    # 7. SAR loop Vt flavours (round 2): rescale n6's FO4-counted loop by measured ratios (_sar_vt)
    t_conv, static_W = _sar_vt(p, t, adc, parts, va, t_conv, static_W, notes)
    t_pass_ns = (max(t["t_word_ns"], t_conv) if t["rail"]["pingpong"] else t["t_word_ns"] + t_conv) * margin
    # 7b. row broadcast line (critic r2). The per-plate drivers move the row RC onto a digital line of phys
    #     cells: C = wire + 2 fins per input, R = wire. Repeated at the optimum (n = sqrt(Elmore / t_rep),
    #     t_rep = 3 FO4 at the logic VDD), the sample clock forwarded along the same line (source-synchronous),
    #     so the line costs latency, not slot time. Repeaters (INVx4, 0.087 um2) on data + forwarded clock.
    cell = t["cell"]
    pitch = math.sqrt(cell["area_um2_per_weight"])
    L = phys * pitch
    c_line = L * k.get("wire_c_fF_per_um") + phys * 2 * k.get("nfet_cgg_per_fin_aF") * 1e-3       # fF
    elm = 0.5 * k.get("wire_r_ohm_per_um") * L * c_line * 1e-6                                   # ns
    t_rep = 3 * k.get("fo4_delay_ps_lib") * k.get("fo4_delay_ps", vd) / k.get("fo4_delay_ps") * 1e-3   # liberty FO4
    n_rep = max(1, round(math.sqrt(elm / t_rep)))
    notes.update(row_line_elmore_ns=elm, row_line_repeated_ns=2 * math.sqrt(elm * t_rep), row_line_rep=n_rep)
    if d in PLATE_DEV:
        parts["n9_drivers"] += 2 * R * planes_clk * n_rep * 8 * cgg * vd ** 2 * 1e-15           # data + clock repeaters
        area["n9_row_rep"] = 2 * R * n_rep * 0.087
        # per-plate drive devices: FEOL, so they take the FEOL slack under the MOM caps first
        n_t, a_dev = PLATE_DEV[d]
        dev_um2 = R * phys * a_dev
        slack = _feol_slack(p, area["weights"], cell)
        area["n9_plate_dev"] = max(0.0, dev_um2 - slack)
        slack_left = max(0.0, slack - dev_um2)
        if stages == 0:
            notes["pdn_r_req_ohm"] = slot * 1e-9 / (R * c_row * 1e-15 * math.log(1 / p.get("n9_rail_err", 1e-3)))
    else:
        n_t, slack_left = 0, _feol_slack(p, area["weights"], cell)
    n_w = area["weights"] / cell["area_um2_per_weight"]
    notes["transistors_tile"] = dict(weights=round(n_w * cell.get("transistors_per_weight", 0)), plate_drive=R * phys * n_t,
                                     adc=n_adc * SAR_T_PER_ADC, repeaters=4 * R * n_rep)
    # 8. MOS decaps (reference reservoir, bootstrap boost caps) in the FEOL slack under the MOM weight array.
    #    Critic r2 fix: the slack is footprint - FEOL (area_um2_per_weight - feol_um2), not 1 - feol/beol: on the
    #    hybrid tile n2 keeps a stale whole-weight beol_um2 while the footprint is FEOL-set (slack 0).
    if p.get("n9_decap_under"):
        slack = slack_left
        movable = {n: v for n, v in (("n9_ref_buffer", area.get("n9_ref_buffer", 0) - 20.0),
                                     ("n9_ref_decap", area.get("n9_ref_decap", 0)),
                                     ("n9_bootstrap", area.get("n9_bootstrap", 0) - 0.3 * phys)) if v > 0}
        moved = min(slack, sum(movable.values()))
        if moved > 0:
            area["n9_under_array"] = -moved
            notes["under_array_um2"] = moved
    if d == "pwm":
        notes["pwm"] = NOTES["drv_pwm"]
    t.update(e_pass_J_parts=parts, e_pass_J=sum(parts.values()), area_um2_parts=area,
             area_um2=sum(area.values()), t_pass_s=t_pass_ns * 1e-9, t_conv_ns=t_conv,
             t_load_s=t["t_load_s"] * margin, leak_W=t["leak_W"] + static_W + static_drv,
             n9=dict(notes, slot_ns=slot, margin=margin, c_row_fF=c_row, c_inj_fF=c_inj))
    if "t_stage_s" in t:
        t["t_stage_s"] *= margin
    return t


def _sar_vt(p, t, adc, parts, va, t_conv, static_W, notes):
    """Quiet-class (n9_sar_vt_q) and logic/cheap-class (n9_sar_vt_l) Vt flavours of the SAR loop.
    n6's sar_direct loop is t = (10 q + AZ 10) FO4_q + (6 (nd - q) + ISO 2 nd + 10) FO4 + t_pool (+ fine);
    the quiet class scales by the measured comparator t_dec ratio, the rest by the measured FO4 ratio
    (the measured cheap-comparator ratio is faster still: conservative). Quiet decisions cost kappa x at
    fixed noise (CMP_KAPPA_X, derived); the other converter energy scales as the cell energy E_FJ.
    Leakage: the flavour's Ioff on SAR_FINS_PER_ADC per ADC (delta over RVT, TT 27 C)."""
    fq, fl = p.get("n9_sar_vt_q", "rvt"), p.get("n9_sar_vt_l", "rvt")
    if fq == fl == "rvt" or "decisions" not in adc:
        return t_conv, static_W
    q, nd = adc["decisions"]["quiet"], adc["decisions"]["total"]
    fo4 = k.get("fo4_delay_ps", va) * 1e-3
    tq, tl = (10 * q + 10) * fo4, (8 * nd - 6 * q + 10) * fo4
    c1 = adc["t_conv_ns"]
    if tq + tl > c1:                                   # n6 changed its loop law: scale the whole loop, logic ratio
        tq, tl = 0.0, c1
    rq, rl = CMP_TDEC_PS[fq] / CMP_TDEC_PS["rvt"], FO4_PS[fl][-1] / FO4_PS["rvt"][-1]
    ratio = (tq * rq + tl * rl + (c1 - tq - tl)) / c1
    bd = adc.get("breakdown_fJ") or {}
    d = bd.get("decisions", 0.0) / max(sum(bd.values()), 1e-30)
    el = E_FJ[fl][-1] / E_FJ["rvt"][-1]
    parts["converters"] *= 1 + d * (CMP_KAPPA_X[fq] - 1) + (1 - d) * (el - 1)
    n_adc = t["n_adc"]
    dleak = sum(va * (IOFF_N[f][-1] + IOFF_P[f][-1] - IOFF_N["rvt"][-1] - IOFF_P["rvt"][-1]) / 2 * 1e-9 * fr
                for f, fr in ((fq, 0.2), (fl, 0.8)))     # 20 % of the fins are the quiet class (projected)
    notes.update(sar_ratio=ratio, sar_leak_uW=n_adc * SAR_FINS_PER_ADC * dleak * 1e6)
    return t_conv * ratio, static_W + n_adc * SAR_FINS_PER_ADC * dleak


ANALOG_FNS = {("n2_domain", "array"), ("n3_cell", "cell"), ("n6_readout", "adc"), ("n5_array", "accuracy")}


def evaluate_full(design, knobs=None):
    """model.evaluate with N9's hooks (module docstring) and the analog nodes on analog_vdd()."""
    from arch_eval import model
    orig = model.tile

    def tile(ctx, vdd, clk_frac):
        if not getattr(ctx, "_n9", False):
            call = ctx.call

            def routed(nid, fn, *a):
                if (nid, fn) in ANALOG_FNS:
                    a = (analog_vdd(ctx.p, a[0]),) + a[1:]
                out = call(nid, fn, *a)
                if "n9_amp" not in ctx.p:
                    return out
                if (nid, fn) == ("n2_domain", "array"):
                    va, fmt, cell, rows = a
                    geo = call("n5_array", "geometry")
                    phys = (geo["cols"] + geo["checksum"]) * fmt["slices"]
                    out = _arr_fix(ctx.p, va, dict(out, c_row_fF=_row_c_fF(ctx.p, out, cell, phys)), fmt, rows)
                elif (nid, fn) == ("n5_array", "accuracy"):
                    out = _acc_fix(ctx.p, *a, out)
                return out
            ctx.call, ctx._n9 = routed, True
        t = orig(ctx, vdd, clk_frac)
        return plumb(ctx.p, t) if "n9_amp" in ctx.p else t

    model.tile = tile
    try:
        return model.evaluate(design, knobs)
    finally:
        model.tile = orig


# ── scoring harness: every option, best over a small grid of the other nodes ─────────────────────
# Base = the best feasible composed design on the live tree (2026-10-05 ~21:40), pinned node by node
# because the other nodes' DEFAULTs move: n8.best("bundle_lead") with n3 = gaincell_mom_caps_mom6
# (the strict g43_lossless gate and the live n3 default gaincell_mos_caps have no feasible design:
# max SNR 30.3 dB against 37.0). n2 charge_rail (rail bottom plates, RC slot) and n5 blk_diff_lead /
# n6 sar_vtc_fine are the live leads; n4 w8a8_2slice is radix (N9 owns the driver; N4's
# w8a8_lead_amp = this base + drv_row_dac). Re-derive when the other nodes move.
BASE = dict(nodes=dict(n1_system="stream_single", n2_domain="charge_rail", n3_cell="gaincell_mom_caps_mom6",
                       n4_formats="w8a8_2slice", n5_array="blk_diff_lead", n6_readout="sar_vtc_fine",
                       n7_dataflow="lean_int8_rail", n8_quality="bundle_lead", n10_wildcards="none"),
            params=dict(kv_bits=8, k_sigma=16.0, cu_fF=1.0, adc_bits=13))
FRACS = (0.18, 0.25, 0.35, 0.43, 0.5)
GRID = [dict(nodes=dict(BASE["nodes"], n1_system=m), params=dict(BASE["params"], adc_bits=b, cu_fF=c, share_fins=sf))
        for m in ("stream_single", "streaming", "resident") for b in (12, 13, 14) for c in (1.0, 2.0, 4.0)
        for sf in (8, 32)]


def best(option, conditions="arch", extra_nodes=None, grid=None):
    from arch_eval import design, metric
    knobs = metric.knobs_for(conditions)
    prm = OPTIONS[option]["params"]
    cap = swing_cap(prm, prm.get("n9_vdd_analog", 0.7))
    fracs = [f for f in FRACS if f <= cap + 1e-9] or [round(cap, 3)]
    top = None
    for g in grid or GRID:
        for fr in fracs:
            nodes = dict(g["nodes"], n9_circuits=option, **(extra_nodes or {}))
            if prm.get("n9_ota"):
                nodes["n6_readout"] = "integrator_coarse_sar"
            s = evaluate_full(design.make(nodes, dict(g["params"], v_exc_frac=fr), name=option), knobs)
            s["grid"] = dict(g, frac=fr)
            if top is None or metric.better(s, top):
                top = s
    return top


def characterize(out_json):
    """Re-run this node's ESPice measurements (TG, FO4/E per flavour, Ioff vs VDS, inverter preamp).
    Run inside the mixed nix shell, PDK=asap7, under the machine-wide SPICE flock (CHAR.md)."""
    import json
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[5] / "analog/docs/asap7"))
    import char as C  # noqa: E402
    lib = lambda c="tt", T=27: "\n".join(C.P.model_lines(c)) + f"\n.temp {T}\n"   # noqa: E731 (char.lib is shadowed)
    C.lib = lib
    res = dict(tg={}, fo4={}, ioff={}, preamp={}, ron_vgs={}, ioff85={}, inl={}, fo4_corner={})
    for fl in ("rvt", "lvt", "slvt"):
        for v in _V5:
            vin = np.linspace(0, v, 13)
            d = lib() + f"vx x 0 0\nvdd vdd 0 {v}\n" + "".join(
                f"vs{i} s{i} 0 {x}\nvd{i} d{i} 0 {x + 0.005}\nMn{i} d{i} vdd s{i} 0 nmos_{fl} L=21n NFIN=1\n"
                f"Mp{i} d{i} 0 s{i} vdd pmos_{fl} L=21n NFIN=1\n" for i, x in enumerate(vin))
            r = C._espice(d + ".dc vx 0 0 1\n")
            res["tg"][f"{fl}@{v}"] = max(0.005 / abs(r[f"i(vd{i})"][0]) for i in range(len(vin)))
        for v in _V4:
            res["fo4"][f"{fl}@{v}"] = C.inv_fo4(v, "tt", fl)
        d = lib() + "vx x 0 0\n" + "".join(f"vd{j} d{j} 0 {v}\nM{j} d{j} 0 0 0 nmos_{fl} L=21n NFIN=1\n"
                                           f"vp{j} p{j} 0 {-v}\nMp{j} p{j} 0 0 0 pmos_{fl} L=21n NFIN=1\n"
                                           for j, v in enumerate(_V4))
        r = C._espice(d + ".dc vx 0 0 1\n")
        res["ioff"][fl] = {v: (abs(r[f"i(vd{j})"][0]) * 1e9, abs(r[f"i(vp{j})"][0]) * 1e9) for j, v in enumerate(_V4)}
    for v in _V3:
        d = lib() + f"vdd vdd 0 {v}\nvin in 0 {v / 2}\nMp y in vdd vdd pmos_rvt L=21n NFIN=2\nMn y in 0 0 nmos_rvt L=21n NFIN=2\n"
        r = C._espice(d + f".dc vin 0 {v} 0.0005\n")
        vi, vo = np.asarray(r["v(in)"]), np.asarray(r["v(y)"])
        g = -np.gradient(vo, vi)
        i0 = int(np.argmax(g))
        ok = np.where(g >= 0.7 * g[i0])[0]
        res["preamp"][v] = dict(gain=float(g[i0]), span_V=float(abs(vo[ok[0]] - vo[ok[-1]])))
    # critic pass: NMOS Ron vs VGS (VG 0.7, VS swept; bootstrapped VG = VS + 0.7 gives the 0.7 entry), Ioff 85 C
    for fl in ("rvt", "lvt", "slvt"):
        d = lib() + "vx x 0 0\n" + "".join(f"vg{j} g{j} 0 0.7\nvs{j} s{j} 0 {0.7 - g:.3f}\nvd{j} d{j} 0 {0.705 - g:.3f}\n"
                                         f"M{j} d{j} g{j} s{j} 0 nmos_{fl} L=21n NFIN=1\n" for j, g in enumerate(_VGS))
        r = C._espice(d + ".dc vx 0 0 1\n")
        res["ron_vgs"][fl] = [0.005 / abs(r[f"i(vd{j})"][0]) for j in range(len(_VGS))]
        r = C._espice(lib(T=85) + f"vx x 0 0\nvd d 0 0.35\nM1 d 0 0 0 nmos_{fl} L=21n NFIN=1\n.dc vx 0 0 1\n")
        res["ioff85"][fl] = abs(r["i(vd)"][0]) * 1e9
    # row-DAC buffer static INL: inverting unity gain through 10 Mohm, 1 vs 3 inverters, SS
    for st in (1, 3):
        nodes = ["vm"] + [f"n{i}" for i in range(1, st)] + ["y"]
        d = lib("ss") + "vdd vdd 0 0.7\nvin in 0 0.35\nRi in vm 10meg\nRf y vm 10meg\n" + "".join(
            f"Mp{i} {nodes[i + 1]} {nodes[i]} vdd vdd pmos_rvt L=21n NFIN=2\nMn{i} {nodes[i + 1]} {nodes[i]} 0 0 nmos_rvt L=21n NFIN=2\n"
            for i in range(st))
        r = C._espice(d + ".dc vin 0 0.7 0.001\n")
        vi, vo = np.asarray(r["v(in)"]), np.asarray(r["v(y)"])
        mid = vo[np.argmin(abs(vi - 0.35))]
        res["inl"][st] = {}
        for span in _SPAN:
            ok = (vo > mid - span / 2) & (vo < mid + span / 2)
            err = vo[ok] - np.polyval(np.polyfit(vi[ok], vo[ok], 1), vi[ok])
            res["inl"][st][span] = (100 * float(np.max(abs(err))) / span, 100 * float(np.std(err)) / span)
    for c, v, T in (("tt", 0.7, 27), ("ss", 0.63, 100)):     # sign-off FO4 ratio (C.inv_fo4 reads C.lib)
        C.lib = lambda corner="tt", T=T: lib(corner, T)
        res["fo4_corner"][f"{c}_{v}_{T}"] = C.inv_fo4(v, c, "rvt")["fo4_ps"]
    Path(out_json).write_text(json.dumps(res, indent=1, default=str))
    return res


def _selfcheck():
    o = op(LEAD, 0.7)
    assert abs(o["e_scale"] - 1) < 1e-9 and abs(o["delay_scale"] - 1) < 1e-9 and abs(o["leak_scale"] - 1) < 1e-9
    lo = op(LEAD, 0.45)
    assert 0.3 < lo["e_scale"] < 0.45 and 2.4 < lo["delay_scale"] < 2.8 and 0.3 < lo["leak_scale"] < 0.6
    s = op(dict(LEAD, n9_logic_vt="slvt"), 0.7)
    assert s["leak_scale"] > 50 and s["delay_scale"] < 0.8
    assert _column_switch_ohm(dict(LEAD, n9_colsw="midrail_tg"), 0.45, 0.0) > 10 * _column_switch_ohm(dict(LEAD, n9_colsw="ground_nmos"), 0.45, 0.0)
    assert abs(_column_switch_ohm(dict(LEAD, n9_colsw="midrail_nmos"), 0.7, 0.0) - 29848) < 1   # = CHAR.md 31 k
    assert abs(_column_switch_ohm(dict(LEAD, n9_colsw="bootstrap"), 0.7, 0.2) - 5932) < 1      # flat in VS
    assert swing_cap(LEAD) == 0.5 and swing_cap(dict(LEAD, n9_driver="inv_bitserial")) == 0.5 and 0.26 < swing_cap(dict(LEAD, n9_driver="row_dac")) < 0.29
    assert swing_cap(dict(LEAD, n9_driver="nibble_dac")) > 0.42 and swing_cap(dict(LEAD, n9_driver="row_dac_ms")) > 0.42
    t0 = dict(n_adc=128)
    adc0 = dict(t_conv_ns=1.576, decisions=dict(quiet=5, total=13), breakdown_fJ=dict(decisions=842.0, dac=55.0))
    assert _sar_vt(LEAD, t0, adc0, dict(converters=1.0), 0.7, 6.3, 0.0, {}) == (6.3, 0.0)        # RVT = n6 as is
    pr, nt = dict(converters=1.0), {}
    tc, st = _sar_vt(dict(LEAD, n9_sar_vt_l="slvt"), t0, adc0, pr, 0.7, 6.3, 0.0, nt)
    assert 0.8 < nt["sar_ratio"] < 0.9 and 1.0 < pr["converters"] < 1.1 and st > 0       # dual-Vt: faster, ~E, leaks
    hyb = dict(area_um2_per_weight=3.023, feol_um2=3.023, beol_um2=5.856)       # FEOL-set footprint: no slack
    assert _feol_slack(LEAD, 9508.0, hyb) == 0 and abs(_feol_slack(LEAD, 9320.0, dict(area_um2_per_weight=2.928, feol_um2=2.274)) - 1040) < 5
    print("PASS n9_circuits self-check (op identity at VDD_nom; SLVT leak > 50x; RVT TG > 10x at 0.45 V; "
          "Ron(VGS) tables; driver swing caps from measured INL; r2 dual-Vt SAR loop)")


def baseline(conditions="arch", margin=1.0):
    """Systolic baseline (baseline_systolic.py, its ppa.json PE) with every cycle stretched by `margin`."""
    from arch_eval import baseline_systolic as bs, metric
    orig = bs.ppa
    pe, src = orig()
    bs.ppa = lambda: (dict(pe, fmax_GHz=pe["fmax_GHz"] / margin), src)
    try:
        wb = metric.SOHU_WBITS if conditions == "sohu" else 4
        return bs.evaluate(wb, metric.knobs_for(conditions))
    finally:
        bs.ppa = orig


def _row(name, s):
    return (f"{name:<26} tok/s/die {s['tok_s_die']:>9.5g} TOPS/W {s['tops_w']:>7.3g} tok/W {s['tok_w']:>7.4g} "
            f"tok/J {s['tok_j']:>7.4g}")


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    if "--char" in sys.argv:
        print(characterize(sys.argv[-1]))
        sys.exit()
    _selfcheck()
    if "--score" in sys.argv:
        cond = "sohu" if "--sohu" in sys.argv else "arch"
        from arch_eval import design, metric, model
        kn = metric.knobs_for(cond)
        b0 = evaluate_full(design.make(dict(BASE["nodes"], n9_circuits="lead"), BASE["params"]), kn)
        assert b0["tok_s_die"] > 0, f"BASE is infeasible on this tree: re-derive it ({b0['binding']})"
        names = [a for a in sys.argv[1:] if a in OPTIONS] or list(OPTIONS)
        out = {}
        for name in names:
            s = best(name, cond)
            g = s["grid"]
            c = model.evaluate(design.make(dict(g["nodes"], n9_circuits=name), dict(g["params"], v_exc_frac=g["frac"])), kn)
            pk, t = s.get("peak") or {}, s.get("tile") or {}
            q = t.get("quality") or {}
            print(_row(name, s) + f" | {g['nodes']['n1_system'][:8]} b{g['params']['adc_bits']} cu{g['params']['cu_fF']} "
                  f"sf{g['params']['share_fins']} fr{g['frac']} V{pk.get('vdd')} word {t.get('t_word_ns', 0):.3g} "
                  f"conv {t.get('t_conv_ns', 0):.3g} ns m{q.get('margin_db', float('nan')):.2f}dB "
                  f"bind {s['binding'] if isinstance(s['binding'], str) else s['binding'].get('prefill')}/"
                  f"{'' if isinstance(s['binding'], str) else s['binding'].get('decode')} | core@pt "
                  f"{c['tok_s_die']:.5g}/{c['tops_w']:.3g}/{c['tok_j']:.4g}", flush=True)
            out[name] = dict({m: s[m] for m in metric.METRICS}, grid=g, core={m: c[m] for m in metric.METRICS},
                             t_word_ns=t.get("t_word_ns"), t_conv_ns=t.get("t_conv_ns"), margin_db=q.get("margin_db"),
                             parts=t.get("snr_parts_db"), n9=t.get("n9"), binding=s["binding"],
                             e_parts={n: v / max(1, t.get("macs_per_pass", 1)) * 1e15
                                      for n, v in (t.get("e_pass_J_parts") or {}).items()},
                             area_parts=t.get("area_um2_parts"))
        for m in (1.0, 1.06, DIG_SIGNOFF):
            out[f"baseline_m{m:.3g}"] = {x: v for x, v in baseline(cond, m).items() if x in metric.METRICS}
            print(_row(f"baseline margin {m:.3g}", out[f"baseline_m{m:.3g}"]))
        if "--json" in sys.argv:
            Path(sys.argv[sys.argv.index("--json") + 1]).write_text(json.dumps(out, indent=1, default=str))
