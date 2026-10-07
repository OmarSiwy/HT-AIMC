"""Physics-robust architect (panel, round 1): score a design at TT and at SS / FF corners, then search for
the highest TT tok/s per die that passes N8's gate at EVERY corner with only measured-credit levers.

    python3 robust.py                 # corner search from the joint-search seeds -> robust.json, robust.result.json
    python3 robust.py --score d.json  # one design, every corner
    python3 robust.py --start d.json  # polish (coordinate descent) from one design -> robust.json
    python3 robust.py --selfcheck     # TT corner == search.evaluate exactly; SS/FF strictly harder

The core (model.py / search.py joint frame) scores at TT 25 C only (ARCH_METRIC). This file adds the cost
model the nodes lack: process/temperature/supply corners and the mismatch band, applied by patching the
constants every node reads (arch_eval.asap7.TABLE, the N9 measured tables) and by one extra error term on
n5.accuracy. Nothing in the nodes is edited. Labels: measured = ESPice ASAP7 tables in asap7_constants.json /
n9_circuits.py; derived = a law applied to them; projected = literature only.

Corner definitions (each factor is relative to TT 27 C, VDD 0.7 V):
  ss  SS devices, VDD -10 % (0.63 V), 100 C  -- the liberty SS sign-off point
      delay  x1.425  measured (n9 FO4_SIGNOFF: FO4 at SS 0.63 V 100 C / TT 0.7 V 27 C)
      Ron    x1.42   derived (Id_tt/Id_ss = 35.3/27.6 measured, x Ron(0.63)/Ron(0.7) = 1.11 measured)
      kT     x1.53   derived: T 373/300 K, and the -10 % rail folded in as signal^2 0.81 (thermal SNR ~ V^2/kT)
      leak   x0.64 (SS/TT, measured) on top of the 85 C tables N9 already uses for hold droop
  ff  FF devices, VDD 0.7 V, 85 C (fast-hot: leakage and hold-droop worst case)
      delay  x0.887  measured (fo4_delay_ps_ff / fo4_delay_ps)
      Ron    x0.777  derived (Id_tt/Id_ff measured)
      kT     x1.193  derived (358/300 K)
      leak   x1.51 (FF/TT, measured) on the 85 C hold tables, and x1.51 x 85C/27C on the static tables
  both corners also take the mismatch band end (no ASAP7 mismatch models exist):
      cap_match_sigma 0.5 -> 1.0 % at 1 fF and A_VT 1.3 -> 1.5 mV um (projected: literature band ends)
  supply term (every corner, new error class 'supply', fresh additive, N8 weight 0):
      eps = ripple x rejection; ripple 1 % rms of VDD at TT, 2 % at SS/FF (projected, 15s1/15s2);
      rejection 0.1 (row-drive rails and SAR reference buffered from ONE analog rail: ratiometric,
      27d7 / 27i1), 0.05 behind an LDO. SNR_supply = 1/eps^2 (a per-conversion gain error).
The DLL-replica clock tracks the corner (N9 lead), so tile and rail times scale with 'delay' (tok/s at SS is
reported as the floor a die at that corner delivers).
"""
import argparse
import contextlib
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from arch_eval import asap7, design, metric, search  # noqa: E402
from arch_eval.nodes import n5_array as n5, n9_circuits as n9  # noqa: E402

M = metric.METRICS
CORNERS = dict(
    tt=dict(delay=1.0, ron=1.0, kT=1.0, leak=1.0, leak85=1.0, mm=1.0, avt=1.3, ripple=0.01),
    ss=dict(delay=1.425, ron=1.42, kT=(373 / 300) / 0.81, leak=0.64 * 12.1, leak85=0.64, mm=2.0, avt=1.5, ripple=0.02),
    ff=dict(delay=0.887, ron=0.777, kT=358 / 300, leak=1.51 * 12.1, leak85=1.51, mm=2.0, avt=1.5, ripple=0.02),
)
# Levers whose credit was MEASURED on the proxy (quality_spotcheck.json: Hadamard format +0.06 %, noise inside
# budget). lv_protect_tensor's 6 dB was measured unrotated on one tensor and the harness could not emulate it.
MEASURED_LEVERS = ("g43_lossless", "lv_hadamard")
# Not SPICE-verifiable in ASAP7 (no BJT / resistor models, N9.md): excluded from the robust pick.
# Worst stacked corner must keep at least the margin the search winner keeps at TT (+0.26 dB): the pick is not
# allowed to sit on the gate edge at SS/FF any closer than r01 sits at TT.
MARGIN_FLOOR_DB = 0.25
UNVERIFIABLE = {"n9_circuits": ("ref_bandgap_ldo",)}


