# The compiler structure

This document is the AnalogIOC design method written down. A compiler cannot schedule a single instruction until it understands the workload completely: which values are constants, which bytes get read twice, which buffers die young, which loops parallelize, which do not. That analysis already exists for LLM inference. If we extract it and take it seriously, the hardware design falls out of it. The compiler dictates what the machine should be, not the other way around.

The payoff sits at the end: the analysis forces a two-chip machine with no HBM in the attention path. Chip 1 is a main accelerator built around analog in-memory compute. Chip 2 is an in-memory attention engine that lives where the KV cache lives. Everything before Part IV is the evidence for that split.

The document has four parts:

- **Part I (sections 1 to 9):** the arithmetic as it actually runs, for attention and for state-space models.
- **List A:** every operation the hardware must support, ranked by how much it hurts.
- **List B:** the compiler analysis proper. When each value becomes known, what lives how long, what can be computed at the memory, what parallelizes.
- **Part IV:** what all of it forces for AnalogIOC.

---

# Part I: the workload

## 1. Attention, step by step

Before any hardware talk, the arithmetic goes on the table one step at a time: one transformer layer, one token at position `t`, hidden dim `d`, head dim `d_h`, `H` heads. Watch one thing as you read: which steps look at other tokens, and which look only at token `t`. That single distinction organizes the entire document.

### Step 1: RMSNorm

$$\hat{x}_t = \frac{x_t}{\sqrt{\tfrac{1}{d}\sum_{i=1}^{d} x_{t,i}^2 + \epsilon}} \odot \gamma$$

The sum runs over the *feature* axis, not the sequence axis. Token `t` needs nothing from token `t-1`.

### Step 2: QKV projection

$$q_t = W_Q^\top \hat{x}_t, \quad k_t = W_K^\top \hat{x}_t, \quad v_t = W_V^\top \hat{x}_t$$

Still only `x_t`. This is where essentially all the parameters live.

### Step 3: RoPE

For coordinate pair `(2i, 2i+1)` with $\theta_i = 10000^{-2i/d_h}$:

$$\begin{pmatrix} q'_{t,2i} \\ q'_{t,2i+1}\end{pmatrix} = \begin{pmatrix} \cos t\theta_i & -\sin t\theta_i \\ \sin t\theta_i & \cos t\theta_i \end{pmatrix}\begin{pmatrix} q_{t,2i} \\ q_{t,2i+1}\end{pmatrix}$$

This depends on the *position* `t`, but not on any other token's *values*. Positional is not the same as token-dependent, and the distinction matters later.

### Step 4: KV cache write

`k'_t, v_t` are appended to the cache. This append is the interface between the two halves of the layer.

### Step 5: Scores

$$s_{tj} = \frac{q'^\top_t k'_j}{\sqrt{d_h}}, \quad j = 0 \ldots t$$

Here is the break. Token `t` now reads values produced by tokens `0 … t-1`. This is the first cross-token communication in the entire layer.

### Step 6: Causal mask

$s_{tj} \leftarrow -\infty$ for $j > t$.

### Step 7: Softmax

$$m_t = \max_j s_{tj}, \qquad a_{tj} = \frac{e^{s_{tj}-m_t}}{\sum_{j'} e^{s_{tj'}-m_t}}$$

A reduction along the sequence axis, of a length not known at compile time.

### Step 8: Value aggregation

$$o_t^{(h)} = \sum_{j \le t} a_{tj}\, v_j^{(h)}$$

### Step 9: Output projection

$$y_t = W_O^\top \left[o_t^{(1)} \| \cdots \| o_t^{(H)}\right]$$

### Steps 10 and 11: Residual and MLP

$$z_t = x_t + y_t, \qquad x_t^{\text{out}} = z_t + W_{down}^\top\big(\text{SiLU}(W_{gate}^\top \hat z_t) \odot W_{up}^\top \hat z_t\big)$$

Back to reading only token `t`. The layer opened token-local, crossed tokens exactly once in the middle, and closed token-local.

---

## 2. The token-independent / token-dependent split

Sort the eleven steps by the question from section 1 and you get three classes:

| Steps | Class | Character |
|---|---|---|
| 1, 2, 3, 9, 10, 11 | **Token-independent** | `activation × weight`, reductions along the feature axis |
| 4 | **Interface** | KV cache: producer/consumer channel between the domains |
| 5, 6, 7, 8 | **Token-dependent** | `activation × activation`, reductions along the sequence axis |

```
        ┌─────────────────────────────┐
        │  Norm, QKV proj, RoPE       │  token-independent
        │  reads only token t         │
        └──────────────┬──────────────┘
                       │
  tokens 0..t-1 ──►┌───▼──────────────┐
                   │  KV cache        │  interface
                   │  write 1, read L │
                   └───┬──────────────┘
                       │
        ┌──────────────▼──────────────┐
        │  Scores, softmax, weighted  │  token-dependent
        │  sum. Reads all past tokens │
        └──────────────┬──────────────┘
                       │
        ┌──────────────▼──────────────┐
        │  Out proj, residual, MLP    │  token-independent
        │  reads only token t         │
        └─────────────────────────────┘
```

The clean statement:

> Attention is the only place in a transformer where one token's data meets another token's data, and it is also the only place with no learned parameters.

Those two facts coincide, and the coincidence is what makes a hardware split viable. The parameter-heavy work never crosses tokens; the token-crossing work carries no parameters. You can put them on different silicon without tearing either one apart.

---

## 3. Why the split forces different hardware

### Arithmetic intensity under batching

**Token-independent path.** Weights are shared across the whole batch. Load `W_Q` once and use it for all `B` sequences, so intensity scales as `O(B)`. At large batch you become compute-bound, and a big MAC array is exactly the right tool.

**Token-dependent path.** Each sequence has its own private KV cache. For one decode step at context length `L`:

$$\text{FLOPs} \approx 4 L d_h H, \qquad \text{bytes} \approx 2 L d_h H_{kv}$$

The ratio is a small constant, independent of `B`. **Batching does not help.** This half is memory-bound and stays memory-bound forever. More multipliers do not fix it; only a shorter path to the bytes does.

### The consequence

