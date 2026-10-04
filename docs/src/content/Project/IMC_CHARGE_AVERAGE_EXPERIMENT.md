# Fresh experiment: calibrated charge averaging with one readout

Date: 2026-09-07. Testbench: tb_charge_average_research.py. Companion review: [IMC_CIRCUIT_RESEARCH.md](IMC_CIRCUIT_RESEARCH.md).

**Result: the passive divider is recoverable, but conversion precision and settling have a real cost.** A fresh Sky130 transistor-switch simulation recovers the summed voltage after calibration. The fast circuit fails the chosen deterministic-error gate at several operating points; a slower acquisition/sharing schedule restores the transfer. One unchanged ADC then has substantially more input-referred error after gain recovery. This experiment supports continued circuit exploration, not a chip-level speedup or energy claim.

## What was simulated

K = 1, 2, 4, 8 held partial voltages, each on a 200-fF capacitor, share through **real Sky130 NMOS+PMOS transmission gates** onto a 100-fF bus plus a 120-fF ADC input-load capacitor. Both TG devices use W/L = 0.42/0.15 µm, reusing the repository switch generator. Separate real TGs acquire the partial voltages and reset the bus. Supply/common mode are 1.8/0.9 V.

The signal values, capacitor elements and clock generators are ideal. There is **no physical OTA, comparator, SAR controller, reference generator or extracted layout** in this probe. A single noiseless ADC is modeled numerically after the transient; thermal noise and assumed ADC noise are evaluated separately. This is stronger than the existing ideal-S-switch divider test, but is still only a sampling/combining circuit test.

Each K uses three common-mode calibration patterns and 16–20 held-out patterns, including ±180-mV excursions, random mixed signs, exact cancellation and a 5-mV near-cancellation residue. Gain and offset are recalibrated at each tested condition. Corners are TT/27 °C, SS/85 °C and FF/−20 °C; they are three combined operating points, not a complete process/temperature matrix or mismatch-yield sweep.

The initial schedule acquires for 40 ns, isolates for 10 ns, then shares for 60 ns before reading. The diagnostic acquires for 200 ns and shares for 300 ns. Full fixture slots are 150 and 550 ns, respectively. Those are test-fixture timing choices, not a synthesized accelerator clock period.

## Deterministic transfer results

The ideal passive divider is `K + (100 + 120)/200 = K + 1.1`. For example, K=4 gives 5.1, not unity. The test calibrates this gain and compares the recovered value against the **original sum**, not the divided voltage. The predefined deterministic gate is maximum error below 2 mV in summed-voltage units, approximately one LSB of the illustrative 8-bit/0.5-V-range single-partial ADC.

| K | Condition | Fast RMS error, mV | Fast maximum, mV | Fast gate | Slow maximum when needed, mV |
|---|---|---:|---:|---|---:|
| 1 | TT, 27 °C | 0.4450 | 0.8312 | PASS | — |
| 1 | SS, 85 °C | 10.2286 | 20.0627 | FAIL | 0.0081 |
| 1 | FF, −20 °C | 0.0062 | 0.0116 | PASS | — |
| 2 | TT, 27 °C | 0.7188 | 1.9353 | PASS | — |
| 2 | SS, 85 °C | 14.6233 | 38.4259 | FAIL | 0.0082 |
| 2 | FF, −20 °C | 0.0068 | 0.0134 | PASS | — |
| 4 | TT, 27 °C | 1.1956 | 2.9646 | FAIL | 0.0219 |
| 4 | SS, 85 °C | 22.2015 | 59.9398 | FAIL | 0.0179 |
| 4 | FF, −20 °C | 0.0095 | 0.0234 | PASS | — |
| 8 | TT, 27 °C | 2.0585 | 5.7511 | FAIL | 0.0421 |
| 8 | SS, 85 °C | 38.9888 | 112.4745 | FAIL | 0.0408 |
| 8 | FF, −20 °C | 0.0203 | 0.0407 | PASS | — |

Rounded values above are from the final sweep. Fast cases use the original 0.1-ns grid; the fully settled diagnostics use a separately checked 1-ns grid. The machine-readable output is charge_average_research.json.

At K=4, the nominal long-settled divider is approximately **5.109**, close to the ideal 5.1; at K=8 it is approximately **9.122**, close to 9.1. The small difference includes transistor loading. The restored transfer does not prove a globally constant calibration over temperature, and the sub-0.05-mV residuals do not include thermal noise, capacitor mismatch or a real comparator.

Two negative controls prevent the result from merely verifying its calibration fit:

- Comparing the raw bus voltage to an unscaled sum fails by hundreds of millivolts. The digital scale is necessary.
- Increasing only the first storage capacitor by 25% leaves **20.72-mV held-out RMS error and 42.17-mV maximum error at K=4**, even after the same scalar gain/offset fit. This intentionally large perturbation verifies sensitivity to unequal summand weights; it is not a claimed process mismatch magnitude.

