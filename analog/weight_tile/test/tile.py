"""weight_tile testbench fixture: a programmed tile DUT on every $DUT source, the real
column integrator as the measuring instrument, the write port and the chop-grid stimulus.

A tile is R rows x C columns, codes Cp[j][i] / Cn[j][i] (a plain list per row = one
column). The DUT is the same programmable netlist for every code; the codes go in
through the write port (wwl<i>, wd<k>, INTERFACE §7) before the window, one row per
WR_ROW slot:
  DUT=sch  netlist/weight_tile.py build(R, C)
  DUT=va   R x C instances of va/weight_tile.va (one crosspoint each: own wwl<i>, the
           column's wd<8j>..wd<8j+7>), crail on row 0 of each column
  DUT=pex  R x C copies of the post-layout canonical crosspoint, Xrail0 kept on row 0
Crosspoint (i, j) sees xin_p_r<i> xin_n_r<i> col<j> wwl<i> wd<8j..8j+7> phi1 phi1e phi2
vcm vdd vss.

Timeline: [0, T_W) the write phase — tile parked (phi1 = phi1e = 1, phi2 = 0, the
analogioc rest state, INTERFACE §6.2), integrators in reset; the chop grid of
tb_pwm_driver then runs from T_START = T_W + its T_START, reset released 1 ns before.

Instrument per column (AnalogIOC _conv_common.integrator_fixture): the migrated ota block
with its replica bias (ota/test/ota_bench.bias_network), C_int = specs.c_int() from
vout(j) to col<j>, a reset TG across C_int. Chop grid, envelopes: pwm_driver's tb.
"""
import hashlib
import math
import os
import sys
from pathlib import Path

A = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(A / "docs"), str(A / "common"), str(A / "weight_tile" / "netlist"),
                str(A / "ota" / "netlist"), str(A / "ota" / "test"),
                str(A / "cmos_switch" / "netlist"), str(A / "pwm_driver" / "test")]
import cmos_switch  # noqa: E402
import ota  # noqa: E402
import specs  # noqa: E402
import weight_tile as wt  # noqa: E402
from bench import dut_kind, dut_path  # noqa: E402
from devices import deck  # noqa: E402
from ota_bench import bias_network  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402
import tb_pwm_driver as pwm  # noqa: E402
from tb_pwm_driver import PHI1_D, PHI1_W, PHI2_D, T_CLK, T_EDGE, pulse_train  # noqa: E402

import spicerack as ps  # noqa: E402

PDK = get_pdk()
VDD = PDK.vdd
VCM = specs.VCM_FRAC * VDD
TQ = specs.TQ_SIM
C_INT = specs.c_int()
U1 = specs.u1()                  # ideal volts per MAC code unit
T_RST = 4e-9                     # reset TG sizing window (AnalogIOC)
# write slot per row: wd changes at the slot start, wwl high WR_SETUP later for
# T_WRITE_CELL (the cell's own budget, INTERFACE §7.3), data held WR_HOLD after it falls
WR_SETUP, WR_HOLD = 0.2e-9, 0.3e-9
WR_ROW = WR_SETUP + wt.T_WRITE_CELL + 2 * T_EDGE + WR_HOLD
WR_T0 = 0.5e-9
T_W = WR_T0 + specs.N_ROWS * WR_ROW          # room to write a full tile
T_START = T_W + pwm.T_START
BUILD = A / "weight_tile" / "output" / "tb"
# reset TG: C_int to B_Y bits inside the T_RST window (AnalogIOC sh_sw 0.84/1.68 um)
R_RST = T_RST / ((specs.B_Y + 1) * math.log(2) * C_INT)


def xp_ports(i, j):
    """Port nets of crosspoint (i, j) in the canonical (1 x 1) port order."""
    return ([f"xin_p_r{i}", f"xin_n_r{i}", f"col{j}", f"wwl{i}"]
            + [f"wd{wt.CELL_BITS * j + k}" for k in range(wt.CELL_BITS)]
            + ["phi1", "phi1e", "phi2", "vcm", "vdd", "vss"])


def vout(j):
    """Integrator output net of column j (column 0 keeps the plain `vout`)."""
    return "vout" if j == 0 else f"vout{j}"


def _cols(c):
    """Codes as [col][row]: a flat per-row list is one column."""
    return [list(x) for x in c] if hasattr(c[0], "__len__") else [list(c)]


def _write(text, tag):
    BUILD.mkdir(parents=True, exist_ok=True)
    p = BUILD / f"{tag}_{hashlib.sha1(text.encode()).hexdigest()[:10]}.spice"
    if not p.exists():
        p.write_text(text)
    return p


def _instrument():
    rst = cmos_switch.build("int_rst_sw", **cmos_switch.sizes(r_on=R_RST))
    return _write(deck(ota.build(), rst), "instrument")


def _drop(text, names):
    """Deck text without the device lines named in `names` (lowercase)."""
    return "\n".join(ln for ln in text.splitlines()
                     if not ln.split() or ln.split()[0].lower() not in names)


