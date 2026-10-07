"""The AnalogIOC architecture as one multi-page diagram, in the Cocoon-AI architecture-diagram style (dark theme,
JetBrains Mono, colour-coded rounded blocks, export toolbar).

Every analog block carries its transistor circuit as cktImg placed it (analog/imc_tile/netlist/imc_tile.py --draw
writes the placed geometry to analog/imc_tile/output/schematics/<view>.json), and the wires between blocks land on
those circuits' ports. Digital blocks show their RTL module hierarchy (digital/imc_driver/src).

    python3 docs/architecture/gen_architecture.py              # inside ./env.sh analog: draw, html, pdf, png
    python3 docs/architecture/gen_architecture.py --no-draw    # reuse the schematics already drawn
    python3 docs/architecture/gen_architecture.py --html-only  # no pdf / png

Writes docs/architecture/imc_architecture.html, .pdf (all pages) and .png (page 1). The pdf and png come from
headless chromium (`chromium` on PATH, else `nix-shell -p chromium`).
"""
import argparse
import html
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SCH = ROOT / "analog/imc_tile/output/schematics"
PW, PH = 1680, 1050                     # one page, css px
VW, VH = 1616, 952                      # its drawing

# palette (Cocoon): analog, digital, memory, reference, stream, slate
AN, DG, MEM, REF, ST, SL, ROSE = "#34d399", "#22d3ee", "#a78bfa", "#fbbf24", "#fb923c", "#94a3b8", "#fb7185"
FILL = {AN: "rgba(6, 78, 59, 0.40)", DG: "rgba(8, 51, 68, 0.40)", MEM: "rgba(76, 29, 149, 0.40)",
        REF: "rgba(120, 53, 15, 0.30)", ST: "rgba(124, 45, 18, 0.35)", SL: "rgba(30, 41, 59, 0.50)",
        ROSE: "rgba(136, 19, 55, 0.40)"}
INK, DIM, FAINT = "#e2e8f0", "#64748b", "#334155"


def esc(s):
    return html.escape(str(s), quote=False)


class Svg:
    """An SVG fragment: a list of elements."""

    def __init__(self):
        self.o = []

    def add(self, s):
        self.o.append(s)

    def __str__(self):
        return "\n".join(self.o)

    def line(self, x1, y1, x2, y2, c=SL, w=1.2, dash=None, arrow=False, op=None):
        self.add(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{c}" stroke-width="{w}"'
                 + (f' stroke-dasharray="{dash}"' if dash else "") + (f' opacity="{op}"' if op else "")
                 + (f' marker-end="url(#ah-{c[1:]})"' if arrow else "") + "/>")

    def poly(self, pts, c=SL, w=1.2, dash=None, arrow=False, fill="none", op=None):
        self.add(f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in pts)}" fill="{fill}" stroke="{c}" '
                 f'stroke-width="{w}" stroke-linejoin="round" stroke-linecap="round"'
                 + (f' stroke-dasharray="{dash}"' if dash else "") + (f' opacity="{op}"' if op else "")
                 + (f' marker-end="url(#ah-{c[1:]})"' if arrow else "") + "/>")

    def text(self, x, y, s, c=INK, size=9, anchor="start", weight=400, italic=False, op=None):
        self.add(f'<text x="{x:.1f}" y="{y:.1f}" fill="{c}" font-size="{size}" font-weight="{weight}" '
                 f'text-anchor="{anchor}"' + (' font-style="italic"' if italic else "")
                 + (f' opacity="{op}"' if op else "") + f">{esc(s)}</text>")

    def circle(self, x, y, r, c=SL, fill="none", w=1.2):
        self.add(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{fill}" stroke="{c}" stroke-width="{w}"/>')

    def rect(self, x, y, w, h, c=SL, fill=None, rx=6, dash=None, sw=1.5, op=None):
        self.add(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx}" '
                 f'fill="{fill if fill is not None else FILL.get(c, "none")}" stroke="{c}" stroke-width="{sw}"'
                 + (f' stroke-dasharray="{dash}"' if dash else "") + (f' opacity="{op}"' if op else "") + "/>")

    def box(self, x, y, w, h, c, title=None, sub=(), tsize=11, ssize=8, rx=6, dash=None, align="middle"):
        """A Cocoon block: opaque backing, tinted fill, title and grey sub-lines."""
        self.add(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx}" fill="#0b1222"/>')
        self.rect(x, y, w, h, c, rx=rx, dash=dash)
        tx = x + w / 2 if align == "middle" else x + 10
        if title:
            self.text(tx, y + 17, title, "white", tsize, align if align == "middle" else "start", 600)
        for i, s in enumerate(sub):
            self.text(tx, y + 17 + (tsize + 4) + (ssize + 3) * i, s, SL, ssize, align if align == "middle" else "start")

    def tag(self, x, y, s, c, size=8, anchor="start"):
        """A small pill label (net names at block edges)."""
        w = 6.0 * size / 9.5 * len(s) + 8
        x0 = x - (w if anchor == "end" else w / 2 if anchor == "middle" else 0)
        self.add(f'<rect x="{x0:.1f}" y="{y - size + 0.5:.1f}" width="{w:.1f}" height="{size + 5:.1f}" rx="3" '
                 f'fill="#0b1222" stroke="{c}" stroke-width="0.8"/>')
        self.text(x0 + w / 2, y + 2, s, c, size, "middle", 500)


def wire(g, pts, c=AN, w=1.3, label=None, at=0.5, dash=None, arrow=False, lsize=8, loff=-4):
    """An orthogonal wire through `pts`; a label at fraction `at` along its longest horizontal run."""
    g.poly(pts, c, w, dash=dash, arrow=arrow)
    if label:
        runs = [(abs(b[0] - a[0]), a, b) for a, b in zip(pts, pts[1:]) if a[1] == b[1]]
        if runs:
            _, a, b = max(runs)
            g.text(a[0] + (b[0] - a[0]) * at, a[1] + loff, label, c, lsize, "middle", 500)
        else:
            a, b = pts[0], pts[1]
            g.text(a[0] + 4, (a[1] + b[1]) / 2, label, c, lsize, "start", 500)


def dot(g, x, y, c):
    g.circle(x, y, 2.2, c, fill=c, w=0)


# ----------------------------------------------------------------------------- cktImg views
# Symbol strokes in the class frame (cktImg tests/symbols.zon, the set cktimg-json places with); the switch
# class is drawn as a transmission gate: imc_tile.py --draw collapses nmos + pmos pairs into it.
SYM = {
    "nmos": [[(20, 0), (8, 0), (8, -3)], [(-20, 0), (-8, 0), (-8, -3)], [(10, -3), (-10, -3)], [(8, -7), (-8, -7)],
             [(0, -20), (0, -7)]],
    "pmos": [[(20, 0), (8, 0), (8, -3)], [(-20, 0), (-8, 0), (-8, -3)], [(10, -3), (-10, -3)], [(8, -7), (-8, -7)],
             [(0, -20), (0, -11)], ("c", 0, -9, 2)],
    "cap": [[(-20, 0), (-3, 0)], [(3, 0), (20, 0)], [(-3, -8), (-3, 8)], [(3, -8), (3, 8)]],
    "res": [[(-20, 0), (-12, 0)], [(12, 0), (20, 0)],
            [(-12, 0), (-9, 4), (-6, -4), (-3, 4), (0, -4), (3, 4), (6, -4), (9, 4), (12, 0)]],
    "switch": [[(-20, 0), (-9, 0)], [(9, 0), (20, 0)], [(-9, -6), (-9, 6), (0, 0), (-9, -6)],
               [(9, -6), (9, 6), (0, 0), (9, -6)], [(-6, -20), (-6, -4)], [(6, -20), (6, -7.5)], ("c", 6, -5.5, 1.6)],
    "gnd": [[(-9, 0), (9, 0)], [(-6, 3), (6, 3)], [(-2, 6), (2, 6)]],
    "vdd": [[(-9, 0), (9, 0)]],
}


def orient(rot, mirror, x, y):
    if mirror:
        x = -x
    return [(x, y), (-y, x), (-x, -y), (y, -x)][rot]


class Placed:
    """A view drawn on the page: its box and where each port's wires land."""

    def __init__(self, box, ports, xy):
        self.box, self.ports, self.xy = box, ports, xy

    def port(self, net, k=0):
        """(x, y, dir) of the k-th landing point of a net; dir is the side a wire leaves by."""
        ps = self.ports.get(net)
        if not ps:
            raise KeyError(f"no port {net!r} (have {sorted(self.ports)})")
        return ps[min(k, len(ps) - 1)]

    def has(self, net):
        return net in self.ports

    def take(self, net, k=0, d=None):
        """A landing point whose label the arriving wire replaces (the wire carries the name from there)."""
        x, y, dd = self.port(net, k)
        i = getattr(self, "labs", {}).get((round(x, 1), round(y, 1)))
        if i is not None:
            self.g.o[i] = ""
        return (x, y, d or dd)

    def at(self, net, k=0, d=None):
        x, y, dd = self.port(net, k)
        return (x, y, d or dd)


