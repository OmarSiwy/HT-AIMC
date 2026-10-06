# Tool issues found during the AnalogIOC migration

Each row: what breaks, how it was found, the workaround in this repo, and what the
upstream fix is. Found 2026-09-28/29 on sky130A / gf180mcuD.

## Philis (UW-ASIC/Philis, EDA-Packaged build) — reported to the philis-a0 session 2026-09-29

| Issue | Found by | Workaround here | Upstream fix |
|---|---|---|---|
| **Own signoff under-reports badly:** strongarm v3_seed5 — Philis "DRC 2 / LVS MATCH", but the PDK's klayout deck (`sky130A_mr.drc`) finds **264** (li.5 48, via2.1a_a 72, via.5a 40, m2.5 39, via2.5 34, li.6 16, li.3 8, m5.4 7), magic DRC 648, netgen LVS **fails** (12 vs 10 nets: floating n-wells, no pin labels) | layout-infra, 2026-09-29 | run the independent klayout/magic/netgen checks on every Philis GDS; never quote Philis's own DRC/LVS as signoff | complete GPurify rule coverage; treat wells as nets in LVS |
| `extracted_pex.spice` not simulatable: no `.subckt`, generic `nmos`/`pmos`, passives dropped, parasitics as comments, NMOS bulks on `vdd`, d/s swapped, parallel FETs merged into one summed-W device | strongarm | `analog/common/pex.py` rebuilds it against the source deck | emit a subckt with PDK models, true bulks and R/C elements |
| Ports renamed `n<id>` without `--interface` | strongarm | always pass `layout/interface.json` | carry `.subckt` port names to the layout |
| Several `cap_mim_m3_1` in one deck: first "extracting feedback" never finishes (> 8 h, 1 thread) | async_ctrl | P&R a cap-free deck; `pex.py` re-adds the MIM caps from the full deck | — |
| `poly min_extension` DRC on long-L PFETs (L = 9.6 µm) and on W = 0.42 µm devices | removed long-L block | recorded as residual DRC | device generator |
| LVS "topology mismatch: device class N" although the extraction matches the source | pwm_driver seed 1 | judge by `extracted_pex.spice` + `pex.py` | LVS device classing |
| **Nets merged in layout (a short):** async_ctrl seed 2 extracts 43 N / 43 P vs 45 / 45 in the source — four inverters (Xinv_rd1, Xsettle_dly X16–X18) come back as two double-width inverters, i.e. their nets were joined | async_ctrl | seed rejected (LVS mismatch); `pex.py` also exits on merged source nets | router / connectivity check |
| Long-L devices laid out ~3·L wide (`footprint exceeds the die`) | removed long-L block | bigger die / split into series devices | cell generator |
| Runtime: ~23 min / 100 iterations at 9 FETs; 45–60 min **per iteration** at 30–90 FETs; loop does not stop early | all blocks | `--max-iters 4…25`, 2 seeds in parallel | — |
| `LI.3` (li spacing) residual on most runs | strongarm, pwm_driver | recorded | router |
| **No well / substrate taps drawn:** a rail that reaches only device bulks is an `unconnected_pin` (ERC), and the PMOS n-well is tied to `vdd` only "through the well" (`soft_connection`) — not a real tap | cmos_switch (all 4 runs) | recorded; a real layout needs taps | generate well/substrate ties for bulk nets |
| Advanced IR-drop / EM / reliability checks do not run on small cells ("power-grid topology / stress models not supplied") | cmos_switch | — | — |
| Budget data point: tiny decks converge by themselves (cmos_switch, 2 FETs: stops at 14–21 iterations, identical result at 100); large decks (30–90 FETs) do not stop early | cmos_switch vs async_ctrl; pwm_driver (34 FETs) 100-iteration runs found their best at iterations 40 and 57 | budget 100 ≤ 30 FETs, 60 above | early-stop schedule |
| **Pin text on a non-conductor layer:** every top-level text (pins *and* instance names Xtail, Xinp, …) is written on 236/0, which is not a sky130 layer, so no net binds to it. GPurify, magic/KLayout LVS and any LEF abstract can't find the pins | GPurify session, 2026-10-04 (strongarm if_seed1, cmos_switch seed12, ota if_seed1) | use `output/gen/*.gds` (substrate2, pins on met1/met2 .pin + .label) for anything that needs pins | emit each pin as `<metal>.pin` (e.g. met2 69/16) + `<metal>.label` (69/5) on the conductor reaching the boundary; keep instance names off conductor layers |
| Only `sky130.json` / `generic_finfet.json` rule decks packaged | — | layout rung is sky130-only | package gf180/ihp decks |
| `--hier` shares one config and one `-o` dir across blocks, so it cannot take `--interface`: hierarchical P&R loses port names | phase 4 harden wiring (analogioc top), 2026-10-05 | analogioc top: hierarchical assembly by a substrate2 generator (REQUIRED_TOOLING §4) | per-block interface files under `--hier` |

