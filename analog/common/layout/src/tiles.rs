//! PDK-agnostic tile parameter and IO types shared by every generator.
//!
//! Adapted from the substrate2 `strongarm` example (BSD-3, Substrate Labs), with gate
//! length, MIM and poly-resistor tiles added. Sizes are nanometres and come from the
//! block's deck ([`crate::deck`]), never typed into a generator.

use substrate::{
    geometry::dir::Dir,
    types::{InOut, Io, Signal},
};

/// The kind of tile.
#[derive(Clone, Copy, Debug, Hash, PartialEq, Eq)]
pub enum TileKind {
    /// An n-type tile.
    N,
    /// A p-type tile.
    P,
}

/// The IO of a tap.
#[derive(Default, Debug, Clone, Copy, Io)]
pub struct TapIo {
    /// The tap contact.
    pub x: InOut<Signal>,
}

/// MOS tile parameters.
#[derive(Clone, Copy, Debug, Hash, PartialEq, Eq)]
pub struct MosTileParams {
    /// Whether MOS is n-channel or p-channel.
    pub tile_kind: TileKind,
    /// Total device width over all fingers, nm (the deck's W x m).
    pub w: i64,
    /// Gate length, nm. Any length: the tile widens its gate pitch to fit.
    pub l: i64,
    /// Number of fingers; `w / nf` must land on the 5 nm grid.
    pub nf: i64,
}

impl MosTileParams {
    /// Creates a new [`MosTileParams`].
    pub fn new(tile_kind: TileKind, w: i64, l: i64, nf: i64) -> Self {
        Self { tile_kind, w, l, nf }
    }

    /// The same device folded into `nf` fingers (a layout choice; LVS merges the
    /// fingers back into the deck's single device).
    pub fn nf(self, nf: i64) -> Self {
        assert_eq!(self.w % (5 * nf), 0, "W = {} nm does not split into {nf} fingers on the 5 nm grid", self.w);
        Self { nf, ..self }
    }
}

/// Tap tile parameters.
#[derive(Clone, Copy, Debug, Hash, PartialEq, Eq)]
pub struct TapTileParams {
    /// The kind of tap.
    pub kind: TileKind,
    /// The direction in which this tap extends.
    pub dir: Dir,
    /// Number of layer 0/1 tracks this horizontal/vertical tap must span.
    pub span: i64,
}

impl TapTileParams {
    /// Creates a new [`TapTileParams`].
    pub fn new(kind: TileKind, dir: Dir, span: i64) -> Self {
        Self { kind, dir, span }
    }
}

/// The IO of a three-terminal resistor.
#[derive(Default, Debug, Clone, Copy, Io)]
pub struct ResistorIo {
    /// The positive terminal.
    pub p: InOut<Signal>,
    /// The negative terminal.
    pub n: InOut<Signal>,
    /// The body terminal.
    pub b: InOut<Signal>,
}

/// Poly resistor flavour (sheet resistance class of the PDK).
#[derive(Clone, Copy, Debug, Hash, PartialEq, Eq)]
pub enum ResKind {
    /// High sheet resistance.
    High,
    /// Extra-high sheet resistance.
    XHigh,
}

/// Poly resistor tile parameters.
#[derive(Clone, Copy, Debug, Hash, PartialEq, Eq)]
pub struct ResTileParams {
    /// The flavour.
    pub kind: ResKind,
    /// Body width, nm (fixed per PDK model).
    pub w: i64,
    /// Body length between the contact heads, nm.
    pub l: i64,
}

/// MIM capacitor tile parameters: the top-plate (cap layer) rectangle, nm.
#[derive(Clone, Copy, Debug, Hash, PartialEq, Eq)]
pub struct MimTileParams {
    /// Width, nm.
    pub w: i64,
    /// Length, nm.
    pub l: i64,
}
