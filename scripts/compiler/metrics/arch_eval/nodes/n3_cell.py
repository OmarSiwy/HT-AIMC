"""N3 storage cell, weight density and write (researched 2026-10-05, revised after critics; doc: ArchResearch/nodes/N3.md).

A weight cell = STORAGE (holds the code) x CAPACITOR (does the charge-domain multiply), plus how
banks share the capacitors. Per 4-b slice (sign rides the +/- lines, n2/n5), b = slice bits:

  units/slice   binary  2^(b-1)-1 identical units (20i5a: unary units, ratio = lithography, 27i1)
                c2c     3(b-1)-1 units, column sees 2 Cu (27i4 Thevenin)
  BEOL [um2]    MOM:  units Cu / rho_MOM,  rho_MOM = 2.0 fF/um2 (asap7_constants, derived)
  FEOL [um2]    bits x (A_bit + n_tg A_tg) x route  +  MOS units x fins x A_fin x ov
                A_bit, A_tg: LOGIC rules from the asap7sc7p5t liberty (INVx1 0.04374 um2 per 2T,
                DHLx1 0.2187); SRAM pushed rules only for a foundry 6T bitcell (and as an
                optimistic bound, gaincell_mos_caps_sramrule)
  area/weight   max(FEOL, BEOL) / banks_shared / (1 - occ_refresh)        (caps stacked over cells)
  MOS cap       nmos_slvt gate in inversion, both drive levels in [v_lo, rail] (MEASURED C(V) here,
                ESPice BSIM-CMG TT 27C). rail = cap_rail (fixed; storage + TG domain sit on it).
                Signal-equivalent unit for the n2/n5 laws (they assume a VDD_nom/2 total swing):
                  k = ((rail - v_lo) / (VDD_nom/2))^2,  C_eq = (C_real + k_mom C_mom) k a_par
                  a_par = C_real / (C_real + C_par): S/D diffusion of every unit on the column
                  (passive column; 1 with an active virtual-ground column)
                Settling must see the REAL charge: cell reports settle_c_ratio = C_real_tot / C_eq
                (n2 does not read it yet; score_option applies it by re-timing n2 with real C)
                unit sigma = rss(Vt term, geometric A_C/sqrt(n W L)); Vt term derived, A_C projected
  retention     t_ret = C_node dV / I_node(V), I_node MEASURED here. Design retention = the 6-sigma
                write FET (-0.20 V Vt, WWL proxy) at 85 C: refresh rate and occupancy use it.
  refresh       eDRAM-style local sense + restore: E_ref = E_wr + E_rd + E_sa per node
                P_ref/weight = bits nodes E_ref / t_ret_design;  occ = 2 R t_row / t_ret_design
  crowbar       the bit inverter (or the off PMOS switch of the dual-rail cell) sees a drooping '1':
                MEASURED supply current vs droop, averaged over [0, dv_bit], 1/2 of bits are '1'
  write/bit     C_WBL = R (C_j + pitch c_wire);  E = a C_WBL V^2 + C_WWL V_WWL^2
                (SRAM/latch: a = 1; gain bit: a = 0.5, WWL boosted to V + 0.3 V: reliability item)
  t_write_row   2 FO4 (decode) + 5 tau_WBL,  tau_WBL = (Ron/8 + r_wire L/2) C_WBL

model.py consumes: area_um2_per_weight (per weight, all slices, ONE bank: banks are multiplied
by the core, so a shared-cap bank pair reports half the pair), c_weight_fF (per slice, on its
column), e_write_fJ_per_bit, t_write_row_ns, leak_nW_per_weight. Analog-level weights (copier /
log gain cell, destructive cap), NVM, MIM, ROM and per-use rewrite are not OPTIONS: they need an
N2 current/log domain, a device ASAP7 lacks, or core hooks the evaluator lacks; N3.md scores them.
Labels: measured = ESPice here; derived = law on measured; projected = literature only.
"""
import contextlib
import math

from arch_eval import asap7 as k

# --- measured here (ESPice BSIM-CMG ASAP7 TT; decks in N3.md "Reproduction") ----------------------
I_WRITE_FET_PA = {0.10: 0.048, 0.35: 0.736, 0.40: 1.112, 0.50: 1.979, 0.60: 3.811, 0.70: 5.895,
                  0.80: 8.479}                                   # nmos_sram 1 fin, WWL -0.15, WBL 0, 27C
I_WRITE_TAIL85_PA = {0.40: 36.54, 0.50: 39.31, 0.60: 42.91, 0.70: 46.77, 0.80: 51.08}  # same, 85C, -0.20 V Vt (6 sigma)
I_WRITE85_PA = {0.40: 1.310, 0.50: 2.248, 0.60: 4.257, 0.70: 6.584, 0.80: 9.572}     # same, 85C, nominal Vt
I_GATE_PA_PER_FIN = {0.10: 0.028, 0.35: 0.007, 0.60: 0.129, 0.70: 0.238, 0.80: 0.448}  # nmos_rvt read gate, D 0.35 V, 27C
I_GATE85_PA_PER_FIN = {0.40: 0.070, 0.50: 0.168, 0.60: 0.462, 0.70: 0.907, 0.80: 1.687}  # D=S=0 (worst), 85C
CROWBAR_NA = {   # 1-fin inverter supply current vs droop of its input below its rail (27C, VDD 0.7)
    "rvt": {0.0: 0.018, 0.05: 0.121, 0.10: 0.810, 0.15: 5.337, 0.20: 33.19, 0.25: 175.8, 0.30: 687.9},
    "sram": {0.0: 0.0036, 0.05: 0.0248, 0.10: 0.170, 0.15: 1.156, 0.20: 7.685, 0.25: 47.18, 0.30: 235.0},
}
C_MOS_AF_PER_FIN = {0.20: 38.64, 0.30: 54.57, 0.35: 58.75, 0.40: 61.75, 0.45: 63.99, 0.50: 65.71,
                    0.55: 67.06, 0.60: 68.12, 0.65: 68.98, 0.70: 69.68, 0.75: 70.27, 0.80: 70.76,
                    0.85: 71.18}                                 # nmos_slvt Cgg, D=S=B=0
FIN_FP_UM2 = 0.027 * 0.054         # derived: fin pitch x CPP (LIT_ASAP7 2.1)
W_EFF_UM, L_UM = 0.0705, 0.021     # one fin (LIT_ASAP7 2.1)
A_C_PCT_UM = 0.15                  # projected: MOS gate-area matching (L/LWR, H_fin, EOT), range 0.1-0.5 %um
LOGIC_T_UM2 = 0.04374 / 2          # liberty INVx1_ASAP7_75t_R per transistor (logic rules)

