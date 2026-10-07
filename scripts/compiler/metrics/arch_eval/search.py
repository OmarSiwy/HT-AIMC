"""Joint architecture search over every node's OPTIONS and SWEEP (round 1, 2026-10-05).

    python3 scripts/compiler/metrics/arch_eval/search.py            # full run -> ArchResearch/search/
    python3 scripts/compiler/metrics/arch_eval/search.py --score d.json [--frame joint|core|credit]
    python3 scripts/compiler/metrics/arch_eval/search.py --quick    # small beam, for a smoke run
    python3 scripts/compiler/metrics/arch_eval/search.py --selfcheck

Scorer frames (one design JSON, three readings; every number is projected):
  core    model.evaluate = cli.py. Only what the core contract carries.
  joint   core + the three hooks the node owners wrote but the core has not adopted:
          N9 evaluate_full (driver/reference/column-switch/clock energy and area, analog rail,
          droop/INL accuracy terms; charge-domain arrays only, N9's model scope), N4 tile_effects (true unit count, conversions per scale
          block, slice merge, input-side digital work), N8 rail_frac (weight MACs a lever moves
          to the digital rail are charged on the rail). RANKING FRAME: these are real costs.
  credit  joint + N2's hybrid relief (the analog noise weight of the low input planes,
          6.02 dB per digital plane) credited to the gate. N2/N4's claim; N8 has NOT adopted
          it, so a design that needs it is reported, flagged, never the strict winner.

Search: beam over single moves (node option or swept param), seeded from every node's lead and
DEFAULT. Infeasible designs are ordered by their best gate margin so the beam can climb out.
Pruned (logged, never silent): options a node's verdict or ARCH_METRIC rules out (PRUNE), n8
gate policies other than the G43 lossless gate (they are sensitivity rows, not design choices),
designs whose evaluation fell back to a default node (contract error), all-digital hybrids.
"""
import argparse
import json
import math
import sys
import time
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from arch_eval import ROOT, baseline_systolic, design, metric, model  # noqa: E402
from arch_eval.design import NODES  # noqa: E402

OUT = ROOT / "docs/src/content/Project/ArchResearch/search"
M = metric.METRICS

# ---- what the search may not pick, and why (each reason is printed into results.json) ---------
_ARCH = "ARCH_METRIC"
PRUNE = {
    "n1_system": {"resident": f"{_ARCH}: weights stream from HBM (user decision 2026-10-05)"},
    "n2_domain": {"digital_cim_ref": f"{_ARCH} scope: all-digital CIM is not analog/mixed IMC (N2 verdict)"},
    "n3_cell": {o: f"{_ARCH} constraint 2: no SRAM bitcells in the tile (N3 verdict)"
                for o in ("sram6t_binary_caps", "sram6t_mos_caps", "sram6t_c2c")},
    "n4_formats": dict(
        {o: "N4 verdict infeasible: fails the lossless format tier or range (N4.md)" for o in (
            "w8a8_lead_k16", "w8a8_lead_lsb4", "fp8_per_element_analog", "ternary_bitnet", "binary", "w3a8",
            "w2a8", "a6", "a4_rotated", "w4a4")},
        **{o: f"N4 verdict infeasible + {_ARCH} constraint 3 (no PWM inputs by default)"
           for o in ("a8_pwm", "a8_pwm_split_nibble")}),
    "n5_array": {o: "N5 verdict infeasible (settling / write bitline / as-quantized rho / coupling, N5.md)" for o in (
        "blk_diff_r256", "blk_diff_r256_wseg8", "blk_diff_r512_wseg16", "blk_diff_r1024_hier_wseg32",
        "blk_diff_r512_m6", "blk_diff_r1024_hier", "blk_diff_r4096_hier", "diff_r128c64", "se_r128c64",
        "pseudo_r128c64", "se_rot", "pseudo_rot", "blk_diff_unshielded")},
    "n6_readout": {o: "N6 verdict infeasible (N6.md)" for o in (
        "pipelined_shared", "null_sar_sky130_port", "sense_amp_1b")},
    "n8_quality": {"lv_resistive_ir": "N8: resistive domains only (n/a)", "lv_nvm_program": "N8: program-once NVM only (n/a)"},
    "n9_circuits": {o: "N9 verdict infeasible (N9.md)" for o in (
        "vt_slvt_all", "colsw_ground_slvt", "ref_ratiometric_decap", "amp_ota_integrator",
        "amp_twostage_integrator", "drv_sf_dac")},
    "n10_wildcards": {o: "N10 verdict infeasible (N10.md)" for o in (
        "dps48_strassen", "moe_experts", "cam_topk_kv", "iterative_refinement")},
}
_VDD = f"{_ARCH}: VDD in [0.45, 0.7] V; a supply rail above 0.7 V on ASAP7 thin oxide (reliability unchecked)"
PRUNE["n9_circuits"]["analog_rail_09"] = _VDD + ": analog rail 0.9 V"
PRUNE["n3_cell"]["gaincell_mos_r08"] = _VDD + ": 0.8 V cap rail (N3: needs a gate-stress check first)"
PRUNE["n3_cell"]["gaincell_mos_r08_vlo035"] = PRUNE["n3_cell"]["gaincell_mos_r08"]
GATE = "g43_lossless"            # N8's gate. Other gate policies are sensitivity rows only:
GATE_POLICIES = ("snr28_w4a8", "g_paper_28_38", "g40_lossless_lowA", "g46_lossless_highA", "g47_top1_97",
                 "g38_3pct", "g33_10pct", "g43_w4_acceptable", "bundle_lead_lowA")
