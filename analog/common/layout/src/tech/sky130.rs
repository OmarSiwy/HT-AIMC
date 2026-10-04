//! SKY130 binding of the [`Tech`] trait: any-L MOS, taps, guard rings, MIM, poly R.
//!
//! MOS, tap and resistor geometry is adapted from `sky130::atoll` / `sky130::res`
//! (BSD-3, Substrate Labs); upstream MOS tiles only draw L = 150 nm and upstream
//! resistors only the extra-high flavour. Values this file adds cite their rule and deck:
//! `sky130A_mr.drc` is klayout's deck, `sky130A.tech` magic's.

use std::collections::HashMap;
use std::path::{Path, PathBuf};

use atoll::abs::TrackCoord;
use atoll::grid::{AtollLayer, LayerStack, PdkLayer, RoutingGrid};
use atoll::route::{GreedyRouter, ViaMaker};
use atoll::{AtollPrimitive, Tile, TileBuilder, TileData, TileWrapper};
use gds::GdsUnits;
use gdsconv::GdsLayer;
use geometry_macros::{TransformRef, TranslateRef};
use layir::{Cell, Element, Instance, LibraryBuilder, Shape, Text};
use sky130::atoll::{MosTileIo, MosTileIoView, NtapTile, PtapTile, Sky130ViaMaker};
use sky130::layers::Sky130Layer;
use sky130::layout::GDS_UNITS;
use sky130::mos::{MosParams, Nfet01v8, Pfet01v8};
use sky130::{Primitive, Sky130};
use substrate::arcstr::{self, ArcStr};
use substrate::block::Block;
use substrate::context::Context;
use substrate::error::Result;
use substrate::geometry::bbox::Bbox;
use substrate::geometry::dir::Dir;
use substrate::geometry::prelude::Transformation;
use substrate::geometry::rect::Rect;
use substrate::geometry::span::Span;
use substrate::geometry::transform::Translate;
use substrate::layout::tracks::RoundingMode;
use substrate::layout::{CellBuilder, Layout};
use substrate::schematic::{PrimitiveBinding, Schematic};
use substrate::types::codegen::{PortGeometryBundle, View};
use substrate::types::layout::{PortGeometry, PortGeometryBuilder};
use substrate::types::schematic::{Node, NodeBundle};
use substrate::types::{Array, ArrayBundle, FlatLen, InOut, Input, MosIo, MosIoView, Signal, TwoTerminalIo, TwoTerminalIoView};

use crate::tech::Tech;
use crate::tiles::{
    MimTileParams, MosTileParams, ResKind, ResTileParams, ResistorIo, ResistorIoView, TapIo, TapIoView, TapTileParams,
    TileKind,
};

/// licon.11 (sky130A.tech): diffusion licon to gate spacing.
const LICON_GATE: i64 = 55;
/// licon.8 (sky130A.tech): poly enclosure of a poly licon.
const POLY_LICON: i64 = 50;
/// licon.7 (sky130A.tech) tap enclosure of licon, taken on all sides.
const TAP_LICON: i64 = 120;
/// nsd/psd.5a (sky130A.tech) implant enclosure of tap, as drawn upstream.
const IMPLANT_TAP: i64 = 130;
/// diff/tap.10 (sky130A.tech): n-well enclosure of n-tap / p-diffusion.
const NWELL_DIFF: i64 = 180;
/// li.5 (sky130A_mr.drc): li enclosure of licon on one of two adjacent edges.
const LI_LICON: i64 = 80;
/// capm.3 (sky130A_mr.drc): met3 enclosure of capm.
const M3_CAPM: i64 = 140;
/// capm.4 (sky130A_mr.drc): capm enclosure of via3.
const CAPM_VIA3: i64 = 140;
/// via3.1 / via3.2 (sky130A_mr.drc): via3 size and spacing.
const VIA3: i64 = 200;
/// via2.1a (sky130A_mr.drc): via2 size.
const VIA2: i64 = 200;
/// via2.4 / via2.5 (sky130A_mr.drc): met2 / met3 enclosure of via2 (adjacent-edge value).
const M2_VIA2: i64 = 40;
const M3_VIA2: i64 = 85;
/// via3.5 (sky130A_mr.drc): met3 enclosure of via3 on two adjacent edges.
const M3_VIA3: i64 = 90;
/// m4.3 (sky130A.tech): met4 enclosure of via3.
const M4_VIA3: i64 = 65;
/// rpm.1a / urpm.1a (sky130A_mr.drc): min implant width of a precision resistor.
const RPM_W: i64 = 1_270;
/// capm drawing layer 89/44 (sky130A_mr.drc `capm = polygons(89, 44)`).
const CAPM_GDS: GdsLayer = GdsLayer(89, 44);
// ponytail: sky130 0.10.3's Sky130Layer has no capm; Tunm (not used by sky130A) stands in
// and to_gds() maps it to 89/44. Drop once the crate grows a Capm layer.
const CAPM: Sky130Layer = Sky130Layer::Tunm;