# --- measured round 2 (A4, 2026-10-06; ESPice BSIM-CMG ASAP7, decks scratchpad a4/{wr,sw,ret}.py, N3_r2.md) -----
# Net storage-node current (pA, + = node discharges) with the REAL 5-gate load (sram inverter 1+1 fin, P-TG nmos,
# N-TG pmos, N-gnd nmos; TG channels at 0.35 V) + the write FET (nmos_sram 1 fin, WWL -0.15 V), TT, 85 C.
# Key (wbl_hold_V, write FET): "nom" nominal Vt, "6s" = -0.20 V Vt (WWL +0.20 V proxy, as round 1).
_LV = [-0.05 + 0.025 * i for i in range(31)]
NODE_LEAK85_PA = {
    (0.0, "nom"): [-1.965, -1.637, -1.383, -1.242, -1.118, -0.991, -0.87, -0.76, -0.661, -0.568, -0.47, -0.358, -0.223,
                   -0.057, 0.15, 0.38, 0.626, 1.035, 1.338, 1.658, 2.019, 2.416, 2.852, 3.332, 3.858, 4.434, 5.062,
                   5.747, 6.493, 7.306, 8.199],
    (0.0, "6s"): [-113.775, -36.469, -1.417, 14.39, 21.508, 24.939, 26.902, 28.19, 29.157, 29.966, 30.697, 31.391,
                  32.074, 32.765, 33.478, 34.2, 34.925, 35.803, 36.565, 37.336, 38.141, 38.975, 39.843, 40.746,
                  41.691, 42.678, 43.712, 44.795, 45.931, 47.124, 48.386],
    (0.7, "nom"): [-2.158, -1.75, -1.459, -1.303, -1.172, -1.042, -0.92, -0.81, -0.713, -0.621, -0.524, -0.414, -0.28,
                   -0.115, 0.091, 0.32, 0.565, 0.973, 1.274, 1.593, 1.953, 2.349, 2.784, 3.263, 3.788, 4.362, 4.99,
                   5.674, 6.418, 7.231, 8.123],
    (0.7, "6s"): [-212.556, -96.144, -43.788, -20.284, -9.693, -4.884, -2.674, -1.639, -1.137, -0.877, -0.72, -0.601,
                  -0.485, -0.352, -0.189, -0.011, 0.174, 0.515, 0.743, 0.98, 1.25, 1.548, 1.878, 2.242, 2.644, 3.087,
                  3.572, 4.103, 4.682, 5.316, 6.015],
}
NODE_LEAK27_PA = {   # same, TT 27 C (the 'nom' retention corner)
    (0.0, "nom"): [-1.137, -0.989, -0.88, -0.801, -0.717, -0.638, -0.57, -0.511, -0.453, -0.391, -0.317, -0.225, -0.109,
                   0.038, 0.209, 0.376, 0.58, 0.906, 1.141, 1.41, 1.713, 2.05, 2.424, 2.835, 3.287, 3.779, 4.313, 4.89,
                   5.513, 6.187, 6.917],
    (0.7, "nom"): [-1.143, -0.991, -0.882, -0.802, -0.719, -0.64, -0.572, -0.513, -0.455, -0.393, -0.318, -0.227,
                   -0.111, 0.036, 0.207, 0.374, 0.578, 0.904, 1.139, 1.408, 1.711, 2.048, 2.421, 2.833, 3.284, 3.776,
                   4.31, 4.888, 5.511, 6.185, 6.916],
}
# Write (wr.py): a boosted-WWL (1.0 V) nmos_sram write leaves '1' at 0.631 V (TT 27C) / 0.645 V (TT 85C) /
# 0.619 V (SS 27C) after the WWL falls, '0' at -0.072 V; 99 % of final in 44.3 ps TT, 45.3 ps SS (8-row WBL,
# 750 ohm + 2.4 fF). Energy of one '1' write (WBL source + WWL) 0.52 fJ, below the formula's 0.70 (kept: conservative).
V_WRITE1 = {27: 0.6308, 85: 0.6452}
# Critic fix (wr2.py, measured): the write level falls when cold. SS: 0.591 (-40 C), 0.608 (0 C), 0.619 (27 C),
# 0.636 (85 C); TT: 0.604 / 0.621 / 0.631 / 0.645. Design corner = min over {SS, TT} x {0, 27, 85} C per leakage
# table: 85 C tables start at 0.636 (SS 85 C), the cold/27 C table starts at 0.608 (SS 0 C). -40 C is A4-V1.
V_WRITE1_SS = {0: 0.608, 27: 0.6187, 85: 0.6364}
V_WRITE0 = -0.072
T_WFET_PS = 45.3
# TG dead zone (sw.py, ret.py): a 1-fin RVT TG whose n gate is the stored node and p gate the inverter output does
# NOT pass the V/3 level of the 4-level row drive once the node droops: 0.52 V -> 6-13 mV error after a 1.13 ns slot
# (TT and SS 85C); 0.55 V -> settles from below only; 0.60 V -> 0.1 % in 732 ps (SS 85C, from 0.7 V). So a stored '1'
# is valid only down to V_MIN1 = 0.60 V (round 1 assumed 0.50 V: dv_bit 0.2). A stored '0' is valid up to ~0.20 V
# (derived: the N-TG nmos sub-threshold current against the 1-fin ground leg stays < 0.7 mV on the plate).
# Critic fix (crit_a4/dz.py, measured SS/TT x 0/27/85 C): the zone is worse COLD. From 0.7 V at node 0.60 V: 732 ps
# (SS 85), 896 (SS 27), 996 (SS 0; 12 % slot margin); at 0.58 V it fails at SS 27/0 C. But the row driver returns X to
# 0 V between slots (gc3t/gc_cs have no reset TG), so the plate always starts from 0: from 0 at 0.58 V settles in
# 645 (SS 85) / 779 (SS 27) / 856 ps (SS 0), all < 0.16 mV. Criterion = from-0 settling, so V_MIN1 = 0.58 V for v2.
V_MIN1, V_MAX0 = 0.58, 0.20

