//! Analog layout generators on substrate2 — the signoff layout route next to Philis.
//!
//! - `deck`: reads `analog/<block>/netlist/<block>.spice`; every size comes from it.
//! - `pins`: labelled boundary pins placed from `analog/<block>/layout/interface.json`.
//! - `tiles`: PDK-agnostic parameter/IO types (MOS, tap, MIM, poly resistor).
//! - `tech`: the [`tech::Tech`] trait generators are written against, plus per-PDK
//!   bindings (`tech::sky130` only: the registry ships no other PDK crate).
//!
//! Block generators live next to their block, `analog/<block>/layout/<block>.rs`, and
//! are binaries of this crate (see Cargo.toml and README.md).

pub mod deck;
pub mod pins;
pub mod tech;
pub mod tiles;