## GPurify (`gpurify lib`, local build 0.1.0) — found wiring analogioc's Liberty, 2026-10-05

| Issue | Workaround here | Upstream fix |
|---|---|---|
| A corner's `models` line goes into the ngspice deck verbatim, with no environment expansion, so a spec with `$PDK_ROOT` cannot be committed | `analog/analogioc/layout/liberty.py` writes the spec at `make lib` time, into `output/lib/liberty.json` | expand `$VAR` / `~` in `models` |
| Every arc case's first vector must drive every digital input. For analogioc (415 inputs, 70 cases) the spec is 0.8 MB | generated, not committed | default unnamed inputs to a `defaults` vector |
| Spec, LEF and reference pins are compared by exact name, so a `.subckt` with `x<0>` never matches a LEF/Verilog `x[0]` | `make lib` writes `output/lib/analogioc_ref.spice` with `<i>` → `[i]`; `macro_views.py` renames GDS labels | a bus-bit spelling option |
| Drives `ngspice -p` only; the analog shell has ESPice | `nix-shell -p ngspice` for `make lib` | REQUIRED_TOOLING §5 |

## cktImg (OmarSiwy/cktImg `298fee1`, EDA-Packaged `4b6c5be`)

| Issue | Found by | Workaround here | Upstream fix |
|---|---|---|---|
| Dense arrays route poorly: no short any more (L9 + final cleanup), but in gain_cell_array about 16 of 33 nets get no wire and are joined only by labels (746 wires left out), because the long shared vss/`rd*` lines sit on the same rows. write_dac and rstring_ladder have fewer label-only joins | cktImg router-fix session, 2026-10-05 | schematic is still correct (labels connect); just less readable | a real detour router |

## substrate2 (ucb-substrate/substrate2, `substrate` registry) — found by layout-infra 2026-09-29

| Issue | Workaround here (`analog/common/layout/`) | Upstream fix |
|---|---|---|
| Registry ships a `sky130` PDK crate only (no gf180) | layout rung sky130-only; `Tech` trait kept for a gf180 binding | gf180 PDK crate |
| `sky130` 0.10.3 `Sky130Layer` has no capm (MIM) layer | MIM drawn on unused `Tunm`, mapped to GDS 89/44 in our `to_gds` | add capm |
| MOS tiles only allow L = 150 nm (`MosLength::L150`) | own `Mos` primitive: upstream geometry, S/D pitch widened for any L | arbitrary-L tiles |
| `sky130::res::PrecisionResistorCell` fails DRC (urpm.1a: 0.75 < 1.27 µm at W=0.35; head 2.08 < 2.16 µm, licon.1c + li.5) and draws xhigh only | own `Res` (high + xhigh, both rules fixed; marker 60 nm into each head so magic extracts L exactly) | fix the cell |
| `magic_netgen` / `pegasus` crates need `OPEN_PDKS_ROOT` or Cadence and LVS against substrate's own netlist | `verify.py` drives klayout, magic, netgen directly against our deck | — |
| `cache` crate needs `protoc` at build time | `pkgs.protobuf` in `Analog.nix` | — |
| magic cannot name `_0p35` resistors from GDS | `verify.py` renames `res_high_po w=0.35` → `_0p35` | — |
| klayout `sky130A_mr.drc` is weak on front-end rules (missed licon.8 that magic caught) | `gen-drc` also prints magic's full DRC count | — |

## ESPice (OmarSiwy/ESPice `716a502`, EDA-Packaged `8194a27`) — limits found 2026-10-05

| Issue | Workaround | Upstream status |
|---|---|---|
| A distribution in a top-level `.param` is not redrawn per Monte Carlo seed | put mismatch in the model sections (sky130 `tt_mm`, which works) | documented in ESPice `docs/sky130.md` |
| Distributions inside behavioural sources stay at nominal (same as ngspice for sky130: resistor mismatch reads 0) | size resistor matching from `pdk_specs` declared values | documented |
| PWL longer than 64 points with `r=` is refused | split the source | documented |
| A Verilog-A device with more than 64 unknowns (ports + internal nodes) does not compile: `device/eval.zig` keeps each Jacobian row as a `u64` mask ("shift by negative amount", "u6 cannot represent 64", `GeneratedDeviceDoesNotCompile`) | split the model into child modules ≤ 64 unknowns and wire them in the deck (`lora_sidecar`: 4 modules, the whole sidecar has 201) | not reported upstream yet |
| Seed N draws a different mismatch sample than ngspice's seed N (own RNG); only the spread matches (σ(ln Id) 0.269 vs 0.274 over 100 seeds) | compare statistics, not single seeds | by design |
| Once in ~70 runs under 6 parallel processes, `espice` exited `Error: <tmp>/deck.sp: FileNotFound` for a deck SpiceRack had just written (weight_tile, 2026-10-05); the rerun passed | rerun | not reported yet |
| **BSIM4 comes from Cogenda VA-BSIM48 (CC-BY-NC 4.0)** compiled by VerA | — | **licence: non-commercial**; check before any commercial use |
| `m=` on a Verilog-A device is refused: `module 'bsimcmg' has no parameter 'm'` (ASAP7, 2026-10-05) | `devices.fet` folds `m` into BSIM-CMG `NF` (exact) | REQUIRED_TOOLING §3 |
| A deck whose first line is `.lib`/`.include` loses it: line 1 is the title (SPICE rule), and the device then fails `UnsupportedDevice` with no hint | always write a title line (`gmid._espice` does) | a warning when line 1 is a dot-card would help |
| **The 64-unknown cap also applies to `.v` (VerA digital) devices**, so a co-simulated RTL block holds at most 64 pins in ESPice, not VerA's 256 (imc_tile, 2026-10-06) | `analog/imc_tile/test/tb_cosim.py` runs open loop: iverilog writes a pin trace, ESPice runs the tiles from it, the RTL replays the SAR codes (exact because the tile's inputs never depend on its outputs) | not reported upstream yet |
| A B-source takes at most 8 probes (imc_tile) | book event energies in Python from the same parameters the models use | not reported upstream yet |
| A Verilog-A device whose `@(cross)` events probe fast-moving inputs continuously drives the timestep down to about 0.1 fs (imc_tile) | probe inputs only inside events (`imc_col.va`) | not reported upstream yet |

