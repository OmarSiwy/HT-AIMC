"""N1 system & memory: weight residency vs streaming, dies, fabric, KV, concurrency.

Research write-up: docs/src/content/Project/ArchResearch/nodes/N1.md (option table, evidence,
critic responses).

Options the core (model.system_point) runs directly, selected by `mode` + `double_buffer`:
  stream_single  (DEFAULT, lead) one die = one replica with its own HBM stack. Weights stream
                 HBM -> tile in K-complete column chunks; each chunk is written once and serves
                 V vectors. One storage bank per weight; tiles are rewritten just in time, skewed
                 per tile (a tile is overwritten as soon as it has served its V vectors).
  streaming      same, double-buffered (two banks per weight). Kept under this name:
                 baseline_systolic.py selects it.
  resident       one weight copy over D = ceil(tiles_needed / tiles_per_die) dies, layer
                 pipeline over the die-to-die link, written once (27n2: not charged).

Equations (units in names; constants are the evaluator's, from asap7_constants.json via the
other nodes):
  compute ceiling: R_c [tok/s] = n_tiles / (tiles_needed x t_pass)                  (27a2 roof P)
  double-buffer area law (cap_dup = 1 analog-stored caps, 0 digitally-selected caps):
      A_w(f) = R (C+chk) max(FEOL (1+f), BEOL (1 + f cap_dup));  R_c(f) = R_c(0) A(0)/A(f)
  write exposure per tile: x = t_fill / (t_fill + V t_pass), skewed JIT t_fill = t_load,
      chunk-staged (not skewed) t_fill = max(t_load, chunk_bytes / BW_hbm)
  retention: a chunk lives V t_pass <= t_ret = C_w dV / I_leak  =>  X <= r t_ret / t_pass
  continuous batching (decode-first, chunked prefill; two micro-batch groups interleave so the
      rail's attention overlaps the tiles): X = min(R_c (1-x), att, (BW - r w)/(kv_tok + spill),
      B_max r (P+G)/G, r t_ret/t_pass), maximized over r >= floor; no interleave:
      compute term -> 1/(1/R_c + 1/att). Power over the cap is throttled (clock-gated duty
      cycle), not discarded: X <= nd (cap - static) / e_dyn_per_token.
  activation spill, per matrix with V K a > buffer: L (min(K a c, K N b_w/8 x K a/buf) + N a) bytes/token
      (c = K-complete chunks of that matrix; the min picks input re-read vs V-blocking with weight
      re-stream). Charged by the CB rows only; the core charges none.
  KV capacity: B_max = (HBM_bytes - w_bytes - embed_bytes) / (kv_bytes_per_token (P+G))
  tensor-parallel group of N dies: all-reduce 2 L d x 2 B x 2(N-1)/N bytes per token over d2d.
Provenance: 27a2, 27a3 + 27l1 (E_prog/R), 27n2 (programming), 27l8 (resident die count),
LIT_SYSTEMS.md §5, LIT_QUALITY.md, asap7_constants.json (leakage per fin). Every output is
projected (laws on projected / measured-sky130 / measured-ASAP7-device constants).

KV format: pick n4 option "w4a8_kv8" (the evaluator reads the flat param `kv_bits`). The d2d PHY
area is n7's phy_d2d_mm2: the single-die lead needs phy_d2d_mm2 = 0 as a design param.
"""
import math

OPTIONS = {
    "stream_single": dict(params=dict(mode="streaming", double_buffer=False),
                          provenance="derived (N1.md): streamed weights, one bank, skewed JIT rewrite; "
                                     "exposure t_load/(V t_pass) < 1 % (27a2, 27l1 R = V)"),
    "streaming": dict(params=dict(mode="streaming", double_buffer=True),
                      provenance="ARCH_METRIC default memory, double-buffered; dominated (never better than "
                                 "one bank; -49 % for analog-stored caps) (N1.md)"),
    "resident": dict(params=dict(mode="resident", double_buffer=False),
                     provenance="ARCH_METRIC d2d 2 TB/s 0.5 pJ/bit; ~500 iso-dies for W4 8B (27l1, 27l8); "
                                "ties stream_single on tok/s/die, excluded by the user's streaming decision"),
}
DEFAULT = "stream_single"
SWEEP = dict(double_buffer=[False, True])   # B is swept by model.py; KV bits by n4

