"""Score a design JSON: the four ARCH_METRIC numbers, breakdowns, binding constraint.

    python3 scripts/compiler/metrics/arch_eval/cli.py [design.json] [--conditions arch|sohu]
                                                     [--knob die_mm2=200 ...]
                                                     [--baseline [--wbits 8]] [--sohu-target] [--json]
No argument = the shipped default design (every node on its DEFAULT option). A design run also scores
the systolic baseline with that design's weight and KV formats (lever-matched) and prints the ratios;
--baseline alone keeps W4 (or --wbits) and the default KV16 unless --knob kv_bits=N.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from arch_eval import asap7, baseline_systolic, design, metric, model  # noqa: E402

LABEL = ("projected: laws applied to measured sky130 anchors, measured ASAP7 gm/Id and "
         "literature constants; a number is 'derived' only when every input is measured")


def table(s, k):
    """The standard systolic-array metrics at the peak-tok/s point, per die. Peak and utilization
    are the tiles' weight GEMM/GEMV; achieved adds the attention MACs run on the digital rail."""
    pk, t, d = s["peak"], s["tile"], s["die"]
    peak, tiles = 2 * d["mac_rate"] / 1e12, 2 * pk["tile_macs_s_die"] / 1e12
    return dict(peak_tops=peak, achieved_tops=2 * pk["useful_macs_s_die"] / 1e12, tile_tops=tiles,
                utilization=tiles / peak, peak_tops_mm2=peak / k["die_mm2"],
                pj_per_mac=t["e_pass_J"] / t["macs_per_pass"] * 1e12, pass_rate_GHz=1e-9 / t["t_pass_s"],
                stage_ns=t.get("t_stage_s", t["t_pass_s"]) * 1e9, decode_step_ms=pk["T_step_s"] * 1e3,
                hbm_GBps=pk["hbm_Bps_die"] / 1e9, hbm_decode_GBps=pk["hbm_Bps_decode_die"] / 1e9,
                hbm_avail_GBps=k["hbm_Bps"] / 1e9, hbm_MB_per_token=pk["hbm_bytes_per_token"] / 1e6,
                buffer_MB=s.get("buffer_MB"))


def matched_baseline(d, s, conditions, knobs):
    """The systolic baseline with the design's memory formats (N8 fairness rule): its weight width in
    HBM (FP8 under sohu, which fixes the format) and its KV format. Same die, HBM, rail and schedule."""
    wb = metric.SOHU_WBITS if conditions == "sohu" else s["tile"]["fmt"]["wbits"]
    mem = {k: v for k, v in d["params"].items() if k.startswith(("kv_", "nn_"))}
    return wb, baseline_systolic.evaluate(wb, knobs, mem)


