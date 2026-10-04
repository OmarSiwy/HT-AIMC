# PDK, corners, Verilog-A, external netlists

Verified against SpiceRack source (`src/python.rs`, `src/codegen/*`,
`python/spicerack/testbenches/analysis.py`) at e67e52f.

## PDK model libraries

```python
import os, spicerack as ps
lib = ps.ModelLibrary(f"{os.environ['PDK_ROOT']}/{os.environ['PDK']}/libs.tech/ngspice/sky130.lib.spice",
                      corner="tt")
tb = ps.Testbench(dut); tb.use_pdk(lib)
```

* `ModelLibrary(path, corner=None, setup_includes=None, **backend_paths)` —
  `backend_paths` maps a backend to its own file, e.g. `spectre="/pdk/x.scs"`.
* `corner` is passed through verbatim as the lib section. No tt/ss/ff table exists; the
  names are the PDK's own. sky130A `sky130.lib.spice`: `tt sf ff ss fs ll hh hl lh`,
  `*_mm`, `mc`. gf180mcuD `sm141064.ngspice`: `typical ff ss fs sf statistical`.
* ngspice/ltspice emit `.lib <path> <corner>` (`.include` with no corner);
  spectre/vacask emit `include "<path>" section=<corner>`.
* `use_pdk` **appends** — each call adds another library.
* `Testbench` has no `lib`/`include`; put them on the DUT. A `.lib`, `.include` or
  `osdi` on a *child* subcircuit (added with `add_subcircuit`) is dropped.
* **Nothing reads PDK specs** (VDD, Lmin, Vth, device params). A spec reader is plain
  Python you write against `$PDK_ROOT/$PDK`.

## Corners

```python
from spicerack.testbenches import CornerCase, corner_netlists, evaluate_corners
L = lambda s: ps.ModelLibrary(LIB, corner=s)
corners = [CornerCase("ss_125", temperature=125, model_libraries=[L("ss")]),
           CornerCase("ff_m40", temperature=-40, model_libraries=[L("ff")])]
decks = corner_netlists(make_tb, corners)                    # {name: deck}
summary = evaluate_corners(make_tb, corners, rules, extract)  # YieldSummary
```

* `CornerCase(name, backend=None, temperature=None, nominal_temperature=None,
  parameters={}, model_libraries=())` — frozen; `parameters` emits `.param k=v`.
* `make_tb` takes **no arguments** and is called once per corner — build the whole
  bench fresh inside it, including `use_pdk`, or libraries pile up.
* `evaluate_corners(factory, corners, rules, metric_extractor, backend="ngspice",
  runner=None)`: the extractor gets `runner(bench)` if given, else the bench — so the
  extractor must run the simulation itself.

## PDK devices with parameters

sky130 FETs/passives are subcircuits in the ngspice lib, so they need `X` lines with
`W=`/`L=` — but `X()` takes no parameters and `M()` emits an `M` card sky130 cannot
resolve. Emit them with `raw_spice` (one helper, e.g. `analog/common/devices.py:fet`).
Cards differ per PDK — sky130 FETs are `X` subckts with W/L in plain µm (its
`all.spice` sets `.option scale=1.0u`); gf180 FETs are `X` wrappers (`fets_mm`) with
metre `w=`/`l=`, its MIM caps take `c_width`/`c_length` and resistors
`r_width`/`r_length`. Keep that in declared per-PDK card templates
(`analog/docs/pdk_specs.py`), never in circuit code.

## Monte Carlo

* `MonteCarloPlan(backend="spectre", samples=100, distributions={},
  spectre_inner="tran1", spectre_inner_type="tran", seed=None)` is **Spectre only**
  (any other backend raises), and `distributions` is never read. Set `spectre_inner` /
  `spectre_inner_type` to an analysis you actually queued.
* `evaluate_monte_carlo_file(path, rules, backend="auto", names=None)` only parses
  existing result files (csv/tsv/log/.mt0/Spectre mcdata/`.measure` blocks).
* **ngspice route:** no API. Load local mismatch and run a Python loop of N fresh benches
  with `tb.options(seed=i)` — verified on sky130: different seeds flip a comparator's
  decision at 0 V input. Score each run with `validate_metrics` or plain asserts.
  Mismatch is switched on differently per PDK (sky130: `tt_mm` lib section; gf180:
  `.param sw_stat_mismatch=1` with the corner section, which loads `fets_mm`), so go
  through `get_pdk().model_library(pdk.typical + pdk.mismatch_suffix)`, which writes the
  right wrapper for any declared PDK.

## Verilog-A devices (OpenVAF / OSDI)

```python
dut = ps.Subcircuit("amp_va", ["inp", "inn", "out"])
dut.veriloga("amp.va")                     # runs `openvaf amp.va -o amp.osdi`, loads it
dut.raw_spice(".model ampmod amp gain=1e4")
dut.raw_spice("N1 inp inn out ampmod")
```

* `veriloga(src_or_path)` compiles with **OpenVAF** (skips if `.osdi` is newer) and
  returns the `.osdi` path. `osdi(path)` loads a prebuilt one; `ps.compile_veriloga(src)`
  compiles without loading.
* No device method for VA instances — use an `N` line via `raw_spice`.
* Per backend: ngspice `.control / pre_osdi / .endc`; vacask `load "<p>"` (and needs
  VACASK instance syntax in `raw_spice`); spectre gets `ahdl_include` but **drops all
  `raw_spice`**; ltspice drops OSDI silently.
* This is not the VerA/ESPice path — see the `vera` skill.
* `verilog(...)` on a `Subcircuit` is dropped from Testbench decks; it works only on a
  flat `Circuit`.

## External netlist as DUT (post-layout)

```python
top = ps.Subcircuit("tb_top"); top.include("/abs/path/block_pex.spice")
top.X("xdut", "block", "vdd", "0", "inp", "out")   # X is fully positional
tb = ps.Testbench(top)
```

## Printing a bare `.subckt` (for Philis, cktImg)

No API returns just the subckt. The testbench deck **flattens** the DUT (no wrapper).
Wrap it in a `Circuit` and slice:

```python
c = ps.Circuit("x"); c.subcircuit(dut); deck = str(c)
body = deck[deck.index(".subckt"): deck.index("\n", deck.index(".ends"))]
```

Parameters come out as `PARAMS:` on the `.subckt` line.
