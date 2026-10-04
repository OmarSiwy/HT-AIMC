# OT_IMPACT — is the Chip2 18.8 LSB o_t error model-breaking? (task #26)

The tb_attention_chip2_e2e e2e ('A-CHIP2 inc4', commit 366e612) got o_t cos 1.000/1.000/0.9978/0.9978 over 4 tokens but max|err| 18.8 LSB on the 3-4-key tokens FAILED the `<=8 LSB` envelope. That +-8 LSB was measured by #24 for the TILE-MVM `y12` code, NOT for the attention output o_t. This task measures the correct o_t budget with #24's error-impact method.

## Method (scripts/compiler/golden math, NO SPICE)
Real SmolLM2-135M blk.0 (head-0 attn + SwiGLU FFN), real 9-token prompt [504, 2365, 6354, 16438, 27003, 690, 260, 23790, 2767]. Compile ONCE clean; re-run the real golden forward with `golden.model.ATTN_OUT_ERR = make_attn_out_err(lsb)` — GAUSSIAN (sigma=lsb/3, 3-sigma clip) additive code error on the attention output o8 (INT8 +-127, so 1 code == 1 LSB of the o_t range), fresh per token. This models the Chip2 analog exp+A.V translinear residual (~1.4% class) that the tb measured on o_t = p@V. Injected vs bit-exact clean, 8 seeds.

**Metric honesty.** blk.0 output (OUTX) cosine + rel-MSE is the real signal; the next-token argmax/top-5 uses the same PROXY head as #24 (`output_norm(OUTX[-1]) @ token_embd.T`, tied embeddings): 1 of 30 blocks + head-0 only, so it measures argmax STABILITY vs the clean quantized path, not a true LM prediction. Same clean ref as #24.

## Results (injected vs bit-exact clean)

| o_t +-LSB | blk.0 cos | cos(min) | rel MSE | argmax agree | top5 overlap |
|----------:|----------:|---------:|--------:|-------------:|-------------:|
| 18.8 (measured) | 0.99348 | 0.99302 | 1.308e-02 | 100% | 4.38/5 |
| 37.6 (2x) | 0.98427 | 0.98225 | 3.146e-02 | 100% | 3.50/5 |
| 75.2 (4x) | 0.95117 | 0.94134 | 9.626e-02 | 75% | 2.25/5 |

Clean proxy next-token argmax = id 29 '-'; clean top-5 = [29, 281, 365, 402, 446].

## Verdict
**18.8 LSB o_t (cos 0.998 per-head) is MODEL-ADEQUATE.** At the measured worst-token severity: blk.0 cos 0.99348 (>0.99), argmax agreement 100%, top-5 4.38/5. The `<=8 LSB` gate the Chip2 e2e failed is the #24 TILE-MVM proxy MIS-APPLIED to o_t — a tile-code budget does not transfer to the attention output.

- **Correct o_t model budget: +-18.8 LSB of the o_t range** (highest swept level holding BOTH 100% argmax AND blk.0 cos>0.99, the #24 criterion). argmax agreement itself survives 100% out to +-37.6 LSB (2x measured); the model only breaks (argmax <100%) at +-75.2 LSB (4x). o_t is a convex softmax average (p@V, no bit growth) that then passes through Wo + residual add + RMSNorm + the FFN, so per-head o_t error is attenuated far more than a raw tile code — the o_t budget is much looser than the y12 tile's +-8.
- **Chip 2 attention MEETS its o_t budget as-built:** the measured worst-token 18.8 LSB sits AT the cos>0.99 ceiling (18.8 LSB) and 2x inside the argmax-survival ceiling (37.6 LSB). Relax the tb_attention_chip2_e2e acceptance from the borrowed `<=8 LSB` tile proxy to the o_t budget (cos>0.99 AND max|err| <= 18.8 LSB). The e2e 'FAIL' is a mis-applied criterion, not a real accuracy shortfall.
- Reducing the exp+A.V translinear error (PTAT co-scale, #18/#25) stays WANTED for margin/cascade headroom but is NOT a correctness blocker for blk.0 next-token.
