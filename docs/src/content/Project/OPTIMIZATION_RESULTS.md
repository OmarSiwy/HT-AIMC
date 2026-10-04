# AnalogIOC optimization campaign — consolidated honest scorecard

Date: 2026-08-29. Baseline `ce939f6` → head (25+ commits). Every number below
is labeled **measured** (SPICE tb in this repo), **derived** (specs.py law on
measured params), or **projected** (projection-grade PDK sets / model-scaling,
low confidence). The campaign's discipline was to surface and *correct* its own
overclaims rather than ship green lies — the corrections are listed as
prominently as the wins.

## 1. Executive summary (the honest headline)

- **Weight engine tok/s vs Etched Sohu: PARITY→1.20×** (N4/7B: series **0.97×**,
  parallel super-tile **1.20×**, projected), not the 2× an early pass claimed.
  The parallel super-tile is now SPICE-VERIFIED (gain error flat 0.44% across
  K=1/2/4 vs series 0.44→1.13%); it lifts FFN K 7→9 (+2 free), but 2× is not
  reachable — the random √K term caps FFN at K=9 and the gain servo is
  Pelgrom-floored. Past 1.20× needs higher per-stage SNR, not topology.
- **tok/J: >5× vs an INFERRED Sohu number, and PROJECTION-CONTINGENT.** The
  measured mini SPICE chain is static-OTA-dominated (~35 tok/J at 7B, *loses*
  to Sohu); the win requires the paper's amortized converter (~45k tok/J
  projection). Sohu published no power number — the 35–60 tok/J band we
  compare against is inferred, not vendor.
- **Cascade STRUCTURE is silicon-proven** (energy/pass 0.55×/0.41×, chain
  0.49×/0.31× at K=2/4, measured). This is the real tok/s + tok/J lever.
- **Accuracy is model-adequate, not bit-exact.** The tile reads ±3 LSB (not
  ±1) on real multi-bank passes; the model tolerates ±8 LSB (100% argmax) — so
  it's fine. The strict ±1 gate was a converter-ENOB target, not a model
  requirement.

## 2. Silicon-proven (measured SPICE)

| Result | Measured | Commit |
|---|---|---|
| K* cascade amortization | E/pass 0.55×(K2)/0.41×(K4); chain 0.49×/0.31×; timing tracks law ±15 ns | ad8e4a3 |
| Cascade mechanism faithful | cascade-c1 == proven lo window bit-for-bit | ec97a2f |
| Multi-bank charge deficit root cause | real column delivers ~84% of ideal (finite-OTA on shared rail + C_RAIL) | ec97a2f |
| Per-column measured gain | col1 −48 → exact (removes cell-pattern scatter) | bff2b15 |
| mac+15 fine-SAR fix | tb_integrator_conv 5/5 ±1 LSB (fine_ref_trim) | 30022ce |
| Tile accuracy model-adequate | ±3 LSB measured; model tolerant to ±8 (argmax 100%) | cd44e48/ee8e810 |
| Parallel super-tile | gain error K-INDEPENDENT (flat 0.44% K=1/2/4 vs series 0.44→1.13%); 1.20× Sohu; charge-bus lossy→INT8 digital sum | 84410e6 |

## 3. Projected (labeled, lower confidence)

- **tok/s/die 7B (per-layer K, avg K=6.54):** sky130-real ~1.0k, asap7 42.8k,
  **N4 60.3k = 0.97× Sohu** (derived from measured amortization + PDK laws).
- **tok/J 7B:** amortized-converter projection ~45k (>5× the inferred Sohu
  band); the measured mini chain is ~35 (static-OTA-limited) — gap is the
  amortization the mini's 50×-slow grid doesn't show.
- **3D vertical (L):** capacity 11→3–6 dies at realistic L=2–4; **not an
  energy win** (+½log₂L converter bit → falsifier fires at L=2). L=8 charge-
  domain is projection-only (no silicon).
- **MoE:** tok/J advantage = E/k (DeepSeek 32×, Mixtral 4×), on the existing
  charge-domain substrate; needs per-expert gating + separate-tile mapping.

## 4. Honest negatives (what does NOT work — as valuable as the wins)

- **DPS-48 bilinear:** exact in integer arith (−0.02 dB) but +4.7–10.9 dB
  under INT4 cap quantization; recovering it needs 1.5× passes → net-negative.
  Dead-end at INT4 (may revive at fp8). `0d59d88`
- **CSD recode:** −0.6% real (not −33%) — real INT4 weight density is already
  0.196 ≪ ½, so signed-digit recode barely helps. `9ebd804`
- **Adaptive-range converter:** ~0.2% whole-pass — early-termination already
  harvested it; 83% of pass energy is OTA static (conversion *time*), which
  range doesn't shorten. Did NOT build the circuit. `07c4c7c`
- **2× tok/s via gain servo:** not reachable — eg→tok/s saturates at ~1.2×
  (random √K caps FFN K at 9–10); Pelgrom uncorrelated floor (1.4–2.3%) sits
  ~10× above the 0.15% eg the 2× would need. `a0b47d7`
- **Levers don't multiply:** cascade-K, lattice thresholds, per-layer-K all
  draw the *same* SNR budget; only cascade-amortization × CSD stack. `9ebd804`
- **Count-dependent INL theory:** wrong — it's fine-SAR mid-code DNL ×
  mixed-sign gain (no cheap digital-LUT fix). `d75a817`

## 5. vs Etched Sohu — the honest comparison (SOHU_VERIFIED.md, 844587e)

- Sohu **62.5k tok/s/die** = vendor 500k/8-chip, at **Llama-70B FP8
  batch~1000** — a high-batch GEMM number, NOT batch-1 decode (where AnalogIOC's
  analog edge lives). tok/s comparison is thus cross-regime.
- Sohu **tok/J is UNPUBLISHED**; the 35–60 band is inferred. Our ">5× tok/J"
  is our projection vs an inferred denominator.

## 6. Remaining work (ranked, not blocking the above)

- **#22 parallel super-tile** — SPICE verification in flight; projected ~1.2×
  tok/s (gain K-independent). Modest; optional.

## 7. The one-paragraph verdict

AnalogIOC is a **defensible energy-efficient analog accelerator, not a raw-speed
killer**. Its silicon-proven strengths are the cascade amortization and model-adequate charge-domain accuracy;
its honest position is **tok/s parity** with a 4 nm production ASIC (projected)
and a **tok/J advantage that is real in the laws but projection-contingent** on
the amortized converter, compared against a Sohu energy number that isn't even
published. The campaign's value is the *map*: every lever measured or refuted,
every claim labeled, the wins (cascade) separated cleanly from the
mirages (2× tok/s, −33% CSD, DPS-48, adaptive range).
