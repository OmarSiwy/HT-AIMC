"""CMOS transmission gate: R_on across the input range, charge injection, off-leakage.

Spec rows (analog/cmos_switch/docs/architecture.md), default instance = write-DAC tap,
over its signal range [0, V_W], V_W = VCM_FRAC*VDD (AnalogIOC's 0.9 V write ceiling):
  R_on(v_in) <= r_on_budget()                          (write-settle budget)
  |charge-injection pedestal| on c_store <= LSB_W/2
  mux leakage error (MUX_N-1) * I_off(|V_DS| = V_W) * R_on,peak <= LSB_W/4
LSB_W = V_W / (MUX_N-1), the write-DAC step. A write opens the gain-cell switch before
the tap code moves, so the TG's charge lands on the re-driven bus, not the store; the
pedestal bound is the mis-sequenced case, which then owns the whole 1/2 LSB_W. Leakage
acts while the cell switch is on and shares 1/2 LSB_W with that switch's own pedestal.
R_on is printed over the full [0, VDD] too — parents using the default size mid-rail
read it there.

New (AnalogIOC had no cmos_switch testbench; SIZING.md (c) measured R_on by hand).
"""
import sys
from pathlib import Path

A = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(A / "docs"), str(A / "common"), str(A / "cmos_switch" / "netlist")]
import specs  # noqa: E402
from bench import Report, testbench  # noqa: E402
from cmos_switch import DV, PORTS, r_on_budget, v_write  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402

VDD = get_pdk().vdd
C_STORE = specs.design()["c_store"]
R_ON_MAX = r_on_budget()
EDGE = 0.1e-9           # ctrl edge (AnalogIOC phase clocks: 0.1 ns)
T_OFF = 20e-9           # switch opens here (c_store long settled at ~26k * 30f)
WRITE_BITS = 4          # write_dac / rstring_ladder: 4b R-string + 16:1 TG tap mux
MUX_N = 2 ** WRITE_BITS
V_W = v_write()
LSB_W = V_W / (MUX_N - 1)
PED_MAX = LSB_W / 2
LEAK_MAX = LSB_W / 4


def supplies(tb, on=True):
    tb.V(name="sup", positive="vdd", negative="0", value=VDD)
    tb.V(name="ss", positive="vss", negative="0", value=0.0)
    if on is not None:
        tb.V(name="c", positive="ctrl", negative="0", value=VDD if on else 0.0)
        tb.V(name="cb", positive="ctrl_b", negative="0", value=0.0 if on else VDD)


def r_on_curve():
    """R_on(v_in): out held DV below in_ by a series source, I read through it."""
    tb = testbench("cmos_switch", PORTS)
    supplies(tb)
    tb.V(name="in", positive="in_", negative="0", value=0.0)
    tb.V(name="dv", positive="in_", negative="out", value=DV)
    res = tb.dc(Vin=slice(0.0, VDD, VDD / 18))
    i = res["i(vdv)"]
    return list(res.sweep), [DV / abs(x) for x in i]


def pedestal(v_in):
    """V(out) after the switch opens minus before, on c_store."""
    tb = testbench("cmos_switch", PORTS)
    supplies(tb, on=None)
    tb.V(name="in", positive="in_", negative="0", value=v_in)
    tb.PieceWiseLinearVoltageSource(name="c", positive="ctrl", negative="0", values=[
        (0, VDD), (T_OFF, VDD), (T_OFF + EDGE, 0), (T_OFF + 10e-9, 0)])
    tb.PieceWiseLinearVoltageSource(name="cb", positive="ctrl_b", negative="0", values=[
        (0, 0), (T_OFF, 0), (T_OFF + EDGE, VDD), (T_OFF + 10e-9, VDD)])
    tb.C(name="h", positive="out", negative="0", value=C_STORE)
    tb.save("V(out)")
    r = tb.transient(step_time=0.01e-9, end_time=T_OFF + 5e-9, max_time=0.02e-9)
    t, v = r.time, r["out"]
    before = next(v[k] for k in range(len(t) - 1, -1, -1) if t[k] <= T_OFF)
    return v[-1] - before


def i_off(v_in, v_out):
    tb = testbench("cmos_switch", PORTS)
    supplies(tb, on=False)
    tb.V(name="in", positive="in_", negative="0", value=v_in)
    tb.V(name="o", positive="out", negative="0", value=v_out)
    op = tb.operating_point()
    return abs(op["i(vo)"])


def main():
    r = Report("cmos_switch")

    v, ron = r_on_curve()
    print("  R_on (kohm) " + " ".join(f"{x:.2f}:{y / 1e3:.1f}" for x, y in zip(v, ron)))
    k = max((i for i in range(len(v)) if v[i] <= V_W + 1e-9), key=ron.__getitem__)
    r.check(f"R_on <= budget over [0, {V_W:.2f}] V", ron[k] <= R_ON_MAX,
            f"peak {ron[k] / 1e3:.1f} kohm at {v[k]:.2f} V, budget {R_ON_MAX / 1e3:.0f} kohm")

    steps = [V_W * i / 6 for i in range(7)]
    ped = [pedestal(x) for x in steps]
    print("  pedestal (mV) " + " ".join(f"{x:.2f}:{p * 1e3:+.1f}" for x, p in zip(steps, ped)))
    worst = max(ped, key=abs)
    r.check(f"|pedestal| on {C_STORE * 1e15:.0f} fF <= {PED_MAX * 1e3:.0f} mV",
            abs(worst) <= PED_MAX, f"worst {worst * 1e3:+.2f} mV")

    leak = max(i_off(V_W, 0.0), i_off(0.0, V_W))
    err = (MUX_N - 1) * leak * ron[k]
    r.check(f"mux leakage error <= {LEAK_MAX * 1e3:.0f} mV", err <= LEAK_MAX,
            f"I_off {leak * 1e12:.1f} pA -> {err * 1e3:.3f} mV")
    r.done()


if __name__ == "__main__":
    main()
