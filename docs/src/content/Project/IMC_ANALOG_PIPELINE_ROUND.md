# Analog sample/hold pipeline: bounded circuit round

Date: 2026-09-10. Circuit:
[tb_imc_analog_pipeline.py](../../../../analog/testbenches/tb_imc_analog_pipeline.py).
Artifacts: [imc_analog_pipeline.json](../../../../build/sim/imc_analog_pipeline.json).

**The two-bank fixture can overlap acquisition with a retained output, but
accurate capture fails.** Raw capture error reaches 10.75 mV at TT27 and
10.91 mV at SS85; the final output also fails the fixed 1-mV passive-read
screen. The programmed storage schedule reduces result interval from 395 to
295 ns while leaving first completion at 395 ns. No actual ADC or IMC array
is present, so this is not a demonstrated accurate pipeline-throughput gain.

The useful distinction is that concurrent activity contributes much less error
in this fixture than capture/read switching. More buffering would preserve the
wrong voltage more efficiently until that capture path is fixed.

## Circuit and frozen experiment

The experiment uses actual sky130 NMOS+PMOS transmission gates, 1.8-V supply,
0.9-V common mode, two 304-fF holders and one shared 948-fF capacitive read
load. Each holder has an acquisition TG, reset TG and output-selection TG.
Acquisition/read devices have Wn=Wp=6.72 µm; reset devices have Wn=Wp=3.36 µm;
all lengths are 0.15 µm. A 0.3-µm rectangular diffusion extension supplies
explicit AD/AS/PD/PS sensitivity geometry; it is assumed, not extracted.

The holder matches the smallest capacitance in the archived array experiment.
The 948-fF load matches the separate SAR's stated acquisition capacitance, but
it is **only an ideal capacitor** here. It does not reproduce the SAR's split
node switching, reference changes, comparator kickback or digital decisions.
The fixture's ideal voltage input is explicitly an external stimulus, not a
replayed array output represented as an integrated circuit.

The input sequence is frozen before simulations: 0.65, 1.15, 0.90 V followed
by nine samples uniformly drawn over [0.65, 1.15] V with seed 97164. No gain or
offset is fitted. All runs include reset, acquisition, isolation, return of the
source to common mode, bus reset, read connection and final closing reset.

| Relative time for each item | Operation |
|---:|---|
| 1–10.2 ns | Reset selected holder through its TG |
| 11.8–12 ns | Set input level |
| 14–98.2 ns | Acquire on selected holder |
| 99 ns | Observe after opening acquisition TG |
| 100–100.2 ns | Return input source to VCM |
| 101–110.2 ns | Reset shared read capacitor |
| 111.8 ns | Observe holder and bus before read connection |
| 112–393.2 ns | Connect selected holder to read load |
| 160 and 390 ns | Observe early/final read voltage |
| 395 ns | Complete configured service |

The two-bank overlap schedule starts a new item every 295 ns. While bank A
remains connected to the read load, bank B resets and acquires the next input.
The shared input transitions and both banks' clock activity are actual sources
connected to the transistor network.

There are two serial controls: two identical banks operated without overlap,
which isolates the incremental effect of concurrent activity, and one bank
operated without overlap, which exposes the resource and energy difference.
Both start items every 395 ns and use the same input levels and local phase
timing. TT27 and SS85 are tested at fixed 1.8 V; these are two combined
operating points, not complete PVT qualification.

## Measured deterministic results

Maximum errors over all twelve levels follow. “Read error” compares the final
bus voltage with the expected passive divider from the intended external input:

`Videal = VCM + [304/(304+948)] (Vin−VCM)`.

This correctly expects attenuation by 0.2428115; it does not expect a unity
gain buffer that does not exist. Gates were fixed at 100 µV while acquisition
is on, 1 mV for raw retained capture and 1 mV for the passive read result.

| Case | Capture error (mV) | Passive read error (mV) | Complete positive delivery (fJ/result) | Capture/read screen |
|---|---:|---:|---:|---|
| TT27, two banks, overlap | 10.7469 | 2.94276 | 122.087 | FAILED |
| TT27, two banks, serial | 10.7469 | 2.94274 | 122.102 | FAILED |
| TT27, one bank, serial | 10.7475 | 3.20876 | 119.264 | FAILED |
| SS85, two banks, overlap | 10.9061 | 4.55611 | 129.552 | FAILED |
| SS85, two banks, serial | 10.9061 | 4.55607 | 129.552 | FAILED |
| SS85, one bank, serial | 10.9043 | 4.49934 | 126.476 | FAILED |

