//! Every sky130 primitive as a standalone cell, for DRC of the primitives themselves:
//!
//!     cargo run --bin primitives [out_dir]     (default target/primitives)
//!     -> <name>.gds per cell, and prints `<gds> <top cell>` per line
//!
//! Sizes span what the decks use: L 0.15 - 9.6 um, folded and single-finger W, both
//! resistor flavours at 0.35 um, the minimum (capm.1) and a large MIM.

use std::path::PathBuf;

use analog_layout::tech::Tech;
use analog_layout::tech::sky130::{Sky130Tech, write_cell};
use analog_layout::tiles::{MimTileParams, MosTileParams, ResKind, ResTileParams, TapTileParams, TileKind};
use atoll::route::GreedyRouter;
use atoll::{Tile, TileBuilder, TileData, TileWrapper};
use sky130::Sky130;
use substrate::arcstr::{self, ArcStr};
use substrate::block::Block;
use substrate::error::Result;
use substrate::geometry::bbox::Bbox;
use substrate::geometry::dir::Dir;
use substrate::types::codegen::{PortGeometryBundle, View};
use substrate::types::schematic::{IoNodeBundle, NodeBundle};
use substrate::types::{MosIo, MosIoView};

/// A MOS tile inside a guard ring tied to its bulk (p ring round NMOS, n ring round PMOS).
#[derive(Debug, Clone, Copy, Hash, PartialEq, Eq)]
struct Ringed(MosTileParams);

impl Block for Ringed {
    type Io = MosIo;
    fn name(&self) -> ArcStr {
        arcstr::literal!("ringed")
    }
    fn io(&self) -> Self::Io {
        Default::default()
    }
}

impl Tile for Ringed {
    type Schema = Sky130;
    type NestedData = ();
    type LayoutBundle = View<MosIo, PortGeometryBundle<Sky130>>;
    type LayoutData = ();

    fn tile<'a>(&self, io: &'a IoNodeBundle<Self>, cell: &mut TileBuilder<'a, Sky130>) -> Result<TileData<Self>> {
        let m = cell.generate_connected(Sky130Tech::mos(self.0), NodeBundle::<MosIo> { d: io.d, g: io.g, s: io.s, b: io.b });
        let inner = m.physical_bounds();
        let m = cell.draw(m)?;
        let ring = if self.0.tile_kind == TileKind::N { TileKind::P } else { TileKind::N };
        let (outer, b) = Sky130Tech::guard_ring(cell, inner, ring, io.b)?;
        cell.set_top_layer(2);
        cell.set_router(GreedyRouter::new());
        cell.set_via_maker(Sky130Tech::via_maker());
        let io = m.layout.io();
        Ok(TileData {
            nested_data: (),
            layout_bundle: MosIoView { d: io.d, g: io.g, s: io.s, b },
            layout_data: (),
            outline: outer.union(cell.layout.bbox_rect()),
        })
    }
}

fn main() -> Result<()> {
    let out = std::env::args().nth(1).map(PathBuf::from).unwrap_or_else(|| {
        PathBuf::from(concat!(env!("CARGO_MANIFEST_DIR"), "/target/primitives"))
    });
    let (n, p) = (TileKind::N, TileKind::P);
    let mos = |k, w, l, nf| MosTileParams::new(k, w, l, 1).nf(nf);
    let mut cells: Vec<(String, ArcStr)> = Vec::new();
    let mut put = |file: &str, name: ArcStr, r: Result<()>| -> Result<()> {
        r?;
        cells.push((out.join(format!("{file}.gds")).display().to_string(), name));
        Ok(())
    };
    let path = |f: &str| out.join(format!("{f}.gds"));
    for (f, m) in [
        ("nmos_w420_l150", mos(n, 420, 150, 1)),
        ("nmos_w21800_l600_nf4", mos(n, 21_800, 600, 4)),
        ("nmos_w5000_l9600_nf2", mos(n, 5_000, 9_600, 2)),
        ("pmos_w10330_l150_nf2", mos(p, 10_330, 150, 2)),
        ("pmos_w1500_l1000_nf3", mos(p, 1_500, 1_000, 3)),
    ] {
        let b = TileWrapper::new(Sky130Tech::mos(m));
        put(f, b.name(), Sky130Tech::write_gds(Sky130Tech::mos(m), &path(f)))?;
    }
    for (f, k) in [("ntap", n), ("ptap", p)] {
        let t = Sky130Tech::tap(TapTileParams::new(k, Dir::Horiz, 6));
        put(f, t.name(), Sky130Tech::write_gds(t, &path(f)))?;
    }
    for (f, m) in [("pring_nmos", mos(n, 2_300, 600, 2)), ("nring_pmos", mos(p, 2_300, 150, 2))] {
        put(f, Ringed(m).name(), Sky130Tech::write_gds(Ringed(m), &path(f)))?;
    }
    for (f, c) in [("mim_1u", MimTileParams { w: 1_000, l: 1_000 }), ("mim_5u", MimTileParams { w: 5_000, l: 5_000 })] {
        let m = Sky130Tech::mim(c);
        put(f, m.name(), write_cell(m, &path(f)))?;
    }
    for (f, k) in [("res_high", ResKind::High), ("res_xhigh", ResKind::XHigh)] {
        let r = Sky130Tech::res(ResTileParams { kind: k, w: 350, l: 5_000 });
        put(f, r.name(), write_cell(r, &path(f)))?;
    }
    for (gds, top) in cells {
        println!("{gds} {top}");
    }
    Ok(())
}
