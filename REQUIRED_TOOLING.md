# Required tooling

Tools and features AnalogIOC still needs. Each section says what we want and why. Bugs in
tools that already work, with their workarounds, are listed in
[`analog/docs/TOOL_ISSUES.md`](analog/docs/TOOL_ISSUES.md).

| # | Gap | Blocks | Owner |
|---|---|---|---|
| 1 | cktImg: grouping hints | readable schematics of matched structures | cktImg |
| 2 | SpiceRack: EGSpice backend | the successor simulator | SpiceRack, EGSpice |
| 3 | ASAP7 as the only PDK (after the sky130 design is complete) | the port | several |
| 4 | VerA `.v` device: > 256 pins, output-variable ports on part-selects, task-enable panic | `make cosim` (A9, A12 co-sim) | VerA (ESPice picks it up) |

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

## 3. Port to ASAP7 (after sky130 is finished)

**Decision (2026-10-04):** finish and verify the full IMC on sky130 first, then port
everything to ASAP7 (7 nm FinFET, predictive, not fabricable) and drop sky130.

**Needed before the port can start:**
- **Open DRC/LVS for ASAP7:** the official decks are Calibre-only. Need a KLayout (or Magic)
  deck usable by GPurify/Philis, or a GPurify `asap7.deck`.
- **Digital flow:** confirm LibreLane can harden ASAP7; ciel ships sky130/gf180/IHP only.
  Otherwise use OpenROAD-flow-scripts' asap7 platform with the same `macros.toml`.
- **Layout generators:** substrate2 has no ASAP7 crate. Write one, or generate layout with
  Philis plus a real ASAP7 rule deck.
- **Device models:** BSIM-CMG via OpenVAF/OSDI in ngspice; gm/ID tables via GmIDVisualizer.
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
