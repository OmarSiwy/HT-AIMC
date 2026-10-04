"""Characterise the electrical facts pdk_specs.py leaves to measurement, with the PDK's
own models in ngspice, and cache them in pdk_char/<name>.json.

    python3 analog/docs/pdk_char.py [<pdk>]      (default: $PDK)

Measured (typical corner, 27 C unless noted):
  ss_mv_dec          ln(10) / max(gm/ID), min-L nfet (gmid.py table)
  vth_n/p, un/up_cox extrapolated-linear on sqrt(J_D) vs VGS at L = 4*Lmin (gmid.py)
  mim_ff_um2/_um     |I|/(2 pi f V) of square mim_caps at min side and 10x it, 1 MHz:
                     C = ca*s^2 + 4*cp*s solved for area ca and perimeter cp
  res_*_ohm_sq, tc1  R of a 10-square poly_res at 27 and 85 C
  t_inv_ps_per_ff    min inverter (Wp = 2*Wn = 2*Wmin): mean tpd slope 50 -> 150 fF
  a_vt               diode-connected W=L=1 um nfet forced at gm/ID=10, 40 mismatch
                     seeds (<typical><mismatch_suffix>): sigma(VGS) * sqrt(2*W*L)

Every run prints the measured value next to any declared one; declared values win in
get_pdk(), so a large disagreement is a declaration to re-check.
"""
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gmid  # noqa: E402
from pdk_specs import MEASURED, get_pdk  # noqa: E402


def ngspice(lines):
    """Run a raw deck, return {name: value} from `print` lines."""
    with tempfile.TemporaryDirectory() as d:
        cir = Path(d) / "c.cir"
        cir.write_text("\n".join(lines) + "\n.end\n")
        out = subprocess.run(["ngspice", "-b", str(cir)], capture_output=True, text=True,
                             cwd=d, timeout=600).stdout
    vals = {}
    for m in re.finditer(r"^(\w+)\s*=\s*([-+\d.eE]+)", out, re.M):
        vals[m.group(1)] = float(m.group(2))
    if not vals:
        raise RuntimeError("ngspice printed nothing:\n" + out[-1500:])
    return vals


def elr(dev, L):
    """(Vth, u*Cox [uA/V^2]) by extrapolated-linear fit of sqrt(J_D) vs |VGS|."""
    t = gmid.load_table(dev, L)
    v, sj = t["VGS"], np.sqrt(t["ID_per_W"])
    slope = np.gradient(sj, v)
    i = int(np.argmax(slope))
    vth = v[i] - sj[i] / slope[i]
    return float(vth), float(2 * L * slope[i] ** 2 * 1e6)


