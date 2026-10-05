# analogioc — analog macro ↔ digital rail interface contract (phase 0)

Every agent building the converter, the analog top, the digital top, the behavioural
model or the co-simulation builds against this file. If it conflicts with anything else,
this file wins for the macro boundary; `docs/src/content/Project/INTERFACES.md` stays
authoritative for the digital rail modules (`tile_fsm`, `event_ctrl`, `sar_ctrl`, …), and
CONTRACT.md for the acceptance tests. Changing a port means changing
`analog/analogioc/netlist/analogioc.ports` first, in its own commit.

Machine-readable port list: [`../netlist/analogioc.ports`](../netlist/analogioc.ports).
Macro declaration for harden and simulation: `digital/analogioc/build/macros.toml`.

Simulation-grid numbers below assume `specs.TQ_SIM` = 10 ns, sky130, D = 1. "t_q" means the
macro's own t_q grid (`tq_chain`), never the fabric clock.

## 1. Decisions

| # | Decision | Why |
|---|---|---|
| D1 | Phase 0 has one chip: the IMC MVM core. The macro `analogioc` contains the 16×17 tile (16 data + ABFT checksum column), 16 pwm_driver rows (inside `weight_tile`), 17 `integrator_conv`, 4 `rstring_ladder`, the `async_ctrl` timebase and `lora_sidecar`. It has no KV cache, softmax or attention. | user scope, AGENTS.md, APPLICATION_ATTENTION.md |
| D2 | **The req/ack ↔ phase-clock wrapper lives inside the analog macro.** It is two new subcircuits, `tile_seq` (×1) and `conv_seq` (×17). Both are emitted by `analog/async_ctrl/netlist/async_ctrl.py` next to `async_ctrl`/`tq_chain`/`muller_c` and use only that deck's cells and sizing rules (min inverter, nand2/nor2, `muller_c`, loaded-inverter delay elements, `tq_chain`). `tile_seq` instantiates the existing `async_ctrl` and `tq_chain` unchanged. | see §1.1 |
| D3 | The converter's XSPICE decision state (sign latch, `done` latch, fire flop, SAR keep flops) is **removed** from `integrator_conv`. The RTL already holds that state (`event_ctrl.count`, `sar_ctrl.code`). The converter exports raw comparator outputs (§5). Only the sign latch stays analog-side, in `conv_seq`, because the converter needs the sign for the threshold, vref and packet-polarity muxes. | no duplicated state; less analog logic than the origin |
| D4 | One integrate handshake for the whole tile: the 17 `tile_fsm` instances are joined in the digital top by a registered C-element into one `integ_req`, and `integ_ack` fans back out. The coarse and fine handshakes are per column. | the PWM window is shared by all rows/columns; the coarse loops terminate per column |
| D5 | The activation enters as quasi-static nibble data (`x_mag`, `x_neg`, `win_hi`) bundled with `integ_req`. The macro makes the PWM envelopes on its own t_q grid. The rail does not drive `xin_p/n_r*`. | envelope edges must land in the 0.8 ns all-off chop gap; a 20 ns fabric clock cannot place them (and 200 ps silicon t_q even less) |
| D6 | The converter LSB D is runtime: `pkt_d[2:0]` = packet length in converter chop cycles (D=1..7; 0 means 1). The packet bank is sized once at D=1 (`specs.c_pkt(D=1)`). The reference spans for D come from the external ladder rails. | tensors on one chip use D ∈ {1,2} (`digital_config.json`); `c_pkt(D)` is linear in D |
| D7 | Weights are a **build-time parameter** of the macro: the netlist is generated per pass from `caps.spice`, and the behavioural model loads `weights.hex`. No weight-write port. | that is how every existing tile netlist works (`weight_tile.build(Cp,Cn,chk)`). Open question Q1. |
| D8 | Digital top for phases 1–4 = new non-TinyTapeout module `analogioc_top` with a wide parallel interface. The TT stub `src/analogioc.v` is deleted, because module name `analogioc` now belongs to the macro. A TT wrapper `tt_um_analogioc` comes later. | macro needs 13 analog pins + 5 supplies; open question Q3 |
| D9 | `tile_fsm.ota_en` must be HIGH for the whole FINE phase (INTERFACES.md, authoritative). The RTL currently drops it in `S_FINE`, which is the twice-reverted fine-phase park. That is a required RTL fix (§7.4). The macro still ORs `acq` into the OTA gate. | INTERFACES.md `ota_en`; origin `tb_ic_park` |

### 1.1 Why the wrapper is analog-side (D2)

Three options were considered.

- **Digital RTL wrapper: rejected.**
  1. INTERFACES.md fixes the GALS boundary: "every analog-side signal is an async 4-phase
     (RZ) req/ack pair". It also names the translator "the analog wrapper", which "parks the
     column OTA" and "ORs its own acq strobe". An RTL wrapper would move the boundary to the
     phase clocks.
  2. CONTRACT.md: "Timebase: … self-timed sequencer in the async_ctrl idiom generating t_q
     grid + non-overlapping integrate/convert phases. No global clock in the analog domain."
  3. The phase edges are sub-t_q (phi1 0.3→1.9 ns inside a 10 ns t_q; silicon t_q is 200 ps).
     LibreLane `CLOCK_PERIOD` is 20 ns, so a fabric-clocked wrapper cannot produce them.
