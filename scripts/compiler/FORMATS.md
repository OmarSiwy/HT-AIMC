# Compiler output formats (A5 -> A2/A3/A4/A6)

Everything lands in `scripts/compiler/out/` (regenerate any time with
`PYTHONPATH=scripts python3 scripts/compiler/compile.py`; deterministic,
seed in manifest). All codes follow the golden conventions in
`scripts/golden/model.py` and the rail widths in
`scripts/digital/INTERFACES.md`.

## Directory map

```
out/
  manifest.json            index: model, prompt, token ids, per-matrix dims,
                           D, budgets, pass counts, file map
  passes.json              EXACT tile-pass counts/token + tok/s formula +
                           per-matrix N_eval histograms (early termination)
  digital_config.json      per-matrix A4 rail fields (see below)
  golden_trace.npz         per-token observation points of the real forward
  programming/<m>.npz      Wq, Cp, Cn, chk caps, s16, smooth, dw, dx_in, D,
                           dy, requant scale/shift/offset   (per matrix m)
  acts/<m>.npz             xq (T, I): bit-true INT8 input stream per matrix
  passes/pass_NN_<tag>/    >= 8 representative REAL tile passes for SPICE
```

Matrices `m`: `attn_q attn_k attn_v attn_o ffn_gate ffn_up ffn_down`
(SmolLM2-135M blk.0, head-0 slice; shapes in manifest).

## Representative pass directory (what A2's tb includes)

Selected from the real last-token stream: `worst_code` (global max |y12|),
`sparse` (max zero weights+acts), `eterm_min`/`eterm_max` (early-termination
extremes), `chk_max` (largest clean ABFT residual), `typ_<m>` per matrix.

### caps.spice — cap-code params for one 16x16(+chk) tile
```
.param wcp_r{i}c{j}=<0..15>   i = tile row (input) 0..15
.param wcn_r{i}c{j}=<0..15>   j = tile column (output) 0..15
.param wcp_r{i}c16=...        column 16 = ABFT checksum column (differential
.param wcn_r{i}c16=...        split of signed chk_i, |chk_i| <= 15)
```
Weight of column j at row i is `wcp - wcn` in 4b LSBs (W = C+ - C-,
zero = both 0). Consume as `{wcp_r3c7}` inside a python-generated netlist or
`.include` the file and reference the params in cap expressions.

### pwm_lo.spice / pwm_hi.spice — one nibble window each
Independent sources per differential row input:
```
vxin_p_r{i} xin_p_r{i} 0 PWL(...)   pulse on the + rail when sign >= 0
vxin_n_r{i} xin_n_r{i} 0 PWL(...)   pulse on the - rail when sign < 0
```
Pulse amplitude VDD=1.8, edges `t_edge`=0.1 ns, start `t_start`=5 ns.
Width = `lo_i * t_q` (lo window) or `hi_i * 16 * t_q` (hi window) with
xq_i = sign * (16*hi_i + lo_i); zero nibble = flat 0 source. Sum contract
(tested): T_lo + T_hi = |xq_i| * t_q. Convert each window separately;
the rail's nibble_combine makes y12 = sat12(16*code_hi + code_lo).

### params.spice
`t_q` (10 ns sim; real target 200 ps — scale linearly), `vdd`, `t_start`,
`t_edge`, `t_win_lo` = t_start+16*t_q (LO window close), `t_win_hi` =
t_start+128*t_q, `dcode` = converter LSB D (code units per reference
packet), `abft_budget`.

### expected.json — golden numbers for the numeric asserts
Per column (16 data + chk): `mac_hi/lo` (ideal charge MAC in code units),
`code_hi/lo` (signed, tile_fsm clamp +-127), `coarse_*` (event count),
`fine_*` (SAR residue), `n_eval_*` (comparator strobes = early-termination
count, min(count+1,15)), `y12`, `y14`, `chk_*`, `abft_residual`, `budget`,
plus the programmed `Wq/Cp/Cn/chk/s/xq/pwm`. Acceptance per CONTRACT:
silicon codes within +-1 LSB of `code_*`; residual <= budget.

## digital_config.json (A4 rail programming)

Per matrix: `requant.scale` (unsigned 8b, per channel), `requant.shift`
(0..24), `requant.offset` (signed 8b, applied AFTER shift — 0 everywhere,
symmetric quant), `D`, `acc_rounds` (bacc tile_cnt is 4b: row-tiles > 15
accumulate in fabric-summed rounds, e.g. 36 -> [15,15,6]), `relu_en` (0 for
all real-model matrices — multi-row-tile outputs; see relu_note),
`abft.{s, chk_shift, budget, max_clean_residual}`.

