# NULLSEEK — is a null-seeking column worth building?

**2026-09-07 scope correction:** the main rejection below evaluates the earlier OTA/PWM topology and its error assumptions. It does not rule out an OTA-free charge-null SAR on the new passive accumulator. The comparator's ±10-mV test range is not a measured noise/resolution floor, and charge-domain nulling need not use incremental ΔΣ. See the current [Mythic nulling review](IMC_MYTHIC_NULLING.md) and [circuit convergence](IMC_CIRCUIT_CONVERGENCE.md). Historical calculations below retain their stated topology and assumptions.

Date 2026-08-30. Session 3, branch `session3/conv-time-attack`. **No SPICE run**
(simulator owned by another agent). Every claim labelled **measured** /
**derived** / **literature** / **projected** / **speculation**. This is a
CHECK-BEFORE-YOU-BUILD document; the answer is mostly negative and the negative
half is the load-bearing half.

---

## 0. VERDICT UP FRONT

**NO-GO as an accuracy lever. Conditional GO for one small piece of it, and that
piece is not null-seeking.**

Five sentences, each with its number:

1. **We already do charge balancing.** The distinction the brief proposes is
   correct but it is narrower than "different principle": we balance
   *sequentially after* the integration; Mythic balances *concurrently during*
   the read. Same principle, different phase ordering. (§1)
2. **Null-seeking does relax the OTA DC-gain requirement, and by a lot:
   `A0 >= 6,300` becomes `A0 >= 545`** — the as-built 1,532 already clears it
   3x. But that requirement was never the binding constraint on CSNR, because
   the 4.1-point deficit it produces is a *mean gain error* that the shipped
   per-window corrector already removes. (§2)
3. **It does NOT touch the 5.5-point large-signal term** (the φ2 connect
   impulse), and plausibly makes it 0–50% worse by adding up to 7 more
   full-size impulses inside the window. (§2.3)
4. **It does NOT touch Pelgrom. Confirmed, plainly.** Crosspoint cap mismatch
   corrupts the summands before any readout exists. **With the converter error
   set to exactly zero, total CSNR goes 23.42 → 25.03 dB (+1.61 dB) at
   sky130's own `A_C`, and is still 18.3 dB short of 43.3 dB** — 11.3 dB short
   even after crediting the +7.0 dB "frozen weight error is gentler" measurement.
   **The entire converter, perfected, is worth 1.6 dB.** (§3)
5. **The conversion-time win is real but it comes from BINARY SEARCH, not from
   null-seeking.** Replacing the 7-slot unary coarse loop with a 3-slot binary
   one gives **1.62x tok/s (17,915 → 29,043 = 0.46x Sohu)** with no
   re-architecture and a bit-identical golden. Moving the balance *into* the
   window buys ~2 more slots at N4 because the whole PWM window (13.6 ns) is
   under 2 decision slots (7.3 ns each). (§5)

**Recommended action: drop the null-seeking re-architecture. Spend the session's
SPICE budget on the 3-bit binary coarse search (§8.2), which is a ~1.6x tok/s
lever, and on the mismatch term (§8.3), which is the only thing standing between
us and the accuracy target.**

---

## 1. Q1 — What we already have, and what would actually change

### 1.1 Your reading is correct. Stated crisply:

> We integrate the full-scale signal onto `C_int` **through** the OTA first —
> which is what demands OTA linearity across full scale — and only then balance.
> Mythic never integrates; the cancellation happens at the summing node
> **during** the read, so no amplifier ever handles a full-scale linear signal.

**Confirmed.** The evidence, all in-repo:

- `integrator_conv.py` docstring, verbatim (**measured**, it is the shipped
  netlist): *"COARSE (event-rate, **post-window** per tile_fsm
  INTEGRATE->COARSE->FINE; the ±4σ B_y schedule keeps the window sum inside the
  OTA swing)"*. The packets fire **after** the PWM window closes.
- `specs.MAC_MAX = 185` is *"OTA compression ceiling in code units
  (measured)"*, and `specs.c_u()` sizes the crosspoint cap so the **worst
  |mac| on C_int sits inside the telescopic swing** (`V_SWING = 0.25 V`). That
  constant exists only because the OTA must hold the full-scale integrated
  signal linearly. In a balance-during column it would not exist.
- `scripts/golden/model.py::eventrate_convert` computes `count = |q| >> 4` — the number
  of reference packets that balance the already-accumulated charge. This is
  charge balancing. `c(y) = ceil(|y|/Δ_c)` is exactly Mythic's "drive until the
  summation equals zero", executed unary instead of binary.

### 1.2 The sharper statement, from our own paper

`paper/sec_circuits.tex` §sec:converter already names our converter
(**repo, verbatim**):

> the **two-step extended-counting incremental ΔΣ** mapped onto the existing
> charge-balanced integrator (coarse: 16 self-timed charge-balance cycles = 4 b;
> fine: 4 b SAR on the residue; one redundancy bit)

and it already evaluated the balance-during version as the **runner-up**:

> **first-order incremental ΔΣ that reuses the column integrator as the loop
> integrator** — conversion becomes counting 1-b reference-charge packets until
> the accumulated dot-product charge balances… the 1-b DAC is inherently linear;
> comparator offset is loop-suppressed to `V_OS/(1+A_0)`; gain is one capacitor
> ratio. It is the most *architecturally* native choice and the lowest-
> calibration one, **but first order needs M = 2^B_y = 256 cycles in the window**

So: **"null-seeking" for a charge-domain column IS first-order incremental ΔΣ,
it was already on the table, and it was rejected on cycle count, not on
principle.** The shipped design is the standard fix for that (extended counting:
coarse balance + binary residue search). We are not missing the idea; we are
running the cycle-efficient variant of it, with the balance serialised after the
integration instead of interleaved into it.

### 1.3 So what would ACTUALLY change

Exactly three things, and nothing else:

