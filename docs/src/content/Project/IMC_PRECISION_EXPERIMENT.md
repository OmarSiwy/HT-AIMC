# Selective precision: a new held-out full-depth experiment

2026-09-07. **Result: protecting one FFN-down tensor, representing 0.833% of MAC work across the model's seven weight-projection types, reduces simulated output-distribution error by approximately 5–8× on the tested passages.** Protecting the equally sized neighboring tensor gives essentially no improvement. This supports a small selectively precise compute path; it does not establish a whole-chip speed or energy improvement.

The hypothesis came from the previous [depth study](../../../../scripts/compiler/metrics/DEPTH_BUDGET.md), the user's notes 27k2/27k5/27l11, and newer heterogeneous precision/noise-aware adaptation papers. The old study selected layer 11 using README/AGENTS text. This experiment fixes that choice, then scores previously unused passages from the user's `27l1` and `27h1` notes. No tensor is selected after inspecting the new results.

## Method

- Full 30-layer SmolLM2-135M forward, all nine query heads, GQA, RoPE and tied language-model head, using the existing `depth_budget.Net` implementation.
- Two held-out technical-note passages, 256 tokens each, with seeds 70/71 paired across configurations. These are two passages, not four independent corpora. Tokenization remains the repository's greedy tokenizer; Markdown prefixes remain present.
- Teacher-forced causal scoring, not autoregressive token generation or a decode timing benchmark. Perplexity covers 255 next-token transitions per passage; KL also includes the final output distribution.
- Additive MVM-output noise at nominal SNR 28.45 or 36.74 dB. Noise scale depends on the whole current output tensor's variance. This is not fixed-LSB ADC-residual replay, measured device noise, or a universal analog error model.
- Four configurations: all seven MVMs analog; protect only `blk.11.ffn_down`; protect `blk.10.ffn_down` as an equal-work sham; protect all 30 `ffn_down` tensors.
- Protected math is ideal **relative to the current weight-mode reference**. It does not add precision to quantized weights. All other MVMs retain noise. Standardized random draws are paired; later amplitudes can change as activations change.
- Repeat with dequantized Q8_0 weights and naive per-output-channel RTN INT4 weights. The latter is a control, not the deployed smoothed W4A8 compiler path. Activations and KV remain floating point apart from the injected output noise.

## Results

Mean KL is averaged across two passages and two noise seeds. A lower KL means a closer output distribution to that weight mode's clean reference. PPL ratios are relative to the **same** weight mode's clean reference.

| Weights | Injected SNR | Protected work | Mean KL, nats | Mean PPL ratio |
|---|---:|---|---:|---:|
| Q8 dequantized | 28.45 dB | None | 0.44535 | 1.5741 |
| Q8 dequantized | 28.45 dB | Layer-11 down, 0.833% | 0.05586 | 1.0731 |
| Q8 dequantized | 28.45 dB | Layer-10 down sham, 0.833% | 0.44630 | 1.5764 |
| Q8 dequantized | 28.45 dB | All down, 25% | 0.03353 | 1.0414 |
| Q8 dequantized | 36.74 dB | None | 0.04756 | 1.0719 |
| Q8 dequantized | 36.74 dB | Layer-11 down, 0.833% | 0.00808 | 1.0150 |
| Q8 dequantized | 36.74 dB | Layer-10 down sham, 0.833% | 0.04755 | 1.0716 |
| Q8 dequantized | 36.74 dB | All down, 25% | 0.00487 | 1.0081 |
| Naive RTN INT4 | 28.45 dB | None | 0.55533 | 1.7653 |
| Naive RTN INT4 | 28.45 dB | Layer-11 down, 0.833% | 0.10275 | 1.0960 |
| Naive RTN INT4 | 28.45 dB | All down, 25% | 0.06951 | 1.0578 |
| Naive RTN INT4 | 36.74 dB | None | 0.07426 | 1.0982 |
| Naive RTN INT4 | 36.74 dB | Layer-11 down, 0.833% | 0.01478 | 1.0189 |
| Naive RTN INT4 | 36.74 dB | All down, 25% | 0.00983 | 1.0112 |

