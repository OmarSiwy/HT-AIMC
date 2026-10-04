# Application: transformer attention on the IMC core

How a transformer attention layer maps onto AnalogIOC: which parts run in the
analog in-memory-compute (IMC) tiles, which run on the digital rail, and why that
split is the natural one. Model numbers are SmolLM2-135M, the model the compiler
and golden tests use (`scripts/models/smollm2-135m-q8_0.gguf`).

## 1. Two kinds of matmul

An attention layer has two different kinds of matrix product:

| Product | Operands | Changes | Fits IMC? |
|---|---|---|---|
| Q, K, V, O projections | activation x **weight** | weights fixed after compile | **yes**: weight-stationary |
| qKᵀ scores, A·V | activation x **activation** | new K, V row every token | no: would reprogram the array every token |

The IMC tile is weight-stationary. `weight_tile` holds 4-bit differential
capacitor codes that the compiler programs once (`scripts/compiler/compile.py` ->
`programming/<matrix>.npz`). INT8 activations stream through as PWM nibbles, and
each column converts once per pass. That pays off only when the same weights are
reused for every token.

The projections are exactly that case. qKᵀ and A·V are not: their "weights" are
the K and V cache, which grows by one row per token and differs per sequence.
Holding them in analog memory means writing every new K/V row into the array,
plus the refresh and retention that dynamic analog storage needs. That cost is
paid per token and buys nothing back. So the split is:

```
x --INT8--> [IMC: W_q] --> q ┐
x --INT8--> [IMC: W_k] --> k ├─> digital rail: KV cache, scores = q·Kᵀ/sqrt(d),
x --INT8--> [IMC: W_v] --> v ┘                 softmax, A·V
                                                    │ INT8
                                                    v
                                              [IMC: W_o] --> o
```

This is what `golden.model.attention_forward` implements bit-true. The four
projections go through `proj()` (tile MVM, event-rate conversion, requant).
K and V are cached as the dequantized INT8 tile outputs. Scores, `softmax_ref` and
A·V are plain digital arithmetic. `scripts/compiler/test_compile.py` runs it on the
real model.

## 2. Where the MACs are

Per token, per layer, for SmolLM2-135M (d = 576, 9 query heads and 3 KV heads of
d_head = 64, FFN 1536, 30 layers):

| Work | MACs/token/layer | Where |
|---|---|---|
| Q + O projections | 2 x 576 x 576 = 663,552 | IMC |
| K + V projections (GQA) | 2 x 576 x 192 = 221,184 | IMC |
| FFN gate/up/down | 3 x 576 x 1536 = 2,654,208 | IMC |
| **Weight MACs total** | **3,538,944** | IMC |
| qKᵀ + A·V at context L | 2 x 9 x 64 x L = 1,152 L | digital |

The weight MACs don't depend on context length. The digital attention MACs grow
with L, but they stay below the weight MACs up to L ≈ 3,072 (3,538,944 / 1,152).
That covers most chat and decode workloads at this model size. Past that point,
attention arithmetic is the larger term, and it lands on whatever digital or
near-memory engine sits next to the KV cache. It is not an IMC problem.

## 3. Why the mapping is a good fit

- **The analog work is in the parts that never change.** All seven weight matrices
  per layer are programmed once and reused for every token. The compiler counts
  10,944 tile passes per token for blk.0 (`passes.json`, asserted in `test_compile.py`).
- **Precision is matched to where errors are tolerable.** Projections absorb the tile's
  measured residual: a ±8 LSB tile error keeps argmax 100% and cosine 0.9948
  ([ERROR_IMPACT.md](ERROR_IMPACT.md)). Softmax is the one place that needs a wide
  dynamic range: max subtraction, exponentials and a long-axis sum. It runs on the
  digital rail and adds no analog error.
- **No analog dynamic memory.** The KV cache is ordinary digital storage, so there is
  no retention, refresh or read-disturb budget to close in analog.
- **Activations already cross the boundary at INT8.** q, k and v leave the IMC as INT8
  codes, and the A·V result re-enters as INT8 for W_o. The analog/digital interface
  is the same one the FFN uses, so attention adds no new converter or port.
- **Other architectures map the same way.** GQA, RoPE (applied digitally to q and k)
  and MoE expert FFNs (selected expert weights resident in tiles, see
  [MOE_MAPPING.md](MOE_MAPPING.md)) only change which weight matrices are resident.
  The tile operation is the same.

## 4. Open questions

- Throughput balance: at what context length does the digital attention engine,
  rather than tile passes, set tokens/s? That depends on the rail's MAC rate, which
  isn't sized yet.
- KV cache size: 2 x 30 layers x 3 heads x 64 x L bytes at INT8 is 11.5 kB per token
  of context. Whether that lives on-die SRAM or off-chip sets the system memory
  budget.
