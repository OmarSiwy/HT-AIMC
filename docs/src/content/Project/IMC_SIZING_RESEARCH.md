# Concrete passive-MAC sizing experiment

Date: 2026-09-07. Research testbench: tb_imc_sizing_research.py. Artifacts: imc_sizing_research.json. This supplements [IMC_CIRCUIT_RESEARCH.md](IMC_CIRCUIT_RESEARCH.md) and [IMC_CHARGE_AVERAGE_EXPERIMENT.md](IMC_CHARGE_AVERAGE_EXPERIMENT.md); it changes no operational circuit.

**The most complete tested candidate is a 128-row × 8-column signed passive macro with physical bit-significance accumulation.** On three saved FFN-down input words, a variable seven/six/five-plane schedule with a 15.6-ns sharing aperture achieves 70.13-dB deterministic transfer at TT/27°C and 62.47 dB at SS/85°C; both pass the original full-word error screen. Mean A8 word time is 366 ns, and ideal-port positive delivery is 4.4998/4.5872 fJ/MAC, before ADC, memory-control and regulator costs. It uses four-fF unit capacitors, 0.42-µm hybrid row switches, 3.36-µm matched reset switches and 6.72-µm sharing TGs. The faster 318-ns schedule passes TT but fails SS. This is a schematic-level W4 result with ideal capacitors and incomplete parasitics; it does not establish 100 or 250 TOPS/W for a chip.

The concrete improvements are physically shared row drivers, legal charge accumulation before conversion, matching then resizing the reset switches, and removing unused high activation planes. They were tested incrementally with real Sky130 MOS models, failed size/timing candidates and a capacitor-ratio negative control. The converter/noise budget and full weight-storage implementation remain decisive.

## Candidate circuit and physical boundary

The present weight_tile.py repeatedly transfers charge through a biased OTA, uses a nominal 0.15-fF unit, 4-fF ballast per populated bank, and a 500-fF column ballast. Its compile-time capacitor selection is not a programmable memory implementation. The initial sizing experiment instead directly connects the tops of sixteen weighted capacitor banks to a passive output node. Each bottom plate selects common mode, a high reference, or a low reference through a **real complementary Sky130 transmission gate**. The column reset also uses a real TG. There is no per-weight top ballast or standing OTA bias.

The initial weight vector is `[1,2,3,4,5,6,7,8]` repeated twice: sixteen **fixed unsigned 4-bit weights**. Inputs are signed ternary activation slices, `x_i ∈ {-1,0,+1}`. A zero-input bank stays clamped to common mode during evaluation, rather than floating and changing the denominator. The 4-bit banks are nominal lumped equivalents of binary-weighted unit-cap combinations. This initial fixture does not contain SRAM, programmable coefficient switches, or signed-weight routing. The later distinct-column matrix experiment described below adds complementary row buses and fixed signed-weight routing, with their energy included. Runtime programmable storage remains missing throughout.

For ideal capacitors, charge conservation gives

```text
C_total = C_load + C_unit * sum(w_i)
V_out - V_cm = C_unit * V_excitation * sum(w_i*x_i) / C_total
```

The program uses 1.8-V clock/well supply, 0.9-V common mode, and a 120-fF output load representing the existing fine converter's nominal CDAC capacitance. That load is initially just a capacitor; it is not an ADC. For the 8-fF unit, the signal capacitance is 576 fF and the total is 696 fF before transistor parasitics. Excitation ±0.45 V uses references 0.45 and 1.35 V. The measured calibrated gain is 5.142 mV per integer MAC unit, versus 5.172 mV ideally.

The capacitor values are ideal SPICE elements. **4 fF is a MOM research target, not a demonstrated legal Sky130 MIM device.** The existing 0.15-fF unit has no validated physical implementation. The 8/16-fF experiments avoid relying on that extreme value but still require a legal capacitor generator, extraction and matching data. MOS instances use the repository's W/L-only generators; explicit diffusion area/perimeter geometry is absent, with zero AD/AS/PD/PS defaults visible in the expanded models. Intrinsic compact-model capacitance is represented; extracted junction geometry and routing capacitance are not. The public PDK distinguishes MIM and VPP devices; a generic capacitance density does not validate a minimum capacitor geometry. [Sky130 device/rule documentation](https://skywater-pdk.readthedocs.io/en/main/rules/periphery.html).

The leading scalable precedent is PICO-RAM's reuse of local capacitors for DAC, MAC, significance combination and readout, together with storage multiplexing. Its published 65-nm prototype uses approximately 4-fF MOM capacitors and a cluster of nine SRAM cells sharing a MAC unit. That is evidence for a different physical organization; it does not validate this Sky130 testbench or transfer its measured efficiency. [PICO-RAM, Sections III–V](https://arxiv.org/html/2407.12829v1).

