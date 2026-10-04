# Dynamic sensing experiment: a stronger simple comparator control

The integrating preamplifier is **FAILED as a low-noise, low-energy readout
candidate in the tested sizing**. It reduces regenerative disturbance, but
its startup moves retained charge and its actual stationary device-noise
screen is substantially worse than the idealized estimate. The useful partial
result is simpler: **equal floating input holders and balanced digital receiver
loads** repair the deterministic near-zero decisions of the existing
StrongARM in this standalone fixture.

This is not a complete ADC or MAC connection, and no novelty is claimed. The
root's [connected charge-core experiment](CONNECTED_CHARGE_CORE.md) must test
the mechanism against the actual CDAC's frequency-dependent input impedance.
The source is [tb_imc_dynamic_preamp.py](../../../../../analog/testbenches/tb_imc_dynamic_preamp.py).
Results, decks, logs, traces, and available generator snapshots are indexed by
the [artifact manifest](../../../../../build/research/imc_dynamic_preamp_campaign/manifest.json)
and [numerical summary](../../../../../build/research/imc_dynamic_preamp_campaign/summary.json).

## Fixture and accounting

The positive input is a real 568-fF capacitor acquired through a Sky130
transmission gate with Wn=Wp=3.36 µm, L=.15 µm. The input source is external,
so this tests sensing of a charged endpoint rather than a MAC. The original
negative input is a stiff .9-V source. The matched-reference variant gives it
an equal 568-fF capacitor and identical acquisition switch. The two 8-kΩ/60-fF
filters are absent from the strongest result; this change must not be hidden
when comparing with the complete SAR.

The StrongARM has input W=3.5 µm, tail .42 µm, regenerative NMOS 1 µm,
regenerative PMOS 2.25 µm, and reset PMOS 1 µm, all L=.15 µm. Both latch
outputs drive real minimum CMOS receivers. The original receiver positive
output has a 10-fF digital load; the balanced variant adds the same 10 fF to
the other receiver output. No internal-drain reset transistor is used in the
best simple variant.

At the default 54-ns fixture period, acquisition stays on through 15 ns and
opens by 15.2 ns. The comparator clock rises from 26 to 28 ns, stays high
through 36 ns, and resets by 38 ns. Reacquisition begins at 50 ns. The
retained-state variant acquires only during the initial frame; the next
twelve measured decisions do not reacquire either holder. This 54-ns schedule
does not establish a new SAR trial period or ADC throughput.

Every independent voltage-source positive delivery is integrated, including
supplies, both reference/input ports, acquisition controls, latch clocks,
receiver supply, and closing reset. For the preamplifier, the diode-reference
branch's continuous supply current and any positive current-source delivery
are also counted. `direct` mode does not instantiate the preamplifier or its
bias branch, despite retaining unused preamp configuration fields in its JSON.
Steady measured frames follow a warmup. Full trace delivery is also recorded
in later results; it is not power-on energy from initially uncharged devices.
Finite clock and reference generators remain outside the fixture.

All MOS instances in this round omit explicit AD/AS/PD/PS, whose Sky130 wrapper
defaults are zero. Thus source/drain junction capacitance and leakage area are
not represented by drawn diffusion. Gate/channel capacitance is present.
This pre-layout result needs a controlled geometry sensitivity run. The next
passive-stack experiment uses the installed Sky130 symbol's .29-µm diffusion
extension explicitly and preserves zero-geometry controls.

All runs use the pinned native ngspice/Sky130 path. Transient noise and random
device mismatch are absent. A deterministic sign screen excludes inputs with
absolute **measured presense differential** below 25 µV; zero cannot establish
a reliable comparator decision. Raw decisions, including near-zero failures,
are retained. The screen was introduced during development; fresh validation
must be distinguished from reused development inputs.

## What survived the tests

| Circuit and stimulus | TT/27 °C | SS/85 °C | Interpretation |
|---|---:|---:|---|
| Stiff-reference direct comparator, initial wide-signal sequence | 83.029 fJ/read; 3.954-mV maximum held-node disturbance during latch interval; sign failures | 85.267 fJ/read; 4.148 mV; sign failures | FAILED. A quiet stiff-source comparator test misses floating-node disturbance. |
| Equal 568-fF reference, original unequal receiver loads | 117.509 fJ/read; −50-µV decision wrong | Not selected as final baseline | Matching source impedances removes most differential kickback, but another asymmetry remains. |
| Equal reference plus .42-µm internal-drain reset PMOS, scrambled sequence 97605 | 125.011 fJ/read; −50.26-µV actual input wrong | 127.805 fJ/read; −50.29 µV wrong | FAILED. Internal precharge alone does not repair the remaining offset. |
| Equal reference plus equal 10-fF receiver loads, same scrambled sequence, 20-ps step | 130.590 fJ/read; all signs correct | 133.831 fJ/read; all signs correct | VERIFIED deterministic fixture result; no fitted offset. |
| Same balanced circuit, 10-ps refinement | 130.733 fJ/read; all signs correct | 134.113 fJ/read; all signs correct | Energy changes .109%/.211%; decision agreement survives. |
| Same balanced circuit, twelve retained −100-µV reads | 104.954 fJ/read; all correct | 106.062 fJ/read; all correct | Actual presense signal changes only .00117/.00057 µV between first and last measured reads. |
| Same balanced circuit, twelve retained +100-µV reads | 104.949 fJ/read; all correct | 106.063 fJ/read; all correct | Actual presense signal changes −.00068/−.00021 µV between first and last measured reads. |