- **New standalone block: rejected.** It needs the same cells as `async_ctrl` and would
  repeat its block overhead: a new `docs/`, `va/`, tb ladder and layout.
- **Extend async_ctrl's deck: chosen.** It adds no new analog circuit, only static CMOS
  logic and delay elements that `async_ctrl` already sizes and verifies. Its sequencer
  already has the integrate shape (GO → reset pulse → settle → start → done ⇒
  `integ_req` → `rst` → window → `integ_ack`). With D3, the analog side loses more logic
  (the XSPICE flops) than the wrapper adds.

## 2. Macro port list

`.subckt analogioc` takes the ports **in this order**. Vectors are bit-blasted LSB first.
The `.subckt` spells bit i as `name<i>` and Verilog/`.ports` spell it `name[i]`
(`macros.py` maps `<i>`↔`[i]`). The Verilog blackbox and behavioural model declare the 35
signal ports in this order with `[N-1:0]` ranges, and no supply pins. Direction is as seen
from the macro.

Digital pins are 0/1.8 V CMOS on the macro's `vdd`. The digital top drives them from
VPWR/VGND std cells. Requirement: |vdd − VPWR| ≤ 0.1 V and vss = VGND at chip level. There
are no level shifters.

| # | Port | Dir | Kind | Domain | Width | Meaning |
|---|---|---|---|---|---|---|
| 1 | `seq_rst_n` | in | digital | vdd | 1 | async active-low reset of `tile_seq`/`conv_seq` state. Tied to the top's `rst_n`. While low, all macro outputs are 0, integrators are in reset and the tile clocks are parked. |
| 2 | `integ_req` | in | digital | vdd | 1 | 4-phase req: reset integrators, apply PWM window, settle, sign-strobe (§6.2) |
| 3 | `integ_ack` | out | digital | vdd | 1 | 4-phase ack: all 17 `col_sign` valid |
| 4 | `win_hi` | in | digital | vdd | 1 | 0 = LO window (16 chop cycles of t_q), 1 = HI window (8 chop cycles of 16·t_q). Bundled with `integ_req`. |
| 5 | `x_mag` | in | digital | vdd | 64 | row i nibble magnitude = `x_mag[4i+3:4i]` (0..15 LO, 0..7 HI). Bundled with `integ_req`. |
| 6 | `x_neg` | in | digital | vdd | 16 | row i sign: 1 drives the `xin_n` rail, 0 drives `xin_p`. Bundled with `integ_req`. |
| 7 | `pkt_d` | in | digital | vdd | 3 | converter LSB D = chop cycles per coarse packet. Static for a whole pass. |
| 8 | `lora_en` | in | digital | vdd | 1 | 1 = sidecar A·x integrate + B ramp onto columns 0..15 this window. Static for the pass. |
| 9 | `col_sign` | out | digital | vdd | 17 | 1 = column negative (V_out < vcm). Valid from ≥ T_BUNDLE before `integ_ack`↑ until the next `integ_req`↑. |
| 10 | `coarse_en` | in | digital | vdd | 17 | per column: the macro may start a coarse decision only while high |
| 11 | `cb_req` | out | digital | vdd | 17 | per column 4-phase req: one coarse decision ready |
| 12 | `cb_cross` | out | digital | vdd | 17 | decision, quasi-static: valid ≥ T_BUNDLE before `cb_req`↑ until `cb_ack`↓ |
| 13 | `cb_ack` | in | digital | vdd | 17 | ack; rising edge with `cb_cross`=1 = fire one packet |
| 14 | `cmp_req` | in | digital | vdd | 17 | per column 4-phase req: one SAR trial on `dac_code` |
| 15 | `cmp_ack` | out | digital | vdd | 17 | ack: trial resolved |
| 16 | `cmp_result` | out | digital | vdd | 17 | 1 iff residue ≥ DAC(trial). Valid ≥ T_BUNDLE before `cmp_ack`↑ until `cmp_ack`↓. |
| 17 | `dac_code` | in | digital | vdd | 68 | column j trial code = `dac_code[4j+3:4j]`. Stable ≥ 1 clk before `cmp_req`↑ (sar_ctrl guarantees this). |
| 18 | `ota_en` | in | digital | vdd | 17 | per column OTA bias gate (tile_fsm `ota_en`). Awake = `ota_en | acq`. |
| 19 | `lora_wa_sel` | in | digital | vdd | 16 | one-hot write select, sidecar A cell i |
| 20 | `lora_wb_sel` | in | digital | vdd | 16 | one-hot write select, sidecar B cell j |
| 21 | `lora_da` | in | digital | vdd | 4 | A write-DAC code |
| 22 | `lora_db` | in | digital | vdd | 4 | B write-DAC code |
| 23 | `vcm` | inout | analog | vdd | 1 | virtual ground / common mode, `specs.VCM_FRAC`·vdd = 0.9 V |
| 24 | `vrn_thrp` `vrp_thrp` | inout | analog | vdd | 1+1 | thr_p ladder rails: vcm, vcm + 15.5·D·u_cal |
| 25 | `vrn_thrn` `vrp_thrn` | inout | analog | vdd | 1+1 | thr_n ladder rails: vcm − 15.5·D·u_cal, vcm |
| 26 | `vrn_sarp` `vrp_sarp` | inout | analog | vdd | 1+1 | sar_p ladder rails: vcm, vcm + 16·D·u_cal·trim |
| 27 | `vrn_sarn` `vrp_sarn` | inout | analog | vdd | 1+1 | sar_n ladder rails: vcm − 16·D·u_cal·trim, vcm |
| 28 | `vb_nc` `vb_pc` `vb_tail` | inout | analog | vdd_ota | 1+1+1 | OTA bias, shared by the 17 converter OTAs and the 2 sidecar OTAs. Origin values 1.25 / 0.29 / 0.665 V (`specs.ota()` governs). |
| 29 | `vb_ramp` | inout | analog | vdd | 1 | sidecar V→T ramp pfet gate (origin 0.656 V) |
| 30 | `vdd` | inout | supply | vdd | 1 | 1.8 V: logic, sequencers, TG drivers, tile, ladders, sidecar |
| 31 | `vdd_ota` | inout | supply | vdd_ota | 1 | 1.8 V: 17 integrator OTAs |
| 32 | `vdd_cmp` | inout | supply | vdd_cmp | 1 | 1.8 V: 34 StrongARMs |
| 33 | `vdd_pkt` | inout | supply | vdd_pkt | 1 | 1.8 V: 17 packet drivers + banks |
| 34 | `vss` | inout | supply | vss | 1 | 0 V |

