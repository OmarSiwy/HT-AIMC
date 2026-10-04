"""o-charge accumulation + retroactive stored-charge rescale on the OTA column integrator.

Spec row (analog/ota/docs/architecture.md): after a 3-block rising-max stream, the
charge-accumulated and twice-rescaled o matches golden online_softmax_monoid o within
O_BUDGET (5 %; AnalogIOC measured 3.59 %).

Path (AnalogIOC Chip 2 inc 3b, CHIP2_SPEC 4): the OTA with C_int from out to the virtual
ground inn (inp = vcm) is the column integrator.
  1. ACCUMULATE: each block's o-partial lands as one timed current packet on inn
     (gain-cell read current x I->T duration); Q/C_int moves out.
  2. RESCALE: when the running max rises, the STORED o-charge is multiplied by
     g = exp(beta*(m_old - m_new)) by sharing C_int with an empty C_share, sized so
     C_int/(C_int+C_share) = g, through an NMOS switch. Loss sources in the netlist: OTA
     finite gain, switch charge injection, redistribution settling.
The verdict AnalogIOC drew (analog rescale holds at mini scale but compounds per rescale
-> the long-axis rescale lives in the fp32 island) is printed, not asserted.

Adapted from AnalogIOC analog/testbenches/tb_o_charge.py (ngspice batch -> SpiceRack).
"""
import sys
from pathlib import Path

import numpy as np

A = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(A / "docs"), str(A / "common"), str(Path(__file__).parent), str(A.parent / "scripts")]
import golden.model as G  # noqa: E402
import specs  # noqa: E402
from bench import Report  # noqa: E402
from devices import fet  # noqa: E402
from ota_bench import ota_testbench  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402

PDK = get_pdk()
VDD = PDK.vdd
VCM = specs.VCM_FRAC * VDD
C_INT = specs.c_int()
C_LOAD = 50e-15                    # comparator/filter load on out (AnalogIOC)
TIGHT = dict(reltol=1e-4, abstol=1e-14, vntol=1e-7, method="gear")
O_BUDGET = 0.05                    # CHIP2_SPEC 4 analog ~2 % + margin
BETA = 1.0
SCALE = 0.15                       # o -> volts on C_int, keeps out inside the swing
I_READ = 2e-6                      # gain-cell read-current class
# Share switch: min size. R_on ~ L/(un_cox W (VDD-VCM-vth_n)) ~ 3 kohm -> R_on*C_share
# < 1 ns, << the 350 ns share window; the smallest W minimises the channel + overlap
# charge it dumps on the virtual ground (the loss term under test). AnalogIOC: W = 20 um.
W_SHARE_SW = PDK.min_w
BLOCKS = [  # (scores, values), rising max so the stored o is rescaled every block
    (np.array([0.20, 0.05, 0.15, 0.10]), np.array([1.0, -0.5, 0.8, 0.3])),
    (np.array([0.60, 0.30, 0.45, 0.25]), np.array([-0.4, 0.9, 0.2, 0.6])),
    (np.array([1.10, 0.70, 0.85, 0.60]), np.array([0.5, -0.2, 0.7, -0.3])),
]


def integrator(tb):
    """inp = vcm, C_int out -> inn (the virtual ground), out load."""
    tb.options(**TIGHT)
    tb.V(name="cm", positive="inp", negative="0", value=VCM)
    tb.C(name="int", positive="inn", negative="out", value=C_INT)
    tb.C(name="load", positive="out", negative="0", value=C_LOAD)
    tb.save("V(out)")


def integrate_charge(i_pkt, dur):
    """One packet I*dur onto the reset integrator -> settled V(out) - VCM."""
    tb = ota_testbench()
    integrator(tb)
    tb.initial_condition(out=VCM, inn=VCM)
    t = 100e-9                                   # settle margin before the packet
    tb.PieceWiseLinearCurrentSource(             # inn -> 0 sinks charge: out rises
        name="p", positive="inn", negative="0",
        values=[(0, 0), (t, 0), (t + 1e-12, i_pkt), (t + dur, i_pkt),
                (t + dur + 1e-12, 0), (t + dur + 220e-9, 0)])
    r = tb.transient(step_time=1e-9, end_time=t + dur + 220e-9, use_initial_condition=True)
    return r["out"][-1] - VCM


def o_packet(o):
    """Signed o -> (I, t) with Q/C_int = o*SCALE."""
    return np.sign(o) * I_READ, max(abs(o) * SCALE * C_INT / I_READ, 1e-12)


def rescale_stored(v_stored, g):
    """Stored V(out)-VCM = v_stored on C_int; close a switch at 50 ns onto an empty
    C_share = C_int(1-g)/g (across inn -> out) -> V(out)-VCM ~ g*v_stored."""
    if g >= 0.999:
        return v_stored
    tb = ota_testbench(lambda top: fet(top, "shsw", "cs_top", "swg", "inn", "vss", "nfet",
                                       W_SHARE_SW, PDK.min_l, pdk=PDK))
    integrator(tb)
    tb.C(name="sh", positive="cs_top", negative="out", value=C_INT * (1 - g) / g)
    tb.PieceWiseLinearVoltageSource(name="sw", positive="swg", negative="0",
                                    values=[(0, 0), (50e-9, 0), (50.01e-9, VDD), (400e-9, VDD)])
    # C_share empty: both plates at V(out). AnalogIOC's .ic put cs_top at vcm, which
    # pre-charges C_share to the stored voltage and shares nothing; its W = 20 um
    # switch's injection (~25 fC) then pulled V(out) down by about the missing factor.
    tb.initial_condition(out=VCM + v_stored, inn=VCM, cs_top=VCM + v_stored)
    r = tb.transient(step_time=1e-9, end_time=400e-9, use_initial_condition=True)
    return r["out"][-1] - VCM


def main():
    r = Report("ota o-charge accumulate + retroactive rescale")
    m_g, l_g, o_g = G.online_softmax_monoid(list(BLOCKS), BETA)
    print(f"  golden final: m={m_g:.3f} l={l_g:.3f} o={o_g:.4f}")

    m_run, v_run, o_ideal, errs = None, 0.0, 0.0, []
    for i, (s, v) in enumerate(BLOCKS):
        m_i, _, o_i = G.block_reduce(s, v, BETA)
        if m_run is None:
            m_run, o_ideal = m_i, o_i
            v_run = integrate_charge(*o_packet(o_i))
        else:
            m_new = max(m_run, m_i)
            g_run, g_new = np.exp(BETA * (m_run - m_new)), np.exp(BETA * (m_i - m_new))
            v_run = rescale_stored(v_run, g_run) + integrate_charge(*o_packet(o_i * g_new))
            m_run, o_ideal = m_new, o_ideal * g_run + o_i * g_new
        errs.append(abs(v_run / SCALE - o_ideal) / (abs(o_ideal) + 1e-9))
        print(f"  after block{i}: o analog={v_run / SCALE:+.4f} ideal={o_ideal:+.4f} "
              f"(rel {errs[-1] * 100:.2f} %)  m_run={m_run:.2f}")

    o_rel = abs(v_run / SCALE - o_g) / (abs(o_g) + 1e-9)
    r.check(f"final o within {O_BUDGET * 100:.0f} % of golden", o_rel <= O_BUDGET,
            f"{o_rel * 100:.2f} %, per step " + ", ".join(f"{e * 100:.2f}" for e in errs))
    print("  verdict: error compounds per rescale -> the long-axis retroactive rescale "
          "belongs in the fp32 island (CHIP2_SPEC 4 level 2)")
    r.done()


if __name__ == "__main__":
    main()
