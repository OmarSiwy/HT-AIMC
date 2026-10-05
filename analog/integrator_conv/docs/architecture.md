# integrator_conv — column converter

One per tile column (17 in `analogioc`). Integrates the column charge on C_int, then
converts it: an event-rate coarse loop (reference-charge packets of 16·D code units, one
per threshold crossing, early termination on the first no-cross) followed by a 4b
resampling SAR on the residue. Migrated from AnalogIOC `components/integrator_conv`
(subckt `int_conv`) to the macro contract `analog/analogioc/docs/INTERFACE.md` §5:
the converter keeps every analog element and exports raw comparator outputs; the XSPICE
decision state (sign latch, done latch, fire flop, SAR keep flops) is gone (D3). The sign
latch, both handshakes and every strobe live in `conv_seq` (async_ctrl deck), the counting
in the RTL (`event_ctrl`, `sar_ctrl`).

## Interface

```
.subckt integrator_conv vg out rst phi1 phi1e phi2 run fire sign sgd clk_c c1p c1n
+ acq clk_f b3 b2 b1 b0 c2p c2n awake thr_p thr_n sar_p sar_n vcm vb_nc vb_pc vb_tail
+ vdd_ota vdd_cmp vdd_pkt vdd vss
```

Port meanings: INTERFACE.md §5 (this list is checked against it line by line).
Polarities: `c1p` falls when the filtered `out` is above SA1's vinn; `c2p` falls when the
CDAC top `ct` is above vcm; both rails high in precharge. `fire·sign` lowers `out`
(driver `inn`), `fire·!sign` raises it.

Driven by `conv_seq` (one per column, `analog/async_ctrl`):

```
.subckt conv_seq rst_n sgo phi1 phi2 coarse_en cb_ack cmp_req ota_en pkt_d0 pkt_d1 pkt_d2
+ c1p c1n c2p c2n sdone col_sign cb_req cb_cross cmp_ack cmp_result busy
+ run fire sign sgd clk_c acq clk_f awake vdd vss
```

Supplies: `vdd_ota` OTA, `vdd_cmp` both StrongARMs, `vdd_pkt` packet driver, `vdd` logic,
switches and reference muxes. Bias `vb_nc/vb_pc/vb_tail` comes from outside (shared by the
17 OTAs; testbenches use `ota_bench.bias_network`, the replica bias of the `ota` block).

## Specs

| Metric | Min | Typ | Max | Unit | Testbench |
|--------|-----|-----|-----|------|-----------|
| \|code − golden.eventrate_convert\|, mac ∈ {0, 15, 16, −50, 165}, D = 1, tt 27 °C | | | 1 | LSB | `tb_integrator_conv` (A1) |
| same, every corner × −40/27/125 °C (ideal nominal rails) | | | CODE_TOL = 8 | LSB | `tb_integrator_conv` (corners) |
| coarse decisions per conversion | count+1 | | count+1 | — | `tb_integrator_conv` (A1) |
| E(code 0) / E(165) | | | 0.30 | — | `tb_integrator_conv` (A1) |
| E_conv vs \|code\|, ≥ 7 points | non-decreasing (5 % slack) | | | — | `tb_eventrate` (A2) |
| E(code 0) / mean | | | 0.30 | — | `tb_eventrate` (A2) |
| offset-corrected code (code(50) − code(0) − 50), Monte Carlo | | | CODE_TOL | LSB | `tb_integrator_conv_mc` |
| raw offset code(0), Monte Carlo | | reported | | LSB | `tb_integrator_conv_mc` |

