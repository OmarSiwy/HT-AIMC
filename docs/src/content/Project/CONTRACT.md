# AnalogIOC-mini — Implementation Contract (all agents read this first)

Goal: end-to-end **inference AND training** transformer hardware on **sky130**
(sky130A default via `library/pdks`; sky130B allowed where its devices help),
netlists in the **MVM template idiom** (python generators, see
`scripts/library/pdk.py`, `cap_array.py`, MVM's `components/` and
`testbenches/` for style), sized with **gm/ID from real ngspice sweeps**,
functionally simulated with the **flake toolchain (ngspice 43 pinned; Xyce/
VACASK available)**. Assume ideal layout parasitics and infinite silicon area.
PDKs at `~/.volare/sky130A` and `~/.volare/sky130B`.

Run everything through `nix develop` in this directory (flake copied from MVM).
`PYTHONPATH=scripts` for all python. Every block ships with a passing
testbench; every testbench prints `PASS`/`FAIL` and asserts numerically.

## Architecture (AnalogIOC-mini, SPICE-tractable dims)

Paper reference: `/home/omare/Documents/Projects/OmarSiwy.github.io/Notes/Circuit Design/Analog Design/Analog Compute/paper/` (sec_arch, sec_circuits).

- **Weight tile**: 16 rows (+1 random-sign checksum row) x 16 differential
  column pairs (+1 checksum column). Charge-domain capacitive crossbar per MVM
  `cap_array` idiom: weight = 4-bit binary-weighted cap code, differential
  (W = C+ - C-). VDD = 1.8 V.
- **Inputs**: INT8 activations as two 4-bit nibbles of binary-amplitude PWM,
  duration ratio 1:16, **t_q = 10 ns for simulation** (real target 200 ps —
  document scaling), driven by the timebase below.
- **Column readout (the converged converter)**: per differential pair —
  virtual-ground integrator (OTA, gm/ID-sized) with charge-balancing
  **event-rate coarse loop** (4b: reference-charge packets fire on threshold
  crossings, EARLY TERMINATION on first no-cross) + **4b SAR fine** on the
  residue (cap-DAC per `cap_array`), 1 redundancy bit. StrongARM comparator
  (MVM `strongarm.py` as starting point). Output: 8b code + `done` event.
- **Threshold/references**: non-uniform-capable R-string ladder + tap mux
  (monotonic by construction). Write DACs for gain cells: 4b R-string + mux.
- **Gain-cell KV array**: 8x8 two-transistor gain cells (nfet write switch,
  storage MOM cap ~20-50 fF, nfet read device), per-token column write,
  non-destructive PWM read. One K-array + one V-array, d_head = 8.
- **LoRA sidecar (training target)**: rank-1 — gain-cell vectors A (16) and
  B (16); y += B*(A·x) summed IN CHARGE onto the tile's column integrators.
  Training = outer-product update: write A,B increments from digital.
- **Translinear softmax**: 8-input subthreshold shared-source bank + tail
  current source; outputs = normalized currents. Verify sum(I_i) = I_b (KCL
  checksum) and softmax accuracy vs golden at 3 temperatures (27/55/85 C).
- **Timebase**: delay-chain/replica-based self-timed sequencer in the MVM
  `async_ctrl` idiom generating t_q grid + non-overlapping integrate/convert
  phases. No global clock in the analog domain (GALS).
- **Digital rail (Verilog, synthesizable)**: nibble shift-add (x16), slice
  combine, b_acc accumulator, ABFT compare (|sum(y_i)-y_chk| < budget flag),
  sign-early-exit control, SAR/counter logic, per-channel affine requant
  (INT8), controller FSM. Synthesize with yosys to sky130_fd_sc_hd; simulate
  with iverilog (add to dev shell via nix-shell -p if flake lacks them).
- **Compiler (python)**: tiny transformer (1 attention head d=8 + FFN 16->16,
  weights supplied as numpy) -> per-channel smoothing -> INT4 weights ->
  differential cap codes / programming vectors; INT8 activations -> PWM
  schedules; per-tensor B_y schedule; emits (a) SPICE stimuli + param files
  for testbenches, (b) golden expected outputs, (c) digital-rail config.
- **Golden model (python/numpy)**: bit-true reference of the entire path
  (quantize, clip +-4sigma, PWM, ideal MAC, event-rate code, shift-add,
  checksum). Single source of truth for every testbench's expected values.

## End-to-end acceptance tests (the deliverable)

1. `tb_tile_mvm`: random INT8 x INT4 MVMs on the 16x16 tile vs golden —
   all output codes within +-1 LSB. Checksum residual within budget.
2. `tb_attention_e2e`: 8 tokens streamed: per-token KV write -> qK^T ->
   softmax (analog) -> A·V -> codes vs golden.