ABFT wiring (A4's abft_check computes a PLAIN sum): feed
`y_flat[j] = s[j] * acc_j` and
`y_chk_port = (acc_chk << chk_shift) + sum_passes round_half_away(e.xq / D)`
where `e` = `programming/<m>.npz` key `e4` (per-tile compile-time checksum
rounding, |e_i| <= 4) and xq is the pass's activation tile (the fabric
schedules it, so both terms are known digitally). The correction removes the
traffic-dominated rounding term; the remaining budget covers conversion
rounding only, which is what makes single-cap faults visible. Then
`|residual| <= budget` on clean traffic. LoRA-active passes bypass/widen the
check (sidecar charge has no checksum-column image).

ReLU sequencing (fixture-scale FFN only): HI window converts first with
relu_en=1 (negative col_sign -> code 0, no conversion, LO skipped);
LO gets relu_en only when code_hi == 0; the fabric then ReLU-clamps the
recombined y12 to >= 0 (free digital compare — exact; the sign exit itself
is an energy prediction, see golden `tile_mvm` docstring).

## npz schemas

`programming/<m>.npz`: `Wq` (O,I) int in [-7,7]; `Cp`,`Cn` (O,I) 0..15;
`chk` (Oc,Rc,16) signed checksum-column caps per tile; `s16` (16) +-1;
`smooth` (I) SmoothQuant divisors (digital wrapper applies x/s before
quant); `dw` (O) weight LSBs; `dx_in`, `D`, `dy` scalars; `scale`,`shift`,
`offset` (O) requant fields.

`acts/<m>.npz`: `xq` (T,I) INT8 codes actually driven for the prompt —
derive any pass's PWM via golden `pwm_schedule`; tile (c,r) of token t uses
`xq[t, r*16:(r+1)*16]` against columns `c*16..c*16+15`.

`golden_trace.npz`: `ids, E, A_in, q8, q8p, k4, v4, p (T,T causal), av8,
attn_out8, H, F_in, g8, u8, ffn_out8, out` — every observation point of the
real-model forward (head-0 attention contribution + full blk.0 FFN,
residual stream included; documented slice fidelity: 1 of 9 heads).

## Format-universal compilation (A5b): `formats.py`, `--wfmt/--afmt`

`compile.py --wfmt <f> --afmt <f>` compiles ANY source quantization onto the
fixed substrate. Defaults (`int4 x int8`) run the frozen A5 path above —
regression-locked bit-identical. Anything else runs the format-exploration
flow into `out_formats/<wfmt>__<afmt>/` (same npz/json layout; no SPICE rep
passes / golden e2e trace — those are the default-format deliverable).

Registry (`formats.py FORMATS`): int2..int8 (symmetric signed),
fp2 {0,±1} (s+e1m0, ternary — the set {0,±.5,±1,±2} needs 3 bits and is
fp3_e2m0), fp3_e1m1, fp3_e2m0, fp4_e2m1 (=MXFP4, alias fp4), fp6_e2m3,
fp6_e3m2, fp8_e4m3 (OCP: no inf, s.1111.111=NaN, max 448), fp8_e5m2 (OCP:
IEEE inf/nan, max 57344), bf16, fp16, fp32. decode() honors subnormals and
specials; encode() saturates (|x|>max -> max_finite, never inf; NaN -> 0).

THE LOWERING LAW (one theorem, no per-format hacks): weights lower to
`W[j,i] ~ w_scale[j] * 2^exp[j,rt] * M[j,i]` — per-output-channel float
scale (folded into requant, like dw today), per-(row, 16-input-block) shared
exponent aligned to row-tiles (BFP), integer mantissa of width
`b_eff = min(source full-capture width, target 8)`. M splits into
`S = ceil((b_eff-1)/4)` slices of 4b differential cap codes (sign rides the
C+/C- pair for free), slice significance 16^s applied in the digital
shift-add; block exponents are per-column left-shifts on tile partials in
the accumulator. **Exponents never enter the analog core.** Activations:
per-tensor scale + INT-b_x mantissa driven as ceil((b_x-1)/4) PWM nibbles,
2 nibbles (1:16) per hardware pass.