/// The SKY130 technology binding.
pub struct Sky130Tech;

impl Tech for Sky130Tech {
    type Schema = Sky130;
    type MosTile = MosTile;
    type TapTile = TapTile;
    type MimTile = Mim;
    type ResTile = Res;
    type ViaMaker = Sky130Vias;

    fn mos(params: MosTileParams) -> Self::MosTile {
        MosTile(params)
    }
    fn tap(params: TapTileParams) -> Self::TapTile {
        TapTile(params)
    }
    fn mim(params: MimTileParams) -> Self::MimTile {
        Mim(params)
    }
    fn res(params: ResTileParams) -> Self::ResTile {
        Res(params)
    }
    fn via_maker() -> Self::ViaMaker {
        Sky130Vias
    }

    fn guard_ring(
        cell: &mut TileBuilder<'_, Sky130>,
        inner: Rect,
        kind: TileKind,
        net: Node,
    ) -> Result<(Rect, PortGeometry<Sky130Layer>)> {
        let (px, py, line) = (
            cell.layer_stack.layer(0).pitch(),
            cell.layer_stack.layer(1).pitch(),
            cell.layer_stack.layer(0).line(),
        );
        assert!(
            inner.left() % px == 0 && inner.right() % px == 0 && inner.bot() % py == 0 && inner.top() % py == 0,
            "guard ring must wrap an LCM-aligned rect, got {inner:?}"
        );
        // ring centre line: one li track / met1 row outside `inner`; its implant and
        // well stay inside the next one, which is the ring's outer bound
        let (x0, x1, y0, y1) = (inner.left() / px - 1, inner.right() / px + 1, inner.bot() / py - 1, inner.top() / py + 1);
        let (imp, tap_layer) = match kind {
            TileKind::N => (Sky130Layer::Nsdm, Sky130Layer::Tap),
            TileKind::P => (Sky130Layer::Psdm, Sky130Layer::Tap),
        };
        let (mut taps, mut port) = (Vec::new(), PortGeometryBuilder::new());
        // own net id, joined to `net`, so the router connects the ring to the net's pins
        let ring = cell.signal("guard_ring", Signal);
        cell.connect(ring, net);
        for (side, horiz) in [
            (Rect::from_sides(x0, y0, x1, y0), true),
            (Rect::from_sides(x0, y1, x1, y1), true),
            (Rect::from_sides(x0, y0, x0, y1), false),
            (Rect::from_sides(x1, y0, x1, y1), false),
        ] {
            let li = Rect::from_sides(
                side.left() * px - line / 2,
                side.bot() * py - line / 2,
                side.right() * px + line / 2,
                side.top() * py + line / 2,
            );
            // horizontal sides overhang the corner licons so no licon has two bare
            // adjacent edges (li.5)
            let li = if horiz { li.expand_dir(Dir::Horiz, LI_LICON) } else { li };
            cell.layout.draw(Shape::new(Sky130Layer::Li1, li))?;
            port.merge(PortGeometry::new(Shape::new(Sky130Layer::Li1, li)));
            for x in side.left()..=side.right() {
                for y in side.bot()..=side.top() {
                    let cut = Rect::from_sides(x * px - line / 2, y * py - line / 2, x * px + line / 2, y * py + line / 2);
                    cell.layout.draw(Shape::new(Sky130Layer::Licon1, cut))?;
                }
            }
            let tap = li.expand_all(TAP_LICON);
            cell.layout.draw(Shape::new(tap_layer, tap))?;
            cell.layout.draw(Shape::new(imp, tap.expand_all(IMPLANT_TAP)))?;
            cell.assign_grid_points(Some(ring), 0, side);
            taps.push(tap);
        }
        if kind == TileKind::N {
            let well = taps.iter().fold(inner, |a, t| a.union(*t)).expand_all(NWELL_DIFF);
            cell.layout.draw(Shape::new(Sky130Layer::Nwell, well))?;
        }
        Ok((inner.expand_dir(Dir::Horiz, 2 * px).expand_dir(Dir::Vert, 2 * py), port.build()?))
    }