| # | changes | does not change |
|---|---|---|
| a | the **accumulated** OTA output excursion: `0 → V_sig` becomes a sawtooth bounded by ±1 packet | the **per-transfer** charge impulse at the virtual ground |
| b | the OTA DC-gain requirement (§2.1) | `beta`, `gm_in`, `tau_absorb`, `C_par ∝ N` (§4) |
| c | *nothing* about the crosspoint capacitors (§3) | the 25.0 dB mismatch floor |

That is the whole delta. Everything below is scoring those three rows.

---

## 2. Q2 — Does it relax `A0 >= 6,300`, and by how many dB?

### 2.1 The transfer, worked

Mechanism of the measured `k = (eff_inf - eff)·A0 = 63` (**measured**,
`tb_csnr.py gainsweep`): finite `A0` leaves the virtual ground at
`v_x = v_out/A0` instead of 0, so each φ2 connect strands
`(C_bank + C_par)·v_x` of charge instead of delivering it to `C_int`.

**Integrate-then-balance (as built).** `v_out` ramps linearly to `V_sig` over
`n` chop transfers, so the stranded charge sums to
`(C_b + C_par)·V_sig·(n+1)/(2·A0)`. As a fraction of the signal charge
`C_int·V_sig` the `V_sig` **cancels** — the deficit is a pure *gain* error:

```
deficit = k / A0 ,   k = (C_b + C_par)(n+1) / (2 C_int) = 63   (measured)
```

**Balance-during (null-seeking).** `|v_out|` is bounded by one packet step
`Δ = 16u`, so the stranded charge sums to `(C_b + C_par)·n·Δ/(2·A0)` and
`V_sig` no longer cancels:

```
deficit = (k · Δ/V_sig) / A0        i.e.  k_eff = k · Δ/V_sig
error_out = k·Δ/A0   (ABSOLUTE, amplitude-independent)
```

### 2.2 Numbers (**derived** from measured `k`, `u`, `C_pkt`, `MAC_MAX`)

`u = 1.337 mV/code`, `Δ = 16u = 21.4 mV`, full scale `MAC_MAX·u = 247.4 mV`,
±4σ ceiling `CODE_MAX·u = 160.5 mV`, rms signal (σ=30 codes) `= 40.1 mV`.

| reference amplitude | `Δ/V` | `k_eff` | deficit @ `A0`=1532 | `A0` for 1 point |
|---|---:|---:|---:|---:|
| as built (gain error, amplitude-free) | — | 63 | **4.11 pts** | **6,300** |
| null-seek vs full scale (185 codes) | 0.087 | 5.45 | 0.36 pts | **545** |
| null-seek vs ±4σ ceiling (120 codes) | 0.133 | 8.40 | 0.55 pts | 840 |
| null-seek vs rms signal (30 codes) | 0.533 | 33.6 | 2.19 pts | 3,360 |

**Headline: `A0 >= 6,300` becomes `A0 >= 545` (11.6x relief) and the as-built
1,532 clears it 2.8x.** Equivalently the DC-gain term stops being a 4.11%
gain error and becomes a fixed **0.88 mV = 0.66-code** output offset.

Uncertainty on the 11.6x: **±2x**. Sources — (i) the sawtooth mean-|v_out|
assumption (uniform residue) is worth ±1.4x; (ii) `k = 63` is a single-fit
lumped constant measured at `n_banks = 11`, and the deficit is known to depend
on bank count (`specs.py` A9 `eff(n_banks)`); (iii) the last row of the table is
the honest reminder that at *typical* rather than full-scale amplitudes the
relief is only 1.9x, because the residue bound is a fixed 16 codes against a
30-code rms signal.

**Cross-check against literature.** The standard incremental-ΔΣ integrator
requirement is `A0 ≳ OSR`; `sec_circuits.tex` quotes `A0 > 1.7M` with `M = 256`
→ `A0 > 435` (**repo/literature**). Our derived 545 lands within 25% of that.
Two independent routes agree, which is the main reason I believe the 11.6x.

### 2.3 The harder half: the 5.5-point LARGE-SIGNAL term

**It is not relieved, and the honest direction is neutral-to-worse.**

The term is input-pair nonlinearity / slewing during the **φ2 connect impulse**
(**measured**, `tb_csnr gainsweep`: 5.5 points of excess of the real OTA over
the finite-`A0` ideal-amp prediction). Its magnitude is set by the *instantaneous*
step at the virtual ground, `ΔV_x ≈ Q_bank/(C_par + C_int)`, i.e. by the size of
ONE transfer — not by the accumulated `V_out`. `C_RAIL = 500 fF` absorbs it by
enlarging that denominator, which is exactly why shrinking `C_RAIL` makes it
**worse** (measured). Moving the packets in time changes the accumulated level;
it does not change the per-transfer impulse.

Worse: under balance-during, up to 7 cancelling packets fire *inside* the
window, interleaved with the signal banks. A packet is `C_pkt = 2.38 fF`,
comparable to a full mixed-sign bank (~15 units × 0.15 fF = 2.25 fF), so the
node sees **up to 7 additional full-size impulses per conversion** that it does
not see today.

**Quantified estimate with its uncertainty (projected, NOT measured):**

```
large-signal term:  5.5 pts  ->  5.5 to 8.3 pts   (+0% to +50%)
total charge deficit: 9.4 pts -> 5.9 to 8.7 pts   (best case -37%, worst -7%)
```