class View:
    """One cktImg view: the placed geometry, cktImg's own name anchors, the deck's fin counts."""

    def __init__(self, name):
        self.name = name
        self.g = json.loads((SCH / f"{name}.json").read_text())
        idx = json.loads((SCH / "views.json").read_text()).get(name, {})
        self.note, self.subckt, self.roles = idx.get("note", ""), idx.get("subckt", name), idx.get("ports", {})
        deck = (SCH / f"{name}.spice").read_text()
        self.fins = {t[0].lower(): re.search(r"NFIN=(\d+)", ln).group(1) for ln in deck.splitlines()
                     if (t := ln.split()) and t[0][0] == "M" and "NFIN=" in ln}
        self.dev = {d["name"]: d for d in self.g["devices"]}
        # device names where cktImg's renderer put them (svg px -> placement units; scale 1.6, margin 40)
        svg = (SCH / f"{name}.svg").read_text()
        p0 = re.search(r'<polyline points="([\d.]+),([\d.]+)', svg)
        w0 = self.g["wires"][0]["segments"][0][0] if self.g["wires"] else [0, 0]
        lo = (w0[0] - (float(p0.group(1)) - 40) / 1.6, w0[1] - (float(p0.group(2)) - 40) / 1.6) if p0 else (0, 0)
        self.anchor = {}
        for mt in re.finditer(r'<text x="([\d.]+)" y="([\d.]+)" text-anchor="start" font-size="11" fill="#56607a"'
                              r' stroke="none">([^<]+)</text>', svg):
            if mt.group(3) in self.dev:
                self.anchor[mt.group(3)] = (lo[0] + (float(mt.group(1)) - 40) / 1.6, lo[1] + (float(mt.group(2)) - 40) / 1.6)
        self.ends = {}                  # wire end points -> the neighbouring point (a terminal's attached side)
        for w in self.g["wires"]:
            for seg in w["segments"]:
                for a, b in ((seg[0], seg[1]), (seg[-1], seg[-2])):
                    self.ends.setdefault(tuple(a), []).append(tuple(b))
        pts = [tuple(p) for w in self.g["wires"] for seg in w["segments"] for p in seg]
        pts += [tuple(lb["at"]) for lb in self.g["labels"]]
        for d in self.g["devices"]:
            if d["class"] in ("ipin", "opin"):
                at = d["pins"][0]["xy"]
                free = self._free(at, "l" if d["class"] == "ipin" else "r")
                if free is None:
                    continue            # drawn by name elsewhere
                n = 7 * min(len(d["pins"][0]["net"]), 22) + 8
                pts.append((at[0] + {"l": -n, "r": n}.get(free, 0), at[1]))
            pts += [tuple(p["xy"]) for p in d["pins"]] + [tuple(d["pos"])]
        self.bb = (min(p[0] for p in pts) - 14, min(p[1] for p in pts) - 14,
                   max(p[0] for p in pts) + 14, max(p[1] for p in pts) + 14)

    @property
    def size(self):
        return self.bb[2] - self.bb[0], self.bb[3] - self.bb[1]

    def fit(self, w, h):
        return min(w / self.size[0], h / self.size[1])

    def _free(self, at, prefer="lr"):
        """The side a wire can leave a terminal by: one no wire of the drawing uses there."""
        x, y = at
        used = set()
        for w in self.g["wires"]:
            for seg in w["segments"]:
                for a, b in zip(seg, seg[1:]):
                    if a[0] == b[0] == x and min(a[1], b[1]) <= y <= max(a[1], b[1]):
                        used |= {"u"} if min(a[1], b[1]) < y else set()
                        used |= {"d"} if max(a[1], b[1]) > y else set()
                    if a[1] == b[1] == y and min(a[0], b[0]) <= x <= max(a[0], b[0]):
                        used |= {"l"} if min(a[0], b[0]) < x else set()
                        used |= {"r"} if max(a[0], b[0]) > x else set()
        if not used:
            return None
        return next((d for d in prefer + "udlr" if d not in used), None)

    def draw(self, g, x, y, s, c=AN, names=True, fins=False, text=7.5, hide=(), nets_c=None):
        """Draw at (x, y) (the view's top-left) with s px per unit. Returns a Placed."""
        X = lambda u: x + (u - self.bb[0]) * s          # noqa: E731
        Y = lambda v: y + (v - self.bb[1]) * s          # noqa: E731
        lw = max(0.7, min(1.4, 1.1 * s / 0.6))
        wc = nets_c or c
        for w in self.g["wires"]:
            for seg in w["segments"]:
                g.poly([(X(p[0]), Y(p[1])) for p in seg], wc, lw * 0.9, op=0.85)
        ports, labs = {}, {}
        for d in self.g["devices"]:
            cls, (px, py) = d["class"], d["pos"]
            if cls.startswith("block:"):
                self._block(g, d, X, Y, s, c, text)
                continue
            if cls in ("ipin", "opin", "vdd", "gnd"):
                net = d["pins"][0]["net"]
                free = self._free(d["pins"][0]["xy"], "l" if cls == "ipin" else "r")
                if cls in ("ipin", "opin"):
                    if free is None or net in hide:
                        continue                # cktImg could not wire it: the net's labels carry it
                    g.circle(X(px), Y(py), max(1.6, 3 * s), INK, fill="#0b1222", w=lw)
                    ports.setdefault(net, []).append((X(px), Y(py), free))
                    labs[(round(X(px), 1), round(Y(py), 1))] = len(g.o)          # the name, appended next
                    dx = {"l": -1, "r": 1}.get(free, 0)
                    g.text(X(px) + dx * (5 * s + 3), Y(py) + (text * 0.36 if dx else (-5 if free == "u" else text + 3)),
                           abbrev(net, 22), "white", text + 0.5, "end" if dx < 0 else "start" if dx > 0 else "middle", 600)
                    continue
                if cls == "vdd":
                    ports.setdefault(net, []).append((X(px), Y(py), "u"))
                    g.text(X(px), Y(py) - 4, net, REF if net != "vdd" else SL, text, "middle", 500)
            for item in SYM.get(cls, []):
                if isinstance(item, tuple):
                    cx, cy = orient(d["rot"], d["mirror"], item[1], item[2])
                    g.circle(X(px + cx), Y(py + cy), max(0.9, item[3] * s), INK, fill="#0b1222", w=lw)
                else:
                    g.poly([(X(px + q[0]), Y(py + q[1])) for q in (orient(d["rot"], d["mirror"], *p) for p in item)],
                           INK, lw)
            if names and d["name"] in self.anchor and not d["name"].startswith("_"):
                ax, ay = self.anchor[d["name"]]
                lab = d["name"] + (f" {self.fins[d['name']]}f" if fins and d["name"] in self.fins else "")
                g.text(X(ax), Y(ay), lab, DIM, text * 0.85)
        for j in self.g["junctions"]:
            dot(g, X(j[0]), Y(j[1]), wc)
        for lb in self.g["labels"]:
            ax, ay = X(lb["at"][0]), Y(lb["at"][1])
            sd = lb["side"]
            dx, dy, an = {"right": (4, text * 0.36, "start"), "left": (-4, text * 0.36, "end"),
                          "up": (0, -4, "middle"), "down": (0, text + 2, "middle")}[sd]
            labs[(round(ax, 1), round(ay, 1))] = len(g.o)
            g.text(ax + dx, ay + dy, abbrev(lb["net"], 22), "#7dd3fc" if c != DG else "#a5f3fc", text, an, italic=True)
            ports.setdefault(lb["net"], []).append((ax, ay, sd[0]))
        for n in self.g["no_connects"]:
            g.line(X(n[0]) - 3, Y(n[1]) - 3, X(n[0]) + 3, Y(n[1]) + 3, ROSE)
            g.line(X(n[0]) - 3, Y(n[1]) + 3, X(n[0]) + 3, Y(n[1]) - 3, ROSE)
        box = (x, y, x + self.size[0] * s, y + self.size[1] * s)
        pl = Placed(box, ports, (X, Y))
        pl.g, pl.labs = g, labs
        return pl

    def _block(self, g, d, X, Y, s, c, text):
        """A subckt instance: the box cktImg generated (pins one unit beyond the edge), its port names inside."""
        px, py = d["pos"]
        side = {}
        for p in d["pins"]:
            dx, dy = p["xy"][0] - px, p["xy"][1] - py
            side[p["term"]] = "l" if dx < -abs(dy) else "r" if dx > abs(dy) else "t" if dy < 0 else "b"
        cnt = lambda k: sum(1 for v in side.values() if v == k)        # noqa: E731
        m_lr, m_tb = max(cnt("l"), cnt("r")) | 1, max(cnt("t"), cnt("b")) | 1
        hh, hw = (m_lr - 1) * 20 + 20, max((m_tb - 1) * 20 + 20, 30)
        g.add(f'<rect x="{X(px - hw):.1f}" y="{Y(py - hh):.1f}" width="{2 * hw * s:.1f}" height="{2 * hh * s:.1f}" '
              f'rx="3" fill="{FILL.get(c, FILL[SL])}" stroke="{c}" stroke-width="1"/>')
        name = d["class"][6:].rstrip("'")
        g.text(X(px), Y(py - hh) - 3, name, "white", text + 1, "middle", 600)
        fs = text * 0.8
        room = {"l": hw * s - 4 if cnt("r") else 2 * hw * s - 6, "r": hw * s - 4 if cnt("l") else 2 * hw * s - 6}
        for p in d["pins"]:
            (qx, qy), sd = p["xy"], side[p["term"]]
            ex, ey = {"l": (qx + 10, qy), "r": (qx - 10, qy), "t": (qx, qy + 10), "b": (qx, qy - 10)}[sd]
            g.line(X(qx), Y(qy), X(ex), Y(ey), c, 1)
            ix = {"l": 3, "r": -3}.get(sd, 0)
            name = abbrev(p["term"], room.get(sd, 2 * hw * s) / (0.6 * fs))
            g.text(X(ex) + ix * s * 1.5, Y(ey) + ({"t": text + 1, "b": -2}.get(sd, text * 0.36)), name, SL,
                   fs, {"l": "start", "r": "end"}.get(sd, "middle"))


def abbrev(name, chars):
    """A bus name cut to `chars`: its first parts, an ellipsis, its last part."""
    chars = int(chars)
    if len(name) <= chars:
        return name
    parts = name.split("/")
    for k in range(len(parts) - 2, 0, -1):
        cut = "/".join(parts[:k]) + "/…/" + parts[-1]
        if len(cut) <= chars:
            return cut
    return name[:max(1, chars - 1)] + "…"


_VIEWS = {}


def view(name):
    if name not in _VIEWS:
        _VIEWS[name] = View(name)
    return _VIEWS[name]


