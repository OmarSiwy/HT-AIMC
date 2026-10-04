//! cmos_switch layout (substrate2): the transmission gate as one column —
//! NMOS / p-tap / PMOS / n-tap, bottom to top — so both bulk-only rails get real taps
//! and the PMOS n-well abuts its n-tap's; ports are edge pins placed by
//! layout/interface.json. Sizes: netlist/cmos_switch.spice.
//!
//!     make -C analog/cmos_switch/build/layout gen gen-drc gen-lvs gen-pex

use std::any::Any;
use std::collections::BTreeMap;
use std::marker::PhantomData;

use analog_layout::deck::{Deck, gds_path};
use analog_layout::pins::{self, Spot};
use analog_layout::tech::Tech;
use analog_layout::tech::sky130::Sky130Tech;
use analog_layout::tiles::{MosTileParams, TapTileParams, TileKind};
use atoll::route::GreedyRouter;
use atoll::{Tile, TileBuilder, TileData};
use substrate::arcstr::{self, ArcStr};
use substrate::block::Block;
use substrate::error::Result;
use substrate::geometry::align::AlignMode;
use substrate::geometry::dir::Dir;
use substrate::types::codegen::{PortGeometryBundle, View};
use substrate::types::schematic::{IoNodeBundle, NodeBundle};
use substrate::types::{InOut, Io, MosIo, Signal};

/// Ports of `.subckt cmos_switch`, same names.
#[derive(Debug, Default, Clone, Io)]
pub struct CmosSwitchIo {
    pub in_: InOut<Signal>,
    pub out: InOut<Signal>,
    pub ctrl: InOut<Signal>,
    pub ctrl_b: InOut<Signal>,
    pub vdd: InOut<Signal>,
    pub vss: InOut<Signal>,
}

#[derive_where::derive_where(Clone, Debug, Hash, PartialEq, Eq)]
struct CmosSwitch<T> {
    n: MosTileParams,
    p: MosTileParams,
    pins: BTreeMap<String, Spot>,
    _t: PhantomData<fn() -> T>,
}

impl<T: Any> Block for CmosSwitch<T> {
    type Io = CmosSwitchIo;
    fn name(&self) -> ArcStr {
        arcstr::literal!("cmos_switch")
    }
    fn io(&self) -> Self::Io {
        Default::default()
    }
}

impl<T: Tech> Tile for CmosSwitch<T> {
    type Schema = T::Schema;
    type NestedData = ();
    type LayoutBundle = View<CmosSwitchIo, PortGeometryBundle<T::Schema>>;
    type LayoutData = ();

    fn tile<'a>(&self, io: &'a IoNodeBundle<Self>, cell: &mut TileBuilder<'a, T::Schema>) -> Result<TileData<Self>> {
        let n = cell.generate_connected(T::mos(self.n), NodeBundle::<MosIo> { d: io.in_, g: io.ctrl, s: io.out, b: io.vss });
        let p = cell.generate_connected(T::mos(self.p), NodeBundle::<MosIo> { d: io.in_, g: io.ctrl_b, s: io.out, b: io.vdd });
        let span = n.lcm_bounds().width().max(p.lcm_bounds().width()) - 1;
        let ptap = cell.generate(T::tap(TapTileParams::new(TileKind::P, Dir::Horiz, span)));
        let ntap = cell.generate(T::tap(TapTileParams::new(TileKind::N, Dir::Horiz, span)));
        cell.connect(ptap.io().x, io.vss);
        cell.connect(ntap.io().x, io.vdd);

        let ptap = ptap.align_rect(n.lcm_bounds(), AlignMode::Above, 0).align_rect(n.lcm_bounds(), AlignMode::Left, 0);
        let p = p.align_rect(ptap.lcm_bounds(), AlignMode::Above, 0).align_rect(ptap.lcm_bounds(), AlignMode::Left, 0);
        let ntap = ntap.align_rect(p.lcm_bounds(), AlignMode::Above, 0).align_rect(p.lcm_bounds(), AlignMode::Left, 0);

        let placed = [n.physical_bounds(), p.physical_bounds(), ptap.physical_bounds(), ntap.physical_bounds()]
            .into_iter()
            .reduce(|a, b| a.union(b))
            .unwrap();
        for i in [n, p] {
            cell.draw(i)?;
        }
        for i in [ptap, ntap] {
            cell.draw(i)?;
        }
        cell.set_top_layer(2);
        cell.set_router(GreedyRouter::new());
        cell.set_via_maker(T::via_maker());

        let ports = [
            ("in_", io.in_),
            ("out", io.out),
            ("ctrl", io.ctrl),
            ("ctrl_b", io.ctrl_b),
            ("vdd", io.vdd),
            ("vss", io.vss),
        ];
        let (outline, pins) = pins::place(cell, placed, &ports, &self.pins)?;
        let [in_, out, ctrl, ctrl_b, vdd, vss] = pins.try_into().unwrap();
        Ok(TileData {
            nested_data: (),
            layout_bundle: CmosSwitchIoView { in_, out, ctrl, ctrl_b, vdd, vss },
            layout_data: (),
            outline,
        })
    }
}

fn main() -> Result<()> {
    let deck = Deck::read("cmos_switch");
    let block = CmosSwitch::<Sky130Tech> {
        n: deck.mos("Xcmos_switch_n"),
        p: deck.mos("Xcmos_switch_p"),
        pins: pins::interface("cmos_switch"),
        _t: PhantomData,
    };
    let path = gds_path("cmos_switch");
    Sky130Tech::write_gds(block, &path)?;
    println!("gen: {}", path.display());
    Ok(())
}
