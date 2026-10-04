"""OTA testbench around bench.dut: supplies plus the bias the system must supply.

The OTA's bias ports take voltages, but fixed voltages cannot hold the operating point
across PVT: the tail runs in weak inversion (gm/ID = 18), so a fixed vb_tail moves its
current exponentially with Vt and T (AnalogIOC's ideal bias_spice sources give 1.8 uA at
ss/-40 C against the 12 uA spec). Every testbench therefore drives the rails the way a
bias generator does — this is the block's bias contract:

  vb_tail  diode-connected copy of the tail carrying I_TAIL (a 1:1 mirror). The tail
           itself sits at Vds = ts ~ 0.1 V, so it delivers ~9 uA (AnalogIOC: 8 uA).
           Forcing the full 12 uA (a replica at the tail's own Vds) was tried: it
           pushes the tail into triode, the buffer's CM rejection collapses and the
           closed-loop gain error fails (loop gain 154 at tt) — the stack has no
           headroom for the design current at vcm = VDD/2.
  vb_pc    diode-connected copy of the load cascode carrying I_SIDE, its source held
           ota.vsd_pm() below vdd (same VSG and body effect as the real cascode)
  vb_nc    fixed ota.bias() voltage: VGS_in and VGS_nc are both NMOS and shift
           together, so the input pair's Vds holds without tracking

The reference currents are PVT-flat — generating them is the reference block's job, not this one's.
They flow through vdd: REF_CURRENT is subtracted from the supply current to get the
OTA's own.
"""
import os
import sys
from pathlib import Path

A = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(A / "docs"), str(A / "common"), str(A / "ota" / "netlist")]
import specs  # noqa: E402
from bench import dut  # noqa: E402
from devices import fet  # noqa: E402
from ota import PORTS, bias, sizes, vsd_pm  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402

import spicerack as ps  # noqa: E402

PDK = get_pdk()
VDD = PDK.vdd
VCM = specs.VCM_FRAC * VDD
I_TAIL = specs.ota(PDK)["i_tail"]
REF_CURRENT = I_TAIL + specs.I_SIDE


def bias_network(top, pdk=PDK):
    """Replica bias on the wrapper subcircuit `top` (nets vb_*, vdd, vss)."""
    sz = sizes(pdk)
    fet(top, "rep_tail", "vb_tail", "vb_tail", "vss", "vss", "nfet", *sz["ota_tail"], pdk=pdk)
    top.I(name="ref_tail", positive="vdd", negative="vb_tail", value=I_TAIL)
    top.V(name="rep_pm", positive="vdd", negative="rep_y", value=vsd_pm())
    fet(top, "rep_pc", "vb_pc", "vb_pc", "rep_y", "vdd", "pfet", *sz["ota_pcasc"], pdk=pdk)
    top.I(name="ref_pc", positive="vb_pc", negative="vss", value=specs.I_SIDE)
    top.V(name="vb_nc", positive="vb_nc", negative="vss", value=bias(pdk)["vb_nc"])


def ota_testbench(extra=None, corner=""):
    """Testbench: DUT xdut on its port nets, vdd/vss sources, bias_network on vb_*.
    `extra(top)` adds devices to the wrapper (a Testbench carries only sources and R/C).
    $CORNER / $TEMP as bench.testbench."""
    top = dut("ota", PORTS)
    bias_network(top)
    if extra:
        extra(top)
    tb = ps.Testbench(top)
    tb.use_pdk(PDK.model_library(corner or os.environ.get("CORNER", "")))
    tb.temperature = float(os.environ.get("TEMP", 27))
    tb.V(name="sup", positive="vdd", negative="0", value=VDD)
    tb.V(name="ss", positive="vss", negative="0", value=0.0)
    return tb


if __name__ == "__main__":
    tb = ota_testbench()
    tb.V(name="p", positive="inp", negative="0", value=VCM)
    tb.V(name="fb", positive="out", negative="inn", value=0.0)
    op = tb.operating_point()
    print(f"  rails {({k: round(op[k], 3) for k in ('vb_tail', 'vb_nc', 'vb_pc')})}  "
          f"ota.bias() {bias()}  I_ota {(-op['i(vsup)'] - REF_CURRENT) * 1e6:.2f} uA "
          f"out-vcm {(op['out'] - VCM) * 1e3:+.2f} mV")
