# sysreference versions under ARCH_METRIC

Every evaluated configuration of the digital systolic baseline, scored with the shared
scorer (`scripts/compiler/metrics/arch_eval/baseline_systolic.py`, called unchanged by
`scripts/score.py`): Llama-3-8B, 512-token prompt + 128 generated, 100 mm2 die, one
HBM-class stack per die (819 GB/s, 24 GB), weights W4 in HBM (same format as the IMC
default), 16-bit KV, power cap 1 W/mm2, VDD 0.45-0.7 V and clock fraction swept by the
scorer. Metrics in ARCH_METRIC order: tok/s per die (king) > TOPS/W > tok/W > tok/J.

Labels: **measured** = synthesized/placed/simulated here (s16, ASAP7 RVT TT);
**derived** = a law (area fit, 16/N edge amortization) applied to measured numbers;
**projected** = literature only. The system model around the tile (rail, HBM PHY,
buffer, KV, schedule) is the scorer's and is projected for every candidate, IMC included.

| v | config | area/PE um2 (128x128, 70 % util) | fmax MHz (TT) | E/MAC fJ | tok/s/die | TOPS/W | tok/W | tok/J | label |
|---|---|---|---|---|---|---|---|---|---|
| 1 | WS 128x128, INT8xINT8 PE, Booth r4, CG, PipeMul, 2 weight banks, 7-stage edge | 123.9 | 1150 | 252 | 29150 | 7.21 | 370.1 | 661.3 | derived (PE measured at s16) |