GATE_STEPS = dict(looser=40.0 - 43.01, tighter=45.8 - 43.01)   # dB shift to N8's A-band ends (g40 / g46)

# swept params (None = the chosen options' own value); n9 vdd/clk are operating points inside the metric
PARAMS = dict(adc_bits=[None, 8, 9, 10, 11, 12, 13, 14], kv_bits=[None, 4, 8, 16], k_dig=[None, 0, 1, 2, 3, 4, 5],
              cu_fF=[None, 0.2, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0], mos_fins=[None, 4, 8, 16, 32, 128],
              share_fins=[None, 8, 16, 32], wire_x=[None, 1, 2, 4],
              ra_gain=[None, 4.0, 8.0, 16.0], v_exc_frac=[None, 0.25, 0.35, 0.43, 0.5],
              rail_headroom=[None, 0.5, 1.0, 1.25, 2.0], buffer_MB=[None, 2, 8, 32], mcast=[None, 1, 4, 8, 16],
              double_buffer=[None, False, True])
# Not swept: n5 rows/cols/adc_share/k_sigma. Each n5 option IS a geometry (26 of them) and some carry
# geometry-specific laws (exact_conv at R8, block-rho at its R); overriding rows under them built
# chimeras the n5 owner never priced (first run: blk_diff_r8_exact at rows 128 dropped the ADC term).
HYBRID_ONLY = ("k_dig",)        # N2's digital MSB planes exist only on the hybrid options
MIN_WEIGHT_UM2 = 0.1            # < ~4 ASAP7 6T bitcells per weight = a model hole (n4 x n2 rescale hit 0)

_MODS = {}


def mods():
    if not _MODS:
        ctx = model.Ctx(design.make())
        _MODS.update(ctx.mods)
    return _MODS


def allowed(nid):
    m = mods()[nid]
    out = [o for o in m.OPTIONS if o not in PRUNE.get(nid, {})]
    if nid == "n8_quality":
        out = [o for o in out if o not in GATE_POLICIES]
    return out


# ---- the scorer -----------------------------------------------------------------------------
def _ctx(d, knobs, frame):
    from arch_eval.nodes import n2_domain as n2, n4_formats as n4
    ctx = model.Ctx(d, knobs)
    if frame == "core":
        return ctx
    f = float(ctx.p.get("q_rail_macs_frac", 0.0) or 0.0)       # N8 hook: moved weight MACs go to the rail
    if f:
        wl, extra = ctx.wl, f * ctx.wl["weight_macs_per_token"]
        wl["att_macs_prefill"] += extra * wl["prompt"]
        wl["att_macs_decode"] += extra * wl["gen"]
        wl["att_macs_per_ctx"] += extra / (wl["ctx_decode_sum"] / wl["gen"])
        wl["weight_macs_per_token"] -= extra
    if ctx.mods["n4_formats"] is n4:                              # N4 hook as an n10-style tile transform
        n10 = ctx.mods["n10_wildcards"]
        ctx.mods["n10_wildcards"] = types.SimpleNamespace(
            apply=lambda p, t: n10.apply(p, n4.tile_effects(ctx, t)), OPTIONS=n10.OPTIONS,
            SWEEP=getattr(n10, "SWEEP", {}), DEFAULT=n10.DEFAULT)
    if frame == "credit" and is_hybrid(d["nodes"]) and int(ctx.p.get("k_dig", 0) or 0) + int(ctx.p.get("k_wbits", 0) or 0):
        planes = int(ctx.call("n4_formats", "fmt")["input_planes"])
        ctx.p["q_credit_db"] = ctx.p.get("q_credit_db", 0.0) + n2.relief_db(ctx.p, planes)
    return ctx


