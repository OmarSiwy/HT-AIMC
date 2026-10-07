"""Self-check for arch_eval: prints PASS/FAIL per check, exits non-zero on any FAIL.

    python3 scripts/compiler/metrics/arch_eval/test_arch_eval.py
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from arch_eval import asap7, baseline_systolic, design, metric, model, workload  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))
    if not cond:
        FAILS.append(name)


def close(a, b, rel=1e-9):
    return abs(a - b) <= rel * max(abs(a), abs(b))


# --- workload: MAC counts -------------------------------------------------------------
w_tab = workload.llama3_8b(vocab=128000)
w = workload.llama3_8b()
check("weight MACs/token, Table-3 vocab 128000 = 7,503,609,856",
      w_tab["weight_macs_per_token"] == 7_503_609_856, w_tab["weight_macs_per_token"])
check("weight MACs/token, ARCH_METRIC vocab 128256 = 7,504,658,432",
      w["weight_macs_per_token"] == 7_504_658_432, w["weight_macs_per_token"])
check("1x1 tiling = MAC count", workload.tiles(w, 1, 1) == w["weight_macs_per_token"])
check("attention MACs: 2 L hq dh per context position = 262144", w["att_macs_per_ctx"] == 262144)
check("decode context sum 513..640 = 73792", w["ctx_decode_sum"] == 73792)
check("KV bytes/token at 16 bit = 131072", w["kv_bytes_per_token"] == 131072)
check("serial stages = 4L+1 = 129", w["stages"] == 129)

w70 = workload.llama3("70B-class", vocab=128000)
check("70B weight MACs/token, Table-3 vocab 128000 = 69,499,617,280",
      w70["weight_macs_per_token"] == 69_499_617_280, w70["weight_macs_per_token"])
check("sohu conditions: 70B FP8, 2048/128, batch 1000, 8 dies", metric.knobs_for("sohu")["model"] == "70B-class"
      and metric.knobs_for("sohu")["batch"] == 1000 and metric.knobs_for("sohu")["system_dies"] == 8)

# --- metric definitions on hand-computed points ------------------------------------------
K = dict(metric.KNOBS)


def pt(tok, P, ext, macs, stream, kv=True, q=True, B=1):
    return dict(tok_s_die=tok, gen_tok_s_die=tok / 5, die_power_W=P, ext_power_W=ext,
                useful_macs_s_die=macs, per_stream_tok_s=stream, kv_ok=kv, quality_ok=q,
                B=B, vdd=0.7, clk_frac=1.0)


pts = [pt(1000, 50, 10, 5e14, 30),            # feasible; tok/W 1000/60
       pt(2000, 80, 20, 8e14, 25),            # feasible peak: 2000 tok/s
       pt(5000, 150, 20, 1e15, 40),           # over the 100 W power cap
       pt(4000, 60, 20, 1e15, 10),            # below the 20 tok/s per-stream floor (ok for tok/J)
       pt(9000, 10, 1, 1e15, 50, kv=False)]   # exceeds KV capacity
s = metric.score(pts, K)
check("peak = best tok/s among KV/floor/power/quality-feasible points", s["tok_s_die"] == 2000)
check("TOPS/W = 2 x useful MAC/s / die power at peak = 20", close(s["tops_w"], 2 * 8e14 / 80 / 1e12))
check("tok/W = tok/s / (die + ext) at peak = 20", close(s["tok_w"], 2000 / 100))
check("tok/J = max over KV/power-feasible points, floor ignored = 50", close(s["tok_j"], 4000 / 80))
check("tok/J >= tok/W", s["tok_j"] >= s["tok_w"])
check("all-infeasible -> zero tok/s", metric.score([pts[2]], K)["tok_s_die"] == 0)

A = dict(tok_s_die=10, tops_w=1, tok_w=1, tok_j=1)
Bs = dict(tok_s_die=9.99, tops_w=100, tok_w=100, tok_j=100)
Cs = dict(tok_s_die=10, tops_w=2, tok_w=0.5, tok_j=0.5)
Ds = dict(tok_s_die=5, tops_w=0.5, tok_w=0.5, tok_j=0.5)
check("lexicographic: tok/s wins outright over 100x TOPS/W", metric.better(A, Bs))
check("lexicographic: TOPS/W breaks a tok/s tie", metric.better(Cs, A))
check("rank order", [r["tops_w"] for r in metric.rank([A, Bs, Cs, Ds])] == [2, 1, 100, 0.5])
front = metric.pareto([A, Bs, Cs, Ds])
check("Pareto keeps the non-dominated A, B, C and drops D", front == [A, Bs, Cs])

# --- system schedule on a hand-built toy tile --------------------------------------------
ctx = model.Ctx(design.make({"n1_system": "resident"}))
toy_knobs = dict(K, hbm_Bps=1e30)
ctx.knobs = toy_knobs
rail = dict(ctx.call("n7_dataflow", "rail", 0.7, ctx.call("n9_circuits", "op", 0.7, 1.0), K),
            att_mac_per_s=1e30, e_att_mac_J=0, e_exp_J=0, e_elem_J=0, phy_J_per_bit=0, e_buf_J_per_byte=0)
need = workload.tiles(ctx.wl, 4096, 4096)
toy = dict(rows=4096, cols=4096, macs_per_pass=4096 ** 2, t_pass_s=1e-6, t_load_s=0, e_pass_J=1e-6,
           e_pass_J_parts={}, wbits=4, write_bits_per_load=0, e_write_J_per_bit=0, leak_W=0,
           quality=dict(passed=True), op=dict(vdd=0.7, clk_frac=1.0), rail=rail)
die = dict(n_tiles=need, tiles_needed=need, static_W=0.0)
p = model.system_point(ctx, toy, die, dict(mode="resident", dies=1), 256)
# T = prefill 256*512 us + 128 steps * max(256 us occupancy, 129 us latency chain) = 0.16384 s
check("toy: tok/s = 256*640/0.16384 = 1e6", close(p["tok_s_die"], 1e6), p["tok_s_die"])
check("toy: generated tok/s = 2e5", close(p["gen_tok_s_die"], 2e5))
check("toy: per-stream = 1/256 us = 3906.25", close(p["per_stream_tok_s"], 1 / 256e-6))
check("toy: die power = tokens * tiles * 1 uJ / T", close(p["die_power_W"], 256 * 640 * need * 1e-6 / 0.16384))
p1 = model.system_point(ctx, toy, die, dict(mode="resident", dies=1), 1)
check("toy B=1: decode step = latency chain 129 stages", close(p1["T_step_s"], 129e-6), p1["binding"])

# --- default design and systolic baseline score finite positive numbers -----------------
ok_keys = all(k in asap7.TABLE for k in asap7.REQUIRED) and all(
    f"{k}@{v}" in asap7.TABLE for k in ("fo4_delay_ps", "inv_switch_energy_fJ") for v in (0.45, 0.5, 0.6, 0.7))
check("asap7: every required key resolves (file or fallback)", ok_keys, asap7.report()["load_error"] or "file loaded")
# Reference = the round-1 pick. Each node's DEFAULT is that node's own lead, not a joint
# design, so the all-default combination only has to run cleanly, not pass the quality gate.
sd = model.evaluate(design.load(str(Path(__file__).parent / "designs/notes_native.json")))
check("reference design (round-1 pick): four finite positive metrics",
      all(math.isfinite(sd[m]) and sd[m] > 0 for m in metric.METRICS), {m: f"{sd[m]:.4g}" for m in metric.METRICS})
check("reference design: no node fallbacks", not sd["errors"], sd["errors"])
check("reference design: tok/J >= tok/W", sd["tok_j"] >= sd["tok_w"] * (1 - 1e-12))
s0 = model.evaluate(design.make())
check("all-default design runs without node fallbacks", not s0["errors"], s0["errors"])
sb = baseline_systolic.evaluate()
check("systolic baseline: four finite positive metrics", all(math.isfinite(sb[m]) and sb[m] > 0 for m in metric.METRICS),
      {m: f"{sb[m]:.4g}" for m in metric.METRICS})

# --- systolic table and the lever-matched baseline ----------------------------------------
from arch_eval import cli  # noqa: E402
m = cli.table(sd, K)
check("table: 0 < utilization <= 1 and achieved >= tile throughput", 0 < m["utilization"] <= 1
      and m["achieved_tops"] >= m["tile_tops"], m)
check("table: HBM traffic within the available bandwidth", m["hbm_decode_GBps"] <= m["hbm_avail_GBps"] * (1 + 1e-9), m)
wb, bm = cli.matched_baseline(design.load(str(Path(__file__).parent / "designs/notes_native.json")), sd, "arch", K)
b16 = baseline_systolic.evaluate(wb, K)
check("matched baseline takes the design's W8 and KV4: more KV room than KV16", wb == 8
      and bm["peak"]["b_max"] > b16["peak"]["b_max"], (wb, bm["peak"]["b_max"], b16["peak"]["b_max"]))


# --- defensive loading: a broken node falls back and is reported ------------------------
import arch_eval.nodes.n6_readout as n6  # noqa: E402
orig = n6.adc
n6.adc = lambda *a: 1 / 0
sf = model.evaluate(design.make())
n6.adc = orig
# The fallback is the frozen nodes/default copy, which differs from the researched n6 once it
# has been edited, so only "reported and still evaluated" is invariant, not the score.
check("raising node -> frozen default used, error reported, still evaluated",
      any("n6_readout.adc raised" in e for e in sf["errors"]) and math.isfinite(sf["tok_s_die"]))


# --- condition sets: fixed batch is honoured; Sohu calibration hits its target ----------------
sb = baseline_systolic.evaluate(metric.SOHU_WBITS, metric.knobs_for("sohu"))
check("sohu baseline runs at the fixed batch", sb["peak"] is not None and sb["peak"]["B"] == 1000,
      sb["peak"] and sb["peak"]["B"])
area, se = baseline_systolic.sohu_equivalent()
check("sohu-equivalent die reaches 62,500 tok/s/chip within 1 %", area is not None
      and abs(se["tok_s_die"] / metric.SOHU_TOK_S_CHIP - 1) < 0.01, (area, se["tok_s_die"]))
check("sohu conditions are iso-area with the Sohu-equivalent", close(metric.knobs_for("sohu")["die_mm2"], area),
      (metric.knobs_for("sohu")["die_mm2"], area))

print(f"\n{'FAIL' if FAILS else 'PASS'}: {len(FAILS)} failing check(s)" + (f": {FAILS}" if FAILS else ""))
sys.exit(1 if FAILS else 0)
