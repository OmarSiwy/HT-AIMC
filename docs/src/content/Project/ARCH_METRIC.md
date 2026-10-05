# Architecture metric (the objective the architecture search maximizes)

2026-10-05. Agreed with the user before the search launched. Every candidate, including the
digital systolic reference, is scored with this definition and nothing else.

## Ranking

Strict order, tok/s first:

1. **tok/s per die** (king)
2. **TOPS/W**
3. **tok/W**
4. **tok/J**

A higher-ranked metric wins outright. Every Pareto point the search finds is still recorded
(versioned in commit history with its four numbers), and every path is studied, so a design
that trades 10x TOPS/W for tok/s is documented even when it is not the pick.

## Definitions

| Symbol | Definition |
|---|---|
| Process | ASAP7 (7 nm FinFET, predictive), TT 25 C for scoring. Sky130 data is the calibrated anchor only. |
| Die | Iso-area: every candidate gets the same **A_die = 100 mm²** (knob). Results are also given per mm² so another die size can be read off. |
| Power density cap | P_die <= **1 W/mm²** (knob, thermal sanity). |
| Workload | **Llama-3-8B layer shapes**: 32 layers, d=4096, FFN 14336 (SwiGLU), 32 Q heads, 8 KV heads, d_head 128, vocab 128256. Model size is otherwise free: the architecture must run any transformer's GEMM and GEMV. |
| Request | 512-token prompt (prefill, GEMM) + 128 generated tokens (decode, GEMV). |
| tok/s per die | Steady-state processed tokens (prompt + generated) per second of the whole system, divided by the number of iso-area dies the system uses. Generated-only tok/s is reported alongside. Concurrency is free (throughput-optimal) but bounded by KV capacity and a per-stream decode floor of **>= 20 tok/s** (knob). |
| Weight memory | Resident across N dies **or** streamed from external DRAM and rewritten into the arrays (or a hybrid). This is a decision in the tree, not an assumption. Default external memory if streamed: one HBM3-class stack per die, 819 GB/s, 24 GB, 4 pJ/bit (knob). Die-to-die: 2 TB/s per die at 0.5 pJ/bit (knob). |
| TOPS/W | 2 x useful model MACs/s (the workload's MACs, including QK^T and A·V; excluding padding, checksum columns, bit-slice replicas and redundancy) over **die power** (everything on the die: arrays, converters, drivers, digital rail, SRAM, PHY). Excludes the DRAM device. Measured at the peak-tok/s operating point. The precision-normalized value (27n1) is reported alongside. |
| tok/W | tok/s per die divided by (die power + that die's external memory access power), at the **peak-tok/s operating point**. Not gameable by slowing down. |
| tok/J | Best tokens per joule over **any** operating point (VDD in [0.45, 0.7] V, any clock, any concurrency). Gameable by running slow, which is why it ranks last. |
| Quality gate | **Set by the research** (decision node N8), justified from the notes and the literature, and measured numerically on SmolLM2-135M (in repo) as the proxy. Compiler and hardware co-design (re-quantization, rotation, hardware-aware fine-tuning) is allowed and must be counted when used. |
| Scope | Analog / mixed-signal IMC only. The digital systolic array in `digital/sysreference/` is the baseline it has to beat, not a candidate. |
| Labels | Every number is **measured** (SPICE / RTL sim / synthesis here), **derived** (law on measured params) or **projected** (literature/law only). |

## Verification ladder for the pick

Verilog-A behavioural model (VerA/ESPice) proves the architecture is sound, then the ASAP7
transistor-level SPICE circuit. Post-layout is out of scope.

## Design direction (user, 2026-10-05)

These steer the search. The first three are constraints; the rest is the leading hypothesis,
which the search must test honestly against SOTA and the alternatives, not assume.

1. **The tile is the only heavy part, and it should be lightweight too.** Every add-on to the
   tile (sidecars, extra columns, per-cell extras) must pay for itself on the metric. The
   rank-1 LoRA sidecar does not count toward inference metrics: drop it unless it is shown to
   help them.
2. **No SRAM bitcells in the tile.** Weights are stored as analog quantities (charge or
   voltage on a capacitor, gain cell, or similar) written by the compiler's flow.
3. **No PWM inputs by default.** Time-encoding activations costs 2^b time steps per pass;
   use it only if it wins on tok/s.
4. **Use numerics to make pre- and post-processing nearly free.** Choose number formats so the
   tile does the arithmetic and the digital work around it shrinks. Wide fixed-point
   accumulators, nibble/slice recombination and requantization are costs to remove, not givens.
5. **Leading hypothesis: a log-domain, float-in/float-out tile.**
   - The compiler stores weights and streams activations in logarithmic form (LNS, close to a
     float's exponent + mantissa).
   - Multiply = adding logs = charge sharing between the weight and activation capacitors.
   - A MOSFET in subthreshold (or another exponential device) turns the shared voltage back
     into a linear current or charge, so the column sum is plain charge accumulation (KCL).
   - Results are read out as floats (exponent + mantissa, or log), avoiding a wide fixed-point
     conversion. Floats may enter via the write path or the compiler.
   - Known issues from this repo's sky130 study (`IMC_LOG_PIPELINE_CRITIC.md`,
     `IMC_LOG_GMID_ROUND.md`): equal-cap sharing averages the logs (√(x·w)) unless the
     exponential slope matches the log slope; the slope tracks kT/q and needs a live
     reference; V_th mismatch is exponentiated; signs and zero need explicit handling; a word
     took 1.8 µs on sky130, which is the tok/s problem to solve at ASAP7's 0.7 V.
6. **Research method.** Combine digital computer-arithmetic theory (LNS, Mitchell/Gaussian-log
   tricks, floating-point and block-floating formats, exact accumulators) with SOTA analog
   IMC theory and analog multiply-accumulate cells (charge sharing, translinear/current-mode,
   time-domain, capacitive, floating-point CIM), and the strengths and limits of FinFET devices
   at 0.7 V (subthreshold slope, mismatch, leakage, headroom). Be creative: transfer ideas
   across these fields.
