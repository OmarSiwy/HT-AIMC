"""Testbench plumbing: pick the DUT from $DUT, wrap it for SpiceRack, report PASS/FAIL.

Every testbench runs unchanged on three DUT sources (analog-design-flow skill, stage 3):

    DUT=va   analog/<block>/va/<block>.va         golden model (VerA -> ESPice, `.hdl`)
    DUT=sch  analog/<block>/netlist/<block>.spice  generated deck (make netlist)
    DUT=pex  analog/<block>/output/$PEX_FROM/<block>_pex.spice   post-layout netlist:
             PEX_FROM=pnr (default) converted Philis extraction (analog/common/pex.py),
             PEX_FROM=gen substrate2 generator + magic (analog/common/layout/verify.py)

The DUT is always instance `xdut` on nets named after its ports, so stimulus and probes
never change between sources. Process corner / temperature come from $CORNER / $SIM_TEMP
(defaults: the PDK's typical section, 27 C).
"""
import os
import sys
from pathlib import Path

ANALOG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ANALOG / "docs"))
from pdk_specs import get_pdk  # noqa: E402

import spicerack as ps  # noqa: E402

KINDS = ("va", "sch", "pex")
PEX_FROM = ("pnr", "gen")


def dut_kind() -> str:
    kind = os.environ.get("DUT", "sch")
    if kind not in KINDS:
        raise ValueError(f"DUT={kind!r}; expected one of {KINDS}")
    return kind


def pex_from() -> str:
    src = os.environ.get("PEX_FROM", "pnr")
    if src not in PEX_FROM:
        raise ValueError(f"PEX_FROM={src!r}; expected one of {PEX_FROM}")
    return src


def dut_path(block: str, kind: str = "") -> Path:
    kind = kind or dut_kind()
    return {"va": ANALOG / block / "va" / f"{block}.va",
            "sch": ANALOG / block / "netlist" / f"{block}.spice",
            "pex": ANALOG / block / "output" / pex_from() / f"{block}_pex.spice"}[kind]


def dut(block: str, ports: list, kind: str = "", **va_params) -> ps.Subcircuit:
    """A wrapper Subcircuit holding `xdut` (the block) on nets named after its ports."""
    kind = kind or dut_kind()
    path = dut_path(block, kind)
    if not path.exists():
        hint = {"va": "write it (vera skill)",
                "sch": f"make -C analog/{block}/build/schematic netlist",
                "pex": {"pnr": "run Philis then analog/common/pex.py (philis skill)",
                        "gen": f"make -C analog/{block}/build/layout gen gen-pex"}[pex_from()]
                }[kind]
        raise FileNotFoundError(f"DUT={kind}: {path} missing — {hint}")
    top = ps.Subcircuit(f"tb_{block}")
    if kind == "va":
        top.veriloga(str(path))
        params = " ".join(f"{k}={v}" for k, v in va_params.items())
        top.raw_spice(f".model {block}_va {block} {params}".rstrip())
        top.raw_spice(f"Nxdut {' '.join(ports)} {block}_va")
    else:
        top.include(str(path))
        top.X("xdut", block, *ports)
    return top


def testbench(block: str, ports: list, kind: str = "", corner: str = "",
              temp: float = None, **va_params) -> ps.Testbench:
    """Testbench around the DUT with the PDK models of `corner` at `temp`."""
    pdk = get_pdk()
    tb = ps.Testbench(dut(block, ports, kind, **va_params))
    tb.use_pdk(pdk.model_library(corner or os.environ.get("CORNER", "")))
    tb.temperature = float(temp if temp is not None else os.environ.get("SIM_TEMP", 27))
    return tb


class Report:
    """Collect named checks, print them, exit non-zero on any failure."""

    def __init__(self, title: str):
        self.title, self.ok = title, True
        print(f"\n== {title} [DUT={dut_kind()} PDK={get_pdk().name} "
              f"CORNER={os.environ.get('CORNER', get_pdk().typical)} "
              f"SIM_TEMP={os.environ.get('SIM_TEMP', 27)}] ==")

    def check(self, label: str, passed: bool, detail: str = "") -> bool:
        self.ok &= bool(passed)
        print(f"  {'PASS' if passed else 'FAIL'}  {label}" + (f"  ({detail})" if detail else ""))
        return passed

    def done(self):
        print(f"  OVERALL: {'PASS' if self.ok else 'FAIL'}")
        sys.exit(0 if self.ok else 1)
