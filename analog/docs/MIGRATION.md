# AnalogIOC → ResearchBoutros migration ledger

Source: `~/Documents/Projects/Research` working tree as of 2026-09-11 (last edit),
uncommitted research included; source repo left untouched. Each analog block goes
through the full `analog-design-flow` ladder. Status column: `—` not started,
`wip`, or the highest rung passed (`sch`, `va`, `pnr`, `pex`, `corners`, `mc`).

## Shared foundation (done)

| New | From | Check |
|-----|------|-------|
| `analog/docs/pdk_specs.py` | `library/pdks/*.py` (process fields only) | `python3 analog/docs/pdk_specs.py` |
| `analog/docs/gmid.py` + `gmid_tables/` | `sizing/lookup.py` + `gen_tables.py` → GmIDVisualizer | self-check vs AnalogIOC J_D within 2% |
| `analog/docs/specs.py` | `schematics/specs.py`; caps/delay → `_DESIGN_DEFAULT` + per-PDK overrides; OTA L in Lmin units; uncalibrated PDKs fall back to sky130 `_CAL` with a warning | self-check PASS on sky130 (identical but OTA W ±1%, decap area −3% from measured MIM 2.07 fF/µm²) and gf180 |
| `analog/common/devices.py` | `PDKConfig.mos()` | — |
| `analog/common/bench.py` | `library/testbenches/base.py` (ngspice batch → SpiceRack, `$DUT`) | strongarm |
| `analog/common/corners.py` | `parse_rigor` | strongarm |
| `analog/common/pex.py` | new (Philis `extracted_pex.spice` → simulatable) | strongarm |
| `analog/docs/pdk_char.py` + `pdk_char/*.json` | new: measured Vth/uCox/SS/MIM/poly R+tc/t_inv per PDK | sky130, gf180mcu |
| `analog/docs/pdk_models/` | new: per-PDK/corner model wrappers (incl. mismatch) from `pdk_specs` | sky130, gf180mcu |
| `analog/docs/mismatch.py` + `mismatch_cache/` | new: measured sigma(VGS) per (device, W, L, I) — Pelgrom fails at short L on sky130 | strongarm |
| `analog/common/hotswap.py` | new: every block + gmid + specs re-derive on every installed PDK | 7/8 wave-1 blocks PASS on gf180 |

Fixed on the way: `specs.cal()` falls back to `pdk.cal_proj`, so projection PDKs evaluate
without the compiler's `specs._CAL[...] = cal_proj` patching (AnalogIOC raised KeyError).
Carried over unchanged: `gmid` lookups use the *active* PDK's tables, so projection PDKs
size the OTA with sky130 gm/ID.

Removed on purpose: `PDKConfig.sizing` (each block derives W/L from gm/ID in its
netlist script), `library/pdks/base.py ACTIVE_PDK` (→ `$PDK`), `ft()` (GmIDVisualizer
has no cgg; only `tb_imc_log_sizing.py` used it), substrate2 layout (→ Philis).

Tool bugs found on the way: `analog/docs/TOOL_ISSUES.md`.

## Blocks

Leaves first; a block starts once everything in its DEPENDS reached `sch`.

