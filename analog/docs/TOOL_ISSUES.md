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

## cktImg (OmarSiwy/cktImg `51f348d`, EDA-Packaged `6015a4b`) — found 2026-10-04

| Issue | Found by | Workaround here | Upstream fix |
|---|---|---|---|
| Router runs a wire straight across other nets' pins / wire ends (weight_tile `rowa0` over the `phi1`/`phi2` inverter gates), which xschem connects: a short in the drawing | `cktimg_to_xschem.py` self-check; rstring_ladder, write_dac, gain_cell_array, weight_tile | the converter drops the offending net's wires and joins it by labels on its pins (prints `note: cktImg routed ...`) | router must treat foreign pins and wire ends as blockages |

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

## VerA / ESPice (OmarSiwy/VerA, OmarSiwy/ESPice) — reported to the vera-ac / arpice-7f sessions 2026-09-29

| Issue | Workaround | Upstream status |
|---|---|---|
| Published ESPice pins VerA `297e97dc` (pre-release, 626 commits before v0.9.0): codegen's `var h: [n]S` shadows `const h = @import("../h.zig")` → `GeneratedDeviceDoesNotCompile` for any non-trivial model | golden models run on ngspice via OpenVAF | **fixed on ESPice (ARPice) local `main` `01fa6f93`** (pins VerA `c964f644`): verified 2026-09-29 — `twotr.va` and an event-driven comparator (`@(cross)` + `transition()`) simulate correctly. The GitHub ESPice (`bcc13b3`) still pins the pre-release `297e97dc`. Build needs `../Gompute` next to the checkout |
| ESPice writes `.hdl` builds into `<src>/.zig-cache` → `AccessDenied` from the nix store | build ESPice from a source checkout (`ESPICE_SRC`) | wip, untested: ARPice branch `worktree-agent-aa8d73f15dbb06acd`, commit `da324431` — cache → `$ESPICE_CACHE` / `~/.cache/espice/hdl`, runtime sources installed to `share/espice` |
| ESPice: `.hdl` errors are bare names; misspelled params / missing nodes / `pre_osdi` silently ignored | `vera --lint` first | wip in the same commit: VerA diagnostics printed, `UnknownParameter` / `WrongNodeCount` errors, `pre_osdi` loads the `.va` beside the `.osdi` |

## Others

| Tool | Issue | Workaround | Upstream fix |
|---|---|---|---|
| OpenVAF | no `@(cross)`/`@(timer)` events, no `transition()` | golden models use tanh switching + RC/`ddt` delay | — (upstream limitation) |
| SpiceRack | no ESPice (ARPice) or EGSpice backend | ngspice via SpiceRack | add backends |
| EGSpice | separate successor simulator, mid-rewrite: current build rejects a resistor (`no device model compiled for kind resistor`) and a sky130 FET (`UndefinedReference`); devices compiled from Verilog-A at build time only | not in the flow yet | finish the analysis/device migration (STEPS.md step 4) |
| sky130 models | mismatch does not follow Pelgrom at short L (10.45/0.30: 3.66 mV vs 2.10 predicted) | `analog/docs/mismatch.py` measures per geometry | — (model property) |
| sky130 models | `m=` alone does not scale mismatch (`sqrt(l*w*mult)`); gf180 uses `par` | `pdk.mult_card` | — |
| ngspice | after a gate overshoot, transient `i(Vdrain)` sits ~15 % above `@m[id]` for > 30 µs | judge startup on node voltages | report upstream |
