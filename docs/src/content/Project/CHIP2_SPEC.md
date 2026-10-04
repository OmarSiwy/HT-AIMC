# Chip 2 — in-memory attention engine (implementation spec)

Build target for the attention half of AnalogIOC (THE_COMPILER_STRUCTURE.md
Part IV, B3). Full analog except (a) the die-to-die link and (b) the fp32
digital islands the precision table mandates. Style and conventions follow
CONTRACT.md: python netlist generators, gm/ID sizing from A1 tables, every
block ships a numeric-assert PASS/FAIL testbench, sky130 first, one status
line to STATUS.md per agent.

Source labels used throughout: [measured, STATUS A3/METRICS] = SPICE tb in
this repo; [paper, sec_attention/sec_formats] = paper law; [compiler doc
Bn/Part IV] = THE_COMPILER_STRUCTURE.md; [projected] = law-scaled, no sim.

---

## 1. Function and the traffic law

One unit computes, per query, the fused loop at the KV cache:

```
broadcast in : q                    (d_h values)
stream local : K, V                 (2·L·d_h values, never leave the die)
return       : (o, m, l)            (d_h + 2 values)
```

qK^T → online-softmax → A·V, fused, is the canonical
broadcast-stream-reduce op [compiler doc B3]. Traffic ratio:

```
R = bytes(streamed) / (bytes(broadcast) + bytes(result))
  = 2·L·d_h / (2·d_h + 2)  ≈  L
```

At L = 128k this is ~**128,000×** less memory-interface traffic than
shipping K,V to the compute [compiler doc B3/Part IV]. This ratio is the
reason the chip exists; nothing in this spec may reintroduce an O(L) term
across the die boundary.

The same unit serves **MoE decode FFN**: tiny activation broadcast in, huge
expert weights streamed from the same banks, tiny result out — identical
geometry [compiler doc B3, "the MoE row is the one people miss"]. Mode
switch in §8.

### Geometry

| param | mini (SPICE, this repo) | target (projected) |
|---|---|---|
| d_h | 8 | 128 |
| bank = tokens/gain-cell array pair | 8 | 64 |
| banks/group G (analog combine) | 2 | 16 (window-limited, §4) |
| groups/session window | 1 | W_res/(G·64), e.g. 2 at W_res=2048 |
| rows driven simultaneously | 8 | 8 (sub-bank interleave; 10 uA class-A column budget [measured, STATUS A3]) |

Mini numbers are the acceptance-test scale; target numbers are parametric
and labeled [projected] wherever used.

---

## 2. Block list

| # | block | analog realization | measured anchor |
|---|---|---|---|
| B1 | KV gain-cell banks | 2T all-NMOS cell, 30 fF store, 0.9 V write ceiling (components/gain_cell_array) | E_wr 7.5 fJ/cell, E_rd 2.4 pJ/8-row pass, tau_ret ~27 ms, 10 reads = -43 uV, write disturb -6.2 uV [measured, STATUS A3] |
| B2 | qK charge-domain MAC | q as PWM on rd source lines, column charge on virtual-ground integrators; converter = integrator_conv reuse (event-rate coarse + 4b SAR) | gain-cell read monotone 16/16 levels; converter ±1 LSB, E(0) 0.50 pJ [measured, STATUS A3/A8b] |
| B3 | running max | WTA: shared-source follower-max, replica-biased | new; budget §2.3 |
| B4 | exp + local sum | translinear softmax bank (components/translinear_softmax); shared-source node voltage = logsumexp readout | KCL checksum ≤0.16%, branch err ≤1.4%, beta 27.31/24.71/22.36 /V at 27/55/85 C, settle 0.99 us, 2.08 pJ/op [measured, STATUS A3/METRICS]; logsumexp *readout* itself unmeasured → tb_online_softmax_analog |
| B5 | rescale multiply | programmable gain = translinear ratio pair, gain = exp(beta·ΔV) ≤ 1; fallback V→T ramp per lora_sidecar idiom | same subthreshold physics as B4 [measured beta]; V→T eps 18 ns baseline-cancelled [measured, STATUS A3] |
| B6 | A·V drive | softmax output currents → I→T (lora_sidecar ramp idiom) → PWM on V-array rd lines; o accumulates in charge on column integrators | V→T measured [STATUS A3]; e2e path exercised by tb_attention_e2e [CONTRACT test 2] |
| B7 | fp32 combine island (digital) | monoid combine across groups and across time-multiplexed passes; max/exp/FMA in fp32 | mandate: softmax max+sum fp32, long-axis accumulators fp32 [compiler doc precision table] |
| B8 | sink SRAM island (digital) | 128-entry K/V protected set, exact digital rescore | 3% energy for ~100% accuracy recovery anchor [paper, sec_attention / feng2026selective] |
| B9 | die-to-die link | serial link + dual-clock Gray-pointer async FIFO (GALS) | Gray-CDC idiom already in A4 rail [INTERFACES.md] |
| B10 | sequencer | async_ctrl delay-chain idiom, no global analog clock | tq_chain measured [STATUS A1] |
| B11 | CAM spill prefilter | 2b discharge-race signatures over spilled keys, top-k candidates | **phase-2, unverified** [paper, sec_attention] |

