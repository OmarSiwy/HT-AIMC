# async_ctrl — self-timed sequencer + t_q grid

Schematic, drawn by cktImg from `netlist/async_ctrl.spice` (`make import NETLIST=async_ctrl`): [async_ctrl.svg](async_ctrl.svg)

Leaf block. The analog domain has no global clock (GALS, `analog/docs/architecture.md`):
`async_ctrl` turns one GO edge into the column phases, and `tq_chain` — defined in the
same deck, instantiated beside it by `analogioc` — lays the t_q PWM grid. `muller_c` is in
the deck for parity with AnalogIOC's generator; nothing instantiates it.

## Interface

`.subckt async_ctrl go adc_done xbar_rst adc_go latch_out done vdd vss`

| Port | Dir | Meaning |
|------|-----|---------|
| go | in | rising edge starts a conversion |
| adc_done | in | converter finished (from integrator_conv) |
| xbar_rst | out | crossbar reset pulse, high for the reset-chain delay after GO |
| adc_go | out | rises after reset + settle chains: start conversion |
| latch_out, done | out | adc_done buffered (2 and 4 inverters) |
| vdd, vss | supply | `pdk_specs.vdd`, 0 |

`.subckt tq_chain in tap1 tap2 tap3 tap4 vdd vss` — tap k rises ~k·t_q after `in`
(`specs.design()["tq_n_taps"]` taps, 2 loaded inverters each).

Structure (AnalogIOC's): go → 2-inverter buffer → `rst_delay` (n_rst_stages loaded
inverters) → 2 inverters → `settle_delay` (n_settle_stages) → 2 inverters → 2 inverters
→ adc_go. `xbar_rst = go_buf · NOT(rst_delayed)` (nand2 + inverter).

## Specs

Supply `pdk_specs.vdd`. Sequencing stimulus: GO step at 10 ns; AnalogIOC's ADC model
(adc_go → 5 kΩ / 1.6 pF → 2 min inverters → adc_done). t_q target `specs.TQ_SIM`
(simulation grid; the silicon target 200 ps scales the loads 50× down).

| Metric | Min | Typ | Max | Unit | Testbench |
|--------|-----|-----|-----|------|-----------|
| All edges present, order GO ≤ xbar_rst↑ ≤ xbar_rst↓ ≤ adc_go↑ ≤ done↑ | ordered | | | — | `tb_async_ctrl` |
| Reset pulse width (xbar_rst) | 1 | 21.5 | 50 | ns | `tb_async_ctrl` |
| Settle phase (xbar_rst↓ → adc_go↑) | 2 | 48 | | ns | `tb_async_ctrl` |
| done high at end of run (200 ns) | high | | | — | `tb_async_ctrl` |
| t_q stage 1, tt / 27 °C | 0.5·TQ_SIM | 7.1 | 1.3·TQ_SIM | ns | `tb_async_ctrl` |
| t_q inner stages, tt / 27 °C | 0.7·TQ_SIM | 9.55 | 1.3·TQ_SIM | ns | `tb_async_ctrl` |
| t_q inner-stage spread, every corner | | 0.0 | 10 | % | `tb_async_ctrl` |
| t_q inner-stage spread, Monte Carlo (mismatch), every sample | | | 10 | % | `tb_async_ctrl_mc` |

The absolute t_q window is a typical-corner spec (AnalogIOC: "10 ns ±30% at TT"); an open
delay line cannot hold it over PVT, and the PWM grid is ratiometric to t_q, so corners
check spread and report the absolute value.

## Sizing

Derived in `netlist/async_ctrl.py`; every device is rail-to-rail logic (no gm/ID
coordinate). AnalogIOC hand values in brackets.

| Device | Rule | W / L (µm) |
|--------|------|------------|
| inverter N | min W, min L | 0.42 / 0.15 [0.42 / 0.15] |
| inverter P | Wn·√(J_D,n/J_D,p) at \|VGS\| = VDD — min-average-delay ratio | 0.70 / 0.15 [0.84 / 0.15] |
| nand2 N (2-stack) | 2 × inverter N: inverter-equal fall | 0.84 / 0.15 [0.84 / 0.15] |
| nand2 P (parallel) | = inverter P | 0.70 / 0.15 [0.84 / 0.15] |
| reset/settle load | `specs.design()["c_load_delay"]` per inverter, MIM | 220 fF [220 fF] |
| tq_chain inverter | TQ_M = 2 × inverter W: matching (Pelgrom σ ∝ 1/√(WL)); at 1× MC worst spread was 10.15% | 0.84, 1.40 / 0.15 [0.42, 0.84 / 0.15] |
| tq_chain load | TQ_SIM = K_RAMP·C·VDD/2·(1/I_n + 1/I_p), I = J_D(VDD)·W | 971 fF [550 fF] |
| muller series N / P | 2 × inverter N / P | 0.84, 1.40 / 0.15 [0.5, 1.0 / 0.15] |
| muller keepers | min W, 4 × min L (≈¼ of the stack) | 0.42 / 0.60 [0.25/0.15 N, 0.5/0.15 P] |
| muller feedback inverter | = inverter | 0.42, 0.70 / 0.15 [0.15, 0.25 / 0.30] |