## What the sizing sweep actually measures

Each candidate runs three calibration inputs and twenty held-out inputs: independent ternary vectors, exact signed cancellation, and ±1-MAC sparse perturbations. The calibration fits one affine column gain/offset. Acceptance is **maximum error <0.25 MAC and RMS error <0.1 MAC** on held-out patterns. These are circuit screening thresholds, not established LLM accuracy thresholds. TT/27°C screening varies equal NMOS/PMOS TG widths and timing; all TG lengths are 0.15 µm. The reset TG uses four times the row-TG width.

The complete activation-plane period is

```text
cycle = 2*evaluate reset + evaluate + 4 ns guards/edges + 2*evaluate return
      = 5*evaluate + 4 ns
```

Thus “14 ns” means the entire reset/evaluate/return cycle, with a 2-ns evaluation aperture. It does not mean a 14-ns aperture repeated across three phases. The test includes a return to common mode; it does not bill only the favorable charging edge.

| Row TG Wn=Wp (µm) | Evaluation / full cycle (ns) | Held-out RMS / maximum (MAC units) | All-port positive delivery (fJ/plane) | Result |
|---:|---:|---:|---:|---|
| 0.42 | 2 / 14 | 1.0568 / 1.7954 | 164.44 | Fail |
| 0.42 | 5 / 29 | 0.1259 / 0.3784 | 167.66 | Fail |
| 0.42 | 10 / 54 | 0.0065 / 0.0216 | 167.97 | Pass; low energy |
| 0.84 | 2 / 14 | 0.2011 / 0.5761 | 221.98 | Fail |
| 0.84 | 5 / 29 | 0.0036 / 0.0117 | 222.43 | Pass; intermediate |
| 1.68 | 2 / 14 | 0.0074 / 0.0239 | 325.95 | Pass; lowest energy×delay in this grid |
| 3.36 | 2 / 14 | 0.0007 / 0.0012 | 529.62 | Pass; extra accuracy at greater energy |

The 1.68-µm point improves the full cycle by 3.86× for 1.94× the port-delivery energy compared with the 0.42-µm passing point. This is a Pareto tradeoff: one cannot call it both the minimum-energy and maximum-throughput design. The sweep does not establish a global optimum over all widths, circuits and schedules.

At 1.68 µm and the same 14-ns cycle, SS/85°C gives RMS/maximum 0.0719/0.2126 MAC and 338.15 fJ; FF/−20°C gives 0.0007/0.0010 MAC and 313.02 fJ. The supply remains 1.8 V in all three cases; this is not a complete PVT characterization. There is no transistor mismatch Monte Carlo.

Two falsifiers pass as experiments: a +25% error on the first capacitor bank leaves 0.2314-MAC RMS and 0.3142-MAC maximum error after scalar calibration, failing the transfer gate; doubling temporal resolution from 0.1 to 0.05 ns changes nominal RMS error by 0.0007 MAC and delivered energy by 0.06%. The first shows scalar calibration cannot repair individual coefficients. The second supports numerical convergence at the selected point, not all possible transient conditions.

## Energy accounting and activation precision

Every ideal voltage-source port is included: VDD/well bias, common mode, both excitation references, and every true/complement clock. Supply current follows ngspice's sign convention. Two quantities are recorded:

```text
net energy       = sum_ports integral(-V_source * I_source) dt
positive delivery = sum_ports integral(max(-V_source * I_source, 0)) dt
```

The distinction is material. For the 1.68-µm, 8-fF, ±0.45-V nominal point:

| Port/phase boundary | Energy (fJ/plane) |
|---|---:|
| All-port net energy | 77.07 |
| VDD/well positive delivery | 55.72 |
| Reference positive delivery | 156.02 |
| Clock positive delivery | 114.21 |
| Total positive delivery | **325.95** |
| Initial reset phase, positive delivery | 10.37 |
| Evaluation phase and guards, positive delivery | 210.67 |
| Return phase, positive delivery | 104.90 |

A signed net VDD/clock contribution can be negative because capacitive current returns energy to an ideal source. Using only net VDD would therefore be particularly misleading. Positive delivery is a transparent **non-recovering port-energy proxy**, not measured regulator input energy: real decoupling can reuse some returned charge, while physical clock drivers and reference generators add loss, bias and distribution costs. Neither proxy is full-chip energy. Startup and the three calibration cycles are excluded from steady-state averages; actual recalibration and startup must be charged separately.

For an 8-bit activation, a simple bit-plane implementation needs at least eight such cycles and a defined sign convention. At the 14-ns point this is **112 ns before ADC service and reconstruction**, and 8×325.95/16 = **162.97 fJ per A8×W4 MAC for the one-column interface alone**. It has not beaten a full-chip Mythic efficiency target. With separately digitized planes it also needs eight actual ADC conversions per output. A single final conversion requires a physical significance accumulator.

