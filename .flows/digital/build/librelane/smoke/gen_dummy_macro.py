# Writes the smoke test's dummy analog macro (LEF + GDS) from one pin table, so the
# two views cannot drift. Run: klayout -b -r gen_dummy_macro.py -rd out=<dir>
# -> <dir>/lef/dummy_macro.lef, <dir>/gds/dummy_macro.gds (the analog/<block>/output/ layout).
# The GDS holds only the pin metal, labels and prBoundary: enough for DRC/LVS/XOR.
# ponytail: stand-in for a real Philis/magic macro; the real one comes from analog/<block>/output/.
import os

import pya as db

NAME = "dummy_macro"
W, H = 60.0, 80.0
# sky130 GDS layer number, datatypes (drawing, pin, label)
LAYERS = {"met2": (69, 20, 16, 5), "met4": (71, 20, 16, 5)}
# name, direction, use, layer, (x0, y0, x1, y1) in um
PINS = [
    ("en",   "INPUT",  "SIGNAL", "met2", (4.86, 0.0, 5.14, 1.0)),
    ("c0",   "INPUT",  "SIGNAL", "met2", (9.86, 0.0, 10.14, 1.0)),
    ("c1",   "INPUT",  "SIGNAL", "met2", (14.86, 0.0, 15.14, 1.0)),
    ("c2",   "INPUT",  "SIGNAL", "met2", (19.86, 0.0, 20.14, 1.0)),
    ("c3",   "INPUT",  "SIGNAL", "met2", (24.86, 0.0, 25.14, 1.0)),
    ("done", "OUTPUT", "SIGNAL", "met2", (29.86, 0.0, 30.14, 1.0)),
    # analog signal: routed like a signal, but RSZ_DONT_TOUCH_RX keeps buffers off it
    ("ana",  "INOUT",  "SIGNAL", "met2", (39.86, 0.0, 40.14, 1.0)),
    # digital-domain supplies: hooked to the top VPWR/VGND grid by PDN_MACRO_CONNECTIONS
    ("VPWR", "INOUT",  "POWER",  "met4", (45.0, 2.0, 46.6, 78.0)),
    ("VGND", "INOUT",  "GROUND", "met4", (50.0, 2.0, 51.6, 78.0)),
    # analog supplies: deliberately NOT in PDN_MACRO_CONNECTIONS, so they stay off VPWR/VGND
    ("VDDA", "INOUT",  "POWER",  "met4", (10.0, 2.0, 11.6, 78.0)),
    ("VSSA", "INOUT",  "GROUND", "met4", (15.0, 2.0, 16.6, 78.0)),
]


def lef():
    out = [
        "VERSION 5.7 ;",
        'BUSBITCHARS "[]" ;',
        'DIVIDERCHAR "/" ;',
        f"MACRO {NAME}",
        "  CLASS BLOCK ;",
        f"  FOREIGN {NAME} ;",
        "  ORIGIN 0 0 ;",
        f"  SIZE {W} BY {H} ;",
    ]
    for name, d, use, layer, (x0, y0, x1, y1) in PINS:
        out += [
            f"  PIN {name}",
            f"    DIRECTION {d} ;",
            f"    USE {use} ;",
            "    PORT",
            f"      LAYER {layer} ;",
            f"        RECT {x0} {y0} {x1} {y1} ;",
            "    END",
            f"  END {name}",
        ]
    # Router keep-out over the body; met2 leaves a 1.5 um strip at the bottom for pin access.
    out += [
        "  OBS",
        "    LAYER li1 ;", f"      RECT 0 0 {W} {H} ;",
        "    LAYER met1 ;", f"      RECT 0 0 {W} {H} ;",
        "    LAYER met2 ;", f"      RECT 0 1.5 {W} {H} ;",
        "    LAYER met3 ;", f"      RECT 0 0 {W} {H} ;",
        "  END",
        f"END {NAME}",
        "END LIBRARY",
    ]
    return "\n".join(out) + "\n"


def gds(path):
    ly = db.Layout()
    ly.dbu = 0.001
    top = ly.create_cell(NAME)
    top.shapes(ly.layer(235, 4)).insert(db.DBox(0, 0, W, H))  # prBoundary
    for name, _, _, layer, box in PINS:
        num, drw, pin, lbl = LAYERS[layer]
        b = db.DBox(*box)
        top.shapes(ly.layer(num, drw)).insert(b)
        top.shapes(ly.layer(num, pin)).insert(b)
        top.shapes(ly.layer(num, lbl)).insert(db.DText(name, b.center().x, b.center().y))
    ly.write(path)


out = globals().get("out") or "."
for kind in ("lef", "gds"):
    os.makedirs(os.path.join(out, kind), exist_ok=True)
with open(os.path.join(out, "lef", NAME + ".lef"), "w") as f:
    f.write(lef())
gds(os.path.join(out, "gds", NAME + ".gds"))
print(f"wrote {out}/lef/{NAME}.lef, {out}/gds/{NAME}.gds")
