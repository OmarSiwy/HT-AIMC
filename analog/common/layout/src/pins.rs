//! Boundary pins: every port gets a labelled stub on the cell edge, placed by the
//! block's `layout/interface.json` (the Philis file: `{"pins": [{"net", "side",
//! "frac"}]}`; its `die` is ignored, the cell is as big as it needs to be). Ports it
//! does not place go on the west edge in deck order.
//!
//! [`place`] widens the outline by a pin frame of `FRAME` LCM units, hands one grid point
//! per port to the router as that net, and draws the stub from it to the edge: met1 on
//! east/west, met2 on north/south. Parents route to the stubs; LVS keeps port names.

use std::collections::{BTreeMap, HashSet};

use atoll::TileBuilder;
use atoll::grid::AtollLayer;
use layir::Shape;
use substrate::error::Result;
use substrate::geometry::dir::Dir;
use substrate::geometry::rect::Rect;
use substrate::types::layout::PortGeometry;
use substrate::types::Signal;
use substrate::types::schematic::Node;
use substrate::{layout, schematic};

use crate::deck::analog_dir;

/// LCM units between the placed cell and its edge: the pin column/row sits strictly
/// outside everything the tiles drew.
const FRAME: i64 = 2;

/// A cell edge.
#[derive(Clone, Copy, Debug, Hash, PartialEq, Eq)]
pub enum Side {
    /// Top edge.
    North,
    /// Bottom edge.
    South,
    /// Right edge.
    East,
    /// Left edge.
    West,
}

/// Where one port sits: an edge and a fraction along it (0 = left/bottom), in 1/1000.
pub type Spot = (Side, i64);

/// Pin spots of `block` by port name, from `analog/<block>/layout/interface.json`
/// (empty when the block has none).
pub fn interface(block: &str) -> BTreeMap<String, Spot> {
    let path = analog_dir().join(block).join("layout/interface.json");
    let Ok(text) = std::fs::read_to_string(&path) else { return BTreeMap::new() };
    let json: serde_json::Value = serde_json::from_str(&text).unwrap_or_else(|e| panic!("{}: {e}", path.display()));
    let mut out = BTreeMap::new();
    for pin in json["pins"].as_array().into_iter().flatten() {
        let side = match pin["side"].as_str() {
            Some("north") => Side::North,
            Some("south") => Side::South,
            Some("east") => Side::East,
            Some("west") => Side::West,
            _ => continue, // `at: [x, y]` pins are die coordinates: fall back to west
        };
        let frac = pin["frac"].as_f64().unwrap_or(0.5);
        out.insert(pin["net"].as_str().expect("pin without net").to_string(), (side, (frac * 1000.0).round() as i64));
    }
    out
}

/// Draws a pin per `(name, net)` on the edge of `outline` (physical, LCM-aligned) at
/// its spot in `spots`; returns the widened outline and the pin geometry in `ports`
/// order — use it as the port's layout geometry so the label lands on the edge.
#[allow(clippy::type_complexity)]
pub fn place<S: schematic::schema::Schema + layout::schema::Schema>(
    cell: &mut TileBuilder<'_, S>,
    outline: Rect,
    ports: &[(&str, Node)],
    spots: &BTreeMap<String, Spot>,
) -> Result<(Rect, Vec<PortGeometry<S::Layer>>)> {
    let stack = cell.layer_stack.clone();
    let (px, py) = (stack.layer(0).pitch(), stack.layer(1).pitch());
    assert_eq!(stack.layer(2).pitch(), px, "met2 must share the li track pitch");
    let outer = outline.expand_dir(Dir::Horiz, FRAME * px).expand_dir(Dir::Vert, FRAME * py);
    // pin tracks: one outside the placed cell on each side
    let (x0, x1, y0, y1) = (outline.left() / px - 1, outline.right() / px + 1, outline.bot() / py - 1, outline.top() / py + 1);
    let mut used: HashSet<(Side, i64)> = HashSet::new();
    let mut west = 0;
    let n_west = ports.iter().filter(|(p, _)| !spots.contains_key(*p)).count() as i64;
    let mut out = Vec::new();
    for &(name, net) in ports {
        let (side, frac) = spots.get(name).copied().unwrap_or_else(|| {
            west += 1;
            (Side::West, 1000 * west / (n_west + 1))
        });
        let (lo, hi) = match side {
            Side::East | Side::West => (y0 + 1, y1 - 1),
            Side::North | Side::South => (x0 + 1, x1 - 1),
        };
        // two ports at one spot: the nearest free track
        let ideal = lo + ((hi - lo) * frac + 500) / 1000;
        let t = (0..=hi - lo)
            .flat_map(|d| [ideal + d, ideal - d])
            .find(|t| (lo..=hi).contains(t) && !used.contains(&(side, *t)))
            .unwrap_or_else(|| panic!("no free track for pin {name} on {side:?}"));
        used.insert((side, t));
        let (layer, (gx, gy)) = match side {
            Side::West => (1, (x0, t)),
            Side::East => (1, (x1, t)),
            Side::South => (2, (t, y0)),
            Side::North => (2, (t, y1)),
        };
        // reserve the stub's grid points out to the edge track too
        let edge = match side {
            Side::West => Rect::from_sides(gx - 1, gy, gx, gy),
            Side::East => Rect::from_sides(gx, gy, gx + 1, gy),
            Side::South => Rect::from_sides(gx, gy - 1, gx, gy),
            Side::North => Rect::from_sides(gx, gy, gx, gy + 1),
        };
        // a net of its own, joined to `net`: the router only connects distinct net ids,
        // so a pin sharing the port's id would be left floating
        let pin = cell.signal(format!("pin_{name}"), Signal);
        cell.connect(pin, net);
        cell.assign_grid_points(Some(pin), layer, edge);
        let half = stack.layer(layer).line() / 2;
        let (cx, cy) = (gx * px, gy * py);
        let stub = match side {
            Side::West => Rect::from_sides(outer.left(), cy - half, cx + half, cy + half),
            Side::East => Rect::from_sides(cx - half, cy - half, outer.right(), cy + half),
            Side::South => Rect::from_sides(cx - half, outer.bot(), cx + half, cy + half),
            Side::North => Rect::from_sides(cx - half, cy - half, cx + half, outer.top()),
        };
        let shape = Shape::new(stack.layer(layer).layer.clone(), stub);
        cell.layout.draw(shape.clone())?;
        out.push(PortGeometry::new(shape));
    }
    Ok((outer, out))
}