The weighted banks make `C_total` depend on programmed weights. An equal-capacitor recurrence cannot assume an identical column capacitance after reprogramming. It needs programmable normalization/accumulation capacitance or a fixed-total-capacitance organization, for example always-connected unit caps on binary weight planes with PICO-style significance combination. The SRAM, selections and accumulator must be built and measured before eliminating seven ADC conversions in a throughput model.

## Capacitor/swing/noise tradeoff

At Wn=Wp=1.68 µm and a 14-ns full cycle:

| Unit C (fF) | Excitation magnitude (V) | Gain (mV/MAC) | Delivered energy (fJ/plane) | Deterministic transfer | Conditional 9-bit SNR (dB) |
|---:|---:|---:|---:|---|---:|
| 4 | 0.0675 | 0.655 | 178.88 | Pass | 23.86 |
| 4 | 0.25 | 2.427 | 216.13 | Pass | 35.23 |
| 4 | 0.45 | 4.368 | 263.44 | Pass | 40.33 |
| 8 | 0.45 | 5.142 | 325.95 | Pass | 41.78 |
| 16 | 0.25 | 3.134 | 302.96 | Fail | 29.20 |
| 16 | 0.45 | 5.642 | 444.53 | Fail | 37.87 |

The noise column is an explicit analytical scenario: 1-V ADC span, nine ideal quantizer bits, 0.2-mV RMS ADC noise, 100-µV RMS excitation-amplitude uncertainty, one reset `kT/C_total` term, measured deterministic residual and zero capacitor mismatch. The JSON also sweeps eight/ten bits and independent 0.5%/1% unit-cap mismatch. These noise values are **assumptions**, not transient-noise measurements. Additional row-switch noise and correlations, comparator offset/kickback, reference/common-mode covariance, leakage, interconnect coupling and supply fluctuations remain unresolved. The subsequently tested physical latch must not inherit the assumed 0.2-mV noise as a measurement.

The charge-equivalent alternative `4 fF × 67.5 mV = 0.15 fF × 1.8 V` retains the old nominal charge packet but loses output gain on the larger total capacitance. Its low net energy of 1.25 fJ becomes 178.88 fJ after positive clock/reference delivery is counted, and its conditional SNR is poor. Larger legal capacitors plus tiny excitation is therefore not a free repair for the old capacitor. The highest capacitor value also needs more settling at the fixed switch width; nominal capacitance alone does not improve accuracy.

The noise logic follows the user's notes 27g2 (sampled thermal floor), 27g3 (compute SNR), 27h5 (bit-plane reconstruction), 27i1 (ratio matching) and 27i4 (capacitive significance combination). For signed sums, the linearized independent unit-mismatch contribution used here is

```text
variance(error in MAC units) = sigma_unit^2 * sum_i w_i * (x_i - a)^2
a = C_unit * sum_i(w_i*x_i) / C_total
```

This includes the perturbation of the denominator. It avoids asserting a universal relative-error improvement for cancellation-heavy dot products. Any independent-error variance model still needs validation against extracted capacitance covariance and full-model operands.

## gm/ID decision

The actual sizing lookup tables are real nominal Sky130 sweeps at VDS=0.9 V and 27°C. For an NMOS input device at L=0.3 µm and fixed gm=72 µS:

| gm/ID (V⁻¹) | ID (µA) | W (µm) | VGS (V) | Intrinsic gm/gds |
|---:|---:|---:|---:|---:|
| 8 | 9.0 | 0.375 | 0.857 | 46.6 |
| 12 | 6.0 | 0.544 | 0.778 | 57.0 |
| 16 | 4.5 | 0.910 | 0.721 | 62.7 |
| 20 | 3.6 | 2.166 | 0.660 | 64.2 |

Moving the existing OTA input pair from gm/ID=12 to 16 could reduce its required branch current by 25% at fixed gm, while increasing width 1.67×. It changes parasitic loading, overdrive/headroom, input range, flicker noise and bias matching; it is not a demonstrated OTA improvement. The passive alternative removes the standing input-pair current from this phase altogether, but spends switching and converter energy instead. TGs operate predominantly in triode, so these saturation gm/ID tables do **not** directly size their on-resistance. The fresh TG transient sweep is the appropriate evidence for the actual switch-size choice.

## Larger load and physical readout checks

The 128-row, one-column endpoint keeps the same repeated weight-code distribution and switch width. At 8-fF units and a 14-ns cycle it passes TT with RMS/maximum 0.0241/0.0495 MAC, consuming 2419.93 fJ of positive delivery per activation plane. This is 151.25 fJ per reconstructed A8 MAC before ADCs, storage and reconstruction. More rows improve amortization of some overhead but do not make the repeated row clocks disappear.

