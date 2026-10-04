# Switch conductance and terminal-capacitance sizing

**VERIFIED within the stated small-signal PDK fixture:** full terminal-current
extraction atTT27 andSS85 shows body/junction coupling dominates the off-state
TG terminal capacitance. Ideal individually floating clock gates reduce that
capacitance only about5–7% when the opposite channel terminal and bodies are
AC stiff. A complete floating-clock stack is **SPECULATIVE** and low priority;
clock isolation, retention, safe bias and added capacitance have not been built.

Source: `tb_imc_switch_admittance.py`.
The60 configurations per corner spanW=.42/.84/1.68/3.36/13.44µm,L=.15µm,
terminalA=.85/.9/.95V withB=.9V, on/off gates, and zero versus explicit
rectangular.29µm diffusion. NMOS andPMOS share the same width. The geometry
usesAD=AS=.29W,PD=PS=2(W+.29),NRD=NRS=.29/W from the installedSky130 symbol;
this is a pre-layout sensitivity, not extracted geometry. No transistor is
replaced by an ideal resistor or capacitor in the measurement.

For each configuration, three independent replicas exciteA,Gn,Gp in turn.
All six terminal voltage-source currents are saved at1MHz. Delivered current
is the negative voltage-source current. The resulting three-by-threeY matrix
uses rowsA/Gn/Gp and columns for the independently excited ports; the other
channel terminal and both bodies remain clamped. Every six-terminal
capacitive current sum passes a strict KCL check. The full complex matrix,
individual body and gate coupling, residuals and source/deck hashes are saved.

AtVDS=0 in the on state,1/Re(YAA) measures deep-triodeRon. This is the
appropriate conductance measurement for a settled sampling switch; a
saturationgm/ID table at a fixed drain voltage does not give that resistance.
The device still needs transient large-signal and end-of-phase verification.

| Equal N/P W | TT Ron | SS85 Ron | TT off-terminal C | SS85 off-terminal C | TT ideal floating-clock reduction | SS reduction |
|---:|---:|---:|---:|---:|---:|---:|
| .42µm | 30.831kΩ | 78.255kΩ | .550604fF | .584028fF | 5.889% | 4.825% |
| .84µm | 13.264kΩ | 24.046kΩ | 1.034685fF | 1.118642fF | 6.224% | 5.319% |
| 1.68µm | 5.592kΩ | 9.170kΩ | 2.002827fF | 2.187845fF | 6.440% | 5.610% |
| 3.36µm | 2.376kΩ | 3.380kΩ | 3.939147fF | 4.326491fF | 6.583% | 5.799% |
| 13.44µm | .520kΩ | .620kΩ | 15.556944fF | 17.157343fF | 6.930% | 6.198% |

All table entries use equal.9V channel terminals and full diffusion geometry.
Ron·Coff atTT falls16.98→13.72→11.20→9.36→8.09ps across these widths.
The narrow-width PDK behavior therefore makes conductance per off-capacitance
worse at minimum width. This does not establish that the widest switch is
optimal: total capacitance, clock energy, injection, topology and area still
increase, and the physical stack has a distributed capacitance penalty.

ForW=.84µm atTT, the measured1.034685fF off-terminal capacitance divides
approximately into.206904fF to the NMOS gate,.057323fF to the PMOS gate,
.398627fF to the NMOS body and.371835fF to the PMOS body. The tiny residual
opposite-terminal mutual term is model dependent and can be negative.
A biased MOS charge model need not be a network of reciprocal positive
pairwise capacitors; the analysis does not impose that assumption.

Partition the extracted matrix into signal porta and the two gatesg. With
ideal isolated gates, incremental gate current iszero, so

\[
Y_{a,\mathrm{float}}=Y_{aa}-Y_{ag}Y_{gg}^{-1}Y_{ga}.
\]

This Schur complement, including the measured gate-to-body and gate-to-other
terminal paths, gives.970291fF atW=.84µm, a6.224% reduction. Adding.2fF
of hypothetical clock-hold capacitance to each gate gives.984412fF, only
4.859% reduction; adding.5fF gives3.658%. These added capacitances are
parameter bounds, not a fabricated clock-hold circuit or priced area.

Deleting all measured gate coupling would incorrectly suggest25.54%
improvement at this point. The floating gates do not follow the signal
perfectly because their other capacitances remain. Conversely, the6.224%
result is **not a universal whole-stack upper bound**: a real native bus can
also float, changing the opposite-terminal impedance. Shared clock gates
couple several nodes and require their complete capacitance matrix. Even
perfect removal of the measured gate coupling leaves the dominant body
contribution, and an actual clock-isolation device adds more junction,
gate and routing capacitance. No full floating-clock transient is justified
as the next experiment by this local screen.

The initial analysis gate was too strict on real KCL residuals: explicit
series diffusion resistance causes numerical subtraction residuals of a few
femtosiemens while imaginary-current conservation remains near machine
precision. It also incorrectly required every off-state pairwise mutual
capacitance to be positive. Both failed analysis attempts and their decks
remain preserved. The final analysis separately records real residuals,
checks their absolute/relative numerical bound, retains strict capacitive
KCL and uses the complete matrix. TheTT result reuses an existing deck only
after exact text comparison; generator and analysis snapshots have separate
hashes. No electrical parameter or noise scale changed to pass a gate.

Artifacts:

- `build/sim/imc_switch_admittance_tt_27_kclv2.json`
- `build/sim/imc_switch_admittance_ss_85_kclv2.json`

These are deterministic small-signal measurements. They do not qualify
switching noise, gate retention, large-signal settling, mismatch, complete
PVT, routing or extracted area. The independent critic checked the delivered
current sign, matrix ordering and complex Schur elimination without finding
an algebra error.

The local Analog Design references used are sampling notes18k1 (end-of-track
triode),18m1 (resistance versus junction-capacitance sizing),18p1 (conditional
charge-injection/time-constant product),18v1 (incremental physical controls),
andgm/ID note16w1 (include intrinsic, overlap and junction terms). Their
ideal width-scaling equations are explanatory approximations; the table
above uses the actual PDK at each width and bias.
