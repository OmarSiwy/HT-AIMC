"""N7 dataflow & scheduling: the digital rail, the activation buffer, the on-die network, the PHYs,
and the schedule of prefill (GEMM) and decode (GEMV) on weight-stationary tiles.

Research write-up: docs/src/content/Project/ArchResearch/nodes/N7.md (option table, evidence).

Two halves:
  rail()      what the core (model.py) prices: rail area/rate/energy, buffer, PHY, NoC, leakage.
  schedule()  analytic schedules the core cannot express (continuous batching, activation
              residency of a streamed prefill, global-mesh cap, speculative decode, exiling hard
              layers to digital), computed on the core's own tile/die and scored by metric.score.

Rail equations (units in names; ASAP7 constants from asap7_constants.json via arch_eval.asap7):
  attention lane (Q x K/V MAC + 24-32 b accumulator), array-multiplier law (Multipliers notes:
  partial-product count ~ b_q b_kv):
      A_lane_um2 = (a_fix + a_mul (b_q b_kv / 64)) x rail_overhead
      E_lane_fJ  = (e_fix + e_mul (b_q b_kv / 64)) x e_scale(V)
      a_mul 25 um2, a_fix 55 um2, e_mul 50 fJ, e_fix 50 fJ: the INT8 PE of baseline_systolic.LIT
      (80 um2, 100 fJ at 1 GHz, 0.7 V; projected 7 nm literature) split into multiplier and the rest.
  att_mac_per_s = lanes x clk_GHz(V) x 1e9, lanes = headroom x demand / 1 GHz,
      demand = (att_prefill / (P w_macs)) x tile_tmacs_per_mm2 x die_mm2 + hbm_Bps (hq/hkv) 8 / kv_bits
      (rail_demand(); the core default 5.7 TMAC/s/mm2 = the W4 systolic baseline's peak die density
      (own_density, derived), the densest tile the rail must not throttle; the study passes each
      design's own density, so h is a multiple of its own demand; 8B/512: prefill share 0.92 %)
  lane width: (q_bits + pv_bits)/2 x kv_bits (mixed_rail: INT8 Q.K^T, 16 b P.V)
  rail_mm2 = lanes A_lane + exp_units A_exp + elem_lanes A_elem + rail_fixed_mm2 (sequencer, SIMD,
      KV staging, host I/O control)
  softmax exp: base-2 with log2(e)/sqrt(d) folded into the score scale (FloatingPointE digest #2),
      8-10 b direct ROM after max subtraction (Table-Based Function Evaluation, "plain ROM for
      <= 10 b"), online (m, l, o) merge, one reciprocal per row (Arithmetic for DL: Softmax Unit).
      E_exp ~ 100 fJ: ~120 DFF-equivalent toggles at 0.82 fJ (dff_energy_fJ, derived).
  per-pass buffer energy (blended over the core's buf_bytes = R ab/8 in + 2C out):
      e_in  = 8 (e_sram + e_wire_mm x mcast x pitch_mm) / mcast   [J/B, one SRAM read multicast
              to `mcast` column tiles that share the input rows; NoC digest: activation multicast]
      e_out = 8 e_wire_mm x cluster_mm + e_acc                     [psum to the cluster accumulator]
      e_wire_mm = wire_c_fF_per_um x 1000 x VDD^2 x alpha_01 0.25 x repeater 1.5   (derived, ORFS RC)
  HBM bytes cross the die: phy_J_per_bit = PHY + transport_mm x e_wire_mm (derived)
  leakage: measured RVT Ioff (nfet_ileak_per_fin_nA) x fin density (derived from NAND2 area);
      SRAM: nfet_ileak_per_fin_nA_sram x 3 fins per 6T cell.
  NoC: 2D mesh of tile clusters (one router per `cluster_mm`^2), router area law
      p V B w DFFs + p^2 w crosspoints (NoC digest §5); TDM circuit switching drops the VC buffers.
      Per-token inter-cluster transport (layer-boundary activations) is charged in e_elem_J.

Schedule equations (schedule(); core = model.system_point, "lockstep waves"):
  tokens per weight sweep:  lockstep prefill n = B P, decode n = B;  continuous n = B (P+G)/G
  activation working set per token ws = 2 d (16 b residual) + max_m K_m ab/8      [B]
  on-die residency: a sweep holds n tokens' inputs on die only if n ws <= buffer;
      else either split into ceil(n ws / buffer) sweeps (weights re-streamed), or spill:
      spill/token = sum_m r_m [ceil(N_m / (C g_m)) K_m + N_m] ab/8 + L 4 d,
      g_m = max(1, n_tiles // ceil(K_m / R))  (column groups the die holds at once, 27l7)
  phase time (_step): groups 0 = ideal max (the core), 1 = serial tile phase + attention phase,
      k >= 2 = k nano-batches interleaved (weights swept k times) + min(A, B)/(k L) fill;
      (1 - eta) of the hidden work leaks in every mode, lockstep and continuous alike
  ping-pong: second capture bank = pingpong_area_frac (2.5 %) of tile area, via tile_util
  NoC (mesh/tdm, tile < cluster): busiest link carries tiles_per_cluster x min(C psum_B, R ab/8)
      per pass; utilization > 1 stretches t_pass
  options: stagger (False: unstaged die-load fetch stalls), cal_frac (tile time lost), write_x,
      order (spill loop order), budget (Sarathi: 1/beta of steps carry beta x prefill),
      floor (tbt: 1/longest step; avg: G over the request's steps incl. its prefill step)
      hbm = sweeps w + B ctx_avg kv + B kv + (n - B) 2 kv + spill
  per-stream rate 1/T_step >= floor; KV paged (vLLM): B (P + (G+1)/2) kv + (n - B) kv + spill space
  global mesh (no locality): sum of per-pass bytes / s <= 2 x bisection = 4 sqrt(routers) link_Bps
  speculative decode: per step B (k+1) verify vectors, a accepted tokens per stream, KV read once.
Labels: every number is projected (laws on projected / measured-sky130 / measured-ASAP7-device
constants); the schedule overlay is derived from the core's projected tile/die.
"""
import math
import sys
from pathlib import Path

if __name__ == "__main__":   # run as a script: put scripts/compiler/metrics on the path first
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from arch_eval import asap7 as k  # noqa: E402

