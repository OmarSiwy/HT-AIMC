# Analog LUT study: the four transcendental primitives

Feasibility study for the AnalogIOC working assumption (THE_COMPILER_STRUCTURE.md
sec 8, Part IV "How far the analog goes"): can `exp2`, `log2`, `reciprocal`,
`rsqrt` run in analog cheaper than the digital seed-table baseline? This was the
highest-risk open assumption; it is now measured for exp2 and answered per
primitive below.

Labels follow METRICS.md: **measured** = SPICE tb in this repo, **counted** =
yosys/compiler counts, **estimated** = documented model, **projected** =
law-scaled.

## 1. The comparison that actually matters

A pure-digital special-function unit is almost free: a 256-entry ROM is under
100 fJ and a couple of ns (sec 2). Analog cannot beat that on op energy and does
not need to. The datapath is analog: attention scores arrive as charge on the
tile integrators, softmax outputs drive the A·V row currents. Running the
transcendental digitally means paying a domain crossing on both sides:

| leg | cost | source |
|---|---|---|
| ADC (coarse+fine conversion) | 0.48–4.83 pJ, 1.79 pJ at mid \|code\| | measured, METRICS E_conv |
| 256x8 ROM lookup | 0.09 pJ | counted (sec 2) x METRICS digital rail method |
| DAC back to analog | 1.2 pJ, 4.6 ns settle | measured, tb_write_dac |
| **chain total** | **1.8–6.1 pJ, ~3.1 pJ typical, >100 ns** | |

So the bar for an analog primitive is ~3.1 pJ/op and the bar for the digital
primitive (when operands are already digital) is ~0.1 pJ/op. Both bars get used
below; which one applies is decided by where the operand lives, and that is
decided per primitive by the op inventory (sec 5).

## 2. Digital baseline (counted + notes-derived)

