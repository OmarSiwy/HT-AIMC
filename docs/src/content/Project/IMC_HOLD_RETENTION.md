# Multilevel hold over an ADC-sharing wait

A small Sky130 sample-and-hold fixture retains its **already sampled value**
within an illustrative **100 µV over 9.145 µs** at TT27 and SS85. The largest
observed drift is 72.57 µV with assumed nonzero diffusion geometry; a numerical
conductance-floor control reduces the largest SS drift to 44.22 µV. This is
evidence that dynamic analog storage is a plausible ingredient, not a complete
analog latch, precision ADC, macro-retention or throughput result.

The sampling operation itself introduces **1.68–11.43 mV** of signal-dependent
error after isolation and input return. Thus this test does not establish
100-µV absolute sampling accuracy, even though subsequent drift meets that
illustrative limit. No offset or gain was fitted.

## Fixture and frozen inputs

[tb_imc_hold_retention.py](../../../../analog/testbenches/tb_imc_hold_retention.py) uses
one 304-fF ideal storage capacitor, a 6.72-µm NMOS/PMOS isolation TG, and a
3.36-µm NMOS/PMOS reset TG to 0.9 V. All gate lengths are 0.15 µm. These sizes
come from the existing 128-row retained-charge array, whose actual programmed
accumulator capacitances are 568/484/304/600/516/336/444/424 fF. The smallest
capacitance is selected before testing, using its actual rule
`Cacc = 120 fF + 4 fF × sum(abs(Wq))`; the program hash is in the artifact.

The fixed input levels are **0.65, 0.90 and 1.15 V**, each simulated at both
corners. Reset and acquisition use actual TGs; the ideal input source returns
to 0.9 V after isolation. The first held sample is observed at 220 ns, after
the switching transient, and the last at 9365 ns. There is no ADC, output mux,
array switching during the hold, capacitor dielectric leakage, transient
noise, mismatch, extraction, or real reference/clock generator.

The initial DC state explicitly precharges the capacitor. A short initialization
phase is followed by a paid reset edge at 1 ns, acquisition, isolation, and the
hold. Source-positive energy is clipped per physical source before summing;
signed energy is also stored. Initial DC stored energy is excluded, and the
0–1 ns initialization delivery is reported separately. These are finite
fixture energy measurements, not a complete repeated macro service cost.

## Deterministic results and model limits

| Model setting | Drift at 0.65 / 0.90 / 1.15 V (µV) |
|---|---:|
| TT27, native TG geometry | +30.905 / +0.883 / −29.150 |
| SS85, native TG geometry | +30.852 / +0.825 / −29.245 |
| TT27, assumed 0.3-µm diffusion extensions | +30.186 / +0.732 / −28.745 |
| SS85, assumed 0.3-µm diffusion extensions | −13.722 / −43.128 / −72.570 |
| Same SS geometry, `gmin=1e-14` instead of `1e-12` | −43.534 / −43.913 / −44.215 |

The native [TG generator](../../../../analog/schematics/library/cmos_switch.py) supplies
W/L but no AD/AS/PD/PS. The installed Sky130 subcircuits default these diffusion
areas and perimeters to zero. The sensitivity case explicitly supplies
`AD=AS=W×0.3 µm` and `PD=PS=2×(W+0.3 µm)`; it is an assumed rectangular
geometry, **not a layout-derived or extracted junction model**. The installed
nominal transistor models also set `igcmod=igbmod=0`, so direct gate-tunneling
leakage is absent. The ideal capacitor has no dielectric leakage.

The numerical-floor control matters: default `gmin` contributes a drift toward
mid-supply comparable to the native result. Lowering it changes drift while
leaving all physical devices and input levels fixed. Therefore the native
roughly 30-µV result is not a precise transistor-leakage prediction. Real
junction geometry, capacitor leakage, device variation and temperature
coverage remain necessary before relying on retention in silicon.

For this capacitance and wait, the illustrative leakage allowance is

```
I = C × ΔV / t = 304 fF × 100 µV / 9.145 µs = 3.324 pA.
```

The numerical-floor SS sensitivity corresponds to approximately 1.45–1.47 pA
of net current removing charge from the ideal storage capacitor. Integrated
capacitor current independently agrees with `C×ΔV` in every case under the
testbench's explicit tolerance. A deliberately injected **100-pA** discharge
current produces **−2.948 mV** drift and fails the retention gate as intended.
The difference from the ideal `−I×t/C ≈ −3.008 mV` includes transistor loading
and currents; it is not silently treated as an exact ideal-capacitor circuit.

Positive source delivery during the wait is **0.052–0.182 fJ** per normal
fixture; reset plus acquisition plus the wait costs **40.7–138.3 fJ**, depending
on level and model setting. These figures exclude the omitted blocks above.
Holding a value does not itself remove the shared ADC's serial conversion
work or prove that readout will preserve that value.

## Reproduction

The final five tiny simulator runs take approximately **21 seconds total** in
this session. They use the qualified optional native-bin-pruning build; stock
pinned ngspice43 can also run the same fixture.

```sh
NGSPICE=/home/omare/Documents/Projects/Research/build/research/ngspice43_native_prune/ngspice-native-prune OMP_NUM_THREADS=1 \
/nix/store/qk5sl1xvg05cmqh03mn1srdggj39dg7p-python3-3.12.13-env/bin/python3 analog/testbenches/tb_imc_hold_retention.py
```

The self-checking result, frozen input plan, initial/final voltages, charge
checks and energy are in `build/sim/imc_hold_retention.json`. Incomplete
transients are rejected. An initial experiment with unusually tight current
tolerances failed during reset; its deck/log are preserved as
`imc_hold_retention_strict_tolerance_failure.*`. The completed cases use the
same established solver tolerances as the existing array testbench. The
100-µV deterministic drift gate is illustrative and is separate from the
unvalidated complete ADC noise budget.
