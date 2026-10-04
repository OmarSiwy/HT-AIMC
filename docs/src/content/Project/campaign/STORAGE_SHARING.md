# Resident storage and shared arithmetic capacitance

**The present replicated capacitor banks do not support an area win over Mythic.**
The most useful new branch is dense resident storage feeding a smaller number of
local charge-compute sites. Generic capacitor sharing is established prior art;
its useful sharing factor must be selected against paid memory access and the
actual transformer schedule.

## Capacity audit

The frozen model contains106,168,320 W8 matrix weights, observed in−127…127.
Original signed-magnitude radix16 and balanced radix9 each require22 conventional
binary magnitude units per weight for this support. At Cu=4fF, fully installed
arrays contain9.34281216µF; equal matched holder capacity doubles this to
18.68562432µF before extra column floors, padding, fine DACs, clocks or references.
At the repository's nominal single-layer2fF/µm² plate density, the corresponding
capacitor footprint projection is **9342.81216mm²**. The same construction at
Mythic's79,691,776 logical-weight capacity projects **7012.876288mm²**.

These are **conditional plate-area projections**, not universal foundry bounds.
Perimeter capacitance, legal MIM layer stacking, capacitor shape/spacing, routing,
and capacitor metal over SRAM alter projected footprint. ActiveC obtained by
bypassing unused units must not be substituted for physically installedC.
Likewise capacitor and SRAM footprints cannot simply be added if a legal layout
can overlap them. A substrate layout is needed to resolve that overlap.
The nominal2fF/µm² value is the existing local
SKY130 technology parameter.