_LEAN = dict(
    rail="lanes", rail_headroom=1.25, tile_tmacs_per_mm2=5.7, q_bits=8, a_mul_um2=25.0, a_fix_um2=55.0, e_mul_fJ=50.0, e_fix_fJ=50.0,
    rail_overhead=2.0, rail_fixed_mm2=1.0, exp_per_lane=1 / 64, a_exp_um2=400.0, e_exp_fJ=100.0,
    elem_per_lane=1 / 16, a_elem_um2=100.0, e_elem_fJ=100.0, noc_hop_mm=3.0,
    buffer_MB=2.0, e_sram_fJ_per_bit=15.0, mcast=8, tile_pitch_mm=0.18, cluster_mm=0.5, e_acc_fJ_per_B=12.0,
    phy_hbm_mm2=12.0, phy_d2d_mm2=4.0, phy_host_mm2=1.0, phy_pJ_per_bit=0.4, transport_mm=5.0,
    hop_ns=20.0, noc="mesh", noc_ports=5, noc_vcs=2, noc_depth=4, noc_flit_bits=128,
    tile_util=0.85, pingpong=True, pingpong_area_frac=0.025, psum_bytes=3)
OPTIONS = {
    "lean_int8_rail": dict(params=dict(_LEAN), provenance=(
        "projected (N7.md): INT8 attention lanes sized to ~1 % of the weight-MAC rate (27l2 I_KV=1, "
        "APPLICATION_ATTENTION), base-2 table exp + online softmax (FloatingPointE, Table-Based), "
        "multicast clustered buffer + local psum reduction (NoC digest), mesh NoC; MAC from "
        "baseline_systolic.LIT, wire from ORFS RC, leakage from measured ASAP7 Ioff")),
    "digital_rail": dict(params=dict(rail="frac", rail_frac=0.10, rail_mac_per_s_per_mm2=2e12, e_att_mac_pJ=0.4,
                                     e_exp_pJ=5.0, e_elem_pJ=0.3, buffer_MB=8.0, e_buf_pJ_per_byte=0.5,
                                     phy_hbm_mm2=12.0, phy_d2d_mm2=4.0, phy_pJ_per_bit=0.5,
                                     hop_ns=20.0, logic_leak_W_per_mm2=0.02, tile_util=0.85,
                                     pingpong=True),
                         provenance="projected: shipped default (10 % of die, FP16-class literature); "
                                    "dominated: 5-10x oversized for the attention demand (N7.md)"),
    "fp16_rail": dict(params=dict(_LEAN, q_bits=16, kv_force_bits=16, e_exp_fJ=300.0, e_elem_fJ=300.0),
                      provenance="projected: Hermes-style FP16 rail (27l11); 16x16 lanes regardless of KV format"),
    "mixed_rail": dict(params=dict(_LEAN, pv_bits=16),
                       provenance="projected: INT8 Q.K^T lanes + 16 b P.V lanes (SageAttention v1 keeps "
                                  "P.V in FP16; v2 FP8) — a quality hedge for N8"),
    "lns_rail": dict(params=dict(_LEAN, a_mul_um2=60.0, e_mul_fJ=120.0, e_exp_fJ=20.0),
                     provenance="projected: LNS rail (NumberFormats digest): exp/div become shifts, "
                                "but every attention add needs a Gaussian-log table (f+ table)"),
    "tdm_noc": dict(params=dict(_LEAN, noc="tdm"),
                    provenance="projected: compile-time TDM circuit-switched fabric + scavenger VC "
                               "for KV (NoC digest, TDM Slot Table Scheduler)"),
    "unicast_buffer": dict(params=dict(_LEAN, mcast=1),
                           provenance="projected: no activation multicast (every tile reads its own input)"),
    "no_pingpong": dict(params=dict(_LEAN, pingpong=False),
                        provenance="projected: serial integrate-then-convert (REPO-A: ping-pong measured "
                                   "1.339x interval on sky130, +2.4 % energy)"),
    "global_mesh": dict(params=dict(_LEAN, noc="global_mesh"),
                        provenance="projected: every tile pass's inputs/psums cross one die-wide mesh "
                                   "(NoC digest derived ceiling); cap applied in schedule() only"),
}
DEFAULT = "lean_int8_rail"
SWEEP = dict(rail_headroom=[0.5, 1.0, 1.25, 2.0], buffer_MB=[2, 8, 16, 32, 64], mcast=[1, 4, 8, 16])


def e_wire_fJ_per_bit_mm(vdd):
    """Repeated full-swing signal wire: C V^2 per 0->1 edge, alpha_01 = 0.25 for random data,
    repeaters x1.5 (derived from ORFS RC; 32 fJ/bit/mm at 0.7 V)."""
    return k.get("wire_c_fF_per_um") * 1000 * vdd ** 2 * 0.25 * 1.5   # alpha_0->1 = 0.25 (random data)


def _noc_mm2(p, die_mm2):
    routers = die_mm2 * 0.6 / p["cluster_mm"] ** 2
    w, ports = p["noc_flit_bits"], p["noc_ports"]
    bufs = 0 if p["noc"] == "tdm" else ports * p["noc_vcs"] * p["noc_depth"] * w
    regs = ports * w + (64 * ports * 3 if p["noc"] == "tdm" else 0)       # output regs (+ TDM slot table)
    um2 = ((bufs + regs) * k.get("dff_area_um2") + ports ** 2 * w * 2 * k.get("nand2_area_um2")) / 0.7
    return routers * um2 / 1e6, routers


def rail_demand(p, knobs, kv_bits):
    """Attention MAC/s the rail must sustain so it never caps tok/s [MAC/s at 1 GHz-class lanes]:
    prefill share of the densest tile's weight-MAC rate + decode attention at the HBM KV rate
    (27l2: I_KV = 1 MAC per KV element per query head; GQA gives hq/hkv MACs per element)."""
    from arch_eval import workload
    wl = workload.llama3(knobs.get("model", "8B-class"), prompt=knobs["prompt"], gen=knobs["gen"], kv_bits=kv_bits)
    m = wl["model"]
    pre = wl["att_macs_prefill"] / (wl["prompt"] * wl["weight_macs_per_token"])
    dec = knobs["hbm_Bps"] * (m["hq"] / m["hkv"]) * 8 / kv_bits
    return pre * p["tile_tmacs_per_mm2"] * 1e12 * knobs["die_mm2"] + dec


