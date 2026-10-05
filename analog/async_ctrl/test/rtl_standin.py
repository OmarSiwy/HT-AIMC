"""XSPICE stand-ins for the parts of a column a conv_seq testbench does not simulate at
transistor level (INTERFACE.md §9: "an ideal tile_fsm stand-in ... XSPICE").

rtl(...)   tile_fsm + event_ctrl + sar_ctrl, reduced to what one conversion needs:
           coarse_en rises T_SYNC after sdone (integ_ack, synchronised) and falls on the
           first no-cross (cb_ack rising with cb_cross = 0); cb_ack / cmp_ack-paced
           cmp_req follow their req/ack T_SYNC later (2FF sync at T_CLK_MAX); ota_en is
           low only between coarse done and the fine phase; 4 MSB-first SAR trials
           (dac_code = kept bits | trial bit, kept bit := cmp_result at cmp_ack rise).
           Nets: sdone cb_req cb_cross cmp_ack cmp_result -> coarse_en cb_ack cmp_req
           ota_en b3 b2 b1 b0 rtl_done.
sa1(n_cross), sa2(fine)
           dual-rail comparator stand-ins for conv_seq's own tb: SA1 says "out > vinn" on
           the sign strobe and the next n_cross strobes, then "below"; SA2 keeps a trial
           iff fine >= dac_code.
"""
import sys
from pathlib import Path

A = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(A / "docs")]
from pdk_specs import get_pdk  # noqa: E402

import spicerack as ps  # noqa: E402

T_CLK = 20e-9            # fabric clock = T_CLK_MAX (the slowest the contract allows)
T_SYNC = 2 * T_CLK       # 2FF synchroniser latency
VDD = get_pdk().vdd


def _models(s):
    s.raw_spice(".model xab adc_bridge(in_low={0} in_high={1})".format(0.35 * VDD, 0.65 * VDD))
    s.raw_spice(f".model xdb dac_bridge(out_low=0 out_high={VDD} t_rise=0.2n t_fall=0.2n)")
    s.raw_spice(".model xsync d_buffer(rise_delay={0:g} fall_delay={0:g})".format(T_SYNC))
    s.raw_spice(".model xclk d_buffer(rise_delay={0:g} fall_delay=1n)".format(T_SYNC))
    s.raw_spice(".model xbuf d_buffer(rise_delay=0.5n fall_delay=0.5n)")
    s.raw_spice(".model xand d_and(rise_delay=0.1n fall_delay=0.1n)")
    s.raw_spice(".model xor d_or(rise_delay=0.1n fall_delay=0.1n)")
    s.raw_spice(".model xnand d_nand(rise_delay=0.1n fall_delay=0.1n)")
    s.raw_spice(".model xinv d_inverter(rise_delay=0.1n fall_delay=0.1n)")
    s.raw_spice(".model xff d_dff(clk_delay=0.1n set_delay=0.1n reset_delay=0.1n "
                "ic=0 rise_delay=0.1n fall_delay=0.1n)")
    s.raw_spice(".model xtff d_tff(clk_delay=0.1n set_delay=0.1n reset_delay=0.1n "
                "ic=0 rise_delay=0.1n fall_delay=0.1n)")