The scrambled development sequence is
`default_rng(97605).permutation(arange(-500,501,50))` µV. It contains large
sign reversals as well as ±50-µV and zero inputs. A fresh 24-input sequence
uses seed 97608, fixed ±25/±50-µV points, and twenty uniform draws from
±500 µV, with the chosen circuit frozen before simulation.

That fresh sequence passes **all 24 requested nonzero signs** at both corners,
including the requested ±25 and ±50 µV points. Its mean energies are
**131.565 fJ TT /134.947 fJ SS**. Requested signs and requested-point coverage
are checked alongside the measured-presense screen: acquisition must not move
a difficult requested point into an excluded guardband without disclosure.
The stiff-reference preamp tests do not establish absolute-input accuracy
merely because a measured-presense sign happens to be correct.

At 10-ps resolution the balanced circuit's maximum differential disturbance
during the latch interval is **1.554 µV TT /1.630 µV SS**, while individual
holders move by about 4 mV. Maximum differential error after the complete
sense/evaluate/reset cycle is **.3659/.3834 µV** on the changing-input
sequence. On retained ±100-µV inputs, per-cycle differential changes are at
most .0124/.0138 µV. Repeated-state measurements and complete-cycle metrics
are more informative than a single common-mode waveform peak.

These observations support two different physical statements:

1. Almost equal injected charge into equal floating capacitances produces
   mostly common-mode voltage movement. For injected charges qp and qn,
   the differential error is `qp/Cp−qn/Cn`, not either node's individual
   kickback voltage.
2. Asymmetric receiver output loading can feed back through the receiver's
   gate-drain capacitance during resolution. Adding the second 10-fF output
   load repairs the observed negative near-zero decision without a preamp or
   a fitted comparator offset. This controlled comparison supports the cause;
   it does not characterize every receiver loading or mismatch condition.

## Negative controls and matching sensitivity

Increasing only the reference holder by 1%, to 573.68 fF, produces up to
**39.73 µV differential latch disturbance**, versus 1.55 µV nominal. The
tested ≥25-µV sign screen still passes, but its margin is smaller. A 3%
increase, to 585.04 fF, produces **113.90 µV** disturbance and makes an actual
**+42.91-µV** input decide negative. That is a retained **FAILED** control.
These are explicit deterministic capacitor perturbations, not foundry Monte
Carlo or a yield estimate.

The first-order common-charge sensitivity is

\[
\Delta v_d=q\left(\frac1C-\frac1{C(1+\epsilon)}\right)
\simeq\frac qC\epsilon.
\]

A roughly 4-mV common excursion therefore predicts about 40 µV differential
error at 1% mismatch, consistent with the measurement. At a real CDAC port,
matching the scalar DC capacitance is insufficient: the impedance through
bottom-plate switches, the split bridge, any input filter, and device charge
must match during the regenerative edge. The reference holder has not yet
been shown to reproduce that network over frequency or DAC code.

For independently thermalized equal holders, reset noise alone has
`sigma_d=sqrt(2kT/C)`, approximately **121 µV** at 300 K and 568 fF. Common
reference-source noise may correlate, but independent switch thermal noise
does not disappear through geometrical symmetry. Therefore the deterministic
±50-µV result must not be reported as 50-µV noisy resolution. Larger native
holders, true covariance analysis, or another mechanism is still required.

## The preamplifier failure and the useful gm/ID result

The tested preamp has an NMOS pair W=1.35 µm/L=.3 µm; a W=4 µm/L=.5 µm
tail mirror; a W=3.36 µm/L=.15 µm source-enable device; .84-µm PMOS output
precharge devices; and 25 fF per output. A real .5-µm/.5-µm diode NMOS biased
at 550 nA generates the mirror gate voltage. Table gm/ID=20 is only an
initial sizing suggestion. Actual clamped DC operating points are:

| Quantity | TT/27 °C | SS/85 °C |
|---|---:|---:|
| Per-input drain current | 2.131 µA | 2.933 µA |
| gm/ID | 18.436 V⁻¹ | 14.953 V⁻¹ |
| gds/ID | .2526 V⁻¹ | .1737 V⁻¹ |
| Input AC port capacitance | 1.858 fF | 1.901 fF |
| Shared input source voltage | .1852 V | .1550 V |

