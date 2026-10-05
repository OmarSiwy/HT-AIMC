# lora_sidecar — rank-1 signed LoRA sidecar

Adds the `golden.tile_mvm(lora=(A, B, rho))` term in charge onto tile columns 0..15:

    Delta mac_j = rho * B_j * sum_i A_i * s_i * m_i        (code units, per nibble window)

A (16) and B (16) are signed 4b weights held in 2T gain cells (`gain_cell_array`),
written through two `write_dac`s; `s_i * m_i` is row i's signed PWM nibble. `colb<j>`
ties to column j's integrator virtual ground (INTERFACE.md §3). Depends on
`cmos_switch`, `gain_cell_array`, `ota`, `write_dac`. AnalogIOC origin:
`components/lora_sidecar` (unsigned |x|, LO window only, rho never measured — INTERFACE
Q6). This block resolves Q6; the changes and the reasons are in §Design.

## Interface

`.subckt lora_sidecar xen0..15 xneg0..15 colb0..15 wa_sel0..15 wb_sel0..15 da0..3 db0..3
rst ramp_en vaxp vaxn vcm vb_ramp vb_nc vb_pc vb_tail vdd vss`

| Port | Dir | Meaning |
|------|-----|---------|
| xen<i> | in, logic | row i's A-integrate gate: LO window high for m_i·t_q from the window start; HI window high for the **first t_q of each** 16·t_q chop cycle k < m_i |
| xneg<i> | in, logic | row i's sign (`x_neg`), static over the pass |
| colb<j> | inout | column j virtual ground (≈ vcm). Charge sunk from it = +Delta mac |
| wa_sel<i>, wb_sel<j> | in, logic | one-hot write select of A row i / B column j (both cells of the element) |
| da3..0, db3..0 | in, logic | sign-magnitude code: d3 = sign, d2..d0 = magnitude m (0..7) = golden W_MAX grid |
| rst | in, logic | integrator reset (macro `lrst`): high T_RST before the window |
| ramp_en | in, logic | V→T phase (macro `ramp_en`) |
| vaxp, vaxn | out | A integrator outputs (monitor only) |
| vcm | ref | virtual ground / write ceiling / current dump |
| vb_ramp | bias | ramp PMOS gate: diode replica of the ramp device carrying `specs.lora_i_ramp()` (4.854 µA; 0.375 V at tt) |
| vb_nc vb_pc vb_tail | bias | OTA biases (`ota` contract); vb_tail also biases the B-mirror standing current |
| vdd, vss | supply | |

Changes against the origin port list (`analog/docs/architecture.md` §2 row, now
updated): `xrd<i>` (a vss/vcm source line) is replaced by logic `xen<i>`; `xneg<i>` is
new; `vax` became `vaxp vaxn`. The macro port list (`analogioc.ports`) is unchanged:
`x_neg` is already a macro input; `tile_seq` must route it, and drive `xen` instead of
the 16 xrd TG drivers (INTERFACE §3), which are no longer needed.

## Design (what changed from the origin, and why)

| Origin | Here | Why |
|---|---|---|
| A cells source-switched by xrd (0.9→0 V pulse) | cells always on (source at vss), drain **steered** colp / coln / vcm-dump by logic | the cell must carry ≤ I_SIDE/16 = 375 nA at full scale in strong inversion (matching), i.e. W/L = 0.43/19.2 µm; its 60 fF gate is the store, so a switched source bootstraps the floating gate and the cell turns itself off |
| unsigned \|x\| | Ap/An cell pair per row, swapped by xneg; two integrators (P, N): Q_P − Q_N = A·x | golden uses signed x and signed A (`lora_quant`) |
| one ramp + one comparator, B window = ramp_en..crossing (eps = 18 ns offset, needs an x=0 baseline pass) | both integrators ramp to vth = vcm − V_PED; B window = XOR of the two crossings, polarity = which side is later; each crossing latched until ramp_en falls | the window is \|Q_P − Q_N\|/I_ramp; comparator delays cancel: **x = 0 reads 0.000 code with no baseline**. The latch: a ramp step moves vax by I_ramp/gm_OTA (~70 mV at tt, 180 mV at fs/125 °C) — the same on both sides at the start, but when a ramp stops it lifts vax back over vth; unlatched, the window chattered and left −10 code of switch charge per column |
| B cells sink only | per column: direct cells sink (+), mirrored cells source (−) through a PMOS mirror; pos window: bpd + bnm, neg window: bnd + bpm | signed B × signed A·x needs both polarities on each column |
| — | each mirror carries a standing bias I_MB = I_cell/8 (NMOS on vb_tail), taken back off its output | an unbiased mirror on ≤ 291 nA slews its 0.6 pF gate for µs after a write |
| x pulses unchopped in both windows | HI window integrates one t_q per chop cycle | the tile delivers one transfer per chop cycle in both windows, so golden uses one rho for both; an unchopped HI pulse integrates 16× the charge |
| write code = level | sign-magnitude; DAC code = 8 + m (m > 0), 0 for m = 0; the sign picks the cell, the other cell gets 0 V | 1 + 3 bits = golden W_MAX = 7; the top half of the DAC is where the cell conducts |