An identical-column loading test multiplies signal/load capacitance by sixteen and supplies sixteen parallel physical reset TGs while sharing the row drivers. This electrical symmetry reduction is valid only for identically programmed/loaded columns. It tests load/fanout, **not eight/sixteen independent matrix outputs**. The original 1.68-µm/14-ns point fails badly, at 13.81-MAC RMS. Increasing the row width to 6.72 µm and the full cycle to 44 ns passes at 0.0017-MAC RMS, but consumes 4527.87 fJ per 16×16 plane: 141.50 fJ/A8 MAC before conversion. Wider shared drivers largely consume the hoped-for amortization in this example.

The first lumped-reset deck exceeded the PDK's device-width bins; it was corrected to one real reset TG per column. A 32-column extreme subsequently hit a ngspice startup timestep failure and is **not a result**. The script now rejects incomplete transients explicitly even if ngspice's batch process returns exit code zero. These solver failures are not silicon failures, and neither should be silently converted into performance points.

The real StrongARM generator was also tested against a held 696-fF input capacitor, matched 8-kΩ/60-fF input filters, and 10-fF loads on both latch outputs. A real TG acquires the held input. A separate zero-input acquisition calibrates its deterministic injection offset; the following tests start at approximately ±0.977 mV, half an LSB for a nine-bit, one-volt quantizer. Nine repeated decisions at the **same threshold** expose cumulative kickback. This is not a SAR conversion, since no changing CDAC or bit decisions are implemented.

| Latch input-pair width | Corner / clock edge | Initial differential | Nine decisions | Held-node drift | Positive energy per decision |
|---|---|---:|---|---:|---:|
| Existing 7 µm | TT / 2 ns | −0.977 mV | All correct | −1.238 mV | 120.55 fJ |
| Existing 7 µm | TT / 2 ns | +0.980 mV | Only first correct | −1.239 mV | 125.87 fJ |
| 3.5 µm | TT / 2 ns | −0.977 mV | All correct | −0.662 mV | 110.84 fJ |
| 3.5 µm | TT / 2 ns | +0.980 mV | All correct | −0.662 mV | 130.66 fJ |
| Existing 7 µm | SS/85°C / 2 ns | +0.980 mV | Only first correct | −1.489 mV | 130.70 fJ |

At the original 7-µm input width, changing the clock edge to 0.2 ns does not repair the repeated positive-input decisions in this fixture. Halving the **input pair only** is a concrete candidate for lower kickback; it is not established as a lower-noise or lower-offset latch. The nominal positive case actually spends more measured energy despite the smaller input pair. Transistor mismatch, noise, common-mode range, reference matching, late/metastable decisions and a complete ADC sequence must decide that tradeoff.

Decision energy integrates every ideal source over the repeated-read interval and divides by nine. Acquisition was performed physically but its initial charging energy is outside this interval, so this is a readout-only energy figure. Nine decisions alone are approximately 1.0–1.2 pJ with the fixture's output loads; reference generation, CDAC switching and controller energy are additional. Repeating nine such decisions for each of eight activation planes is not a low-energy ADC by assertion.

## Independent signed columns and real A8 operands

A subsequent probe implements **sixteen rows and eight separate output nodes**, with independently selected signed weight banks. Each row has complementary positive/negative buses. Real TGs drive both buses from shared 0.45/0.9/1.35-V references; a positive coefficient connects to one bus and a negative coefficient to the other. Each column has its own 120-fF load and reset TG. This measures physical coupling through shared row drivers with distinct outputs, rather than using the identical-column simplification above. Coefficients remain fixed capacitor connections; runtime SRAM/programming/selectors are absent.

With independent random signed weights −7…7, 4-fF units, six random ternary calibration vectors and twenty-one held-out vectors:

| Row Wn=Wp | Complete plane / A8 time | Delivered interface energy per A8 MAC | Held-out RMS / maximum (MAC) | Corner |
|---:|---:|---:|---:|---|
| 0.42 µm | 44 / 352 ns | 40.29 fJ | 0.0327 / 0.1030 | TT/27°C |
| 0.84 µm | 29 / 232 ns | 45.55 fJ | 0.0102 / 0.0303 | TT/27°C |
| 1.68 µm | 14 / 112 ns | 55.35 fJ | 0.0203 / 0.0556 | TT/27°C |
| 0.42 µm | 44 / 352 ns | 40.55 fJ | 0.2172 / 0.7325; fail | SS/85°C |
| 0.42 µm | 164 / 1312 ns | 40.74 fJ | 0.0033 / 0.0117 | SS/85°C |

This is a better array-level candidate than the high-capacitance identical-column loading case. It also illustrates why one operand distribution cannot establish every matrix's energy or timing.