One region wants a huge MAC array and modest bandwidth. The other wants modest MACs and the fattest possible path to its memory. Building one unit for both means either the array starves during attention or the bandwidth sits idle during the MLP. This is the first load-bearing argument for AnalogIOC's two chips, and Part IV picks it up.

### Other asymmetries

| | Token-independent | Token-dependent |
|---|---|---|
| Operands | activation × weight | activation × activation |
| Shapes | fixed at compile time | `L` varies at runtime, differs per sequence |
| Memory | weights, shared across batch | KV cache, private per sequence |
| Special functions | one activation fn | `max`, `exp`, `reciprocal` |
| Control complexity | none | all of it |

---

## 4. Prefill vs decode: same math, different machine

The same block of math runs in two regimes depending on how many tokens arrive at once.

| | Prefill (`T` tokens) | Decode (1 token) |
|---|---|---|
| `QK^T` shape | `(T × d_h)(d_h × T)`, a real GEMM | `(1 × d_h)(d_h × L)`, a GEMV |
| FLOPs | `O(T² d_h)` | `O(L d_h)` |
| Bytes | `O(T d_h)` | `O(L d_h)` |
| Regime | **compute-bound** | **bandwidth-bound** |
| Wants | matrix engine | memory streaming |

Two workloads, two regimes, one block of math. This is why prefill and decode are often scheduled onto separate machines even on GPUs.

---

## 5. The dependency graph

A compiler's first real question: what must wait for what? Everything else (parallelism, pipelining, offload) is downstream of this table.

| Scope | Structure |
|---|---|
| Within one token, one layer | Strictly sequential, 1 → 11. No reordering. |
| Across tokens, **prefill** | Steps 1 to 4 embarrassingly parallel over all `T`. Steps 5 to 8 also parallel over all `T` query rows. Causality restricts *which* keys row `t` reads, but every key already exists. **Causality constrains the data, not the schedule.** |
| Across tokens, **decode** | Fully serial. Token `t+1`'s embedding is the argmax of token `t`'s output after all `N` layers. Irreducible. |
| Across heads | Steps 5 to 8 fully independent. |
| Across layers | Sequential per token, but pipelineable across microbatches. |
| **Cross-domain edge** | Step 4 of token `j` must complete before step 5 of any token `t > j`. The only edge crossing the boundary. |

That last row deserves a pause. In the entire layer, exactly one dependency edge crosses the token-independent / token-dependent boundary: the KV append. A boundary with one edge through it is exactly where you cut a design into two chips.

## 6. Online softmax: the enabling trick

Naively, step 7 needs `m_t = max_j s_tj` before exponentiating anything, which means materializing all `L` scores first. At `L = 128,000` that is a lot of SRAM per query per head.

The fix: process the KV cache in blocks `i`, keeping a running max `m`, a running denominator `ℓ`, and an output accumulator `o`:

$$m^{(i)} = \max\!\left(m^{(i-1)},\, \tilde m_i\right)$$
$$\ell^{(i)} = e^{m^{(i-1)}-m^{(i)}}\,\ell^{(i-1)} + e^{\tilde m_i - m^{(i)}}\,\tilde\ell_i$$
$$o^{(i)} = e^{m^{(i-1)}-m^{(i)}}\,o^{(i-1)} + e^{\tilde m_i - m^{(i)}}\,\tilde o_i$$

with $o_t = o^{(\text{last})}/\ell^{(\text{last})}$. Each rescaling factor is $e^{\text{old max} - \text{new max}} \le 1$, so it is numerically safe. When a new block raises the max, you retroactively shrink everything accumulated so far by one multiply. No pass over old data.

**Hardware consequence:** the attention unit's state is `O(d_h)` regardless of context length. Three small registers per head. The KV cache streams past a fixed-size accumulator.

**Compiler consequence:** the combine step is an *associative monoid*:

$$(m_1,\ell_1,o_1)\circ(m_2,\ell_2,o_2) = \big(m,\ \ell_1 e^{m_1-m} + \ell_2 e^{m_2-m},\ o_1 e^{m_1-m} + o_2 e^{m_2-m}\big),\quad m=\max(m_1,m_2)$$

Associativity means partial results can be combined in any grouping. That single algebraic property licenses both tree-parallel reduction and near-memory offload (B3). It is the mathematical permission slip for Chip 2.

## 7. Operation inventory for attention

Sorted by silicon cost.

| Operation | Where | Notes |
|---|---|---|
| Multiply-accumulate | steps 2, 5, 8, 9, 11 | >99% of FLOPs. Two flavours: weight-stationary and data-on-data. |
| Add / subtract | residuals, max subtraction, accumulator updates | |
| Elementwise multiply | `γ` scaling, SwiGLU gate, softmax rescale | |
| Max | softmax stability | comparator tree |
| `exp` | softmax | one per score: `L` per query per head |
| Reciprocal | softmax denominator | once per row with online softmax |
| Reciprocal square root | RMSNorm | see below |
| SiLU / GELU | MLP | decomposes into exp + reciprocal + multiply |
| `sin` / `cos` | RoPE | never computed, always a table lookup |
| Round / clamp / scale | quantization | plus amax reductions for dynamic scaling |

**Functional units required:** a big MAC array, a small vector ALU (add, mul, max, select), and a special function unit doing `exp`, `reciprocal`, `rsqrt`. That is the whole list.

Attention is arithmetically boring. The difficulty is dataflow, not operator variety. Hold onto that: it means the hard design work is in List B, not List A.

### About the two square roots

Neither is a runtime square root.

- **`1/√d_h` in the score** is a *compile-time constant*. Fold it into `W_Q` before loading weights, or into the exp's scale factor. Costs zero.
- **RMSNorm's** is a genuine runtime `rsqrt`, not `sqrt` followed by divide. Hardware computes `x^(-1/2)` directly: extract the float's exponent field, negate and halve it, refine the mantissa. Same reason the Quake trick was rsqrt and not sqrt.

## 8. Special functions and lookup tables

Every special function in the model follows one pattern: **table lookup for a seed, then polynomial or Newton-Raphson refinement.** Once you see the pattern, the "transcendental problem" shrinks to a few small ROMs.

### exp2, not exp

