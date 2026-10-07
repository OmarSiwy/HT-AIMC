"""Digital weight-stationary INT8 systolic die (digital/sysreference) under the identical metric.

Same die area, HBM, digital rail, KV, schedule and metric as the IMC candidates
(model.system_point); only the tile changes: an N x N INT8 PE array that streams
weights from HBM (N-cycle shift-in, double-buffered weight registers), one vector
per cycle, 2N-cycle stage latency, exact arithmetic (quality always passes).
Weights in HBM default to W4 (matched to the IMC default format, unpacked to the INT8
PE; the RTL has an INT4-weight regression, cfg16_int4w); pass wbits=8 for native INT8.

PE numbers: digital/sysreference/build/ppa.json when present (keys read if they
exist: area_um2_per_pe, fmax_GHz | fmax_mhz, energy_per_mac_fJ, array_rows/array_cols,
leak_W_per_pe), otherwise projected 7 nm literature values below.
"""
import json
import math

from . import ROOT, design, metric, model

PPA = ROOT / "digital/sysreference/build/ppa.json"
LIT = dict(area_um2_per_pe=80.0, fmax_GHz=1.0, energy_per_mac_fJ=100.0, array_rows=128,
           array_cols=128, leak_W_per_pe=1e-6)
LIT_SRC = ("projected: ASAP7 INT8 mult (~25 um2) + 24b acc + ~50 DFF at 70 % util; "
           "~0.1 pJ/INT8 MAC incl. pipeline regs at 0.7 V (7 nm literature)")


def ppa():
    src, v = dict.fromkeys(LIT, LIT_SRC), dict(LIT)
    try:
        raw = json.loads(PPA.read_text())
    except (OSError, ValueError):
        return v, src
    if "fmax_mhz" in raw and "fmax_GHz" not in raw:
        raw["fmax_GHz"] = raw["fmax_mhz"] / 1e3
    for key in LIT:
        if isinstance(raw.get(key), (int, float)):
            v[key], src[key] = float(raw[key]), f"measured/derived: {PPA.name}"
    return v, src


def tile(ctx, vdd, clk_frac, wbits=4, pe=None):
    pe = pe or ppa()[0]
    op = ctx.call("n9_circuits", "op", vdd, clk_frac)
    rail = ctx.call("n7_dataflow", "rail", vdd, op, ctx.knobs)
    N, M = int(pe["array_rows"]), int(pe["array_cols"])
    cyc = 1e-9 / (pe["fmax_GHz"] / op["delay_scale"] * clk_frac)
    e = dict(pe_macs=N * M * pe["energy_per_mac_fJ"] * op["e_scale"] * 1e-15,
             buffer=(N + 2 * M) * rail["e_buf_J_per_byte"])
    return dict(rows=N, cols=M, slices=1, phys_cols=M, macs_per_pass=N * M, t_pass_s=cyc,
                t_stage_s=(N + M) * cyc, t_load_s=N * cyc, e_pass_J=sum(e.values()), e_pass_J_parts=e,
                area_um2=N * M * pe["area_um2_per_pe"], area_um2_parts=dict(pes=N * M * pe["area_um2_per_pe"]),
                wbits=wbits, write_bits_per_load=N * M * 8,
                e_write_J_per_bit=rail["e_buf_J_per_byte"] / 8 + 1.5e-15 * op["e_scale"],
                leak_W=N * M * pe["leak_W_per_pe"] * op["leak_scale"], snr_db=math.inf, snr_parts_db={},
                quality=dict(passed=True), op=op, rail=rail, fmt=dict(wbits=wbits, abits=8))


def evaluate(wbits=4, knobs=None, params=None):
    """params: extra design params, e.g. a candidate's KV format (kv_bits, kv_*) for a lever-matched run."""
    ctx = model.Ctx(design.make({"n1_system": "streaming"}, dict(params or {}, double_buffer=True)), knobs)
    pe, src = ppa()
    pts, keep = [], {}
    for v in [x for x in model.SWEEP_VDD if ctx.knobs["vdd_min"] <= x <= ctx.knobs["vdd_max"]]:
        for f in model.SWEEP_CLK:
            t = tile(ctx, v, f, wbits, pe)
            d = model.die(ctx, t)
            plan = dict(mode="streaming", dies=1)
            keep[(v, f)] = (t, d, plan)
            pts += model.b_sweep(ctx, t, d, plan)
    s = metric.score(pts, ctx.knobs)
    if s["peak"]:
        s["tile"], s["die"], s["plan"] = keep[(s["peak"]["vdd"], s["peak"]["clk_frac"])]
        s["binding"] = dict(s["peak"]["binding"], concurrency=model.why_b(ctx, s["peak"], pts))
    s["pe"], s["pe_source"], s["buffer_MB"] = pe, src, ctx.p.get("buffer_MB")
    return s


def sohu_equivalent(wbits=metric.SOHU_WBITS, target=metric.SOHU_TOK_S_CHIP, a_max=2000.0):
    """Size this systolic die (mm2) until it delivers Sohu's claimed tok/s per chip under the
    "sohu" conditions; its area and power are then a modeled Sohu-equivalent at ASAP7.
    -> (die_mm2, score), or (None, score at a_max) when HBM, KV or power binds first.
    ponytail: geometric bisection on area; tok/s is monotone in area up to the binding limit."""
    def f(a):
        return evaluate(wbits, metric.knobs_for("sohu", die_mm2=a))
    top = f(a_max)
    if top["tok_s_die"] < target:
        return None, top
    lo, hi = 1.0, a_max
    for _ in range(40):
        mid = (lo * hi) ** 0.5
        lo, hi = (lo, mid) if f(mid)["tok_s_die"] >= target else (mid, hi)
    return hi, f(hi)
