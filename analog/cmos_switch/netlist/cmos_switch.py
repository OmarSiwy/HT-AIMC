"""CMOS transmission gate — topology + R_on-budget sizing. Prints the bare .subckt deck.

Ported from AnalogIOC library/cmos_switch.py: NMOS + PMOS in parallel between in_ and
out, gated by ctrl / ctrl_b. Parametrised: every parent (write_dac, rstring_ladder,
integrator_conv, weight_tile, lora_sidecar) instantiates its own uniquely named copy,
    build(f"{parent}_sw", **sizes(r_on=<parent budget>))
or passes explicit W/L like AnalogIOC's cmos_switch_spice(name, w_n, l_n, w_p, l_p).

Sizing (spec: analog/cmos_switch/docs/architecture.md). A switch sits in triode, so it
has no gm/ID coordinate; it is sized from an R_on budget. L = min for every switch:
R_on*C and injected charge (Q ~ W*L) both favour the shortest channel.

sizes(r_on) — parents: square-law triode,
    G_on(v) = un_cox W_n/L (VDD - v - vth_n) + up_cox W_p/L (v - vth_p)
  W_p/W_n = un_cox/up_cox cancels the v term: G_on is flat across the range at
  un_cox W_n/L (VDD - vth_n - vth_p), so W_n = L / (un_cox (VDD - vth_n - vth_p) R_on).
  Each device then clamps to min_w on its own (injection and leakage scale with W).
  ponytail: square law ignores body effect, mobility degradation and the slow-cold dead
  zone — on sky130 it reads the mid-rail R_on 20x low at tt and ~400x low at ss/-40 C;
  a parent with a tight budget verifies its own settling rather than trusting it.

sizes() — the default instance, write-DAC tap role (AnalogIOC SIZING.md (c)): c_store
  settles to B_Y bits in T_WRITE over the write range [0, V_W], V_W = VCM_FRAC*VDD.
  At the top of that range only the NMOS conducts, and in the slow/cold corner it is
  subthreshold there (body effect on top of the corner Vth), so R_on has no closed form.
  dead_zone() measures R_on(V_W) against W_n on every corner x temperature of the PDK
  (cached in netlist/char/<pdk>.json, like docs/pdk_char.py) and W_n is the smallest
  width whose worst case sits R_GUARD under the budget. PMOS carries only the top of
  [0, VDD], outside the write range: min_w, least injection and leakage.
  (sky130: 0.42 -> 788k, 0.58 -> 380k ohm at ss/-40 C vs 534k; the ff/125 C pedestal
  caps W_n near 0.6 um — tb_cmos_switch checks it.)
"""
import json
import math
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

A = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(A / "docs"), str(A / "common")]
import specs  # noqa: E402
from devices import deck, fet  # noqa: E402
from pdk_char import ngspice  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402

import spicerack as ps  # noqa: E402

PORTS = ["in_", "out", "ctrl", "ctrl_b", "vdd", "vss"]

T_WRITE = 100e-9    # s, gain-cell write slot (AnalogIOC write_dac / lora_sidecar: < 100 ns)
R_GUARD = 0.75      # worst-corner R_on target / budget: margin for mismatch and layout
TEMPS = (-40, 27, 125)
DV = 5e-3           # V across the on switch when measuring R_on (small-signal)
CHAR = Path(__file__).resolve().parent / "char"


def v_write(pdk=None):
    """Top of the default role's signal range (AnalogIOC's 0.9 V write ceiling)."""
    return specs.VCM_FRAC * (pdk or get_pdk()).vdd


def r_on_budget(pdk=None):
    """Default role's R_on ceiling [ohm]: c_store settles to B_Y bits in T_WRITE."""
    return T_WRITE / ((specs.B_Y + 1) * math.log(2) * specs.design(pdk)["c_store"])


