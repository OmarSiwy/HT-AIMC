"""N2 compute domain at ASAP7: charge, current, time, log (translinear), hybrid (+ digital reference).

Write-up and scored table: docs/src/content/Project/ArchResearch/nodes/N2.md.
`python3 n2_domain.py` (numpy shell) self-checks, then scores every option (best reachable
design per option) on the frozen reference stack. Flags: --hi (adds the 43 dB gate), --sohu
(Sohu conditions, W8), --live (live node set), option names to restrict.

What array() returns (README contract + what the live consumers read):
  e_mac_fJ   per crosspoint (row x physical column) per input word, one weight slice
  t_word_ns  one input word through the array (planes x slot, or one window)
  slot_ns    one plane (live n5 settling / row-RC terms read it)
  v_exc_V    charge kinds: the physical bottom-plate excitation; other kinds: the equivalent
             excitation (refit by score() so n5's signal equals the domain's sig_V)
  c_col_fF   physical capacitance on the summing node: R C_w (charge), C_int (current/log),
             a nominal sampling cap (time/digital); live n5 uses it for pitch and attenuation
  breakdown_fJ always carries delivery/switch_gates/row_wire (n9.plumb reads them)
  domain_parts_db  non-charge kinds: the domain's own error terms (dB, vs signal). n5's
             accuracy law is a passive charge share; for these kinds score() keeps only n5's
             adc/clip terms and uses these instead (open question: n5 should do it itself).
  extra_parts_db   charge kinds with extra error terms (OTA, analog weight): added to n5's.
  adc_credit_db    bit-slice: per-column ADC ranges recombined (added to n5's adc term).
  Contract gaps (ponytail: in-place, the contract has no channel; upgrade = core reads arr[...]):
  - non-cap domains write their own area/leak/write into `cell` (model.tile reads it after n2);
  - single-slice W8 C-2C sets fmt["slices"] = 1;
  - a domain with its own readout (CCO, digital) puts p["_adc_override"]; the scorer's n6
    wrapper returns it instead of the stack's SAR.

Storage: every option except the sky130 anchor `charge` is scored with the live N3 gain-cell bits
(gaincell_mom_caps), never 6T SRAM (ARCH_METRIC constraint 2).

Labels: every number is PROJECTED (laws on measured ASAP7 Ron/Cgg/FO4/gm-Id/Ioff and the
measured sky130 macro, plus literature constants). No ASAP7 SPICE of a compute column yet.
Round 2 (A2, ArchResearch/nodes/N2_r2.md): charge_rail_meas3 / charge_rail_bps2 time each plane with explicit
phases on MEASURED ASAP7 ESPice settling (column switch, row segment, V/3 rail) and price the row drivers.
Round 2b (critic): bps2 uses the measured two-pole cascade (casc_ns); grid-driven rows carry a popcount droop
term (supply_droop -> n5 eps_ref); charge_rail_bps2_cc / const_charge adds constant-charge row coding; delivery
is C_on V^2 per plane; driver area counts physical columns.

Notes (vault, Analog Compute): 27a1 KCL MAC; 27f9 tau ~ N without cell conductance; 27g1
SNR_T <= SNR_a; 27g2 kT/C; 27g4 E ~ SNR, E ~ (gm/ID)^2 A_VT^2 SNR / L; 27h1 ADC (VDD/Vc)^2 4^B;
27h7 TIA bias / integrator time / CCO linearity; 27h9 PWM 2^b t_q; 27i1 ratio linearity; 27i2
digital CIM; 27i3 T* = aCV/I; 27i4 C-2C; 27i5 PVT; 27i6 gain cell; 27k6 closed-loop programming;
27n1 bit-normalized TOPS/W. Slices: 15h1 IR law gm r N^2/2 (AD-ProcessLayouta-1), 1f
exp(dVt/nUT) (AD-MOSDevicePhysi-1), (B+1) ln2 settling (AD-FrequencyRespo-1), OTA settle energy
(AD-gmIDSizingMeth-1).
"""
import math

if __name__ == "__main__":     # script run: make `arch_eval` importable
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from arch_eval import asap7 as k  # noqa: E402

# ASAP7 geometry (Clark 2016, mej_paper_asap7.pdf Table 1): fin H 32 nm, T 6.5 nm, pitch 27, CPP 54
FIN_W_UM = 2 * 0.032 + 0.0065
FIN_PITCH_UM, CPP_UM, L_UM = 0.027, 0.054, 0.021
FA_UM2, NAND_UM2 = 0.20412, 0.05832   # FAx1 / NAND2xp33 (asap7sc7p5t RVT liberty, derived)
MOS_FF_PER_UM2 = 69.68e-3 / (FIN_PITCH_UM * CPP_UM * 2.0)   # SLVT gate cap, ov 2 (live n3 table; derived)
ANCHOR = dict(e_fJ=4.4998, cu_fF=4.0, vdd=1.8, planes=6, slot_ns=61.0)   # measured sky130 macro
GAIN_STORE = "gaincell_mom_caps"       # live N3 storage used by every non-anchor option
# Round 2 (A2) measured ASAP7 ESPice, TT 27 C, no layout parasitics (scratchpad a2/sp1.py, N2_r2.md):
R_COL_FIN = 6886.0    # ohm x fin: bootstrapped NMOS reset/share switch into 56 fF incl. its own caps (tau 24.1 ps @16 f)
R_RAIL_FIN = 8900.0   # ohm x fin: NMOS or TG from the V/3 rail into a 32-col row segment (tau 279 ps @8 f, 87 @32 f)
# RVT inverter 0 -> 0.7 V (rising, PMOS-limited) into the same segment. Critic r2: 15,700 was a single-pole fit at 8/32
# fins (493 / 133 ps); at the 96-192 fins actually used the 2^-8 settle of the far plate fits 8,100 (ESPice a2r/sp4.py:
# 232 ps @96 f, 200 ps @128 f with the n5 strap/2 term). The cascade law below is checked against the top plate.
R_INV_FIN = 8100.0
# Critic r2 cascade (ESPice a2r/sp4.py, sp6.py): the top plate held by the column switch settles through BOTH poles,
# slower than max(n_c tc, n_r tr). Law: casc(tr, tc) with a real bootstrap (boost cap 5x the gate load: VGS ~0.58 V,
# Ron x KB_BOOT) and a fixed column-loop floor TAU_COL0 (crosspoint TG, 2 fins into a 4 fF MSB group per row, and the
# switch's own caps). Fitted on the seven measured TG + VGS 0.58 points (row_seg 8-32, rf 32-192, sf 16-24): the law
# is 0.6-8.8 % slower than measured (never faster).
KB_BOOT, TAU_COL0_NS = 1.1, 0.013
# Critic r2 row reference: in bit-serial drive the row level V IS the multiply reference, and it comes from the local
# VDD/GND grid. One row switching draws c_row V from the tile decap; the droop depends on the plane's popcount and is
# common to every column (no differential cancel, no post-merge trim). DECAP_FRAC = share of the array footprint
# usable as MOS decap: 1.0 is the upper bound (the gain cells and n9's under-array parts also want that FEOL), so
# the term is optimistic. Constant-charge coding (const_charge: a dummy cap of the row's charge switched when
# x_b = 0) makes the per-plane supply charge data-independent; CC_MISMATCH = dummy vs row charge residual after a
# one-time trim, MOS vs MOM tracking over PVT (projected).
DECAP_FRAC, CC_MISMATCH = 1.0, 0.03
# Tile-shared V/3 rail settling floor for a row phase (|error| <= 0.7 mV with all 8 rows switching on): 1.0 ns,
# the A5 measured class-AB super source follower (n9 ML2_ANCHOR, 0.136 mV over 1.0-1.5 ns, 2.8 mW; n9 prices its
# power). Cross-check here (ESPice E3, a2/sp3.py): a class-A NMOS follower needs 0.8 ns at 32 mA, > 1.5 ns at 8 mA.
RAIL_FLOOR_NS = 1.0
MEAS_TIMING = ("meas3", "bps2")
STATIC = ("mismatch", "store_ktc", "dac_inl", "cal_residual", "pvt", "pwm_edge", "droop", "trim")


def _int_stats(sigma=7 / 3, mag=3):
    """Discrete half-normal magnitude m = min(2^mag-1, round(|N(0, sigma)|)) (INT4 weights; derived):
    E m, E m^2, P(bit b = 1) and E (m mod 2^j)^2 for j = 0..mag."""
    top = 2 ** mag - 1
    cdf = lambda x: math.erf(x / (sigma * math.sqrt(2)))          # noqa: E731  P(|z| < x)
    pmf = [cdf(0.5)] + [cdf(v + 0.5) - cdf(v - 0.5) for v in range(1, top)] + [1 - cdf(top - 0.5)]
    em = sum(v * q for v, q in enumerate(pmf))
    em2 = sum(v * v * q for v, q in enumerate(pmf))
    pb = [sum(q for v, q in enumerate(pmf) if v >> b & 1) for b in range(mag)]
    low = [sum((v % 2 ** j) ** 2 * q for v, q in enumerate(pmf)) for j in range(mag + 1)]
    return dict(em=em, em2=em2, pb=pb, em2_low=low)


ST = _int_stats()
EM, EM2 = ST["em"], ST["em2"]          # 1.85 / 5.50


def _c(**kw):
    return dict(dict(domain_kind="charge", v_exc_frac=0.25, timing="port", share_fins=8, wire_x=1, n_phase=3,
                     corner_margin=1.2, settle_tau=8.0, sw_activity=0.5, bitslice=False, packets=False, c2c=False,
                     k_dig=0, k_wbits=0, analog_w=False, e_fa_fJ=0.36), **kw)