STORAGE = {   # um2 per bit
    "sram6t": dict(bit_um2=1.25 * k.get("sram6t_bitcell_um2"),   # 112-class foundry cell with assist (LIT_ASAP7 5)
                   refresh=False, static=True),
    "gain_bit": dict(bit_um2=4 * LOGIC_T_UM2,                         # 4T logic rule: write + inverter + read
                     refresh=True, static=False, node_fins=5, nodes=1, crowbar=True),
    "gain_bit_sramrule": dict(bit_um2=4 / 6 * 1.25 * k.get("sram6t_bitcell_um2"), tg_um2=0.02,  # optimistic bound
                              refresh=True, static=False, node_fins=5, nodes=1, crowbar=True),
    "gain_dual_p": dict(bit_um2=6 * LOGIC_T_UM2, n_tg=1,              # Q,Qb nodes: write+read each,
                        refresh=True, static=False, node_fins=3, nodes=2, crowbar=True),  # node = PMOS switch gate
    # round 2 (A4): constant-sum differential pair shares ONE 4T bit (node S drives the P column's TG-n and the
    # complement column's TG-p / ground leg; the inverter output drives the other halves): 2T per column-bit.
    # Crosspoint per column-bit = 1 TG to the row line + 1 NMOS ground leg (n_tg 1.5); the row driver returns the
    # line to 0 for reset (no third TG). WBL held at VDD between writes (hold-high retention).
    "gain_cs": dict(bit_um2=2 * LOGIC_T_UM2, n_tg=1.5, refresh=True, static=False, node_fins=5, nodes=1, crowbar=True,
                    share_pair=True, hold=0.7),
    "gain_3t": dict(bit_um2=4 * LOGIC_T_UM2, n_tg=1.5, refresh=True, static=False, node_fins=5, nodes=1, crowbar=True,
                    hold=0.7),   # same crosspoint, one bit per column (any topology)
    "latch": dict(bit_um2=0.2187, refresh=False, static=True, leak_fins=4, leak_key="nfet_ileak_per_fin_nA"),  # DHLx1
    "latch_custom": dict(bit_um2=6 * LOGIC_T_UM2, refresh=False, static=True, leak_fins=3,   # cross-coupled + pass
                         leak_key="nfet_ileak_per_fin_nA_sram"),                             # SRAM-Vt devices
}
CAPS = ("mom_binary", "mom_c2c", "mos_binary")

_B = dict(storage="gain_bit", cap="mom_binary", cu_fF=1.0, mos_fins=8, mos_ov=2.0, v_inv=0.45, cap_rail=0.7,
          tg_um2=2 * LOGIC_T_UM2, n_tg=3, route_overhead=1.3, share_banks=False, dv_bit=0.2, mom_density=None,
          inv_vt="sram", mom_over_fF_per_um2=0.0, active_col=False, ret_model="v1")


def _o(prov, **kw):
    return dict(params=dict(_B, **kw), provenance=prov)


_MOS = dict(cap="mos_binary", mos_fins=32)
OPTIONS = {
    "sram6t_binary_caps": _o("projected: sky130 passive macro cell (measured topology) ported: 6T bits steer binary "
                             "MOM units; violates the user's no-SRAM-in-tile constraint (ARCH_METRIC 2)",
                             storage="sram6t"),
    "sram6t_c2c": _o("projected: 6T + C-2C ladder (27i4, Intel JSSC 2023, PICO-RAM); dominated whenever kT/C binds",
                     storage="sram6t", cap="mom_c2c"),
    "sram6t_mos_caps": _o("projected: 6T bits + MOS gate units; reference for what the no-SRAM constraint costs",
                          storage="sram6t", **_MOS),
    "gaincell_mom_caps": _o("CO-LEAD (lowest risk): dynamic 4T logic-rule gain-cell bits (27i6; leakage measured "
                            "here) steer binary 2 fF/um2 MOM units; local refresh", storage="gain_bit"),
    "gaincell_mom_caps_mom6": _o("CO-LEAD (density): as gaincell_mom_caps, min-pitch MOM on M2-M5 (4.78 fF/um2, "
                                 "derived geometric upper bound; M1 is taken by the cells)",
                                 storage="gain_bit", mom_density=5.97645 * 4 / 5),
    "gaincell_c2c": _o("projected: gain-cell bits + C-2C ladder (27i4); dominated whenever kT/C binds",
                       storage="gain_bit", cap="mom_c2c"),
    "latch_mos_caps": _o("projected: std-cell latch DHLx1 (0.2187 um2, liberty) + MOS units; NEEDS USER RULING "
                         "(a static bistable is an SRAM cell without access FETs)", storage="latch", **_MOS),
    "customlatch_mos_caps": _o("projected: logic-rule cross-coupled latch (6T SRAM-Vt, 0.131 um2) + MOS units; "
                               "NEEDS USER RULING (it is an SRAM bitcell drawn in logic rules)",
                               storage="latch_custom", **_MOS),
    "gaincell_mos_caps": _o("VIABLE (old default; dominated by min-pitch MOM and by the 0.8 V rail): logic-rule gain-cell bits + SLVT MOS gate units in "
                            "inversion [0.45, 0.7] V (C(V) measured here; nonlinearity/mismatch unverified in "
                            "transient; 15g4/13p2/15n warn)", storage="gain_bit", **_MOS),
    "gaincell_mos_caps_sramrule": _o("optimistic bound of gaincell_mos_caps: gain bit at SRAM pushed rules "
                                     "(0.019 um2, TG 0.02), not drawable in logic rules", storage="gain_bit_sramrule",
                                     **_MOS),
    "gaincell_mos_r08": _o("CO-LEAD where kT/C binds: gain-cell + MOS units on a 0.8 V cap rail, window [0.45, 0.8] (C_eq 2x); storage and "
                           "TGs on the 0.8 V rail; DC gate stress unverified (TDDB/BTI)", storage="gain_bit",
                           cap_rail=0.8, **_MOS),
    "gaincell_mos_r08_vlo035": _o("as gaincell_mos_r08 with v_lo 0.35 V: window [0.35, 0.8] (C_eq 3.2x, C +-9 %)",
                                  storage="gain_bit", cap_rail=0.8, v_inv=0.35, **_MOS),
    "gaincell_mos_plus_mom": _o("gain-cell + MOS units with M3-M5 MOM (1.2 fF/um2) stacked over the unit footprint, "
                                "driven in the same window (caged per 20w6a)", storage="gain_bit",
                                mom_over_fF_per_um2=1.2, **_MOS),
    "dualp_mos_caps": _o("dual-rail gain bit (Q, Qb nodes ARE the gates of two PMOS switches to v_hi / v_lo): no "
                         "inverter, no NMOS TG halves", storage="gain_dual_p", **_MOS),
    "gaincell_mom_shared_bank": _o("gain-cell bits, two storage banks sharing one MOM unit set (CAP-RAM S=2, 27i7): "
                                   "for double-buffered streaming only", storage="gain_bit", share_banks=True),
    "gaincell_mos_shared_bank": _o("gain-cell bits x 2 banks sharing MOS units", storage="gain_bit",
                                   share_banks=True, **_MOS),
    # --- round 2 (A4): fewer transistors per cell, measured write / retention / TG dead zone (N3_r2.md) ---------
    "gaincell_mom6_v2": _o("derived: the DEFAULT cell re-modelled with the round-2 ESPice data (write level 0.645 V, "
                           "TG dead zone 0.60 V, real-load node leakage, WBL hold 0): same area, design retention "
                           "0.31 us (round 1 claimed 1.32 us), more refresh power", mom_density=5.97645 * 4 / 5,
                           ret_model="v2"),
    "gc3t_mom6": _o("derived (ESPice): 4T gain bit + 3T crosspoint (TG + NMOS ground leg, row-driver reset), WBL "
                    "held high: 7T per column-bit (round 1: 10T); any column topology", storage="gain_3t",
                    mom_density=5.97645 * 4 / 5, ret_model="v2"),
    "gc_cs_mom6": _o("r2 (needs w_enc='complement': 15 units/slice; else it IS gc3t) (derived, ESPice): constant-sum differential pair shares one 4T bit (complement "
                     "column = inverted bits, AD-DiffAmp-1 / N5 diff topology), 3T crosspoint, WBL hold-high: 5T per "
                     "column-bit, 80T per logical W8 weight (round 1: 160T); half the write bitlines",
                     storage="gain_cs", mom_density=5.97645 * 4 / 5, ret_model="v2"),
    "gc_cs_mom7": _o("projected (upper bound): gc_cs_mom6 + MOM on M7 (64 nm SADP, ~0.75 fF/um2 per 1/pitch law "
                     "from the M1-M5 derivation; M6 kept for column/row straps): 5.53 fF/um2, not extracted",
                     storage="gain_cs", mom_density=5.97645 * 4 / 5 + 0.747, ret_model="v2"),
}
DEFAULT = "gaincell_mom_caps_mom6"   # revised after critics: linear, wins where density or energy binds
SWEEP = dict(cu_fF=[0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 4.0, 8.0, 16.0], mos_fins=[4, 8, 16, 32])