def rail(p, vdd, op, knobs):
    if p.get("rail", "frac") == "frac":
        return _legacy(p, vdd, op, knobs)
    e = op["e_scale"]
    kvb = int(p.get("kv_force_bits") or knobs.get("kv_bits") or p.get("kv_bits", 16))
    pp = (p["q_bits"] + p.get("pv_bits", p["q_bits"])) * kvb / 128    # QK^T lane + P.V lane, averaged
    lane_um2 = (p["a_fix_um2"] + p["a_mul_um2"] * pp) * p["rail_overhead"]
    lanes = int(p.get("rail_lanes") or rail_demand(p, knobs, kvb) * p["rail_headroom"] / 1e9)
    rail_mm2 = (lanes * lane_um2 + lanes * p["exp_per_lane"] * p["a_exp_um2"]
                + lanes * p["elem_per_lane"] * p["a_elem_um2"]) / 1e6 + p["rail_fixed_mm2"]
    sram_mm2 = p["buffer_MB"] * 8 * 2 ** 20 * k.get("sram6t_bitcell_um2") * 1.5 / 1e6
    need_d2d = p.get("mode") == "resident" or int(knobs.get("system_dies", 1)) > 1
    noc_mm2, routers = _noc_mm2(p, knobs["die_mm2"])
    area = dict(rail=rail_mm2, buffer=sram_mm2, noc=noc_mm2,
                phy=p["phy_hbm_mm2"] + p["phy_host_mm2"] + (p["phy_d2d_mm2"] if need_d2d else 0.0))
    ew = e_wire_fJ_per_bit_mm(vdd)
    e_in = 8 * (p["e_sram_fJ_per_bit"] * e + ew * p["mcast"] * p["tile_pitch_mm"]) / p["mcast"]
    e_out = 8 * ew * p["cluster_mm"] + p["e_acc_fJ_per_B"] * e
    r_in = p.get("rows", 128) * p.get("abits", 8) / 8
    r_out = 2 * p.get("cols", 64)
    e_buf = (r_in * e_in + r_out * e_out) / (r_in + r_out)
    # per-token NoC transport of layer-boundary activations, amortized over the elementwise op count
    from arch_eval import workload
    m = workload.MODELS[knobs.get("model", "8B-class")]
    wl_d, wl_f, L = m["d"], m["f"], m["layers"]
    act_B = L * (3 * wl_d + 2 * 1024 + 2 * wl_f + wl_d) * p.get("abits", 8) / 8
    elem_ops = L * (10 * wl_d + 3 * wl_f)
    e_elem = p["e_elem_fJ"] * e + act_B * 8 * ew * p["noc_hop_mm"] / elem_ops
    v0 = k.get("vdd_nom")    # W/mm2 at VDD_nom: half of ~8 fins per NAND2 footprint off, 70 % placement
    leak_logic = 0.5 * k.get("nfet_ileak_per_fin_nA") * 1e-9 * v0 * 8 / k.get("nand2_area_um2") * 1e6 * 0.7
    leak_sram = 3 * k.get("nfet_ileak_per_fin_nA_sram") * 1e-9 * v0 / k.get("sram6t_bitcell_um2") * 1e6
    return dict(area_mm2=area, att_mac_per_s=lanes * op["clk_GHz"] * 1e9,
                e_att_mac_J=(p["e_fix_fJ"] + p["e_mul_fJ"] * pp) * e * 1e-15, e_exp_J=p["e_exp_fJ"] * e * 1e-15,
                e_elem_J=e_elem * 1e-15, e_buf_J_per_byte=e_buf * 1e-15,
                phy_J_per_bit=p["phy_pJ_per_bit"] * 1e-12 + p["transport_mm"] * ew * 1e-15,
                hop_s=p["hop_ns"] * 1e-9,
                leak_W=((rail_mm2 + noc_mm2) * leak_logic + sram_mm2 * leak_sram) * op["leak_scale"],
                # ping-pong second capture bank (12j: 2x the capture element) charged as tile area:
                # half the frozen tile's ADC area (4.9 %) = 2.5 % (derived); 0 if it is the SAR's own CDAC
                tile_util=p["tile_util"] / (1 + p.get("pingpong_area_frac", 0.0) * bool(p["pingpong"])),
                pingpong=bool(p["pingpong"]),
                lane_um2=lane_um2, kv_bits=kvb, e_in_fJ_per_B=e_in, e_out_fJ_per_B=e_out, routers=routers)


def _legacy(p, vdd, op, knobs):
    """The shipped default, unchanged (kept so the old numbers stay reproducible)."""
    e = op["e_scale"]
    sram_mm2 = p["buffer_MB"] * 8 * 2 ** 20 * k.get("sram6t_bitcell_um2") * 1.5 / 1e6
    area = dict(rail=p["rail_frac"] * knobs["die_mm2"], buffer=sram_mm2,
                phy=p["phy_hbm_mm2"] + p["phy_d2d_mm2"])
    return dict(area_mm2=area, att_mac_per_s=area["rail"] * p["rail_mac_per_s_per_mm2"] * op["clk_GHz"],
                e_att_mac_J=p["e_att_mac_pJ"] * e * 1e-12, e_exp_J=p["e_exp_pJ"] * e * 1e-12,
                e_elem_J=p["e_elem_pJ"] * e * 1e-12, e_buf_J_per_byte=p["e_buf_pJ_per_byte"] * e * 1e-12,
                phy_J_per_bit=p["phy_pJ_per_bit"] * 1e-12, hop_s=p["hop_ns"] * 1e-9,
                leak_W=(area["rail"] + area["buffer"]) * p["logic_leak_W_per_mm2"] * op["leak_scale"],
                tile_util=p["tile_util"], pingpong=bool(p["pingpong"]))


# --------------------------------------------------------------------------------------------
# Schedule overlay. ponytail: re-derives model.system_point's resource terms because the core
# exposes only the binding max; ask the core for a per-resource hook and delete the copy.
# --------------------------------------------------------------------------------------------

def ws_bytes(wl, abits):
    """Activation working set per token that one weight sweep needs on die [B]."""
    return 2 * wl["model"]["d"] + max(a for a, _, _ in wl["matrices"]) * abits / 8


