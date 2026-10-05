# Required tooling

Tools and features AnalogIOC still needs. Each section says what we want and why. Bugs in
tools that already work, with their workarounds, are listed in
[`analog/docs/TOOL_ISSUES.md`](analog/docs/TOOL_ISSUES.md).

| # | Gap | Blocks | Owner |
|---|---|---|---|
| 1 | cktImg: grouping hints | readable schematics of matched structures | cktImg |
| 2 | SpiceRack: EGSpice backend | the successor simulator | SpiceRack, EGSpice |
| 3 | ASAP7 as the target PDK | the port; all new work | several |
| 4 | VerA `.v` device: > 256 pins, output-variable ports on part-selects, task-enable panic | `make cosim` (A9, A12 co-sim) | VerA (ESPice picks it up) |
| 5 | Hierarchical layout assembly of the analogioc top | `make -C analog/analogioc/build/layout views` | substrate2 generator (ours) |
| 6 | GPurify in the nix shell, and a simulator it can drive | `make -C analog/analogioc/build/lib lib` | EDA-Packaged, GPurify |
| 7 | Liberty characterization that scales to a whole-chip macro | `ACCURACY=spice` on analogioc | GPurify |

## 1. cktImg: grouping hints

Hierarchy, `--svg` and the MOS bulk field landed (cktImg `51f348d`, pinned in EDA-Packaged
`6015a4b`); `.flows/tools/cktimg_to_xschem.py` uses them and every block with a netlist
imports and netlists back clean.

**Still needed:** grouping hints, so placement keeps a diff pair or current mirror
together. Not started.

## 2. SpiceRack: EGSpice backend

**Done:** ESPice is SpiceRack's backend for this repo (SpiceRack `21de39b`, ESPice
`716a502`); ngspice and OpenVAF are gone from the env.

**Want:** an EGSpice backend once EGSpice can run decks. Its current build rejects even
a resistor. Also, Spectre still drops `raw_spice`; it needs a `simulator lang=spice` wrapper
and a Spectre install to test.

## 3. Port to ASAP7 (the target process)

**Decision (2026-10-05):** ASAP7 (7 nm FinFET, predictive, not fabricable) is the target
process. New architecture work, scoring and the systolic reference are at ASAP7 now; the
sky130 blocks are the calibrated anchor and get ported.

**Needed before the port can start:**
- **Open DRC/LVS for ASAP7:** the official decks are Calibre-only. Need a KLayout (or Magic)
  deck usable by GPurify/Philis, or a GPurify `asap7.deck`.
- **Digital flow:** confirm LibreLane can harden ASAP7; ciel ships sky130/gf180/IHP only.
  Otherwise use OpenROAD-flow-scripts' asap7 platform with the same `macros.toml`.
- **Layout generators:** substrate2 has no ASAP7 crate. Write one, or generate layout with
  Philis plus a real ASAP7 rule deck.
- **Device models:** BSIM-CMG compiled by VerA for ESPice (no OSDI/ngspice in the env); gm/ID tables via GmIDVisualizer.
- **pdk_specs.py:** `asap7_proj` becomes a real PDK, with models, corners, MOM-cap and fin
  parameters.