def evaluate(d, knobs=None, frame="joint"):
    """-> score dict (metric.score keys) + margin_db (best gate margin over operating points),
    kind (n2 array kind), errors. Mirrors model.evaluate; the N9 hook patches model.tile."""
    from arch_eval.nodes import n9_circuits as n9
    knobs = dict(knobs or metric.KNOBS)
    orig = model.tile
    ctx = _ctx(d, knobs, frame)
    if frame != "core" and ctx.mods["n9_circuits"] is n9 and "n9_amp" in ctx.p:
        def tile(c, vdd, clk):          # = n9.evaluate_full's wrapper, on our ctx
            if not getattr(c, "_n9", False):
                call = c.call

                def routed(nid, fn, *a):
                    if (nid, fn) in n9.ANALOG_FNS:
                        a = (n9.analog_vdd(c.p, a[0]),) + a[1:]
                    out = call(nid, fn, *a)
                    if (nid, fn) == ("n2_domain", "array") and out.get("kind", "charge") != "charge":
                        c._n9_off = True      # N9's laws are bottom-plate drive / column-switch laws of the
                    if getattr(c, "_n9_off", False):   # charge array; on time/current kinds they are a model
                        return out                     # hole (drv_pwm cut a time array's energy 6x)
                    if (nid, fn) == ("n2_domain", "array"):
                        va, fmt, cell, rows = a
                        geo = call("n5_array", "geometry")
                        phys = (geo["cols"] + geo["checksum"]) * fmt["slices"]
                        out = n9._arr_fix(c.p, va, dict(out, c_row_fF=n9._row_c_fF(c.p, out, cell, phys)), fmt, rows)
                    elif (nid, fn) == ("n5_array", "accuracy"):
                        out = n9._acc_fix(c.p, *a, out)
                    return out
                c.call, c._n9 = routed, True
            t = orig(c, vdd, clk)
            return t if getattr(c, "_n9_off", False) else n9.plumb(c.p, t)
        model.tile = tile
    try:
        pts, dies = model.operating_points(ctx)
    finally:
        model.tile = orig
    s = metric.score(pts, ctx.knobs)
    s["errors"] = list(ctx.errors)
    s["margin_db"] = max((t["quality"].get("margin_db", -99.0) if t["quality"].get("fmt_ok", True)
                          and t["quality"].get("clip_ok", True) else -99.0 for t, _, _ in dies.values()),
                         default=-99.0)
    s["kind"] = next(iter(dies.values()))[0]["arr"].get("kind", "charge") if dies else "?"
    t0 = next(iter(dies.values()))[0] if dies else None     # guard facts, feasible or not
    s["g"] = dict(tier=t0["fmt"].get("tier", "lossless"), enc=t0["fmt"].get("enc"),
                  w_ok=t0["area_um2_parts"]["weights"] >= MIN_WEIGHT_UM2 * t0["rows"] * t0["cols"]) if t0 else {}
    pk = s["peak"]
    if pk:
        t, dd, plan = dies[(pk["vdd"], pk["clk_frac"])]
        s.update(tile=t, die=dd, plan=plan, binding=dict(pk["binding"], concurrency=model.why_b(ctx, pk, pts)))
    s["p"] = ctx.p
    return s


# ---- state, moves, ordering -------------------------------------------------------------------
def make(nodes, params):
    """Design from a search state. Imposed (an option's own conditions, which the core ignores):
    n8 lever 'requires' that are params (KV8, rows, operand rho), n5 option 'score_params' (e.g. r8_exact's
    48.7 dB per-conversion target). '_gate_shift' (sensitivity) moves the effective target."""
    nodes = {k: v for k, v in nodes.items() if v is not None}
    params = {k: v for k, v in params.items() if v is not None}
    m8, m5 = mods()["n8_quality"], mods()["n5_array"]
    o8 = m8.OPTIONS.get(nodes.get("n8_quality", m8.DEFAULT), {})
    o5 = m5.OPTIONS.get(nodes.get("n5_array", m5.DEFAULT), {})
    req = o8.get("requires", {})
    params.update({k: req[k] for k in ("kv_bits", "rows") if k in req})
    if "rho" in req:                     # the lever's operand statistic, as N8's own harness applies it
        params.update(rho_mode="fixed", rho=req["rho"])
    params.update(o5.get("score_params") or {})
    shift = params.pop("_gate_shift", None)
    if shift:
        params["q_snr_target_db"] = params.get("q_snr_target_db", o8.get("params", {}).get("q_snr_target_db", 43.01)) + shift
    return design.make(nodes, params)