_C = _c()
_RAIL = dict(_C, v_exc_frac=0.5, timing="rc")
_CUR = dict(_C, domain_kind="current", gmid_cell=10.0, sigma_u=0.04, tq_ns=0.1, v_out_pk=0.15,
            i_amp_uA=2.0, act_mean=0.25, src_rail_x=8, units=7, clamp="rgc", c_store_fF=1.0,
            clamp_area_um2=10.0, pvt_res=0.006, gamma_n=1.0, edge_frac=0.3, tq_tau_x=3.0, n2_cal=False, n_iter=1,
            sigma_verify=0.003, t_live_us=2.0, droop_res=0.3, cur_readout="cint", cco_tlsb_ps=150.0)


def _o(prov, **kw):
    return dict(params=kw, provenance=prov)


OPTIONS = {
    # ---- charge -------------------------------------------------------------------------------
    "charge": _o("measured sky130 passive macro (IMC_SIZING_RESEARCH.md) ported by CV^2/FO4 laws: V_exc = "
                 "VDD/4, 61 ns/plane x FO4 ratio (the shipped default, kept bit-identical as the anchor; 6T bits)",
                 **_C),
    "charge_rail": _o("projected: passive share with rail-only bottom plates (+-VDD/2: 11c, 18s) and an RC plane "
                      "slot n_phase (B+1) ln2 (tau_switch + tau_wire); share switch = 1n1p TG at its worst-case "
                      "Ron (measured 18.4 kOhm), ORFS wire RC", **_RAIL),
    "charge_bitslice": _o("projected: one unit cap per weight bit (CAP-RAM/PICO-RAM style), analog popcount per "
                          "bit column, x3 conversions; bit columns recombined with 4^b noise weights (derived)",
                          **dict(_RAIL, bitslice=True)),
    "charge_pulse_count": _o("projected: unary charge packets (TSMC 7 nm RWL pulse count, LIT #1); 14.1/2.45 "
                             "transfer ratio measured here (REPO-A unary PWM falsified for energy)",
                             **dict(_RAIL, packets=True)),
    "charge_c2c": _o("projected: C-2C ladder weights (27i4, Intel LIT #4): 3M-1 units, column sees 2 Cu, "
                     "M-1 serial sections in every share; at W8 one 7-b ladder per weight (single slice)",
                     **dict(_RAIL, c2c=True, c2c_single=True)),
    "charge_ota": _o("projected: virtual-ground integrator (gain C_col/C_int), OTA settle energy VDD C_L (B+1) ln2 "
                     "/(beta gm/ID), A0 = measured ASAP7 (gm/gds)_n (gm/gds)_p; falsified on sky130 (F13, F35)",
                     **dict(_RAIL, domain_kind="ota", v_out_pk=0.15, gmid_ota=12.0, k_nl=0.5, c_par_fF=20.0,
                            c_adc_fF=20.0, ota_area_um2=25.0)),
    "charge_analog_weight": _o("projected: weight written as a voltage on a hold cap C_h = M C_u (per-column DAC, "
                               "MOS gate cap), each 1-plane samples it onto C_u and shares onto the column (the "
                               "ARCH_METRIC dataflow sketch); errors: data-dependent droop, write kT/C_h, DAC INL; "
                               "no stored bits, no PWM", **dict(_RAIL, analog_w=True, m_ratio=64.0, dac_inl=0.003)),
    # ---- round 2 (A2): explicit plane phases on measured ASAP7 settling ----------------------
    "charge_rail_meas3": _o("derived (A2, N2_r2.md): the round-1 pick's plane sequence with its phases made explicit: "
                            "reset top || row RTZ, row drive (top floating), share; column tau = measured bootstrapped "
                            "NMOS (ESPice E1), row tau = measured rail switch into a 32-col segment (E2); row-switch "
                            "gates and area priced. row_fins 64 keeps the round-1 1.13 ns slot (8 fins: 3.8 ns)",
                            **dict(_RAIL, timing="meas3", share_fins=16, row_bits=8)),
    "charge_rail_bps2": _o("derived (A2, N2_r2.md): bottom-plate sampling, 2 phases per plane: row drive while the top "
                           "plate is held at V_cm, then top released and row returned to 0 while the column shares "
                           "(SAR-DAC bottom-plate practice: top-plate injection signal-independent); same measured "
                           "taus and pricing as charge_rail_meas3", **dict(_RAIL, timing="bps2", share_fins=16, row_bits=8)),
    "charge_rail_bps2_cc": _o("derived (A2 critic r2, N2_r2.md): charge_rail_bps2 with constant-charge row coding: "
                              "each row has a dummy MOS cap of its own charge, driven when x_b = 0, so the supply "
                              "charge per plane does not depend on the input popcount (the n3 gc_cs constant-sum "
                              "idea on the row). Costs: dummy cap area, a second driver set, row activity 1",
                              **dict(_RAIL, timing="bps2", share_fins=16, row_bits=8, const_charge=True)),
    # ---- current ------------------------------------------------------------------------------
    "current_pwm": _o("projected: gain-cell-gated binary FinFET current units (EKV from measured gm/ID, A_VT 1.3), "
                      "binary-window (PWM) inputs (27h9), regulated-cascode clamp, C_int integration (27h7); "
                      "t_q >= 3 tau_row; PVT = column gain trimmed on the checksum column", **_CUR),
    "current_tia": _o("projected: as current_pwm with a resistive TIA, I_D >= I_col 2^B/(V_read gm/ID) (27h7, F11)",
                      **dict(_CUR, clamp="tia", v_read=0.1, gmid_tia=10.0)),
    "current_gaincell": _o("projected: 2T gain cell, analog weight on the read gate (27i6), no stored bits; one read "
                           "device carries the whole weight's mismatch; analog write = one DAC step per weight",
                           **dict(_CUR, units=1, sigma_u=0.03)),
    "current_gaincell_cal": _o("projected: as current_gaincell with closed-loop program-verify (27k6): read-device "
                               "Vt and beta absorbed into the written gate voltage; residual = write kT/C_s, verify "
                               "step, droop; n_iter x write time/energy", **dict(_CUR, units=1, n2_cal=True, n_iter=6,
                                                                                 n_stack=16, c_store_fF=4.0)),
    "cco_freq_mac": _o("projected: current_pwm columns read by a per-column CCO + counter (HERMES, 27h7) instead of "
                       "C_int + SAR: count window >= 2^B t_LSB (150 ps), +-1 LSB INL after cal (live n6 law)",
                       **dict(_CUR, cur_readout="cco")),
    # ---- log / translinear (ARCH_METRIC leading hypothesis) -----------------------------------
    "log_translinear": _o("projected: subthreshold I = I0 exp((Vw+Vx)/nUT) per crosspoint, KCL sum, PTAT DAC refs; "
                          "per-cell Vt trim (8 b), log weight on C_s (kT/C exponentiated: 1f/1f1), clamped bitline "
                          "(DIBL exponentiates V_BL)",
                          **dict(_C, domain_kind="log", ic_max=0.1, sigma_store=0.03, trim=True, sigma_trim_mV=0.3,
                                 t_win_ns=4.0, v_out_pk=0.15, i_amp_uA=2.0, mean_ratio=0.03,
                                 clamp_area_um2=10.0, pvt_res=0.02, gmid_dac=15.0)),
    # ---- time ---------------------------------------------------------------------------------
    "time_delay": _o("projected: binary-weighted delay units per weight in +/- chains, ring-oscillator TDC built "
                     "from the same cells (ratiometric, DD-AsynchronousSe), NTHU/TSMC TD-CIM LIT #6",
                     **dict(_C, domain_kind="time", sigma_u=0.05, t_u_fo4=1.0, t_mux_fo4=1.0, jitter_frac=0.01,
                            alpha=1.3, pvt_res=0.004, n2_cal=False)),
    "time_delay_cal": _o("projected: as time_delay with a per-unit load trim (cal_bits gain-cell bits per delay "
                         "unit, set once per physical cell, not streamed); residual = trim LSB/sqrt(12)",
                         **dict(_C, domain_kind="time", sigma_u=0.05, t_u_fo4=1.0, t_mux_fo4=1.0, jitter_frac=0.01,
                                alpha=1.3, pvt_res=0.004, n2_cal=True, n_f_cal=1, cal_bits=6)),
    # ---- hybrid -------------------------------------------------------------------------------
    "hybrid_msb_digital": _o("projected: top k input planes through a per-column digital adder tree (exact; "
                             "DD-SumsofWeighted) reading the same gain-cell weight bits, the rest passive charge; "
                             "output-referred analog noise weight (4^(P-k)-1)/(4^P-1) (the gate target is lowered "
                             "by that)", **dict(_RAIL, k_dig=3)),
    "hybrid_wmsb_digital": _o("projected: MSB weight bit(s) through a digital AND + adder tree, the low magnitude bits "
                              "as binary caps; analog noise referred down by E m^2 / E m_low^2", **dict(_RAIL, k_wbits=1)),
    "digital_cim_ref": _o("OUT OF SCOPE reference (27i2): NAND + adder-tree digital CIM, FA/NAND areas from the "
                          "ASAP7 liberty, e_FA 0.36 fJ (5 nm DCIM literature scaled to 0.7 V), liberty INV, no ADC",
                          **dict(_C, domain_kind="digital", t_cyc_fo4=100.0)),
}
DEFAULT = "hybrid_msb_digital"   # lead (N2.md); "charge" stays the bit-identical sky130 anchor
SWEEP = dict(share_fins=[8, 16, 32], wire_x=[1, 2, 4], row_fins=[8, 16, 32, 64, 128], row_bits=[6, 8, 10])

