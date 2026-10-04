//! The PDK abstraction: one `Tech` trait every block generator is written against.
//! Bind a new PDK by implementing `Tech` (see `sky130.rs`); a gf180 binding needs a
//! gf180 substrate PDK crate, which the registry does not ship yet.
//!
//! Pattern follows the substrate2 `strongarm` example's `StrongArmImpl`, widened to the
//! device set the analog blocks use (any-L MOS, taps and guard rings, MIM, poly R).

use std::any::Any;
use std::path::Path;

use atoll::route::ViaMaker;
use atoll::{AtollPrimitive, Tile, TileBuilder};
use substrate::block::Block;
use substrate::error::Result;
use substrate::geometry::rect::Rect;
use substrate::types::codegen::{PortGeometryBundle, View};
use substrate::types::layout::PortGeometry;
use substrate::types::schematic::Node;
use substrate::types::{MosIo, TwoTerminalIo};
use substrate::layout::Layout;
use substrate::{layout, schematic};

use crate::tiles::{MimTileParams, MosTileParams, ResTileParams, ResistorIo, TapIo, TapTileParams, TileKind};

pub mod sky130;

/// The tile types of a technology, all with the same schema.
pub trait Tech: Any + Sized {
    /// The combined schematic + layout schema for this technology.
    type Schema: layout::schema::Schema + schematic::schema::Schema;

    /// The MOS tile (any gate length in [`MosTileParams`]).
    type MosTile: Tile<Schema = Self::Schema, LayoutBundle = View<MosIo, PortGeometryBundle<Self::Schema>>>
        + Block<Io = MosIo>
        + Clone;

    /// The tap tile.
    type TapTile: Tile<Schema = Self::Schema, LayoutBundle = View<TapIo, PortGeometryBundle<Self::Schema>>>
        + Block<Io = TapIo>
        + Clone;

    /// The MIM capacitor primitive (`p` top plate, `n` bottom plate).
    type MimTile: AtollPrimitive<Schema = Self::Schema>
        + Layout<Bundle = View<TwoTerminalIo, PortGeometryBundle<Self::Schema>>>
        + Block<Io = TwoTerminalIo>
        + Clone;

    /// The poly resistor primitive.
    type ResTile: AtollPrimitive<Schema = Self::Schema>
        + Layout<Bundle = View<ResistorIo, PortGeometryBundle<Self::Schema>>>
        + Block<Io = ResistorIo>
        + Clone;

    /// A PDK-specific via maker for the router.
    type ViaMaker: ViaMaker<<Self::Schema as layout::schema::Schema>::Layer>;

    /// Creates an instance of the MOS tile.
    fn mos(params: MosTileParams) -> Self::MosTile;
    /// Creates an instance of the tap tile.
    fn tap(params: TapTileParams) -> Self::TapTile;
    /// Creates a MIM capacitor (instantiate with `generate_primitive`).
    fn mim(params: MimTileParams) -> Self::MimTile;
    /// Creates a poly resistor (instantiate with `generate_primitive`).
    fn res(params: ResTileParams) -> Self::ResTile;
    /// Creates a PDK-specific via maker.
    fn via_maker() -> Self::ViaMaker;

    /// Draws a closed tap ring of `kind` around `inner` (physical, on the tile's LCM
    /// grid) tied to `net`; returns the ring's outer bounds (fold into the tile outline)
    /// and its li as port geometry. An n ring also draws the n-well over everything it
    /// encloses. `inner` must not hold a tap of the ring's own kind at its edge.
    #[allow(clippy::type_complexity)]
    fn guard_ring(
        cell: &mut TileBuilder<'_, Self::Schema>,
        inner: Rect,
        kind: TileKind,
        net: Node,
    ) -> Result<(Rect, PortGeometry<<Self::Schema as layout::schema::Schema>::Layer>)>;

    /// Writes `block` as GDS with this PDK's layer map; the top cell is `block.name()`.
    fn write_gds<B: Tile<Schema = Self::Schema> + Clone>(block: B, path: &Path) -> Result<()>;
}
