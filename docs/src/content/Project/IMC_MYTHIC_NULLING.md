# Mythic's nulled columns and the retained-charge readout

Research follow-up, 2026-09-07. **Yes: the local research explicitly considered Mythic's column nulling. Its most useful transferable feature is a local balancing DAC with a shared precision reference. That deserves a fresh, complete readout experiment on the new passive accumulator.** The earlier rejection in [NULLSEEK.md](NULLSEEK.md) evaluated the old OTA/PWM path and cannot settle that experiment.

This document separates the primary patent disclosure, corrections to earlier reasoning, and a proposed charge-domain implementation. It reports no new SPICE result and does not establish that a particular patent embodiment is the production M1076/M1 circuit. Subsequent transistor results are in [the complete null-SAR experiment](IMC_NULL_SAR.md); [readout alternatives](IMC_NULL_READOUT_OPTIONS.md) examine direct fine charge injection and dynamic preamplification using primary circuit papers.

## Exact mechanism and evidence

The directly retrieved primary disclosure is [Mythic US10389375B1](https://patents.google.com/patent/US10389375B1/en), the parent of US10523230B2 cited in the notes. Its Figures 1/3/8 describe paired programmable currents feeding two summation nodes. A common-mode circuit regulates their average toward a target voltage. A local DAC supplies an adjustable differential current; a comparator and state machine search for cancellation. At balance, both nodes reach the target and the DAC state encodes the result. Earlier trials can leave substantial differential voltage. Figure 8A describes a single-ended variant that can omit the common-mode circuit. These are circuit descriptions verified against the patent text; the PDF figure images were unavailable through the browsing interface.

[Mythic US10255205B1](https://patents.google.com/patent/US10255205B1/en), Figures 1A and 4 and claims 4–9, supplies the reference-sharing detail: one global reference drives local accumulators, with current mirrors and stored charge in one implementation. Local comparator decisions select charge increments/decrements. Binary-weighted reference steps permit B-bit conversion in B cycles; the columns retain independent decisions while sharing the reference sequence. The precision reference can therefore be amortized across columns. This disclosure does not supply a measured complete-chip energy saving for our application.

For clarity, these functions have different meanings:

| Function | Physical purpose | Relevance here |
|---|---|---|
| Common-mode regulation | Keep the average of a differential pair in its operating range | Needed if the chosen input/output devices require it; include its bias and settling |
| Differential current null | Cancel the measured current with an adjustable reference | The digitization principle under discussion |
| Virtual-ground TIA | Use amplifier feedback to constrain a summing node while producing an output | One possible frontend, with a different gain/loading requirement |
| Differential/reference columns | Represent signed weights or subtract a baseline | Can coexist with nulling; consumes physical cells, wires and readout resources |
| Zero-output gating | Skip provably unnecessary operations | Requires a valid prediction or detection mechanism; a zero differential sum can still involve large currents or switched charge |

## Corrections to the earlier local analysis

The source trail is unusually direct: [MYTHIC_ARCH.md](MYTHIC_ARCH.md), [NULLSEEK.md](NULLSEEK.md), the vault's [27h10 null-balancing SAR note](</home/omare/Documents/Projects/OmarSiwy.github.io/Notes/Circuit Design/Analog Design/Analog Compute/27h10 A Null-Balancing SAR Readout Pays for Precision with Matching Instead of Standing Bias.md>), [27f9 summing-node conductance note](</home/omare/Documents/Projects/OmarSiwy.github.io/Notes/Circuit Design/Analog Design/Analog Compute/27f9 A Summing Node Escapes tau Proportional to N Only When Each Cell Adds Conductance Along with Its Capacitance.md>), and [27k6 programming-under-load note](</home/omare/Documents/Projects/OmarSiwy.github.io/Notes/Circuit Design/Analog Design/Analog Compute/27k6 Closed-Loop Weight Programming Under Realistic Array Loading Absorbs IR Drop into the Stored Weights.md>). The [paper's converter section](</home/omare/Documents/Projects/OmarSiwy.github.io/Notes/Circuit Design/Analog Design/Analog Compute/paper/sec_circuits.tex:293>) describes extended-counting conversion in the old charge-balanced integrator.

Five corrections change how we use that research:

1. **A SAR's residue is not bounded to one LSB throughout the search.** For a normalized input 0.99, a first trial at 0.5 leaves 0.49 full scale. Only the final bracket is one LSB wide. Avoiding a precise full-scale linear TIA remains useful, but early trial headroom, current and settling cannot be discarded.
2. **Charge nulling does not uniquely imply first-order incremental delta-sigma.** Unary equal-charge counting, binary charge redistribution, and hybrid coarse/fine schedules all balance charge. The old document's 256-cycle objection concerns its specified unary schedule; a B-decision SAR has a different DAC, matching and settling cost.
3. **The prior 13.6× static-power comparison was assumed arithmetic.** It is not a measured Mythic saving or a measured saving for this array. A shared reference still pays distribution energy; local mirrors still have noise, finite output resistance and mismatch; a common-mode servo still costs energy.
4. **The old mismatch ceiling and 43.3-dB acceptance premise no longer decide the new topology.** Those conclusions used the old sub-fF PWM array and an error-family-dependent quality proxy. The new 4-fF passive array, W8 reference, and full-model temporal-noise experiments have different limits. See [capacitor sizing](IMC_CAPACITOR_SIZING.md) and [full-model radix results](IMC_RADIX_FULL_MODEL.md).
5. **A ±10-mV comparator test range is not its measured resolution or temporal-noise floor.** The old NULLSEEK argument inferred an unavoidable preamplifier and standing bias from that test bar. It does not establish either requirement. Resolve input sensitivity, offset, temporal noise and metastability independently; a dynamic preamplifier can also have clocked energy without continuous standing bias.

The local conductance argument is also conditional. A lumped model can have

```text
tau_differential = (N_physical C_cell + C_wire) / (sum_cells(g_ds) + G_differential).
```

Here G_differential means an actual restoring conductance in the differential mode. An ideal common-mode servo injects equal currents into both nodes, so its injection cancels from the differential equation; its transconductance cannot simply be substituted for G_differential. Device mismatch can couple the modes and must be modeled explicitly. Moreover, physical cell capacitance remains connected while activation-dependent g_ds can change sharply: the number of conducting rows need not equal N_physical.

Holding device bias and active fraction fixed and ignoring distributed wire effects can make the ratio approach a constant. That is not a demonstration of row-independent accurate conversion: finite g_ds also makes cell currents depend on node voltage. Neither that conductance nor any corresponding current budget appears automatically in a passive capacitor bank. Programming under representative load is a calibration idea, not proof that every later activation has identical IR drop. Failure to find a segmented bitline in a patent search does not prove its absence from a shipped chip.

## Transfer to our passive accumulator

The concrete candidate is **direct charge-null SAR on the retained accumulator, with a shared reference and local signed decisions**. This is an implementation candidate for the direct-charge-injection option already identified in [the circuit convergence report](IMC_CIRCUIT_CONVERGENCE.md), rather than a demonstrated replacement.

For an isolated hold node with its complete connected capacitance C_H, define charge relative to its reset/common-mode voltage:

```text
Q_signal = C_H (V_hold - V_CM)
V_residue(k) = [Q_signal - Q_DAC(k) + Q_error(k)] / C_H
decision(k) = sign[V_residue(k) - V_offset]
```

These are design equations, assuming C_H is constant through the decisions. A local feedback controller adjusts Q_DAC and reads the residual. The held node can serve as the conversion state, potentially avoiding an additional full input sampling array or precision voltage buffer. The implementation must account for any capacitor connected or disconnected during conversion: changing C_H changes both signal gain and packet size. Destructive conversion is acceptable after the last radix accumulation, provided the following reset restores a known state.

A passive stored charge does not provide the continuously generated current of the flash circuit. Use controlled charge injection, such as `Q_packet = C_packet ΔV` or `Q_packet = integral(I_reference dt)`. Connecting a DC cancellation current without a specified integration interval would continuously change the stored result. Signed sums require bidirectional packets, differential storage, or a proved offset-binary schedule. That choice determines physical energy and common-mode limits.

Reference sharing permits simultaneous column decisions; it does not remove local conversion work. Conversely, multiplexing one comparator across columns serializes those decisions. Keep these separate:

```text
activation planes per input block: B_A
weight slices per logical weight:  S_W
completed ADC services per block:  S_W × output columns
SAR comparisons per service:      B_Y (+ redundancy/retries if used)
```

The completed-service count above presumes all activation planes are physically accumulated before reading. Reading each plane separately restores the B_A factor. Checksum columns add actual services. W8 represented as two W4 slices requires both slices; signed arithmetic does not make the second slice free.

**Nulling the final hold does not undo radix signal attenuation.** With the existing equal-capacitance recurrence, `V_hold - V_CM = g × MAC / 2^B_A`. A direct-null readout still sees that voltage and must satisfy its input-referred noise budget. Changing the readout can reduce loading and energy; it cannot recover signal-to-noise already lost in prior sharing/reset steps.

## The reference range and energy cannot be implicit

A numerical sizing check exposes an important trap. For an illustrative C_H = 0.5 pF and a total 0.5-V conversion span:

| Quantity | 10-bit readout | 12-bit readout |
|---|---:|---:|
| Voltage LSB | 488.28 µV | 122.07 µV |
| Charge LSB | 0.24414 fC | 0.06104 fC |
| Voltage step on a 4-fF injection capacitor for that charge | 61.04 mV | 15.26 mV |

However, an MSB charge step of `C_H × span / 2 = 125 fC` would require **31.25 V** on that same 4-fF packet capacitor. Sharing a precision reference does not make a single tiny capacitor cover the whole range in ten or twelve decisions. Use a physically sized coarse packet bank, controlled-current integration, additional packet repetitions, a segmented range, or another explicitly modeled mechanism. Every extra reference transition and packet counts. These numbers are a design example, not extracted capacitances from a proposed ADC.

For a complete service, account for

```text
E_service = E_hold/interface
          + sum_decisions(E_packet + E_comparator + E_local_control)
          + allocated(E_global_reference + E_reference_distribution)
          + E_reset + E_calibration/amortization + E_leakage_during_service.
```

Include both signed rails and all physical source ports before summing delivered energy. Reference startup may amortize across multiple active columns, but wire charging and local load grow with the physical distribution network. A single comparison energy cannot be reported as a complete B-bit conversion energy. Noise must include reference/packet variation, reset noise, hold droop, comparator kickback and input-referred comparator noise; deterministic DAC gain calibration does not remove their temporal component.

The current fixed-eight-plane 128-row W4 fixture costs 5.140 fJ/MAC before ADC and other missing work. At the 100-TOPS/W research target, it leaves 1.902 pJ per output; at 250 TOPS/W it leaves 366 fJ. Under the explicitly unverified assumption of duplicating that interface for W8, the 100-TOPS/W remainder is only **622 fJ per conversion**, before checksum and all other omissions; the W8 interface alone exceeds the 250-TOPS/W budget. Dividing 622 fJ across twelve decisions gives **51.8 fJ per decision for all remaining service costs**, not a latch-only allowance. Real W8 low-slice capacitance can exceed that of the W4 fixture, so even doubled energy is an accounting example, not a physical bound. These budgets and their boundaries are detailed in [the architecture search](IMC_ARCHITECTURE_SEARCH.md).

## Concrete next experiment

Build one complete native charge-null conversion on the held node and compare it against the current low-load readout candidate at the **same output error distribution and actual W8 slice loads**. Use the existing TT/SS accumulator stimulus, plus zero, cancellation, both signs, range endpoints and deliberately challenging midscale transitions. Generate every subsequent trial from the physical comparator outcome. A golden-precomputed packet sequence is useful for diagnosis but cannot verify a closed converter.

Freeze a short calibration set for zero, gain and packet weights, then test separate words. Measure complete decision codes, monotonicity, clipping, elapsed conversion time, post-conversion reset, all-source energy, and input-referred noise. Sweep global-reference fanout only after one column closes. Preserve the current accumulator's share/return timing; a cheap readout that disturbs that state invalidates the comparison.

Acceptance is a Pareto improvement after the complete modeled noise is replayed through the full model. The strongest plausible gain is **sharing precision reference circuitry while converting directly on retained charge**. Neither the old blanket rejection nor a claimed removal of all column bias is adequate evidence. The deciding result must include the entire balancing search.

## Independent check of the proposed split 6+4-bit DAC

The circuit lane subsequently proposed a concrete ten-bit split CDAC, a useful closed-search control before attempting a smaller direct-injection implementation. This is a newly proposed circuit, not a reproduced Mythic layout. It uses coarse bank `C_C = 63 C_u`, fine bank `C_F = 16 C_u` including a one-unit dummy, and bridge `C_B = 16 C_u / 15`. For C_u = 12 fF, these are 756, 192 and 12.8 fF; the capacitance seen at the coarse top node is 768 fF. The physical capacitor sum is 960.8 fF before device/wire parasitics.

Reset both top nodes A/B to V_CM while **all bottom plates, including the dummy, sample V_in**. Release both top resets before returning bottoms to V_lo; the dummy stays at V_lo during conversion. For `a = V_A - V_CM`, `b = V_B - V_CM`, charge conservation gives

```text
[ C_C+C_B  -C_B    ] [a] = [ C_C(V_lo-V_in) + Q_coarse ]
[ -C_B      C_F+C_B] [b]   [ C_F(V_lo-V_in) + Q_fine   ]

C_effective,A = C_C + C_B C_F/(C_B+C_F) = 64 C_u
fine coupling = C_B/(C_B+C_F) = 1/16
a = V_lo - V_in + V_span (16 D_coarse + D_fine)/1024
```

Keep a trial bit when `a <= 0`, subject to confirming the physical latch's output polarity. An ideal two-node solve and ten-step comparator-feedback enumeration checked all 1,024 interior codes: PASS, with maximum transfer error 2.22e-16 of span. The acquisition shift has unity gain in this ideal model.

Negative controls also behaved as predicted. Increasing only the bridge by 1% produces a 16-code-period residual with maximum 0.13846 LSB after endpoint gain/offset correction. Removing the dummy produces 0.91908-LSB maximum residual. Keeping the dummy but failing to sample the input on it changes input gain to 1023/1024. The numerical record is split_sar_ideal.json; this check used no SPICE or device/noise model.

The ideal check does not demonstrate avoidance of an additional sampling load. If the CDAC replaces the existing accumulator, its capacitances and switching states must preserve the complete accumulation recurrence; if sampled from a separate retained node, include that acquisition load. Top-node parasitic capacitance must enter both cases. In particular, extra capacitance at B changes the fine/coarse ratio. A schematic with ideal input sampling cannot demonstrate that the passive accumulator supplies the required charge with unchanged gain, noise and energy.