Counts: 263 digital in + 86 digital out + 13 analog + 5 supply = **367 `.subckt` pins**.
That is 35 Verilog signal ports (349 bits) plus 5 supply pins. Supplies are split for
per-block energy accounting (CONTRACT metrics mandate). `macros.toml` declares all five
as `analog_supplies` (kept off the digital PDN; `pg = []`).

u_cal = `specs.u_cal()` (1.337 mV on sky130) and trim = `specs.fine_ref_trim()` (0.8).
The rails are ideal sources in every testbench ("ideal ref territory", CONTRACT). D is
the pass's `dcode`/`D` and must equal `pkt_d`. Ladder codes are hard-wired as in the
origin: thr_p 15, thr_n 0, sar_p 15, sar_n 0.

## 3. What is inside the macro, and what is in the digital top

| Inside `analogioc` (analog, `.subckt`) | Count | Block |
|---|---|---|
| `weight_tile` 16 rows × 17 columns, rows driven by its embedded `pwm_driver` | 1 (16 pwm_driver) | weight_tile |
| `integrator_conv` (migrated ports, §5) | 17 | integrator_conv |
| `rstring_ladder` thr_p, thr_n, sar_p, sar_n, shared by all columns | 4 | rstring_ladder |
| `lora_sidecar` (gain_cell_array ×2 and write_dac ×2 inside), `colb<j>` tied to column j's virtual ground for j = 0..15 | 1 | lora_sidecar |
| `tile_seq`: integrate sequencer, chop ring, PWM envelopes, sidecar phases; instantiates `async_ctrl` ×1 and `tq_chain` ×1 | 1 | async_ctrl deck |
| `conv_seq`: per-column coarse/fine handshake translator | 17 | async_ctrl deck |
| xrd drivers: per row TG pair, xrd_i = vss while row i's envelope is active, else vcm | 16 | cmos_switch |