The next replay uses the **first sixteen input channels and first eight output rows** of `scripts/compiler/out/programming/ffn_down.npz`, with saved `xq` token indices 6, 7 and 8 from `scripts/compiler/out/acts/ffn_down.npz`. Both files' SHA-256 fingerprints, exact matrices, inputs and recovered outputs are stored in the JSON. This fixed first block has mean |W|=0.84375 and 1.3542 active magnitude bits per eight-bit input, or 16.93% activation-plane density. It is smaller/sparser than the global artifact averages; it was not selected by an energy search.

MAC denominators count the original dense matrix dimensions once per reconstructed A8 word; bit planes and repeated comparisons do not become additional useful MACs. The measured cost depends on the compiled weight/input sparsity. Zero or inactive coefficient capacitors are absent from this fixed-programming probe, so it is not a programmable worst-case loading or storage-area specification.

Every input is decomposed into eight signed-magnitude planes, simulated in sequence, then reconstructed digitally with its exact binary significance. All eight cycles remain present even when the highest planes are zero. The following **complete A8 interface** results include all source ports but still exclude ADCs, weight-storage controls, regulators and digital reconstruction:

| Switch choice | Corner / A8 time | Delivered interface fJ/MAC | Reconstructed A8 RMS / max error | Deterministic SNR |
|---|---|---:|---:|---:|
| TG at all three references | TT / 352 ns | 16.78 | 0.0548 / 0.1246 MAC | 56.01 dB |
| PMOS at 1.35 V, NMOS at 0.45 V, TG at 0.9 V | TT / 352 ns | 16.57 | 0.0538 / 0.1224 MAC | 56.17 dB |
| Same hybrid | SS/85°C / 1312 ns | 17.59 | 0.00517 / 0.01044 MAC | 76.51 dB |

The hybrid removes only the weak parallel endpoint branch, preserves the ±0.45-V excitation, and selects device polarity from the **actual reference**, including on the complementary bus. It saves only 1.23% of positive delivery here, despite removing some transistor gates. A device-count reduction is not an equal energy reduction. Acquisition samples precede the row-switch return; the later physical accumulator experiment separately verifies retention through those edges.

## Physical binary significance accumulation

The array was extended with a real sharing TG and a held capacitor per column. With `C_acc=C_load+C_unit*sum(|w_i|)`, an ideal equal-capacitor share implements `h_next=(h+z_bit)/2`. Starting from zero and applying bits least-significant first yields `h_B=g*(W*x)/2^B`. The accumulator resets once per complete word; it disconnects before the array's bottom-plate return and reset. The final sample is taken **after those final return/reset edges**, so off-switch coupling is included. Six complete-word calibration stimuli are separate from the three saved held-out words.

The first nominal-capacitance experiment used a 0.42-µm accumulator reset TG but the array's 6.72-µm reset TG. Scalar output calibration left approximately 1.08-MAC RMS error. Matching the reset TGs at 6.72 µm on both nodes substantially restores the intended coefficient ratio without a fitted capacitor trim. Equal nominal capacitor values alone were insufficient; the switch environment also needed matching.

| Accumulation | Corner | Delivered interface fJ/A8 MAC | Total word time | Reconstructed RMS / max error | Deterministic SNR |
|---|---|---:|---:|---:|---:|
| Eight physical planes, matched resets | TT | 21.10 | 424 ns | 0.03615 / 0.08858 MAC | 59.62 dB |
| Same, intentionally +1% C_acc | TT | 21.10 | 424 ns | 0.52089 / 1.26759 MAC | 36.45 dB |
| Five physical planes, matched resets | TT | 14.70 | 265 ns | 0.01117 / 0.02710 MAC | 69.83 dB |
| Five physical planes, matched resets | SS/85°C | 15.55 | 865 ns | 0.24992 / 0.60967 MAC | 42.83 dB |

Five planes suffice for these three particular saved words, whose maximum magnitude is 25; the first word actually needs only four. Fewer planes also require changing the digital recovery scale. The five-plane values must be compared against a five-plane independently converted baseline, not against eight arbitrarily retained cycles.

**This is physical charge-domain significance accumulation before a planned final readout. No ADC is instantiated in this experiment.** The circuit demonstrates that the intermediate eight/five ADC operations are mathematically unnecessary for this fixed programming. It does not demonstrate the quality, speed or energy of the remaining ADC. Programmable weights require a matching per-column accumulator capacitance or a fixed-total-capacitance organization; the ideal programmable trim and runtime selectors have not been built.

The absolute final signal is small. With eight planes, the measured signal gain is roughly 33–46 µV per integer A8 MAC, so a 0.2-mV input-referred ADC noise assumption corresponds to several MAC units. Five planes increase that gain about eightfold. Significance accumulation saves ADC operations while demanding a careful final noise/range budget; the paper's converter number cannot simply be attached to this held node. Capacitor mismatch, sampled sharing noise and comparator/reference noise remain absent from deterministic SPICE. [Architecture-side noise/range budget](IMC_ARCHITECTURE_SEARCH.md) should be used alongside the physical result.