def option_conditions(d, p):
    """None, or why the design breaks a chosen option's own stated conditions (n5 score_fmts/score_bits)."""
    m5, m4 = mods()["n5_array"], mods()["n4_formats"]
    o5 = m5.OPTIONS.get(d["nodes"].get("n5_array", m5.DEFAULT), {})
    n4 = d["nodes"].get("n4_formats", m4.DEFAULT)
    if o5.get("score_fmts") and n4 not in o5["score_fmts"]:
        return f"n5 option needs n4 in {o5['score_fmts']} (its exact-conversion law), got {n4}"
    if o5.get("score_bits") and int(p.get("adc_bits", 0)) not in o5["score_bits"]:
        return f"n5 option needs adc_bits in {o5['score_bits']}, got {p.get('adc_bits')}"
    m8 = mods()["n8_quality"]
    if m8.OPTIONS.get(d["nodes"].get("n8_quality", m8.DEFAULT), {}).get("requires", {}).get("rot") and not p.get("f_rot"):
        return "n8 lever requires a rotated (Hadamard) format; the n4 format has f_rot False (credit without the rotation)"
    return None


def dkey(d):
    return json.dumps([d["nodes"], d["params"]], sort_keys=True)


class Scorer:
    """Memoized evaluate() + the search ordering. Every scored design is kept (for the Pareto set)."""

    def __init__(self, knobs=None, frame="joint", kv_min=8):
        self.knobs, self.frame, self.memo, self.n = dict(knobs or metric.KNOBS), frame, {}, 0
        self.kv_min = kv_min

    def __call__(self, d):
        k = dkey(d)
        if k not in self.memo:
            self.n += 1
            try:
                s = evaluate(d, self.knobs, self.frame)
            except Exception as e:  # noqa: BLE001  (a node law out of its domain at this point)
                s = dict(tok_s_die=0.0, tops_w=0.0, tok_w=0.0, tok_j=0.0, peak=None, margin_db=-99.0,
                         errors=[f"raised {type(e).__name__}: {e}"], kind="?", p={})
            why = None
            errs = [e for e in s["errors"] if not e.startswith("VDD ")]   # "no tile fits at VDD x" is not an error
            if errs:
                why = "contract error / node fallback: " + errs[0][:160]
            elif s.get("g", {}).get("tier", "lossless") != "lossless":
                why = (f"N8 G1: n4 format tier '{s['g']['tier']}' under the lossless gate "
                       "(the gate checks only wbits >= 8; LNS6 stores 6 b at +13 % proxy PPL)")
            elif s.get("g", {}).get("enc") in ("amp", "nib_amp", "thermo") and s["kind"] != "charge":
                why = (f"n4 '{s['g']['enc']}' input encoding is a row C-DAC on bottom plates (N4 law 8): "
                       f"charge arrays only, here on a '{s['kind']}' array")
            elif option_conditions(d, s["p"]):
                why = option_conditions(d, s["p"])
            elif self.kv_min and int(s["p"].get("kv_bits", 16) if self.knobs.get("kv_bits") in (0, None)
                                     else self.knobs["kv_bits"]) < self.kv_min:
                why = f"N8 gate: KV{s['p'].get('kv_bits')} is the acceptable tier (QServe), not lossless (lv_kv8)"
            elif s["kind"] == "digital":
                why = f"{_ARCH} scope: every input plane digital (digital CIM)"
            elif s.get("g") and not s["g"]["w_ok"]:
                why = "model hole: weight area below 0.1 um2 per weight (node rescale collapsed it)"
            s["pruned"] = why
            self.memo[k] = (d, s)
        return self.memo[k][1]

    @staticmethod
    def order(s):
        if s.get("pruned"):
            return (-1, 0, 0, 0, 0)
        if s["tok_s_die"] > 0:
            return (1,) + tuple(s[m] for m in M)
        return (0, s.get("margin_db", -99.0), 0, 0, s.get("tok_j", 0.0))


def coords():
    return [("node", n) for n in NODES] + [("param", p) for p in PARAMS]


def values(c, state=None):
    if c[0] == "node":
        return allowed(c[1])
    if c[1] in HYBRID_ONLY and state is not None and not is_hybrid(state[0]):
        return [None]
    return PARAMS[c[1]]