def _interp(tab, v):
    xs = sorted(tab)
    v = min(max(v, xs[0]), xs[-1])
    for a, b in zip(xs, xs[1:]):
        if v <= b:
            return tab[a] + (tab[b] - tab[a]) * (v - a) / (b - a)
    return tab[xs[-1]]


def mos_c_avg_aF(v_lo, v_hi):
    """Mean C per fin over the drive swing (aF), midpoint rule on the measured C(V)."""
    n = 10
    return sum(_interp(C_MOS_AF_PER_FIN, v_lo + (v_hi - v_lo) * (i + 0.5) / n) for i in range(n)) / n


def mos_k(p, vdd=None):
    """Signal-equivalent factor of the [v_lo, rail] swing vs the VDD_nom/2 swing n2/n5 assume.
    The rail is fixed (cap_rail), so k does not move with logic VDD (vdd kept for the old signature)."""
    return max(1e-6, (max(0.0, p["cap_rail"] - p["v_inv"]) / (k.get("vdd_nom") / 2)) ** 2)


def mos_unit(p, units=7):
    """Per MOS unit (fF): real gate C, column-side S/D parasitic, stacked MOM, signal-equivalent C."""
    f = p["mos_fins"]
    c_real = f * mos_c_avg_aF(p["v_inv"], p["cap_rail"]) * 1e-3
    c_par = 0.0 if p["active_col"] else f * (units + 1) / units * k.get("switch_coff_aF_per_fin") * 1e-3
    c_mom = f * FIN_FP_UM2 * p["mos_ov"] * p["mom_over_fF_per_um2"]
    c_sig = c_real + c_mom
    c_eq = c_sig * mos_k(p) * c_sig / (c_sig + c_par)     # SNR: Q^2/(kT C_tot) with C_tot = C_sig + C_par
    return dict(c_real=c_real, c_par=c_par, c_mom=c_mom, c_eq=c_eq)


def mos_cu_eq_fF(p, vdd=None):
    """Equivalent unit cap (fF) the n2/n5 laws should see. Set the design's cu_fF to this value."""
    return mos_unit(p)["c_eq"]


def mos_unit_sigma(p, vdd=None):
    """Unit charge sigma: Vt term (derived: measured C(V), projected A_VT) rss geometric term (projected A_C)."""
    wl = p["mos_fins"] * W_EFF_UM * L_UM
    s_vt = k.get("avt_mV_um") * 1e-3 / math.sqrt(wl)
    rail, vi = p["cap_rail"], p["v_inv"]
    q = mos_c_avg_aF(vi, rail) * (rail - vi)
    vt_term = s_vt * abs(_interp(C_MOS_AF_PER_FIN, vi) - _interp(C_MOS_AF_PER_FIN, rail)) / q
    return math.hypot(vt_term, A_C_PCT_UM / 100 / math.sqrt(wl))


for _opt in OPTIONS.values():          # MOS options: cu_fF (read by n2 energy / n5 mismatch) = equivalent unit
    if _opt["params"]["cap"] == "mos_binary":
        _opt["params"]["cu_fF"] = round(mos_cu_eq_fF(_opt["params"]), 4)


def _v_store(p):
    """Storage + TG domain: pinned to the cap rail for MOS units (an off TG must see its full gate)."""
    return p["cap_rail"] if p["cap"] == "mos_binary" else k.get("vdd_nom")


def t_ret_us(p, corner="design"):
    """Dynamic bit: time for a stored '1' to droop by dv_bit (us). corner: 'nom' (TT 27C, nominal Vt) or
    'design' (85C, 6-sigma write FET: what refresh is sized to)."""
    st = STORAGE[p["storage"]]
    v_hi = _v_store(p)
    iw, ig = (I_WRITE_FET_PA, I_GATE_PA_PER_FIN) if corner == "nom" else (I_WRITE_TAIL85_PA, I_GATE85_PA_PER_FIN)
    c_node = st["node_fins"] * k.get("nfet_cgg_per_fin_aF") * 1e-18
    n, t = 20, 0.0
    for i in range(n):                      # integrate dt = C dV / I(V) from v_hi down by dv_bit
        v = v_hi - p["dv_bit"] * (i + 0.5) / n
        i_pa = _interp(iw, v) + st["node_fins"] * _interp(ig, v)
        t += c_node * (p["dv_bit"] / n) / (i_pa * 1e-12)
    return t * 1e6


def _hold(p, st):
    return st.get("hold", 0.0)


