"""weight_tile write port: cell write margin, leakage, row write time, row-line edge,
write energy (INTERFACE §7.2/§7.3, Q13, §7.5 t_q_floor).

Spec rows (analog/weight_tile/docs/architecture.md), at $CORNER/$SIM_TEMP:
  1. cell write margin (BL level that flips a stored 1, WL = BLB = VDD) >= wt.wm_min()
  2. storage leakage of all 8*N_ROWS*N_COLS bits < 1 % of the converters' OTA static power
  3. row write at VDD*(1 - VDD_TOL): a full row (1 x N_COLS tile, wire + 15 rows of BL
     drains lumped on) takes the complement of its word: every bit stores, and the worst
     wwl 50 % -> Q 50 % delay is inside T_WRITE_CELL (the cell budget of T_WR)
  4. row-line 10-90 % edge with every bit on (the full programmed row, specs.c_row()):
     < TQ_SIM/3 (pwm_driver's gate); reported against t_q_floor/3
  5. (info) write energy per row: every bit toggling / none toggling; per pass (16 rows,
     random data = half toggling) — Q13
Transistor-level only: DUT=va has no cell (its write is checked through MAC by
tb_weight_readback) and skips with PASS.
"""
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tile import PDK, T_EDGE, VDD, WR_ROW, WR_SETUP, _write, write_port  # noqa: E402
from bench import Report, dut_kind, dut_path  # noqa: E402
import specs  # noqa: E402
import weight_tile as wt  # noqa: E402

import spicerack as ps  # noqa: E402

VDD_TOL = 0.1            # supply tolerance the write timing must hold at (INTERFACE §7.3)
SEED = 7                 # the row word under test
SLOTS = (0.5e-9, 4e-9, 8e-9, 12e-9)    # word, complement, complement again, all ones
T_EDGE_ROW = 16e-9       # xin_p_r0 rises here (phi1e parked high: rowa follows)
T_END = 22e-9
N_BITS_TILE = wt.CELL_BITS * specs.N_ROWS * specs.N_COLS


def _bench(top, vdd, corner, temp, seed=None):
    tb = ps.Testbench(top)
    tb.use_pdk(PDK.model_library(corner or os.environ.get("CORNER", "")))
    tb.temperature = float(temp if temp is not None else os.environ.get("SIM_TEMP", 27))
    if seed is not None:
        tb.options(seed=seed)
    tb.V(name="sup", positive="vdd", negative="0", value=vdd)
    tb.V(name="ss", positive="vss", negative="0", value=0.0)
    return tb


def _cell_top():
    top = ps.Subcircuit("tb_cell")
    top.include(str(dut_path("weight_tile")))
    top.X("xc", "weight_tile_cell", "q", "qb", "wl", "bl", "blb", "vdd", "vss")
    return top


def write_margin(corner="", temp=None, seed=None):
    """BL level [V] at which a stored 1 flips (WL = BLB = VDD, BL ramped down over
    wt.WM_RAMP); -VDD if it never flips. The 1 is written first (BL = VDD, BLB = 0)."""
    t0, tr = wt.WM_RAMP
    t0 += 2e-9
    tb = _bench(_cell_top(), VDD, corner, temp, seed)
    tb.V(name="wl", positive="wl", negative="0", value=VDD)
    tb.PieceWiseLinearVoltageSource(name="blb", positive="blb", negative="0",
                                    values=[(0, 0.0), (1e-9, 0.0), (1.1e-9, VDD)])
    tb.PieceWiseLinearVoltageSource(name="bl", positive="bl", negative="0",
                                    values=[(0, VDD), (t0, VDD), (t0 + tr, 0.0)])
    tb.save("V(q)")
    d = tb.transient(step_time=tr / 2e4, end_time=t0 + tr)
    t, q = np.array(d.time), np.array(d["q"])
    k = np.where((t > t0) & (q < VDD / 2))[0]
    return VDD * (1 - (t[k[0]] - t0) / tr) if len(k) else -VDD


def leakage(corner="", temp=None):
    """Static current [A] of one holding cell, WL = 0, BL = BLB = VDD (one access
    device leaks into the 0 node), all sources summed."""
    tb = _bench(_cell_top(), VDD, corner, temp)
    for n in ("bl", "blb"):
        tb.V(name=n, positive=n, negative="0", value=VDD)
    tb.V(name="wl", positive="wl", negative="0", value=0.0)
    tb.node_set(q=VDD, qb=0.0)
    op = tb.operating_point()
    return -sum(op[f"i(v{n})"] for n in ("sup", "bl", "blb"))


