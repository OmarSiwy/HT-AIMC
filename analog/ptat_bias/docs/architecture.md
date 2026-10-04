# ptat_bias — PTAT current reference for the softmax tail

Leaf block. Drives the `vb_tail` port of `translinear_softmax` (and the matched
`wta`/`rescale` tails) so the softmax normalisation current I_b tracks T instead of
blowing up exponentially under a fixed gate voltage (AnalogIOC measured +281 % over
27→85 C with the fixed 0.44 V bias). It fixes I_b(T), not the softmax sharpness:
beta = 1/(nUT) still drifts, and that needs the compiler's T/T0 score co-scale
(`ptat_score_gain`, AnalogIOC task #25). AnalogIOC source: `components/ptat_bias/ptat_bias.py`
(task #18); used by `top/chip2_attention.py` and `testbenches/tb_softmax.py`.

## Interface

`.subckt ptat_bias vb_tail vdd vss`

| Port | Dir | Meaning |
|------|-----|---------|
| vb_tail | out | gate of a diode-connected softmax-tail replica carrying I_ptat; tie to the softmax `vb_tail` |
| vdd, vss | supply | `pdk_specs.vdd`, 0 |

The load is a gate (no DC current); the testbenches put a copy of the softmax tail device
on `vb_tail`, drain held at the softmax shared-source voltage V_CM,in − VGS(25, 1.0).

## Topology

ΔVGS-over-R PTAT. A PMOS mirror forces K = 4 : 1 currents into two equal-W weak-inversion
NMOS with tied gates, so the 1× leg's source sits at I·R ≈ UT·ln K (bulk-referenced weak
inversion) plus moderate-inversion and DIBL excess; I ∝ T. A 1-unit PMOS copies the
current into the tail replica.

| Device | Role | Nets (d g s b) |
|--------|------|----------------|
| mpl0..3 | K mirror units feeding the diode leg | nl vb_p vdd vdd |
| mpr | mirror reference (diode, R leg) | vb_p vb_p vdd vdd |
| mpo | output copy | vb_tail vb_p vdd vdd |
| mnl | Kx diode leg | nl nl vss vss |
| mnr | 1x leg, source degenerated | vb_p nl src_r vss |
| rptat | PTAT resistor (low-tempco poly) | src_r vss (body vss) |
| mtailrep | softmax-tail replica (diode) | vb_tail vb_tail vss vss |
| mpu0, mpu1 | startup pull-up (weak, gate at vss, two series halves) | pu vss vdd vdd / su vss pu vdd |
| msn | startup sense (copy of mnl) | su nl vss vss |
| mstart | startup pull-down on vb_p | vb_p su vss vss |

Changes from AnalogIOC:

* **Startup.** AnalogIOC used `Rstart vb_p vss 50meg` — 8.7 mm of the densest sky130 poly,
  not a layout. Tried, in order:
  1. a diode `vb_p → nl` (its docstring's "Mstart"): cannot pull vb_p below nl + VT_n,
     which at −40 C is above VDD − VT_p (loop never starts), and at 125 C it leaks enough
     for 23 % line sensitivity;
  2. the self-disabling startup (mstart, msn sense, pull-up) with one gate-grounded 0.42/64.8 pfet pull-up:
     correct in simulation, but Philis draws long-L devices ~3L wide — a 196 µm cell
     outside the die;
  3. a min-L pull-up gated by nl: no long device, but it stays on at the op point
     (I_dd 6.1 µA at 27 C, 11 µA and 23 % line sensitivity at ff 125 C). Rejected.
  Kept: that startup with the pull-up split into two series 0.42/16.2 halves. At the op point
  su ≈ 2 mV, so mstart is off and draws no current.
* **`Rtie nout vb_tail 1`** (a 1-Ω wire) → one net.
* **Resistor type.** AnalogIOC's R was ideal (tc = 0). The dense sky130 poly
  (`xhigh_po`, tc1 −1.47e-3/K) makes I super-PTAT: 27→85 C slope +31.4 %, outside
  AnalogIOC's own 12..28 % band. `rptat` uses the PDK's low-tempco poly
  (`pdk_specs.res_poly_lotc`: sky130 `high_po_0p35`, tc1 ≈ +0.5e-3/K; gf180 `ppolyf_u`),
  giving +17.6 %.

## Specs

| Metric | Min | Typ | Max | Unit | Testbench |
|--------|-----|-----|-----|------|-----------|
| I_b at 27 C, tt, VDD | 0.50 | 0.58 | 0.66 | µA | `tb_ptat_bias` |
| I_b · T0/T, every corner × temp | 0.40 | | 0.80 | µA | `tb_ptat_bias` |
| PTAT exponent dln I_b / dln T (≡ AnalogIOC 27→85 C slope 12..28 %) | 0.64 | 0.92 | 1.40 | — | `tb_ptat_bias` |
| I_b change over VDD ± 10 % | | | 5 | % | `tb_ptat_bias` |
| Supply current (× T/T0: every leg is PTAT) | | | 1.25·(K+2)·0.66 = 4.95 | µA | `tb_ptat_bias` |
| Startup from a 1 µs VDD ramp, vb_tail within 1 % of I_b (0.4 mV) of DC | | | 6 | µs | `tb_ptat_bias` |
| I_b 3σ/µ, Monte Carlo (mismatch) | | | 20 | % | `tb_ptat_bias_mc` |

The I_b band and slope band are AnalogIOC's `ptat_bias.py --check` assertions. The corner
band is the ±20 % poly-R trim reach AnalogIOC relies on, plus margin. The slope partner of
$TEMP is TEMP + 58 C (TEMP − 58 C above 67 C), so at 27 C it is AnalogIOC's check unchanged.

## Sizing

In `netlist/ptat_bias.py`, W = I_B / J_D(gm/ID, L) through `docs/gmid.py`, L = 1 µm
(AnalogIOC's), I_B = 500 nA (AnalogIOC's softmax design point `I_B_NOM`):

| Device | (gm/ID, L) | Why | W/L [µm] sky130 | AnalogIOC hand |
|--------|-----------|-----|-----------------|--------------|
| mtailrep | (25, 1.0) nfet | the softmax tail coordinate (AnalogIOC VB_TAIL = VGS(25, 1.0)) | 35.99/1 | 47.4/1 |
| mnl, mnr | (25, 1.0) nfet | same device as the tail (AnalogIOC); 1× leg deep in weak inversion | 35.99/1 | 47.4/1 |
| mirror units | (18, 1.0) pfet | matching: MC 3σ was 31 % at (16) 2.7 µm, 28 % at (17) 5.3 µm, 19.5 % here; 4× this area gains nothing (the tail/replica pair dominates) | 48.53/1 | 10/1 |
| rptat | V(src_r) = [VGS(K·J) − VGS(J)]/n, n from the table's gm/ID ceiling | first-order: misses mnr's DIBL, lands I_b +21 % over I_B, inside the band | 81.2 kΩ, high_po L=69.69 | 86 kΩ ideal (trimmed) |
| mpu0, mpu1 | square law (up_cox), Vov = VDD − VGS_p(18, 1.0), I = I_B; two series halves because Philis lays a long-L device out ~3L wide (a single 0.42/64.8 became a 196 µm cell outside the die) | msn wins K:1 at the op point | 2 × 0.42/16.2 | — |
| msn | copy of mnl | sinks K·I_B once running | 35.99/1 | — |
| mstart | min W, L = 1 | switch | 0.42/1 | Rstart 50 MΩ |

AnalogIOC's 47.4 µm came from its own ngspice tables (J_D(25, 1.0) = 10.6 nA/µm);
GmIDVisualizer gives 13.9 nA/µm. Tried and dropped: core at (26, 1.0) (130 µm, m = 4):
no MC gain, line sensitivity 2.7 → 4.6 % (DIBL grows as a share of V(src_r)).

`I_B`, `GMID_TAIL`, `K` are softmax architecture constants shared with
`translinear_softmax`; they belong in `specs.py` when that block migrates.

## Golden model

`va/ptat_bias.va`: vb_tail = vb0 + tcv·(T − tnom) behind rout (the replica's 1/gm),
gated by a tanh supply-on factor and an internal RC (tau) for startup; supply current
idd0·T/T0. Defaults fitted to the transistor-level deck at tt 27/85 C. The PTAT current
itself comes from the PDK tail device in the testbench. Not modelled: line sensitivity
(the model shows 0 %), mismatch, process corners.

## Results

| Rung | Result | Measured |
|------|--------|----------|
| pre-layout (`DUT=sch`, tt 27 C) | PASS | I_b 606.6 nA; 27→85 C +17.6 % (α 0.92); line 2.74 %; I_dd 4.07 µA; startup settles 1.69 µs |
| golden model (`DUT=va`) | PASS | I_b 606.9 nA; +18.3 % (α 0.95); line 0.00 % (not modelled); I_dd 4.07 µA; startup 2.67 µs |
| layout (Philis, `--interface`, `--max-iters 4`, 2 seeds) | FAIL (tool) | kept seed 1: DRC 6 blocking, all `poly min_extension` on the three W = 0.42 devices (mpu0/1, mstart); LVS "topology mismatch: device class 109 has 1 in layout vs 0 in reference"; advanced 5/6 (IrDrop); 3080 s. Seed 2: same DRC, LVS "class 126 0 vs 1", 3508 s. The extracted netlist is device-for-device and net-for-net the source (mpl0..3 merged into one 194.12 µm device), so the mismatch is in Philis's LVS, not in the wiring — see `output/pnr/runs.txt` |
| post-layout (`DUT=pex`, seed 1) | PASS | I_b 606.6 nA; +17.6 %; line 2.74 %; I_dd 4.07 µA; startup 1.83 µs. Lumped C only (vb_p 101 fF, nl 73 fF); Philis gives no R topology, so DC equals sch. Converted with the shared `pex.py` (parallel-FET merge landed): 13 FETs from 10 extracted |
| corners (`corners.py`, DUT=sch, tt/ss/ff/sf/fs × −40/27/125 C) | PASS 15/15 | I_b·T0/T 584.6–620.1 nA (I_b 474.7 nA sf −40 C … 790.8 nA fs 125 C); α 0.88–0.95; line ≤ 3.46 % (ss −40 C); I_dd ≤ 5.20 µA at 125 C (limit 6.57); startup ≤ 1.80 µs |
| Monte Carlo (`tb_ptat_bias_mc`, tt_mm, 30 seeds) | PASS | mean 609.2 nA, σ 40.3 nA, 3σ/µ 19.9 % (limit 20 %) |

AnalogIOC reference (ideal R = 86 kΩ, its hand sizing): I_b 568.9 / 629.7 / 696.3 nA at
27 / 55 / 85 C (+22.4 %).

MC is marginal: the softmax-tail/replica pair (gm/ID 25, 36 µm²
each, owned by `translinear_softmax`'s coordinate) sets the floor — 4× the mirror area
did not move it. A bigger tail (e.g. L = 2 µm at the same gm/ID) is the lever, and it is
the softmax's call.
