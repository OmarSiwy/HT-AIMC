#!/usr/bin/env python3
"""
cktImg netlist placement -> xschem schematic.

Runs `cktimg-json --target xschem_sky130.json` on a SPICE deck and turns the placed
geometry it reports into a `.sch` file that xschem can open, edit and netlist back to
sky130 devices.

## Why not cktImg's own `cktimg-xschem`

It writes xschem's generic `devices/nmos4.sym`/`res.sym` with a fixed built-in mapping:
no sky130 symbols (so `XM1 ... sky130_fd_pr__nfet_01v8` netlists back as an `M` card the
sky130 models cannot simulate), no target manifest, and nothing at all for a subcircuit
instance (its pins become bare labels, so the block vanishes from the netlist). This
script keeps the manifest, the real PDK symbols, the block symbols and the self-check.

## What lives where

  * `xschem_sky130.json` -- a cktImg target manifest (cktImg's docs/TARGETS.md). It is
    the whole symbol mapping: per cktImg class, the `.sym` path, the pin offsets
    (`style.pin_xy`, in the manifest's pin order), the attribute template
    (`style.attrs`), and for MOSFETs the default model/W/L and bulk pin. Adding a class
    or changing a symbol is a JSON edit; cktImg validates class and terminal names.
    `unmapped.mode = box` sends every other class -- in practice `block:<subckt>` -- here
    with `style.box`, and the script draws it a symbol (see `box_symbol`).
  * `cktimg_sky130.zon` -- cktImg's own config: strict symbol geometry.
  * this file -- the xschem-specific geometry and nothing symbol-specific.

`sym` and `attrs` are `str.format` templates over: name, ref (name without a leading
`x`, since sky130 symbols add their own `X` prefix), value, net (first pin's net), cell
(the class without `block:`), and, for classes whose style carries `model`, model/w/l
from the device's card.

## The mismatch this file exists to absorb

cktImg draws its own MOSFET with d/g/s 20 grid units from the centre. sky130's
`nfet_01v8.sym` puts D(20,-30), G(-20,0), S(20,30) and a fourth bulk pin cktImg does not
draw. The pitch, the offsets and the pin count do not line up, so:

  * Orientation is *derived*, not copied. `best_orientation` tries all eight xschem
    placements and keeps whichever lands the pins closest to where cktImg put them,
    which stays correct if either project redefines what "rot=1" means.

  * Whatever offset survives is absorbed by a stub wire. The same `rotate()` that
    computes a pin's position is the one written into the `C` line, so a stub spans
    exactly the gap. A bad orientation guess costs looks, never a net.

  * The bulk net is cktImg's `devices[].bulk`; it is labelled on the symbol's B pin.
    Model and W/L come from the card text cktImg reports as `value`.

## Scale

cktImg places on a 40-unit grid with MOS/R/C pins 20 from the centre; sky130's pins are
30 from the centre. `units.scale` = 1.5 makes the two coincide along the device axis
(cktImg passes it through and never applies it); `--scale` overrides it.
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
DEFAULT_CONFIG = HERE / "cktimg_sky130.zon"
DEFAULT_TARGET = HERE / "xschem_sky130.json"
LAB_PIN = "devices/lab_pin.sym"
PDK_PREFIX = "sky130_fd_pr__"
VERSION = "v {xschem version=3.4.5 file_version=1.2}\n"
HEADER = VERSION + "G {}\nK {}\nV {}\nS {}\nE {}\n"


def rotate(pt, rot, flip):
    """Apply xschem's instance transform (its ROTATION macro) to a symbol-local point."""
    x, y = pt
    if flip:
        x = -x
    return [(x, y), (-y, x), (-x, -y), (y, -x)][rot % 4]


