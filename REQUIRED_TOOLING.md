# Required tooling

Tools and features AnalogIOC still needs. Each section says what we want and why. Bugs in
tools that already work, with their workarounds, are listed in
[`analog/docs/TOOL_ISSUES.md`](analog/docs/TOOL_ISSUES.md).

| # | Gap | Blocks | Owner |
|---|---|---|---|
| 1 | cktImg: grouping hints | readable schematics of matched structures | cktImg |
| 2 | SpiceRack: EGSpice backend | the successor simulator | SpiceRack, EGSpice |
| 3 | ASAP7 as the only PDK (after the sky130 design is complete) | the port | several |

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
