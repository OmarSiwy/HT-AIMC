# Required tooling

Tools and features AnalogIOC still needs. Each section says what we want and why. Bugs in
tools that already work, with their workarounds, are listed in
[`analog/docs/TOOL_ISSUES.md`](analog/docs/TOOL_ISSUES.md).

| # | Gap | Blocks | Owner |
|---|---|---|---|
| 1 | cktImg: land the hierarchy/SVG branch in the env | block diagrams, top-level schematics | cktImg, EDA-Packaged, `.flows/tools` |
| 2 | SpiceRack: ESPice / EGSpice backends | Verilog-A models with events, without the OpenVAF detour | SpiceRack |
| 3 | GmIDVisualizer: export cgg (for `gmid.ft`) | `gating_value.py` | GmIDVisualizer |
| 4 | ASAP7 as the only PDK (after the sky130 design is complete) | the port | several |

## 1. cktImg: land the hierarchy/SVG branch

**Done on branch `analogioc/hierarchy-render`** (OmarSiwy/cktImg): `X` subcircuit instances
are placed as `block:<name>` boxes, there is headless `--svg` output, and the MOS bulk net
is a `bulk` field.

**Still needed:**
- **Engine bugs:** layout time blows up when many blocks share a net, and the strongarm
  latch's `outp`/`outn` come out in disconnected pieces. Both are being fixed; the branch
  is pushed once they pass.
- **EDA-Packaged:** bump the cktImg pin from `1cbffa9` to the pushed branch.
- **`.flows/tools/cktimg_to_xschem.py` and the manifest:**
  - read `devices[].bulk`
  - accept named rails (`_vdd9`)
  - add `ipin`/`opin` and `block:<name>` (or `box`) classes
  - retune `units.scale` for the new grid
  - drop `.pdk` from `cktimg_sky130.zon`
  - treat several rail/port symbols on one net as one node
- **Grouping hints** (keep a diff pair or current mirror together in placement): not started.

## 2. SpiceRack: ESPice / EGSpice backends

Everything else from this gap is done and pushed (SpiceRack `cdba3b9`): the local fixes
went upstream, `X(**params)`, characterization recipes and `run_corners`.

**Want:** ESPice (ARPice) and EGSpice backends, so Verilog-A golden models compiled by VerA
run with `@(cross)`/`transition()` (OpenVAF -> ngspice has neither). The SpiceRack README
"Not yet a backend" section lists the integration points. EGSpice is blocked: its current
build rejects even a resistor. Also: Spectre still drops `raw_spice`, which needs a
`simulator lang=spice` wrapper and a Spectre install to test.

## 3. GmIDVisualizer: export cgg

**Done (2026-10-04):** GmIDVisualizer is packaged in EDA-Packaged (`gmidvisualizer`),
included in `Analog.nix`, and `GMID_LIB` is exported. The PMOS `abs()` and relative
`model_file` fixes are upstream (`OmarSiwy/GmIDVisualizer` `fab7970`).

**Still missing:** `analog/docs/gmid.py:ft()` raises `NotImplementedError` because the
LUTs carry no gate capacitance, so `scripts/compiler/metrics/gating_value.py` stops there.

**Want:** GmIDVisualizer also sweeps `cgg` (ngspice `@m[cgg]`, or `cgs + cgd + cgb`) into
the LUT, so `ft = gm / (2π·cgg)` can be interpolated like `J_D`.

## 4. Port to ASAP7 (after sky130 is finished)

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
