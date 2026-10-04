"""StrongARM comparator: decision, offset, delay, output levels.

Spec rows (analog/strongarm/docs/architecture.md):
  resolves both polarities at |vdiff| = 10 mV
  single decision flip across -10..+10 mV (no chatter); |offset| < 10 mV
  clk -> decision < 3 ns at 100 mV overdrive
  outputs rail-to-rail complementary into 10 fF

Convention: vinp > vinn -> outp resolves LOW.
Adapted from AnalogIOC analog/testbenches/tb_strongarm.py (ngspice batch -> SpiceRack).
"""
import sys
from pathlib import Path

A = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(A / "docs"), str(A / "common")]
from bench import Report, testbench  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402

PORTS = ["vinp", "vinn", "outp", "outn", "clk", "vdd", "vss"]
VDD = get_pdk().vdd
VCM = VDD / 2
SIM_TIME = 30e-9
CLK_RISE = 5e-9
CLK_EDGE = 1e-9
C_LOAD = 10e-15


def run(vdiff):
    tb = testbench("strongarm", PORTS)
    tb.V(name="sup", positive="vdd", negative="0", value=VDD)
    tb.V(name="ss", positive="vss", negative="0", value=0.0)
    tb.V(name="inp", positive="vinp", negative="0", value=VCM + vdiff / 2)
    tb.V(name="inn", positive="vinn", negative="0", value=VCM - vdiff / 2)
    tb.PieceWiseLinearVoltageSource(
        name="clk", positive="clk", negative="0",
        values=[(0, 0), (CLK_RISE, 0), (CLK_RISE + CLK_EDGE, VDD), (SIM_TIME, VDD)])
    tb.C(name="lp", positive="outp", negative="0", value=C_LOAD)
    tb.C(name="ln", positive="outn", negative="0", value=C_LOAD)
    tb.save("V(clk)", "V(outp)", "V(outn)")
    return tb.transient(step_time=0.05e-9, end_time=SIM_TIME)


def crossing(t, v, level, falling=False):
    for i in range(1, len(t)):
        if (v[i - 1] > level >= v[i]) if falling else (v[i - 1] < level <= v[i]):
            return t[i]
    return None


def main():
    r = Report("strongarm")

    offsets_mv = list(range(-10, 11, 2))
    decisions = [1 if run(mv * 1e-3)["outp"][-1] > VDD / 2 else 0 for mv in offsets_mv]
    print(f"  decisions (vdiff {offsets_mv[0]}..{offsets_mv[-1]} mV): {decisions}")
    r.check("resolves both polarities at +-10 mV", decisions[0] == 1 and decisions[-1] == 0)
    flips = [i for i in range(1, len(decisions)) if decisions[i - 1] != decisions[i]]
    r.check("single decision flip (no chatter)", len(flips) == 1)
    if flips:
        off = offsets_mv[flips[0]]
        r.check("|offset| < 10 mV", abs(off) <= 10, f"flip at {off} mV")

    d = run(0.1)
    t = d.time
    t_clk = crossing(t, d["clk"], VDD / 2)
    t_out = crossing(t, d["outp"], VDD / 2, falling=True)
    delay = (t_out - t_clk) if t_clk is not None and t_out is not None else None
    r.check("clk->decision < 3 ns @ 100 mV", delay is not None and 0 < delay < 3e-9,
            f"{delay * 1e9:.2f} ns" if delay else "no edge")
    r.check("outputs rail-to-rail complementary",
            d["outn"][-1] > VDD - 0.1 and d["outp"][-1] < 0.1,
            f"outn {d['outn'][-1]:.3f} V, outp {d['outp'][-1]:.3f} V")
    r.done()


if __name__ == "__main__":
    main()
