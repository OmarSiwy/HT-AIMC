"""Compose the node functions into tile -> die -> system and emit metric points.

Node loading is defensive: a node module that fails to import, lacks the function,
or raises is replaced by its frozen copy in nodes/default/, and the failure is
recorded in Ctx.errors (printed by the CLI).

System schedule (lockstep waves, ponytail: continuous batching would overlap
prefill and decode; upgrade if prefill ever binds):
  wave = B requests: prefill phase (B x 512 tokens as GEMM) then 128 decode steps
  (B vectors per step as GEMV). Each phase takes the max over its resources:
  compute (tile occupancy), HBM bytes, digital-rail attention MACs, die-to-die bytes
  and the serial latency chain ((4L+1) stages x (tile pass + hop) + one stream's
  attention). Per-stream decode rate = 1 / decode-step time.
"""
import importlib
import math

from . import metric, workload
from .design import NODES

FNS = dict(n1_system=["plan"], n2_domain=["array"], n3_cell=["cell"], n4_formats=["fmt"],
           n5_array=["geometry", "v_range", "accuracy"], n6_readout=["adc"],
           n7_dataflow=["rail"], n8_quality=["gate"], n9_circuits=["op"],
           n10_wildcards=["apply"])


class Ctx:
    def __init__(self, design, knobs=None):
        self.design, self.knobs, self.errors = design, dict(knobs or metric.KNOBS), []
        self.mods, self.defaults, p, self.options = {}, {}, {}, {}
        for nid in NODES:
            d = importlib.import_module(f"arch_eval.nodes.default.{nid}")
            self.defaults[nid] = d
            try:
                m = importlib.import_module(f"arch_eval.nodes.{nid}")
                for fn in FNS[nid]:
                    getattr(m, fn)
                m.OPTIONS[m.DEFAULT]["params"]
            except Exception as e:  # noqa: BLE001  (any researcher bug -> default)
                self.errors.append(f"{nid}: import/contract failed ({type(e).__name__}: {e}); using default")
                m = d
            self.mods[nid] = m
            opt = design["nodes"].get(nid, m.DEFAULT)
            if opt not in m.OPTIONS:
                self.errors.append(f"{nid}: option {opt!r} unknown; using {m.DEFAULT!r}")
                opt = m.DEFAULT
            self.options[nid] = opt
            p.update(d.OPTIONS[d.DEFAULT]["params"])     # default params first: default fns always find theirs
            p.update(m.OPTIONS[opt]["params"])
        p.update(design["params"])
        self.p = p
        self.wl = workload.llama3(self.knobs.get("model", "8B-class"), prompt=self.knobs["prompt"],
                                  gen=self.knobs["gen"],
                                  kv_bits=int(self.knobs.get("kv_bits") or p.get("kv_bits", 16)))

    def call(self, nid, fn, *args):
        try:
            return getattr(self.mods[nid], fn)(self.p, *args)
        except Exception as e:  # noqa: BLE001
            msg = f"{nid}.{fn} raised {type(e).__name__}: {e}; using default"
            if msg not in self.errors:
                self.errors.append(msg)
            return getattr(self.defaults[nid], fn)(self.p, *args)

    def provenance(self):
        return {nid: f"{self.options[nid]}: {self.mods[nid].OPTIONS[self.options[nid]].get('provenance', '')}"
                for nid in NODES}


