# pwm_driver — PWM row driver

Schematic, drawn by cktImg from `netlist/pwm_driver.spice` (`make import NETLIST=pwm_driver`): [pwm_driver.svg](pwm_driver.svg)

Leaf block, 16 per weight tile (one per row) plus the packet bank of each
`integrator_conv`. Chops the A5 PWM envelope onto the tile's two-phase switched-cap
grid, so every chop cycle while the envelope is high moves exactly C·VDD per bank:
charge = code · C · VDD, linear in PWM width. See `analog/docs/architecture.md`
§Tile path and AnalogIOC `components/pwm_driver` (the physics argument).

## Interface

`.subckt pwm_driver inp inn phi1 phi1e outa outb vdd vss`

| Port | Dir | Meaning |
|------|-----|---------|
| inp, inn | in | A5 envelope, VDD pulse of width code·t_chop (positive / negative activation) |
| phi1 | in | recharge phase (bank tops to vcm) |
| phi1e | in | phi1 with a stretched fall, into the phi1→phi2 gap |
| outa | out | bottom plates of the row's C+ banks: (inp & phi1e) \| (inn & !phi1) |
| outb | out | bottom plates of the row's C− banks: (inp & !phi1) \| (inn & phi1e) |
| vdd, vss | supply | `pdk_specs.vdd`, 0 |

P-style line (`& phi1e`): high during phi1, falls in the gap. N-style (`& !phi1`):
low during phi1, rises in the gap. Both transfer one C·VDD at the phi2 connect.

Chop grid (tile-path contract, AnalogIOC `_conv_common`, carried in
`test/tb_pwm_driver.py`): cycle k at t0 = 5 ns + k·t_chop; phi1 high
[t0+0.3, t0+2.0] ns, phi1e 0.2 ns longer, phi2 high [t0+2.5, t0+t_chop−0.5] ns;
t_chop = `specs.TQ_SIM` (lo window) or 16·TQ_SIM (hi window).

## Specs

| Metric | Min | Typ | Max | Unit | Testbench |
|--------|-----|-----|-----|------|-----------|
| Transfers on the P-style line vs code, codes 0..15, both signs | = code | | = code | — | `tb_pwm_driver` |
| Gated width per cycle, deviation over codes 1..15 | | | 2 | % | `tb_pwm_driver` |
| 10–90 % edge into C_ROW = 100 fF | | | TQ_SIM/3 | s | `tb_pwm_driver` |
| Hi window (chop 16·TQ_SIM), code 7, both signs | = 7 | | = 7 | transfers | `tb_pwm_driver` |
| Gap margin: phi2 50 % − latest bottom-edge 50 % | reported | | | ps | `tb_pwm_driver` (info) |
| MC: transfer count exact, every sample | = code | | | — | `tb_pwm_driver_mc` |
| MC: 3σ sign width skew \|w_a − w_b\| / w̄ (code 4) | | | 2 | % | `tb_pwm_driver_mc` |

All AnalogIOC `tb_pwm_driver` assertions kept with their thresholds. The gap margin is
new and informational: the phi1e stretch (0.2 ns) and phi1e→phi2 gap (0.3 ns) are
set by the clock generator, not this block; see *Timing hazard*.

## Sizing

Every device is a rail-to-rail switch, so there is no gm/ID coordinate: sizes are
on-current budgets from J_ON = I_D/W at |VGS| = VDD, L = min (`docs/gmid.py` table,
saturation). Derived in `netlist/pwm_driver.py`; L = `pdk.min_l` everywhere.

| Stage | Derivation | W n / p (µm) | AnalogIOC hand |
|-------|------------|--------------|--------------|
| final inverter | I_on = 0.8·VDD·C_ROW / (`specs.t_q_floor()`/3); W = I_on / J_ON, n and p each from their own J_ON (equal rise/fall) | 4.74 / 13.06 | 4.0 / 8.0 |
| mid inverter | geometric mean of logic and final (equal stage fanout) | 1.41 / 3.89 | 0.42 / 0.84 (min) |
| logic (inv, NAND2) | N = `pdk.min_w`, P = N·J_ON,n/J_ON,p | 0.42 / 1.16 | 0.42 / 0.84 |

34 FETs. The edge budget is the *silicon* t_q (`t_q_floor` = 200 ps → 67 ps), not
the 10 ns simulation grid the testbench spec uses (3.33 ns), which is why the final
stage is near AnalogIOC's despite a spec that a minimum inverter would meet.

## Timing hazard

The P-style fall starts at the phi1e fall and runs NAND → NAND → mid → final (four
stages) inside the 0.3 ns phi1e→phi2 window. Measured margin (phi2 50 % − edge
50 %, code 1, both signs): tt/27 °C +50 ps, ff/−40 °C +125 ps, ss/−40 °C −50 ps,
ss/125 °C −85 ps; post-layout (seed2 parasitics, 5–8 fF per logic node) already
−85 ps at tt/27 °C. At ss, and post-layout already at tt, the edge lands after the
connect, and the tail of that edge transfers during phi2 through the bank series R (AnalogIOC's older "driven edge"
path, ~0.7 % charge loss). None of the AnalogIOC checks see this; it belongs to the
weight_tile charge-accuracy benches and to the clock generator's phi1e / gap
timing.

## Results

| Rung | Result | Notes |
|------|--------|-------|
| pre-layout (`DUT=sch`, tt 27 C) | PASS | counts exact 0..15 both signs; 1.927 ns/cycle, max dev 0.15 %; worst edge 136 ps; hi window [7, 7]; gap margin +50 ps |
| golden model (`DUT=va`) | PASS | counts exact; 1.898 ns/cycle, max dev 0.03 %; edge 157 ps; hi window [7, 7]; gap margin +15 ps |
| layout (Philis, 60×50 µm die, `layout/interface.json`) | partial — seed2 kept | DRC 2 blocking (LI.3 li spacing 153 < 170 nm), LVS match (17 N / 17 P), 0 unrouted, advanced 5/6 (IrDrop: vdd_load 44 % drop), ERC 3 blocking; exit 1 |
| post-layout (`DUT=pex`, seed2, tt 27 C) | PASS | counts exact; 1.918 ns/cycle, max dev 0.10 %; edge 150 ps; hi window [7, 7]; gap margin −85 ps |
| corners (`DUT=sch`, tt ss ff sf fs × −40/27/125 C) | PASS 15/15 | gap margin (info) ss −50…−85 ps, see *Timing hazard* |
| Monte Carlo (30 × tt_mm) | PASS | counts exact every sample; sign width skew mean −0.02 %, σ 0.37 % → 3σ 1.14 % (< 2 %); gap margin 49 ± 2.7 ps |

Philis runs (100 iters default, machine heavily loaded):

| Seed | Runtime | DRC blocking | LVS | Unrouted | Advanced |
|------|---------|--------------|-----|----------|----------|
| 1 | 36220 s | 6 (LI.3 ×4, M3.2, NWELL.1) | mismatch (device class 24: 0 layout vs 1 ref) | 0 | 5/6 |
| 2 | 34576 s | 2 (LI.3 ×2) | match | 0 | 5/6 |

AnalogIOC reference (its hand sizing, STATUS.md A2): counts exact 0..15 both signs,
width linearity 0.26 %, edges 0.25 ns, hi window exact.
