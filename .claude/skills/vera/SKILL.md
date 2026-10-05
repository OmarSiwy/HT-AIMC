---
name: vera
description: Write, lint and unit-test Verilog-A behavioural models with VerA (`vera`), and simulate them in ESPice (the ARPice repo). Use when writing or debugging a .va model, running `vera`/`espice`, or wiring a Verilog-A golden model into a simulation.
---

# VerA

VerA compiles Verilog-A to **Zig source** — a stateless device (`eval`/`jacobian`/`psd`)
that ESPice compiles into its Newton loop. **ESPice is this repo's only simulator** (SpiceRack
backend `espice`, `BACKEND ?= espice` in every block). There is no OSDI and no OpenVAF:
an OSDI card in a deck is an error, and `osdi()` on an ESPice bench raises.

| Use | How |
|---|---|
| golden model in a SpiceRack bench (`DUT=va`) | `top.veriloga("model.va")` → SpiceRack emits `.hdl "model.va"`; ESPice compiles it through VerA at first use (cache `~/.cache/espice`) |
| hand-written deck | `.hdl "model.va"` card, `espice deck.sp -r out.raw` |
| digital sim of a leaf block | `vera model.va --emit-verilog -o model_beh.v` (see below) |

ESPice (EDA-Packaged `espice`) and `vera` share one VerA (1.0.0, `998a3223`), so the
binaries agree. The full Verilog-A subset below works, including `@(cross)` and
`transition()`. Keep models continuous where you can anyway: it simulates faster.

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

`$VERA_CONTRACT` (exported by the nix shell, from the package's `share/vera/contract.zig`)
matches the binary, and `--contract` defaults to the built-in copy anyway. Exit 0 = OK (warnings don't fail), 1 = diagnosed error, 2 = bad flags. `vera --explain
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

`--run` steps a fixed grid of your `time` points, with no truncation-error control and no
breakpoints. `@(cross)` fires at the next grid point after a crossing (W0750 if late). It
ties unnamed unknowns to 0 unless `//! solve` is present. It is a unit check, not a
transient simulator; real transients go through ESPice.

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
* The packaged ESPice runs `.hdl` models straight from the nix store (cache in
  `~/.cache/espice`); no source build or `zig` on PATH needed.
* Internal nodes of a Verilog-A instance read as `v(<instance>#<net>)` (ngspice naming).
* PWL sources longer than 64 points are fine, except with `r=` (refused).

## Behavioural Verilog (`--emit-verilog`)

```bash
vera model.va --emit-verilog -o model_beh.v [--digital-pins a,b|file] [--power-pins] [--vdd=1.8]
```

Same module/ports. Each driven net becomes one bit, with RC-derived rise/fall delays
(overridable `parameter real vera_rise_*`). Mark pins in the model with
`(* vera_pin = "digital"|"analog"|"power"|"ground" *)` and delays with
`(* vera_delay = 2n *)`; both attributes must go on the **`inout`** line (they're silently
ignored on `electrical`). Refused: events/held state, `ddt`/`idt` assigned to variables,
arrays, more than 20 pins + driven nodes. Good for leaf blocks (strongarm, async_ctrl);
the `analogioc` macro's model is hand-written.

## Silent-failure traps

* **Parameter ranges are compile-time only.** `--param tau=-1` is refused (E0361); the
  same value on an ESPice card or a `//! param` runs and gives wrong output. Check ranges
  in the testbench script.
* **`$strobe`/`$display` vanish in device builds** (W0850). Prints show only under `--run`.
* Always `vera --lint` first; it's the fastest place to see a diagnostic.
* `ln` is the natural-log keyword — not a variable name (E0208).
* ESPice ignores `noise_table` output, correlated-noise weights and nodesets.