def _r_on_at(pdk, corner, temp, widths):
    """R_on(V_W) of a TG (nfet W in widths, pfet min_w) on one corner/temperature."""
    vw, L = v_write(pdk), pdk.min_l
    lines = [f"* cmos_switch dead zone {corner} {temp}C", pdk.lib_line(corner),
             f".temp {temp}", f"Vdd vdd 0 {pdk.vdd}", f"Vw vw 0 {vw}"]
    for k, w in enumerate(widths):
        lines += [pdk.fet_card.format(name=f"n{k}", d="vw", g="vdd", s=f"o{k}", b="0",
                                      model=pdk.nfet, w=pdk.um(w), l=pdk.um(L), extra=""),
                  pdk.fet_card.format(name=f"p{k}", d="vw", g="0", s=f"o{k}", b="vdd",
                                      model=pdk.pfet, w=pdk.um(pdk.min_w), l=pdk.um(L),
                                      extra=""),
                  f"Vd{k} vw o{k} {DV}"]
    lines += [".control", "op"] + [f"let r{k} = {DV}/abs(i(Vd{k}))\nprint r{k}"
                                   for k in range(len(widths))] + [".endc"]
    r = ngspice(lines)
    return [r[f"r{k}"] for k in range(len(widths))]


def dead_zone(pdk=None):
    """{"widths": [...], "r_on": {"<corner>@<temp>": [...]}} — R_on(V_W) per nfet width,
    measured once per PDK and cached."""
    pdk = pdk or get_pdk()
    widths = [round(pdk.min_w + 0.01 * k, 2) for k in range(int(2 * pdk.min_w / 0.01) + 1)]
    key = {"v_w": v_write(pdk), "min_l": pdk.min_l, "w_p": pdk.min_w, "widths": widths,
           "corners": list(pdk.corners), "temps": list(TEMPS)}
    path = CHAR / f"{pdk.name}.json"
    if path.exists():
        got = json.loads(path.read_text())
        if got["key"] == key:
            return got
    runs = [(c, t) for c in pdk.corners for t in TEMPS]
    with ThreadPoolExecutor(len(runs)) as ex:
        res = list(ex.map(lambda ct: _r_on_at(pdk, *ct, widths), runs))
    got = {"key": key, "widths": widths,
           "r_on": {f"{c}@{t}": r for (c, t), r in zip(runs, res)}}
    CHAR.mkdir(exist_ok=True)
    path.write_text(json.dumps(got, indent=1) + "\n")
    return got


def sizes(r_on=None, pdk=None):
    """{w_n, l_n, w_p, l_p} in um: square-law flat R_on of `r_on` ohm, or the default
    write-DAC-tap sizing when r_on is None."""
    pdk = pdk or get_pdk()
    L = pdk.min_l
    if r_on is None:
        # AnalogIOC default (inv_n / inv_p): 0.42 / 0.84 um — a 2:1 inverter ratio, not a
        # switch derivation: 788 kohm at V_W in ss/-40 C, +15 mV pedestal, 40x leakage
        dz = dead_zone(pdk)
        worst = [max(r[k] for r in dz["r_on"].values()) for k in range(len(dz["widths"]))]
        target = R_GUARD * r_on_budget(pdk)
        ok = [w for w, r in zip(dz["widths"], worst) if r <= target]
        if not ok:
            raise ValueError(f"no nfet up to {dz['widths'][-1]} um meets "
                             f"{target:.3g} ohm at V_W: widen the search")
        return {"w_n": ok[0], "l_n": L, "w_p": pdk.min_w, "l_p": L}
    w_n = L / (pdk.un_cox * 1e-6 * (pdk.vdd - pdk.vth_n - pdk.vth_p) * r_on)
    w_p = w_n * pdk.un_cox / pdk.up_cox
    return {"w_n": max(pdk.min_w, round(w_n, 2)), "l_n": L,
            "w_p": max(pdk.min_w, round(w_p, 2)), "l_p": L}


def build(name="cmos_switch", w_n=None, l_n=None, w_p=None, l_p=None, pdk=None):
    """`.subckt <name> in_ out ctrl ctrl_b vdd vss`; unset W/L take sizes()."""
    pdk = pdk or get_pdk()
    d = sizes(pdk=pdk) if None in (w_n, l_n, w_p, l_p) else {}
    s = ps.Subcircuit(name, PORTS)
    fet(s, f"{name}_n", "in_", "ctrl", "out", "vss", "nfet", w_n or d["w_n"],
        l_n or d["l_n"], pdk=pdk)
    fet(s, f"{name}_p", "in_", "ctrl_b", "out", "vdd", "pfet", w_p or d["w_p"],
        l_p or d["l_p"], pdk=pdk)
    return s


if __name__ == "__main__":
    print(deck(build()), end="")