INFEASIBLE = {   # no ASAP7 realization: scored 0, reasons and falsifiers in N2.md
    "current_null_sar_nvm": "flash/eNVM current array with a null SAR (Mythic, 27h10, F11): ASAP7 has no eNVM, and "
                            "streaming rewrites every weight ~100x/s (10^4-cycle endurance lasts minutes, 27m4)",
    "resistive_voltage_average": "open-circuit voltage-mode averaging (Wan 2022 in 27h7): needs dense linear resistive "
                                 "cells; ASAP7 has no high-R poly and no RRAM",
    "fefet_time_both": "both operands in time on multilevel-Vt FeFET (Soliman 2023, 27h9): no FeFET in ASAP7",
}
BD0 = dict(delivery=0.0, switch_gates=0.0, row_wire=0.0)


def _db(x):
    return 10 * math.log10(max(x, 1e-30))


def _vs(vdd):
    return (vdd / k.get("vdd_nom")) ** 2


def _fa_per_xp(rows, bits):
    """Full adders per crosspoint of an R-input tree of `bits`-bit operands: sum_l R/2^l (bits+l-1) / R."""
    return sum((rows >> lv) * (bits + lv - 1) for lv in range(1, int(math.log2(rows)) + 1)) / rows


def _dig(p, vdd, rows, bits, planes):
    """Gating + adder tree for `planes` input planes of `bits`-bit operands: (fJ / crosspoint, um2 / crosspoint).
    Liberty INVx1 energy (cell parasitics) for the gates, e_FA for the FAs (27i2)."""
    fa = _fa_per_xp(rows, bits)
    e = planes * (bits * k.get("inv_switch_energy_fJ_lib") + fa * p["e_fa_fJ"]) * _vs(vdd)
    return e, 1.3 * (bits * NAND_UM2 + fa * FA_UM2)


def _bit_um2(cell):
    """Area of one stored weight bit incl. routing: the N3 cell's storage share (gain cell with the live N3),
    else 6T x 1.3 (frozen N3)."""
    if "feol_store_um2" in cell and cell.get("_wb"):
        return cell["feol_store_um2"] / cell["_wb"]
    return 1.3 * k.get("sram6t_bitcell_um2")


def relief_db(par, planes=6):
    """dB by which the analog part's gate is lowered: digital MSB input planes cut the output-referred analog
    (data-independent) noise by (4^P-1)/(4^(P-k)-1); digital MSB weight bits by E m^2 / E m_low^2."""
    r = 0.0
    kd, kw = int(par.get("k_dig", 0)), int(par.get("k_wbits", 0))
    if 0 < kd < planes:
        r += _db((4 ** planes - 1) / (4 ** (planes - kd) - 1))
    if kw:
        r += _db(EM2 / ST["em2_low"][3 - kw])
    return r


# ---- device helpers (EKV in gm/ID form, calibrated to measured ASAP7 numbers) --------------------
def _nut():
    return 1.0 / k.get("nfet_gm_over_id_max_per_V")


def _ic(gmid):
    """Inversion coefficient from gm/ID (Enz EKV: gm nUT / ID = 1/(0.5 + sqrt(0.25 + IC)))."""
    x = 1.0 / (gmid * _nut()) - 0.5
    return max(x * x - 0.25, 1e-4)


def _ispec_uA():
    """Specific current per fin at L_min: measured Id(VGS = VDS = 0.7) / IC_on, IC_on = (Vov/2nUT)^2."""
    s = (k.get("vdd_nom") - k.get("vt_rvt_V")) / (2 * _nut())
    return k.get("nfet_id_per_fin_uA") / (s * s)


def _stack_for(sigma, gmid, n_f=1):
    """Series devices (L = stack x 21 nm) so that gm/ID x A_VT/sqrt(WL) <= sigma (27g1, 27g4)."""
    wl = (gmid * k.get("avt_mV_um") * 1e-3 / sigma) ** 2
    return max(1, math.ceil(wl / (n_f * FIN_W_UM * L_UM)))


def _dev_um2(n_f, stack):
    return n_f * FIN_PITCH_UM * (stack + 1) * CPP_UM


def _ron_share(p, vdd):
    """Share-switch Ron per fin (pair): RVT nmos at V_S = 0 for the port anchor; 1n1p TG at its worst case over
    0..VDD for rail drive (the share node sits near V_cm, where the nmos alone is 31 kOhm: measured)."""
    if p["timing"] == "port":
        return k.get("switch_ron_ohm_per_fin", vdd)
    return k.get("tgate_ron_max_ohm_1n1p") * k.get("switch_ron_ohm_per_fin", vdd) / k.get("switch_ron_ohm_per_fin")


# ---- charge domain -----------------------------------------------------------------------------
def _charge(p, vdd, fmt, cell, rows):
    planes, wb = fmt["input_planes"], min(4, fmt["wbits"])
    if p["c2c"] and p.get("c2c_single") and fmt["wbits"] > 4:
        wb, fmt["slices"] = fmt["wbits"], 1           # one 7-b ladder per weight (contract gap, docstring)
    mag, cu, kw = wb - 1, p["cu_fF"], int(p.get("k_wbits", 0))
    if p["bitslice"]:
        n_caps, c_w = mag, cu                        # one unit per magnitude bit, one bit column each
    elif p["c2c"]:
        n_caps, c_w = 3 * mag - 1, 2 * cu            # ladder units; Thevenin C at the output ~ 2 Cu
    elif p.get("analog_w"):
        n_caps, c_w = 1, cu                          # one sampling cap per weight
    elif kw:
        n_caps = 2 ** (mag - kw) - 1                 # low magnitude bits only
        c_w = n_caps * cu
    else:
        n_caps, c_w = 2 ** mag - 1, cell["c_weight_fF"]
    swing = p["v_exc_frac"] / 0.25                   # the anchor excited +-VDD/4
    deliver = (ANCHOR["e_fJ"] * (n_caps * cu / (7 * ANCHOR["cu_fF"])) * (vdd / ANCHOR["vdd"]) ** 2
               * swing ** 2 * planes / ANCHOR["planes"])
    if p["packets"]:
        deliver *= 14.112 / 2.449                    # measured unary/binary transfer ratio (repo)
    cgg = k.get("nfet_cgg_per_fin_aF") * 1e-3
    gate = (n_caps if p["bitslice"] else min(wb, 4)) * 2 * cgg * vdd ** 2 * p["sw_activity"] * planes
    pitch = math.sqrt(cell["area_um2_per_weight"])
    wire = pitch * k.get("wire_c_fF_per_um") * vdd ** 2 * planes
    c_col = rows * c_w
    tau_sw = _ron_share(p, vdd) / p["share_fins"] * c_col * 1e-6                     # ns
    r_w = k.get("wire_r_ohm_per_um") / p["wire_x"] * rows * pitch
    tau_w = 0.5 * r_w * (c_col + k.get("wire_c_fF_per_um") * p["wire_x"] ** 0.5 * rows * pitch) * 1e-6
    fo4 = k.get("fo4_delay_ps", vdd) * 1e-3
    bd = dict(delivery=deliver, switch_gates=gate, row_wire=wire)
    if p["timing"] in MEAS_TIMING:   # round 2: explicit phases on measured ASAP7 settling (A2, N2_r2.md)
        out = _charge_meas(p, vdd, fmt, cell, rows, bd, c_col, c_w, pitch, tau_w, fo4, cgg)
        if p["k_dig"]:
            _hybrid(p, vdd, fmt, cell, rows, out)
        return out
    if p["timing"] == "port":
        slot = max(ANCHOR["slot_ns"] * k.get("fo4_delay_ps", vdd) / k.get("sky130_fo4_delay_ps"),
                   p["settle_tau"] * tau_sw)
    else:   # each phase settles to half an LSB: (B+1) ln2 tau (AD-FrequencyRespo-1); C-2C: serial sections
        b = int(p.get("adc_bits", 8))
        slot = (p["n_phase"] * (b + 1) * math.log(2) * (tau_sw + tau_w) * (1 + (mag - 1) * p["c2c"])
                * p["corner_margin"] + 4 * fo4)
        bd["share_switch"] = planes * 2 * (2 * p["share_fins"] * cgg) * vdd ** 2 / rows   # diff. TG gates
    t_word = (2 ** planes - 1) * slot * 2 / p["n_phase"] if p["packets"] else planes * slot
    v_exc = vdd * p["v_exc_frac"]
    if p["bitslice"]:   # thermal-equivalent ratio: word noise sum 4^b over equal columns (derived, any weights)
        v_exc *= (2 ** mag - 1) / math.sqrt((4 ** mag - 1) / 3)
    if p["c2c"]:
        v_exc *= (2 ** mag - 1) / 2 ** mag
    if kw:              # the column carries the low part only: its own normalized rms
        lo = 2 ** (mag - kw) - 1
        v_exc *= math.sqrt(ST["em2_low"][mag - kw] / lo ** 2 / (EM2 / (2 ** mag - 1) ** 2))
    out = dict(v_exc_V=v_exc, c_col_fF=c_col, e_mac_fJ=sum(bd.values()), t_word_ns=t_word, slot_ns=slot,
               tau_ns=dict(switch=tau_sw, wire=tau_w), breakdown_fJ=bd)
    if p["bitslice"] or p["c2c"] or kw:
        beol = n_caps * cu / k.get("mom_cap_density_fF_per_um2")
        out["cell"] = dict(area_um2_per_weight=max(cell["feol_um2"], beol), beol_um2=beol)
    if p["bitslice"]:
        # mag bit columns per weight column: (mag-1) extra conversions, priced at the per-bit range;
        # per-column ADC ranges recombined: ADC SNR x E m^2 / sum 4^b p_b (derived)
        e_x = (mag - 1) * p.get("_e_conv_fJ", 0.0) / rows
        out["e_mac_fJ"] += e_x
        bd["extra_conversions"] = e_x
        out["t_word_ns"] = max(t_word, mag * p.get("_t_conv_all_ns", 0.0))
        out["adc_credit_db"] = _db(EM2 / sum(4 ** b * q for b, q in enumerate(ST["pb"])))
    if p.get("analog_w"):
        _analog_w(p, vdd, fmt, cell, rows, out, mag)
    if p["k_dig"] or kw:
        _hybrid(p, vdd, fmt, cell, rows, out)
    return out