Output compliance was swept on one branch with the other fixed at 1.4 V.
This is not a common-mode sweep of both drains. Actual source/body bias was
retained, which explains why fixed-VDS, grounded-source tables do not exactly
predict the circuit's gm/ID.

The first 4-ns pulse produces gain only 1.197. Turning on the source switch
pulls the diode bias from .661 to .534 V, and the tail current takes much of
the sensing interval to recover. A 100-fF bias capacitor and 2.5-ns warmup
raise gain to 5.477 TT /6.190 SS. However, source motion during warmup moves
the floating signal by about **−468/−581 µV before the original sensing
marker**. Only reporting the later 66/89-µV motion would conceal the larger
state error. Near-zero sweeps then fail at actual +89 µV TT and +120 µV SS.

The matched floating reference cancels most of this common motion. The
preamp then resolves the tested nonzero ±50-µV steps at 223.34 fJ TT and a
scrambled SS sequence at 242.80 fJ. It is still more expensive than balancing
the direct comparator's receiver loads. Keeping the tail continuously on
costs 537.84 fJ/read TT and still leaves sign errors; that version is also
**FAILED**. A one-event latch-disabled control preserves every previous
cycle's history and distinguishes residual preamp evolution from actual
regenerative disturbance. Earlier all-events-disabled controls are retained
but are not a clean same-history subtraction.

For per-device gm, ideal output Co, and a constant-current integrating
interval T, `Av≈gm T/Co`. Independent one-sided channel noise PSD
`4 kT gamma gm` on each input device gives

\[
\sigma_{v,\mathrm{pair}}^2\simeq\frac{4\gamma kT}{g_mT}.
\]

The factor is four under those conventions. The initial informal factor-two
estimate was corrected before sizing acceptance. With gamma=2/3, 100-µV
pair-only noise needs gmT≈1.104 pF, and at gm/ID=20 with VDD=1.8 V the
pair current alone costs about 199 fJ/trial. Output headroom also constrains
gain: each output's common-mode drop is roughly `ID T/Co=Av/(gm/ID)`.

The actual native BSIM stationary-noise probe is less favorable:

| Frequency | TT input ASD | SS input ASD | Conditional 4-ns flat-PSD boxcar RMS, TT/SS |
|---|---:|---:|---:|
| 100 MHz | 39.532 nV/√Hz | 43.834 nV/√Hz | 441.98/490.07 µV |
| 1 GHz | 36.711 nV/√Hz | 41.196 nV/√Hz | 410.44/460.59 µV |

The GHz PSD corresponds to gamma-equivalent 1.597/1.882 under
`Svin=8kT gamma/gm`; lower frequencies include substantial flicker noise.
These values include the selected DC-biased MOS network's noise. Noiseless
1-S clamping conductances are explicitly measurement instruments, not
proposed physical loads. The boxcar column assumes a flat PSD and a real
aperture of four nanoseconds; it is a conditional diagnostic, **not** a
dynamic-noise simulation. Reset noise, floating-input covariance, nonlinear
regeneration, actual aperture weighting, and mismatch remain unverified.
Even this screening result gives no basis to call the present preamp a
100-µV readout.

## Reproduction and provenance

Use the cached Nix Python and pinned ngspice resolution from repository
helpers. For the final refined deterministic sequence:

```python
import sys
import numpy as np
sys.path.insert(0, "analog/testbenches")
from tb_imc_dynamic_preamp import probe
levels = np.random.default_rng(97605).permutation(np.arange(-500,501,50))
for corner, temp in (("tt",27), ("ss",85)):
    probe(mode="direct", corner=corner, temp=temp,
          reference_holder_ff=568, balanced_receivers=True,
          step_ps=10, inputs_uv=levels, seed=97605)
```

The CLI supports `--dc`, `--noise-dc`, `--mode`, `--reference-holder-ff`,
`--balanced-receivers`, `--internal-reset-width`, `--retain`, and the explicit
preamp sizing/timing knobs. The test asserts trace completeness, finite
values, positive DC quantities, and closing latch reset. Proposed performance
failures remain in result files rather than being silently discarded.

During early development, generator snapshots were taken after simulation;
concurrent edits can make such a snapshot later than the emitted deck. The
**emitted decks and trace hashes are authoritative for those development
runs**. Before the final 10-ps, mismatch, positive-retention, and fresh-input
runs, snapshotting was changed to freeze source bytes at entry, before deck
generation and simulation. That limitation is preserved rather than assigning
old results a retrospective exact-source guarantee. The complete manifest
records actual retained files, not nonexistent layout or transistor-noise
artifacts.

What remains unverified is substantial: complete SAR decisions, real MAC
connection, code-dependent/frequency-dependent impedance matching, reference
generation, extracted parasitics, mismatch/yield, transient noise and BER,
and full-model error qualification. The immediate integration candidate is
the balanced direct comparator with a properly matched floating reference;
the preamp remains a useful negative result and a source of gm/ID/noise data.
