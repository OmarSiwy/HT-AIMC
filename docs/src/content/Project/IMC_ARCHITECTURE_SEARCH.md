# Architecture sizing search and requirements for a competitive IMC

2026-09-07; circuit status updated 2026-09-09. **Decision: develop a passive, low-swing, shared-capacitor macro with explicit input/weight planes and locally shared references. Further scaling of the present ballast-heavy OTA/PWM tile does not meet the declared resident-system target in this search.** Preserve two four-bit weight planes as an INT8 quality reference; qualify a cheaper W4 mode through model adaptation. The leading deterministic transfer fixture is **128 rows × 8 columns**, after repairing reset and sharing settling. Dynamic high-bit skipping delivers **4.500/4.587 fJ/A8×W4 MAC at TT27/SS85 in 366 ns average before ADCs** on the tested operands. The earlier 318-ns schedule failed SS. ADC noise, extracted corners and storage density remain open. The development targets are **100 TOPS/W minimum and 250 TOPS/W stretch at a complete chip power boundary**, corresponding to **20 and 8 fJ per useful MAC**. Weight-engine budgets below are necessary allocations before accounting for the rest of the chip; achieving them alone is insufficient. Neither target is achieved by this component result. This is a macro-development sequence, not a proven optimum.

The [self-checking search](../../../../scripts/compiler/metrics/imc_architecture_search.py) evaluates **810 macro configurations and 12,960 workload conditions**. It produces **15 nondominated component points** after a declared quantization screen. No point passes all necessary conditions for the example eight-die resident package, and none has verified layout or deployed-model quality. Separately, inverse energy budgets state what a replacement macro must achieve to exceed commercial operation-efficiency targets; those budgets are requirements, not invented performance estimates.

## Evidence and assumptions

Read [AGENTS.md](../../../../AGENTS.md), [CONTRACT.md](CONTRACT.md), the user's 27l1/27l7 residency/tiling notes and 27h1/27h4/27h5/27h9 conversion/encoding notes, and the preceding [architecture research](IMC_ARCHITECTURE_RESEARCH.md). The script follows the implemented weight tile, specs, [metrics](METRICS.md), and PDK configuration. It does not reuse the old fictitious division of digitally performed ADC operations by cascade depth.

Two deliberately separate tracks are evaluated:

1. **Current-topology extrapolation:** retain the 0.15-fF unit, 1.8-V supply, OTA, two-bank storage, 4-fF ballast per bank, 500-fF column rail, and local reference reservoirs. This reveals structural costs. The unit capacitor's physical geometry is unverified, and all resized configurations require new characterization.
2. **Replacement-macro inverse budgets:** use actual saved operand activity to price only signal-capacitor switching, then solve for the maximum affordable ADC/interface energy. Include 4-fF effective units and a hypothetical 0.4-V switching step. This does not claim that low-voltage reference generation, switches or ADCs are free or already working.

The eight-die system envelope is an explicit engineering scenario: **8 × 400 mm², 70% usable area, 400 W total, 1 TB/s external service, 32 TB/s aggregate internal leaf traffic, 1 TMAC/s attention service, and 32 GiB KV capacity**. None is a measured AnalogIOC resource. The fabric figure is an aggregate service assumption, not a bisection-bandwidth proof. These constants are at the top of the script and are not fitted to make a competitor comparison pass.