    fn write_gds<B: Tile<Schema = Sky130> + Clone>(block: B, path: &Path) -> Result<()> {
        write_cell(TileWrapper::new(block), path)
    }
}

/// Writes any sky130 layout cell (a primitive or a wrapped tile) as GDS.
pub fn write_cell<B: Layout<Schema = Sky130>>(block: B, path: &Path) -> Result<()> {
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir).unwrap_or_else(|e| panic!("{}: {e}", dir.display()));
    }
    let root = std::env::var("PDK_ROOT").map(PathBuf::from).unwrap_or_default().join("sky130A");
    let ctx = Context::builder().install(Sky130::open(root)).build();
    ctx.write_layout(block, to_gds, path)
}

fn gds_layer(l: &Sky130Layer) -> GdsLayer {
    if *l == CAPM { CAPM_GDS } else { l.gds_layer() }
}

/// `sky130::layout::to_gds` with the capm stand-in mapped (see [`CAPM`]).
fn to_gds(lib: &layir::Library<Sky130Layer>) -> (layir::Library<GdsLayer>, GdsUnits) {
    let mut olib = LibraryBuilder::<GdsLayer>::new();
    for id in lib.topological_order() {
        let cell = lib.cell(id);
        let mut ocell = Cell::new(cell.name());
        for elt in cell.elements() {
            ocell.add_element(elt.map_layer(gds_layer));
        }
        for (_, inst) in cell.instances() {
            let child = olib.cell_id_named(lib.cell(inst.child()).name());
            ocell.add_instance(Instance::with_transformation(child, inst.name(), inst.transformation()));
        }
        for (name, oport) in cell.ports() {
            let mut port = oport.map_layer(|l| l.gds_pin_layer().unwrap());
            for s in oport.elements().filter_map(|e| match e {
                Element::Shape(s) => Some(s),
                Element::Text(_) => None,
            }) {
                let c = s.bbox_rect().center();
                for layer in [s.layer().gds_pin_layer().unwrap(), s.layer().gds_label_layer().unwrap()] {
                    port.add_element(Element::Text(Text::with_transformation(layer, name.clone(), Transformation::translate(c.x, c.y))));
                }
            }
            ocell.add_port(name, port);
        }
        olib.add_cell(ocell);
    }
    (olib.build().unwrap(), GDS_UNITS)
}

/// [`Sky130ViaMaker`] (mcon, via) plus via2 and via3, so tiles holding MIM plates
/// (met3/met4) can be routed.
pub struct Sky130Vias;

impl ViaMaker<Sky130Layer> for Sky130Vias {
    fn draw_via(&self, ctx: Context, c: TrackCoord) -> Vec<Shape<Sky130Layer>> {
        let stack = ctx.get_installation::<LayerStack<PdkLayer<Sky130Layer>>>().unwrap();
        let (via, bot, top) = match c.layer {
            1 | 2 => return Sky130ViaMaker.draw_via(ctx, c),
            // met2 tracks are narrower than via2 + 2 x via2.4: widen along the track only
            3 => (Sky130Layer::Via2, (VIA2 / 2 + M2_VIA2, VIA2 / 2 + M3_VIA2), (VIA2 / 2 + M3_VIA2, stack.layer(3).line() / 2)),
            4 => (Sky130Layer::Via3, (VIA3 / 2 + M3_VIA3, stack.layer(3).line() / 2), (stack.layer(4).line() / 2, VIA3 / 2 + M4_VIA3)),
            n => unimplemented!("sky130 via to layer {n}"),
        };
        let grid = RoutingGrid::new((*stack).clone(), 0..c.layer + 1);
        let p = grid.xy_track_point(c.layer, c.x, c.y);
        let r = |(hx, hy): (i64, i64)| Rect::from_sides(p.x - hx, p.y - hy, p.x + hx, p.y + hy);
        vec![
            Shape::new(stack.layer(c.layer - 1).layer, r(bot)),
            Shape::new(via, r((VIA2 / 2, VIA2 / 2))),
            Shape::new(stack.layer(c.layer).layer, r(top)),
        ]
    }
}

