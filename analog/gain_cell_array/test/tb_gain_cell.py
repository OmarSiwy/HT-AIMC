"""8x8 gain-cell KV array: write levels, read monotonicity, retention, disturb, energy.

Spec rows (analog/gain_cell_array/docs/architecture.md). One K-array AND one V-array
(same subckt, shared wdata/wsel/rd buses, separate column clamps):
  1. write-then-read across 16 DAC levels [0, V_W]: stored voltage within 1 LSB of the
     driven wdata; read plateau current monotone in stored level; K and V arrays agree
     < 2 % (instance equivalence); full-scale read current <= the column OTA sink (I_SIDE)
  2. retention: < 1 LSB droop over 10x the read interval (320 ns = full INT8 PWM, two
     16-slot nibbles at t_q = 10 ns), wdata bus parked at 0 V; tau extrapolated
  3. non-destructive read: 10 read pulses move storage < 1 LSB
  4. write disturb: writing the neighbouring column (opposite data on the shared wdata
     bus) moves a victim cell < 1 LSB
  5. energy (reported): per cell write and per 8-row read pass (ideal-source V*I)
Columns are clamped at VCM (the tile-integrator virtual ground) by ideal sources.
Adapted from AnalogIOC analog/testbenches/tb_gain_cell.py (ngspice batch -> SpiceRack).
"""
import os
import sys
from pathlib import Path

import numpy as np

A = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(A / "docs"), str(A / "common")]
import specs  # noqa: E402
from bench import Report, dut_kind, testbench  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402

import spicerack as ps  # noqa: E402

BLOCK = "gain_cell_array"
N = 8
VDD = get_pdk().vdd
VCM = specs.VCM_FRAC * VDD     # column rail / virtual ground = write ceiling V_W
LSB = VCM / 15                 # 4b write-DAC LSB (levels k * V_W / 15)
TIGHT = dict(reltol=1e-4, abstol=1e-12, vntol=1e-6, method="gear")   # AnalogIOC TIGHT
READ_INTERVAL = 2 * 16 * specs.TQ_SIM   # full INT8 PWM window (2 nibbles x 16 t_q)
T_WR = 150e-9                  # per-column write phase
T_RD = 150e-9                  # per-row read slot (pulse 100 ns inside)
TR = 0.5e-9


def lvl(k):
    return k * LSB


def pulse(t0, t1, lo, hi):
    return [(0, lo), (t0, lo), (t0 + TR, hi), (t1, hi), (t1 + TR, lo)]


def nets(arr):
    return ([f"wdata{r}" for r in range(N)] + [f"wsel{c}" for c in range(N)]
            + [f"rd{r}" for r in range(N)] + [f"{arr}col{c}" for c in range(N)] + ["vss"])


def store(arr, r, c):
    """Probe name of cell (r, c)'s storage node in array arr ("k" / "v")."""
    inst = "xdut" if arr == "k" else "xv"
    return f"n{inst}_{r}_{c}#s" if dut_kind() == "va" else f"x{inst}.xc{r}_{c}.store"


def va_testbench(corner="", temp=None):
    """DUT=va: ngspice 44 takes at most 18 terminals on an OSDI instance, so the 33-port
    va/gain_cell_array.va cannot be placed; both arrays are built from 64
    va/gain_cell_array_cell.va instances each (same CELL law), otherwise as testbench()."""
    top = ps.Subcircuit(f"tb_{BLOCK}")
    top.veriloga(str(A / BLOCK / "va" / f"{BLOCK}_cell.va"))
    top.raw_spice(f".model {BLOCK}_cell_va {BLOCK}_cell")
    for inst, n in (("xdut", nets("k")), ("xv", nets("v"))):
        for r in range(N):
            for c in range(N):
                top.raw_spice(f"N{inst}_{r}_{c} {n[r]} {n[N + c]} {n[2 * N + r]} "
                              f"{n[3 * N + c]} {n[-1]} {BLOCK}_cell_va")
    tb = ps.Testbench(top)
    tb.use_pdk(get_pdk().model_library(corner or os.environ.get("CORNER", "")))
    tb.temperature = float(temp if temp is not None else os.environ.get("TEMP", 27))
    return tb


