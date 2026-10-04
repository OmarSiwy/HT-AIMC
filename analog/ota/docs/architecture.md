# ota — telescopic-cascode column-integrator OTA

Leaf block. The amplifier of every column integrator: `integrator_conv` wraps it with
C_int (feedback from `out` to the virtual ground `inn`, `inp` at vcm) and charge packets
land on `inn`; `lora_sidecar` reuses it. AnalogIOC source: `library/ota.py`
(`ota_spice`, `bias_spice`), sizing `schematics/sizing/SIZING.md` §(a).

## Interface

`.subckt ota inp inn out vb_nc vb_pc vb_tail vdd vss`

| Port | Dir | Meaning |
|------|-----|---------|
| inp | in | non-inverting input (vcm in the integrator) |
| inn | in | inverting input (the virtual ground; feedback goes here) |
| out | out | single-ended output |
| vb_nc | bias | NMOS cascode gate, `netlist/ota.py bias()` |
| vb_pc | bias | PMOS cascode gate, `bias()` |
| vb_tail | bias | tail gate, `bias()` = VGS(18, 0.5) |
| vdd, vss | supply | `pdk_specs.vdd`, 0 |

vcm = `specs.VCM_FRAC * pdk_specs.vdd`. The bias generator is not part of this block,
but its contract is (`test/ota_bench.py`, used by every testbench):

| Rail | Driven by | Reference current |
|------|-----------|-------------------|
| vb_tail | diode-connected copy of the tail (1:1 mirror) | `specs.ota().i_tail` |
| vb_pc | diode-connected copy of the load cascode, source `ota.vsd_pm()` below vdd | `specs.I_SIDE` |
| vb_nc | fixed `ota.bias()` voltage (VGS_in and VGS_nc are both NMOS and shift together) | — |

AnalogIOC drove all three with fixed ideal voltages (`bias_spice`). That holds only at
tt/27: the tail runs in weak inversion, so a fixed vb_tail moves its current
exponentially — 1.8 µA at ss/−40 °C, loop gain 98 at tt/125 °C. The reference currents
are assumed PVT-flat.

## Topology

NMOS input pair on a weak-inversion tail, NMOS cascodes, PMOS cascoded mirror load with
its diode taken at the cascode drain (x1). 9 FETs, AnalogIOC's device for device:

| Device | Role | Nets (d g s b) |
|--------|------|----------------|
| tail | tail current | ts vb_tail vss vss |
| in_p / in_n | input pair | d1/d2 inp/inn ts vss |
| nc_l / nc_r | NMOS cascode | x1/out vb_nc d1/d2 vss |
| pc_l / pc_r | PMOS cascode | x1/out vb_pc y1/y2 vdd |
| pm_l / pm_r | PMOS mirror | y1/y2 x1 vdd vdd |

Telescopic, not 5T: 0.5 % charge transfer needs loop gain > 200 and gm/gds(12, 0.3) ~ 57
alone cannot give it.

## Specs

| Metric | Min | Typ | Max | Unit | Testbench |
|--------|-----|-----|-----|------|-----------|
| Tail (supply) current | 0.4 × `specs.ota().i_tail` | 12 | 1.5 × | µA | `tb_ota` |
| Static buffer error at vcm | | | 1 | mV | `tb_ota` |
| Closed-loop gain error (unity buffer) | | | 0.5 | % | `tb_ota` |
| 50 mV step, settle to 0.5 %, CL = `specs.c_int()` | | | 100 | ns | `tb_ota` |
| 50 mV step settle (S1 squeeze) | | | `specs.coarse_cadence()/2` = 30 | ns | `tb_ota` |
| Slew rate, 0.5 V step | 50 | | | V/µs | `tb_ota` |
| 0.5 V step, settle to 0.5 % | | | 100 | ns | `tb_ota` |
| Output range, open-loop A0 ≥ 200, single-sided | 0.9 × `specs.V_SWING` = 225 | | | mV | `tb_ota_swing` |
| tau_absorb, integrator config | | `specs.tau_absorb()` | `coarse_cadence/K_SETTLE` = 30 | ns | `tb_ota_swing` |
| o after a 3-block rising-max stream vs golden monoid | | | 5 | % | `tb_o_charge` |
| Input offset \|µ\| + 3σ, mismatch MC | | | 0.4 × `specs.V_SWING` = 100 | mV | `tb_ota_mc` |

