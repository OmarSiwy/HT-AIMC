---
name: analog-netlist-first
description: Author analog circuits as SPICE netlists with SpiceRack, turn them into editable xschem schematics with cktImg, and simulate them. Use when working in analog/<block>/ or .flows/analog/, writing or converting a SPICE deck, generating a schematic from a netlist, or asked about cktimg-json / cktimg_to_xschem.py / xschem_sky130.json / spicerack / DesignBench.
---

# Netlist-first analog design

The template's original analog flow starts in the xschem GUI and netlists downward. This
one runs the other way: **the SPICE netlist is the source of truth**, and the schematic and
simulation are both derived from it. Both flows work; neither touches the other's targets.

Everything hangs off one artifact:

```
SpiceRack (spicerack)         <- author the circuit + testbench here
        |
   netlist/<name>.spice       <- the interchange format
   +----+---------------+
   |    |               |
cktImg  ngspice     Philis (make pnr -- see section 4)
   |    corners/MC      |
schematics/<name>.sch   GDS
```

Pick this flow when the circuit is easier to *write* than to *draw* -- which is almost
always true when an LLM is producing it.

## 1. Write the deck (SpiceRack)

SpiceRack (formerly DeSpice / PySpice, module `pyspice_rs`) is a Rust-backed Python
library, imported as `spicerack`. The nix shell puts it on `PYTHONPATH` already; check
with `python -c 'import spicerack'`. Old scripts need only the import renamed -- the
`Circuit` API and `unit` module are unchanged.

Put scripts in `analog/<block>/netlist/*.py`. **The contract is one line: the script prints a
SPICE deck to stdout.** That holds for a plain circuit and for a generated testbench
alike, which is why `make netlist` does not care which one you wrote.

```python
# analog/<block>/netlist/divider.py
import spicerack as ps
from spicerack.unit import u_V, u_kOhm

circuit = ps.Circuit("divider")
circuit.V(name="in", positive="vin", negative=circuit.gnd, value=10 @ u_V)
circuit.R(name="top", positive="vin", negative="vout", value=2 @ u_kOhm)
circuit.R(name="bot", positive="vout", negative=circuit.gnd, value=1 @ u_kOhm)

print(circuit)          # <- the deck. This is the whole interface.
```

Then:

```bash
cd analog/<block>/build/schematic
make netlist            # every .py in analog/<block>/netlist/ -> a matching .spice
```

To simulate directly, skip the file and use the backend from Python:

```python
sim = circuit.simulator(simulator="ngspice")
print(sim.operating_point()["vout"])
```

Backends: `ngspice`, `xyce`, `ltspice`, `spectre`, `vacask` -- whichever is installed.
`ngspice` is in the nix shell.

### Prebuilt testbenches

`spicerack.testbenches` ships with the package (it used to be a separate top-level
`testbenches` that the build never installed):

```python
from spicerack.testbenches import amplifier_voltage_gain, validate_metrics
```

It covers the common analog blocks, so an LLM does not have to reinvent a gain
measurement. Each returns a `DesignBench` with a `.netlist(backend)`
method:

`amplifier_voltage_gain`, `amplifier_current_gain`, `amplifier_transimpedance`,
`charge_amplifier`, `dac_static_linearity`, `adc_ramp`, `switch_characterization`,
`mux_routing`, `demux_routing`, `sample_hold`, `pll_lock`, `bandgap_reference`,
`bandgap_tempco`.

Plus the validation layer: `MetricSpec` / `extract_metrics` to pull numbers out of a
result, `ValidationRule` / `validate_metrics` to assert on them, and `CornerCase` /
`MonteCarloPlan` with `corner_netlists` / `monte_carlo_netlist` for spread, and
`evaluate_corners` / `evaluate_monte_carlo_file` to score them.

`examples/` in the SpiceRack repo is ordered from trivial to advanced; example 22 is the
testbench tour.

## 2. Netlist -> schematic (cktImg)