def is_hybrid(nodes):
    m = mods()["n2_domain"]
    o = m.OPTIONS.get(nodes.get("n2_domain") or m.DEFAULT, {}).get("params", {})
    return bool(o.get("k_dig") or o.get("k_wbits"))


def moved(state, c, v):
    nodes, params = dict(state[0]), dict(state[1])
    (nodes if c[0] == "node" else params)[c[1]] = v
    return nodes, params


def descend(sc, state, frozen=(), passes=4):
    """Coordinate descent: per coordinate take the best value, until a full pass changes nothing."""
    best = sc(make(*state))
    for _ in range(passes):
        changed = False
        for c in coords():
            if c in frozen:
                continue
            for v in values(c, state):
                st = moved(state, c, v)
                s = sc(make(*st))
                if sc.order(s) > sc.order(best):
                    state, best, changed = st, s, True
        if not changed:
            break
    return state, best


def beam(sc, seeds, width=6, iters=8, log=print):
    pool = {dkey(make(*st)): st for st in seeds}
    front = sorted(pool.values(), key=lambda st: sc.order(sc(make(*st))), reverse=True)[:width]
    for it in range(iters):
        cand = dict((dkey(make(*st)), st) for st in front)
        for st in front:
            for c in coords():
                for v in values(c, st):
                    s2 = moved(st, c, v)
                    cand.setdefault(dkey(make(*s2)), s2)
        new = distinct(sc, cand.values(), width)
        top = sc(make(*new[0]))
        log(f"  beam iter {it}: {sc.n} evals, top {sc.order(top)[:3]}")
        if [dkey(make(*s)) for s in new] == [dkey(make(*s)) for s in front]:
            break
        front = new
    return front


def distinct(sc, states, n):
    """Top-n states by order, one per distinct score (equivalent designs waste beam width)."""
    out, seen = [], set()
    for st in sorted(states, key=lambda st: (sc.order(sc(make(*st))), -len(dkey(make(*st)))), reverse=True):
        o = tuple(round(x, 6) for x in sc.order(sc(make(*st))))
        if o not in seen:
            seen.add(o)
            out.append(st)
        if len(out) == n:
            break
    return out


def seeds():
    from arch_eval.nodes import n10_wildcards as n10
    out = [({}, {})] + [({}, dict(adc_bits=b)) for b in (10, 11, 12, 13, 14)]
    out += [({}, dict(adc_bits=b, k_dig=4, kv_bits=8)) for b in (12, 14)]
    out += [(dict(n4_formats="w8a8_lead_amp", n2_domain="charge_rail", n3_cell="gaincell_mos_caps"),
             dict(adc_bits=12, kv_bits=8, mos_fins=32)),                                   # N5 lead stack
            (dict(n2_domain="charge_rail", n6_readout="sar_vtc_fine"), dict(kv_bits=8, k_sigma=16.0, adc_bits=13)),  # N9
            (dict(n5_array="blk_diff_r16_c256_s4" if "blk_diff_r16_c256_s4" in mods()["n5_array"].OPTIONS
                  else "blk_diff_r16_c256_s8"), dict(adc_bits=12, cu_fF=1.0, kv_bits=8))]  # N5 robust fallback
    out += [(dict(c.get("nodes") or {}), dict(c.get("params") or {})) for c in n10.CANDIDATES.values()]
    return out


# ---- reporting --------------------------------------------------------------------------------
def row(sc, st, name, kind="design"):
    """Score summary + a design file the CLI can score (designs/<name>.json)."""
    d = make(*st)
    d["name"] = name
    s = sc(d)
    (OUT / "designs").mkdir(parents=True, exist_ok=True)
    path = OUT / "designs" / f"{name}.json"
    design.dump(dict(d, frame=sc.frame, label="projected"), path)
    t, pk = s.get("tile"), s.get("peak")
    ch = {n: v for n, v in d["nodes"].items()}
    summ = ", ".join(f"{n.split('_')[0]}={v}" for n, v in ch.items()) or "all node DEFAULTs"
    if d["params"]:
        summ += "; " + ", ".join(f"{k}={v}" for k, v in sorted(d["params"].items()))
    if t:
        summ += (f" | tile {t['rows']}x{t['cols']}x{t['slices']}, {t['e_pass_J'] / t['macs_per_pass'] * 1e15:.3g} fJ/MAC, "
                 f"SNR {t['quality'].get('snr_eff_db', t['snr_db']):.1f} dB (margin {t['quality']['margin_db']:+.2f}), "
                 f"B {pk['B']}, VDD {pk['vdd']}, binding {s['binding']}")
    elif s.get("pruned"):
        summ += f" | PRUNED: {s['pruned']}"
    else:
        summ += f" | infeasible (best gate margin {s['margin_db']:+.2f} dB)"
    return dict(name=name, design_file=str(path.relative_to(ROOT)), label=f"projected ({sc.frame} frame)",
                summary=summ, **{m: round(float(s[m]), 4) for m in M})