While the acquisition switch is still on, error is below 0.01 µV in these
deterministic runs. Opening it and changing the source causes the large error;
this is consistent with the earlier
[hold-retention experiment](IMC_HOLD_RETENTION.md). Accurate tracking is not
accurate sampling. The new fixture also includes physical output selection,
which introduces its own transfer error. A read prediction using both actual
pre-join capacitor voltages still differs by approximately 5 mV in some cases;
simple divider arithmetic omits device charge and intrinsic capacitance.

Comparing the matched two-bank overlap and serial controls:

| Condition | Largest final-read difference (µV) | Largest read-window difference during the other acquisition (µV) |
|---|---:|---:|
| TT27, 0.1-ns transient step | 0.243 | 0.337 |
| SS85, 0.1-ns transient step | 0.366 | 0.381 |

These small differences must be read with the numerical control below: their
exact sub-microvolt values are not independently established physical isolation
specifications. They show no millivolt additional interference in this ideal-
reference, unextracted fixture. Shared supply impedance, physical clocks,
substrate coupling and a switching comparator are absent.

The deliberate **no-isolation fault** leaves the selected acquisition switch on
during readout. Changing the shared input then corrupts the supposedly held
result: TT27 final read error reaches **310.703 mV**, with 236.806 fJ/result.
This fails the same read screen by a wide margin, demonstrating that the
experiment detects loss of isolation rather than merely checking scheduled
waveforms.

## Numerical verification and energy boundary

The TT27 overlap and matched serial cases were repeated at a 0.05-ns transient
step. Maximum final-voltage change from the 0.1-ns overlap run is 2.187 µV;
positive delivery changes by 0.114%. The fine-step final overlap-versus-serial
difference is 0.458 µV. Consequently, the millivolt capture/read failures are
numerically robust, while a precise sub-microvolt crosstalk claim is unwarranted.
No simulator tolerance or device-model changes were used to obtain these results.

Every independent voltage-source port contributes

`Epositive = Σports integral max(−Vsource Isource, 0) dt`.

This includes VDD/well supply, common mode, input stimulus and every true and
complement clock. The table divides the complete twelve-item stream, including
closing reset, by twelve. Initial DC precharge is not measured as energy;
the 0-to-1-ns initialization interval is reported separately and included in
the transient total. For the two-bank overlap run it contributes 12.944/13.869
fJ per stream at TT/SS; closing reset contributes 42.173/45.352 fJ.

Relative to one-bank serial operation, two-bank overlap raises this delivered
energy by approximately 2.37% at TT and 2.43% at SS. It adds one 304-fF holder
and three TGs; two-bank implementation has 608 fF of holding capacitance and
six holder TGs, plus the shared load and bus reset. Equal capacitance is not
an extracted area claim. Averaging the table into watts would describe this
standalone storage fixture, not a converter, macro or chip.

Real clock/reference generation, capacitor dielectric leakage, thermal/flicker
noise, device mismatch and extracted wiring are absent. For scale only,
`sqrt(kT/304 fF)` is approximately 117 µV at 300 K before the transfer and
readout-noise budget. A noiseless transient cannot establish ten-bit storage
precision, particularly when capture offsets already exceed 10 mV.

## Latency, initiation interval and resources

For a producer of duration Tp and a consumer of duration Tc, a serial single
bank has initiation interval `II1 = Tp+Tc`. With independent producer and
consumer resources and enough separate storage, a two-bank schedule can reach

`II2 >= max(Tp, Tc, (Tp+Tc)/2)`.

The third term follows from bank occupancy; each item occupies one bank through
production and consumption. For two stages it is no larger than the maximum,
but writing it explicitly prevents claiming overlap when a bank remains busy.
More generally, each shared resource r requires `II >= work_r / count_r`.
Buffer duplication cannot defeat the converter-service requirement.

For this fixture's configured Tp=100 ns and Tc=295 ns:

- Serial interval is 395 ns and overlapped interval is 295 ns: a **1.339×
  scheduled service-rate ratio**.
- First final observation remains 390 ns and first service completion remains
  395 ns in both schedules. Pipeline fill latency has not disappeared.
- A bank is reused every 590 ns, after its prior service ends at 395 ns, so
  the schedule has 195 ns of reuse margin.
- Twelve configured results complete at 4740 ns serially versus 3640 ns with
  overlap. The finite-stream ratio is 1.302, below the steady-state ratio.

The consumer is a timed capacitive-load fixture, not an actual 295-ns ADC.
Thus these are scheduled times supported by the transistor storage experiment;
the failed capture screen prevents reporting them as accurate conversion
throughput. Existing 295-ns ADC service evidence comes from a different circuit
with an exposed reserved SS failure.

### Applying the accounting to charge-domain IMC

