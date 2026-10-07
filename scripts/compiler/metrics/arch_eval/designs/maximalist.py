"""Maximalist architect: score a design JSON at the system level the core cannot express.

The core (model.system_point) runs one die, lockstep waves (prefill, then 128 decode steps).
At the search winner that schedule leaves the HBM idle during prefill and the rail/tiles idle
during decode, and one die's 24 GB holds the 8 GB weight copy plus only 368 streams of KV8.
This file adds the two system levers the maximalist design uses, both from existing node code:

  1. tensor-parallel group of nd dies (metric knob system_dies; one HBM stack per die). The
     weight copy is split nd ways, so KV capacity per die rises from 24 - 8 to 24 - 8/nd GB and
     each decode sweep's weight bytes are shared by nd x more streams. The core treats the
     group as ideal (no d2d cost); here the all-reduce bytes and energy are charged with
     n1_system.tp_d2d (2 all-reduces per layer, 16-bit, ring 2(nd-1)/nd) and its link ceiling
     is checked against 2 TB/s.
  2. continuous batching with chunked prefill riding the decode weight sweeps (n1_system.
     continuous / cb_score: Sarathi-Serve-style, two micro-batch groups so rail attention
     overlaps the tiles; activation spill charged; power over the cap throttled).

Tiles are the search's JOINT frame (N4/N8/N9 hooks), captured from search.evaluate.

    python3 designs/maximalist.py [design.json ...]      # score in all frames
    python3 designs/maximalist.py --scan DIR             # best design file in DIR under the levers
    python3 designs/maximalist.py --selfcheck

Every number this prints is projected (laws on projected/measured-sky130/measured-ASAP7-device
constants, as the search's are). ponytail: the CB law is N1's steady-state model, not an
event-driven scheduler simulation; upgrade if the decision rests on the last 5 %.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from arch_eval import baseline_systolic, design, metric, model, search  # noqa: E402
from arch_eval.nodes import n1_system as n1  # noqa: E402

M = ("tok_s_die", "tops_w", "tok_w", "tok_j")
ETA = 0.85   # N7's realistic overlap efficiency (N7.md lead); the CB law is its eta = 1 ceiling


def _joint(d, knobs):
    """search.evaluate (joint frame) + the ctx and (VDD, clk) grid it built."""
    got = {}
    orig = model.operating_points

    def cap(ctx):
        pts, dies = orig(ctx)
        got.update(ctx=ctx, keep=dies)
        return pts, dies
    model.operating_points = cap
    try:
        s = search.evaluate(d, knobs, "joint")
    finally:
        model.operating_points = orig
    return s, got.get("ctx"), got.get("keep", {})


def _with_d2d(c, knobs, nd, kv_bits):
    """Charge the TP all-reduce on a CB point (per die, per token); re-throttle at the cap."""
    if nd <= 1 or not c["tok_s_die"]:
        return dict(c, d2d_uJ_tok=0.0, d2d_ceiling=float("inf"))
    tp = n1.tp_d2d(knobs, nd, kv_bits)
    X = c["tok_s_die"]
    e_die = c["die_power_W"] / X + tp["e_J_per_token"]
    e_tot = 1 / c["tok_w"] + tp["e_J_per_token"]
    cap = knobs["power_cap_W_per_mm2"] * knobs["die_mm2"]
    X = min(X, tp["ceiling_tok_s"], cap / e_die)        # ponytail: static treated as per-token here
    return dict(c, tok_s_die=X, die_power_W=e_die * X, tops_w=c["tops_w"] * (c["die_power_W"] / c["tok_s_die"]) / e_die,
                tok_w=1 / e_tot, d2d_uJ_tok=tp["e_J_per_token"] * 1e6, d2d_ceiling=tp["ceiling_tok_s"])


def score(d, nd=1, cb=True, conditions="arch", **kn):
    """-> dict(lock=lockstep joint score, cb=continuous-batching point (or None), best=the 4 metrics)."""
    knobs = metric.knobs_for(conditions, **kn)
    knobs["system_dies"] = nd
    s, ctx, keep = _joint(d, knobs)
    lock = {m: float(s[m]) for m in M}
    out = dict(lock=lock, margin_db=s["margin_db"], binding_lock=s.get("binding"), cb=None, best=dict(lock))
    if not cb or not s.get("peak") or ctx is None:
        return out
    kv = int(ctx.p.get("kv_bits", 8))
    c = n1.cb_score(ctx, keep, knobs)
    if not c["tok_s_die"]:
        return out
    c = _with_d2d(c, knobs, nd, kv)
    c["tok_j"] = max(c["tok_j"], lock["tok_j"])          # tok/J: best over any operating point/scheduler
    out["cb"] = c
    if c["tok_s_die"] > lock["tok_s_die"]:
        out["best"] = {m: float(c[m]) for m in M}
    return out


def baseline(nd=1, cb=True, wbits=8, pe="ppa", conditions="arch", params=None, **kn):
    """Systolic baseline (digital/sysreference model) under the same system levers.
    pe='ppa': ppa.json PE (derived); pe='lit': literature PE (projected)."""
    knobs = metric.knobs_for(conditions, **kn)
    knobs.update(system_dies=nd, kv_bits=8)
    pev = baseline_systolic.LIT if pe == "lit" else baseline_systolic.ppa()[0]
    ctx = model.Ctx(design.make({"n1_system": "streaming"}, dict(params or {}, double_buffer=True)), knobs)
    pts, keep = [], {}
    for v in [x for x in model.SWEEP_VDD if knobs["vdd_min"] <= x <= knobs["vdd_max"]]:
        for f in model.SWEEP_CLK:
            t = baseline_systolic.tile(ctx, v, f, wbits, pev)
            keep[(v, f)] = (t, model.die(ctx, t), dict(mode="streaming", dies=1))
            pts += model.b_sweep(ctx, *keep[(v, f)])
    s = metric.score(pts, knobs)
    lock = {m: float(s[m]) for m in M}
    out = dict(lock=lock, best=dict(lock), cb=None)
    if cb:
        c = _with_d2d(n1.cb_score(ctx, keep, knobs), knobs, nd, 8)
        c["tok_j"] = max(c["tok_j"], lock["tok_j"])
        out["cb"] = c
        if c["tok_s_die"] > lock["tok_s_die"]:
            out["best"] = {m: float(c[m]) for m in M}
    return out


def lockstep_spill(d, **kn):
    """The core's lockstep score with N1's activation-spill law charged (the core charges none):
    a prefill wave makes every weight chunk meet B x P vectors, whose inputs overflow the rail
    buffer. Same B and operating point as the core's peak (not re-optimized: a lower bound)."""
    knobs = metric.knobs_for("arch", **kn)
    s, ctx, keep = _joint(d, knobs)
    pk = s["peak"]
    t, dd, _ = keep[(pk["vdd"], pk["clk_frac"])]
    wl, B, P, G = ctx.wl, pk["B"], ctx.wl["prompt"], ctx.wl["gen"]
    buf = t["rail"]["area_mm2"].get("buffer", 0) * 1e6 / n1.SRAM_UM2_PER_BIT / 8
    bw = knobs["hbm_Bps"]
    hbm_pre = wl["stored_weights"] * t["wbits"] / 8 + 2 * B * P * wl["kv_bytes_per_token"]
    t_pre = max(pk["T_prefill_s"], (hbm_pre + B * P * n1.act_spill(wl, t, dd, buf, B * P)) / bw)
    t_step = max(pk["T_step_s"], pk["T_step_s"] + B * n1.act_spill(wl, t, dd, buf, B) / bw)
    return B * (P + G) / (t_pre + G * t_step)