def admissible(d):
    """Rule check (PRUNE + gate policies). Separate from Scorer.pruned (model holes) so a
    counterfactual can still optimize around a rule-pruned option and report where it leads."""
    return all((d["nodes"].get(n) or mods()[n].DEFAULT) in allowed(n) for n in NODES)


def ranked_states(sc, n, feasible=True, by_nodes=False):
    """Top-n admissible states. by_nodes: one per distinct node-option tuple (params ignored), so
    the list shows different architectures instead of one design with tweaked knobs."""
    good = [(d, s) for d, s in sc.memo.values() if not s["pruned"] and admissible(d)
            and (s["tok_s_die"] > 0 or not feasible)]
    sts = [(d["nodes"], d["params"]) for d, _ in good]
    if not by_nodes:
        return distinct(sc, sts, n)
    out, seen = [], set()
    for st in distinct(sc, sts, len(sts)):
        k = tuple(st[0].get(nid) or mods()[nid].DEFAULT for nid in NODES)
        if k not in seen:
            seen.add(k)
            out.append(st)
        if len(out) == n:
            break
    return out


def front(items):
    """4-metric Pareto front of (key, score) items. Sorted lexicographically descending, a point can
    only be dominated by one before it, so this is O(n x |front|) (metric.pareto is O(n^2))."""
    out = []
    for k, s in sorted(items, key=lambda ks: tuple(ks[1][m] for m in M), reverse=True):
        v = tuple(s[m] for m in M)
        if not any(all(a >= b for a, b in zip(f, v)) and f != v for f, _, _ in out) and v not in {f for f, _, _ in out}:
            out.append((v, k, s))
    return out


