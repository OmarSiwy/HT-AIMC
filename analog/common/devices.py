"""PDK device instances on a SpiceRack Subcircuit, and bare-subckt deck emission.

Every card is the PDK's declared template (pdk_specs: fet_card, mim_card, res_card) —
sky130 FETs are `X` subckts with W/L in um, gf180's are `X` wrappers with metre w/l,
MIM caps take W/L or c_width/c_length — so nothing here knows a PDK. SpiceRack's `X()`
takes no parameters, so the cards go in through `raw_spice`
(ponytail: drop this once SpiceRack's X() accepts **params).
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs"))
from pdk_specs import get_pdk  # noqa: E402

import spicerack as ps  # noqa: E402

_KINDS = ("nfet", "pfet", "nfet_lvt", "pfet_lvt", "pfet_hvt")


def fet(sub, name, d, g, s, b, kind, W, L, nf=1, m=1, pdk=None):
    """One PDK MOSFET. kind in _KINDS; W (per instance) and L in um; m instances.
    FinFET PDKs (pdk.w_fin) round W to whole fins (NFIN) and carry m as fingers (NF).

    A W past the PDK's widest model bin (pdk.w_max) is split into equal parallel
    instances automatically. Multiplicity goes through pdk.mult_card, which scales the
    mismatch area as well as the current (a bare `m=` under-simulates Monte Carlo)."""
    pdk = pdk or get_pdk()
    if kind not in _KINDS:
        raise ValueError(f"kind {kind!r} not in {_KINDS}")
    model = getattr(pdk, kind)
    if not model:
        raise ValueError(f"{pdk.name} has no {kind} device")
    W = max(W, pdk.min_w)          # no PDK draws narrower (Philis widens it, pex then mismatches)
    if pdk.w_max and W > pdk.w_max:
        k = math.ceil(W / pdk.w_max)
        W, m = round(W / k, 3), m * k
    nfin = max(1, round(W / pdk.w_fin)) if pdk.w_fin else 0
    if pdk.w_fin:                  # FinFET: ESPice VA devices take no m=, fold it into NF
        nf, m = nf * m, 1
    extra = (f" nf={nf}" if nf > 1 else "") + (pdk.mult_card.format(m=m) if m > 1 else "")
    sub.raw_spice(pdk.fet_card.format(name=name, d=d, g=g, s=s, b=b, model=model,
                                      w=pdk.um(W), l=pdk.um(L), nfin=nfin, extra=extra))


def mim_cap(sub, name, p, n, C, pdk=None):
    """MIM capacitor of value C [F] as a square PDK device: side s solves
    ca*s^2 + 4*cp*s = C (area + perimeter). A value below the PDK's smallest drawable
    MIM (pdk.mim_min_side) is still emitted at its exact size — simulation is right —
    but warned about on stderr: it cannot be built as a MIM (use a MOM/fringe cap).
    A PDK without MIM (ASAP7) declares a `C` mim_card: an ideal C of the value, with
    mim_ff_um2 the MOM density its area is budgeted at."""
    pdk = pdk or get_pdk()
    ca, cp, c_ff = pdk.mim_ff_um2, pdk.mim_ff_um, C * 1e15
    s_um = c_ff / ca if not ca else \
        (-4 * cp + (16 * cp * cp + 4 * ca * c_ff) ** 0.5) / (2 * ca)
    if pdk.mim_min_side and s_um < pdk.mim_min_side:
        print(f"devices.mim_cap: {name} = {c_ff:.3g} fF needs a {s_um:.2f} um side, below "
              f"{pdk.name}'s {pdk.mim_min_side} um MIM minimum — not buildable as a MIM",
              file=sys.stderr)
    side = pdk.um(round(s_um, 2))
    sub.raw_spice(pdk.mim_card.format(name=name, p=p, n=n, model=pdk.mim_cap, w=side, l=side,
                                      c=f"{C:g}"))


def poly_res(sub, name, p, n, R, body, pdk=None, kind="res_poly"):
    """Poly resistor of value R [ohm] (fixed-width device, length from sheet R).
    `body` is the substrate/well terminal (usually the ground rail). kind="res_poly"
    (high sheet R, dense) or "res_poly_lotc" (low tempco, for references)."""
    pdk = pdk or get_pdk()
    w = getattr(pdk, kind + "_w")
    length = R / getattr(pdk, kind + "_ohm_sq") * w
    sub.raw_spice(pdk.res_card.format(name=name, p=p, n=n, b=body, model=getattr(pdk, kind),
                                      w=pdk.um(w), l=pdk.um(round(length, 2))))


def deck(*subs):
    """`.subckt ... .ends` text for each Subcircuit, in order — children first, top
    last (Philis takes the last .subckt as the top). No title, no `.end`."""
    c = ps.Circuit("deck")
    for sub in subs:
        c.subcircuit(sub)
    text = str(c)
    return text[text.index(".subckt"): text.rindex(".ends")].rstrip() + "\n" + \
        text[text.rindex(".ends"):].splitlines()[0] + "\n"