def best_orientation(offsets, pins):
    """The xschem (rot, flip) that lands a symbol's pins nearest cktImg's placement.

    `offsets`: terminal -> symbol-local pin offset. `pins`: terminal -> target xy relative
    to the device origin, already scaled. Returns (rot, flip, total Manhattan stub length).
    """
    best = (0, 0, None)
    for flip in (0, 1):
        for rot in range(4):
            cost = 0
            for term, target in pins.items():
                if term in offsets:
                    px, py = rotate(offsets[term], rot, flip)
                    cost += abs(px - target[0]) + abs(py - target[1])
            if best[2] is None or cost < best[2]:
                best = (rot, flip, cost)
    return best


def card(value, style):
    """(model, w, l) from cktImg's `value` (the card past its nodes), style defaults where
    the card is silent. Reads both `nfet_01v8 W=..` and `sky130_fd_pr__nfet_01v8 W=..`."""
    tok = value.split()
    kv = dict(t.lower().split("=", 1) for t in tok if "=" in t)
    # A leading number (`R1 a b 2k`) is a value, not a model: the style's default stands.
    named = tok and tok[0][0].isalpha() and "=" not in tok[0]
    model = tok[0].lower().removeprefix(PDK_PREFIX) if named else style["model"]
    return model, kv.get("w", style["w"]), kv.get("l", style["l"])


def box_symbol(cell, pins):
    """An embedded xschem symbol for a box class: a rectangle round its pins, one B 5 per
    pin in port order, netlisted as `<name> <pins> <value>` (`Xdrv0 ... pwm_driver`).

    `type=primitive` so xschem writes the card and does not look for `<cell>.sch` to
    descend into; the subcircuit's definition comes from its own deck.
    """
    xs = [x for _, (x, _) in pins] + [0]
    ys = [y for _, (_, y) in pins] + [0]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    out = ["[\n", VERSION, "G {}\n",
           'K {type=primitive\nformat="@name @pinlist @value"\ntemplate="name=x1"}\n',
           "V {}\nS {}\nE {}\n",
           f"P 4 5 {x0} {y0} {x1} {y0} {x1} {y1} {x0} {y1} {x0} {y0} {{}}\n",
           f"T {{@name}} {x0} {y0 - 20} 0 0 0.2 0.2 {{}}\n",
           f"T {{{cell}}} {x0} {y1 + 5} 0 0 0.2 0.2 {{}}\n"]
    for term, (x, y) in pins:
        out.append(f"B 5 {x - 2.5} {y - 2.5} {x + 2.5} {y + 2.5} {{name={term} dir=inout}}\n")
        out.append(f"T {{{term}}} {x + 3} {y - 8} 0 0 0.12 0.12 {{}}\n")
    out.append("]\n")
    return "".join(out)


