# Model-quality harness (SmolLM2-135M proxy)

Sets and checks the **quality gate** of `docs/src/content/Project/ARCH_METRIC.md`
(decision node N8): perplexity of SmolLM2-135M with an injectable analog-IMC error
model on every linear layer (Q, K, V, O, gate, up, down, LM head). Every number
this harness prints is **measured** (numpy emulation on the real GGUF weights and
real text). It is a proxy: SmolLM2-135M is not Llama-3-8B; small models carry
proportionally larger activation outliers and are usually *less* quantization
tolerant, so a gate set here is conservative for 8B.

```sh
P='python3.withPackages(p:[p.numpy p.scipy])'
nix-shell -p "$P" --run 'python3 test_quality.py'                       # self-check, ~2.5 min
nix-shell -p "$P" --run 'python3 quality.py --set w_fmt=int4 --set w_gran=group \
   --set a_fmt=int8 --set rows=128 --set w_slice_bits=4 --set x_slice_bits=4 --set adc_bits=8 --set noise=0.01'
nix-shell -p "$P" --run 'python3 quality.py ... --head fp'             # LM head kept exact (digital)
nix-shell -p "$P" --run 'python3 quality.py ... --only q,k,v,o'         # perturb only these kinds
nix-shell -p "$P" --run 'python3 quality.py --sweep'                    # the sweep below, ~80 min
```

```python
from quality import Err, evaluate
evaluate({"all": Err(w_fmt="int8", a_fmt="int8", rows=128, w_slice_bits=4,
                     x_slice_bits=4, adc_bits=8, noise=0.01),
          "head": None})          # None = exact; any kind q,k,v,o,gate,up,down,head
# -> {ppl, ppl_ref, delta_pct, delta_pct_se, top1_agree, n_tokens, seconds}
```

`delta_pct` = 100 (PPL/PPL_ref - 1); `delta_pct_se` is its standard error from the
per-token NLL differences (paired, so it is much tighter than the PPL's own spread);
`top1_agree` = fraction of positions whose argmax next token equals the unperturbed
model's. Runtime per configuration (32-thread host): digital quantization only ~10 s,
analog column path ~80 s, analog + noise ~110 s.

## Text and reference

- `data/wikitext2_test_head.txt`: the first 76 lines (32 KB, 7,441 tokens) of the
  **WikiText-2 test split** (Merity et al. 2016, `wikitext-2-raw-v1` test), unmodified:
  verified to be an exact prefix of the concatenated rows of Hugging Face
  `Salesforce/wikitext` `wikitext-2-raw-v1/test-00000-of-00001.parquet`.
- Eval: 4 windows x 512 tokens (512 = the ARCH_METRIC prompt length) -> **2,044 scored
  tokens**. A disjoint 5th window is the calibration set (static ADC full scale,
  per-tensor activation scale, SmoothQuant statistics); it never overlaps the eval text.
- Tokenizer: byte-level BPE from the GGUF vocab/merges (pre-type `smollm`: isolated
  digits then GPT-2 regex). **Verified** token-for-token identical (7,441/7,441) to the
  Hugging Face `tokenizers` BPE built from the same vocab/merges with the SmolLM2
  pre-tokenizer (`Digits(individual)` + `ByteLevel`).
- Reference model = the GGUF Q8_0 weights dequantized to fp32, fp32 activations,
  no BOS. PPL_ref = **23.53** (4 windows). The reference NLL/argmax and calibration
  activation maxima are cached in `out/ref_<hash>.npz` (gitignored).

## Error-model fields (`Err`, one per layer kind)

The emulated `y = x W^T`, in order: co-design transforms -> quantization -> analog
column -> digital recombination. Defaults are exact; `Err()` == reference.

| field | default | meaning |
|---|---|---|
| `w_fmt` | None | weight format: `int2`..`int8`, `fp8_e4m3`, `fp8_e5m2`, `fp6_e2m3`, `fp6_e3m2`, `fp4`, `log3`..`log8` (sign + exponent, values 0 and 2^-k), MX: `mxfp8`, `mxfp8_e5m2`, `mxfp6`, `mxfp4`, `mxint8`, `mxint4` (group 32, power-of-two shared scale, OCP MX) |
| `w_gran` | channel | scale granularity: `channel` (per output row), `group` (per `w_group` along K), `tensor` |
| `w_group` | 128 | group size |
| `w_pow2` | False | power-of-two scale (E8M0 style) |
| `w_clip` | 1.0 | scale = w_clip * absmax / fmt max (<1 clips outliers) |
| `a_fmt` | None | activation format (same list) |
| `a_gran` | token | `token` (dynamic per token), `tensor` (static, from the calibration window), `group` (dynamic per token-group of `a_group`) |
| `a_group`, `a_pow2` | 32, False | as for weights |
| `a_clip` | 1.0 | **input clipping**: activations saturate at a_clip * absmax |
| `rows` | None | rows summed per analog conversion (row tile); None = all of K. With `w_gran=group`, rows must equal `w_group` |
| `w_slice_bits` | None | magnitude bits per weight cell (bit-slicing; sign-magnitude, sign on every slice = differential cell); None = whole code in one cell |
| `x_slice_bits` | None | magnitude bits per input pulse: 1 = bit-serial, 4 = PWM nibble, None = full-precision DAC |
| `adc_bits` | None | ADC resolution per partial sum (per w-slice x x-slice x row tile); None = ideal |
| `adc_fs` | 4.0 | ADC full scale: float k -> FS = k * std(partial) (statistical clip, 27h6), frozen per (layer, slice pair) from the calibration window; `"max"` -> FS = rows * dmax_w * dmax_x (worst-case swing, pure LSB truncation, no clipping) |
| `noise` | 0 | additive Gaussian compute noise, sigma as a fraction of FS, fresh per conversion |
| `gain` | 0 | static per-column gain error, relative sigma (frozen per column per tile) |
| `offset` | 0 | static per-column offset, sigma as a fraction of FS |
| `hadamard` | False | randomized block-Hadamard rotation of K (x R, W R; exact in FP) |
| `smooth` | None | SmoothQuant alpha (x / s, W * s; exact in FP) |
| `seed` | 0 | seed of the static gain/offset draws |

Analog partial-sum model (per w-slice i, x-slice j, row tile r; LSB = FS / 2^(adc_bits-1)):
`P' = P (1 + gain) + offset FS + noise FS N(0,1)`, `P^ = clip(round(P'/LSB)) LSB`,
then `y = sum_ijr 2^(i bw + j bx) P^ * w_scale * x_scale` digitally.
Noise is drawn from a fixed 2^26-sample N(0,1) pool at random offsets (each
conversion still N(0,1); `ponytail:` note in `_noise` says how to make it strictly
independent). The calibration pass runs noise-free.

## Self-check (`test_quality.py`, measured)

Exact recombination of slices; `None` and `Err()` reproduce the reference bit-for-bit
(dPPL 0, top-1 100 %); the ideal analog path (rows=128, 4b cells, 4b input nibbles,
no ADC/noise) equals the digital quantized linear to 6e-7 relative error per layer;
FP Hadamard + smoothing is output-invariant (dPPL -3e-5 %); 5 % FS noise + 8b ADC and
INT2 weights both destroy the model. Note: the end-to-end PPL of the ideal analog path
differs from the digital path by ~1 se (fp32 summation order flips a few round-half
activation codes, which then propagate), which is why that equality is checked per layer.

## First sweep (measured, 2,044 tokens, PPL_ref = 23.53)

SWEEP_RESULTS
