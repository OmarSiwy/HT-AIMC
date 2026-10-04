"""OTA unity-gain step settling + slew (spec rows: analog/ota/docs/architecture.md).

  tail (supply) current within 0.4..1.5x specs.ota()["i_tail"]
  static buffer error at VCM < 1 mV; closed-loop gain error < 0.5 % (loop gain > 200)
  50 mV step settles to 0.5 % in < 100 ns and < specs.coarse_cadence()/2 (S1 squeeze)
  0.5 V step: slew rate > 50 V/us, settles to 0.5 % in < 100 ns
Load: CL = specs.c_int() (200 fF), the column integrator cap.

Adapted from AnalogIOC analog/testbenches/tb_ota.py (ngspice batch -> SpiceRack). The tail
current is read as the supply current (the bias gates draw none), so the check runs on
every DUT source instead of probing the tail device. Bias: ota_bench (replica bias
network) instead of AnalogIOC's fixed bias_spice voltages.
"""
import sys
from pathlib import Path

import numpy as np

A = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(A / "docs"), str(A / "common"), str(Path(__file__).parent)]
import specs  # noqa: E402
from bench import Report  # noqa: E402
from ota_bench import REF_CURRENT, ota_testbench  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402

VDD = get_pdk().vdd
VCM = specs.VCM_FRAC * VDD
CL = specs.c_int()
T_STEP = 100e-9
T_END = 250e-9
SETTLE_WINDOW = 100e-9                     # t_q = 10 ns PWM grid budget
SETTLE_SQUEEZE = specs.coarse_cadence() / 2
I_TAIL_SPEC = specs.ota()["i_tail"]
SMALL_STEP = 0.05
V_LO, V_HI = VCM - 0.2, VCM + 0.3          # large step, AnalogIOC 0.7 -> 1.2 V
# sub-mV measurement -> tighter tolerances than the default
TIGHT = dict(reltol=1e-4, abstol=1e-12, vntol=1e-6, method="gear")


def buffer(v0, v1):
    """Unity-gain buffer: out -> inn, inp steps v0 -> v1 at T_STEP."""
    tb = ota_testbench()
    tb.options(**TIGHT)
    tb.PieceWiseLinearVoltageSource(
        name="in", positive="inp", negative="0",
        values=[(0, v0), (T_STEP, v0), (T_STEP + 0.5e-9, v1), (T_END, v1)])
    tb.V(name="fb", positive="out", negative="inn", value=0.0)
    tb.C(name="l", positive="out", negative="0", value=CL)
    tb.save("V(out)", "I(Vsup)")
    r = tb.transient(step_time=0.05e-9, end_time=T_END)
    return np.array(r.time), np.array(r["out"]), -np.array(r["i(vsup)"]) - REF_CURRENT


def settle_time(t, v, target, band, t_from):
    """Time after t_from at which v enters |v-target| < band and stays there."""
    out = np.where((np.abs(v - target) >= band) & (t >= t_from))[0]
    if len(out) == 0:
        return 0.0
    if out[-1] + 1 >= len(t):
        return None
    return t[out[-1] + 1] - t_from


def fmt_ns(ts):
    return "never" if ts is None else f"{ts * 1e9:.1f} ns"


def main():
    r = Report("ota step settling + slew")

    # small step: bias, static error, gain error, 0.5 % settling
    t, out, isup = buffer(VCM, VCM + SMALL_STEP)
    itail = isup[t < T_STEP].mean()
    r.check("tail current 0.4..1.5x spec", 0.4 * I_TAIL_SPEC < itail < 1.5 * I_TAIL_SPEC,
            f"{itail * 1e6:.2f} uA, spec {I_TAIL_SPEC * 1e6:.0f} uA")
    # The offset cancels in the differential column pair; the gain error (change of
    # the error over the step) is what corrupts charge transfer.
    err0 = out[t < T_STEP][-1] - VCM
    err1 = out[-1] - (VCM + SMALL_STEP)
    gain_err = abs(err1 - err0) / SMALL_STEP
    r.check("static buffer error < 1 mV", abs(err0) < 1e-3, f"{err0 * 1e6:+.0f} uV")
    r.check("closed-loop gain error < 0.5 %", gain_err < 0.005,
            f"{gain_err * 100:.3f} %, loop gain ~{1 / max(gain_err, 1e-9):.0f}")
    ts = settle_time(t, out, out[-1], 0.005 * SMALL_STEP, T_STEP)
    r.check(f"50 mV step settles to 0.5 % < {SETTLE_WINDOW * 1e9:.0f} ns",
            ts is not None and ts < SETTLE_WINDOW, fmt_ns(ts))
    r.check(f"50 mV step settles < cadence/2 = {SETTLE_SQUEEZE * 1e9:.0f} ns",
            ts is not None and ts < SETTLE_SQUEEZE, fmt_ns(ts))

    # large step: slew + settling
    t, out, _ = buffer(V_LO, V_HI)
    win = (t > T_STEP) & (t < T_STEP + 50e-9)
    sr = np.gradient(out, t)[win].max()
    r.check("slew rate > 50 V/us", sr > 50e6, f"{sr / 1e6:.0f} V/us")
    ts = settle_time(t, out, out[-1], 0.005 * (V_HI - V_LO), T_STEP)
    r.check(f"0.5 V step settles to 0.5 % < {SETTLE_WINDOW * 1e9:.0f} ns",
            ts is not None and ts < SETTLE_WINDOW, fmt_ns(ts))
    r.done()


if __name__ == "__main__":
    main()
