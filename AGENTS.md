# AGENTS.md

Guide for agents working in **AnalogIOC**, an analog in-memory-compute (IMC)
transformer accelerator on sky130. Read this before adding anything.

`docs/src/content/Project/CONTRACT.md` is the authoritative spec. Read it first.
`docs/src/content/Project/STATUS.md` is the running log: append to it, never rewrite it.

## Layout

```
AnalogIOC/
├── AGENTS.md                # this file
├── env.sh                   # environment entry point (see "Environment")
├── analog/                  # one dir per analog block, see analog/README.md
│   ├── <block>/             # netlist/ va/ test/ docs/ schematics/ layout/ build/ output/
│   ├── common/              # shared python: bench, corners, devices, pex
│   ├── docs/                # system architecture, specs.py, gm/Id tables, PDK char
│   └── library/             # UW-ASIC analog library (ADC, DAC, LDO, OpAmp, TIAs)
├── digital/analogioc/       # RTL (src/), iverilog testbenches (test/), synth.ys
├── scripts/
│   ├── compiler/            # GGUF -> hardware compiler + metrics/ campaigns
│   ├── golden/              # bit-exact reference models
│   └── models/              # test weights (*.gguf), gitignored
├── docs/                    # docs SITE (Vite + Bun), deployed to GitHub Pages
│   └── src/content/
│       ├── Project/         # research docs: spec, status, results, IMC studies (plain .md)
│       └── Template/        # original flow docs: environment, flows, TinyTapeout
├── .claude/skills/          # agent skills for this repo's tools (tracked, do not ignore)
└── .flows/                  # template flow machinery: nix env, tools, DEF templates
```

`.flows/` is no longer the design flow, but parts of it are still in use:
`env.sh` runs `.flows/env/shell.nix`, and the analog block Makefiles read
`.flows/tools/` (cktImg/xschem mapping) and `.flows/def/` (TinyTapeout DEF).
Do not delete it.

## Environment

All tools come from Nix. Do not assume host tools.

```sh
./env.sh            # auto-detects analog+digital -> mixed
./env.sh analog     # or: digital | mixed
```

What `env.sh` does:

1. On macOS it hands off to `.flows/env/mac_shell.sh`. On Linux/WSL it installs Nix if missing.
2. Runs `cachix use omarsiwy`. That binary cache holds cktImg, SpiceRack and VLSI
   netgen. Without it these are compiled locally (Zig, Rust and C builds).
3. Enters `nix-shell .flows/env/shell.nix --argstr type <mode> --extra-experimental-features flakes`.

`shell.nix` pins nixpkgs 25.11 and pulls the custom EDA tools from the flake
**`github:OmarSiwy/EDA-Packaged`** with `builtins.getFlake`. That flake is
why flakes have to be enabled.

- `.flows/env/Analog.nix`: xschem, klayout, magic, ngspice + libngspice, netgen
  (VLSI, from the flake), cktImg (`cktimg-json`), SpiceRack (on `PYTHONPATH`),
  Philis, OpenVAF (as `openvaf`), VerA, and a Rust toolchain + protobuf for
  substrate2 layout generators.
- `.flows/env/Digital.nix`: yosys, verilator, gtkwave, cocotb, openroad, openlane
  (pip). It has no iverilog, so the digital tbs use `nix-shell -p iverilog yosys`.
- The shell hook sets `PDK=sky130A`, `PDK_ROOT=~/.volare`, enables the pinned
  PDK with volare, creates `.venv/`, and prints which tools resolved.

To add a tool, add it to `Analog.nix` or `Digital.nix`. If nixpkgs does not
carry it, add it to EDA-Packaged. ESPice is the exception: it is not in the
store, so set `ESPICE_SRC` to a local ESPice checkout (see the `vera` skill).

For one-off commands outside the full shell, use
`nix-shell -p 'python3.withPackages(p:[p.numpy p.scipy])' --run '...'` or
`nix-shell -p iverilog yosys --run '...'`.