Reciprocal is **not** a Chip 2 block — decision in §3.

### 2.1 KV banks (B1): sizing from the lifetime-matched-memory law

Law: tau_ret > 2^b · T_use, b = 4 stored bits → tau_req = 16 · T_res,
where T_res is window residency (seconds at ms-class token cadence), not
the per-read interval [paper, sec_attention].

- Measured CMOS cell: tau ≈ 27 ms [measured, STATUS A3] → refresh-free
  residency T_res ≤ 27 ms / 16 ≈ **1.7 ms**. Any decode session outlives
  that by orders of magnitude, so **refresh-from-shadow is mandatory**
  (rewrite each entry from its digital shadow copy at tau/2 cadence; the
  shadow exists anyway for spill) [paper, sec_attention].
- Refresh budget, target scale (W_res = 2048, d_h = 128, K+V): 2·262k
  cells × 7.5 fJ = 3.9 uJ per full rewrite, every tau/2 = 13.5 ms →
  **~0.3 mW per head** [projected from measured E_wr]. Time: 150 ns
  column write slot [measured, METRICS] × 2048 columns = 307 us per array
  per 13.5 ms = **2.3% write duty** [projected]. Refresh writes serialize
  against reads on the wsel/wdata buses — sequencer must interleave
  (risk R4, §10).
- Escape hatch: BEOL oxide-semiconductor gain cells, ~3 orders longer
  retention [paper, sec_attention cite leroux2024analog] — drops refresh
  to Hz-class. Not in sky130; document as production option only.
- K/V stored at 4/4 bits per element (co-designed quantizer) [paper,
  sec_attention]; write path = write_dac, 4b, 16/16 monotone, 1.2 pJ/slot
  [measured, STATUS A3].

### 2.2 qK MAC (B2)

Per the weight-tile idiom: broadcast q as PWM durations on the 8 rd
source lines (per 8-row sub-bank), each token column integrates
sum_r I_read(k[r][j])·t_r = q·k_j in charge on its 0.9 V virtual-ground
rail [measured read path, STATUS A3]. d_h = 128 → 16 sub-bank passes
interleaved in time, partial charges summed on the shared column
integrator (the class-A OTA sinks ≤ ~10 uA, so ≤ 8 simultaneous rows —
compiler schedule constraint carried over verbatim from STATUS A3).
Read-current I(V) is exponential below Vth → compiler pre-distortion via
the code→I calibration (tb_lora method, 0.1%) [measured, STATUS A3].
Tile phis clock-gated outside the window (A8 FIX v2 discipline).

### 2.3 Running max (B3): WTA topology + precision budget

**Primary topology**: N-input source-follower max — N NMOS followers
sharing one source node with a tail sink; V_out = max(V_i) − VGS + soft
excess. Replica follower (same coordinate, driven by a reference) cancels
VGS. This is the softmax bank's own topology re-biased (the paper notes
spread beyond headroom turns the normalizer *into* a WTA
[paper, sec_formats §translinear]), so it reuses the measured device
coordinate (47.4/1.0 at gm/ID 25 [measured, STATUS A3]).
**Fallback**: Lazzaro current-mode WTA — rejected as primary because it
returns argmax, not the max value.

Precision budget. Softmax is shift-invariant: an m̂ error that is applied
*consistently* to numerator and denominator cancels exactly. So the WTA
carries no accuracy requirement, only a **range** requirement:

