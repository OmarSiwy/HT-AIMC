# cmos_switch — CMOS transmission gate

Schematic, drawn by cktImg from `netlist/cmos_switch.spice` (`make import NETLIST=cmos_switch`): [cmos_switch.svg](cmos_switch.svg)

Leaf block, parametrised. An NMOS and a PMOS in parallel between `in_` and `out`; every
switched-charge block uses its own sized copy: `write_dac` / `rstring_ladder` tap muxes,
`integrator_conv` reset / packet / CDAC switches, `weight_tile` transfer switches,
`lora_sidecar` integrator reset. See `analog/docs/architecture.md`.

## Interface

`.subckt cmos_switch in_ out ctrl ctrl_b vdd vss` (AnalogIOC `library/cmos_switch.py`)

| Port | Dir | Meaning |
|------|-----|---------|
| in_, out | inout | switched terminals (symmetric) |
| ctrl | in | NMOS gate: high = on |
| ctrl_b | in | PMOS gate: complement of `ctrl` |
| vdd, vss | supply | PMOS / NMOS bulks only, `pdk_specs.vdd` / 0 |

Parents instantiate a uniquely named copy:
`build(f"{parent}_sw", **sizes(r_on=<budget>))` or explicit `w_n/l_n/w_p/l_p` (µm),
then emit it before themselves in `deck(...)`.

## Specs