The full artifact retains every sham result and seed. At 36.74 dB the protected Q8 case has KL near the old 0.01 proxy gate, but its PPL increase ranges from **0.14% to 2.38%** across the four runs. It therefore does **not** establish a universal +1% quality guarantee. At the nominal 28.45-dB point, protection alone is plainly insufficient for such a strict budget.

The INT4 reference itself has PPL **90.04 vs 43.77** on the first passage, and **124.88 vs 60.53** on the second—approximately **2.06×** the Q8-dequantized reference before any analog noise. A near-one *marginal* ratio in the INT4 rows cannot be called recovery to the original model. This is evidence that model adaptation and improved quantization must accompany circuit work.

## Implication for chip design

The seven MVMs account for 106,168,320 MACs/token in this model, excluding dynamic attention and the LM head. One down projection has 884,736 MACs: **1/120** of that work. Protecting every down projection costs 25%, for a much smaller incremental accuracy gain than selecting the single sensitive tensor.

If that protected fraction f uses r times the energy/MAC of the bulk analog path, the weight-MVM energy factor is `1 + f*(r-1)`. At f=1/120 and r=10 it is **1.075**, a conditional 7.5% premium. This does not include digital-island area, weight storage, routing, buffering or idle power. A small work fraction can still dominate latency unless the precise engine's service rate meets the schedule.

The practical candidate is **per-tensor precision with a resident digital or calibrated high-precision path**, alongside analog-aware range training for the bulk. Fixed tensor selection may change by model or context. The experiment does not justify spending its apparent accuracy improvement on a particular cascade depth: the cascade/dataflow model and the real physical error distribution remain separate gates.

## Reproduction and faster iteration

```sh
OPENBLAS_NUM_THREADS=2 python3 scripts/compiler/metrics/imc_precision_experiment.py
OPENBLAS_NUM_THREADS=2 python3 scripts/compiler/metrics/imc_precision_experiment.py --quick
OPENBLAS_NUM_THREADS=2 python3 scripts/compiler/metrics/test_fast_depth.py
```

Use the repository NumPy environment and local GGUF. The executed environment was `/nix/store/qk5sl1xvg05cmqh03mn1srdggj39dg7p-python3-3.12.13-env/bin/python3` (NumPy 2.4.4).

`--quick` uses one 64-token passage, one seed, one SNR and Q8 only, saves a separate `_quick.json`, and is **screening only**. Its much shorter context produces different sensitivity and perplexity; never substitute its results for the full experiment.

The simulator now uses batched matrix multiplication for attention and partial vocabulary selection for top-five metrics. A paired three-repeat benchmark on the 256-token model forward measured **1.692 → 0.923 s (1.83×)**; vocabulary top-five selection measured **0.270 → 0.035 s (7.80×)** over five repeats. These component gains overlap within the full iteration and must not be multiplied. Full logits agree within the tested numerical tolerance; greedy and top-five predictions match, and KL between implementations is below 1e-7. Top-five selection matches the old sort exactly, including tied boundaries. The original attention summation order remains available with `Net(fast_attention=False)`.

Numerical checks passed: zero-noise reference, protected-call placement, paired draws, 210 MVM calls, tied/random vocabulary selection and full-model parity. Artifacts: `build/research/imc_precision_experiment.json`, `imc_precision_experiment_quick.json`, and the original pre-optimization result retained as `imc_precision_experiment_original.json`.

The entire 64-case experiment was rerun after acceleration and completed in **130.4 s**. Against the original run, maximum KL change was **7.97e-7**, maximum PPL-ratio change **2.09e-6**, and argmax/top-five metrics were identical in every case. Quick screening completed in **16.8 s** including loading/tokenization; its reduced workload is not a numerical substitute for the full run. The independent golden suite also passed all 15 checks.