def pareto_states(sc, cap=40):
    good = [(dkey(d), s) for d, s in sc.memo.values() if not s["pruned"] and admissible(d) and s["tok_s_die"] > 0]
    f = front(good)
    sts = [(sc.memo[k][0]["nodes"], sc.memo[k][0]["params"]) for _, k, _ in f]   # tok/s descending
    step = max(1, -(-len(sts) // cap))       # ponytail: evenly thinned to `cap` rows, full size reported
    return sts[::step], len(f)


def baselines():
    out = {}
    for cond in ("arch", "sohu"):
        for wb in ((4, 8) if cond == "arch" else (8,)):
            for kv in ((16, 8) if cond == "arch" else (8,)):
                kn = metric.knobs_for(cond, **({"kv_bits": kv} if cond == "arch" else {}))
                s = baseline_systolic.evaluate(wb, kn)
                out[f"{cond}_W{wb}_KV{kv}"] = dict({m: round(float(s[m]), 4) for m in M}, binding=s.get("binding"),
                                                    die_mm2=kn["die_mm2"], pe_source=sorted(set(s["pe_source"].values())))
                # same baseline on the literature PE numbers (projected), as the deferred-synthesis frame
                keep = baseline_systolic.ppa
                baseline_systolic.ppa = lambda: (dict(baseline_systolic.LIT), dict.fromkeys(baseline_systolic.LIT,
                                                                                         baseline_systolic.LIT_SRC))
                try:
                    s = baseline_systolic.evaluate(wb, kn)
                finally:
                    baseline_systolic.ppa = keep
                out[f"{cond}_W{wb}_KV{kv}_litPE"] = dict({m: round(float(s[m]), 4) for m in M},
                                                          binding=s.get("binding"), die_mm2=kn["die_mm2"],
                                                          pe_source=["projected: " + baseline_systolic.LIT_SRC])
    return out


def ratios(w, b):
    return {m: round(w[m] / b[m], 4) if b[m] else None for m in M}


def run(width=6, iters=10, cf_passes=2, quick=False, log=print):
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    res = dict(date=time.strftime("%Y-%m-%d %H:%M"), label="every number projected (laws + measured ASAP7/sky130 "
               "anchors + literature constants; nothing here is silicon or post-layout)",
               prune_rules={n: v for n, v in PRUNE.items()}, gate=GATE, gate_policies_excluded=list(GATE_POLICIES),
               params_swept={k: v for k, v in PARAMS.items()}, frames=__doc__.split("Search:")[0].strip())
    # 1. main search, ranking frame
    sc = Scorer(frame="joint")
    log("== joint-frame beam")
    front = beam(sc, seeds(), width, iters, log)
    for st in front:                                   # polish: coordinate descent from every beam state
        descend(sc, st, passes=3)
    win = ranked_states(sc, 1)[0]
    res["winner_beam"] = row(sc, win, "winner_beam")
    pruned = {}
    for _, s in sc.memo.values():
        if s["pruned"]:
            k = s["pruned"][:110]
            pruned[k] = pruned.get(k, 0) + 1
    res["pruned_counts"] = pruned
    res["evals_main"] = sc.n
    log(f"   beam winner {res['winner_beam']['tok_s_die']:.0f} tok/s ({sc.n} evals, {time.time() - t0:.0f} s)")
    w0 = res["winner_beam"]["tok_s_die"]
    # 2. the other frames (same seeds + the joint winner)
    res["frames_best"] = {}
    for fr in ("core", "credit"):
        s2 = Scorer(frame=fr)
        f2 = beam(s2, seeds() + [win], max(2, width // 2), iters if not quick else 2, log)
        res["frames_best"][fr] = dict(best=row(s2, f2[0], f"frame_{fr}_best"),
                                      joint_winner_here=row(s2, win, f"frame_{fr}_winner"))
    # 3. counterfactuals: every node x every option (pruned ones too, flagged)
    log("== counterfactuals")
    cfs = []
    for nid in NODES:
        m = mods()[nid]
        for opt in list(m.OPTIONS)[:2 if quick else None]:
            c = ("node", nid)
            starts = [moved(win, c, opt)]
            if nid == "n8_quality" and m.OPTIONS[opt].get("requires", {}).get("rot"):
                starts.append(moved(starts[0], ("node", "n4_formats"), "w8a8_lead"))   # the rotation it needs
            inmemo = [(d["nodes"], d["params"]) for d, s in sc.memo.values()
                      if (d["nodes"].get(nid) or m.DEFAULT) == opt and not s["pruned"] and s["tok_s_die"] > 0
                      and admissible(dict(d, nodes=dict(d["nodes"], **{nid: None})))]
            if inmemo:
                starts.append(distinct(sc, inmemo, 1)[0])
            best_st, best = None, None
            for st in starts:
                st2, b = descend(sc, st, frozen=(c,), passes=cf_passes)
                if best is None or sc.order(b) > sc.order(best):
                    best_st, best = st2, b
            why = PRUNE.get(nid, {}).get(opt) or ("N8 gate policy, not a design lever (sensitivity row)"
                                                   if nid == "n8_quality" and opt in GATE_POLICIES else None)
            r = row(sc, best_st, f"cf_{nid}__{opt}")
            cfs.append(dict(node=nid, option=opt, best=r, pruned_by_rule=why,
                            delta_tok_s_pct=0.0))
        log(f"   {nid}: {len(m.OPTIONS)} options, {sc.n} evals, {time.time() - t0:.0f} s")
    # the counterfactual descents explore too: the winner is the best admissible design of all of it
    win = ranked_states(sc, 1)[0]
    res["winner"] = row(sc, win, "winner")
    res["winner_found_after_beam"] = res["winner"]["tok_s_die"] > w0 * (1 + 1e-9)
    for c in cfs:
        c["delta_tok_s_pct"] = round(100 * (c["best"]["tok_s_die"] / res["winner"]["tok_s_die"] - 1), 2)
    res["counterfactuals"] = cfs
    res["ranked"] = [row(sc, st, f"r{i + 1:02d}") for i, st in enumerate(ranked_states(sc, 15, by_nodes=True))]
    res["ranked_same_arch"] = [row(sc, st, f"k{i + 1:02d}") for i, st in enumerate(ranked_states(sc, 5))]
    pst, res["pareto_size"] = pareto_states(sc)
    res["pareto"] = [row(sc, st, f"p{i + 1:02d}") for i, st in enumerate(pst)]
    res["evals_after_cf"] = sc.n
    # 4. baseline
    res["baseline"] = baselines()
    # 5. sensitivity: re-optimize from the top designs under each knob change
    log("== sensitivity")
    tops = ranked_states(sc, 2 if quick else 5)
    sens = {}
    cases = dict(die_50=dict(die_mm2=50.0), die_400=dict(die_mm2=400.0), hbm_x0p5=dict(hbm_Bps=0.5 * 819e9),
                 hbm_x2=dict(hbm_Bps=2 * 819e9), floor_10=dict(stream_floor_tok_s=10.0),
                 floor_50=dict(stream_floor_tok_s=50.0))
    for name, kn in list(cases.items()) + [(f"gate_{k}", v) for k, v in GATE_STEPS.items()]:
        knobs = dict(metric.KNOBS, **kn) if isinstance(kn, dict) else dict(metric.KNOBS)
        s3 = Scorer(knobs=knobs, frame="joint")
        sts = tops if isinstance(kn, dict) else [(n, dict(p, _gate_shift=kn)) for n, p in tops]
        fixed_st = win if isinstance(kn, dict) else (win[0], dict(win[1], _gate_shift=kn))
        for st in [fixed_st] + sts:
            descend(s3, st, passes=cf_passes)
        best = ranked_states(s3, 1)
        b = row(s3, best[0], f"sens_{name}") if best else None
        w = row(s3, fixed_st, f"sens_{name}_winner")
        bl = baseline_systolic.evaluate(8, dict(knobs, kv_bits=8))
        sens[name] = dict(knobs=kn, best=b, winner_fixed=w, baseline_W8_KV8={m: round(float(bl[m]), 4) for m in M},
                          winner_changes=bool(b and dkey(make(*best[0])) != dkey(make(*fixed_st))))
        log(f"   {name}: best {b['tok_s_die'] if b else 0:.0f}, winner {w['tok_s_die']:.0f}")
    res["sensitivity"] = sens
    # 6. Sohu conditions: winner as-is and re-tuned
    log("== sohu")
    s4 = Scorer(knobs=metric.knobs_for("sohu"), frame="joint")
    for st in tops:
        descend(s4, st, passes=cf_passes)
    sb = ranked_states(s4, 1)
    res["sohu"] = dict(die_mm2=metric.sohu_area(), winner=row(s4, win, "sohu_winner"),
                       best=row(s4, sb[0], "sohu_best") if sb else None)
    res["seconds"] = round(time.time() - t0)
    return res


def selfcheck():
    """front() == metric.pareto on random points (ties included); guards fire on known holes."""
    import random
    rnd = random.Random(0)
    pts = [dict(zip(M, (rnd.choice((1, 2, 3)) for _ in M))) for _ in range(300)]
    got = {tuple(s[m] for m in M) for _, _, s in front([(i, s) for i, s in enumerate(pts)])}
    assert got == {tuple(s[m] for m in M) for s in metric.pareto(pts)}, "front() != metric.pareto"
    sc = Scorer()
    holes = {"LNS6 acceptable tier": ({"n4_formats": "lns6_linear_tile"}, {"adc_bits": 11, "kv_bits": 8}),
             "KV4": ({"n8_quality": "lv_protect_tensor"}, {"kv_bits": 4, "adc_bits": 12}),
             "rot lever on norot format": ({"n8_quality": "lv_hadamard", "n4_formats": "w8a8_lead_norot"}, {}),
             "amp input on a time array": ({"n2_domain": "time_delay", "n4_formats": "w8a8_lead_amp"}, {})}
    for why, st in holes.items():
        assert sc(make(*st))["pruned"], why
    print("search selfcheck PASS")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--score", help="score one design JSON (all frames unless --frame)")
    ap.add_argument("--frame", choices=("core", "joint", "credit"))
    ap.add_argument("--conditions", default="arch", choices=sorted(metric.CONDITIONS))
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--selfcheck", action="store_true")
    a = ap.parse_args(argv)
    if a.selfcheck:
        return selfcheck()
    if a.score:
        d = design.load(a.score)
        for fr in ([a.frame] if a.frame else ("core", "joint", "credit")):
            s = evaluate(d, metric.knobs_for(a.conditions), fr)
            print(f"{fr:<7} " + "  ".join(f"{m} {s[m]:.5g}" for m in M) + f"  margin {s['margin_db']:+.2f} dB"
                  + (f"  binding {s.get('binding')}" if s.get("binding") else ""))
        return
    res = run(width=3 if a.quick else 6, iters=3 if a.quick else 10, cf_passes=1 if a.quick else 2, quick=a.quick)
    (OUT / "results.json").write_text(json.dumps(res, indent=1, default=str))
    print(f"wrote {OUT / 'results.json'} ({res['seconds']} s)")


if __name__ == "__main__":
    main()