## ASAP7 (EDA-Packaged `asap7`, 2026-10-05)

| Tool | Issue | Workaround | Upstream fix |
|---|---|---|---|
| OpenVAF-r | exits 0 when its link step fails (no `cc` in a `stdenvNoCC` build), leaving only `bsimcmg.o*` | the derivation uses `stdenv` and tests for the `.osdi` | report to arpadbuermen/OpenVAF |
| VerA `--check` | with a host `zig` other than 0.17 first on PATH (here 0.16), it reports "codegen produced Zig that does not compile — this is an engine bug" (`@backingInt`) — the toolchain is wrong, not the engine | put zig 0.17 first, or skip `--check`: ESPice's wrapper sets `ZIG` itself | name the Zig version mismatch in the message |
| ORFS `asap7.lydrc` | S.1 on LISD/LIG/M1–M3 dropped every violation touching a ≤ 36 nm edge, so two parallel 18 nm wires passed at any spacing; `M1.S.2` output as `"  "`, `LIG.S.2` reported as `LISD.S.2`, `LIG.S.4-5` filtered on `lisd` edges; batch runs need a GUI view for the report path | fixed in EDA-Packaged `nix/asap7/klayout_drc.py` | report to OpenROAD-flow-scripts |
| ngspice 44.2 + OSDI | an OSDI model on an `M` card: "model type mismatch … incorrect model type" | `N` cards for the ngspice reference (ESPice takes `M`) | — (ngspice binds OSDI to `N` only) |
| ASAP7 models | BSIM-CMG 111 runs the CMG 107 cards (`version`, `capmod`, `coremod`, `nseg` dropped). Idsat is 4–9 % under Clark et al. 2016, and nmos_sram Ioff (GIDL) is 4.9× the paper, which predates the 160803 cards | judge against `asap7_smoke.py`, not the paper | — (no CMG 107 Verilog-A is public) |

## VerA (vera 1.0.0, EDA-Packaged `VERA_CONTRACT` build) — found by imc_tile, 2026-10-06

| Issue | Workaround | Upstream status |
|---|---|---|
| `vera --check` fails on every model, including the repo's reference `strongarm.va`: a contract `isDenseEnum` comptime error | gate on `vera --lint` instead | not reported upstream yet |
| The event engine is IEEE 1364 only | write co-simulated RTL as Verilog-2001 with the `_d/_q` discipline | by design |

## Others

| Tool | Issue | Workaround | Upstream fix |
|---|---|---|---|
| SpiceRack | no EGSpice backend | ESPice via SpiceRack | add once EGSpice runs decks |
| SpiceRack | a run holds the GIL for the whole simulation, so a `ThreadPoolExecutor` of benches simulates one at a time (ngspice and espice; seen 2026-10-05: one simulator process under JOBS=8) | `ProcessPoolExecutor` with module-level callables (`analog/weight_tile/test/tb_*.py`) | release the GIL around the backend call |
| EGSpice | separate successor simulator, mid-rewrite: current build rejects a resistor (`no device model compiled for kind resistor`) and a sky130 FET (`UndefinedReference`); devices compiled from Verilog-A at build time only | not in the flow yet | finish the analysis/device migration (STEPS.md step 4) |
| sky130 models | mismatch does not follow Pelgrom at short L (10.45/0.30: 3.66 mV vs 2.10 predicted) | `analog/docs/mismatch.py` measures per geometry | — (model property) |
| sky130 models | `m=` alone does not scale mismatch (`sqrt(l*w*mult)`); gf180 uses `par` | `pdk.mult_card` | — |
| ngspice | after a gate overshoot, transient `i(Vdrain)` sits ~15 % above `@m[id]` for > 30 µs | judge startup on node voltages | report upstream |