The second result is the physical distinction that the earlier divider argument missed: known uniform attenuation is removable; unequal transfer coefficients corrupt the sum.

## Noise and readout energy budget

The analytical comparison starts from K independent stored voltages, each with reset-noise variance `sT² = kT/C_int`, and a single-partial ADC with voltage-noise RMS `sA` and step `Delta`. Let `c = 1.1` denote the bus plus readout load in units of the storage capacitor.

For a digital sum of K independently digitized partials, the simplified summed-error variance is:

`var_digital = K * (sT² + sA² + Delta²/12)`.

For an ideal fully shared node, with independent reset noise on the added bus capacitance and one ADC, gain recovery gives:

`var_shared = (K+c)*sT² + (K+c)²*(sA² + Delta²/12)`.

This model separates stored sampling noise from fixed ADC voltage noise. It does not simulate sampled switch-noise spectra, comparator kickback, reference noise, OTA errors or correlated drift. Those are additional design obligations, not zero-valued measured terms. The digital baseline assumes an acquisition interface that preserves the stated input-referred ADC accuracy; such an interface also needs a physical implementation.

At 27 °C, 200-fF storage, 8 bits over 0.5 V, and assumed **0.2-mV ADC noise RMS**, the model gives:

| K | K-ADC digital-sum RMS, mV | One unchanged ADC RMS, mV | Additional ADC bits for equal ADC error | Thermal-limited one-ADC energy / K-ADC energy |
|---|---:|---:|---:|---:|
| 1 | 0.615 | 1.274 | 1.07 | 4.410 |
| 2 | 0.870 | 1.872 | 1.13 | 2.402 |
| 4 | 1.231 | 3.068 | 1.35 | 1.626 |
| 8 | 1.740 | 5.461 | 1.69 | 1.294 |

The extra bits follow from tightening ADC voltage error by `(K+c)/sqrt(K)`. If ADC energy is thermal limited and scales inversely with noise variance, the one-ADC/K-ADC energy ratio becomes `(1+c/K)²`. With no parasitic load it tends to **one**, not `1/K`. Thus the conversion-count saving can be entirely spent preserving accuracy. Added fixed bus capacitance can make the readout-energy trade worse.

This does **not** rule out the architecture. It identifies the conditions under which it can win:

- Existing ADCs spend substantial fixed switching/control energy rather than thermal-limited energy.
- The current per-partial path over-resolves the mathematical result, leaving unused error margin.
- Capacitor/reference reuse reduces c or avoids a separate sampling operation.
- Model sensitivity permits the resulting coarser final reduction.

Reference scaling can remove unused voltage range; it does not by itself remove input-referred comparator or reference noise. The noise comparison assumes continuous, sufficiently exercised values; a discrete lattice can change quantization statistics and must be tested on actual model partials.

## Reproducibility and runtime

The experiment uses the existing pinned Nix-store ngspice 43 through `build/ngspice43`, and cached Nix Python with NumPy:

```sh
/nix/store/qk5sl1xvg05cmqh03mn1srdggj39dg7p-python3-3.12.13-env/bin/python3 \
  analog/testbenches/tb_charge_average_research.py
```

This invokes the cached toolchain directly; it does not install dependencies or change `flows/`. Netlists, simulator logs, traces and the summary JSON remain under `build/sim/`.

The final sweep took approximately 134.6 seconds of aggregate simulator wall time across 19 decks on this machine. For runtime, the probe saves only `v(bus)`. The fast experiments retain a 0.1-ns transient step. Relaxing it to 1 ns changed the intentionally unsettled K=8/SS result by 0.186 mV, failing a 0.03-mV numerical-equivalence check, so that relaxation was rejected. The settled K=8/SS diagnostic changed by only about 0.0000015 mV; the final script uses 1 ns only for the long-settled diagnostic. This is a localized sampling choice validated against the finer run, not a blanket change to simulator tolerances.

The script prints individual circuit PASS/FAIL results, verifies that longer settling resolves the tested transfer failures, and asserts the negative controls and analytical noise inequalities. Its final PASS means the experiment and its falsifiers behaved as specified. It does not mean that every fast operating point or a full accelerator passed.

## Decision

Continue this candidate as a **conversion-sharing experiment**, with a physical readout and real model reductions next. The existing conclusion that any `1/K` voltage divider is fundamentally unusable is too strong. The equally attractive conclusion that K outputs can be combined with one unchanged ADC for `1/K` energy is also unsupported.

The next decisive comparison is a loaded physical converter after the averaging node, using programmable **distinct model reduction blocks**, capacitor mismatch and reference noise, versus K individually converted partials at the same full-model accuracy and total area. Wider switches, different common mode, matched capacitor reuse and a lower-load readout are legitimate design variables. Their clock energy, acquisition time, matching and area must be counted together.
