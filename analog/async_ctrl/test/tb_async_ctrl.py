"""async_ctrl sequencing + tq_chain t_q grid.

Spec rows (analog/async_ctrl/docs/architecture.md):
  sequencing: GO rise -> xbar_rst pulse -> settle -> adc_go -> (modelled adc_done) -> done;
    every edge present, in that order; reset pulse 1-50 ns; settle > 2 ns; done high at end
  t_q grid: tap k rises ~k * TQ_SIM after `in`; at the typical corner / 27 C stage 1 in
    0.5-1.3 x TQ_SIM (it sees the driving edge, not a slow ramp), inner stages
    TQ_SIM +-30%; inner-stage spread < 10% everywhere (the PWM grid is ratiometric to
    t_q, the absolute value is a TT spec)

Adapted from AnalogIOC analog/testbenches/tb_async_ctrl.py (ngspice batch -> SpiceRack).
The ADC-done model (adc_go -> 5k/1.6p RC -> 2 inverters) is stimulus, kept from AnalogIOC.
"""
import os
import sys
from pathlib import Path

A = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(A / "docs"), str(A / "common"), str(A / "async_ctrl" / "netlist")]
import specs  # noqa: E402
from async_ctrl import PORTS, sizes, tq_ports  # noqa: E402
from bench import Report, dut_kind, dut_path, testbench  # noqa: E402
from devices import fet  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402

import spicerack as ps  # noqa: E402

PDK = get_pdk()
VDD = PDK.vdd
VTH = VDD / 2
SIM_TIME = 200e-9      # AnalogIOC 100 ns; room for the slow corners to reach `done`
GO_RISE = 10e-9
TQ_PORTS = tq_ports()
TQ_SPEC = specs.TQ_SIM   # nominal t_q per stage
TQ_TOL = 0.3             # +-30% absolute window at TT
TQ_SPREAD = 0.10         # stage-to-stage mismatch bound (identical stages)
TQ_IN_RISE = 5e-9
TQ_END = 120e-9


def cross(t, v, level, falling=False):
    """First crossing time of v through level, or None."""
    for i in range(1, len(t)):
        if (v[i - 1] > level >= v[i]) if falling else (v[i - 1] < level <= v[i]):
            return t[i]
    return None


def adc_model():
    """AnalogIOC's modelled ADC: adc_go through a ~8 ns RC and a 2-inverter buffer."""
    sz = sizes(PDK)
    s = ps.Subcircuit("adc_model", ["adc_go", "adc_done", "vdd", "vss"])
    s.R(name="adc", positive="adc_go", negative="adc_dly", value=5e3)
    s.C(name="adc", positive="adc_dly", negative="vss", value=1.6e-12)
    for name, out, inp in (("ad1", "adc_buf_b", "adc_dly"), ("ad2", "adc_done", "adc_buf_b")):
        fet(s, f"{name}_n", out, inp, "vss", "vss", "nfet", *sz["inv_n"], pdk=PDK)
        fet(s, f"{name}_p", out, inp, "vdd", "vdd", "pfet", *sz["inv_p"], pdk=PDK)
    return s


def run_sequencing(r):
    tb = testbench("async_ctrl", PORTS)
    tb.V(name="sup", positive="vdd", negative="0", value=VDD)
    tb.V(name="ss", positive="vss", negative="0", value=0.0)
    tb.PieceWiseLinearVoltageSource(
        name="go", positive="go", negative="0",
        values=[(0, 0), (GO_RISE - 0.1e-9, 0), (GO_RISE, VDD), (SIM_TIME, VDD)])
    tb.add_subcircuit(adc_model())
    tb.extra_line("Xadc adc_go adc_done vdd 0 adc_model")
    tb.save("V(go)", "V(xbar_rst)", "V(adc_go)", "V(adc_done)", "V(done)")
    d = tb.transient(step_time=0.1e-9, end_time=SIM_TIME)
    t = d.time
    e = {"go_rise": cross(t, d["go"], VTH),
         "rst_rise": cross(t, d["xbar_rst"], VTH),
         "rst_fall": cross(t, d["xbar_rst"], VTH, falling=True),
         "adc_go_rise": cross(t, d["adc_go"], VTH),
         "done_rise": cross(t, d["done"], VTH)}
    print("  " + "  ".join(f"{k} {'never' if v is None else f'{v * 1e9:.2f} ns'}"
                           for k, v in e.items()))
    if not r.check("all sequencing edges present", None not in e.values()):
        return
    order = list(e)
    for a, b in zip(order, order[1:]):
        r.check(f"{a} <= {b}", e[a] <= e[b])
    rst_w = e["rst_fall"] - e["rst_rise"]
    settle_w = e["adc_go_rise"] - e["rst_fall"]
    r.check("reset pulse 1-50 ns", 1e-9 < rst_w < 50e-9, f"{rst_w * 1e9:.2f} ns")
    r.check("settle phase > 2 ns", settle_w > 2e-9, f"{settle_w * 1e9:.2f} ns")
    r.check("done asserted at end", d["done"][-1] > VTH,
            f"GO -> done {(e['done_rise'] - e['go_rise']) * 1e9:.2f} ns")


