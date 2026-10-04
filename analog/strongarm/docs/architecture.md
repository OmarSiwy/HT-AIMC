# strongarm — StrongARM latch comparator

Leaf block. Clocked decision element of the column readout: `integrator_conv`
uses it for both the event-rate coarse loop (threshold crossings of the integrator)
and the fine SAR trials. See `analog/docs/architecture.md` §Column readout.

## Interface

`.subckt strongarm vinp vinn outp outn clk vdd vss`

| Port | Dir | Meaning |
|------|-----|---------|
| vinp, vinn | in | differential input, common mode VDD/2 |
| outp, outn | out | drain-side latch outputs; both high while `clk` is low |
| clk | in | low = precharge, rising edge = decide |
| vdd, vss | supply | `pdk_specs.vdd`, 0 |

Convention: `vinp > vinn` → `outp` resolves **low**, `outn` stays high.

## Specs

Offset is uncritical here: the coarse loop sees a uniform threshold shift, i.e.
range loss only. Noise must sit well under the ~5 mV coarse LSB.

| Metric | Min | Typ | Max | Unit | Testbench |
|--------|-----|-----|-----|------|-----------|
| Decision at \|vdiff\| = 10 mV, both polarities | correct | | | — | `tb_strongarm` |
| Decision flips across −10…+10 mV | | 1 | 1 | flips | `tb_strongarm` |
| Input offset \|Vos\| | | | 10 | mV | `tb_strongarm` |
| clk → decision delay @ 100 mV overdrive, 10 fF load | | | 3 | ns | `tb_strongarm` |
| Output high / low after resolution | VDD−0.1 / | | / 0.1 | V | `tb_strongarm` |
| Offset 3σ, Monte Carlo (mismatch) | | | 10 | mV | `tb_strongarm_mc` |

Supply `pdk_specs.vdd`; loads 10 fF per output; clock edge 1 ns.

## Sizing

gm/ID coordinates, derived in `netlist/strongarm.py` from `docs/gmid.py`:

| Device | Role | Coordinate |
|--------|------|------------|
| tail | clocked switch, VGS = VDD | min W × min L; sets I_TAIL = J_D(VDD)·W_min |
| input pair | noise / offset per µA | gm/ID = 13, I_TAIL/2; L = smallest k·Lmin whose **measured** pair offset (`docs/mismatch.py`) ≤ (10 mV/3)·√0.9 |
| latch nfet | regeneration | gm/ID = 8, L = min, I_TAIL/2 (not offset-limiting: see results) |
| latch pfet | regeneration, matched gm | gm/ID = 8, L = min, I_TAIL/2 |
| reset | precharge switch (triode) | W = (1/4.5)·W_latch_p (AnalogIOC's ratio; output node scales with the latch) |

## Results

Sizing history — the ladder sent this block back to stage 5 three times:

| Version | Input pair | Latch | MC σ(Vos) | Outcome |
|---------|-----------|-------|-----------|---------|
| v1 | 6.53/0.15 (gm/ID only) | 2.3/0.15, 10.33/0.15 | 6.94 mV | FAIL 3σ 20.8 mV |
| v2 | 10.45/0.30 (Pelgrom, A_vt 5.0) | same | 4.71 mV | FAIL 3σ 14.1 mV |
| v2b | same | 9.61/0.75, 36.4/0.75 (Pelgrom share) | 4.57 mV | FAIL; also broke ss/fs 125 C — latch is not the source |
| v3 | **21.8/0.60** (measured mismatch) | 2.3/0.15, 10.33/0.15 | **1.84 mV** | PASS (predicted 2.17 mV) |

Root cause: sky130 mismatch models break Pelgrom at short L (10.45/0.30: 3.66 mV measured
vs 2.10 mV Pelgrom). Sizing now uses `docs/mismatch.py`.

| Rung (v3) | Result | Notes |
|------|--------|-------|
| hotswap (sky130A, gf180mcuD) | PASS | gf180: pair 27.16/0.56 µm (measured σ(VGS) 1.53 mV), latch 4.73/0.28, 12.46/0.28 |
| pre-layout (`DUT=sch`, tt 27 C) | PASS | flip 0 mV, delay 0.90 ns |
| golden model (`DUT=va`) | PASS | flip +2 mV (tie at 0 V → vinn), 0.49 ns |
| **layout (substrate2 generator, `layout/strongarm.rs`) — kept** | klayout DRC 0, magic DRC 0, netgen LVS match | 13.47 × 24.89 µm (335 µm²) incl. guard rings; input pair 4 fingers, latch 2 |
| **post-layout (`DUT=pex PEX_FROM=gen`)** | PASS | flip 0 mV, delay 1.20 ns (magic PEX incl. junction caps) |
| layout (Philis, seeds 2/5 at 8 iters; 11/12 at 100 iters) | superseded | Philis self-report "DRC 2 / LVS MATCH", but independent check of seed 5: klayout DRC 264, magic 648, LVS FAIL (floating n-wells, no pins). 100-iteration seeds: best at iters 51 / 37, budget exhausted, advanced 5/6 — no better than 8 iterations |
| post-layout (`DUT=pex`, Philis v3 seed 5) | PASS (on a layout that fails DRC) | flip +2 mV, delay 1.05 ns |
| corners (5 × −40/27/125 C) | PASS | 15/15 |
| Monte Carlo (30, tt_mm) | PASS | mean 0.14 mV, σ 1.84 mV, 3σ 5.5 mV < 10 mV |

AnalogIOC reference (its hand sizing, latch 1.0/4.5 µm): flip at +2 mV, 0.48 ns.
