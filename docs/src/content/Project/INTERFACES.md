# Near-tile digital rail — port contracts (A4)

Everything the analog agents (A2/A3) and the compiler (A5) target. RTL in
`rtl/`, self-checking tbs in `tb/`, `make test` / `make synth`
(run under `nix-shell -p iverilog yosys`).

## Global conventions

- Single synchronous clock `clk` (near-tile = fabric clock domain), async
  active-low reset `rst_n` (maps to sky130 `dfrtp`). All fabric-side
  interfaces are synchronous ready/valid on `clk`.
- GALS boundary: every analog-side signal is an async 4-phase (RZ) req/ack
  pair. All async inputs pass through 2FF synchronizers inside the rail.
  Data lines accompanying a req/ack (`cmp_result`, `cb_cross`, `col_sign`)
  are quasi-static: the analog must hold them stable from before the
  qualifying edge rises until after the return edge falls; they are
  synchronized with equal-depth 2FF so the sampled value is glitch-free.
- Async handshake pacing: after its side of a 4-phase cycle completes, the
  analog must wait >= 2 `clk` periods before issuing the next req (the
  synchronizers add 2-cycle latency; testbenches model this).
- All "signed" buses are two's complement.

## Datapath (per differential column pair)

### nibble_combine (combinational)
| port | dir | width | meaning |
|---|---|---|---|
| lsb_code | in | signed 8 | column ADC code, x1 (t_q) nibble pass |
| msb_code | in | signed 8 | column ADC code, x16 nibble pass |
| partial | out | signed 12 | sat12(16*msb + lsb) |

Exact when |16*msb+lsb| <= 2047 (compiler's B_y clip schedule must
guarantee this); saturates instead of wrapping otherwise.

MERGED-CONVERSION BYPASS (item S5, digital_config `merged`): when a
tensor runs the single-conversion-per-pass schedule (one 8b statistical
conversion of the full 255 t_q window at LSB D_merged, law:bout —
golden.tile_mvm_merged), nibble_combine is a PASSTHROUGH: drive
msb_code = 0 and lsb_code = code8; partial = sign-extended code8. No RTL
change needed — bypass is a wiring/config mode. Requant then uses the
`merged.requant` scale set (unit D_merged instead of D). tile_fsm runs
one INTEGRATE->COARSE->FINE sequence per pass instead of two.

### slice_combine (combinational)
| port | dir | width | meaning |
|---|---|---|---|
| p_lo | in | signed 12 | nibble-combined partial, weight bits [1:0] |
| p_hi | in | signed 12 | nibble-combined partial, weight bits [3:2] (signed slice) |
| y | out | signed 14 | sat14(4*p_hi + p_lo) |

### bacc_accum (clocked, parameter W, instantiated W=20)
b_acc = 8 + 7 + s(S-1) + ceil(log2 T) = 20 for s=2, S=2, T<=8.

| port | dir | width | meaning |
|---|---|---|---|
| clear | in | 1 | sync clear, restart accumulation (wins over d_valid) |
| d | in | signed 14 | slice-combined partial |
| d_valid | in | 1 | accumulate d this cycle |
| tile_cnt | in | 4 | partials per output, 1..15 (exactness guaranteed T<=8) |
| acc | out | signed W | running/final sum |
| done | out | 1 | level: tile_cnt partials absorbed; further d_valid ignored until clear |

Adds saturate at +-2^(W-1) (unreachable in-spec at W=20).

### abft_check (combinational, parameter W=20)
| port | dir | width | meaning |
|---|---|---|---|
| y_flat | in | 16*W | 16 signed column sums, y_i = y_flat[i*W +: W] |
| y_chk | in | signed W | checksum-column sum |
| budget | in | 16 (unsigned) | residual budget, acc LSBs |
| residual | out | signed W+5 | sum_i(y_i) - y_chk, exact |
| flag | out | 1 | \|residual\| > budget |

Random-sign checksum conventions are absorbed when the compiler programs
the checksum column; the rail computes a plain sum. Sample when all
accumulators' `done` are high.

### requant (combinational, per channel)
q = sat8( ((y*scale + round) >>> shift) + offset ), round = shift?2^(shift-1):0
(round-half-up), offset applied AFTER the shift, sat8 to [-128,127].

| port | dir | width | meaning |
|---|---|---|---|
| y | in | signed 20 | accumulated column sum |
| scale | in | 8 (unsigned) | per-channel multiplier |
| shift | in | 5 | arithmetic right shift, 0..24 meaningful |
| offset | in | signed 8 | output zero-point |
| q | out | signed 8 | INT8 activation |

## Conversion controllers (per column converter)

### sar_ctrl (clocked)
4b SAR on the residue. 4-phase toward the StrongARM comparator:
`dac_code` (trial) is stable >= 1 clk before `cmp_req` rises; comparator
answers `cmp_result` = 1 iff residue >= DAC(trial), holds it stable, then
raises `cmp_ack`; controller drops `cmp_req`; comparator drops `cmp_ack`.
MSB-first, 4 trials; `done` is a level (cleared on next `start`), `code`
holds the result, `dac_code` parks on the final code.

| port | dir | width |
|---|---|---|
| start | in | 1 (pulse) |
| busy / done | out | 1 |
| code | out | 4 |
| cmp_req | out | 1 |
| cmp_ack / cmp_result | in | 1 (async / quasi-static) |
| dac_code | out | 4 |