```bash
cd analog/<block>/build/schematic
make import NETLIST=divider         # netlist/divider.spice -> schematics/divider.sch + docs/divider.svg
make schematic TOP_SCHEMATIC=divider   # open it
```

`make import` runs `.flows/tools/cktimg_to_xschem.py`, which runs cktImg's place-and-route
(`cktimg-json --svg`) and converts the placed geometry to an xschem `.sch` using **real sky130
symbols**; the SVG is cktImg's own drawing, for the block's docs. A deck of only `.subckt`
definitions draws its last one. The result opens, edits, and netlists back: every block
with a netlist (strongarm, cmos_switch, ota, pwm_driver, rstring_ladder, write_dac,
gain_cell_array, async_ctrl, weight_tile) was netlisted back with xschem and matched its
deck device by device and pin by pin, with W/L.

cktImg also ships `cktimg-xschem`. It is not used here: it maps to xschem's generic
`nmos4.sym`/`res.sym` with a built-in table (no sky130 symbols, no manifest), and drops
subcircuit instances to bare labels, so an `X` block vanishes from the netlist.

Three files, each owning one thing:

| File | Owns |
|------|------|
| `.flows/tools/xschem_sky130.json` | The symbol mapping: a cktImg **target manifest** (`--target`) |
| `.flows/tools/cktimg_sky130.zon` | cktImg's config (`--config`): strict geometry |
| `.flows/tools/cktimg_to_xschem.py` | xschem geometry: orientation, stubs, labels, block symbols, the self-check |

### The manifest: adding or changing a symbol

`xschem_sky130.json` follows cktImg's `docs/TARGETS.md` schema. Keys of `classes` are
cktImg class names; `sym` is the xschem symbol path. Everything the script needs rides in
the class's `style`, which cktImg passes through untouched:

```json
"nmos": {
  "sym": "sky130_fd_pr/{model}.sym",
  "style": {
    "pin_xy": [[20, -30], [-20, 0], [20, 30]],
    "attrs": "name={ref} model={model} W={w} L={l}",
    "model": "nfet_01v8", "w": "1", "l": "0.15",
    "bulk": { "xy": [20, 0], "net": "0" }
  }
}
```

* `pin_xy` -- the centre of each `B 5 x0 y0 x1 y1` pin box in the `.sym` file, in the
  manifest's pin order (catalog order unless the class sets `pins`), which must also be
  the symbol's netlist order (the order of its `B 5` lines).
* `sym` and `attrs` are Python format strings over `name`, `ref` (name minus a leading
  `x`, since sky130 symbols add their own `X`), `value`, `net` (first pin's net), `cell`
  (the class minus `block:`) and -- for a class whose style has `model` --
  `model`/`w`/`l`, read from the card (cktImg's `value`), falling back to the style's
  defaults. A card whose first word is a number (`R1 a b 2k`) keeps the default model.
* `bulk` -- where to label the device's extra node (cktImg's `devices[].bulk`: a MOS body,
  a `res_high_po` substrate). `net` is the fallback when the card has none; without it
  nothing is labelled.
* `rail: true` -- a label symbol (`vdd`/`gnd`/`ipin`/`opin`); its net is not labelled twice.
* `unmapped.mode = box` -- every other class, in practice `block:<subckt>` (an `X` of a
  `.subckt`). The script draws a box symbol with the instance's ports where cktImg put
  them and embeds it in the `.sch` (`embed=true`), so nothing is written to `symbols/`.
  It netlists as `<name> <ports> <subckt>`, `type=primitive`, so xschem does not look
  for the child's schematic.

cktImg validates class and terminal names, so a typo fails the run instead of miswiring.
To find the classes a deck needs, run `cktimg-json deck.spice` and read the `class` fields.

### What it handles, and why you should care

* **Net names survive.** Every net gets a label. Without one, xschem renames unlabelled
  nodes `net1`, `net2`, ... and name-based LVS against your source deck silently breaks.
* **MOSFETs and passives match the deck.** The model (so `_lvt`/`_hvt`/`res_high_po_*`
  get their own sky130 symbol), W/L and the bulk net come from cktImg's `value` and `bulk`.
* **Symbol geometry is reconciled automatically.** cktImg's MOSFET and sky130's are
  different shapes. The script picks whichever of xschem's 8 orientations fits best and
  bridges any remaining gap with a short stub wire.
* **Router shorts are routed around.** cktImg sometimes runs a wire across another net's
  pin or wire end (seen on rstring_ladder, write_dac, gain_cell_array, weight_tile), which
  xschem would short. Such a net loses its wires and gets a label on each of its pins
  instead; the run prints `note: cktImg routed <nets> across another net`.
* **It self-checks.** Every run asserts each net comes out as one node and no two nets
  share one, modelling xschem's real rule (a pin, label or wire end on a wire joins it;
  same-named labels and rail/port symbols are one node). A failure aborts rather than
  writing a plausible-looking broken schematic.