SRAM_UM2_PER_BIT = 0.027 * 1.5              # 6T bitcell x array overhead (n7 buffer law)


def plan(p, wl, tile, die, knobs):
    need, n = die["tiles_needed"], max(1, die["n_tiles"])
    chunk_B = n * tile["rows"] * tile["cols"] * tile["wbits"] / 8
    # ponytail: the core models the skewed just-in-time rewrite (t_load per tile, serialized);
    # the chunk-staged alternative (whole chunk delivered before compute) is t_fill_staged.
    extra = dict(chunk_bytes=chunk_B, t_fill_s=tile["t_load_s"],
                 t_fill_staged_s=max(tile["t_load_s"], chunk_B / knobs["hbm_Bps"]),
                 b_min_1pct=99 * tile["t_load_s"] / tile["t_pass_s"],
                 b_min_hbm_prefetch=chunk_B / knobs["hbm_Bps"] / tile["t_pass_s"],
                 compute_ceiling_tok_s=n / (need * tile["t_pass_s"]))
    if p["mode"] == "resident":
        return dict(mode="resident", dies=max(1, -(-need // n)), **extra)
    return dict(mode="streaming", dies=1, **extra)


# --------------------------------------------------------------------------------------------
# Analytic variants the core cannot express (continuous batching, retention, spill, hybrid,
# partial double buffer, TP d2d, on-die KV). Each uses the evaluator's own tile/die/point.
# --------------------------------------------------------------------------------------------

def _wl(knobs, kv_bits):
    from arch_eval import workload
    return workload.llama3(knobs.get("model", "8B-class"), prompt=knobs["prompt"], gen=knobs["gen"],
                           kv_bits=kv_bits)


def _cb_rate(R_c, att_cap, BW, w, kv_tok, b_cap, P, G, floor, fill=0.0, t_pass=1.0, t_ret=math.inf,
             spill=lambda V: 0.0):
    """Steady-state continuous batching, whole system: every iteration sweeps the weights once
    (r sweeps/s = per-stream decode rate). X = min(compute (1 - exposure), attention, HBM, KV
    capacity, retention) maximized over r >= floor (Little: B_d = X G / ((P+G) r)). -> (X, r, binding)."""
    best = (0.0, floor, "floor")
    for r in [floor * 1.05 ** i for i in range(260)]:          # floor .. ~3e5 x floor
        V = R_c / r                                             # vectors per chunk lifetime
        lim = dict(compute=R_c * V * t_pass / (V * t_pass + fill) if R_c < math.inf else R_c,
                   attention=att_cap, hbm=(BW - r * w) / (kv_tok + spill(V)), kv_capacity=b_cap * r * (P + G) / G,
                   retention=r * t_ret / t_pass)
        b = min(lim, key=lim.get)
        if lim[b] > best[0] * (1 + 1e-9):
            best = (lim[b], r, b)
    return best


def act_spill(wl, t, d, buf_bytes, V):
    """Activation bytes/token through HBM at V vectors per chunk lifetime. Per matrix, when the V
    inputs (V K a) overflow the buffer, the cheaper loop order wins: (a) re-read the input for each
    of its c K-complete chunks (K a c), or (b) block V into buffer-sized groups V_b = buf/(K a) and
    re-stream that matrix's weights V/V_b times (K N b_w/8 / V_b). Outputs are written once (N a)."""
    a, R, C, n = t["fmt"].get("abits", 8) / 8, t["rows"], t["cols"], max(1, d["n_tiles"])
    tot = 0.0
    for K, N, reps in wl["matrices"]:
        if V * K * a <= buf_bytes:
            continue
        c = -(-(-(-K // R) * -(-N // C)) // n)
        tot += reps * (min(K * a * c, K * N * t["wbits"] / 8 * K * a / buf_bytes) + N * a)
    return tot


def head_skip_factor(wl, t):
    """R_c gain from running the LM head only for the last prompt token + G decode tokens."""
    from arch_eval import workload
    P, G, need = wl["prompt"], wl["gen"], workload.tiles(wl, t["rows"], t["cols"])
    K, N, _ = wl["matrices"][-1]
    head = -(-K // t["rows"]) * -(-N // t["cols"])
    return need * (P + G) / (need * (P + G) - head * (P - 1))


def continuous(ctx, t, d, plan, knobs, cap=None, t_ret=math.inf, spill=True, interleave=True,
               staged=False, t_load=None, stage_Bps=None):
    """Continuous batching on one evaluator tile/die (one VDD, clock). Bytes per token, sweeps per
    token and dynamic energy per token equal the lockstep wave at B = B_d ((1+G)/(B_d (P+G)) = r/X),
    so energy comes from model.system_point(B_d) plus the spill; static energy follows X.
    Over the power cap the point is throttled to the cap. -> per-die dict or None."""
    from arch_eval import model
    wl, k = ctx.wl, knobs
    P, G, kvb = wl["prompt"], wl["gen"], wl["kv_bytes_per_token"]
    nd = int(k.get("system_dies", 1))
    w = wl["stored_weights"] * t["wbits"] / 8
    kv_tok = (G * (wl["ctx_decode_sum"] / G + 1) + 2 * P) / (P + G) * kvb
    att_tok = (wl["att_macs_prefill"] + wl["att_macs_decode"]) / (P + G)
    buf = t["rail"]["area_mm2"].get("buffer", 0) * 1e6 / SRAM_UM2_PER_BIT / 8
    spf = (lambda V: act_spill(wl, t, d, buf, V)) if spill else (lambda V: 0.0)
    b_cap = min(model.system_point(ctx, t, d, plan, 1)["b_max"], int(k.get("batch") or 10 ** 12))
    R_c = nd * d["n_tiles"] / (d["tiles_needed"] * t["t_pass_s"])
    att = nd * t["rail"]["att_mac_per_s"] / att_tok
    if not interleave:
        R_c = 1 / (1 / R_c + 1 / att)
    tl = t["t_load_s"] if t_load is None else t_load
    fill = max(tl, d["n_tiles"] * t["rows"] * t["cols"] * t["wbits"] / 8 / (stage_Bps or k["hbm_Bps"])) if staged else tl
    if ctx.p.get("double_buffer"):
        fill = 0.0                                              # shadow bank hides the write (V t_pass >> t_load)
    X, r, bind = _cb_rate(R_c, att, nd * k["hbm_Bps"], w, kv_tok, b_cap, P, G,
                          k["stream_floor_tok_s"], fill, t["t_pass_s"], t_ret, spf)
    sp = spf(R_c / r)
    if X <= 0 or not t["quality"]["passed"]:
        return None
    rail, stat = t["rail"], d["static_W"] * nd
    for _ in range(2):                                          # second pass only if throttled
        B_d = max(1, round(X * G / ((P + G) * r)))
        pt = model.system_point(ctx, t, d, plan, B_d)
        tok_pt = B_d * (P + G)
        e_dyn = ((pt["die_power_W"] - d["static_W"]) * pt["T_wave_s"] * nd / tok_pt
                 + sp * 8 * rail["phy_J_per_bit"])
        if cap is None or (e_dyn * X + stat) / nd <= cap * (1 + 1e-9):
            break
        X, bind = nd * (cap - d["static_W"]) / e_dyn, "power_cap (throttled)"
        if X <= 0:
            return None
    e_die = e_dyn + stat / X
    e_ext = pt["ext_power_W"] * pt["T_wave_s"] * nd / tok_pt + sp * 8 * k["hbm_pJ_per_bit"] * 1e-12
    useful = pt["useful_macs_s_die"] * pt["T_wave_s"] * nd / tok_pt
    return dict(tok_s_die=X / nd, tops_w=2 * useful / e_die / 1e12, tok_w=1 / (e_die + e_ext),
                per_stream_tok_s=r, B=B_d, binding=bind, die_power_W=e_die * X / nd, V=X / r,
                hbm_GBps=(r * w + X * (kv_tok + sp)) / nd / 1e9, spill_MB_tok=sp / 1e6,
                exposure=fill / (fill + X / r * t["t_pass_s"]), vdd=t["op"]["vdd"], clk_frac=t["op"]["clk_frac"])


def cb_score(ctx, keep, knobs, **kw):
    """Best continuous-batching point over the (VDD, clock) grid `keep` = {(v, f): (tile, die, plan)},
    power cap applied by throttling. tok_j = best tok/W over the grid."""
    cap = knobs["power_cap_W_per_mm2"] * knobs["die_mm2"]
    pts = [c for c in (continuous(ctx, *tdp, knobs, cap=cap, **kw) for tdp in keep.values()) if c]
    if not pts:
        return dict(tok_s_die=0.0, tops_w=0.0, tok_w=0.0, tok_j=0.0, B=0, per_stream_tok_s=0, binding="infeasible")
    best = max(pts, key=lambda c: (c["tok_s_die"], c["tok_w"]))
    return dict(best, tok_j=max(c["tok_w"] for c in pts))


def hbm_ceiling(wl, wbits, knobs, b_max):
    """Per-die memory ceiling under continuous batching with infinite compute, no spill (law)."""
    P, G, kvb = wl["prompt"], wl["gen"], wl["kv_bytes_per_token"]
    kv_tok = (G * (wl["ctx_decode_sum"] / G + 1) + 2 * P) / (P + G) * kvb
    return _cb_rate(math.inf, math.inf, knobs["hbm_Bps"], wl["stored_weights"] * wbits / 8, kv_tok,
                    min(b_max, int(knobs.get("batch") or 10 ** 12)), P, G, knobs["stream_floor_tok_s"])[0]


def retention_s(c_fF, leak_nA_per_fin, bits=4, vfs=0.7, fins=1):
    """Hold time of a charge-stored weight: droop of half an LSB of `bits` over `vfs`."""
    return c_fF * 1e-15 * vfs / 2 ** bits / 2 / (leak_nA_per_fin * 1e-9 * fins)


def retention_table(c_fF):
    """t_ret per access device, from the measured ASAP7 off-currents (asap7_constants.json).
    Underdrive -0.2 V: SS 65 mV/dec at 27 C, ~78 mV/dec at 85 C (projected)."""
    from arch_eval import asap7
    lk = {n: asap7.get(f"nfet_ileak_per_fin_nA{s}") for n, s in
          (("rvt27", ""), ("rvt85", "_85C"), ("sramvt27", "_sram"))}
    t = {n: retention_s(c_fF, v) for n, v in lk.items()}
    t["rvt27_underdrive"] = t["rvt27"] * 10 ** (0.2 / 0.065)
    t["rvt85_underdrive"] = t["rvt85"] * 10 ** (0.2 / 0.078)
    return t


def hybrid_bound(s, kv_bits, knobs):
    """Upper bound on the tok/s gain from keeping a hot subset resident on one streaming die."""
    t, d, pk = s["tile"], s["die"], s["peak"]
    wl = _wl(knobs, kv_bits)
    phi = d["n_tiles"] / d["tiles_needed"]                    # fraction of one weight copy a die holds
    w = wl["stored_weights"] * t["wbits"] / 8
    step_hbm = w + pk["B"] * (wl["ctx_decode_sum"] / wl["gen"] + 1) * wl["kv_bytes_per_token"]
    dec_share = wl["gen"] * pk["T_step_s"] / pk["T_wave_s"]
    return dict(phi=phi, max_gain=phi * w / step_hbm * dec_share)   # prefill: compute-bound, 0 gain


def partial_db(s, f, cap_dup=1):
    """tok/s ratio of a shadow-bank fraction f against one bank (compute-bound). cap_dup = 1 when
    the caps hold the weight (shadow duplicates them), 0 when SRAM bits select shared caps."""
    t = s["tile"]
    a = t["area_um2_parts"]
    a0, cell = sum(a.values()), t["cell"]
    nw = a["weights"] / cell["area_um2_per_weight"]
    w_f = nw * max(cell.get("feol_um2", 0) * (1 + f), cell.get("beol_um2", cell["area_um2_per_weight"]) * (1 + f * cap_dup))
    return a0 / (a0 - a["weights"] + w_f)


def tp_d2d(knobs, N, kv_bits):
    wl = _wl(knobs, kv_bits)
    L, dm = wl["model"]["layers"], wl["model"]["d"]
    b = 2 * L * dm * 2 * 2 * (N - 1) / N                      # bytes/token: 2 all-reduces per layer, 16-bit
    return dict(bytes_per_token=b, ceiling_tok_s=knobs["d2d_Bps"] / max(b, 1e-30),
                e_J_per_token=b * 8 * knobs["d2d_pJ_per_bit"] * 1e-12)


def kv_on_die(knobs, kv_bits, um2_per_bit=SRAM_UM2_PER_BIT, frac=1.0):
    """Streams whose full KV fits on die using `frac` of the die (0 tiles left)."""
    wl = _wl(knobs, kv_bits)
    cap_B = knobs["die_mm2"] * frac * 1e6 / um2_per_bit / 8
    return cap_B / (wl["kv_bytes_per_token"] * (wl["prompt"] + wl["gen"]))


# N1 is scored with every other node FROZEN at its shipped default (nodes/default/: the 128x64
# charge-domain W4A8 tile, SRAM bits switching shared MOM caps, legacy 28 dB gate), so the system
# effects are reproducible while the other nodes are being researched. study(base={}) scores live.
BASE = {}


def freeze_others():
    """Point arch_eval.nodes.n2..n10 at their frozen defaults (sys.modules), n1 stays live."""
    import importlib
    import sys
    from arch_eval.design import NODES
    for nid in NODES[1:]:
        sys.modules[f"arch_eval.nodes.{nid}"] = importlib.import_module(f"arch_eval.nodes.default.{nid}")


def _baseline(k, wb, extra):
    """Systolic baseline (literature PE, projected): lockstep score + the (VDD, clk) grid."""
    from arch_eval import baseline_systolic, design, metric, model
    ctx = model.Ctx(design.make({"n1_system": "streaming"}, dict(double_buffer=True, **extra)), k)
    pts, keep = [], {}
    for v in [x for x in model.SWEEP_VDD if k["vdd_min"] <= x <= k["vdd_max"]]:
        for fr in model.SWEEP_CLK:
            t = baseline_systolic.tile(ctx, v, fr, wb)
            keep[(v, fr)] = (t, model.die(ctx, t), dict(mode="streaming", dies=1))
            pts += model.b_sweep(ctx, *keep[(v, fr)])
    return metric.score(pts, k), ctx, keep


def study(conditions="arch", base=BASE):
    """Score every N1 option (core + analytic) with the evaluator. -> list of row dicts."""
    from arch_eval import metric, model, design
    rows = []

    def ev(opt, kv, extra=None, knob=None, **kn):
        k = metric.knobs_for(conditions)
        k.update(kn)
        k["kv_bits"] = kv
        d = design.make(dict(base, n1_system=opt), dict(extra or {}, kv_bits=kv))
        k2 = dict(k, **(knob or {}))
        return model.evaluate(d, k2), k2, model.Ctx(d, k2)

    def add(name, sc, label, note="", lock=None):
        tj = max(sc.get("tok_j", 0.0), (lock or {}).get("tok_j", 0.0))   # tok/J: any scheduler
        rows.append(dict(name=name, tok_s_die=sc["tok_s_die"], tops_w=sc["tops_w"], tok_w=sc["tok_w"],
                         tok_j=tj, label=label, note=note))

    def add_cb(name, ctx, keep, k, label, lock=None, **kw):
        c = cb_score(ctx, keep, k, **kw)
        add(name, c, label, f"B_d={c['B']} r={c['per_stream_tok_s']:.3g} V={c.get('V', 0):.0f} "
                            f"bind={c['binding']} HBM={c.get('hbm_GBps', 0):.0f}GB/s spill={c.get('spill_MB_tok', 0):.2f}MB/tok "
                            f"x={c.get('exposure', 0):.1e} VDD={c.get('vdd')} clk={c.get('clk_frac')}", lock)
        return c

    lab_cb = "projected (analytic CB on the evaluator's tiles)"
    if conditions == "arch":
        for kv in (16, 8, 4):
            s, k, ctx = ev("stream_single", kv)
            add(f"stream_single kv{kv} (lockstep)", s, "projected",
                f"B={s['peak']['B']} bind={s['binding']}")
            add_cb(f"stream_single kv{kv} +CB", ctx, model.operating_points(ctx)[1], k, lab_cb, s)
            add(f"  hbm ceiling (CB, compute inf) kv{kv}",
                dict(tok_s_die=hbm_ceiling(ctx.wl, s["tile"]["wbits"], k, s["peak"]["b_max"]), tops_w=0, tok_w=0),
                "projected (law)")
            s0, k0, ctx0 = ev("stream_single", kv, dict(phy_d2d_mm2=0.0))
            keep0 = model.operating_points(ctx0)[1]
            add(f"stream_single no-d2d kv{kv} (lockstep)", s0, "projected", f"tiles {s0['die']['n_tiles']}")
            c = add_cb(f"stream_single no-d2d kv{kv} +CB", ctx0, keep0, k0, lab_cb, s0)
            if kv != 8:
                continue
            # ---- the lead's sensitivities (KV8, no d2d PHY) ----
            add_cb("A1 no attention interleave", ctx0, keep0, k0, lab_cb, s0, interleave=False)
            add_cb("A1 without spill (old accounting)", ctx0, keep0, k0, lab_cb, s0, spill=False)
            add_cb("A1 chunk-staged (no per-tile skew)", ctx0, keep0, k0, lab_cb, s0, staged=True)
            add_cb("A1 DAC write 5 ns/row", ctx0, keep0, k0, lab_cb, s0, t_load=128 * 5e-9)
            hf = head_skip_factor(ctx0.wl, s0["tile"])
            add("A1 + LM head only on 1+G tokens (core change)", dict(c, tok_s_die=c["tok_s_die"] * hf), lab_cb,
                f"R_c x {hf:.4f}; energy not re-scored")
            for n, tr in retention_table(s0["tile"]["cell"]["c_weight_fF"]).items():
                add_cb(f"A1 analog-stored weight, t_ret {n} = {tr * 1e6:.3g} us", ctx0, keep0, k0, lab_cb, s0,
                       t_ret=tr)
            sh, ksh, ctxsh = ev("stream_single", kv, dict(phy_d2d_mm2=2.35))   # 8 MB SRAM shadow area proxy
            add_cb("single bank + 8 MB SRAM-staged chunk shadow", ctxsh, model.operating_points(ctxsh)[1], ksh,
                   lab_cb + " (shadow area via phy_d2d_mm2 = 2.35; SRAM->array 10 TB/s projected)", sh,
                   staged=True, stage_Bps=10e12)
            # ---- memory-interface width (HBM channels of 16; PHY, BW and capacity scale together) ----
            for ch in (4, 6, 7, 8, 9, 10, 12):
                f = ch / 16
                sm, km, ctxm = ev("stream_single", kv, dict(phy_d2d_mm2=0.0, phy_hbm_mm2=12.0 * f),
                                  knob=dict(hbm_Bps=819e9 * f, hbm_bytes=24e9 * f))
                if not sm["peak"]:
                    add(f"HBM {ch}/16 channels", dict(tok_s_die=0, tops_w=0, tok_w=0), "projected", "infeasible")
                    continue
                add(f"HBM {ch}/16 channels (lockstep)", sm, "projected", f"B={sm['peak']['B']}")
                add_cb(f"HBM {ch}/16 channels +CB", ctxm, model.operating_points(ctxm)[1], km, lab_cb, sm)
            # ---- double buffer, partial, resident, hybrid, TP ----
            for nm, f in (("streaming double-buffered", 1.0), ("partial double buffer f=0.5", 0.5)):
                add(f"{nm} (analog-stored caps law)", dict(s, tok_s_die=s["tok_s_die"] * partial_db(s, f, 1)),
                    "projected (area law)", f"ratio {partial_db(s, f, 1):.3f}")
                add(f"{nm} (digitally-selected caps law)", dict(s, tok_s_die=s["tok_s_die"] * partial_db(s, f, 0)),
                    "projected (area law)", f"ratio {partial_db(s, f, 0):.3f}")
            sd, _, _ = ev("streaming", kv)
            add("streaming double-buffered (evaluator)", sd, "projected", f"B={sd['peak']['B']}")
            h = hybrid_bound(s, kv, k)
            add("hybrid hot-layers resident", dict(s, tok_s_die=s["tok_s_die"] * (1 + h["max_gain"])),
                "projected (upper bound)", f"phi={h['phi']:.2e} gain<= {h['max_gain']:.2e}")
            for N in (2, 4, 8):
                st, kt, ctxt = ev("stream_single", kv, system_dies=N)
                tp = tp_d2d(kt, N, kv)
                add(f"stream_tp{N} (lockstep)", st, "projected (ideal TP + analytic d2d)",
                    f"d2d {tp['bytes_per_token'] / 1e3:.0f} kB/tok, {tp['e_J_per_token'] * 1e6:.2f} uJ/tok, "
                    f"ceiling {tp['ceiling_tok_s']:.3g}")
                if N == 4:
                    add_cb("stream_tp4 +CB", ctxt, model.operating_points(ctxt)[1], kt, lab_cb, st)
        for kv in (16, 8, 4):
            sr, _, _ = ev("resident", kv)
            add(f"resident kv{kv}", sr, "projected", f"B={sr['peak']['B']} dies={sr['peak']['dies']}")
        for kv in (16, 8, 4):
            k = metric.knobs_for(conditions)
            k["kv_bits"] = kv
            for tag, extra in (("", {}), (" no-d2d", dict(phy_d2d_mm2=0.0))):
                sb, ctx, keep = _baseline(k, 4, extra)
                add(f"BASELINE W4 kv{kv}{tag} (lockstep)", sb, "projected (literature PE)")
                add_cb(f"BASELINE W4 kv{kv}{tag} +CB", ctx, keep, k, "projected (analytic, literature PE)", sb)
    else:
        s, k, ctx = ev("stream_single", 8)
        add("stream_single (lockstep)", s, "projected", f"B=1000 bind={s['binding']} die={k['die_mm2']:.1f} mm2")
        add_cb("stream_single +CB (throttled)", ctx, model.operating_points(ctx)[1], k, lab_cb, s)
        add_cb("stream_single +CB no interleave", ctx, model.operating_points(ctx)[1], k, lab_cb, s, interleave=False)
        for opt in ("streaming", "resident"):
            so, _, _ = ev(opt, 8)
            add(f"{opt} (lockstep)", so, "projected", f"dies={so['peak']['dies']}")
        h = hybrid_bound(s, 8, k)
        add("hybrid (upper bound)", dict(s, tok_s_die=s["tok_s_die"] * (1 + h["max_gain"])), "projected", f"phi={h['phi']:.2e}")
        sb, ctxb, keep = _baseline(k, metric.SOHU_WBITS, {})
        add("BASELINE W8 (lockstep)", sb, "projected (literature PE)")
        add_cb("BASELINE W8 +CB (throttled)", ctxb, keep, k, "projected (analytic, literature PE)", sb)
        # n7's fixed 8 MB buffer on a 1,121 mm2 die makes the spill dominate; the no-spill rows are
        # the critics' accounting (a Sohu-class die carries far more SRAM).
        add_cb("stream_single +CB (throttled, no spill)", ctx, model.operating_points(ctx)[1], k, lab_cb, s, spill=False)
        add_cb("BASELINE W8 +CB (throttled, no spill)", ctxb, keep, k, "projected (analytic, literature PE)", sb,
               spill=False)
    return rows


def _selfcheck():
    from arch_eval import design, metric, model
    freeze_others()
    d1 = design.make(dict(BASE, n1_system="stream_single"), {"kv_bits": 8})
    s1 = model.evaluate(d1)
    s2 = model.evaluate(design.make(dict(BASE, n1_system="streaming"), {"kv_bits": 8}))
    assert not s1["errors"], s1["errors"]
    assert s1["tok_s_die"] > 1.5 * s2["tok_s_die"], (s1["tok_s_die"], s2["tok_s_die"])
    k = dict(metric.KNOBS)
    ctx = model.Ctx(d1, k)
    keep = model.operating_points(ctx)[1]
    c = cb_score(ctx, keep, k)
    assert c["tok_s_die"] >= s1["tok_s_die"] * (1 - 1e-9) and c["per_stream_tok_s"] >= k["stream_floor_tok_s"], c
    assert c["tok_s_die"] <= s1["plan"]["compute_ceiling_tok_s"] * (1 + 1e-9)
    # throttling: a cap below the uncapped power must give a lower, still positive, rate at the cap
    tdp = keep[(0.7, 1.0)]
    free = continuous(ctx, *tdp, k)
    capd = continuous(ctx, *tdp, k, cap=0.5 * free["die_power_W"])
    assert 0 < capd["tok_s_die"] < free["tok_s_die"] and capd["die_power_W"] <= 0.5 * free["die_power_W"] * 1.001
    # retention binds: a 1 us hold cannot keep V t_pass ~ 100 us chunks alive
    assert cb_score(ctx, keep, k, t_ret=1e-6)["tok_s_die"] < 0.5 * c["tok_s_die"]
    assert 0.98 < partial_db(s1, 1.0, 0) <= 1.0 and partial_db(s1, 1.0, 1) < 0.6
    assert hybrid_bound(s1, 8, k)["max_gain"] < 0.01
    assert 1 < act_spill(ctx.wl, s1["tile"], s1["die"], 8e6, 1333) / 1e6 < 10   # MB/token, critic: ~3-5
    assert act_spill(ctx.wl, s1["tile"], s1["die"], 8e6, 100) == 0                # 100 vectors fit the buffer
    assert kv_on_die(k, 8) < 10                               # on-die KV: single-digit streams per die
    print("PASS n1_system self-check")


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    _selfcheck()                     # freezes n2..n10 for the study below
    from arch_eval import metric
    for cond in ("arch", "sohu"):
        print(f"== {cond}")
        for r in study(cond):
            print(f"{r['name']:<52} {r['tok_s_die']:9.0f} {r['tops_w']:6.2f} {r['tok_w']:7.1f} {r['tok_j']:7.1f}"
                  f"  [{r['label']}] {r['note']}")
    print("sohu die (sohu_area):", round(metric.sohu_area(), 1), "mm2")
    for n, um2 in (("SRAM", SRAM_UM2_PER_BIT), ("gain cell 2.5x denser", SRAM_UM2_PER_BIT / 2.5)):
        print(f"on-die KV8 streams/die, whole die {n}:", round(kv_on_die(metric.KNOBS, 8, um2), 2))