- systematic: m̂ ∈ [m, m + nU_T·ln N] (logsumexp smoothing; 37 mV × ln 8
  ≈ 77 mV worst-case all-equal, ≤ ~5 mV when the winner leads by 4 nU_T).
  Overestimate is safe (pushes exp args negative); the score mapping must
  reserve nU_T·ln N of the 120 mV window as headroom [measured window,
  STATUS A3].
- random: replica-cancelled offset ≤ ±5 mV (Pelgrom-sized or trimmed —
  the paper's own budget line for the bank: sigma_VT 3–5 mV vs nU_T 36 mV
  [paper, sec_formats]).
- structural rule (non-negotiable): the **same physical m̂ node** biases
  both the exp bank (B4) and the rescale pair (B5). Two independent m̂
  copies would break shift-invariance and turn ±5 mV into ~14% exp error
  (e^(beta·5mV), beta 27.31 /V [measured]).
- settle ≤ 1 us (match softmax settle 0.99 us [measured]).

### 2.4 exp + local sum (B4), rescale (B5), A·V (B6)

- B4: scores sampled onto the bank gates inside the 0.6–0.85 V CM,
  ≤120 mV spread window [measured, STATUS A3]. Outputs: (i) normalized
  currents a_j·I_b (drive B6), (ii) the shared-source node voltage V_ls
  which physically carries ln(sum_j e^(beta·s_j))/beta — the local
  denominator in log domain, no max subtraction needed (normalization by
  the tail is overflow-proof [paper, sec_formats eq. softmax]). V_ls as a
  *readout* is new and unverified → acceptance test T4.
- B5: per-bank gain g_b = exp(beta·(V_ls,bank − V_ls,group)) ≤ 1 by
  construction, one translinear ratio pair per bank output bundle. PTAT
  bias on the sampling gain closes beta(T) (production fix already noted
  for the bank: fixed-bias I_b drifted 0.58→2.2 uA over 27→85 C
  [measured, STATUS A3]).
- B6: a_j currents → PWM durations via the measured V→T ramp idiom
  (integrate on C, linear pfet ramp, comparator self-times the window;
  eps cancelled by x=0 baseline pass [measured, STATUS A3]); durations
  drive the V-array rd lines; o_bank accumulates in charge on the group's
  column integrators (KCL, exact, carry-free [paper, sec_formats]).

---

## 3. Reciprocal: digital, host-side. Decision and why

The softmax denominator l accumulates over the full sequence axis
(L up to 128k). The precision table is explicit: "softmax internals: fp32
for max and sum" and "anything that accumulates over a long axis ... needs
fp32" [compiler doc, precision table]. A translinear divide is a 1–2%-class
operation (measured branch error 1.4% [STATUS A3]) and an error on l
multiplies **every element of o systematically** — not a random-walk term
the sqrt(K) budget absorbs. So:

- Chip 2 never divides. It returns raw (o, m, l).
- The one reciprocal per query row runs in fp32 on Chip 1's digital rail
  ("reciprocal once at the end, which can live host-side"
  [compiler doc B3]). o_t = o/l lands right where the output projection
  consumes it.
- Consequence: Chip 2's only mandated digital arithmetic is the B7 combine
  island (max, exp, FMA in fp32) + the B8 SRAM island. No divider anywhere.

---

## 4. The online-softmax monoid in analog

The combine [compiler doc §6]:

```
(m1,l1,o1) ∘ (m2,l2,o2) = (m, l1·e^(m1−m) + l2·e^(m2−m),
                              o1·e^(m1−m) + o2·e^(m2−m)),  m = max(m1,m2)
```

Associativity of ∘ is the offload-legality proof [compiler doc B3]: any
grouping of per-bank partials is bit-equivalent in exact arithmetic, so
banks may reduce independently and a tree may merge them. The hardware
mapping splits the tree at the point the precision table dictates:

**Level 0 — bank (analog).** 64 tokens (mini: 8). Produces
(m̃ = WTA output, V_ls = log-domain l̃, o_bank = charge on integrators,
normalized to I_b).