Nobody builds `e^x`. Floats are base-2, so rewrite $e^x = 2^{x \log_2 e}$ and fold $\log_2 e$ into the same constant that already carries `1/√d_h`. Then split `x = i + f`:

$$2^{i+f} = 2^i \cdot 2^f$$

`2^i` is an add into the exponent field: a shift, no multiply. `2^f` for `f ∈ [0,1)` comes from a table indexed by the top 5 to 8 bits of `f`, plus a linear or quadratic correction. **Table size: 32 to 256 entries.**

### rsqrt

Exponent handled by arithmetic (`e → -⌊e/2⌋`), mantissa seeded from a 64 to 256 entry table, then one or two Newton steps:

$$y \leftarrow y\left(1.5 - 0.5\,x\,y^2\right)$$

Each step doubles the correct bits.

### Reciprocal

Same shape, Newton iteration $y \leftarrow y(2 - xy)$.

### The low-precision shortcut

If softmax runs in fp8, there are only **256 possible input bit patterns**. So `exp` becomes a *complete* 256-entry lookup with zero arithmetic and zero error. Same for sigmoid, same for SiLU.

This is an underrated reason quantization helps beyond the bandwidth win: special functions stop being computation and become addressing.

### The one large table: RoPE

`sin(t·θ_i)` and `cos(t·θ_i)` precomputed for all positions and dimension pairs. Shape `[max_pos, d_h/2, 2]`. At 128k context and `d_h = 128` in fp16 that is ~32 MB. Genuinely large, and the reason implementations often regenerate it in tiles or keep only the active window resident.

### Table summary

| Table | Where | Size | Real memory? |
|---|---|---|---|
| exp2 mantissa seed | all | 32-256 entries | no, ROM |
| rsqrt seed | all (RMSNorm) | 64-256 entries | no, ROM |
| reciprocal seed | softmax, SiLU | 64-256 entries | no, ROM |
| softplus midrange | SSM | ~128 entries | no, ROM |
| full fp8 exp / sigmoid / SiLU | any quantized | 256 entries, exact | no, ROM |
| RoPE sin/cos | attention | up to tens of MB | **yes** |
| token embedding | all | GBs | yes, outside the layer |

Total transcendental ROM: on the order of a kilobyte. Negligible against 144 GB of HBM.

### AnalogIOC note: these tables are analog candidates

A seed table plus a low-order polynomial correction is a small, fixed, read-only function of a few input bits. Nothing about it demands digital logic. These lookups can plausibly be done in analog, and that is AnalogIOC's working assumption: aside from PCIe and the chip-to-chip interconnect, essentially every block in this document is a candidate for analog implementation. The research on analog function tables specifically has not been done yet; treat this as a stated direction, not a verified result. Part IV returns to it.

---

## 9. State-space models

Frontier models increasingly hybridize attention with SSM or linear-attention layers, so the machine has to run these too. The arithmetic barely changes. The *structure* changes a lot, and the differences are exactly the ones a compiler cares about.

### Mamba 1 (S6)

Per channel `c ∈ [1..D]`, state dimension `N` (typically 16):

$$\Delta_t = \text{softplus}(W_\Delta x_t + b), \qquad B_t = W_B x_t, \qquad C_t = W_C x_t$$

`A ∈ R^(D×N)` is diagonal and learned, stored as $A = -\exp(A_{\log})$ so it is guaranteed negative and the system is stable. Discretize:

$$\bar{A}_t = \exp(\Delta_t A), \qquad \bar{B}_t = \Delta_t \otimes B_t$$
$$h_t = \bar{A}_t \odot h_{t-1} + \bar{B}_t x_t, \qquad y_t = C_t^\top h_t + D \odot x_t$$

**New operations relative to attention:**

- **`softplus`**, `log(1 + e^x)`. Needs exp *and* log, a second transcendental family attention never touches. Implemented piecewise: `≈ x` for `x ≳ 15`, `≈ e^x` for `x ≲ -15`, table only across the middle.
- **`exp` at a completely different volume.** `Ā_t = exp(Δ_t A)` is elementwise over a `D × N` tensor, *every token*. With `D = 8192` and `N = 16` that is 131k exponentials per token per layer. Attention's exp count scales with context length; Mamba 1's scales with model width and is paid on every token regardless of sequence length. A real hardware complaint about Mamba 1.
- **Parallel associative scan.** `h_t = a_t h_{t-1} + b_t` is first-order linear, and that class is associative under

  $$(a_1, b_1) \circ (a_2, b_2) = (a_1 a_2,\; a_2 b_1 + b_2)$$

  A Blelloch scan computes all `h_t` with `O(L)` work and `O(log L)` span. Arithmetically trivial: one multiply and one FMA. The cost is *structural*. It needs a tree or butterfly network, a shape no attention unit has. **This is the single biggest reason a transformer ASIC cannot run Mamba.**
- **Depthwise causal conv1d**, kernel width 4. Small MACs, sliding-window access.

Note `Δ_t > 0` and `A < 0`, so `Ā_t ∈ (0,1)` always: a decay factor. Bounded input range means a smaller table.

### Mamba 2 (SSD)

The change that matters: `A` becomes a **scalar per head** rather than diagonal per channel. So `a_t = exp(Δ_t A_h)` is one number per head per timestep.

That restriction collapses the recurrence into a matrix product:

$$Y = \left(L \odot CB^\top\right)X, \qquad L_{ij} = \begin{cases}\prod_{k=j+1}^{i} a_k & i \ge j \\ 0 & i < j\end{cases}$$

which is masked attention with a decay mask instead of a causal mask. Computed in log space: cumulative sum of `Δ`, then differences, then one exp:

$$L_{ij} = \exp\!\left(A_h \sum_{k=j+1}^{i}\Delta_k\right)$$

**What changes:**

- **Cumulative sum replaces the general scan.** Additions only. Far cheaper and a much more common hardware primitive.
- **exp count collapses** from `O(D×N)` per token to `O(H)` per token.
- **GEMM comes back.** `CB^T` and the multiply by `X` are real matrix multiplies. This is the entire point of Mamba 2: it was designed so the token-dependent part runs on tensor cores instead of a bespoke scan kernel.

