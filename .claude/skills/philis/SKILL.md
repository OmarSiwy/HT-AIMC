---
name: philis
description: Automated analog place-and-route to GDS with Philis (`philis run`). Use when running `make pnr`, preparing a deck for Philis, reading signoff.txt/signoff.json, iterating Philis runs for a better layout, or using its extracted_pex.spice.
---

# Philis

SPICE `.subckt` + PDK rule deck → placed, routed GDS with in-loop DRC/LVS/PEX (GPurify).
Quick placement feedback, **not signoff — and its own DRC/LVS numbers are not trustworthy**:
on strongarm Philis reported "DRC 2 / LVS MATCH" while the PDK's klayout deck found 264
violations, magic 648, and netgen LVS failed (floating n-wells: no taps drawn; no pin
labels). Always run the independent checks on a Philis GDS (`make pnr-verify RUN=...`);
for a layout you mean to keep, write a substrate2 generator (`make gen`, see
`analog/common/layout/README.md`).

```bash
philis run block.spice $PHILIS_PDK_DIR/sky130.json -o out/ [--seed N] [--max-iters N] [-v]
philis gds2svg out/block.gds -p $PHILIS_PDK_DIR/sky130.json    # -p default is relative: pass it
```

In this repo: `make -C analog/<block>/build/layout pnr-seeds SEEDS="1 2"`
→ `output/pnr/seed<N>/` (interface file, seed and iteration cap wired in), then
`make ... pex RUN=seed<N>`. One output dir per run; kill only the PIDs you started.
Packaged rule decks: **`sky130.json`, `generic_finfet.json` only** (gf180/ihp live in the
unpackaged `new_skeleton/` rewrite with a different schema).

## Deck requirements

The CLI parses the file text directly — **`.include`/`.lib` are not followed.** Emit
everything inline.

* **The last `.subckt` is the top**; earlier ones are flattened in. GDS is named after it.
* Any non-dot line outside a `.subckt` is parsed as a device — strip testbench sources
  and loads (they fail as `model '1.8' not found`).
* Every device is typed by its model name against the PDK `devices` table, whatever the
  prefix letter; unknown model = hard error. sky130: `nfet_01v8`, `pfet_01v8` (+`_lvt`
  `_hvt`), `nfet/pfet_g5v0d10v5`, `nfet_03v3_nvt`, `nfet_05v0_nvt`, `res_generic_po`,
  `res_high_po_0p35/0p69/1p41`, `res_xhigh_po_0p35/0p69`, `res_generic_m1..m4`,
  `cap_mim_m3_1`, `diode_pw2nd_05v5`, `npn_05v5_1x1`, `pnp_05v5_W3p40L3p40`,
  `pnp_05v5_W0p68L0p68` — bare or `sky130_fd_pr__`-prefixed.
* **R and C are PDK model + `W=`/`L=`, never a value** (`R1 a b 5k` fails). `cap_mim_m3_1`,
  the diode and `npn_05v5_1x1` need explicit `W= L=`; `res_*` needs `L=`.
* Params read: `W` (total, finger = W/nf), `L`, `nf`/`nfin`, `m`/`multi` (`mult=` is
  ignored). Numbers ≥ 0.01 are µm, smaller are metres. `.param`/`{expr}` evaluate from
  global `.param` only; `.subckt` default params are **not** substituted.
* Comments: `*` at line start, `//` inline. ngspice `$`/`;` inline comments are not stripped.

## Nets and constraints

No constraint syntax on the CLI — everything is inferred:

* **Net roles by name.** Supply: `vdd vcc avdd dvdd` (+`_*`). Ground: `gnd vss avss dvss 0`.
  Clock: any name *containing* `clk clock phi1 phi2 ck` (so `fdbck` is a clock).
  TinyTapeout's `VPWR`/`VGND` count as signals — name supplies `vdd`/`vss` in the deck.
* **Symmetry/matching** from same-type, same-W/L FET pairs (cross-coupled > diff pair >
  mirror); common-centroid only for symmetric pairs with a W mismatch. To get matching,
  make matched devices identical in type, W and L.
* **Guard rings only on nets passed with `--pad-net NET`** (repeatable).
* Pins: without `--interface FILE.json` the IO is unattached. Interface JSON:
  `{"die":{"w":nm,"h":nm},"pins":[{"net":"vout","side":"east","frac":0.5}]}`
  (`side`+`frac` or `at:[x,y]`). A fixed die is never grown.

## Reading a run

stdout: `drc: N blocking (M waived) | lvs: match|<reason> | unrouted: K | gds: <path>`.
Exit 0 only when DRC blocking = 0, LVS match, nothing unrouted — **ERC and advanced checks
don't affect the exit code**; for those read `signoff.json .all_required_checks_clean`.

`-o DIR` holds `<top>.gds`, `signoff.txt` (summary + `advanced signoff: k/6`),
`signoff.json` (`drc_violations[{rule,layer,x,y,...}]`, `erc_violations`, `lvs`, `pex`),
`feedback.jsonl` (one record per iteration), placement/route reports and traces.

**`extracted_pex.spice` is not simulatable as written:** no `.subckt`, generic
`nmos`/`pmos`/`npn` models, resistors/caps/diodes omitted, parasitics only as
`* net X R = … ohm  C = … fF` comments, NMOS bulks reported on `vdd`, drain/source
freely swapped, and — without `--interface` — ports renamed `n<id>`. Convert with
`analog/common/pex.py <block> <run_dir>` (matches devices back to the source deck by
type/W/L/nets, restores models and bulks, re-adds passives, adds per-net C to ground;
per-net R is reported only). Always run with `--interface` so ports keep their names.

## Iterating

Budget: Philis converges with more iterations, so give it the default (100 up to 30
FETs, 60 above — `make pnr` computes it) and cut it only when the runtime forces you to.
One knob per run, log each row (knob, value, runtime, DRC, LVS, unrouted, `advanced k/6`),
keep the best `-o` dir.
Order that pays off:

1. `--seed` — cheapest; the search explores differently per seed.
2. `--max-iters` (default 100; README results use 200). The loop stops 12 iterations
   after the first feasible candidate stops improving ≥0.5%.
3. `--pad` (sets wire width *and* pitch), `--via-size`, `--li-width`.
4. `--via-cost` (4.0), `--rg-max-iters`/`--rd-max-iters`, `--history-decay` (0.65).
5. Deck-side: `nf` (generator also tries nf ∈ {1,2,4,6,8,12,16}), `m`, matched sizing,
   `--pad-net` guard rings.

**No effect — overwritten inside the flow:** `--utilization`, `--cell-margin`,
`--min-side`, `--route-pitch`, `--wire-width`, `--feedback-threshold`. Don't spend
iterations on them.

`--hier` P&Rs each subckt once as a macro; it shares one config and `-o` dir across
blocks, so keep it away from `--interface`.

Observed (strongarm, 9 FETs, heavily loaded host): ~23 min per 100-iteration run;
`LI.3` (li spacing) is the typical residual DRC; `IrDrop` is the advanced check that
varies by seed. Run 2–3 seeds in parallel rather than serially.

## Scale

README (200 iters): 4 devices 3 s, 5T OTA 52 s, 10-device OTAs ~275 s, all DRC 0 + LVS
match. Benchmark suite: larger blocks (19–156 cells) often end in LVS mismatch or
unrouted nets. Above ~10 devices, P&R sub-blocks separately or expect a manual layout.
Debug env: `PNR_DEBUG_LVS=1`, `PNR_TIME_SIGNOFF=1`.