def _drive_planes(p, fmt):
    """Row-drive planes per word: N9's driver (ml2 rails: ceil(8/2) = 4); its own bit planes otherwise."""
    try:
        from arch_eval.nodes import n9_circuits as n9
        return n9._driver(p, fmt)[2]
    except Exception:  # noqa: BLE001
        return fmt["input_planes"]


def row_tau_ns(p, c_w, pitch):
    """Measured row-segment settling tau (ESPice E2): rail switch R_RAIL_FIN / row_fins in series with half the
    strap (n5's law: R_sq x 18 nm / (strap_frac pitch)), into row_seg bottom plates + wire."""
    seg = p.get("row_seg", 32)
    c_seg = seg * c_w + seg * pitch * k.get("wire_c_fF_per_um")
    r_strap = k.get("wire_r_ohm_per_um") * 0.018 / (p.get("strap_frac", 0.1) * pitch) * seg * pitch
    r_fin = R_INV_FIN if p.get("n9_driver") == "inv_bitserial" else R_RAIL_FIN
    return (r_fin / p.get("row_fins", 8) + r_strap / 2) * c_seg * 1e-6


def casc_ns(tb, tc, eps):
    """Settle time of the top plate held by the column switch (pole tc) while the row (pole tb) steps: the deviation
    is tc/(tb-tc) (e^-t/tb - e^-t/tc) (t/tb e^-t/tb when equal); the first t after which it stays below eps."""
    if abs(tb - tc) < 1e-6 * tb:
        f = lambda t: t / tb * math.exp(-t / tb)                                  # noqa: E731
    else:
        f = lambda t: tc / (tb - tc) * (math.exp(-t / tb) - math.exp(-t / tc))    # noqa: E731
    lo, hi = max(tb, tc), 80 * max(tb, tc)
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if abs(f(mid)) > eps else (lo, mid)
    return hi


def supply_droop(p, cell, rows, fmt, c_xp, p1):
    """Row-reference error per plane for drive from the VDD/GND grid (critic r2): alpha = one row's charge over the
    tile decap = c_xp / (rows a_xp rho DECAP_FRAC); rms over the plane popcount n_b ~ Bin(rows, p1) (p1 = share of
    rows at the grid level: bit-serial sw_activity; ml2 the top level V, 1/4; V/3, 2V/3 are buffered); the mean part
    is a fixed gain (trimmed). const_charge leaves the dummy mismatch only. -> (eps, alpha)."""
    a_xp = cell["area_um2_per_weight"] / (2 * fmt["slices"])          # per physical crosspoint (diff x slices)
    alpha = c_xp / (rows * a_xp * MOS_FF_PER_UM2 * p.get("decap_frac", DECAP_FRAC))
    eps = alpha * math.sqrt(rows * p1 * (1 - p1)) * (p.get("cc_mismatch", CC_MISMATCH) if p.get("const_charge") else 1)
    return eps, alpha


def _charge_meas(p, vdd, fmt, cell, rows, bd, c_col, c_w, pitch, tau_w, fo4, cgg):
    """Per input plane, explicit phases (A2). meas3 = the round-1 sequence made explicit:
         reset top (column switch) || return row to 0, drive row (top floating), share to the accumulator
         slot = m [max(n_c tc, n_r tr) + n_r tr + n_c tc] + 4 FO4
    bps2 = bottom-plate sampling: drive the row while the top is held at V_cm, then release the top and
         return the row to 0 while the column shares (signal-independent top-plate injection)
         slot = m 2 max(casc(tr, tc, 2^-(B+1)), n_r tr, n_c tc) + 4 FO4    (critic r2: measured cascade)
    tc = KB_BOOT R_COL_FIN / share_fins C_col + TAU_COL0 + tau_wire (bootstrapped NMOS, E1; floor fit sp4/sp6),
    n_c = (B+1) ln2 (n9 rule); tr = row_tau_ns (measured E2, refit sp4), n_r = row_bits ln2 (residual = a static per-level gain, trimmed: n5 cal).
    Priced here (unpriced in round 1): row rail-switch gates (TG, 2 on/off cycles per plane) and area,
    the column-switch events beyond the one n9.plumb charges. arr carries tau_meas_ns, not tau_ns, so
    n9._arr_fix keeps this slot.
    Critic r2: bps2 phases use the measured cascade (casc_ns, real bootstrap, crosspoint TG); bit-serial delivery is
    C V^2 per 1-bit; driver area counts physical (differential) columns; the grid droop is a gain term (eps_ref);
    const_charge adds the dummy row cap and its driver."""
    b = int(p.get("adc_bits", 8))
    tc = KB_BOOT * R_COL_FIN / p["share_fins"] * c_col * 1e-6 + TAU_COL0_NS + tau_w
    tr = row_tau_ns(p, c_w, pitch)
    nc, nr = (b + 1) * math.log(2), p.get("row_bits", 8) * math.log(2)
    rails = p.get("n9_driver", "inv_bitserial") == "ml2_rails"    # V/3, 2V/3 from tile-shared buffers
    t_row = max(nr * tr, p.get("rail_floor_ns", RAIL_FLOOR_NS) if rails else 0.0)
    if p["timing"] == "bps2":   # critic r2: each phase is a cascade (row -> top plate held/shared by the switch)
        core = 2 * max(casc_ns(tr, tc, 2.0 ** -(b + 1)), t_row, nc * tc)
    else:
        core = max(nc * tc, t_row) + t_row + nc * tc
    ev = 2
    slot = p["corner_margin"] * core + 4 * fo4
    planes = fmt["input_planes"]
    seg, rf = p.get("row_seg", 32), p.get("row_fins", 8)
    cc = bool(p.get("const_charge"))
    p_hi = 0.25 if rails else p["sw_activity"]          # rows drawing from the VDD grid per plane
    # row driver gates per crosspoint: ml2 = TG level switch + zero switch, 2 on/off cycles per plane, 6 device sets
    # per segment (0, V/3 TG, 2V/3 TG, V); inverter = n + p, one cycle per 1-bit (sw_activity), FO4 taper x 4/3;
    # constant charge: a dummy inverter set (+2), driven when the row is not at V (delivery +(1 - p_hi) C_on V^2).
    act = p["sw_activity"] + ((1 - p_hi) if cc else 0.0)
    cyc, devs, sets = (2.0, 2, 6) if rails else (act * 4 / 3, 2, 2)
    sets += 2 if cc else 0
    bd["row_switch"] = planes * cyc * devs * rf * cgg * vdd ** 2 / seg
    bd["share_switch"] = planes * (ev - 1) * 3 * p["share_fins"] * cgg * vdd ** 2 / rows   # n9 charges 1 event
    # charge one row draws per physical crosspoint: the bit-gated (connected) caps E m Cu + the row wire
    c_on = c_w * EM / (2 ** (min(4, fmt["wbits"]) - 1) - 1)
    c_xp = c_on + pitch * k.get("wire_c_fF_per_um")
    # critic r2: the driver steps the connected plates with the top held: C_on V^2 per plane at the mean level
    # (bit-serial: p1 = sw_activity; ml2: mean 2-b level ~ the same; const charge: 1). Per input plane of fmt:
    # n9 rescales the array part to its own drive planes (ml2: 4 of 6) and adds its supply/buffer loss on top.
    bd["delivery"] = planes * act * c_on * vdd ** 2
    bd["row_wire"] = planes * act * pitch * k.get("wire_c_fF_per_um") * vdd ** 2
    # driver area per logical weight: one segment driver per row_seg PHYSICAL columns = 2 (diff) x slices per weight
    sw_um2 = 2 * fmt["slices"] / seg * sets * rf * FIN_PITCH_UM * 2 * CPP_UM
    dummy_um2 = 2 * fmt["slices"] * c_xp / MOS_FF_PER_UM2 if cc else 0.0
    out = dict(v_exc_V=vdd * p["v_exc_frac"], c_col_fF=c_col, e_mac_fJ=sum(bd.values()),
               t_word_ns=_drive_planes(p, fmt) * slot, slot_ns=slot, breakdown_fJ=bd,
               tau_meas_ns=dict(col=tc, row=tr, wire=tau_w),
               phases_ns=dict(n_c_tc=nc * tc, n_r_tr=nr * tr, casc=casc_ns(tr, tc, 2.0 ** -(b + 1))),
               cell=dict(area_um2_per_weight=cell["area_um2_per_weight"] + sw_um2 + dummy_um2,
                         row_switch_um2=sw_um2, row_dummy_um2=dummy_um2))
    # row reference = the grid (bit-serial; ml2's V level): fold the popcount droop into n5's eps_ref
    eps, alpha = supply_droop(p, cell, rows, fmt, c_xp, p_hi)
    p.setdefault("_eps_ref0", p.get("eps_ref", 0.002))   # ponytail: contract gap, n5 reads p["eps_ref"]
    p["eps_ref"] = math.hypot(p["_eps_ref0"], eps)
    out["supply"] = dict(alpha_per_row=alpha, eps=eps, const_charge=cc)
    return out


