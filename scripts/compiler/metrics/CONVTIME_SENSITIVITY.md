# CONV_TIME SENSITIVITY (session 3, rev 2)

Re-scored after `N_COARSE = 11` + derived `beta_int` landed in `specs.py`, and after the sim agent MEASURED the per-stage CSNR that the cascade depth K rests on.

Pure arithmetic through `specs.py` / `perlayer_k.py` / `pdk_projections.py`. **NO SPICE** (an analog agent owns the simulator). Regenerate: `PYTHONPATH=analog/schematics:. python3 scripts/compiler/metrics/convtime_sensitivity.py`.

Labels: **measured** = SPICE anchor (sky130 tb, or the session-3 sim agent's CSNR); **derived** = a specs.py law on measured/sourced params; **projected** = projection-grade PDK parameter set (asap7_proj / tsmc_n4_proj, LOW-MEDIUM confidence).

## TL;DR

1. **Both fixes re-scored.** N4/7B at the landed schedule (avg K = 6.54): **114,168 tok/s/die = 1.83x Sohu** (was 60,328 = 0.97x). asap7/7B: **70,868 = 1.13x**.
2. **The fixes compose MULTIPLICATIVELY, not sublinearly** (1.603x x 1.187x = 1.903x vs the actual 1.892x — a 0.54% interaction). **97% of FIX 2 survived FIX 1.** No saturation yet: even after both, the FFN class sits at conv/K = 13.55 ns, still -0% above the 13.6 ns window floor, so `max()` never engaged.
3. **That headline rests on a K the measured CSNR does not support.** At 19.9 / 16.7 dB uncorrected (27.8-30.1 dB attn with A10 cal, circular) the budget gives **K = 1**. N4/7B at K=1 = **17,915 tok/s/die = 0.29x Sohu**; best-case K=2 = **35,680 = 0.57x**. That is 6.4x below the headline and 3.5x short of parity. Section 3.
4. **The stopping line did not move, because it is absolute** (conv = K x t_in). At K=1 it is 13.6 ns and we are at 94.9 ns — **7.0x of runway. conv_time work is NOT dead; at K=1 it is the only timing lever left.** At K=7 only -0% of travel remains, and at K >= 7 it is exactly zero. Section 5c.
5. **`t_q` flips from 'cheapest ceiling-mover' to worth EXACTLY ZERO.** It only enters through `t_in`, which `max()` ignores while the conversion binds. At K=1/2/4, t_q 100 -> 75 ps buys +0.1%/+0.2%/+0.4% (the swap gap only); it is worth +33% only at K >= 7. I over-sold it in rev 1 by ranking it at the aspirational K. Section 4d.
6. **2.0x Sohu remains unreachable** by conv_time and K (N4 ceiling 1.950x, asap7 1.463x) — but that ceiling only binds in a world where K goes deep, which the measured CSNR says it will not.
7. **The binding constraint is per-stage CSNR, not time.** K=2 needs >= 31.11 dB; the best measured (circular) number is 30.1 dB. Closing that ~1.0 dB is worth 2x tok/s — more than every conv_time lever in this document combined. Section 6 is re-prioritised accordingly.

## 0. Which tok/s law is in force (unchanged correction)

The session brief quotes `cascade_pass_time(K) = window_lo + window_hi + 2*(8*TQ_SIM + conv)/K` (SERIAL). That is **not** the law behind the perlayer_k numbers. `perlayer_k.pass_time_K` uses the **ping-pong** law `max(136*t_q, conv/K) + 4*t_q` (`specs.cascade_pingpong_pass_time`). _(derived)_

| law | window floor | conv term | sensitivity once conv/K < window |
|---|---|---|---|
| serial `cascade_pass_time` | 144 t_q | **added** | never zero |
| ping-pong `pass_time_K` (**in force**) | 136 t_q | **max()** | **exactly zero** |

At N4 the serial law gives 39,098 tok/s (0.63x) on the same schedule vs the ping-pong 114,168. The `max()` is what creates the stopping line in 5c.

## 1. Re-scored baseline: how FIX 1 and FIX 2 compose

Landed per-tensor schedule unchanged (attn K=3 on 4 tensors / 576 passes-tok; ffn K=7 on 3 / 10368) -> avg K = 6.54. N4 tau 4.315 -> **3.645 ns** (FIX 2); conv 182.42 -> **94.86 ns** (both). _(projected)_

| | n_coarse | beta_int | conv_time | N4/7B tok/s | vs Sohu | x baseline |
|---|---|---|---|---|---|---|
| baseline (pre-session) | 17 | 0.3333 (stale) | 182.42 ns | 60,328 | 0.97x | 1.000x |
| FIX 1 only (N_COARSE 11) | 11 | 0.3333 | 112.82 ns | 96,701 | 1.55x | 1.603x |
| FIX 2 only (derived beta) | 17 | 0.3946 | 153.26 ns | 71,614 | 1.15x | 1.187x |
| **both (landed)** | **11** | **0.3946** | **94.86 ns** | **114,168** | **1.83x** | **1.892x** |

**How much of FIX 2 survives FIX 1: 96.6%.** Naive product 1.9028x vs actual 1.8924x — interaction 0.54%. _(derived)_

**Why it did NOT go sublinear, contra expectation.** Saturation only starts when a class's `conv/K` reaches `t_in`. After both fixes the FFN class (95% of passes, K=7) sits at conv/K = 13.55 ns against a 13.6 ns floor — still -0% above it — and attention (K=3) is 4x further away. So `max()` never engaged and both fixes acted on a pure `1/K`-scaled conversion term. **Sublinearity is close but has not started: one more 1.00x cut in conv_time at K=7 and the FFN class clamps.**

`pdk_projections.py` (the K=1, no-cascade point) re-scores 8,524 -> **17,915 tok/s/die** (2.10x). The old 8,524-vs-60,328 gap had two factors (n_coarse 19-vs-17, and K). **FIX 1 collapsed the merged/ping-pong 19 to the same N_COARSE = 11, so that factor is now exactly 1.000x and the entire remaining gap is the cascade K** (6.373x = the avg-K amortization). _(derived)_

## 2. Sensitivity surface: tok/s vs Sohu over (conv scale s, K)

`s` scales the POST-FIX `conv_time` (94.9 ns at N4, 115.5 ns at asap7) by any mechanism. K is UNIFORM so the contour is readable; the landed heterogeneous schedule is the _sched_ row. 7B, tok/s/die / 62,500 _(projected)_. **The K=1 and K=2 rows (bold) are the only ones the measured CSNR supports — see section 3.**

### tsmc_n4_proj / 7B — tok/s vs Sohu

| K | s=1.0 | s=0.9 | s=0.8 | s=0.7 | s=0.6 | s=0.5 | s=0.4 | s=0.3 | s=0.2 |
|---|---|---|---|---|---|---|---|---|---|
| **1** | **0.29** | **0.32** | **0.36** | **0.41** | **0.48** | **0.57** | **0.71** | **0.95** | **1.41** |
| **2** | **0.57** | **0.63** | **0.71** | **0.81** | **0.95** | **1.13** | **1.41** | **1.87** | **1.95** |
| 3 | 0.85 | 0.95 | 1.06 | 1.21 | 1.41 | 1.68 | 1.95 | 1.95 | 1.95 |
| 4 | 1.13 | 1.26 | 1.41 | 1.61 | 1.87 | 1.95 | 1.95 | 1.95 | 1.95 |
| 5 | 1.41 | 1.56 | 1.75 | 1.95 | 1.95 | 1.95 | 1.95 | 1.95 | 1.95 |
| 6 | 1.68 | 1.87 | 1.95 | 1.95 | 1.95 | 1.95 | 1.95 | 1.95 | 1.95 |
| 7 | 1.95 | 1.95 | 1.95 | 1.95 | 1.95 | 1.95 | 1.95 | 1.95 | 1.95 |
| 8 | 1.95 | 1.95 | 1.95 | 1.95 | 1.95 | 1.95 | 1.95 | 1.95 | 1.95 |
| 9 | 1.95 | 1.95 | 1.95 | 1.95 | 1.95 | 1.95 | 1.95 | 1.95 | 1.95 |
| 10 | 1.95 | 1.95 | 1.95 | 1.95 | 1.95 | 1.95 | 1.95 | 1.95 | 1.95 |
| 11 | 1.95 | 1.95 | 1.95 | 1.95 | 1.95 | 1.95 | 1.95 | 1.95 | 1.95 |
| 12 | 1.95 | 1.95 | 1.95 | 1.95 | 1.95 | 1.95 | 1.95 | 1.95 | 1.95 |
| 13 | 1.95 | 1.95 | 1.95 | 1.95 | 1.95 | 1.95 | 1.95 | 1.95 | 1.95 |
| 14 | 1.95 | 1.95 | 1.95 | 1.95 | 1.95 | 1.95 | 1.95 | 1.95 | 1.95 |
| _sched (6.54)_ | _1.83_ | _1.85_ | _1.87_ | _1.89_ | _1.91_ | _1.93_ | _1.95_ | _1.95_ | _1.95_ |

Hard ceiling (K -> inf, any s): pass -> t_in + 4 t_q = 14.0 ns -> **121,903 tok/s/die = 1.95x Sohu**. Conversion goes non-binding at conv = K x t_in (5c). _(derived)_

### asap7_proj / 7B — tok/s vs Sohu

| K | s=1.0 | s=0.9 | s=0.8 | s=0.7 | s=0.6 | s=0.5 | s=0.4 | s=0.3 | s=0.2 |
|---|---|---|---|---|---|---|---|---|---|
| **1** | **0.18** | **0.20** | **0.22** | **0.25** | **0.29** | **0.35** | **0.44** | **0.58** | **0.87** |
| **2** | **0.35** | **0.39** | **0.44** | **0.50** | **0.58** | **0.70** | **0.87** | **1.16** | **1.46** |
| 3 | 0.53 | 0.58 | 0.66 | 0.75 | 0.87 | 1.04 | 1.30 | 1.46 | 1.46 |
| 4 | 0.70 | 0.78 | 0.87 | 0.99 | 1.16 | 1.38 | 1.46 | 1.46 | 1.46 |
| 5 | 0.87 | 0.97 | 1.08 | 1.24 | 1.44 | 1.46 | 1.46 | 1.46 | 1.46 |
| 6 | 1.04 | 1.16 | 1.30 | 1.46 | 1.46 | 1.46 | 1.46 | 1.46 | 1.46 |
| 7 | 1.21 | 1.34 | 1.46 | 1.46 | 1.46 | 1.46 | 1.46 | 1.46 | 1.46 |
| 8 | 1.38 | 1.46 | 1.46 | 1.46 | 1.46 | 1.46 | 1.46 | 1.46 | 1.46 |
| 9 | 1.46 | 1.46 | 1.46 | 1.46 | 1.46 | 1.46 | 1.46 | 1.46 | 1.46 |
| 10 | 1.46 | 1.46 | 1.46 | 1.46 | 1.46 | 1.46 | 1.46 | 1.46 | 1.46 |
| 11 | 1.46 | 1.46 | 1.46 | 1.46 | 1.46 | 1.46 | 1.46 | 1.46 | 1.46 |
| 12 | 1.46 | 1.46 | 1.46 | 1.46 | 1.46 | 1.46 | 1.46 | 1.46 | 1.46 |
| 13 | 1.46 | 1.46 | 1.46 | 1.46 | 1.46 | 1.46 | 1.46 | 1.46 | 1.46 |
| 14 | 1.46 | 1.46 | 1.46 | 1.46 | 1.46 | 1.46 | 1.46 | 1.46 | 1.46 |
| _sched (6.54)_ | _1.13_ | _1.26_ | _1.37_ | _1.39_ | _1.41_ | _1.43_ | _1.45_ | _1.46_ | _1.46_ |

Hard ceiling (K -> inf, any s): pass -> t_in + 4 t_q = 14.0 ns -> **91,429 tok/s/die = 1.46x Sohu**. Conversion goes non-binding at conv = K x t_in (5c). _(derived)_

### The 2.0x-Sohu iso-contour — still EMPTY

No (conv_time, K) pair reaches 2.0x at either PDK at 7B. Identity on the law, not a projection uncertainty _(derived)_:

- **tsmc_n4_proj**: ceiling 1.950x. 2.0x needs pass <= 13.65 ns, i.e. t_in <= 13.25 ns = 133 t_q (have 136 t_q) — **conv_time cannot supply it at any K**.
- **asap7_proj**: ceiling 1.463x. 2.0x needs pass <= 10.24 ns, i.e. t_in <= 9.84 ns = 98 t_q (have 136 t_q) — **conv_time cannot supply it at any K**.

Ceiling-movers are t_q, chop cycles per window (<128), tile mm2, die count. **But at K=1 those levers are worth zero (4d): the pass is nowhere near the ceiling.** They matter only in the world where the CSNR problem is solved and K goes deep.

## 3. The honest number: K at the MEASURED per-stage CSNR

`perlayer_k.py` sets K from `SNR_S_DB = {attn: 34, ffn: 38}` (STATUS anchors) against a shared `SNR_T_DB = 28 dB` end-to-end target. The session-3 sim agent **measured** the per-stage analog CSNR instead. It is far below those anchors. _(measured)_

| per-stage CSNR | source | cascade SNR at K=1 | clears 28 dB at K=1? | largest K clearing 28 dB |
|---|---|---|---|---|
| 19.9 dB | **measured** (attn, uncorrected) | 19.9 dB | **NO** | 1 — floor clamp, the budget is already violated at K=1 |
| 16.7 dB | **measured** (ffn, uncorrected) | 16.7 dB | **NO** | 1 — floor clamp, the budget is already violated at K=1 |
| 27.8 dB | **measured** (attn, A10 gain cal (worst)) | 27.8 dB | **NO** | 1 — floor clamp, the budget is already violated at K=1 |
| 30.1 dB | **measured** (attn, A10 gain cal (best)) | 30.1 dB | yes | 1 |
| 34.0 dB | _assumed_ (attn, STATUS anchor) | 33.9 dB | yes | 3 |
| 38.0 dB | _assumed_ (ffn, STATUS anchor) | 37.8 dB | yes | 7 |

**Plainly, without softening:**

- At the UNCORRECTED measured CSNR the 28 dB end-to-end target is **not met at any K, including K=1**: K=1 delivers 19.9 dB (attn) and 16.7 dB (FFN). `k_for_budget` returning 1 is its FLOOR clamp, not a pass.
- With A10 per-column gain cal the attention class reaches 27.8-30.1 dB. Only the TOP of that range clears 28 dB, and only at K=1. **That number is flagged CIRCULAR / best-case by the sim agent** (the per-column gain is calibrated on the same data it is scored against), so it is an upper bound, not a result.
- **K=2 requires per-stage CSNR >= 31.11 dB** (series) / 31.04 dB (parallel super-tile). The gap depends entirely on which measurement you believe: the CIRCULAR best case is only **1.01 dB** short, but the honest uncorrected attention number is **11.2 dB** short and FFN is **14.4 dB** short. _(derived from `specs.cascade_snr_db`)_
- **That spread is the single most important open question in the session.** ~1 dB is an engineering afternoon; ~11-14 dB is a different converter. Everything downstream — whether K=2 is reachable, whether any conv_time lever is worth its testbenches — hangs on de-circularising the A10 number (calibrate on held-out columns / a separate excitation, then re-score).

### What each K costs in per-stage CSNR _(derived)_

| K | series needs SNR_s >= | parallel super-tile needs >= | best measured (30.1 dB, circular) reaches it? |
|---|---|---|---|
| 1 | 28.02 dB | 28.02 dB | yes |
| 2 | 31.11 dB | 31.04 dB | **no** |
| 3 | 33.00 dB | 32.80 dB | **no** |
| 4 | 34.44 dB | 34.05 dB | **no** |
| 7 | 37.90 dB | 36.48 dB | **no** |
| 9 | 40.31 dB | 37.57 dB | **no** |
| 14 | **impossible** — the (1+eg)^K gain term alone busts the budget at ANY per-stage CSNR | 39.49 dB | **no** |

The parallel super-tile (#22) removes the `(1+eg)^K` compounding, so it helps at LARGE K — at K=2 it saves only 0.08 dB. **It does not rescue us: the binding term is the RANDOM one, i.e. raw per-stage CSNR, and the parallel topology does not touch that.**

### tok/s at the K we can actually defend

_(projected timing x measured CSNR — the timing is the same post-FIX model as everywhere else; only K changed.)_

| operating point | K | N4/7B tok/s | vs Sohu | asap7/7B | vs Sohu |
|---|---|---|---|---|---|
| **measured CSNR (honest)** | **1** | **17,915** | **0.29x** | **11,042** | **0.18x** |
| measured CSNR, circular best case | 2 | 35,680 | 0.57x | 22,007 | 0.35x |
| _assumed_ 34/38 dB schedule | 6.54 avg | 114,168 | 1.83x | 70,868 | 1.13x |
| _assumed_ uniform K=14 | 14 | 121,903 | 1.95x | 91,429 | 1.46x |

**0.29x Sohu is what AnalogIOC can defend today** — 6.4x below the 1.83x headline and 3.5x short of parity. Even the circular best case (K=2) is 0.57x. And at K=2 the 28 dB budget is violated by every measured CSNR, so K=2 is not a defensible row either — it is there to bound the upside.

**This is a per-stage-CSNR problem, not a scheduling problem.** Every tok/s lever in this document multiplies a number that is currently 3.5x short. dB buy tok/s directly: +1.0 dB off the circular best case reaches K=2 (2.0x); reaching 34 dB gives K=3 (3.0x); 38 dB gives K=7 (6.8x). **CSNR is worth more than every conv_time lever in this document combined**, and it is the one quantity this metrics file cannot compute — it needs the sim lane.

## 4. conv_time decomposed at N4 — the ranking is K-DEPENDENT

### 4a. The N4 term budget (post-FIX-2 beta)

The session brief's lever constants (`beta_int` 0.22, `c_par_vg` 700 fF, `C_self` 187 fF, `C_int` 200 fF) are **sky130** values. N4 differs in kind, not degree:

| term | sky130 (measured) | tsmc_n4_proj (projected) | share of N4 C_out_eff |
|---|---|---|---|
| C_filt | 138 fF (free, clamp-solved) | **60 fF = C_FILT_MIN (PINNED)** | **57.9%** |
| C_self | 186.6 fF | 12 fF | 11.6% |
| C_ser (C_int || C_par) | 155.6 fF | 31.6 fF | 30.5% |
| C_int | 200 fF (layout floor) | 52.1 fF (kT/C law) | — |
| C_par_vg | 700 fF | 80 fF | — |
| beta_int (**now DERIVED**) | 0.2222 (A2 measured 0.22; the identity reproduces it to 1.0%) | 0.3946 | — |
| gm_in | 72 uS | 72 uS | — |
| tau_absorb | 30.0 ns | 3.645 ns | — |

**C_FILT_MIN is 57.9% of N4 C_out_eff (2.11 of 3.65 ns)** — the single largest term, as PDK_PROJECTIONS.md suspected. Precision: it is **not an absolute floor on tau**; it is an additive 60 fF that still divides by beta*gm, so more gm still shortens tau. Dominant term, not a wall. _(derived)_

### 4b. Why sky130 cannot rank these levers (the clamp)

`specs.kick_filter` solves `C_filt = beta*gm*(3*TQ_SIM) - C_self - C_ser`, clamped to [C_FILT_MIN, 220 fF]. **Inside the clamp band tau is pinned at exactly `3*TQ_SIM` by construction**, regardless of gm, C_par or C_self — hence sky130/sim-grid tau = 3 x 10 ns = 30 ns, insensitive to every device lever. FIX 2 is a live demonstration: it moved sky130's beta 0.22 -> 0.2222 and C_filt 133 -> 138 fF, and tau did not budge from 30.0 ns — the clamp absorbed the whole change. At N4 the solve goes negative (-35.0 fF) so C_FILT_MIN binds and tau is fully sensitive again. **Any lever ranked on the sky130 grid is measuring the clamp, not the physics.** _(derived)_

### 4c. Ranked levers — at K=1 (honest) and K=7 (aspirational)

`e = d ln(tok/s)/d ln(term)`, two-sided +-10%, UNIFORM K, N4/7B. Positive e = raising the term raises tok/s. Sorted by |e| at K=1. _(derived on projected params)_

| lever | move | e (K=1) | e (K=7) | K=1 tok/s (vs Sohu) | K=7 tok/s (vs Sohu) | what it is |
|---|---|---|---|---|---|---|
| gm_in (I_SIDE x gm/ID) | x2 (I_SIDE 6 -> 12 uA, 2x static power) | +1.001 | +0.530 | 35,348 (0.57x) | 121,903 (1.95x) | tau ~ 1/gm exactly (C_filt is C_FILT_MIN-clamped, no feedback) |
| c_par_vg | 80 -> 40 fF | -0.737 | -0.352 | 27,849 (0.45x) | 121,903 (1.95x) | hits tau twice: C_ser AND beta = C_int/(C_int+C_par) |
| K_SETTLE | 2.0 -> 1.5 (needs tb_integrator_conv) | -0.704 | -0.337 | 21,586 (0.35x) | 121,903 (1.95x) | same coarse term as n_coarse; grid snap ~0.3% at N4 |
| n_coarse | 11 -> 9 (COARSE_MARGIN 4 -> 2, needs SPICE) | -0.688 | -0.307 | 17,915 (0.29x) | 121,903 (1.95x) | linear on the 69%-of-conv coarse term |
| C_FILT_MIN | 60 -> 30 fF (needs a CDAC scaling law) | -0.598 | -0.289 | 25,129 (0.40x) | 121,903 (1.95x) | 58% of C_out_eff; additive, divides by beta*gm |
| C_int | x2 (2x tile cap area; c_u ~ C_int -> A7) | +0.408 | +0.230 | 22,567 (0.36x) | 121,903 (1.95x) | raises beta faster than C_ser -> tau DOWN (see 5a) |
| sar_time | x0.5 (fewer trials / shorter tail) | -0.305 | -0.129 | 21,153 (0.34x) | 121,903 (1.95x) | 31% of conv at N4 (already tau-scaled) |
| c_ota_self | x0.5 (narrower devices, less gm) | -0.082 | -0.046 | 18,968 (0.30x) | 121,903 (1.95x) | only 12% of C_out_eff at N4 |
| _(baseline, post-FIX-1+2)_ | — | — | — | 17,915 (0.29x) | 121,903 (1.95x) | — |

Chain rule _(derived)_: `d ln(tok/s)/d ln(conv)` = -0.996 at K=1 and -0.971 at K=7 (the swap gap is the only non-conversion term left in the pass); `d ln(conv)/d ln(tau) = 1.000` exactly (coarse cadence AND the tau-scaled SAR are both linear in tau); `d ln(tau)/d ln(term)` = the capacitance shares in 4a.

**Does the ranking invert? The ORDER barely moves; the MAGNITUDE and the RUNWAY invert.** gm_in still leads, c_ota_self is still dead. What changes is what a lever is worth:

- At K=7 conv_time has only -0% of useful travel before the window floor clamps it (5c). Every lever in the table is capped by that, which is why the K=7 column compresses toward the ceiling.
- At K=1 the runway is 7.0x. gm_in x2 alone takes K=1 from 0.29x to 0.57x — 1.97x, essentially a clean doubling, because nothing clamps.
- **So conv_time became MORE load-bearing, not less.** With K=1 the `2*(...)/K` term does not divide at all, the pass IS the conversion, and conv_time is the only timing lever that still does anything. That is the opposite of the rev-1 conclusion, and it follows entirely from the measured CSNR.

### 4d. `t_q` — rev 1 called it the cheapest ceiling-mover. At K=1 it is worth ZERO.

`t_q` enters the pass ONLY through `t_in = 136*t_q` and the `4*t_q` swap gap. Under `max(t_in, conv/K)` it can only pay when `t_in` is the binding term. Both terms are scaled below. _(derived)_

| K | conv/K | t_in (100 ps grid) | binding term | tok/s at t_q=100 ps | at t_q=75 ps (row-RC floor) | gain |
|---|---|---|---|---|---|---|
| 1 | 94.86 ns | 13.6 ns | conversion | 17,915 (0.29x) | 17,934 (0.29x) | +0.1% |
| 2 | 47.43 ns | 13.6 ns | conversion | 35,680 (0.57x) | 35,755 (0.57x) | +0.2% |
| 4 | 23.72 ns | 13.6 ns | conversion | 70,769 (1.13x) | 71,064 (1.14x) | +0.4% |
| 7 | 13.55 ns | 13.6 ns | **window** | 121,903 (1.95x) | 123,207 (1.97x) | +1.1% |
| 14 | 6.78 ns | 13.6 ns | **window** | 121,903 (1.95x) | 162,537 (2.60x) | +33.3% |
| 20 | 4.74 ns | 13.6 ns | **window** | 121,903 (1.95x) | 162,537 (2.60x) | +33.3% |

**t_q 100 -> 75 ps is worth +0.1%/+0.2%/+0.4% at K=1/2/4** — the conversion binds, the window is irrelevant, and shrinking it moves only the 0.4 ns swap gap. It becomes a lever only once K >= 7 (where conv/K crosses t_in), i.e. in the world where the CSNR problem is already solved. **Correcting rev 1: I ranked t_q at the aspirational K. t_q is a CEILING lever, and we are not near the ceiling.**

## 5. Falsified levers, the STOPPING LINE, and tok/J

### 5a. Raising C_int for kT/C reasons — DEAD, and the brief's premise was an artifact FIX 2 removed

- kT/C law `C >= 12 kT 4^B_y / V_swing^2` = **52.1 fF** at B_y=8, V_swing=0.25 V _(derived)_.
- sky130 C_int = 200 fF (the layout floor) = **3.84x** the noise requirement. Noise never bound; `specs.c_int` returns `max(c_noise, layout_floor)` and its docstring says 'swing, not noise, binds'.
- At N4 the layout floor (40 fF) is BELOW the noise law, so C_int = 52.1 fF sits EXACTLY on the kT/C line — zero margin in either direction.

Since `C_ser/beta == C_par` identically, the closed form is

```
tau = (C_filt + C_self) * (1 + C_par/C_int) / gm  +  C_par / gm
```

so **raising C_int LOWERS tau** (it raises beta faster than it raises C_ser), saturating at (C_filt+C_self+C_par)/gm = 2.11 ns (-42%). At K=1, C_int x2 gives 22,567 tok/s (+26.0%). **The brief's 'raising C_int only raises tau' was an artifact of the stale stored beta — FIX 2 removed exactly that artifact, so the sign is now unambiguous.**

**The conclusion (do not do it) survives anyway**, for reasons unrelated to kT/C: `c_u = C_int*V_swing/(MAC_MAX*VDD)`, so C_u scales WITH C_int — you pay the whole tile's cap area, you re-open the A7 `k_cal` anchor and the `_selfcheck` c_u assert, and the entire win is bounded at 42% of tau. `gm_in` buys the same tau with no anchor churn.

### 5b. K_SETTLE 2.0 -> 1.5 — real at N4, but now BLOCKED by CSNR

- **sky130 (sim grid, t_q = 10 ns)**: cadence 60.00 -> 50.00 ns. conv falls -11.5% snapped vs -17.3% un-snapped -> the chop-grid snap eats 33% of the win.
- **tsmc_n4_proj (t_q = 100 ps)**: cadence 7.30 -> 5.50 ns. conv falls -17.1% snapped vs -17.4% un-snapped -> the chop-grid snap eats 2% of the win.

At N4 the snap is nearly free, so K_SETTLE 2.0 -> 1.5 is worth -17.1% conv_time -> **21,586 tok/s at K=1 (0.35x, +20.5%)**. At sky130's 10 ns grid a third of the win evaporates AND sky130 is window-bound anyway, so it converts to 0% tok/s there — exactly the class of conclusion that ranking on the sim grid gets wrong.

**COST, and this is now decisive:** 1.5 tau leaves a 22% settling residue vs 13.5% at 2 tau. That is a direct debit against per-stage CSNR — the quantity section 3 shows is already in deficit by ~1.0 dB. **Spending settling accuracy to buy nanoseconds is the wrong trade in a CSNR-bound design. Rev 1 called this a cheap SPICE ask; rev 2 downgrades it to blocked until CSNR has headroom.**

### 5c. The STOPPING LINE — and why the fixes did not move it

The pass flips conversion-bound -> window-bound when `conv/K <= t_in`, i.e. at **conv = K x t_in**. That threshold is ABSOLUTE and independent of how conv_time got where it is, so FIX 1 and FIX 2 moved us TOWARD it without moving it. Below it `d(tok/s)/d(conv_time) = 0` identically — and so is `d(tok/J)/d(conv_time)`, since the only conv_time-dependent energy term is `P_static x pass_time`. _(derived)_

| PDK | t_in | conv now | stop conv at K=1 | K=2 | K=7 | K=14 | headroom at K=1 | at K=7 |
|---|---|---|---|---|---|---|---|---|
| tsmc_n4_proj | 13.60 ns | 94.86 ns | **13.6 ns** | 27.2 ns | 95.2 ns | 190.4 ns | **6.98x** | 1.00x (PAST IT) |
| asap7_proj | 13.60 ns | 115.53 ns | **13.6 ns** | 27.2 ns | 95.2 ns | 190.4 ns | **8.49x** | 1.21x |
| sky130 (sim grid) | 1360.00 ns | 780.00 ns | **1360.0 ns** | 2720.0 ns | 9520.0 ns | 19040.0 ns | **0.57x** | 0.08x (PAST IT) |

**Are we past the stopping line? NO — and the answer depends entirely on K.** At the honest K=1 we are 7.0x above it: conv_time can fall from 94.9 ns all the way to 13.6 ns and every nanosecond pays at full elasticity. **At K=1, conv_time work is emphatically NOT dead — it is the only timing lever with runway.** At K=7 only -0% of travel remains; at K >= 7 we are past it and further conv_time work buys exactly zero.

sky130 on the SIM grid is window-bound at every K (conv 780 ns vs t_in 1360 ns, headroom 0.57x < 1) — another reason the sim grid cannot rank conv_time levers.

### 5d. tok/J vs conv_time — the two accountings disagree

| accounting | conv_time enters? | N4/7B tok/J at K=1 | K=2 | K=7 |
|---|---|---|---|---|
| measured-anchor (`compose.py`: per-block SPICE pJ, conv/K) | **NO** — structurally independent | 17 | 24 | 35 |
| projected static+dynamic (`pdk_projections` e_sq) | **YES** — via pass time | 2,037 | 3,125 | 5,052 |

(The measured-anchor row is the mini SPICE chain scaled to 27.3 M passes/token — see COMPOSED_RESULTS.md's scope warning; the mini-scope number is ~87k tok/J. Sohu's 35-60 tok/J band is INFERRED, no vendor power published.) On the projected accounting at K=1, halving conv_time buys 1.14x tok/J — **tok/J tracks tok/s closely at K=1 and stops at the same line.**

## 6. Re-anchoring dependency map (approved re-anchored branch)

Per proposed change: which CALIBRATED constants stop being valid, which ASSERTS break, and the minimum testbench set to re-anchor. Constants live in `analog/schematics/specs.py` (`_CAL['sky130']`, module constants) and `library/pdks/*_proj.py` (`cal_proj`).

**Section 3 re-prioritises this entire list.** Each entry is now scored twice: what it does for tok/s, and what it does for **per-stage CSNR**, which is the binding constraint. A change that buys dB is worth more than one that buys nanoseconds — we are ~1.0 dB short of K=2 (worth 2x) and ~4.3 dB short of K=4.

### 6.1 `V_SWING` 0.25 -> 0.5 V

**Feasibility veto first.** V_SWING is the *single-sided* swing about a virtual ground at `VCM_FRAC = 0.5 x VDD`. sky130 (1.8 V) -> VCM 0.9 V, tight but arguable. **asap7_proj (0.7 V) -> VCM 0.35 V; tsmc_n4_proj (0.75 V) -> VCM 0.375 V: a 0.5 V single-sided swing exceeds the rail and is physically impossible.** Both advanced PDKs already carry `topology_flags['ota'] = two_stage_or_ringamp` for this headroom reason. So it is a sky130-only experiment. _(derived — arithmetic on VDD.)_

| breaks | why | re-anchor with |
|---|---|---|
| `c_u` (0.15 -> 0.30 fF) | `c_u = C_int*V_swing/(MAC_MAX*VDD)`, snapped to the 10 aF grid. **Every reference span moves.** | `tb_weight_tile` (A7 Q_UNIT) |
| `k_cal` (0.9906, A7 measured) | it is `Q_UNIT/(C_u*VDD)` measured AT the current unit-cell geometry | `tb_weight_tile` A7 rerun |
| `MAC_MAX = 185` (measured OTA compression ceiling) | it is the code where the OTA compresses AT the current swing; doubling the swing is precisely a claim about where compression starts | `tb_ota` + `tb_tile_mvm` compression sweep |
| `CODE_MAX = 120`, `cascade_k_swing` | derived from MAC_MAX; `_selfcheck` asserts `cascade_k_swing(CODE_MAX)==1` and `cascade_k_swing(46)==4` — both break | recompute, then `tb_cascade` K=4 code guard |
| `c_int` at advanced nodes | `c_noise` falls 4x (52.1 -> 13.0 fF), so N4/asap7 C_int drops to their layout floors (40/50 fF). **`beta_int` is now DERIVED, so it follows automatically — FIX 2 already removed this hazard.** | no tb (projection-only); re-run this script |
| `fine_ref_trim = 0.80` (A11 measured droop) | droop is residue-amplitude dependent; a 2x residue span re-droops | `diag_fine15` + `tb_integrator_conv` |
| `MB_EFF_FLOOR = 0.84` (A9 measured) | charge-sharing efficiency at the new unit-cell size | `diag_multibank` |
| `specs._selfcheck()` | the `c_u` +-11%-of-0.15 fF assert and the `k_cal` 0.9906 +-0.001 assert fail immediately | both are re-anchor targets, not bugs |

**Checklist (ordered):** `tb_ota` (compression -> MAC_MAX) -> `tb_weight_tile` (k_cal, A7) -> `diag_a8` (zero point) -> `diag_fine15` (A11) -> `diag_multibank` (MB_EFF_FLOOR) -> `tb_integrator_conv` (+-1 LSB) -> `tb_tile_mvm` (energy anchor; `E ~ CV^2` on a 2x span) -> `tb_cascade` (K=4 guard). **8 tbs.**

**REVISED VERDICT (rev 1 said: skip).** V_SWING is worth **0%** on conv_time — it appears nowhere in `tau_absorb`, `coarse_cadence`, `conv_time` or the window. But it is the list's only **CSNR** lever: doubling signal swing at a fixed noise floor is up to +6 dB of per-stage SNR, and we need ~1.0 dB for K=2 (2x tok/s) and ~4.3 dB for K=4. **In a CSNR-bound design this becomes the highest-value change on the list** — provided the OTA delivers the swing LINEARLY (`MAC_MAX` is the falsifier, and it is measured at the current swing, so `tb_ota` must run first), and provided you accept it is sky130-only. The 8-tb cost is real; the alternative is K stays 1.

### 6.2 `c_par_vg` 700 -> 350 fF (sky130)

| breaks | why | re-anchor with |
|---|---|---|
| `beta_int` — **nothing to break any more** | FIX 2 made it `C_int/(C_int+C_par)`, so it follows automatically (0.2222 -> 0.3636) | re-run this script; `tb_integrator_conv` to confirm the closed-loop settle |
| `c_ota_self = 311 fF` (**back-solved**, not measured) | the specs comment says it was back-solved from measured tau = 26 ns as `tau*beta*gm - c_filt - c_ser`. Change beta or C_ser and the back-solve is INVALID — re-back-solve from a NEW measured tau | `tb_integrator_conv` absorb transient |
| `MB_EFF_FLOOR = 0.84` | `c_par_vg` is explicitly 'C_RAIL(500 fF) + banks'; halving it halves the charge-sharing dilution the multibank fit models. eff should IMPROVE — **and per section 3 that is a CSNR gain, which is exactly what we need** | `diag_multibank` on pass_00 cols 1/3/8 + pass_05 |
| `k_cal = 0.9906` | measured on a column WITH that C_RAIL | `tb_weight_tile` |
| `specs._selfcheck` cadence assert | sky130 C_filt jumps 138 -> 220 fF (UPPER clamp) and tau falls 30 -> ~20 ns, so the `cadence == 60 ns` assert fails | update the anchor after `tb_integrator_conv` |

**Checklist:** `tb_integrator_conv` -> `diag_multibank` -> `tb_weight_tile` -> `tb_tile_mvm`. **4 tbs**, no span/code changes, A7/A8/A11 codes structurally unmoved. Cheapest change on the list, and FIX 2 just made it cheaper by one constant. At N4 `c_par_vg` is already 80 fF so this buys sky130 falsifiability, not N4 tok/s — **but the `MB_EFF` improvement is a real CSNR path, which now matters more than the tok/s it does not buy.**

### 6.3 LVT devices

| breaks | why | re-anchor with |
|---|---|---|
| every `OTA_COORDS` width | `specs.ota()` sizes `W = I_D/J_D(gm/ID, L, type)` from `sizing/lookup.py` tables keyed by device flavor | regenerate LVT gm/ID tables; `_selfcheck` width asserts (+-3% vs `pdk.sizing`) |
| `pdk.sizing` in `library/pdks/sky130.py` | stores the vault widths the +-3% assert compares against | re-run the sizing recipe |
| `c_ota_self` + its `i_side_ref` scaling | different widths -> different self-load; the constant-J `c_self ~ i_side` law is only valid within ONE flavor | `tb_integrator_conv` re-back-solve |
| loop gain (330 measured vs 200 needed) | LVT lowers r_o (DIBL). The telescopic's 5-stack intrinsic gain is what the 0.5%-transfer requirement rests on | `tb_ota` DC gain + AC sweep |
| `a_vt` / offset / `MB_EFF_FLOOR` | LVT Pelgrom A_VT is typically WORSE — **per section 3 that is a CSNR REGRESSION we cannot afford** | `tb_strongarm` (offset), `diag_multibank` |
| leakage in `ota_static_w` | LVT sub-threshold leakage is not in the model at all | `tb_tile_mvm` |

**Checklist:** LVT gm/ID tables -> `tb_ota` -> `tb_strongarm` -> `tb_integrator_conv` -> `diag_multibank` -> `tb_tile_mvm`. **6 tbs.**

**REVISED VERDICT (rev 1 said: only if you commit to gm_in).** LVT does NOT raise gm/ID at a fixed inversion level (gm/ID is set by the inversion coefficient, not V_t) — it buys **stack headroom**, i.e. it is an enabler for raising I_SIDE (the gm_in lever) or for V_SWING. But it **costs** matching (worse A_VT) and gain (DIBL), and both are CSNR. With CSNR short by ~1.0 dB, **spending matching to buy settling time is the wrong trade. Defer.**

### 6.4 Lowering `C_FILT_MIN` (60 fF)

| breaks | why | re-anchor with |
|---|---|---|
| the CDAC-match premise | the comment is explicit: 'floor: match the CDAC-side 8k/60f network'; `C_KICK_CDAC = 96 fF` is the sample load it must match. Lowering C_filt without the CDAC side breaks the kick-charge balance | `tb_rstring` + `tb_integrator_conv` |
| `RC_KICK = 0.44 ns` held constant | `kick_filter` returns `R = RC_KICK/C`, so halving C DOUBLES R. The kick CHARGE is held, but the higher R interacts with the comparator input, and the 0.44 ns product is itself a measured anti-kick anchor | `tb_integrator_conv` coarse-decision noise, `tb_strongarm` |
| nothing at sky130 | the floor is NOT active there (C_filt solves to 138 fF) — **no sky130 tb can falsify this change** | land it as a PARAMETER with a stated CDAC scaling law, labelled projected |
| PDK_PROJECTIONS.md's own open item | it already lists the '`C_FILT_MIN` becomes the tau_absorb floor at advanced nodes' hook. This is its quantification: 58% of N4 C_out_eff | — |

**Checklist:** derive the CDAC scaling law FIRST -> `tb_rstring` -> `tb_integrator_conv`. **2 tbs + a law.**

**VERDICT: still the best conv_time-per-tb on the list** (25,129 tok/s at K=1, +40%), and unlike V_SWING/LVT it costs no CSNR. But it buys nanoseconds, and section 3 says nanoseconds are not what is short.

### 6.5 Summary — re-prioritised for a CSNR-bound design

| change | CSNR effect | N4/7B tok/s at K=1 | tbs | verdict |
|---|---|---|---|---|
| `V_SWING` 0.25 -> 0.5 (sky130 only) | **up to +6 dB** — the only entry that attacks the binding constraint | 0% directly | 8 | **now the top candidate**, if `MAC_MAX` survives `tb_ota` |
| `c_par_vg` 700 -> 350 (sky130) | **+ via `MB_EFF`** (must re-measure) | ~0% at N4 | 4 | do it — cheapest, and FIX 2 removed a constant |
| raise `I_SIDE` 6 -> 12 uA (gm_in) | neutral | 35,348 (+97%) | 2 | biggest pure-timing lever; costs 2x static power |
| lower `C_FILT_MIN` 60 -> 30 fF | neutral | 25,129 (+40%) | 2 + a law | best tok/s-per-tb, but tok/s is not what binds |
| `K_SETTLE` 2.0 -> 1.5 | **NEGATIVE** (22% vs 13.5% settling residue) | 21,586 (+20%) | 1 | **blocked** while CSNR is in deficit |
| LVT | **NEGATIVE** (worse A_VT, worse gain) | 0% directly | 6 | **defer** — wrong trade |