The +50% upper bound is `(11 banks + 7 packets)/11 banks` applied linearly to
the term; the 0% lower bound assumes the packets land in the chop all-off gap
where the current design already puts them (`integrator_conv.py`: *"packet fires
must land in the chop all-off gap — off-grid envelopes give partial transfers"*).
The truth depends on whether an in-window packet can be scheduled into that gap,
which is a SPICE question, not an arithmetic one. **This is the single largest
uncertainty in the proposal and it is why §8.1's experiment exists.**

### 2.4 …and now the part that kills the dB claim

**A mean gain error is worth ~0 dB, because it is already calibrated out.**

The measured 28.5 dB held-out CSNR is the residual **after** the per-window gain
correction (`g_lo = 0.9227`, `g_hi = 1.0660`, **measured**, `CSNR_HOLDOUT.md`
§3). That correction is worth **+8.5 dB** (19.91 → 28.45 dB, measured) and it
removes precisely the class of error the 9.4-point deficit belongs to. What
limits 28.5 dB is the **residual scatter** — 1.90 LSB rms (lo) / 1.25 LSB rms
(hi) about the fitted gain line, attributed by `CSNR_HOLDOUT` §3 to
*"per-operating-point coarse-loop INL plus code rounding"*, not to the mean
deficit.

So the correct question is not *"how many of the 9.4 points disappear"* but
*"how much of the 1.90/1.25 LSB scatter disappears"*. **No existing measurement
decomposes that scatter.** The plausible mechanism by which null-seeking would
help is that a *gain* error whose value depends on operating point becomes a
near-constant *offset* — which removes the amplitude dependence and hence part
of the scatter. That is a real argument, but it is a hypothesis with no number
attached, and §3 shows the argument cannot matter much regardless.

**Answer to Q2, in one line:** null-seeking relaxes `A0 6,300 → 545 ± 2x`
(**derived**), leaves the 5.5-point large-signal term at 5.5–8.3 points
(**projected**), and is worth **0 to +1.6 dB** of CSNR — where the +1.6 dB is
not its own ceiling but the ceiling for *any* converter improvement whatsoever
(§3).

---

## 3. Q3 — Pelgrom. Plainly: NO, and this is the answer that decides it

### 3.1 Verified. Null-seeking cannot touch the mismatch term.

The weight is a differential crosspoint capacitor ratio (`CONTRACT.md`:
*"weight = 4-bit binary-weighted cap code, differential (W = C+ − C−)"*).
A mismatch `δC_ij` changes the charge that crosspoint `(i,j)` *actually
delivers*: `q_ij = (C_ij + δC_ij)·V_DD·x_i`. The summing node receives
`Σ_i q_ij`. **The error is inside the summand.** Any readout — impedance,
cancellation, or otherwise — reads the sum it is handed. The topology of the
thing that reads a number cannot repair the number.

`tb_cap_mismatch.py` proves this operationally rather than rhetorically: it
injects `δC` at the cell level, propagates through the *linear charge model*
(**measured-validated**: slope 1.064, R² 0.9997 against 30 SPICE draws;
shuffled control R² 0.017), and the resulting CSNR is a property of `Eps @ x`
alone — no converter parameter appears anywhere in the computation.

Literature agrees and gives it a name. Vault note **27h3** (*An Analog CIM
Column Is a Data Converter Whose Input Is a Dot Product*) separates
**weight-INL** from **input-INL** as independent specifications, citing
Khaddam-Aljameh et al. (Hermes, JSSC 2022): weight nonlinearity comes from the
device and the array, input nonlinearity from the driver and the front end.
**Cap mismatch is weight-INL. Readout topology is an input-INL/front-end
question. They are different axes of the transfer surface.**

One thing null-seeking *does* do to the mismatch budget, and it is the wrong
sign: the cancelling DAC's own mismatch adds a **new** error term in power on
top of the existing one (§6.1).

### 3.2 The residual shortfall — the number to lead with

`tb_cap_mismatch.py` power-sums the mismatch MC against `CSNR_HOLDOUT`'s
28.5 dB (legality self-checked: the two ensembles share a signal variance to
within 15%, **measured** — the check is `SELF-CHECK: the two CSNRs share a
signal variance, so powers may be added`). Inverting that sum gives the
mismatch-only term, i.e. **the total CSNR if the converter were PERFECT**:

| `A_C` (%·µm) | total now (**measured**) | mismatch-only = perfect-converter ceiling (**derived**) | credit for a perfect converter | still short of 43.3 dB |
|---|---:|---:|---:|---:|
| 1.0 (lit low, optimistic) | 27.41 dB | **33.95 dB** | +6.54 dB | **9.4 dB** |
| 1.5 (lit high) | 26.34 dB | **30.41 dB** | +4.07 dB | **12.9 dB** |
| **2.8 (sky130's own PDK)** | **23.42 dB** | **25.03 dB** | **+1.61 dB** | **18.3 dB** |

(The derived column reproduces `tb_cap_mismatch`'s own printed
"mismatch CSNR now" figures — 34.01 / 30.48 / 25.06 dB — to within 0.06 dB, so
the inversion is arithmetically consistent with the tb.)

**At the PDK's own mismatch, deleting the converter's entire error contribution
buys 1.61 dB and leaves us 18.3 dB short.** Every dB argued in §2 is a fraction
of that 1.61 dB. That is the whole verdict on null-seeking as an accuracy lever.

### 3.3 The one honest credit, and it does not rescue it

`DEPTH_BUDGET.md` §5b **measured** that a real INT4 weight error is **+7.0 dB
gentler** end-to-end than iid additive noise at the same measured SNR, because a
weight error is a fixed, input-correlated perturbation of a linear map rather
than a fresh vector per pass. **Cap mismatch is exactly that class** — it is
literally a perturbation of `W`. So the mismatch term should arguably be scored
against **36.3 dB**, not 43.3 dB:

```
perfect-converter ceiling at A_C=2.8:  25.03 dB   vs a 36.3 dB bar  ->  11.3 dB short
                       at A_C=1.0:     33.95 dB   vs a 36.3 dB bar  ->   2.4 dB short
```

Caveat, stated because it points the other way: `DEPTH_BUDGET` §5a **measured**
that a *frozen per-output-channel additive* error at 43.3 dB is 2.30x worse in
KL than iid. Cap mismatch has both characters — it is a frozen weight
perturbation (§5b, gentler) but it manifests as a frozen per-column gain/offset
(§5a, harsher). The two measurements bracket it. I am not going to pretend the
+7.0 dB is bankable.

**Either way, the requested lead sentence holds: after the best case, we are
still short by more than 10 dB** at sky130's own `A_C`, and the shortfall is
entirely in the capacitors.

---

## 4. Q4 — `C_par ∝ N`. Confirmed: null-seeking alone does NOT fix it

`MYTHIC_ARCH.md` §3.2 is right and I have nothing to add against it: the N-
independence comes from the flash cell contributing `g_ds` in proportion to its
drain capacitance, so `τ = N·C_cell/(N·g_ds)` cancels. A capacitor contributes
`C` and `g = 0`.

Checking it directly against our own law, `specs.tau_absorb()`:

```
tau_absorb = (C_filt + C_self + C_ser) / (beta_int · gm_in)
beta_int   = C_int / (C_int + C_par_vg)          # C_par_vg = C_RAIL + banks ∝ N
```

Neither expression contains the search strategy, the packet schedule, or the
number of decision slots. **Moving the packets from post-window to in-window
changes no symbol on either line.** Confirmed: null-seeking is orthogonal to
`τ ∝ N`. (**derived**, from the shipped law.)

Two footnotes, for completeness, both **speculation**-grade:

- The *amplifier-free* variant (passive summing node, no OTA — the literal
  Mythic topology transplanted to charge) does break the law, but for a
  different reason: the settling resistance is then the DAC drive switch, one
  device you can widen with `N` for free, and the signal voltage `N·Q_u/(N·C_u)`
  is `N`-invariant while `kT/C` falls as `1/√N`. That is a property of
  *deleting the OTA*, not of null-seeking, and §6.3 shows it fails on comparator
  resolution by 26x.
- The `G = √N` hierarchical-buffer route (`FLASH_LESSONS` §4.3 /
  `MYTHIC_ARCH` §3.3) remains the only transferable fix, and it is unaffected by
  anything in this document.

---

## 5. Q5 — Conversion TIME, scored through `specs.cascade_pass_time`

### 5.1 Where the time goes at tsmc_n4_proj / 7B (**projected**, shipped model)

```
t_q = 100 ps    tau_absorb = 3.645 ns    coarse cadence = 7.30 ns (2τ, grid-snapped)
sar_time = 29.16 ns  (acq 4.86 + 0.61 + 4 x trial 4.25 + tail 6.68)
conv_time = 9 x 7.30 + 29.16 = 94.86 ns
PWM window (136 t_q) = 13.60 ns
pass = max(window, conv) + 4 t_q = 95.26 ns   ->  17,915 tok/s = 0.29x Sohu  [reproduces the honest baseline exactly]
```

**The conversion is 7.0x the window.** The reason is structural and worth
stating: `t_q` scales to the wire/jitter floor (100 ps) but `tau_absorb = C/gm`
does not scale with it. One decision slot (7.30 ns) is **more than half the
entire PWM window**.

### 5.2 What each schedule buys (tiles/die 46,667; 27.34 M passes/token)

| schedule | conv (ns) | pass (ns) | tok/s | vs Sohu | vs base |
|---|---:|---:|---:|---:|---:|
| **as built**: 9 unary coarse slots + 4b SAR | 94.9 | 95.3 | **17,915** | 0.29x | 1.00x |
| 7 slots, margin 0, + 4b SAR | 80.3 | 80.7 | 21,158 | 0.34x | 1.18x |
| **3b BINARY coarse (3 slots + 1 margin) + 4b SAR** | 58.4 | 58.8 | **29,043** | **0.46x** | **1.62x** |
| unified 8b binary null-search, 8 slots + tail | 65.1 | 65.5 | 26,063 | 0.42x | 1.45x |
| unified 8b binary, 8 slots + 1 margin + tail | 72.4 | 72.8 | 23,449 | 0.38x | 1.31x |
| unified 8b binary, MSB slots slew-penalised (+3 slots) | 87.0 | 87.4 | 19,531 | 0.31x | 1.09x |
| null-seek: 2 slots hidden inside the window | 50.5 | 50.9 | 33,541 | 0.54x | 1.87x |
| **MAGIC `conv_time = 0` (absolute ceiling)** | 0 | 14.0 | **121,905** | **1.95x** | 6.80x |

(**projected**; `pdk_projections.evaluate` conventions — `sar_time` scaled by the
`tau_absorb` ratio, ping-pong pass law, which is what produces the shipped
17,915 / 121,903 anchors.)

### 5.3 The finding

**The time win comes from BINARY SEARCH, not from NULL-SEEKING.** They are
separable and only one of them is cheap:

- **Binary vs unary** (row 3): 1.62x, post-window, no re-architecture, and the
  golden model is **bit-identical** — `eventrate_convert` returns
  `count = mag >> 4`, and a monotonic exact binary search over the same
  0..7 integer range returns the same `count`. Only `specs.N_COARSE` and
  `n_eval` (the energy model) change.
- **Balance-during vs balance-after** (row 7): at most ~2 extra slots hidden,
  because the window is 13.6 ns and a slot is 7.3 ns. It requires the full
  re-architecture and everything in §2.3 and §6.
- **Even a free conversion is only 6.8x** (1.95x Sohu). Conversion time is a
  bounded lever; we are already within 4.2x of its ceiling.

Two honest counterweights on the binary row:

- **Slew risk.** A binary search's MSB step is 64 codes (≈86 mV) against the
  unary loop's 16 codes (21 mV). If the first 3 slots need 2x cadence the win
  collapses from 1.62x to 1.09x (row 6). At sky130 `SR = 2·I_side/C_int =
  60 V/µs` → 86 mV in 1.4 ns against a 30 ns `tau_absorb`, so linear settling
  should still dominate (**derived**) — but this is a SPICE question and it is
  the second thing §8.2 must measure.
- **Energy.** Early termination dies: the unary loop averages `n_eval` 1.36–1.73
  strobes (**measured**, A5/A8); binary always spends 3. Against that, 83% of
  pass energy is OTA *static* burn set by conversion time (**measured**,
  session 1), and conv falls 38%. Net tok/J almost certainly still positive,
  but it must be measured, not assumed.

---

## 6. Q6 — What it COSTS

### 6.1 The DAC, and its matching — the surprising part

**Matching is NOT the blocker; area and OTA loading are.** Working it (sky130
MiM 2.0 fF/µm², `A_C = 2.8 %·µm`, `σ_INL,max ≈ σ_u·√(2^B)/2`):

| 8b CDAC unit | total | area/column | `σ_u` | `σ(INL)max` | `kT/C` |
|---|---:|---:|---:|---:|---:|
| 7.5 fF (today's `C_DACU`) | 1.92 pF | 960 µm² | 1.45% | 0.12 LSB | 0.04 LSB |
| 0.94 fF | 0.24 pF | 120 µm² | 4.08% | 0.33 LSB | 0.10 LSB |
| 0.47 fF | 0.12 pF | 60 µm² | 5.78% | 0.46 LSB | 0.15 LSB |
| *(reference)* whole crosspoint array/column | 36 fF | **18 µm²** | 10.2%/cell | — | — |

A 0.33 LSB DAC INL against a 30-code rms signal is a **39.2 dB** error term
(**derived**), which power-sums into the 25.0 dB floor for a −0.05 dB hit.
Negligible. **So the DAC is easier to match than the 16 crosspoint cells it
joins in the budget** — the crosspoints run at `σ = 10.2%` per unit cap
(0.075 µm² at `A_C = 2.8`) and produce a **measured** 5.17% rms per-column
charge spread. Answer to the sub-question: *easier*, and that is the one piece
of good news in this section.

The costs that are real:

- **Area.** 120 µm²/column is **6.7x the entire crosspoint cap array** and 2x
  today's 4b CDAC. Per `27h1`, converter area/energy already dominates a CIM
  macro past ~5 bits; this pushes hard in that direction.
- **OTA acquisition loading — the concrete killer.** `specs._CAL` carries
  `fine_ref_trim = 0.80`, a **measured** calibration meaning *the 6 µA OTA
  droops the residue to 0.80x under the CDAC acquisition load at only 120 fF*.
  An 8b CDAC is 240 fF–1.92 pF on the same node. `C_DACU` was already reduced
  from 30 fF to 7.5 fF for exactly this reason (`integrator_conv.py`: *"30 fF
  units made the acq sampling load drag the OTA −22% of the residue"*). Scaling
  the CDAC 16x is a direct assault on a term that has already bitten twice.
- **The ratiometric property is spent.** Today's coarse packet is ONE cap fired
  up to 7 times, so its mismatch is *perfectly correlated across fires* — a pure
  scale error on the coarse LSB, which is exactly what the per-window gain
  corrector removes. A binary DAC converts that correlated gain error into
  **uncorrelated INL**. For the cheap 3-bit binary coarse of §5.2: 7 units of
  `C_pkt = 2.38 fF` → `σ_u = 2.57%` → `σ(INL) ≈ 0.65 code rms` → a 33.3 dB
  term, which power-sums to **−0.6 dB at `A_C = 2.8` but −3.3 dB at `A_C = 1.0`**
  (**derived**). **This is the real price of binary search and it must be in the
  ledger.** Mitigation: build each binary weight from parallel/series
  sub-units to buy area at fixed C (4 sub-units → σ/2 → −0.15 dB), or rotate
  which of 7 nominal units forms each weight (DEM — whitens but does not shrink
  the single-conversion variance, so it helps only if the error would otherwise
  be code-correlated).

### 6.2 Common-mode servo and differential banks

- **Common-mode servo: not needed.** We are single-ended into one virtual-ground
  rail per differential pair, by the A3/A6 convention (`integrator_conv.py`:
  *"signs live in the SC phasing"*). The OTA's `+` input already pins the node at
  `vcm`. Mythic needs the servo because their two bitlines float; ours does not
  float. **Zero cost — and correspondingly zero benefit.** Going differential to
  copy Mythic would mean two rails, two OTAs (or a fully-differential OTA plus
  CMFB), 2x `C_int`, 2x static burn, and a rewrite of `weight_tile`'s sign
  phasing. There is no identified dB to pay for it.
- **Comparator.** Unchanged in the OTA-retaining version; the coarse comparator
  already decides against ladder taps behind a matched R-C anti-kick network
  arrived at through three documented failure modes. Any re-timing of the
  packets re-opens that whole kickback question (`integrator_conv.py` lines
  239–251, 333–351 are a catalogue of what goes wrong).

### 6.3 The amplifier-free version fails on comparator resolution

If you delete the OTA to kill the 5.5-point large-signal term (§2.3), the
summing node becomes passive and its LSB is
`C_u·V_DD/C_node = 270 aC / 700 fF = 0.386 mV` (**derived** from `c_par_vg`).
`tb_strongarm.py`'s acceptance bar is `|offset| < 10 mV` and it sweeps
±10 mV to check resolution — i.e. **the comparator is spec'd 26 code LSBs
coarser than the passive node's LSB**. Auto-zero removes the offset but not the
noise. Recovering 26x means a preamp, which means standing bias, which is the
impedance cost you were trying to avoid. **Dead as specified.**

### 6.4 Software blast radius

- `scripts/golden/model.py::eventrate_convert` — **bit-identical** for a binary coarse
  search (§5.3). For a full balance-during 8b null-search it is **not**: the
  `coarse/fine` split and `n_eval` both change, and `n_eval` feeds the energy
  model, so `tb_eventrate`'s `E_conv` vs `|code|` monotonicity assert
  (`CONTRACT.md` acceptance test 6) would need a new expectation.
- `integrator_conv.py` — the coarse FSM (`sgdone`/`cross`/`fire`/`done` XSPICE
  chain, ~40 lines) is replaced by a 3-bit or 8-bit SAR register; the packet
  branch gains 2 (binary coarse) or 7 (8b) more banks. The `run_c` gating
  discipline (A7) and the done-gated OTA park (S4) both key off `done_v`, which
  a fixed-length binary search no longer produces — early termination is gone,
  so both mechanisms need rework.
- `specs.py` — `N_COARSE`, `COARSE_CAP`, `COARSE_MARGIN`, `c_pkt()`,
  `conv_time()`. The `K=1` self-check anchor
  (`assert cascade_pass_time(1) == pass_time()`) survives; the A7 `mac 32→32`
  anchor survives only if the packet unit is unchanged.
- `CONTRACT.md` byte-identical-default requirement: satisfiable. Gate the binary
  coarse behind a `specs.COARSE_BINARY = False` flag and an
  `integrator_conv.generate(..., coarse="unary")` default. The golden needs no
  flag at all for the binary-coarse variant, which is the strongest argument for
  doing that one and not the other.

---

## 7. Q7 — Literature

**Local notes** (Obsidian vault, `Circuit Design/Analog Design/Analog Compute/`):

- **27h7** — *TIA readout costs static current; charge integration costs time;
  CCO costs neither but costs linearity.* The trichotomy `MYTHIC_ARCH` extends.
  The TIA law `I_D ≥ I_col·2^B/(V_read·gm/I_D)` is the "precision by impedance"
  cost; ours is the middle currency (`C·V_c/I_col` of column occupancy), which
  is exactly why our binding constraint is `conv_time` and not standing bias.
- **27h1** — *The column ADC dominates macro energy and area past ~5 bits.*
  Gives the fitted converter energy law
  `E_ADC = k1[B + log2(V_DD/V_c)] + k2 (V_DD/V_c)^2 4^B`, `k1 = 100 fJ`,
  `k2 = 1 aJ` (Gonugondla et al. 2022, **literature**). **Null-seeking changes
  neither term's form**: `k1` counts decisions (binary search minimises it —
  this is the §5 lever) and `k2` is thermal sizing on the reference capacitor,
  which a cancelling DAC still needs. At our `r = V_DD/V_c ≈ 7` the corner sits
  at 5–7 bits, i.e. we are already past it at `B_y = 8`.
- **27h3** — *A CIM column is a data converter whose input is a dot product.*
  The weight-INL / input-INL separation that §3.1 rests on. Direct literature
  support for "no readout topology fixes cap mismatch."
- **27g3** — *Compute-SNR, not ENOB, is the correct accuracy metric.* Why this
  document is scored in dB of CSNR against 43.3 dB and not in bits.

**`paper/sec_circuits.tex`** — quoted in §1.2. Carries the incremental-ΔΣ
quantization law `P_Q = π²Δ²/36M³` (1st order) and `π⁴Δ²/60M⁵` (2nd), the
`E_conv ∝ 4^B` thermal law, and the converged verdict (two-step extended-
counting incremental ΔΣ, ≈25 µm²/column at 14 nm, ~50 ns, 0.2–0.3 pJ).

**External** (WebSearch, **literature**, secondary where noted):

- **Charge-balancing = incremental ΔΣ, and it is old, well-characterised art.**
  Tutorial: Pavan/Schreier, *Incremental Delta-Sigma ADCs: A Tutorial Review*.
  Achievable ENOB is high (12–16 b routinely) but the currency is **cycles**: a
  first-order incremental ΔΣ needs `M = 2^B` clocks; a documented 12-bit /
  10 kS/s part used **512x oversampling**. For a design whose binding constraint
  is `conv_time` at 7x the window, that is the wrong currency, and it is the same
  objection `sec_circuits.tex` already recorded.
- **The escape is noise-shaping / extended-counting SAR**, not pure null-seeking:
  "12-bit accuracy in 13 clock cycles with 9-bit capacitor matching"
  (secondary-source summary). Fully-capacitive noise-shaping SAR reaching 102 dB
  SNDR at 31 kS/s / 68 µW (arXiv 1903.08680) is the state of the art. **Relevance
  and its limit:** noise shaping buys resolution without CDAC matching area,
  which is attractive because matching area is our binding cost — but it shapes
  the *quantisation* error of the converter, which is downstream of the
  crosspoint mismatch. It does nothing to §3.
- **No published analog-IMC macro uses Mythic-style null-balance readout in the
  charge domain.** Searched ISSCC/VLSI/JSSC/TVLSI 2020–2025 charge-domain SRAM
  and RRAM CIM. What exists: SAR/flash/charge-sharing column ADCs, C-2C ladder
  MAC units, cell-embedded ADCs, and one delta-sigma macro — the 22 nm
  **ΔΣCIM** (ISSCC 2023 / JSSC 2025, 21.38 TOPS/W) — which applies delta-sigma
  to the **input data stream** (delta-MVM, near-zero-mean outputs, LSB-first
  ADCs), **not** as a null-balancing column readout. **This is a labelled
  negative result from a bounded search, not a proof of absence.**
- **Converter area/energy modelling**: the open-source CIM ADC model
  (arXiv 2404.06553) fits Murmann's 1997–2024 survey and gives
  `Area(µm²) = 21.1·Tech(nm)^1.0·Throughput^0.2·(E/conv in pJ)^0.3`, with the
  caveat quoted verbatim: *"area and energy of published ADCs can vary by
  orders-of-magnitude even for ADCs with the same architecture-level
  parameters."* Which is a fair warning against believing any of §6.1's areas to
  better than 2x.
- **CDAC mismatch is the acknowledged linearity limit of every SAR-class
  converter**, addressed in the literature by calibration and DEM rather than by
  topology. Consistent with §6.1's finding that binary search converts a
  correlated gain error into uncorrelated INL.

---

## 8. Q8 — Verdict and plan

### 8.1 The null-seeking re-architecture: NO-GO

Scored against the brief's own bar:

| claim | result |
|---|---|
| relaxes `A0 >= 6,300` | **TRUE**, → 545 ± 2x (**derived**, corroborated by the incremental-ΔΣ `A0 ≳ OSR` law) |
| removes the 4.1-point DC-gain deficit | **TRUE in points, ~0 dB in value** — it is a mean gain error already corrected in software |
| removes the 5.5-point large-signal deficit | **FALSE**, 0 to +50% *worse* (**projected**) |
| addresses the 23.4 dB mismatch limit | **FALSE**, structurally (§3.1) |
| closes the ~20 dB gap | **FALSE.** Ceiling for a *perfect* converter is +1.61 dB at `A_C = 2.8`; 18.3 dB still short (11.3 dB with the §5b credit) |
| buys conversion time | **partly** — but the win is binary search (1.62x), not null-seeking (~+0.25x on top, at the cost of the whole re-architecture) |

**If you want the falsifier anyway** — because §2.3's ±50% is the one honest
uncertainty and it is cheap to close — here is the minimal experiment. It is
worth running only if the goal is `conv_time` or if you want the §2 physics
nailed down for the record; it cannot change §3.

> **EXPERIMENT N1 — does moving the packets into the window change `k`, and what
> does it do to the large-signal term?**
>
> **Harness (existing, no new netlist):** `analog/testbenches/tb_csnr.py
> gainsweep`, which already monkey-patches `IC.ota_spice` to an ideal VCVS of
> settable `A0` and calls `diag_multibank.eff_point(tag, n_banks, q, wb)` to
> measure per-column charge-transfer efficiency. One converter per sim, minutes
> each.
>
> **The one change:** an **open-loop** packet-fire schedule. Do NOT build the
> closed null-seeking loop. Precompute the fire times from the known `mac`
> (golden gives it) and inject them as the existing `fire_win` / packet-driver
> PULSE stimuli, spaced so that a packet fires every `ceil(n_chop/count)` chop
> cycles **inside** the PWM window, each landing in the chop all-off gap exactly
> as post-window packets do today. The physics under test (charge stranding vs
> accumulated `v_out`, and impulse nonlinearity) does not care whether a
> comparator or a lookup chose the fire times.
>
> **Matrix:** ordering ∈ {`post` (as built), `interleaved`} × `A0` ∈
> {300, 1000, 3000, 10000, 1e6} (ideal VCVS) × `n_banks` ∈ {11, 21}, plus the
> **real OTA** at both orderings and both bank counts. 24 transients.
>
> **Declared predictions (write them down before the run):**
> 1. `post`, ideal amp: `k = (eff_inf − eff)·A0` constant at **63 ± 10**.
>    *(reproduction CONTROL — if this moves, the harness changed, stop.)*
> 2. `interleaved`, ideal amp: `k' = 5.5 ± 2`, i.e. **≥ 5x smaller**.
>    **Falsified if `k' > 30.`**
> 3. real-OTA large-signal excess `(pred_ideal − meas_real)`: `post` reproduces
>    **5.5 pts**; `interleaved` lands in **5.5–8.3 pts**.
>    **Falsified if interleaved excess > 9.4 pts** (net deficit got worse).
> 4. Net total deficit `interleaved`: **5.9–8.7 pts** vs 9.4 measured.
>
> **CONTROL THAT MUST FAIL:** run the `interleaved` code path with a degenerate
> schedule that fires all packets on the **last** chop cycle of the window. That
> is the as-built ordering wearing the new label. It **must** return `k = 63`,
> not 5.5. If it returns 5.5 the harness is responding to the flag, not to the
> physics, and every other row is void.
>
> **Second control:** `A_C`-style sanity — the `A0 = 1e6` row must give the same
> `eff_inf` in both orderings to within 0.5 points. Ordering cannot matter to an
> infinite-gain amplifier; if it does, the schedule change is perturbing
> something other than the gain term.

### 8.2 What to build instead, part 1 — the 3-bit binary coarse search: GO

**1.62x tok/s (17,915 → 29,043 = 0.46x Sohu), bit-identical golden, no
re-architecture.** This is the actual answer to `session3/conv-time-attack` and
it fell out of the null-seeking analysis rather than from it.

Change: replace the unary event-rate coarse loop with a 3-decision binary search
over the same `count ∈ 0..7` range. Add 2 packet banks so the coarse DAC is
`{1x, 2x, 4x} · C_pkt` (7 units total, 16.6 fF, ~8 µm²). Keep the OTA, keep the
post-window ordering, keep the 4b SAR fine stage, keep the ladder.

> **EXPERIMENT N2 — the one to run first.**
>
> `analog/testbenches/tb_integrator_conv.py` with `coarse="binary"` behind an
> opt-in flag (`specs.COARSE_BINARY`, default `False` so every existing anchor
> stays byte-identical).
>
> **Gates:**
> 1. **Code match**: output code equals `golden.eventrate_convert` within ±1 LSB
>    at every existing test point, *including* the A7 `mac 32 → 32` anchor.
>    *(This is the bit-identity claim of §5.3; if it fails, the binary search is
>    not exact.)*
> 2. **MSB slew**: measure the settle time after the 4x-packet fire (a 64-code /
>    86 mV step). Gate: `< 2 · tau_absorb`, i.e. the existing cadence holds.
>    **If it needs > 2x cadence the win drops 1.62x → 1.09x and the item dies.**
>    This is the single number that decides the experiment.
> 3. **Coarse INL**: rms code error over the full `count` range vs the unary
>    loop at the same points. Gate: **≤ 0.65 LSB rms** (the §6.1 prediction from
>    `σ_u = 2.57%`). Above ~1.0 LSB rms the binary DAC's uncorrelated INL costs
>    more dB than the time is worth at `A_C = 1.0`.
> 4. **Energy**: `E_conv` vs `|code|` — early termination is gone, so the
>    `tb_eventrate` monotonicity assert and the "code-0 energy < 30% of mean"
>    gate will both change. Report the new pass energy; the claim to check is
>    that the 38% cut in OTA static burn beats the ~1.5 extra strobes.
>
> **CONTROL THAT MUST FAIL:** run the binary search with the `2x` packet bank
> deliberately mis-sized by 25% (`pkt_scale` already exists as a per-bank knob).
> Gate 1 must FAIL with a visible ±2–4 LSB code error. If a 25% DAC error passes
> the code-match test, the test is not sensitive to the thing §6.1 says is the
> new risk.

### 8.3 What to build instead, part 2 — the mismatch term is the only real gap

`~20 dB` of shortfall, of which the converter can contribute at most 1.6 dB.
Everything else is capacitors. The measured options, ranked by honesty:

1. **18.1x unit-cap area** (`tb_cap_mismatch`, **measured** cost at
   `A_C = 2.8`): `C_u` 0.15 → 2.71 fF. Moves `tau_absorb` and energy/MAC the
   wrong way at the same time. Priced, and priced badly.
2. **Re-score the target.** `DEPTH_BUDGET` §5b's +7.0 dB (frozen weight error is
   gentler than iid) is measured, and cap mismatch is exactly that class. It
   moves the bar 43.3 → 36.3 dB *for the mismatch term only* and shrinks the gap
   to 11.3 dB at `A_C = 2.8` and **2.4 dB at `A_C = 1.0`** — for zero silicon.
   **This is the cheapest dB in the repo and it is an analysis, not a build.**
   The experiment `DEPTH_BUDGET` §8 already specifies (replay the *measured*
   converter residual as the error shape instead of iid Gaussian) is the one
   that settles it, and it should be extended to replay the *mismatch* residual
   too. **Run this before spending a single ngspice-hour on circuits.**
3. **Verify `A_C`.** The whole verdict swings 6.5 dB between `A_C = 1.0` and
   2.8, and 2.8 is sky130's PDK number for a process we will never tape out on.
   `tb_cap_mismatch`'s own caveat applies: *"carrying a sky130 converter result
   to N4 is optimistic"* — and the reverse is true for `A_C`. An `A_C` for the
   MiM/MOM of the projection PDK is a literature lookup, not a simulation, and
   it is worth up to 6.5 dB of the answer.
4. **Bake per-cell correction into the compiled weight codes.** Our cells are
   volatile and rewritten every pass, so unlike Mythic we pay no program-verify
   loop — but the cap code is 4-bit and quantised, so a 5% per-cell trim has
   nowhere to land. It would need the LoRA sidecar or spare rows as the trim
   vector. **Unpriced, and the only structurally new idea in this list.**

Item 2 costs an afternoon of numpy and is worth more dB than anything in this
document. That is where the session should go.

---

## 9. What this document does NOT settle

1. **The decomposition of the 1.90 / 1.25 LSB residual scatter** that actually
   limits 28.5 dB. §2.4's argument that null-seeking converts an
   amplitude-dependent gain error into a constant offset is *plausible and
   unmeasured*. It cannot matter more than 1.6 dB (§3.2), which is why I did not
   chase it — but that is an argument from the ceiling, not a measurement.
2. **Whether an in-window packet can land in the chop all-off gap.** The entire
   ±50% band on §2.3 hangs on this and only SPICE answers it (Experiment N1).
3. **`A_C` at the projection node.** 6.5 dB of the verdict.
4. **Whether the MSB binary step slews.** 1.62x vs 1.09x on the one item I am
   recommending (Experiment N2, gate 2).
5. **`C_pkt` sub-unit construction.** §6.1 asserts you can buy 4x area at fixed C
   with a series/parallel sub-unit network to halve `σ_u`. Standard technique,
   not verified against sky130's MiM rules or the tile pitch.
6. **Nothing here re-derives the 43.3 dB target or the 23.4 dB mismatch MC.**
   Both are taken as measured from `DEPTH_BUDGET.md` and `tb_cap_mismatch.py`,
   including their own stated caveats (135M is not 7B; corner `tt` carries no
   OTA/comparator/switch mismatch, so 23.4 dB is an **upper** bound).

---

## Sources

**Repo (read-only, all MEASURED unless noted)**
`analog/schematics/specs.py` (`tau_absorb`, `conv_time`, `cascade_pass_time`,
`N_COARSE`, `_CAL.fine_ref_trim`, `MAC_MAX`, `V_SWING`);
`analog/schematics/components/integrator_conv/integrator_conv.py` (post-window
coarse ordering, `C_DACU` history, kickback lineage);
`scripts/golden/model.py::eventrate_convert`;
`analog/testbenches/tb_csnr.py::gainsweep` (`k = 63`, `A0 = 1532`,
DC-gain/large-signal split); `analog/testbenches/tb_cap_mismatch.py` +
`out/tb_cap_mismatch_final.log` (23.42/26.34/27.41 dB totals, 25.06/30.48/34.01
mismatch-only, 18.1x area, linear-charge-model validation, 0/1000 yield);
`analog/testbenches/tb_strongarm.py` (|offset| < 10 mV bar);
`scripts/compiler/metrics/DEPTH_BUDGET.md` (43.3 dB, slope 0.966, §5a 2.30x, §5b +7.0 dB);
`scripts/compiler/metrics/CSNR_HOLDOUT.md` (28.45 dB held out, `g_lo`/`g_hi`, 1.90/1.25
LSB residuals); `scripts/compiler/metrics/pdk_projections.py` (N4 evaluation conventions,
17,915 / 121,903 anchors); `docs/src/content/Project/MYTHIC_ARCH.md`;
`docs/src/content/Project/CONTRACT.md`.

**Paper (repo, external checkout)**
`.../Analog Compute/paper/sec_circuits.tex` §sec:converter — converter selection,
incremental-ΔΣ runner-up and its `M = 256` / `A0 > 1.7M` rejection, the converged
two-step extended-counting verdict.

**Vault notes** `27h1`, `27h3`, `27h7`, `27g3`.

**Literature (external, via WebSearch/WebFetch 2026-08-30)**
- Gonugondla et al., converter energy law `E = k1(B + log2 r) + k2 r² 4^B`
  (`k1 = 100 fJ`, `k2 = 1 aJ`) — via note `27h1`.
- Khaddam-Aljameh et al., *HERMES* (JSSC 2022) — weight-INL / input-INL
  separation — via note `27h3`.
- Pavan & Schreier, *Incremental Delta-Sigma ADCs: A Tutorial Review*.
  https://www.researchgate.net/publication/347068955
- Noise-shaping SAR, 102 dB SNDR, 68 µW / 31 kS/s.
  https://arxiv.org/pdf/1903.08680
- 22 nm ΔΣ Computing-In-Memory SRAM macro, 21.38 TOPS/W (ISSCC 2023 / JSSC 2025)
  — delta-sigma on the **input stream**, not a null-balancing readout.
  https://ieeexplore.ieee.org/document/10892305/
- *Modeling ADC Energy and Area for Compute-In-Memory Accelerator Design*
  (arXiv 2404.06553), area fit and the orders-of-magnitude-scatter caveat.
  https://arxiv.org/abs/2404.06553
- *A Review of SRAM-based Compute-in-Memory Circuits* (arXiv 2411.06079) and
  *IMAGINE* (arXiv 2412.19750) — surveyed for a null-balance readout; **none
  found** (bounded search, §7).