def emit(data, scale):
    """Build the .sch body from a cktimg-json document carrying a `target` block.

    Returns (sch text, wires, named, pins): `named` is every (x, y, net) xschem names a
    node at (lab_pins and rail/port symbols), `pins` every real symbol pin (x, y, net).
    """
    out = [HEADER]
    wires = []       # (x1, y1, x2, y2, net)
    pins_at = []     # (x, y, net) -- every symbol pin, where xschem will look for it
    bulks = []       # (x, y, net) -- MOS body pins, labelled since nothing wires them
    rails = []       # (x, y, net) -- rail/port symbols, which are labels themselves
    boxes = {}       # cell -> pin offsets of its embedded symbol

    def S(p):
        return (round(p[0] * scale), round(p[1] * scale))

    mapped = {t["device"] for t in data["target"]["devices"]}
    for i, dev in enumerate(data["devices"]):
        if i not in mapped:
            print(f"warning: no symbol mapped for class '{dev['class']}' "
                  f"(device {dev['name']}), skipped", file=sys.stderr)

    for t in data["target"]["devices"]:
        dev = data["devices"][t["device"]]
        style = t.get("style", {})
        # `pins` is the manifest's pin order, as indices into this device's own pins;
        # `pin_xy` is written in that same order.
        pins = [dev["pins"][i] for i in t["pins"]]
        ox, oy = S(dev["pos"])
        targets = {p["term"]: (S(p["xy"])[0] - ox, S(p["xy"])[1] - oy) for p in pins}

        name = dev["name"]
        fields = {"name": name, "ref": name[1:] if name[0] == "x" else name,
                  "value": dev.get("value", ""), "net": pins[0]["net"],
                  "cell": dev["class"].removeprefix("block:")}
        if "model" in style:
            fields.update(zip(("model", "w", "l"), card(fields["value"], style)))
        embed = ""
        if style.get("box"):
            if fields["cell"] not in boxes:
                boxes[fields["cell"]] = [(p["term"], targets[p["term"]]) for p in pins]
                embed = box_symbol(fields["cell"], boxes[fields["cell"]])
            offsets = dict(boxes[fields["cell"]])
        else:
            offsets = {p["term"]: tuple(xy) for p, xy in zip(pins, style["pin_xy"])}
        rot, flip, _ = best_orientation(offsets, targets)

        attrs = style["attrs"].format(**fields) + (" embed=true" if embed else "")
        out.append(f"C {{{t['sym'].format(**fields)}}} {ox} {oy} {rot} {flip} {{{attrs}}}\n")
        out.append(embed)

        for p in pins:
            px, py = rotate(offsets[p["term"]], rot, flip)
            at = (ox + px, oy + py, p["net"])
            (rails if style.get("rail") else pins_at).append(at)
            wires += stub(at[:2], S(p["xy"]), p["net"])
        bulk = dev.get("bulk", style.get("bulk", {}).get("net"))
        if "bulk" in style and bulk is not None:
            bx, by = rotate(style["bulk"]["xy"], rot, flip)
            bulks.append((ox + bx, oy + by, bulk))

    for w in data["wires"]:
        for seg in w["segments"]:
            pts = [S(p) for p in seg]
            for a, b in zip(pts, pts[1:]):
                if a != b:
                    wires.append((a[0], a[1], b[0], b[1], w["net"]))

    # Label every net once, on a symbol pin: xschem renames unlabelled nodes `net1`,
    # `net2`, ..., which silently breaks name-based LVS against the source deck. Nets a
    # rail/port symbol already names are skipped.
    seen = {net for _, _, net in rails}
    first = []
    for x, y, net in pins_at:
        if net not in seen:
            seen.add(net)
            first.append((x, y, net))
    routed_labels = [(*S(lab["at"]), lab["net"]) for lab in data.get("labels", [])]

    # cktImg's router can run a wire across another net's pin or wire end, which xschem
    # would short. Such a net loses its wires and is joined by name instead: a label on
    # every one of its symbol pins. Repeat, since a new label can land on a third net's wire.
    labelled = set()
    while True:
        live = [w for w in wires if w[4] not in labelled]
        named = (rails + bulks + first + [lab for lab in routed_labels if lab[2] not in labelled]
                 + [p for p in pins_at if p[2] in labelled])
        ends = [e for w in live for e in ((w[0], w[1], w[4]), (w[2], w[3], w[4]))]
        bad = {w[4] for w, p in touching(live, pins_at + named + ends) if p[2] != w[4]}
        if not bad:
            break
        labelled |= bad
    if labelled:
        print(f"note: cktImg routed {', '.join(sorted(labelled))} across another net; "
              f"joined by labels instead", file=sys.stderr)

    for x1, y1, x2, y2, net in live:
        out.append(f"N {x1} {y1} {x2} {y2} {{lab={net}}}\n")
    lab_pins = dict.fromkeys(lab for lab in named if lab not in rails)
    for i, (x, y, net) in enumerate(lab_pins):
        out.append(f"C {{{LAB_PIN}}} {x} {y} 0 0 {{name=p{i} lab={net}}}\n")

    return "".join(out), live, named, pins_at + rails