def _analog_w(p, vdd, fmt, cell, rows, out, mag):
    kT, cu, planes = k.get("kT_300K_J"), p["cu_fF"], fmt["input_planes"]
    c_h = p["m_ratio"] * cu
    v_w = vdd * p["v_exc_frac"] * math.sqrt(EM2) / (2 ** mag - 1)          # rms weight voltage
    droop = math.sqrt(planes - 1) / 2 / p["m_ratio"]   # MSB-plane spread of earlier 1-samples (mean part trimmed)
    ktc = math.sqrt(kT / (c_h * 1e-15)) / v_w
    out["extra_parts_db"] = dict(droop=_db(1 / max(droop, 1e-9) ** 2), store_ktc=_db(1 / ktc ** 2),
                                 dac_inl=_db(1 / p["dac_inl"] ** 2))
    feol = 1.3 * (c_h / MOS_FF_PER_UM2 + 3 * 0.02)
    beol = cu / k.get("mom_cap_density_fF_per_um2")
    pitch = math.sqrt(max(feol, beol))
    c_wl = rows * pitch * k.get("wire_c_fF_per_um") + c_h
    tau = k.get("tgate_ron_max_ohm_1n1p") / 4 * c_wl * 1e-6                  # ns, 4-fin write TG
    out["cell"] = dict(area_um2_per_weight=max(feol, beol), feol_um2=feol, beol_um2=beol,
                       e_write_fJ_per_bit=(c_wl * vdd ** 2 + 20.0) / 4, leak_nW_per_weight=0.0,
                       t_write_row_ns=9 * math.log(2) * tau + 4 * k.get("fo4_delay_ps", vdd) * 1e-3)
    out["aw"] = dict(c_h_fF=c_h, droop=droop, ktc=ktc)


def _hybrid(p, vdd, fmt, cell, rows, out):
    """k_dig: top input planes in a per-column adder tree over all weight bits; k_wbits: top weight bits in a
    tree over every plane. Both read the same stored weight bits."""
    kd, kw, planes, wb = int(p["k_dig"]), int(p.get("k_wbits", 0)), fmt["input_planes"], min(4, fmt["wbits"])
    f_an = (planes - kd) / planes
    if kd:
        e_dig, a_dig = _dig(p, vdd, rows, wb, kd)
        t_dig = kd * 100 * k.get("fo4_delay_ps", vdd) * 1e-3
    else:
        e_dig, a_dig = _dig(p, vdd, rows, kw + 1, planes)      # MSB bit(s) + sign
        t_dig = planes * 100 * k.get("fo4_delay_ps", vdd) * 1e-3
    out["e_mac_fJ"] = out["e_mac_fJ"] * f_an + e_dig
    out["breakdown_fJ"] = dict({n: v * f_an for n, v in out["breakdown_fJ"].items()}, digital_planes=e_dig)
    out["t_word_ns"] = max(out["t_word_ns"] * f_an, t_dig)
    base = out.get("cell", cell)
    feol = cell["feol_um2"] + a_dig
    out["cell"] = dict(area_um2_per_weight=max(feol, base.get("beol_um2", cell.get("beol_um2", 0.0))), feol_um2=feol)


def _ota(p, vdd, fmt, cell, rows):
    out = _charge(p, vdd, fmt, cell, rows)
    kT, b, ks = k.get("kT_300K_J"), int(p.get("adc_bits", 8)), p.get("k_sigma", 4.0)
    c_col = out["c_col_fF"]
    sig_in = 2 * out["v_exc_V"] * p["rho"] / math.sqrt(rows)        # passive differential signal
    g = (p["v_out_pk"] / ks) / sig_in
    c_int = c_col / g
    beta = c_int / (c_int + c_col + p["c_par_fF"])
    c_l = c_int * (1 - beta) + p["c_adc_fF"]
    a0 = k.get("nfet_gm_gds_at_gmid10") * k.get("pfet_gm_gds_at_gmid10")   # two-stage, measured gm/gds
    eps = p["k_nl"] / (a0 * beta)                                           # swing-dependent gain error
    sig_out = g * sig_in
    e_ota = vdd * 2 * c_l * (b + 1) * math.log(2) / (beta * p["gmid_ota"])  # fJ per settle (fully diff)
    planes = fmt["input_planes"]
    out["e_mac_fJ"] += planes * e_ota / rows
    out["breakdown_fJ"]["ota"] = planes * e_ota / rows
    # n5 sees the amplified output: same C_col (thermal SNR unchanged by gain), signal x g
    out["v_exc_V"] *= g
    out["extra_parts_db"] = dict(ota_noise=_db(sig_out ** 2 / (2 * 2 * kT / (beta * c_l * 1e-15))),
                                 ota_nonlinearity=_db(1 / eps ** 2))
    out["cell"] = dict(area_um2_per_weight=cell["area_um2_per_weight"] + p["ota_area_um2"] / rows)
    out["ota"] = dict(gain=g, c_int_fF=c_int, beta=beta, loop_gain=a0 * beta, eps=eps)
    return out


# ---- current domain ------------------------------------------------------------------------------
def _hold_us(c_fF, dv_mV):
    """Analog gate hold (live N3 measured leakage); 1 pA fallback."""
    try:
        from arch_eval.nodes import n3_cell
        return n3_cell.analog_hold_us(c_fF, dv_mV)
    except Exception:  # noqa: BLE001
        return c_fF * 1e-15 * dv_mV * 1e-3 / 1e-12 * 1e6


def _current(p, vdd, fmt, cell, rows):
    kT, planes, ks = k.get("kT_300K_J"), fmt["input_planes"], p.get("k_sigma", 4.0)
    gmid, units, cal, cco = p["gmid_cell"], p["units"], p["n2_cal"], p["cur_readout"] == "cco"
    b_adc = int(p.get("adc_bits", 8))
    stack = int(p["n_stack"]) if cal else _stack_for(p["sigma_u"], gmid)
    i_u = _ic(gmid) * _ispec_uA() * 1e-6 / stack                     # replica-biased at fixed gm/ID
    em = EM if units > 1 else 1.0
    gm_avg = gmid * i_u * em * p["act_mean"]
    bits = 0 if units == 1 else min(4, fmt["wbits"])
    feol = 1.3 * (units * _dev_um2(1, stack) + (3 if units > 1 else 2) * 0.02) + bits * _bit_um2(cell)
    phys = (int(p["cols"]) + int(p.get("checksum", 1))) * fmt["slices"]
    cgg = k.get("nfet_cgg_per_fin_aF") * 1e-18
    t_q = p["tq_ns"] * 1e-9
    for _ in range(3):   # t_q >= 3 tau_row, tau_row depends on the pitch, which depends on C_int(t_q)
        t_win = (2 ** planes - 1) * t_q
        if cco:          # 2^B counts inside the window
            t_win = max(t_win, 2 ** b_adc * p["cco_tlsb_ps"] * 1e-12)
        s_q = 2 * p["rho"] * units * i_u * t_win * math.sqrt(rows)   # rms column charge (differential)
        c_int = ks * s_q / p["v_out_pk"]                              # per side, +-k sigma = v_out_pk
        beol = 0.0 if cco else 2 * c_int * 1e15 / (rows * k.get("mom_cap_density_fF_per_um2"))
        if units == 1:
            beol += p["c_store_fF"] / k.get("mom_cap_density_fF_per_um2")
        area = max(feol, beol) + p["clamp_area_um2"] / rows          # one RGC clamp per column
        pitch = math.sqrt(area)
        c_row = phys * (k.get("wire_c_fF_per_um") * pitch * 1e-15 + units * cgg)
        tau_row = 0.5 * k.get("wire_r_ohm_per_um") * phys * pitch * c_row
        t_q = max(p["tq_ns"] * 1e-9, p["tq_tau_x"] * tau_row)
    sig = p["v_out_pk"] / ks
    r_src = k.get("wire_r_ohm_per_um") / p["src_rail_x"] * pitch
    eps_ir = gm_avg * r_src * rows ** 2 / 2                           # 15h1 law at the average current
    ch_q = 2 * p["gamma_n"] * kT * rows * gm_avg * t_win              # integrated 4kT gamma gm (C^2)
    if cco:
        thermal = _db(s_q ** 2 / (2 * ch_q))
    else:
        thermal = _db(sig ** 2 / (2 * (kT / c_int + ch_q / c_int ** 2)))
    if units > 1:
        mm = _db((EM2 / EM) / p["sigma_u"] ** 2)
    elif cal:   # program-verify residual: write kT/C_s at the gate, verify step, droop not cancelled
        dv_mV = p["t_live_us"] / _hold_us(p["c_store_fF"], 1.0)
        s2 = (gmid * math.sqrt(kT / (p["c_store_fF"] * 1e-15))) ** 2 + p["sigma_verify"] ** 2 \
            + (gmid * dv_mV * 1e-3 * p["droop_res"]) ** 2
        mm = _db(1 / s2)
    else:
        mm = _db(1 / (p["sigma_u"] ** 2 + (gmid * math.sqrt(kT / (p["c_store_fF"] * 1e-15))) ** 2))
    eps_edge = p["edge_frac"] * tau_row * math.sqrt(planes) / (0.5 * (2 ** planes - 1) * t_q)
    q_avg = rows * em * i_u * t_win * p["act_mean"]
    i_col_max = rows * units * i_u
    t_word = t_win + 0.5e-9                                           # + C_int reset
    if p["clamp"] == "tia":
        i_bias = i_col_max * 2 ** b_adc / (p["v_read"] * p["gmid_tia"])
    else:
        i_bias = p["i_amp_uA"] * 1e-6
    reset = 0.0 if cco else 2 * c_int * p["v_out_pk"] ** 2
    e_col = vdd * (2 * q_avg + 2 * i_bias * t_word) + reset           # J / column-word
    gate = 2 * (3 if units > 1 else 1) * 2 * cgg * vdd ** 2           # 2 edges
    e_cal = 64 * p["e_fa_fJ"] * _vs(vdd) / rows if p["pvt_res"] < 0.006 else 0.0   # 8x8 column gain multiply
    parts = dict(thermal=thermal, mismatch=mm, ir_drop=_db(1 / eps_ir ** 2), pvt=_db(1 / p["pvt_res"] ** 2),
                 pwm_edge=_db(1 / eps_edge ** 2))
    bd = dict(BD0, cell_charge=vdd * 2 * q_avg / rows * 1e15, clamp=vdd * 2 * i_bias * t_word / rows * 1e15,
              reset=reset / rows * 1e15, switch_gates=gate * 1e15, gain_cal=e_cal)
    if cco:
        e_cco = 2 ** b_adc * (5 * k.get("inv_switch_energy_fJ_lib") + 2 * k.get("dff_energy_fJ")) * _vs(vdd)
        p["_adc_override"] = dict(bits=b_adc, e_conv_fJ=e_cco, t_conv_ns=10 * k.get("fo4_delay_ps", vdd) * 1e-3,
                                  area_um2=4 * (5 * k.get("inv_x1_area_um2") + b_adc * k.get("dff_area_um2") + 1.0))
        parts["cco_inl"] = _db(4 * 4 ** b_adc / 64)                   # +-1 LSB INL after cal (var d^2/4)
    out = dict(sig_V=sig, c_col_fF=max(c_int * 1e15, 1e-3), e_mac_fJ=sum(bd.values()),
               t_word_ns=t_word * 1e9, slot_ns=t_word * 1e9, breakdown_fJ=bd, domain_parts_db=parts,
               cur=dict(stack=stack, i_unit_uA=i_u * 1e6, c_int_fF=c_int * 1e15, eps_ir=eps_ir, t_q_ns=t_q * 1e9,
                        tau_row_ns=tau_row * 1e9, feol_um2=feol, beol_um2=beol, i_col_max_uA=i_col_max * 1e6,
                        i_bias_uA=i_bias * 1e6))
    out["cell"] = dict(area_um2_per_weight=area, feol_um2=feol, beol_um2=beol)
    if units == 1:      # gain cell: analog write = C_s V^2 + a 20 fJ DAC share (+ a compare) per iteration
        n = p["n_iter"]
        out["cell"].update(leak_nW_per_weight=2 * k.get("nfet_ileak_per_fin_nA_sram") * k.get("vdd_nom"),
                           e_write_fJ_per_bit=n * (p["c_store_fF"] * vdd ** 2 + 20.0
                                                   + (k.get("comparator_energy_fJ") if cal else 0.0)) / 4,
                           t_write_row_ns=n * 2.0)                      # DAC settle + compare ~2 ns (projected)
    return out


