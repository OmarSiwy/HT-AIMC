---
name: analog-design-flow
description: The analog block design process for this repo — architecture, Verilog-A golden models, SpiceRack testbenches, topology, gm/Id sizing, Philis layout, corners and Monte Carlo. Use when starting, sizing, laying out, or verifying an analog block under analog/, or when asked "what's next" on one.
---

# Analog design flow

Five stages, then a loop up the **signoff ladder**. Tool mechanics live in their own
skills — load the one a stage names before writing its first file:

| Skill | For |
|---|---|
| `spicerack` | circuits, testbenches, PDK libs, corners, MC, external DUTs |
| `vera` | Verilog-A models, `vera` checks, ESPice (ARPice) |
| `philis` | P&R, iteration knobs, signoff reports |
| `analog-netlist-first` | `make netlist`, cktImg schematics, nix-shell gotchas |

## Ground rules

* **Netlists are build byproducts.** Every `.spice` comes from a Python script via
  SpiceRack; edit the script, re-run, never the deck. `make clean` deletes decks anyway.
* **SpiceRack builds every deck** and ngspice runs it (`tb.with_backend`); VACASK is the
  other SpiceRack backend. Two Zig simulators sit beside it, neither a SpiceRack backend:
  ESPice (the ARPice repo) runs Verilog-A via `.hdl` (see `vera`), and **EGSpice** — a
  separate successor simulator (`~/Documents/Projects/Zig/EGSpice`) — is the intended
  target but mid-rewrite: as of 2026-09-29 its build rejects even a resistor ("no device
  model compiled for kind resistor"). When EGSpice runs decks, it becomes a SpiceRack
  backend and this rule changes.
* **PDK-agnostic, always.** No process number, device name or hand-picked W/L appears
  in any block script. Everything a design needs from the process flows down one chain:

  ```
  pdk_specs.py   what the process IS: declared from the PDK's own files (+ pdk_char.py
      |          measurements), device cards, model wrapper per corner
  gmid.py        gm/ID tables of the active PDK (GmIDVisualizer, generated on demand)
  specs.py       architecture math: design choices + laws -> currents, caps, timing
      |          (L in units of Lmin, per-PDK design overrides, tile calibration)
  <block>.py     topology + sizing derived from the three above -> deck
  ```

  Where AnalogIOC-style code "picked" an L or W, search it (step L in `min_l` units until
  the gain/Pelgrom/Ron budget holds). `$PDK=<other>` and re-running must be the whole
  port; `analog/common/hotswap.py` proves it for every installed PDK.

## Where things live

The role model is `~/Documents/Projects/Trial/ResearchBoutros` (AnalogIOC migrated onto
this flow; `analog/strongarm/` is the reference block). Copy its layout exactly:

```
analog/docs/                      system level — shared by every block
  architecture.md                 system architecture, block table, system spec table
  pdk_specs.py                    PDK registry: declared facts, device cards, model wrapper
  pdk_char.py -> pdk_char/<pdk>.json   measured facts (Vth, uCox, SS, MIM, poly R, t_inv)
  pdk_models/<pdk>/<corner>.spice     generated model wrappers (corner, <corner>_mm)
  gmid.py -> gmid_tables/<pdk>/   gm/ID lookups + committed tables
  mismatch.py -> mismatch_cache/  measured sigma(VGS) per (device, W, L, I), per PDK
  specs.py                        executable architecture spec (design knobs + laws)
analog/common/                    flow plumbing — no design content
  devices.py                      fet() / mim_cap() / poly_res() through PDK cards; deck()
  bench.py                        testbench() with the $DUT va|sch|pex switch; Report
  corners.py                      any tb across pdk.corners x -40/27/125 C
  pex.py                          Philis extraction -> simulatable <block>_pex.spice
  hotswap.py                      every block re-derives on every installed PDK
analog/<block>/                   one per block (make -C .flows AddAnalogBlock ...)
  docs/architecture.md            interface, spec table (row -> testbench), sizing, results
  va/<block>.va                   golden model, ports 1:1 with the subckt
  netlist/<block>.py              topology + sizing; build() + prints deck (-> .spice)
  test/tb_*.py, tb_<block>_mc.py  nominal testbenches, Monte Carlo
  layout/interface.json           Philis pin placement
  output/pnr/                     Philis runs + <block>_pex.spice (gitignored)
```

## 1. Architecture

Write `analog/docs/architecture.md` (system) and `analog/<block>/docs/architecture.md`
(per block). Each block doc carries a **spec table**: metric, min/typ/max, unit, which
testbench measures it. Specs derived from process limits cite `pdk_specs.py` keys, not
numbers.

Extend `analog/docs/pdk_specs.py` for every PDK quantity the specs touch. A value is
either **declared** (read from the PDK's own model lib / DRC decks, with a comment citing
the file and rule) or **measured** by `pdk_char.py` with the PDK's own models; never
typed from memory. Architecture numbers go in `specs.py` as functions of `get_pdk()`.
Adding a PDK: declare its entry (device names, `fet_card`/`mim_card`/`res_card`, lib,
corner and mismatch mechanics, layout rules), run `pdk_char.py <pdk>`, then
`hotswap.py`. Ask the user for any value the PDK files don't state.

**Done when:** every block in the system doc has its own doc, every spec row names its
testbench, and `python analog/docs/pdk_specs.py` reports no unset field for any
installed PDK.

## 2. Verilog-A golden models

One `.va` per block, **1:1 with the netlist subcircuits** — same module name as the
`.subckt`, same port names and order. Model in-out behaviour only: gain, poles, offset,
limits, bias current, whatever the spec table measures. Write it in the OpenVAF subset
(continuous: `tanh` switching, RC + `ddt` delay — see `vera`), so `DUT=va` runs on
ngspice. `make -C analog/<block>/build/va lint` (VerA) and `va` (OpenVAF → OSDI) on
every edit — both must pass.

**Done when:** every block has a `.va` passing `vera --lint` and OpenVAF, ports matching its planned subckt,
and the golden model meets its own spec table in the stage-3 testbenches.

## 3. Testbenches

Write every testbench the spec table names now — including ones only post-layout,
corners, or MC will use. Start from `spicerack.testbenches` (catalog in `spicerack`);
write a custom `DesignBench` only when none fits.

Each testbench takes its DUT from the `DUT` env var and runs unchanged on all three:

| `DUT` | Source |
|-------|--------|
| `va` | `analog/<block>/va/<block>.va` golden model |
| `sch` | `analog/<block>/netlist/<block>.spice` |
| `pex` | Philis post-layout netlist, converted (see `philis`: raw `extracted_pex.spice` won't simulate) |

Assert with `ValidationRule` / `validate_metrics`; exit non-zero on any failure so
`make test` stops. Limits come from the block doc's spec table.

**Done when:** every spec row has a testbench, `DUT=va make -C analog/<block>/build/sim
test` passes, and `DUT=sch` fails only because the netlist doesn't exist yet.

## 4. Topology

In `analog/<block>/netlist/<block>.py`: devices and connectivity inside `.subckt <block>
<ports>` matching the `.va`, using PDK-qualified model names (e.g.
`sky130_fd_pr__nfet_01v8`, from `pdk_specs.py`), every device through `devices.py`
(`fet`/`mim_cap`/`poly_res` — no ideal R/C) and `deck()` printing the bare `.subckt`
(children first) — Philis parses it as-is. Placeholder sizes only. `make -C
analog/<block>/build/schematic netlist` must emit a deck; `make import NETLIST=<block>`
gives a schematic to eyeball.

**Done when:** deck generates, ports match the `.va` exactly, and the user agrees the
topology (show the schematic or a device list with roles).

## 5. Sizing (gm/Id)

Same file as the topology: sizing math sits above the device instantiation and feeds it.
Every MOSFET is sized from a chosen gm/Id:

1. Pick gm/Id per device from its role (≈5–8 speed, ≈10–15 balanced, ≈18–25 low-power/
   matching), write the reason in a comment.
2. gm from the spec (GBW, noise, offset) → Id = gm / (gm/Id).
3. Look up current density Jd(gm/Id, L) from the GmIDVisualizer LUT → W = Id / Jd.
4. Intrinsic gain / gds at that gm/Id and L checks the gain budget; raise L if short —
   in code: step L in `pdk.min_l` units until the budget holds, never a typed L.

Offset / matching specs: size against **measured** mismatch —
`mismatch.pair_offset(dev, W, L, I)` runs the PDK's own mismatch models at that exact
geometry and current (cached like the gm/ID tables). `pdk.a_vt` is only a first guess:
PDK mismatch models are binned and break Pelgrom at short L (sky130 10.45/0.30 µm:
3.66 mV measured vs 2.10 mV Pelgrom). Budget every stage that reaches the input, but
check which one dominates before growing it — Monte Carlo, not the formula, decides.

BJTs: gm/Ic is fixed (≈1/V_T). Set the **effective** gm/Ic with the surrounding
resistors — emitter degeneration gives gm_eff = gm / (1 + gm·R_E) — and size R_E, R_C
from that target.

Look everything up through `analog/docs/gmid.py` (`J_D`, `VGS`, `gm_gds`, `W_for_gm`,
`load_table`): it serves the active PDK's tables and characterises a missing (device, L)
on demand with [GmIDVisualizer](https://github.com/OmarSiwy/GmIDVisualizer) — C FFI
`gmid_characterise` via `$GMID_LIB`, model file = the PDK's `gmid_device_file` or its
typical-corner wrapper, sweep limits from `pdk.vdd`. Tables are committed per PDK. The
library missing → stop and tell the user; it isn't in the nix shell yet.

**Done when:** no placeholder size remains, every device has a gm/Id (or effective
gm/Ic) and its derivation in the script, and `hotswap.py` passes for the block.

## Loop: signoff ladder

Climb one rung at a time. A failing rung sends you back to 4/5 (topology or sizing) and
you re-climb from rung 0.

0. **Hotswap:** `python3 analog/common/hotswap.py` — the block's script sizes itself on
   every installed PDK with only that PDK's devices.

1. **Pre-layout:** `DUT=sch make -C analog/<block>/build/sim test` — all specs pass.
   Compare against `DUT=va` on the same testbench; a large gap means the golden model or
   the topology is wrong, decide which before changing sizes.
2. **Layout.** Two routes, same rung: a **substrate2 generator** (`analog/<block>/layout/
   <block>.rs`; `make gen gen-drc gen-lvs gen-pex`, `DUT=pex PEX_FROM=gen`) is the layout
   you keep — DRC/LVS from the PDK's own klayout/magic/netgen decks, taps and guard rings
   drawn (crate + README: `analog/common/layout/`, sky130 only today). **Philis** is quick
   placement feedback only: its own DRC/LVS under-report (see `philis`), so verify any
   Philis GDS with `make pnr-verify` before quoting it. Philis route: `make -C analog/<block>/build/layout pnr-seeds [SEEDS="1 2"]
   [MAX_ITERS=...]` → `output/pnr/seed<N>/`, with `layout/interface.json` picked up
   automatically. Philis converges with more iterations: the default budget is 100 up to
   30 FETs and 60 above (an iteration there costs ~45–60 min) — run it in the background
   and climb the other rungs meanwhile. Iterate per the `philis`
   skill's knob order, logging each row; keep the best run. Several MIM caps hang
   Philis: P&R a cap-free deck (`PNR_DECK=...`). Quick feedback, not signoff.
3. **Post-layout:** `make -C analog/<block>/build/layout pex RUN=seed<N>`
   (`analog/common/pex.py`, which also re-adds caps left out of the P&R deck), then
   `DUT=pex ... test` — all specs pass.
4. **Corners:** `make -C analog/<block>/build/sim corners` (`corners.py` re-runs every
   nominal `tb_*.py` over `pdk.corners` × −40/27/125 °C via `$CORNER`/`$TEMP`) — all pass.
5. **Monte Carlo:** `make ... mc` runs `test/tb_<block>_mc.py`: N fresh benches on the
   mismatch section (`pdk.typical + pdk.mismatch_suffix`) with `tb.options(seed=i)`
   (SpiceRack's `MonteCarloPlan` is Spectre-only) — yield target from the block doc met.

**Done when:** all five rungs pass on the same sizing, results recorded in the block doc
(spec table gets a measured column per rung).