In practice it is chunked. Within a chunk, the quadratic masked-GEMM form; between chunks, the linear recurrent form. So Mamba 2 uses **both** modes.

### Side by side

| | Attention | Mamba 1 | Mamba 2 |
|---|---|---|---|
| Cross-token mechanism | softmax-weighted sum over history | first-order linear scan | segsum + masked GEMM |
| Per-sequence state | KV cache, grows with `L` | fixed, `D × N` | fixed, `H × P × N` |
| Dominant special fn | exp, `O(L)` per query | exp, `O(DN)` per token | exp, `O(H)` per token |
| Extra transcendental | none | softplus (needs log) | softplus |
| Communication pattern | reduction over `L` | scan tree / butterfly | prefix sum + GEMM |
| Reduction length known at compile time | no | yes (`N`) | yes (chunk size) |
| Runs on a MAC array | yes | poorly | yes |
| **State mutability** | **immutable (append-only)** | **mutable** | **mutable** |

That last row is the deepest difference in this document, deeper than any FLOP count. B2 explains why.

---

# List A: full hardware operation requirements

What an accelerator must support to run a modern frontier LLM. This list is deliberately exhaustive and deliberately flat; the ranking of what actually hurts comes at the end (A9).

## A1. Matrix engine

| Operation | Where | Note |
|---|---|---|
| Dense GEMM, weight-stationary | projections, MLP | 90%+ of FLOPs |
| GEMV | decode, batch 1 | same unit, terrible utilization |
| **Grouped GEMM, per-group shapes** | MoE expert FFNs | group sizes known only after routing |
| Data-on-data GEMM | `QK^T`, `AV` | no weights, both operands are activations |
| Masked GEMM | causal, decay, tree/spec-decode masks | mask applied pre-softmax |
| Chained low-rank GEMM | MLA up/down projections | `W_a W_b x`; associativity matters for the absorb trick |
| Outer-product accumulate | linear attention / SSM state | `S += k vᵀ` |
| Mixed-precision MAC | everywhere | fp4/fp8/int8 in, fp32 accumulate |

Grouped GEMM with runtime-determined group sizes is the one that hurts. A fixed dataflow array wants shapes known at compile time; MoE gives shapes known only after the router fires.

## A2. Vector ALU

`add` · `sub` · `mul` · `FMA` · `max` · `min` · `compare-and-select` (predication) · `abs` · `sign` · `clamp`/`saturate` · `ReLU` · `shift`/`mask` (exponent manipulation, fp4 packing) · integer add (address generation) · type conversion across fp32/bf16/fp16/fp8/fp4/int8 · `round-to-nearest-even` · `stochastic round`

None individually interesting. All mandatory.

## A3. Special function unit

| Function | Consumed by |
|---|---|
| `exp2` | softmax, SSM decay, softplus |
| `log2` | softplus, logsumexp, log-space cumulative products |
| `reciprocal` | softmax denominator, mean, sigmoid |
| `rsqrt` | RMSNorm, LayerNorm |
| `sigmoid` | SwiGLU variants, MoE router, gated deltanet gates |
| `tanh` | some gating, GELU approximation, logit soft-capping |
| `softplus` | SSM `Δ` discretization |
| `erf` | exact GELU (usually approximated away) |
| `sin`/`cos` | RoPE (table, not computed) |

**Everything on this list reduces to `exp2`, `log2`, `reciprocal`, `rsqrt` plus multiplies.** Four true transcendental primitives is the whole requirement. Sigmoid is exp plus reciprocal; tanh is sigmoid rescaled; softplus is exp plus log; GELU is tanh or erf approximated. Build four, get nine.

## A4. Reductions and scans

This is where architectures actually differ, and where naive accelerator designs fail.

| Pattern | Axis | Used by |
|---|---|---|
| Sum, sum-of-squares | feature | RMSNorm |
| Max | sequence | softmax |
| Streaming max + sum + rescale | sequence, variable length | FlashAttention |
| Absmax | tile/block | quantization scale factors |
| Dot product | feature | scores, router logits |
| **Prefix sum (cumsum)** | sequence | SSM segsum, MoE expert offsets |
| **Associative scan** `(a₁,b₁)∘(a₂,b₂) = (a₁a₂, a₂b₁+b₂)` | sequence | Mamba, gated deltanet, KDA |
| **Top-k** | expert / block axis | MoE routing, sparse-attention block selection, top-k sampling |
| Argmax | vocab | greedy decode |
| Sort / partial sort | vocab (~128k-256k) | top-p / nucleus sampling |
| Histogram / bincount | expert axis | load balancing, capacity tracking |

Top-k is the sleeper. Sparse-attention indexers select top-512 blocks per query token per head, inside the attention inner loop. That is a real sorting-network problem sitting on the critical path.

## A5. Data movement

- Strided load/store, transpose, broadcast, concat/split
- **Gather** by index vector: MoE dispatch, embedding lookup, paged KV block table, sparse-attention block fetch
- **Scatter with accumulate**: MoE combine back to token order
- Sub-byte pack/unpack, for fp4 storage
- Masked/predicated load
- Ragged / variable-length tensor addressing
- Indirect addressing through a page table
- Async DMA with double buffering

## A6. Control

Variable trip-count loops (context length). Dynamic shapes (expert group sizes, selected block counts). Predication. **Per-sequence divergence within a batch**: continuous batching means sequence 3 is in prefill at length 40k while sequence 7 is in decode at length 200, in the same step, on the same chip.

## A7. Collectives

| Collective | Forced by |
|---|---|
| All-reduce | tensor parallelism |
| **All-to-all** | expert parallelism |
| All-gather / reduce-scatter | sharded weights, sequence parallelism |
| Point-to-point | pipeline parallelism |

On a trillion-parameter MoE, all-to-all is frequently the actual bottleneck, not any arithmetic op in this document.

## A8. RNG

Uniform random for sampling. Also needed for stochastic rounding in low-precision accumulation.

## A9. Ranked by how badly each breaks a fixed-function design

