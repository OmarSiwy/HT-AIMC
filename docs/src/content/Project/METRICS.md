# AnalogIOC-mini METRICS (A6)

Labels: **measured** = SPICE tb in this repo; **counted** = exact
compiler/yosys counts; **estimated** = documented cap model;
**projected** = law-scaled (paper eval section).

## Per-block energy (one 16x16 INT8xINT4 tile pass = 256 MACs)

| block | energy | source |
|---|---|---|
| tile window (integrate) | 820.83 pJ | measured, tb_tile_mvm |
| converter coarse (17 cols) | 1061.59 pJ | measured, tb_tile_mvm |
| converter fine/SAR (17 cols) | 283.51 pJ | measured, tb_tile_mvm |
| digital rail / pass | 24.6 pJ | estimated: 3158 cells (counted, yosys) x 3 fF x VDD^2 x a=0.1 x 8 cyc |
| KV cell write | 7.5 fJ | measured, A3 |
| KV 8-row read pass | 2.4 pJ | measured, A3 |
| write-DAC slot | 1.2 pJ | measured, A3 |
| softmax op (settle x static) | 2.08 pJ | measured, A3 |
| LoRA sidecar outer-product op | 67.0 pJ | measured, A3 |

## E_conv vs |code| (early termination, measured)

- |code| 0: 0.48 pJ (coarse 0.20)
- |code| 16: 0.91 pJ (coarse 0.64)
- |code| 16: 0.91 pJ (coarse 0.64)
- |code| 51: 1.79 pJ (coarse 1.52)
- |code| 127: 4.83 pJ (coarse 4.56)

## Timing (sim grid t_q = 10 ns, measured schedules)

- window lo 165 ns + hi 1285 ns; conversion 1.26 us/window (coarse cadence 60 ns = 2 tau of the integrator absorb, specs.coarse_cadence, O1 falsified) -> pass 4.12 us _(measured)_
- KV col write slot 150 ns (settle 17 ns, A1); softmax settle 0.99 us _(measured)_

## Mini-chip tokens/s and tokens/J (one tile, time-multiplexed)

- passes/token = 10944 _(counted, A5 exact tiling of real SmolLM2-135M blk.0 head-0 + FFN)_
- per-token analog+digital MVM energy = 10944 x 2190.5 pJ = 23.97 uJ _(measured x counted + estimated digital)_
- per-token KV/softmax adds 27.0 pJ _(measured x counted: 16 col writes + 2 read passes + softmax settle)_
- **tok/s (sim grid) = 22.2** (token time 45.1 ms) _(measured x counted)_
- **tok/J = 41,714** (23.97 uJ/token) _(measured x counted)_
- fJ/MAC (analog path) = 8461 fJ _(measured)_; TOPS/W-equiv = 0.00 TOPS/W _(measured+estimated, 2 ops/MAC)_

At the real t_q = 200 ps the PWM windows scale 50x down (charge per transfer is t_q-invariant: C*VDD per cycle); the conversion stays OTA-limited unless re-sized -> pass time ~2549 ns _(projected)_.

## Format variants (A5b pass law, counted)

passes/tile = ceil((b_w_eff-1)/4) x ceil(ceil((b_x-1)/4)/2):
- int4 x int8 (this chip): 1x -> 10944/token
- fp8 e4m3 x e5m2: S=2 -> 21888/token (2x energy/time)
- fp16/bf16: S=2, 4 nibbles -> 43776/token (4x)

## 7B AnalogIOC projection (paper eval-section laws, projected)

- anchor: paper tile-energy chain ~3.2 fJ/MAC INT8xINT4 at converged K*=64 conversion amortization (law:wrapper + law:convdens); mini-chip measures 8461 fJ/MAC at K*=1 per-pass conversion on a 50x slowed t_q grid - the gap is the conversion amortization + static-OTA duty the laws model.
- 7B token = ~7e9 MACs (2 ops/param GEMV): E/token ~ 7e9 x 3.2 fJ = 22.4 uJ -> ~45k tok/J _(projected)_.
- throughput: paper f_MVM ~19.6 MHz over 512x256 MACs/tile = 2.6e12 MAC/s -> 7B token in ~2.7 ms/tile-column-group; layer-parallel dies scale linearly (law:batch caveats apply) _(projected)_.

## Composed levers (task #13, all landed optimizations stacked)

See `docs/src/content/Project/COMPOSED_RESULTS.md` (regenerate: `PYTHONPATH=<repo>
python3 scripts/compiler/metrics/compose.py`). Composes THIS measured 2190.5 pJ/pass
chain with the landed levers:

- **K\* cascade (per-tensor, avg K=6.54):** the conversion component
  (coarse+fine 1345.1 pJ) amortizes /K; tile-integrate (820.83) + digital
  (24.6) stay per-pass. tb_cascade MEASURED 0.55x(K=2)/0.41x(K=4) on the
  pass_05 tile; on THIS fuller chain (37% tile / 61% conversion) it amortizes
  milder, 0.69x/0.54x. Mini-scope composed tok/J = **87,343** (2.09x the
  41,714 K=1 anchor) _(measured amortization x derived K)_.
- **CSD recode:** -0.6% tile charge on the REAL INT4 mini (the paper -33% is
  the wide-uniform-word asymptote; real INT4 density already ~0.196 << 1/2).
  Negligible here _(measured, FORMATS.md)_.
- **CSNR lattice thresholds:** regime-dependent (pitch >> sigma_a); NOT a flat
  multiplier and SHARES the per-tensor SNR budget with cascade K — does NOT
  stack on throughput/energy _(measured, FORMATS.md)_.
- **measured-gain accuracy:** a correctness precondition (in-contract +-1 LSB),
  not an energy/throughput factor _(measured, A10/A11)_.

**Composed headline (N4/7B) = 60,328 tok/s/die = 0.97x Sohu** _(projected)_ —
throughput-set by the K schedule, FFN bulk gain-capped at K=7. INTERFERENCE:
cascade K, lattice thresholds, and the per-layer-K gain cap draw on ONE SNR
budget; only cascade-amortization x CSD-tile-charge stack multiplicatively.
The composed number is BELOW the naive lever product because the
gain-compounding servo-eg term (ln(1.02)/eg=6.6) binds FFN at K=7 regardless
of the SNR headroom lattice would add. Full breakdown + interference proof in
COMPOSED_RESULTS.md.

Digital rail: 3158 cells, 24712 um2 (counted, A4 yosys), 0 latches; audit/ABFT overhead = checksum col (1/17 columns = 5.9% counted) + 1268/3158 abft cells (counted).