def characterise(pdk):
    got = {}
    got["ss_mv_dec"] = 1000 * math.log(10) / float(gmid.load_table("nfet", pdk.min_l)["gm_ID"].max())
    L4 = round(4 * pdk.min_l, 3)
    got["vth_n"], got["un_cox"] = elr("nfet", L4)
    got["vth_p"], got["up_cox"] = elr("pfet", L4)

    head = [f"* pdk_char {pdk.name}", pdk.lib_line()]
    # MIM: C(s) = ca*s^2 + 4*cp*s from two square sizes (min side and 10x that)
    cs = {}
    for side in (max(pdk.mim_min_side, 1.0), 10 * max(pdk.mim_min_side, 1.0)):
        cap = pdk.mim_card.format(name="c1", p="c", n="0", model=pdk.mim_cap,
                                  w=pdk.um(side), l=pdk.um(side))
        r = ngspice(head + ["V1 c 0 AC 1", cap, ".control", "ac lin 1 1meg 1meg",
                            "let c = abs(i(V1))/(2*3.14159265*1e6)", "print c", ".endc"])
        cs[side] = r["c"] * 1e15
    (s1, c1), (s2, c2) = sorted(cs.items())
    cp = (c1 / s1 ** 2 - c2 / s2 ** 2) / (4 / s1 - 4 / s2)
    got["mim_ff_um"] = cp
    got["mim_ff_um2"] = (c2 - 4 * cp * s2) / s2 ** 2

    tc = {}
    for kind in ("res_poly", "res_poly_lotc"):
        w = getattr(pdk, kind + "_w")
        card = pdk.res_card.format(name="r1", p="a", n="0", b="0", model=getattr(pdk, kind),
                                   w=pdk.um(w), l=pdk.um(10 * w))
        rr = {}
        for temp in (27, 85):
            rr[temp] = ngspice(head + [f".temp {temp}", "V1 a 0 1", card, ".control", "op",
                                       "let r = -1/i(V1)", "print r", ".endc"])["r"]
        got[kind + "_ohm_sq"] = rr[27] / 10
        tc[kind] = (rr[85] / rr[27] - 1) / 58

    wn, L = pdk.min_w, pdk.min_l
    fn = pdk.fet_card.format(name="n1", d="y", g="a", s="0", b="0", model=pdk.nfet,
                             w=pdk.um(wn), l=pdk.um(L), extra="")
    fp = pdk.fet_card.format(name="p1", d="y", g="a", s="vdd", b="vdd", model=pdk.pfet,
                             w=pdk.um(2 * wn), l=pdk.um(L), extra="")
    tpd = {}
    for cl in (50, 150):
        vd, t = pdk.vdd, 20e-9
        r = ngspice(head + [f"Vdd vdd 0 {vd}",
                            f"Va a 0 PULSE(0 {vd} 1n 20p 20p {t / 2} {t})", fn, fp,
                            f"Cl y 0 {cl}f", ".control", f"tran 1p {1.5 * t}",
                            f"meas tran tf TRIG v(a) VAL={vd / 2} RISE=1 TARG v(y) VAL={vd / 2} FALL=1",
                            f"meas tran tr TRIG v(a) VAL={vd / 2} FALL=1 TARG v(y) VAL={vd / 2} RISE=1",
                            "let tpd = (tf + tr) / 2", "print tpd", ".endc"])
        tpd[cl] = r["tpd"]
    got["t_inv_ps_per_ff"] = (tpd[150] - tpd[50]) * 1e12 / 100

    W = L = 1.0
    i_d = float(gmid.J_D(10.0, L, "nfet")) * W
    mm = [f"* pdk_char {pdk.name} mismatch", pdk.lib_line(pdk.typical + pdk.mismatch_suffix)]
    diode = pdk.fet_card.format(name="n1", d="g", g="g", s="0", b="0", model=pdk.nfet,
                                w=pdk.um(W), l=pdk.um(L), extra="")
    vgs = [ngspice(mm + [f".options seed={i}", f"I1 0 g DC {i_d:.4e}", diode, ".control",
                         "op", "let vgs = v(g)", "print vgs", ".endc"])["vgs"]
           for i in range(1, 41)]
    got["a_vt"] = float(np.std(vgs, ddof=1)) * 1e3 * math.sqrt(2 * W * L)
    return got, tc


def main():
    pdk = get_pdk(sys.argv[1] if len(sys.argv) > 1 else "")
    if not pdk.installed or not pdk.lib_path().exists():
        sys.exit(f"{pdk.name}: not installed under {pdk.lib_path() if pdk.installed else '-'}")
    got, tc = characterise(pdk)
    decl = pdk.__class__()
    print(f"{pdk.name} (typical, 27 C)     measured    declared")
    for k in MEASURED:
        if k in got:
            d = getattr(decl, k)
            print(f"  {k:<22} {got[k]:>10.4g}  {d if d else '-':>10}")
    for k, v in tc.items():
        print(f"  {k + ' tc1':<22} {v:>10.3e}  (1/K)")
    out = HERE / "pdk_char" / f"{pdk.name}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"pdk": pdk.name, "corner": pdk.typical, "temp_c": 27,
                               "values": got, "tc1": tc}, indent=2) + "\n")
    print(f"-> {out}")


if __name__ == "__main__":
    main()