/// Primitive geometry: the ATOLL outline.
#[derive(TranslateRef, TransformRef)]
pub struct PrimData {
    lcm_bbox: Rect,
}

fn lcm_bbox(cell: &CellBuilder<Sky130>) -> Rect {
    let stack = cell.ctx().get_installation::<LayerStack<PdkLayer<Sky130Layer>>>().unwrap();
    let slice = stack.slice(0..2);
    slice.lcm_to_physical_rect(slice.expand_to_lcm_units(cell.bbox_rect()))
}

/// `nf` fingers of one sky130 MOSFET, `w` per finger, any `l`. Source/drain stripes sit
/// `stride` li tracks apart, the smallest stride whose gap holds the gate plus licon.11
/// on each side; the gate is centred in it. Stride 1 (L = 150 nm) is exactly
/// `sky130::atoll::MosTile`. Gates pair up on the stripe between them.
#[derive(Debug, Clone, Copy, Hash, PartialEq, Eq)]
pub struct Mos {
    kind: TileKind,
    w: i64,
    l: i64,
    nf: i64,
}

impl Block for Mos {
    type Io = MosTileIo;

    fn name(&self) -> ArcStr {
        let k = if self.kind == TileKind::N { "n" } else { "p" };
        arcstr::format!("{k}mos_w{}_l{}_nf{}", self.w, self.l, self.nf)
    }

    fn io(&self) -> Self::Io {
        MosTileIo {
            sd: Array::new(self.nf as usize + 1, InOut(Signal::new())),
            g: Array::new(((self.nf - 1) / 2 + 1) as usize, Input(Signal::new())),
            b: InOut(Signal::new()),
        }
    }
}

impl Layout for Mos {
    type Schema = Sky130;
    type Bundle = View<MosTileIo, PortGeometryBundle<Sky130>>;
    type Data = PrimData;