| In the digital top `analogioc_top` (RTL, std cells) | Count |
|---|---|
| `tile_fsm` (column 16 = checksum, `relu_en` forced 0) | 17 |
| integrate join: registered C-element over the 17 `integ_req` | 1 |
| `nibble_combine` → `slice_combine` (p_hi = 0, S = 1) → `bacc_accum` W=20 | 17 each |
| `abft_check` W=20 | 1 |
| `requant` (one instance per channel, or one time-multiplexed: implementer's choice, same results) | 16 or 1 |
| pass sequencer (HI then LO window, relu masking, ABFT wiring, LoRA write timing) | 1 |
| `rail_top` | **not instantiated**. It stays the `make synth` smoke wrapper (one slice). |

## 4. Handshake conventions (all three handshakes)

- 4-phase RZ: req↑ → ack↑ → req↓ → ack↓. The macro never raises a req while the previous
  ack is high.
- **Bundling:** each quasi-static datum (`col_sign`, `cb_cross`, `cmp_result`) settles
  **T_BUNDLE ≥ 2 ns** before its qualifying edge (`integ_ack`↑, `cb_req`↑, `cmp_ack`↑) and
  holds until the return edge (ack↓ for integ/cmp, `cb_ack`↓ for cb). The rail samples the
  datum and its req/ack through equal-depth 2FF, so the setup it needs is one flop
  aperture (well under 1 ns on sky130_fd_sc_hd); 2 ns covers routing skew. Digital→macro
  data (`x_*`, `win_hi`, `pkt_d`, `lora_en`, `dac_code`) is stable ≥ 1 `clk` before its
  req↑. It holds until ack↑ (`dac_code`: until `cmp_ack`↓; `x_*`/`win_hi`: until
  `integ_ack`↑; `pkt_d`/`lora_en`: the whole pass).
- **Pacing:** after `cb_ack`↓ or `cmp_ack`↓, the macro waits ≥ 2·T_CLK_MAX before its next
  req, or before sampling `coarse_en` (INTERFACES.md). T_CLK_MAX = 20 ns, the LibreLane
  `CLOCK_PERIOD`. The wait is a delay element in `conv_seq`, sized for T_CLK_MAX. A faster
  fabric clock is always safe; a slower one is not.
- **Electrical meaning of the analog-side edges.**
  - `integ_ack`↑: for every column, the window charge has transferred, the integrator has
    settled, the sign comparator has resolved, its result is latched in `conv_seq`, and
    `col_sign` has been driven for T_BUNDLE. This is a `muller_c` join of 17 completions.
  - `cb_req`↑: the coarse StrongARM resolved (completion = NOT(c1p AND c1n), §5), the
    decision is latched and driven on `cb_cross`, and the comparator clock is back low.
  - `cmp_ack`↑: the same, for the fine StrongARM and `cmp_result`.

  Completion is detected, not timed: a strobe stays high until its comparator resolves, so
  a metastable decision delays the handshake instead of corrupting it.

## 5. Converter boundary (migrated `integrator_conv`)

This supersedes the origin port list in `analog/docs/architecture.md` §2 for this block.
Integrator, OTA, packet bank, kick filters, CDAC and mid-tread half-LSB are unchanged.
Removed: `go clk_cs fire_win clk_fs tr3..tr0 tl3..tl0`, all XSPICE bridges and `d_*`
primitives, and the internal bias V sources.

```
.subckt integrator_conv vg out rst phi1 phi1e phi2 run fire sign sgd clk_c c1p c1n
+ acq clk_f b3 b2 b1 b0 c2p c2n awake thr_p thr_n sar_p sar_n vcm vb_nc vb_pc vb_tail
+ vdd_ota vdd_cmp vdd_pkt vdd vss
```

| Port | Dir | Meaning (origin node) |
|---|---|---|
| vg | inout | column virtual ground = tile `col<j>` (+ sidecar `colb<j>`) |
| out | out | integrator output (monitor only; analog tbs probe `x…cv<j>.out`) |
| rst | in | 1 = integrator in unity feedback (origin `rst`) |
| phi1 phi1e phi2 | in | converter chop at period t_q, same offsets as the tile chop (§6.1) |
| run | in | packet-bank chop gate (origin `run_c` = go·!done) |
| fire | in | packet envelope (origin `fire_env`). Polarity is internal: fire·sign → driver `inn` (lowers V_out), fire·!sign → `inp`. |
| sign | in | latched sign, 1 = V_out > vcm (origin `sign_v`) |
| sgd | in | sign done (origin `sgdone_v`). 0: SA1 vinn = vcm. 1: vinn = thr_p if sign else thr_n; vref = sar_p/vref_o = sar_n if sign, else swapped. |
| clk_c | in | SA1 clock (origin `ck1`; gating moves to `conv_seq`) |
| c1p c1n | out | SA1 `outp`/`outn` buffered non-inverting. Both 1 in precharge; out_filt > vinn ⇒ c1p → 0. |
| acq | in | CDAC acquire: bottoms sample `out`, top reset to vcm |
| clk_f | in | SA2 clock, 10–90 % edges ≥ 2 ns (kick, origin A6 fix) |
| b3..b0 | in | CDAC bit drive during hold (origin `bit{k}_v`) = `dac_code` |
| c2p c2n | out | SA2 `outp`/`outn` buffered. ct > vcm ⇒ c2p → 0. |
| awake | in | OTA bias gate, 1 = biased (origin `awake`) |
| thr_p thr_n sar_p sar_n vcm | in | references |
| vb_nc vb_pc vb_tail | in | OTA bias (were internal V sources) |

`conv_seq` derives the decisions from these:

| Signal | Rule |
|---|---|
| sign latch | sign := c1n at the sign strobe (sgd = 0); `col_sign` = !sign |
| `cb_cross` | (c1n == sign) at a coarse strobe (sgd = 1). Origin `cross = (cmp == sign)`. |
| `cmp_result` | sign ? c2p : c2n. Origin `keep`; 1 ⇔ residue ≥ trial. |

## 6. Wrapper behaviour (`tile_seq`, `conv_seq`)

### 6.1 Chop grid (tile and converter)

A gated ring built from `tq_chain` stages runs while the macro is busy, from `integ_req`↑
until all `coarse_en` and `cmp_req` are low after `integ_ack`↓. It sets the t_q period.
Per chop cycle k, starting t0 = T_W0 + k·Tc, with absolute offsets from delay elements (the
verified origin grid, `_conv_common.py`):

| Edge | Time in cycle | Tol |
|---|---|---|
| phi1 high | [t0+0.3, t0+1.9] ns | ±0.1 |
| phi1e high | [t0+0.3, t0+2.1] ns | ±0.1 |
| phi2 high | [t0+2.5, t0+Tc−0.5] ns | ±0.1 |
| all-off gap | [t0+Tc−0.5, t0+Tc+0.3] | envelope, fire and `x` changes happen only here |

The **tile** chop (`tphi1/tphi1e/tphi2` → `weight_tile`) runs only during the window, with
Tc = t_q (LO) or 16·t_q (HI). Outside the window it is parked: tphi1 = tphi1e = 1,
tphi2 = 0 (A8 tile clock gate). The **converter** chop (`phi1/phi1e/phi2` →
`integrator_conv`) runs at Tc = t_q whenever the ring runs. Each column gates it with `run`.

### 6.2 `tile_seq`: integrate handshake

The `async_ctrl` instance provides the reset and start: go ← `integ_req`, `xbar_rst` →
`rst`/`lrst`, `adc_go` → window start, `adc_done` ← sign join, `done` → `integ_ack`.

| Step | Trigger | Action | Duration (sim) | Min / max |
|---|---|---|---|---|
| I0 | `seq_rst_n`=0 or idle | rst = lrst = 1, tile chop parked, ramp_en = 0, all envelopes 0, xrd = vcm, sgd = 0 | — | — |
| I1 | `integ_req`↑ | latch `x_mag/x_neg/win_hi/lora_en/pkt_d`; clear 17 sign latches; sgd = 0; rst = lrst = 1; start ring | T_RST = 4 t_q (40 ns) | ≥ 20 ns (async_ctrl rst chain, 21.5 ns typ) |
| I2 | T_RST elapsed | rst = lrst = 0 | gap T_RG = 1 t_q | ≥ 1 ns |
| I3 | `adc_go` | window: N cycles of tile chop (LO N = 16, Tc = t_q; HI N = 8, Tc = 16 t_q). Row i: `xin_p_r<i>` = !x_neg_i·(k < m_i), `xin_n_r<i>` = x_neg_i·(k < m_i), m_i = x_mag[4i+3:4i], changing only in the gap. If lora_en: xrd_i = vss while k < m_i (unchopped), else vcm. | 160 ns LO / 1280 ns HI | exact N·Tc |
| I4 | window end | park tile chop (within 0.4 ns of the last cycle end) | — | — |
| I5a | lora_en = 1 | gap T_RAMP0 = 4 t_q; ramp_en = 1 for T_RAMPW = 50 t_q; then T_SETTLE_L = 10 t_q | 40 + 500 + 100 ns | T_RAMPW ≥ 250 ns (T_B max) |
| I5b | lora_en = 0 | settle T_SETTLE = 8 t_q | 80 ns | ≥ 8 t_q (a short settle latches false no-cross) |
| I6 | settle done | all 17 `conv_seq`: sign strobe (sgd = 0, clk_c↑ aligned at chop offset +1 ns). On completion: sign := c1n, clk_c↓, sgd = 1, drive `col_sign` | resolve ≤ 3 ns | strobe held until completion |
| I7 | 17 completions (`muller_c` join) + T_BUNDLE | `integ_ack`↑ | — | T_BUNDLE ≥ 2 ns |
| I8 | `integ_req`↓ | `integ_ack`↓. Integrators **hold** (rst stays 0) until the next I1. | — | — |

### 6.3 `conv_seq`: coarse loop, column j

| Step | Trigger | Action | Time (sim) | Min / max |
|---|---|---|---|---|
| C0 | after I7, cb_ack = 0, pacing elapsed | sample `coarse_en[j]`. If 1, go to C1; else stay idle. run = 0. | — | pacing ≥ 2·T_CLK_MAX after the last `cb_ack`↓ |
| C1 | | run = 1 (packet chop live); clk_c↑ at the next chop offset +1 ns (sgd = 1) | — | — |
| C2 | completion | latch cross = (c1n == sign); clk_c↓; drive `cb_cross`; wait T_BUNDLE; `cb_req`↑ | ~3 ns + 2 ns | — |
| C3 | `cb_ack`↑ | if cross: `fire` = 1 for `pkt_d` converter chop cycles, starting at the next gap. If !cross: run = 0 now (early termination: the packet bank freezes). | pkt_d·t_q | fire edges only in the gap |
| C4 | C3 done | `cb_req`↓ (hold `cb_cross`) | — | — |
| C5 | `cb_ack`↓ | release `cb_cross`. Wait T_ABS from the end of the packet, then go to C0. | T_ABS = 40 ns | T_ABS ≥ `specs.coarse_cadence()` − 2 t_q (origin: packet end → next strobe 41 ns) and ≥ pacing |

The macro never counts: termination is the RTL's job (no-cross, or 15 crossings). After
`event_ctrl` is done, `tile_fsm` drops `coarse_en` within 1 clk, and C0's pacing wait makes
sure that is seen. Packet energy depends on `pkt_d`; one packet = 16·D code units
(`specs.c_pkt`).

### 6.4 `conv_seq`: SAR trial, column j

| Step | Trigger | Action | Time (sim) | Min / max |
|---|---|---|---|---|
| F1 | `cmp_req`↑ | acq = 1. Awake = ota_en \| acq. b3..b0 ignored during acq. | first trial after `coarse_en`↓: T_ACQ1 = 80 ns; later trials T_ACQ = 14 ns | T_ACQ1 ≥ 2·`specs.T_ACQ` (OTA settle + parked-wake recovery); T_ACQ ≥ 14 ns |
| F2 | acq↓ | hold: b3..b0 = `dac_code[4j+3:4j]` (vref/vcm), half cap → vref_o, terminator → vcm | T_HOLD = 15 ns to clk_f↑ | ≥ 15 ns |
| F3 | | clk_f↑ (≥ 2 ns edges); on completion latch `cmp_result` = sign ? c2p : c2n; clk_f↓ | high ≥ 4 ns | strobe held until completion |
| F4 | + T_BUNDLE | `cmp_ack`↑ | — | — |
| F5 | `cmp_req`↓ | `cmp_ack`↓; release `cmp_result` | — | — |

This is the resampling SAR: every trial re-acquires the residue held on the awake
integrator, so a stale `dac_code` between trials is harmless.

## 7. Digital top composition

### 7.1 Module `analogioc_top` (new, `digital/analogioc/src/analogioc_top.v`)

Synchronous on `clk`, async active-low `rst_n`. `config.mk` changes to
`DESIGN_TOP := analogioc_top`, and the LibreLane `DESIGN_NAME` to the same. Delete
`src/analogioc.v`.

| Port | Dir | Width | Meaning |
|---|---|---|---|
| clk, rst_n | in | 1 | |
| cfg_relu_en | in | 1 | ReLU sign-early-exit for data columns |
| cfg_pkt_d | in | 3 | D of the current tensor → macro `pkt_d` |
| cfg_tile_cnt | in | 4 | passes per output (bacc `tile_cnt`) |
| cfg_abft_s | in | 16 | bit j = 1 ⇒ s_j = −1 |
| cfg_abft_budget | in | 16 | |
| cfg_rq_scale / cfg_rq_shift / cfg_rq_offset | in | 16×8 / 16×5 / 16×8 | per channel, channel j at [8j+7:8j] / [5j+4:5j] |
| cfg_lora_en | in | 1 | → macro `lora_en` |
| idle | out | 1 | no pass in flight. cfg_* may change only while idle. |
| pass_valid / pass_ready | in / out | 1 | ready/valid, one tile pass |
| pass_x | in | 16×8 | signed INT8 xq, row i at [8i+7:8i] |
| pass_abft_corr | in | 16 signed | `golden._half_up_div(chk_e·xq, D)` for this pass |
| code_valid | out | 1 | pulse: both windows of a pass converted |
| code_hi / code_lo | out | 17×8 | signed col codes per window, column j at [8j+7:8j] (j = 16 checksum) |
| res_valid / res_ready | out / in | 1 | ready/valid, one output after cfg_tile_cnt passes |
| res_q | out | 16×8 | requant INT8 |
| res_acc | out | 17×20 | accumulators (j = 16 checksum) |
| res_residual / res_abft_flag | out | 25 signed / 1 | abft_check |
| lw_valid / lw_ready | in / out | 1 | LoRA cell write, only while idle |
| lw_b, lw_idx, lw_code | in | 1, 4, 4 | 0 = A / 1 = B, cell index, 4b level |
| vcm, vrn_*/vrp_* (8), vb_nc, vb_pc, vb_tail, vb_ramp | inout | 1 each | passed through straight to the macro (the analog_nets in macros.toml) |

### 7.2 Behaviour per pass

1. Accept the pass and latch `pass_x`. Split it with `golden.pwm_nibbles`: sign, hi = |x|>>4,
   lo = |x|&15.
2. **HI window:** `x_mag` = hi, `x_neg` = sign<0, `win_hi` = 1. Start all 17 `tile_fsm` in
   the same cycle, only when all 17 `start_ready` are high. relu_en_j = cfg_relu_en for
   j < 16, 0 for j = 16. Wait for all `col_valid`, latch `code_hi` and `col_exit` (§7.4),
   then `col_ready`.
3. **LO window:** `x_mag` = lo, `win_hi` = 0. relu_en_j = cfg_relu_en & (code_hi_j == 0).
   After conversion, force code_lo_j = 0 where `col_exit` was set in HI. This makes it
   bit-equal to `golden.tile_mvm(relu=True)`.
4. y12_j = `nibble_combine(msb=code_hi_j, lsb=code_lo_j)`. If cfg_relu_en and j < 16,
   y12_j = max(y12_j, 0). y14 = `slice_combine(p_lo=y12, p_hi=0)`. Then
   `bacc_accum[j].d_valid`, and pulse `code_valid`.
5. Accumulate Σ`pass_abft_corr` in 20 bits. When all 17 bacc are `done`: `abft_check` with
   `y_flat[j]` = s_j·acc_j and `y_chk` = (acc_16 <<< 3) + Σcorr (FORMATS.md
   `abft_wiring`). Then `requant` for each channel j < 16 and present `res_*`. Clear the
   accumulators on the `res` handshake.
6. **LoRA write:** set `lora_da`/`lora_db` = lw_code. After 1 clk, raise the one-hot
   `lora_wa_sel[idx]` or `lora_wb_sel[idx]` for WR_CYCLES = ceil(120 ns / T_clk) (origin
   T_SLOT; write_dac spec 100 ns). Drop it, hold data 1 more clk, then `lw_ready`.

Integrate join: `integ_req_q <= (&fsm_req) ? 1 : (~|fsm_req) ? 0 : integ_req_q`, and
`integ_ack` fans out to all 17. Per-column signals connect directly. `seq_rst_n` = `rst_n`.

### 7.3 TinyTapeout

Phases 1–4 target `analogioc_top` only. `tt_um_analogioc` comes later and serializes the
§7.1 fabric interface over `ui_in`/`uo_out`/`uio`. Its pin plan is open (Q3).

### 7.4 Required RTL changes (owner: digital-top agent)

1. `tile_fsm.ota_en`: add `|| (state == S_FINE)`. Fix the stale comment. Re-run `tb_tile_fsm`.
2. `tile_fsm`: new output `col_exit` (registered, set in S_DECIDE on `se_exit`, cleared on
   the next start accept, valid with `col_valid`). This is additive; update INTERFACES.md
   and `tb_tile_fsm`.
3. `rail_top`, nibble/slice/bacc/abft/requant/event/sar: unchanged.

## 8. Behavioural model contract (`analog/analogioc/va/analogioc_beh.v`)

Module `analogioc`, ports exactly as §2 (no supplies), `timescale 1ns/1ps`. Simulation
only. It is the reference the RTL is verified against, so it must be **bit-true to
`scripts/golden/model.py`**:

- **Weights:** `parameter WEIGHTS = "weights.hex"`, overridable by plusarg
  `+weights=<path>`. The file has 272 lines; line j·16+i is two hex digits, the 8-bit
  two's complement of W[j][i] = `wcp_r{i}c{j}` − `wcn_r{i}c{j}` (j = 16 = signed checksum
  column).
