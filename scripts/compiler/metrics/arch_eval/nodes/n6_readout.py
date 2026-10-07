"""N6 readout & conversion (researched model, 2026-10-05; write-up docs/.../ArchResearch/nodes/N6.md).

One physics core prices every converter: what it costs to resolve an LSB Delta of the
range it is handed (v_fs_V from n5, the +-4 sigma column swing).

  Delta      = v_eff / 2^B,  v_eff = G_stack * v_fs / sqrt(K)                     [V]
  quiet dec. E_q = max(E_cmp_min, kappa / sigma_q^2),  sigma_q = g * Delta          [J]
             (thermal-noise law: comparator/preamp noise^2 ~ kT/C, energy ~ C VDD^2;
              notes 19p, 27g2, 27h2; kappa anchored below)
  cheap dec. E_c = measured min StrongARM, sigma_c = its derived noise (7.5 mV)
  converter noise  sigma_adc^2 = Delta^2/12 + sigma_q^2 + droop^2/3 (+ INL^2)
  returned `bits` = effective bits = log2(v_eff / (sqrt(12) sigma_adc)), so n5's
  10 log10(12 4^B / 64) term carries converter noise honestly (nominal bits in `bits_nominal`).

kappa (J V^2), labelled:
  KAPPA_SA  = 2.94 fJ x (1.24 mV)^2 = 4.5e-21: ASAP7 IMC-grade StrongARM, energy measured
              (asap7_constants comparator_imc_*), noise derived (19p) -> derived.
  KAPPA_PRE = 150 fJ x (87 uV)^2 = 1.1e-21: capacitor-biased dynamic preamp (Choo ISSCC 2021,
              simulated, IMC_NULL_READOUT_OPTIONS) -> projected. Differential integrating-gm ideal
              8kT gamma VDD/(gm/ID) = 1.55e-21 (NMOS pair), 7.8e-22 (CMOS pair); only current-reuse
              stacking (Wu CICC 2024, abstract only) claims below it, 1.9e-22.
Continuous-time detectors (residue VTC, ramp) are priced as n_ct = 3 integrating windows (a
band-limited detector with its fixed delay calibrated out settles in ~3 tau); n_ct = 1 is the
optimistic bound and 2^(nv+1) the fixed-bandwidth (PICO-RAM-like) bound. One law for VTC and ramp.

Noise the DAC adds (2026-10-05 revision, critic): floated charge-injection packets carry
2kT v_eff/(VDD C_col); a buffered reference adds kT v_eff/(VDD C_col) and draws a static bias
sized to settle C_dac to 2^-(B+1) per decision; a bottom-plate CDAC removes the packet term at an
attenuation C_col/(C_col + C_dac). Kickback isolation (2 FO4/decision), one auto-zero phase and
10 um2 trim per comparator class are priced.

Floor (derived): E_conv/MAC >= n_q kappa SNR_adc / (g a V_exc rho)^2, independent of R; options
differ in n_q (quiet-noise window equivalents), kappa and fixed overheads. LEAD (DEFAULT) =
sar_direct_residue_amp: noise-scaled coarse SAR on the retained column, one dynamic residue
amplifier (the KAPPA_PRE device, one sampled window), relaxed back-end (n_q ~ 1.1).
Scores and verdicts: N6.md.

Every option is a set of params on that core (or a measured sky130 port). Options that are
rules/modifiers rather than converters (rounding, sharing ratio = n5 adc_share, zero/MSB-skip,
CSNR thresholds, per-layer resolution, analog inter-layer chaining, TIA) are argued in N6.md.
C_col is recomputed from the n3 default law (_c_col_fF).

Round 2 (A1, 2026-10-06; N6_r2.md). Every round-1 option keeps its numbers (checked: 600 adc() calls identical).
New, opt-in through params (a design or a "r2_*" option sets them):
  t_model="meas"  measured ASAP7 parts instead of the FO4 law: FIA kappa per input flavor (cmp_cls, FIA table,
                  gamma_n 1.25 in the 1-1.5 band), the comparator's input gate loading the column (fixed point),
                  an asynchronous loop (23q, 23q1, 23q6) whose logic runs at the liberty FO4 (CHAR.md 3), a DAC
                  settle law from an ESPice driver run, a metastability slack for p_meta per conversion (19n-19n3,
                  23q5), and the K-tile pool bus from the tile floorplan (tile_pitch_um, pool_tracks; ESPice ladder).
  n_red           several redundant cycles; bpc = k bits per cycle on the redundancy-covered decisions (23r);
  dac="mono"      detect-then-inject, one packet per decision (23t; CM drift 23t1); pipe_ra = pipelined
                  residue stage (24a1); dac_density = n3's MOM6 density for the DAC caps.
Round 2b (critic fixes, meas path only; 2,700 non-meas adc() calls identical): FIA switches sized 32/16 fins with their
gate drive in kappa (ESPice); FIA area from the measured device scaled by C_in; the pool-bus wire attenuates the pooled
node (g_bus); each front decision is broadcast to the K tiles' DAC drivers (t_bc); residue gain up to A_FIA (clamp
0.38 VDD, critic ESPice linearity); back end on IMC-grade StrongARMs (KAPPA_SA law, timed at their sigma) plus its CDAC
on Co; async logic and broadcast energy; the pipelined period covers RA window + back stage (no ping-pong FIA).
"""
import itertools
import math

from arch_eval import asap7 as k

KAPPA_SA = (k.get("comparator_imc_energy_fJ") * 1e-15) * (k.get("comparator_imc_noise_mV_rms") * 1e-3) ** 2
KAPPA_PRE = 150e-15 * (87e-6) ** 2
RHO_MOS_fF_um2 = 20.0   # FinFET gate cap: 59.8 aF/fin over 27 nm x 54 nm = 41 fF/um2, /2 for routing (derived)
ISO_FO4 = 2.0           # kickback isolation phase per decision on the unisolated retained node (projected)
AZ_FO4 = 10.0           # one auto-zero phase per conversion, both comparator classes (projected)
EPS_BRIDGE = 2e-3       # residual bridge-cap ratio error after per-column cal (projected, Pelgrom ~10 fF)
EPS_RA_GAIN = 1e-3      # residual residue-amp gain error after background cal (projected)

