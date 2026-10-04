//! The block's source deck, `analog/<block>/netlist/<block>.spice` — every size a
//! generator lays out is read from it, so LVS compares the layout against the same
//! numbers `devices.py` emitted. Generators name devices, never dimensions.

use std::collections::HashMap;
use std::path::PathBuf;

use crate::tiles::{MimTileParams, MosTileParams, ResKind, ResTileParams, TileKind};

/// `analog/` of this repo.
pub fn analog_dir() -> PathBuf {
    PathBuf::from(concat!(env!("CARGO_MANIFEST_DIR"), "/../..")).canonicalize().expect("analog/ dir")
}

/// Where `make gen` expects a block's GDS: `analog/<block>/output/gen/<block>.gds`.
pub fn gds_path(block: &str) -> PathBuf {
    analog_dir().join(block).join("output/gen").join(format!("{block}.gds"))
}

/// One device card of the deck.
#[derive(Debug, Clone)]
pub struct Device {
    /// Instance name as written (`Xinp`).
    pub name: String,
    /// Terminal nets in card order.
    pub nets: Vec<String>,
    /// Model (subckt) name.
    pub model: String,
    params: HashMap<String, String>,
}

impl Device {
    /// A length parameter in nm. Plain numbers are um (sky130 decks), SI-suffixed or
    /// sub-1e-3 values are metres — the same rule as `analog/common/pex.py`.
    pub fn nm(&self, key: &str) -> i64 {
        let v = self.params.get(key).unwrap_or_else(|| panic!("{}: no {key}=", self.name));
        let (num, scale) = match v.find(|c: char| c.is_ascii_alphabetic() && c != 'e') {
            Some(i) => (&v[..i], match &v[i..] { "u" => 1e3, "n" => 1.0, "m" => 1e6, s => panic!("{}: unit {s}", self.name) }),
            None => (v.as_str(), 1e3),
        };
        let x: f64 = num.parse().unwrap_or_else(|_| panic!("{}: {key}={v}", self.name));
        (if x < 1e-3 { x * 1e9 } else { x * scale }).round() as i64
    }

    fn count(&self, key: &str) -> i64 {
        self.params.get(key).map_or(1, |v| v.parse().unwrap())
    }
}

/// The top `.subckt` of a block's deck.
#[derive(Debug, Clone)]
pub struct Deck {
    /// Port names in order.
    pub ports: Vec<String>,
    /// Device cards in order.
    pub devices: Vec<Device>,
}

impl Deck {
    /// Reads `.subckt <block>` from `analog/<block>/netlist/<block>.spice`.
    pub fn read(block: &str) -> Self {
        let path = analog_dir().join(block).join("netlist").join(format!("{block}.spice"));
        let text = std::fs::read_to_string(&path)
            .unwrap_or_else(|e| panic!("{}: {e} — make -C analog/{block}/build/schematic netlist", path.display()));
        let mut lines: Vec<String> = Vec::new();
        for raw in text.lines().map(str::trim).filter(|l| !l.is_empty() && !l.starts_with('*')) {
            match raw.strip_prefix('+') {
                Some(cont) if !lines.is_empty() => *lines.last_mut().unwrap() += &format!(" {cont}"),
                _ => lines.push(raw.to_string()),
            }
        }
        let start = lines.iter().position(|l| {
            let t: Vec<_> = l.split_whitespace().collect();
            t.len() > 1 && t[0].eq_ignore_ascii_case(".subckt") && t[1] == block
        });
        let start = start.unwrap_or_else(|| panic!("{}: no .subckt {block}", path.display()));
        let ports = lines[start].split_whitespace().skip(2).filter(|t| !t.contains('=')).map(String::from).collect();
        let devices = lines[start + 1..]
            .iter()
            .take_while(|l| !l.to_lowercase().starts_with(".ends"))
            .filter(|l| !l.starts_with('.'))
            .map(|l| {
                let (pos, kv): (Vec<&str>, Vec<&str>) = l.split_whitespace().partition(|t| !t.contains('='));
                Device {
                    name: pos[0].to_string(),
                    nets: pos[1..pos.len() - 1].iter().map(|s| s.to_string()).collect(),
                    model: pos[pos.len() - 1].to_string(),
                    params: kv.iter().filter_map(|t| t.split_once('=')).map(|(k, v)| (k.to_lowercase(), v.to_string())).collect(),
                }
            })
            .collect();
        Self { ports, devices }
    }

    /// The device card named `name`.
    pub fn device(&self, name: &str) -> &Device {
        self.devices.iter().find(|d| d.name == name).unwrap_or_else(|| panic!("no device {name} in deck"))
    }

    /// A MOSFET card as tile parameters: total width W x m, the deck's nf.
    pub fn mos(&self, name: &str) -> MosTileParams {
        let d = self.device(name);
        let kind = if d.model.contains("nfet") {
            TileKind::N
        } else if d.model.contains("pfet") {
            TileKind::P
        } else {
            panic!("{name}: {} is not a nfet/pfet", d.model)
        };
        MosTileParams::new(kind, d.nm("w") * d.count("m"), d.nm("l"), d.count("nf"))
    }

    /// A poly-resistor card: the flavour and the fixed body width come from the model
    /// name (`..._po_0p35` = 0.35 um), the length from `L=`.
    pub fn res(&self, name: &str) -> ResTileParams {
        let d = self.device(name);
        let kind = if d.model.contains("xhigh_po") { ResKind::XHigh } else if d.model.contains("high_po") { ResKind::High } else {
            panic!("{name}: {} is not a high/xhigh poly resistor", d.model)
        };
        let w = d.model.rsplit('_').next().unwrap().replace('p', ".");
        let w = (w.parse::<f64>().unwrap_or_else(|_| panic!("{name}: no width suffix on {}", d.model)) * 1e3).round() as i64;
        ResTileParams { kind, w, l: d.nm("l") }
    }

    /// A MIM capacitor card (`W=` x `L=`).
    pub fn mim(&self, name: &str) -> MimTileParams {
        let d = self.device(name);
        MimTileParams { w: d.nm("w"), l: d.nm("l") }
    }
}
