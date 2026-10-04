# Outlier-channel routing to reduce radix planes

2026-09-07. Exact behavioral experiment on frozen compiler artifacts; no SPICE, complete ADC, physical digital residual engine or full-model quality result.

**One selected channel per 128-row block does not reach the proposed 1.493× relative noise-improvement screen.** It schedules **0.850%** of MACs on an exact digital path. Static channel choices increase pooled tolerance to final-read noise by **1.134×**; even a per-token largest-magnitude control reaches only **1.298×**. Both are below the **200/134 = 1.493×** heuristic motivated by the earlier readout budget. This rejects that uniform one-channel-per-block configuration for this particular screen, not all possible allocations of a 1% global precision budget. The threshold is a relative screening choice, not an absolute ADC feasibility test.

Higher fractions sometimes pass the pooled ratio, but individual tensors remain limiting: even the dynamic four-channel configuration permits only **158.6 µV** for FFN-up at the illustrative 36.74-dB output-SNR target, before other noise sources. Outlier routing is a useful selective tool; it is not a demonstrated replacement for a low-noise readout.

## Inputs, policies and invariants

The [self-checking experiment](../../../../scripts/compiler/metrics/imc_outlier_planes.py) evaluates the complete `Wq`/`xq` arrays for `attn_q`, `attn_k`, `attn_v`, `attn_o`, `ffn_gate`, `ffn_up`, and `ffn_down`. Shapes range from 64×576 to 1536×576 and 576×1536. All contiguous input blocks are included at nominal row counts **16, 64 and 128**, including shorter final blocks. Input positions 0–5 select static channels; positions 6–8 are scored. The existing upstream smoothing/quantization was fitted on the saved compiler stream, so these are held-out positions for the **new routing choice**, not independent model deployment data.

For each block, test the fixed menu of zero, one, two and four precise rows:

- **Static:** choose largest `max(abs(x))` over the first six positions; equal magnitudes choose lower channel indices. Freeze that support for evaluation.
- **Dynamic control:** choose largest `abs(x)` separately for each token, with the same index tie-break. This minimizes the remaining maximum magnitude for a fixed number of excluded rows. It requires runtime selection and weight access.

Both policies still detect the analog block's highest nonzero magnitude bit at runtime; “static” refers to the selected channel set, not a fixed plane count. Every policy is reported. No policy, threshold or support is selected by held-out reconstruction error.

Set selected activation channels to zero on the analog path and compute their original signed W4×A8 products digitally. The integer identity is `W*x = W*x_analog + W*x_precise`. Exhaustive signed-eight-bit scalar/radix controls include **−128**, zero and cancellation; all **147 full-tensor cases** assert the exact integer partition and product identity. The residual preserves the already quantized compiler result; it does not recover FP32 weights or repair its existing quantization error.

## Voltage and noise model

Reuse the exact matched-capacitor radix identity from [imc_radix_budget.py](../../../../scripts/compiler/metrics/imc_radix_budget.py): for `B = bit_length(max(abs(x_analog)))`, the held voltage is `h = g*y_analog/2^B`. Assume a 4-fF weight unit, ±0.45-V excitation, 120-fF fixed load, and a per-output accumulator matched to `Carray = 120 fF + 4 fF*sum(abs(Wq))`; thus `g = 4 fF*0.45 V/Carray`.

**Physical capacitance is unchanged by routing.** Excluded rows remain present, with zero excitation; there is no assumed removal of their weight capacitors or parasitics. The proxy `2^(B_baseline-B_new)` is the improvement in volts per remaining analog integer MAC at fixed capacitance. It need not increase the actual output RMS voltage, since the removed products also change the analog signal and its cancellations. Both statistics are in the artifact.

For independent final-ADC voltage noise of standard deviation `sigma`, each active input block contributes output-error variance `sigma²*(2^B/g)²`. Sum these variances across blocks before scoring the complete tensor output. An all-zero analog block skips its ADC. Pooled tolerance gain is `sqrt(sum(K_baseline)/sum(K_policy))`, where `K` is this noise coefficient over all scored tensor outputs. The aggregation weights raw integer-output error; it does not weight token quality, dequantization scales or tensor sensitivity.

The **134→200-µV** motivation is only that variance-ratio comparison. The earlier 134-µV scenario arose from a different 16×8 FFN-down fixture with additional modeled noise; it cannot become an absolute R128 allowance by multiplication with this pooled gain. A separate per-tensor allowance derives from the exact integer-output signal and an illustrative 36.74-dB SNR. Both screens include **final read noise only**: quantization, clipping, sharing/reset/filter noise, mismatch, offset, parasitics and correlations are absent. No finite-resolution ADC, range calibration or noisy quantizer is simulated.

## Results at 128 rows