def _pex_rows(n_rows, rail=True):
    """The canonical post-layout crosspoint, one copy per row (rail on row 0 only)."""
    src = dut_path("weight_tile", "pex").read_text()
    body = src[src.index(".subckt weight_tile "): src.index(".ends weight_tile")]
    out = []
    for i in range(n_rows):
        lines = _drop(body, set() if i == 0 and rail else {"xrail0"}).splitlines()
        lines[0] = lines[0].replace(".subckt weight_tile ", f".subckt weight_tile_r{i} ", 1)
        out += lines + [f".ends weight_tile_r{i}", ""]
    return "\n".join(out)


def column(n_rows, kind="", rail=True, ideal_ota=False, n_cols=1):
    """Wrapper Subcircuit: an n_rows x n_cols programmable tile + one instrument per
    column (vout(j)) + OTA bias. Nets: xin_p_r<i>, xin_n_r<i>, col<j>, wwl<i>, wd<k>,
    phi1/phi1e/phi2, vcm, vdd, vss, rst/rst_b, vout(j). rail=False drops C_RAIL;
    ideal_ota swaps the OTA for an A=1e6 VCVS with a 1 ps pole (tb_csnr isolate)."""
    kind = kind or dut_kind()
    path = dut_path("weight_tile", kind)
    if not path.exists():
        raise FileNotFoundError(f"DUT={kind}: {path} missing")
    top = ps.Subcircuit("tb_weight_tile")
    xps = [(i, j) for j in range(n_cols) for i in range(n_rows)]
    if kind == "sch":
        text = wt.text(n_rows, n_cols)
        rails = {f"xrail{j}" for j in range(n_cols)}
        top.include(str(_write(text if rail else _drop(text, rails), "sch")))
        top.X("xdut", "weight_tile", *wt.ports(n_rows, n_cols))
    elif kind == "va":
        sz = wt.sizes()
        top.veriloga(str(path))
        for i in range(n_rows):
            top.raw_spice(f".model wt_r{i} weight_tile cu={sz['c_u']:.6g} cb={sz['c_ball']:.6g} "
                          f"crail={sz['c_rail'] if i == 0 and rail else 0:.6g}")
        for i, j in xps:
            top.raw_spice(f"Nxdut{i}_{j} {' '.join(xp_ports(i, j))} wt_r{i}")
    else:
        top.include(str(_write(_pex_rows(n_rows, rail), "pex")))
        for i, j in xps:
            top.X(f"xdut{i}_{j}", f"weight_tile_r{i}", *xp_ports(i, j))
    top.include(str(_instrument()))
    for j in range(n_cols):
        col, out = f"col{j}", vout(j)
        if ideal_ota:
            top.E(name=f"ota{j}", positive=f"oi{j}", negative="0", control_positive="vcm",
                  control_negative=col, voltage_gain=1e6)
            top.R(name=f"ota{j}", positive=f"oi{j}", negative=out, value=1e3)
            top.C(name=f"ota{j}", positive=out, negative="0", value=1e-15)
        else:
            top.X(f"xota{j}", "ota", "vcm", col, out, "vb_nc", "vb_pc", "vb_tail", "vdd", "vss")
        top.X(f"xrst{j}", "int_rst_sw", out, col, "rst", "rst_b", "vdd", "vss")
    bias_network(top)
    return top


def writes(cp, cn, t0=WR_T0, rows=None):
    """Write schedule [(t, row, wd bits)]: rows (default all) of the tile, in order, one
    WR_ROW slot each from t0. cp/cn as in testbench()."""
    cp, cn = _cols(cp), _cols(cn)
    rows = range(len(cp[0])) if rows is None else rows
    return [(t0 + n * WR_ROW, i, wt.row_word([c[i] for c in cp], [c[i] for c in cn]))
            for n, i in enumerate(rows)]


def write_port(tb, n_rows, n_bits, schedule, vdd=VDD):
    """PWL sources on wwl0..wwl<n_rows-1> and wd0..wd<n_bits-1> playing `schedule`
    (writes(): wd lines change at t, wwl<row> pulses WR_SETUP later for T_WRITE_CELL),
    swinging 0..vdd (the macro's own rail, INTERFACE §2)."""
    wd = [[(0, 0.0)] for _ in range(n_bits)]
    wl = [[(0, 0.0)] for _ in range(n_rows)]
    for t, i, bits in sorted(schedule):
        for line, b in zip(wd, bits):
            if line[-1][1] != vdd * b:
                line += [(t, line[-1][1]), (t + T_EDGE, vdd * b)]
        a = t + WR_SETUP
        wl[i] += [(a, 0.0), (a + T_EDGE, vdd), (a + T_EDGE + wt.T_WRITE_CELL, vdd),
                  (a + 2 * T_EDGE + wt.T_WRITE_CELL, 0.0)]
    for name, lines in (("wd", wd), ("wwl", wl)):
        for k, pts in enumerate(lines):
            tb.PieceWiseLinearVoltageSource(name=f"{name}{k}", positive=f"{name}{k}",
                                            negative="0", values=pts)