**Design changes the port forces:** 0.7 V supply (the telescopic-cascode OTA doesn't fit),
MOM instead of MIM caps, fin-quantized widths and near-fixed L, and re-measured calibration
constants (`K_CAL`, `c_ota_self`, fine trim).

## 4. VerA `.v` device: wide designs (blocks the analogioc co-sim)

**Mechanism in use (2026-10-05):** the co-sim runs `analogioc_top` as an ESPice `.v`
device (`.hdl "cosim_dut.v"` + `N` card): VerA's event engine inside ESPice, each input pin
an A2D bridge at `vth`, each output pin a D2A Thevenin driver with `trise`/`tfall` ramps
(ESPice `docs/devices/verilog-digital.md`). The harness is
`digital/analogioc/build/cosim/` (`make cosim-smoke` passes on a toy macro;
`make cosim-elab` stops on the items below). Checked with `vera --emit-zig`/`--check`, vera 1.0.0
(`/nix/store/865al4jp…-vera-1.0.0`, the env's `VERA_CONTRACT` build). The smoke ran on
espice `w9fhfbmb…-espice-1.0.0`.

**Needed, in order:**

1. **More than 256 pins per device.** The digital top crosses the macro boundary on 501
   bits (415 macro inputs, 86 outputs, `analogioc.ports`), plus 10 observation pins:
   511. VerA refuses at 256 (`E1103 "more than 256 pins"`, `src/sim/digital/emit.zig`
   and the pin index in `src/sim/rt/device.zig`). Want: at least 1024 pins. Only pins
   some process is sensitive to cost A2D work, so wide static buses (`w_data`,
   `dac_code`, `x_mag`) should cost little.
2. **An `output reg` port connected to a part-select of a parent net.** VerA refuses
   it (`E1100 "an output variable port connects to one whole net"`,
   `src/sim/digital/elab.zig` `PortBind.send` on a variable port). It is legal IEEE 1364
   (§12.3.9.2) and is how `analogioc_top` wires its 17 `tile_fsm`/`bacc_accum` slices
   (`.col_code(col_code[8*j +: 8])`, `.acc(acc_flat[20*j +: 20])`). With the ports
   rewritten as `output wire` + an internal `reg` (a scratch copy, not committed), the
   whole RTL elaborates and `vera --check` passes once the pin count is under 256.
   The RTL stays as it is; the fix belongs in VerA.
3. **Panic on a user task enable.** `vera --emit-zig` aborts (index out of bounds
   0xAAAAAAAA in `digital.compile.infer` via `checkArgs`/`compileEnable`) when a module
   calls a task and the design also contains `abft_check.v` or `bacc_accum.v`. The same
   task works without them. Workaround in use: `cosim.py` inlines the task.
4. **Nice to have: a device transcript.** A hosted device drops `$display`
   (`src/sim/rt/device.zig` `open()`: `quiet`, a discarding sink), because a rejected
   step would replay it. Results now leave through pins (`obs_d[7:0]`/`obs_v`). An
   accepted-time-only transcript would make debugging easier.

**Not chosen:** a lockstep bridge between cocotb/iverilog and ESPice. ESPice's C ABI
(`include/espice.h`) advances whole analyses and cannot pause a transient at time t to
change a source. That would need a new stepping API plus a VPI bridge, which is far more
new code than items 1 to 3.
## 5. Hierarchical layout assembly of the analogioc top

**Decision (2026-10-05):** the analogioc macro is laid out hierarchically. Each block in its
`DEPENDS` gets its own verified layout and macro views (`make -C analog/<block>/build/layout
views`), then a top generator places and routes them. Flat Philis is ruled out: the flattened
top has more than 20k devices (the 2176 6T bitcells alone are 13k FETs), and Philis costs
45–60 min per iteration above 30 FETs. Philis `--hier` is ruled out too: it cannot take
`--interface`, so the ports come out as `n<id>`, and it writes pin text on 236/0.

**Needed:**
- `analog/analogioc/layout/analogioc.rs`, a `[[bin]]` of `analog/common/layout`. It places the
  blocks' `output/gds/<block>.gds` and routes the block pins to each other and to the
  519 boundary pins (`pins::place` with an `analogioc` interface.json). Not written.
- substrate2/atoll: confirm it can instance an imported GDS (a raw cell with its pin stubs)
  inside a `Tile` and route to it. If it cannot, assemble the top in KLayout Python and
  route the top-level nets with another tool.
- A substrate2 generator for every leaf. Philis GDS cannot become macro views until its pins
  are on a metal (TOOL_ISSUES.md). Generators exist for cmos_switch and strongarm only.

## 6. GPurify in the nix shell, and a simulator it can drive

`gpurify lib` produces analogioc's Liberty. Today it is a local build
(`~/Documents/Projects/Rust/GPurify`), so `make lib` takes `GPURIFY=` and `GPURIFY_DECK=`.

**Needed:** package the `gpurify` CLI and its `pdks/*.deck` in EDA-Packaged, and add it to
`Analog.nix` (exporting `GPURIFY_DECK`). Above `interface` accuracy it runs `ngspice -p`, but
the analog shell has only ESPice. So either add ngspice to the shell for this one step, or
give ESPice ngspice's pipe-mode interface (`-p`, `source`, `RES` lines).

## 7. Liberty characterization that scales to a whole-chip macro

`ACCURACY=spice` simulates the whole extracted analogioc macro (>20k devices plus RC) once
per arc × slew × load × corner. That is 53 arcs × 2 × 2 tables × 3 corners, each a
transient of several hundred ns. It is days of runtime, and the field solve is quadratic
in panel count.

**Want:** characterize per sub-block or on a reduced netlist (only the handshake logic in
`tile_seq`/`conv_seq` drives the pins), then compose the results. Until then, `make
lib-interface` (pins, supplies, area) is enough to floorplan and harden. The arcs matter
little here, because the rail samples every macro output through 2FF synchronizers.