def wire_loads(text, n_rows, n_cols):
    """Deck text with the full tile's wire (XP_PITCH per crosspoint, specs.C_WIRE) on
    every row/WL/BL line, plus the BL drains of the rows this tile leaves out — the
    pre-layout line loads of a 16 x 17 tile on a smaller one (testbench-side estimate)."""
    xp = specs.XP_PITCH * PDK.wire_pitch * specs.C_WIRE
    c_bl = specs.N_ROWS * xp + (specs.N_ROWS - n_rows) * PDK.cd_n_ff_um * \
        wt.sizes()["cell"]["ax"][0] * 1e-15
    caps = [f"Cw{n}{k} {n}{k} vss {c_bl:.4g}" for n in ("bl", "blb")
            for k in range(wt.CELL_BITS * n_cols)]
    caps += [f"Cw{n}{i} {n}{i} vss {specs.N_COLS * xp:.4g}" for n in ("wl", "rowa", "rowb")
             for i in range(n_rows)]
    end = text.rindex(".ends weight_tile")
    return text[:end] + "\n".join(caps) + "\n" + text[end:]


def q_node(j, k):
    """Storage node of row 0, column j, wd bit k (0..3 Cp, 4..7 Cn)."""
    pol, b = ("p", k) if k < wt.N_BITS else ("n", k - wt.N_BITS)
    return f"xxdut.xbit{pol}0_{j}_{b}.q"     # Xxdut.Xbit..: q is the bit's net on the cell port


def row_run(vdd, corner="", temp=None):
    """One transient of a 1 x N_COLS row tile (parked clocks): write the word, its
    complement, the complement again, then all ones, then step xin_p_r0. Returns
    (word bits, time, {signal: array})."""
    n_cols = specs.N_COLS
    rng = np.random.default_rng(SEED)
    cp, cn = rng.integers(0, 16, n_cols), rng.integers(0, 16, n_cols)
    word = wt.row_word(cp, cn)
    comp = [1 - b for b in word]
    top = ps.Subcircuit("tb_row")
    top.include(str(_write(wire_loads(wt.text(1, n_cols), 1, n_cols), "row")))
    top.X("xdut", "weight_tile", *wt.ports(1, n_cols))
    tb = _bench(top, vdd, corner, temp)
    for n, v in (("phi1", vdd), ("phi1e", vdd), ("phi2", 0.0), ("xin_n_r0", 0.0)):
        tb.V(name=n, positive=n, negative="0", value=v)
    tb.V(name="cm", positive="vcm", negative="0", value=specs.VCM_FRAC * vdd)
    for j in range(n_cols):
        tb.V(name=f"col{j}", positive=f"col{j}", negative="0", value=specs.VCM_FRAC * vdd)
    tb.PieceWiseLinearVoltageSource(name="xp", positive="xin_p_r0", negative="0", values=[
        (0, 0.0), (T_EDGE_ROW, 0.0), (T_EDGE_ROW + T_EDGE, vdd)])
    write_port(tb, 1, wt.CELL_BITS * n_cols,
               [(t, 0, w) for t, w in zip(SLOTS, (word, comp, comp, [1] * len(word)))], vdd)
    sigs = ["wwl0", "xxdut.rowa0"] + [q_node(j, k) for j in range(n_cols) for k in range(wt.CELL_BITS)]
    tb.save(*(f"V({s})" for s in sigs), "I(Vsup)")
    d = tb.transient(step_time=20e-12, end_time=T_END)
    return word, np.array(d.time), {s: np.array(d[s]) for s in sigs + ["i(vsup)"]}


def cross(t, v, level, t0, rising):
    """First crossing of `level` after t0, linearly interpolated."""
    k = np.where((t >= t0) & ((v >= level) if rising else (v <= level)))[0]
    if not len(k):
        return np.inf
    k = k[0]
    if k == 0 or t[k - 1] < t0 or v[k] == v[k - 1]:
        return t[k]
    return t[k - 1] + (level - v[k - 1]) * (t[k] - t[k - 1]) / (v[k] - v[k - 1])


