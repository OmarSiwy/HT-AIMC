"""Column converter — integrator + event-rate coarse loop + 4b resampling SAR. Prints the
bare .subckt deck (children first: ota, strongarm, pwm_driver, switches).

AnalogIOC components/integrator_conv (subckt `int_conv`) minus its XSPICE decision state
and internal bias sources, per the macro contract (analog/analogioc/docs/INTERFACE.md
§5, D3): the converter exports raw comparator outputs; the sign latch, the coarse/fine
handshakes and every strobe live in async_ctrl's conv_seq. Ports, in contract order:

    vg out rst phi1 phi1e phi2 run fire sign sgd clk_c c1p c1n acq clk_f b3 b2 b1 b0
    c2p c2n awake thr_p thr_n sar_p sar_n vcm vb_nc vb_pc vb_tail
    vdd_ota vdd_cmp vdd_pkt vdd vss

Topology (unchanged from AnalogIOC):
  integrator  ota (inp = vcm, inn = vg) + C_int out->vg + reset TG. Bias gate (item S4):
              vb_tail / vb_pc reach the OTA through TGs closed by `awake`; parked, the
              tail gate is pulled to vss and the load-cascode gate to vdd, so the
              residue holds on the floating out / C_int / filter node.
  packet      a weight_tile bank clone (C_pkt = specs.c_pkt(D=1) = 16 code units, same
              TG / ballast / dummies) driven by a pwm_driver through the converter chop;
              phis gated by `run`. fire*sign -> driver inn (lowers out), fire*!sign ->
              inp. Identical structure to the signal banks keeps the conversion
              ratiometric (bank gain divides out of code = Q_sig / Q_pkt).
  coarse SA1  out through the anti-kick R-C (specs.kick_filter) vs a vinn mux: vcm while
              !sgd (sign strobe), thr_p if sign else thr_n after.
  fine SA2    charge-redistribution CDAC (8/4/2/1 units + half unit to the OPPOSITE
              reference = mid-tread round-half-away + terminator to vcm), bottom-plate
              sampling of `out` during acq, top reset to vcm; vref = sar_p if sign else
              sar_n (vref_o the other), each behind a reservoir cap. R-C to SA2
              (RC = specs.RC_KICK on C_FILT_MIN, AnalogIOC 8k/60f).
  kick        CHANGED from AnalogIOC: both comparators' reference inputs are replicas of
              their signal inputs, so the StrongARM strobe kick lands common-mode. SA1:
              mux -> replica of out's load (C_out) -> same R-C. SA2: a floating replica of
              the CDAC top (same C, same reset TG, same R-C) instead of hard vcm. Why: the
              migrated strongarm's input pair (MC-sized, 21.8/0.60 um) has ~13x AnalogIOC's
              gate area; against hard vcm the SA2 strobe kicked the floating CDAC top by
              ~-48 mV (AnalogIOC measured -3.7 mV) and every trial read "keep".
  outputs     c1p/c1n, c2p/c2n: StrongARM outp/outn through 2 inverters (vdd logic).

Sizing (no gm/ID coordinate below the OTA and StrongARM, which size themselves):
  rst TG      R_on: C_int to B_Y bits inside the contract's minimum reset, T_RST_MIN.
  packet      weight_tile.sizes() TG / dummy / ballast (identical to a signal bank);
              phi buffers: weight_tile's edge rule (EDGE_SWING*VDD*C_line / I_on inside
              PHI_EDGE) on ONE bank's gate load.
  tgd         CDAC, reference and park switches. Mid-rail TGs, where both devices are
              weak: R_on from the TG's MEASURED peak (rstring_ladder.tg_peak_r_on, R*W
              const, CORNER_GUARD x for slow/cold) so the whole CDAC settles to B_Y bits
              inside the shortest acquisition, T_ACQ (async_ctrl). W_p/W_n = un/up.
  C_DAC unit  specs.design() c_dac_u.
  C_vref      reservoir: one full CDAC charge at the fine span droops it by V_TAP_TOL/2
              (the ladder tap tolerance): C = 16*C_u_dac * 16*u_cal*trim / (V_TAP_TOL/2).
  logic       async_ctrl's gates (Logic): inverter, nand2, nor2.
"""
import math
import sys
from pathlib import Path

A = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(A / "docs"), str(A / "common")] + [
    str(A / b / "netlist") for b in ("ota", "strongarm", "pwm_driver", "cmos_switch",
                                     "weight_tile", "rstring_ladder", "async_ctrl")]
import async_ctrl  # noqa: E402
import cmos_switch  # noqa: E402
import ota  # noqa: E402
import pwm_driver  # noqa: E402
import rstring_ladder  # noqa: E402
import specs  # noqa: E402
import strongarm  # noqa: E402
import weight_tile as wt  # noqa: E402
from devices import deck, fet, mim_cap, poly_res  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402

import spicerack as ps  # noqa: E402

PORTS = ["vg", "out", "rst", "phi1", "phi1e", "phi2", "run", "fire", "sign", "sgd",
         "clk_c", "c1p", "c1n", "acq", "clk_f", "b3", "b2", "b1", "b0", "c2p", "c2n",
         "awake", "thr_p", "thr_n", "sar_p", "sar_n", "vcm", "vb_nc", "vb_pc", "vb_tail",
         "vdd_ota", "vdd_cmp", "vdd_pkt", "vdd", "vss"]
T_RST_MIN = 20e-9        # INTERFACE.md §6.2 I1: reset >= 20 ns (async_ctrl rst chain)
N_BITS = 4


def sizes(pdk=None):
    pdk = pdk or get_pdk()
    L, vdd = pdk.min_l, pdk.vdd
    c_int = specs.c_int(pdk)
    tile = wt.sizes(pdk)
    # integrator reset TG: R_on * C_int * (B_Y+1) ln2 <= T_RST_MIN
    rst = cmos_switch.sizes(r_on=T_RST_MIN / ((specs.B_Y + 1) * math.log(2) * c_int), pdk=pdk)
    # mid-rail TGs from the measured peak R_on (R*W constant)
    c_dac_u = specs.design(pdk)["c_dac_u"]
    c_dac = 2 ** N_BITS * c_dac_u
    r_budget = async_ctrl.T_ACQ / ((specs.B_Y + 1) * math.log(2) * c_dac)
    ratio = pdk.un_cox / pdk.up_cox
    w_ref = rstring_ladder.W_REF_MULT * pdk.min_w
    r_ref = rstring_ladder.tg_peak_r_on(w_ref, ratio * w_ref, pdk)
    wn = max(pdk.min_w, round(rstring_ladder.CORNER_GUARD * w_ref * r_ref / r_budget, 2))
    tgd = {"w_n": wn, "l_n": L, "w_p": max(pdk.min_w, round(ratio * wn, 2)), "l_p": L}
    # packet phi buffers: weight_tile's edge rule on one bank
    ch = wt._char(pdk)
    w_tg, w_dum = tile["tg"][0], tile["dummy"][0]
    c_line = (ch["cg_n"] * w_tg + ch["cg_p"] * max(w_tg, w_dum)) * 1e-15
    i_on = wt.EDGE_SWING * vdd * c_line / wt.PHI_EDGE
    k_phi = max(1, math.ceil(i_on / pwm_driver.j_on("nfet", pdk) / pdk.min_w))
    r_kf, c_kf = specs.kick_filter(pdk)
    trim, u = specs.fine_ref_trim(pdk), specs.u_cal(pdk)
    # out's own load behind the SA1 filter: OTA self-load + C_int in series with the
    # virtual-ground parasitic (the tau_absorb terms of specs, minus the filter)
    ca, o = specs.cal(pdk), specs.ota(pdk)
    c_out = (ca["c_ota_self"] * o["i_side"] / ca["i_side_ref"]
             + c_int * ca["c_par_vg"] / (c_int + ca["c_par_vg"]))
    return {
        "c_int": c_int, "c_pkt": specs.c_pkt(pdk, D=1), "c_ball": tile["c_ball"],
        "tg": tile["tg"], "dummy": tile["dummy"], "rst": rst, "tgd": tgd, "k_phi": k_phi,
        "r_kf": r_kf, "c_kf": c_kf, "c_out": c_out, "c_dac": c_dac,
        "r_kf2": specs.RC_KICK / specs.C_FILT_MIN, "c_kf2": specs.C_FILT_MIN,
        "c_dac_u": c_dac_u,
        "c_vref": c_dac * 2 ** N_BITS * u * trim / (specs.V_TAP_TOL / 2),
    }