# ---- log / translinear ---------------------------------------------------------------------------
def _log(p, vdd, fmt, cell, rows):
    kT, nut, q_e, ks = k.get("kT_300K_J"), _nut(), 1.602e-19, p.get("k_sigma", 4.0)
    if p["trim"]:
        n_f, stack, s_m = 1, 1, p["sigma_trim_mV"] * 1e-3 / nut
    else:
        n_f, stack, s_m = 1, _stack_for(0.03, 1 / nut), 0.03
    i_max = p["ic_max"] * _ispec_uA() * 1e-6 * n_f / stack
    t = p["t_win_ns"] * 1e-9
    s_q = 2 * p["rho"] * i_max * t * math.sqrt(rows)
    c_int = max(ks * s_q / p["v_out_pk"], 5e-15)
    sig = s_q / c_int
    c_s = kT / (p["sigma_store"] * nut) ** 2                          # kT/C on the stored log weight
    q_avg = rows * i_max * p["mean_ratio"] * t
    th = 2 * (kT / c_int + q_e * q_avg / c_int ** 2)                  # kT/C_int + shot noise
    # trim bits: +-4 sigma_Vt of a 1-fin device in steps of sigma_trim sqrt(12) (8 b at 0.3 mV, 10 b at 0.1 mV)
    sv_raw = k.get("avt_mV_um") / math.sqrt(FIN_W_UM * L_UM)
    n_trim = math.ceil(math.log2(8 * sv_raw / (p["sigma_trim_mV"] * math.sqrt(12)))) if p["trim"] else 0
    feol = 1.3 * (_dev_um2(n_f, stack) + 3 * 0.02) + n_trim * _bit_um2(cell)
    beol = c_s * 1e15 / k.get("mom_cap_density_fF_per_um2")
    t_word = t + 1.0e-9                                               # + reset and log-DAC settle
    i_amp = p["i_amp_uA"] * 1e-6
    e_col = vdd * (2 * q_avg + 2 * i_amp * t_word) + 2 * c_int * p["v_out_pk"] ** 2
    c_row = k.get("nfet_cgg_per_fin_aF") * 1e-3 * n_f + k.get("wire_c_fF_per_um") * math.sqrt(max(feol, beol))
    # each row's log-DAC voltage carries kT/C of the row line (phys columns of c_row) into every product
    phys = (int(p["cols"]) + int(p.get("checksum", 1))) * fmt["slices"]
    s_row = math.sqrt(kT / (phys * c_row * 1e-15)) / nut
    e_dac = vdd * phys * c_row * (fmt["abits"] + 1) * math.log(2) / p["gmid_dac"] / phys   # fJ/crosspoint
    area_cl = p["clamp_area_um2"] / rows
    return dict(sig_V=sig, c_col_fF=c_int * 1e15, e_mac_fJ=e_col / rows * 1e15 + c_row * vdd ** 2 + e_dac,
                t_word_ns=t_word * 1e9, slot_ns=t_word * 1e9,
                breakdown_fJ=dict(BD0, cell_charge=vdd * 2 * q_avg / rows * 1e15,
                                  clamp=vdd * 2 * i_amp * t_word / rows * 1e15, row_wire=c_row * vdd ** 2),
                domain_parts_db=dict(thermal=_db(sig ** 2 / th), trim=_db(1 / s_m ** 2),
                                     store_ktc=_db(1 / p["sigma_store"] ** 2), row_ktc=_db(1 / s_row ** 2),
                                     pvt=_db(1 / p["pvt_res"] ** 2)),
                log=dict(c_store_fF=c_s * 1e15, trim_bits=n_trim, i_max_nA=i_max * 1e9, c_int_fF=c_int * 1e15,
                         feol_um2=feol, beol_um2=beol),
                cell=dict(area_um2_per_weight=max(feol, beol) + area_cl, feol_um2=feol, beol_um2=beol,
                          e_write_fJ_per_bit=(c_s * 1e15 * vdd ** 2 + 20.0) / 4))


# ---- time domain (delay chain + TDC) -------------------------------------------------------------
def _time(p, vdd, fmt, cell, rows):
    planes, wb = fmt["input_planes"], min(4, fmt["wbits"])
    units = 2 ** (wb - 1) - 1
    fo4 = k.get("fo4_delay_ps", vdd) * 1e-12
    t_u, t_mux = p["t_u_fo4"] * fo4, p["t_mux_fo4"] * fo4
    od = vdd - k.get("vt_rvt_V")
    if p["n2_cal"]:     # trimmed: raw spread of n_f fins, residual = 8 sigma_raw / 2^b / sqrt(12)
        n_f = int(p["n_f_cal"])
        s_raw = p["alpha"] * k.get("avt_mV_um") * 1e-3 / math.sqrt(n_f * FIN_W_UM * L_UM) / od
        s_u = 8 * s_raw / 2 ** p["cal_bits"] / math.sqrt(12)
        trim_um2 = units * p["cal_bits"] * (_bit_um2(cell) + 1.3 * FIN_PITCH_UM * 2 * CPP_UM)
        e_x = 1.25                                                   # trim load on each stage
    else:
        s_u = p["sigma_u"]
        sv = s_u * od / p["alpha"]                                   # sigma_Vt giving sigma_t/t = sigma_u
        n_f = max(1, math.ceil((k.get("avt_mV_um") * 1e-3 / sv) ** 2 / (FIN_W_UM * L_UM)))
        trim_um2, e_x = 0.0, 1.0
    s_t = 2 * p["rho"] * units * t_u * math.sqrt(rows)               # signal rms in time
    t_plane = rows * t_mux + rows * EM * 0.5 * t_u + 2 * p.get("k_sigma", 4.0) * s_t + 2 * fo4
    stages = rows * (1 + EM * 0.5)
    jit2 = stages * (p["jitter_frac"] * fo4) ** 2
    e_stage = n_f * k.get("inv_switch_energy_fJ_lib") * _vs(vdd) / 2 * e_x
    e_chain = planes * (2 + EM * 0.5) * e_stage                      # fJ / crosspoint / word
    e_tdc = (t_plane / t_u) * k.get("inv_switch_energy_fJ_lib") * _vs(vdd) + 10 * k.get("dff_energy_fJ") * _vs(vdd)
    e_cal = 64 * 0.36 * _vs(vdd) / rows if p["pvt_res"] < 0.004 else 0.0
    feol = 1.3 * (units * 2 * n_f * FIN_PITCH_UM * 2 * CPP_UM + 2 * 0.05 + 3 * 0.02) + wb * _bit_um2(cell) + trim_um2
    c = dict(area_um2_per_weight=feol, feol_um2=feol, beol_um2=0.0)
    if p["n2_cal"] and cell.get("_wb"):
        c["leak_nW_per_weight"] = cell["leak_nW_per_weight"] * (1 + units * p["cal_bits"] / cell["_wb"])
    return dict(sig_V=vdd / 8, c_col_fF=50.0, e_mac_fJ=e_chain + planes * e_tdc / rows + e_cal,
                t_word_ns=planes * t_plane * 1e9, slot_ns=t_plane * 1e9,
                breakdown_fJ=dict(BD0, chain=e_chain, tdc=planes * e_tdc / rows, gain_cal=e_cal),
                domain_parts_db=dict(mismatch=_db((EM2 / EM) / s_u ** 2), jitter=_db(s_t ** 2 / jit2),
                                     pvt=_db(1 / p["pvt_res"] ** 2)),
                time=dict(n_fins=n_f, sigma_u=s_u, t_plane_ns=t_plane * 1e9), cell=c)


