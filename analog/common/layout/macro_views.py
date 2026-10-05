# Hard-macro views of a verified block layout: the GDS and LEF LibreLane places.
#
#   klayout -b -r macro_views.py -rd block=<b> -rd gds=<in.gds> -rd out=<dir> [-rd ports=<b>.ports or <b>.spice]
#   -> <dir>/gds/<b>.gds, <dir>/lef/<b>.lef
#
# - Pins are the labels on a metal (li1, met1..met5 label/pin/drawing datatype), each on the
#   pin shape under it. A Philis GDS writes its texts on 236/0, a non-layer (TOOL_ISSUES.md),
#   so it has no pins here and the run fails: use a substrate2 (`make gen`) GDS.
# - Bus bits are renamed `name<i>` (SPICE, LVS) -> `name[i]` (Verilog, LEF BUSBITCHARS),
#   so the LEF/GDS pin names are the blackbox's bit names. LVS runs on the input GDS.
# - The cell is moved so its box starts at (0, 0): LEF and GDS share coordinates.
# - OBS: the whole box on li1..met4, notched KEEPOUT um around each pin so the router can
#   reach it. met5 stays free for the top's power straps.
# - `ports` (an analogioc.ports-style table, or the block's deck: its .subckt ports, INOUT)
#   gives direction and USE; every port in it must have a pin, else exit 1. Without it every
#   label is an INOUT SIGNAL pin, unchecked.
#   ponytail: bbox OBS, a per-layer merged-geometry OBS if the top needs over-the-macro routing.
import os
import re
import sys

import pya as db

# sky130 GDS layer numbers; datatypes: drawing 20 (li1 too), pin 16, label 5
METALS = {"li1": 67, "met1": 68, "met2": 69, "met3": 70, "met4": 71, "met5": 72}
OBS_LAYERS = ("li1", "met1", "met2", "met3", "met4")
KEEPOUT = 0.3  # um, > met1/met2 spacing


def die(msg):
    print(f"macro_views: {msg}", file=sys.stderr)
    sys.exit(1)


def bits(name):
    return re.sub(r"<(\d+)>", r"[\1]", name)


def read_ports(path, block):
    """{bit name: (DIRECTION, USE)} from `<name> <in|out|inout> <digital|analog|supply> <domain>`
    lines, or from `.subckt <block>` of a SPICE deck (INOUT; vdd*/vss* named supplies)."""
    out = {}
    if path.endswith((".spice", ".sp", ".cir")):
        deck = re.sub(r"\n\+", " ", open(path).read())
        m = re.search(rf"^\s*\.subckt\s+{block}\s+([^\n]*)", deck, re.M | re.I)
        if not m:
            die(f"{path}: no .subckt {block}")
        for p in (t for t in m.group(1).split() if "=" not in t):
            use = "GROUND" if re.match(r"(vss|gnd)", p, re.I) else "POWER" if re.match(r"vdd", p, re.I) else "SIGNAL"
            out[bits(p)] = ("INOUT", use)
        return out
    for line in open(path):
        tok = line.split("#", 1)[0].split()
        if len(tok) < 3:
            continue
        name, d, kind = tok[:3]
        use = "SIGNAL"
        if kind == "supply":
            use = "GROUND" if re.match(r"(vss|gnd)", name, re.I) else "POWER"
        out[bits(name)] = ({"in": "INPUT", "out": "OUTPUT"}.get(d, "INOUT"), use)
    return out


def main():
    block, src, outdir = globals().get("block"), globals().get("gds"), globals().get("out")
    if not (block and src and outdir):
        die("usage: klayout -b -r macro_views.py -rd block=B -rd gds=IN -rd out=DIR [-rd ports=P]")
    ly = db.Layout()
    ly.read(src)
    top = ly.cell(block)
    if top is None:
        die(f"{src}: no top cell {block}")
    box = top.dbbox()
    top.transform(db.DTrans(-box.left, -box.bottom))
    box = top.dbbox()

    pins = {}  # name -> [(layer, DBox)]
    for lname, num in METALS.items():
        for dt in (5, 16, 20):
            li = ly.find_layer(num, dt)
            if li is None:
                continue
            for s in list(top.shapes(li).each(db.Shapes.STexts)):
                t = s.text.dup()
                t.string = bits(t.string)
                s.text = t
                p = s.dtext.position()
                hit = None
                for pdt in (16, 20):
                    pli = ly.find_layer(num, pdt)
                    for sh in top.shapes(pli).each_touching(db.DBox(p, p)) if pli is not None else ():
                        if sh.is_box() or sh.is_polygon() or sh.is_path():
                            hit = sh.dbbox()
                            break
                    if hit:
                        break
                if hit and (lname, hit) not in pins.get(t.string, []):
                    pins.setdefault(t.string, []).append((lname, hit))

    ports = read_ports(globals()["ports"], block) if globals().get("ports") else None
    if ports is not None:
        missing = [p for p in ports if p not in pins]
        if missing:
            die(f"{len(missing)} port(s) have no pin label on a metal: {missing[:12]}"
                + (" ..." if len(missing) > 12 else ""))
        pins = {p: pins[p] for p in ports}  # port order; other labels are internal nets

    for kind in ("gds", "lef"):
        os.makedirs(os.path.join(outdir, kind), exist_ok=True)
    ly.write(os.path.join(outdir, "gds", f"{block}.gds"))

    f = lambda v: f"{v:.3f}"
    lef = ['VERSION 5.7 ;', 'BUSBITCHARS "[]" ;', 'DIVIDERCHAR "/" ;', f"MACRO {block}",
           "  CLASS BLOCK ;", f"  FOREIGN {block} ;", "  ORIGIN 0 0 ;",
           f"  SIZE {f(box.width())} BY {f(box.height())} ;", "  SYMMETRY X Y ;"]
    for name, shapes in pins.items():
        d, use = (ports or {}).get(name, ("INOUT", "SIGNAL"))
        lef += [f"  PIN {name}", f"    DIRECTION {d} ;", f"    USE {use} ;", "    PORT"]
        for lname, b in shapes:
            lef += [f"      LAYER {lname} ;", f"        RECT {f(b.left)} {f(b.bottom)} {f(b.right)} {f(b.top)} ;"]
        lef += ["    END", f"  END {name}"]
    lef.append("  OBS")
    dbu = ly.dbu
    for lname in OBS_LAYERS:
        reg = db.Region(box.to_itype(dbu))
        for shapes in pins.values():
            for pl, b in shapes:
                if pl == lname:
                    reg -= db.Region(b.enlarged(KEEPOUT, KEEPOUT).to_itype(dbu))
        lef.append(f"    LAYER {lname} ;")
        for poly in reg.each():
            for tz in poly.decompose_trapezoids(db.Polygon.TD_htrapezoids):
                b = tz.bbox().to_dtype(dbu)
                lef.append(f"      RECT {f(b.left)} {f(b.bottom)} {f(b.right)} {f(b.top)} ;")
    lef += ["  END", f"END {block}", "END LIBRARY"]
    with open(os.path.join(outdir, "lef", f"{block}.lef"), "w") as fh:
        fh.write("\n".join(lef) + "\n")
    print(f"macro_views: {block}: {len(pins)} pins, {f(box.width())} x {f(box.height())} um "
          f"-> {outdir}/gds/{block}.gds, {outdir}/lef/{block}.lef")


main()