def bench(drive, **kw):
    """K array = xdut on kcol<c>, V array = xv on vcol<c>; drive = {net: const | PWL}."""
    if dut_kind() == "va":
        tb = va_testbench(**kw)
    else:
        tb = testbench(BLOCK, nets("k"), **kw)
        tb.extra_line(f"Xxv {' '.join(nets('v'))} {BLOCK}")
    tb.options(**TIGHT)
    tb.V(name="ss", positive="vss", negative="0", value=0.0)
    for c in range(N):
        drive.setdefault(f"kcol{c}", VCM)
        drive.setdefault(f"vcol{c}", VCM)
    for net, val in drive.items():
        if isinstance(val, list):
            tb.PieceWiseLinearVoltageSource(name=net, positive=net, negative="0", values=val)
        else:
            tb.V(name=net, positive=net, negative="0", value=val)
    return tb


def run(tb, step, end, *probes):
    tb.save(*probes)
    d = tb.transient(step_time=step, end_time=end)
    return np.array(d.time), {p: np.array(d[p[2:-1].lower() if p[0] == "V" else p.lower()])
                              for p in probes}


def write_victim(drive):
    """Cell (0,0) <- level 13; wdata0 then parks at 0 V (worst case: opposite data)."""
    drive["wdata0"] = [(0, lvl(13)), (150e-9, lvl(13)), (151e-9, 0)]
    drive["wsel0"] = pulse(10e-9, 140e-9, 0, VDD)
    for r in range(1, N):
        drive.setdefault(f"wdata{r}", 0.0)
    for c in range(1, N):
        drive.setdefault(f"wsel{c}", 0.0)
    for r in range(N):
        drive.setdefault(f"rd{r}", VCM)
    return drive


# -- 1: 16 levels, write-then-read, monotone current -----------------------------
def run_levels(r):
    t_rd0 = 2 * T_WR + 100e-9  # reads start after both write phases
    drive = {}
    for row in range(N):       # cell (row, c) stores level 8*c + row for c in {0, 1}
        drive[f"wdata{row}"] = [(0, lvl(row)), (T_WR - 1e-9, lvl(row)), (T_WR, lvl(8 + row)),
                                (2 * T_WR - 1e-9, lvl(8 + row)), (2 * T_WR, 0)]
        t0 = t_rd0 + row * T_RD
        drive[f"rd{row}"] = pulse(t0, t0 + 100e-9, VCM, 0)
    for c in range(N):
        drive[f"wsel{c}"] = pulse(c * T_WR + 10e-9, c * T_WR + 130e-9, 0, VDD) if c < 2 else 0.0
    t_end = t_rd0 + N * T_RD + 50e-9
    stores = [store("k", row, c) for c in range(2) for row in range(N)]
    icols = ["vkcol0", "vkcol1", "vvcol0", "vvcol1"]
    iwr = [f"vwdata{row}" for row in range(N)] + ["vwsel0", "vwsel1"]
    t, d = run(bench(drive), 0.5e-9, t_end, *[f"V({s})" for s in stores],
               *[f"I({s})" for s in icols + iwr])

    i_smp = np.argmin(np.abs(t - (t_rd0 - 20e-9)))      # just before the read phase
    vst = np.array([d[f"V({s})"][i_smp] for s in stores])   # index k = level k
    err = vst - np.array([lvl(k) for k in range(16)])
    r.check("all 16 stores within 1 LSB", np.all(np.abs(err) < LSB),
            f"error {err.min() * 1e3:+.1f} .. {err.max() * 1e3:+.1f} mV, "
            f"LSB {LSB * 1e3:.0f} mV")

    ik, iv = np.zeros(16), np.zeros(16)       # plateau average per read slot
    for row in range(N):
        w = (t > t_rd0 + row * T_RD + 40e-9) & (t < t_rd0 + row * T_RD + 90e-9)
        for c in range(2):
            ik[8 * c + row] = -d[f"I(vkcol{c})"][w].mean()
            iv[8 * c + row] = -d[f"I(vvcol{c})"][w].mean()
    print("  read current per level (K array): " +
          " ".join(f"{i * 1e9:.4g}" for i in ik) + " nA")
    mono = all(ik[k + 1] > ik[k] if ik[k + 1] > 1e-9 else ik[k + 1] >= ik[k] - 5e-12
               for k in range(15))
    r.check("K read current monotone in stored level", mono)
    big = ik > 1e-9
    dkv = np.max(np.abs(ik[big] - iv[big]) / ik[big])
    r.check("K/V arrays agree < 2 %", dkv < 0.02, f"{dkv * 100:.3f} %")
    r.check("full-scale read current <= column sink I_SIDE", ik.max() <= specs.I_SIDE,
            f"{ik.max() * 1e6:.2f} uA vs {specs.I_SIDE * 1e6:.1f} uA")

    e_wr = 0.0                 # V*I per ideal source; wdata voltage = level map
    for row in range(N):
        for c, (t0, t1) in enumerate([(0, T_WR), (T_WR, 2 * T_WR)]):
            w = (t >= t0) & (t < t1)
            e_wr += np.trapezoid(-d[f"I(vwdata{row})"][w], t[w]) * lvl(8 * c + row)
    for s in ("vwsel0", "vwsel1"):
        w = t < 2 * T_WR
        e_wr += np.trapezoid(-d[f"I({s})"][w], t[w]) * VDD
    rdw = t > t_rd0
    e_rd = sum(np.trapezoid(-d[f"I({s})"][rdw], t[rdw]) * VCM for s in icols)
    print(f"  E_write (16 cells x 2 arrays): {e_wr * 1e12:.3f} pJ ({e_wr / 32 * 1e15:.1f} fJ/cell)")
    print(f"  E_read (8-row pass, 2 cols x 2 arrays): {e_rd * 1e12:.3f} pJ")
    return ik