PASS-COUNT LAW (identity: int4 x int8 = 1 pass/tile, today's 10944/token):
```
passes/tile = ceil((b_w_eff-1)/4)  *  ceil( ceil((b_x-1)/4) / 2 )
              [weight slices]         [nibble-pair rounds; b_x<=8 -> 1]
```

Fidelity report: manifest records per-tensor `sqnr_w_db` (lowering vs
float64), `sqnr_x_db`, and `mvm_sqnr_db` (golden MVM vs float64, last
token). **CSNR ceiling: the B_y=8 readout caps end-to-end MVM SQNR at
~25 dB regardless of source precision — >8b per-element mantissa
(fp16/bf16/fp32) is physically unredeemable; lowering allows it but flags
`over_by8`.** Measured consequence: b_eff<=5 single-slice formats (fp4,
fp8_e4m3 at target 5) are the pass-count sweet spot; S=2 doubles passes
for a few dB.

digital_config for format runs: `slices`, `slice_sig`, `b_eff`, `b_x`,
`nibble_rounds`, `exp_shift_span`, `required_acc_bits` (generalized-rail
spec — A4's sat14 x4 slice_combine covers only the historic 2b-slice case),
`abft: null` (slice digits span ±15, exceeding the chk-cap range at
CHK_SHIFT=3; chk_shift=4 rail change is the upgrade path).

GGUF reader now also dequantizes Q4_K / Q5_K / Q6_K (llama.cpp super-block
layouts), so common K-quant checkpoints load through the same law.

## CSD weight recoding (task A): `compile.py --csd`

`formats.csd_digits` recodes integer weight/slice codes to canonical signed
digits (non-adjacent form): digits in {-1,0,+1}, no two adjacent nonzeros,
`sum_k d_k 2^k == W` exactly. `formats.csd_caps` maps digits onto the
differential pair: +1 at position k sets bit k of C+, -1 of C-, 0 programs
nothing. `Cp - Cn == Wq` always, so the analog pass converts BIT-IDENTICALLY
to the one-sided split (`golden.tile_mvm_caps`; asserted on the real Wq
head-0 grid in test_formats). `--csd` writes the recoded programming vectors
+ rep-pass caps.spice to `out_csd/` plus a measured `csd_report.json`;
the default `out/` stays byte-identical (regression-checked).

Width constraint: NAF of an n-bit magnitude can carry into position n
(7 -> +8-1, 15 -> +16-1), so 4S-bit slice digits can need one extra slice
position. |Wq| <= 7 stays single-slice (carry lands on bit 3); sources with
b_eff = 4S+1 (e.g. fp4 at b_eff 5) grow S_csd = S+1. `csd_caps` sizes this
automatically and reports `S_csd`.

Measured on the REAL SmolLM2 blk.0 matrices (duty = mean|xq|/255 over the
real 9-token stream), `charge_cost` unit conventions:

| metric                                   | one-sided | CSD    | change |
|------------------------------------------|-----------|--------|--------|
| nonzero-digit density (of 4 positions)   | 0.196     | 0.195  | -0.3%  |
| unit-cell charge (cells x duty, pooled)  | --        | --     | -0.6%  |
| binary-weighted C_u charge (value x duty)| --        | --     | +16.4% |

The paper's 1/2 -> 1/3 (~33%) density claim is the WIDE-UNIFORM-WORD
asymptote and lives in the unit-cell (bit-sliced) cost model: measured
ladder = uniform 8b codes 20.8% digit drop, real int8-lowered Wq mantissas
13.1%, real INT4 codes 0.3% (in [-7,7] only |w|=7 saves a digit, and the
real density is already 0.196 << 1/2 because quantized weights concentrate
near zero). On the mini's binary-weighted charge banks the value-weighted
charge RISES ~16% under CSD (one-sided Cp+Cn = |W| is provably minimal), so
CSD only pays on unit-cell/bit-sliced arrays or for switch-count-dominated
costs — both reports come from the same `charge_cost` fn, per matrix, in
`csd_report.json`.

## DPS rank-48 bilinear lowering (task B): `compile.py --dps48`  -- VERDICT: dead-end at INT4

`scripts/compiler/dps48.py` embeds the Dumas-Pernet-Sedoglavic rank-48 <4,4,4>
scheme (arXiv:2506.13242; tensor from fmm.univ-lille.fr, `verify()` checks
the Brent equations exactly). It multiplies 4x4 blocks of 16x16 tiles with 48
products instead of 64 -> **x0.75 tile passes** (432 vs 576 per 4-token
group; steady-state 0.75x/token, confirmed in `passes.json`). A-side (weight)
combos are programmed once as differential cap tiles; B-side (activation)
combos are cheap digital pre-adds before PWM; C-side is digital post-adds
(dyadic coeffs W in {+-1/2,+-1/4,+-1/8}, the /8 folds into the requant shift).

**The verdict, measured on the real SmolLM2 blk.0 matrices (`test_dps.py`):**
the scheme's promise holds in EXACT arithmetic -- algorithm tax -0.02 dB on
attn_q, matching the paper's +0.13 dB claim -- but it does NOT survive INT4
cap quantization. The tax decomposes:

| stage (attn_q, real Wq) | SQNR | tax vs classical |
|-------------------------|------|------------------|
| classical single-slice  | 23.70 dB | (baseline) |
| DPS exact arithmetic    | ~23.7 dB | **-0.02 dB** (paper's promise) |
| DPS + s_a/s_b re-quant  | ~16.2 dB | +7.5 dB |
| DPS full (+conversion)  | 16.19 dB | **+7.52 dB** |

Root cause (not a bug -- the shift sizing is provably minimal): a folded
A-side combo is `sum_ab U[m,a,b]*Wq_tile[..]`, a sum of up to 16 INT4 weights,
so `|A|` reaches ~35 (needs ~7 bits) vs a single weight's 7 (4 bits). Forcing
each combo into one 4-bit differential cap slice requires a per-product
power-of-2 shift `s_a` (÷2 on most products, ÷4 on a few) that throws away
~2 bits; `s_b` does the same on the B-side. That lost precision -- not the
recombination and not the converter -- IS the 7.5 dB. Across all seven
matrices the INT4 tax is +4.69 .. +10.93 dB.

Recovering the precision needs a second 4-bit slice per combo tile, i.e.
`2*48/64 = 1.5x` passes -- which erases the 0.75x win and then some.
**So DPS-48 is net-negative at INT4 x INT8 cap quantization and stays
flag-gated OFF.** It is kept as a documented dead-end-at-this-precision, not
deleted: the algorithm is exact and the win is real in code count, so it may
turn net-positive at higher operand precision (b_x/b_w with enough native
slices to hold the combo range for free -- e.g. fp8 where S=2 is already the
baseline, so the extra combo bit is amortized). `--dps48` still emits the
full `out_dps48/` tree (programming/manifest/passes/digital_config) with the
measured per-matrix `snr_tax_db` recorded in the manifest fidelity block, so
the tradeoff is auditable. ABFT is disabled under `--dps48` (chk-cap range
can't carry combined-tile column sums; Freivalds on the recombination tree is
the upgrade path).

## CSNR lattice thresholds (task C): `compile.py --lattice`

Paper L6 / law:csnr: the ideal pre-ADC signal is a discrete `(N+1)`-point
lattice of achievable MAC values, not a continuum. Placing converter
comparator thresholds MID-LATTICE (midpoints between adjacent achievable
values) instead of on the uniform `(k+1/2)*D` grid lets the converter DELETE
analog noise below half the local lattice pitch -- up to +6 dB / -3 converter
bits when the pitch >> sigma_a; it dies as N or sigma_a collapses the pitch to
the converter LSB. `scripts/compiler/lattice.py` + golden `output_lattice /
lattice_thresholds / convert_lattice / convert_uniform / csnr_db`.

Measured (`test_lattice.py`, injected Gaussian analog noise, code units):

- Controlled sparse column (2 nonzero weights = pitch 3): +inf dB at
  sigma 0.4 (pitch/sigma 7.5, noise fully deleted), collapsing to +0.17 dB at
  sigma 6 (pitch/sigma 0.5). A fully DENSE lattice (every integer achievable,
  pitch 1) at sigma >> 1 gives ~0 dB -- mid-lattice == uniform, the death
  regime. This is the paper's law reproduced end to end.
- Real SmolLM2 blk.0 matrices (D=1, dense-ish but genuinely SPARSE achievable
  sets over a wide extent): peak CSNR gain +15.8 .. +25.7 dB in the low-noise
  regime (attn_k lowest, ffn_gate highest), decaying with sigma_a. Because the
  real achievable set stays sparse over a wide range, the win decays slowly
  (attn_q: ~13 dB at sigma 1 -> ~1 dB at sigma 128) rather than dying sharply;
  the sharp death only appears once the lattice is made fully dense. Net: the
  effect is real and positive on every real matrix at realistic converter
  noise, biggest where the pre-ADC lattice is sparsest.

**Handoff interface (SPICE wiring OUT OF SCOPE -- golden-validated only).**
`out_lattice/threshold_schedule.json`: per matrix `D` and per output
column-block `{vrn_code, vrp_code, lattice, boundaries, tap_codes, pitch,
sigma_break}`. Boundaries and rails are in CONVERTER CODE UNITS; the converter
maps a code-unit value `c` to the tap voltage `vcm + c*u`, `u = D*C_u*VDD/
C_int` volts/unit (`analog/.../integrator_conv`). `tap_codes` are 4b R-string
taps for the coarse comparator + SAR reference: `tap_k = vrn + k*(vrp-vrn)/15`,
k=0..15 (`analog/.../rstring_ladder`, monotone by construction, non-uniform via
the tap mux selecting a tap code per decision). `out_lattice/csnr_gain.json`
is the measured gain curve per matrix per sigma_a. A3's converter consumes
`tap_codes`; A6 can fold the CSNR gain into the B_y/energy tradeoff (fewer
converter bits at equal CSNR when the lattice is sparse).

## Metrics hooks (A6)

`passes.json`: exact per-token tile-pass counts (counted, not estimated):
144 per 64x576 projection, 3456 per FFN matrix, 10944 total/token; KV/softmax
aux-op formulas in 8x8-array units; `tok_per_s_formula`; per-matrix N_eval
histograms -> E_conv vs |code| evidence for tb_eventrate cross-check.