def fmt(r):
    return " / ".join(f"{r[m]:,.4g}" for m in M)


def scan(dirpath, nds=(1, 8)):
    rows = []
    for f in sorted(Path(dirpath).glob("*.json")):
        if f.name in ("results.json",):
            continue
        d = design.load(f)
        for nd in nds:
            r = score(d, nd)
            rows.append((tuple(r["best"][m] for m in M), f.name, nd, r))
    rows.sort(reverse=True)
    for k, name, nd, r in rows[:25]:
        print(f"{name:<48} nd={nd:<2} {fmt(r['best'])}  bind={(r['cb'] or {}).get('binding')}")
    return rows


def selfcheck():
    w = design.load(HERE.parents[4] / "docs/src/content/Project/ArchResearch/search/designs/r01.json")
    a = score(w, 1, cb=False)
    assert abs(a["lock"]["tok_s_die"] - 53863.5) < 50, a["lock"]          # = SEARCH.md winner, joint frame
    b = score(w, 1)
    assert b["best"]["tok_s_die"] >= a["lock"]["tok_s_die"] * (1 - 1e-9)
    c = score(w, 8)
    assert c["cb"]["d2d_uJ_tok"] > 0 and c["cb"]["tok_s_die"] <= c["cb"]["d2d_ceiling"]
    cap = metric.KNOBS["power_cap_W_per_mm2"] * metric.KNOBS["die_mm2"]
    assert c["cb"]["die_power_W"] <= cap * 1.001, c["cb"]["die_power_W"]
    # HBM roofline: no scheduler can beat BW / KV bytes per processed token
    wl = model.Ctx(w).wl
    kv_tok = (wl["gen"] * (wl["ctx_decode_sum"] / wl["gen"] + 1) + 2 * wl["prompt"]) / (wl["prompt"] + wl["gen"]) \
        * wl["kv_bytes_per_token"]
    assert c["best"]["tok_s_die"] <= metric.KNOBS["hbm_Bps"] / kv_tok * (1 + 1e-9)
    print("PASS maximalist self-check")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["--selfcheck"]:
        selfcheck()
    elif args[:1] == ["--scan"]:
        scan(args[1])
    else:
        for p in args or [str(HERE / "maximalist.json")]:
            d = design.load(p)
            nd = int(json.loads(Path(p).read_text()).get("system", {}).get("system_dies", 1))
            for tag, kw in (("joint lockstep 1 die", dict(nd=1, cb=False)), ("joint+CB 1 die", dict(nd=1)),
                            (f"joint+CB TP{nd}", dict(nd=nd))):
                r = score(d, **kw)
                print(f"{Path(p).name} {tag:<22} {fmt(r['best'])}  (eta {ETA}: {r['best']['tok_s_die'] * ETA:,.4g} tok/s)"
                      f"  margin {r['margin_db']:+.2f} dB "
                      f"cb={({k: r['cb'][k] for k in ('B', 'per_stream_tok_s', 'binding', 'die_power_W', 'vdd', 'clk_frac', 'hbm_GBps')} if r['cb'] else None)}")