# -- 2: retention ----------------------------------------------------------------
def run_retention(r):
    t_hold0 = 200e-9
    t_end = t_hold0 + 10 * READ_INTERVAL + 100e-9
    s = store("k", 0, 0)
    t, d = run(bench(write_victim({})), 1e-9, t_end, f"V({s})")
    v = d[f"V({s})"]
    i0 = np.argmin(np.abs(t - t_hold0))
    v0, v1 = v[i0], v[-1]
    droop, dt = v0 - v1, t[-1] - t[i0]
    tau = dt * v0 / droop if droop > 1e-9 else float("inf")
    print(f"  store {v0 * 1e3:.2f} -> {v1 * 1e3:.2f} mV over {dt * 1e6:.2f} us; tau "
          + ("> 1 s (leakage below solver floor)" if tau > 1 else f"{tau * 1e3:.2f} ms"))
    r.check("droop < 1 LSB over 10x read interval", abs(droop) < LSB,
            f"{droop * 1e6:+.1f} uV")


# -- 3+4: non-destructive read + write disturb --------------------------------------
def run_disturb(r):
    t_rd0, n_rd = 250e-9, 10
    t_wr2 = t_rd0 + n_rd * 150e-9 + 100e-9    # neighbour-column write phase
    t_end = t_wr2 + 200e-9
    pts = [(0, VCM)]                          # 10 read pulses on row 0
    for k in range(n_rd):
        t0 = t_rd0 + k * 150e-9
        pts += [(t0, VCM), (t0 + TR, 0), (t0 + 100e-9, 0), (t0 + 100e-9 + TR, VCM)]
    drive = write_victim({"rd0": pts, "wsel1": pulse(t_wr2, t_wr2 + 130e-9, 0, VDD)})
    s = store("k", 0, 0)
    t, d = run(bench(drive), 0.5e-9, t_end, f"V({s})", "I(vkcol0)")
    v = d[f"V({s})"]
    v_pre = v[np.argmin(np.abs(t - (t_rd0 - 20e-9)))]
    v_post = v[np.argmin(np.abs(t - (t_wr2 - 20e-9)))]
    r.check("10 reads move storage < 1 LSB", abs(v_post - v_pre) < LSB,
            f"{v_pre * 1e3:.2f} -> {v_post * 1e3:.2f} mV ({(v_post - v_pre) * 1e6:+.1f} uV)")
    t9 = t_rd0 + 9 * 150e-9
    i10 = -d["I(vkcol0)"][(t > t9 + 40e-9) & (t < t9 + 90e-9)].mean()
    print(f"  10th read current: {i10 * 1e6:.3f} uA")
    r.check("write disturb < 1 LSB", abs(v[-1] - v_post) < LSB,
            f"victim {v[-1] * 1e3:.2f} mV ({(v[-1] - v_post) * 1e6:+.1f} uV)")


def main():
    r = Report("gain_cell_array")
    run_levels(r)
    run_retention(r)
    run_disturb(r)
    r.done()


if __name__ == "__main__":
    main()