def t_ret_v2_us(p, st, corner="design"):
    """Round-2 retention (us): min over the stored states of the time to leave the valid window, integrating
    dt = C_node dV / I_net(V) on the MEASURED real-load node current. '1': V_WRITE1 -> V_MIN1 (TG dead zone);
    '0': V_WRITE0 -> V_MAX0. design = 85 C, min over nominal and 6-sigma write FETs; nom = 27 C nominal."""
    c_node = (st["node_fins"] * k.get("nfet_cgg_per_fin_aF") + k.get("switch_coff_aF_per_fin")) * 1e-18
    hold = _hold(p, st)
    tabs = ([NODE_LEAK85_PA[(hold, "nom")], NODE_LEAK85_PA[(hold, "6s")]] if corner == "design"
            else [NODE_LEAK27_PA[(hold, "nom")]])
    v1s = ([V_WRITE1_SS[85], V_WRITE1_SS[85], V_WRITE1_SS[0]] if corner == "design" else [V_WRITE1[27]])
    if corner == "design":
        tabs = tabs + [NODE_LEAK27_PA[(hold, "nom")]]   # cold: 27 C leak table (gate tunnelling ~T-flat) from 0.608 V
    best = math.inf
    for v1, tab in zip(v1s, tabs):
        lk = dict(zip(_LV, tab))
        for a, b, sign in ((v1, V_MIN1, 1.0), (V_WRITE0, V_MAX0, -1.0)):   # sign: + current moves '1' down
            n, t = 40, 0.0
            for i in range(n):
                v = a + (b - a) * (i + 0.5) / n
                i_pa = sign * _interp(lk, v)
                if i_pa <= 1e-6:            # leakage pushes this state back into its window: holds
                    t = math.inf
                    break
                t += c_node * abs(b - a) / n / (i_pa * 1e-12)
            best = min(best, t)
    return best * 1e6


def crowbar_v2_nW_per_bit(p):
    """Crowbar of the bit inverter over the '1' window actually used: droop 0.7 - V_WRITE1 .. 0.7 - V_MIN1."""
    tab, lo, hi, n = CROWBAR_NA[p["inv_vt"]], 0.7 - V_WRITE1[85], 0.7 - V_MIN1, 20   # widest window (conservative)
    return 0.5 * sum(_interp(tab, lo + (hi - lo) * (i + 0.5) / n) for i in range(n)) / n * 0.7


def crowbar_nW_per_bit(p):
    """Mean supply current of the stage a drooping '1' drives, over droop [0, dv_bit], x rail, x 1/2 ('1' bits)."""
    tab = CROWBAR_NA[p["inv_vt"]]
    n = 20
    i_na = sum(_interp(tab, p["dv_bit"] * (i + 0.5) / n) for i in range(n)) / n
    return 0.5 * i_na * _v_store(p)


def _units(p, b):
    # w_enc "complement" (offset-binary / constant-sum bits): b magnitude bits per slice, 2^b - 1 units (15 at b=4);
    # default "sign": sign rides the +/- lines (N3.md, n2/n5), 2^(b-1) - 1 units (projected pricing, critic A4)
    if p["cap"] == "mom_c2c":
        return 3 * (b - 1) - 1
    return 2 ** b - 1 if p.get("w_enc") == "complement" else 2 ** (b - 1) - 1


def _pair_shared(p, st):
    """One bit per pair needs complement bits on the two columns: a sign-steering diff (P = w+, N = w-), the
    repo's encoding, stores independent bits per column (critic A4). So both topo 'diff' AND w_enc 'complement'."""
    return bool(st.get("share_pair")) and p.get("topo", "diff") == "diff" and p.get("w_enc", "sign") == "complement"


def cell(p, vdd, fmt):
    st = STORAGE[p["storage"]]
    wb, S, R = fmt["wbits"], fmt["slices"], int(p["rows"])
    sb = [min(4, wb - 4 * i) if wb > 4 else wb for i in range(S)]
    units = sum(_units(p, b) for b in sb)
    mos = p["cap"] == "mos_binary"
    banks_db = 2 if p.get("double_buffer") else 1
    share = banks_db if p["share_banks"] else 1
    vst = _v_store(p)
    # capacitors
    if mos:
        mu = mos_unit(p, _units(p, sb[0]))
        c_unit_eq, c_unit_real = mu["c_eq"], mu["c_real"] + mu["c_mom"] + mu["c_par"]
        feol_caps, beol = units * p["mos_fins"] * FIN_FP_UM2 * p["mos_ov"], 0.0
    else:
        c_unit_eq = c_unit_real = p["cu_fF"]
        feol_caps = 0.0
        beol = units * p["cu_fF"] / (p["mom_density"] or k.get("mom_cap_density_fF_per_um2"))
    tg = st.get("tg_um2", p["tg_um2"])                       # logic-rule TG (2T) unless the storage overrides
    n_tg = st.get("n_tg", p["n_tg"])
    # constant-sum pair sharing needs a fully differential pair (n5 topo "diff"); else one bit per column
    pair = 2 if _pair_shared(p, st) else 1
    bit_um2 = st["bit_um2"] * (2 if st.get("share_pair") and pair == 1 else 1)
    feol_store = wb * (bit_um2 + n_tg * tg) * p["route_overhead"]
    site = max(share * feol_store + feol_caps, beol)          # one cap set + `share` storage banks
    area0 = site / share                                       # per weight per bank (core x banks)
    n_w = 2 if p["cap"] == "mom_c2c" else _units(p, sb[0])
    c_w, c_w_real = n_w * c_unit_eq, n_w * c_unit_real
    # write path
    pitch = math.sqrt(area0)
    c_wbl = R * (k.get("switch_coff_aF_per_fin") * 1e-3 + pitch * k.get("wire_c_fF_per_um"))       # fF
    c_wwl = k.get("nfet_cgg_per_fin_aF") * 1e-3 + pitch / max(1, wb) * k.get("wire_c_fF_per_um")   # fF per bit
    if st["static"]:
        e_bit = c_wbl * vst ** 2 + 2 * c_wwl * vst ** 2
    else:
        e_bit = st["nodes"] * (0.5 * c_wbl * vst ** 2 + c_wwl * (vst + 0.3) ** 2)
    tau = (k.get("switch_ron_ohm_per_fin") / 8 + k.get("wire_r_ohm_per_um") * R * pitch / 2) * c_wbl * 1e-15
    v2 = p.get("ret_model") == "v2" and st["refresh"] and not mos and vst == 0.7
    if v2:   # decode in liberty FO4 (logic, CHAR.md), and the write FET's own measured settling (99 %, SS)
        fo4 = k.get("fo4_delay_ps_lib") * k.get("fo4_delay_ps", vdd) / k.get("fo4_delay_ps")
        t_row = 2 * fo4 * 1e-3 + max(5 * tau * 1e9, T_WFET_PS * 1e-3)
    else:
        t_row = 2 * k.get("fo4_delay_ps", vdd) * 1e-3 + 5 * tau * 1e9                                # ns
    # retention / refresh / leakage (at nominal: the core applies n9 leak_scale)
    if v2:
        tr_nom = t_ret_v2_us(p, st, "nom")
        tr = min(t_ret_v2_us(p, st), tr_nom)      # design = worst of 85 C (nominal, 6 sigma) and 27 C (lower write level)
        e_ref = e_bit + st["nodes"] * (0.5 * c_wbl * vst ** 2 + k.get("comparator_energy_fJ"))
        p_ref = wb * e_ref * 1e-15 / (tr * 1e-6) * 1e9 / pair       # per counted weight: a pair shares one bit
        p_cb = wb * crowbar_v2_nW_per_bit(p) / pair
        leak = p_ref + p_cb
        occ = 2 * R * t_row * 1e-3 / tr
        e_bit = e_bit / pair                                         # model counts both columns' bits
    elif st["refresh"]:
        tr, tr_nom = t_ret_us(p), t_ret_us(p, "nom")
        e_ref = e_bit + st["nodes"] * (0.5 * c_wbl * vst ** 2 + k.get("comparator_energy_fJ"))   # restore + read + SA
        p_ref = wb * e_ref * 1e-15 / (tr * 1e-6) * 1e9                            # nW per weight per bank
        p_cb = wb * crowbar_nW_per_bit(p) if st.get("crowbar") else 0.0
        leak = p_ref + p_cb
        occ = 2 * R * t_row * 1e-3 / tr
    else:
        tr = tr_nom = math.inf
        p_ref = p_cb = occ = 0.0
        leak = wb * st.get("leak_fins", 3) * k.get(st.get("leak_key", "nfet_ileak_per_fin_nA_sram")) * vst  # nW
    area = area0 / (1 - occ) if occ < 0.95 else 1e12     # refresh cannot keep up: no tile fits
    return dict(area_um2_per_weight=area, c_weight_fF=c_w, e_write_fJ_per_bit=e_bit, t_write_row_ns=t_row,
                leak_nW_per_weight=leak, feol_um2=feol_store + feol_caps, beol_um2=beol, site_um2=site,
                feol_store_um2=feol_store, banks_sharing_caps=share, t_ret_us=tr, t_ret_nom_us=tr_nom,
                refresh_occ=occ, refresh_nW=p_ref, crowbar_nW=p_cb, units_per_weight=units,
                c_unit_eq_fF=c_unit_eq, c_weight_real_fF=c_w_real, settle_c_ratio=c_w_real / c_w,
                v_lo_V=p["v_inv"] if mos else None, v_hi_V=p["cap_rail"] if mos else None,
                mos_k=mos_k(p) if mos else 1.0, mos_unit_sigma=mos_unit_sigma(p) if mos else None,
                cu_fF_expected=mos_cu_eq_fF(p) if mos else p["cu_fF"], sram_in_tile=p["storage"] == "sram6t",
                transistors_per_weight=transistors_per_weight(p, wb), pair_shared=pair == 2, ret_model="v2" if v2 else "v1")