Model dimensions follow the authors' Llama 3 Table 3: 32/80 layers, 4,096/8,192 hidden dimensions, 14,336/28,672 FFN dimensions, 32/64 query heads and eight KV heads. The table's rounded 128,000 vocabulary is used, so these are **8B-/70B-class architectural workloads**, not exact checkpoint benchmarks. Including the output head gives **7,503,609,856 / 69,499,617,280 weight MACs/token**. Including a separate embedding table gives **8,027,897,856 / 70,548,193,280 stored weights**; normalization parameters and associated work are omitted. [Primary model paper](https://arxiv.org/html/2407.21783v3#S3.T3).

## Mapping and physical service equations

For a matrix with input/output dimensions I/O and a tile with R rows and C useful columns:

`N_tiles = ceil(I/R) * ceil(O/C)`.

With S stored weight planes, D separately converted input digits and one checksum column:

`N_ADC/token = N_tiles * S * D * (C+1)`.

For requested sharing q, `N_ADC_instances=ceil((C+1)/q)` and `rounds=ceil((C+1)/N_ADC_instances)`. Sharing changes instances and waiting time, not the number of converted outputs. Both lower/higher weight planes remain resident; serializing their use does not mean rewriting weights.

The sweep covers R=16/32/64/128/256, C=16/64/128, q=1/4/8, output bits=6/8/10, two-/four-bit physical weight planes, and three INT8 input schedules:

| Input schedule | Array digit windows | Padded excitation quanta | ADCs per column per W4 plane |
|---|---:|---:|---:|
| Current duration-weighted nibbles | 2 | 144 | 2 |
| Equal-duration nibbles plus digital significance | 2 | 32 | 2 |
| Binary digits plus digital significance | 8 | 8 | 8 |

Every window also has eight guard/settling quanta in the analytical current-topology schedule. A fixed 10-ns grid is retained. The equal-nibble path is a new encoding proposal; its hardware reference scaling and reconstruction must be verified. The binary path wins on excitation work but can lose badly on conversion. No analog radix accumulation is silently assumed.

For the current column, the model uses

`Cpar = 500 fF + 2R*(4 fF + (2^weight_plane_bits−1)*Cu)`

and scales Cint to preserve coherent row headroom, subject to the existing thermal floor. Packet settling is

`tau = [A*(Cint+Cpar)/Cint + Cpar]/gm`,

with gm=72 µS and A back-solved from the original 30-ns/200-fF/700-fF anchor. Coarse cadence is rounded upward to two tau on the grid. The nine-slot lossless coarse cap already in `specs.py` replaces the historical 17-slot schedule; fine time scales with the number of fine decisions and modeled settling. This is a first-order closed-loop model, not a SPICE validation of large arrays or changed precision.

Energy starts from the historical **820.83-pJ integration, 1,345.10-pJ conversion and 24.6-pJ digital** totals. Known 12-µA column bias at 1.8 V is separated from residual phase energy; the historical 4.12-µs / 2,190.53-pJ point is reproduced exactly as a check. Residual switching scales with saved operand activity, and converter residual energy scales linearly with decision bits. That extrapolation is deliberately coarse: the historical measurements do not separate every reference/clock/interface component. Waiting integrators remain biased when converters are shared. A design that disconnects and holds them must supply its own droop, acquisition and switching model.

The reported energies are **conditional estimates**, not rigorous physical lower bounds: positive omitted terms cannot turn uncertain extrapolations of included terms into guaranteed bounds. The corresponding token-rate ceilings are conditional on the assumed macro timing and resource capacities. Artifact field names preserve that distinction.

Capacitor plate area includes reserved differential binary banks, both bank ballasts, Cint, rail ballast, optional hold capacitors and **two 5-pF local fine-reference reservoirs per converter**. It uses the nominal 2-fF/µm² density. The area screen takes the maximum of capacitor plate area and scaled synthesized digital cell area, allowing optimistic FEOL/BEOL overlap. It excludes SRAM control area, routing/spacing, switches, clock trees, references outside the counted reservoirs, extraction and yield. It is a necessary area estimate for the specified reserved topology, not a layout prediction; the sub-fF geometry cannot be justified by dividing capacitance by MIM density.

## The conditional component frontier

Dominance minimizes **energy/MAC, macro service latency, and area per stored weight**. Raw macro area is not compared as though different macro dimensions stored the same work. Selected points below illustrate the trade; all 15 frontier points and all rejected cases are in the artifact.

| R×C, converter sharing | Bits / encoding | Estimated fJ/MAC | Service µs | Plate/digital area bound µm²/weight |
|---|---|---:|---:|---:|
| 32×128, 1:1 | 8 / equal nibbles | 2,655 | 1.994 | 177.94 |
| 64×128, 1:1 | 10 / equal nibbles | 1,755 | 2.270 | 95.54 |
| 128×128, 1:1 | 10 / equal nibbles | 1,216 | 2.870 | 53.93 |
| 256×128, 1:1 | 10 / equal nibbles | 965 | 4.287 | 33.27 |
| 256×128, about 4:1 | 10 / equal nibbles | 1,936 | 15.706 | 19.01 |
| 256×128, about 8:1 | 10 / equal nibbles | 3,231 | 30.932 | 16.57 |

The 256×128 energy point corresponds to only approximately **2.07 TOPS/W equivalent** under this conditional component model. It is not a recommendation to build that large OTA tile. The widest/fattest design reduces overhead per MAC but increases settling, absolute macro size and headroom cost. Converter sharing improves density while increasing hold/static energy and latency. It is not an independent energy gain.

The quantization screen is also explicit. A generic uniform quantizer covering ±4 sigma has `SNRq=10log10(12*4^b/64)` at the original operating point. The script tracks the voltage gain change caused by actual Cint and row count. A hypothetical combined 36.74-dB target leaves a required non-quantization error budget

`10^(−SNRanalog/10) < 10^(−36.74/10) − 10^(−SNRq/10)`.

Negative remaining budgets reject a point **under this model**. The 256-row/10-bit energy point needs approximately 38.85 dB in the remaining error term. This is not a universal LLM target, a measurement of the new circuit, or a guarantee after digit/weight-plane reconstruction. Real clipping, error correlation, integer-lattice behavior and model sensitivity can invalidate the scalar approximation. All candidates retain `quality_verified=false`.

## Resident capacity and the compute-bound condition

The assumed eight-die package has 2,240 mm² usable area. It permits only:

| Workload | Maximum total area per weight | Maximum capacitor equivalent at 2 fF/µm² |
|---|---:|---:|
| 8B-class | 0.2790 µm² | 0.5581 fF/weight |
| 70B-class | 0.03175 µm² | 0.06350 fF/weight |

These are whole-budget ceilings before any other component. The present topology's **8 fF of differential top ballast alone** exceeds them by roughly 14× and 126×. Increasing Cu uniformly cannot fix this. Even the best current-topology energy point needs at least **954 die-equivalents** for the 8B-class stored model under its area calculation. The smallest area/MAC point still fails the eight-die condition.

This motivates sharing physical capacitors across stored bits, removing per-weight ballast, denser storage/process integration or a much larger package. For a single 4-fF capacitor shared among S SRAM bits, W4 costs at least `16/S fF per weight`: the eight-die capacitor-only allowance requires **S≥28.7 for 8B or S≥252 for 70B**, before SRAM and peripherals. W8 doubles those requirements. These are not promises that such sharing is physically possible. A design with nine bits sharing one capacitor still needs additional density, more dies or stacking at these assumptions.

Explore **32/64 resident storage bits per reused 4-fF compute capacitor** as capacity requirements. They imply 0.5/0.25 fF per W4 weight, or 1.0/0.5 fF per W8 weight, before the omitted structures. Only the latter 64-bit case reaches the 8B W8 capacitor-only allowance, with almost no room left for other capacitors. Keeping many coefficient groups beside one compute element does not create extra compute ports. Its bank schedule must satisfy `sum_j(request_rate_j * plane_service_time_j) < 1`; if all groups are requested each token, their service times add. MoE exclusivity can change demand, but cannot be presumed for a dense model.

Batch-one recurrence is enforced. With resident independent projection resources, weight latency is optimistically `(4L+1)*Tmacro`: Q/K/V parallel, attention, output projection, gate/up parallel, down, repeated across L layers, then the LM head. Reduction, normalization and transport latency are omitted, so this is an optimistic schedule. The shared attention engine adds its total attention MAC service time. Aggregate rate obeys

`R <= min(1/Tmacro, concurrency/Ltoken, attention_capacity/attention_MACs, P/Etoken, BWj/bytes_j)`.

KV uses `2*L*Hkv*dhead*context*concurrency*bits/8` bytes. Digital16 reads the K/V cache once per generated token under ideal GQA reuse. Analog4 with an external shadow pays `KV_bytes/Trefresh` even during low decode activity, with `Trefresh=−27ms*ln(15/16)=1.743ms`. Its write occupancy is `context*150ns/Trefresh`, assuming complete-width writes and parallel K/V banks. Independent sessions require independent resident banks. Real analog read service, maintenance energy and cache area are not characterized here.

For the illustrative 128×64/10-bit/equal-nibble component point, **ignoring its failed resident-capacity gate**:

| Context / concurrency | KV policy | Conditional rate ceiling | Binding service or failure |
|---|---|---:|---|
| 4k / 1 | Digital16 | 693 tok/s | Token dependency plus assumed attention engine |
| 4k / 64 | Digital16 | 931 tok/s | Assumed 1-TMAC/s attention service; KV exactly 32 GiB |
| 4k / 64 | Analog4 + external shadow | 0 | 4.93-TB/s refresh exceeds 1-TB/s budget |
| 32k / 1 | Digital16 | 112 tok/s | Token dependency plus attention |
| 32k / 1 | Analog4 + external shadow | 0 | Refresh write duty 2.82 exceeds one port's time |
| 32k / 64 | Digital16 | Infeasible | 256-GiB KV exceeds 32-GiB capacity |

A modeled memory margin of at least 1.2 is required in addition to capacity and quality screens. None of these conditional rates is published as a working chip result. Weight capacity fails globally; analog shadow refresh fails several workloads; the analog read ports, embedding access, all-die fabric, idle/leakage and full nonlinear path remain unverified. Making an already memory-limited design slower is not credited as an optimization merely because compute then binds.

## Invert the energy budget for the replacement macro

For an operation-efficiency target eta TOPS/W, the two-operations/MAC convention gives

`e_target = 2000/eta fJ/MAC`.

With code-weighted switched-capacitor activity a, actual switching step V, unit Cu and other work e_other:

`e_switch = Cu_fF * V² * a`;

`E_ADC_max = (e_target − e_switch − e_other) * R / [S*D*(C+1)/C]`.

The last expression is in fJ/conversion. An impossible or negative budget is rejected. The script also computes the minimum rows required for a 1-pJ ADC and the maximum permissible number of code-weighted transfers. **These are necessary budgets, not a claim that energy scales ideally with V² across a complete circuit.**

The real saved INT4/INT8 artifacts give mean code-weighted transfers **14.112** for weighted PWM, **7.719** for equal nibbles, and **2.449** for binary digits. These are calibration-stream measurements from the first six positions of seven layer-0 matrices; the mean absolute weight is 1.198. They do not establish a universal LLM activation distribution.

At Cu=4 fF and a 0.4-V switching step, signal-capacitor energy alone is **9.03 / 4.94 / 1.57 fJ/MAC**, respectively. Gate drive, ballast, references, reset, SRAM, ADCs and transport are absent. At the 1.8-V step, those costs become **182.9 / 100.0 / 31.7 fJ/MAC**: the 120-TOPS/W target is already impossible before any other energy. Low swing and fewer physical repetitions are therefore meaningful design requirements.

The following **maximum ADC energies** assume C=64, W4, 4-fF units, 0.4-V steps and an explicit **10-fJ/MAC reserve for everything except signal caps and ADCs**. That reserve is an allowance to meet, not a measured cost.

| Target | R | Two equal-nibble conversions | Eight binary-digit conversions |
|---|---:|---:|---:|
| 8.33 TOPS/W | 16 | 1.774 pJ | 0.450 pJ |
| 8.33 TOPS/W | 64 | 7.094 pJ | 1.800 pJ |
| 40.2 TOPS/W | 64 | 1.097 pJ | 0.301 pJ |
| 40.2 TOPS/W | 256 | 4.387 pJ | 1.203 pJ |
| 120 TOPS/W | 64 | 0.0544 pJ | 0.0402 pJ |
| 120 TOPS/W | 256 | 0.2176 pJ | 0.1607 pJ |

The [Mythic evidence](IMC_COMPETITOR_RESEARCH.md) distinguishes the roughly 8.33-TOPS/W current M1 headline from the 120-TOPS/W roadmap. PICO-RAM's measured 40.2-TOPS/W W4A4 point is a useful intermediate research target, with different precision and power boundaries; it is not a AnalogIOC multiplier. [PICO-RAM primary paper](https://arxiv.org/html/2407.12829v1).

Those values are comparison anchors, not the goal. The updated artifact includes **100- and 250-TOPS/W targets** and R=128 inverse budgets. At R=128, C=64, W4, 4-fF units and 0.4-V steps, binary input planes leave at most **0.290 / 0.101 pJ per ADC** at those targets, even with zero allowance for other interface work. Two equal-nibble conversions leave **0.949 / 0.193 pJ**. The measured passive radix implementation below supplies a more useful next budget than signal-capacitor CV² alone.

The model explains the next architectural experiment: binary input planes can substantially reduce switched work, but eight ADCs per result demand a much cheaper converter or a verified analog radix accumulator. Sharing an ADC across columns saves instances; combining mathematically valid input/weight significance before conversion can save actual events. Those are different operations.

## What the stronger targets would mean for tokens

For M weight MACs/token and a complete weight-engine target e, `E_weight=M*e`. The actual system has

`tok/J = 1/(E_weight + E_attention + E_KV + E_nonlinear + E_links + E_idle_per_token)`.

The omitted terms are unknown. The following is **target arithmetic for the weight engine**, including both coefficient slices if W8 is used, not measured system efficiency. Model MAC counts are those stated above, including the output head.

| Workload / target | Target weight energy per token | Ideal weight-only tok/J | Power-only ceiling at 400 W |
|---|---:|---:|---:|
| 8B / 100 TOPS/W | 0.1501 mJ | 6,663 | 2.665 million tok/s |
| 8B / 250 TOPS/W | 0.06003 mJ | 16,659 | 6.663 million tok/s |
| 70B / 100 TOPS/W | 1.390 mJ | 719 | 287,771 tok/s |
| 70B / 250 TOPS/W | 0.5560 mJ | 1,799 | 719,428 tok/s |

Those large power-only numbers expose other bottlenecks; they are not proposed achievable rates. Apply the **same existing system envelope**: 4k context, 1-TMAC/s shared attention service, 1-TB/s KV reads, 32-TB/s leaf traffic, 32-GiB KV and independent resident projection resources. Use a provisional **848-ns W8 service**, twice the measured 424-ns W4 interval, still before final ADC/reduction latency. At either energy target, batch-one dependency plus attention limits the conditional rate to **845 tok/s for 8B and 177 tok/s for 70B**. At concurrency 64, attention service limits the resource-only rates to **931 / 186 tok/s**; the 70B case additionally fails KV capacity, requiring **80 GiB**. The 8B case uses the full 32-GiB KV budget. Neither replacement macro has verified resident weight capacity, and the present OTA topology fails it, so these are conditional ceilings rather than feasible chip points.

Consequently, a 2.5× improvement from 100 to 250 TOPS/W does not raise modeled token throughput in this envelope. It reduces target weight energy while attention, concurrency, storage and transport still constrain service. Faster attention compute and adequate resident capacity are necessary companions to the IMC work. Achieved system tok/J cannot be obtained by assigning the entire 400-W allowance to the weight arithmetic while omitting the other engines. The artifact records every per-resource ceiling and its assumptions in `target_system_ceilings`.

## Allocate resources for 10k, 100k and 500k tok/s

The earlier 1-TMAC/s attention engine is a diagnostic scenario, not the optimized architecture. Invert the workload instead. For aggregate rate r, context T, layer count L and hidden dimension d, two attention matmuls require `2*L*d*T*r MAC/s`. With ideal GQA reuse, conventional attention reads `2*L*Hkv*dhead*T*bits/8` KV bytes per generated token. These are **aggregate services at the memory owners**, not necessarily off-chip traffic. An attention-in-memory design may avoid materializing that full bit stream, but must supply the equivalent computation, precision and maintenance.

| Model / context | Requested tok/s | Required attention TMAC/s | KV read TB/s, 16-bit / 4-bit |
|---|---:|---:|---:|
| 8B / 4k | 10,000 | 10.74 | 5.37 / 1.34 |
| 8B / 4k | 100,000 | 107.37 | 53.69 / 13.42 |
| 8B / 4k | 500,000 | 536.87 | 268.44 / 67.11 |
| 8B / 32k | 10,000 | 85.90 | 42.95 / 10.74 |
| 8B / 32k | 100,000 | 858.99 | 429.50 / 107.37 |
| 8B / 32k | 500,000 | 4,294.97 | 2,147.48 / 536.87 |
| 70B / 4k | 10,000 | 53.69 | 13.42 / 3.36 |
| 70B / 4k | 100,000 | 536.87 | 134.22 / 33.55 |
| 70B / 4k | 500,000 | 2,684.35 | 671.09 / 167.77 |
| 70B / 32k | 10,000 | 429.50 | 107.37 / 26.84 |
| 70B / 32k | 100,000 | 4,294.97 | 1,073.74 / 268.44 |
| 70B / 32k | 500,000 | 21,474.84 | 5,368.71 / 1,342.18 |

Four-bit KV is an unvalidated quality/storage option here; it is not inherited from the W8A8 projection experiments, which retain floating attention/KV. Metadata, refresh, new-token writes and read amplification would add service. Independent sessions increase capacity without reducing bytes per generated token:

| Model / context | 16-bit KV GiB, B=1 / B=64 | 4-bit KV GiB, B=1 / B=64 |
|---|---:|---:|
| 8B / 4k | 0.5 / 32 | 0.125 / 8 |
| 8B / 32k | 4 / 256 | 1 / 64 |
| 70B / 4k | 1.25 / 80 | 0.3125 / 20 |
| 70B / 32k | 10 / 640 | 2.5 / 160 |

The following power allocation uses the target **20/8-fJ logical weight-engine MAC costs**, including both W8 slices when used. It does not assert that the chip achieves those efficiencies. Weight power is independent of context in this dense decode approximation; attention and KV are not.

| Model / requested tok/s | Weight power W, 100 / 250 TOPS/W allocation | Remaining of 400 W for all other work, same order |
|---|---:|---:|
| 8B / 10,000 | 1.50 / 0.60 | 398.50 / 399.40 |
| 8B / 100,000 | 15.01 / 6.00 | 384.99 / 394.00 |
| 8B / 500,000 | 75.04 / 30.01 | 324.96 / 369.99 |
| 70B / 10,000 | 13.90 / 5.56 | 386.10 / 394.44 |
| 70B / 100,000 | 139.00 / 55.60 | 261.00 / 344.40 |
| 70B / 500,000 | 695.00 / 278.00 | **−295.00, infeasible / 122.00** |

At 70B/32k/500k tok/s, the latter 122-W remainder would permit at most **5.68 fJ per attention MAC if attention consumed all of it**, or **11.36 fJ per materialized 4-bit-KV traffic bit if KV consumed all of it**. These mutually exclusive ceilings cannot both be spent. They omit softmax, input quantizers, activation transport, memory control and leakage. Remaining 400-W power is headroom under a package cap, not permission to consume that power while claiming 100/250 TOPS/W at every token rate. Complete chip efficiency requires complete energy and native-operation accounting.

Autoregressive dependencies give another allocation: if there are `(4L+1)` serial weight stages, a necessary stage-service bound is `t_stage <= min(1/r, B/[r*(4L+1)])`, even with zero attention/reduction latency. At 500k tok/s, B=1 requires **15.50 ns for 8B or 6.23 ns for 70B** per stage; B=64 allows **992 / 399 ns**. Thus concurrency, stage latency and KV capacity must be chosen together. The tested 318-ns W4 average cannot be assigned to W8 or to the newer dynamic block quantizer, which generally uses seven planes rather than the old fixture's six-plane average.

The resource decision is to size attention alongside locally resident KV, then select concurrency and coefficient-bank sharing against the desired rate. Neither external weight residency alone nor a fixed 1-TMAC/s attention block closes these requirements. The artifact's 12 `requested_rate_budgets` records preserve all rates, capacities, power remainders and stage bounds; no new large architecture sweep is required to reproduce them.

## Candidate to build and what decides it

Use the [fresh passive-column sizing study](IMC_SIZING_RESEARCH.md) to characterize a **128-row × 16-column load group**, initially retaining one converter per output so the new readout does not inherit arbitrary hold delay. Share row/reference/clock generation where physical loading supports it. Compare 4-/8-fF effective units and supported low-swing references, with a stable four-bit capacitor-code plane. The exact unit structure must be extracted; a 4-fF ideal element is not a drawable Sky130 minimum MIM device.

The first actual 128×8 signed-weight radix replay with matched 0.84-µm resets gives 4.397 fJ/MAC and 424 ns, but **RMS 2.642 MAC, maximum 7.487 MAC, and 34.31-dB deterministic SNR**. It fails the transfer criterion. Increasing only the two matched reset widths to **3.36 µm** repairs the nominal case: **5.140 fJ/MAC, 424 ns, RMS 0.04514 MAC, maximum 0.08930 MAC, and 69.66 dB**. Row TGs remain 0.42 µm and sharing TGs 6.72 µm. This is an eligible nominal transfer anchor, not a completed macro. Do not combine the failed smaller-reset energy with the repaired accuracy; 128-row process corners, noise, mismatch, full ADC acquisition and heterogeneous programs remain gates.

The earlier 16-row, one-column transistor experiment cost **162.97 fJ/A8×W4 MAC** for its fixed unsigned-weight interface. Shared row/reference/clock fanout and actual signed radix experiments subsequently reduced the measured interface cost substantially. The compared programs and operand activity differ, so their energy ratio is not an isolated architectural speedup or a chip-efficiency claim. Positive delivery measured at ideal supply/reference/clock ports still omits the physical generators and the ADC.

The initial activation control should support binary planes and two ordinary nibbles. Preserve wide digital significance reconstruction as the correctness reference. Build analog radix accumulation only if it removes enough measured conversion energy to repay its capacitor ratios, switches, noise and hold time. The old high-duration nibble schedule should not determine the new macro architecture.

The [full-depth capacitor study](IMC_CAPACITOR_SIZING.md) makes **two W4 planes for W8** a valuable quality-preserving option: its INT8 reference is much closer to the original model than naive W4 on the tested passages. With separate conversions, W8 requires twice the W4 ADC services and stored coefficient planes. Shared peripherals double plane service latency; parallel peripherals duplicate hardware. Independent differential programming can require 16 physical control bits per W8 weight versus eight for a W4 pair. New W8 digit activity must be characterized before assigning energy; doubling a W4 energy number is not a validated W8 measurement. The script records these requirements without manufacturing a W8 energy prediction.

The decisive gates are: measured whole-macro reference/clock/reset/readout energy below the inverted budget; settling and output error with real diverse column programs; full-model W8 and adapted-W4 quality using fixed weight mismatch plus temporal converter error; extracted capacitor/configuration density; and a finite-resource KV/interconnect schedule. The 128-row starting point is chosen to test useful ADC amortization without jumping immediately to a 256-row unverified macro. Move to 256 rows, 64-column groups or converter sharing only when the measured Pareto frontier warrants it.

## New radix-accumulator check: fewer conversions with an explicit error budget

The signed 16×8 transistor array subsequently measured **40.29 fJ/A8×W4 MAC of interface positive-port delivery** at 4-fF units, 0.42-µm shared row TGs and eight 44-ns planes. This supersedes the isolated-column interface estimate for that tested array organization. It remains before ADCs, coefficient storage and physical clock/reference generation. A candidate recurrence can remove intermediate conversions, but it also changes the physical loading and phases; its energy cannot be obtained by simply appending one ADC to the existing array trace. [Circuit experiment](IMC_SIZING_RESEARCH.md).

The circuit agent then implemented the recurrence with real transmission gates and real compiler operands. Matching the array and accumulator reset-TG widths corrected distortion of the intended one-half ratio through unequal parasitic loading. The first matched pair used 6.72 µm; a subsequent smaller matched pair used 0.84 µm. With all return/reset edges included, the reported interface points are:

| Physical radix schedule | Total time | Positive-port interface fJ/A8×W4 MAC | Deterministic output SNR |
|---|---:|---:|---:|
| TT, eight planes | 424 ns | 21.10 | 59.62 dB |
| TT, five planes | 265 ns | 14.70 | 69.83 dB |
| SS/85°C, slower five-plane schedule | 865 ns | 15.55 | 42.83 dB |
| TT, five planes, smaller matched 0.84-µm resets | 265 ns | 5.95 | 67.00 dB |
| TT, dynamic 4/5/5 planes, 0.84-µm resets | 247.33 ns average | 5.745 | 67.45 dB |
| SS/85°C, dynamic 4/5/5 planes, 0.84-µm resets | 247.33 ns average | 5.838 | 41.74 dB; fails RMS screen |
| SS/85°C, slower dynamic schedule, 0.84-µm resets | 807.33 ns average | 5.841 | 42.58 dB; fails RMS screen |
| TT, **128 rows × 8 columns**, eight planes, 3.36-µm resets | 424 ns | **5.140** | **69.66 dB** |
| TT, **128 rows × 8 columns**, dynamic 7/6/5 planes, 3.36-µm resets | 318 ns average | **4.500** | **67.57 dB** |
| SS/85°C, 128 rows × 8 columns, same dynamic schedule | 318 ns average | 4.588 | 43.37 dB; fails RMS screen |
| SS/85°C, same 128×8, sharing interval 7.6→15.6 ns | 366 ns average | **4.587** | **62.47 dB; full-word PASS** |

Unless stated otherwise, table rows use 16×8 arrays. These are physical sampling/accumulation results with **one planned final ADC not instantiated**. The five-plane run uses a static choice for its actual-input block; dynamic runs physically use B=4/5/5. Dynamic calibration uses **eight words: six gain-calibration inputs plus two zero words**, one for each B. Startup calibration energy must be amortized separately. The two small-reset SS cases have full-accumulator RMS **0.2835 / 0.2572 MAC**, both above the strict 0.25-MAC screen; their top-level `transfer_pass` covers individual plane transfer and must not override `accumulator_transfer_pass=false`. The deterministic SNR excludes transient noise, converter error and capacitor mismatch. A +1% accumulator-capacitor falsifier falls to **36.45 dB**, so nominal ratio matching is not a manufacturing-yield result. W8 still requires the separate second W4 coefficient plane and its service/energy.

A matched five-plane **0.84-µm-reset** comparison uses the same actual inputs and row drivers: separate plane sampling costs **3.74049 fJ/MAC and 220 ns**, while radix costs **5.94655 fJ/MAC and 265 ns**. The accumulator therefore adds **2.20606 fJ/MAC and 45 ns** to remove four intermediate ADC services per output. At 16 rows, the interface surcharge is **35.30 fJ per output**; saving four ADCs repays that energy only if the new final conversion and other control costs also satisfy the same error budget. The older matched 6.72-µm-reset comparison similarly added 3.338 fJ/MAC and 45 ns. Reset resizing is distinct from eliminating conversion events.

The repaired 128-row interface gives a concrete inverse budget for the stronger targets. At **100 TOPS/W**, its 5.140-fJ/MAC interface leaves **1.902 pJ per useful output** for the ADC and all remaining work; at **250 TOPS/W**, only **0.366 pJ** remains. Reserving one additional checksum ADC for eight useful columns lowers the complete-ADC-only allowance to **1.691 / 0.325 pJ per conversion**, before the checksum's own interface energy, SRAM, references, control, links or leakage. Every 1 fJ/MAC allocated to other work removes 0.1138 pJ from that allowance. These are W4-probe requirements, not proof that the final readout achieves them. The W8 engine must pay for both coefficient planes within its logical-MAC target; the second plane's measured energy is still missing.

For a concrete conservative accounting scenario, **duplicate the measured W4 schedule for the two W8 coefficient slices**. This assumes equal slice activity/interface cost and is not a measured W8 result; common input-driver sharing could change it and needs characterization.

| Logical mode / accounting | Interface fJ per logical MAC | ADCs per useful 128-term output | ADC-only allowance at 100 TOPS/W | At 250 TOPS/W |
|---|---:|---:|---:|---:|
| Measured W4 interface | 5.140 | 1 | 1.902 pJ | 0.366 pJ |
| W8 with two duplicated W4 schedules | 10.281, assumed | 2 | 0.622 pJ each | Impossible before ADCs |

These allowances omit checksum and every unmeasured cost. Including one checksum conversion per eight outputs reduces the W8 100-TOPS/W allowance to **0.553 pJ per ADC**, before extra checksum interface energy. The stronger 250-TOPS/W goal therefore needs a further circuit or representation change if model quality requires W8. The W8 quality result cannot be paired with the single-slice W4 energy number.

The completed **dynamic 128-row** replay improves the nominal W4 interface to **4.499905 fJ/MAC**, with actual word times **371 / 318 / 265 ns** and 318 ns average. It uses nine calibration words, including three zero words for B=7/6/5. Full-accumulator RMS is **0.05741 MAC**, maximum 0.11807, and deterministic SNR 67.57 dB. Its SS/85°C replay fails: RMS **0.93095 MAC**, maximum 1.75398, at 4.5878 fJ/MAC and the same timing. The new nominal W4 ADC-plus-other allowance is **1.984 / 0.448 pJ per output** at 100/250 TOPS/W. Duplicating that dynamic schedule for W8 gives an assumed **9.000 fJ/logical MAC** and **0.704 pJ per ADC at 100 TOPS/W**, or **0.626 pJ including checksum conversions**; it still exceeds the entire 250-TOPS/W budget before ADCs. Real W8 low-magnitude digits can reach 15 rather than the saved INT4 fixture's magnitude 7, so their activity, capacitance and energy must be measured instead of assuming exact duplication.

The new [behavioral test](../../../../scripts/compiler/metrics/imc_radix_budget.py) establishes the arithmetic and error requirements independently of SPICE. Let `m_b = sum_i(w_i*sign(x_i)*bit_b(abs(x_i)))`, with per-column plane voltage `z_b=g*m_b`, relative to common mode. Equal-capacitor sharing gives

`h_0=0; h_(b+1)=(h_b+z_b)/2`.

Processing eight **LSB-first** planes gives `h_8=g*(W x)/256`. Exact checks cover every signed INT8 scalar code, including −128, signed cancellation and zero input. Resetting the accumulator between planes is a failing control: it destroys the earlier significance terms.

The array resets each plane; the accumulator resets only once. After evaluating a plane, share, isolate the accumulator, then return/reset the array. Returning row voltages while the accumulator remains connected changes the stored charge and is not this recurrence. Connecting a previously absent ADC sampling capacitor at the end adds attenuation `Cacc/(Cacc+CADC)` and sampling error; calibrating the attenuation does not remove the resulting input-referred ADC noise.

For the implemented weighted array, `Carray=120 fF+Cu*sum_i|w_i|`. The accumulator must match **each column's actual total capacitance**, including connected parasitics. A common nominal value is insufficient. With `Cacc=(1+delta)*Carray`,

`a=(1+delta)/(2+delta); h_next=a*h+(1−a)*z`.

The recovered bit-b coefficient, relative to its ideal value, is `2^(8−b)*(1−a)*a^(7−b)`. For small delta its fractional error is approximately `(6−b)*delta/2`. A scalar column calibration can correct common gain, but the LSB/MSB coefficient ratio still changes by approximately `3.5*delta`. General per-bit gains or settling differences multiply these coefficients and cannot be assumed equivalent to one output offset.

The test uses the first 8 outputs × 16 inputs of seven real compiler matrices, six saved positions for calibration and three for evaluation, plus a separately labeled full-range synthetic stress set. For FFN-down the eight column totals range **148–204 fF**. After scalar calibration, replacing their matched accumulators with one mean capacitance leaves **25.96-dB** output SNR in the dynamic-plane experiment. A uniform 0.3% ratio error gives **57.06 dB**, and 1% gives **46.64 dB**, on those three tokens. These are small deterministic behavioral results, not manufacturing tolerances or model-quality guarantees; the full-range and other-tensor results remain in the artifact.

### Skip unused high bits before they attenuate the answer

Compute `B=bit_length(max_i|x_i|)` for the current row group and process only planes 0 through B−1. Then `h_B=g*(Wx)/2^B` exactly. All-zero groups need no ADC. The decoder needs B metadata and a variable shift; the max/leading-bit logic and scheduling cost belong in the design. Unused interior planes still require the halving operation. Initial zero low-bit planes can be omitted while the accumulator remains at zero, with reconstruction retaining the original B exponent.

The FFN-down held-out inputs require **B=[4,5,5]**, rather than eight planes each. Their final voltage RMS rises from **1.369 to 12.575 mV**. There are **24 final ADC events**, versus **112** for a separate-conversion implementation that also skips unused high bits: a **4.67× count reduction for this stream**, not an unconditional 8×. Full-range inputs can still require eight planes. Static per-column converter ranges are fitted on calibration inputs only; changing B changes digital reconstruction, not the stored weights.

To check selection bias, the script also counts **every row group and every output tile in all seven saved compiler matrices**, on xq[6:9], with zero-padding of the last row group. Output tiles have 16 useful columns. Results below weight B by data-column ADC services; all these row groups are nonzero. They remain the current compiled subset, not all layers of the model.

| Rows/group | Mean B / maximum | Separate data ADC events | Final data ADC events | Separate/final count ratio |
|---|---|---:|---:|---:|
| 16 | 5.389 / 7 | 2,831,104 | 525,312 | 5.389× |
| 64 | 6.106 / 7 | 801,920 | 131,328 | 6.106× |
| 128 | 6.410 / 7 | 457,856 | 71,424 | 6.410× |

MSB skipping reduces separate-conversion events by **32.6%, 23.7% and 19.9%** versus always running eight planes. Larger row groups encounter higher outliers more often. At 16 rows, per-tensor mean B ranges from **4.760 (FFN-down) to 5.815 (FFN-up)**; every tensor reaches B=7 somewhere. A universal static five-plane schedule would therefore be incorrect. The artifact records each tensor's full B histogram and separate checksum events, one per output tile: for R=16 these add **176,944 separate / 32,832 final** conversions. Useful-MAC-weighted mean B is also stored; it differs at R=128 because of padding (**6.448**, versus 6.410 for service weighting). These count reductions do not establish a shared accuracy budget or a chip-energy gain.

### One unchanged ADC does not match eight independent ADCs

With independent voltage error sigma on each separate plane conversion, the reconstructed variance is

`Var_separate = (sigma/g)^2 * sum_(b=0..7) 4^b = 21845*(sigma/g)^2`.

One final conversion has `Var_final = 65536*(sigma_final/g)^2`. The same ADC therefore produces **3.000046×** the error variance. Matching it requires `sigma_final <= 0.577346*sigma`, approximately **0.7925 additional effective bits**, before sharing errors. A half-size final input range is legal under the worst-case signed-INT8 amplitude bound and reduces quantization error, but fixed comparator/reference voltage noise does not halve with the range.

If each sharing operation adds independent held-voltage error eta *after* the average, it contributes `87380*(sigma_eta/g)^2` to the eight-plane result. Initial accumulator reset error contributes only `(sigma_reset/g)^2`; new array-plane errors retain the same significance weighting as separately digitized planes. None of these independence assumptions certifies physical switch noise or covariance.

For an illustrative separate nine-bit/1-V ADC with 0.2-mV fixed read noise, and sharing variance `kT/(2*Cacc)` at Cacc=300 fF, a final ten-bit converter gives **1.079×** the separate-conversion error variance; eleven bits gives **0.579×**. This sharing-noise expression is a topology-dependent analytical assumption, not a transient-noise measurement. The ADC energy may grow substantially with precision, so the conversion-count ratio is not an energy ratio.

Actual FFN-down conditional results, including 0.2-mV ADC noise and the same sharing-noise assumption:

| Schedule / final ADC | Voltage range | Conditional SNR |
|---|---|---:|
| Fixed eight planes / 9 bits | 1 V | 6.68 dB |
| Dynamic B / 9 bits | 1 V | 26.89 dB |
| Dynamic B / 9 bits | Static per-column calibration | 34.63 dB |
| Dynamic B / 11 bits | Static per-column calibration | 34.72 dB |

Extra quantizer bits reach a noise floor. At the dynamic nine-bit calibrated-range point, quantization RMS is **0.0946 MAC** and assumed sharing-noise RMS is **0.3373 MAC**. Reaching an illustrative 36.74-dB output target requires ADC read noise at most **134.5 µV**, before actual plane-transfer error, coefficient mismatch, covariance or final sampling disturbance. The older full-depth Gaussian-noise threshold must not be treated as a universal acceptance condition for this error family.

The valid energy decision is therefore

`E_final_ADC + sum(E_share+E_hold+E_extra_control) < sum(E_separate_ADCs)`

at the **same declared output-error/model-quality budget**, using remeasured array energy where loading changes. Timing must include every evaluation, share, isolation, reset/return and final conversion, with only physically supported overlap. The recurrence provides an exact route to fewer conversions; the physical accumulator and complete ADC must show that the saved operations are worth their precision and sharing costs.

### The repaired 128-row transfer exposes a harder readout case

The behavioral artifact now includes the exact **first eight FFN-down outputs × first 128 inputs** used by the repaired transistor replay. Its integer outputs match the physical fixture. On the three held-out inputs, the true dynamic exponent schedule is **B=[7,6,5]**; final ideal voltage RMS rises from **1.980 mV at fixed eight planes to 6.688 mV**. The subsequent dynamic physical run independently uses that same schedule; the voltage/noise figures here remain the ideal-capacitor behavioral budget.

The simple per-column ADC range fitted with 20% headroom on the first six calibration words **clips 2/24 held-out outputs at fixed eight planes and 4/24 dynamically**. The favorable small-array range result therefore does not transfer automatically. Even an unclipped 11-bit/1-V dynamic ADC gives only **27.97-dB conditional SNR** with 0.2-mV fixed read noise and the stated sharing-noise model. Nominal deterministic transfer at 69.66 dB does not close this readout budget. More representative range calibration, exponent-aware gain/range control, actual low-noise acquisition and model-level error characterization are the next useful gates. Higher ADC bit count alone does not remove fixed input-voltage noise or clipping.

### Diagnose the slow corner before adding capacitance

The [read-only settling diagnostic](../../../../scripts/compiler/metrics/imc_radix_settling_diagnosis.py) loads the existing TT/SS traces and first reproduces their reported full-word errors. Row evaluation and reset length do not control the **fixed 7.6-ns fully-on sharing interval**. Immediately before share-off, SS accumulator voltage still changes by **10.41 µV/ns RMS**, versus 0.70 µV/ns at TT. The two plates' differential voltage alone underestimates this error: the loaded row network also moves their common voltage while they share.

Fit the final settling tail using **only the six calibration words, 42 planes**. With samples at 6, 7 and 7.9 ns after the plane sample, let `a=h7−h6` and `b=h7.9−h7`. A per-column least-squares ratio `dot(a,b)/dot(a,a)` determines the exponential time constant; extrapolated remaining tail is `b/(exp(0.9ns/tau)−1)`. SS fitted tau is **1.69–2.06 ns**, giving a **15.63-µV RMS** residual tail. Propagating that correction through subsequent one-half recurrences, while retaining the original calibration procedure, predicts RMS **0.931→0.179 MAC** and maximum **1.754→0.387 MAC**. This extrapolation assumes unchanged switching behavior and is an experiment-selection model, not a substituted circuit result.

The resulting single-knob circuit experiment extends sharing **7.6→15.6 ns**, shifting share-off and all dependent return/reset edges together. Row evaluation stays 8 ns; row/reset/share widths stay 0.42/3.36/6.72 µm. **Fresh SS/85°C SPICE confirms the repair:** RMS **0.10333 MAC**, maximum **0.22338 MAC**, **62.47 dB**, passing the original `<0.25 RMS / <1 maximum` gate. The slot rises 53→61 ns; actual B=7/6/5 word times become **427/366/305 ns**, averaging **366 ns**. Interface energy is **4.58724 fJ/MAC**, effectively unchanged at the displayed precision. This closes this deterministic corner/fixture failure, not transient noise, yield or the larger W8 capacitor loads. Artifact: `build/sim/imc_sizing_research.json`, `share_settling_repair`.

Zero-word calibration also deserves a separate control: retaining the measured zero and fitting gain through the origin reduces the original SS error from 0.931 to 0.358 MAC, while worsening calibration-set RMS. It does not by itself meet the original full-word gate. The successful physical repair above keeps the original affine calibration; no acceptance threshold was relaxed.

## Reproduction

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 scripts/compiler/metrics/imc_architecture_search.py
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 scripts/compiler/metrics/imc_radix_budget.py
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 scripts/compiler/metrics/imc_radix_settling_diagnosis.py
```

Executed with the cached Nix Python/NumPy environment. The run takes approximately one second. Artifacts: `build/research/imc_architecture_search/results.json` and `summary.json`, including all assumptions, source fingerprints, exact operation counts, per-resource rates, rejected constraints, component frontier and inverse budgets.

The radix experiment writes `build/research/imc_radix_budget.json`, recording all column capacitances, held-out ratio/gain/reset sweeps, ADC range/precision/noise cases and source fingerprints. Its arithmetic, reset, sign and cancellation controls pass; this behavioral PASS does not validate a fabricated radix accumulator.

**PASS** checks reproduce the historical energy/timing anchor, preserve conversion counts under ADC sharing, enforce the sharing latency/static cost, preserve per-token work across batching, scale KV capacity, reject an impossible refresh duty and verify Pareto dominance. These checks validate the model's implementation and arithmetic. They do not certify the assumed circuit scaling or the target chip.