1. **Runtime-dependent shapes**: MoE group sizes, selected block counts. Breaks any statically-scheduled dataflow.
2. **Gather/scatter at high rate**: MoE dispatch/combine, paged KV. Wants a real memory system, not a streaming feeder.
3. **Large-k top-k in the inner loop**: new as of the sparse-attention generation, and not cheap.
4. **All-to-all**: the trillion-parameter tax; mostly an interconnect problem.
5. **Associative scan**: a tree/butterfly network with no counterpart in an attention datapath.

The arithmetic surface is ~25 scalar operations and 4 transcendentals, and it has barely changed since 2017. Items 1, 3, and 5 above did not exist in a 2023 transformer. The ops are stable; the *structures* are where the churn is.

---

## Feature → operation mapping

A quick lookup: pick any architectural feature a model card brags about, read off what it forces into the ISA.

| Architectural feature | What it forces into the ISA |
|---|---|
| MoE | top-k, sigmoid/softmax router, additive expert bias (aux-loss-free balancing), gather/scatter, grouped GEMM, histogram, all-to-all |
| MLA | chained low-rank GEMM, extra RMSNorms, decoupled RoPE path |
| GQA/MQA | nothing new; changes the intensity ratio only |
| Sparse attention (DSA, CSA) | low-precision scoring path, large-k top-k, gather of selected blocks, ragged reduction |
| Softmax-gated pooling compression | segment-wise softmax over a strided window, learned positional bias add |
| RoPE / YaRN | large sin/cos table, per-dimension frequency scaling |
| Long context (1M) | paged KV, indirect addressing, streaming softmax with `O(d_h)` state |
| Multi-token prediction | extra small heads, tree-shaped attention masks |
| Speculative decoding | arbitrary (non-causal) mask matrices, batched verification compares |
| FP4/FP8 quantization | block-wise scale factors, absmax reduction, sub-byte pack/unpack, per-tile dequant |
| Linear attention / SSM hybrid | associative scan, cumsum, softplus, outer-product state update |
| Sampling | sort or partial sort, RNG, temperature divide, repetition-penalty scatter |

---

## Precision requirements

| Stage | Typical today |
|---|---|
| Weight storage | fp4 / fp8 with per-block scales |
| MAC inputs | fp4 / fp8 |
| MAC accumulate | fp32, or fp22-ish with periodic fp32 promotion |
| Softmax internals | fp32 for max and sum; exp may be fp8-tabled |
| Norm statistics | **fp32 mandatory** |
| KV cache | fp8, sometimes fp4 |
| Router logits | **fp32**, because top-k ties on low precision cause routing thrash |
| Accumulator across experts | fp32 |
| SSM state | **fp32**, because it persists across all timesteps and error compounds |

**The rule:** anything that accumulates over a long axis or feeds a discrete decision needs fp32. Everything else can be tiny. For an analog design this rule is the precision floor: analog compute handles the "everything else," and the fp32 accumulate/decide points mark where a digital island is non-negotiable.

---

# List B: the compiler analysis

List A told us *what* the operations are. It was short and honestly a little boring. List B asks the questions a compiler asks about those same operations, and this is where the machine actually gets designed. Three separable passes: binding-time analysis, liveness analysis, offload legality. Plus the parallelism table that falls out of them.

Two corrections before starting, because sloppy vocabulary here produces wrong hardware:

> **First.** "Token-independent vs token-dependent" conflates two things: *when a value becomes known* (staging) and *whether a value's shape is known* (dynamic shapes). Value-dynamism is cheap. A static schedule with different numbers flowing through it works fine. **Shape-dynamism forces dynamic scheduling.** MoE routing and top-k block selection are shape-dynamic, and that is why a purely static compiler fails on modern models.

> **Second.** "Feedthrough from previous steps" is *temporal reuse*: the same bytes read many times, which wants caching and broadcast. "In-place" is *storage reuse*: a dead buffer recycled, which wants last-use analysis. They are orthogonal and they fight. Writing in-place destroys temporal reuse for anything still live. Keep them as separate lattices.

---

## B1. Binding-time lattice

The question this pass asks: for every value in the model, *when does it become known?* The earlier a value binds, the more the compiler (or the silicon) can do with it for free. Six stages, each strictly later than the last. A value's stage is the max over its inputs' stages.

| Stage | Bound at | Contents | What the compiler may do |
|---|---|---|---|
| **S0** | build | `d`, `H`, `d_h`, `d_ff`, `E`, `k`, `1/√d_h`, `log₂e`, LUT contents, mask patterns | Constant-fold. Fold `1/√d_h · log₂e` into one scale. Unroll. Size all buffers. |
| **S1** | weight load | `W_{Q,K,V,O}`, MLP/expert weights, `γ`, quant scales, `A = -exp(A_log)`, RoPE tables, expert bias | Pre-transform once, amortized over the model's whole life: transpose, pre-quantize, absorb `γ` into `W`, absorb scale into `W_Q`, precompute `Ā` tables, fold low-rank chains (`W_aW_b` or the MLA absorb, whichever is cheaper). Replicate freely: read-only forever. |
| **S2** | request | context length bound, sampling params, LoRA deltas, prefix-cache hit | Select kernel variants, pick tiling, allocate KV pages, plan collectives. |
| **S3** | position | `t` itself | RoPE angles become table indices. Mask rows become known. Purely positional, not value-dependent, so still fully static per token. |
| **S4** | token value | `x_t`, `q_t`, `k_t`, `v_t`, norms, MLP activations | Values dynamic, **shapes static**. Static schedule still valid. |
| **S5a** | history | scores, softmax, `o_t`, SSM state | Reads S4 outputs of `j < t`. Shapes static given `L`. |
| **S5b** | **control** | router top-k indices, expert group sizes, selected KV block IDs, sampled token | **Shapes dynamic.** Static schedule invalid. Requires dispatch, ragged buffers, or capacity-padding. |

### The key result

**S0 through S5a are all statically schedulable.** S4 and S5a have dynamic *values* but static *shapes*, so a fixed dataflow can be baked into silicon. **S5b breaks it.**

Concretely, S5b is: MoE routing, sparse-attention block selection, speculative-decode accept counts, continuous-batching sequence lengths. Four things. That's the entire list.