- **On `integ_req`↑:** after T_INTEG, for each column, compute
  mac_j = Σ_i W[j][i]·(x_neg_i ? −1 : 1)·m_i, plus LoRA if `lora_en` and j < 16
  (see below). Then `golden.eventrate_convert(mac_j, D = max(pkt_d,1))`:
  q = floor((2|mac| + D)/(2D)), mag = min(q,255), count_j = mag>>4, fine_j = mag&15,
  col_sign_j = (mac_j < 0). Drive `col_sign`, wait T_BUNDLE, raise `integ_ack`. A column
  with |mac_j| > `specs.MAC_MAX` (185) prints a warning (OTA compression in silicon; golden
  ignores it).
  T_INTEG = T_RST + T_RG + N·Tc + (lora_en ? T_RAMP0+T_RAMPW+T_SETTLE_L : T_SETTLE) + T_SIGN.
- **Coarse:** decision k (0-based) of the current conversion has cb_cross = (k < count_j).
  Follow §6.3 timing: T_DEC, then `cb_req`; on `cb_ack`↑, wait T_PKT = pkt_d·TQ if
  crossing; drop req; on ack↓ wait max(T_ABS, 2·T_CLK_MAX), then sample `coarse_en`.
- **Fine:** `cmp_result` = (fine_j ≥ `dac_code` col j). Timing per §6.4
  (T_ACQ1/T_ACQ + T_HOLD + T_FSTROBE).
