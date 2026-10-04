"""Self-timed sequencer + t_q tap chain — topology + sizing. Prints the bare deck.

AnalogIOC components/async_ctrl, device for device. `async_ctrl` turns a GO edge into the
column phases: xbar_rst pulse (reset delay chain) -> settle (settle delay chain) ->
adc_go; adc_done is buffered back out as latch_out / done. `tq_chain` is the t_q PWM
grid (tap k rises k*t_q after `in`); analogioc instantiates it next to async_ctrl.
`muller_c` is in AnalogIOC's deck but instantiated nowhere — ported for deck parity.

Sizing (spec: analog/async_ctrl/docs/architecture.md). All logic, no gm/ID coordinate
(every device switches rail to rail, VGS = VDD):
  inverter  Wn = min W, L = min L. Wp = Wn * sqrt(r), r = J_D,n / J_D,p at |VGS| = VDD
            from the gm/ID tables: the minimum-average-delay P/N ratio for a chain of
            identical inverters (Rabaey, Digital ICs, sec. 5.4). AnalogIOC: 0.42/0.84.
  nand2     2-stack pull-down doubled (Wn = 2 * inverter Wn) for inverter-equal fall;
            parallel pull-up = inverter Wp. AnalogIOC: 0.84/0.84.
  loads     reset/settle chains: specs.design() c_load_delay per inverter.
            tq_chain: inverters TQ_M x wider (matching, see TQ_M); C per inverter from
            the t_q target, t_stage = 2 inverters,
                t_inv = K_RAMP * C * (VDD/2) / I_on,  I_on = J_D(VGS=VDD) * W
            averaged over one fall + one rise. AnalogIOC: 550 fF (hand-calibrated).
  muller_c  series stacks doubled (2 x inverter W); keepers min W at 4 x min L (~1/4 of
            the stack drive, so the stack always wins); feedback inverter = inverter.
"""
import sys
from pathlib import Path

A = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(A / "docs"), str(A / "common")]
import gmid  # noqa: E402
import specs  # noqa: E402
from devices import deck, fet, mim_cap  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402

import spicerack as ps  # noqa: E402

PORTS = ["go", "adc_done", "xbar_rst", "adc_go", "latch_out", "done", "vdd", "vss"]
# ponytail: calibration knob. Inner chain stages see the previous stage's slow ramp, not
# a step: measured/step-model delay = 10.15 ns / 6.15 ns on AnalogIOC's 550 fF chain.
K_RAMP = 1.65
KEEPER_L = 4           # muller keeper L in units of min L (drive ~1/4 of the stack)
# tq_chain inverters at TQ_M x the logic inverter width, for matching (Pelgrom:
# sigma ~ 1/sqrt(WL)). tb_async_ctrl_mc at 1x: stage sigma 3.1%, worst 3-stage spread
# 10.15% of 30 samples (spec 10%); 2x area -> / sqrt(2). C_tq follows the drive.
TQ_M = 2


def tq_ports(n_taps=None):
    n_taps = n_taps or specs.design()["tq_n_taps"]
    return ["in"] + [f"tap{k + 1}" for k in range(n_taps)] + ["vdd", "vss"]


def i_on(dev, W, pdk):
    """Saturation drive [A] at |VGS| = VDD (mid-VDS gm/ID table slice)."""
    t = gmid.load_table(dev, pdk.min_l)
    return float(gmid.pchip(t["VGS"], t["ID_per_W"], pdk.vdd)) * W


def sizes(pdk=None):
    """{device: (W, L)} in um and {load: C} in F, from the active PDK."""
    pdk = pdk or get_pdk()
    L, wn = pdk.min_l, pdk.min_w
    r = i_on("nfet", 1.0, pdk) / i_on("pfet", 1.0, pdk)
    wp = round(wn * r ** 0.5, 2)
    # t_stage = K_RAMP * C * VDD/2 * (1/I_n + 1/I_p)  ->  C for t_stage = TQ_SIM
    c_tq = specs.TQ_SIM / (K_RAMP * pdk.vdd / 2 * (1 / i_on("nfet", TQ_M * wn, pdk)
                                                  + 1 / i_on("pfet", TQ_M * wp, pdk)))
    return {
        "inv_n": (wn, L), "inv_p": (wp, L),
        "tq_n": (TQ_M * wn, L), "tq_p": (TQ_M * wp, L),
        "nand_n": (2 * wn, L), "nand_p": (wp, L),
        "mul_n": (2 * wn, L), "mul_p": (2 * wp, L),
        "keep_n": (wn, KEEPER_L * L), "keep_p": (wn, KEEPER_L * L),
        "c_delay": specs.design(pdk)["c_load_delay"],
        "c_tq": round(c_tq, 17),
    }


def inv(s, name, out, inp, sz, pdk, kind="inv"):
    fet(s, f"{name}_n", out, inp, "vss", "vss", "nfet", *sz[f"{kind}_n"], pdk=pdk)
    fet(s, f"{name}_p", out, inp, "vdd", "vdd", "pfet", *sz[f"{kind}_p"], pdk=pdk)


def nand2(s, name, out, a, b, sz, pdk):
    """AnalogIOC nand2 minus its 1 fF ideal cap on the stack node (a convergence stub,
    not layout-realisable: below the MIM minimum)."""
    fet(s, f"{name}_p1", out, a, "vdd", "vdd", "pfet", *sz["nand_p"], pdk=pdk)
    fet(s, f"{name}_p2", out, b, "vdd", "vdd", "pfet", *sz["nand_p"], pdk=pdk)
    fet(s, f"{name}_n1", out, a, f"{name}_mid", "vss", "nfet", *sz["nand_n"], pdk=pdk)
    fet(s, f"{name}_n2", f"{name}_mid", b, "vss", "vss", "nfet", *sz["nand_n"], pdk=pdk)


