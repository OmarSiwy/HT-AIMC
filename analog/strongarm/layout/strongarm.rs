//! strongarm layout (substrate2). NMOS stack in a p guard ring (vss), PMOS row in an
//! n guard ring (vdd) above it; the two halves side by side, mirrored about the centre:
//!
//!     n ring [ rstp xpp | xpn rstn ]
//!     p ring [ xnp | xnn ]  [ inp | inn ]  [ tail ]
//!
//! Ports are edge pins placed by layout/interface.json. Sizes: netlist/strongarm.spice. Folding (nf) is the only layout choice here: the
//! input pair and the PMOS latch fold to keep each row near-square.
//!
//!     make -C analog/strongarm/build/layout gen gen-drc gen-lvs gen-pex

use std::any::Any;
use std::collections::BTreeMap;
use std::marker::PhantomData;

use analog_layout::deck::{Deck, gds_path};
use analog_layout::pins::{self, Spot};
use analog_layout::tech::Tech;
use analog_layout::tech::sky130::Sky130Tech;
use analog_layout::tiles::{MosTileParams, TileKind};
use atoll::route::GreedyRouter;
use atoll::{Orientation, Tile, TileBuilder, TileData};
use substrate::arcstr::{self, ArcStr};
use substrate::block::Block;
use substrate::error::Result;
use substrate::geometry::align::AlignMode;
use substrate::geometry::rect::Rect;
use substrate::types::codegen::{PortGeometryBundle, View};
use substrate::types::schematic::{IoNodeBundle, NodeBundle};
use substrate::types::{InOut, Io, MosIo, Signal};

/// Ports of `.subckt strongarm`, same names.
#[derive(Debug, Default, Clone, Io)]
pub struct StrongArmIo {
    pub vinp: InOut<Signal>,
    pub vinn: InOut<Signal>,
    pub outp: InOut<Signal>,
    pub outn: InOut<Signal>,
    pub clk: InOut<Signal>,
    pub vdd: InOut<Signal>,
    pub vss: InOut<Signal>,
}

/// Device sizes, by deck name.
#[derive(Clone, Copy, Debug, Hash, PartialEq, Eq)]
struct Sizes {
    tail: MosTileParams,
    input: MosTileParams,
    xn: MosTileParams,
    xp: MosTileParams,
    rst: MosTileParams,
}

#[derive_where::derive_where(Clone, Debug, Hash, PartialEq, Eq)]
struct StrongArm<T>(Sizes, BTreeMap<String, Spot>, PhantomData<fn() -> T>);

impl<T: Any> Block for StrongArm<T> {
    type Io = StrongArmIo;
    fn name(&self) -> ArcStr {
        arcstr::literal!("strongarm")
    }
    fn io(&self) -> Self::Io {
        Default::default()
    }
}

impl<T: Tech> Tile for StrongArm<T> {
    type Schema = T::Schema;
    type NestedData = ();
    type LayoutBundle = View<StrongArmIo, PortGeometryBundle<T::Schema>>;
    type LayoutData = ();

    fn tile<'a>(&self, io: &'a IoNodeBundle<Self>, cell: &mut TileBuilder<'a, T::Schema>) -> Result<TileData<Self>> {
        let s = self.0;
        let (tail, drn_p, drn_n) = (cell.signal("tail", Signal), cell.signal("drn_p", Signal), cell.signal("drn_n", Signal));
        let mut mos = |p, d, g, src, b| cell.generate_connected(T::mos(p), NodeBundle::<MosIo> { d, g, s: src, b });
        let xtail = mos(s.tail, tail, io.clk, io.vss, io.vss);
        let inp = mos(s.input, drn_p, io.vinp, tail, io.vss);
        let inn = mos(s.input, drn_n, io.vinn, tail, io.vss);
        let xnp = mos(s.xn, io.outp, io.outn, drn_p, io.vss);
        let xnn = mos(s.xn, io.outn, io.outp, drn_n, io.vss);
        let xpp = mos(s.xp, io.outp, io.outn, io.vdd, io.vdd);
        let xpn = mos(s.xp, io.outn, io.outp, io.vdd, io.vdd);
        let rstp = mos(s.rst, io.outp, io.clk, io.vdd, io.vdd);
        let rstn = mos(s.rst, io.outn, io.clk, io.vdd, io.vdd);