# ---- round 2 (A1, 2026-10-06): measured ASAP7 comparator classes + asynchronous loop (opt-in t_model="meas") ----
# ESPice, BSIM-CMG TT 27 C, 0.7 V (decks: N6_r2.md section 2). Noise is derived (19p form on the measured gain and
# charge), never transient-simulated.
# FIA = capacitor-biased floating inverter amp (Tang JSSC 2020 / Choo ISSCC 2021 form), 16 fins per device, Cres 160 fF,
# Co 20 fF. kappa_amp = (E(t) + E_sw) 4kT/(A Co_tot) at gamma 1 (measured E, A; derived noise); aco_cin = A Co_tot / C_in at
# the end of the integration window: what one fF of input gate buys (sets the comparator's load on the column).
# Critic r2 (2026-10-06): the switches are now sized for the job (series Mps/Mns 32 fins, reset Mrt/Mrb 16 fins; the
# round-1 deck used 64/64) and their gate drive E_sw = fins x Cgg x VDD^2 = 3.05 fJ is charged (the deck's clocks were
# ideal sources). rvt450/rvt300/lvt150: measured at ser32/rst16 (scratchpad a1r2/sp2.py); lvt300/slvt*: derived from
# their 64/64 runs with the same E_sw and the measured 0.96x gain loss.
FIA = {
    "rvt300": dict(kappa_amp=8.11e-22, t_int_ps=300.0, A=10.02, aco_cin=109.6),
    "rvt450": dict(kappa_amp=7.56e-22, t_int_ps=450.0, A=12.95, aco_cin=141.7),
    "lvt150": dict(kappa_amp=1.04e-21, t_int_ps=150.0, A=9.54, aco_cin=104.4),
    "lvt300": dict(kappa_amp=1.01e-21, t_int_ps=300.0, A=14.6, aco_cin=160.0),
    "slvt100": dict(kappa_amp=1.47e-21, t_int_ps=100.0, A=8.48, aco_cin=92.7),
    "slvt50": dict(kappa_amp=1.58e-21, t_int_ps=50.0, A=5.29, aco_cin=57.9),
}
# Area of one FIA from the measured device (critic r2): the run's 16-fin device has C_in 1.914 fF per side and needs
# Cres + 2 Co = 200 fF of cap and 168 fins (4 x 16 amp, 2 x 32 + 2 x 16 switches, 8 reset); scale by C_in / 1.914 fF.
FIA_RUN = dict(cin_fF=1.914, cap_fF=200.0, fins=168)
SA = dict(imc=dict(tau_ps=3.37, t1mV_ps=32.6), min=dict(tau_ps=4.30, t1mV_ps=26.8))  # measured, t(v)=t1mV+tau ln(1mV/v)
TAU_DAC_PS = 4.63       # measured: RVT inverter, 1 fin per fF of C_inj into 224 fF; settle(b) = tau (6.9 + 0.72 (b-6))
BUS_SETTLE13 = 10.9     # measured: injected packet on a distributed RC bus settles to 2^-13 in 10.9 tau_law (L 39-552 um)
FO4_TT = 9.8756         # ps, the bare-device FO4 the measured times are relative to (corners scale them)


def _t_sa(cls, v):
    s = SA[cls]
    return s["t1mV_ps"] + s["tau_ps"] * math.log(1e-3 / max(v, 1e-9))     # ps


def _kappa_meas(p, kT):
    """kappa_eff of FIA + IMC StrongARM latch, optimal noise split (Lagrange): (sqrt(g ka) + sqrt(kSA)/A)^2;
    returns (kappa_eff, FIA share of the comparator variance, FIA row). Scales with kT (corners)."""
    f = FIA[p.get("cmp_cls", "lvt150")]
    r = kT / 4.141947e-21
    a, b = math.sqrt(p.get("gamma_n", 1.25) * f["kappa_amp"] * r), math.sqrt(KAPPA_SA * r) / f["A"]
    return (a + b) ** 2, a / (a + b), f

COMMON = dict(adc_bits=8, cmp_noise_lsb=0.5, redundant=False, red_frac=0.5, preamp=True,
              stack_n=1, stack_alpha=0.1, cascade_K=1, slice_merge=False, trim_um2=10.0,
              digital_gates=60, hold_fins=8, range_mult=1.0, bus_ohm_per_um=12.0,
              n_ct=3.0,        # band-limited CT detector = n_ct integrating windows (3 tau settle; AZ in kappa)
              dac="inj", ref="dyn", fine=None, ra_gain=8.0, cs_mult=1.0, vdd_pre=None, ramp_tlsb_ps=50.0)


def _opt(adc, prov, **kw):
    return dict(params=dict(COMMON, adc=adc, **kw), provenance=prov)