Mean B is weighted by useful MACs, including the actual length of short blocks. Precise-work percentages count every scheduled selected-row product, including zero activations; useful dense W4×A8 products define the denominator.

| Selection | Precise rows/block | Precise MACs | Mean analog B | Pooled noise-tolerance gain | Gain ≥1.493×? |
|---|---:|---:|---:|---:|---|
| Baseline | 0 | 0% | 6.448 | 1.000× | No |
| Static | 1 | 0.850% | 6.204 | 1.134× | No |
| Static | 2 | 1.700% | 5.996 | 1.369× | No |
| Static | 4 | 3.399% | 5.782 | 1.727× | Yes |
| Dynamic | 1 | 0.850% | 5.914 | 1.298× | No |
| Dynamic | 2 | 1.700% | 5.631 | 1.777× | Yes |
| Dynamic | 4 | 3.399% | 5.330 | 2.184× | Yes |

The static support does not reliably capture FFN-down's largest held-out channels: selecting one channel reduces B on only **2/36 block-token pairs**. Dynamic selection reduces B on **18/36**, giving **1.781×** FFN-down read-noise tolerance versus **1.064×** for static selection. Conversely, static one-channel routing gives no B reduction on any of attention-K's **15** held-out block-token pairs. Attention-O has only 64 input channels, so its single “128-row” block is physically half full and one selected channel costs 1.5625% of its own MACs.

The read-only allowances below show why the pooled result cannot establish universal closure:

| Tensor at R=128 | Static one-channel allowance | Dynamic one-channel allowance | Static four-channel allowance | Dynamic four-channel allowance |
|---|---:|---:|---:|---:|
| FFN-down | 144.2 µV | 241.4 µV | 171.3 µV | 357.0 µV |
| FFN-gate | 110.2 µV | 135.6 µV | 177.1 µV | 225.2 µV |
| FFN-up | 88.6 µV | 92.6 µV | 135.9 µV | 158.6 µV |

Each value targets illustrative 36.74-dB complete-tensor integer-output SNR with final-read noise alone. It is not an accepted model-quality threshold.

Smaller blocks require more precise work for the same row count. At R=64, one row costs **1.5625%**, with **1.340× static / 1.474× dynamic** tolerance gains. At R=16, one row costs **6.25%**, with **1.527× / 1.728×** gains. All row counts and B/drop histograms are retained in the artifact rather than choosing one setting from evaluation results.

## Storage, ports and service costs

At R=128, static one-row selection duplicates **95,232 W4 payload bits = 11.625 KiB** across these seven matrices, plus **266 index bits** for 38 input blocks. Two/four selected rows multiply those payloads by two/four. This is a lower bound: SRAM organization, precision accumulators, masks, routing, checksum work and control add overhead. Keeping selected weights in nearby registers may avoid repeated SRAM access, but does not remove their delivery or MAC energy.

Dynamic selection can request any weight channel. It therefore requires read access to **all 11,206,656 W4 bits = 1.336 MiB** represented here, or a digital shadow when resident analog storage cannot expose those values. This is an access requirement, not a claim that a second full memory is always necessary. At one selected row, the nominal selected weight payload is **95,232 bits/token**; three scored tokens consume 285,696 weight operand bits, and their dynamic indices use **798 bits**. Payloads exclude banking, read-port area, repeated fanout and alignment. Magnitude comparisons, selection, activation broadcast and B detection are not free.

The precise engine must service each block's selected rows before digital recombination can complete. An average 0.850% fraction does not prove sufficient peak bandwidth or hide a serial dependency. ADC integer scaling, finite-word accumulation and checksum regeneration need implementation. This experiment predicts neither tokens/s nor tokens/J and assigns no energy to an unbuilt precise engine.

The decomposition is related to [LLM.int8()](https://arxiv.org/abs/2208.07339), which isolates outlier feature dimensions into a higher-precision matrix product. This experiment instead preserves frozen W4/A8 arithmetic and asks about analog radix scaling. [NORA](https://research.ibm.com/publications/nora-noise-optimized-rescaling-of-llms-on-analog-compute-in-memory-accelerators) motivates input/output noise-aware optimization, but its rescaling algorithm is not implemented here. This is an independently derived engineering experiment, not a novelty claim or reproduction of either paper's headline gains.

## Reproduce

Run the script with the existing Nix NumPy Python environment:

```sh
python3 scripts/compiler/metrics/imc_outlier_planes.py
```

Output: `build/research/imc_outlier_planes.json`, containing all 147 records, selections, B histograms, conditional noise coefficients, payload costs and SHA-256 hashes of all 14 input artifacts. **PASS:** signed-code/radix identity, exact residual recombination, stable ties, calibration isolation, and dynamic remaining-maximum checks. No SPICE or source compiler artifacts are modified.