A further physical sizing refinement reduces **both** matched reset widths from 6.72 to 0.84 µm. At the same five-plane schedule, TT RMS/max remain 0.01546/0.03568 MAC (67.00 dB), while positive delivery drops from 14.70 to **5.95 fJ/A8 MAC**, with the same 265-ns word time. The fitted held-node offset falls from roughly 12–15 mV to 1.2–1.7 mV. This is a substantial measured reduction of reset-clock loading; it is not a technology-node extrapolation. Its storage/ADC/noise boundaries remain unchanged.

The fair earlier five-plane separately read interface, using 6.72-µm array resets, costs 11.37 fJ/A8 MAC and 220 ns. Thus adding the original matched 6.72-µm accumulator costs 3.34 fJ/MAC and 45 ns while reducing five planned conversions to one. The newer 0.84-µm reset must also be applied to the independently read baseline before claiming an accumulator energy saving. Intermediate-conversion energy has not been measured here.

That matched baseline was then measured: with 0.84-µm resets it consumes **3.7405 fJ/A8 MAC and 220 ns**, versus **5.9466 fJ/A8 MAC and 265 ns** with the same reset size and physical accumulator. The extra analog accumulation costs **2.2061 fJ/MAC and 45 ns** and can remove four planned conversions per output. This is the useful like-for-like trade; neither case includes ADC energy. The converter saving must exceed this measured interface overhead while maintaining accepted accuracy.

The final small-array schedule physically applies **four, five and five planes** to the three respective saved words. It changes the output scale with the plane count and measures a zero-input offset separately for B=4 and B=5. Those two extra zero-word calibrations are additional to the six complete-word gain/offset calibration vectors. This is an explicit calibration requirement, not a correction fitted on held-out outputs.

| Dynamic-B physical accumulator | Energy (fJ/A8 MAC) | Word times / mean | RMS / max error | Deterministic SNR | Screening |
|---|---:|---|---:|---:|---|
| TT/27°C, 8-ns evaluation | **5.7447** | 212, 265, 265 / **247.33 ns** | 0.01468 / 0.03568 MAC | 67.45 dB | Pass |
| SS/85°C, 8-ns evaluation | 5.8381 | 212, 265, 265 / 247.33 ns | 0.28351 / 0.70587 MAC | 41.74 dB | Fail |
| SS/85°C, 32-ns evaluation | 5.8412 | 692, 865, 865 / 807.33 ns | 0.25718 / 0.65634 MAC | 42.58 dB | Fail |

The reconstructed-word screen is RMS <0.25 MAC and maximum <1 MAC. Slowing the SS case only modestly improves error, so its remaining issue is not purely acquisition settling. The small-array candidate has a nominal deterministic result; it does **not** have a closed PVT, sampled-noise or full-model accuracy guarantee. The reference/noise study indicates why simply adding converter bits cannot resolve all remaining error. A broader workload requires its own bit counts; this three-word block does not justify five planes globally.

The first **128-row × 8 independent signed-column** complete-word replay uses the first 128 FFN-down channels, four-fF units, 0.42-µm hybrid row drivers, 0.84-µm matched resets and 6.72-µm sharing TGs. Eight planes take 424 ns and consume 4.3965 fJ/A8 MAC, but full-word RMS/max error is **2.6422/7.4872 MAC (34.31 dB)**. It fails accuracy before an ADC is added. Its low interface-energy number is therefore not an accepted architecture performance point.

Changing **only the matched reset widths to 3.36 µm** restores the 128-row deterministic transfer: **0.04514-MAC RMS, 0.08930-MAC maximum, 69.66 dB**, at **5.1403 fJ/A8 MAC and the same 424 ns**. This isolates a useful larger-array sizing repair. It does not establish PVT or ADC performance. The three actual words have maximum magnitudes 127, 32 and 25, so their legal minimal significance schedules are seven, six and five planes respectively.

That shorter schedule was simulated at TT and SS with nine calibration words (six gain-calibration words plus zero-input words for each of B=7/6/5):

| 128×8 physical dynamic accumulation | Positive interface energy | Word times / mean | Full-word RMS / maximum | Deterministic SNR |
|---|---:|---|---:|---:|
| TT/27°C | **4.4999 fJ/A8W4 MAC** | 371, 318, 265 / **318 ns** | 0.05741 / 0.11807 MAC; pass | 67.57 dB |
| SS/85°C | 4.5878 fJ/A8W4 MAC | 371, 318, 265 / 318 ns | 0.93095 / 1.75398 MAC; fail | 43.37 dB |