    fn layout(&self, cell: &mut CellBuilder<Sky130>) -> Result<(Self::Bundle, Self::Data)> {
        let stack = cell.ctx().get_installation::<LayerStack<PdkLayer<Sky130Layer>>>().unwrap();
        let grid = RoutingGrid::new((*stack).clone(), 0..2);
        let (pitch, line) = (stack.layer(0).pitch(), stack.layer(0).line());
        let stride = (self.l + 2 * LICON_GATE + line + pitch - 1) / pitch;

        let top_m1 = grid.tracks(1).to_track_idx(self.w + 10, RoundingMode::Up);
        let bot_m1 = grid.tracks(1).to_track_idx(-10, RoundingMode::Down);
        let gate_vspan = grid.track_span(1, bot_m1 - 1).union(grid.track_span(1, bot_m1 - 2)).shrink_all(45);

        let tracks: Vec<Rect> = (0..=self.nf)
            .map(|i| Rect::from_spans(grid.track_span(0, 1 + i * stride), Span::new(-10, self.w + 10)))
            .collect();
        let gate_spans: Vec<Span> = tracks
            .windows(2)
            .map(|t| {
                let lo = (t[0].right() + t[1].left()) / 2 - self.l / 2;
                Span::new(lo, lo + self.l)
            })
            .collect();

        let (mut sd, mut g) = (Vec::new(), Vec::new());
        for rect in &tracks {
            let sd_rect = rect.with_vspan(grid.track_span(1, bot_m1).union(grid.track_span(1, top_m1)).shrink_all(45));
            let shape = Shape::new(Sky130Layer::Li1, sd_rect);
            cell.draw(shape.clone())?;
            sd.push(PortGeometry::new(shape));
            for j in 0..(self.w + 20 - 160 + 170) / 340 {
                let base = rect.bot() + 10 + 80 + 340 * j;
                cell.draw(Shape::new(Sky130Layer::Licon1, Rect::from_spans(rect.hspan(), Span::with_start_and_length(base, 170))))?;
            }
        }

        let diff = Rect::from_sides(tracks[0].left() - 130, 0, tracks.last().unwrap().right() + 130, self.w);
        cell.draw(Shape::new(Sky130Layer::Diff, diff))?;

        for i in 0..self.nf as usize {
            let li_track = tracks[if i % 2 == 0 { i + 1 } else { i }];
            let poly_li = Rect::from_spans(li_track.hspan(), gate_vspan);
            if i % 2 == 0 {
                let shape = Shape::new(Sky130Layer::Li1, poly_li);
                cell.draw(shape.clone())?;
                g.push(PortGeometry::new(shape));
                let cut = Rect::from_spans(li_track.hspan(), Span::new(poly_li.top() - 90, poly_li.top() - 260));
                cell.draw(Shape::new(Sky130Layer::Licon1, cut))?;
                let npc = Rect::from_spans(poly_li.hspan(), Span::new(poly_li.top(), poly_li.top() - 350))
                    .expand_dir(Dir::Vert, 10)
                    .expand_dir(Dir::Horiz, 100);
                cell.draw(Shape::new(Sky130Layer::Npc, npc))?;
            }
            let head = li_track.hspan().expand_all(POLY_LICON);
            let bar = Rect::from_spans(gate_spans[i].union(head), Span::new(poly_li.top() - 350, poly_li.top()));
            cell.draw(Shape::new(Sky130Layer::Poly, bar))?;
        }
        for &span in &gate_spans {
            cell.draw(Shape::new(Sky130Layer::Poly, Rect::from_spans(span, Span::new(gate_vspan.stop() - 350, self.w + 130))))?;
        }

        let lcm = lcm_bbox(cell);
        let imp = diff.expand_all(130);
        let imp = imp.with_hspan(lcm.hspan().union(imp.hspan()));
        let body = match self.kind {
            TileKind::N => {
                cell.draw(Shape::new(Sky130Layer::Nsdm, imp))?;
                Shape::new(Sky130Layer::Pwell, lcm)
            }
            TileKind::P => {
                cell.draw(Shape::new(Sky130Layer::Psdm, imp))?;
                let nwell = diff.expand_all(NWELL_DIFF).union(lcm);
                Shape::new(Sky130Layer::Nwell, nwell)
            }
        };
        cell.draw(body.clone())?;
        Ok((
            MosTileIoView {
                sd: ArrayBundle::new(Signal, sd),
                g: ArrayBundle::new(Signal, g),
                b: PortGeometry::new(body),
            },
            PrimData { lcm_bbox: lcm },
        ))
    }
}

impl AtollPrimitive for Mos {
    type Schema = Sky130;
    fn outline(cell: &substrate::layout::TransformedCell<Self>) -> Rect {
        cell.data().lcm_bbox
    }
}

impl Schematic for Mos {
    type Schema = Sky130;
    type NestedData = ();

    fn schematic(
        &self,
        io: &substrate::types::schematic::IoNodeBundle<Self>,
        cell: &mut substrate::schematic::CellBuilder<Sky130>,
    ) -> Result<()> {
        for i in 0..self.nf as usize {
            let params = MosParams { w: self.w, l: self.l, nf: 1 };
            let conn = NodeBundle::<MosIo> { d: io.sd[i], g: io.g[i / 2], s: io.sd[i + 1], b: io.b };
            match self.kind {
                TileKind::N => {
                    cell.instantiate_connected(Nfet01v8::new(params), conn);
                }
                TileKind::P => {
                    cell.instantiate_connected(Pfet01v8::new(params), conn);
                }
            }
        }
        Ok(())
    }
}

/// A [`Mos`] behind the PDK-agnostic [`MosIo`]: even stripes are the source, odd the
/// drain, every gate is `g`.
#[derive(Block, Copy, Clone, Debug, Hash, PartialEq, Eq)]
#[substrate(io = "MosIo")]
pub struct MosTile(MosTileParams);

