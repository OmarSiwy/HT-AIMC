# AGENTS.md

Guide for agents working in **AnalogIOC**, an analog in-memory-compute (IMC)
transformer accelerator. Read this before adding anything.

**Target process: ASAP7** (7 nm FinFET, predictive). The existing blocks were designed and
measured on sky130; treat that data as the calibrated anchor and port it. New work, scoring
and comparisons are at ASAP7 (`REQUIRED_TOOLING.md` §3 lists what the port needs).

Scope: one chip, the IMC MVM core. Transformer attention is an *application*: its
projections run on the tiles, while the KV cache, softmax and A·V run on the digital
rail (`docs/src/content/Project/APPLICATION_ATTENTION.md`). Don't add analog attention
blocks.

`docs/src/content/Project/CONTRACT.md` is the authoritative spec. Read it first.
`docs/src/content/Project/STATUS.md` is the running log: append to it, never rewrite it.

## Layout

```
AnalogIOC/
├── AGENTS.md                # this file
├── REQUIRED_TOOLING.md      # tools/features we need but don't have yet
├── env.sh                   # environment entry point (see "Environment")
├── analog/                  # one dir per analog block, see analog/README.md
│   ├── <block>/             # netlist/ va/ test/ docs/ schematics/ layout/ build/ output/
│   ├── common/              # shared python: bench, corners, devices, pex
│   ├── docs/                # system architecture, specs.py, gm/Id tables, PDK char
│   └── library/             # submodule: UW-ASIC/AnalogLibrary, components shared across projects
├── digital/imc_driver/      # tile-array controller RTL (src/), iverilog regression (test/)
├── digital/sysreference/    # digital systolic baseline (RTL, bit-exact regression)
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

- `.flows/env/Analog.nix`: ESPice (the simulator), VerA, SpiceRack (on `PYTHONPATH`),
  xschem, klayout, magic, netgen (VLSI, from the flake), cktImg (`cktimg-json`), Philis,
  GmIDVisualizer (`GMID_LIB`), and a Rust toolchain + protobuf for substrate2 layout
  generators. No ngspice and no OpenVAF: golden models go VerA -> ESPice.
- `.flows/env/Digital.nix`: yosys, verilator, iverilog, gtkwave, cocotb, openroad.
  LibreLane comes from its own flake in `shell.nix` and is used as-is.
- The shell hook sets `PDK=sky130A` (unless `PDK` is already set), `PDK_ROOT=~/.ciel`, enables the pinned
  PDK with ciel (the same store LibreLane uses), creates `.venv/`, and prints which tools resolved.
- **ASAP7** (the target process) is not under `PDK_ROOT`: `Analog.nix` exports
  `ASAP7_ROOT` (EDA-Packaged `asap7`). It holds `models/espice/asap7.lib` (BSIM-CMG via VerA,
  sections tt/ff/ss), `models/ngspice/` + `models/osdi/bsimcmg.osdi` (reference only),
  `klayout/asap7.drc` (open DRC), the layer maps and the DRM. Select it with
  `PDK=asap7 ./env.sh analog` (or `PDK=asap7` per command; `get_pdk("asap7")` in python).
  Devices are `M<name> d g s b nmos_rvt L=0.021u NFIN=<fins>`; use `devices.fet`, which
  turns W into fins. Smoke check: `python3 analog/docs/asap7_smoke.py`.

To add a tool, add it to `Analog.nix` or `Digital.nix`. If nixpkgs does not
carry it, add it to EDA-Packaged.

For one-off commands outside the full shell, use
`nix-shell -p 'python3.withPackages(p:[p.numpy p.scipy])' --run '...'` or
`nix-shell -p iverilog yosys --run '...'`.

## Dependency skills

Each tool has a skill in `.claude/skills/`. Load the skill before writing the
first file that uses its tool.

| Tool | Skill | Upstream | Use for |
|---|---|---|---|
| **cktImg** | [`analog-netlist-first`](.claude/skills/analog-netlist-first/SKILL.md) | via `EDA-Packaged` | SPICE netlist -> placed schematic (`cktimg-json`, `.flows/tools/cktimg_to_xschem.py`) |
| **SpiceRack** | [`spicerack`](.claude/skills/spicerack/SKILL.md) | [OmarSiwy/SpiceRack](https://github.com/OmarSiwy/SpiceRack) (`skills/spicerack`) | Netlists, testbenches, metric extraction; this repo uses backend `espice` |
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
| Reusable component other projects will use (OTA, comparator, DAC, LDO, ...) | `analog/library/<Module>/`, following `analog/library/ADDING_MODULE.md` |
| Shared analog python (this repo only) | `analog/common/` |
| System specs / design math | `analog/docs/specs.py`, `analog/docs/architecture.md` |
| RTL / digital tbs | `digital/imc_driver/src/`, `digital/imc_driver/test/` |
| Compiler, metrics campaigns | `scripts/compiler/`, `scripts/compiler/metrics/` |
| Golden models | `scripts/golden/` |
| Test weights | `scripts/models/` (gitignored, never committed) |
| Research / design docs | `docs/src/content/Project/*.md` (plain markdown, shows up on the site automatically) |
| Tool or env dependency | `.flows/env/Analog.nix` / `Digital.nix` |
| Missing tool / feature request | `REQUIRED_TOOLING.md`; bugs in existing tools go in `analog/docs/TOOL_ISSUES.md` |

`analog/library/` is a git submodule
([UW-ASIC/AnalogLibrary](https://github.com/UW-ASIC/AnalogLibrary)). Put a component
there when other projects will reuse it, and keep blocks specific to AnalogIOC in
`analog/<block>/`. Commit changes inside the submodule and push them to its own repo,
then commit the updated submodule pointer here. After cloning, run
`git submodule update --init`.

## Running tests

```sh
# python suites
python3 scripts/golden/test_golden.py
python3 scripts/compiler/test_compile.py     # needs scripts/models/smollm2-135m-q8_0.gguf
python3 scripts/compiler/test_formats.py
python3 scripts/compiler/test_lattice.py
python3 scripts/compiler/test_dps.py

# digital: driver and systolic baseline regressions (iverilog)
make -C digital/imc_driver test
make -C digital/sysreference test

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
- Theory references: `~/Documents/Notes/OmarSiwy.github.io/Notes/Circuit Design/`
  (gm/Id sizing, converters, the Analog Compute paper). Check there before inventing anything.

## Local-only docs

Some working docs are kept out of git and exist only in the original checkout
(`~/Documents/Projects/Trial/ResearchBoutros`), not in clones:

- `docs/src/content/Project/local/`: earlier research reports
- `docs/src/content/Project/ArchResearch/digest/`: digests of the Circuit Design notes and
  of this repo's history (`_slices.json` lists the note slices)
- `docs/src/content/Project/ArchResearch/lit/`: surveys for the architecture search

Read them when relevant. Don't force-add them; put new local-only docs in one of these
directories.