def main():
    r = Report("weight_tile write")
    if dut_kind() == "va":
        print("  skip  transistor-level cell/row checks (DUT=va: tb_weight_readback)")
        r.done()
    corner, temp = os.environ.get("CORNER", ""), os.environ.get("SIM_TEMP")
    cs = wt.sizes()["cell"]
    with ThreadPoolExecutor(4) as ex:
        f_wm = ex.submit(write_margin, corner, temp)
        f_lk = ex.submit(leakage, corner, temp)
        f_lo = ex.submit(row_run, VDD * (1 - VDD_TOL), corner, temp)
        f_no = ex.submit(row_run, VDD, corner, temp)
    wm = f_wm.result()
    r.check("cell write margin >= wm_min", wm >= cs["wm_min"],
            f"{wm * 1e3:.0f} mV vs {cs['wm_min'] * 1e3:.0f} mV (pull-up {cs['pu'][0]}/"
            f"{cs['pu'][1]} um, access/pull-down {cs['ax'][0]}/{cs['ax'][1]} um)")
    i_lk = f_lk.result()
    p_lk, p_ota = N_BITS_TILE * i_lk * VDD, specs.ota_static_w()
    r.check("storage leakage < 1 % of OTA static", p_lk < 0.01 * p_ota,
            f"{i_lk * 1e12:.2f} pA/bit, {N_BITS_TILE} bits {p_lk * 1e6:.3f} uW vs OTA "
            f"{p_ota * 1e6:.0f} uW")

    for vdd, (word, t, s) in ((VDD * (1 - VDD_TOL), f_lo.result()), (VDD, f_no.result())):
        t_wl = cross(t, s["wwl0"], vdd / 2, SLOTS[1], True)
        t_end = SLOTS[2]
        qs = [q_node(j, k) for j in range(specs.N_COLS) for k in range(wt.CELL_BITS)]
        delays, stored = [], True
        for q, b in zip(qs, word):        # complement written: every Q leaves level b
            v = s[q]
            delays.append(cross(t, v, vdd / 2, SLOTS[1], rising=not b) - t_wl)
            stored &= (v[np.searchsorted(t, t_end)] > vdd / 2) == (not b)
        worst = max(delays)
        if vdd != VDD:
            r.check(f"row write at {vdd:.2f} V: all {len(qs)} bits store the complement",
                    stored)
            r.check("row write: worst wwl -> Q inside T_WRITE_CELL",
                    worst < wt.T_WRITE_CELL,
                    f"{worst * 1e12:.0f} ps vs {wt.T_WRITE_CELL * 1e9:.1f} ns")
            continue
        r.check(f"row write at {vdd:.2f} V: all {len(qs)} bits store the complement", stored,
                f"worst wwl -> Q {worst * 1e12:.0f} ps")
        # row edge, every bit on (slot 3 wrote all ones)
        v = s["xxdut.rowa0"]
        t10, t90 = (cross(t, v, f * vdd, T_EDGE_ROW, True) for f in (0.1, 0.9))
        edge = t90 - t10
        r.check("row edge (full programmed row) < TQ_SIM/3", edge < specs.TQ_SIM / 3,
                f"{edge * 1e12:.0f} ps; t_q_floor/3 = {specs.t_q_floor() / 3 * 1e12:.0f} ps; "
                f"specs.c_row() {specs.c_row() * 1e15:.0f} fF")
        # energy per row write: supply charge over the slot minus the quiet current
        i = -s["i(vsup)"]

        def energy(t0):
            q = (t >= t0 - 0.5e-9) & (t < t0)
            i0 = np.trapezoid(i[q], t[q]) / (t[q][-1] - t[q][0])
            w = (t >= t0) & (t <= t0 + WR_ROW + 0.5e-9)
            return vdd * (np.trapezoid(i[w], t[w]) - i0 * (t[w][-1] - t[w][0]))
        e_all, e_none = energy(SLOTS[1]), energy(SLOTS[2])
        e_pass = specs.N_ROWS * (e_all + e_none) / 2
        print(f"  info  write energy per row: {e_all * 1e12:.2f} pJ all bits toggling, "
              f"{e_none * 1e12:.2f} pJ none; per pass (16 rows, random data) "
              f"{e_pass * 1e12:.1f} pJ = {e_pass * 1e12 / specs.pass_energy_pj() * 100:.1f} % "
              f"of pass_energy_pj ({specs.pass_energy_pj():.0f} pJ); worst "
              f"{specs.N_ROWS * e_all * 1e12:.1f} pJ")
    r.done()


if __name__ == "__main__":
    main()