> **Design consequence:** if you are building a machine, S0 through S5a can be hardwired. S5b needs the escape hatch. That is the smallest programmable surface that covers modern models, a much narrower requirement than "make the chip general-purpose." For AnalogIOC this is the license to make Chip 1 mostly fixed-function analog with a small digital control region, instead of a sea of programmable cores.

### A naming suggestion

S4 is not "token-independent." It is ***position-local***: the algebraic fact is that it is a `map` over the token axis. S5a is a `reduce` or `scan` over the token axis. That framing hands you the parallelization strategy for free (B4), because map parallelizes trivially and reduce/scan parallelize exactly as far as their combine operator is associative.

---

## B2. Liveness, storage reuse, and effects

Two orthogonal classifications: what an op *does* to memory (effect), and how long its output *lives* (lifetime).

### Effect class

| Effect | Ops | Aliasing consequence |
|---|---|---|
| **Pure** | GEMM, norm, activation, softmax, scores | No hazards. Reorder freely. |
| **Read-only-persistent** | weight read, LUT read, RoPE table read | Replicate to every unit. No coherence protocol. Never invalidated. |
| **Append-only** | KV cache write | **Immutable after write.** |
| **Destructive update** | SSM state, linear-attention state, residual `+=` | Read-modify-write. Exclusive ownership. Serializes on the write. |
| **Indexed scatter-accumulate** | MoE combine | Needs disjointness proof or atomics. |

### Why append-only is the most important property in the model

- Reads are pure → no read-read or read-write hazards among consumers → **attention rows parallelize with zero synchronization.**
- No invalidation → arbitrarily cacheable and replicable.
- **Prefix sharing is free.** Two sequences with a common prefix share the same physical pages, no copy-on-write, because nothing ever mutates.
- Only one hazard exists in the entire structure: `write(j) → read(t>j)`. In prefill you can order all writes before all reads, which erases it.

SSM state has **none** of these properties. Destructively updated → no prefix sharing without explicit checkpointing, and the write serializes. Two "token-dependent" mechanisms, completely different aliasing behavior. This is why the side-by-side table in section 9 called state mutability the deepest difference: it changes what the memory system must be, not just how fast it must be.

### Lifetime tier

| Tier | Lives | Examples | Placement |
|---|---|---|---|
| Model | forever | weights, LUTs, RoPE tables | HBM or on-chip ROM, replicated |
| Sequence | request | KV pages, SSM state | paged, per-sequence |
| Layer | one layer | residual stream `x_t` | on-chip, must survive attn + MLP |
| Block | one sub-block | `q,k,v`, scores, `o_t`, MLP intermediate | on-chip, dead at block exit |
| Tile | one iteration | online-softmax `(m, ℓ, o)`, MAC accumulators | registers, never spill |

### In-place legality rule

Op `f: A → B` may write into `A`'s buffer **iff all three hold**:

1. `shape(B) == shape(A)` and dtype widths match
2. each output element reads only the corresponding input element (or a fixed small local group: a pair, a lane)
3. this op is `A`'s **last use** in the dependency graph

| Op | In-place? | Why |
|---|---|---|
| RMSNorm scale | yes | elementwise, condition 2 holds |
| RoPE | yes | pairwise orthogonal rotation, no aliasing beyond the pair |
| Softmax | yes | rewrites the score row it read |
| Activation (SiLU/GELU) | yes | elementwise |
| Quantize/dequantize | no if width changes | violates condition 1 |
| Residual add | yes, into the residual buffer | that is the idiom |
| GEMM | **never** | condition 2 fails: every output reads all of a row |
| KV write | yes, at the tail | append |
| SSM state update | yes | that is the definition |
| Attention accumulator | yes, in registers | tile-local |

> **The interesting failure is condition 3, not 1 or 2.** RMSNorm's input is the residual stream, which is still live for the residual add. So the norm **cannot** be in-place despite being elementwise. That single case is where most naive in-place passes go wrong. Reordering does not help; the value is genuinely needed twice.

### Temporal reuse (separate metric: reads per byte loaded)

| Value | Reuse factor | Implication |
|---|---|---|
| Weights (prefill or large batch) | `B × T` | weight-stationary, huge win, compute-bound |
| Weights (decode, batch 1) | **1** | no reuse at all: bandwidth-bound, worst case |
| KV cache | 1 per decode step | zero reuse within a step, full reuse across steps |
| `q_t` inside attention | `L` | broadcast operand, keep in registers |
| RoPE table entry | `B` | small enough to keep resident |
| Residual stream | 2 (norm + add) | forces the layer-lifetime tier |

Decode at batch 1 has reuse factor 1 on **both** weights and KV. Everything is streamed once and discarded. That is the whole reason batching exists. It is also why MoE decode is so hard: expert weights are loaded per token with reuse ≈ 1 even at moderate batch, because different tokens pick different experts.

---

## B3. Near-memory offload legality

This pass is the theoretical core of Chip 2. It answers: which operations are *allowed* to move out of the main accelerator and into the memory that holds their data?

**The test:** an op is offloadable iff it has the **broadcast-stream-reduce** shape. One small operand broadcast in, one large resident operand streamed locally, one small result returned.

Profitable iff:

$$\frac{\text{bytes(streamed operand)}}{\text{bytes(broadcast)} + \text{bytes(result)}} \gg 1$$

In words: the big operand never crosses a chip boundary, only the small ones do, and the win is the ratio between them.

### Attention's inner loop is the textbook case

| Op | Broadcast in | Streamed locally | Returned | Traffic saved |
|---|---|---|---|---|
| `s_j = q·k_j` | `q`: `d_h` | `K`: `L·d_h` | `s`: `L` | ≈ `d_h` (128×) |
| online softmax | `(m,ℓ)`: 2 | `s`: `L` | `(m,ℓ)`: 2 | ≈ `L/2` |
| `o = Σ a_j v_j` | `a`: `L` | `V`: `L·d_h` | `o`: `d_h` | ≈ `d_h` |
| **fused all three** | `q`: `d_h` | `K,V`: `2L·d_h` | `o,m,ℓ`: `d_h+2` | **≈ `L`** |

Fused, you cross the boundary with `2·d_h` values instead of `2·L·d_h`. At `L = 128k` that is roughly a **128,000×** reduction in memory-interface traffic. This single table is why Chip 2 exists.

