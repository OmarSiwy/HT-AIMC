"""Philis `extracted_pex.spice` -> a simulatable post-layout subckt (DUT=pex).

    python3 analog/common/pex.py <block> <philis_run_dir>
        -> analog/<block>/output/pnr/<block>_pex.spice

Philis's extraction is not simulatable as written (philis skill): no .subckt, generic
nmos/pmos models, passives omitted, parasitics only as `* net X R=.. C=..` comments,
NMOS bulks reported on the wrong net. This rebuilds it against the source deck:

  1. flatten netlist/<block>.spice (child subckts expanded)
  2. match every extracted MOS to a source device by (type, W, L), then by d/g/s net
     overlap; the match supplies model, nf, m and the bulk net
  3. map source nets -> extracted nets from matched terminals; re-add the source's
     passives and non-FET devices through that map
  4. per-net C -> a grounded cap to the block's ground port (nets no device touches —
     well/stub nets — are skipped: a cap-only node has no DC path); per-net R is reported
     in a comment only (Philis gives no per-segment topology to place it on)

Every port must survive into the extracted netlist (run Philis with --interface),
otherwise it exits non-zero naming the missing ones. Source nets that land on one
extracted net (a layout short) also exit non-zero.
"""
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ANALOG = Path(__file__).resolve().parents[1]
GROUND_NAMES = ("vss", "gnd", "vgnd", "0")


def _num(tok):
    """SPICE number -> float (engineering suffixes)."""
    m = re.fullmatch(r"([-+]?[\d.]+(?:e[-+]?\d+)?)([a-z]*)", tok.lower())
    if not m:
        raise ValueError(tok)
    scale = {"": 1, "f": 1e-15, "p": 1e-12, "n": 1e-9, "u": 1e-6, "m": 1e-3,
             "k": 1e3, "meg": 1e6, "g": 1e9}
    return float(m.group(1)) * scale[m.group(2)[:3] if m.group(2).startswith("meg")
                                     else m.group(2)[:1]]


def _lines(text):
    out = []
    for raw in text.splitlines():
        s = raw.strip()
        if not s or s.startswith("*"):
            continue
        if s.startswith("+") and out:
            out[-1] += " " + s[1:].strip()
        else:
            out.append(s)
    return out


def parse_deck(text):
    """{name: (ports, [lines])} for every .subckt in the deck."""
    subs, cur = {}, None
    for s in _lines(text):
        low = s.lower()
        if low.startswith(".subckt"):
            tok = s.split()
            cur = tok[1]
            subs[cur] = ([t for t in tok[2:] if "=" not in t and t.upper() != "PARAMS:"], [])
        elif low.startswith(".ends"):
            cur = None
        elif cur and not s.startswith("."):
            subs[cur][1].append(s)
    return subs


def flatten(subs, top, prefix="", netmap=None):
    """Flat device lines of `top`: [(name, nets, model, params)]. Subckt instances whose
    model is defined in the deck are expanded; anything else is a leaf device."""
    ports, body = subs[top]
    netmap = netmap or {p: p for p in ports}

    def net(n):
        if n in netmap:
            return netmap[n]
        return n if n == "0" else (prefix + n if prefix else n)

    out = []
    for s in body:
        tok = s.split()
        params = {k.lower(): v for k, v in (t.split("=", 1) for t in tok if "=" in t)}
        pos = [t for t in tok if "=" not in t]
        name, rest = pos[0], pos[1:]
        if name[0].lower() == "x" and rest and rest[-1] in subs:
            child = rest[-1]
            cports = subs[child][0]
            cmap = {p: net(n) for p, n in zip(cports, rest[:-1])}
            out += flatten(subs, child, f"{prefix}{name}.", cmap)
        else:
            nets = [net(n) for n in rest[:-1]] if name[0].lower() in "xm" else \
                   [net(n) for n in rest[:2]]
            model = rest[-1] if name[0].lower() in "xmq" else None
            out.append((prefix + name, nets, model, params, s))
    return out


def _meters(v):
    """A W/L token in metres: plain numbers are um (sky130 scale=1u), suffixed are SI."""
    x = _num(v)
    return x * 1e-6 if x > 1e-3 else x


def fet_type(model):
    m = (model or "").lower()
    return "pmos" if ("pfet" in m or "pmos" in m) else "nmos" if ("nfet" in m or "nmos" in m) \
        else None


def parse_extracted(text):
    devs, par = [], {}
    for raw in text.splitlines():
        s = raw.strip()
        m = re.match(r"\*\s*net\s+(\S+)\s+R\s*=\s*([\d.eE+-]+)\s*ohm\s+C\s*=\s*([\d.eE+-]+)\s*fF", s)
        if m:
            par[m.group(1)] = (float(m.group(2)), float(m.group(3)) * 1e-15)
            continue
        if not s or s.startswith("*"):
            continue
        tok = s.split()
        if tok[0][0] in "Mm":
            p = {k.lower(): _num(v) for k, v in (t.split("=", 1) for t in tok if "=" in t)}
            devs.append((tok[0], tok[1:5], tok[5].lower(), p))
    return devs, par