- **LoRA:** latch the A_i/B_j codes on the falling edge of `lora_wa_sel`/`lora_wb_sel`
  (value of `lora_da`/`lora_db`). Contribution = LORA_RHO·B_j·Σ_i A_i·m_i, using real
  arithmetic so the golden half-away rounding sees fractional macs. The x magnitude is
  unsigned, matching the hardware xrd. See Q6.
- **Protocol assertions** (`$error`, and a fatal under `+strict`): data changing while its
  req/ack window is open; `cb_req` attempted while `coarse_en` = 0; a req while its ack is
  high; `integ_req` while any column is mid-conversion; `pkt_d` changing mid-pass.
- **Parameters** (ns, sim-grid defaults): `TQ=10, T_RST=40, T_RG=10, T_SETTLE=80,
  T_RAMP0=40, T_RAMPW=500, T_SETTLE_L=100, T_SIGN=6, T_BUNDLE=2, T_DEC=6, T_ABS=40,
  T_CLK_MAX=20, T_ACQ1=80, T_ACQ=14, T_HOLD=15, T_FSTROBE=6, LORA_RHO=0.0` (real), and
  `JITTER=0`. JITTER > 0 scales every analog delay by U[1−JITTER, 1+JITTER] per event,
  seeded by `+seed=`, to test delay-insensitivity.