Window pedestal c0: every time a B window opens and closes, the colb steering switch
leaves a fixed charge on the column (−0.35 code on sky130 tt, the same on every column
and independent of B). It is calibrated with rho (`lora_bench.calibrate`) and removed
like a zero point.

**Level table (not linear).** The read current is a square-law-ish function of the
stored level: measured I_m/I_7 = 0, .0141, .0474, .1261, .2638, .4595, .7065, 1 for
m = 0..7. Seven current levels linear in m would need ~25 mV write steps near the top;
`write_dac`'s LSB is 60 mV, and the level map moves with Vt over corners. So the
hardware's effective weight of code (s, m) is (−1)^s · 7 · levels[m] — a companded
4b format — and golden must quantize onto it (§Golden).

## Specs

TOL(gold) = max(TOL_ABS, TOL_REL·|gold|), TOL_ABS = 1 code (converter LSB at D = 1),
TOL_REL = 5 % (system architecture §4: outer-product column error ≤ 5 %).

| Metric | Min | Typ | Max | Unit | Testbench |
|--------|-----|-----|-----|------|-----------|
| LoRA term vs golden `tile_mvm(lora)`, LO and HI, random and coherent signed x, all 16 columns | | | TOL | code | `tb_lora_sidecar` |
| x → −x negates every column | | | TOL_ABS | code | `tb_lora_sidecar` |
| x = 0, no baseline pass | | | 0.5 | code | `tb_lora_sidecar` |
| Storage non-destructive (reference pass repeated after 5 passes) | | | 0.5 | % | `tb_lora_sidecar` |
| A integrator swing (budget set at the nominal cell current; fast corners carry ~1.2× — the compiler's per-chip budget uses the calibrated I_7) | | | 1.5 × `specs.V_SWING` (inside the OTA's ±370 mV) | V | `tb_lora_sidecar` |
| Level table strictly monotone; level 0 | | | 1 | % of level 7 | `tb_lora_rho` |
| rho fit vs physical rho (ΔV_ax·I_B7/(49·Σm·slope·q_unit)) | | | 5 | % | `tb_lora_rho` |
| Window pedestal \|c0\| (calibrated out) | | | 2 TOL_ABS | code | `tb_lora_rho` |
| Mirror path error \|km − 1\|·level | | | 2 | % FS | `tb_lora_rho` |
| Delta mac linear in A·x (1..4 reference rows, residual from a line through 0) | | | TOL_ABS / 2 | code | `tb_lora_rho` |
| SGD step: L1 < L0; updated columns golden sign and \|Δy − pred\| ≤ TOL; others ≤ TOL_ABS | | | | | `tb_lora_update` |
| Yield, every column within TOL after per-chip calibration + x = 0 zero point (tt_mm, 30 samples) | 90 | | | % | `tb_lora_sidecar_mc` |
| Energy per LO op, per write slot | | report | | pJ | `tb_lora_sidecar` |

Calibration knob: rho, levels, c0 are measured per run (the per-chip calibration:
two reference passes on rows 0..3 = +7, x = ±15). `tb_lora_rho` records the typical
values for `specs.lora_cal()`.

## Sizing

`netlist/lora_sidecar.py`; design laws in `specs.py` (`lora_*`).