impl Tile for MosTile {
    type Schema = Sky130;
    type NestedData = ();
    type LayoutBundle = View<MosIo, PortGeometryBundle<Sky130>>;
    type LayoutData = ();

    fn tile<'a>(
        &self,
        io: &'a substrate::types::schematic::IoNodeBundle<Self>,
        cell: &mut TileBuilder<'a, Sky130>,
    ) -> Result<TileData<Self>> {
        cell.flatten();
        let p = self.0;
        assert_eq!(p.w % p.nf, 0, "W = {} nm does not split into {} fingers", p.w, p.nf);
        let mos = cell.generate_primitive(Mos { kind: p.tile_kind, w: p.w / p.nf, l: p.l, nf: p.nf });
        let mos = cell.draw(mos)?;
        cell.connect(mos.schematic.io().b, io.b);
        let (mut d, mut g, mut s) = (PortGeometryBuilder::new(), PortGeometryBuilder::new(), PortGeometryBuilder::new());
        let lio = mos.layout.io();
        for i in 0..mos.schematic.io().g.len() {
            cell.connect(mos.schematic.io().g[i], io.g);
            g.merge(lio.g[i].clone());
        }
        for i in 0..mos.schematic.io().sd.len() {
            cell.connect(mos.schematic.io().sd[i], if i % 2 == 0 { io.s } else { io.d });
            if i % 2 == 0 { s.merge(lio.sd[i].clone()) } else { d.merge(lio.sd[i].clone()) }
        }
        cell.set_top_layer(1);
        cell.set_router(GreedyRouter::new());
        cell.set_via_maker(Sky130Vias);
        Ok(TileData {
            nested_data: (),
            layout_bundle: MosIoView { d: d.build()?, g: g.build()?, s: s.build()?, b: mos.layout.io().b },
            layout_data: (),
            outline: cell.layout.bbox_rect(),
        })
    }
}

/// An N/P tap biasing an n-well or the p-substrate (upstream `NtapTile` / `PtapTile`).
#[derive(Debug, Clone, Copy, Hash, Eq, PartialEq)]
pub struct TapTile(TapTileParams);

impl Block for TapTile {
    type Io = TapIo;

    fn name(&self) -> ArcStr {
        let k = if self.0.kind == TileKind::N { "n" } else { "p" };
        arcstr::format!("{k}tap_tile_{}", self.0.span)
    }

    fn io(&self) -> Self::Io {
        Default::default()
    }
}

impl Tile for TapTile {
    type Schema = Sky130;
    type NestedData = ();
    type LayoutBundle = View<TapIo, PortGeometryBundle<Sky130>>;
    type LayoutData = ();

    fn tile<'a>(
        &self,
        io: &'a substrate::types::schematic::IoNodeBundle<Self>,
        cell: &mut TileBuilder<'a, Sky130>,
    ) -> Result<TileData<Self>> {
        cell.flatten();
        let (x, y) = match self.0.dir {
            Dir::Horiz => (self.0.span, 2),
            Dir::Vert => (2, self.0.span),
        };
        let x = match self.0.kind {
            TileKind::N => {
                let tap = cell.generate_primitive(NtapTile::new(x, y));
                let tap = cell.draw(tap)?;
                cell.connect(tap.schematic.io().vpb, io.x);
                tap.layout.io().vpb
            }
            TileKind::P => {
                let tap = cell.generate_primitive(PtapTile::new(x, y));
                let tap = cell.draw(tap)?;
                cell.connect(tap.schematic.io().vnb, io.x);
                tap.layout.io().vnb
            }
        };
        Ok(TileData { nested_data: (), layout_bundle: TapIoView { x }, layout_data: (), outline: cell.layout.bbox_rect() })
    }
}

/// A MIM capacitor: the cap layer is the `W x L` top plate (`p`, reached by a via3
/// array to met4), met3 under it the bottom plate (`n`).
#[derive(Debug, Clone, Copy, Hash, PartialEq, Eq)]
pub struct Mim(MimTileParams);

impl Block for Mim {
    type Io = TwoTerminalIo;
    fn name(&self) -> ArcStr {
        arcstr::format!("mim_w{}_l{}", self.0.w, self.0.l)
    }
    fn io(&self) -> Self::Io {
        Default::default()
    }
}

