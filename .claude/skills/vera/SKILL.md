---
name: vera
description: Write, lint and unit-test Verilog-A behavioural models with VerA (`vera`), and simulate them in ESPice (the ARPice repo). Use when writing or debugging a .va model, running `vera`/`espice`, or wiring a Verilog-A golden model into a simulation.
---

# VerA

VerA compiles Verilog-A to **Zig source** — a stateless device (`eval`/`jacobian`/`psd`)
that ESPice compiles into its Newton loop. It does **not** emit `.osdi`. Two routes to a
simulation, pick by simulator:

| Simulator | Route | Compiler |
|---|---|---|
| ngspice / VACASK | SpiceRack `dut.veriloga("model.va")` → `.osdi` | OpenVAF, not VerA |
| ESPice (ARPice) | `.hdl "model.va"` card in the deck | VerA, at ESPice runtime |

**Default to the ngspice route, and write golden models in the OpenVAF subset:**
OpenVAF implements no `@(cross)`/`@(above)`/`@(timer)` events (only `initial_step`/
`final_step`) and no `transition()`. Model switching with `tanh`, delay with an internal
RC node (`ddt`), outputs as Thevenin sources — continuous behaviour every compiler
accepts. Lint every model with `vera --lint` too, so it stays ESPice-ready.

**ESPice route (2026-09-29):** use a source build of ESPice (the ARPice repo) `main`
(`01fa6f93` or later; needs `../Gompute` beside it) via `ESPICE_SRC` — there `.hdl` models
with `@(cross)` and `transition()` simulate correctly. The GitHub/nix ESPice pins a
pre-release VerA (`297e97dc`) whose codegen breaks any non-trivial model (`var h` shadows
`const h`), and its store build cannot cache `.hdl` builds (fix is WIP). Golden models
that must also run on ngspice stay in the OpenVAF subset (continuous).

## Write the model

* **One module per file, file stem = module name.** VerA lowers only one module of a
  multi-module file, and ESPice's build panics on duplicate stems.
* `disciplines.vams` / `constants.vams` are built in; `` `include`` them as usual, no `-I`.
* Supported and verified: `ddt idt idtmod ddx absdelay transition slew laplace_nd
  laplace_zp zi_nd last_crossing limexp`, `@(cross) @(above) @(timer) @(initial_step)
  @(final_step)`, `$bound_step $discontinuity white_noise flicker_noise $table_model`,
  `analog function`, parameter ranges `from [a:b] exclude v`.
* Refused: `@(absdelta(...))` in an analog block (E0513); string range `from {"a","b"}`
  (E0207 — write `from '{"a","b"}'`); keywords as names, e.g. a module `ddx` (E0208).
* Write noise as an assignment, `w = white_noise(...)`; a declaration initializer
  `real w = white_noise(...)` exports no noise source.
* Two instances on the same node pair share one branch — `I(r1.branch(p,n))` reads the
  parallel sum.

## Check it — every edit, in this order

```bash
vera model.va --lint --allow=W0650                         # parse + lower + finiteness
vera model.va --check --contract $VERA_CONTRACT  # type-check generated Zig
vera model.va --run   --contract $VERA_CONTRACT  # self-checking testbench
```

`$VERA_CONTRACT` (exported by the nix shell) = `contract.zig` from the SAME VerA commit
as the binary — else "generated for a different device ABI". VerA is adding it to the
package (`share/vera/contract.zig`); until then set `VERA_SRC` to a VerA checkout. Exit 0 = OK (warnings don't fail), 1 = diagnosed error, 2 = bad flags. `vera --explain
CODE` explains a diagnostic. W0650 (strict float mode) fires on nearly every model and is
about speed — allow it. `--diagnostics=json` for machine parsing.

`--run` executes `//!` header directives: `param bias sweep psweep wave time temp solve
analysis print noise acstim reject exit checks` (unknown ones are refused):

```verilog
//! time 0,1e-5,2e-5,5e-4,1e-3
//! wave V(in) = 0,1,1,1,1
//! solve
//! print none
```

`--run` steps a fixed grid of your `time` points — no truncation-error control, no
breakpoints, **no inserted crossing points, so `@(cross)` events did not fire** (being
fixed upstream: a crossing between grid points must fire at the next point) — and ties
unnamed unknowns to 0 unless `//! solve` is present. It is a unit check for continuous
models, not a transient simulator; real transients go through ngspice or ESPice.

## Simulate in ESPice

```spice
.hdl "amp.va"                 * path relative to the deck; .va only
N1 inp inn out amp gain=1e4   * or: .model ampmod amp gain=1e4 / N1 ... ampmod
```

```bash
espice deck.sp -r out.raw [--format=ascii|csv|...] [--jobs=N]
```

* Instance letter must take a variable node count (`N`, `X`, `U`). `R C L V I D B F H W`
  (2), `Q Z J` (3), `E G S M T O` (4) split nodes from the model at the wrong place.
* ESPice needs `zig` on PATH, its source tree where it was built **and writable** (it
  compiles `.hdl` models into `<src>/.zig-cache/espice-hdl/`, so the nix-store build
  fails `AccessDenied` — build ESPice from a source checkout), and a ReleaseFast build
  (Debug fails `HdlNeedsLlvmHost`). First load compiles, later ones cache.
* From SpiceRack: `deck = tb.netlist("ngspice")`, add the `.hdl` line, **don't** call
  `veriloga()` (ESPice ignores `pre_osdi`), run the CLI, parse the raw file yourself.
  SpiceRack has no ESPice backend.

## Silent-failure traps

* **Misspelled instance parameter → default used**, no error (ESPice drops unknown keys).
* **Too few nodes on an instance → missing ports tied to ground**, no error.
* **Parameter ranges are compile-time only.** `--param tau=-1` is refused (E0361); the
  same value on an ESPice card or a `//! param` runs and gives wrong output. Check ranges
  in the testbench script.
* **`$strobe`/`$display` vanish in device builds** (W0850). Prints show only under `--run`.
* **Runtime `.hdl` errors surface as a bare error name.** Always `vera --lint` first.
* `ln` is the natural-log keyword — not a variable name (E0208).
* OpenVAF's binary may be installed as `openvaf-r`; SpiceRack calls `openvaf` (alias it).
* **ESPice pins an older VerA** (`297e97dc`). A HEAD `vera` can accept what `espice`
  refuses; `zig build vera -- <args>` in the ESPice tree runs the pinned one — use it when
  they disagree.
* ESPice ignores `noise_table` output, correlated-noise weights and nodesets.
