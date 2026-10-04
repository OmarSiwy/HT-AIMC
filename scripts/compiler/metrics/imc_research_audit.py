"""Reproduce arithmetic in docs/src/content/Project/IMC_OPTIMIZATION_RESEARCH.md.

Stdlib only. These are bounds/scenarios, not a chip simulator. No file writes.
Run: python3 scripts/compiler/metrics/imc_research_audit.py
Frozen inputs are explicitly sourced below; existing projection code is not
imported because it combines incompatible capacity/accuracy assumptions.
"""
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def energy_bound(macs_per_token, tops_per_w):
    """2 operations/MAC; compute-only at the stated operation precision."""
    assert macs_per_token > 0 and tops_per_w > 0
    joules = 2 * macs_per_token / (tops_per_w * 1e12)
    return {"joules_per_token": joules, "tokens_per_joule": 1 / joules}


def resident_dies(weights, weights_per_tile, tile_mm2, usable_mm2):
    assert min(weights, weights_per_tile, tile_mm2, usable_mm2) > 0
    tiles = math.floor(usable_mm2 / tile_mm2)
    assert tiles > 0
    capacity = tiles * weights_per_tile
    return {"weights_per_die": capacity, "minimum_dies": math.ceil(weights / capacity)}


def self_check():
    # Physical identities catch the energy-unit, and capacity
    # mistakes found in the research. These do not validate the input models.
    assert math.isclose(energy_bound(7e9, 8)["joules_per_token"], 0.00175)
    assert math.isclose(energy_bound(7e9, 8)["tokens_per_joule"], 571.4285714285714)
    assert resident_dies(1001, 10, 1, 100)["minimum_dies"] == 2
    # Four independently digitized partials require four conversions.
    partials = [19, 18, 23, 15]
    assert sum(partials) == 75 and len(partials) == 4


def audit():
    # docs/src/content/Project/METRICS.md, baseline 16x16 pass; mixed SPICE+digital estimate.
    pass_pj = 820.83 + 1061.59 + 283.51 + 24.6
    fixed_pj = 820.83 + 24.6
    result = {
        "labels": "Derived arithmetic on stated inputs; no new SPICE or silicon measurements",
        "self_check": "PASS",
        "baseline": {
            "pass_pj": pass_pj,
            "fJ_per_MAC": pass_pj * 1000 / 256,
            "TOPS_per_W_equivalent": 512 / pass_pj,
            "mini_subset_tokens_per_J": 1 / (10944 * pass_pj * 1e-12),
            "7B_MAC_only_tokens_per_J": 1 / (7e9 / 256 * pass_pj * 1e-12),
            "7B_zero_conversion_energy_tokens_per_J": 1 / (7e9 / 256 * fixed_pj * 1e-12),
            "eliminate_all_conversion_energy_max_gain": pass_pj / fixed_pj,
        },
    }
    # scripts/compiler/metrics/pdk_projections.py: DIE_MM2=400, FILL=.7,
    # TILE_MM2[n4]=.006, SCALES divide parameters by 256 MAC/pass.
    result["resident_capacity"] = {
        str(p): resident_dies(p, 256, 0.006, 400 * 0.7)
        for p in (7_000_000_000, 70_000_000_000)
    }
    # Paper sec_eval alternatives, applied to the SAME 280 mm2 usable area.
    result["paper_capacity_scenarios_7B"] = {
        str(area): resident_dies(7_000_000_000, 512 * 256, area, 400 * 0.7)
        for area in (0.03, 0.04, 0.1, 0.5)
    }
    # Full INT4 reload per batch; no protocol/metadata/programming overhead.
    result["7B_weight_stream_TB_per_s_at_17915_tokens_per_s"] = {
        str(batch): (7e9 * 4 / 8) * 17915 / batch / 1e12
        for batch in (1, 8, 64, 1000)
    }
    # Generic 32-layer GQA design point, not asserted as any named checkpoint.
    # L=32, H_kv=8, d_head=128, 4-bit KV; exact full-context attention.
    result["KV_scenarios"] = {}
    for context in (2048, 4096, 32768):
        kv_bytes = 2 * 32 * 8 * 128 * context * 4 / 8
        attn_macs = 2 * 32 * 32 * 128 * context  # H_q=32, including GQA reuse
        result["KV_scenarios"][str(context)] = {
            "bytes_per_session": kv_bytes,
            "bytes_at_64_sessions": kv_bytes * 64,
            "attention_MACs_per_token": attn_macs,
            "external_KV_TB_per_s_at_62500_tokens_per_s": kv_bytes * 62500 / 1e12,
        }
    # Operation-equivalent targets; all are compute-only, with precision and
    # boundary matching still required. They are NOT competitor token rates.
    result["7B_MAC_only_energy_targets"] = {
        str(tops): energy_bound(7e9, tops) for tops in (8, 25 / 3, 120, 200, 625)
    }
    # More SNR through pure independent-noise averaging or capacitor area costs
    # 10**(delta_dB/10). Systematic nonlinear errors do not follow this rule.
    result["noise_power_reduction_from_28_45dB"] = {
        str(target): 10 ** ((target - 28.45) / 10)
        for target in (31.11, 36.74, 43.33)
    }
    # Optional existing analysis artifacts; no need to regenerate or overwrite.
    depth_path = ROOT / "scripts/compiler/out/depth_budget.json"
    if depth_path.exists():
        d = json.loads(depth_path.read_text())
        tensor_total = sum(x["kl"] for x in d["tens"])
        result["existing_depth_experiment"] = {
            "source": str(depth_path.relative_to(ROOT)),
            "scope": "SmolLM2-135M, 256 tokens, greedy tokenizer, simulated errors",
            "SNR_at_KL_proxy_gate_dB": d["snr_t_emp"],
            "actual_PPL_ratio_at_that_gate": d["ver"]["ppl_ratio"],
            "PPL_ratio_at_28dB": d["ctl"]["ppl_ratio"],
            "hot_layer": d["hot"],
            "ffn_down_fraction_of_tensor_KL": next(x["kl"] for x in d["tens"] if x["tensor"] == "ffn_down") / tensor_total,
            "quiet_layer_SNR_proxy_dB": d["snr_t_quiet"],
        }
    return result


if __name__ == "__main__":
    self_check()
    print(json.dumps(audit(), indent=2))