### The one knob

`units.scale` in the manifest converts cktImg's grid to xschem units (1.5: cktImg puts
MOS/R/C pins 20 from the centre, sky130 30). cktImg passes it through without applying
it. Override per run:

```bash
make import NETLIST=divider SCALE=2
```

**Tune it by eye with the schematic open.** Too small and symbols overlap; too large and
the routing sprawls. It only affects looks, never connectivity.

### Limits

* Mapped classes: `nmos`/`pmos`/`nfet`/`pfet`, `res`, `cap`, `vsource`, the rails and
  ports. Anything else becomes a generated box -- add it to the manifest for a real symbol.
* A plain-valued `R`/`C` (`2k`, `1p`) becomes `res_generic_m1`/`cap_mim_m3_1` with the
  style's W/L; the value is not kept.
* Nets joined by labels (see above) read worse than wired ones: the fix is in cktImg's
  router, not here.
* `make clean` deletes `analog/<block>/netlist/*.spice`. That is correct for generated decks --
  but a **hand-written `.spice` with no `.py` beside it will be lost.** Keep hand decks
  elsewhere or give them a generator.

### Why `cktimg_sky130.zon` sets `symbol_geometry = .err`

xschem connects by geometry -- a wire touching a pin *is* a connection -- which is exactly
the host cktImg's lint rule says `.err` is for. At the default `.warn`, cktImg does not
spread margin-band feedback devices that share a centre, so two of them can land on the
same point.

## 3. Direct tool use

Bypass make when you need to:

```bash
T=.flows/tools
cktimg-json deck.spice                                  # raw geometry, to stdout
cktimg-json --config $T/cktimg_sky130.zon --target $T/xschem_sky130.json --svg out.svg deck.spice
python3 $T/cktimg_to_xschem.py deck.spice out.sch [--svg out.svg] [--scale 2] [--config F] [--target F]
xschem -x -q -n -s -o outdir out.sch                    # netlist it back (run beside xschemrc)
```

`lint.zon` also tunes cktImg's placement and routing (`abut_gap`, `track_w`, `refine`,
...). Unrecognized keys are reported, not fatal. Router cost weights are deliberately not
configurable -- see cktImg's `ALGORITHM.md`.

## 4. Philis (P&R to GDS)

`make -C analog/<block>/build/layout pnr NETLIST=<name>` → `output/pnr/`. Deck rules,
outputs and iteration knobs: the `philis` skill.

## Gotchas

* **Everything runs inside the nix shell.** `./env.sh` first; the Makefiles hard-fail
  without `IN_NIX_SHELL`.
* **xschem is a GUI.** `make schematic` now fails loudly with no `DISPLAY`/`WAYLAND_DISPLAY`
  instead of appearing to succeed. Over SSH use `ssh -X`; under WSL you need WSLg or an X
  server.
* **The PDK path is version-independent.** `xschemrc` resolves through `$PDK_ROOT/$PDK`,
  the symlink `volare enable` keeps current. Do not reintroduce a hardcoded version hash --
  a stale one makes xschem *core dump* on startup, which is exactly the failure this
  replaced.