### Why the fusion is legal

The online-softmax monoid (section 6) is **associative**. Each memory bank reduces its own local slice independently; a tiny tree combines the per-bank partials. No global max is needed before starting.

> **Associativity is the offload-legality proof.** Without it, softmax would need a full pass over all scores before the second pass could begin, and near-memory compute would be pointless.

### What each near-memory unit needs

MAC, `max`, `exp2`, and the rescale multiply. Plus `reciprocal` once at the end, which can live host-side. A few hundred gates per bank in a digital sketch, and every one of those primitives is on the analog-candidate list from section 8.

`rsqrt` and `log2` are **not** needed here. They belong to norm and softplus, which are position-local and stay on the compute side. The near-memory op set is even smaller than the already-small SFU list.

### Offload verdict by op

| Op | Near-memory? | Reason |
|---|---|---|
| `QK^T`, softmax, `AV` (fused) | **yes, ideal** | canonical broadcast-stream-reduce |
| KV write | yes | pure store at the tail |
| KV dequant | **yes, essential** | dequantize after the boundary and you have thrown away the compression |
| Paged KV table walk | yes | indirection resolved where the pages live |
| Sparse-attention block scoring | yes | scores all blocks locally, returns only top-k indices: massive reduction |
| Gather of selected KV blocks | yes | selection happens at the data |
| **MoE expert FFN at low batch** | **yes, same shape** | small activation broadcast in, huge expert weights streamed, small result out. Structurally identical to attention decode. |
| SSM scan | partially | local scan offloadable; cross-chunk carry must return |
| QKV / output projection | no | weights live elsewhere; wrong operand geometry |
| Dense MLP at high batch | no | compute-bound, wants the big array |
| Norm, RoPE, activations | no | position-local, cheap, belongs with the residual stream |
| Router, sampling | no | small, control-flow-adjacent |

> **The MoE row is the one people miss.** During decode, expert FFN has the *same* geometry as attention: tiny activation in, enormous streamed weight matrix, tiny output back. A near-memory unit built for attention offloads MoE decode with no modification.

---

## B4. The parallelism table

Axes: `b` batch, `t` position, `l` layer, `h` head, `d` feature, `e` expert, `j` KV index. For each op: which axes are free (partition with zero communication), which are reductions (tree, log depth), which are sequential.

| Op | Structure | Free (parallel) | Reduced (tree) | Sequential |
|---|---|---|---|---|
| RMSNorm | map+reduce | `b,t` | `d` | - |
| QKV proj | map+reduce | `b,t,h,d_out` | `d` | - |
| RoPE | map | `b,t,h,d` | - | - |
| KV write | map | `b,t,h,d` | - | - |
| Scores | map+reduce | `b,t,h,j` | `d_h` | - |
| Softmax | reduce (assoc) | `b,t,h` | `j` | - |
| `AV` | map+reduce | `b,t,h,d_h` | `j` | - |
| Out proj | map+reduce | `b,t,d` | `h·d_h` | - |
| MLP | map+reduce | `b,t,d_ff` | `d` | - |
| Router | map+topk | `b,t` | `e` | - |
| Expert FFN | grouped map | `b,t` (ragged), `d_ff` | `d` | - |
| **SSM scan** | scan (assoc) | `b,d,n` | - | `t` → `O(log t)` |
| **Decode loop** | recurrence | - | - | `t`, **irreducible** |

### Reading it off

- `b` and `h` are free in **every single row**. Partition on those first, always, zero communication.
- `t` is free in every row **except** the scan and the decode loop. During prefill it is fully parallel. Attention's cross-token edge is an *expanding read set over immutable history*, not a recurrence: order all writes before all reads and it vanishes. That is the append-only property from B2 paying off directly.
- SSM's cross-token edge **is** a recurrence, over mutable state, so it needs the scan: `O(log t)` span instead of `O(1)`.
- The decode loop is the only true serial dependency in the entire model. Nothing fixes it; speculative decoding just gambles on it.
- `e` is free but ragged. Parallelism exists, load balance does not.
- `d` is a reduction axis nearly everywhere, so it is the last resort for partitioning (it costs an all-reduce).

---

## B5. Pass ordering

The order the analyses must run, because each one changes the facts the next one reads:

1. **Shape inference**, separating static from S5b-dynamic. Everything downstream branches on this.
2. **Binding-time analysis** → specialize S0/S1, emit the pre-transform pass that runs once at weight load.
3. **Structure classification** (map / reduce / scan / stencil per op) → gives the parallelism table mechanically.
4. **Effect + alias analysis** → classify each buffer append-only / destructive / pure.
5. **Fusion**, gated on associativity for anything spanning a reduction axis.
6. **Offload legality** → tag ops matching broadcast-stream-reduce.
7. **Liveness + last-use** → in-place decisions, buffer coloring, tier assignment.
8. **Partitioning**, in priority order `b`, `h`, then `t` if not a scan, then `d` last.
9. **Dynamic dispatch** for the S5b residue only.

> Step 6 comes before step 7 deliberately: offloading changes where values live, which changes liveness. Get this backwards and you compute in-place decisions against the wrong memory hierarchy.

---

## The one-sentence version

**Append-only immutability is what makes attention parallelize, and associativity is what makes it offloadable.**

Both are properties of the *algebra*, not the arithmetic. That is why List A is short and boring while List B is where the machine actually gets designed. It is also why a linear-attention or SSM layer, which has the same op list, needs a different machine: its state is mutable, so the first property is gone, and it must buy parallelism back through the scan's associativity instead.

---

# Part IV: what this forces for AnalogIOC

Everything above was analysis. This part is the design decision it produces: a two-chip accelerator with no HBM in the attention path.

## Chip 1: the main accelerator

Chip 1 handles the position-local work: norms, QKV and output projections, RoPE, MLP, and the S5b control residue (routing, sampling, dispatch). It is built around analog in-memory compute plus other blocks for more general usage, so AnalogIOC can operate at the same general-purpose degree as Nvidia while being faster and more energy efficient.