E = vdd_cmp + vdd_pkt energy (AnalogIOC's accounting) from `sgo` to the last `cmp_ack`
fall. The rails are ideal sources at their nominal values (INTERFACE.md §2: thr
vcm ± 15.5·D·u_cal, sar vcm ± 16·D·u_cal·trim) through real `rstring_ladder`s.

## Sizing

`netlist/integrator_conv.py`; OTA and StrongARM size themselves (`ota`, `strongarm`).

| Element | Rule | Value (sky130) [AnalogIOC] |
|---------|------|-------|
| C_int | `specs.c_int()` | 200 fF [200 fF] |
| packet cap | `specs.c_pkt(D=1)` = 16·C_u·k_cal | 2.377 fF [same] |
| packet bank TG / dummy / ballast | `weight_tile.sizes()` (identical to a signal bank) | 0.42/0.42, 0.42, 3.75 fF [0.42, 0.42, 4 fF] |
| packet phi buffers | weight_tile edge rule on one bank | min inverter [4/8 µm] |
| reset TG | R_on·C_int·(B_Y+1)·ln2 ≤ T_RST_MIN = 20 ns | 0.42/0.42 [0.42/0.42] |
| CDAC / reference / park TGs | measured mid-rail peak R_on (`rstring_ladder.tg_peak_r_on`) × CORNER_GUARD so 120 fF settles to B_Y bits in T_ACQ = 14 ns | 1.40/4.20 [1.68/3.36] |
| SA1 anti-kick R/C | `specs.kick_filter()` | 3.19 kΩ / 138 fF [same] |
| SA2 anti-kick R/C | RC_KICK on C_FILT_MIN | 7.33 kΩ / 60 fF [8 kΩ / 60 fF] |
| CDAC unit | `specs.design()["c_dac_u"]` | 7.5 fF [7.5 fF] |
| vref / vref_o reservoir | full-CDAC charge at the fine span droops ≤ V_TAP_TOL/2 | 8.2 pF [5 pF] |
| logic | async_ctrl `Logic` gates | min inverter / nand2 / nor2 |

## Results

Pre-layout, `DUT=sch`, tt 27 °C. ESPice is the backend (main 1b2b91e); ngspice numbers
are from before the switch, same decks.

| Testbench | ESPice | ngspice | AnalogIOC origin |
|-----------|--------|---------|------------------|
| `tb_integrator_conv` (A1) | **PASS**: mac 0/15/16/−50/165 → −1/15/16/−51/127, worst 1; decisions 1/1/2/4/11 = golden n_eval; E(0)/E(165) = 1.43/10.48 pJ = 0.14 | 0/15/16/−50 → −1/15/15/−51 (165 not run); E within 1.2 % of ESPice | 0/15/16/−51/127, worst 1; E(0)/E(165) = 0.48/4.83 = 0.10 |
| `tb_eventrate` (A2) | **FAIL**: 7 points, monotone (PASS); E(code 0)/mean = 1.43/3.87 = **0.37** (bar 0.30) | not run | 0.27 |
| E_conv vs \|code\| | 0: 1.43 (0.50 + 0.94) · 15: 1.45 · 16: 2.36 · 31 (mac 32): 2.33 · 51: 4.01 · 79 (mac 80): 5.03 · 127: 10.48 pJ | | 0.48 / 0.47 / 0.91 / 1.35 / 1.79 / 2.65 / 4.83 pJ |
| conversion time from sgo | 724 ns (code 0) … 2224 ns (165) | 734 ns (code 0) | fixed schedule |
| `tb_integrator_conv_mc` | not run (written; ESPice runs were stopped) | not run | — |
| corners | not run | not run | — |
| `DUT=va` | model lints (VerA); not simulated on ESPice | — | — |

Deviations from the origin:

1. **E(code 0)/mean = 0.37 > 0.30 (A2 fails).** The comparators set the floor: the migrated
   `strongarm` (MC-sized input pair 21.8/0.60 µm for a 10 mV 3σ offset) costs **0.29 pJ
   per strobe** at any clock edge rate (measured on ESPice at 0.1/1/3.3 ns edges); the
   origin's was ≈ 0.07 pJ (its 0.27 pJ fine phase over 4 strobes). Fine phase 0.94 pJ
   (4 SA2 strobes) vs 0.27; code-0 coarse floor 0.50 pJ (sign + one no-cross) vs 0.20;
   0.90 pJ per crossing vs 0.56 (one SA1 strobe + the packet + idle packet chop during the
   slower handshake cadence). Early termination itself works (E(0)/E(165) = 0.14). Closing
   the bar needs a lower-energy comparator (a smaller pair, with offset removed by the
   zero-point), which is a strongarm sizing decision, not made here.
2. **Codes at exact multiples of 16 read −1** (mac 32 → 31, 80 → 79 on ESPice, 16 → 15 on
   ngspice): the last crossing sits 0.5 unit (0.67 mV) above thr; the SAR then saturates at
   15. Within ±1 (A1); the origin read 16 and 32 exactly. mac 0 reads −1 (origin 0).
3. **Kick symmetry** (topology change, see `netlist/integrator_conv.py`): both comparators'
   reference inputs are replicas of their signal inputs. Against hard vcm the migrated
   strongarm kicked the floating CDAC top −48 mV (origin −3.7 mV) and every SAR trial read
   "keep" (mac 16 → 31 before the fix).
4. vref reservoir 8.2 pF (derived) vs 5 pF; SA2 filter R 7.33 kΩ (RC_KICK/C_FILT_MIN) vs 8 kΩ.