For the research architecture, use the full eight-plane timing projection
488 ns, an illustrative 100-ns pooling service, and 295 ns per ADC service.
The 100-ns pooling experiment is separate from this sample/hold fixture and
does not establish passing eight-plane accumulation. Let producer time be
`Tp=488+100=588 ns`.

| Resource boundary | Producer time | Consumer time | Serial interval | Two-bank lower-bound interval | First complete result |
|---|---:|---:|---:|---:|---:|
| One scalar output with its own available ADC | 588 ns | 295 ns | 883 ns | 588 ns | 883 ns |
| 1024-output W4 group sharing 256 ADCs | 588 ns | 4×295=1180 ns | 1768 ns | 1180 ns | 1768 ns |
| Hypothetical 30-ns multiplier plus 100-ns pooling, one scalar | 130 ns | 295 ns | 425 ns | 295 ns | 425 ns |
| Same hypothetical multiplier, 1024 outputs/256 ADCs | 130 ns | 1180 ns | 1310 ns | 1180 ns | 1310 ns |

All rows are **SPECULATIVE schedule projections**. They do not assert passing
integrated circuits or paid control/storage costs. The hypothetical multiplier
duration is a sensitivity input, not a measured logarithmic multiplier result.

The group consumer has four rounds only after successful pre-ADC row reduction.
Without that reduction, the prior 32-round partial-output schedule remains
converter limited, and storage-only overlap retains its approximately 3.88%
headroom. Reducing producer delay with a log/linear multiplier cannot reduce
that unchanged converter work.

For two W4 services per W8 result in the reduced-group scenario, serial time
is `2(588+1180)=3536 ns`. With two appropriately mapped banks and the same
resources, the ideal steady W8 interval is `2×1180=2360 ns`, while first
complete W8 fill time is `588+2×1180=2948 ns`. This requires storage and weight
selection for overlapping coefficient services; neither is free or implemented
by the standalone two-capacitor test.

A three-stage compute/pool/ADC pipeline would have an ideal interval
`max(488,100,295)=488 ns` for one scalar lane, but needs distinct resources and
state between both stage boundaries. Treating the same retained capacitor as
two independently available buffers is invalid. A logarithmic implementation
must include input log generation, settling, operating-point maintenance,
multiplication, output capture and linearization in Tp; quoting only an
exponential device's response time would omit required work.

At batch-one autoregressive inference, dependent layers and token feedback
still constrain useful overlap. Lower initiation interval for independent
analog samples does not establish lower first-token latency or higher token
rate under the actual model, weight-capacity and memory-service schedule.

## Decision and next falsifier

**VERIFIED:** the physical TG fixture follows the two-bank schedule, the
no-isolation control fails, all source energies are accounted at the stated
boundary, and fine-step checks preserve the millivolt failure.

**FAILED:** raw multilevel capture and passive read accuracy at the frozen
1-mV screens, at both tested operating points. No calibration was used to hide
these failures.

**SPECULATIVE:** a useful IMC pipeline, any log/linear multiplier stage balance,
and a workload-level throughput/energy improvement.

The next useful experiment should address capture/read charge injection and
the actual converter input impedance before adding more buffering. Candidate
repairs include a physically matched differential acquisition sequence,
bottom-plate sampling or a direct charge-domain converter that avoids a
redundant sample transfer. Each must be compared with the same input sequence,
full reset/clock energy and operating corners. A real array connection must
replace the external ideal stimulus before claiming integration.

Analog storage, capacitive partial-sum reduction and converter reuse are
established mechanisms: [MANTIS](https://arxiv.org/html/2411.07946) includes
analog image storage and charge-domain partial-sum aggregation, while
[CAP-RAM](https://arxiv.org/abs/2107.02388) removes separate sample/hold and
input/reference buffers through a charge-injection SAR. This fixture does not
support a novelty claim for ping-pong analog storage.

## Reproduction

```sh
/nix/store/qk5sl1xvg05cmqh03mn1srdggj39dg7p-python3-3.12.13-env/bin/python3 analog/testbenches/tb_imc_analog_pipeline.py
```

The experiment writes only `build/sim/imc_analog_pipeline*` artifacts and uses
the cached Nix ngspice through the existing testbench helper. Nine unique decks
cover six nominal configurations, one isolation fault and two TT timestep
controls. Identical decks are reused only when their text matches the saved
deck byte-for-byte and the trace exists; the report records reuse. The initial
seven decks took approximately 40.7 seconds in aggregate. A final cached report
refresh took roughly half a second.

The script prints individual failed capture/read gates and then
`PIPELINE EXPERIMENT PASS; raw capture/read accepted=False`. That PASS means
the experiment, arithmetic and deliberate falsifier behaved as specified; it
does not mean the candidate meets its circuit accuracy target.