K_RAMP = 1.65 is the one calibration knob: inner stages see the previous stage's slow
ramp, not a step (AnalogIOC measured 10.15 ns against the 6.15 ns step model). The
testbench prints the measured ps/fF per inverter for recalibration after a PDK swap.

## Results

| Rung | Result | Notes |
|------|--------|-------|
| pre-layout (`DUT=sch`, tt 27 C) | PASS | rst 21.47 ns, settle 48.10 ns, GO→done 78.65 ns; t_q 7.10 / 9.55 / 9.55 / 9.55 ns, spread 0.00% |
| golden model (`DUT=va`) | PASS | rst 21.55 ns, settle 48.30 ns, GO→done 76.25 ns; t_q 7.10 / 9.55 / 9.55 / 9.60 ns, spread 0.52% |
| layout (Philis) | | |
| post-layout (`DUT=pex`) | | |
| corners (`DUT=sch`, tt ss ff sf fs × −40 27 125 °C) | PASS 15/15 | slowest ss/125: rst 31.67 ns, settle 72.30 ns, GO→done 114.5 ns, t_q 13.03 ns (spread 0.38%); fastest ff/−40: rst 15.74 ns, settle 34.60 ns, t_q 7.28 ns (0.69%) |
| Monte Carlo (`tt_mm`, 30 seeds) | PASS | t_q σ 177 ps (1.86%), spread worst 6.81%, mean 2.99% (at TQ_M = 1: σ 3.14%, worst 10.15% FAIL) |

AnalogIOC reference (its hand sizing): reset 19.7 ns, settle 43.1 ns, t_q 7.7 / 10.15 ns
inner, spread 0.00%.

## Macro wrapper cells: `conv_seq` and `tile_seq` (phase 1a)

The req/ack ↔ phase-clock translator of the macro (`analog/analogioc/docs/INTERFACE.md`
D2, §6) is emitted by this generator next to `async_ctrl`/`tq_chain`/`muller_c`. Static
CMOS from this deck's cells only: the inverter / nand2 sizing above, nor2 (p stack
doubled), NOR set-reset latches (reset priority), master-slave D flops built from NOR2
latches with non-overlapping enables, `muller_c`, and loaded-gate delay elements. The
default deck carries them; `--no-caps` (the Philis deck) and `tq_chain` decks are
unchanged, and `async_ctrl` stays the last `.subckt`. `async_ctrl` / `tq_chain` devices
are unchanged (tb_async_ctrl numbers identical).

```
.subckt conv_seq rst_n sgo phi1 phi2 coarse_en cb_ack cmp_req ota_en pkt_d0 pkt_d1 pkt_d2
+ c1p c1n c2p c2n sdone col_sign cb_req cb_cross cmp_ack cmp_result busy
+ run fire sign sgd clk_c acq clk_f awake vdd vss
.subckt tile_seq seq_rst_n integ_req integ_ack win_hi lora_en x_mag0..x_mag63 x_neg0..x_neg15
+ sdone0..sdone16 busy0..busy16 sgo rst phi1 phi1e phi2 tphi1 tphi1e tphi2
+ xin_p_r0 xin_n_r0 .. xin_p_r15 xin_n_r15 xrd_en0..xrd_en15 ramp_en vdd vss
```

Wiring in `analogioc`: every `conv_seq` takes `rst_n = seq_rst_n`, `sgo`, `phi1`, `phi2`
from `tile_seq` and the column's rail pins; its `run fire sign sgd clk_c acq clk_f awake`
go to the column's `integrator_conv`, whose `c1p c1n c2p c2n` come back; `sdone_j` and
`busy_j` (= coarse_en_j | cmp_req_j) go to `tile_seq`; `col_sign` etc. are macro pins.
`tile_seq` drives `integrator_conv.rst` (and the sidecar `lrst`, the same net),
`phi1/phi1e/phi2` (converter chop, all 17 columns), `tphi1/tphi1e/tphi2` and
`xin_p_r<i>/xin_n_r<i>` (weight_tile), `xrd_en<i>` (the xrd TG drivers: xrd_i = vss while
high, else vcm) and `ramp_en`. `x_mag`/`x_neg`/`win_hi` are not latched: the contract holds
them until integ_ack rises and nothing reads them later. `pkt_d` goes to every conv_seq.