def convert(block, run_dir):
    run_dir = Path(run_dir)
    deck = (ANALOG / block / "netlist" / f"{block}.spice").read_text()
    subs = parse_deck(deck)
    top = list(subs)[-1]
    ports = subs[top][0]
    flat = flatten(subs, top)
    fets = [d for d in flat if fet_type(d[2])]
    others = [d for d in flat if not fet_type(d[2])]
    ext, par = parse_extracted((run_dir / "extracted_pex.spice").read_text())

    # 2. match extracted MOS -> source FET. Philis extracts parallel FETs (same type,
    # d/g/s/b, L — including m>1 and w_max-split devices) as ONE device of summed W, so
    # group them first; W matches within 1% (Philis snaps W to its grid).
    groups = defaultdict(list)
    for d in fets:
        groups[fet_type(d[2]), tuple(d[1][:4]), round(_meters(d[3].get("l", "0")) * 1e9)].append(d)
    pool = defaultdict(list)
    for (typ, _, l_nm), g in groups.items():
        w_tot = sum(_meters(d[3].get("w", "0")) * float(d[3].get("m", 1)) for d in g)
        pool[typ, l_nm].append((w_tot, g))
    votes = defaultdict(Counter)
    out_fets, unmatched = [], []
    for name, nets, typ, p in ext:
        w_ext = p.get("w", 0)
        cands = [c for c in pool.get((typ, round(p.get("l", 0) * 1e9)), [])
                 if abs(c[0] - w_ext) <= 0.01 * max(c[0], w_ext)]
        if not cands:
            unmatched.append(f"{name}(W={w_ext * 1e6:.2f}u)")
            continue
        # MOS drain/source are symmetric: score both orientations, keep the better
        swap = [nets[2], nets[1], nets[0]] + nets[3:]

        def score(d, n):
            return sum(a == b for a, b in zip(d[1][:3], n[:3])) * 10 + \
                len(set(d[1][:3]) & set(n[:3]))
        (w_tot, grp), nets = max(((c, n) for c in cands for n in (nets, swap)),
                                 key=lambda cn: score(cn[0][1][0], cn[1]))
        pool[typ, round(p.get("l", 0) * 1e9)].remove((w_tot, grp))
        for src, dst in zip(grp[0][1][:3], nets[:3]):
            votes[src][dst] += 1
        out_fets.append((grp, nets))
    left = [d[0] for c in pool.values() for _, g in c for d in g]
    if unmatched or left:
        sys.exit(f"pex: device mismatch — extracted-only {unmatched}, source-only {left}")
    netmap = {src: c.most_common(1)[0][0] for src, c in votes.items()}
    # extracted -> source name wherever the correspondence is one-to-one, so ports
    # (and readable internal nets) keep their names even without --interface
    images = Counter(netmap.values())
    rename = {dst: src for src, dst in netmap.items() if images[dst] == 1}
    shorted = [f"{'/'.join(s for s, d in netmap.items() if d == dst)}->{dst}"
               for dst, k in images.items() if k > 1]
    if shorted:
        sys.exit(f"pex: source nets merged in layout (short?): {shorted}")
    ren = lambda n: rename.get(n, n)  # noqa: E731
    netmap = {src: ren(dst) for src, dst in netmap.items()}
    for p in ports:
        netmap.setdefault(p, p)
    body_nets = {ren(n) for _, nets in out_fets for n in nets[:3]} | \
        {netmap.get(d[1][3], d[1][3]) for grp, _ in out_fets for d in grp}   # bulk-only ports
    missing = [p for p in ports if p not in body_nets
               and not any(p in d[1] for d in others)]
    gnd = next((p for p in ports if p.lower() in GROUND_NAMES), "0")

    lines = [f"* {block} post-layout (Philis {run_dir.name}) — converted by analog/common/pex.py",
             f".subckt {block} {' '.join(ports)}"]
    for grp, nets in out_fets:
        for name, snets, model, params, srcline in grp:   # every merged member, verbatim params
            bulk = netmap.get(snets[3], snets[3])
            extra = " ".join(t for t in srcline.split() if "=" in t)
            lines.append(f"{name.replace('.', '_')} {ren(nets[0])} {ren(nets[1])} "
                         f"{ren(nets[2])} {bulk} {model} {extra}")
    for name, nets, model, params, src in others:
        tok = src.split()
        mapped = [netmap.get(n, n) for n in nets]
        lines.append(" ".join([name.replace(".", "_")] + mapped + tok[1 + len(nets):]))
    rsum, live = [], body_nets | set(ports) | {n for d in others for n in d[1]}
    for net, (r, c) in sorted(par.items()):
        net = ren(net)
        if c > 0 and net != gnd and net in live:   # a cap-only node has no DC path
            lines.append(f"Cpar_{net} {net} {gnd} {c:.4e}")
        rsum.append(f"{net}={r:.0f}")
    lines.append("* per-net R (not placed, no segment topology): " + " ".join(rsum))
    # Ports must be named nets of the extracted body — rename via netmap
    if missing:
        sys.exit(f"pex: ports not present in the extraction: {missing} — run Philis "
                 f"with --interface so boundary pins keep their names")
    lines.append(f".ends {block}")
    out = ANALOG / block / "output" / "pnr" / f"{block}_pex.spice"
    out.write_text("\n".join(lines) + "\n")
    print(f"pex: {sum(len(g) for g, _ in out_fets)} FETs ({len(out_fets)} extracted), {len(others)} other devices, "
          f"{sum(ln.startswith('Cpar_') for ln in lines)} parasitic caps -> {out}")
    return out


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    convert(sys.argv[1], sys.argv[2])