**Level 1 — group (analog), G ≤ 16 banks.** A second shared-source stage
over the banks' V_ls values computes the group logsumexp; B5 ratio pairs
apply g_b = l_b/l_group to each bank's o currents; group o = KCL charge
sum. No retroactive rescale exists at this level — banks combine
*spatially*, in parallel, so no stored charge is ever rescaled. G is
capped by the constant-beta window: combining G banks grows the log axis
by up to ln G nats = 37 mV·ln 16 ≈ 103 mV, against the measured ≤120 mV
window [measured, STATUS A3] → **G = 16 max** (mini: 2).

**Level 2 — root (digital fp32, island B7).** Group partials are
digitized and the streaming monoid runs in fp32 across (a) groups and
(b) successive time-multiplexed passes when a session window exceeds the
physically resident banks. Retroactive rescale (new max raises m) happens
only here, as an fp32 multiply. This placement is exactly the mandated
island: l at this level accumulates over L [compiler doc precision table].

**Precision per partial** (what crosses level 1 → 2):
- m̃: 8b in the score-voltage domain (existing integrator_conv converter,
  ±1 LSB [measured]).
- l̃: 8b code of V_ls — a *log-domain* code, so 8b buys relative precision
  over the whole octave span [paper, sec_formats format algebra]; expanded
  to fp32 by exp in the island.
- o: d_h × 8b codes + one shared per-group scale (analog block-FP,
  the inter-tile format row of Table formats [paper, sec_formats]).

**Error accumulation law**: analog errors are multiplicative and compound
as sqrt(#crossings) [paper, sec_formats "compounds as sqrt(#ops)"]. Two
analog levels at ~1.4% per translinear crossing [measured] → ~2% analog
contribution; everything above level 1 is exact fp32. Budget: ≤3% on any
output element pre-requant (test T5).

---

## 5. Sink protection (non-negotiable)

KV noise sensitivity is position-concentrated: m = 8 sink tokens + the
recent window lose most; protecting exactly those recovers near-clean
perplexity at ~3% energy [paper, sec_attention / feng2026selective].
Protected set: **8 sinks + 120 recent = 128 entries per head**, softmax
kept (protection policy and scoring function chosen jointly [paper]).

Two options, quantified:

- **Full-analog: high-C gain cells.** +2 bits of SNR at the kT/C law
  (sigma_V = sqrt(kT/C); +1 bit = 4× C) → 16× C: 30 fF → **480 fF** per
  cell. Also buys ~16× retention (~430 ms) [projected from measured tau].
  Area at MiM 2 fF/um² [STATUS O1 raw param]: 240 um²/cell × 128 entries
  × 128 (d_h) × 2 (K,V) = **~7.9 mm² per head** [projected]. And the
  entries still decay, still eat read disturb, still need refresh.
- **Digital SRAM island (B8).** 128 × 128 × (4b+4b) = 128 kb per head;
  exact, no droop, no disturb. Rescore cost: 128·d_h = 16k digital MACs
  per query per head — the paper's measured anchor for exactly this
  policy is **~3% energy for ~100% accuracy recovery** [paper,
  sec_attention].

**Decision: digital SRAM island.** The analog option pays ~an order of
magnitude more area for a set whose whole point is to be *exact*, and the
corpus result we are anchoring to is the digital-protection experiment.
Budget line: ≤5% of per-query attention energy for the sink rescore
(test T7; paper anchor 3%). Integrity rule inherited from the spill path:
sink tokens are never CAM-filter candidates — pinned digital [paper,
sec_attention].

---

## 6. Chip 1 ↔ Chip 2 link contract

Exactly one dependency edge crosses the token-local / token-crossing
boundary in the whole model: the KV append (step 4 of token j before
step 5 of any t > j) [compiler doc §5]. That is why this link is the only
inter-chip dependency and why the cut survives: it carries the smallest
tensors in the model [compiler doc Part IV].

**Messages** (all O(d_h), fixed size, no O(L) term ever):

| dir | flit | payload | size at d_h=128 |
|---|---|---|---|
| C1→C2 | KV_APPEND | hdr{session 6b, layer 6b, kv-head 6b, pos 20b} + k' d_h×4b + v d_h×4b | ~133 B |
| C1→C2 | Q_BCAST | hdr + q d_h×8b (score-path precision [paper 4/4/8]) | ~133 B |
| C2→C1 | O_PARTIAL | hdr + o d_h×8b + scale 8b + m 8b + l fp32 | ~137 B |
| C1→C2 | CFG | mode bit (§8), refresh/window params, PTAT trim | ≤32 B |

**Rates at decode cadence** [projected]: 1000 tok/s/session, 32 layers,
8 KV heads (GQA), 32 query heads: forward ≈ 32·8·133 B·1e3 ≈ 34 MB/s +
Q_BCAST 32·32·133·1e3 ≈ 136 MB/s; return ≈ 140 MB/s. Sub-GB/s per session
against a UCIe-class die-to-die link — three orders of headroom. Mini
scale: 128b-class flits at 22 tok/s [measured cadence, METRICS] = kHz
traffic, trivially testable.

**GALS boundary**: Chip 2's analog domain is self-timed (async_ctrl
idiom, no global clock [CONTRACT]); the link SerDes has its own clock.
Crossing = dual-clock **Gray-pointer async FIFO** per direction, 2FF
synchronizers on the pointers, same discipline as the A4 rail's Gray
event-count export and the ≥2-clk pacing rule [INTERFACES.md]. Depth 16
flits/direction (decode-cadence traffic never backs up; assert
never-full in T9). Data quasi-static while its req is in flight, per the
existing A4 handshake contract.