def children(name="integrator_conv", pdk=None, sz=None):
    pdk = pdk or get_pdk()
    sz = sz or sizes(pdk)
    (w, L) = sz["tg"]
    return [ota.build(pdk=pdk), strongarm.build(pdk=pdk), pwm_driver.build(pdk=pdk),
            cmos_switch.build(f"{name}_tg", w_n=w, l_n=L, w_p=w, l_p=L, pdk=pdk),
            cmos_switch.build(f"{name}_tgr", pdk=pdk, **sz["rst"]),
            cmos_switch.build(f"{name}_tgd", pdk=pdk, **sz["tgd"])]


def build(name="integrator_conv", pdk=None, sz=None):
    pdk = pdk or get_pdk()
    sz = sz or sizes(pdk)
    s = ps.Subcircuit(name, PORTS)
    g = async_ctrl.Logic(s, pdk, {})
    tg, tgr, tgd = f"{name}_tg", f"{name}_tgr", f"{name}_tgd"

    def sw(cell, a, b, ctl, ctlb):
        s.X(f"s{g.net()}", cell, a, b, ctl, ctlb, "vdd", "vss")

    # integrator + OTA bias gate
    s.X("ota", "ota", "vcm", "vg", "out", "vb_nc", "vb_pc_i", "vb_tail_i", "vdd_ota", "vss")
    mim_cap(s, "cint", "out", "vg", sz["c_int"], pdk=pdk)
    sw(tgr, "out", "vg", "rst", g.inv("rst"))
    awb = g.inv("awake")
    sw(tgd, "vb_tail", "vb_tail_i", "awake", awb)
    sw(tgd, "vb_pc", "vb_pc_i", "awake", awb)
    fet(s, "park_tail", "vb_tail_i", awb, "vss", "vss", "nfet", pdk.min_w, pdk.min_l, pdk=pdk)
    fet(s, "park_pc", "vb_pc_i", "awake", "vdd", "vdd", "pfet", pdk.min_w, pdk.min_l, pdk=pdk)
    # packet bank (weight_tile bank clone), chop gated by run
    signb = g.inv("sign")
    fire_pos = g.and_("fire", "sign")
    fire_neg = g.and_("fire", signb)
    s.X("pdrv", "pwm_driver", fire_neg, fire_pos, g.and_("phi1", "run"),
        g.and_("phi1e", "run"), "pk_a", "pk_b", "vdd_pkt", "vss")
    mim_cap(s, "cpk", "tpk", "pk_a", sz["c_pkt"], pdk=pdk)
    mim_cap(s, "cballpk", "tpk", "vss", sz["c_ball"], pdk=pdk)
    ph = {}
    for p in ("phi1", "phi2"):
        i = g.inv(g.nand(p, "run"), k=sz["k_phi"])
        ph[p] = (i, g.inv(i, k=sz["k_phi"]))
    sw(tg, "tpk", "vcm", *ph["phi1"])
    sw(tg, "tpk", "vg", *ph["phi2"])
    fet(s, "dunpk", "vg", ph["phi2"][1], "vg", "vss", "nfet", *sz["dummy"], pdk=pdk)
    fet(s, "duppk", "vg", ph["phi2"][0], "vg", "vdd", "pfet", *sz["dummy"], pdk=pdk)
    # coarse comparator SA1 behind the matched anti-kick R-C
    poly_res(s, "rk1p", "out", "cmp1p", sz["r_kf"], "vss", pdk=pdk)
    mim_cap(s, "ck1p", "cmp1p", "vss", sz["c_kf"], pdk=pdk)
    # reference side = a replica of the signal side (out's load, R, C): the StrongARM
    # kick lands common-mode
    mim_cap(s, "cout_r", "m1n", "vss", sz["c_out"], pdk=pdk)
    poly_res(s, "rk1n", "m1n", "cmp1n", sz["r_kf"], "vss", pdk=pdk)
    mim_cap(s, "ck1n", "cmp1n", "vss", sz["c_kf"], pdk=pdk)
    s.X("sa1", "strongarm", "cmp1p", "cmp1n", "out1p", "out1n", "clk_c", "vdd_cmp", "vss")
    g.inv(g.inv("out1p"), "c1p")
    g.inv(g.inv("out1n"), "c1n")
    g_thp_n = g.nand("sgd", "sign")
    g_thn_n = g.nand("sgd", signb)
    g_thp, g_thn = g.inv(g_thp_n), g.inv(g_thn_n)
    sw(tgd, "vcm", "m1n", g.inv("sgd"), "sgd")
    sw(tgd, "thr_p", "m1n", g_thp, g_thp_n)
    sw(tgd, "thr_n", "m1n", g_thn, g_thn_n)
    # SAR CDAC + SA2
    acqb = g.inv("acq")
    sw(tgd, "sar_p", "vref", g_thp, g_thp_n)
    sw(tgd, "sar_n", "vref", g_thn, g_thn_n)
    sw(tgd, "sar_n", "vref_o", g_thp, g_thp_n)
    sw(tgd, "sar_p", "vref_o", g_thn, g_thn_n)
    mim_cap(s, "cvref", "vref", "vss", sz["c_vref"], pdk=pdk)
    mim_cap(s, "cvrefo", "vref_o", "vss", sz["c_vref"], pdk=pdk)
    sw(tgd, "ct", "vcm", "acq", acqb)
    poly_res(s, "rk2p", "ct", "cmp2p", sz["r_kf2"], "vss", pdk=pdk)
    mim_cap(s, "ck2p", "cmp2p", "vss", sz["c_kf2"], pdk=pdk)
    # reference side: a floating replica of the CDAC top (same cap, same reset TG, same
    # R-C), reset with it every acquisition, so the SA2 kick lands common-mode
    mim_cap(s, "cdac_r", "ctr", "vcm", sz["c_dac"], pdk=pdk)
    sw(tgd, "ctr", "vcm", "acq", acqb)
    poly_res(s, "rk2n", "ctr", "cmp2n", sz["r_kf2"], "vss", pdk=pdk)
    mim_cap(s, "ck2n", "cmp2n", "vss", sz["c_kf2"], pdk=pdk)
    s.X("sa2", "strongarm", "cmp2p", "cmp2n", "out2p", "out2n", "clk_f", "vdd_cmp", "vss")
    g.inv(g.inv("out2p"), "c2p")
    g.inv(g.inv("out2n"), "c2n")
    for k in range(N_BITS):
        bb = f"bb{k}"
        mim_cap(s, f"cb{k}", "ct", bb, sz["c_dac_u"] * (1 << k), pdk=pdk)
        sw(tgd, "out", bb, "acq", acqb)
        bh_n = g.nand(f"b{k}", acqb)                     # hold: bit -> vref
        bh = g.inv(bh_n)
        bl = g.nor(bh, "acq")                            # hold: !bit -> vcm
        sw(tgd, "vref", bb, bh, bh_n)
        sw(tgd, "vcm", bb, bl, g.inv(bl))
    mim_cap(s, "chalf", "ct", "bbh", sz["c_dac_u"] / 2, pdk=pdk)
    sw(tgd, "out", "bbh", "acq", acqb)
    sw(tgd, "vref_o", "bbh", acqb, "acq")                # mid-tread half LSB
    mim_cap(s, "cterm", "ct", "bbt", sz["c_dac_u"] / 2, pdk=pdk)
    sw(tgd, "out", "bbt", "acq", acqb)
    sw(tgd, "vcm", "bbt", acqb, "acq")
    return s


def text(name="integrator_conv", pdk=None):
    pdk = pdk or get_pdk()
    sz = sizes(pdk)
    return deck(*children(name, pdk, sz), build(name, pdk, sz))


if __name__ == "__main__":
    print(text(), end="")