def transistors_per_weight(p, wb=8):
    """Cell-array transistors per LOGICAL weight of a fully differential pair (both columns, all slices' bits).
    Storage + crosspoint switches only (refresh sense amps, drivers, converters are periphery)."""
    st = STORAGE[p["storage"]]
    t_bit = {"sram6t": 6, "gain_bit": 4, "gain_bit_sramrule": 4, "gain_dual_p": 4, "latch": 8, "latch_custom": 6,
             "gain_cs": 4, "gain_3t": 4}[p["storage"]]
    t_sw = 2 * st.get("n_tg", p["n_tg"])
    shared = _pair_shared(p, st)
    return int(round(wb * (t_bit * (1 if shared else 2) + 2 * t_sw)))


# --- analog-level weights (not OPTIONS: need an N2 current/log domain) -----------------------------
def analog_hold_us(c_fF, dv_mV, v=0.4, residual=1.0, corner="nom"):
    """Hold of an analog gate-stored weight before droop dv (us); measured write-FET + 2-fin gate leakage.
    residual = fraction of the COMMON droop a ratiometric reference / pre-distortion does not cancel (27d7).
    corner 'design': the 6-sigma write FET at 85C; only the nominal 85C part is common (cancellable)."""
    if corner == "nom":
        i_pa = (_interp(I_WRITE_FET_PA, v) + 2 * _interp(I_GATE_PA_PER_FIN, v)) * residual
    else:
        i_pa = (_interp(I_WRITE_TAIL85_PA, v) - (1 - residual) * _interp(I_WRITE85_PA, v)
                + 2 * _interp(I_GATE85_PA_PER_FIN, v))
    return c_fF * 1e-15 * dv_mV * 1e-3 / (i_pa * 1e-12) * 1e6


def analog_copier_area(p_rows=128, gm_id=15.0, levels=7, t_copy_ns=5.5, feol_um2=0.03, residual=1.0, mos_cs=True,
                       corner="nom"):
    """Copier gain cell (LIT_STREAMING_LOG cand. B): 0.5 LSB current droop budget dV = 1/(2 levels gm/ID).
    Refresh = re-copy, occupancy R t_copy / t_hold, charged as area; returns the area-optimal C_S.
    mos_cs: C_S is the read FET's own gate (~24 fF/um2 footprint incl. ov 2), else 2 fF/um2 MOM."""
    dv_mV = 1e3 / (2 * levels * gm_id)
    dens = 69.68e-3 / (FIN_FP_UM2 * 2.0) if mos_cs else k.get("mom_cap_density_fF_per_um2")
    best = None
    for c in [0.25 * i for i in range(1, 2000)]:
        hold = analog_hold_us(c, dv_mV, residual=residual, corner=corner)
        occ = p_rows * t_copy_ns * 1e-3 / hold
        if occ < 1:
            a = (feol_um2 + c / dens) / (1 - occ)
            if best is None or a < best[0]:
                best = (a, c, hold, occ)
    if best is None:
        return dict(area_um2=math.inf, gm_id=gm_id, residual=residual, corner=corner)
    return dict(area_um2=round(best[0], 3), c_s_fF=best[1], hold_us=round(best[2], 2), occ=round(best[3], 3),
                dv_mV=round(dv_mV, 2), gm_id=gm_id, residual=residual, corner=corner)