OPTIONS = {
    # --- references and measured ports -------------------------------------------------
    "sar_27h1": _opt("sar", "projected: 27h1 Gonugondla-2022 survey fit k1(B+log2 r)+k2 r^2 4^B (k2 1 aJ); "
                     "switching from measured ASAP7 comparator/DFF", k2_aJ=1.0, adc_area_fixed_um2=100.0, cu_adc_fF=0.5),
    "integrator_coarse_sar": _opt("integrator", "derived: measured sky130 tb_tile_mvm chain 79.1 pJ / 1.26 us "
                                  "(METRICS.md) ported VDD^2/FO4; two-stage OTA gain ~29^2 caps bits at ~9.6 (16i, projected)",
                                  adc_area_fixed_um2=400.0, int_bits_cap=9.6),
    "integrator_cascade_k4": _opt("integrator", "derived: CASCADE.md measured sky130 K=4 E/pass 0.41x, conversion "
                                  "amortized /4; same OTA cap", adc_area_fixed_um2=400.0, int_bits_cap=9.6, cascade_K=4),
    "null_sar_sky130_port": _opt("null_port", "derived: IMC_NULL_SAR measured 1.42-1.56 pJ / 295 ns / 10 dec ported "
                                 "VDD^2/FO4, swing-blind; noise from ported decision energy via KAPPA_SA", adc_bits=10),
    # --- bottom-up SAR family (this node's model) ----------------------------------------
    "sar_sampled": _opt("sar_sampled", "projected: conventional SAR, own sampling CDAC C_s = cs_mult C_col by "
                        "charge sharing (extra kT/C_s referred, signal x C_col/(C_col+C_s); 23d, 18q, 27g2)",
                        redundant=True),
    "sar_direct": _opt("sar_direct", "projected: SAR on the retained column (compute caps = sampler, charge-injection "
                       "DAC; 23d, 21b, CAP-RAM ciSAR, 27h10 null), every decision quiet"),
    "sar_direct_redundant": _opt("sar_direct", "projected: as sar_direct + 1 redundant cycle, cheap/quiet comparator "
                                 "split (repo 6+5 proof, 23 redundancy, Ahmadi/Namgoong)", redundant=True),
    "sar_direct_stack": _opt("sar_direct", "projected: redundant direct SAR behind passive series-stacking gain "
                             "G=n/(1+(n-1)a) of n column segments (bottom-plate a=0.1 assumed)",
                             redundant=True, stack_n=4),
    "sar_direct_pool_k4": _opt("sar_direct", "projected: K=4 row tiles charge-pooled (equal C, native-charge identity) "
                               "into one redundant direct SAR (27l3, 28h4, CASCADE)", redundant=True, cascade_K=4),
    "sar_direct_stack_pool": _opt("sar_direct", "projected: stack gain + K-tile pooling combined",
                                  redundant=True, stack_n=4, cascade_K=4),
    "sar_vtc_fine": _opt("sar_direct", "projected: noise-scaled redundant coarse SAR, then a residue VTC + ring TDC "
                         "for the last vtc_bits, detector priced as a band-limited CT comparator = n_ct (3) "
                         "integrating windows (27h8, 27h9, PICO-RAM)", redundant=True, vtc_bits=4, fine="vtc"),
    "sar_vtc_fine_bpdac": _opt("sar_direct", "projected: sar_vtc_fine with a bottom-plate CDAC attached to the column "
                               "(no floated packets, attenuation C_col/(C_col+C_dac))", redundant=True, vtc_bits=4,
                               fine="vtc", dac="bp"),
    "sar_direct_residue_amp": _opt("sar_direct", "projected: noise-scaled coarse SAR on the column, one dynamic "
                                   "residue amp (capacitor-biased FIA, Choo 2021 = KAPPA_PRE) x ra_gain, relaxed "
                                   "back-end SAR (24a1 pipelined-SAR, 23d)", redundant=True, vtc_bits=5, fine="ra",
                                   ra_gain=16.0),
    "sar_ra_bpdac": _opt("sar_direct", "projected: sar_direct_residue_amp with the bottom-plate CDAC",
                         redundant=True, vtc_bits=5, fine="ra", ra_gain=16.0, dac="bp"),
    "sar_direct_redundant_bpdac": _opt("sar_direct", "projected: sar_direct_redundant with the bottom-plate CDAC",
                                       redundant=True, dac="bp"),
    "sar_vtc_pool": _opt("sar_direct", "projected: sar_vtc_fine behind K-tile equal-C charge pooling (27l3, 28h4): "
                         "noise term neutral, fixed costs and converter area / K", redundant=True, vtc_bits=4, fine="vtc",
                         cascade_K=4),
    "flash_sar_hybrid": _opt("flash_sar", "projected: 3-b flash seed + redundant direct SAR fine (24j, DD seed table)",
                             redundant=True, flash_bits=3),
    # --- other converter families ------------------------------------------------------
    "flash": _opt("flash", "projected: 2^B-1 quiet comparators, one cycle (22a, 22g, 19a2)", adc_bits=6),
    "flash_per_plane": _opt("flash", "projected: flash on each input plane separately (no in-charge radix), x planes",
                            adc_bits=4, per_plane=True),
    "sense_amp_1b": _opt("flash", "projected: SA reused as 1-b converter (27h8, PRIME)", adc_bits=1, per_plane=True),
    "ramp_single_slope": _opt("ramp", "projected: column discharged at constant current over the full range "
                              "(merges full-range VTC/TDC, 27h9), band-limited CT comparator = n_ct windows, "
                              "shared Gray bus at t_LSB >= 50 ps (27h1 Marinella 2^B time law)"),
    "ramp_cis_coupled": _opt("ramp_cc", "projected: CIS-style shared ramp coupled through C_c = 0.1 C_col (no "
                             "discharge shot noise), band-limited CT comparator = n_ct windows, Gray bus "
                             "t_LSB >= 50 ps"),
    "cco_per_column": _opt("cco", "projected: Hermes-style CCO + counter, integrating Gm front end, 3x cal area "
                           "(27h7, 27h4; t_LSB 150 ps projected from 300 ps at 14 nm)", cco_tlsb_ps=150.0),
    "dsm_incremental": _opt("dsm", "projected: incremental 2nd-order DT DS, M cycles, OTA settle per cycle "
                            "(26o1, 26q, 16g1)"),
    "pipelined_shared": _opt("pipe", "projected: shared 1.5-b/stage pipeline, kT/C front sampler, OTA settle "
                             "(24a1, 24x; needs calibration at gm/gds 29)"),
}
_R2 = dict(redundant=True, fine="ra", ra_gain=16.0, t_model="meas", dac="mono", pool_tracks=4, pipe_ra=True,
           dac_density=4.78, adc_bits=12)
OPTIONS.update({
    "r2_ra_pipe_k4": _opt("sar_direct", "projected on measured parts (ROUND-2b LEAD, ARCH, post-critic): pipelined "
                          "residue-amp SAR (24a1) on K=4 charge-pooled tiles, LVT 150 ps FIA, 2-b flash seed, 3 bits/cycle (23r), "
                          "11 b, async loop at the liberty FO4 (23q6), monotonic injection (23t), 2-track center-tapped pool bus "
                          "(wire on the pooled node), decision broadcast; design adc_share 6, cu 1.25 fF (N6_r2.md)",
                          **dict(_R2, vtc_bits=7, cascade_K=4, cmp_cls="lvt150", bpc=3, flash_bits=2, pool_tracks=2, adc_bits=11)),
    "r2_ra_pipe_k4_sohu": _opt("sar_direct", "projected on measured parts (ROUND-2b LEAD, Sohu): as r2_ra_pipe_k4 with the "
                               "lower-kappa LVT 300 ps FIA, 2 bits/cycle, 6 fine bits; design adc_share 4, cu 1.25 fF",
                               **dict(_R2, vtc_bits=6, cascade_K=4, cmp_cls="lvt300", bpc=2, flash_bits=2, pool_tracks=2,
                                      adc_bits=11)),
    "r2_ra_pipe_k8_sohu": _opt("sar_direct", "projected on measured parts (round-2a Sohu lead, SUPERSEDED: rests on N9 I1 "
                               "and the bus wire it ignored): K=8 pooling, RVT 450 ps FIA, 2-b flash seed, 2-track bus",
                               **dict(_R2, vtc_bits=6, cascade_K=8, cmp_cls="rvt450", bpc=1, flash_bits=2, pool_tracks=2)),
    "r2_ra_pipe_k8": _opt("sar_direct", "projected on measured parts (round-2a upper bound, INFEASIBLE post-critic: the "
                          "4-track bus wire on the pooled node): K=8, LVT 150 ps FIA, 2 bits/cycle, 4-track pool bus",
                          **dict(_R2, vtc_bits=7, cascade_K=8, cmp_cls="lvt150", bpc=2, flash_bits=2)),
    "r2_ra_pipe_k2": _opt("sar_direct", "projected on measured parts: K=2, LVT 150 ps FIA; best only under the shared N9 "
                          "reference accounting (per n_adc), which under-charges it 3x (N6_r2.md I1)",
                          **dict(_R2, vtc_bits=7, cascade_K=2, cmp_cls="lvt150", bpc=2)),
    "r2_pool_k4_meas": _opt("sar_direct", "projected on measured parts: the round-1 pick's converter (sar_direct_pool_k4) "
                            "re-priced on the measured loop; the honest reading of round 1", redundant=True, cascade_K=4,
                            t_model="meas", cmp_cls="lvt150"),
    "r2_ra_nopool": _opt("sar_direct", "projected on measured parts: pipelined residue-amp SAR per tile (K=1), exact "
                         "digital accumulation across tiles (T2 chain): no pool bus", **dict(_R2, vtc_bits=6, cascade_K=1,
                                                                                             cmp_cls="slvt50", bpc=1)),
})
DEFAULT = "sar_direct_residue_amp"
SWEEP = dict(adc_bits=[6, 7, 8, 9, 10, 12, 14], cmp_noise_lsb=[0.5, 1.0], vtc_bits=[3, 4, 5],
             cascade_K=[1, 2, 4, 8, 16, 32], ra_gain=[4.0, 8.0, 16.0], cs_mult=[0.25, 0.5, 1.0, 2.0, 4.0],
             vdd_pre=[None, 0.45],
             t_model=[None, "meas"], cmp_cls=list(FIA), gamma_n=[1.0, 1.25, 1.5], n_red=[1, 2, 3], bpc=[1, 2, 3],
             dac=["inj", "mono", "bp"], pool_tracks=[1, 2, 4], pipe_ra=[False, True], dac_density=[None, 4.78],
             p_meta=[1e-9, 2e-11, 1e-14])