The compiler analysis says exactly how much generality that requires, and it is less than you'd fear. B1 showed that S0 through S5a can be hardwired, because their shapes are static even when their values are not. Only the S5b residue (four things: MoE routing, sparse-block selection, speculative-decode accept counts, continuous-batching lengths) needs a programmable escape hatch. So "general-purpose degree of Nvidia" does not mean a sea of cores. It means a mostly fixed-function analog datapath with a small dynamic-dispatch region, which is a far better energy proposition.

## Chip 2: the in-memory attention engine

Attention means grabbing the KV cache, and normally (as in Etched's architecture) that goes through HBM. However fast HBM is, section 3 showed the problem stays memory-bound: the FLOP-to-byte ratio of decode attention is a small constant that batching cannot improve. Meanwhile the main accelerator is compute-bound, whether from digital systolic arrays or analog IMC. Feeding a compute-bound machine from a memory-bound pipe wastes one of them at all times.

Chip 2's goal is to stop being memory-bound entirely: move the computation to where the KV cache lives, so the problem turns back into a compute-bound one, which we can then keep optimizing with analog IMC and mathematical techniques. B3 is the proof this is legal and profitable:

- The fused `QK^T` → online-softmax → `AV` loop is the canonical broadcast-stream-reduce op. Broadcast `q` in (`d_h` values), stream `K,V` locally, return `o,m,ℓ` (`d_h+2` values). At `L = 128k` the interface traffic drops by roughly 128,000×.
- The fusion is legal because the online-softmax monoid is associative (section 6): each bank reduces its own slice, a small tree merges partials, no global pass needed.
- The unit needs only MAC, `max`, `exp2`, and a rescale multiply per bank, with one `reciprocal` at the end. No `rsqrt`, no `log2`; those stay on Chip 1 with the position-local ops.
- KV cache is append-only (B2): immutable after write, no coherence protocol, free prefix sharing, and the only hazard in the structure (`write(j) → read(t>j)`) is erased in prefill by ordering writes before reads. The memory system Chip 2 needs is therefore radically simpler than a general cache hierarchy.
- The same unit offloads MoE expert FFN at decode with no modification, because tiny-activation-in, huge-weights-streamed, tiny-result-out is the same geometry. Chip 2 is an attention engine that happens to also be an MoE decode engine.
- The SSM scan offloads partially: local scans run in-memory, cross-chunk carries return to Chip 1.

## The interconnect between them

Section 5 found exactly one dependency edge crossing the token-local / token-crossing boundary: the KV append. Chip 1 sends `k'_t, v_t` across once per token; Chip 2 sends back `o_t` per query. Both are `O(d_h)`-sized messages. The chip-to-chip link carries the smallest tensors in the entire model, which is what makes a two-chip cut survivable where an arbitrary cut would drown in traffic.

## How far the analog goes

Working assumption: essentially everything other than PCIe and the chip-to-chip interconnect should be analog. The op inventory backs this up. Sections 7 and 8 reduced the entire model to MACs, a small vector ALU, and four transcendentals built from seed tables plus refinement, and a seed table is a small fixed read-only function that has no inherent need to be digital. The function lookup tables themselves are analog candidates. The dedicated research on analog LUTs has not been done yet, so this is a direction we are committing to investigate, not a verified result. The digital islands that must remain are the fp32 accumulation and decision points from the precision table (norm statistics, router logits, long-axis accumulators, SSM state) plus the S5b control logic and the serial links.

## The remark: why there is no third chip for the weights

The obvious next step would be a third chip doing weights-in-memory, the way Chip 2 does KV-in-memory. It was purposefully avoided, and the effect classes from B2 explain the asymmetry.

Weights are read-only-persistent: written once at model load, read forever, never invalidated. But our analog IMC is consuming: the stored data is disturbed whenever math is done with it, and lost when power is lost. A consuming substrate cannot hold a read-only-persistent value; every read would degrade the thing that must never change. So the weights would still need HBM backing anyway, which defeats the purpose of the third chip.

This stays true until a non-consuming approach to analog IMC is researched, one where reads leave the weights untouched and unmodified, and the cells do not drift over long periods. Digital IMC may be the right space for that, since digital storage does not degrade on read and does not drift. Note the contrast that makes Chip 2 viable where a weight chip is not: the KV cache is written fresh every request and read a bounded number of times, so a consuming read is survivable there in a way it never is for weights that must live for the model's whole deployment.

---

## Notes on specific models

**DeepSeek V4** is public and unusually informative for this analysis. A 1.6T MoE whose main change over V3 is a dual-path hybrid attention replacing MLA: token-wise 4:1 compression along the sequence axis via a softmax-gated pooling function with learned positional bias, plus a "Lightning Indexer" running in FP4 that does ReLU-scored multi-head dot products to select the top-512 compressed blocks per query. The MoE stays DeepSeekMoE; multi-token prediction is unchanged from V3; RMSNorm is applied directly to attention queries and KV entries to prevent logit explosion. DeepSeek explicitly flags that expert parallelism imposes substantial interconnect bandwidth and latency demands. That single model exercises nearly every op class in List A.

**Kimi K3** does not appear to exist as of this writing; the current line is K2/K2.5. Moonshot's architectural direction is visible in Kimi Linear: Kimi Delta Attention, a gated-DeltaNet variant using a specialized Diagonal-Plus-Low-Rank transition matrix, hybridized layerwise with MLA. That is a linear-attention/SSM primitive, so it pulls in the scan operations and the mutable-state consequences from B2.

**Claude Fable 5**: Anthropic does not publish architecture details. Nothing in this document should be read as describing it.

**Etched Sohu** has not published a microarchitecture. The public claims concern fixed-function attention circuits and high sustained FLOP utilization; Etched has said the shipping architecture handles MoE and long context rather than only dense transformers. The token-independent/token-dependent framing used throughout this document is the split the *math* forces, not a documented Sohu block diagram.

### Sources

- DeepSeek-V3 Technical Report - https://arxiv.org/abs/2412.19437
- DeepSeek-V4: Towards Highly Efficient Million-Token Context Intelligence - https://arxiv.org/html/2606.19348v1
- Kimi Linear: An Expressive, Efficient Attention Architecture - https://arxiv.org/pdf/2510.26692
