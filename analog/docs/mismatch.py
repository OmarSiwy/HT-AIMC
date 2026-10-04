"""Measured local mismatch for sizing: sigma(VGS) of one device at its operating point.

    sigma_vgs(dev, W, L, i_d)  -> mV, one device, current-forced diode, N mismatch seeds
    pair_offset(dev, W, L, i_d) -> mV, sigma of a matched pair's input offset (sqrt(2)x)

Why not Pelgrom: pdk.a_vt (pdk_char.py, W=L=1 um) is a first guess only. PDK mismatch
models are binned and do not scale as 1/sqrt(W*L) at short L — sky130 nfet_01v8 at
W=10.45/L=0.30 has sigma(VGS) 3.66 mV where A_vt=5.26 predicts 2.10 (implied A_vt 9-11).
So offset budgets are sized against the PDK's own mismatch at the candidate geometry.

Results are cached in mismatch_cache/<pdk>.json keyed by (dev, W, L, I) and committed like
the gm/ID tables; a missing point costs N ngspice runs on the PDK's mismatch corner
(<typical><mismatch_suffix>). MISMATCH_N sets N (default 30: ~13% sigma uncertainty).
"""
import json
import math
import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from pdk_specs import get_pdk  # noqa: E402

N = int(os.environ.get("MISMATCH_N", 30))
_mem = {}


def _cache_path(pdk):
    return HERE / "mismatch_cache" / f"{pdk.name}.json"


def _load(pdk):
    if pdk.name not in _mem:
        p = _cache_path(pdk)
        _mem[pdk.name] = json.loads(p.read_text()) if p.exists() else {}
    return _mem[pdk.name]


def sigma_vgs(dev, W, L, i_d, pdk=None):
    """sigma(VGS) [mV] of one `dev` ("nfet"/"pfet") W x L [um] carrying i_d [A]."""
    from pdk_char import ngspice   # lazy: only when a point must be measured
    pdk = pdk or get_pdk()
    key = f"{dev} W={W:g} L={L:g} I={i_d:.3e}"
    cache = _load(pdk)
    if key not in cache:
        model = pdk.nfet if dev == "nfet" else pdk.pfet
        # diode-connected; PMOS hangs from vdd with the current pulled out of its gate
        if dev == "nfet":
            card = pdk.fet_card.format(name="m1", d="g", g="g", s="0", b="0", model=model,
                                       w=pdk.um(W), l=pdk.um(L), extra="")
            src, probe = f"I1 0 g DC {i_d:.4e}", "v(g)"
        else:
            card = pdk.fet_card.format(name="m1", d="g", g="g", s="vdd", b="vdd", model=model,
                                       w=pdk.um(W), l=pdk.um(L), extra="")
            src, probe = f"Vdd vdd 0 {pdk.vdd}\nI1 g 0 DC {i_d:.4e}", "v(vdd)-v(g)"
        head = [f"* mismatch {pdk.name} {key}", pdk.lib_line(pdk.typical + pdk.mismatch_suffix)]
        v = [ngspice(head + [f".options seed={i}", src, card, ".control", "op",
                             f"let vgs = {probe}", "print vgs", ".endc"])["vgs"]
             for i in range(1, N + 1)]
        cache[key] = float(np.std(v, ddof=1)) * 1e3
        p = _cache_path(pdk)
        p.parent.mkdir(exist_ok=True)
        p.write_text(json.dumps(dict(sorted(cache.items())), indent=1) + "\n")
    return cache[key]


def pair_offset(dev, W, L, i_d, pdk=None):
    """sigma [mV] of a matched pair's input offset: sqrt(2) x one device's sigma(VGS)."""
    return math.sqrt(2) * sigma_vgs(dev, W, L, i_d, pdk)


if __name__ == "__main__":
    p = get_pdk()
    s = sigma_vgs("nfet", 1.0, 1.0, 4.9e-6)
    print(f"{p.name}: nfet 1x1 um @4.9uA sigma(VGS) = {s:.2f} mV "
          f"(Pelgrom a_vt {p.a_vt:.2f} -> {p.a_vt / math.sqrt(2):.2f} mV)")