The TT mean positive delivery per activation plane is 767.98 fJ: 314.79 fJ from ideal clock ports, 302.46 fJ from reference ports, and 150.73 fJ from the well/supply port. Individual row/reset/sharing clock groups were not separately exported; those cannot be reconstructed from the aggregate trace without another transient run. The SS failure remains visible rather than being averaged into the nominal result. Supply voltage variation, noise, mismatch and layout extraction remain untested.

The saved slow/hot traces identify a separate timing constraint: the sharing TG remains fully on for only 7.6 ns, even when the row evaluation time is increased. In the last 0.9 ns before sharing ends, SS accumulator voltage still moves at 10.41 µV/ns RMS (42.61 µV/ns maximum), versus 0.70/3.53 µV/ns at TT. The array-to-accumulator voltage difference is already small; the remaining motion comes from their common connection to the settling row network. Calibration-only tail fits suggest roughly 1.69–2.06-ns time constants. These fits motivate a fresh transient run; they are not accepted transfer results.

The dedicated `--share-settling` experiment changes only `share_hold_ns` from its 7.6-ns default to 15.6 ns. It shifts sharing-off, the final observation, bottom-plate return and reset together, preserving their guards. Row evaluation stays at 8 ns and both resets stay at 3.36 µm. The period becomes 61 ns, giving seven/six/five-plane word times 427/366/305 ns. A generated-deck audit confirms identical 1,344 physical-component lines, 778 voltage ports and all clock voltage sequences (774 ports, 174,200 PWL breakpoints) against the original SS deck. Both full-word error thresholds remain unchanged. The CLI records SS first and runs TT only if SS passes; every voltage-source port still contributes to energy.

The fresh SS/85°C result **passes**: full-word RMS/max error falls to **0.10333/0.22338 MAC**, or **62.47 dB**, at **4.58724 fJ/A8W4 MAC and 366-ns mean word time**. Its positive delivery is 782.89 fJ/plane, split into clock 329.97 fJ, reference 290.79 fJ and well/supply 162.13 fJ. Energy changes by only −0.012% relative to the failed 7.6-ns-share SS run, below a meaningful efficiency improvement at this integration resolution. The real benefit is 9.0× lower RMS error for 15.1% longer word time, with the original device sizes. This validates the settling diagnosis at the tested corner; noise, mismatch, supply variation and extracted parasitics remain absent.

The corresponding TT/27°C confirmation also passes at **0.04277-MAC RMS, 0.07934-MAC maximum and 70.13 dB**, with **4.49981 fJ/A8W4 MAC** at the same 366-ns mean. Thus one physical size/schedule combination passes both tested process/temperature corners. The run does not change or validate the separate held-comparator fixture, whose SS positive-input sequence still fails. The two fresh transients took 239.64 and 271.06 seconds, including analysis, with the default Sparse solver. Their complete outputs are under `share_settling_repair` in the JSON; the original failed shorter-share data remain intact.

## Readout receiver sizing with its energy included

The final bounded readout experiment replaces arbitrary direct capacitive loads with actual Sky130 CMOS receiver inverters (Wn/Wp=0.42/0.84 µm, L=0.15 µm), powered from a separately measured supply. It retains 10 fF of digital destination capacitance. Both latch nodes see a real receiver; in the single-decision version only one receiver drives the destination capacitance, while the unused receiver remains and its switching energy is counted. The comparator input pair is 3.5 µm. All other sampling/filter conditions remain those of the held-capacitor test above.

| TT readout interface | Positive energy, negative / positive input | Equal-sign average | Approximate latch-ready delay from clock midpoint | Nine decisions |
|---|---:|---:|---:|---|
| Direct 10 fF on each latch output | 110.84 / 130.66 fJ | 120.75 fJ | 1.39–1.71 ns | Pass both |
| Two real receivers, each driving 10 fF | 110.63 / 119.70 fJ | 115.16 fJ | 0.90–0.99 ns | Pass both |
| Two real receivers, one 10-fF destination | **81.36 / 118.68 fJ** | **100.02 fJ** | 0.93–0.98 ns | Pass both |

The last row includes 11.58/44.21 fJ per decision from the receiver supply. It reduces the equal-polarity average by 17.2%; the energy is data dependent because only one decision polarity charges the destination. This average is not a measured SAR decision distribution. The output is sampled as an actual rail-to-rail digital receiver signal and must agree with the latch. The existing ten-ns strobe period is unchanged, so a shorter latch-ready delay is not credited as a complete ADC throughput gain.

At SS/85°C the single-destination version passes the negative input but the positive input changes sign after its first decision. The direct-load control at the **same 3.5-µm input width and SS corner also fails that positive sequence**, so the receiver did not create the pre-existing corner failure. This remains a held-node/readout limitation. No transistor noise or mismatch was simulated, and reducing latch load changes the decision aperture, so the nominal energy reduction does not prove unchanged effective input-referred noise.

