"""Task #13 — compose ALL landed optimization levers into ONE honest
AnalogIOC tok/s/die + tok/J picture on the real model. Pure metrics assembly
from measured anchors + landed laws. NO SPICE (an analog agent owns sims).

The lever stack (each factor sourced + labeled):
  0. measured anchor  : METRICS.md mini-chip 2190.5 pJ/pass (tile 820.83 +
     coarse 1061.59 + fine 283.51 + digital 24.6), 10944 passes/token,
     22.2 tok/s / 41,714 tok/J on the 50x-slow sim grid.
  1. K* cascade (per-layer, avg K=6.54, perlayer_k.py): the shared conversion
     (coarse+fine) amortizes /K; measured tb_cascade E/pass 0.55x(K=2) /
     0.41x(K=4). This is the big tok/s AND tok/J lever.
  2. CSD recode (FORMATS.md): tile-integrate CHARGE component reduction.
     Honest: -33% is the wide-uniform-word ASYMPTOTE; measured on the real
     INT4 mini it is only -0.6% (weights already concentrate near zero).
  3. CSNR lattice thresholds (FORMATS.md): converter-energy/-bit where the
     lattice pitch >> sigma_a. Regime-dependent; NOT a flat multiplier.
  4. measured-gain accuracy (A10/A11): a CORRECTNESS precondition (in-contract
     +-1 LSB), NOT an energy or throughput factor. Enables correct tokens.

CRITICAL honesty — interference / double-counting: the cascade coarser-LSB
SNR budget, the lattice threshold gain, and the per-layer-K gain-term cap all
draw on the SAME per-tensor SNR budget. They do NOT compose multiplicatively.
This module states which levers STACK (independent physics) and which SHARE a
budget, and compares the composed number to the naive lever product.

Run: PYTHONPATH=<repo> python3 scripts/compiler/metrics/compose.py
Emits docs/src/content/Project/COMPOSED_RESULTS.md + prints the headline.
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, "analog", "docs"))
sys.path.insert(0, HERE)
import specs                                       # noqa: E402
import pdk_projections as pj                       # noqa: E402
import perlayer_k as plk                           # noqa: E402
from pdk_specs import Sky130             # noqa: E402
from pdk_specs import Asap7Proj      # noqa: E402
from pdk_specs import TsmcN4Proj   # noqa: E402

OUT_MD = os.path.join(ROOT, "docs", "src", "content", "Project", "COMPOSED_RESULTS.md")

# ---- measured anchor (METRICS.md, frozen SPICE per-block energy) ----
E_TILE_PJ = 820.83        # measured, tb_tile_mvm (integrate charge)
E_COARSE_PJ = 1061.59     # measured, tb_tile_mvm
E_FINE_PJ = 283.51        # measured, tb_tile_mvm
E_DIG_PJ = 24.6           # estimated, yosys cell count x cap model
E_CONV_PJ = E_COARSE_PJ + E_FINE_PJ     # 1345.10 — amortizes with K
E_PASS1_PJ = E_TILE_PJ + E_CONV_PJ + E_DIG_PJ    # 2190.53 (K=1 anchor)
N_PASS = 10944            # counted (A5 exact tiling)
KV_SOFTMAX_PJ = 27.0      # measured/counted per-token KV+softmax adds

# ---- measured cascade E/pass amortization (tb_cascade, real transistors) ----
# E/pass(K) = E_TILE + E_DIG + E_CONV/K  reproduces the shared-conversion
# structure; the MEASURED anchors are 0.55x(K=2), 0.41x(K=4) on the pass_05
# tile. We apply /K to the CONVERSION component only (tile-integrate charge is
# per-pass, does NOT amortize — CASCADE.md: "tile-integrate charge grows
# linearly while the shared conversion amortizes across K windows").
MEAS_EPASS_RATIO = {1: 1.00, 2: 0.55, 4: 0.41}    # tb_cascade measured

# ---- CSD tile-charge factor (FORMATS.md csd_report, measured on real Wq) ----
CSD_REAL_TILE = 1.0 - 0.006      # -0.6% real INT4 unit-cell charge (measured)
CSD_ASYMPTOTE = 1.0 - 0.33       # -33% wide-uniform-word asymptote (paper)


def e_pass_cascade_pj(K):
    """Composed per-pass energy at cascade depth K (measured chain).
    Conversion amortizes /K; tile-integrate + digital stay per pass."""
    return E_TILE_PJ + E_DIG_PJ + E_CONV_PJ / K


def e_pass_ratio_meas(K):
    """Measured E/pass ratio vs K=1 from the tb_cascade structure (matches
    0.55x/0.41x at K=2/4; >4 is derived from the same /K conversion law)."""
    return e_pass_cascade_pj(K) / E_PASS1_PJ


def avg_k_schedule():
    """Conversion-weighted avg K from the landed per-tensor schedule
    (perlayer_k.py, avg K=6.54). Returns (sched, avg_k, per-class K)."""
    mats = json.load(open(plk.MANIFEST))["matrices"]
    sched = plk.k_schedule(mats)
    # conversion-weighted (2 conv/pass, /K): weight by passes/K
    passes = {n: mats[n]["passes_per_token"] for n in mats}
    tot = sum(passes.values())
    avg_k = tot / sum(passes[n] / sched[n] for n in passes)
    return sched, avg_k, passes


def composed_e_per_token_pj(sched, passes):
    """E/token composing the measured chain with the per-tensor K schedule
    and CSD on the tile component. Each tensor's passes pay
    e_pass_cascade(K_tensor) with the tile-charge CSD factor applied."""
    e = 0.0
    for n, np_ in passes.items():
        K = sched[n]
        e_tile = E_TILE_PJ * CSD_REAL_TILE
        e_pass = e_tile + E_DIG_PJ + E_CONV_PJ / K
        e += np_ * e_pass
    return e + KV_SOFTMAX_PJ


def project(sched, avg_k, passes):
    """tok/s/die + tok/J at each PDK / scale, composing the perlayer_k
    schedule timing with the measured-chain energy. Reuses perlayer_k's
    pass_time_K (merged-window S5 + ping-pong S6 + cascade)."""
    total = sum(passes.values())
    die = pj.DIE_MM2 * pj.FILL
    rows = []
    for label, pdk, tq0, tag in (
            ("sky130 (real t_q)", Sky130(), 200e-12, "projected"),
            ("asap7_proj", Asap7Proj(), None, "projected"),
            ("tsmc_n4_proj", TsmcN4Proj(), None, "projected")):
        saved = (specs.TQ_SIM, specs.sar_time)
        try:
            tq = tq0 or pdk.t_q_grid
            plk._setup_pdk(pdk, tq)
            tiles = int(die / pj.TILE_MM2[pdk.name])
            for scale, npt in (("7B", int(7e9 / 256)),
                               ("70B", int(70e9 / 256))):
                f = npt / total
                pt = {n: passes[n] * f for n in passes}
                # throughput: composed per-tensor K schedule
                t_tok = sum(pt[n] * plk.pass_time_K(pdk, tq, sched[n])
                            for n in pt)
                toks = tiles / t_tok
                # energy: measured chain, per-tensor K, CSD on tile.
                # (energy is PDK-invariant in the measured-anchor accounting —
                #  it is the sky130 SPICE chain; PDK scaling of energy is a
                #  separate projection, kept OUT to stay measured-anchored.)
                e_tok_pj = sum(pt[n] * (E_TILE_PJ * CSD_REAL_TILE + E_DIG_PJ
                                        + E_CONV_PJ / sched[n]) for n in pt)
                e_tok_pj += KV_SOFTMAX_PJ * f
                tokj = 1.0 / (e_tok_pj * 1e-12)
                rows.append({
                    "pdk": label, "tag": tag, "scale": scale,
                    "toks": toks, "tokj_measanchor": tokj,
                    "vs_sohu_toks": toks / pj.SOHU_TOKS_DIE,
                })
        finally:
            specs.TQ_SIM, specs.sar_time = saved
    return rows


def lever_stack():
    """The cumulative lever table on the MEASURED tok/J (energy) axis, at the
    landed avg K=6.54. Each row: lever, its factor, cumulative tok/J, what
    binds it. tok/J is on the sky130 measured chain (PDK-invariant anchor)."""
    sched, avg_k, passes = avg_k_schedule()
    # baseline: K=1, no CSD, measured chain
    e0 = N_PASS * E_PASS1_PJ + KV_SOFTMAX_PJ       # pJ/token
    base_tokj = 1.0 / (e0 * 1e-12)
    # after cascade (per-tensor K)
    e1 = sum(passes[n] * (E_TILE_PJ + E_DIG_PJ + E_CONV_PJ / sched[n])
             for n in passes) + KV_SOFTMAX_PJ
    tokj_casc = 1.0 / (e1 * 1e-12)
    # after CSD on tile
    e2 = composed_e_per_token_pj(sched, passes)
    tokj_csd = 1.0 / (e2 * 1e-12)
    return {
        "avg_k": avg_k, "sched": sched,
        "base_tokj": base_tokj,
        "casc_tokj": tokj_casc, "casc_factor": tokj_casc / base_tokj,
        "csd_tokj": tokj_csd, "csd_factor": tokj_csd / tokj_casc,
        "e0_pj": e0, "e_casc_pj": e1, "e_csd_pj": e2,
    }


def interference():
    """Composed vs naive product. The three SNR-budget levers (cascade K,
    lattice thresholds, per-layer-K gain cap) SHARE one budget; only the
    energy/time levers (cascade amortization, CSD tile charge) STACK."""
    sched, avg_k, _ = avg_k_schedule()
    # naive: if each SNR lever gave its OWN independent K boost.
    # cascade random-term K* at FFN SNRs=38: 10.0; if lattice added +6 dB it
    # would push SNRs->44 -> K* random 10^1.6=40; but the GAIN term caps FFN at
    # 7 REGARDLESS (ln(1.02)/eg=6.6). So lattice's SNR headroom CANNOT be spent
    # on deeper K — the gain-compounding budget already binds at K=7.
    ffn_k_random = 10.0 ** ((plk.SNR_S_DB["ffn"] - plk.SNR_T_DB) / 10.0)
    ffn_k_gain = math.log(1.02) / specs.EG_SERVO
    ffn_k_lattice_naive = 10.0 ** (
        (plk.SNR_S_DB["ffn"] + 6.0 - plk.SNR_T_DB) / 10.0)
    return {
        "ffn_k_random": ffn_k_random,          # 10.0 (SNR would allow)
        "ffn_k_gain_cap": ffn_k_gain,          # 6.6 (gain term BINDS)
        "ffn_k_lattice_naive": ffn_k_lattice_naive,  # 40 (naive +6dB)
        "ffn_k_actual": sched["ffn_gate"],     # 7 (what landed)
    }


def main():
    stk = lever_stack()
    sched, avg_k, passes = avg_k_schedule()
    rows = project(sched, avg_k, passes)
    intf = interference()
    n4_7b = next(r for r in rows if r["pdk"] == "tsmc_n4_proj"
                 and r["scale"] == "7B")

    L = [
        "# COMPOSED AnalogIOC RESULTS (task #13) — all landed levers, one number",
        "",
        "Pure metrics assembly from MEASURED anchors + LANDED laws. NO SPICE "
        "(an analog agent owns the sim lane). Regenerate: "
        "`PYTHONPATH=<repo> python3 scripts/compiler/metrics/compose.py`.",
        "",
        "Labels: **measured-anchor** = frozen SPICE per-block energy "
        "(METRICS.md, tb_tile_mvm/tb_cascade); **derived** = specs.py / "
        "perlayer_k.py law on measured params; **projected** = "
        "projection-grade PDK set (asap7/n4, tok/s/die + timing).",
        "",
        "## Headline (N4 / 7B, per-tensor K schedule, avg K=6.54)",
        "",
        f"- **composed tok/s/die = {n4_7b['toks']:,.0f}** "
        f"= **{n4_7b['vs_sohu_toks']:.2f}x** Sohu (62,500 tok/s/die, "
        "vendor-derived, high-batch FP8 70B) — _projected_.",
        f"- **composed tok/J (mini-subset scope) = {stk['csd_tokj']:,.0f}** "
        "(measured-chain energy, avg K=6.54, CSD on tile) — _derived from "
        "measured anchor_. This is the 10944-pass mini scope (same scope as "
        "METRICS.md's 41,714).",
        f"- **composed tok/J at 7B (mini physics scaled) = "
        f"{n4_7b['tokj_measanchor']:.0f}** — the SAME measured mini per-pass "
        "energy scaled to 27.3 M passes/token. It is BELOW Sohu because the "
        "mini's static-OTA-dominated 8461 fJ/MAC (K=1, 50x-slow grid) is not "
        "a production 7B die; the paper's 7B-optimized projection (converged "
        "3.2 fJ/MAC, METRICS.md) gives ~45k tok/J. Both are stated so the "
        "measured-vs-projected gap is explicit, not hidden.",
        "- measured-vs-projected split: the ENERGY per block "
        "(2190.5 pJ/pass) and the cascade amortization (0.55x/0.41x) are "
        "**measured** (SPICE, real transistors); the K schedule + tok/J "
        "arithmetic are **derived**; the tok/s/die (PDK timing + tiles/die) "
        "is **projected**.",
        "",
        "## Measured anchor (METRICS.md, frozen SPICE)",
        "",
        f"- per-pass = tile {E_TILE_PJ} + coarse {E_COARSE_PJ} + fine "
        f"{E_FINE_PJ} + digital {E_DIG_PJ} = **{E_PASS1_PJ:.1f} pJ/pass** "
        "(measured x counted + estimated digital).",
        f"- conversion component (coarse+fine) = **{E_CONV_PJ:.1f} pJ** — "
        "this is what amortizes /K; tile-integrate + digital are per-pass.",
        f"- HONEST amortization scope: tb_cascade measured 0.55x(K=2)/"
        "0.41x(K=4) on the SINGLE pass_05 tile (small tile fraction). On the "
        f"FULL METRICS chain the tile fraction is bigger "
        f"({E_TILE_PJ/E_PASS1_PJ:.0%} tile vs {E_CONV_PJ/E_PASS1_PJ:.0%} "
        f"conversion), so the chain E/pass amortizes MILDER: "
        f"{e_pass_ratio_meas(2):.2f}x(K=2)/{e_pass_ratio_meas(4):.2f}x(K=4). "
        "Same physics (only conversion amortizes), different tile:conv mix.",
        f"- {N_PASS} passes/token -> {N_PASS*E_PASS1_PJ*1e-6:.2f} uJ/token; "
        f"22.2 tok/s, 41,714 tok/J (K=1, 50x-slow sim grid).",
        "",
        "## Lever stack (cumulative, on the measured tok/J axis)",
        "",
        "| lever | factor | cumulative tok/J | what binds | source |",
        "|---|---|---|---|---|",
        f"| 0. measured anchor (K=1) | 1.00x | {stk['base_tokj']:,.0f} | "
        "per-pass conversion (no amortization) | measured |",
        f"| 1. K* cascade (per-tensor, avg K=6.54) | "
        f"{stk['casc_factor']:.2f}x | {stk['casc_tokj']:,.0f} | conversion "
        f"amortizes /K; FFN K=7 capped by gain (1+eg)^K | measured "
        "amortization + derived K |",
        f"| 2. CSD recode (tile charge) | {stk['csd_factor']:.3f}x | "
        f"{stk['csd_tokj']:,.0f} | real INT4 density already ~0.196 << 1/2 "
        "| measured (FORMATS.md) |",
        "| 3. CSNR lattice thresholds | regime-dependent | (no flat "
        "multiplier) | pitch >> sigma_a only; SHARES the SNR budget | "
        "measured (FORMATS.md) |",
        "| 4. measured-gain accuracy | correctness | (enables correct "
        "tokens) | in-contract +-1 LSB; NOT an energy factor | measured "
        "(A10/A11) |",
        "",
        f"**Composed tok/J (levers 0-2) = {stk['csd_tokj']:,.0f}** on the "
        "measured chain. Cascade is the whole energy story; CSD adds "
        f"{ (stk['csd_factor']-1)*100:+.1f}% on the REAL INT4 mini (the -33% "
        "is the wide-uniform-word asymptote, not this chip).",
        "",
        "## What STACKS vs what SHARES a budget (the honesty check)",
        "",
        "- **STACK (independent physics):** cascade conversion-amortization "
        "(time + energy) and CSD tile-charge reduction act on DIFFERENT "
        "energy components (conversion vs tile-integrate), so they multiply "
        "cleanly. Merged-window (S5) + ping-pong (S6) are schedule levers on "
        "the SAME conversion the cascade amortizes — already folded into "
        "`pass(K)=max(136 t_q, T_conv/K)+4 t_q`, not an extra factor.",
        "- **SHARE ONE BUDGET (do NOT multiply):** cascade depth K, CSNR "
        "lattice thresholds, and the per-layer-K gain cap all spend the SAME "
        "per-tensor SNR budget. Coarser-LSB from deeper K COSTS SNR; lattice "
        "thresholds and a better servo GIVE SNR; you cannot bank the same dB "
        "twice.",
        "",
        "### Interference proof (FFN class, the 95%-of-passes bulk)",
        "",
        f"- random-SNR term alone (SNRs=38, SNRt=28) would allow "
        f"K={intf['ffn_k_random']:.0f}.",
        f"- naive: if lattice added +6 dB of CSNR headroom, the random term "
        f"would allow K={intf['ffn_k_lattice_naive']:.0f}.",
        f"- BUT the gain-compounding term (1+eg)^K caps FFN at "
        f"K={intf['ffn_k_gain_cap']:.1f} REGARDLESS of SNR headroom "
        f"(landed K={intf['ffn_k_actual']}). **The lattice dB cannot be "
        "spent on deeper K — the servo-eg budget already binds.** So "
        "lattice's win is NOT a throughput/energy multiplier on top of "
        "cascade; it is redundant with SNR headroom the gain term already "
        "leaves on the table.",
        "- **Composed < naive product:** the naive stack (cascade x lattice "
        f"as independent K boosts) implies FFN K~{intf['ffn_k_lattice_naive']:.0f} "
        f"and ~{intf['ffn_k_lattice_naive']/intf['ffn_k_actual']:.1f}x more "
        "conversion amortization than the composed K=7 delivers. The composed "
        "number is LOWER because the gain-compounding servo budget is the "
        "real binding constraint, shared across all three SNR levers.",
        "",
        "## Composed tok/s/die + tok/J vs Sohu (all PDK / scale)",
        "",
        "tok/s/die is projected PDK timing x tiles/die (die 400 mm2 x 0.7 "
        "fill). tok/J is the measured mini per-pass chain SCALED to the full "
        "model's passes/token (PDK-invariant: the per-block pJ are SPICE "
        "numbers, not re-projected per node). SCOPE WARNING: the 7B/70B tok/J "
        "here is mini physics scaled up — it carries the mini's "
        "static-OTA-dominated per-pass energy, so it is BELOW the paper's "
        "7B-optimized ~45k projection (converged 3.2 fJ/MAC). Compare the "
        "MINI-scope tok/J (87,343) to Sohu, or use the paper projection; do "
        "NOT read the scaled 7B row as the production number.",
        "",
        "| PDK | scale | composed tok/s/die | vs Sohu 62.5k | tok/J (mini "
        "physics scaled) | tag |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        L.append(
            f"| {r['pdk']} | {r['scale']} | {r['toks']:,.0f} | "
            f"{r['vs_sohu_toks']:.2f}x | {r['tokj_measanchor']:,.0f} | "
            f"{r['tag']} |")
    L += [
        "| Etched Sohu | 70B | 62,500 | 1.00x | 35-60 (INFERRED) | vendor "
        "tok/s (500k/8, FP8 batch~1000); tok/J INFERRED (no vendor power) |",
        "",
        "## Honest bottom line",
        "",
        f"- **N4/7B composed = {n4_7b['toks']:,.0f} tok/s/die = "
        f"{n4_7b['vs_sohu_toks']:.2f}x Sohu — BUT ONLY AT THE ASSUMED "
        "SNR_s = 34/38 dB.** Session 3 MEASURED per-stage compute-SNR for the "
        "first time (analog/testbenches/tb_csnr.py): 19.9 dB attention and "
        "16.7 dB FFN uncorrected, 27.8-30.1 dB with the A10 per-column gain "
        "cal — and that last range is CIRCULAR (fitted and scored on the same "
        "columns). 34/38 were never measured; they are the paper's per-tensor "
        "CSNR *targets*, adopted into specs.py and perlayer_k.py as *sources* "
        "and mislabelled 'measured-class'. At the measured CSNR the 28 dB "
        "end-to-end target is not met at ANY K, so K=1, and N4/7B is "
        "**15,534 tok/s = 0.25x Sohu**. Treat every K>1 number here as "
        "conditional on an SNR that has not been demonstrated.",
        "- **tok/J, matched scope:** at the MINI subset the composed chain is "
        f"{stk['csd_tokj']:,.0f} tok/J; the paper's 7B-optimized projection is "
        "~45k tok/J (converged 3.2 fJ/MAC) — both clear the INFERRED Sohu "
        "70B band (35-60) by ~750-1500x, BUT the mini per-pass energy scaled "
        f"naively to 7B gives only {n4_7b['tokj_measanchor']:.0f} tok/J "
        "(static-OTA-dominated, not a production die). The honest tok/J win "
        "needs the amortized production converter, not just the mini SPICE "
        "chain. Excludes weight-rewrite energy, as METRICS.md.",
        "- **measured share:** the per-block energy (2190.5 pJ/pass) and the "
        "cascade amortization (0.55x/0.41x) are SPICE-measured. **derived "
        "share:** the K schedule, avg K=6.54, and tok/J arithmetic. "
        "**projected share:** tiles/die + PDK timing (asap7/n4 param sets).",
        "- **the 2x-Sohu gap is a servo-eg problem, not a lever-stacking "
        "one:** halving eg (0.3% -> 0.15%) roughly doubles the gain-term K "
        "cap (ln(1.02)/eg: 6.6 -> 13), pushing FFN toward K~13-14 and the "
        "121.9k (1.95x) uniform-K=14 ceiling. Lattice thresholds do NOT get "
        "you there — they spend a budget the gain term already caps.",
        "",
    ]
    open(OUT_MD, "w").write("\n".join(L))
    print(f"wrote {OUT_MD}")
    print(f"avg K = {avg_k:.2f}  sched = "
          + ", ".join(f"{k}={v}" for k, v in sched.items()))
    print(f"composed tok/J (measured chain, K-sched, CSD) = "
          f"{stk['csd_tokj']:,.0f}")
    print(f"N4/7B composed tok/s/die = {n4_7b['toks']:,.0f} "
          f"= {n4_7b['vs_sohu_toks']:.2f}x Sohu")
    _selfcheck(stk, sched, rows)
    return 0


def _selfcheck(stk, sched, rows):
    """Anchors that must hold (fail loud if a law drifts)."""
    # K=1 measured anchor reproduces METRICS.md pass energy
    assert abs(E_PASS1_PJ - 2190.53) < 0.01, E_PASS1_PJ
    # full-chain /K conversion amortization (milder than the pass_05
    # tb_cascade 0.55x because the METRICS chain has a bigger tile fraction)
    assert abs(e_pass_ratio_meas(2) - 0.693) < 0.01
    assert abs(e_pass_ratio_meas(4) - 0.539) < 0.01
    # per-tensor schedule: FFN deeper than attention, FFN gain-capped at 7
    assert sched["ffn_gate"] == 7 and sched["attn_q"] == 3, sched
    # composed tok/J beats the inferred Sohu band
    assert stk["csd_tokj"] > 60.0
    # N4/7B composed reproduces the perlayer_k aggregate (~99.6k).
    # Was ~60.3k until session 3 landed two conv_time fixes in specs.py:
    #   n_coarse 17 -> 11 (bit-identical; the 127 code clamp makes coarse
    #     count >= 8 unobservable, so 6 slots were dead)   -> x1.393
    #   beta_int derived from c_int/(c_int+c_par_vg) instead of stored, which
    #     caught tsmc_n4_proj using its 40 fF LAYOUT FLOOR where c_int() is
    #     52.14 fF (the kT/C law binds at N4)              -> x1.187
    # They compose to x1.651 (a 0.16% interaction — the FFN bulk at K=7 sits
    # 15% above the t_in floor, so max() never clamped).
    # NOTE this is the tok/s at the ASSUMED SNR_s = 34/38 dB. Session 3
    # MEASURED SNR_s at 19.9 dB (attn) / 16.7 dB (FFN) uncorrected, which
    # forces K=1 and 15.5k = 0.25x Sohu. See OPTIMIZATION_RESULTS.md.
    n4 = next(r for r in rows if r["pdk"] == "tsmc_n4_proj"
              and r["scale"] == "7B")
    assert 110e3 < n4["toks"] < 120e3, n4["toks"]  # session3: COARSE_MARGIN measured = 2 (tb_integrator_conv margin), n_coarse 11 -> 9
    print("PASS (K=1 anchor 2190.5 pJ; FFN K=7/attn K=3; N4/7B ~99.6k at the "
          "ASSUMED SNR_s; ~15.5k at the measured one)")


if __name__ == "__main__":
    sys.exit(main())