| Quantity | Derivation | sky130 |
|---|---|---|
| full-scale cell current | `lora_i_cell` = I_SIDE / N_ROWS (16 rows on one integrator stay inside the class-A sink) | 375 nA (measured 291 nA: write pedestal) |
| C_int (×2) | `lora_c_int` = LORA_AX_MAX · I_cell · t_q / V_SWING; LORA_AX_MAX = 60 (compiler budget per side, worst case 240) | 0.90 pF |
| LoRA full scale | `lora_mac_max` = MAC_MAX − CODE_MAX (headroom above the 4σ code ceiling) | 65 code |
| longest B window | `lora_t_b_max` = lora_mac_max · q_unit / I_cell | 46.3 ns |
| ramp current | `lora_i_ramp` = C_int · V_SWING / t_b_max | 4.854 µA |
| cell read device | VGS = V_W carries I_cell; L stepped (Lmin multiples) until W ≥ min_w and measured σ(I)/I ≤ 1 % | 0.43 / 19.2 µm (σ(VGS) 1.40 mV, 0.76 %) |
| cell write switch | `gain_cell_array.write_size()` | 0.54 / 0.30 µm |
| ramp PMOS (×2) | gm/ID 5; L stepped until measured P/N pair σ ≤ 0.5 code / lora_mac_max | 7.02 / 7.2 µm (σ(VGS) 0.85 mV → 0.60 %) |
| B mirror PMOS (×4/col) | gm/ID 10 (diode node 0.59 V keeps the cell saturated) at 1.125·I_cell; σ ≤ 2 % | 3.65 / 9.6 µm (1.6 %) |
| mirror bias NMOS (×4/col) | gate vb_tail (tail VGS), I_cell/8, L stepped until min_w carries it, σ ≤ 10 % | 0.52 / 28.8 µm |
| V_PED | 3σ of (integrator − comparator) OTA offset: 3·√2·pair σ(in 0.54/0.3) | 57 mV |
| vth divider | vcm → vss at I_SIDE; R_top/R_bot from V_PED; decap = C_int | 9.5 k / 140.5 k, 0.9 pF |
| TGs at vcm | R_on(vcm) **measured** per width on every corner × temp (`tg_vcm`, `netlist/char/<pdk>.json`; a min TG reads 30 kΩ at tt, 788 kΩ at ss/−40 °C), PMOS min | |
| cell / mirror steering TG | R_on·I_cell ≤ 0.3 V (keeps cell and mirror saturated; wider → more charge per window, c0) | n 0.42, p 0.42 / 0.15 µm |
| ramp steering TG (×4) | R_on·I_ramp ≤ 20 mV (a min TG at ss/−40 °C would collapse the ramp source) | n 13.44, p 0.42 / 0.15 µm |
| reset TG (×2) | R_on ≤ T_RST / (C_int ln(2 V_SWING/V_PED)) | n 3.36, p 0.42 / 0.15 µm |
| comparator latch | NOR SR latch per side, set by the crossing, cleared by ramp_en low | logic sizes |
| logic | min N, equal-drive P at Lmin; window buffers fan-out 4 | 0.42 / 1.16 / 0.15 µm |
| OTAs (×4: 2 integrators, 2 comparators) | `ota` block as is | |

## Golden model

Four modules, 1:1 with the netlist's child subckts: `va/lora_sidecar_arow.va`,
`_bcol.va`, `_wbus.va`, `_vt.va`. DUT=va wires them with the netlist's own
`instances()` list (`lora_bench.va_dut`). There is no single `lora_sidecar.va`: ESPice
compiles a Verilog-A device with at most 64 unknowns (its Jacobian rows are u64 masks;
`eval.zig` refuses with "shift by negative amount"), and one module for the whole
sidecar has 201. Cells: write-switch-gated RC store, EKV read law fitted to the DUT=sch
level table (is 9.2 nA, vt 0.544 V, nut 31.4 mV, within 2 %); ideal integrators; equal
ramps; first-order latched comparator delay; ideal mirror; write buses park at vref.
Not modelled: switch injection (c0 = 0), the OTA's finite gm (ramp-start kick), OTA
limits/offset, mismatch, DAC settling.

**Golden (`scripts/golden/model.py`) change needed — described, not made.** `tile_mvm`
needs nothing: it already takes real-valued (A_q, B_q, rho). `lora_quant` must quantize
onto the hardware grid instead of integers:

```python
def lora_quant(A, B, dw_cols, levels=None, rho=None):
    # levels: specs.lora_cal()["levels"] (levels[0] = 0, levels[7] = 1); None = today
    grid = W_MAX * np.asarray(levels)                 # effective magnitudes
    def q(v, d):                                      # -> (signed effective, code)
        m = np.argmin(np.abs(np.abs(v)[:, None] / d - grid[None, :]), axis=1)
        return np.sign(v) * grid[m], (np.sign(v) < 0) * 8 + m
    dA = max|A| / W_MAX;  dB0 = (rho / dA) if rho else max|B/dw| / W_MAX
    ...
    return A_eff, B_eff, dA * dB0, A_code, B_code
```