        // NMOS stack: the pair on a row, the cross-coupled pair above, the tail below;
        // right-hand devices mirrored so the halves match
        let inn = inn.orient(Orientation::ReflectHoriz).align(&inp, AlignMode::ToTheRight, 0).align(&inp, AlignMode::Bottom, 0);
        let row = inp.lcm_bounds().union(inn.lcm_bounds());
        let xnp = xnp.align_rect(row, AlignMode::Above, 0).align(&inp, AlignMode::Right, 0);
        let xnn = xnn.orient(Orientation::ReflectHoriz).align(&xnp, AlignMode::ToTheRight, 0).align(&xnp, AlignMode::Bottom, 0);
        let xtail = xtail.align_rect(row, AlignMode::Beneath, 0).align_rect(row, AlignMode::CenterHorizontal, 0);
        let n_inner = [&inp, &inn, &xnp, &xnn].iter().fold(xtail.physical_bounds(), |r, i| r.union(i.physical_bounds()));
        let n_lcm = [&inp, &inn, &xnp, &xnn].iter().fold(xtail.lcm_bounds(), |r, i| r.union(i.lcm_bounds()));

        // PMOS row above both guard rings (2 LCM units each)
        let mid = inp.lcm_bounds().right();
        let xpp = xpp.align_rect(n_lcm, AlignMode::Above, 4).align_rect(Rect::from_sides(mid, 0, mid, 0), AlignMode::Right, 0);
        let xpn = xpn.orient(Orientation::ReflectHoriz).align(&xpp, AlignMode::ToTheRight, 0).align(&xpp, AlignMode::Bottom, 0);
        let rstp = rstp.align(&xpp, AlignMode::ToTheLeft, 0).align(&xpp, AlignMode::Bottom, 0);
        let rstn = rstn.orient(Orientation::ReflectHoriz).align(&xpn, AlignMode::ToTheRight, 0).align(&xpn, AlignMode::Bottom, 0);
        let p_inner = [&xpn, &rstp, &rstn].iter().fold(xpp.physical_bounds(), |r, i| r.union(i.physical_bounds()));

        let (n_outer, _) = T::guard_ring(cell, n_inner, TileKind::P, io.vss)?;
        let (p_outer, _) = T::guard_ring(cell, p_inner, TileKind::N, io.vdd)?;
        for i in [xtail, inp, inn, xnp, xnn, xpp, xpn, rstp, rstn] {
            cell.draw(i)?;
        }
        cell.set_top_layer(2);
        cell.set_router(GreedyRouter::new());
        cell.set_via_maker(T::via_maker());

        let ports = [
            ("vinp", io.vinp),
            ("vinn", io.vinn),
            ("outp", io.outp),
            ("outn", io.outn),
            ("clk", io.clk),
            ("vdd", io.vdd),
            ("vss", io.vss),
        ];
        let (outline, pins) = pins::place(cell, n_outer.union(p_outer), &ports, &self.1)?;
        let [vinp, vinn, outp, outn, clk, vdd, vss] = pins.try_into().unwrap();
        Ok(TileData {
            nested_data: (),
            layout_bundle: StrongArmIoView { vinp, vinn, outp, outn, clk, vdd, vss },
            layout_data: (),
            outline,
        })
    }
}

fn main() -> Result<()> {
    let deck = Deck::read("strongarm");
    let sizes = Sizes {
        tail: deck.mos("Xtail"),
        input: deck.mos("Xinp").nf(4),
        xn: deck.mos("Xxnp").nf(2),
        xp: deck.mos("Xxpp").nf(2),
        rst: deck.mos("Xrstp"),
    };
    // the halves must match: one size per mirrored pair
    for (a, b) in [("Xinp", "Xinn"), ("Xxnp", "Xxnn"), ("Xxpp", "Xxpn"), ("Xrstp", "Xrstn")] {
        assert_eq!(deck.mos(a), deck.mos(b), "{a} and {b} differ in the deck");
    }
    let path = gds_path("strongarm");
    Sky130Tech::write_gds(StrongArm::<Sky130Tech>(sizes, pins::interface("strongarm"), PhantomData), &path)?;
    println!("gen: {}", path.display());
    Ok(())
}