impl Layout for Mim {
    type Schema = Sky130;
    type Bundle = View<TwoTerminalIo, PortGeometryBundle<Sky130>>;
    type Data = PrimData;

    fn layout(&self, cell: &mut CellBuilder<Sky130>) -> Result<(Self::Bundle, Self::Data)> {
        let capm = Rect::from_sides(0, 0, self.0.w, self.0.l);
        cell.draw(Shape::new(CAPM, capm))?;
        let bot = Shape::new(Sky130Layer::Met3, capm.expand_all(M3_CAPM));
        cell.draw(bot.clone())?;
        let inner = capm.shrink_all(CAPM_VIA3).expect("MIM narrower than 2 x capm.4");
        let (nx, ny) = ((inner.width() + VIA3) / (2 * VIA3), (inner.height() + VIA3) / (2 * VIA3));
        let (x0, y0) = (inner.center().x - (2 * nx - 1) * VIA3 / 2, inner.center().y - (2 * ny - 1) * VIA3 / 2);
        for i in 0..nx {
            for j in 0..ny {
                let v = Rect::from_sides(0, 0, VIA3, VIA3).translate(substrate::geometry::point::Point::new(x0 + 2 * VIA3 * i, y0 + 2 * VIA3 * j));
                cell.draw(Shape::new(Sky130Layer::Via3, v))?;
            }
        }
        let top = Shape::new(Sky130Layer::Met4, capm);
        cell.draw(top.clone())?;
        let lcm = lcm_bbox(cell);
        Ok((TwoTerminalIoView { p: PortGeometry::new(top), n: PortGeometry::new(bot) }, PrimData { lcm_bbox: lcm }))
    }
}

impl AtollPrimitive for Mim {
    type Schema = Sky130;
    fn outline(cell: &substrate::layout::TransformedCell<Self>) -> Rect {
        cell.data().lcm_bbox
    }
}

fn raw_prim(cell: &mut substrate::schematic::CellBuilder<Sky130>, name: &str, pins: &[(&str, Node)]) {
    let mut prim = PrimitiveBinding::new(Primitive::RawInstance {
        cell: name.into(),
        ports: pins.iter().map(|(p, _)| ArcStr::from(*p)).collect(),
        params: HashMap::new(),
    });
    for (p, n) in pins {
        prim.connect(*p, *n);
    }
    cell.set_primitive(prim);
}

impl Schematic for Mim {
    type Schema = Sky130;
    type NestedData = ();
    fn schematic(
        &self,
        io: &substrate::types::schematic::IoNodeBundle<Self>,
        cell: &mut substrate::schematic::CellBuilder<Sky130>,
    ) -> Result<()> {
        raw_prim(cell, "sky130_fd_pr__cap_mim_m3_1", &[("P", io.p), ("N", io.n)]);
        Ok(())
    }
}

/// A precision poly resistor, horizontal: `W` wide body of length `L` between two
/// slotted-licon heads (`p` left, `n` right on li). High = rpm implant, XHigh = urpm.
#[derive(Debug, Clone, Copy, Hash, PartialEq, Eq)]
pub struct Res(ResTileParams);

/// Slotted poly-resistor licon (licon.1b, sky130A.tech): 0.19 x 2.0 um.
const SLOT_W: i64 = 190;
const SLOT_L: i64 = 2_000;
/// magic's poly-resistor terminal growth into the body (sky130A.tech cifinput xpolyterm).
const XPC_GROW: i64 = 60;
/// Slot spacing inside one head (upstream `sky130::res`).
const SLOT_SPACE: i64 = 510;

impl Block for Res {
    type Io = ResistorIo;
    fn name(&self) -> ArcStr {
        let k = if self.0.kind == ResKind::High { "high" } else { "xhigh" };
        arcstr::format!("res_{k}_w{}_l{}", self.0.w, self.0.l)
    }
    fn io(&self) -> Self::Io {
        Default::default()
    }
}

impl Layout for Res {
    type Schema = Sky130;
    type Bundle = View<ResistorIo, PortGeometryBundle<Sky130>>;
    type Data = PrimData;