# --- self-check and option scoring ---------------------------------------------------------------
@contextlib.contextmanager
def _real_c_timing(mod):
    """Re-time n2 with the real column charge (settle_c_ratio): energy and SNR keep C_eq, timing
    (t_word, slot, tau) comes from n2's own law called with the real per-weight C. Undone on exit."""
    orig = mod.array

    def array(p, vdd, fmt, cell_, rows):
        out = orig(p, vdd, fmt, cell_, rows)
        r = cell_.get("settle_c_ratio", 1.0)
        if abs(r - 1) < 1e-9:
            return out
        re = orig(dict(p, cu_fF=p["cu_fF"] * r), vdd, fmt, dict(cell_, c_weight_fF=cell_["c_weight_real_fF"]), rows)
        return dict(out, **{x: re[x] for x in ("t_word_ns", "slot_ns", "tau_ns") if x in re})
    mod.array = array
    try:
        yield
    finally:
        mod.array = orig


def _score(nodes, params, frozen, knobs=None, real_c=True):
    """Design score with this N3 option fixed. frozen=True scores against the shipped nodes/default/*
    (stable reference); False against the live node modules. real_c: re-time n2 with the real C."""
    import importlib
    import sys
    from arch_eval import design, model
    saved = {}
    if frozen:
        for nid in design.NODES:
            if nid != "n3_cell":
                name = f"arch_eval.nodes.{nid}"
                saved[name] = sys.modules.get(name)
                sys.modules[name] = importlib.import_module(f"arch_eval.nodes.default.{nid}")
    n2 = importlib.import_module("arch_eval.nodes.default.n2_domain" if frozen else "arch_eval.nodes.n2_domain")
    try:
        with _real_c_timing(n2) if real_c else contextlib.nullcontext():
            return model.evaluate(design.make(nodes, params), knobs)
    finally:
        for name, m in saved.items():
            if m is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = m


REGIMES = ("frozen", "frozen_nocap", "frozen_g43", "live_gated", "live_fine")