Default instance (`build()`) = the write-DAC tap (`write_dac`, `lora_sidecar`), over its
signal range [0, V_W], V_W = `specs.VCM_FRAC`·VDD (AnalogIOC's 0.9 V write ceiling).
LSB_W = V_W / 15 = 60 mV (4b write DAC).

| Metric | Min | Typ | Max | Unit | Testbench |
|--------|-----|-----|-----|------|-----------|
| R_on over v_in ∈ [0, V_W] | | | `r_on_budget()` = 534 | kΩ | `tb_cmos_switch` |
| Charge-injection pedestal on `c_store` (30 fF), v_in ∈ [0, V_W], 0.1 ns ctrl edges | −LSB_W/2 = −30 | | +30 | mV | `tb_cmos_switch` |
| Mux leakage error 15·I_off(\|V_DS\| = V_W)·R_on,peak (16:1 tap mux) | | | LSB_W/4 = 15 | mV | `tb_cmos_switch` |
| Peak R_on over [0, V_W], mean + 3σ, Monte Carlo (mismatch) | | | 534 | kΩ | `tb_cmos_switch_mc` |

* `r_on_budget()` = T_WRITE / ((B_Y + 1)·ln2·c_store): the gain-cell store settles to
  `specs.B_Y` bits within the 100 ns write slot (AnalogIOC SIZING.md (c): 537 kΩ).
* Pedestal: a write opens the gain-cell switch before the tap code moves, so this TG's
  charge lands on the re-driven bus, not the store. The bound covers the mis-sequenced
  case, which then owns the whole ½ LSB_W. (A first draft split ½ LSB_W between the two
  switches, ±15 mV; that has no window against the R_on corner — see Sizing.)
* Leakage acts while the cell switch is on and shares ½ LSB_W with that switch's own
  pedestal, hence ¼.
* The tb also prints R_on over the full [0, VDD]: mid-rail it peaks at 31.6 kΩ (tt) and
  ~1 MΩ (ss, −40 °C). **A parent that runs the default size near VDD/2** (AnalogIOC
  `lora_sidecar` integrator reset, `integrator_conv` reset/packet switches at vcm)
  **must size its own copy**.

## Sizing

Derived in `netlist/cmos_switch.py` (a switch sits in triode: no gm/ID coordinate).
L = min_l for both: R_on·C and injected charge (∝ W·L) favour the shortest channel.

| Device | Derivation | AnalogIOC hand | sky130 | gf180mcuD |
|--------|------------|--------------|--------|-----------|
| n | smallest W whose worst R_on(V_W) over every corner × {−40, 27, 125} °C is ≤ R_GUARD·budget (0.75) — `dead_zone()` | 0.42/0.15 (`inv_n`) | 0.58/0.15 | 0.22/0.28 |
| p | min_w: carries only the top of [0, VDD], outside the write range; least injection and leakage | 0.84/0.15 (`inv_p`) | 0.42/0.15 | 0.22/0.28 |

At V_W only the NMOS conducts, and at the slow/cold corner it is subthreshold there
(body effect on top of the corner Vth), so no square-law form holds (it predicts
~2 kΩ; ss/−40 °C measures 788 kΩ at 0.42 µm). `dead_zone()` measures R_on(V_W) against
W_n = min_w … 3·min_w on every corner/temperature of the active PDK with its own models
(ngspice via `docs/pdk_char.ngspice`) and caches it in `netlist/char/<pdk>.json`, the
same pattern as `docs/pdk_char.py`. sky130 worst case (ss, −40 °C): 0.42 → 788 k,
0.50 → 535 k, 0.55 → 486 k, 0.58 → 380 k, 0.63 → 256 kΩ. gf180 at 3.3 V has no dead
zone (17 kΩ worst at min size), so both devices stay at min_w.

`sizes(r_on)` for parents is square-law with W_p/W_n = un_cox/up_cox (flat first-order
R_on), each clamped to min_w. It ignores body effect and the dead zone and reads the
mid-rail R_on ~20× low at tt (predicts 1.8 kΩ, measured 38.9 kΩ at 0.42/0.42); a parent
with a tight budget (AnalogIOC `dac_sw` < 500 Ω, tap mux ~7 kΩ) verifies its own settling.

Options measured on the way (tt / 27 °C unless noted, W in µm):

| W_n / W_p | R_on peak [0, VDD] | R_on(V_W) ss −40 °C | Pedestal [0, VDD] | I_off @1.8 V |
|-----------|--------------------|---------------------|-------------------|--------------|
| 0.42 / 0.84 (AnalogIOC) | 25.2 kΩ | — | −9.2 … +15.4 mV | 649 pA |
| 0.42 / 1.26 (un/up) | 23.1 kΩ | — | −7.7 … +24.6 mV | 60.4 pA |
| 0.42 / 0.42 | 38.9 kΩ | 788 kΩ (fails) | −10.8 … +5.1 mV | 16.4 pA |
| **0.58 / 0.42 (chosen)** | 31.6 kΩ | 380 kΩ | −14.7 … −6.9 mV on [0, V_W] | 3.0 pA @ V_W |
| 0.63 / 0.42 | — | 256 kΩ | −16.0 mV @ ff 125 °C | — |

The AnalogIOC 0.84 µm pfet leaks ~40× the 0.42 µm one (a different sky130 width bin).

## Golden model

`va/cmos_switch.va`: two softplus triode channels with a linear body-effect term, channel
charge `cg·vov` drawn half from each side (charge injection), gate-overlap caps and an
off conductance. Defaults are a least-squares fit to the default sky130 netlist at
tt / 27 °C: kn 923 µA/V², kp 75.3 µA/V², vtn 0.851 V, vtp 0, bn 0, bp 0.825,
cgn 0.48 fF, cgp 0.33 fF, covn 0.23 fF, covp 0.10 fF, goff 3.3 pS. It models that one
size, PDK and corner; refit for another.

## Results

| Rung | Result | Measured |
|------|--------|----------|
| pre-layout (`DUT=sch`, tt 27 °C) | PASS | R_on peak on [0, V_W] 16.6 kΩ @ 0.9 V (1.2 kΩ @ 0); full range 31.6 kΩ @ 1.0 V; pedestal −14.7 … −6.9 mV; I_off 3.0 pA → 0.001 mV |
| golden model (`DUT=va`) | PASS | R_on 15.7 kΩ @ 0.9 V (full 33.0 kΩ @ 1.0 V); pedestal −12.9 … −7.3 mV; I_off 3.0 pA |
| layout (Philis, `--interface`) | PASS (DRC 0, LVS match), ERC blocked | seeds 1/2 identical by DRC/LVS/advanced 3/6; kept seed 1 (11.2 fF vs 11.5 fF). Re-run at `--max-iters 100` (`make pnr-seeds SEEDS="11 12"`): both converge early (best iter 9/21, 17/18) to the same DRC 0 / LVS match / 3/6 / ERC 5, C 11.3 / 11.5 fF — no gain, seed 1 kept. vdd/vss reach only the bulks and Philis draws no well/substrate tap: ERC `unconnected_pin` on both rail pins + `soft_connection` |
| post-layout (`DUT=pex`, seed 1) | PASS* | R_on 16.6 kΩ @ 0.9 V; pedestal −14.1 … −6.6 mV; I_off 3.0 pA. *converted with a one-line `pex.py` fix not yet applied (bulk-only ports) |
| corners (5 × {−40, 27, 125} °C, `DUT=sch`) | PASS 15/15 | worst R_on(V_W) 380 kΩ (ss −40 °C, `char/sky130.json`); worst pedestal −16.0 mV (ss 125 °C) |
| Monte Carlo (30 × `tt_mm`) | PASS | peak R_on on [0, V_W] mean 17.1 kΩ, σ 2.95 kΩ (17.3 %), mean + 3σ 26.0 kΩ ≤ 534 kΩ |