### conv_seq

| Function | Implementation |
|---|---|
| decision decode | dual rail: `p = !c?p & c?n`, `n = !c?n & c?p`, completion = p \| n. A rail pair falling together (the StrongARM common-mode dip before regeneration) is not a decision. |
| SA1 strobe | `arm` = request seen while phi1 low (dropped with the request); `clk_c` rises with phi1 while armed, falls once disarmed and phi1 is low. So it rises at a phi1 rise (chop offset) and is held until completion. |
| sign (I6) | sign := p at the strobe with sgd = 0; sgd when the strobe is low and SA1 precharged again; col_sign = sgd & !sign; sdone = sgd |
| coarse (C0-C5) | `ready` = T_PACE after both the last cb_ack fall and the sign strobe; strobe request latched from ready & coarse_en & !cb_ack; cross := (cmp == sign); cb_req = T_BUNDLE after the latched, precharged decision; on cb_ack with cross: `fire` for pkt_d (0 → 1) chop cycles, counted by phi2-fall flops, edges in the gap; cb_req falls after the packet (or at once on no-cross); run set at the first strobe, cleared by a no-cross ack or by coarse_en low after pacing |
| SAR trial (F1-F5) | acq = cmp_req for T_ACQ1 (first trial since sgo) or T_ACQ; clk_f T_HOLD after acq falls, through a slew-limited driver (≥ T_FEDGE 10-90 %), held until completion and ≥ T_FHI; cmp_result := sign ? c2p : c2n; cmp_ack T_BUNDLE after the precharge, falls with cmp_req |
| awake / busy | ota_en \| acq; coarse_en \| cmp_req |

Minimum-time delay elements (`dly_*`): DLY_PAIRS nand(in, prev)+inverter pairs; a falling
input resets every pair at once (re-arms fast). Sized for t_min / T_FAST at tt (T_FAST =
0.72, the measured ff/−40 °C to tt ratio of this deck's chains), L stepped up from Lmin
until the per-gate load fits `c_load_delay`:

| Element | Contract minimum | L (µm) | C per gate |
|---|---|---|---|
| dly_pace | T_PACE = 2·T_CLK_MAX = 40 ns | 1.2 | 122 fF |
| dly_acq1 | T_ACQ1 = 2·specs.T_ACQ = 80 ns | 2.4 | 127 fF |
| dly_acq / dly_hold | 14 / 15 ns | 0.3 | 136 / 145 fF |
| dly_fhi / dly_bundle | 4 / 2 ns | 0.15 | 67 / 34 fF |
| clk_f driver | 10-90 % ≥ 2 ns | 0.15 | 369 fF |

### tile_seq

| Function | Implementation |
|---|---|
| t_q ring | `tq_chain` closed by one nand2(ring_en, tap4) sized for equal rise/fall current and one full t_q per edge; each edge of its 5 nodes is a tick, p = their parity; ring_en = integ_req \| integ_ack \| any busy |
| chop (§6.1) | `chop_gen(p)`: e(x) = p xor p_delayed(x) from one line of identical 0.2 ns cells; phi1 = e(2.4)&!e(0.8), phi1e = e(2.6)&!e(0.8), phi2 = !e(3.0) (falls at the tick = gap start), ck = e(0.8) |
| integrate (I1-I2) | async_ctrl unchanged: go = integ_req & seq_rst_n; rst = xbar_rst \| not-yet-started (I0); adc_go 2-flop synchronised to ck |
| window (I3-I4) | 8-bit synchronous counter on ck; LO 16 tile cycles of t_q, HI 8 of 16 t_q; p_tile toggles at each tile tick, tile chop = chop_gen(p_tile) gated by w2 (opens at the first tile phi1, closes at the window-end tick; parked tphi1 = tphi1e = 1, tphi2 = 0); row i envelope = (tile cycle < m_i) by a ripple-majority comparator, registered, then a latch transparent only while the tile ck = e(0.8) is high, i.e. inside the tile gap |
| settle / LoRA (I5) | counter restarts at the window end: sgo after N_SETTLE = 8 t_q, or with lora_en ramp_en from 4 to 54 t_q and sgo at 64 t_q |
| sign join (I6-I8) | sgo latched until the next xbar_rst; 17 sdone joined by a muller_c tree, + T_BUNDLE, & this-request flag → async_ctrl adc_done → done = integ_ack; integ_req low clears the flag, so integ_ack falls with integ_req while the columns keep converting |

### Results (wrapper cells)

WRAPPER_RESULTS
