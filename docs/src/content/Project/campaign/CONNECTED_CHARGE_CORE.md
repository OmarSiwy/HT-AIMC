# Native charge accumulation and conversion

This campaign tests a complete electrical connection between the repository's
strongest physical charge MAC fixture and a conversion capacitor network.
The initial test is deliberately narrower than a working ADC: it asks whether
the receiver's physical capacitance and reset history preserve the accumulated
product. ADC decisions, converter noise, reference generation and overlapping
operation require subsequent tests.

## Physical state and objective

For column j, the fixture's active array capacitance is

\[
C_{A,j}=120\,\mathrm{fF}+c_w\sum_i |w_{ij}|,
\qquad c_w=4\,\mathrm{fF}.
\]

The published fixture models the nominal equivalent of the selected weight
capacitors. It does not include the complete SRAM weight cell, every disabled
capacitor's switch parasitic or a fabricated programmable capacitor layout.
Its eight columns have native capacitances 568, 484, 304, 600, 516, 336, 444
and 424 fF. These specific W4 compiler coefficients are not the more heavily
loaded W8 format required by the strongest full-depth quality control.

Let h be held voltage relative to VCM and p the signed one-bit plane sum.
With an equal-capacitance accumulator and fully settled sharing,

\[
h_{k+1}=\tfrac12 h_k+\frac{c_wV_s}{2C_A}p_k,
\qquad h_B=\frac{c_wV_s}{C_A2^B}\sum_{k=0}^{B-1}2^kp_k.
\]

Here planes arrive least significant first, Vs=0.45 V, and h starts at zero.
Thus the useful state is charge

\[
q_B=C_Ah_B=\frac{c_wV_s}{2^B}S.
\]

The signal's weight-dependent denominator disappears in charge. Switch
injection, incomplete sharing, finite row settling and imperfect capacitance
matching perturb this identity; they remain in the actual transistor test.
The original six random calibration words and zero classes precede the three
scored workload words. The campaign must freeze new calibration before fresh
validation; these three archived words only establish integration continuity.

## Split DAC as the accumulator

A ten-bit split capacitor DAC uses coarse capacitance 63u, fine capacitance
16u including its dummy, and bridge capacitance 16u/15. A parallel top-node
capacitance C0 includes deliberate matching capacitance and any settled input
filter capacitance. Its small-signal capacitance matrix is

\[
M=\begin{pmatrix}63u+16u/15+C_0&-16u/15\\
-16u/15&16u+16u/15\end{pmatrix}.
\]

Eliminating the floating fine top gives

\[
C_\mathrm{eff}=63u+C_0+\frac{(16u/15)(16u)}{16u/15+16u}
=64u+C_0.
\]

Choosing this effective capacitance equal to CA preserves the native half
radix. During computation all bottom plates sit at VCM. Both top nodes reset
through real switches at the start of each word. Subsequent conversion changes
bottom plates while retaining the already computed charge on these capacitors;
there is no separate voltage-copy acquisition in this proposal.

The actual comparator gate contributes nonlinear, state-dependent capacitance.
The initial loading test does **not** silently subtract an assumed gate value.
It reports the uncorrected penalty first. A later calibration can explicitly
adjust matching capacitance, but must be frozen before new inputs/corners.

## Fixed charge steps across columns

It is unnecessary to scale the entire DAC unit with each column's native CA.
Keep u common and select the parallel matching capacitance

\[
C_0=C_A-64u.
\]

One fine LSB injects an effective top-node charge u ΔV/16. A coarse bit k≥4
injects u 2^(k−4) ΔV, and a fine bit k<4 injects u 2^k ΔV/16. All ten weights
therefore form the same binary charge sequence. Their voltage responses are
divided by CA, just as the accumulated signal is:

\[
\frac{h_B}{\Delta V_\mathrm{LSB}}
=\frac{16c_wV_s}{u\Delta V\,2^B}S.
\]

This ideal ratio is independent of the programmed column denominator. It is
an analytical mechanism, not proof of a complete architecture's novelty or
accuracy. Native capacitance matching still needs a realizable programmable
bank and trim. Its maximum physical area, code storage and parasitics must be
counted even when the selected capacitance is small.

The capacitance budget is a hard constraint: 4-fF DAC units plus a 60-fF filter
need at least 316 fF and do not fit the fixture's 304-fF column. A 3.75-fF unit
leaves 4 fF of parallel matching capacitance in that column. Larger comparator
gate capacitance can consume this remaining margin. The physical split network
also costs 16.0667u more capacitance than its effective value; at u=3.75 fF
this is 60.25 fF per column before any duplicate pipeline bank.

## Initial experiments

tb_imc_connected_core.py
reuses the archived 128×8 physical row network and analysis. Only Cacc0 is
replaced; the other seven loaded columns serve as controls. The generated
original and modified decks, imported source snapshots, simulator identity,
trace hashes and numerical assertions are saved under
`build/campaign/connected_core/`.

The first three cases are: ideal-bottom split capacitors with a real fine-node
reset; real midpoint/high/low transmission gates held in compute state; and
those gates plus a 60-fF/8-kΩ filter and a physical StrongARM held in reset.
Every added device uses the original metered supplies/references. Ideal
digital controls, row references and capacitor models remain explicit limits.
The original product gates are RMS <0.25 MAC and max <1 MAC after permitted
calibration. No ADC conversion, PVT yield or complete-chip energy is implied
by passing them.

The initial TT results are:

| Physical connection on column 0 | Column-0 RMS / max product error (MAC) | Outcome |
|---|---:|---|
| Split capacitors, ideal VCM bottoms, real fine reset | 0.009906 / 0.014507 | VERIFIED on the archived cohort |
| 0.42-µm bottom reference TGs | 5.017663 / 5.870666 | FAILED |
| Same TGs, filter and reset-state comparator | 3.915408 / 4.639534 | FAILED |

The first case's emitted original deck is byte-identical to the freshly
reproduced native baseline. Its complete interface delivery is 4.52312 fJ/MAC
versus 4.49981 fJ/MAC before the fine reset was added; the mean word time
remains 366 ns. These are the eight-column fixture's ideal-port delivery
figures, not fabricated-chip energy.

The failed TG case has a directly visible settling error: its largest coarse
bottom plate remains as much as **6.509 mV** away from VCM immediately before
the 15.6-ns sharing interval ends. Its RMS bottom error across all planes at
that instant is 1.553 mV. With the filter/comparator case's smaller DAC unit,
those values are 5.360/1.278 mV. Subsequent settling cannot restore the exact
charge division that should have occurred while the array and accumulator
were connected. `bottom_settling_diagnostic.json` records these observations.
The next controlled experiments widen the reference TGs, reduce the portion
of total accumulator capacitance assigned to the DAC, and combine both.

## Prior art and falsification

Stationary MAC charge and reuse of compute capacitors as a SAR DAC are already
demonstrated in [CR-CIM's author manuscript](https://arxiv.org/pdf/2302.06463).
This campaign must evaluate a more specific implementation and benefit; it
cannot claim the generic reuse principle as new. The broader collisions and
native-versus-normalized performance boundaries are recorded in
[the campaign literature map](SOTA_EVIDENCE.md).

The main rejection mechanisms are unequal effective capacitance, comparator
kickback into a floating signal but stiff reference, finite filter settling,
fine-top reset injection, mismatched bridge ratio, charge leakage during the
conversion interval and a converter precision/range incompatible with the
full model. Pipeline gain additionally requires two independent resident
states and real overlap; an isolated sample-and-hold schedule is insufficient.
