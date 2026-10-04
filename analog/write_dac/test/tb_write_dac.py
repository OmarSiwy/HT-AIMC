"""write_dac: 16 levels, settling and energy into the real write path.

Spec rows (analog/write_dac/docs/architecture.md):
  16 settled store levels strictly monotone
  level error |v_k - k*vref/15| < 5 mV
  settling < 100 ns for every code step incl. 15 -> 0 -> 15 (band +-LSB/2)
  energy per 200 ns code slot (ladder from vref + logic from vdd) <= 1.2 pJ

Load = the gain-cell write path: an ON cell write switch (gate at VDD) into c_store.
Adapted from AnalogIOC analog/testbenches/tb_write_dac.py (ngspice batch -> SpiceRack).
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

A = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(A / "docs"), str(A / "common")]
import specs  # noqa: E402
from bench import Report, testbench  # noqa: E402
from devices import fet  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402

PORTS = ["b0", "b1", "b2", "b3", "dacout", "vref", "vdd", "vss"]
PDK = get_pdk()
VDD = PDK.vdd
VREF = specs.VCM_FRAC * VDD    # write-level ceiling (AnalogIOC 0.9 V)
LSB = VREF / 15
C_STORE = specs.design()["c_store"]
# Gain-cell write switch: AnalogIOC gc_write_n 0.42/0.5 um (long L for retention).
# ponytail: stand-in until gain_cell_array is migrated; take its sizes() then.
GC_WRITE = (PDK.min_w, 0.5)
T_SLOT = 200e-9
T_EDGE = 0.5e-9
SETTLE_SPEC = 100e-9
LEVEL_ERR = 5e-3
E_SLOT_MAX = 1.2e-12           # AnalogIOC measured 1.208 pJ/slot (METRICS.md, A3)
CODES = list(range(16)) + [0, 15]   # monotone sweep + full-scale jumps


def code_pwl(bit, codes):
    pts = []
    for k, code in enumerate(codes):
        v = VDD if (code >> bit) & 1 else 0.0
        if not pts:
            pts.append((0.0, v))
        elif pts[-1][1] != v:
            pts += [(k * T_SLOT, pts[-1][1]), (k * T_SLOT + T_EDGE, v)]
    return pts


def run(codes=CODES, seed=None, **kw):
    """Transient over `codes`, one T_SLOT each. -> (t, store, i_vref, i_vdd) arrays."""
    tb = testbench("write_dac", PORTS, **kw)
    if seed is not None:
        tb.options(seed=seed)
    tb.options(reltol=1e-4, abstol=1e-12, vntol=1e-6, method="gear")   # AnalogIOC TIGHT
    tb.V(name="sup", positive="vdd", negative="0", value=VDD)
    tb.V(name="ss", positive="vss", negative="0", value=0.0)
    tb.V(name="ref", positive="vref", negative="0", value=VREF)
    tb.V(name="sel", positive="wsel", negative="0", value=VDD)
    fet(SimpleNamespace(raw_spice=tb.extra_line), "wsw", "dacout", "wsel", "store", "0",
        "nfet", *GC_WRITE)
    tb.C(name="s", positive="store", negative="0", value=C_STORE)
    for b in range(4):
        pts = code_pwl(b, codes)
        pts.append((len(codes) * T_SLOT, pts[-1][1]))
        tb.PieceWiseLinearVoltageSource(name=f"b{b}", positive=f"b{b}", negative="0",
                                        values=pts)
    tb.save("V(store)", "I(Vref)", "I(Vsup)")
    d = tb.transient(step_time=0.2e-9, end_time=len(codes) * T_SLOT)
    return (np.array(d.time), np.array(d["store"]), np.array(d["i(vref)"]),
            np.array(d["i(vsup)"]))


def finals(t, v, n):
    """Settled value per slot: 5 ns before its end."""
    return np.array([v[np.argmin(np.abs(t - ((k + 1) * T_SLOT - 5e-9)))] for k in range(n)])


def main():
    r = Report("write_dac")
    t, v, i_ref, i_vdd = run()
    fin = finals(t, v, len(CODES))
    lv = fin[:16]
    err = lv - np.arange(16) * LSB
    for k in range(16):
        print(f"    {k:2d}: {lv[k] * 1e3:7.2f} mV (err {err[k] * 1e3:+.2f} mV)")
    r.check("16 levels strictly monotone", np.all(np.diff(lv) > 0))
    r.check(f"level error < {LEVEL_ERR * 1e3:.0f} mV", np.max(np.abs(err)) < LEVEL_ERR,
            f"worst {np.max(np.abs(err)) * 1e3:.2f} mV")

    worst = 0.0
    for k in range(1, len(CODES)):
        t0 = k * T_SLOT
        w = (t >= t0) & (t < t0 + T_SLOT)
        out = np.where(np.abs(v[w] - fin[k]) > LSB / 2)[0]
        worst = max(worst, 0.0 if not len(out) else t[w][out[-1]] - t0)
    r.check(f"settle < {SETTLE_SPEC * 1e9:.0f} ns (incl. 15->0->15)", worst < SETTLE_SPEC,
            f"worst {worst * 1e9:.1f} ns")

    n = len(CODES)
    e_ref = np.trapezoid(-i_ref, t) * VREF / n
    e_vdd = np.trapezoid(-i_vdd, t) * VDD / n
    r.check(f"energy per slot <= {E_SLOT_MAX * 1e12:.1f} pJ", e_ref + e_vdd <= E_SLOT_MAX,
            f"ladder {e_ref * 1e12:.3f} + logic {e_vdd * 1e12:.3f} pJ")
    r.done()


if __name__ == "__main__":
    main()