SWEEP["vtc_bits"] = [3, 4, 5, 6, 7, 8]


def _c_col_fF(p):
    """Column capacitance per slice, n3 default law (ponytail: duplicate of n3/n2; the core
    should hand arr['c_col_fF'] to adc() - see N6.md open questions)."""
    bits = min(4, int(p.get("wbits", 4)))
    caps = bits if p.get("unit_caps") else 2 ** (bits - 1) - 1
    return p["rows"] * caps * p.get("cu_fF", 1.0)


def _e_quiet(p, vdd, sigma):
    """Integrating-window noise law E = kappa / sigma^2 (kappa ~ VDD for an integrating gm, 27h1/19p);
    vdd_pre = separate quiet-class rail (input common mode must fit: unchecked, projected)."""
    vdd = p.get("vdd_pre") or vdd
    kap = (p.get("kappa_J_V2", KAPPA_PRE) * vdd / 0.7) if p["preamp"] else KAPPA_SA * (vdd / 0.7) ** 2
    e_min = k.get("comparator_imc_energy_fJ") * 1e-15 * (vdd / 0.7) ** 2
    return max(e_min, kap / sigma ** 2)          # J


def _bits_eff(v_eff, var):
    return math.log2(v_eff / math.sqrt(12 * var))


def adc(p, vdd, v_fs_V):
    """range_mult m > 1: cover m x the n5 range at the same B (clip-free +-4m sigma when n5 hands
    +-4 sigma, the N8 heavy-tail requirement); bits are returned relative to n5's range."""
    a, B = p["adc"], int(p["adc_bits"])
    m = float(p.get("range_mult", 1.0))
    v_fs_V *= m
    s2 = (vdd / 0.7) ** 2
    fo4 = k.get("fo4_delay_ps", vdd) * 1e-3                                  # ns
    dff_e, dff_a = k.get("dff_energy_fJ") * s2, k.get("dff_area_um2")
    e_dig = p["digital_gates"] * k.get("inv_switch_energy_fJ", vdd)          # shift-add + accumulate, fJ
    K = int(p.get("cascade_K", 1))
    slices = 2 if (p.get("slice_merge") and int(p.get("wbits", 4)) > 4) else 1
    amort = K * slices                                                        # conversions shared per phys column

    def out(bits, e_fJ, t_ns, area, bits_nom=None, **extra):
        return dict(bits=bits - math.log2(m), bits_nominal=bits_nom if bits_nom is not None else B,
                    e_conv_fJ=e_fJ / amort, t_conv_ns=t_ns, area_um2=area / amort,
                    e_digital_fJ=e_dig / amort, **extra)

    if a == "sar":   # 27h1 survey fit (shipped default, kept as the reference)
        sw = B * (k.get("comparator_energy_fJ") + 2 * k.get("dff_energy_fJ")) * s2
        th = p["k2_aJ"] * 1e-3 * (vdd / v_fs_V) ** 2 * 4 ** B
        cdac = 2 ** B * p["cu_adc_fF"] / k.get("mom_cap_density_fF_per_um2")
        # same retained-node interface as every other option: ideal-ENOB core + DAC packet + reference kT
        d, cc = v_fs_V / 2 ** B, _c_col_fF(p) * 1e-15 * K
        var = d * d / 12 + 3 * k.get("kT_300K_J") * v_fs_V / (vdd * cc)
        t = B * 6 * fo4 + 10 * fo4 + B * ISO_FO4 * fo4 + AZ_FO4 * fo4         # same isolation + auto-zero
        return out(_bits_eff(v_fs_V, var), sw + th, t, p["adc_area_fixed_um2"] + cdac + 2 * B * dff_a,
                   breakdown_fJ=dict(switching=sw, thermal=th))

    if a == "integrator":   # measured sky130 chain, OTA gain sets the input range (Vc-independent)
        r = k.get("fo4_delay_ps", vdd) / k.get("sky130_fo4_delay_ps")
        e = 79.12e3 * (vdd / 1.8) ** 2
        return out(min(B, p["int_bits_cap"]), e, 1260 * r, p["adc_area_fixed_um2"])

    if a == "null_port":    # measured sky130 null SAR, energy/time ported, noise re-derived
        e = 1.49e3 * (vdd / 1.8) ** 2
        e_dec = 0.10e3 * (vdd / 1.8) ** 2 * 1e-15                            # ~1.0 pJ decision path / 10
        sig = math.sqrt(KAPPA_SA * s2 / e_dec)
        d = v_fs_V / 2 ** B
        return out(min(B, _bits_eff(v_fs_V, d * d / 12 + sig ** 2)), e,
                   295 * k.get("fo4_delay_ps", vdd) / k.get("sky130_fo4_delay_ps"), 60.0)

    c_col = _c_col_fF(p) * 1e-15 * K                                          # node being converted, F
    kT = k.get("kT_300K_J")
    n = int(p["stack_n"])
    # Passive stacking: the compute caps keep Q_top = 0, so they cannot be re-stacked themselves;
    # each of n segments is sampled onto C_s = C_seg (the noise optimum, attenuation 1/2) and the
    # samples are series-stacked: G = (n/2)/(1+(n-1)alpha); added noise 4kT/C_col per side,
    # 8kT/C_col differential, referred to the column (derived, 27g2 kT/C).
    G = (0.5 * n / (1 + (n - 1) * p["stack_alpha"])) if n > 1 else 1.0
    var_x = (8 * kT / c_col) if n > 1 else 0.0
    v_eff = v_fs_V / math.sqrt(K)                                             # pooled K equal-C tiles average
    d = v_eff / 2 ** B
    sq = p["cmp_noise_lsb"] * d                                               # input-referred quiet noise
    e_q = _e_quiet(p, vdd, sq * G)                                            # comparator sees G x signal
    fo4_q = k.get("fo4_delay_ps", p.get("vdd_pre") or vdd) * 1e-3            # quiet class on its own rail
    leak = p["hold_fins"] * k.get("nfet_ileak_per_fin_nA") * 1e-9
    # K-tile pooling bus: K tiles stacked along the column, length K R pitch (n5 pitch law), distributed
    # RC tau = r L C_tot / pi^2 (27f9); settle (B+1) ln2 tau before converting (18j). M6-class r (CHAR.md).
    t_pool = 0.0
    if K > 1:
        pitch = math.sqrt(max(c_col / K * 1e15 / p["rows"] / k.get("mom_cap_density_fF_per_um2"), 0.45))
        L = K * p["rows"] * pitch
        c_bus = L * k.get("wire_c_fF_per_um") * 1e-15
        t_pool = (B + 1) * math.log(2) * p["bus_ohm_per_um"] * L * (c_col + c_bus) / math.pi ** 2 * 1e9
    trim = p["trim_um2"]
    e_c = k.get("comparator_energy_fJ") * 1e-15 * s2                           # min StrongARM, measured
    # Bridge-cap mismatch after per-column calibration when two W slices are merged in charge (20y)
    var_br = (EPS_BRIDGE * v_eff / 16) ** 2 / 3 if slices == 2 else 0.0

    if a in ("sar_direct", "sar_sampled", "flash_sar"):
        red = int(p.get("n_red", 1)) if p["redundant"] else 0
        meas = p.get("t_model") == "meas"
        g_in, c_in, no_fit = 1.0, 0.0, 0.0
        nf = int(p.get("flash_bits", 0))
        fine = p.get("fine") or ("vtc" if p.get("vtc_bits") else None)
        nv = min(int(p.get("vtc_bits", 0)), B - 1) if fine else 0             # bits left to the fine stage
        ndec = B - nf - nv + red                                              # coarse decisions on the column
        gain = G
        if a == "sar_sampled":   # own CDAC C_s by charge sharing: a = C_col/(C_col+C_s), extra kT/C_s (referred)
            cs = p["cs_mult"] * c_col
            a_s = c_col / (c_col + cs)
            var_s = kT / cs
            e_dac = 0.5 * cs * vdd ** 2 + cs * vdd * a_s * v_eff
            c_dac = cs
            gain = a_s
        elif p.get("dac") == "bp":   # bottom-plate CDAC attached to the column: rails drive plates, nothing floats
            c_dac = c_col * v_eff / vdd
            a_bp = c_col / (c_col + c_dac)
            gain = G * a_bp
            var_s = kT / c_col * (1 / a_bp - 1)                               # C_dac shares the column reset event
            e_dac = 0.5 * c_dac * vdd ** 2
        else:                    # charge-injection packets from a reference onto the retained node
            c_dac = c_col * v_eff / vdd                                       # C_inj VDD ~ C_node v_eff
            var_s = (1 if p.get("dac") == "mono" else 2) * kT * v_eff / (vdd * c_col)   # packet kT/C, trial + kept
            # (dac="mono": detect-then-inject, one kept packet per decision, none removed; 23t, 23t1)
            e_dac = 0.5 * c_dac * vdd ** 2
        dac_um2 = c_dac * 1e15 / (p.get("dac_density") or k.get("mom_cap_density_fF_per_um2")) + B * 0.05
        # (dac_density 4.78 = n3's min-pitch MOM6 M2-M5 density, the weight caps' own law: derived upper bound)
        # Reference: a buffered (not rail) reference; its noise into the packet load kT gamma / C_dac,
        # referred through C_dac/C_col (derived, gamma 1). Bias settles each packet to 2^-(B+1) in one
        # decision: gm = C_i (B+1) ln2 / t_dec, I = gm / (gm/ID 15). ref="dyn" (default): bias scaled
        # per decision to its packet, sum C_i ~ C_dac; ref="static": the MSB bias held for every decision.
        var_ref = kT * v_eff / (vdd * c_col)
        # Coarse decisions. Binary weights + one redundant cycle placed after decision m: decisions
        # 0..m may err by the redundant weight (absolute tolerance), later ones must be quiet; m optimal.
        # With a fine stage the residue range is doubled (overlap): every coarse decision may err by
        # red_frac 2^nv Delta. sigma_i = max(sq, tol/4); two comparator classes approach this (Ahmadi).
        if nv:
            sig = [max(sq, p["red_frac"] * 2 ** nv * d / 4)] * ndec
        elif red == 1:
            sig = min(([max(sq, p["red_frac"] * 2 ** (B - nf - 1 - m) * d / 4)] * (m + 1) + [sq] * (ndec - m - 1)
                       for m in range(ndec - 1)), key=lambda ss: sum(1 / s ** 2 for s in ss))
        elif red:   # n_red redundant cycles at positions ms: decision i takes the tolerance of the first m_j >= i
            def _sig(ms):
                return [next((max(sq, p["red_frac"] * 2 ** (B - nf - 1 - m) * d / 4) for m in ms if m >= i), sq)
                        for i in range(ndec)]
            sig = min((_sig(ms) for ms in itertools.combinations(range(ndec - 1), red)),
                      key=lambda ss: sum(1 / s ** 2 for s in ss))
        else:
            sig = [sq] * ndec
        quiet = sum(s == sq for s in sig)
        g_bus, c_bx = 1.0, 0.0
        if meas and K > 1:   # critic r2: the pool-bus wire is on the pooled node; n5 already counts (K R + 4 S) cell
            # pitches of it (c_in_mode direct), so only the rest attenuates here (vs c_col: conservative, no n5 c_par)
            Lb = K * p.get("tile_pitch_um", 138.0)
            c_bw = Lb * k.get("wire_c_fF_per_um") * (1 + 0.25 * (p.get("pool_tracks", 1) - 1)) * 1e-15
            pitch5 = math.sqrt(max(c_col / K * 1e15 / p["rows"] / k.get("mom_cap_density_fF_per_um2"), 0.45))
            c_n5 = (K * p["rows"] + 4 * int(p.get("adc_share", 1))) * pitch5 * k.get("wire_c_fF_per_um") * 1e-15 \
                if p.get("c_in_mode") == "direct" else 0.0
            c_bx = max(0.0, c_bw - c_n5)
            g_bus = c_col / (c_col + c_bx)
            gain *= g_bus
        if meas:    # measured comparator: kappa_eff, and its input gate loads the column (fixed point on the gain)
            kap, share, fia = _kappa_meas(p, kT)
            p = dict(p, kappa_J_V2=kap, preamp=True)
            g0 = gain
            for _ in range(30):
                c_in = 4 * kT * p.get("gamma_n", 1.25) / (share * (sq * g0 * g_in) ** 2 * fia["aco_cin"])
                g_in = c_col / (c_col + c_in) if c_in < 3 * c_col else 0.25
            gain = g0 * g_in
            no_fit = v_eff ** 2 if c_in >= 3 * c_col else 0.0   # quiet comparator cannot fit on this column: infeasible
        e_dec = [_e_quiet(p, vdd, s * gain) for s in sig]
        bpc = int(p.get("bpc", 1)) if meas else 1     # k bits per cycle on the tolerant (redundancy-covered) decisions (23r)
        groups = [[i] for i in range(ndec) if sig[i] != sq]
        if bpc > 1:     # 2^k - 1 cheap comparators with capacitive threshold offsets (23r1, 23r2); errors -> redundancy
            tol = [i for i in range(ndec) if sig[i] != sq]
            groups = [tol[j:j + bpc] for j in range(0, len(tol), bpc)]
            e_tol = sum((2 ** len(g) - 1) * max(e_dec[i] for i in g) for g in groups)
            e_dec = [e_dec[i] for i in range(ndec) if sig[i] == sq] + [e_tol]
        e_flash = (2 ** nf - 1) * e_c if nf else 0.0      # seed comparators: errors absorbed by redundancy
        e_f = var_f = t_f = e_fq = 0.0
        nback, a_extra, n_bc = 0, 0.0, 0
        if fine == "vtc":   # residue 2^(nv+1) Delta discharged at constant current; CT detector, ring TDC
            v_res = 2 ** (nv + 1) * d
            e_fq = p["n_ct"] * _e_quiet(p, vdd, sq * gain)                    # band-limited CT detector windows
            e_f = e_fq + 2 ** (nv + 1) * (2 * k.get("inv_switch_energy_fJ", vdd) + dff_e) * 1e-15 \
                + c_col * v_res * vdd
            var_f = 2 * 2 * 1.602e-19 * v_res / c_col                         # discharge-current shot noise, gamma 2
            t_f = 2 ** (nv + 1) * fo4
        elif fine == "ra":  # dynamic residue amp (capacitor-biased FIA = the KAPPA_PRE device), x Gr, back-end SAR
            Gr = max(1.0, min(p["ra_gain"], (0.38 if meas else 0.25) * vdd / (2 ** (nv + 1) * d * gain)))  # output headroom
            if meas:   # measured FIA gain at its window; linear within 1.1 % to +-20 mV in, ~0.27 V out (critic ESPice: 0.38 VDD)
                Gr = min(Gr, fia["A"])
            e_fq = _e_quiet(p, vdd, sq * gain)                                # one integrating window at quiet noise
            c_o = 4 * kT / (Gr * gain * sq) ** 2                              # output kT/C referred = sq^2/4
            nback = nv + 1                                                    # one redundant back-end cycle
            n_bc = -(-nback // bpc)                                           # back-end cycles at bpc bits/cycle
            p_be = dict(p, preamp=False) if meas else p                       # meas: back end = scaled IMC StrongARMs
            e_f = e_fq + c_o * vdd ** 2 + n_bc * (2 ** bpc - 1) * _e_quiet(p_be, vdd, Gr * gain * sq) \
                + nback * 2 * dff_e * 1e-15 + (0.5 * c_o * vdd ** 2 if meas else 0.0)   # + back-end CDAC on Co
            var_f = sq ** 2 / 4 + (EPS_RA_GAIN * 2 ** nv * d) ** 2 / 3        # + residual gain error after cal
            t_f = 10 * fo4_q + nback * 6 * fo4
            a_extra = 2.0 + 5.0                                               # amp + background gain-cal state
        e_ref = c_dac * vdd * (B + 1) * math.log(2) / 15.0 * ((ndec + nback) if p.get("ref") == "static" else 1.0)
        e = sum(e_dec) + e_f + e_flash + e_dac + e_ref + 2 * ndec * dff_e * 1e-15 \
            + (2 * n * 4 * k.get("nfet_cgg_per_fin_aF") * 1e-18 * vdd ** 2 if n > 1 else 0.0)
        t = quiet * 10 * fo4_q + (ndec - quiet) * 6 * fo4 + ndec * ISO_FO4 * fo4 + AZ_FO4 * fo4_q \
            + (4 * fo4 if nf else 0) + 10 * fo4 + t_f + t_pool + (4 * fo4 if n > 1 else 0)
        tb = None
        if meas:    # asynchronous loop (23q, 23q1, 23q6) on measured parts; logic at the liberty FO4 (CHAR.md 3)
            r = k.get("fo4_delay_ps", vdd) / FO4_TT                           # corner/VDD tracking of measured times
            lib = k.get("fo4_delay_ps_lib") * r
            vq = fia["A"] * sq * gain                                         # latch input at a quiet-class decision
            t_q = fia["t_int_ps"] * r + _t_sa("imc", vq) * r
            t_c = _t_sa("min", 1e-3) * r                                      # cheap class, >= 1 mV typical input
            t_bc = 0.0
            if K > 1:   # critic r2: each front decision is broadcast to the 1/K DAC drivers of all K tiles (center
                Lc = K * p.get("tile_pitch_um", 138.0) / 2   # converter, far tile at K pitch / 2): buffer + Elmore 0.38 RC
                c_bc = Lc * k.get("wire_c_fF_per_um") * 1e-15 + 2e-15            # + local buffer gates per tile
                t_bc = 2 * lib + 0.38 * p["bus_ohm_per_um"] * Lc * c_bc * 1e12

            def loop(s_i, w_i, bc=True):                                      # completion detect + DAC latch + settle
                bits = min(13.0, max(6.0, math.log2(max(w_i * d / max(s_i, 1e-12), 2.0))))
                return 2 * lib + TAU_DAC_PS * r * (6.9 + 0.72 * (bits - 6)) + ISO_FO4 * fo4 * 1e3 + (t_bc if bc else 0.0)
            ws = [2.0 ** max(0, B - nf - 1 - i) for i in range(ndec)]
            t_dec = sum(t_q + loop(sq, ws[i]) for i in range(ndec) if sig[i] == sq) \
                + sum(t_c + loop(min(sig[i] for i in g), ws[g[0]]) + (lib if bpc > 1 else 0.0) for g in groups)
            p_m = p.get("p_meta", 2e-11)                                      # per conversion (19n, 19n1 x1.6, 19n2 /A)
            t_meta = max(0.0, SA["imc"]["tau_ps"] * r * math.log(1.6 * 0.5 * vdd / (fia["A"] * p_m * d * gain))
                         - _t_sa("imc", vq) * r)
            t_back = 0.0
            t_front_ra = 0.0
            if fine == "ra":
                t_front_ra = fia["t_int_ps"] * r                              # the residue amp's own window
                t_be = _t_sa("imc", Gr * gain * sq) * r                       # IMC-grade SA at its own sigma (critic r2)
                t_back = n_bc * (t_be + loop(Gr * gain * sq, 2.0 ** nback, bc=False) + (lib if bpc > 1 else 0.0))
            elif fine == "vtc":
                t_back = t_f * 1e3
            t_pl = 0.0
            if K > 1:                                                         # pool bus from the tile floorplan
                Lb = K * p.get("tile_pitch_um", 138.0)
                tr = p.get("pool_tracks", 1)
                cb = Lb * k.get("wire_c_fF_per_um") * (1 + 0.25 * (tr - 1)) * 1e-15
                tau_b = p["bus_ohm_per_um"] / tr * Lb * (c_col + cb) / (4 * math.pi ** 2)   # center-tapped, s
                t_pl = (1.0 + 0.76 * (B + 1)) * tau_b * 1e12                  # measured ladder law, 13 b = 10.9 tau
            t_front = t_dec + t_meta + t_front_ra + AZ_FO4 * fo4_q * 1e3 + 4 * lib + t_pl + (4 * fo4 * 1e3 if nf else 0)
            if fine == "ra" and p.get("pipe_ra"):    # pipelined SAR (24a1): back-end converts sample j while the
                rnd = max(1, int(p.get("adc_share", 1)))   # front takes j+1; one back stage of latency per pass
                # FIA Co holds the residue from the RA window to the end of the back stage: no ping-pong FIA, so the
                # period is at least window + back (critic r2: binding only if back > front - window)
                t_ps = max(t_front, t_back + t_front_ra) + min(t_front, t_back) / rnd
            else:
                t_ps = t_front + t_back
            t = t_ps * 1e-3
            cyc = len(groups) + quiet
            tb = dict(quiet_ps=t_q, cheap_ps=t_c, decisions_ps=t_dec, meta_ps=t_meta, back_ps=t_back, pool_ps=t_pl,
                      front_ps=t_front, cycles=cyc, bcast_ps=t_bc, window_ps=t_front_ra)
            # unpriced in round 2a (critic r2), projected: async completion/sequencing logic ~400 T, ~20 gate toggles
            # per cycle; decision broadcast (2^bpc - 1 lines per front cycle over the K-tile run)
            e_async = (cyc + n_bc) * 20 * k.get("inv_switch_energy_fJ", vdd) * 1e-15
            e_bcast = cyc * (2 ** bpc - 1) * (c_bc if K > 1 else 0.0) * vdd ** 2 if K > 1 else 0.0
            e += e_async + e_bcast
            e_drv = c_dac * 1e15 * 2 * k.get("nfet_cgg_per_fin_aF") * 1e-18 * vdd ** 2   # 1 fin/fF drivers
            e_dac += e_drv
            e += e_drv
        droop = leak * p.get("adc_share", 1) * t * 1e-9 / c_col
        var = d * d / 12 + sq ** 2 + var_x + var_s + var_ref + var_f + var_br + droop ** 2 / 3 + no_fit   # at the column
        vp = p.get("vdd_pre") or vdd
        c_noise = max(e_dec + [e_fq / max(1.0, p["n_ct"]) if fine == "vtc" else e_fq]) / vp ** 2 * 1e15 * 2
        if meas:    # critic r2: area from the measured FIA (cap + fins scaled by C_in), not 2E/V^2
            sc_f = min(c_in, 3 * c_col) * 1e15 / FIA_RUN["cin_fF"]        # (no-fit designs are infeasible anyway)
            c_noise = sc_f * (FIA_RUN["cap_fF"] + FIA_RUN["fins"] * k.get("nfet_cgg_per_fin_aF") * 1e-3)
        area = (c_noise / RHO_MOS_fF_um2 + 1.0) + (2 ** nf - 1) * (0.5 + trim) + dac_um2 + 2 * ndec * dff_a \
            + 2 * trim + 0.5 + a_extra + (n * (c_col * 1e15 / n) / k.get("mom_cap_density_fF_per_um2") / K if n > 1 else 0) \
            + (2 ** bpc - 2) * (trim + 1.0) * (2 if fine == "ra" else 1)       # extra trimmed comparators (23r3)
        return out(_bits_eff(v_eff, var), e * 1e15, t, area,
                   breakdown_fJ=dict(decisions=sum(e_dec) * 1e15, fine=e_f * 1e15, dac=e_dac * 1e15,
                                     ref=e_ref * 1e15, flash=e_flash * 1e15),
                   noise_uV=dict(q=sq * 1e6, dac=math.sqrt(var_s) * 1e6, ref=math.sqrt(var_ref) * 1e6,
                                 fine=math.sqrt(var_f) * 1e6),
                   decisions=dict(quiet=quiet, total=ndec, n_q=sum((sq / s) ** 2 for s in sig)),
                   v_eff_V=v_eff, lsb_uV=d * 1e6, droop_uV=droop * 1e6, pool_K=K, phys_adc_frac=1.0 / amort,
                   cmp_load=dict(c_in_fF=c_in * 1e15, g_in=g_in, g_bus=g_bus, c_bus_extra_fF=c_bx * 1e15), t_breakdown_ps=tb)

    if a == "flash":
        planes = (p.get("input_planes") or (int(p.get("abits", 8)) - 2)) if p.get("per_plane") else 1
        ncmp = 2 ** B - 1
        e = planes * (ncmp * e_q + B * dff_e * 1e-15)
        t = planes * (10 * fo4 + 4 * fo4)
        var = d * d / 12 + sq ** 2 + var_x
        area = ncmp * (e_q / vdd ** 2 * 1e15 / RHO_MOS_fF_um2 + 1.0 + trim) + B * dff_a
        return out(_bits_eff(v_eff, var), e * 1e15, t, area, comparators=ncmp, planes=planes)

    if a in ("ramp", "ramp_cc"):   # one CT detector watches a ramp: band-limited to ~1/T_ramp, so its noise
        # energy is n_ct integrating windows independent of 2^B (constant delay calibrated out); a detector
        # with a fixed fast bandwidth would instead pay 2^B windows (PICO-RAM's linear-in-levels TD-ADC).
        t_lsb = max(p["ramp_tlsb_ps"] * 1e-3, 2 * fo4)                        # shared Gray bus, ns
        if a == "ramp":       # column node itself discharged: shot noise of the current source over v_eff
            g_r, var_r = G, 2 * 2 * 1.602e-19 * v_eff / c_col
            e_r = c_col * v_eff * vdd
        else:                 # ramp coupled through C_c: attenuation, C_c reset noise, shared ramp drive
            c_c = max(0.1, v_eff / (0.9 * vdd - v_eff)) * c_col if v_eff < 0.9 * vdd else 1e3 * c_col  # ramp <= 0.9 VDD
            g_r = G * c_col / (c_col + c_c)
            var_r = kT / c_col * (c_c / c_col)
            e_r = c_c * (v_eff / g_r) * vdd
        e_dq = p["n_ct"] * _e_quiet(p, vdd, sq * g_r)
        e = e_dq + e_r + 2 ** B * k.get("dff_clk_cap_fF") * 1e-15 * vdd ** 2 + B * dff_e * 1e-15
        t = 2 ** B * t_lsb + 4 * fo4 + AZ_FO4 * fo4
        var = d * d / 12 + sq ** 2 + var_x + var_r + var_br
        area = e_dq / p["n_ct"] / vdd ** 2 * 1e15 * 2 / RHO_MOS_fF_um2 + 1.0 + trim + B * dff_a
        return out(_bits_eff(v_eff, var), e * 1e15, t, area, t_lsb_ps=t_lsb * 1e3)

    if a == "cco":    # integrating Gm front end (T-independent noise energy) + ring/counter 2^B
        deg = min(5.0, max(1.0, v_eff / 0.03))                                # degeneration for linearity >~30 mV
        e = deg * _e_quiet(p, vdd, sq * G) + 2 ** B * (5 * k.get("inv_switch_energy_fJ", vdd) + 2 * dff_e) * 1e-15
        t = 2 ** B * p["cco_tlsb_ps"] * 1e-3 * k.get("fo4_delay_ps", vdd) / k.get("fo4_delay_ps")
        var = d * d / 12 + sq ** 2 + (0.5 * d) ** 2 + var_x + var_br          # +-1 LSB INL after cal (Hermes)
        area = 4 * (5 * k.get("inv_x1_area_um2") + B * dff_a + 1.0)           # x4: 3x calibration (Ghosh 2024)
        return out(_bits_eff(v_eff, var), e * 1e15, t, area, degeneration=deg)

    gmid, beta = 15.0, 0.5
    if a == "dsm":    # incremental 2nd order: B ~ log2(M(M+1)/2); per-cycle sampling cap /M
        M = math.ceil(math.sqrt(2 * 2 ** B))
        cs = max(2e-15, p["cs_mult"] * c_col / M)    # total sampled charge M cs = cs_mult C_col (swept)
        e_cyc = (B + 1) * math.log(2) * cs * vdd / (gmid * beta) * vdd + e_c
        e = M * e_cyc + _e_quiet(p, vdd, sq)
        t = M * 12 * fo4
        a_d = c_col / (c_col + M * cs)        # M samples drawn from the retained column: charge sharing (as sar_sampled)
        var = (d * d / 12 + sq ** 2 + kT / (M * cs)) / a_d ** 2              # + feedback-ref noise; referred
        return out(_bits_eff(v_eff, var), e * 1e15, t, cs * 1e15 / k.get("mom_cap_density_fF_per_um2") * 2 + 10,
                   cycles=M)

    if a == "pipe":   # front sampler kT/C at the full B, stage caps /4 per 1.5-b stage
        stages = math.ceil(B / 1.5)
        cs = 12 * kT * 4 ** B / v_eff ** 2
        c_tot = cs * sum(0.25 ** i for i in range(stages))
        e = (B + 1) * math.log(2) * c_tot * vdd ** 2 / (gmid * beta) + 0.5 * cs * vdd ** 2 + stages * 2 * e_c
        t = 2 * 12 * fo4
        a_p = c_col / (c_col + cs)            # front sampler fed from the retained column: charge sharing
        var = (d * d / 12 + sq ** 2 + kT / cs) / a_p ** 2                     # + MDAC reference noise; referred
        return out(_bits_eff(v_eff, var), e * 1e15, t, 2 * c_tot * 1e15 / k.get("mom_cap_density_fF_per_um2") + 20,
                   stages=stages)

    raise ValueError(f"unknown adc {a!r}")


if __name__ == "__main__":   # self-check: physics sanity on the default column (v_fs ~ 24.7 mV)
    base = dict(rows=128, wbits=4, cu_fF=1.0, adc_share=8, abits=8)
    r = {n: adc(dict(base, **o["params"]), 0.7, 0.0247) for n, o in OPTIONS.items()}
    for n, x in r.items():
        print(f"{n:<24} bits {x['bits']:5.2f}  E {x['e_conv_fJ']:10.1f} fJ  t {x['t_conv_ns']:8.2f} ns  "
              f"A {x['area_um2']:8.1f} um2")
    assert r["sar_direct"]["e_conv_fJ"] < r["sar_27h1"]["e_conv_fJ"]          # retained-node conversion beats fit
    assert r["sar_direct_stack"]["e_conv_fJ"] < r["sar_direct_redundant"]["e_conv_fJ"]   # gain cuts 1/sigma^2
    x = r["sar_direct"]                                                       # g=0.5 costs 1 bit, + DAC/ref kT
    extra = sum(v ** 2 for kk, v in x["noise_uV"].items() if kk in ("dac", "ref")) / (x["lsb_uV"] ** 2 / 12)
    assert abs(x["bits"] - (8 - 0.5 * math.log2(1 + 12 * 0.25 + extra))) < 0.05
    assert r["sar_vtc_fine_bpdac"]["noise_uV"]["dac"] < r["sar_vtc_fine"]["noise_uV"]["dac"]   # no floated packets
    e6, e8 = (adc(dict(base, **dict(OPTIONS["ramp_cis_coupled"]["params"], adc_bits=bb)), 0.7, 0.0247 * 2 ** (bb - 6))
              ["e_conv_fJ"] for bb in (6, 8))
    assert e8 / e6 < 2.5                                                      # same LSB: CT detector energy not ~2^B
    assert r["null_sar_sky130_port"]["bits"] < 6                              # swing-blind port is noise-limited
    # round 2: the measured loop is slower than the FO4 law on the round-1 pick converter; pipelining the residue
    # stage cuts the interval; monotonic injection halves the packet variance; kappa_eff stays in the measured band
    pk = dict(base, rows=8, adc_share=4, **OPTIONS["sar_direct_pool_k4"]["params"]); pk["adc_bits"] = 12
    t1, tm = adc(pk, 0.7, 1.41)["t_conv_ns"], adc(dict(pk, t_model="meas"), 0.7, 1.41)["t_conv_ns"]
    assert tm > 1.5 * t1, (t1, tm)
    ra = dict(base, rows=8, adc_share=4, **OPTIONS["r2_ra_pipe_k8"]["params"])
    a_p, a_s = adc(ra, 0.7, 1.41), adc(dict(ra, pipe_ra=False), 0.7, 1.41)
    assert a_p["t_conv_ns"] < a_s["t_conv_ns"] and a_p["e_conv_fJ"] == a_s["e_conv_fJ"]
    a_i = adc(dict(ra, dac="inj"), 0.7, 1.41)
    assert abs(a_i["noise_uV"]["dac"] / a_p["noise_uV"]["dac"] - math.sqrt(2)) < 1e-9
    assert all(5e-22 < _kappa_meas(dict(cmp_cls=c), k.get("kT_300K_J"))[0] < 3.5e-21 for c in FIA)
    # critic r2: the pool-bus wire attenuates the pooled node, the decision broadcast is charged, the period covers
    # window + back stage, and the FIA area follows the measured device (>= 2E/V^2 law)
    ld = dict(base, rows=8, adc_share=4, **OPTIONS["r2_ra_pipe_k4"]["params"])
    a_l = adc(dict(ld, tile_pitch_um=124.0), 0.7, 1.41)
    tb = a_l["t_breakdown_ps"]
    assert tb["bcast_ps"] > 0 and a_l["t_conv_ns"] * 1e3 >= tb["back_ps"] + tb["window_ps"] - 1e-6
    assert a_l["cmp_load"]["g_bus"] < 1.0
    assert adc(dict(ld, tile_pitch_um=248.0), 0.7, 1.41)["cmp_load"]["g_bus"] < a_l["cmp_load"]["g_bus"]
    print("PASS")