def score_option(opt, regime="frozen", knobs=None, real_c=True):
    """Best design over a grid with this N3 option fixed -> {"streaming": (score, design), "resident": ...}.
    frozen*: shipped nodes, W4; frozen_g43 adds the N8 43 dB gate (+1 dB die margin) with a 10-b ADC.
    live_gated: live nodes with the N8 gate satisfiable (W8 formats, k_sigma 32, adc_bits 10-14)."""
    import itertools
    from arch_eval import metric
    o = OPTIONS[opt]["params"]
    mos = o["cap"] == "mos_binary"
    big = regime in ("frozen_g43", "live_gated", "live_fine")                 # 43-dB-class gate: caps grow ~30x
    if regime == "live_gated":
        dens = ([dict(mos_fins=2 ** i) for i in (4, 5, 6, 8, 10, 12)] if mos
                else [dict(cu_fF=2.0 ** i) for i in (-1, 0, 1, 3, 5, 7)])
    elif regime == "live_fine":   # refinement around the live_gated optimum (its grid edges: rows 32, 14 b)
        dens = [dict(mos_fins=f) for f in (96, 128, 192, 256, 384, 512)] if mos else \
            [dict(cu_fF=c) for c in (3.0, 4.0, 6.0, 8.0, 12.0, 16.0)]
    else:
        dens = ([dict(mos_fins=2 ** i) for i in range(2, 13 if big else 9)] if mos
                else [dict(cu_fF=2.0 ** i) for i in range(-2, 8 if big else 5)])
    extra = dict(snr_target_db=44.0, adc_bits=10) if regime == "frozen_g43" else {}
    if regime.startswith("frozen"):
        modes = [dict(mode="streaming", double_buffer=False), dict(mode="streaming", double_buffer=True),
                 dict(mode="resident", double_buffer=False)]
        nodes1 = [dict(n3_cell=opt, n1_system="streaming")]
        grid = dict(rows=[32, 64, 128, 256], adc_share=[4, 8], misc=[{}])
    elif regime == "live_fine":
        modes = [dict(double_buffer=False)]
        nodes1 = [dict(n3_cell=opt, n1_system="stream_single", n4_formats="w8a8_lead_amp")]
        grid = dict(rows=[16, 32, 64, 128], adc_share=[4, 8], misc=[dict(k_sigma=32.0, adc_bits=b) for b in (13, 14, 15, 16)])
    else:
        modes = [dict(double_buffer=False), dict(double_buffer=True)]
        nodes1 = [dict(n3_cell=opt, n1_system=n, n4_formats=f) for n in ("stream_single", "resident")
                  for f in ("w8a8_lead_amp", "w8a8_2slice")]
        grid = dict(rows=[32, 64, 128], adc_share=[8, 32], misc=[dict(k_sigma=32.0, adc_bits=b) for b in (10, 12, 14)])
    if regime == "frozen_nocap":
        knobs = dict(knobs or metric.KNOBS, power_cap_W_per_mm2=1e9)
    top = {}
    for nodes, m, dn, rows, sh, mi in itertools.product(nodes1, modes, dens, grid["rows"], grid["adc_share"],
                                                        grid["misc"]):
        par = dict(kv_bits=8, **m, **dn, rows=rows, adc_share=sh, **mi, **extra)
        if mos:
            par["cu_fF"] = mos_cu_eq_fF(dict(o, **par))
        s = _score(nodes, par, regime.startswith("frozen"), knobs, real_c)
        fam = "resident" if "resident" in (par.get("mode"), nodes.get("n1_system")) else "streaming"
        if fam not in top or metric.better(s, top[fam][0]):
            top[fam] = (s, dict(nodes=nodes, params=par))
    return top   # ARCH_METRIC streams (user decision): "streaming" is the headline


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    fmt4 = dict(wbits=4, slices=1)
    p = lambda o, **kw: dict(OPTIONS[o]["params"], rows=128, **kw)   # noqa: E731
    c = cell(p("sram6t_binary_caps"), 0.7, fmt4)
    assert abs(c["beol_um2"] - 7 * 1.0 / k.get("mom_cap_density_fF_per_um2")) < 1e-9 and c["refresh_occ"] == 0
    g = cell(p("gaincell_mom_caps"), 0.7, fmt4)
    assert abs(g["area_um2_per_weight"] * (1 - g["refresh_occ"]) / c["area_um2_per_weight"] - 1) < 1e-9  # BEOL-bound
    assert 1 < g["t_ret_nom_us"] < 100 and g["t_ret_us"] < g["t_ret_nom_us"] / 4, (g["t_ret_nom_us"], g["t_ret_us"])
    sh = cell(p("gaincell_mom_shared_bank", double_buffer=True), 0.7, fmt4)
    assert abs(sh["site_um2"] - g["site_um2"]) < 1e-9 and sh["area_um2_per_weight"] < 0.6 * g["area_um2_per_weight"]
    m = cell(p("gaincell_mos_caps"), 0.7, fmt4)
    assert m["area_um2_per_weight"] < g["area_um2_per_weight"] and m["settle_c_ratio"] > 1.5
    assert cell(p("gaincell_mos_caps"), 0.45, fmt4)["c_weight_fF"] == m["c_weight_fF"]      # fixed drive rail
    assert cell(p("gaincell_mos_caps_sramrule"), 0.7, fmt4)["area_um2_per_weight"] < m["area_um2_per_weight"]
    r8 = cell(p("gaincell_mos_r08"), 0.7, fmt4)
    assert 1.8 < r8["c_unit_eq_fF"] / m["c_unit_eq_fF"] < 2.2                       # window [0.45, 0.8]: ~2x
    assert cell(p("gaincell_mos_plus_mom"), 0.7, fmt4)["c_weight_fF"] > m["c_weight_fF"]
    assert m["crowbar_nW"] > 0 and cell(p("latch_mos_caps"), 0.7, fmt4)["crowbar_nW"] == 0
    assert 0.004 < mos_unit_sigma(OPTIONS["gaincell_mos_caps"]["params"]) < 0.012   # geometric term dominates
    assert cell(p("gaincell_c2c"), 0.7, fmt4)["c_weight_fF"] < g["c_weight_fF"]
    w8 = cell(p("gaincell_mom_caps"), 0.7, dict(wbits=8, slices=2))
    assert w8["units_per_weight"] == 14
    cp, cd = analog_copier_area(gm_id=5, residual=0.15), analog_copier_area(gm_id=5, residual=0.15, corner="design")
    assert cd["area_um2"] > 5 * cp["area_um2"]                                      # the 6-sigma 85C tail decides
    # round 2 (A4): sharing halves storage, v2 retention is measured-load and dead-zone limited
    f8 = dict(wbits=8, slices=2)
    q = lambda o, **kw: dict(OPTIONS[o]["params"], rows=8, **kw)   # noqa: E731
    d1, v2, cs = (cell(q(o), 0.7, f8) for o in ("gaincell_mom_caps_mom6", "gaincell_mom6_v2", "gc_cs_mom6"))
    assert d1["transistors_per_weight"] == 160 and cs["transistors_per_weight"] == 112, cs["transistors_per_weight"]
    cc = cell(q("gc_cs_mom6", w_enc="complement"), 0.7, f8)                    # sharing only with complement bits
    assert cc["transistors_per_weight"] == 80 and cc["units_per_weight"] == 30 and cs["units_per_weight"] == 14
    assert cell(q("gc_cs_mom6", topo="pseudo", w_enc="complement"), 0.7, f8)["transistors_per_weight"] == 112
    assert abs(cc["feol_store_um2"] / d1["feol_store_um2"] - 0.5) < 1e-9 and cs["beol_um2"] == d1["beol_um2"]
    assert cc["beol_um2"] > 2 * cs["beol_um2"]                                  # complement doubles the binding MOM
    assert abs(v2["area_um2_per_weight"] / d1["area_um2_per_weight"] - 1) < 0.01 and 0.25 < v2["t_ret_us"] < 0.5, v2["t_ret_us"]
    assert cs["t_ret_us"] > 3 * v2["t_ret_us"] and cs["leak_nW_per_weight"] < v2["leak_nW_per_weight"] / 4
    print("PASS n3 self-check")
    for o in OPTIONS:
        r = cell(p(o), 0.7, fmt4)
        print(f"  {o:27s} area {r['area_um2_per_weight']:.3f} um2 (store {r['feol_store_um2']:.3f})  c_w {r['c_weight_fF']:.2f} fF"
              f" (real {r['c_weight_real_fF']:.2f})  E_wr {r['e_write_fJ_per_bit']:.2f} fJ/b  t_row {r['t_write_row_ns']:.3f} ns"
              f"  leak {r['leak_nW_per_weight']:.2f} nW (ref {r['refresh_nW']:.2f}, cb {r['crowbar_nW']:.2f})"
              f"  t_ret {r['t_ret_nom_us']:.3g}/{r['t_ret_us']:.3g} us  occ {r['refresh_occ']:.3g}")
    for o in ("gaincell_mos_caps", "gaincell_mos_r08", "gaincell_mos_r08_vlo035"):
        q = OPTIONS[o]["params"]
        print(f"  {o} (32 fins): C_eq {mos_cu_eq_fF(q):.3f} fF, k {mos_k(q):.2f}, sigma {100 * mos_unit_sigma(q):.2f} %")
    for vt in ("rvt", "sram"):
        for dv in (0.1, 0.2):
            q = dict(OPTIONS["gaincell_mos_caps"]["params"], inv_vt=vt, dv_bit=dv)
            r = cell(dict(q, rows=128), 0.7, fmt4)
            print(f"  inverter {vt:4s} dv_bit {dv}: crowbar {r['crowbar_nW']:.2f} nW/w, refresh {r['refresh_nW']:.2f}"
                  f" nW/w, t_ret(design) {r['t_ret_us']:.3g} us, occ {r['refresh_occ']:.3f}")
    for corner in ("nom", "design"):
        for gm in (5, 8, 15):
            for res in (1.0, 0.15):
                print(f"  analog copier: {analog_copier_area(gm_id=gm, residual=res, corner=corner)}")
    print(f"  analog log cell hold (10 fF, 0.26 mV = 1 % at gm/ID 38): {analog_hold_us(10, 0.26):.3g} us")
    if "--score" in sys.argv:
        out = {}
        regs = [a.split("=", 1)[1] for a in sys.argv if a.startswith("--regime=")] or list(REGIMES)
        opts = [a.split("=", 1)[1] for a in sys.argv if a.startswith("--opt=")] or list(OPTIONS)
        for regime in regs:
            for o in opts:
                for rc in ((True, False) if "--asis" in sys.argv else (True,)):
                    for fam, (s, d) in score_option(o, regime, real_c=rc).items():
                        key = f"{regime}:{fam}:{o}" + ("" if rc else ":asis")
                        out[key] = dict(d, **{mm: s[mm] for mm in ("tok_s_die", "tops_w", "tok_w", "tok_j")},
                                        snr=(s.get("tile") or {}).get("snr_db"), errors=s.get("errors"))
                        print(f"{key:56s} tok/s/die {s['tok_s_die']:9.5g} TOPS/W {s['tops_w']:7.4g} tok/W "
                              f"{s['tok_w']:7.4g} tok/J {s['tok_j']:7.4g}  {d['nodes']} {d['params']}", flush=True)
        print(json.dumps(out, default=str))