Ordering rule carried from the dependency table: KV_APPEND(pos j) must be
ACKed by the bank sequencer before any Q_BCAST with pos > j is served for
that (session, layer, head). Single-writer append-only cache → no other
coherence exists [compiler doc B2].

---

## 7. Per-session spatial batching + spill path

**Batching**: sessions are parallel in **area** — each bank group holds
one session's window for the die's layer slice, B groups run concurrently.
No amortization exists to chase: the KV cache is private per sequence, so
batching cannot raise arithmetic intensity [compiler doc §3]; throughput
scales with tile-group count, which is the correct currency [paper,
sec_attention batch mapping]. Token cadence is set by Chip 1's weight
engine; attention hides under the FFN super-tile latency [paper].

**Spill (phase 2, unverified — do not build against it)**: context beyond
W_res spills to the digital shadow (HBM/host) as quantized KV. A 2b
discharge-race CAM prefilter stores signatures of spilled keys; a query
races in O(1) and returns top-k candidates; only those k are fetched and
re-scored **exactly** — the CAM is a filter, never the scorer [paper,
sec_attention]. Sinks never filterable (§5). Recall depends on the model
being fine-tuned with the filter in the loop [paper] — untested, ranked
risk R5. Phase-1 fallback: spilled tail re-streamed digitally (correct,
slow), or window-only attention per the co-designed model.

---

## 8. MoE decode FFN mode

One config bit per bank group (CFG flit): `MODE ∈ {ATTN, FFN}`.

| | ATTN | FFN |
|---|---|---|
| bank contents | K, V (per-token append) | expert weight tiles (columns = output channels) |
| broadcast | q (rows, PWM) | activation x (rows, PWM) |
| B3 WTA / B4 exp / B5 gain | active | **bypassed** — column charge goes straight to the converter |
| B7 island | monoid combine | plain fp32 accumulate across sub-bank passes (long-axis mandate holds: expert accumulator fp32 [compiler doc precision table]) |
| return flit | (o, m, l) | y slice, same O_PARTIAL format with m,l fields zeroed |
| refresh | tau/2 shadow refresh of window | **mandatory**: weights are read-only-persistent on a consuming substrate [compiler doc Part IV, "no third chip" remark] — refresh-from-shadow at T_res ≤ tau/2^b = 1.7 ms [measured tau + paper law] |

Expert swap cost [projected from measured]: a 128×256 expert slice =
32k cells × 7.5 fJ = 0.25 nJ write energy, 256 columns × 150 ns = 38 us
write time — fine against ms-class routing cadence, and the whole point
at low batch: activation in, weights streamed locally, result out
[compiler doc B3 MoE row]. Nonlinearity (SiLU) and routing stay on
Chip 1 (position-local / S5b [compiler doc]).

---

## 9. Acceptance tests (CONTRACT style: numeric asserts, PASS/FAIL)

