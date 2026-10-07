"""ARCH_METRIC (docs/src/content/Project/ARCH_METRIC.md), exactly, over operating points.

A point is one (VDD, clock, concurrency B) evaluation of a system. Required keys:
  tok_s_die, gen_tok_s_die      processed / generated tok/s of the system / dies used
  die_power_W, ext_power_W      per die; ext = that die's external-memory access power
  useful_macs_s_die             weight + QK^T + A.V MACs/s per die (no padding/checksum)
  per_stream_tok_s              decode rate of one stream
  kv_ok, quality_ok             booleans (power and floor are checked here)
Ranking: tok/s per die > TOPS/W > tok/W > tok/J (strict lexicographic).
  TOPS/W, tok/W: at the peak-tok/s point (feasible: KV, floor, power cap, quality).
  tok/J: max over points feasible on KV, power cap and quality; the per-stream floor
         is NOT applied (ARCH_METRIC: any concurrency/clock, "gameable by running
         slow"). Same energy boundary as tok/W (die + its external memory), so
         tok/J >= tok/W always.
"""
KNOBS = dict(
    die_mm2=100.0,              # iso-area die
    power_cap_W_per_mm2=1.0,
    hbm_Bps=819e9, hbm_bytes=24e9, hbm_pJ_per_bit=4.0,   # one HBM3-class stack per die
    d2d_Bps=2e12, d2d_pJ_per_bit=0.5,
    stream_floor_tok_s=20.0,
    prompt=512, gen=128,
    vdd_min=0.45, vdd_max=0.7,
    model="8B-class",           # workload shapes (imc_architecture_search.MODELS)
    batch=0,                    # 0 = concurrency free (throughput-optimal); N = fixed batch of N streams
    kv_bits=0,                  # 0 = the design's own KV format; N = forced
    system_dies=1,              # ideal tensor-parallel group of identical dies sharing one batch (no d2d cost)
)
# Condition sets every design is scored under. "arch" = ARCH_METRIC; "sohu" = Etched's published
# benchmark conditions (docs/src/content/Project/local/SOHU_VERIFIED.md): Llama-3-70B, FP8 weights
# and KV, 2048 in / 128 out, batch ~1000, 8 chips per server, ~4.8 TB/s and 144 GB HBM3E per chip.
# Sohu's die area is unpublished: the die is iso-area with the calibrated Sohu-equivalent (sohu_area()).
CONDITIONS = dict(
    arch={},
    sohu=dict(model="70B-class", prompt=2048, gen=128, batch=1000, kv_bits=8,
              hbm_Bps=4.8e12, hbm_bytes=144e9, system_dies=8),
)
SOHU_WBITS = 8                  # FP8 weights: what the systolic baseline streams under "sohu"
SOHU_TOK_S_CHIP = 500_000 / 8   # vendor claim (projected silicon), Llama-3-70B, per chip
METRICS = ("tok_s_die", "tops_w", "tok_w", "tok_j")



def knobs_for(conditions="arch", **over):
    """KNOBS with a condition set applied, then explicit overrides. Under "sohu" the die is
    iso-area with the Sohu-equivalent (the systolic die sized to Sohu's claimed tok/s per chip)
    unless die_mm2 is given."""
    k = dict(KNOBS, **CONDITIONS[conditions], **over)
    if conditions == "sohu" and "die_mm2" not in over:
        k["die_mm2"] = sohu_area()
    return k


_SOHU_AREA = []


def sohu_area():
    """Calibrated Sohu-equivalent die area in mm2 (cached per process; follows ppa.json)."""
    if not _SOHU_AREA:
        from . import baseline_systolic   # late: baseline_systolic imports this module
        area, _ = baseline_systolic.sohu_equivalent()
        _SOHU_AREA.append(area or KNOBS["die_mm2"])
    return _SOHU_AREA[0]


def eff(pt):
    return pt["tok_s_die"] / (pt["die_power_W"] + pt["ext_power_W"])


def power_ok(pt, knobs):
    return pt["die_power_W"] <= knobs["power_cap_W_per_mm2"] * knobs["die_mm2"] * (1 + 1e-12)


def feasible_peak(pt, knobs):
    return (pt["kv_ok"] and pt["quality_ok"] and power_ok(pt, knobs)
            and pt["per_stream_tok_s"] >= knobs["stream_floor_tok_s"])


def feasible_energy(pt, knobs):
    return pt["kv_ok"] and pt["quality_ok"] and power_ok(pt, knobs)


def score(points, knobs=KNOBS):
    """-> dict(tok_s_die, gen_tok_s_die, tops_w, tok_w, tok_j, tok_s_mm2, tok_s_mm2_W, peak, best_j)
    or zeros if infeasible."""
    peak_pool = [p for p in points if feasible_peak(p, knobs)]
    j_pool = [p for p in points if feasible_energy(p, knobs)]
    if not peak_pool:
        return dict(tok_s_die=0.0, gen_tok_s_die=0.0, tops_w=0.0, tok_w=0.0,
                    tok_j=max(map(eff, j_pool), default=0.0), tok_s_mm2=0.0, tok_s_mm2_W=0.0,
                    peak=None, best_j=None, infeasible=True)
    peak = max(peak_pool, key=lambda p: (p["tok_s_die"], eff(p)))
    best_j = max(j_pool, key=eff)
    return dict(tok_s_die=peak["tok_s_die"], gen_tok_s_die=peak["gen_tok_s_die"],
                tops_w=2 * peak["useful_macs_s_die"] / peak["die_power_W"] / 1e12,
                tok_w=eff(peak), tok_j=eff(best_j), peak=peak, best_j=best_j, infeasible=False,
                # reported, not ranked: area efficiency and area x die-power efficiency at the peak point
                tok_s_mm2=peak["tok_s_die"] / knobs["die_mm2"],
                tok_s_mm2_W=peak["tok_s_die"] / knobs["die_mm2"] / peak["die_power_W"])


def key(s):
    return tuple(s[m] for m in METRICS)


def better(a, b):
    """True if score a ranks strictly above score b (higher-ranked metric wins outright)."""
    return key(a) > key(b)


def rank(scores):
    return sorted(scores, key=key, reverse=True)


def pareto(scores):
    """4-metric Pareto front (all maximized), O(n^2)."""
    def dom(q, p):
        return all(q[m] >= p[m] for m in METRICS) and any(q[m] > p[m] for m in METRICS)
    return [p for p in scores if not any(dom(q, p) for q in scores)]