| Block | DEPENDS | AnalogIOC source | Testbenches in | Status |
|-------|---------|----------------|----------------|--------|
| strongarm | — | components/strongarm | tb_strongarm (+ new tb_strongarm_mc) | mc — all rungs, layout = substrate2 (DRC 0 / LVS match); Philis layouts fail independent DRC |
| cmos_switch | — | library/cmos_switch.py | none (new: Ron, charge injection) | mc (all rungs; Philis DRC 0/LVS match, ERC flags bulk-only rails) |
| ota | — | library/ota.py (ota_spice, bias_spice) | tb_ota, tb_ota_swing, tb_o_charge | wip |
| pwm_driver | — | components/pwm_driver | tb_pwm_driver | mc (all rungs; Philis DRC 2 LI.3, ~10 h/seed) |
| async_ctrl | — | components/async_ctrl | tb_async_ctrl | corners+mc pass; Philis running (cap-free deck workaround) |
| gain_cell_array | cmos_switch | components/gain_cell_array | tb_gain_cell | — |
| write_dac | cmos_switch | components/write_dac | tb_write_dac | — |
| rstring_ladder | cmos_switch | components/rstring_ladder | tb_rstring | — |
| weight_tile | cmos_switch pwm_driver | components/weight_tile | tb_weight_tile, tb_cascade, tb_csnr, diag_countinl, a10_closure_driver | — |
| integrator_conv | cmos_switch ota pwm_driver strongarm | components/integrator_conv (AnalogIOC subckt `int_conv` → renamed `integrator_conv`), testbenches/_conv_common.py | tb_integrator_conv, diag_fine15, diag_pingpong, diag_a8b, diag_cascade_gain, diag_multibank, diag_park | — |
| lora_sidecar | cmos_switch gain_cell_array ota write_dac | components/lora_sidecar (+ the sidecar half of top/tb_training_step) | tb_lora_sidecar, tb_lora_rho, tb_lora_update (+ new tb_lora_sidecar_mc) | corners (ESPice; mc not run) — redesigned to resolve INTERFACE Q6 (signed x/A/B, both windows, rho measured); no layout this phase |
| chip_supertile | integrator_conv | top/chip_supertile.py | tb_supertile | — |
| analogioc | async_ctrl gain_cell_array integrator_conv lora_sidecar ota rstring_ladder weight_tile write_dac | top/analogioc_top.py, top/harness.py, top/diag_op.py | tb_tile_mvm, tb_attention_e2e, tb_training_step, tb_ffn_e2e, tb_audit, tb_eventrate, tb_adaptive_range, test_gain_servo, diag_a8 | — |

`library/cap_array.py` is referenced by nothing but its own `__main__` — not migrated.

## Not blocks

| What | Where | Status |
|------|-------|--------|
| Research studies: `tb_imc_*`, `imc_*`, `tb_charge_average_research`, `tb_cap_mismatch`, `tb_lut_exp`, `test_spice_io`, `*.patch` | deleted 2026-10-04 (was a frozen archive at `analog/analogioc/research/`); write-ups remain in `docs/src/content/Project/` | removed |
| digital/analogioc (src, test, Makefile, synth.ys) | verbatim | 10/10 tbs + synth PASS |
| scripts/golden/ | verbatim | test_golden PASS |
| scripts/compiler/ | verbatim, then import paths → `analog/docs` (`specs`, `pdk_specs`) | — |
| docs/src/content/Project/ | verbatim; system architecture distilled into `analog/docs/architecture.md` (§6 lists 12 contradictions between AnalogIOC docs) | done |
| scripts/models/*.gguf | hard-linked, gitignored | — |

## Open follow-ups

- **OTA headroom:** ota reports NMOS-input headroom failures at VCM = 0.9 V on slow-N/cold
  corners; may need a `specs.OTA_COORDS` change (awaiting numbers).
- **gf180 poly-resistor mismatch unknown:** `pdk_specs.GF180MCU.res_poly_a_r` is 0.0 — the
  PDK files state no local resistor mismatch (sky130's is declared from `body_pelgrom`) and
  neither PDK varies it in ngspice MC. write_dac skips that constraint on gf180 (warns).
- **Philis budget raised (user):** 100 iterations up to 30 FETs, 40 above (Philis converges
  with more iterations). Finished blocks with residual DRC/advanced issues are re-running.
- **Layout route is now hybrid (user):** Philis stays the quick-feedback P&R for leaf /
  irregular blocks; substrate2 generators (`analog/common/layout/`, per-block
  `analog/<block>/layout/<block>.rs`, `make gen*`, `DUT=pex PEX_FROM=gen`) take arrays
  (weight_tile, gain_cell_array, rstring_ladder), taps/guard rings, MIM-heavy / long-L
  cells and top assembly. Ported from AnalogIOC's skeleton crate (Tech trait + L=150 nm
  sky130 tiles only). substrate2 ships sky130 only — gf180 needs its own `Tech` binding.
  Status: layout-infra agent building + proving on cmos_switch and strongarm.
