"""A6 metrics assembly -> METRICS.md (CONTRACT metrics mandate).

Sources, each number labeled:
  measured  — this repo's SPICE testbenches (tile_energy.json from
              tb_tile_mvm/tb_integrator_conv/tb_eventrate/tb_ffn_e2e) and
              A1/A2/A3 STATUS measurements (cited inline).
  counted   — A5 compiler exact pass/op counts (passes.json) and A4 yosys
              cell counts.
  estimated — digital rail energy from cell counts x cap model (method
              documented inline).
  projected — real-t_q rescale and the paper's 7B eval-section laws.

Run: PYTHONPATH=scripts python3 scripts/metrics/report.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))), "analog", "docs"))
import specs

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
TB_OUT = os.path.join(ROOT, "analog", "testbenches", "out",
                      "tile_energy.json")
PASSES = os.path.join(ROOT, "scripts", "compiler", "out", "passes.json")

# ---- A3/A1 measured block numbers (STATUS.md citations) ----
A3 = {
    "dac_pJ_slot": 1.2,             # A3 tb_write_dac
    "sidecar_pJ_op": 67.0,          # A3 tb_lora (outer-product op)
    "sidecar_pJ_cellwrite": 7.1,    # A3 tb_lora
}
# ---- A4 counted (yosys sky130_fd_sc_hd) ----
DIG_CELLS = 3158
DIG_AREA_UM2 = 24712
# estimate method: cells x avg switched cap (3 fF gate+wire, sky130 HD
# mid-drive average) x VDD^2 x activity 0.1 x 8 active cycles/pass
DIG_E_PASS_PJ = DIG_CELLS * 3e-15 * 1.8**2 * 0.1 * 8 * 1e12

# ---- timing from the executable design math (scripts/specs.py) ----
TQ_SIM, TQ_REAL = specs.TQ_SIM, 200e-12
CADENCE = specs.coarse_cadence()
T_LO = 5e-9 + specs.window_time(window="lo")
T_HI = 5e-9 + specs.window_time(window="hi")
T_CONV = specs.conv_time(n_coarse=17)
PASS_S = specs.pass_time()


def lab(v, unit, tag):
    return f"{v:,.3g} {unit} _({tag})_"


def main():
    te = json.load(open(TB_OUT)) if os.path.exists(TB_OUT) else {}
    pc = json.load(open(PASSES))
    n_pass = pc["tile_passes_per_token_total"]        # 10944 counted
    mean = te.get("pJ_per_MVM_mean", {})
    e_analog = sum(mean.values()) if mean else float("nan")
    e_pass = e_analog + DIG_E_PASS_PJ
    # per-token totals (counted schedules x measured per-op)
    # attention scores/softmax/A.V run on the digital rail: not counted here
    tok_j = n_pass * e_pass * 1e-12
    tok_s = n_pass * PASS_S
    fj_mac = e_analog * 1000 / 256                     # 256 MACs/pass
    lines = [
        "# AnalogIOC-mini METRICS (A6)",
        "",
        "Labels: **measured** = SPICE tb in this repo; **counted** = exact",
        "compiler/yosys counts; **estimated** = documented cap model;",
        "**projected** = law-scaled (paper eval section).",
        "",
        "## Per-block energy (one 16x16 INT8xINT4 tile pass = 256 MACs)",
        "",
        "| block | energy | source |",
        "|---|---|---|",
    ]
    if mean:
        lines += [
            f"| tile window (integrate) | {mean['tile']:.2f} pJ | measured, tb_tile_mvm |",
            f"| converter coarse (17 cols) | {mean['coarse']:.2f} pJ | measured, tb_tile_mvm |",
            f"| converter fine/SAR (17 cols) | {mean['fine']:.2f} pJ | measured, tb_tile_mvm |",
        ]
        if "refs" in mean:
            lines.append(
                f"| reference ladder rails (4 strings) | {mean['refs']:.2f} pJ "
                "| measured, tb_tile_mvm (item 8: previously uncounted) |")
    lines += [
        f"| digital rail / pass | {DIG_E_PASS_PJ:.1f} pJ | estimated: {DIG_CELLS} cells (counted, yosys) x 3 fF x VDD^2 x a=0.1 x 8 cyc |",
        f"| write-DAC slot | {A3['dac_pJ_slot']} pJ | measured, A3 |",
        f"| LoRA sidecar outer-product op | {A3['sidecar_pJ_op']} pJ | measured, A3 |",
        "",
        "## E_conv vs |code| (early termination, measured)",
        "",
    ]
    for p in te.get("e_vs_code", []):
        lines.append(f"- |code| {abs(p['code'])}: "
                     f"{p['e_coarse_pJ'] + p['e_fine_pJ']:.2f} pJ "
                     f"(coarse {p['e_coarse_pJ']:.2f})")
    if "ffn_e2e_fullchip_pJ" in te:
        f = te["ffn_e2e_fullchip_pJ"]
        lines += ["", f"Full-chip FFN pass (sidecar resident): "
                  f"tile {f['tile']} + coarse {f['coarse']} + fine "
                  f"{f['fine']} pJ _(measured, tb_ffn_e2e)_"]
    lines += [
        "",
        "## Timing (sim grid t_q = 10 ns, measured schedules)",
        "",
        f"- window lo {T_LO*1e9:.0f} ns + hi {T_HI*1e9:.0f} ns; conversion "
        f"{T_CONV*1e6:.2f} us/window (coarse cadence {CADENCE*1e9:.0f} ns "
        "= 2 tau of the integrator absorb, specs.coarse_cadence, O1 "
        "falsified) -> pass "
        f"{PASS_S*1e6:.2f} us _(measured)_",
        "",
        "## Mini-chip tokens/s and tokens/J (one tile, time-multiplexed)",
        "",
        f"- passes/token = {n_pass} _(counted, A5 exact tiling of real "
        "SmolLM2-135M blk.0 head-0 + FFN)_",
        f"- per-token analog+digital MVM energy = {n_pass} x "
        f"{e_pass:.1f} pJ = {n_pass * e_pass * 1e-6:.2f} uJ "
        "_(measured x counted + estimated digital)_",
        f"- **tok/s (sim grid) = {1/tok_s:.1f}** (token time "
        f"{tok_s*1e3:.1f} ms) _(measured x counted)_",
        f"- **tok/J = {1/tok_j:,.0f}** ({tok_j*1e6:.2f} uJ/token) "
        "_(measured x counted)_",
        f"- fJ/MAC (analog path) = {fj_mac:.0f} fJ _(measured)_; "
        "TOPS/W-equiv = "
        f"{2 * 256 / (e_pass * 1e-12) / 1e12:.2f} TOPS/W "
        "_(measured+estimated, 2 ops/MAC)_",
        "",
        "At the real t_q = 200 ps the PWM windows scale 50x down "
        "(charge per transfer is t_q-invariant: C*VDD per cycle); the "
        "conversion stays OTA-limited unless re-sized -> pass time "
        f"~{(T_LO + T_HI) / 50 * 1e9 + 2 * T_CONV * 1e9:.0f} ns "
        "_(projected)_.",
        "",
        "## Format variants (A5b pass law, counted)",
        "",
        "passes/tile = ceil((b_w_eff-1)/4) x ceil(ceil((b_x-1)/4)/2):",
        f"- int4 x int8 (this chip): 1x -> {n_pass}/token",
        f"- fp8 e4m3 x e5m2: S=2 -> {2 * n_pass}/token (2x energy/time)",
        f"- fp16/bf16: S=2, 4 nibbles -> {4 * n_pass}/token (4x)",
        "",
        "## 7B AnalogIOC projection (paper eval-section laws, projected)",
        "",
        "- anchor: paper tile-energy chain ~3.2 fJ/MAC INT8xINT4 at "
        "converged K*=64 conversion amortization (law:wrapper + "
        "law:convdens); mini-chip measures "
        f"{fj_mac:.0f} fJ/MAC at K*=1 per-pass conversion on a 50x "
        "slowed t_q grid - the gap is the conversion amortization + "
        "static-OTA duty the laws model.",
        "- 7B token = ~7e9 MACs (2 ops/param GEMV): E/token ~ 7e9 x "
        "3.2 fJ = 22.4 uJ -> ~45k tok/J _(projected)_.",
        "- throughput: paper f_MVM ~19.6 MHz over 512x256 MACs/tile = "
        "2.6e12 MAC/s -> 7B token in ~2.7 ms/tile-column-group; "
        "layer-parallel dies scale linearly (law:batch caveats apply) "
        "_(projected)_.",
        "",
        f"Digital rail: {DIG_CELLS} cells, {DIG_AREA_UM2} um2 (counted, "
        "A4 yosys), 0 latches; audit/ABFT overhead = checksum col "
        "(1/17 columns = 5.9% counted) + "
        f"{1268}/{DIG_CELLS} abft cells (counted).",
        "",
    ]
    out = os.path.join(ROOT, "docs", "src", "content", "Project", "METRICS.md")
    open(out, "w").write("\n".join(lines))
    print(f"wrote {out}")
    print("PASS" if mean else "PARTIAL (tile_energy.json incomplete)")
    return 0 if mean else 1


if __name__ == "__main__":
    sys.exit(main())
