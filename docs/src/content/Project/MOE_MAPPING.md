# MoE mapping onto AnalogIOC (#19 "support any model")

Analysis + energy projection, **not** an implementation. It answers how a
Mixture-of-Experts (MoE) model maps onto the two-chip architecture, quantifies
the token/J advantage, names what blocks a full analog MoE, and states honest
scope. No SPICE, no compiler lowering — the compiler MoE path is deferred (§4).

Source labels: [compiler doc Bn/Part IV] = THE_COMPILER_STRUCTURE.md;
[CHIP2 §n] = CHIP2_SPEC.md; [27l6] = the MoE-economics note; [projected] =
law-scaled, no sim. specs.py is imported read-only for the energy numbers.

---

## 1. How MoE maps to the two chips

MoE is not a new operator surface. THE_COMPILER_STRUCTURE.md already places
every piece of it; this section just reads them off.

**Expert weights → Chip 1 analog tiles (already weight-stationary).**
An expert FFN is `W_down·(SiLU(W_gate·x) ⊙ W_up·x)` — the same
`activation × weight` position-local GEMM as the dense MLP (steps 10–11), and
Chip 1 is built for exactly that: mostly-fixed analog in-memory tiles whose
weights are stationary [compiler doc Part IV / B1 S1]. An expert is just a set
of weight tiles. The array cannot time-multiplex, so each expert occupies
crosspoints permanently and area is charged for all `E` experts (§2) [27l6].

**Router → the S5b digital dispatch island.**
The router is a top-k over a learned gate: `logits = W_g·x` (fp32), then
`top-k(logits)` → `k` expert indices + softmax/sigmoid gate weights. This is
the ONLY dynamic-shape residue in the whole model — binding stage **S5b**
[compiler doc B1]. It is small, control-flow-adjacent, and **not** analog
(router logits are fp32 by mandate: low-precision ties cause routing thrash
[compiler doc precision table]). It lives in Chip 1's small digital
dispatch island — the programmable escape hatch that B1 licenses, not a sea of
cores [compiler doc Part IV].

**Decode-FFN → Chip 2 with one CFG bit.**
The paper's load-bearing insight: MoE **decode** expert-FFN has the *same*
broadcast-stream-reduce geometry as attention — tiny activation broadcast in,
huge expert weight matrix streamed locally from the banks, tiny result out
[compiler doc B3 "the MoE row is the one people miss"]. So Chip 2 offloads it
with **no netlist change**: `CFG.MODE ∈ {ATTN, FFN}` swaps bank contents
(K,V → expert weight tiles), the broadcast operand (q → activation x), and
bypasses the WTA/exp/rescale softmax path; the fp32 combine island degrades
to a plain long-axis accumulate (expert accumulator fp32) [CHIP2 §8].
Expert-slice swap cost is ~0.25 nJ / ~38 us for a 128×256 slice, fine against
ms-class routing cadence [CHIP2 §8, projected]. Routing and the SiLU
nonlinearity stay on Chip 1 (S5b / position-local).

> Prefill vs decode split (unchanged from the dense case, §4 of compiler doc):
> at high batch the expert FFN is compute-bound and wants Chip 1's big array;
> at low-batch decode it is bandwidth-bound with weight-reuse ≈ 1 (different
> tokens pick different experts [compiler doc B2]) and wants Chip 2's
> stream-at-the-weights geometry.

### What the compiler must emit for S5b

Everything except this list stays static (S0–S5a) [compiler doc B1]. S5b is
the entire dynamic-shape surface, and it is small:

| Emit | Op class [List A] | Consumer |
|---|---|---|
| Router logits, fp32 | dot product / GEMV, then sigmoid/softmax | dispatch island |
| **top-k indices** (per token) | top-k over expert axis (A4) | dispatch |
| **per-expert group sizes** (runtime shapes) | histogram / bincount over expert axis (A4) | grouped-GEMM scheduler |
| Expert **offsets** (prefix over group sizes) | cumsum (A4) | gather |
| **gather** (dispatch): tokens → expert order | gather by index vector (A5) | Chip 1 tiles / Chip 2 banks |
| **grouped GEMM**, per-group shapes | A1 "the one that hurts" | expert tiles |
| **scatter-accumulate** (combine): expert order → token order | scatter-with-accumulate (A5) | residual stream |
| Capacity / drop policy (padding to a static cap, or ragged) | histogram + clamp | scheduler |