## 9. Data flow for tests

```
scripts/compiler/compile.py ─► scripts/compiler/out/
  passes/pass_NN_<tag>/{caps.spice, expected.json, params.spice, pwm_lo/hi.spice}
  programming/<m>.npz   acts/<m>.npz   digital_config.json
        │
        ▼  analog/analogioc/test/pass_vectors.py <pass_dir> <out_dir>   (owner: digital-top/beh agent)
  weights.hex     (§8 format, from caps.spice)
  vectors.json    {tag, matrix, ct, D, budget, s[16], chk_e[16], xq[16], corr = _half_up_div(chk_e·xq, D),
                   relu, expected: code_hi[17], code_lo[17], coarse_*, fine_*, n_eval_*, y12[16], y12_chk, residual,
                   requant: scale/shift/offset[16] (digital_config[matrix], channels ct*16..ct*16+15),
                   q[16] = golden.requant_int8(slice_combine(y12), …)}
  refs.json       {vcm, vrn_*/vrp_* for D} (chimera_top.rail_sources rule, §2)
        │
        ├─► analog tb (SpiceRack):  netlist analogioc.py --caps caps.spice; rails from refs.json;
        │     x_mag/x_neg/win_hi/pkt_d as PWL logic sources; handshakes from an ideal
        │     tile_fsm stand-in (python-scheduled PWL or XSPICE) — pwm_*.spice are NOT used
        │     at macro level (only by weight_tile-level tbs)
        ├─► digital tb (iverilog / cocotb):  analogioc_top + analogioc_beh.v (+weights=weights.hex),
        │     drives pass_x/cfg from vectors.json, compares code_hi/lo, y12, res_* exactly
        └─► co-sim:  analogioc_top RTL ⇄ analogioc SPICE (same vectors.json/refs.json),
              compares with the analog tolerances of §10
```

## 10. Acceptance tests

CODE_TOL = 8 LSB is the gate (ERROR_IMPACT.md; `analog/docs/architecture.md` §6.2(5)).
Every analog test also prints how many codes fall outside ±1 (CONTRACT acceptance 1's
original bar). Every tb prints PASS/FAIL and asserts numerically.