def frame(g, x, y, w, h, c, title, sub="", note=None, tsize=11, foot=None):
    """A block that holds circuits: title, sub-title, a note at the bottom right, a footer at the bottom left."""
    g.add(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="8" fill="#0b1222"/>')
    g.rect(x, y, w, h, c, fill=FILL[c].replace("0.40", "0.22").replace("0.30", "0.18").replace("0.35", "0.2"), rx=8)
    if foot:
        g.text(x + 10, y + h - 7, foot, SL, 7.5)
    g.text(x + 10, y + 17, title, "white", tsize, weight=600)
    if sub:
        g.text(x + 10, y + 30, sub, SL, 8)
    if note:
        g.text(x + w - 8, y + h - 7, note, DIM, 7.5, "end")


def link(g, P, Q, *moves, c=AN, stub=8, w=1.3, dots=True, **kw):
    """Orthogonal wire between two landing points (x, y, dir): out of each along its dir by `stub`, then the
    moves ("x", X) (run horizontally to X) / ("y", Y) (vertically to Y), then into Q. Without moves it turns once,
    half-way between the stubs."""
    (px, py, pd), (qx, qy, qd) = P, Q
    o = lambda x, y, d, k: {"l": (x - k, y), "r": (x + k, y), "u": (x, y - k), "d": (x, y + k)}[d]  # noqa: E731
    p1, q1 = o(px, py, pd, stub), o(qx, qy, qd, stub)
    if not moves:
        moves = [("x", (p1[0] + q1[0]) / 2)] if pd in "lr" else [("y", (p1[1] + q1[1]) / 2)]
    pts = [(px, py), p1]
    for k, v in moves:
        pts.append((v, pts[-1][1]) if k == "x" else (pts[-1][0], v))
    pts += [(pts[-1][0], q1[1]), q1] if moves[-1][0] == "x" else [(q1[0], pts[-1][1]), q1]
    pts.append((qx, qy))
    out = []
    for p in pts:                   # drop repeats and collinear middles
        if out and abs(p[0] - out[-1][0]) < .05 and abs(p[1] - out[-1][1]) < .05:
            continue
        if len(out) >= 2 and ((abs(out[-2][0] - out[-1][0]) < .05 and abs(out[-1][0] - p[0]) < .05) or
                              (abs(out[-2][1] - out[-1][1]) < .05 and abs(out[-1][1] - p[1]) < .05)):
            out[-1] = p
            continue
        out.append(p)
    wire(g, out, c, w=w, **kw)
    if dots:
        for x, y, _ in (P, Q):
            dot(g, x, y, c)
    return out


def logic_box(g, x, y, w, h, title, sub, left=(), right=(), top=(), bottom=(), c=DG, size=8, span=(0, 1)):
    """A digital / behavioural block with named pins; returns {pin: (x, y, dir)}."""
    g.box(x, y + (14 if top else 0), w, h - (14 if top else 0), c, title, sub, tsize=10, ssize=7.5)
    P = {}
    for side, names in (("l", left), ("r", right), ("u", top), ("d", bottom)):
        n = len(names)
        for i, nm in enumerate(names):
            if side in "lr":
                py = y + h * (i + 1) / (n + 1) + (12 if h > 90 else 0) * (1 - 2 * (i + 1) / (n + 1)) * 0
                px = x if side == "l" else x + w
                g.line(px, py, px + (-6 if side == "l" else 6), py, c, 1.2)
                g.text(px + (5 if side == "l" else -5), py + 3, nm, "#a5f3fc" if c == DG else INK, size - 0.5,
                       "start" if side == "l" else "end")
                P[nm] = (px + (-6 if side == "l" else 6), py, side)
            else:
                px = x + w * (span[0] + (span[1] - span[0]) * (i + 1) / (n + 1))
                py = y if side == "u" else y + h
                g.line(px, py, px, py + (-6 if side == "u" else 6), c, 1.2)
                g.text(px, py + (11 if side == "u" else -5), nm, "#a5f3fc" if c == DG else INK, size - 0.5, "middle")
                P[nm] = (px, py + (-6 if side == "u" else 6), side)
    return P


def cap_glyph(g, x, y, c=INK, horiz=True, label=None):
    """A MOM unit between (x - 12, y) and (x + 12, y)."""
    g.line(x - 12, y, x - 2.5, y, AN)
    g.line(x - 2.5, y - 7, x - 2.5, y + 7, c, 1.6)
    g.line(x + 2.5, y - 7, x + 2.5, y + 7, c, 1.6)
    g.line(x + 2.5, y, x + 12, y, AN)
    if label:
        g.text(x, y - 11, label, DIM, 7, "middle")


def feed(g, P, y_end, c=DG, text=None):
    """A control line from a digital pin straight down to a frame edge, with the nets it carries."""
    x, y, _ = P
    g.line(x, y, x, y_end, c, 1.1, dash="3,2", arrow=True)
    if text:
        g.text(x + 4, y_end - 4, text, c, 7.5)


def page_tile():
    g = Svg()
    s1 = 0.6
    # ---- digital sources (RTL)
    drv = logic_box(g, 10, 4, 336, 46, "imc_driver · row codes", ["drive_o: {sgn, bit s of |x|} per row"],
                    bottom=["d", "sg"], span=(0.55, 0.95))
    wst = logic_box(g, 386, 4, 520, 46, "imc_wstage · array writer", ["WL per row, WBL per column bit"],
                    bottom=["wwl", "w7", "w6"])
    seq = logic_box(g, 946, 4, 660, 46, "imc_seq · phases on the DLL tick (142 ps)",
                    ["rst → top-plate resets · samp, sclk → SAR logic · trim → dtq slices 2–3"],
                    bottom=["rst", "sh", "mrg", "brst", "bank", "samp", "sclk", "trim"])

    # ---- B2 row driver
    frame(g, 10, 74, 336, 450, AN, "B2 · row driver (rdrv)", "one bit-plane of |x| per 0.849 ns slot",
          note="× 8 rows, rp and rn")
    rd = view("rdrv").draw(g, 16, 150, 0.55, AN)
    for i, t in enumerate(["NAND(d, sgb) → 4096-fin inverter", "on the tile supply vdr (R_PDN ≤ 0.4 Ω);",
                           "rsp: 46 Ω / 128 strap, cwp: rail wire.", "rn rail: the same driver on sg (x < 0)."]):
        g.text(22, 352 + 12 * i, t, SL, 7.5)
    feed(g, drv["d"], 74, text=None)
    feed(g, drv["sg"], 74)
    g.text(drv["d"][0] - 4, 70, "d, sg →", DG, 7.5, "end")

    # ---- B1 one weight bit
    frame(g, 386, 74, 520, 450, MEM, "B1 · gain-cell weight bit (half)",
          "half = 8 gc3t + smx + 7 xp + 7 MOM6 units", note="× 7 bits × 2 sides × 8 rows × 256 columns")
    gs = view("gc3t").draw(g, 396, 116, s1, MEM)
    gb = view("gc3t").draw(g, 396, 316, s1, MEM)
    sm = view("smx").draw(g, 640, 100, s1, AN)
    xp = view("xp").draw(g, 640, 330, s1, AN)
    g.text(560, 286, "sign bit (w7)", MEM, 8, "end", 600)
    g.text(404, 494, "magnitude bit 6 (w6)", MEM, 8, weight=600)
    bp = xp.at("bp")
    cx = bp[0] + 46
    g.line(bp[0], bp[1], cx - 12, bp[1], AN, 1.2)
    cap_glyph(g, cx, bp[1], label="cu6 4 fF")
    g.text(cx, bp[1] + 18, "MOM6", DIM, 7, "middle")
    tm = (cx + 12, bp[1], "r")
    # wstage -> cells, through the B2 | B1 channel
    for i, (pn, tg, net, x) in enumerate((("wwl", gs, "wwl", 358), ("w7", gs, "wbl", 366), ("w6", gb, "wbl", 374))):
        link(g, wst[pn], tg.at(net), ("y", 58 + 4 * i), ("x", x), c=MEM, w=1.2)
    link(g, wst["wwl"], gb.at("wwl"), ("y", 58), ("x", 358), c=MEM, w=1.2, dots=False)
    # cells -> mux / crosspoint (inside B1)
    for src, dst, net, mv in ((gs, sm, "s", None), (gb, xp, "s", None)):
        P = src.at("s")
        g.line(P[0], P[1], P[0] + 10, P[1], MEM, 1.2)
        g.tag(P[0] + 12, P[1] + 3, "s, sb →", MEM, 7)
    link(g, sm.at("l"), xp.at("l"), ("x", 792), ("y", 312), ("x", 628), c=AN)
    link(g, rd.at("rp"), sm.at("rp"), ("x", 352), ("y", 298), ("x", 616), c=AN, label="rp", lsize=7.5, at=0.93)
    link(g, (346, rd.at("rp")[1] + 18, "r"), sm.at("rn"), ("x", 380), ("y", 306), ("x", 624), c=AN, dash="4,2",
         stub=0, label="rn (sg path)", lsize=7.5, at=0.86, loff=9)

    # ---- ctl and B3
    frame(g, 946, 74, 660, 168, DG, "ctl · bank phase decode", "sh0 = sh·!bank, sh1 = sh·bank; mg, br alike",
          note="per tile; each output drives 1,024 switches")
    ct = view("ctl").draw(g, 1010, 104, 0.47, DG)
    for k in ("sh", "mrg", "brst", "bank"):
        feed(g, seq[k], 74)
    frame(g, 946, 256, 660, 268, AN, "B3 · column bank (bank)", "share → acc · 1:16 merge · MSB acc = C-DAC",
          note="× 2 ping-pong banks × 2 sides × 256 columns")
    sh = view("bank.share").draw(g, 956, 292, 0.55, AN)
    mg = view("bank.merge").draw(g, 1262, 292, 0.6, AN)
    sp = view("bank.step").draw(g, 1300, 404, 0.6, AN)
    link(g, tm, sh.at("tm"), ("x", 926), c=AN, label="tm", lsize=7.5, at=0.25)
    g.tag(1085, sh.at("tl")[1] - 9, "tl ← bits 0–3", AN, 7, "end")
    link(g, sh.at("bl"), mg.at("bl"), ("x", 1244), c=AN)
    A1, A2 = mg.at("a"), sp.at("a")
    link(g, A1, A2, ("x", 1520), c=AN, label=None)
    g.text(1530, (A1[1] + A2[1]) / 2, "a: MSB acc", AN, 7.5)
    g.text(1530, (A1[1] + A2[1]) / 2 + 10, "= C-DAC top", AN, 7.5)

    # ---- B4 converter
    frame(g, 10, 548, 1130, 396, AN, "B4 · E-trim SAR converter (conv)",
          note="1 per 3 columns · 86 per tile · 13 decisions, 1.61 ns, 276.8 fJ",
          foot="bank mux → double-tail comparator (preamp, latch) → async SAR logic → 3-level drivers on the step caps")
    mx = view("mux").draw(g, 24, 676, 0.55, AN)
    pr = view("dtf.pre").draw(g, 316, 610, 0.55, AN)
    la = view("dtf.lata").draw(g, 556, 596, 0.55, AN)
    lb = view("dtf.latb").draw(g, 556, 752, 0.55, AN)
    lg = logic_box(g, 812, 640, 128, 236, "SAR logic", ["imc_sar_logic.va", "cf, cq: the", "comparator clocks"],
                   left=["fa", "fb", "qa", "qb", "samp", "sclk", "bank"], right=["c<k>", "d<k>", "e<c>_<b>", "cv"],
                   top=["cf/cfb", "cq/cqb"], c=DG)
    bd = view("bpd2.out").draw(g, 1000, 640, 0.6, AN)
    # bank a -> mux -> comparator
    link(g, A2, mx.at("a00p", d="u"), ("x", 1520), ("y", 534), ("x", 262), ("y", 640), c=AN,
         label="a0p: column 0, bank 0 → converter", at=0.45, lsize=7.5, loff=9)
    link(g, mx.at("cp"), pr.at("inp"), ("x", 296), c=AN)
    link(g, mx.at("cn"), pr.at("inn"), ("x", 290), ("y", 744), ("x", 540), c=AN)
    link(g, pr.at("d2"), lb.at("d2"), ("x", 534), c=AN)
    link(g, pr.at("d1"), la.at("d1"), ("x", 304), ("y", 604), ("x", 528), c=AN)
    link(g, la.at("oa", d="d"), lg["fa"], ("y", 732), ("x", 780), c=AN)
    link(g, lb.at("ob", d="d"), lg["fb"], ("y", 870), ("x", 788), c=AN)
    link(g, lg["c<k>"], bd.at("ophb"), ("x", 968), c=DG)
    link(g, lg["d<k>"], bd.at("oplo"), ("x", 976), c=DG)
    link(g, bd.at("op"), sp.at("d0"), ("x", 1150), ("y", 540), ("x", 1290), c=AN, label="dp0", lsize=7.5, at=0.6)
    g.text(lg["e<c>_<b>"][0] + 4, lg["e<c>_<b>"][1] - 4, "→ mux e0_0", DG, 7)


    # ---- B5 reference, chain
    frame(g, 1176, 548, 430, 200, REF, "B5 · VCM reference (refbuf)", "class-A two-stage Miller follower",
          note="shared: 20 pF VCM decap per tile")
    rb = view("refbuf").draw(g, 1190, 594, 0.55, REF)
    link(g, rb.at("out", d="d"), bd.at("vcm"), ("y", 754), ("x", 1166), ("y", 616), c=REF, label="vcm", lsize=7.5)
    g.tag(bd.at("vref")[0] - 4, bd.at("vref")[1] - 14, "VREF = VDD_A", REF, 7, "end")
    g.box(1176, 762, 430, 182, DG, "→ imc_chain (RTL)", ["cv: 12-b code per column, 3 rounds per pass",
                                                       "B6 cal: (g·code + o + 2^13) >> 14",
                                                       "block-8 dequant: (c·σx·σw) << (14 − ex − ew)",
                                                       "B10: psum += cal (24 b; 52 b block-8)",
                                                       "→ the K-adjacent tile; requant at the end"],
          tsize=10, ssize=8, align="start")
    link(g, lg["cv"], (1176, 850, "l"), ("x", 1150), c=DG, arrow=False, label="cv", lsize=7.5)
    return g, dict(drv=drv, wst=wst, seq=seq, rd=rd, gs=gs, sm=sm, gb=gb, xp=xp, ct=ct, sh=sh, mg=mg, sp=sp,
                   mx=mx, pr=pr, la=la, lb=lb, lg=lg, bd=bd, rb=rb)


def thumb(g, name, x, y, w, h, c=AN):
    """A circuit thumbnail: the cktImg view, no names, fitted to (w, h)."""
    v = view(name)
    sc = v.fit(w, h)
    return v.draw(g, x + (w - v.size[0] * sc) / 2, y + (h - v.size[1] * sc) / 2, sc, c, names=False, text=4.5)


TILE_PARTS = [  # (title, sub, colour, thumbnail views)
    ("B2 row drive", "BS6H 0/V rails, 7 slots", AN, ["rdrv"]),
    ("B1 gain-cell array", "8 × 256 diff × 2 slices", MEM, ["gc3t", "xp"]),
    ("B3 columns", "share · 2 banks · 1:16 merge", AN, ["bank.merge"]),
    ("B4 E-trim SAR × 86", "1 per 3 columns, 12 b", AN, ["dtf.pre", "dtf.lata"]),
    ("B6 cal · B10 acc", "dequant, 24-b psum", DG, []),
]


def tile_block(g, x, y, w, h, name, thumbs=True):
    """One tile as a block: its five parts stacked in signal order, each with its circuit's thumbnail."""
    g.add(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="8" fill="#0b1222"/>')
    g.rect(x, y, w, h, AN, fill="rgba(6, 78, 59, 0.18)", rx=8, sw=1.8)
    g.text(x + 10, y + 17, name, "white", 11, weight=700)
    g.text(x + w - 10, y + 17, "18,962 µm²", SL, 7.5, "end")
    ph = (h - 30 - 4 * 6) / 5
    rows = []
    for i, (t, sub, c, th) in enumerate(TILE_PARTS):
        yy = y + 26 + i * (ph + 6)
        g.add(f'<rect x="{x + 8:.1f}" y="{yy:.1f}" width="{w - 16:.1f}" height="{ph:.1f}" rx="5" fill="#0b1222"/>')
        g.rect(x + 8, yy, w - 16, ph, c, rx=5, sw=1)
        g.text(x + 15, yy + 13, t, "white", 8.5, weight=600)
        g.text(x + 15, yy + 24, sub, SL, 7)
        if thumbs and th:
            tw = (w - 16) * 0.42 / len(th)
            for j, n in enumerate(th):
                thumb(g, n, x + w - 12 - (len(th) - j) * tw, yy + 3, tw - 2, ph - 6, c)
        rows.append((x + 8, yy, w - 16, ph))
    bx, by, bw, bh = rows[-1]          # the chain stage: psum_in + cal(code) -> psum_out
    cx, cy = bx + bw - 44, by + bh / 2 + 4
    g.circle(cx, cy, 9, DG, fill="#0b1222", w=1.3)
    g.text(cx, cy + 4, "Σ", DG, 11, "middle", 700)
    g.text(cx - 14, cy + 3, "cal(cv) →", DG, 6.5, "end")
    return rows


def page_system():
    g = Svg()
    # ---- memory and streams (top)
    g.box(10, 10, 220, 104, MEM, "HBM3 stack", ["819 GB/s · 24 GB · 4 pJ/b", "W8 weights 8.0 GB, streamed",
                                                "KV cache ≈ 15 GB: 4-b codes + fp16", "scale, 4-b ring for 8 + 120 tok"])
    g.box(262, 10, 190, 104, ST, "HBM PHY", ["13.0 mm² · 0.50 pJ/b", "weights just ahead of", "the activations"])
    g.box(484, 10, 210, 104, ST, "TDM NoC", ["circuit-switched", "multicast 16 · 0.29 mm²", "rail headroom 2.0"])
    g.box(726, 10, 250, 104, MEM, "Activation SRAM 16 MB", ["4.7 mm² · INT8 per token,", "Hadamard-rotated,",
                                                           "8 rows per tile per pass"])
    g.line(230, 50, 260, 50, MEM, 1.6, arrow=True)
    g.line(452, 50, 482, 50, ST, 1.6, arrow=True)
    g.line(694, 50, 724, 50, ST, 1.6, arrow=True)
    g.line(724, 74, 696, 74, ST, 1.2, arrow=True)

    # ---- the tile array
    g.rect(10, 140, 1086, 600, AN, fill="rgba(52, 211, 153, 0.03)", rx=12, dash="8,4", sw=1.2)
    g.text(290, 160, "IMC TILE ARRAY · 3,181 tiles, 60.3 mm² (P) · 8 rows × 256 differential columns × 2 slices",
           AN, 10, weight=600)
    g.text(290, 174, "one pass = 2,048 MACs in t_pass 5.96 ns (RTL, 42 ticks, drive-bound) · K-adjacent tiles chain "
           "their partial sums", SL, 8)
    # driver
    g.box(24, 190, 232, 500, DG, None)
    g.text(34, 208, "imc_driver (RTL)", "white", 11, weight=700)
    g.text(34, 221, "digital/imc_driver/src", SL, 7.5)
    subs = [("descriptor schedule", ["systolic skew: element e", "enters tile t at pass e + t + 1"]),
            ("row codes", ["sign-magnitude |x| ≤ 127,", "bit s of |x| in slot s (BS6H)"]),
            ("imc_seq", ["pass FSM, merge engine,", "conversion rounds, phases"]),
            ("imc_wstage", ["ping-pong stage banks per tile,", "JIT array writes, refresh / 128"]),
            ("imc_chain", ["cal (g, o), block-8 dequant,", "psum chain, edge acc, requant"])]
    for i, (t, ls) in enumerate(subs):
        yy = 232 + i * 90
        g.rect(34, yy, 212, 80, DG, rx=5, sw=1)
        g.text(44, yy + 16, t, "#a5f3fc", 9, weight=600)
        for j, ln in enumerate(ls):
            g.text(44, yy + 32 + 12 * j, ln, SL, 7.5)
    # tiles
    tx = [(288, "tile 0"), (526, "tile 1"), (848, "tile N − 1")]
    for x, nm in tx:
        tile_block(g, x, 190, 224, 430, nm)
    g.text(800, 400, "⋯", SL, 28, "middle")
    g.text(800, 424, "× 3,181", SL, 9, "middle", 600)
    # driver -> tiles: phases and row codes (top bus), weights
    g.line(256, 300, 286, 300, DG, 1.6, arrow=True)
    g.text(271, 293, "x, φ", DG, 7.5, "middle")
    g.poly([(256, 520), (272, 520), (272, 640), (1076, 640), (1076, 612)], DG, 1.1, dash="4,3")
    for x, _ in tx:
        g.line(x + 112, 640, x + 112, 622, DG, 1.1, dash="4,3", arrow=True)
    g.text(684, 634, "phases and row codes → every tile", DG, 7.5)
    # chain
    for (x0, _), (x1, _) in zip(tx, tx[1:]):
        g.line(x0 + 224, 580, x1, 580, DG, 1.8, arrow=True)
    g.text(800, 596, "psum 24 b × 256", DG, 7.5, "middle")
    g.text(524, 574, "", DG, 7.5, "middle")
    # B5 shared reference
    g.box(288, 662, 500, 66, REF, None)
    g.text(298, 680, "B5 · VCM reference (refbuf), shared", "white", 9.5, weight=600)
    g.text(298, 694, "class-A Miller follower → vcm, 20 pF decap per tile", SL, 7.5)
    g.text(298, 706, "VREF = VDD_A 0.7 V; droop calibrated (85 dB)", SL, 7.5)
    thumb(g, "refbuf", 640, 666, 140, 58, REF)
    for x, _ in tx:
        g.line(x + 30, 662, x + 30, 622, REF, 1.2, arrow=True)
    g.text(322, 650, "vcm", REF, 7.5)
    # calibration
    g.box(812, 662, 270, 66, DG, None)
    g.text(822, 680, "calibration · timebase", "white", 9.5, weight=600)
    g.text(822, 694, "cal words per column (g 16 b, o 20 b), once", SL, 7.5)
    g.text(822, 706, "trim bit (SS dies) · DLL replica tick 142 ps", SL, 7.5)

    # ---- weights and activations into the array
    g.poly([(600, 114), (600, 132), (140, 132), (140, 188)], MEM, 1.4, arrow=True)
    g.text(300, 127, "W8 weight stream → stage banks (32,768 b per tile load)", MEM, 7.5)
    g.poly([(850, 114), (850, 136), (200, 136), (200, 188)], ST, 1.4, arrow=True)
    g.text(860, 131, "x_in: INT8 + block scale byte", ST, 7.5)

    # ---- chain end, requant, rail
    g.box(1130, 470, 220, 96, DG, "B6′ requant", ["INT8 per token: 6-b shift,", "scale u8, offset s8", "at the chain end (imc_chain)"])
    g.poly([(1072, 580), (1110, 580), (1110, 520), (1128, 520)], DG, 1.8, arrow=True)
    g.text(1114, 600, "completed outputs, once per K", DG, 7.5)
    g.box(1130, 140, 476, 300, DG, None)
    g.text(1142, 160, "Digital rail · 4.6 mm² (spec B8, no RTL yet)", "white", 11, weight=700)
    rail = [("Q·Kᵀ and P·V lanes", "q8 × k4 bulk · q8 × k8 sink 8 + recent 120", 14.7),
            ("online softmax", "base-2 exp from a ROM", 0),
            ("FWHT", "Hadamard on q, k, v, o", 0),
            ("RMSNorm · RoPE · SwiGLU", "per token", 0),
            ("KV pack / unpack", "4-b codes + fp16 scale per (token, head)", 0)]
    for i, (t, sub, _) in enumerate(rail):
        yy = 172 + i * 52
        g.rect(1142, yy, 452, 44, DG, rx=5, sw=1)
        g.text(1152, yy + 17, t, "#a5f3fc", 9.5, weight=600)
        g.text(1152, yy + 32, sub, SL, 7.5)
    g.text(1152, 444 - 10, "14.7 TMAC/s attention at 45.6 fJ per MAC (P)", SL, 7.5)
    g.line(1240, 470, 1240, 444, DG, 1.6, arrow=True)
    # rail -> activation SRAM (next layer) and KV <-> HBM
    g.poly([(1370, 140), (1370, 124), (990, 124), (990, 74), (978, 74)], ST, 1.4, arrow=True)
    g.text(1180, 119, "next layer's activations", ST, 7.5, "middle")
    g.poly([(1560, 140), (1560, 0 + 6), (120, 6), (120, 8)], MEM, 1.2, dash="5,3")
    g.text(1300, 4 + 0, "", MEM, 7)
    g.text(1556, 128, "KV cache ↔ HBM (via the PHY)", MEM, 7.5, "end")

    # ---- legend, numbers, provenance
    ly = 770
    g.box(10, ly, 400, 170, SL, None)
    g.text(22, ly + 18, "LEGEND", SL, 9, weight=700)
    items = [(AN, "analog: transistor circuits (cktImg)"), (DG, "digital: RTL modules"), (MEM, "memory / weights"),
             (REF, "reference / bias"), (ST, "streams: HBM PHY, NoC")]
    for i, (c, t) in enumerate(items):
        g.rect(22, ly + 30 + 18 * i, 16, 10, c, rx=2, sw=1)
        g.text(46, ly + 39 + 18 * i, t, "#cbd5e1", 8)
    g.line(240, ly + 35, 270, ly + 35, AN, 1.4)
    g.text(278, ly + 38, "signal wire", "#cbd5e1", 8)
    g.line(240, ly + 53, 270, ly + 53, DG, 1.1, dash="4,3")
    g.text(278, ly + 56, "control / phases", "#cbd5e1", 8)
    g.circle(255, ly + 71, 3, INK, fill="#0b1222")
    g.text(278, ly + 74, "circuit port", "#cbd5e1", 8)
    g.text(255, ly + 92, "clk", "#7dd3fc", 8, "middle", italic=True)
    g.text(278, ly + 92, "net by name", "#cbd5e1", 8)
    g.text(22, ly + 136, "P projected (ARCH_CHOSEN target) · D derived · M measured", SL, 7.5)
    g.text(22, ly + 150, "(ESPice on ASAP7, or the RTL for timing)", SL, 7.5)

    g.box(426, ly, 600, 170, AN, None)
    g.text(438, ly + 18, "KEY NUMBERS", AN, 9, weight=700)
    nums = [("t_pass", "5.96 ns", "42 ticks × 142 ps, drive-bound (RTL, M)"),
            ("per tile", "2,048 MAC / pass", "8 rows × 256 diff columns × 2 slices"),
            ("ADC share", "3", "86 E-trim 12-b SARs per tile; 1.61 ns, 276.8 fJ (D on M)"),
            ("drive", "BS6H", "7 bit-serial slots of 0.849 ns; 0.067 % settling (M)"),
            ("banks", "2 ping-pong", "1:16 slice merge under the next pass"),
            ("chain", "24 b", "52 b with block-8; one hop per pass (P)"),
            ("energy", "351 pJ / pass", "≈ 172 fJ / MAC with chain and block-8 (P/D)"),
            ("supplies", "0.7 V / 0.5 V", "VDD_A analog, VDD_L logic at 0.524 GHz")]
    for i, (k, v, d) in enumerate(nums):
        yy = ly + 38 + 16 * i
        g.text(438, yy, k, SL, 8)
        g.text(520, yy, v, "white", 8.5, weight=600)
        g.text(640, yy, d, SL, 7.5)

    g.box(1042, ly, 564, 170, SL, None)
    g.text(1054, ly + 18, "WHERE THE DRAWINGS COME FROM", SL, 9, weight=700)
    prov = ["analog/imc_tile/netlist/imc_tile.py: the ASAP7 transistor netlist (SpiceRack)",
            "  --draw: one cktImg placement per stage or slice → output/schematics/*.json",
            "  every circuit in this document is that placement, restyled, not redrawn",
            "digital/imc_driver/src: imc_driver, imc_seq, imc_wstage, imc_chain (Verilog-2001)",
            "docs/src/content/Project/ARCH_CHOSEN.md: blocks B1–B10 and the numbers",
            "pages: 1 system · 2 one tile · 3 drive and array · 4 column · 5 converter ·",
            "       6 netlist hierarchy and reference · 7 digital"]
    for i, t in enumerate(prov):
        g.text(1054, ly + 38 + 16 * i, t, "#cbd5e1" if not t.startswith(" ") else SL, 7.8)
    return g


def nb(g, P, text, c=AN, n=28, size=7.5, dash=None):
    """A port wired out to a named neighbour: a wire `n` px along the port's free side, then a tag. P is a landing
    point, or (Placed, net[, k]) to use that net's port only when it sits on the circuit's edge (an interior port
    keeps its name and gets no wire)."""
    if isinstance(P[0], Placed):
        pl, net, k = (*P, 0)[:3]
        x, y, d = pl.port(net, k)
        x0, y0, x1, y1 = pl.box
        reach = {"l": x - x0, "r": x1 - x, "u": y - y0, "d": y1 - y}[d]
        if reach > 0.16 * ((x1 - x0) if d in "lr" else (y1 - y0)) + 14:
            return False
        P = pl.take(net, k)
    x, y, d = P
    ex, ey = {"l": (x - n, y), "r": (x + n, y), "u": (x, y - n), "d": (x, y + n)}[d]
    g.line(x, y, ex, ey, c, 1.3, dash=dash)
    dot(g, x, y, c)
    if d == "l":
        g.tag(ex, ey + 3, text, c, size, "end")
    elif d == "r":
        g.tag(ex, ey + 3, text, c, size, "start")
    elif d == "u":
        g.tag(ex, ey - 4, text, c, size, "middle")
    else:
        g.tag(ex, ey + 10, text, c, size, "middle")
    return True


def placed(name, x, y, s, g, c=AN, **kw):
    return view(name).draw(g, x, y, s, c, **kw)


def page_drive_array():
    g = Svg()
    # ---- B2 row driver, large
    frame(g, 10, 10, 760, 470, AN, "B2 · bit-serial row driver (rdrv)", "BS6H: slot s puts bit s of |x| on rp (x ≥ 0) "
          "or rn (x < 0) as 0 or V", note="netlist: rdrv · drawn: the rp rail; × 8 rows per tile")
    rd = placed("rdrv", 96, 76, 0.98, g, fins=True, text=8.5)
    nb(g, rd.take("d", 1), "d ← imc_driver drive_o", DG, 22)
    nb(g, rd.take("sg", 0), "sg ← drive_o sign", DG, 18)
    nb(g, rd.take("vdr"), "vdr: tile supply, R_PDN ≤ 0.4 Ω", REF, 26)
    nb(g, rd.take("rp"), "rp → B1 smx", AN, 16)
    for i, t in enumerate(["The NAND passes the bit when the sign is right: rp carries d when sg = 0, rn when sg = 1.",
                           "The rail inverter is 4,096 fins for a full 256-column row (7.47 pF of plates).",
                           "rsp is the segment strap (46 Ω / 128), cwp the rail wire (0.3 pF).",
                           "Settling at the share edge, 8 rows on V: 0.067 % (M, ESPice, with the share kick).",
                           "Fallback BS6H-cc adds a constant-charge dummy (not drawn): 3 % tracking residual."]):
        g.text(24, 404 + 13 * i, t, SL, 8)

    # ---- B1 cells
    frame(g, 790, 10, 816, 470, MEM, "B1 · gain bit, sign mux, crosspoint", "one W8 weight side = 8 gain bits "
          "(sign + 7) + 1 sign mux + 7 crosspoints + 7 MOM6 units", note="netlist: gc3t, smx, xp")
    gc = placed("gc3t", 800, 90, 0.92, g, MEM, fins=True, text=8.5)
    sm = placed("smx", 1066, 70, 0.92, g, AN, fins=True, text=8.5)
    xp = placed("xp", 1380, 90, min(0.86, 212 / view("xp").size[0]), g, AN, fins=True, text=8.5)
    g.text(812, 82, "gc3t: gain bit", MEM, 9, weight=600)
    g.text(1078, 66, "smx: sign mux", AN, 9, weight=600)
    g.text(1392, 82, "xp: crosspoint", AN, 9, weight=600)
    nb(g, gc.take("wwl"), "wwl ← imc_wstage WL", MEM, 10)
    nb(g, gc.take("wbl"), "wbl ← WBL bit", MEM, 10)
    nb(g, gc.take("s", d="d"), "s → xp / smx", MEM, 14)
    nb(g, sm.take("rp"), "rp ← B2", AN, 10)
    nb(g, sm.take("rn"), "rn ← B2", AN, 10)
    nb(g, sm.take("l"), "l → xp", AN, 10)
    nb(g, xp.take("l"), "l ←", AN, 8)
    nb(g, xp.take("bp", 0), "bp → MOM", AN, 8)
    for i, t in enumerate(["gc3t: SRAM-Vt write FET onto node m (held as charge); two inverters give s and sb",
                           "(the second inverter is the gc5t buffer: 3.3 % plate error without it, M).",
                           "smx: the side's line l follows rp (w ≥ 0) or rn (w < 0); the − side swaps rp / rn.",
                           "xp: bit '1' → the TG ties the unit's bottom plate to l; '0' → mg grounds it.",
                           "Units: MSB slice 1/2/4 × 1 fF, LSB slice 1/2/4/8 × 0.25 fF, top plates tm / tl."]):
        g.text(804, 404 + 13 * i, t, SL, 8)

    # ---- the netlist around them (cktImg block views)
    frame(g, 10, 496, 1596, 446, SL, "How they compose (cktImg block views of the netlist, buses bundled)",
          "half: one side of one weight · wcell: the two sides · rows: the drivers · arr: the array",
          note="block views drawn at 2 rows × 3 columns; supplies left off the blocks")
    hv = view("half")
    placed("half", 30, 560, 1.18, g, MEM, text=8)
    g.text(30, 556, "half (" + hv.note + ")", MEM, 8.5, weight=600)
    placed("wcell", 90, 744, 1.1, g, MEM, text=8)
    g.text(40, 706, "wcell = 2 × half (the − side on swapped rails)", MEM, 8.5, weight=600)
    placed("rows", 520, 712, 0.75, g, AN, text=8)
    g.text(520, 708, "rows = 8 × rdrv (" + view("rows").note + ")", AN, 8.5, weight=600)
    for i, t in enumerate(["arr = 8 rows × 256 wcell: row r's rp/rn and wwl run along the row,",
                           "column c's tmp / tmn / tlp / tln (the slice top plates) down the column.",
                           "Per tile: 4,096 half-cells, 32,768 gain bits written per load in 0.253 ns",
                           "(31.6 ps per row, P), refreshed every 128 passes (0.76 µs, D)."]):
        g.text(900, 740 + 14 * i, t, SL, 8.5)
    return g


def page_column():
    g = Svg()
    frame(g, 10, 10, 560, 470, AN, "bsw · bootstrapped share switch", "constant V_GS: mm's gate rides cb on top of "
          "the input", note="netlist: bsw · 2 per bank (MSB, LSB)")
    bw = placed("bsw", 120, 64, min(0.78, 430 / view("bsw").size[0], 330 / view("bsw").size[1]), g, fins=True, text=8.5)
    nb(g, (bw, "ck"), "sh0 / sh1 (ctl) →", DG, 16)
    for i, t in enumerate(["a ← tm / tl (the slice top plate) · b → a / bl (the bank's accumulator).",
                           "ck low: c1, c2 charge cb to VDD, g0 holds the gate at 0.",
                           "ck high: t1 / t2 put cb between the input and mm's gate: V_GS ≈ 0.65 V.",
                           "mm 32 fins; cb 20 fF ≫ its gate (V7: the gate reaches about 1.3 V)."]):
        g.text(24, 419 + 13 * i, t, SL, 8)

    frame(g, 590, 10, 1016, 470, AN, "bank · one accumulation bank of one column side",
          "share → acc · 1:16 slice merge · the MSB acc is the C-DAC of the direct SAR",
          note="netlist: bank · × 2 ping-pong × 2 sides per column")
    sh = placed("bank.share", 640, 70, 0.95, g, fins=True, text=8.5)
    mg = placed("bank.merge", 1160, 70, 1.0, g, fins=True, text=8.5)
    sp = placed("bank.step", 1200, 270, 1.0, g, fins=True, text=8.5)
    g.text(650, 66, "share switches and bank reset", AN, 9, weight=600)
    g.text(1170, 66, "LSB acc + merge cap (1:16)", AN, 9, weight=600)
    g.text(1210, 266, "step cap 0 of 12 (the C-DAC)", AN, 9, weight=600)
    nb(g, sh.take("tm"), "tm ← B1", MEM, 14)
    nb(g, sh.take("tl"), "tl ←", MEM, 8)
    link(g, sh.at("bl"), mg.take("bl"), ("x", 1130), c=AN, label="bl", lsize=8)
    A1, A2 = mg.take("a"), sp.take("a")
    link(g, A1, A2, ("x", 1520), c=AN)
    nb(g, (1520, (A1[1] + A2[1]) / 2, "r"), "a → B4 mux", AN, 6)
    nb(g, sp.take("d0"), "d0 ← B4 bpd2 (dp0)", AN, 14)
    for i, t in enumerate(["Accumulate: sh closes once per slot; bottoms of the step caps sit at GND (enb).",
                           "Merge, under the next pass: mg joins C_m (ρ = 0.134, 1:16) to the MSB acc a.",
                           "Convert: en hands each step cap's bottom to the converter's driver d<k>.",
                           "Reset: br clears a, bl and mm before the bank's next pass (φ_brst).",
                           "Step caps: 1024, 512, 256, 128, 64, 32, 32, 16, 8, 4, 2, 1 LSB of the 56 fF slice."]):
        g.text(604, 406 + 13 * i, t, SL, 8)

    frame(g, 10, 496, 700, 260, DG, "ctl · per-bank phase decode", "from imc_seq's sh, mrg, brst and bank",
          note="netlist: ctl · drawn: sh0, sh1 (mg, br alike)")
    placed("ctl", 50, 540, 0.72, g, DG, text=8)

    frame(g, 726, 496, 880, 260, SL, "BS6H slot and the bank hand-off (imc_seq, RTL)", "")
    # a small timing strip: one slot of 6 ticks, then the pass of 7 slots
    t0, tk, y0 = 790, 22, 556
    sig = [("φ_rst", [(0, 0.5)], AN), ("rails", [(1, 5.5)], ST), ("φ_sh", [(2, 5)], AN)]
    for i, (nm, ps, c) in enumerate(sig):
        yb = y0 + 22 * i
        g.text(t0 - 8, yb, nm, c, 8, "end")
        pts = [(t0, yb)]
        for a, b in ps:
            pts += [(t0 + a * tk * 2, yb), (t0 + a * tk * 2, yb - 10), (t0 + b * tk * 2, yb - 10), (t0 + b * tk * 2, yb)]
        pts.append((t0 + 6 * tk * 2, yb))
        g.poly(pts, c, 1.4)
    for k in range(7):
        g.line(t0 + k * tk * 2, y0 - 16, t0 + k * tk * 2, y0 + 50, FAINT, 0.8, dash="2,2")
    g.text(t0 + 3 * tk * 2, y0 + 66, "one slot = 6 ticks of 142 ps = 0.849 ns", SL, 8, "middle")
    g.text(t0 + 3 * tk * 2, y0 + 78, "rails on V 4 ticks before the share edge", SL, 8, "middle")
    for i, t in enumerate(["pass p: 7 slots on bank p mod 2 (42 ticks, 5.96 ns)",
                           "hand-off: bank flips one tick after the last share;",
                           "φ_mrg merges the old bank under the next pass's slot 0,",
                           "φ_samp hands it to the SAR; φ_brst resets the new bank",
                           "in slot 0, tick 1. The FSM waits only if the converter",
                           "has not sampled the previous bank yet (StWait)."]):
        g.text(1240, 552 + 14 * i, t, SL, 8)

    frame(g, 10, 770, 1596, 172, SL, "col · one column pair (cktImg block view): 4 top-plate resets + 4 banks",
          "", note="netlist: col · × 256 per tile")
    cv = view("col")
    placed("col", 40, 806, min(1.0, 1540 / cv.size[0], 128 / cv.size[1]), g, AN, text=7)
    return g


def page_converter():
    g = Svg()
    frame(g, 10, 10, 860, 486, AN, "dtf · fast double-tail comparator (decisions 1–6)",
          "stage 1: tail + input pair on Di nodes d1 / d2, reset by clk · stage 2: latch tailed by mt2 on clkb",
          note="netlist: dtf · σ 1.82 mV (M) · cross-coupling drawn by name")
    pr = placed("dtf.pre", 70, 110, 0.92, g, fins=True, text=8.5)
    la = placed("dtf.lata", 460, 60, 0.95, g, fins=True, text=8.5)
    lb = placed("dtf.latb", 460, 300, 0.95, g, fins=True, text=8.5)
    g.text(40, 104, "preamp (Schinkel double tail)", AN, 9, weight=600)
    g.text(470, 56, "latch, side a + output inverter", AN, 9, weight=600)
    g.text(470, 296, "latch, side b + output inverter", AN, 9, weight=600)
    link(g, pr.take("d2"), lb.take("d2"), ("x", 440), c=AN, label="d2", lsize=8)
    link(g, pr.take("d1"), la.take("d1"), ("x", 56), ("y", 92), ("x", 444), c=AN, label="d1", lsize=8, at=0.9)
    nb(g, lb.take("t2", d="r"), "t2: mt2's drain, side a", AN, 30)
    nb(g, (pr, "inp"), "cp ← mux", AN, 10)
    nb(g, (pr, "inn"), "cn ← mux", AN, 10)
    nb(g, (la, "xa"), "xa", AN, 6)
    nb(g, (lb, "xb"), "xb", AN, 6)
    for i, t in enumerate(["oa / ob (the latch nodes) → SAR logic fa / fb; the drawn ob / oa gate names close the loop.",
                           "clk ← SAR logic cf, clkb ← cfb: the logic fires the next decision when one resolves."]):
        g.text(24, 464 + 13 * i, t, SL, 8)

    frame(g, 886, 10, 720, 486, AN, "dtq · quiet tail-starved double-tail (decisions 8–13)",
          "three ×2 input slices on the shared d1 / d2; slices 2–3 run on clkt = clk · trim",
          note="netlist: dtq · σ 0.654 mV TT, 0.585 mV trimmed SS (M / D)")
    placed("dtq.pre", 906, 96, 0.82, g, fins=True, text=8.5)
    qt = placed("dtq.trim", 1260, 96, 0.82, g, fins=True, text=8.5)
    g.text(916, 92, "preamp, slice 1 (32-fin pair)", AN, 9, weight=600)
    g.text(1270, 92, "trim gate: AND(clk, trim)", AN, 9, weight=600)
    nb(g, (qt, "trim"), "trim ← imc_seq", DG, 8)
    for i, t in enumerate(["Slices 2 and 3 are slice 1 again on tails tl2 / tl3, clocked by clkt: on SS dies trim = 1",
                           "and all three run (×6 input pair), off elsewhere. The latch is dtf's with 16-fin",
                           "regeneration and a 16-fin tail: the same two drawings, sizes in the netlist.",
                           "E-trim schedule: 6 fast decisions (1024 … 32 LSB), one redundant 32-LSB step,",
                           "then 7 quiet ones (16 … 1): 13 decisions, 12-b code, 1.61 ns, 276.8 fJ (D on M)."]):
        g.text(906, 400 + 13 * i, t, SL, 8)

    frame(g, 10, 512, 1596, 430, AN, "conv · one converter: bank mux, comparators, SAR logic, 3-level C-DAC drivers",
          "", note="netlist: conv · 1 per 3 columns (86 per tile) · Verilog-A logic, transistors elsewhere")
    mx = placed("mux", 76, 600, 0.84, g, fins=True, text=8.5)
    g.text(40, 592, "column / bank mux (6 TGs per converter; drawn: column 0, bank 0)", AN, 9, weight=600)
    nb(g, (mx, "a00n"), "a0n ← bank", AN, 6)
    for i, t in enumerate(["a00p / a00n ← column 0's bank 0 (+ and − side),", "e0_0 ← the logic: one enable per column "
                           "and bank", "cp / cn → both comparators' inp / inn"]):
        g.text(40, 730 + 13 * i, t, SL, 8)
    lg = logic_box(g, 520, 590, 190, 250, "SAR logic", ["Verilog-A: imc_sar_logic.va", "async: each decision",
                                                       "clocks the next"],
                   left=["fa", "fb", "qa", "qb", "samp", "sclk", "bank"], right=["c<k>", "d<k>", "e<c>_<b>", "cv"],
                   top=["cf/cfb", "cq/cqb"], c=DG)
    for k, t in (("fa", "← dtf oa"), ("fb", "← dtf ob"), ("qa", "← dtq oa"), ("qb", "← dtq ob"),
                 ("samp", "← imc_seq"), ("sclk", "← imc_seq"), ("bank", "← imc_seq")):
        nb(g, lg[k], t, DG if k in ("samp", "sclk", "bank") else AN, 10)
    nb(g, lg["e<c>_<b>"], "→ mux", DG, 10)
    nb(g, lg["cv"], "cv → imc_chain", DG, 10)
    dc = placed("bpd2.dec", 840, 600, 0.82, g, fins=True, text=8.5)
    ou = placed("bpd2.out", 1340, 660, 0.95, g, fins=True, text=8.5)
    g.text(850, 592, "driver decode (NAND, AND of c, d)", AN, 9, weight=600)
    g.text(1350, 592, "3-level driver, 1024-LSB step", AN, 9, weight=600)
    for k in ("c<k>", "d<k>"):
        g.line(lg[k][0], lg[k][1], dc.box[0] - 4, lg[k][1], DG, 1.3, arrow=True)
    g.text((lg["c<k>"][0] + dc.box[0]) / 2, lg["c<k>"][1] + 22, "c<k>, d<k> → cb, db", DG, 7.5, "middle")
    link(g, dc.take("oplo"), ou.take("oplo"), ("x", 1310), c=AN, label="oplo", lsize=8, at=0.7)
    nb(g, ou.take("ophb"), "ophb ← NAND", AN, 10)
    nb(g, (ou, "op"), "dp<k> → step cap k", AN, 12)
    nb(g, ou.take("vcm"), "vcm ← refbuf", REF, 10)
    nb(g, ou.take("vref"), "VREF = VDD_A", REF, 22)
    for i, t in enumerate(["c = 1: the step cap's bottom to VCM (sampling, mid level).",
                           "c = 0, d = 1: + side to VREF, − side to GND; d = 0: the reverse.",
                           "Switches scale with the step: 32 fins on the 1024 cap, 16 / 8 / 4 below."]):
        g.text(850, 880 + 13 * i, t, SL, 8)
    return g


def page_hierarchy():
    g = Svg()
    frame(g, 10, 10, 800, 470, SL, "tile (cktImg block view)", "rows → arr → cgrp, with ctl decoding the bank phases",
          note="netlist: tile · " + view("tile").note)
    tv = view("tile")
    placed("tile", 60, 60, min(1.25, 700 / tv.size[0], 400 / tv.size[1]), g, AN, text=8)
    frame(g, 826, 10, 780, 470, SL, "tiles (cktImg block view)", "N tiles on their R_PDN, one VCM buffer and decap",
          note="netlist: tiles · " + view("tiles").note)
    ts = view("tiles")
    placed("tiles", 846, 120, min(1.0, 740 / ts.size[0]), g, AN, text=8)
    for i, t in enumerate(["rpdn<t>: the tile supply's PDN resistance (0.4 Ω per full tile) between vdd and vdr<t>.",
                           "cvcm: 20 pF of VCM decap per tile. refbuf: the class-A follower that holds vcm.",
                           "Every tile sees the same phases; the RTL gives each its own row codes and weights."]):
        g.text(846, 410 + 13 * i, t, SL, 8)

    frame(g, 10, 496, 980, 446, AN, "cgrp · ADC share 3: three columns, one converter",
          "12 bank nodes (3 columns × 2 banks × 2 sides) into one converter; tm/tl c: column c's 4 slice top plates",
          note="netlist: cgrp = 3 × col + conv · × 86 per tile")
    for c in range(3):
        y = 560 + c * 112
        g.box(90, y, 170, 96, AN, None)
        g.text(100, y + 16, f"col {c} (column 3j + {c})", "white", 9, weight=600)
        g.text(100, y + 29, "4 plate resets, 4 banks", SL, 7.5)
        thumb(g, "bank.merge", 98, y + 34, 110, 56, AN)
        g.line(22, y + 40, 88, y + 40, MEM, 1.3, arrow=True)
        g.text(24, y + 34, f"tm/tl {c}", MEM, 7.5)
        g.line(72, y + 80, 88, y + 80, AN, 1.1, arrow=True)
        for k, nm in enumerate(("a0p", "a0n", "a1p", "a1n")):
            yy = y + 18 + k * 20
            g.text(232, yy + 3, nm, AN, 6.5, "end")
            g.poly([(260, yy), (330 + 4 * (c * 4 + k), yy), (330 + 4 * (c * 4 + k), 576 + 22 * (c * 4 + k)),
                    (390, 576 + 22 * (c * 4 + k))], AN, 1.0)
    g.box(390, 552, 580, 330, AN, None)
    g.text(400, 569, "conv", "white", 10, weight=700)
    g.box(398, 580, 120, 256, AN, None)
    g.text(404, 596, "mux: 12 TGs", INK, 8, weight=600)
    thumb(g, "mux", 402, 600, 112, 40, AN)
    g.text(404, 656, "e<c>_<b> picks", SL, 7)
    g.text(404, 666, "column c, bank b", SL, 7)
    g.line(518, 700, 548, 700, AN, 1.3, arrow=True)
    g.text(533, 694, "cp/cn", AN, 7, "middle")
    for i, (nm, v) in enumerate((("dtf (fast)", "dtf.pre"), ("dtq (quiet)", "dtq.pre"))):
        y = 600 + i * 104
        g.box(550, y, 140, 92, AN, None)
        g.text(558, y + 14, nm, INK, 8, weight=600)
        thumb(g, v, 556, y + 20, 128, 68, AN)
    g.box(712, 600, 110, 196, DG, None)
    g.text(767, 618, "SAR logic", "white", 8.5, "middle", 600)
    g.text(767, 632, "Verilog-A", SL, 7, "middle")
    g.line(690, 646, 710, 646, AN, 1.2, arrow=True)
    g.line(690, 750, 710, 750, AN, 1.2, arrow=True)
    g.box(842, 600, 116, 196, AN, None)
    g.text(900, 616, "bpd2 × 12", INK, 8, "middle", 600)
    thumb(g, "bpd2.out", 848, 624, 104, 120, AN)
    g.line(822, 700, 840, 700, DG, 1.2, arrow=True)
    g.text(831, 694, "c, d", DG, 7, "middle")
    g.poly([(900, 796), (900, 900), (72, 900), (72, 640)], AN, 1.3)
    g.text(520, 914, "dp<0:11> / dn<0:11>: the drivers onto every bank's step caps (the C-DAC)", AN, 7.5, "middle")
    g.line(767, 796, 767, 850, DG, 1.2)
    g.poly([(767, 850), (975, 850)], DG, 1.3, arrow=True)
    g.text(872, 844, "cv_j → imc_chain", DG, 7.5, "middle")
    g.text(400, 876, "rounds: column 3j + r converts in round r of the pass, from the bank merged under it", SL, 7.5)
    frame(g, 1006, 496, 600, 446, REF, "B5 · refbuf: class-A VCM follower", "two-stage Miller, unity gain, "
          "the loop drawn by name (out on m1's gate)", note="netlist: refbuf")
    rb = placed("refbuf", 1030, 560, 0.76, g, REF, fins=True, text=8.5)
    nb(g, (rb, "ib"), "ib ← 20 µA bias", REF, 10)
    for i, t in enumerate(["vin ← vbias (VDD_A / 2); out → vcm, the converters' mid level.",
                           "m1 / m2 input pair on tail mt, m3 / m4 mirror, mo + mk class-A output,",
                           "cc 60 fF Miller. The feedback goes to the mirror's diode side because",
                           "the PMOS output stage inverts (found in the transistor run, M).",
                           "Reference droop: 130 µV per conversion against 3.7 µV (FAIL by 35×),",
                           "a calibrated static error: the ref term is 85 dB (D)."]):
        g.text(1022, 800 + 13 * i, t, SL, 8)
    return g


def page_digital():
    g = Svg()
    g.box(10, 10, 1596, 40, DG, None)
    g.text(24, 35, "imc_driver: the controller a weight-stationary systolic array would have, mapped onto the charge-domain "
           "tile · Verilog-2001 (it also runs as a VerA device in ESPice)", "white", 9.5, weight=600)
    # module boxes with their internals
    mods = [
        (10, 64, 520, 420, "imc_driver.v", "top: descriptor generator, row codes",
         [("descriptor schedule", ["for n-block, m-chunk, k-group, token: one element;",
                                   "element e enters tile t at pass e + t + 1 (systolic skew)"]),
          ("activation read", ["one word per tile per pass: 8 × INT8 + block-8", "scale byte, address token·G·N + k·N + t"]),
          ("row codes (BS6H)", ["|x| ≤ 127 (−128 → 127), sign picks rp / rn;", "slot s drives bit s; a flop per pin, cut by drv_cut"]),
          ("hand-off / sample capture", ["the element of each bank at hand-off and at", "the sample, for the chain's alignment"])]),
        (546, 64, 520, 420, "imc_seq.v", "pass FSM and phase generator",
         [("pass FSM", ["Idle → Drive (7 slots × 6 ticks) → Write (on weight change", "or refresh) / Stall (weights late) / Wait / Done"]),
          ("merge engine", ["takes the driven bank at hand-off; φ_mrg 2 ticks under", "the next pass's slot 0, then φ_samp when the SAR is free"]),
          ("conversion counter", ["AdcShare rounds of 13 ticks on its own counter;", "cap / cap_round / conv_done to the chain"]),
          ("phase flops", ["φ_rst, φ_sh, φ_mrg, φ_brst, φ_samp, sar_clk, bank:", "every pin a single flop, edges on the DLL tick"])]),
        (1082, 64, 524, 420, "imc_wstage.v", "weight staging and the array writer (B1 write port)",
         [("stage banks", ["double-buffered per tile: the HBM stream fills bank", "g mod 2 one group ahead of the array"]),
          ("array writer", ["WL one row per tick in the write window, WBL per", "column: [7] sign, [6:0] |w| (sign-magnitude cell)"]),
          ("refresh", ["a group in the array for RefreshPasses (128 = 0.76 µs)", "is rewritten from its bank (retention 1.32 µs, P)"]),
          ("ready / stall", ["ready when every needed bank is staged; else the", "sequencer stalls and counts the ticks"])]),
    ]
    for x, y, w, h, t, sub, parts in mods:
        g.box(x, y, w, h, DG, None)
        g.text(x + 12, y + 20, t, "white", 11, weight=700)
        g.text(x + 12, y + 34, sub, SL, 8)
        for i, (pt, ls) in enumerate(parts):
            yy = y + 48 + i * 92
            g.rect(x + 12, yy, w - 24, 82, DG, rx=5, sw=1)
            g.text(x + 22, yy + 18, pt, "#a5f3fc", 9.5, weight=600)
            for j, ln in enumerate(ls):
                g.text(x + 22, yy + 36 + 14 * j, ln, SL, 8)
    g.line(530, 270, 544, 270, DG, 1.6, arrow=True)
    g.line(1066, 270, 1080, 270, DG, 1.6, arrow=True)
    # chain
    x, y, w, h = 10, 500, 1060, 442
    g.box(x, y, w, h, DG, None)
    g.text(x + 12, y + 20, "imc_chain.v", "white", 11, weight=700)
    g.text(x + 12, y + 34, "code capture, B6 calibration, block-8 dequant, B10 accumulator chain, B6′ requant", SL, 8)
    steps = [("capture", ["converter j of tile t, round r", "→ column j·3 + r (86 per tile,", "the last one short)"]),
             ("B6 cal", ["c = (g·code + o + 2^13) >> 14", "g u16, o s20 per column,", "written once (cal_we)"]),
             ("dequant (block-8)", ["c · (32 + σx) · (32 + σw)", "<< (14 − ex − ew)", "scale byte: 3-b e, 5-b σ"]),
             ("B10 chain", ["psum[t] = psum[t−1] + cal_t", "24 b (52 b block-8), one", "hop per pass, K-adjacent"]),
             ("edge acc", ["K beyond the chain: summed", "in the edge buffer per", "token of the m-chunk"]),
             ("B6′ requant", ["y8 = sat8(((acc << 6)·scale", "+ half) >> shift + offset)", "per n-block table"])]
    for i, (t, ls) in enumerate(steps):
        bx = x + 14 + i * 172
        g.rect(bx, y + 56, 160, 120, DG, rx=5, sw=1)
        g.text(bx + 10, y + 76, t, "#a5f3fc", 9.5, weight=600)
        for j, ln in enumerate(ls):
            g.text(bx + 10, y + 96 + 14 * j, ln, SL, 8)
        if i:
            g.line(bx - 12, y + 116, bx - 2, y + 116, DG, 1.6, arrow=True)
    for i, ln in enumerate(["Alignment: tile t converts element e at pass e + t + 1, so at each conversion-done the value",
                            "tile t − 1 left in its psum register is the element tile t just converted (bit-exact, 25 cases).",
                            "Ports: codes_i (N·86·12 b), desc_cv_i / xs_i (the element and its x scale), ws_data_i (w scales),",
                            "cal_*, rq_data_i → out_valid_o, out_y_o (INT8), out_acc_o."]):
        g.text(x + 16, y + 206 + 15 * i, ln, SL, 8.5)
    g.text(x + 16, y + 290, "Checks (M on the RTL): t_pass 5.964 ns (42 ticks); no stall after fill; GEMV at the per-tile",
           INK, 8.5)
    g.text(x + 16, y + 305, "HBM share: 28,144 ticks against the 28,032 law; driver + ideal tiles bit-exact against the golden.",
           INK, 8.5)
    # the chain across K-adjacent tiles
    cy = y + 360
    chain = ["tile 0", "tile 1", "⋯", "tile N − 1", "edge acc", "requant", "out_y (INT8)"]
    for i, t in enumerate(chain):
        bx = x + 16 + i * 148
        if t == "⋯":
            g.text(bx + 50, cy + 22, t, SL, 16, "middle")
        else:
            g.box(bx, cy, 120, 40, AN if t.startswith("tile") else DG, t, tsize=9)
        if i:
            g.line(bx - 28, cy + 20, bx - 2, cy + 20, DG, 1.6, arrow=True)
    g.text(x + 16, cy + 60, "psum[t] = psum[t − 1] + cal_t(code): one hop per pass, exact; only completed outputs leave the chain",
           DG, 8)
    # rail
    x, y, w, h = 1086, 500, 520, 442
    g.box(x, y, w, h, DG, None)
    g.text(x + 12, y + 20, "Digital rail (spec ARCH_CHOSEN B8)", "white", 11, weight=700)
    g.text(x + 12, y + 34, "not in RTL yet: the blocks the spec names", SL, 8)
    rail = [("attention lanes", ["Q·Kᵀ and P·V: q8 × k4 bulk,", "q8 × k8 for sink 8 + recent 120"]),
            ("online softmax", ["base-2 exp from a ROM"]),
            ("FWHT", ["Hadamard on q, k, v, o (the 4.5 dB credit)"]),
            ("RMSNorm · RoPE · SwiGLU", ["per token, INT8 in and out"]),
            ("KV pack / unpack", ["4-b codes + fp16 scale per (token, head);", "4-b ring residual, dropped on exit"])]
    for i, (t, ls) in enumerate(rail):
        yy = y + 48 + i * 76
        g.rect(x + 12, yy, w - 24, 68, DG, rx=5, sw=1)
        g.text(x + 22, yy + 18, t, "#a5f3fc", 9.5, weight=600)
        for j, ln in enumerate(ls):
            g.text(x + 22, yy + 36 + 14 * j, ln, SL, 8)
    return g


def page_svg(g):
    return (f'<svg viewBox="0 0 {VW} {VH}" xmlns="http://www.w3.org/2000/svg" font-family="JetBrains Mono, monospace">'
            f'<defs><pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse"><path d="M 40 0 L 0 0 0 40" '
            f'fill="none" stroke="#1e293b" stroke-width="0.5"/></pattern>'
            + "".join(f'<marker id="ah-{c[1:]}" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">'
                      f'<polygon points="0 0, 8 3, 0 6" fill="{c}"/></marker>' for c in (AN, DG, MEM, REF, ST, SL, ROSE, INK))
            + f'</defs><rect width="{VW}" height="{VH}" fill="url(#grid)"/>{g}</svg>')


PAGES = [
    (page_system, "AnalogIOC · analog in-memory-compute accelerator",
     "HBM → NoC → IMC tile array (K-adjacent accumulator chain) → requant → digital rail. Every tile part carries "
     "its transistor circuit, placed by cktImg from imc_tile.py."),
    (page_tile, "One tile, transistor level",
     "Each block holds its circuit as cktImg placed it; wires land on the circuits' ports; italic names join a net by "
     "name; dashed cyan lines are control from the RTL."),
    (page_drive_array, "B2 row drive and B1 gain-cell array",
     "The bit-serial driver, the gain bit, the sign mux and the crosspoint, and the block views that compose them "
     "into a weight, a row and the array."),
    (page_column, "B3 column: share switch, ping-pong bank, phase decode",
     "One bank of one column side: bootstrapped share, 1:16 merge, the step caps that are the SAR's C-DAC, and the "
     "phases that run it."),
    (page_converter, "B4 E-trim SAR converter",
     "Mux → fast and quiet double-tail comparators (drawn by stage) → asynchronous SAR logic → 3-level drivers on the "
     "bank's step caps."),
    (page_hierarchy, "Netlist hierarchy and the B5 reference",
     "cktImg block views of the tile and the tile pair (buses bundled, supplies off the blocks), the ADC-share-3 "
     "converter group, and the class-A VCM follower."),
    (page_digital, "Digital: imc_driver RTL and the rail",
     "The tile-array controller's modules (digital/imc_driver/src) and the attention rail the spec adds."),
]

CSS = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'JetBrains Mono', monospace; background: #020617; color: white; }
.page { width: 100%; max-width: 1680px; margin: 0 auto 28px; padding: 14px 32px 10px; background: #020617; }
.header-row { display: flex; align-items: center; gap: 0.9rem; margin-bottom: 0.25rem; }
.pulse-dot { width: 12px; height: 12px; background: #22d3ee; border-radius: 50%; animation: pulse 2s infinite; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
h1 { font-size: 1.3rem; font-weight: 700; letter-spacing: -0.025em; }
.pg { color: #475569; font-size: 0.8rem; margin-left: auto; }
.subtitle { color: #94a3b8; font-size: 0.78rem; margin-left: 1.65rem; margin-bottom: 0.55rem; }
.diagram { background: rgba(15, 23, 42, 0.5); border: 1px solid #1e293b; border-radius: 1rem; }
svg { width: 100%; height: auto; display: block; }
.toolbar { display: flex; gap: 0.5rem; margin-left: 1rem; flex-shrink: 0; align-items: center; }
.toolbar-toggle { background: transparent; border: none; color: #475569; cursor: pointer; font-size: 1.25rem;
  line-height: 1; padding: 0.25rem 0.5rem; border-radius: 0.375rem; }
.toolbar-toggle:hover { color: #94a3b8; background: rgba(30, 41, 59, 0.5); }
.toolbar-actions { display: none; gap: 0.5rem; }
.toolbar.expanded .toolbar-actions { display: flex; }
.toolbar-actions button { background: rgba(30, 41, 59, 0.8); border: 1px solid #334155; color: #94a3b8;
  padding: 0.375rem 0.75rem; border-radius: 0.375rem; font-family: inherit; font-size: 0.75rem; cursor: pointer; }
.toolbar-actions button:hover { background: rgba(51, 65, 85, 0.8); color: white; border-color: #475569; }
@page { size: 1680px 1050px; margin: 0; }
@media print {
  .page { width: 1680px; height: 1050px; margin: 0; page-break-after: always; break-after: page; overflow: hidden; }
  .toolbar { display: none !important; }
  .pulse-dot { animation: none; }
}
"""

SCRIPT = """
async function grab() {
  const el = document.getElementById('report');
  return await html2canvas(el, { backgroundColor: '#020617', scale: 2, useCORS: true,
    ignoreElements: (e) => e.classList && e.classList.contains('toolbar') });
}
async function copyAsImage(btn) {
  const orig = btn.textContent;
  try { const c = await grab(); const blob = await new Promise(r => c.toBlob(r, 'image/png'));
        await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]); btn.textContent = 'Copied'; }
  catch (e) { btn.textContent = 'Failed'; }
  setTimeout(() => btn.textContent = orig, 2000);
}
async function downloadPNG(btn) {
  const orig = btn.textContent; btn.textContent = '...';
  try { const c = await grab(); const a = document.createElement('a'); a.download = 'imc_architecture.png';
        a.href = c.toDataURL('image/png'); a.click(); btn.textContent = 'Done'; }
  catch (e) { btn.textContent = 'Failed'; }
  setTimeout(() => btn.textContent = orig, 2000);
}
async function downloadPDF(btn) {
  const orig = btn.textContent; btn.textContent = '...';
  try {
    const { jsPDF } = window.jspdf; let pdf = null;
    for (const p of document.querySelectorAll('.page')) {
      const c = await html2canvas(p, { backgroundColor: '#020617', scale: 2, useCORS: true,
        ignoreElements: (e) => e.classList && e.classList.contains('toolbar') });
      if (!pdf) pdf = new jsPDF({ orientation: 'landscape', unit: 'px', format: [c.width, c.height], hotfixes: ['px_scaling'] });
      else pdf.addPage([c.width, c.height], 'landscape');
      pdf.addImage(c.toDataURL('image/png'), 'PNG', 0, 0, c.width, c.height);
    }
    pdf.save('imc_architecture.pdf'); btn.textContent = 'Done';
  } catch (e) { btn.textContent = 'Failed'; }
  setTimeout(() => btn.textContent = orig, 2000);
}
"""


def build_html():
    pages = []
    for i, (fn, title, sub) in enumerate(PAGES):
        r = fn()
        g = r[0] if isinstance(r, tuple) else r
        tools = ("""<div class="toolbar"><div class="toolbar-actions">
          <button onclick="copyAsImage(this)">Copy</button><button onclick="downloadPNG(this)">PNG</button>
          <button onclick="downloadPDF(this)">PDF</button></div>
          <button class="toolbar-toggle" onclick="this.parentElement.classList.toggle('expanded')" title="Export options"
          aria-label="Export options">⋯</button></div>""" if i == 0 else "")
        pages.append(f"""<section class="page" id="p{i + 1}">
  <div class="header-row"><div class="pulse-dot"></div><h1>{esc(title)}</h1><span class="pg">{i + 1} / {len(PAGES)}</span>{tools}</div>
  <p class="subtitle">{esc(sub)}</p>
  <div class="diagram">{page_svg(g)}</div>
</section>""")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AnalogIOC architecture</title>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js" integrity="sha384-ZZ1pncU3bQe8y31yfZdMFdSpttDoPmOZg2wguVK9almUodir1PghgT0eY7Mrty8H" crossorigin="anonymous"></script>
<script src="https://cdn.jsdelivr.net/npm/jspdf@2.5.2/dist/jspdf.umd.min.js" integrity="sha384-en/ztfPSRkGfME4KIm05joYXynqzUgbsG5nMrj/xEFAHXkeZfO3yMK8QQ+mP7p1/" crossorigin="anonymous"></script>
<style>{CSS}</style>
</head>
<body>
<div id="report">
{chr(10).join(pages)}
</div>
<script>{SCRIPT}</script>
</body>
</html>
"""


def chromium(args):
    exe = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
    base = ["--headless", "--no-sandbox", "--disable-gpu", "--hide-scrollbars", "--virtual-time-budget=10000"]
    if exe:
        return subprocess.run([exe, *base, *args], capture_output=True, text=True)
    cmd = " ".join(["chromium", *base, *(f"'{x}'" for x in args)])
    return subprocess.run(["nix-shell", "-p", "chromium", "--run", cmd], capture_output=True, text=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-draw", action="store_true", help="reuse analog/imc_tile/output/schematics")
    ap.add_argument("--html-only", action="store_true", help="skip the pdf and png")
    a = ap.parse_args()
    if not a.no_draw:
        subprocess.run([sys.executable, str(ROOT / "analog/imc_tile/netlist/imc_tile.py"), "--draw"], check=True)
    out = HERE / "imc_architecture.html"
    out.write_text(build_html())
    print("wrote", out)
    if a.html_only:
        return
    url = out.resolve().as_uri()
    r = chromium(["--no-pdf-header-footer", f"--print-to-pdf={HERE / 'imc_architecture.pdf'}", url])
    print("wrote", HERE / "imc_architecture.pdf", "" if r.returncode == 0 else r.stderr[-400:])
    r = chromium([f"--window-size={PW},{PH}", "--force-device-scale-factor=2",
                  f"--screenshot={HERE / 'imc_architecture.png'}", url])
    print("wrote", HERE / "imc_architecture.png", "" if r.returncode == 0 else r.stderr[-400:])


if __name__ == "__main__":
    main()