def _digital(p, vdd, fmt, cell, rows):
    planes, wb = fmt["input_planes"], min(4, fmt["wbits"])
    e, a_dig = _dig(p, vdd, rows, wb, planes)
    feol = wb * _bit_um2(cell) + a_dig
    t = p.get("t_cyc_fo4", 100.0) * k.get("fo4_delay_ps", vdd) * 1e-3
    nb = wb + int(math.log2(rows))
    p["_adc_override"] = dict(bits=16, e_conv_fJ=nb * k.get("dff_energy_fJ") * _vs(vdd),   # column sum register
                              t_conv_ns=2 * k.get("fo4_delay_ps", vdd) * 1e-3, area_um2=nb * k.get("dff_area_um2"))
    return dict(sig_V=vdd / 8, c_col_fF=50.0, e_mac_fJ=e, t_word_ns=planes * t, slot_ns=t,
                breakdown_fJ=dict(BD0, adder_tree=e), domain_parts_db=dict(exact=200.0),
                cell=dict(area_um2_per_weight=feol, feol_um2=feol, beol_um2=0.0))


KINDS = dict(charge=_charge, ota=_ota, current=_current, log=_log, time=_time, digital=_digital)


def array(p, vdd, fmt, cell, rows):
    kind = p.get("domain_kind", "charge")
    if kind == "charge" and p.get("k_dig", 0) >= fmt["input_planes"]:
        kind = "digital"                 # every plane digital: the hybrid is digital CIM
    p.pop("_adc_override", None)
    cell["_wb"] = fmt["wbits"] if "feol_store_um2" in cell else 0
    d = KINDS[kind](p, vdd, fmt, cell, rows)
    if d.get("cell"):
        cell.update(d.pop("cell"))       # ponytail: contract gap (module docstring)
    if "v_exc_V" not in d:               # equivalent excitation on the shipped n5 law (score() refits per stack)
        d["v_exc_V"] = d["sig_V"] * math.sqrt(rows) / (2 * p.get("rho", 0.1))
    d.update(kind=kind, fmt=fmt)
    return d


# ---- scoring helpers (not used by the core) --------------------------------------------------------
class _N5:
    """n5 seen through the domain: non-charge kinds keep only n5's converter terms (adc, clip) and use
    their own error terms; their excitation is refit so n5's signal equals the domain's sig_V. Static
    terms get p['static_penalty_db'] (N8's 3.6 dB measure-once penalty) at the lossless gate."""

    def __init__(self, base):
        self.b, self.OPTIONS, self.DEFAULT = base, base.OPTIONS, base.DEFAULT
        self.SWEEP = getattr(base, "SWEEP", {})

    def geometry(self, p):
        return self.b.geometry(p)

    def _fit(self, p, geo, arr):
        if "sig_V" in arr and not arr.get("_fit"):
            unit = self.b.accuracy(p, k.get("vdd_nom"), geo, dict(arr, v_exc_V=1.0), dict(bits=8), arr["fmt"])
            arr["v_exc_V"] = arr["sig_V"] / unit["v_signal_rms_V"]
            arr["_fit"] = True

    def v_range(self, p, geo, arr):
        self._fit(p, geo, arr)
        return self.b.v_range(p, geo, arr)

    def accuracy(self, p, vdd, geo, arr, adc, fmt):
        self._fit(p, geo, arr)
        a = self.b.accuracy(p, vdd, geo, arr, adc, fmt)
        if "domain_parts_db" in arr:
            parts = dict(arr["domain_parts_db"], **{n: a["parts_db"][n] for n in ("adc", "clip") if n in a["parts_db"]})
        else:
            parts = dict(a["parts_db"], **arr.get("extra_parts_db", {}))
        if "adc" in parts:
            parts["adc"] += arr.get("adc_credit_db", 0.0)
        pen = p.get("static_penalty_db", 0.0)
        parts = {n: v - (pen if n in STATIC else 0.0) for n, v in parts.items()}
        return dict(a, snr_db=-_db(sum(10 ** (-v / 10) for v in parts.values())), parts_db=parts)


class _N6:
    """n6 seen through the domain: a domain with its own readout (CCO, digital register) overrides the SAR."""

    def __init__(self, base):
        self.b, self.OPTIONS, self.DEFAULT = base, base.OPTIONS, base.DEFAULT
        self.SWEEP = getattr(base, "SWEEP", {})

    def adc(self, p, vdd, v_fs):
        a = self.b.adc(p, vdd, v_fs)
        o = p.get("_adc_override")
        return dict(a, **o, breakdown_fJ=dict(own=o["e_conv_fJ"])) if o else a


def ctx_for(d, knobs=None, stack="frozen"):
    """model.Ctx with n5/n6 wrapped. stack="frozen": every node except n2 is its shipped copy
    (nodes/default, the reference stack whose terms are stable), except n3 when the design names a
    live-only N3 option (the gain-cell storage); "live": the current modules."""
    import sys
    from arch_eval import model
    ctx = model.Ctx(d, knobs)
    if stack == "frozen":
        me, live = sys.modules[__name__], dict(ctx.mods)
        ctx.mods = {nid: (me if nid == "n2_domain" else
                          live[nid] if nid == "n3_cell" and d["nodes"].get(nid) in live[nid].OPTIONS
                          and d["nodes"].get(nid) not in m.OPTIONS else m)
                    for nid, m in ctx.defaults.items()}
        p = {}
        for nid, m in ctx.mods.items():
            opt = d["nodes"].get(nid, m.DEFAULT)
            ctx.options[nid] = opt if opt in m.OPTIONS else m.DEFAULT
            p.update(ctx.defaults[nid].OPTIONS[ctx.defaults[nid].DEFAULT]["params"])
            p.update(m.OPTIONS[ctx.options[nid]]["params"])
        p.update(d["params"])
        ctx.p = p
        ctx.wl = model.workload.llama3(ctx.knobs.get("model", "8B-class"), prompt=ctx.knobs["prompt"],
                                       gen=ctx.knobs["gen"], kv_bits=int(ctx.knobs.get("kv_bits") or p.get("kv_bits", 16)))
    elif ctx.p.get("n2_relief_db"):      # live n8 reads q_snr_target_db: credit the hybrid relief there
        ctx.p["q_credit_db"] = ctx.p.get("q_credit_db", 0.0) + ctx.p["n2_relief_db"]
    ctx.mods["n5_array"] = _N5(ctx.mods["n5_array"])
    ctx.mods["n6_readout"] = _N6(ctx.mods["n6_readout"])
    return ctx


def _bitslice_prep(ctx):
    """charge_bitslice: price its extra conversions with the stack's own n5/n6 (stored in params)."""
    if not ctx.p.get("bitslice"):
        return
    from arch_eval import model
    t = model.tile(ctx, k.get("vdd_nom"), 1.0)
    ctx.p["_e_conv_fJ"] = t["adc"]["e_conv_fJ"] + t["adc"]["e_digital_fJ"]
    ctx.p["_t_conv_all_ns"] = t["t_conv_ns"]


def evaluate(d, knobs=None, stack="frozen"):
    from arch_eval import metric, model
    ctx = ctx_for(d, knobs, stack)
    _bitslice_prep(ctx)
    pts, dies = model.operating_points(ctx)
    s = metric.score(pts, ctx.knobs)
    s["errors"] = ctx.errors
    if s["peak"]:
        s["tile"], s["die"], s["plan"] = dies[(s["peak"]["vdd"], s["peak"]["clk_frac"])]
    return s


