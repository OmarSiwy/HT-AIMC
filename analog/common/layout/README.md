# analog/common/layout: substrate2 layout generators

This is the signoff layout route. It sits next to Philis, and the two do different jobs:

- **Philis** is quick P&R feedback for leaf and irregular blocks.
- **This crate** covers regular arrays, anything that needs well/substrate taps or guard
  rings (Philis draws none), MIM-heavy and long-L cells, and top-level assembly.

It is built on [substrate2](https://github.com/ucb-substrate/substrate2): atoll does
placement and routing, and the crates come from the `substrate` registry
(`.cargo/config.toml`). The reference generators are the documentation:
`analog/cmos_switch/layout/cmos_switch.rs` (2 FETs, tap rows) and
`analog/strongarm/layout/strongarm.rs` (9 FETs, folded, two guard rings).

## Make targets (`analog/<block>/build/layout`)

| target | does |
|---|---|
| `gen` | `cargo run --bin <block>` writes `output/gen/<block>.gds` |
| `gen-drc` | klayout `sky130A_mr.drc` (feol+beol+offgrid) plus magic's full DRC count. Fails on any klayout violation |
| `gen-lvs` | magic flat extraction, then netgen with the PDK setup against `netlist/<block>.spice` |
| `gen-pex` | magic extraction with parasitic C into `output/gen/<block>_pex.spice`: same subckt name and port order as the deck, run with `DUT=pex PEX_FROM=gen` |
| `pnr-verify` | the same klayout DRC + magic/netgen LVS on a Philis GDS (`RUN=seedN`) |
| `views` | the macro views a parent or a digital top places: `output/gds/<block>.gds` + `output/lef/<block>.lef` (`macro_views.py`: bus bits `name[i]`, pins checked against `netlist/<block>.ports` or the `.subckt`, bbox OBS on li1..met4). Runs `gen gen-drc gen-lvs` first, or `pnr-verify` with `VIEW_FROM=pnr` |
| `deps` | `views` of every block in `DEPENDS`, deepest first; existing views are kept (`FORCE=1` rebuilds) |

`verify.py` does the checking. It also takes a GDS path (`verify.py drc <block> x.gds`), so
you can run it on a Philis GDS for comparison. Tools: `klayout`, `magic`, `netgen` and
`cargo` from the nix shell. The registry crate `cache` runs `protoc` while it builds:
`protobuf` must be on PATH, or set `PROTOC`.

## Writing a block generator

1. Create `analog/<block>/layout/<block>.rs` and add a `[[bin]]` for it to `Cargo.toml`.
2. **Sizes come from the deck.** `Deck::read("<block>").mos("Xname")`, `.res(..)` and
   `.mim(..)` read the numbers `devices.py` emitted, so LVS compares like with like. The
   only layout choice is folding, `.nf(k)`. The fingers still LVS as one device because
   netgen merges parallel devices.
3. Write an IO struct (`#[derive(Io)]`) whose fields are the `.subckt` ports, then a
   `Tile` generic over `T: Tech`. Name the block after the subckt, since the GDS top cell
   has to match.
4. **Primitives** (`T::`): `mos` (any L: the S/D pitch widens to fit the gate, and at
   L = 150 nm it is upstream's tile), `tap` (n/p tap row), `mim` (capm top plate to met4,
   met3 bottom plate) and `res` (high/xhigh precision poly). Use
   `cell.generate_connected` for tiles and `cell.generate_primitive` for `mim`/`res`.
5. **Taps**: every bulk-only rail needs a tap.
   - Tap rows: a p-tap row between NMOS and PMOS, and an n-tap row abutting the PMOS so
     the n-wells merge.
   - Guard ring: `T::guard_ring(cell, inner, kind, net)` draws a closed ring one
     LCM unit outside `inner`, hands its li to the router as `net`, and returns
     `(outer, port)`. Fold `outer` into the tile outline. An n ring also draws the
     n-well over everything inside it.
   - `inner` must not have a tap of the ring's own kind at its edge, because the
     implants would sit too close.
6. **Placement** works in LCM units (430 x 540 nm on li/met1). Use `align` and
   `align_rect` (`Above`, `ToTheRight`, `Left`, ...), and `orient(ReflectHoriz)` to
   mirror a half.
7. **Routing**: call `set_top_layer(2)`, `set_router(GreedyRouter::new())` and
   `set_via_maker(T::via_maker())`. atoll connects every schematic net on li/met1/met2.
   The via maker also covers via2/via3, for MIM plates.
8. **Pins**: finish with
   `pins::place(cell, placed_bounds, &[("port", io.port), ..], &pins::interface("<block>"))`.
   - It puts one labelled stub per port on the cell edge: met1 on east/west, met2 on
     north/south.
   - It hands each stub to the router as that net, and returns the widened outline plus
     the pin geometry, in port order.
   - Use that geometry as the layout bundle. The GDS labels then sit on the edge, a parent
     can route to the stubs, and LVS keeps the port names.
   - `side`/`frac` come from the block's `layout/interface.json`, the file Philis uses.
     Its `die` is ignored. Ports the file doesn't place go on the west edge.

`cargo run --bin primitives` writes every primitive as a standalone cell for DRC.

## PEX: what `PEX_FROM=gen` includes

`gen-pex` is magic's extraction, run on the whole flattened cell. It contains:

- each device with its drawn junction geometry: `ad`/`as`/`pd`/`ps`, so the sky130 models
  add source/drain junction capacitance;
- every net's capacitance to substrate and its coupling capacitance to other nets, as `C`
  elements (`cthresh 0`);
- no wire resistance.

The Philis route (`PEX_FROM=pnr`, via `analog/common/pex.py`) keeps the deck's device
cards verbatim. That means no `ad`/`as`/`pd`/`ps` and no junction caps, plus one
estimated ground cap per net from Philis, and no coupling. So `gen` is the more
pessimistic of the two, and the gap between them is not layout quality alone. On
strongarm the gen route gives clk-to-decision 1.20 ns against Philis's 1.05 ns, partly
because the long-L input fingers carry wide diffusion (see below).

## sky130 only

The registry ships a `sky130` PDK crate and nothing else. `Tech` keeps generators
PDK-agnostic, so a gf180 binding (a `tech/gf180.rs` implementing `Tech`) is the whole
port once a gf180 substrate crate exists.

Workarounds in `tech/sky130.rs`:

- `Sky130Layer` has no capm layer. `Tunm` stands in for it, and our `to_gds` maps it to
  89/44.
- Upstream MOS tiles are L = 150 nm only. The MOS tile here is our own.
- Upstream poly resistors are xhigh only. Ours draws both flavours, with the contact
  head that magic's `licon.1c` wants.
- magic cannot recover the fixed-width resistor id (`_0p35`) from GDS. `verify.py` maps
  the generic model back.

## Long-L MOS tile

S/D stripes sit on li tracks, and a finger spans `stride` tracks:

    stride = ceil((L + 2 * licon.11 + li width) / li pitch)

The gate is centred between two stripes, so any L on the 5 nm grid works. Examples:
0.6 um takes 3 tracks and 9.6 um takes 23. Gates pair up on the stripe between them for
the gate contact, and even stripes are the source. Long devices get wide: fold them
(`nf`) and let the row height take the width.