Nine decisions at the nominal single-destination equal-polarity average cost approximately **0.90 pJ**, before CDAC/controller/reference-generation costs. The measurement includes all voltage-source ports during the repeated-read interval; acquisition before that interval is excluded and must be charged where it actually occurs. No full ADC was instantiated. This improvement is useful but does not close the aggressive W8 energy/noise budget.

## Connection to the higher efficiency targets

Counting a MAC as two operations, 100 TOPS/W allows **20 fJ/MAC** and 250 TOPS/W allows **8 fJ/MAC** for the stated whole-chip boundary. The present 128-row W4 interface leaves at most 1.984 pJ or 448 fJ, respectively, per output for a final ADC **and all other costs** if there is one conversion per output. Those are inverse design budgets, not achievable converter measurements.

Quality must use the same weight precision. If W8 requires two W4 slices and two conversions, an illustrative serial duplication of the measured W4 interface already consumes approximately 9 fJ/W8 MAC. It then leaves roughly **704 fJ per conversion** for the 100-TOPS/W target before other overhead, while exceeding the 250-TOPS/W energy budget before conversion. Even the 2× interface estimate is not established: a W8 low nibble may have much larger unsigned capacitor codes and loading than the measured W4 matrix. A physical concurrent-slice design could share some row/control work, but pays its actual doubled/different capacitive load and storage. It cannot combine W8 quality results with one W4 slice's energy.

The useful next decisions are therefore converter topology and readout noise, real storage/capacitor reuse, and precision allocation at accepted model quality. CAP-RAM/PICO-style reuse offers a concrete way to remove redundant sampling/reference circuits; it is not already implemented by this testbench. A smaller or lower-voltage readout must be checked with its receiver/clock/reference energy and effective input-referred noise before being credited toward either target.

## Reproduction

The initial 22 decks consumed approximately 148 seconds of aggregate simulation/parsing wall time. Tools came directly from the cached Nix store because the sandbox cannot access the Nix daemon. No package installation, PDK replacement or `flows/` mutation was performed.

```sh
/nix/store/qk5sl1xvg05cmqh03mn1srdggj39dg7p-python3-3.12.13-env/bin/python3 \
  analog/testbenches/tb_imc_sizing_research.py
/nix/store/qk5sl1xvg05cmqh03mn1srdggj39dg7p-python3-3.12.13-env/bin/python3 \
  analog/testbenches/tb_imc_sizing_research.py --extensions
/nix/store/qk5sl1xvg05cmqh03mn1srdggj39dg7p-python3-3.12.13-env/bin/python3 \
  analog/testbenches/tb_imc_sizing_research.py --matrix
/nix/store/qk5sl1xvg05cmqh03mn1srdggj39dg7p-python3-3.12.13-env/bin/python3 \
  analog/testbenches/tb_imc_sizing_research.py --replay
/nix/store/qk5sl1xvg05cmqh03mn1srdggj39dg7p-python3-3.12.13-env/bin/python3 \
  analog/testbenches/tb_imc_sizing_research.py --accumulate
/nix/store/qk5sl1xvg05cmqh03mn1srdggj39dg7p-python3-3.12.13-env/bin/python3 \
  analog/testbenches/tb_imc_sizing_research.py --refine
/nix/store/qk5sl1xvg05cmqh03mn1srdggj39dg7p-python3-3.12.13-env/bin/python3 \
  analog/testbenches/tb_imc_sizing_research.py --large
/nix/store/qk5sl1xvg05cmqh03mn1srdggj39dg7p-python3-3.12.13-env/bin/python3 \
  analog/testbenches/tb_imc_sizing_research.py --large-reset
/nix/store/qk5sl1xvg05cmqh03mn1srdggj39dg7p-python3-3.12.13-env/bin/python3 \
  analog/testbenches/tb_imc_sizing_research.py --large-dynamic
/nix/store/qk5sl1xvg05cmqh03mn1srdggj39dg7p-python3-3.12.13-env/bin/python3 \
  analog/testbenches/tb_imc_sizing_research.py --share-settling
/nix/store/qk5sl1xvg05cmqh03mn1srdggj39dg7p-python3-3.12.13-env/bin/python3 \
  analog/testbenches/tb_imc_sizing_research.py --receiver
```

ngspice resolves through `build/ngspice43/bin/ngspice`, the pinned Nix ngspice 43 binary. The script prints each candidate's PASS/FAIL and asserts convergence and negative controls. An overall experiment PASS means the screening/controls behaved as specified; individual candidate failures remain failures. Extension reuse is allowed only when the generated deck matches the existing `.cir` byte for byte and its trace exists; a reused result is flagged in the JSON.