@contextlib.contextmanager
def corner(name):
    c = CORNERS[name]
    saved_t = {k: dict(e) for k, e in asap7.TABLE.items()}
    saved_n9 = {a: dict(getattr(n9, a)) for a in
                ("NMOS_R_VGS", "TG_RMAX", "IOFF85_N")}
    acc0, op0 = n5.accuracy, n9.op

    def scale(key, f):
        asap7.TABLE[key] = dict(asap7.TABLE[key], value=asap7.TABLE[key]["value"] * f)
    for key in list(asap7.TABLE):
        if key.startswith("fo4_delay_ps"):
            scale(key, c["delay"])
        elif key.startswith("switch_ron_ohm_per_fin") or key.startswith("tgate_ron"):
            scale(key, c["ron"])
        elif key.startswith("nfet_ileak_per_fin_nA"):
            scale(key, c["leak"])
    scale("kT_300K_J", c["kT"])
    scale("cap_match_sigma_pct_at_1fF", c["mm"])
    asap7.TABLE["avt_mV_um"] = dict(asap7.TABLE["avt_mV_um"], value=c["avt"])
    for a, f in (("NMOS_R_VGS", c["ron"]), ("TG_RMAX", c["ron"])):
        setattr(n9, a, {fl: tuple(x * f for x in v) for fl, v in saved_n9[a].items()})
    n9.IOFF85_N = {fl: v * c["leak85"] for fl, v in saved_n9["IOFF85_N"].items()}

    def accuracy(p, vdd, geo, arr, adc, fmt):
        out = dict(acc0(p, vdd, geo, arr, adc, fmt))
        rej = 0.05 if p.get("n9_ref") == "bandgap_ldo" else 0.1
        parts = dict(out["parts_db"], supply=n5._db(1 / (c["ripple"] * rej) ** 2))
        out.update(parts_db=parts, snr_db=-n5._db(sum(10 ** (-v / 10) for v in parts.values())))
        return out
    def op(p, vdd, clk_frac=1.0):     # n9 op is a ratio to its own TT tables: scale its outputs instead
        o = dict(op0(p, vdd, clk_frac))
        o.update(delay_scale=o["delay_scale"] * c["delay"], clk_GHz=o["clk_GHz"] / c["delay"],
                 leak_scale=o["leak_scale"] * c["leak"])
        return o
    n5.accuracy, n9.op = accuracy, op
    try:
        yield c
    finally:
        asap7.TABLE.clear()
        asap7.TABLE.update(saved_t)
        for a, v in saved_n9.items():
            setattr(n9, a, dict(v))
        n5.accuracy, n9.op = acc0, op0


search.PARAMS["cu_fF"] = sorted({*[v for v in search.PARAMS["cu_fF"] if v], 1.25, 1.5, 1.75, 2.5, 3.0}) + [None]
_SC = search.Scorer()     # its guards (tier, KV8, encoding x domain, option conditions, rotation, w area)


def guard(d):
    s = _SC(d)
    if s.get("pruned"):
        return s["pruned"]
    if s.get("kind") != "charge":   # time/current gain = a delay or a bias current: PVT-sensitive, and the corner
        return (f"robust: '{s.get('kind')}' array; its gain is a delay/bias, not a capacitor ratio (27i1, 27i5), "
                "and N9's corner-sensitive accuracy hooks are off on it (model hole)")
    if not search.admissible(d):
        return "search rule (PRUNE / gate policy)"
    if (d["nodes"].get("n8_quality") or search.mods()["n8_quality"].DEFAULT) not in MEASURED_LEVERS:
        return "robust: n8 lever credit not measured on the proxy"
    for nid, bad in UNVERIFIABLE.items():
        if (d["nodes"].get(nid) or search.mods()[nid].DEFAULT) in bad:
            return f"robust: {nid} option not SPICE-verifiable in ASAP7"
    return None


_MEMO = {}


def score(d, knobs=None):
    """-> {corner: metrics + margin_db}, plus 'why' (None = admissible) and 'min_margin_db'."""
    key = search.dkey(d)
    if key in _MEMO and knobs is None:
        return _MEMO[key]
    out = dict(why=guard(d))
    for cn in CORNERS:
        # N8's 1 dB die cushion ("p10 die and calibration drift over temperature") is what the SS/FF corners
        # model explicitly, so it is replaced there, not stacked; TT keeps it (the ARCH_METRIC score).
        dc = d if cn == "tt" else dict(d, params=dict(d["params"], q_die_margin_db=0.0))
        with corner(cn):
            try:
                s = search.evaluate(dc, knobs or metric.KNOBS, "joint")
            except Exception as e:  # noqa: BLE001
                s = dict({m: 0.0 for m in M}, margin_db=-99.0, errors=[repr(e)])
        out[cn] = dict({m: float(s[m]) for m in M}, margin_db=float(s["margin_db"]),
                       binding=s.get("binding"), snr_parts=(s.get("tile") or {}).get("snr_parts_db"),
                       B=(s.get("peak") or {}).get("B"), vdd=(s.get("peak") or {}).get("vdd"),
                       die_W=(s.get("peak") or {}).get("die_power_W"))
    out["min_margin_db"] = min(out[c]["margin_db"] for c in CORNERS)
    out["all_pass"] = all(out[c]["tok_s_die"] > 0 for c in CORNERS) and out["min_margin_db"] >= MARGIN_FLOOR_DB
    if knobs is None:
        _MEMO[key] = out
    return out