`rho` is the hardware's (`specs.lora_cal()["rho"]`): the product of the two scales is
fixed by the silicon (rho ∝ 1/I_ramp, i.e. vb_ramp), so dB0 follows from dA instead of
from max|B| (B saturating at 7 when the requested update is larger). `lora_sgd_step` is
unchanged. INTERFACE §8's behavioural model correspondingly needs LORA_LEVELS[8] next to
LORA_RHO, signed x (x_neg) and sign-magnitude codes, and no "unsigned" note.

## Results

Simulator: ESPice (the repo default since 1b2b91e); the same rungs on ngspice 45 before
the switch are listed for comparison. sky130 tt, 27 °C unless noted.

| Rung | Result | Notes |
|------|--------|-------|
| golden model (`DUT=va`, ESPice) | PASS 3/3 | rho 0.01378; vs golden ≤ 0.04 code; ngspice/OSDI (single module, before the split) 0.01377 |
| pre-layout (`DUT=sch`, ESPice) | PASS 3/3 | see below |
| pre-layout (`DUT=sch`, ngspice 45) | PASS 3/3 | same numbers to ≤ 0.02 code |
| corners (5 × −40/27/125 °C), ngspice | rho 15/15, sidecar 15/15 PASS; update 9/15 (ff, sf failed loss check — tb planned the target from the tt record; fixed in ce39033, not rerun on ngspice) | |
| corners, ESPice | PASS: rho 15/15, sidecar 15/15, update 15/15 | |
| Monte Carlo (tt_mm, 30) | **not run** (bench written; runs killed by session stops, then simulation stopped by the user) | `make -C analog/lora_sidecar/build/sim mc` |
| hotswap | not run | gf180 sizing would characterise new gm/ID tables and mismatch points (~30 min each under load); the script derives every size from `pdk_specs`/`specs`/`gmid`/`mismatch` |
| layout | not this phase | |

Nominal, DUT=sch (ESPice / ngspice):

| Metric | ESPice | ngspice | Origin (AnalogIOC) |
|---|---|---|---|
| rho (code / (A_eff·B_eff·x)) | 0.01337 | 0.01337 | never measured |
| rho physical cross-check | 0.01359 (−1.6 %) | 0.01359 (−1.6 %) | — |
| level table I_m/I_7, m = 1..7 | .0143 .0480 .1270 .2645 .4598 .7065 1 | .0143 .0481 .1269 .2645 .4599 .7065 1 | levels by I_cal at measured stores |
| I_7 (full-scale cell) | 291.0 nA | 291.0 nA | — |
| window pedestal c0 | −0.370 code | −0.381 code | eps = 18 ns (needed an x=0 pass) |
| mirror path error, worst | 0.54 % FS | 0.54 % FS | — (unsigned) |
| LO window vs golden, worst column | 0.06 code | 0.05 code | 1.36 % (unsigned, vs I_cal golden) |
| HI window vs golden, worst | 0.06 code | 0.06 code | not validated |
| coherent x (A·x at the budget) LO / HI, worst | 0.06 / 0.23 code | 0.06 / 0.22 code | — |
| x → −x | 0.11 code | 0.09 code | — |
| x = 0, no baseline | 0.000 code | 0.000 code | — |
| storage after 6 passes | 0.27 % | 0.17 % | — |
| SGD step: loss, worst \|Δy − pred\| | 175.6 → 11.5, 0.05 code | 175.6 → 11.5, 0.04 code | 0.93 % post-update |
| energy per LO op (rst + window + ramp) | 61.6 pJ | 61.6 pJ | 67 pJ |
| energy per write slot (A row + B column, incl. 160 ns of standing current) | 21.2 pJ | 21.2 pJ | 7.1 pJ per cell write |
| static (4 OTAs + cells + mirror bias), vdd | ≈ 50 µA | | 2 OTAs |

Corner spread (diagnostic tb_lora_rho runs on the netlist before the comparator latch,
which does not touch the cells or the ramp; per-chip calibration absorbs it): rho 0.0054
(fs, 125 °C) … 0.0276 (sf, 27 °C), I_7 185 … 417 nA, A swing 122 … 277 mV at the
LORA_AX_MAX budget — the cell's full-scale current tracks Vt, so the compiler's A·x budget
must use the calibrated I_7.