## Dependency skills

Each tool has a skill in `.claude/skills/`. Load the skill before writing the
first file that uses its tool.

| Tool | Skill | Upstream | Use for |
|---|---|---|---|
| **cktImg** | [`analog-netlist-first`](.claude/skills/analog-netlist-first/SKILL.md) | via `EDA-Packaged` | SPICE netlist -> placed schematic (`cktimg-json`, `.flows/tools/cktimg_to_xschem.py`) |
| **SpiceRack** | [`spicerack`](.claude/skills/spicerack/SKILL.md) | [OmarSiwy/SpiceRack](https://github.com/OmarSiwy/SpiceRack) (`skills/spicerack`) | Netlists, testbenches, backends (ngspice/LTspice/VACASK/Spectre), metric extraction |
| **Philis** | [`philis`](.claude/skills/philis/SKILL.md) | [UW-ASIC/Philis](https://github.com/UW-ASIC/Philis) | Automated analog P&R to GDS (`make pnr`). Its DRC/LVS is not signoff: always run `make pnr-verify` |
| **VerA** | [`vera`](.claude/skills/vera/SKILL.md) | [OmarSiwy/VerA](https://github.com/OmarSiwy/VerA), ESPice: [OmarSiwy/ESPice](https://github.com/OmarSiwy/ESPice) | Verilog-A golden models: lint, unit-test, simulate |
| **Substrate2** | none yet; see `analog/<block>/build/layout/Makefile` | [ucb-substrate/substrate2](https://github.com/ucb-substrate/substrate2) | Rust layout generators (`analog/common/layout`), sky130 only |

[`analog-design-flow`](.claude/skills/analog-design-flow/SKILL.md) ties these
together. It covers the per-block process: architecture -> Verilog-A model ->
SpiceRack testbench -> topology -> gm/Id sizing -> Philis layout ->
corners/Monte Carlo. Start any analog block work there.

The `spicerack` skill is a vendored copy with local fixes. When you change it,
upstream the fix and re-copy it.

## Where to add stuff

| What | Where |
|---|---|
| Analog block (netlist, `.va`, tb, docs) | `analog/<block>/`, following `analog-design-flow` |
| Shared analog python | `analog/common/` |
| System specs / design math | `analog/docs/specs.py`, `analog/docs/architecture.md` |
| RTL / digital tbs | `digital/analogioc/src/`, `digital/analogioc/test/` |
| Compiler, metrics campaigns | `scripts/compiler/`, `scripts/compiler/metrics/` |
| Golden models | `scripts/golden/` |
| Test weights | `scripts/models/` (gitignored, never committed) |
| Research / design docs | `docs/src/content/Project/*.md` (plain markdown, shows up on the site automatically) |
| Tool or env dependency | `.flows/env/Analog.nix` / `Digital.nix` |

## Running tests

```sh
# python suites
python3 scripts/golden/test_golden.py
python3 scripts/compiler/test_compile.py     # needs scripts/models/smollm2-135m-q8_0.gguf
python3 scripts/compiler/test_formats.py
python3 scripts/compiler/test_lattice.py
python3 scripts/compiler/test_dps.py

# digital: 10 iverilog tbs + yosys synth (synth needs the volare PDK)
cd digital/analogioc && nix-shell -p iverilog yosys --run 'make test synth'

# docs site
cd docs && bun install && bun run dev
```

No `PYTHONPATH` setup is needed. Every entry point adds its own paths: scripts
add `scripts/` for `compiler.*` / `golden.*` imports, and `ROOT` is always the
repo root.

## Rules

- Build artifacts go in `build/` or `output/`, never committed.
- Every block ships a self-checking testbench that prints PASS/FAIL and asserts numerically.
- Shell scripts stay POSIX.
- Theory references: `~/Documents/Projects/OmarSiwy.github.io/Notes/Circuit Design/`
  (gm/Id sizing, converters, the Analog Compute paper). Check there before inventing anything.