def show(s, title, k):
    print(f"== {title}")
    if s.get("infeasible"):
        print(f"   INFEASIBLE at every operating point (tok/J over KV/power/quality-feasible points: {s['tok_j']:.4g})")
        return
    pk, t, d = s["peak"], s["tile"], s["die"]
    print(f"   tok/s per die  {s['tok_s_die']:12.5g}   (generated-only {s['gen_tok_s_die']:.5g})")
    print(f"   TOPS/W         {s['tops_w']:12.5g}   (x b_w x b_x = {s['tops_w'] * t['fmt']['wbits'] * t['fmt']['abits']:.4g} bit-normalized, 27n1)")
    print(f"   tok/W          {s['tok_w']:12.5g}")
    print(f"   tok/J          {s['tok_j']:12.5g}   (at VDD {s['best_j']['vdd']}, clk x{s['best_j']['clk_frac']}, B {s['best_j']['B']})")
    print(f"   reported:      tok/s per mm2 {s['tok_s_mm2']:.5g}, tok/s per mm2 per W {s['tok_s_mm2_W']:.5g}")
    print(f"   label: {LABEL}")
    print(f"   peak point: VDD {pk['vdd']} V, clock x{pk['clk_frac']}, B {pk['B']} (KV limit {pk['b_max']}), "
          f"{s['plan']['mode']}, dies {pk['dies']}, per-stream {pk['per_stream_tok_s']:.4g} tok/s")
    print(f"   binding: {s['binding']}")
    print(f"   power per die: die {pk['die_power_W']:.4g} W, external memory {pk['ext_power_W']:.4g} W")
    print(f"   tile: {t['rows']}x{t['cols']} x{t['slices']} slice(s), pass {t['t_pass_s'] * 1e9:.4g} ns, "
          f"{t['e_pass_J'] * 1e12:.4g} pJ/pass = {t['e_pass_J'] / t['macs_per_pass'] * 1e15:.4g} fJ/MAC, "
          f"{t['area_um2']:.4g} um2, SNR {t['snr_db']:.4g} dB {({k: round(v, 1) for k, v in t['snr_parts_db'].items()})}")
    print("   tile energy/pass pJ: " + ", ".join(f"{k} {v * 1e12:.4g}" for k, v in t["e_pass_J_parts"].items()))
    print("   tile area um2:       " + ", ".join(f"{k} {v:.4g}" for k, v in t["area_um2_parts"].items()))
    print(f"   die: {d['n_tiles']} tiles ({d['tiles_needed']} per weight copy), "
          f"{d['mac_rate'] / 1e12:.4g} TMAC/s, static {d['static_W']:.3g} W")
    print("   die area mm2:        " + ", ".join(f"{k} {v:.4g}" for k, v in d["area_mm2"].items()))
    print("   energy/token uJ:     " + ", ".join(f"{k.strip()} {v * 1e6:.4g}" for k, v in pk["energy_per_token_J"].items()))
    print(f"   time: wave {pk['T_wave_s']:.4g} s = prefill {pk['T_prefill_s']:.4g} s + 128 x step {pk['T_step_s'] * 1e3:.4g} ms")
    m = table(s, k)
    print(f"   throughput:    peak {m['peak_tops']:.4g} TOPS (tiles), achieved {m['achieved_tops']:.4g} TOPS "
          f"(tiles {m['tile_tops']:.4g} + attention), utilization {m['utilization'] * 100:.3g} %, "
          f"{m['peak_tops_mm2']:.3g} TOPS/mm2 peak, {m['pj_per_mac']:.3g} pJ/MAC (tile)")
    print(f"   rate/latency:  {m['pass_rate_GHz']:.3g} G passes/s x {t['macs_per_pass']} MAC, stage {m['stage_ns']:.3g} ns, "
          f"decode step {m['decode_step_ms']:.3g} ms")
    print(f"   memory:        HBM {m['hbm_GBps']:.4g} GB/s wave average, {m['hbm_decode_GBps']:.4g} GB/s in decode, "
          f"of {m['hbm_avail_GBps']:.4g}; {m['hbm_MB_per_token']:.3g} MB HBM traffic per token; on-chip buffer {m['buffer_MB']} MB")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("design", nargs="?")
    ap.add_argument("--knob", action="append", default=[], help="key=value over metric.KNOBS")
    ap.add_argument("--baseline", action="store_true", help="score the digital systolic baseline instead")
    ap.add_argument("--wbits", type=int, help="baseline HBM weight bits (default 4; 8 under sohu)")
    ap.add_argument("--conditions", default="arch", choices=sorted(metric.CONDITIONS),
                    help="condition set: arch = ARCH_METRIC, sohu = Etched's benchmark conditions")
    ap.add_argument("--sohu-target", action="store_true",
                    help="calibrate the systolic die to Sohu's claimed tok/s per chip; print its area and power")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    knobs = metric.knobs_for(a.conditions)
    for kv in a.knob:
        key, val = kv.split("=")
        cur = knobs.get(key, 0.0)
        knobs[key] = val if isinstance(cur, str) else type(cur)(float(val))
    wbits = a.wbits or (metric.SOHU_WBITS if a.conditions == "sohu" else 4)
    if a.sohu_target:
        area, s = baseline_systolic.sohu_equivalent()
        if area is None:
            print(f"== Sohu target {metric.SOHU_TOK_S_CHIP:.0f} tok/s/chip NOT reached up to 2000 mm2: "
                  f"best {s['tok_s_die']:.5g}, binding {s.get('binding')}")
            return s
        print(f"== Sohu-equivalent systolic die at ASAP7 (projected; calibrated to the vendor's "
              f"{metric.SOHU_TOK_S_CHIP:.0f} tok/s per chip, Llama-3-70B FP8, 2048/128, batch 1000): {area:.4g} mm2")
        show(s, "sohu-equivalent", metric.knobs_for("sohu", die_mm2=area))
        return s
    b = None
    if a.baseline:
        s, title = baseline_systolic.evaluate(wbits, knobs), f"systolic baseline (W{wbits} in HBM)"
    else:
        d = design.load(a.design) if a.design else design.make(name="default")
        s, title = model.evaluate(d, knobs), d["name"]
        if s.get("peak"):
            wb, b = matched_baseline(d, s, a.conditions, knobs)
    title += f" [{a.conditions} conditions]"
    ratio = {m: s[m] / b[m] for m in metric.METRICS} if b and b.get("peak") else None
    if a.json:
        print(json.dumps({m: s[m] for m in metric.METRICS + ("tok_s_mm2", "tok_s_mm2_W")} | dict(
            binding=s.get("binding"), errors=s.get("errors", []), table=s.get("peak") and table(s, knobs),
            vs_matched_baseline=ratio), indent=1))
        return s
    show(s, title, knobs)
    if ratio:
        mb = table(b, knobs)
        mt = table(s, knobs)
        print(f"== vs systolic baseline, lever-matched (W{wb} in HBM, this design's KV format; same die, HBM, rail)")
        print(f"   baseline:      tok/s {b['tok_s_die']:.5g}, TOPS/W {b['tops_w']:.4g}, tok/W {b['tok_w']:.4g}, "
              f"tok/J {b['tok_j']:.4g}; peak {mb['peak_tops']:.4g} TOPS, utilization {mb['utilization'] * 100:.3g} %, "
              f"B {b['peak']['B']}")
        print("   design/base:   " + ", ".join(f"{m} {r:.3g}x" for m, r in ratio.items())
              + f"; peak TOPS {mt['peak_tops'] / mb['peak_tops']:.3g}x, utilization {mt['utilization'] / mb['utilization']:.3g}x")
    for nid, prov in s.get("provenance", {}).items():
        print(f"   {nid:<14} {prov}")
    r = asap7.report()
    print(f"   asap7 constants: {r['keys_from_file']} keys from file; {len(r['keys_on_fallback'])} on fallback"
          + (f" ({r['load_error']})" if r["load_error"] else ""))
    for e in s.get("errors", []):
        print(f"   NODE FALLBACK: {e}")
    return s


if __name__ == "__main__":
    main()