def touching(wires, points):
    """(wire, point) for every point lying on a wire, endpoints included: xschem's rule for
    a pin, label or wire end joining a wire. Points are (x, y, ...) tuples."""
    rows, cols = {}, {}
    for p in points:
        rows.setdefault(p[1], []).append(p)
        cols.setdefault(p[0], []).append(p)
    for w in wires:
        x1, y1, x2, y2 = w[:4]
        if y1 == y2:
            lo, hi = sorted((x1, x2))
            yield from ((w, p) for p in rows.get(y1, ()) if lo <= p[0] <= hi)
        elif x1 == x2:
            lo, hi = sorted((y1, y2))
            yield from ((w, p) for p in cols.get(x1, ()) if lo <= p[1] <= hi)


def stub(frm, to, net):
    """Manhattan path from a symbol pin to where cktImg wants it. Empty when they coincide."""
    if frm == to:
        return []
    if frm[0] == to[0] or frm[1] == to[1]:
        return [(frm[0], frm[1], to[0], to[1], net)]
    corner = (to[0], frm[1])
    return [(frm[0], frm[1], corner[0], corner[1], net),
            (corner[0], corner[1], to[0], to[1], net)]


def check_connectivity(wires, named, pins):
    """Assert every net comes out as exactly one node in the .sch, and no two nets share one.

    Walks xschem's own rule over what was emitted: a pin, label or wire end lying on a wire
    joins it (T-junctions included), and every label or rail/port symbol with the same name
    is one node wherever it sits (so three `gnd.sym` on `vss` are one net, not three).
    `pins` is every symbol pin as (x, y, net).

    Raises AssertionError naming the net. Returns the number of nets checked.
    """
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    ends = [e for w in wires for e in ((w[0], w[1]), (w[2], w[3]))]
    for w, p in touching(wires, pins + named + ends):
        union(p[:2], w[:2])
    by_name = {}
    for x, y, net in named:
        union((x, y), by_name.setdefault(net, (x, y)))

    nets = {}
    for x, y, net in pins:
        nets.setdefault(net, set()).add(find((x, y)))
    owner = {}
    for net, roots in nets.items():
        assert len(roots) == 1, f"net '{net}' emitted as {len(roots)} disconnected groups"
        other = owner.setdefault(roots.pop(), net)
        assert other == net, f"nets '{other}' and '{net}' emitted shorted together"
    return len(nets)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("netlist", help="SPICE deck to place")
    ap.add_argument("out", nargs="?", help="output .sch (default: stdout)")
    ap.add_argument("--scale", type=float,
                    help="cktImg grid units -> xschem units (default: the manifest's units.scale)")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG),
                    help="lint.zon passed through to cktimg-json (default: cktimg_sky130.zon)")
    ap.add_argument("--target", default=str(DEFAULT_TARGET),
                    help="cktImg target manifest mapping classes to xschem symbols "
                         "(default: xschem_sky130.json)")
    ap.add_argument("--svg", help="also write cktImg's own drawing of the deck here")
    args = ap.parse_args()

    exe = shutil.which("cktimg-json")
    if exe is None:
        sys.exit("cktimg-json not found on PATH -- enter the nix shell (./env.sh)")

    cmd = [exe, "--config", args.config, "--target", args.target]
    if args.svg:
        cmd += ["--svg", args.svg]
    proc = subprocess.run(cmd + [args.netlist], capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(f"cktimg-json failed:\n{proc.stderr.strip()}")
    if proc.stderr.strip():
        print(proc.stderr.strip(), file=sys.stderr)

    data = json.loads(proc.stdout)
    scale = args.scale or data["target"].get("units", {}).get("scale", 1.5)
    sch, wires, named, pins = emit(data, scale)

    n = check_connectivity(wires, named, pins)
    print(f"{args.netlist}: {len(data['devices'])} devices, {n} nets, "
          f"{len(wires)} wire segments", file=sys.stderr)

    if args.out:
        Path(args.out).write_text(sch)
    else:
        sys.stdout.write(sch)


if __name__ == "__main__":
    main()
