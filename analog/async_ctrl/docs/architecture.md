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