### event_ctrl (clocked)
Event-rate coarse loop. The ANALOG initiates: one decision per t_q window,
presented as 4-phase `cb_req` with `cb_cross` quasi-static.
- cb_cross=1: count++, `cb_ack` rising edge = fire one reference packet.
- cb_cross=0: EARLY TERMINATION - `done`, no packet (ack still completes).
- count saturates at 15; the 15th crossing also terminates (range exhausted).
`count` binary; `count_gray` = registered Gray copy (successive values
differ in exactly one bit) for sampling from an unrelated fabric clock.

| port | dir | width |
|---|---|---|
| start | in | 1 (pulse) |
| done | out | 1 (level) |
| count / count_gray | out | 4 |
| cb_req / cb_cross | in | 1 (async / quasi-static) |
| cb_ack | out | 1 |

### sign_exit (combinational)
exit = force_zero = relu_en & sign_neg & sign_valid.

## tile_fsm (top controller; instantiates event_ctrl, sar_ctrl, sign_exit)

Phase sequence: IDLE -> INTEGRATE -> (sign early exit?) -> COARSE -> FINE
-> READOUT. One instance per column converter; a tile replicates it 17x
(16 data columns + the ABFT checksum column, which always runs with
`relu_en` = 0) with a common fabric start. `analogioc_top` joins the 17
`integ_req` into the macro's single `integ_req` with a registered C-element
and fans `integ_ack` back out (analog/analogioc/docs/INTERFACE.md §8).

Fabric side (sync, `clk`):
| port | dir | width | meaning |
|---|---|---|---|
| start_valid / start_ready | in/out | 1 | ready/valid; `relu_en` sampled at accept |
| relu_en | in | 1 | enable sign-early-exit for this conversion |
| col_code | out | signed 8 | see assembly below; quasi-static while col_valid |
| col_valid / col_ready | out/in | 1 | ready/valid readout |
| col_exit | out | 1 | ReLU sign-early-exit taken in this conversion (`col_code` forced 0). Registered: set in DECIDE, cleared on the next start accept, valid with `col_valid`. `analogioc_top` uses the HI window's `col_exit` to force that column's LO code to 0. |
| evt_count_gray | out | 4 | LIVE Gray event count; a foreign clock domain may 2FF-sample it directly (Gray counter for the event-count crossing). Caveats: (1) holds the previous conversion's value during an early-exit conversion; (2) it restarts to 0 at conversion start, a multi-bit change - the single-bit-change guarantee holds only WITHIN a conversion, so qualify samples with conversion phase (e.g. between start accept and col_valid) or tolerate one torn sample at start. |

Analog side (async):
| port | dir | meaning |
|---|---|---|
| integ_req (out) / integ_ack (in) | 4-phase | integrate phase: req = apply PWM + integrate; ack = window complete |
| col_sign (in) | quasi-static | 1 = column negative (integrator polarity / MSB decision); stable from before integ_ack rises until end of conversion |
| coarse_en (out) | level | analog may issue cb_req decisions ONLY while high. Never rises on an early-exit conversion (this is what makes early exit safe: no orphaned req). Sample it at the start of each decision window. |
| cb_req / cb_cross (in), cb_ack (out) | 4-phase | via event_ctrl |
| cmp_req (out), cmp_ack / cmp_result (in), dac_code (out) | 4-phase | via sar_ctrl |
| ota_en (out) | level | item S4 OTA bias gate: high through INTEGRATE/DECIDE, low during COARSE once event_ctrl's early-termination done latches (the analog wrapper parks the column OTA tail and pfet cascode gate; residue held on the floating integrator node, < 0.3 fine LSB/us droop measured), then HIGH FOR THE WHOLE FINE PHASE (RTL: `state == S_FINE`; the old RTL dropped it there, fixed per analog/analogioc/docs/INTERFACE.md D9). Fine-phase park is FORBIDDEN (tried twice, reverted): a parked OTA between SAR trials leaves the residue floating under the CDAC acq TGs and their injection walks it ~1 fine LSB/trial (tb_ic_park measured). |

Column code assembly (coarse LSB = 16 fine LSBs; SAR carry realizes the
1-bit redundancy overlap):
```
mag      = 16*evt_count + sar_code            (0..255)
col_code = clamp(col_sign ? -mag : +mag, -127..+127)
         = 0 on ReLU early exit
```
Compiler note: full-scale is +-127; schedule B_y so nominal conversions
keep evt_count <= 7 (mag <= 127) - the clamp is overrange protection.

## rail_top
Synthesis/integration wrapper: 1 column datapath slice (2x nibble_combine,
slice_combine, bacc_accum W=20, requant) + tile-level abft_check + one
tile_fsm. `make synth` maps it to sky130_fd_sc_hd
(sky130_fd_sc_hd__tt_025C_1v80.lib) and reports per-module `stat`.

## Timing/scaling notes
- t_q = 10 ns in simulation (real target 200 ps): all handshakes are
  delay-insensitive 4-phase, so only the ">= 2 clk between reqs" pacing
  rule scales with the fabric clock, not with t_q.
- Latencies (clk cycles): SAR bit ~ 5 + comparator delay; coarse event
  ~ 4 + analog decision; sign-early-exit conversion ~ 6 total after
  integ_ack (no analog conversion activity at all).
