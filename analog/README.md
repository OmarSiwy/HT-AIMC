# analog/

| Directory | What |
|---|---|
| [`imc_tile/`](imc_tile) | The chosen IMC tile: Verilog-A models (`va/`), self-checking testbenches (`test/`), block doc (`docs/architecture.md`). The ASAP7 SpiceRack generator goes in `netlist/` |
| [`common/`](common) | Shared Python: bench, corners, `devices.fet` (turns W into ASAP7 fins), PEX, substrate2 layout crate |
| [`docs/`](docs) | ASAP7 characterization (`asap7/`), gm/ID tables, `pdk_specs.py`, system laws (`specs.py`), tool issues |
| [`library/`](library) | Submodule (UW-ASIC/AnalogLibrary): components reused across projects |

New blocks follow the `analog-design-flow` skill: architecture, Verilog-A model, SpiceRack
testbench, topology, gm/ID sizing, layout, corners. The architecture they implement is
[`ARCH_CHOSEN.md`](../docs/src/content/Project/ARCH_CHOSEN.md). The earlier sky130 blocks were
removed on 2026-10-06 and remain in git history.
