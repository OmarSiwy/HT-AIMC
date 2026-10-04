# SERVO_EG (task #21) — achievable gain-servo residual eg, the eg→tok/s curve, and the honest verdict on 2x-Sohu

Pure compiler math + committed measured data. NO SPICE (an analog agent owns
the sim lane). Regenerate the sweep:
`PYTHONPATH=<repo> python3 -c "..."` on `scripts/compiler/metrics/perlayer_k.eg_sweep`
(additive; the default avg-K=6.54 / 60,328 anchor is untouched).

Context (#12 perlayer_k + #13 compose): the tok/s gap to Sohu is a
gain-servo-eg problem — FFN cascade depth is capped on the `(1+eg)^K`
gain-compounding term in `specs.cascade_snr_db`. This doc quantifies the eg
that is ACTUALLY achievable and what tok/s it yields.

## 1. Achievable eg — three independent estimates

### (a) Measured-gain residual (A10/A11), backed out of in-contract accuracy

The per-column MEASURED gain (A10/A11, CASCADE.md Task B) removes the
correlated/systematic per-column gain error. What it leaves is bounded by the
in-contract `±1 LSB` code match: a residual gain error of `~1 LSB / |code|`
at the tested points.

| tested |code| | residual eg bound (1/|code|) |
|---|---|---|
| 60  | 1.67% |
| 80  | 1.25% |
| 111 (in-range near-full, reads EXACT) | 0.90% |
| 120 (CODE_MAX) | 0.83% |

So the measured-gain calibration pins the **effective eg at ~0.8–0.9%** at
full in-contract scale (the residual is a code-quantization bound, not the
true analog gain error — it is an UPPER bound on eg from the accuracy
contract). This is a per-column scalar; it does NOT touch the within-column
cell scatter (see (c)). Note CASCADE.md Task B is honest that the residual
above `|code|~111` is a count-dependent coarse INL, not a gain — so eg from
this route is a bulk bound, ~0.85%, not a converged servo number.

### (b) ABFT-checksum servo (test_gain_servo), model-measured

`analog/testbenches/test_gain_servo.py` (pure numpy, run read-only) — the
epoch-RLS per-column gain servo off the free ABFT checksum residual. Landed
result (PASS, 3 seeds incl. the worst draw found, seed 7):

| seed | injected eg | servoed eg (data cols) |
|---|---|---|
| 3  | 0.97% | **0.437%** (worst) |
| 7  | 0.98% | 0.203% |
| 42 | 0.95% | 0.196% |

The servo converges to **eg ≈ 0.20% typical, 0.44% worst-seed**. It removes
the correlated per-column gain error (checksum-observable directions); the
residual is the servo's estimation-noise floor on a stationary target. This
is the number `specs.EG_SERVO = 0.30%` is anchored to (a round midpoint of
the 0.20–0.44% band).

### (c) The Pelgrom floor — the insurmountable UNCORRELATED per-cell term

A servo removes the COLUMN-MEAN gain (one scalar per column). The
uncorrelated cell-to-cell mismatch WITHIN a column is invisible to a
per-column scalar and CANNOT be servoed out. Its floor (SC ENOB law
`b_eff = -log2(sigma_r) - 1.79`, sigma_r the per-conversion relative sigma)
is set by the crosspoint unit-cap Pelgrom mismatch `sigma_C/C = A_C/sqrt(area)`,
`area = C_u/cap_density` (A_C ≈ 1.5%·µm MOM):

| PDK | C_u | area (µm²) | per-cell sigma_C/C | eg_floor = sigma/√16 | b_eff |
|---|---|---|---|---|---|
| sky130      | 0.150 fF | 0.075  | 5.5% | **1.37%** | 2.4 |
| asap7_proj  | 0.100 fF | 0.050  | 6.7% | **1.68%** | 2.1 |
| tsmc_n4_proj| 0.090 fF | 0.026  | 9.4% | **2.34%** | 1.6 |

The floor is the residual COLUMN gain uncertainty after averaging the
uncorrelated per-cell spread over the ~16 active cells (`sigma_cell/√N`). At
the tiny unit caps these nodes use, the raw per-cell mismatch is 5–9%, and
even after √16 averaging the **irreducible per-column eg floor is ~1.4% at
sky130 and WORSE at the advanced nodes** (smaller caps → worse matching).

Caveats (why the servo still measures 0.2–0.4% < this floor):
- The servo's `eg_res` is the residual of a per-column SCALAR against a
  per-column CONSTANT injected gain — it does not model the within-column
  cell scatter, so it converges below the physical floor. The floor is the
  honest ceiling the servo model does not see.
- A_C = 1.5%·µm is a generic MOM figure; a MiM unit cap (sky130 cap2) or a
  larger, area-traded unit cell lowers sigma_cell (∝ 1/√area). Doubling the
  unit-cap area cuts the floor by √2. The floor is a KNOB (bigger caps =
  better matching = area/energy cost), not a hard wall — but it sits ABOVE
  0.15% by an order of magnitude at the drawn sizes.

**Honest eg reconciliation:** the servo (0.2–0.4%) is the achievable number
for the CORRELATED gain error; the Pelgrom floor (~1.4%+) is the ceiling on
the UNCORRELATED per-cell term that no servo touches. The effective eg the
cascade sees is the quadrature sum; the committed `EG_SERVO = 0.30%`
represents the servoed correlated part, and reaching materially below it (to
0.15%) is NOT a servo-tightening problem — it is a cell-matching (area) one,
and it is bounded from below by the Pelgrom floor.

## 2. eg → tok/s curve (specs.k_star gain term → perlayer-K aggregate)

`scripts/compiler/metrics/perlayer_k.eg_sweep` — re-runs `k_for_budget` per class
with the swept eg, re-projects the N4/7B heterogeneous schedule
(`pass(K)=max(136·t_q, T_conv/K)+4·t_q`, die 400 mm² × 0.7 fill, 7B). The
uniform-K=14 = 121,903 = 1.95x ceiling is shown for reference.

| eg | gain-cap ln(1.02)/eg | FFN K | attn K | avg K | N4/7B tok/s/die | vs Sohu 62.5k |
|---|---|---|---|---|---|---|
| 0.437% (servo worst) | 4.5 | 5 | 3 | 4.83 | 44,718 | **0.72x** |
| 0.30% (EG_SERVO, committed) | 6.6 | 7 | 3 | 6.54 | 60,328 | **0.97x** |
| 0.20% (servo typical) | 9.9 | 8 | 3 | 7.35 | 67,716 | **1.08x** |
| 0.15% | 13.2 | 8 | 3 | 7.35 | 67,716 | **1.08x** |
| 0.10% | 19.8 | 9 | 3 | 8.14 | 74,844 | **1.20x** |
| eg → 0 | ∞ | **9** (random-capped) | 3 | ~8.1 | ~74,844 | **~1.20x** |
| — uniform K=14 ceiling — | — | 14 | 14 | 14 | 121,903 | 1.95x |

The curve rises with a tightening servo but **saturates at ~1.20x Sohu**, not
1.95x. FFN K tops out at **9**, never 13–14.

**Why it saturates below 1.95x (the crux the projection's `(1+eg)^K` framing
hides):** `specs.cascade_snr_db(K)` carries BOTH terms —
`K·10^(-SNRs/10)` (random, sqrt(K)) AND `((1+eg)^K − 1)²` (gain). At the FFN
per-stage SNRs = 38 dB, the **RANDOM term alone caps FFN at K=10** (with
eg=0, K=9 clears 28 dB and K=10 is marginal). So once eg drops below ~0.1%,
the gain term stops binding and the RANDOM sqrt(K) term takes over. The servo
moves FFN from K=7 (eg=0.3%) to at most K=9 — it recovers ~1.2x, not the 2x.

The 1.95x/K=14 point is a **uniform K=14 across ALL tensors** (attention
included), which the per-tensor schedule never assigns because attention is
random-bound at K=3 and FFN is random-bound at K=9-10. Reaching uniform K=14
requires a HIGHER per-stage SNRs (≥ 44 dB) on top of a tighter servo — a
larger analog accumulation / better converter CSNR, NOT a servo alone.

## 3. Honest verdict — is 2x-Sohu reachable by tightening the servo?

**No.** Tightening the servo alone does not reach 2x, for two stacked
reasons:

1. **The servo tops out at ~1.20x** (FFN K=9), because at eg ≲ 0.1% the FFN
   depth is bound by the RANDOM sqrt(K) term at SNRs=38 dB, not the gain term.
   The eg required to even approach K=14 on the gain term alone (~0.05%) is
   moot — the random term binds first.
2. **The eg needed is below the Pelgrom floor.** Even if the random term were
   lifted, driving eg to 0.15% is below the ~1.4%+ uncorrelated per-cell
   mismatch floor (worse at N4). The servo's 0.2–0.4% is the CORRELATED part;
   the uncorrelated part is floored by cell matching (an AREA problem), not
   removable by any servo. The committed EG_SERVO = 0.30% already sits near
   the practical servo limit for the correlated term.

### The real unlock: the PARALLEL charge-summing super-tile (no gain compounding)

The projection's `(1+eg)^K` cap is the **series-chain** bound — K conversions
chained, each multiplying gain. CASCADE.md's "swing vs SNR vs gain" note and
`test_gain_servo` assert #4 both flag the alternative: the **PARALLEL**
charge-summing super-tile applies **one g per column to the CHARGE SUM**, so
the gain error is **K-INDEPENDENT** — `(1+eg)^K` does NOT apply at all.
`test_gain_servo` confirms it directly: parallel super-tile rel err at
K=1/4/13 = 0.437% / 0.437% / 0.437% (flat, < eps_tot=2% for all K).

Consequences:
- On the parallel path the gain-compounding term VANISHES from
  `cascade_snr_db`, leaving only the random sqrt(K) term. FFN depth is then
  bound purely at SNRs=38 → **K=10** (up from the gain-capped K=7), and
  attention at K=4. That alone lifts the aggregate toward the ~1.2x point
  WITHOUT any servo tightening — the parallel topology BUYS the eg headroom
  the series chain spends.
- To go past K=10 to the K=14 / 1.95x ceiling still needs the random term
  relaxed (higher SNRs, i.e. deeper analog accumulation or a finer
  converter), which the parallel super-tile's single-conversion-on-the-sum
  naturally supports (one conversion of a K-window charge sum, coarser LSB
  but only ONE random-quantization event, not K of them).
- Cost: the parallel super-tile leaves partial sums as INT8 on the digital
  fabric (CASCADE.md, law:cascade) — it trades a digital-accumulation /
  redundancy-bit overhead (fewer passes-savings per the amortization) for
  killing the gain compounding. That trade, not a tighter servo, is the
  path to deep K.

## Bottom line

- **Achievable eg:** servo converges to **0.20% typical / 0.44% worst-seed**
  (correlated part; committed EG_SERVO=0.30%). Measured-gain calibration
  bounds it at **~0.85%** at full in-contract scale. The **Pelgrom
  uncorrelated per-cell floor is ~1.4% (sky130), ~2.3% (N4)** before √16
  cell-averaging drops the effective column term into this range — it sits
  ABOVE 0.15% by an order of magnitude, so **0.15% is NOT servo-reachable;
  it is a cell-area/matching target.**
- **Resulting N4/7B tok/s:** the eg→tok/s curve saturates at **~1.20x Sohu**
  (FFN K=9), NOT 1.95x — because FFN is RANDOM-bound at SNRs=38 once eg is
  small. The committed eg=0.30% gives 0.97x (60,328).
- **2x needs:** NOT servo alone. It needs the **PARALLEL charge-summing
  super-tile** (kills `(1+eg)^K` entirely → K-independent gain error →
  FFN random-bound at K=10 for free) PLUS a higher per-stage SNRs to push the
  random term toward K=14. The series-chain `(1+eg)^K` assumption the
  projection uses is the pessimistic topology; the parallel super-tile is the
  actual unlock, and it is **floored, not by the servo, but by the
  uncorrelated Pelgrom mismatch + the random-SNR budget.**