The compiler runs its normal passes on all of this and hits **one** branch it
cannot statically schedule (pass 9, "dynamic dispatch for the S5b residue
only" [compiler doc B5]): the grouped-GEMM group sizes and the gather/scatter
index vectors are known only after the router fires. Two standard escapes:
**capacity-padding** (pad each expert to a fixed cap → static shapes, wasted
compute on underfull experts) or **ragged/dispatch** (true dynamic shapes,
needs the memory system in §3). This is the compiler's only dynamic-scheduling
requirement in the whole model.

---

## 2. The energy win: E/token ∝ P_act = (k/E)·P_tot

The economics come straight from weight stationarity [27l6]:

```
area      A       ∝ P_tot = E·P_e        (every expert holds crosspoints)
energy    E_token ∝ P_act = (k/E)·P_tot  (only routed experts fire)
utilisation u = P_act/P_tot = k/E
```

An array cannot reuse a multiplier, so idle experts cost **area** but — *iff*
the front-end is charge-domain / gated — cost ~0 **energy**: an undriven
column integrates no charge and passes no DC [27l6, 27i3]. So only `k/E` of
the weight tiles fire per token, and per-token weight-read energy drops by the
factor **E/k** relative to a dense read of `P_tot`.

Representative models (util `u = k/E`, advantage factor `E/k`):

| model | E | k | u = k/E | **E/k** (weight-read energy factor) |
|---|---|---|---|---|
| Mixtral 8×7B | 8 | 2 | 25% | **4×** |
| DeepSeek-class | 256 | 8 | 3.1% | **32×** |

**The E/k number is the token/J advantage of MoE over reading the full
parameter set per token**, in the switched-energy limit. For DeepSeek-class
routing that is a **32×** per-token weight-read energy reduction; for Mixtral,
**4×**. This is *capacity affordability*, not a sparsity-specific efficiency
gain over a GPU (a GPU also fetches only `k` experts, so `u` cancels from the
analog-vs-digital *ratio* [27l6]) — what MoE buys the analog part is the
freedom to make `P_tot` enormous at strictly linear area cost while `P_act`
(which sets latency and per-token energy) stays small.

**The catch is the front-end (see §3).** The clean `E_token ∝ P_act` holds
only for a gated / charge-domain readout. A TIA-terminated column draws
standing bias whether or not its rows are driven, so idle experts burn static
power and the law degrades toward `E_token ∝ P_tot` — the advantage collapses
toward 1× [27l6 "When it breaks"; 27h7].

### Projection function (additive, specs.py read-only)

`scripts/compiler/metrics/pdk_projections.py::moe_energy(E, k, pdk)` prices this. It is
purely additive — **not wired into `main()`**, so the default
`PDK_PROJECTIONS.md` output is bit-identical (mirrors the existing `l_stack`
lever). It splits per-token energy into switched (dynamic, `∝ u`) and static
front-end (OTA + ladder rails, from specs) and reports the advantage under two
front-end regimes:

- `adv_gated = e_dense / e_gated` → **≈ E/k** (idle columns burn ~0).
- `adv_tia   = e_dense / e_tia`  → erodes below E/k, and → **1×** in the
  static-dominated limit (idle columns fully biased).

Self-check `_moe_selfcheck()` asserts `E/k = 32` for DeepSeek, that gated
tracks E/k, that TIA is always worse, and the closed-form collapse law
(`adv_gated → E/k`, `adv_tia → 1` as static ≫ dynamic). Run:
`python3 scripts/compiler/metrics/pdk_projections.py` (prints `moe_table()` +
`PASS`). Numbers are PROJECTION-grade — the tok/J advantage is the E/k factor,
gated on the front-end being charge-domain.

---

## 3. What blocks a full analog MoE, and what AnalogIOC already covers

| Piece | Analog? | Status |
|---|---|---|
| Router / top-k / gate | **No — digital** | S5b dispatch island. fp32 logits by mandate. **Covered** [compiler doc B1]. |
| Gather (dispatch) / scatter-accumulate (combine) | **No — near-tile digital** | A memory-system problem: index-vector gather + disjoint/atomic scatter [compiler doc A5/B2]. **Covered by the digital wrapper**, not a new analog block. |
| Grouped GEMM (expert tiles) | Yes (analog tiles) | Weight-stationary tiles already do the GEMM; only the *shapes* are dynamic (S5b, §1). **Covered.** |
| **Charge-domain expert gating** | **Yes — load-bearing** | See below. |
| All-to-all (expert parallelism) | No — interconnect | The trillion-param interconnect tax; frequently the real bottleneck, not arithmetic [compiler doc A7/A9, DeepSeek-V4 flags it explicitly]. **Not addressed here** — off-chip fabric problem, noted as the scaling ceiling. |

**Charge-domain expert gating — is it already in the tile design?**
Yes, structurally. This is the one load-bearing analog requirement, and
AnalogIOC's tiles already meet it:

- Chip 2 accumulates column charge on virtual-ground integrators (no TIA
  standing bias in the read path) [CHIP2 §1/§8, B2/B6].
- Tile phis are **clock-gated outside the window** (A8 FIX v2 discipline)
  [CHIP2 §2.2], and the S4 bias-gating duty is already modeled (`DUTY_SQ`
  in pdk_projections) — the mechanism that makes an idle expert's periphery
  draw ~0 during the token window.

So the E/k win is *available* on the current substrate. What is **not** yet
proven and is the needed addition/verification:

1. **Per-expert power-gating granularity.** Gating "outside the window"
   exists; gating *idle experts while other experts on the same die are
   active* (the MoE case: `k` fire, `E−k` idle, same token) needs the
   power-gate domain to be per-expert-tile, not per-die-window. This is a
   floorplan/switch-domain requirement, not a new circuit.
2. **Gmin background on shared columns.** If experts share columns, every
   stored device leaks `Gmin` current and idle experts are *not* silent
   [27l6, 27c2] — keeping experts on **separate tiles** (power-gateable
   independently) is the mapping choice that preserves the law, at the cost
   of shared periphery.
3. **Idle-expert drift/recal.** Recalibration burden scales with `P_tot`,
   not `P_act` [27l6] — an idle expert still ages. This refills part of the
   energy term sparsity emptied; a periodic-recal budget is owed but out of
   scope here.

Verdict: **charge-domain gating exists in the read path; per-expert
power-gating granularity + separate-tile mapping are the needed additions to
realize the E/k number in the MoE (many-idle-experts-per-token) case.**

---

## 4. Honest scope

This is a **mapping + energy analysis, not an implementation.**

- No compiler MoE lowering is written. The dynamic-dispatch pass (B5 step 9)
  for the S5b residue — top-k, histogram/cumsum group sizing, gather/scatter,
  grouped-GEMM shape resolution — is **deferred**. Validating it needs a real
  MoE model to test against, and the current end-to-end model, **SmolLM2-135M,
  is DENSE** — it exercises none of the S5b path. A real MoE GGUF
  (e.g. a Mixtral or DeepSeek-class checkpoint) is the prerequisite for
  implementation + validation.
- No SPICE. The energy numbers are law-scaled projections
  (`moe_energy`, PROJECTION-grade), consistent with the E/k economics and the
  measured charge-domain / static-power anchors, but the MoE many-idle-expert
  gating case has **not been run on an array** [27l6: nothing has].
- Chip 2's `MODE=FFN` path is specified (CHIP2 §8) with acceptance test
  `T8 tb_moe_ffn_mode` — but that verifies the *mode switch is CFG-only*, not
  a full MoE decode.

Deliverable now: the mapping (§1), the E/k energy projection (§2, with the
additive `moe_energy` function), the block-by-block coverage (§3). Deferred:
compiler lowering + validation, gated on a real MoE GGUF.

---

## One-paragraph summary

MoE adds no new operator surface to AnalogIOC: expert weights sit on Chip 1's
weight-stationary analog tiles, the router is the S5b digital dispatch island
(fp32 top-k — the only dynamic-shape residue), and decode expert-FFN offloads
to Chip 2 by one CFG bit because it has attention's broadcast-stream-reduce
geometry. The compiler must emit top-k, per-expert group sizes (dynamic
shapes), gather/scatter, grouped GEMM, and a histogram/cumsum for offsets —
its only dynamic-scheduling branch. The token/J win is the **E/k** factor
(**32×** for DeepSeek-class E=256/k=8, **4×** for Mixtral), real *iff* the
front-end is charge-domain gated — which AnalogIOC's read path is, though
per-expert power-gating granularity and separate-tile mapping are the needed
additions. All-to-all remains the interconnect tax. Implementation is deferred:
the e2e model is dense, so a real MoE GGUF is required to build and validate
the S5b lowering.