For comparison, the primary OpenRAM SKY130 paper gives foundry single-port
bitcell area1.896µm² and dual-port area6.162µm². The W8 single-port **bare-cell**
floor is1610.36107776mm² at the same106M-weight capacity, before taps, straps,
decoders, sensing, routing and compute. The cells use foundry memory/OPC rules;
they cannot be freely modified into analog cells while assuming those areas
remain legal. [Cirimelli-Low et al., ISCAS2023, Fig.1 and §II–III](https://escholarship.org/content/qt9dc0v8g3/qt9dc0v8g3.pdf).

A public1-kB dual-port macro LEF is479.78×397.5µm. Replicating that particular
macro to the frozen model capacity would consume about19,773mm² before compute.
This is an implementable reference geometry, but a weak density baseline for a
large single-port model store; it is not the best SRAM possible.
[OpenRAM macro LEF](https://raw.githubusercontent.com/VLSIDA/sky130_sram_macros/main/sky130_sram_1kbyte_1rw1r_32x256_8/sky130_sram_1kbyte_1rw1r_32x256_8.lef).

Mythic's measured architecture is40nm embedded flash with nonvolatile resident
weights. Our present devices and storage are SKY130 CMOS/capacitors, with no
qualified multilevel flash process in the campaign. The density difference is
partly memory technology and process, not merely converter topology. Do not
scale node names quadratically or import flash density into SKY130 SRAM.
[Mythic technical presentation](https://events.vtools.ieee.org/m/307323),
[ISSCC2022 paper](https://doi.org/10.1109/ISSCC42614.2022.9731773).

## Closest existing mechanisms

PICO-RAM already places nine6T stored bits around one thin-cell MAC unit and
roughly4fF local capacitor. Only one stored bit is selected per operation; the
other eight provide resident weights for other layers/channels. Its capacitor
also serves input generation, MAC and shift/add. The measured65nm W4A4 macro
has559Kb/mm² overall density, including periphery. This is direct prior art for
local arithmetic-cap sharing; its native precision and process differ from the
current W8 research. [PICO-RAM §III-A and §V-D](https://arxiv.org/html/2407.12829v1).

The CICC2022 8T1C macro forms multibit-weight charge-domain MAV in one step and
avoids extra charge-sharing switches; its abstract reports1.5× conventional6T
logic-rule cell area. It is a stronger switch-count baseline than the present
16-MOS unsigned4-bit programming bank. Full output precision and normalization
must be audited before comparing headline efficiency.
[Primary CICC abstract](https://doi.org/10.1109/CICC53496.2022.9772821).

## A bounded sharing search

Let M be resident logical weights, S stored weights per active arithmetic site,
a_s the complete resident storage area per weight, a_c the charge-compute site
area, and τ(S) its paid initiation interval including weight selection, charge
operation and ADC resource stalls. With disjoint footprints,

\[
A(S)=Ma_s+Ma_c/S+A_{shared},\qquad
T_{max}(S)=2M/[S\tau(S)].
\]

The throughput expression is an upper envelope requiring useful simultaneous
work on every site. A transformer's layer dependencies, unequal matrix sizes,
activation broadcasts and ADC occupancy usually prevent this ideal utilization.
A completed sweep over all resident weights takes at least Sτ, but **Sτ is not a
validated transformer latency or token interval**. Full DAG scheduling must
replace that bound before a product claim.

At fixedτ and omitted shared overhead, `A*Sτ=Mτ(a_s*S+a_c)` increases with S.
Thus sharing does not improve both area and single-sweep delay simultaneously.
Every distinct S trades those objectives. If a throughput lower bound is fixed,
the best area point is the largest *feasible* S after actual τ(S), routing,
quality, power and DAG utilization are known. There is no evidence-based unique
optimum before those measurements.

The [reproducible bound sweep](../../../../../scripts/compiler/metrics/imc_storage_sharing_bounds.py)
and results enumerate
S=1,2,4,8,9,16,32,64; hypothetical paid service intervals250/500/1000ns; and vector
reuse1/8/32. They assert the expected area/delay tradeoff and retain both ideal
metal-overlap and disjoint footprint envelopes. No service time is promoted to
a measured complete W8 implementation.

Using only nominal capacitor area88µm² per arithmetic site and bare W8 SRAM
area15.168µm² per stored weight gives a density knee `S≈5.80`. Beyond that point,
ideal fully overlapped capacitor area fits under the bare storage footprint.
This makes **S=4,8,16** useful physical experiments around the knee; S=9 is also
a direct comparison with PICO's established clustering. ADC, holder placement,
selectors, wiring and SRAM periphery can shift the knee substantially.

## Memory bandwidth and power cannot disappear

For an architecture that explicitly reads an8-bit word into a reused compute
site for each MAC, with B useful vectors evaluated while that word stays loaded,
required local payload bandwidth is at least

\[
BW_{weight}=8\,T_{native}/(2B).
\]

At16.6TOPS this is66.4Tbit/s, or8.3TB/s, forB=1. It is distributed **local**
traffic if all weights remain on chip, not an assertion that an external bus is
necessary. If the design streams weights from external memory, the same payload
and its I/O energy must be paid unless a demonstrated cache/reuse schedule
reduces it. For an in-situ SRAM cell directly controlling arithmetic, this
explicit-read payload equation does not itself measure wire transitions or
energy; that circuit must be modeled directly.

With per-read-bit energy e_b and compute/readout energy e_c per useful MAC,
`E_MAC ≥ e_c+8e_b/B`, plus reference, control, leakage, activation/output movement,
and memory loading costs. At the historical3.3TOPS/W Mythic system point, the
budget is606.06fJ/MAC. If our complete compute/readout cost were100fJ/MAC, the
remaining read-bit allowance would be at most63.26fJ/bit forB=1, before all other
costs. This is a break-even budget, **not a measured SRAM energy or proof of a
win**. PICO's W4A4 efficiency is not substituted into this W8 equation.

Batch reuse can reduce read/programming amortization but requires activation
and output storage for B vectors, changes latency, and may be unavailable for
one autoregressive stream. A local weight selection held across repeated input
planes is already reuse within one MAC and must not be counted again as B
independent vectors.

Next physical test: one actual legal resident SRAM cluster with S=4/8/16,
finite state-driver impedance, a shared charge site, actual weight selection,
and complete row/clock energy. Compare against the same resident capacity using
an in-situ8T1C/PICO-style cell. Fail the branch if storage access or mux parasitics
consume the expected area/energy advantage, or if the required bandwidth cannot
be scheduled. Qualified NVM would be a separate process branch with retention,
programming, endurance and read-noise evidence; it is not an available free swap.

## Full-model boundary and dependency floor

The106,168,320 count covers the210 block MVM matrices only. Read-only GGUF
metadata inspection confirms30 layers, embedding width576 and vocabulary49152.
The tied token-embedding/output-head matrix adds28,311,552 stored values, bringing
those matrix parameters to134,479,872 before normalization weights and scales.
The present quality injector leaves this tied matrix clean. Therefore the9343mm²
projection is already a **partial-model** capacity projection, and a passing
full-depth inference run does not prove a fully analog physical output head.
The relevant path is explicit in
[Net initialization and evaluation](../../../../../scripts/compiler/metrics/depth_budget.py).

The same evaluator exposes a minimum serial chain per layer: Q/K/V projections
can operate in parallel, followed by attention and output projection; FFN gate/up
can operate in parallel, followed by down projection. Ignoring attention,
normalization, activations, residuals and data movement leaves four dependent
MVM stages per layer, hence120 dependent stages before the output head. Under a
hypothetical uniform S-way per-matrix reuse schedule with every stage taking Sτ,
this alone is120Sτ for one token. AtS=8 andτ=500ns, it is480µs before excluded
work. Independent requests may pipeline across layers; a single autoregressive
stream must wait for its next token. This demonstrates why the all-resident
throughput upper envelope cannot substitute for actual token throughput.

## Intra-weight reuse is a separate design variable

The22-unit compute site is the current binary-weighted magnitude-bank topology,
not a fundamental lower bound on charge arithmetic. An equal-unit capacitor per
weight bit would start with8Cu for W8, before its weight-combination network and
holders. A capacitor shared serially among eight stored bits could start with
oneCu, while adding weight phases and selection/reference work. Under the same
crude matched-holder and2fF/µm² assumptions, the cap/storage knee becomes2.11
for8Cu, and falls below1 foroneCu. These are topology envelopes, not qualified
circuits. PICO's in-situ weight combination is the appropriate prior baseline.

With binary activation planes, serially processing all eight weight bits may
require72 elementary planes for signed9-plane inputs, versus9 planes for two
parallel multibit banks. A multilevel input DAC or analog weight-bit shift/add
can change that count, but its actual row settling, precision, noise, parasitics
and converter cadence must replace the simple count. The useful search must
therefore distinguish **bits per arithmetic capacitor within one weight** from
**resident weights per arithmetic site S**. Sharing either one must not be
credited twice for the same hardware or time reduction.