Method: the fp8 shortcut from THE_COMPILER_STRUCTURE sec 8 — at 8b there are
only 256 input bit patterns, so every primitive is a complete, exact table.
Three tables were written as combinational Verilog case statements and
synthesized with yosys 0.62 → `abc -liberty sky130_fd_sc_hd tt_025C_1v80`
(same flow as A4's digital rail). Energy per the METRICS digital rail line:
3 fF/cell x VDD² x a=0.1 x 1 cycle = 0.972 fJ/cell.

| table | cells | area (µm²) | E/lookup | latency | label |
|---|---|---|---|---|---|
| exp2 full fp8 e4m3 → e4m3 (exact, zero error) | 96 | 522 | 93 fJ | ~2 ns, combinational | counted / estimated (energy) |
| exp2 8b-fraction seed → 8b mantissa | 212 | 1244 | 206 fJ | ~2 ns | counted / estimated |
| reciprocal 8b seed (1/(1+m/256)) | 162 | 940 | 157 fJ | ~2 ns | counted / estimated |

Notable: the *full* fp8 exp2 table synthesizes smaller than the 8b seed table
(96 vs 212 cells) because e4m3 outputs are heavily redundant over the input
range. The fp8 shortcut is even better than the doc assumed — the exact table
is the cheapest of the three.

Alternatives from the digital notes (S23/S26, de Dinechin & Kumm):

- **CORDIC**: ~1 add-shift per output bit; unrolled at 8b ≈ 10 stages x 3
  adders (~12b) ≈ 1500–1800 cells ≈ 1.5–1.7 pJ, 14k µm²; iterative ≈ 400 cells
  x 10 cycles (estimated from sky130 adder cell counts). Strictly dominated by
  the 256-entry table at 8b. CORDIC's no-multiplier argument only starts paying
  above ~12–16 bits, and the notes' own FPGA verdict already prefers
  table+multiplier. Not a contender here.
- **Newton refinement** (recip/rsqrt to >8b): 4–5b seed table + one
  y←y(2−xy) step = two 8x8 multiplies ≈ 800–1000 cells ≈ 0.8–1 pJ (estimated).
  Each step doubles correct bits, so 16b costs one step over an 8b seed.
- **Bipartite/multipartite** (S23): only relevant above ~10 input bits; at 8b
  the plain ROM wins. Kept in reserve for the fp16 variants.

Digital verdict inputs: at fp8, every primitive is ≤ 0.21 pJ, ≤ 1.3k µm²,
~2 ns, exact. The digital baseline is not the weak point; the conversions are.

## 3. Analog candidate: subthreshold translinear exp (measured)

Falsifier: `analog/testbenches/tb_lut_exp.py`. One grounded-source NMOS
(47.4/1.0, the measured translinear_softmax branch sizing) + PMOS 5/1.0 mirror
into the 0.9 V A6 column clamp. exp is native physics: I = I0·e^(βV), so 2^x is
a gate-voltage scaling; the "table" is one transistor plus a calibrated code→V
map (the compiler's job, same calibration tb_softmax already does).

Error budgets: fp8 e4m3 mantissa ulp = 12.5 % relative; faithful (half-ulp) =
6.25 %. Softmax-relevant range after max-subtraction: 8 octaves (2^-8 < 1/256
flushes in fp8).

All numbers **measured** (ngspice, sky130A tt, this repo):

| quantity | 27 C | 55 C | 85 C |
|---|---|---|---|
| exp-law window at 1 ulp (12.5 %) | 14.4 octaves | 12.9 | 11.8 |
| window at half-ulp (6.25 %) | 12.3 octaves | 10.7 | 9.5 |
| 64-code grid over the 8-octave range, worst rel err | 6.26 % (4.0 bits) | 6.29 % | 6.31 % |
| β (per-temp 2-param recal) | 26.5 /V | 24.1 (−9.1 %) | 21.9 (−17.5 %) |
| mirror nonlinearity over window | 0.60 % | 0.61 % | 0.65 % |

- **Precision ceiling: 4.0 bits relative over 8 octaves**, at every temperature
  after per-temp recalibration. That exactly meets faithful fp8-e4m3 mantissa
  and no more. The binding constraint is subthreshold-slope curvature (β drifts
  slowly with VGS across the window), not mismatch and not the mirror. A single
  device does not give a 5th bit; more bits means segmenting the range across
  trimmed devices (an rstring_ladder-seeded gate per segment) or going hybrid.
- **Temperature**: β ∝ 1/T, −17.5 % from 27→85 C — same drift tb_softmax
  measured (−18.1 %). Per-temp recalibration of (β, I0) restores the full
  window; PTAT tail bias is the production fix (A3 note). Without recal the
  code map is wrong by up to ~1.4 octaves at the range bottom: recal is
  mandatory, not optional.
- **Mismatch (MC, tt_mm, 8 seeds)**: σ(I)/I = 5.9–9.0 % over the window
  (σ_VT-equivalent 2.2–3.2 mV at this 47 µm² device) → **3.5–4.1 bits
  untrimmed**. A minimum-size device would sit near the 10–15 % / 3-bit figure
  from the Pelgrom estimate; this branch is large enough that untrimmed error
  ≈ the systematic ceiling. Trim (per-device stored gate offset via the
  measured write_dac + gain-cell path, 60 mV LSB) removes the static part and
  returns the device to the 4.0-bit systematic ceiling.
- **Energy/latency (transient, 16 shuffled codes over 8 octaves, 2 µs slots)**:
  mean **0.64 pJ/op**, worst 2.83 pJ (top code, both mirror legs), static
  0.32 µW. Worst settle 1.90 µs at the bottom code (1.7 nA, mirror-node
  τ = C/gm). The I·τ product is range-bound: settle is set by the *lowest*
  current, energy by the *highest*, and their ratio is fixed at 2^8 — scalar
  analog exp is stuck near ~0.5–3 pJ and ~1–2 µs regardless of bias point.
- **Batched is the real shape**: translinear_softmax computes 8 exps *and the
  normalization* in one 0.99 µs settle for 2.08 pJ = **0.26 pJ/exp, reciprocal
  included** (measured, tb_softmax). All branches settle together and the tail
  fixes total current, so energy/exp falls ~linearly with row width. Softmax is
  exactly this batch shape (L scores per query per head).

Area: 3 devices ≈ 60 µm² active + trim cell — an order below the 522 µm² ROM,
though both are negligible; area decides nothing here.

## 4. Reciprocal, rsqrt, log2 (no new sim — measured-adjacent + estimated)

- **Reciprocal inside softmax is already free and already measured.** The
  translinear normalization I_i = I_b·e^(βVi)/Σe^(βVj) IS the reciprocal: KCL
  checksum ≤ 0.16 %, per-branch ≤ 1.4 % (~6 bits on the ratio), measured in
  tb_softmax at 3 temps. No separate reciprocal op exists in the analog softmax
  path at all. Sigmoid (hence SiLU) is the 2-branch special case of the same
  circuit, so SiLU's exp+reciprocal fuse the same way.
- **Standalone analog reciprocal** (translinear loop I1·I2 = I3·I4): estimated
  at the same ~4-bit calibrated ceiling — MOS subthreshold loops add body-effect
  and n-factor mismatch on top of the single-device curvature. No measured
  candidate built; not worth building, because the only standalone reciprocal in
  the inventory (softmax denominator when computed digitally, Newton seeds) is
  low-volume and already digital-adjacent.
- **rsqrt**: analog geometric-mean loop would carry the same ~4-bit ceiling.
  RMSNorm needs 8+ bits and sits on fp32 norm statistics, which Part IV already
  declares a digital island. At 2 ops/layer/token, the digital cost (157 fJ
  seed + one Newton ≈ 1 pJ, estimated) rounds to zero. There is no case for
  analog rsqrt.
- **log2**: native in the same device run in reverse (V = ln(I)/β), same 4-bit
  ceiling (estimated, symmetric physics with the measured exp). Only consumer
  is softplus's midrange table (SSM); see weighting below.

## 5. What the transformer actually needs per token

Counts from THE_COMPILER_STRUCTURE secs 7–9, 7B-class shapes (32 layers, H=32,
d_h=128, d_ff=11008; Mamba shapes D=8192, N=16). Counted per token per layer:

| primitive | where | count/token/layer | count/token (32 L) |
|---|---|---|---|
| exp2 | softmax, decode | H·L = 32·L (131k at L=4k, 4.2M at 128k) | 4.2M at L=4k |
| exp2 (+recip, fused) | SiLU sigmoid, MLP | d_ff ≈ 11k | 352k |
| reciprocal | softmax denominator (online softmax) | H = 32 | 1k |
| rsqrt | RMSNorm | 2 | 64 |
| softplus (exp+log2) | Mamba 1 only | D = 8k | 262k |
| exp2 | Mamba 1 Ā = exp(ΔA) | D·N = 131k | 4.2M **per token regardless of L** |
| exp2 | Mamba 2 | H = 32 | 1k |

Energy weighting at L=4k, per token (7B projection: 22.4 µJ/token total MVM):

- softmax exp done via conversion chain: 4.2M x 3.1 pJ = **13 µJ/token** — it
  would add ~58 % to the whole token budget. Done analog in-loop: 4.2M x
  0.26 pJ = **1.1 µJ/token** (5 %). This single line is why the analog exp
  matters; at 128k context it is the whole ballgame (projected 419 µJ vs
  35 µJ).
- SiLU: 352k ops → 1.1 µJ chain vs 0.09–0.23 µJ analog (projected from the
  measured scalar/batched numbers). Same verdict class, smaller stakes.
- reciprocal standalone, rsqrt, softplus: 1k + 64 + 0 ops → sub-nJ at any
  implementation. Frequency kills the debate: these can be arbitrarily
  expensive per op without moving the token budget.
- Mamba 1 is the exception that keeps digital honest: 4.2M exps/token at fixed
  cost independent of L, elementwise into a mutable state — on Chip 1, where
  norm-statistics operands are already digital. Digital full-table (93 fJ x
  4.2M = 0.39 µJ/token, estimated) is fast and cheap; an analog translinear
  bank at ~2 µs settle would need ~10⁵-way parallelism to keep pace. Digital
  wins this volume. (Mamba 2 collapses the count to 1k/token and the question
  evaporates.)

## 6. Verdicts

| primitive | verdict | numbers | binding constraint |
|---|---|---|---|
| **exp2 (softmax / SiLU path, Chip 2 + MLP)** | **ANALOG WINS** | 0.26 pJ/exp batched incl. normalization (measured) vs 3.1 pJ digital chain (measured+counted); 4.0 bits over 8 octaves = faithful fp8 e4m3 (measured, 3 temps); settle 1–2 µs, hidden inside the 4.12 µs pass | subthreshold curvature caps it at 4 bits — fp8 exactly, nothing more; β(T) needs per-temp recal/PTAT; per-device trim needed at small geometries |
| **exp2 (Mamba-1 volume, digital-operand contexts)** | **DIGITAL WINS** | 93 fJ, ~2 ns, 522 µm², exact (counted/estimated) | analog latency: µs settle vs 4.2M ops/token at fixed cost; operands already digital |
| **reciprocal** | **ANALOG by fusion** (softmax/sigmoid: it is free — KCL normalization, ≤1.4 % measured); **DIGITAL standalone** (157 fJ table, counted) | standalone volume is 1k ops/token — irrelevant either way | translinear loop ceiling ~4 bits (estimated); fusion only exists inside a normalization |
| **rsqrt** | **DIGITAL WINS** | 157 fJ seed + Newton ≈ 1 pJ (estimated), 64 ops/token | needs 8+ bits on fp32 norm statistics (declared digital island); analog ceiling 4 bits — disqualified, and frequency makes it moot |
| **log2 / softplus** | **DIGITAL** (128-entry midrange table, trivial); analog log is native at 4 bits if a fused SSM path ever wants it (estimated) | 262k ops/token only in Mamba 1 | same curvature ceiling; no fused analog consumer exists yet |

**The one-sentence version:** the analog LUT assumption survives, but narrowly
and specifically — analog wins exactly where the operand already lives in
charge and the op is batched behind a normalization (softmax exp+recip, SiLU),
because what it saves is the 1.8–6.1 pJ conversion tax, not the 0.1 pJ table;
everywhere operands are digital or precision exceeds 4 bits, the fp8 full-table
ROM at 93 fJ is unbeatable and CORDIC never enters the picture.

Chip 2's op list (MAC, max, exp2, rescale, one reciprocal) is therefore fully
analog-feasible at fp8. Chip 1 keeps rsqrt, softplus, and bulk elementwise exp
digital, which matches Part IV's digital-island list.

## 7. Risks and open items

- 4.0 bits is *exactly* faithful fp8-e4m3 — zero margin. Any additional error
  source (drain modulation under real column loads, trim residue, aging) eats
  into softmax quality directly. A tile-context rerun of tb_lut_exp under the
  real A6 load is the next falsifier.
- MC used 8 seeds (device draws); enough for a σ estimate, not tails. Trim
  range needed: ±3σ_VT ≈ ±10 mV ≈ ±0.4 octave — well inside one write_dac LSB
  path, but the trim DAC resolution (60 mV LSB) is coarser than the needed
  offset step; trim wants the rstring_ladder's non-uniform taps or a finer
  vernier. Unresolved.
- Settle at the bottom code (1.9 µs at 1.7 nA) is the latency floor; raising
  the whole window trades it against energy at fixed I·τ. If a future schedule
  needs <1 µs softmax, clip the range to 6 octaves (fp8 flush at 1/64) or add
  a per-branch settle accelerator.
- The exp2 verdict was measured on one device geometry (47.4/1.0). The
  batched 0.26 pJ/exp number inherits tb_softmax's 8-branch row; wider rows
  (real L) amortize further but add wire/mirror error not yet measured.

## Repro

- Analog falsifier: `PYTHONPATH=analog/schematics python analog/testbenches/tb_lut_exp.py`
  (ngspice 43 at build/ngspice43, sky130A via ~/.volare). PASS as of 2026-08-27.
- Digital tables: 256-case Verilog ROMs (exp2 fp8 e4m3 full, exp2 8b seed,
  recip 8b seed) → yosys 0.62 `synth; abc -liberty sky130_fd_sc_hd__tt_025C_1v80`;
  cell/area from `stat -liberty`. Energy = cells x 3 fF x 1.8² x a=0.1
  (METRICS digital rail method).
