# Required tooling

Tools and features AnalogIOC still needs. Each section says what we want and why. Bugs in
tools that already work, with their workarounds, are listed in
[`analog/docs/TOOL_ISSUES.md`](analog/docs/TOOL_ISSUES.md).

| # | Gap | Blocks | Owner |
|---|---|---|---|
| 1 | cktImg: grouping hints | readable schematics of matched structures | cktImg |
| 2 | SpiceRack: EGSpice backend | the successor simulator | SpiceRack, EGSpice |
| 3 | ASAP7 as the target PDK: models, pdk_specs, gm/ID, KLayout DRC done; P&R/LVS decks, layout crate, ORFS harden, `m=` open | the port; all new work | GPurify, Philis, substrate2 (ours), ESPice, digital flow |
| 4 | VerA `.v` device in ESPice: > 64 pins (ESPice's per-device cap; VerA allows 256), output-variable ports on part-selects, task-enable panic | wide mixed-signal co-sim (`analog/imc_tile/test/tb_cosim.py` stays small to fit) | VerA (ESPice picks it up) |

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

**Done (2026-10-05):**

- **PDK in the env.** EDA-Packaged `asap7` (`b85d8fb`) is the ASAP7 r1p7 root, exported as
  `$ASAP7_ROOT` by `Analog.nix`. `PDK=asap7 ./env.sh` selects it.
  - From the PDK: the HSPICE BSIM-CMG cards, cdslib layer maps and the DRM.
  - Added by the package:
    - BSIM-CMG 111.0.0 Verilog-A, 4-terminal, module `bsimcmg`;
    - the cards rewritten for it;
    - `models/espice/asap7.lib` (tt/ff/ss);
    - an ngspice lib with `models/osdi/bsimcmg.osdi`;
    - `klayout/asap7.drc`, `.lyp` and `.lyt`.
  - Licences: PDK BSD-3-Clause, BSIM-CMG ECL-2.0, DRC deck BSD-2.
  - Not included: the Calibre decks (asap.asu.edu download only) and the std cells (ORFS vendors them).
- **Device models on ESPice.** VerA compiles BSIM-CMG as a user `.hdl` model with no ESPice
  or VerA change: about 4 min the first time, cached after. `analog/docs/asap7_smoke.py`
  passes:
  - Idsat of all 8 devices is 4–9 % under the published table.
  - The OSDI cross-check with ngspice agrees to 2e-4.
  - Inverter at 0.7 V: 8 ps into 1 fF.

  Numbers are in STATUS 2026-10-05.
- **`pdk_specs.Asap7`.** Fin cards, no MIM (an ideal C card at a 2.0 fF/µm² MOM estimate),
  literature Pelgrom and no `_mm` sections. `devices.fet` handles NFIN/NF. `asap7_proj` is
  kept for scripts/compiler/metrics.
- **gm/ID tables.** `gmid.py` characterises FinFET PDKs in ESPice (`gmid_tables/asap7/`).
- **Open DRC.** `$ASAP7_ROOT/klayout/asap7.drc` comes from ORFS's `asap7.lydrc`, with an S.1
  spacing bug and three typos fixed. It runs clean on std cells apart from the lone-cell
  latch-up tap rule.

**Still needed:**

- **GPurify `asap7.deck`** (owned by the GPurify session). Start from its
  `pdks/generic_finfet.deck`, which already has ASAP7 layers, DRM-named rules and the M1–M9
  connect/resistance stack. Missing:
  - MOS device recognisers for the 8 cards (`nmos_/pmos_{rvt,lvt,slvt,sram}` on the channel,
    with N/PSELECT and the LVT/SLVT/SRAMVT markers), with NFIN as the size, not W;
  - GATE/LISD/LIG/V0 as conductors (gate–LIG–V0–M1, S/D–LISD–V0–M1), with estimated MOL R;
  - an NTAP/PTAP `supply_short` rule;
  - directional and different-net spacing, and tip-to-tip by edge length;
  - non-zero area and fringe caps for PEX (from ORFS `setRC.tcl`/`rcx_patterns.rules`, or
    the MOM estimate in pdk_specs);
  - the name `asap7.deck`.

  Philis needs an `asap7.json` to match.
- **Open LVS.** None exists. Needs the GPurify deck above, or a KLayout LVS script with
  BSIM-CMG device extraction (NFIN from fin count).
- **Layout generators.** substrate2 has no ASAP7 crate. Estimate: 2–4 weeks for one person.
  - Layer enum: 1 day.
  - FinFET MOS tile on the 54 nm gate and 27 nm fin pitch, with gcut, SDT/LISD/LIG/V0 and
    the M1 grid: 1–2 weeks.
  - Tap tile: 2 days.
  - MOM finger cap replacing the MIM tile: 2–3 days.
  - M1–M3 atoll grid at 36 nm: a few days.

  There is no resistor device, so `ResTile` becomes a metal R or goes away. A cheaper start
  is to use the ASAP7 std cells as fixed primitives.
- **Digital flow.** LibreLane 3.0.14 has no ASAP7 platform, and ciel ships none either.
  Harden at ASAP7 with OpenROAD-flow-scripts' `asap7` platform. Selection: `PLATFORM ?= sky130A`
  in each `digital/<m>/build/config.mk`, and `harden` dispatches to `build/librelane` for
  sky130/gf180/ihp or to `build/orfs/Makefile` for asap7. That Makefile runs
  `make -C $ORFS_HOME/flow DESIGN_CONFIG=…`. `macros.py orfs` would write
  `ADDITIONAL_LEFS/LIBS/GDS` and `MACRO_PLACEMENT_TCL` from `macros.toml`. Needs a pinned ORFS
  checkout as `$ORFS_HOME`, e.g. an EDA-Packaged source package; the OpenROAD version should
  match ORFS's pin.
- **ESPice: `m=` on Verilog-A devices.** `M1 … nmos_rvt NFIN=5 m=2` is refused ("module
  'bsimcmg' has no parameter 'm'"). The LRM gives every instance `$mfactor`. Want: `m` scales
  the device's currents, charges and noise as in ngspice, and `$mfactor` reads it.
  Workaround in use: `devices.fet` folds `m` into BSIM-CMG's `NF`, which matches exactly
  (`NFIN=10` = `NFIN=5 NF=2`).
- **Mismatch.** ASAP7 has no statistical models. Wanted: a `tt_mm` section whose per-instance
  `DELVTRAND = agauss(0, a_vt/sqrt(2·W·L))` is redrawn per instance and per seed in ESPice.
  Check whether ESPice redraws instance-parameter expressions per instance (sky130's mismatch
  sections do something similar) before writing it.
- **GmIDVisualizer.** Its ngspice backend writes `W=…u` cards and has no NFIN and no OSDI
  load, so it cannot characterise ASAP7. `gmid.py` does FinFET in ESPice instead. Only needed
  if GmIDVisualizer itself must serve FinFET PDKs: an ESPice backend plus a `nfin` sizing mode.
- **Design port.**
  - Tile calibration at ASAP7: `K_CAL`, `c_ota_self` and `fine_ref_trim`; `cal()` lacks
    `fine_ref_trim` for asap7 and asap7_proj, so `specs.py` asserts.
  - The block netlist scripts call `pdk.fet_card.format(w=…)` directly and must pass `nfin`.
  - The telescopic-cascode OTA does not fit 0.7 V.

**Design changes the port forces:** 0.7 V supply (the telescopic-cascode OTA doesn't fit),
MOM instead of MIM caps, fin-quantized widths and one gate length (stack devices for long L),
and re-measured calibration constants (`K_CAL`, `c_ota_self`, fine trim).

## 4. VerA `.v` device: wide designs

The sky130 `analogioc` co-sim harness this section describes was removed on 2026-10-06
(git history). The limits still apply to `analog/imc_tile/test/tb_cosim.py`, which runs
`digital/imc_driver` as an ESPice `.v` device on configurations small enough to fit them.

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
