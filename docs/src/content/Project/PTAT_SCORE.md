# PTAT score pre-scale (task #25) — compiler half of softmax temperature-invariance

Pairs with #18's analog tail-PTAT (`analog/.../ptat_bias/ptat_bias.py`). Together
they make the translinear softmax temperature-invariant. Neither half alone does.

## Why the compiler must do this

The translinear softmax output ratios are

    I_i / I_j = exp( beta(T) * (V_i - V_j) ),   beta(T) = 1/(n*U_T) ~ 1/T.

The ratios depend ONLY on `beta(T)` and the score SPREAD `dV = V_i - V_j` about the
common mode. The tail/normalization current `I_b` cancels out of every ratio.

- #18's tail-PTAT stabilizes `I_b` (measured +22.4%/58C clean PTAT vs the fixed-bias
  +281% blow-up), so the KCL sum stays put — but it CANNOT touch `beta(T)`.
- So tail-PTAT alone leaves the sharpness drifting with `beta(T) ~ 1/T`: measured
  **-13% winning-branch ratio drift 27->85 C** (#18 config-B).

The only knob that cancels `beta(T)` is `dV`. If the compiler pre-scales the score
spread by `T/T0`, then

    beta(T) * dV_scaled = (1/(n*U_T(T))) * (T/T0) * dV  ~  const,

because `U_T = kT/q ~ T`. That is temperature-invariant sharpness. #18 config-C
(tail-PTAT + this score co-scale) measured **+0.4%** — flat.

## What landed

Scalar pre-scale on the score map, flag-gated by device temperature.

- `scripts/golden/model.py`
  - `ptat_score_gain(t_kelvin, t0_kelvin=300.15)` -> `T/T0` (mirror of the analog
    `ptat_bias.ptat_score_gain`; the ideal-physics factor).
  - `attention_forward(..., score_gain=1.0)` multiplies the dequantized score `z`
    (the spread about CM; softmax subtracts its own max, so CM is irrelevant) by
    `score_gain` before `softmax_ref`. Default `1.0` -> byte-identical.
- `scripts/compiler/compile.py`
  - `run(..., score_temp=None)`; when set, `score_gain = G.ptat_score_gain(T)` is
    threaded into `attention_forward` and echoed into `digital_config.json`'s
    `attention` block as `score_temp_k` / `score_gain` (emitted ONLY when opted in,
    so the default tree stays byte-identical).
  - `--score-temp <Kelvin>` CLI flag. Unset = `T0` = default path.

`T0 = 300.15 K` (27 C) nominal. `T = T0` -> factor exactly `1.0`.

## Verification

`scripts/golden/test_golden.py::test_ptat_score_gain` uses the measured translinear
`beta(T) = 27.31 / 24.71 / 22.36 /V` at 27/55/85 C (STATUS A3, CHIP2_SPEC B4) on a
fixed score pattern (dV about CM):

| T     | ratio drift, no pre-scale | ratio drift, with `T/T0` pre-scale |
|-------|--------------------------:|-----------------------------------:|
| 27 C  | 0.00%                     | 0.00%                              |
| 55 C  | -5.82%                    | -0.64%                             |
| 85 C  | -11.37%                   | -1.38%                             |

The pre-scale collapses the drift from ~-13% to under ~1.4% — mirroring #18's
config-B (-13%) vs config-C (+0.4%). The ~1.4% residual is the gap between the
ideal `T/T0` factor and the *measured* `beta(T)` (measured -18.1% drift vs ideal
1/T's -16.2%); for exact cancellation, drive `score_gain` from measured `beta(T)`
instead of `T/T0`, at the cost of a per-corner calibration table.

## How the two halves pair

| symptom             | analog fix (#18)        | compiler fix (#25)            |
|---------------------|-------------------------|-------------------------------|
| `I_b` / KCL drift   | tail-PTAT bias          | —                             |
| `beta(T)` sharpness | (cannot — ratios cancel `I_b`) | score spread x `T/T0`  |

Enable both for full temperature-invariance: PTAT tail bias in silicon,
`--score-temp <T>` (or `run(score_temp=T)`) in the compile.