    fn layout(&self, cell: &mut CellBuilder<Sky130>) -> Result<(Self::Bundle, Self::Data)> {
        let ResTileParams { kind, w, l } = self.0;
        let n_slot: i64 = match w {
            350 | 690 => 1,
            1_410 => 2,
            2_850 => 4,
            5_730 => 8,
            _ => panic!("no sky130 precision resistor is {w} nm wide"),
        };
        // head = slot + li.5 on both sides, the extension licon.1c + li.5 (sky130A.tech) asks
        let head = SLOT_L + 2 * LI_LICON;
        let poly = Rect::from_sides(0, 0, 2 * head + l, w);
        cell.draw(Shape::new(Sky130Layer::Poly, poly))?;
        let y0 = (w - (SLOT_W * n_slot + SLOT_SPACE * (n_slot - 1))) / 2;
        let (x0, x1) = (head, poly.right() - head);
        for i in 0..n_slot {
            let y = y0 + i * (SLOT_W + SLOT_SPACE);
            cell.draw(Shape::new(Sky130Layer::Licon1, Rect::from_sides(LI_LICON, y, LI_LICON + SLOT_L, y + SLOT_W)))?;
            cell.draw(Shape::new(Sky130Layer::Licon1, Rect::from_sides(x1 + LI_LICON, y, x1 + LI_LICON + SLOT_L, y + SLOT_W)))?;
        }
        let heads = Span::new(y0 - LI_LICON, w - y0 + LI_LICON);
        let p = Rect::from_spans(Span::new(0, x0), heads);
        let n = Rect::from_spans(Span::new(x1, poly.right()), heads);
        cell.draw(Shape::new(Sky130Layer::Npc, poly.expand_all(95)))?;
        cell.draw(Shape::new(Sky130Layer::Psdm, poly.expand_all(110)))?;
        let imp = poly.expand_all(200);
        let imp = if imp.height() < RPM_W { imp.with_vspan(Span::from_center_span(imp.center().y, RPM_W)) } else { imp };
        cell.draw(Shape::new(if kind == ResKind::High { Sky130Layer::Rpm } else { Sky130Layer::Urpm }, imp))?;
        // magic grows each contact head XPC_GROW into the marker (sky130A.tech cifinput
        // `xpolyterm ... grow 60`); start the marker that much early so the extracted L
        // is the deck's L
        cell.draw(Shape::new(Sky130Layer::PolyRes, Rect::from_sides(x0 - XPC_GROW, 0, x1 + XPC_GROW, w)))?;

        // li heads grown onto the routing grid, as upstream
        let stack = cell.ctx().get_installation::<LayerStack<PdkLayer<Sky130Layer>>>().unwrap();
        let slice = stack.slice(0..2);
        let on_grid = |r: Rect| slice.lcm_to_physical_rect(slice.expand_to_lcm_units(r)).expand_all(slice.layer(0).line() / 2);
        let (p, n) = (Shape::new(Sky130Layer::Li1, on_grid(p)), Shape::new(Sky130Layer::Li1, on_grid(n)));
        cell.draw(p.clone())?;
        cell.draw(n.clone())?;
        let lcm = lcm_bbox(cell);
        let b = Shape::new(Sky130Layer::Pwell, lcm);
        cell.draw(b.clone())?;
        Ok((
            ResistorIoView { p: PortGeometry::new(p), n: PortGeometry::new(n), b: PortGeometry::new(b) },
            PrimData { lcm_bbox: lcm },
        ))
    }
}

impl AtollPrimitive for Res {
    type Schema = Sky130;
    fn outline(cell: &substrate::layout::TransformedCell<Self>) -> Rect {
        cell.data().lcm_bbox
    }
}

impl Schematic for Res {
    type Schema = Sky130;
    type NestedData = ();
    fn schematic(
        &self,
        io: &substrate::types::schematic::IoNodeBundle<Self>,
        cell: &mut substrate::schematic::CellBuilder<Sky130>,
    ) -> Result<()> {
        let k = if self.0.kind == ResKind::High { "high" } else { "xhigh" };
        raw_prim(cell, &format!("sky130_fd_pr__res_{k}_po"), &[("P", io.p), ("N", io.n), ("B", io.b)]);
        Ok(())
    }
}