def delay_chain(name, n_stages, sz, pdk, caps=True):
    """n_stages loaded inverters, in -> out (inverting when n_stages is odd)."""
    s = ps.Subcircuit(name, ["in", "out", "vdd", "vss"])
    for i in range(n_stages):
        src = "in" if i == 0 else f"d{i - 1}"
        dst = "out" if i == n_stages - 1 else f"d{i}"
        inv(s, f"{i}", dst, src, sz, pdk)
        if caps:
            mim_cap(s, f"load{i}", dst, "vss", sz["c_delay"], pdk=pdk)
    return s


def tq_chain(pdk=None, n_taps=None, caps=True):
    """t_q grid: each tap = 2 loaded inverters after the previous (input polarity)."""
    pdk = pdk or get_pdk()
    sz = sizes(pdk)
    ports = tq_ports(n_taps)
    s = ps.Subcircuit("tq_chain", ports)
    prev = "in"
    for tap in ports[1:-2]:
        mid = f"{tap}_m"
        for src, dst in ((prev, mid), (mid, tap)):
            inv(s, f"tq_{dst}", dst, src, sz, pdk, kind="tq")
            if caps:
                mim_cap(s, f"load_{dst}", dst, "vss", sz["c_tq"], pdk=pdk)
        prev = tap
    return s


def muller_c(pdk=None):
    pdk = pdk or get_pdk()
    sz = sizes(pdk)
    s = ps.Subcircuit("muller_c", ["a", "b", "out", "vdd", "vss"])
    fet(s, "p1", "out", "a", "n1p", "vdd", "pfet", *sz["mul_p"], pdk=pdk)
    fet(s, "p2", "n1p", "b", "vdd", "vdd", "pfet", *sz["mul_p"], pdk=pdk)
    fet(s, "p3", "out", "out_b", "vdd", "vdd", "pfet", *sz["keep_p"], pdk=pdk)
    fet(s, "n1", "out", "a", "n1n", "vss", "nfet", *sz["mul_n"], pdk=pdk)
    fet(s, "n2", "n1n", "b", "vss", "vss", "nfet", *sz["mul_n"], pdk=pdk)
    fet(s, "n3", "out", "out_b", "vss", "vss", "nfet", *sz["keep_n"], pdk=pdk)
    inv(s, "fb", "out_b", "out", sz, pdk)
    return s


def children(pdk=None, caps=True):
    """Subckts async_ctrl's deck defines ahead of it (AnalogIOC generate() order).
    caps=False drops the MIM load caps (Philis deck, see __main__)."""
    pdk = pdk or get_pdk()
    sz, d = sizes(pdk), specs.design(pdk)
    return [delay_chain("rst_delay", d["n_rst_stages"], sz, pdk, caps),
            delay_chain("settle_delay", d["n_settle_stages"], sz, pdk, caps),
            tq_chain(pdk, caps=caps), muller_c(pdk)]


def build(pdk=None):
    pdk = pdk or get_pdk()
    sz = sizes(pdk)
    s = ps.Subcircuit("async_ctrl", PORTS)
    inv(s, "inv_go1", "go_b", "go", sz, pdk)
    inv(s, "inv_go2", "go_buf", "go_b", sz, pdk)
    # reset phase: xbar_rst = go_buf AND NOT(go delayed by the reset chain)
    s.X("rst_dly", "rst_delay", "go_buf", "rst_dly_raw", "vdd", "vss")
    inv(s, "inv_rd1", "rst_dly_b", "rst_dly_raw", sz, pdk)
    inv(s, "inv_rd2", "rst_delayed", "rst_dly_b", sz, pdk)
    nand2(s, "nand_rst", "rst_nand", "go_buf", "rst_dly_b", sz, pdk)
    inv(s, "inv_rst", "xbar_rst", "rst_nand", sz, pdk)
    # settle phase
    s.X("settle_dly", "settle_delay", "rst_delayed", "stl_dly_raw", "vdd", "vss")
    inv(s, "inv_sd1", "stl_dly_b", "stl_dly_raw", sz, pdk)
    inv(s, "inv_sd2", "settle_delayed", "stl_dly_b", sz, pdk)
    # adc phase
    inv(s, "inv_ag1", "adc_go_b", "settle_delayed", sz, pdk)
    inv(s, "inv_ag2", "adc_go", "adc_go_b", sz, pdk)
    # done
    inv(s, "inv_ld1", "latch_b", "adc_done", sz, pdk)
    inv(s, "inv_ld2", "latch_out", "latch_b", sz, pdk)
    inv(s, "inv_dn1", "done_b", "latch_out", sz, pdk)
    inv(s, "inv_dn2", "done", "done_b", sz, pdk)
    return s


if __name__ == "__main__":
    # async_ctrl.py [tq_chain] [--no-caps]
    #   tq_chain   tq_chain alone as the top, for its own Philis run
    #   --no-caps  without the MIM load caps: Philis's feedback extraction never finishes
    #              on a deck with several cap_mim devices (>8 h at iteration 0), so the
    #              FETs are P&R'd alone and pex.py re-adds the caps from the full deck
    caps = "--no-caps" not in sys.argv
    print(deck(tq_chain(caps=caps)) if "tq_chain" in sys.argv
          else deck(*children(caps=caps), build()), end="")
