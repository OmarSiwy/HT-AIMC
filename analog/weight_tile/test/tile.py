"""weight_tile testbench fixture: a programmed column DUT on every $DUT source, the real
column integrator as the measuring instrument, and the chop-grid stimulus.

A column is R rows on one rail col0 — (Cp[i], Cn[i]) per row:
  DUT=sch  netlist/weight_tile.py build([Cp], [Cn]) — AnalogIOC generate(), exactly the
           tile the codes make (one phi buffer pair, zero banks omitted)
  DUT=va   R instances of va/weight_tile.va (one crosspoint each) with wp/wn per row,
           crail on row 0 only
  DUT=pex  R copies of the post-layout canonical crosspoint (both banks at code 15),
           each programmed by deleting the bit caps its code leaves out; Xrail0 kept on
           row 0 only. Per-row phi buffers and the parasitics of unused bits stay (a
           zero bank's TGs and dummies too) — conservative against AnalogIOC's column.
Every row instance sees xin_p_r<i> xin_n_r<i> col0 phi1 phi1e phi2 vcm vdd vss.

Instrument (AnalogIOC _conv_common.integrator_fixture): the migrated ota block with its
replica bias (ota/test/ota_bench.bias_network), C_int = specs.c_int() from vout to col0,
a reset TG across C_int released at T_RST. Chop grid, envelopes: pwm_driver's tb.
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
from tb_pwm_driver import PHI1_D, PHI1_W, PHI2_D, T_CLK, T_EDGE, T_START, pulse_train  # noqa: E402

import spicerack as ps  # noqa: E402

PDK = get_pdk()
VDD = PDK.vdd
VCM = specs.VCM_FRAC * VDD
TQ = specs.TQ_SIM
C_INT = specs.c_int()
U1 = specs.u1()                  # ideal volts per MAC code unit
T_RST = 4e-9
ROW = ["xin_p_r{i}", "xin_n_r{i}", "col0", "phi1", "phi1e", "phi2", "vcm", "vdd", "vss"]
BUILD = A / "weight_tile" / "output" / "tb"
# reset TG: C_int to B_Y bits inside the T_RST window (AnalogIOC sh_sw 0.84/1.68 um)
R_RST = T_RST / ((specs.B_Y + 1) * math.log(2) * C_INT)


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


def _pex_rows(cp, cn, rail=True):
    """The canonical post-layout crosspoint, one programmed copy per row."""
    src = dut_path("weight_tile", "pex").read_text()
    body = src[src.index(".subckt weight_tile "): src.index(".ends weight_tile")]
    out = []
    for i, (p, n) in enumerate(zip(cp, cn)):
        drop = {f"x{pol}0_0_b{b}" for pol, c in (("p", p), ("n", n))
                for b in range(wt.N_BITS) if not (c >> b) & 1}
        drop |= {f"xball{pol}0_0" for pol, c in (("p", p), ("n", n)) if not c}
        drop |= {"xrail0"} if i or not rail else set()
        lines = _drop(body, drop).splitlines()
        lines[0] = lines[0].replace(".subckt weight_tile ", f".subckt weight_tile_r{i} ", 1)
        out += lines + [f".ends weight_tile_r{i}", ""]
    return "\n".join(out)


def column(cp, cn, kind="", rail=True, ideal_ota=False):
    """Wrapper Subcircuit: the programmed column (row i codes cp[i], cn[i]) + instrument
    (vout) + OTA bias. Nets: xin_p_r<i>, xin_n_r<i>, col0, phi1/phi1e/phi2, vcm, vdd, vss,
    rst/rst_b, vout. rail=False drops C_RAIL; ideal_ota swaps the OTA for an A=1e6 VCVS
    with a 1 ps pole (tb_csnr isolate)."""
    kind = kind or dut_kind()
    path = dut_path("weight_tile", kind)
    if not path.exists():
        raise FileNotFoundError(f"DUT={kind}: {path} missing")
    top = ps.Subcircuit("tb_weight_tile")
    rows = range(len(cp))
    if kind == "sch":
        text = wt.text([list(cp)], [list(cn)])
        top.include(str(_write(text if rail else _drop(text, {"xrail0"}), "sch")))
        top.X("xdut", "weight_tile", *wt.ports(len(cp), 1))
    elif kind == "va":
        sz = wt.sizes()
        top.veriloga(str(path))
        for i in rows:
            top.raw_spice(f".model wt_r{i} weight_tile wp={cp[i]} wn={cn[i]} cu={sz['c_u']:.6g} "
                          f"cb={sz['c_ball']:.6g} crail={sz['c_rail'] if i == 0 and rail else 0:.6g}")
            top.raw_spice(f"Nxdut{i} {' '.join(p.format(i=i) for p in ROW)} wt_r{i}")
    else:
        top.include(str(_write(_pex_rows(cp, cn, rail), "pex")))
        for i in rows:
            top.X(f"xdut{i}", f"weight_tile_r{i}", *(p.format(i=i) for p in ROW))
    top.include(str(_instrument()))
    if ideal_ota:
        top.E(name="ota", positive="oi", negative="0", control_positive="vcm",
              control_negative="col0", voltage_gain=1e6)
        top.R(name="ota", positive="oi", negative="vout", value=1e3)
        top.C(name="ota", positive="vout", negative="0", value=1e-15)
    else:
        top.X("xota", "ota", "vcm", "col0", "vout", "vb_nc", "vb_pc", "vb_tail", "vdd", "vss")
    top.X("xrst", "int_rst_sw", "vout", "col0", "rst", "rst_b", "vdd", "vss")
    bias_network(top)
    return top


def testbench(cp, cn, kind="", corner="", temp=None, **col):
    """Column + instrument + supplies/vcm/reset; $CORNER/$SIM_TEMP as bench.testbench."""
    tb = ps.Testbench(column(cp, cn, kind, **col))
    tb.use_pdk(PDK.model_library(corner or os.environ.get("CORNER", "")))
    tb.temperature = float(temp if temp is not None else os.environ.get("SIM_TEMP", 27))
    tb.options(reltol=1e-4, abstol=1e-12, vntol=1e-6, method="gear")   # AnalogIOC TIGHT
    tb.C(name="int", positive="vout", negative="col0", value=C_INT)
    tb.V(name="sup", positive="vdd", negative="0", value=VDD)
    tb.V(name="ss", positive="vss", negative="0", value=0.0)
    tb.V(name="cm", positive="vcm", negative="0", value=VCM)
    tb.PieceWiseLinearVoltageSource(name="rst", positive="rst", negative="0",
                                    values=[(0, VDD), (T_RST, VDD), (T_RST + 0.2e-9, 0.0)])
    tb.PieceWiseLinearVoltageSource(name="rstb", positive="rst_b", negative="0",
                                    values=[(0, 0.0), (T_RST, 0.0), (T_RST + 0.2e-9, VDD)])
    return tb


def clocks(tb, t_chop, end):
    """phi1/phi1e/phi2 on the chop grid (AnalogIOC _conv_common.phi_sources)."""
    p2w = t_chop - PHI2_D - 0.5e-9 - T_CLK
    for name, d, w in (("phi1", PHI1_D, PHI1_W), ("phi1e", PHI1_D, PHI1_W + 0.2e-9),
                       ("phi2", PHI2_D, p2w)):
        tb.PieceWiseLinearVoltageSource(name=name, positive=name, negative="0",
                                        values=pulse_train(d, w, t_chop, end))


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