def tile(ctx, vdd, clk_frac):
    c, p = ctx.call, ctx.p
    fmt = c("n4_formats", "fmt")
    geo = c("n5_array", "geometry")
    cell = c("n3_cell", "cell", vdd, fmt)
    arr = c("n2_domain", "array", vdd, fmt, cell, geo["rows"])
    adc = c("n6_readout", "adc", vdd, c("n5_array", "v_range", geo, arr))
    acc = c("n5_array", "accuracy", vdd, geo, arr, adc, fmt)
    gate = c("n8_quality", "gate", acc, fmt)
    op = c("n9_circuits", "op", vdd, clk_frac)
    rail = c("n7_dataflow", "rail", vdd, op, ctx.knobs)
    R, C, S, chk = geo["rows"], geo["cols"], fmt["slices"], geo["checksum"]
    phys = (C + chk) * S
    n_adc = -(-phys // geo["adc_share"])
    rounds = -(-phys // n_adc)
    t_word = arr["t_word_ns"] / clk_frac
    t_conv = rounds * adc["t_conv_ns"] / clk_frac
    t_pass = max(t_word, t_conv) if rail["pingpong"] else t_word + t_conv
    buf_bytes = R * fmt["abits"] / 8 + C * 2
    e = dict(array=R * phys * arr["e_mac_fJ"] * 1e-15,
             converters=phys * adc["e_conv_fJ"] * 1e-15,
             digital_recombination=phys * adc["e_digital_fJ"] * 1e-15,
             buffer=buf_bytes * rail["e_buf_J_per_byte"])
    banks = 2 if p.get("double_buffer") else 1
    w_area = R * (C + chk) * cell["area_um2_per_weight"] * banks
    area = dict(weights=w_area, adcs=n_adc * adc["area_um2"],
                periphery=R * 4 * 0.29 + C * 20 * 0.087)   # row drivers ~4 DFF-sized, ~20 NAND2/col shift-add
    t = dict(rows=R, cols=C, slices=S, phys_cols=phys, n_adc=n_adc, t_pass_s=t_pass * 1e-9,
             t_word_ns=t_word, t_conv_ns=t_conv,
             t_load_s=R * cell["t_write_row_ns"] * 1e-9 / clk_frac,
             e_pass_J=sum(e.values()), e_pass_J_parts=e, macs_per_pass=R * C,
             area_um2=sum(area.values()), area_um2_parts=area, wbits=fmt["wbits"],
             write_bits_per_load=R * phys * 4,          # 4 stored bits per slice per weight
             e_write_J_per_bit=cell["e_write_fJ_per_bit"] * 1e-15,
             leak_W=R * (C + chk) * banks * cell["leak_nW_per_weight"] * 1e-9 * op["leak_scale"],
             snr_db=acc["snr_db"], snr_parts_db=acc["parts_db"], quality=gate,
             fmt=fmt, op=op, rail=rail, cell=cell, arr=arr, adc=adc)
    return c("n10_wildcards", "apply", t)


def die(ctx, t):
    k, rail = ctx.knobs, t["rail"]
    fixed = sum(rail["area_mm2"].values())
    tiles_mm2 = k["die_mm2"] * rail["tile_util"] - fixed
    n_tiles = max(0, int(tiles_mm2 * 1e6 // t["area_um2"]))
    need = workload.tiles(ctx.wl, t["rows"], t["cols"])
    return dict(n_tiles=n_tiles, tiles_needed=need,
                area_mm2=dict(tiles=n_tiles * t["area_um2"] / 1e6, **rail["area_mm2"],
                              unused=k["die_mm2"] - fixed - n_tiles * t["area_um2"] / 1e6),
                mac_rate=n_tiles * t["macs_per_pass"] / t["t_pass_s"],
                static_W=n_tiles * t["leak_W"] + rail["leak_W"])


def _phase(res):
    b = max(res, key=res.get)
    return res[b], b


def system_point(ctx, t, d, plan, B):
    k, wl, rail = ctx.knobs, ctx.wl, t["rail"]
    D, streaming = plan["dies"], plan["mode"] == "streaming"
    nd = int(k.get("system_dies", 1))   # ideal tensor-parallel group: n x tiles, HBM, rail; one shared batch
    G, P, need = wl["gen"], wl["prompt"], d["tiles_needed"]
    kvb = wl["kv_bytes_per_token"]
    w_bytes = wl["stored_weights"] * t["wbits"] / 8
    ctx_avg = wl["ctx_decode_sum"] / G
    hbm_Bps, att_rate = D * nd * k["hbm_Bps"], D * nd * rail["att_mac_per_s"]

    def compute(vectors):
        if streaming:
            loads = -(-need // (nd * d["n_tiles"]))
            per = (max(t["t_load_s"], vectors * t["t_pass_s"]) if ctx.p.get("double_buffer")
                   else t["t_load_s"] + vectors * t["t_pass_s"])
            return loads * per
        rep = max(1, D * nd * d["n_tiles"] // need)
        return vectors * t["t_pass_s"] / rep

    lat_one = wl["stages"] * (t.get("t_stage_s", t["t_pass_s"]) + (rail["hop_s"] if D > 1 else 0))
    hbm_pre = (w_bytes if streaming else 0) + 2 * B * P * kvb
    hbm_step = (w_bytes if streaming else 0) + B * ctx_avg * kvb + B * kvb
    d2d = lambda n: n * wl["act_bytes_per_token"] * (D - 1) / (D * k["d2d_Bps"])  # noqa: E731
    T_pre, b_pre = _phase(dict(compute=compute(B * P), hbm=hbm_pre / hbm_Bps,
                               attention=B * wl["att_macs_prefill"] / att_rate, d2d=d2d(B * P),
                               latency=lat_one + P * t["t_pass_s"]))
    T_step, b_step = _phase(dict(compute=compute(B), hbm=hbm_step / hbm_Bps,
                                 attention=B * wl["att_macs_per_ctx"] * ctx_avg / att_rate, d2d=d2d(B),
                                 latency=lat_one + wl["att_macs_per_ctx"] * ctx_avg / att_rate))
    T = T_pre + G * T_step
    tokens = B * (P + G)
    hbm_bytes = hbm_pre + G * hbm_step
    e = dict(weight_passes=tokens * need * t["e_pass_J"],
             weight_write=(1 + G) * need * t["write_bits_per_load"] * t["e_write_J_per_bit"] if streaming else 0.0,
             attention=B * (wl["att_macs_prefill"] + wl["att_macs_decode"]) * rail["e_att_mac_J"]
             + B * (wl["softmax_exps_prefill"] + wl["softmax_exps_decode"]) * rail["e_exp_J"],
             elementwise=tokens * wl["elem_ops_per_token"] * rail["e_elem_J"],
             hbm_phy=hbm_bytes * 8 * rail["phy_J_per_bit"],
             d2d=tokens * wl["act_bytes_per_token"] * 8 * (D - 1) * k["d2d_pJ_per_bit"] * 1e-12,
             static=D * nd * d["static_W"] * T)
    for n, v in t["e_pass_J_parts"].items():   # split weight_passes for the breakdown
        e[f"  tile.{n}"] = tokens * need * v
    e_die = sum(v for n, v in e.items() if not n.startswith("  "))
    e_ext = hbm_bytes * 8 * k["hbm_pJ_per_bit"] * 1e-12
    if streaming:
        kv_cap = nd * k["hbm_bytes"] - w_bytes - wl["embed_bytes"]
    else:
        kv_cap = D * nd * k["hbm_bytes"] - wl["embed_bytes"]
    b_max = max(0, int(kv_cap // (kvb * (P + G))))
    useful = B * (wl["tokens"] * wl["weight_macs_per_token"] + wl["att_macs_prefill"] + wl["att_macs_decode"])
    return dict(B=B, b_max=b_max, dies=D, mode=plan["mode"], vdd=t["op"]["vdd"], clk_frac=t["op"]["clk_frac"],
                tok_s_die=tokens / T / (D * nd), gen_tok_s_die=B * G / T / (D * nd),
                die_power_W=e_die / T / (D * nd), ext_power_W=e_ext / T / (D * nd),
                useful_macs_s_die=useful / T / (D * nd), per_stream_tok_s=1 / T_step,
                tile_macs_s_die=tokens * wl["weight_macs_per_token"] / T / (D * nd),
                hbm_Bps_die=hbm_bytes / T / (D * nd), hbm_Bps_decode_die=hbm_step / T_step / (D * nd),
                hbm_bytes_per_token=hbm_bytes / tokens,
                phases=dict(prefill=dict(ops=2 * B * (P * wl["weight_macs_per_token"] + wl["att_macs_prefill"]),
                                         bytes=hbm_pre, s=T_pre),
                            decode=dict(ops=2 * B * (wl["weight_macs_per_token"] + wl["att_macs_per_ctx"] * ctx_avg),
                                        bytes=hbm_step, s=T_step)),   # whole system, per phase (one decode step)
                kv_ok=B <= b_max, quality_ok=t["quality"]["passed"],
                binding=dict(prefill=b_pre, decode=b_step), T_wave_s=T, T_prefill_s=T_pre, T_step_s=T_step,
                energy_per_token_J=dict({n: v / tokens for n, v in e.items()}, external_memory=e_ext / tokens))


SWEEP_VDD, SWEEP_CLK = [0.45, 0.5, 0.6, 0.7], [1.0, 0.5, 0.25]   # ARCH_METRIC VDD range; clock fractions


def b_sweep(ctx, t, d, plan):
    """Points over B = powers of two up to the KV limit, plus the limit itself;
    a fixed batch (knob 'batch' > 0) is the only point (it may be KV-infeasible)."""
    if ctx.knobs.get("batch"):
        return [system_point(ctx, t, d, plan, int(ctx.knobs["batch"]))]
    b_max = system_point(ctx, t, d, plan, 1)["b_max"]
    bs = sorted({2 ** i for i in range(int(math.log2(max(1, b_max))) + 1)} | {max(1, b_max)})
    return [system_point(ctx, t, d, plan, b) for b in bs]


def operating_points(ctx):
    """All (VDD, clock, B) points; VDD/clock grid from the n9 module's SWEEP."""
    sw = getattr(ctx.mods["n9_circuits"], "SWEEP", {})
    vdds = [v for v in sw.get("vdd", SWEEP_VDD) if ctx.knobs["vdd_min"] <= v <= ctx.knobs["vdd_max"]]
    pts, dies = [], {}
    for v in vdds:
        for f in sw.get("clk_frac", SWEEP_CLK):
            t = tile(ctx, v, f)
            d = die(ctx, t)
            if d["n_tiles"] < 1:
                ctx.errors.append(f"VDD {v} clk {f}: no tile fits on the die")
                continue
            plan = ctx.call("n1_system", "plan", ctx.wl, t, d, ctx.knobs)
            dies[(v, f)] = (t, d, plan)
            pts += b_sweep(ctx, t, d, plan)
    return pts, dies


def why_b(ctx, peak, pts):
    """Which constraint stops B from growing at the peak point's (VDD, clock)."""
    if peak is None:
        return "infeasible"
    if ctx.knobs.get("batch"):
        return f"fixed batch {int(ctx.knobs['batch'])}"
    nxt = [q for q in pts if q["vdd"] == peak["vdd"] and q["clk_frac"] == peak["clk_frac"] and q["B"] > peak["B"]]
    if not nxt:
        return "kv_capacity (B = KV limit)"
    q = min(nxt, key=lambda q: q["B"])
    k = ctx.knobs
    if q["per_stream_tok_s"] < k["stream_floor_tok_s"]:
        return "per_stream_floor"
    if not metric.power_ok(q, k):
        return "power_cap"
    return "throughput saturates (larger B does not raise tok/s)"


def evaluate(design, knobs=None):
    ctx = Ctx(design, knobs)
    pts, dies = operating_points(ctx)
    s = metric.score(pts, ctx.knobs)
    pk = s["peak"]
    s["binding"] = (dict(pk["binding"], concurrency=why_b(ctx, pk, pts)) if pk else "infeasible")
    if pk:
        t, d, plan = dies[(pk["vdd"], pk["clk_frac"])]
        s["tile"], s["die"], s["plan"] = t, d, plan
    s["errors"], s["provenance"], s["n_points"] = ctx.errors, ctx.provenance(), len(pts)
    s["buffer_MB"] = ctx.p.get("buffer_MB")
    return s