GRID = dict(rows=[64, 128, 256, 512], cols=[64, 128], adc_share=[1, 4, 8, 16], adc_bits=[6, 7, 8, 9, 10, 12])
CU = [0.2, 0.3, 0.5, 1.0, 4.0, 16.0]        # 0.2 fF = unit_cap_min_fF (asap7_constants)
CAPS = dict(cu_fF=CU, share_fins=[8, 32], wire_x=[1, 4])
FAST = dict(cu_fF=CU, share_fins=[32], wire_x=[4])
PVT = [0.001, 0.003, 0.006]
PER = dict(
    charge=dict(adc_bits=[6, 7, 8, 9, 10, 12]),           # the anchor: geometry/bits only
    charge_rail=CAPS, charge_bitslice=CAPS, charge_pulse_count=FAST, charge_c2c=FAST, charge_ota=FAST,
    charge_analog_weight=dict(FAST, cu_fF=[0.2, 0.5, 1.0, 2.0, 4.0], m_ratio=[16.0, 64.0, 256.0]),
    current_pwm=dict(gmid_cell=[3.0, 4.0, 6.0, 10.0, 15.0], sigma_u=[0.006, 0.01, 0.02, 0.03, 0.05], pvt_res=PVT,
                     tq_tau_x=[3.0, 10.0]),
    current_tia=dict(gmid_cell=[10.0]),
    current_gaincell=dict(gmid_cell=[4.0, 6.0, 10.0], sigma_u=[0.006, 0.01, 0.02, 0.03], pvt_res=PVT,
                          c_store_fF=[1.0, 4.0, 16.0], tq_tau_x=[3.0, 10.0]),
    current_gaincell_cal=dict(gmid_cell=[4.0, 6.0, 10.0], n_stack=[1, 4, 16, 64], c_store_fF=[1.0, 4.0, 16.0],
                              pvt_res=PVT, tq_tau_x=[3.0, 10.0]),
    cco_freq_mac=dict(gmid_cell=[6.0, 10.0, 15.0], sigma_u=[0.01, 0.03, 0.05], pvt_res=[0.001, 0.006],
                      adc_bits=[6, 7, 8, 9], tq_tau_x=[3.0, 10.0]),
    log_translinear=dict(sigma_store=[0.005, 0.01, 0.02, 0.03], t_win_ns=[2.0, 4.0, 8.0], sigma_trim_mV=[0.1, 0.3]),
    time_delay=dict(sigma_u=[0.01, 0.02, 0.03, 0.05], pvt_res=[0.001, 0.002, 0.004], k2_aJ=[0.0],
                    adc_area_fixed_um2=[20.0], cu_adc_fF=[0.0]),
    time_delay_cal=dict(n_f_cal=[1, 2, 4], cal_bits=[5, 6, 7, 8], pvt_res=[0.001, 0.002, 0.004], k2_aJ=[0.0],
                        adc_area_fixed_um2=[20.0], cu_adc_fF=[0.0]),
    hybrid_msb_digital=dict(FAST, k_dig=[1, 2, 3, 4, 5]),
    hybrid_wmsb_digital=dict(FAST, k_wbits=[1, 2]),
    digital_cim_ref=dict(adc_bits=[12]),
)


def designs(opt, mode="streaming", gate_db=28.0, conditions="arch", n3=None):
    """Grid per option. 'hi' (cu >= 1 fF, adc_bits >= 8) is keyed on the ANALOG target gate - relief, so a
    hybrid with enough digital planes searches the low-gate grid; 'lo' is cu <= 4 fF, adc_bits <= 8.
    The lossless gate (> 35 dB) applies N8's 3.6 dB static penalty. Sohu conditions stream W8."""
    import itertools
    from arch_eval import design
    axes = dict(GRID, **PER.get(opt, {}))
    if conditions == "sohu":
        axes["wbits"] = [8]
    n3 = n3 or ("sram6t_binary_caps" if opt == "charge" else GAIN_STORE)
    names = list(axes)
    for vals in itertools.product(*(axes[n] for n in names)):
        par = dict(zip(names, vals))
        rel = relief_db(dict(OPTIONS[opt]["params"], **par))
        hi = gate_db - rel > 35
        b, cu = par["adc_bits"], par.get("cu_fF")
        if opt == "digital_cim_ref":
            pass                     # exact: no analog target, no grid rule
        elif (hi and (b < 8 or (cu is not None and cu < 1))) or (not hi and (b > 8 or (cu is not None and cu > 4))):
            continue
        par.update(snr_target_db=gate_db - rel, n2_relief_db=rel, static_penalty_db=3.6 if gate_db > 35 else 0.0)
        yield design.make(dict(n1_system=mode, n2_domain=opt, n3_cell=n3), par, name=f"{opt}/{mode}")


def better(a, b, rel=1e-6):
    """metric.better with float ties (designs pinned at the same HBM/KV cap differ by ~1e-12) treated as equal."""
    from arch_eval import metric
    for m in metric.METRICS:
        if abs(a[m] - b[m]) > rel * max(abs(a[m]), abs(b[m]), 1e-30):
            return a[m] > b[m]
    return False


def best(opt, mode="streaming", gate_db=28.0, conditions="arch", stack="frozen", n3=None):
    from arch_eval import metric
    knobs = metric.knobs_for(conditions)
    top = None
    for d in designs(opt, mode, gate_db, conditions, n3):
        s = evaluate(d, knobs, stack)
        bad = [e for e in s["errors"] if "n2_domain" in e or "n3_cell" in e]
        if bad:
            raise RuntimeError(bad)
        if top is None or better(s, top[0]):
            top = (s, d)
    return top


DROP = ("snr_target_db", "n2_relief_db", "static_penalty_db", "k2_aJ", "adc_area_fixed_um2", "cu_adc_fF")


def row(opt, s, d):
    """Metrics, then the 27n1 bit-normalized TOPS/W (x b_i b_w) and the effective output bits."""
    t = s.get("tile") or {}
    m = max(1, t.get("macs_per_pass", 1))
    pr = d["params"]
    snr = t.get("snr_db", 0) + pr.get("n2_relief_db", 0)
    bb = 8 * int(pr.get("wbits", 4))
    enob = (snr - 1.76) / 6.02 if snr < 150 else float("inf")
    keep = {n: v for n, v in pr.items() if n not in DROP}
    return (f"{opt:<21} {s['tok_s_die']:>8.0f} {s['tops_w']:>6.2f} {s['tok_w']:>6.1f} {s['tok_j']:>6.1f} "
            f"| 1b {s['tops_w'] * bb:6.0f} ENOB {enob:4.1f} | pass {t.get('t_pass_s', 0) * 1e9:6.1f} ns "
            f"{t.get('e_pass_J', 0) / m * 1e15:6.1f} fJ/MAC {t.get('area_um2', 0) / m:5.2f} um2/MAC "
            f"SNR {snr:5.1f} | {keep}")


def _selfcheck():
    """Every option evaluates on both stacks without an n2 fallback; the anchor is bit-identical to
    the shipped default; physical sanity of the key laws."""
    from arch_eval import design, metric, model
    from arch_eval.nodes.default import n2_domain as d0
    ok = True
    for stack in ("frozen", "live"):
        for opt in OPTIONS:
            n1 = "streaming" if stack == "frozen" else model.Ctx(design.make()).mods["n1_system"].DEFAULT
            s = evaluate(design.make(dict(n2_domain=opt, n1_system=n1, n3_cell=GAIN_STORE)), stack=stack)
            bad = [e for e in s["errors"] if "n2_domain" in e or "n3_cell" in e]
            ok &= not bad
            if bad:
                print("FAIL", stack, opt, bad)
    ctx = ctx_for(design.make(dict(n2_domain="charge")), stack="frozen")
    fmt = ctx.call("n4_formats", "fmt")
    c1, c2 = ctx.call("n3_cell", "cell", 0.7, fmt), ctx.call("n3_cell", "cell", 0.7, fmt)
    a, b = array(ctx.p, 0.7, fmt, c1, 128), d0.array(ctx.p, 0.7, fmt, c2, 128)
    checks = {
        "anchor 'charge' == nodes/default n2": all(abs(a[n] - b[n]) < 1e-12
                                                   for n in ("e_mac_fJ", "t_word_ns", "v_exc_V", "c_col_fF")),
        "EKV gm/ID limits": abs(_ic(1 / _nut()) - 1e-4) < 1e-3 and _ic(5.0) > 20,
        "INT4 stats E m 1.85, E m^2 5.50": abs(EM - 1.85) < 0.01 and abs(EM2 - 5.5) < 0.05,
        "64-input 4-b tree = 309 FA": abs(_fa_per_xp(64, 4) * 64 - 309) < 1e-9,
        "relief k=3 of 6 planes = 18.1 dB": abs(relief_db(dict(k_dig=3)) - 18.13) < 0.02,
    }
    par = dict(rows=64, cols=128, adc_share=4, adc_bits=6, cu_fF=0.5)
    h = evaluate(design.make(dict(n1_system="streaming", n2_domain="hybrid_msb_digital", n3_cell=GAIN_STORE),
                             dict(par, k_dig=6)))
    dc = evaluate(design.make(dict(n1_system="streaming", n2_domain="digital_cim_ref", n3_cell=GAIN_STORE), par))
    checks["hybrid k=P == digital_cim_ref"] = all(abs(h[m] - dc[m]) < 1e-9 * max(1, dc[m]) for m in metric.METRICS)
    for name, good in checks.items():
        print("PASS" if good else "FAIL", name)
        ok &= good
    return ok


if __name__ == "__main__":
    import sys
    from arch_eval import baseline_systolic, metric
    assert _selfcheck(), "n2 self-check FAILED"
    print("n2 self-check PASS")
    opts = [a for a in sys.argv[1:] if a in OPTIONS] or list(OPTIONS)
    stack = "live" if "--live" in sys.argv else "frozen"
    cond = "sohu" if "--sohu" in sys.argv else "arch"
    kn = metric.knobs_for(cond)
    bl = baseline_systolic.evaluate(8 if cond == "sohu" else 4, kn)
    print(f"conditions {cond}: die {kn['die_mm2']:.1f} mm2; systolic baseline "
          + " / ".join(f"{bl[m]:.2f}" for m in metric.METRICS))
    modes = ("streaming",) if cond == "sohu" else ("streaming", "resident")
    for gate in ((28.0, 43.0) if "--hi" in sys.argv else (28.0,)):
        for mode in modes:
            print(f"== stack {stack}, {cond}, gate {gate} dB, {mode}   tok/s/die TOPS/W tok/W tok/J", flush=True)
            for opt in opts:
                s, d = best(opt, mode, gate, cond, stack=stack)
                print(row(opt, s, d), flush=True)