3. `tb_ffn_e2e`: FFN layer (16->16, ReLU, sign-early-exit active) vs golden.
4. `tb_training_step`: one LoRA SGD step — compute error on toy target,
   outer-product update written to sidecar gain cells, re-run inference,
   assert loss decreased and matches golden update within tolerance.
5. `tb_audit`: inject a stuck/drifted cap in the tile — ABFT flag raises;
   uninjected run stays clean.
6. `tb_eventrate`: E_conv vs |code| histogram — assert monotone increase and
   code-0 energy < 30% of mean (early-termination working).

## Conventions

- One component = one directory `scripts/components/<name>/<name>.py`
  exposing `generate(...) -> subcircuit netlist string` (match MVM style you
  find in its `scripts/components/`).
- Testbenches in `scripts/testbenches/tb_<name>.py`, self-running via
  `if __name__ == "__main__"`, ngspice batch mode, numeric asserts, print
  PASS/FAIL. Use ngspice `wrdata` + numpy parsing (see MVM tb style).
- Sizing: `scripts/sizing/` — FIRST generate real gm/ID lookup tables
  (ngspice DC sweeps of sky130_fd_pr__nfet_01v8 / pfet_01v8 across L in
  {0.15,0.3,0.5,1.0}u: gm/ID, ID/W, gm/gds, ft proxy vs VGS) into
  `sizing/tables/*.csv`, then size each block by the vault recipe
  (gm = wu*CL -> ID = gm/(gm/ID) -> W = ID/JD). Document every choice in
  `sizing/SIZING.md` with the (gm/ID, L) coordinate per device.
- Digital: `scripts/digital/rtl/*.v`, `scripts/digital/tb/*.v`,
  `scripts/digital/synth.ys` (yosys), `Makefile`.
- Compiler+golden: `scripts/compiler/`, `scripts/golden/`.
- No file outside your assigned directories except appending a status line to
  `STATUS.md`. Read but never edit other agents' dirs.
- Ownership: A1=library+sizing, A2=components(tile path)+their tbs,
  A3=components(attention/sidecar/softmax)+their tbs, A4=digital/,
  A5=scripts/compiler/+scripts/golden/+e2e tbs.

## Metrics mandate (A6 + all)

The functional simulation is a PERFORMANCE instrument, not just a checker:
- Analog energy: every SPICE tb integrates supply current (V*I) per phase;
  report pJ per MVM per block (tile, converter coarse/fine, softmax, KV
  write/read, sidecar) and the E_conv-vs-|code| histogram.
- Digital energy: yosys-synthesized netlist cell counts x liberty
  cap/activity estimate (document method); report pJ/op per rail block.
- Timing: measured per-phase latencies from SPICE (PWM window, conversion
  done-time distribution, softmax settle) + digital cycle counts.
- scripts/metrics/report.py assembles METRICS.md: tokens/s and tokens/J for
  the mini chip (1 attention head + 1 FFN layer, 8-token stream, measured),
  PLUS law-scaled projection to full AnalogIOC (7B, per the paper's eval
  section formulas — cite which law scales what; clearly label measured vs
  projected). Include fJ/MAC, TOPS/W-equivalent, utilization, and the
  audit/overhead fractions.
- Synthesizability bar: digital rail must pass yosys -> sky130_fd_sc_hd with
  zero inferred latches and a clean `stat`; analog blocks are complete
  transistor-level sky130 netlists with all devices from the PDK (no ideal
  elements in the signal path; ideal sources only for supplies/stimuli).
  Top-level: scripts/top/analogioc_top.py assembles the full analog chip
  netlist; digital runs as the verified-equivalent golden rail in the
  mixed-sim harness (RTL equivalence proven by A4 tests).

## Real-model mandate (supersedes "tiny random transformer")

The e2e path runs REAL pretrained weights and real token streams:
- Source: Ollama GGUF blob (being pulled: smollm2:135m-class, q8_0
  preferred; blobs at ~/.ollama/models/blobs, manifest maps names).
  A5 writes a minimal numpy GGUF reader (header + tensor table + Q8_0/F32
  dequant; Q4_0 fallback if needed). No external deps beyond numpy.
- Compiler tiles the REAL layer-0 attention (one real head slice) + FFN
  matrices onto 16x16 differential tiles: exact tile-pass counts per token
  are computed (not estimated). Golden runs the full real-weight forward
  bit-true in numpy on a real tokenized prompt (greedy longest-match over
  the GGUF-embedded vocab is acceptable; document fidelity).
- SPICE validates a representative sample of tile passes drawn from the
  real layer with real activations (>=8 passes incl. worst-case code and
  a sparse one); silicon codes must match golden within +-1 LSB.
- METRICS.md computes tok/s and tok/J from MEASURED per-pass timing/energy
  x EXACT pass counts/token for the real model at mini-chip scale (silicon
  reuse: one physical tile time-multiplexed), plus the law-scaled 7B
  projection. Label measured vs counted vs projected explicitly.