Informational (reported, not gated): AnalogIOC's hypothesis that an LVT rebuild at the same
(gm/ID, L, ID) keeps ≥ 90 % of the SVT range (`tb_ota_swing`, DUT=sch only). Measured:
refuted — see Results.

The MC limit: the integrator resets `out` to vcm + Vos, so the usable range must hold
V_SWING plus the offset; the measured ±370 mV range leaves 120 mV, so the limit is
100 mV = 0.4 × V_SWING.

Corners: every `pdk_specs` corner × {−40, 27, 125} °C (`corners.py` defaults), VDD
nominal.

## Sizing

`specs.ota()` is the single source (gm/ID coordinates `specs.OTA_COORDS`, ID =
`specs.I_SIDE` = 6 µA per side, tail 2×), W = ID / J_D(gm/ID, L) from `docs/gmid.py`,
floored at `pdk_specs.min_w`:

| Device | (gm/ID, L) | Role of the choice | W/L [µm] | AnalogIOC hand |
|--------|-----------|--------------------|----------|--------------|
| in | (12, 0.3) nfet | moderate inversion: gm per µA for settling | 0.54/0.3 | 0.54/0.3 |
| ncasc | (10, 0.3) nfet | cascode, short L keeps its pole high | 0.42/0.3 (min_w floor; 0.37 derived) | 0.37/0.3 |
| pcasc | (10, 0.5) pfet | load cascode | 2.61/0.5 | 2.63/0.5 |
| pmirr | (10, 0.5) pfet | mirror, long L for gds and matching | 2.61/0.5 | 2.63/0.5 |
| tail | (18, 0.5) nfet | weak inversion: small Vdsat under the pair | 6.99/0.5 | 7.06/0.5 |

Bias (`bias()`): vb_tail = VGS(18, 0.5); every stacked device gets Vds = 2/(gm/ID) +
`V_HEADROOM` (0.15 V, absorbs the body effect the VSB = 0 tables miss):
vb_nc = vcm − VGS_in + Vds_in + VGS_nc, vb_pc = vdd − Vsd_pm − |VGS_pc|.

| Rail | Derived | AnalogIOC hand |
|------|---------|--------------|
| vb_nc | 1.251 V | 1.25 V |
| vb_pc | 0.307 V | 0.29 V |
| vb_tail | 0.665 V | 0.665 V |

Known limit, kept from AnalogIOC: the tail sits at Vds = ts ≈ 0.1 V (vcm − VGS_in), so the
1:1 mirror delivers ~9.3 µA instead of 12 µA (AnalogIOC's fixed vb_tail: 8.2 µA, its
"tailfix" lever). Forcing the full 12 µA (a replica held at the tail's own Vds) pushes
the tail into triode and the buffer's closed-loop gain error fails at tt (loop gain
154): at vcm = VDD/2 the stack has no headroom for the design current with the input
pair at gm/ID = 12.

## Golden model

`va/ota.va`: Io = itail·tanh(gm·vid/itail) into g_out = gm/a0, with g_out rising
exponentially outside [vlo, vdd − vhr] (the cascodes leaving saturation), output
self-capacitance cout, supply draws itail. Defaults are the spec point (gm = 72 µS,
itail = 12 µA, a0 = 500). Not modelled: bias-rail dependence, CMRR/PSRR, non-dominant
poles, mismatch.

## Results

RESULTS_TABLE