def rtl():
    s = ps.Subcircuit("rtl_standin", ["sdone", "cb_req", "cb_cross", "cmp_ack", "cmp_result",
                                      "coarse_en", "cb_ack", "cmp_req", "ota_en",
                                      "b3", "b2", "b1", "b0", "rtl_done"])
    _models(s)
    r = s.raw_spice
    r("Ain [sdone cb_req cb_cross cmp_ack cmp_result] [dsd drq dcx dca dcr] xab")
    # coarse: event_ctrl stops on the first no-cross
    r("Asd dsd dsdl xclk")
    r("Aack drq dcba xsync")
    r("Ancx dcx dncx xinv")
    r("Adnd [ddone dncx] ddnd xor")
    r("Adn ddnd dcba NULL NULL ddone ddoneb xff")
    r("Ace [dsdl ddoneb] dce xand")
    # fine: sar_ctrl, MSB first; ota_en low only between coarse done and S_FINE
    r("Afn ddone dfine xsync")
    r("Aot [ddoneb dfine] dota xor")
    r("Acan dca dcan xinv")
    r("Acur3 dtr3 dcur3 xinv")
    for k in (2, 1, 0):
        r(f"Atb{k} dtr{k} dtrb{k} xinv")
        r(f"Acur{k} [dtr{k + 1} dtrb{k}] dcur{k} xand")
    for k in range(4):
        r(f"Atrd{k} [dtr{k} dcur{k}] dtrd{k} xor")
        r(f"Atr{k} dtrd{k} dcan NULL NULL dtr{k} dtrq{k} xff")
        r(f"Ackb{k} [dca dcur{k}] dckb{k} xand")
        r(f"Ab{k} dcr dckb{k} NULL NULL dbit{k} dbitb{k} xff")
        r(f"Adac{k} [dcur{k} dbit{k}] ddac{k} xor")
    r("Aackd dca dackd xsync")
    r("Aackdb dackd dackdb xinv")
    r("Atr0b dtr0 dtr0b xinv")
    r("Areq [dfine dtr0b dackdb] dreq xand")
    r("Aout [dce dcba dreq dota ddac3 ddac2 ddac1 ddac0 ddone] "
      "[coarse_en cb_ack cmp_req ota_en b3 b2 b1 b0 rtl_done] xdb")
    return s


def sa1(n_cross):
    """SA1 stand-in: strobe k (0 = sign) decides out > vinn for k <= n_cross."""
    s = ps.Subcircuit("sa1_standin", ["clk_c", "c1p", "c1n"])
    _models(s)
    r = s.raw_spice
    r("Ain [clk_c] [dck] xab")
    r("Adl dck dckd xbuf")
    r("Ackn dck dckn xinv")
    prev = "dckn"                      # count completed strobes (falling clk_c edges)
    for b in range(3):
        r(f"At{b} done1 {prev} NULL NULL dq{b} dqb{b} xtff")
        prev = f"dqb{b}"
    r(".model xpu d_pullup(load=1e-15)")
    r("Apu done1 xpu")
    k = n_cross + 1                    # first no-cross strobe index
    lits = " ".join(f"dq{b}" if (k >> b) & 1 else f"dqb{b}" for b in range(3))
    r(f"Aeq [{lits}] deq xand")
    r("Acmp deq dcmp xinv")
    r("Acmpb dcmp dcmpb xinv")
    r("Ap [dckd dcmp] dp xnand")
    r("An [dckd dcmpb] dn xnand")
    r("Aout [dp dn] [c1p c1n] xdb")
    return s


def sa2(fine):
    """SA2 stand-in (sign = 1): keep the trial (c2p stays 1) iff fine >= dac_code."""
    s = ps.Subcircuit("sa2_standin", ["clk_f", "b3", "b2", "b1", "b0", "c2p", "c2n"])
    _models(s)
    r = s.raw_spice
    r("Ain [clk_f b3 b2 b1 b0] [dck db3 db2 db1 db0] xab")
    for k in range(4):
        r(f"Ainv{k} db{k} dbb{k} xinv")
    terms = []
    for c in range(fine + 1):
        lits = " ".join(f"db{k}" if (c >> k) & 1 else f"dbb{k}" for k in range(4))
        r(f"Am{c} [{lits}] dm{c} xand")
        terms.append(f"dm{c}")
    r(f"Ares [{' '.join(terms)}] dres xor" if len(terms) > 1 else f"Ares {terms[0]} dres xbuf")
    r("Aresb dres dresb xinv")
    r("Adl dck dckd xbuf")
    r("Ap [dckd dresb] dp xnand")
    r("An [dckd dres] dn xnand")
    r("Aout [dp dn] [c2p c2n] xdb")
    return s