| tb | contents | pass criteria |
|---|---|---|
| T1 tb_qk_bank | 16 random (q, K) on one 8×8 bank pair, PWM broadcast, codes vs golden | every column ±1 LSB; read-pass energy ≤ 2× the 2.4 pJ anchor |
| T2 tb_wta | 8-input follower-max, 16 patterns incl. all-equal and 1-LSB-split winners, 3 temps | settle ≤1 us to ±5 mV; m̂−m ∈ [0, nU_T·ln8 + 5 mV]; replica-cancelled offset ≤ ±5 mV; monotone under permutation |
| T3 tb_rescale_gain | translinear ratio pair, ΔV swept −120..0 mV, PTAT bias, 27/55/85 C | gain vs e^(beta·ΔV) ≤2% rel; T-drift after PTAT ≤ 1 guard bit (paper falsifier) |
| T4 tb_online_softmax_analog | 4 banks × 8 tokens streamed, level-0/1 analog + level-2 fp32, vs golden monoid; includes V_ls-as-logsumexp verification | final o ≤3% rel (±1 LSB post-requant), l ≤3%, m within T2 budget; **associativity**: two different bank groupings agree ≤1% |
| T5 tb_combine_tree | G=16 synthetic partials through level-1 stage | error ≤ 1.4%·sqrt(2) + margin = 2.5% (cascade law sqrt(K)) |
| T6 tb_kv_residency | write bank, 100 read passes + one tau/2 refresh cycle under traffic | store droop ≤1 write-DAC LSB (60 mV); ≤50 uV per 10 reads (anchor −43 uV); refresh/read interleave deadlock-free |
| T7 tb_sink_protect | inject KV noise on analog window, 128-entry set digital, vs no-protection run | ≥90% of attention-output error recovered; sink-path energy ≤5% of query total (anchor 3%) |
| T8 tb_moe_ffn_mode | 16→16 expert slice, MODE=FFN, vs golden | ±1 LSB all outputs; switch is CFG-only (no netlist delta between modes) |
| T9 tb_link_fifo (iverilog) | dual-clock Gray FIFO, 1e5 random flits, clock ratios 1:1/1:3/3:1 + jitter | zero lost/duplicated/torn flits; never-full at decode-cadence rates; KV-before-Q ordering asserted |
| T10 tb_attention_e2e_c2 | 8 tokens end to end: KV_APPEND flits → write → qK → WTA/softmax → A·V → combine → O_PARTIAL → fp32 divide on golden rail, vs golden | codes ±1 LSB (same discipline as CONTRACT tb_attention_e2e) |

Every SPICE tb integrates supply current per phase and reports pJ per op
per block (METRICS mandate).

---

## 10. Open risks, ranked

1. **WTA consistency + headroom (R1).** The whole precision story rests on
   one m̂ node feeding both B4 and B5; any layout/buffering that forks it
   converts ±5 mV offset into ~14% exp error (beta 27.31 /V [measured]).
   The nU_T·ln N overestimate also eats up to 77 mV of a 120 mV window —
   the score-mapping headroom reservation must be enforced by the
   compiler, not hoped for. Falsifiers: T2, T4.
2. **Translinear beta(T) (R2).** Measured −18.1% beta drift 27→85 C and
   fixed-bias I_b 0.58→2.2 uA [measured, STATUS A3]. PTAT-scaled bias is
   the noted production fix, but the *residual* after PTAT on this bank
   is unmeasured; paper falsifier allows ≤1 guard bit over 60 C. T3.
3. **Analog combine-tree error accumulation (R3).** Cascade law: relative
   error compounds as sqrt(K) crossings [paper, sec_formats]. Budgeted at
   2 analog levels ≈ 2%; if T5 fails and G must shrink, the digital tree
   widens → more conversions per query (energy grows toward the
   per-bank-conversion worst case). T4, T5.
4. **Retention vs session length (R4).** tau 27 ms [measured] vs law
   demand 16·T_res [paper]: refresh-from-shadow is load-bearing, its duty
   (2.3% [projected]) collides with read traffic on shared column/wsel
   resources, and a missed refresh silently degrades stored bits rather
   than failing loudly. OS BEOL cell is the escape but is off-PDK. T6.
5. **CAM prefilter (R5, phase 2).** 2b discharge-race recall is unverified
   and the accuracy story assumes filter-in-the-loop fine-tuning [paper].
   Nothing in phase 1 may depend on it.

Secondary note: d_h = 128 needs 16-way sub-bank interleave under the
10 uA class-A column budget [measured constraint, STATUS A3] — a schedule
cost, or a class-AB integrator upgrade, at target scale.