def testbench(cp, cn, kind="", corner="", temp=None, schedule=None, **col):
    """Tile programmed to (cp, cn) through the write port + instruments + supplies/vcm/
    reset; $CORNER/$SIM_TEMP as bench.testbench. cp/cn: per-row codes of one column, or
    [col][row]. schedule: extra writes(...) appended (a rewrite during the hold)."""
    n_cols, n_rows = len(_cols(cp)), len(_cols(cp)[0])
    tb = ps.Testbench(column(n_rows, kind, n_cols=n_cols, **col))
    tb.use_pdk(PDK.model_library(corner or os.environ.get("CORNER", "")))
    tb.temperature = float(temp if temp is not None else os.environ.get("SIM_TEMP", 27))
    tb.options(reltol=1e-4, abstol=1e-12, vntol=1e-6, method="gear")   # AnalogIOC TIGHT
    for j in range(n_cols):
        tb.C(name=f"int{j}", positive=vout(j), negative=f"col{j}", value=C_INT)
    tb.V(name="sup", positive="vdd", negative="0", value=VDD)
    tb.V(name="ss", positive="vss", negative="0", value=0.0)
    tb.V(name="cm", positive="vcm", negative="0", value=VCM)
    t_rel = T_START - 1e-9
    tb.PieceWiseLinearVoltageSource(name="rst", positive="rst", negative="0",
                                    values=[(0, VDD), (t_rel, VDD), (t_rel + 0.2e-9, 0.0)])
    tb.PieceWiseLinearVoltageSource(name="rstb", positive="rst_b", negative="0",
                                    values=[(0, 0.0), (t_rel, 0.0), (t_rel + 0.2e-9, VDD)])
    write_port(tb, n_rows, wt.CELL_BITS * n_cols, writes(cp, cn) + list(schedule or []))
    return tb


def clocks(tb, t_chop, end, t_park=None):
    """phi1/phi1e/phi2 on the chop grid from T_START (AnalogIOC _conv_common.phi_sources),
    parked before it — phi1 = phi1e = VDD (tops clamped to vcm), phi2 = 0 — and again
    from t_park on (a chop-cycle boundary: the tile clock gate, INTERFACE §6.1)."""
    p2w = t_chop - PHI2_D - 0.5e-9 - T_CLK
    for name, d, w in (("phi1", PHI1_D, PHI1_W), ("phi1e", PHI1_D, PHI1_W + 0.2e-9),
                       ("phi2", PHI2_D, p2w)):
        pts = pulse_train(d + T_W, w, t_chop, end if t_park is None else t_park)
        if name != "phi2":
            pts = [(0, VDD)] + pts[3:]       # high until the first pulse's fall
            if t_park is not None:
                pts += [(t_park, 0.0), (t_park + T_CLK, VDD)]
        tb.PieceWiseLinearVoltageSource(name=name, positive=name, negative="0", values=pts)


def envelope_windows(codes, t_chop=TQ, period=None):
    """PWL points of consecutive A5 nibble windows on one line: window k's pulse starts
    at T_START + k*period (default 16*t_chop, AnalogIOC tb_cascade), width code*t_chop."""
    pts, period = [(0, 0.0)], period or 16 * t_chop
    for k, c in enumerate(codes):
        if c:
            t0 = T_START + k * period
            pts += [(t0, 0.0), (t0 + T_EDGE, VDD), (t0 + c * t_chop, VDD),
                    (t0 + c * t_chop + T_EDGE, 0.0)]
    return pts


def drive(tb, xs, period=None):
    """Row i driven by signed nibble(s) xs[i] (int, or a list = consecutive windows)."""
    for i, x in enumerate(xs):
        x = [x] if isinstance(x, int) else list(x)
        for sfx, sgn in (("p", 1), ("n", -1)):
            tb.PieceWiseLinearVoltageSource(
                name=f"x{sfx}{i}", positive=f"xin_{sfx}_r{i}", negative="0",
                values=envelope_windows([max(sgn * c, 0) for c in x], period=period))


def at(d, node, t):
    """Value of node at the sample nearest t."""
    ts = d.time
    k = min(range(len(ts)), key=lambda j: abs(ts[j] - t))
    return d[node][k]


def excursion(cp, cn, xs, kind="", **col):
    """(integrator excursion [V] over one window, col0 at the end) for one column."""
    t_end = T_START + 16 * TQ + 60e-9
    tb = testbench(cp, cn, kind, **col)
    clocks(tb, TQ, t_end)
    drive(tb, xs)
    tb.save("V(vout)", "V(col0)")
    d = tb.transient(step_time=0.1e-9, end_time=t_end)
    return at(d, "vout", t_end - 5e-9) - at(d, "vout", T_START - 1e-9), at(d, "col0", t_end - 5e-9)
