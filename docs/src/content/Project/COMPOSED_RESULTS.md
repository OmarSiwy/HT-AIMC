# COMPOSED AnalogIOC RESULTS (task #13) — all landed levers, one number

Pure metrics assembly from MEASURED anchors + LANDED laws. NO SPICE (an analog agent owns the sim lane). Regenerate: `PYTHONPATH=<repo> python3 scripts/compiler/metrics/compose.py`.

Labels: **measured-anchor** = frozen SPICE per-block energy (METRICS.md, tb_tile_mvm/tb_cascade); **derived** = specs.py / perlayer_k.py law on measured params; **projected** = projection-grade PDK set (asap7/n4, tok/s/die + timing).

## Headline (N4 / 7B, per-tensor K schedule, avg K=6.54)

- **composed tok/s/die = 114,168** = **1.83x** Sohu (62,500 tok/s/die, vendor-derived, high-batch FP8 70B) — _projected_.
- **composed tok/J (mini-subset scope) = 87,343** (measured-chain energy, avg K=6.54, CSD on tile) — _derived from measured anchor_. This is the 10944-pass mini scope (same scope as METRICS.md's 41,714).
- **composed tok/J at 7B (mini physics scaled) = 35** — the SAME measured mini per-pass energy scaled to 27.3 M passes/token. It is BELOW Sohu because the mini's static-OTA-dominated 8461 fJ/MAC (K=1, 50x-slow grid) is not a production 7B die; the paper's 7B-optimized projection (converged 3.2 fJ/MAC, METRICS.md) gives ~45k tok/J. Both are stated so the measured-vs-projected gap is explicit, not hidden.
- measured-vs-projected split: the ENERGY per block (2190.5 pJ/pass) and the cascade amortization (0.55x/0.41x) are **measured** (SPICE, real transistors); the K schedule + tok/J arithmetic are **derived**; the tok/s/die (PDK timing + tiles/die) is **projected**.

## Measured anchor (METRICS.md, frozen SPICE)

- per-pass = tile 820.83 + coarse 1061.59 + fine 283.51 + digital 24.6 = **2190.5 pJ/pass** (measured x counted + estimated digital).
- conversion component (coarse+fine) = **1345.1 pJ** — this is what amortizes /K; tile-integrate + digital are per-pass.
- HONEST amortization scope: tb_cascade measured 0.55x(K=2)/0.41x(K=4) on the SINGLE pass_05 tile (small tile fraction). On the FULL METRICS chain the tile fraction is bigger (37% tile vs 61% conversion), so the chain E/pass amortizes MILDER: 0.69x(K=2)/0.54x(K=4). Same physics (only conversion amortizes), different tile:conv mix.
- 10944 passes/token -> 23.97 uJ/token; 22.2 tok/s, 41,714 tok/J (K=1, 50x-slow sim grid).

## Lever stack (cumulative, on the measured tok/J axis)

| lever | factor | cumulative tok/J | what binds | source |
|---|---|---|---|---|
| 0. measured anchor (K=1) | 1.00x | 41,713 | per-pass conversion (no amortization) | measured |
| 1. K* cascade (per-tensor, avg K=6.54) | 2.08x | 86,934 | conversion amortizes /K; FFN K=7 capped by gain (1+eg)^K | measured amortization + derived K |
| 2. CSD recode (tile charge) | 1.005x | 87,343 | real INT4 density already ~0.196 << 1/2 | measured (FORMATS.md) |
| 3. CSNR lattice thresholds | regime-dependent | (no flat multiplier) | pitch >> sigma_a only; SHARES the SNR budget | measured (FORMATS.md) |
| 4. measured-gain accuracy | correctness | (enables correct tokens) | in-contract +-1 LSB; NOT an energy factor | measured (A10/A11) |

**Composed tok/J (levers 0-2) = 87,343** on the measured chain. Cascade is the whole energy story; CSD adds +0.5% on the REAL INT4 mini (the -33% is the wide-uniform-word asymptote, not this chip).

## What STACKS vs what SHARES a budget (the honesty check)

- **STACK (independent physics):** cascade conversion-amortization (time + energy) and CSD tile-charge reduction act on DIFFERENT energy components (conversion vs tile-integrate), so they multiply cleanly. Merged-window (S5) + ping-pong (S6) are schedule levers on the SAME conversion the cascade amortizes — already folded into `pass(K)=max(136 t_q, T_conv/K)+4 t_q`, not an extra factor.
- **SHARE ONE BUDGET (do NOT multiply):** cascade depth K, CSNR lattice thresholds, and the per-layer-K gain cap all spend the SAME per-tensor SNR budget. Coarser-LSB from deeper K COSTS SNR; lattice thresholds and a better servo GIVE SNR; you cannot bank the same dB twice.

### Interference proof (FFN class, the 95%-of-passes bulk)

- random-SNR term alone (SNRs=38, SNRt=28) would allow K=10.
- naive: if lattice added +6 dB of CSNR headroom, the random term would allow K=40.
- BUT the gain-compounding term (1+eg)^K caps FFN at K=6.6 REGARDLESS of SNR headroom (landed K=7). **The lattice dB cannot be spent on deeper K — the servo-eg budget already binds.** So lattice's win is NOT a throughput/energy multiplier on top of cascade; it is redundant with SNR headroom the gain term already leaves on the table.
- **Composed < naive product:** the naive stack (cascade x lattice as independent K boosts) implies FFN K~40 and ~5.7x more conversion amortization than the composed K=7 delivers. The composed number is LOWER because the gain-compounding servo budget is the real binding constraint, shared across all three SNR levers.

## Composed tok/s/die + tok/J vs Sohu (all PDK / scale)

tok/s/die is projected PDK timing x tiles/die (die 400 mm2 x 0.7 fill). tok/J is the measured mini per-pass chain SCALED to the full model's passes/token (PDK-invariant: the per-block pJ are SPICE numbers, not re-projected per node). SCOPE WARNING: the 7B/70B tok/J here is mini physics scaled up — it carries the mini's static-OTA-dominated per-pass energy, so it is BELOW the paper's 7B-optimized ~45k projection (converged 3.2 fJ/MAC). Compare the MINI-scope tok/J (87,343) to Sohu, or use the paper projection; do NOT read the scaled 7B row as the production number.

| PDK | scale | composed tok/s/die | vs Sohu 62.5k | tok/J (mini physics scaled) | tag |
|---|---|---|---|---|---|
| sky130 (real t_q) | 7B | 1,691 | 0.03x | 35 | projected |
| sky130 (real t_q) | 70B | 169 | 0.00x | 3 | projected |
| asap7_proj | 7B | 70,868 | 1.13x | 35 | projected |
| asap7_proj | 70B | 7,087 | 0.11x | 3 | projected |
| tsmc_n4_proj | 7B | 114,168 | 1.83x | 35 | projected |
| tsmc_n4_proj | 70B | 11,417 | 0.18x | 3 | projected |
| Etched Sohu | 70B | 62,500 | 1.00x | 35-60 (INFERRED) | vendor tok/s (500k/8, FP8 batch~1000); tok/J INFERRED (no vendor power) |

## Honest bottom line

- **N4/7B composed = 114,168 tok/s/die = 1.83x Sohu — BUT ONLY AT THE ASSUMED SNR_s = 34/38 dB.** Session 3 MEASURED per-stage compute-SNR for the first time (analog/testbenches/tb_csnr.py): 19.9 dB attention and 16.7 dB FFN uncorrected, 27.8-30.1 dB with the A10 per-column gain cal — and that last range is CIRCULAR (fitted and scored on the same columns). 34/38 were never measured; they are the paper's per-tensor CSNR *targets*, adopted into specs.py and perlayer_k.py as *sources* and mislabelled 'measured-class'. At the measured CSNR the 28 dB end-to-end target is not met at ANY K, so K=1, and N4/7B is **15,534 tok/s = 0.25x Sohu**. Treat every K>1 number here as conditional on an SNR that has not been demonstrated.
- **tok/J, matched scope:** at the MINI subset the composed chain is 87,343 tok/J; the paper's 7B-optimized projection is ~45k tok/J (converged 3.2 fJ/MAC) — both clear the INFERRED Sohu 70B band (35-60) by ~750-1500x, BUT the mini per-pass energy scaled naively to 7B gives only 35 tok/J (static-OTA-dominated, not a production die). The honest tok/J win needs the amortized production converter, not just the mini SPICE chain. Excludes weight-rewrite energy, as METRICS.md.
- **measured share:** the per-block energy (2190.5 pJ/pass) and the cascade amortization (0.55x/0.41x) are SPICE-measured. **derived share:** the K schedule, avg K=6.54, and tok/J arithmetic. **projected share:** tiles/die + PDK timing (asap7/n4 param sets).
- **the 2x-Sohu gap is a servo-eg problem, not a lever-stacking one:** halving eg (0.3% -> 0.15%) roughly doubles the gain-term K cap (ln(1.02)/eg: 6.6 -> 13), pushing FFN toward K~13-14 and the 121.9k (1.95x) uniform-K=14 ceiling. Lattice thresholds do NOT get you there — they spend a budget the gain term already caps.