def tq_testbench(corner="", temp=None):
    """Bench around tq_chain (bench.testbench() only instantiates the block's own
    subckt; ponytail: fold into bench.dut() as a `subckt=` argument)."""
    kind = dut_kind()
    top = ps.Subcircuit("tb_tq_chain")
    if kind == "va":
        top.veriloga(str(A / "async_ctrl" / "va" / "tq_chain.va"))
        top.raw_spice(".model tq_chain_va tq_chain")
        top.raw_spice(f"Nxdut {' '.join(TQ_PORTS)} tq_chain_va")
    else:
        # pex: tq_chain has its own Philis run (async_ctrl's layout does not contain it)
        path = dut_path("async_ctrl", kind)
        top.include(str(path.with_name("tq_chain_pex.spice") if kind == "pex" else path))
        top.X("xdut", "tq_chain", *TQ_PORTS)
    tb = ps.Testbench(top)
    tb.use_pdk(PDK.model_library(corner or os.environ.get("CORNER", "")))
    tb.temperature = float(temp if temp is not None else os.environ.get("TEMP", 27))
    return tb


def tq_stages(tb):
    """Stage delays [s] of the tap grid (None if a tap never toggles)."""
    taps = TQ_PORTS[1:-2]
    tb.V(name="sup", positive="vdd", negative="0", value=VDD)
    tb.V(name="ss", positive="vss", negative="0", value=0.0)
    tb.PieceWiseLinearVoltageSource(
        name="in", positive="in", negative="0",
        values=[(0, 0), (TQ_IN_RISE - 0.1e-9, 0), (TQ_IN_RISE, VDD), (TQ_END, VDD)])
    tb.save(*(f"V({s})" for s in ["in"] + taps))
    d = tb.transient(step_time=0.05e-9, end_time=TQ_END)
    edges = [cross(d.time, d[s], VTH) for s in ["in"] + taps]
    if None in edges:
        return None
    return [b - a for a, b in zip(edges, edges[1:])]


def spread(stage):
    inner = stage[1:]   # identically driven + loaded stages set the PWM grid
    return (max(inner) - min(inner)) / (sum(inner) / len(inner))


def run_tq_grid(r):
    stage = tq_stages(tq_testbench())
    if not r.check("all taps toggle", stage is not None):
        return
    nominal = os.environ.get("CORNER", PDK.typical) == PDK.typical and \
        float(os.environ.get("TEMP", 27)) == 27
    for k, dt in enumerate(stage, 1):
        lo, hi = (0.5, 1.3) if k == 1 else (1 - TQ_TOL, 1 + TQ_TOL)
        ok = lo * TQ_SPEC < dt < hi * TQ_SPEC
        if nominal:
            r.check(f"t_q stage {k} in {lo * TQ_SPEC * 1e9:.0f}-{hi * TQ_SPEC * 1e9:.0f} ns",
                    ok, f"{dt * 1e9:.2f} ns")
        else:
            print(f"  info  t_q stage {k} = {dt * 1e9:.2f} ns (absolute window is TT-only)")
    inner = stage[1:]
    mean = sum(inner) / len(inner)
    if dut_kind() != "va":
        print(f"  info  inner t_q {mean * 1e9:.2f} ns = "
              f"{mean / 2 / (sizes(PDK)['c_tq'] * 1e15) * 1e12:.2f} ps/fF per inverter")
    r.check(f"inner-stage spread < {TQ_SPREAD * 100:.0f}%", spread(stage) < TQ_SPREAD,
            f"mean {mean * 1e9:.2f} ns, spread {spread(stage) * 100:.2f}%")


def main():
    r = Report("async_ctrl")
    run_sequencing(r)
    run_tq_grid(r)
    r.done()


if __name__ == "__main__":
    main()