def order(r):
    """Admissible and gate-feasible at every corner first, then TT lexicographic, then worst-corner margin."""
    if r["why"]:
        return (-1,) + (0,) * 5
    if not r["all_pass"]:
        return (0, r["min_margin_db"], 0, 0, 0, 0)
    return (1,) + tuple(r["tt"][m] for m in M) + (r["min_margin_db"],)


def descend(state, passes=3, log=print):
    best = score(search.make(*state))
    for i in range(passes):
        changed = False
        for c in search.coords():
            for v in search.values(c, state):
                st = search.moved(state, c, v)
                r = score(search.make(*st))
                if order(r) > order(best):
                    state, best, changed = st, r, True
        log(f"  pass {i}: {order(best)[:3]} min margin {best['min_margin_db']:+.2f} dB ({len(_MEMO)} designs)")
        if not changed:
            break
    return state, best


def seeds():
    D = search.OUT / "designs"
    out = []
    for n in ("winner", "cf_n8_quality__lv_hadamard", "p08", "r03", "sens_gate_tighter"):
        f = D / f"{n}.json"
        if f.exists():
            dd = design.load(f)
            nodes = dict(dd["nodes"])
            if nodes.get("n8_quality") not in MEASURED_LEVERS:
                nodes.update(n8_quality="lv_hadamard", n4_formats="w8a8_lead")
            out.append((nodes, dict(dd["params"])))
    hw = dict(n4_formats="w8a8_lead", n8_quality="lv_hadamard", n7_dataflow="tdm_noc")
    for n9o in ("lead", "vt_lvt_logic"):
        for cu in (1.5, 2.0, 4.0):
            out.append((dict(hw, n9_circuits=n9o), dict(adc_bits=12, cu_fF=cu, kv_bits=8, k_dig=0, mcast=16,
                                                       rail_headroom=2.0, share_fins=32, buffer_MB=8)))
    return out


def baseline():
    """Systolic W8 KV8 (ppa.json PE, derived; literature PE, projected) under the same corner patches."""
    from arch_eval import baseline_systolic as bs
    out = {}
    for lit in (False, True):
        keep = bs.ppa
        if lit:
            bs.ppa = lambda: (dict(bs.LIT), dict.fromkeys(bs.LIT, bs.LIT_SRC))
        try:
            for cn in CORNERS:
                with corner(cn):
                    s = bs.evaluate(8, metric.knobs_for("arch", kv_bits=8))
                out[f"W8KV8_{'litPE' if lit else 'ppaPE'}_{cn}"] = {m: float(s[m]) for m in M}
        finally:
            bs.ppa = keep
    return out


def fmt_row(r, cn):
    x = r[cn]
    return f"{cn}: " + "  ".join(f"{m} {x[m]:.5g}" for m in M) + f"  margin {x['margin_db']:+.2f} dB"


def selfcheck():
    d = design.load(search.OUT / "designs/winner.json")
    plain = search.evaluate(d, metric.KNOBS, "joint")
    with corner("tt"):
        tt = search.evaluate(d, metric.KNOBS, "joint")
    assert abs(tt["tok_s_die"] - plain["tok_s_die"]) < 1e-6 * plain["tok_s_die"], "tt corner must not move tok/s"
    assert tt["margin_db"] <= plain["margin_db"] + 1e-9, "the supply term can only cost margin"
    r = score(d)
    assert r["ss"]["margin_db"] < r["tt"]["margin_db"] and r["ff"]["margin_db"] < r["tt"]["margin_db"]
    assert asap7.get("kT_300K_J") == 1.380649e-23 * 300.0 or asap7.label("kT_300K_J"), "constants restored"
    print("robust self-check PASS:", fmt_row(r, "tt"), "|", fmt_row(r, "ss"), "|", fmt_row(r, "ff"))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--score")
    ap.add_argument("--selfcheck", action="store_true")
    ap.add_argument("--start", help="polish from this design JSON instead of the seed list")
    a = ap.parse_args(argv)
    if a.selfcheck:
        return selfcheck()
    if a.score:
        r = score(design.load(a.score))
        print("why:", r["why"])
        for cn in CORNERS:
            print(fmt_row(r, cn), r[cn]["binding"])
        return
    best_st, best = None, None
    starts = seeds()
    if a.start:
        dd = design.load(a.start)
        starts = [(dd["nodes"], dd["params"])]
    for st in starts:
        print("seed", st)
        st2, r = descend(st)
        if best is None or order(r) > order(best):
            best_st, best = st2, r
    d = search.make(*best_st)
    out = dict(name="robust", frame="joint+corners", label="projected", nodes=d["nodes"], params=d["params"])
    (HERE / "robust.json").write_text(json.dumps(out, indent=1, sort_keys=True))
    D = search.OUT / "designs"
    ref = {n: score(design.load(D / f"{n}.json")) for n in ("winner", "cf_n8_quality__lv_hadamard", "p08")}
    (HERE / "robust.result.json").write_text(json.dumps(dict(robust=best, references=ref, baseline=baseline(),
                                                             corners=CORNERS, evaluated=len(_MEMO)),
                                                        indent=1, default=str))
    for cn in CORNERS:
        print(fmt_row(best, cn))


if __name__ == "__main__":
    main()