def spill_bytes(wl, t, n_tiles, abits, order="input", psum_B=3):
    """HBM bytes per token when the working set lives in HBM instead of SRAM. Loop orders:
    input  27l7 K-complete column groups g on die: the input is re-read once per group load
    output K-slabs of h row tiles over all N columns: input read once per column chunk, psums
           (psum_B bytes) written and read back between slabs
    best   the cheaper order per matrix (a compiler choice)."""
    R, C, L, dm = t["rows"], t["cols"], wl["model"]["layers"], wl["model"]["d"]
    s = 0.0
    for a, b, r in wl["matrices"]:
        g = max(1, n_tiles // -(-a // R))
        inp = (-(-b // (C * g)) * a + b) * abits / 8
        cb = -(-b // C)
        slabs = -(-a // (R * max(1, n_tiles // cb)))
        out = -(-cb // n_tiles) * a * abits / 8 + b * abits / 8 + (slabs - 1) * 2 * b * psum_B
        s += r * {"input": inp, "output": out}.get(order, min(inp, out))
    return s + L * 4 * dm


def _step(res, s, L):
    """One phase's time from its per-resource times [s] -> (T, binding).
    groups 0   ideal: every resource overlaps (the core's max; ignores the per-layer
               QKV -> attention -> O dependency, so it is a roofline, not a schedule)
    groups 1   dependency-honest serial: per layer the tile phase A = max(compute, weight+spill HBM)
               and the attention phase B = max(rail, KV HBM) alternate: T = A + B
    groups k   k nano-batches interleaved (NanoFlow; DeepSeek two-micro-batch overlap): one group
               attends while another uses the tiles, HBM shared: T = max(compute, rail, HBM) +
               min(A, B)/(k L) pipeline fill; the caller charges the weights k times
    overlap_eff eta: (1 - eta) of every hidden term leaks into T (applied to every mode)."""
    k, eta = s.get("groups", 0), s.get("overlap_eff", 1.0)
    c, w, kv, att, d2d, lat = (res[x] for x in ("compute", "w_hbm", "kv_hbm", "attention", "d2d", "latency"))
    if k == 1:
        top = max(max(c, w) + max(att, kv), d2d, lat)
        hidden, bind = min(c, w) + min(att, kv), f"serial {'compute' if c >= w else 'hbm'}+{'rail' if att >= kv else 'kv'}"
    else:
        terms = dict(compute=c, hbm=w + kv, attention=att, d2d=d2d, latency=lat)
        top = max(terms.values())
        hidden, bind = c + w + kv + att - top, max(terms, key=terms.get)
        if k > 1:
            top += min(max(c, w), max(att, kv)) / (k * L)
    return top + (1 - eta) * max(0.0, hidden), bind


def _point(ctx, t, d, plan, B, s):
    kn, wl, rail, p = ctx.knobs, ctx.wl, t["rail"], ctx.p
    D, streaming = plan["dies"], plan["mode"] == "streaming"
    nd = int(kn.get("system_dies", 1))
    G, P, need, L = wl["gen"], wl["prompt"], d["tiles_needed"], wl["model"]["layers"]
    kvb = wl["kv_bytes_per_token"]
    w_bytes = wl["stored_weights"] * t["wbits"] / 8
    ctx_avg = wl["ctx_decode_sum"] / G
    hbm_Bps, att_rate = D * nd * kn["hbm_Bps"], D * nd * rail["att_mac_per_s"]
    ab, wmac = t["fmt"]["abits"], wl["weight_macs_per_token"]
    db = bool(p.get("double_buffer"))
    phi, cal, kg = s.get("exile", 0.0), s.get("cal_frac", 0.0), max(1, s.get("groups", 0))
    t_pass, link_util = t["t_pass_s"], 0.0
    link = p.get("noc_flit_bits", 128) / 8 * t["op"]["clk_GHz"] * 1e9
    if p.get("noc") == "global_mesh":               # uniform-traffic cap, NoC digest lambda_max
        bpp = t["rows"] * ab / 8 + 2 * t["cols"]
        t_pass = max(t_pass, d["n_tiles"] * bpp / (4 * math.sqrt(rail.get("routers", 400)) * link))
    elif p.get("noc") in ("mesh", "tdm") and t["area_um2"] < p["cluster_mm"] ** 2 * 1e6:
        # busiest inter-cluster link, cheaper of two mappings: cluster = column tiles of one K-block
        # (input multicast, psum chain out: C psum_B per tile) or K-blocks of one column (psums reduced
        # in cluster, inputs in: R ab/8 per tile). A tile larger than a cluster has its own port.
        tpc = p["cluster_mm"] ** 2 * 1e6 // t["area_um2"]
        link_util = tpc * min(t["cols"] * p.get("psum_bytes", 3), t["rows"] * ab / 8) / t_pass / link
        t_pass *= max(1.0, link_util)
    buf = p.get("buffer_MB", 8) * 2 ** 20
    order = s.get("order", "input")
    ws, sp_tok = ws_bytes(wl, ab), spill_bytes(wl, t, d["n_tiles"], ab, order, p.get("psum_bytes", 3))
    loads = -(-need // (nd * d["n_tiles"]))
    # no staggered reload: each die-load of weights is fetched after the previous one ends; what the
    # buffer cannot stage stalls the tiles (lead assumes round-robin staggered reloads: 0)
    stall = 0.0 if s.get("stagger", True) else max(0.0, d["n_tiles"] * t["macs_per_pass"] * t["wbits"] / 8 - buf) / hbm_Bps

    def sweep(n):                                   # one pass of all weights over n vectors
        if streaming:
            return loads * ((max(t["t_load_s"], n * t_pass) if db else t["t_load_s"] + n * t_pass) * (1 - phi) + stall)
        return n * t_pass / max(1, D * nd * d["n_tiles"] // need) * (1 - phi)

    def residency(n, b):                            # -> list of (sweeps, spill bytes, spill space)
        if not streaming or s["act"] == "free":
            return [(1, 0.0, 0.0)]
        sram = (max(1, math.ceil(n * ws / b)), 0.0, 0.0)
        spill = (1, n * sp_tok, n * ws)
        return {"sram": [sram], "spill": [spill]}.get(s["act"], [sram, spill])

    def phase(n, kv, att, lat):                     # -> (T, sweeps, spill bytes, space, binding)
        best = None
        for sw, sp, sx in residency(n / kg, buf / kg):   # kg groups share the buffer, each sweeps weights
            sw, sp, sx = sw * kg, sp * kg, sx * kg
            res = dict(compute=sw * sweep(n / sw) / (1 - cal),
                       w_hbm=((sw * w_bytes if streaming else 0) + sp) / hbm_Bps, kv_hbm=kv / hbm_Bps,
                       attention=(att + phi * n * wmac) / att_rate, d2d=d2d(n), latency=lat)
            T, bind = _step(res, s, L)
            if best is None or T < best[0]:
                best = (T, sw, sp, sx, bind)
        return best

    lat_one = wl["stages"] * (t.get("t_stage_s", t_pass) + (rail["hop_s"] if D > 1 else 0))
    d2d = lambda n: n * wl["act_bytes_per_token"] * (D - 1) / (D * kn["d2d_Bps"])  # noqa: E731
    one_att = wl["att_macs_per_ctx"] * ctx_avg / att_rate
    spec = s.get("spec")
    tbt = s.get("floor", "tbt") == "tbt"            # per-stream floor: time between tokens, or request average
    if s["mode"] == "lockstep":
        pre = phase(B * P, 2 * B * P * kvb, B * wl["att_macs_prefill"], lat_one + P * t_pass)
        dec = phase(B, B * (ctx_avg + 1) * kvb, B * wl["att_macs_per_ctx"] * ctx_avg, lat_one + one_att)
        T_step, T = dec[0], pre[0] + G * dec[0]
        sweeps = pre[1] + G * dec[1]
        hbm = sweeps * w_bytes * streaming + 2 * B * P * kvb + G * B * (ctx_avg + 1) * kvb + pre[2] + G * dec[2]
        space, bind = max(pre[3], dec[3]), dict(prefill=pre[4], decode=dec[4])
        att_macs = B * (wl["att_macs_prefill"] + wl["att_macs_decode"])
        vectors, n_hi = B * (P + G), B
        rate = 1 / T_step if tbt else G / T
    else:
        a, kq, ks, dr = (spec["accept"], spec["k"] + 1, spec["k"], spec["draft_frac"]) if spec else (1.0, 1, 0, 0.0)
        n_pre = B * a * P / G                       # steady state: prefill tokens per step keep B streams full
        beta = max(1.0, s.get("budget", 1.0))       # Sarathi budget: 1/beta of steps carry beta x n_pre

        def cstep(npre):
            n = B * kq + npre + B * ks * dr
            kv = B * ctx_avg * kvb + B * a * kvb + npre * 2 * kvb
            att = B * kq * wl["att_macs_per_ctx"] * ctx_avg + npre / P * wl["att_macs_prefill"]
            return phase(n, kv, att, lat_one + one_att), n, kv
        parts = [(1 / beta, cstep(n_pre * beta))] + ([(1 - 1 / beta, cstep(0.0))] if beta > 1 else [])
        T_step = sum(w * ph[0] for w, (ph, _, _) in parts)
        sw = sum(w * ph[1] for w, (ph, _, _) in parts)
        sp = sum(w * ph[2] for w, (ph, _, _) in parts)
        space, bind = max(ph[3] for _, (ph, _, _) in parts), parts[0][1][0][4]
        n_vec, kvs = sum(w * n for w, (_, n, _) in parts), sum(w * kv for w, (_, _, kv) in parts)
        n_hi = max(n for _, (_, n, _) in parts)
        steps = G / a
        T, sweeps = steps * T_step, steps * sw
        hbm = steps * ((sw * w_bytes if streaming else 0) + kvs + sp)
        att_macs = B * (wl["att_macs_prefill"] + kq / a * wl["att_macs_decode"])
        vectors = steps * n_vec
        rate = a / max(ph[0] for _, (ph, _, _) in parts) if tbt else G / ((steps + 1) * T_step)
    tokens = B * (P + G)
    e_x = rail["e_att_mac_J"]
    if phi:                                         # exiled weight MACs run W x A lanes, not Q x KV
        pp = (p["q_bits"] + p.get("pv_bits", p["q_bits"])) * rail["kv_bits"] / 128
        e_x *= (p["e_fix_fJ"] + p["e_mul_fJ"] * t["wbits"] * ab / 64) / (p["e_fix_fJ"] + p["e_mul_fJ"] * pp)
    e = dict(weight_passes=vectors * need * t["e_pass_J"] * (1 - phi) + phi * vectors * wmac * e_x,
             weight_write=sweeps * need * t["write_bits_per_load"] * t["e_write_J_per_bit"] * s.get("write_x", 1.0)
             if streaming else 0.0,
             attention=att_macs * rail["e_att_mac_J"]
             + B * (wl["softmax_exps_prefill"] + wl["softmax_exps_decode"]) * rail["e_exp_J"],
             elementwise=tokens * wl["elem_ops_per_token"] * rail["e_elem_J"],
             hbm_phy=hbm * 8 * rail["phy_J_per_bit"],
             d2d=tokens * wl["act_bytes_per_token"] * 8 * (D - 1) * kn["d2d_pJ_per_bit"] * 1e-12,
             static=D * nd * d["static_W"] * T)
    e_die, e_ext = sum(e.values()), hbm * 8 * kn["hbm_pJ_per_bit"] * 1e-12
    cap = (nd * kn["hbm_bytes"] - w_bytes - wl["embed_bytes"]) if streaming else (D * nd * kn["hbm_bytes"] - wl["embed_bytes"])
    kv_need = B * (P + G) * kvb if s["mode"] == "lockstep" or not s.get("paged", True) \
        else B * (P + (G + 1) / 2) * kvb + (n_hi - B) * kvb
    useful = B * (wl["tokens"] * wmac + wl["att_macs_prefill"] + wl["att_macs_decode"])
    return dict(B=B, dies=D, mode=plan["mode"], vdd=t["op"]["vdd"], clk_frac=t["op"]["clk_frac"],
                tok_s_die=tokens / T / (D * nd), gen_tok_s_die=B * G / T / (D * nd),
                die_power_W=e_die / T / (D * nd), ext_power_W=e_ext / T / (D * nd),
                useful_macs_s_die=useful / T / (D * nd), per_stream_tok_s=rate,
                kv_ok=kv_need + space <= cap, quality_ok=t["quality"]["passed"], binding=bind,
                T_step_s=T_step, sweeps_per_wave=sweeps, hbm_GB_per_wave=hbm / 1e9, link_util=link_util,
                b_kv=int(cap // (kvb * (P + G))))


FROZEN = ("n7_dataflow",)   # study context: every other node on its frozen default (nodes/default/)


def make_ctx(design=None, knobs=None, live=None):
    """model.Ctx, optionally with every node not in `live` replaced by its frozen default
    (the other nodes are being rewritten concurrently; a frozen context keeps N7's comparison
    stable). live=None = the core's own loading."""
    from arch_eval import design as dz, model, workload
    from arch_eval.design import NODES
    design = design or dz.make()
    ctx = model.Ctx(design, knobs)
    if live is None:
        return ctx
    p = {}
    for nid in NODES:
        if nid not in live:
            ctx.mods[nid] = ctx.defaults[nid]
        m, d = ctx.mods[nid], ctx.defaults[nid]
        opt = design["nodes"].get(nid, m.DEFAULT)
        ctx.options[nid] = opt if opt in m.OPTIONS else m.DEFAULT
        p.update(d.OPTIONS[d.DEFAULT]["params"])
        p.update(m.OPTIONS[ctx.options[nid]]["params"])
    p.update(design["params"])
    ctx.p = p
    ctx.wl = workload.llama3(ctx.knobs.get("model", "8B-class"), prompt=ctx.knobs["prompt"], gen=ctx.knobs["gen"],
                             kv_bits=int(ctx.knobs.get("kv_bits") or p.get("kv_bits", 16)))
    return ctx


def _grid(ctx, tile_fn):
    from arch_eval import model
    vdds = [v for v in model.SWEEP_VDD if ctx.knobs["vdd_min"] <= v <= ctx.knobs["vdd_max"]]
    for v in vdds:
        for f in model.SWEEP_CLK:
            t = tile_fn(ctx, v, f) if tile_fn else model.tile(ctx, v, f)
            d = model.die(ctx, t)
            if d["n_tiles"] < 1:
                continue
            plan = dict(mode="streaming", dies=1) if tile_fn else ctx.call("n1_system", "plan", ctx.wl, t, d, ctx.knobs)
            yield v, f, t, d, plan


def core(design=None, knobs=None, live=None, tile_fn=None):
    """The core's own lockstep score (model.system_point + model.b_sweep) on make_ctx(live)."""
    from arch_eval import metric, model
    ctx = make_ctx(design, knobs, live)
    pts, keep = [], {}
    for v, f, t, d, plan in _grid(ctx, tile_fn):
        keep[(v, f)] = (t, d, plan)
        pts += model.b_sweep(ctx, t, d, plan)
    sc = metric.score(pts, ctx.knobs)
    if sc["peak"]:
        sc["tile"], sc["die"], sc["plan"] = keep[(sc["peak"]["vdd"], sc["peak"]["clk_frac"])]
    sc["errors"] = ctx.errors
    return sc


def own_density(design=None, knobs=None, live=None, tile_fn=None):
    """Peak weight-MAC rate per die mm2 [TMAC/s/mm2] of this design over the VDD/clock grid: what
    rail_demand should see as tile_tmacs_per_mm2 (rail() cannot see the tile; core contract)."""
    ctx = make_ctx(design, knobs, live)
    return max(d["mac_rate"] for _, _, _, d, _ in _grid(ctx, tile_fn)) / ctx.knobs["die_mm2"] / 1e12


def schedule(design=None, knobs=None, tile_fn=None, live=None, **s):
    """Score `design` under an analytic schedule. s: mode = lockstep | continuous, act = free (core
    assumption) | sram | spill | auto, paged (bool), overlap_eff, spec = {k, accept, draft_frac},
    exile (fraction of weight MACs moved to rail lanes; caller adds the lanes via rail_lanes).
    tile_fn(ctx, vdd, clk) replaces model.tile (e.g. baseline_systolic.tile). -> metric.score dict."""
    from arch_eval import metric
    s = dict(dict(mode="continuous", act="auto", paged=True, overlap_eff=1.0), **s)
    ctx = make_ctx(design, knobs, live)
    pts, keep = [], {}
    for v, f, t, d, plan in _grid(ctx, tile_fn):
        keep[(v, f)] = (t, d, plan)
        if ctx.knobs.get("batch"):
            bs = [int(ctx.knobs["batch"])]
        else:
            bm = _point(ctx, t, d, plan, 1, s)["b_kv"] * (2 if s["mode"] == "continuous" else 1)
            bs = sorted({2 ** i for i in range(int(math.log2(max(1, bm))) + 1)} | {max(1, bm)}
                        | {max(1, int(bm * i / 64)) for i in range(1, 65)})
        pts += [_point(ctx, t, d, plan, b, s) for b in bs]
    sc = metric.score(pts, ctx.knobs)
    if sc["peak"]:
        sc["tile"], sc["die"], sc["plan"] = keep[(sc["peak"]["vdd"], sc["peak"]["clk_frac"])]
    sc["errors"] = ctx.errors
    return sc


def disaggregated(pre, dec):
    """Prefill dies + decode dies, each iso-area: tok/s per die = (P+G) / (P/X_pre + G/X_dec),
    X_pre = prompt tok/s of a die doing only prefill, X_dec = generated tok/s of a die doing only decode."""
    return 640 / (512 / pre + 128 / dec)


# --------------------------------------------------------------------------------------------
# Study: every option, scored with the evaluator (core) and the overlay.
# --------------------------------------------------------------------------------------------

LEAD = dict(mode="continuous", act="auto", groups=2, overlap_eff=0.85)   # the lead schedule (N7.md)
H_OWN, MB = (0.5, 1.0, 1.5, 2.0, 3.0), (2, 4, 8, 16, 32)


def study(conditions="arch", verbose=False, live=FROZEN):
    """Score every N7 option on a context where every other node is frozen (live=FROZEN).
    Rail headroom h is a multiple of the design's OWN peak demand (own_density) unless noted."""
    from arch_eval import baseline_systolic, design as dz, metric
    rows = []
    arch = conditions == "arch"

    def kn(kv=8, **o):
        return dict(metric.knobs_for(conditions, kv_bits=kv) if arch else metric.knobs_for(conditions), **o)

    def row(name, sc, label, note=""):
        pk, t = sc.get("peak") or {}, sc.get("tile") or {}
        bits = t.get("wbits", 0) * (t.get("fmt") or {}).get("abits", 0)
        rows.append(dict(name=name, tok_s_die=sc["tok_s_die"], tops_w=sc["tops_w"], tok_w=sc["tok_w"],
                         tok_j=sc["tok_j"], tops_w_1b=sc["tops_w"] * bits, label=label, note=note,
                         B=pk.get("B"), bind=pk.get("binding"), per_stream=pk.get("per_stream_tok_s"),
                         power=pk.get("die_power_W"), link=pk.get("link_util")))
        if verbose:
            r = rows[-1]
            print(f"{name:<52} {r['tok_s_die']:9.0f} {r['tops_w']:6.2f} {r['tok_w']:7.1f} {r['tok_j']:7.1f}"
                  f" 1b={r['tops_w_1b']:6.0f} B={r['B']} P={r['power'] or 0:.1f}W link={r['link'] or 0:.2f}"
                  f" ps={r['per_stream'] or 0:.1f} {r['bind']} | {note}", flush=True)

    def sized(nodes, params, kk, tf=None):
        """design with the rail sized against its own peak MAC density (h = rail_headroom)."""
        d = dz.make(nodes, params)
        dens = own_density(dz.make(nodes, dict(params, rail_headroom=1.0)), kk, live, tf)
        return dz.make(nodes, dict(params, tile_tmacs_per_mm2=dens))

    def best(opt, sched=None, kvs=(8,), grid=None, extra=None, tf=None, db=False, kk_over=None):
        """Best design reachable with N7 option `opt` (stream_single, KV and rail sizing free)."""
        cands = []
        if grid is None:
            grid = [{}] if OPTIONS[opt]["params"].get("rail") == "frac" else [
                dict(rail_headroom=h, buffer_MB=mb) for h in H_OWN for mb in MB]
        for kv in (kvs if arch else (8,)):
            kk = kn(kv, **(kk_over or {}))
            for g in grid:
                nodes = {"n1_system": "streaming", "n7_dataflow": opt}
                pr = dict({"kv_bits": kv, "double_buffer": db}, **g, **(extra or {}))
                d = sized(nodes, pr, kk, tf) if OPTIONS[opt]["params"].get("rail") != "frac" else dz.make(nodes, pr)
                sc = schedule(d, kk, tf, live, **sched) if sched else core(d, kk, live, tf)
                tag = " ".join(f"{a}={b}" for a, b in dict(g, **(extra or {})).items())
                cands.append((metric.key(sc), sc, f"kv{kv} {tag}"))
        c = max(cands, key=lambda x: x[0])
        return c[1], c[2]

    L = dict(LEAD) if arch else dict(LEAD, mode="lockstep")
    lc, lo = "projected (core evaluator, ideal overlap)", "projected (N7 overlay on core tile)"
    for opt in OPTIONS:
        sc, how = best(opt)
        row(f"{opt} | core lockstep", sc, lc, how)
    for mode in ("continuous", "lockstep"):
        for g, eta in ((0, 1.0), (0, 0.85), (1, 1.0), (1, 0.85), (2, 1.0), (2, 0.85), (2, 0.7), (4, 0.85)):
            sc, how = best("lean_int8_rail", dict(mode=mode, act="auto", groups=g, overlap_eff=eta))
            row(f"lean | {mode} groups {g} eta {eta}", sc, lo, how)
    for act in ("free", "sram", "spill"):
        sc, how = best("lean_int8_rail", dict(L, act=act))
        row(f"lean | lead sched, act {act}", sc, lo, how)
    for order in ("output", "best"):
        sc, how = best("lean_int8_rail", dict(L, order=order))
        row(f"lean | lead sched, loop order {order}", sc, lo, how)
    for name, o in (("no paged KV", dict(paged=False)), ("no staggered reload", dict(stagger=False)),
                    ("calibration 1 % of tile time", dict(cal_frac=0.01)),
                    ("weight write x100 (DAC write)", dict(write_x=100.0)),
                    ("floor = request average", dict(floor="avg"))):
        sc, how = best("lean_int8_rail", dict(L, **o))
        row(f"lean | lead sched, {name}", sc, lo, how)
    for beta in (2, 4, 16):
        sc, how = best("lean_int8_rail", dict(L, mode="continuous", budget=beta))
        row(f"lean | continuous, Sarathi budget beta {beta}", sc, lo, how)
    for mb in (0.5, 2, 8, 32, 128):
        sc, how = best("lean_int8_rail", L, grid=[dict(buffer_MB=mb, rail_headroom=h) for h in H_OWN])
        row(f"lean | lead sched, buffer {mb} MB", sc, lo, how)
    for h in (0.25,) + H_OWN:
        sc, how = best("lean_int8_rail", L, grid=[dict(buffer_MB=mb, rail_headroom=h) for mb in MB])
        row(f"lean | lead sched, rail h {h} x own demand", sc, lo, how)
    for tu in (0.80, 0.90, 0.95):
        sc, how = best("lean_int8_rail", L, extra=dict(tile_util=tu))
        row(f"lean | lead sched, tile_util {tu}", sc, lo, how)
    for fl in (256,):
        sc, how = best("lean_int8_rail", L, extra=dict(noc_flit_bits=fl))
        row(f"lean | lead sched, {fl} b NoC links", sc, lo, how)
    for opt in [o for o in OPTIONS if o != "lean_int8_rail"]:
        sc, how = best(opt, L)
        row(f"{opt} | lead sched", sc, lo, how)
    sc, how = best("lean_int8_rail", dict(L, spec=dict(k=3, accept=2.5, draft_frac=0.05)))
    row("lean | lead sched + speculative decode", sc, "projected (literature acceptance; changes the workload)", how)
    for phi in (0.02, 0.10):
        sc, how = best("lean_int8_rail", dict(L, exile=phi),
                       grid=[dict(rail_headroom=h, buffer_MB=2) for h in (2.0, 3.0, 5.0, 8.0, 12.0, 20.0)])
        row(f"lean | lead sched, exile {phi:.0%} weight MACs to lanes", sc, lo, how)
    if arch:
        sc, how = best("lean_int8_rail", L, kvs=(4,))
        row("lean | lead sched, KV4", sc, lo, how)
    # disaggregation on the lead's sizing; the prefill die has no per-stream floor (it emits no tokens)
    for g in (1, 2):
        sp = dict(L, groups=g)
        pre, _ = best("lean_int8_rail", dict(sp, mode="continuous"), kk_over=dict(gen=1, stream_floor_tok_s=0.0))
        dec, _ = best("lean_int8_rail", dict(sp, mode="lockstep"))
        mix, _ = best("lean_int8_rail", sp)
        if pre["tok_s_die"] and dec["tok_s_die"]:
            P, G = kn()["prompt"], kn()["gen"]
            per = dec["peak"]["dies"] * int(kn().get("system_dies", 1))      # decode tok/s per die
            xp, xd = pre["tok_s_die"] * P / (P + 1), dec["peak"]["B"] / dec["peak"]["T_step_s"] / per
            row(f"lean | disaggregated prefill/decode dies, groups {g}",
                dict(tok_s_die=(P + G) / (P / xp + G / xd), tops_w=0.0, tok_w=0.0, tok_j=0.0),
                "projected (harmonic law on overlay rates)",
                f"X_pre {xp:.0f} X_dec {xd:.0f}; mixed {mix['tok_s_die']:.0f}")
    # the systolic baseline under the same N7 (projected literature PE)
    wb = 4 if arch else metric.SOHU_WBITS
    tf = lambda c, v, f: baseline_systolic.tile(c, v, f, wb)  # noqa: E731
    for kv in ((16, 8, 4) if arch else (8,)):
        sc, how = best("digital_rail", kvs=(kv,), tf=tf, db=True)
        row(f"BASELINE W{wb} kv{kv} digital_rail | core", sc, "projected (literature PE)", how)
        sc, how = best("lean_int8_rail", kvs=(kv,), tf=tf, db=True)
        row(f"BASELINE W{wb} kv{kv} lean | core", sc, "projected (literature PE)", how)
        for name, sp in (("lockstep groups 2 eta 0.85", dict(L, mode="lockstep")),
                         ("continuous groups 0 eta 1", dict(mode="continuous", act="auto")),
                         ("continuous groups 2 eta 0.85", dict(L, mode="continuous")),
                         ("continuous + spec", dict(L, mode="continuous", spec=dict(k=3, accept=2.5, draft_frac=0.05)))):
            g = [dict(rail_headroom=h, buffer_MB=mb) for h in (1.0, 1.5, 2.0) for mb in (8, 16, 32, 64)]
            sc, how = best("lean_int8_rail", sp, kvs=(kv,), tf=tf, db=True, grid=g)
            row(f"BASELINE W{wb} kv{kv} lean | {name}", sc, lo, how)
    if not arch:   # the floor definition decides feasibility at batch 1000, P/G = 16
        for who, f_, d_ in (("IMC", None, False), (f"BASELINE W{wb}", tf, True)):
            for mode in ("lockstep", "continuous"):
                for fl in ("tbt", "avg"):
                    for beta in ((1, 16) if mode == "continuous" else (1,)):
                        g = [dict(rail_headroom=h, buffer_MB=mb) for h in (1.0, 2.0) for mb in (16, 64, 128)]
                        sc, how = best("lean_int8_rail", dict(L, mode=mode, floor=fl, budget=beta), tf=f_, db=d_, grid=g)
                        row(f"SOHU {who} lean | {mode} floor {fl} beta {beta}", sc, lo, how)
    return rows


def _selfcheck():
    from arch_eval import design as dz, metric
    for n1 in ("streaming", "resident"):
        d = dz.make({"n1_system": n1}, {"double_buffer": False, "kv_bits": 8})
        a, b = core(d, live=FROZEN), schedule(d, live=FROZEN, mode="lockstep", act="free")
        assert a["tok_s_die"] > 0 and not a["errors"], (n1, a["tok_s_die"], a["errors"])
        assert abs(a["tok_s_die"] / b["tok_s_die"] - 1) < 1e-9, (n1, a["tok_s_die"], b["tok_s_die"])
        assert abs(a["tops_w"] / b["tops_w"] - 1) < 1e-6, (n1, a["tops_w"], b["tops_w"])
    d = dz.make({"n1_system": "streaming"}, {"double_buffer": False, "kv_bits": 8})
    lf, la = (schedule(d, live=FROZEN, mode="lockstep", act=x) for x in ("free", "auto"))
    assert la["tok_s_die"] <= lf["tok_s_die"] * (1 + 1e-9)          # residency can only cost
    c = schedule(d, live=FROZEN, act="auto")
    assert c["tok_s_die"] >= la["tok_s_die"], (c["tok_s_die"], la["tok_s_die"])
    assert c["peak"]["per_stream_tok_s"] >= metric.KNOBS["stream_floor_tok_s"]
    ser, nb, ld = (schedule(d, live=FROZEN, act="auto", groups=g, overlap_eff=e)["tok_s_die"]
                   for g, e in ((1, 1.0), (2, 1.0), (2, 0.85)))
    assert ser <= nb <= c["tok_s_die"] * (1 + 1e-9) and ld < nb, (ser, nb, ld)   # serial <= interleave <= ideal
    lk = schedule(d, live=FROZEN, mode="lockstep", act="auto", overlap_eff=0.85)["tok_s_die"]
    assert lk < la["tok_s_die"], (lk, la["tok_s_die"])                          # eta leaks in lockstep too
    r = rail(dict(_LEAN, kv_bits=8), 0.7, dict(e_scale=1, clk_GHz=1.0, leak_scale=1), metric.KNOBS)
    assert 0.5 < sum(r["area_mm2"].values()) < 30 and 5e12 < r["att_mac_per_s"] < 2e13, r["att_mac_per_s"]
    print("PASS n7_dataflow self-check")


if __name__ == "__main__":
    _selfcheck()
    for cond in sys.argv[1:] or ("arch",):
        print(f"== {cond}")
        study(cond, verbose=True)