| ID | Test | Owner | Pass criteria |
|---|---|---|---|
| A0 | port check | analog-top (views), digital-top (beh) | `macros.py check digital/analogioc/build/macros.toml` prints `ports agree (35 signal ports, 5 supply pins)` after the TODO is removed, and the `.subckt` pin order equals `analogioc.ports` line for line |
| A1 | `tb_integrator_conv` | converter | one converter + behavioural `conv_seq`/ideal handshake, D=1, mac ∈ {0, 15, 16, −50, 165}: \|code − `eventrate_convert`\| ≤ 1; E(0) < 0.3·E(165); coarse req count = count+1 per conversion (n_eval) |
| A2 | `tb_eventrate` | converter | ≥ 7 points (A1 + mac 32, 80): E_conv non-decreasing in \|code\| with 5 % slack; E(code 0)/mean < 0.30 |
| A3 | `tb_tile_mvm` | analog-top | pass_00_worst_code (required) and pass_05_typ_attn_q, both windows, all 17 columns: \|code − expected code_hi/lo\| ≤ CODE_TOL; `golden.abft_residual(y12, y12_chk, s, chk_e, xq, D)` ≤ budget (128 / 199) |
| A4 | `tb_ffn_e2e` | analog-top | pass_09_typ_ffn_gate through the full macro (sidecar present, lora_en = 0): codes ≤ CODE_TOL, residual ≤ 217 |
| A5 | `tb_training_step` | analog-top | rank-1 SGD step on pass_05 with lora_en = 1: L1 < L0; every updated column's Δy has the golden sign and \|Δy − pred\| ≤ max(3 LSB, 40 %); ABFT bypassed |
| A6 | digital regression | digital-top | `make test` (all `test/tb_*.v`) PASS; `make synth` 0 latches |
| A7 | `tb_analogioc_top` | digital-top | RTL + beh model, all 11 passes, JITTER = 0 and JITTER = 0.5 (3 seeds): code_hi/lo, y12, residual, q **exactly** equal to vectors.json; one relu fixture equals `golden.tile_mvm(relu=True)` exactly; zero protocol assertions |
| A8 | `tb_audit` | digital-top (beh), co-sim (SPICE, optional) | one weight in weights.hex changed by ±1 cap LSB on a busy column → `res_abft_flag` = 1; clean run → 0, for pass_04_chk_max |
| A9 | `cosim_tile_mvm` | co-sim | `analogioc_top` RTL ⇄ macro SPICE on pass_05: codes ≤ CODE_TOL vs expected, residual ≤ 199, exactly 17 `col_valid` per window, zero protocol violations, and RTL `code_*` equal to the codes decoded from the analog decisions |
| A10 | `tb_attention_e2e` | co-sim (later phase) | projections via A7/A9 path, rail attention vs `golden.attention_forward` (CONTRACT acceptance 2); criteria set when scheduled |

## 11. Open questions (not resolved by the docs)

| Q | Question | Phase 0 stance |
|---|---|---|
| Q1 | **Runtime weight storage.** Caps are compile-time (a zero bit has no capacitor), but the chip time-multiplexes one tile over 10,944 passes/token. No block has weight storage or a write port. | weights are a build-time parameter (D7); no port reserved |
| Q2 | **On-chip references.** The thr/sar spans scale with D, and the A9/A10 per-column gain correction needs per-column spans. Shared external rails give neither on-chip generation nor per-column trim. The converter agent must also confirm that a `pkt_d`-cycle packet matches `c_pkt(D)` within ±1 LSB. | 8 external rail pins, shared; no per-column gain knob |
| Q3 | **TinyTapeout pin budget.** 13 analog pins + 5 supplies do not fit TT's analog pins. A TT build needs on-chip bias/refs (origin `ptat_bias` is out of scope). | non-TT `analogioc_top` (D8) |
| Q4 | **Timing at the silicon grid.** At t_q = 200 ps, T_ABS and the pacing (≥ 2·T_CLK_MAX = 40 ns) dominate the coarse cadence. The per-decision latency ≈ T_DEC + 2–3 clk (sync) + pkt_d·t_q + T_ABS. That makes it slower than the origin's fixed 60 ns slot, and `specs.conv_time()` does not model it. | accept for function; metrics agent to re-derive |
| Q5 | Coarse saturation: `event_ctrl` counts to 15 but `specs.COARSE_CAP` = 7 is lossless, so crossings 8..15 only burn energy. | unchanged RTL; macro never counts |
| Q6 | **LoRA sign and scale.** The sidecar integrates unsigned \|x\| on xrd, but `golden.tile_mvm(lora=…)` uses signed sign·nibble. ρ (code units per A·B·x unit) is unmeasured, and only the LO window was validated. | beh model follows the hardware (unsigned), with LORA_RHO as a parameter; A5 keeps the origin tolerance-based check |
| Q7 | Merged (S5), ping-pong (S6), cascade and super-tile modes need a switchable C_int or a second converter path. | not supported by this macro |
| Q8 | INTERFACES.md says "a tile replicates [tile_fsm] 16x"; ABFT needs the checksum column converted. | 17 instances (D4); update INTERFACES.md |
| Q9 | Should the macro's logic `vdd` join VPWR via `pg`, rather than staying a separate analog supply? | separate (energy accounting); revisit at TT wrapper |
