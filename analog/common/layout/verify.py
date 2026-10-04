"""Signoff for a generated layout: klayout DRC, magic+netgen LVS, magic PEX.

    python3 analog/common/layout/verify.py {drc|lvs|pex} <block> [gds]

gds defaults to analog/<block>/output/gen/<block>.gds; every report lands next to it.
  drc  sky130A_mr.drc (feol+beol+offgrid) -> drc.lyrdb, plus magic's own DRC count
  lvs  magic ext2spice (flat) vs netlist/<block>.spice, netgen + the PDK setup -> lvs.out
  pex  magic ext2spice with parasitic C -> <block>_pex.spice: `.subckt <block>` with the
       source's ports in the source's order, so DUT=pex PEX_FROM=gen simulates it
Exit status is non-zero when the check fails. Tools: $KLAYOUT $MAGIC $NETGEN (default
from PATH), PDK files from $PDK_ROOT/$PDK.
"""
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

ANALOG = Path(__file__).resolve().parents[2]
PDK_ROOT = Path(os.environ.get("PDK_ROOT", Path.home() / ".volare"))
PDK = os.environ.get("PDK", "sky130A")
TECH = PDK_ROOT / PDK / "libs.tech"


def _tool(name):
    return os.environ.get(name.upper(), name)


def magic(script, cwd):
    """Run a magic Tcl script headless with the PDK's rc file; return stdout."""
    r = subprocess.run([_tool("magic"), "-dnull", "-noconsole", "-rcfile",
                        str(TECH / "magic" / f"{PDK}.magicrc")],
                       input=script + "\nquit -noprompt\n", text=True, cwd=cwd,
                       capture_output=True)
    return r.stdout + r.stderr


def _load(gds, top):
    # extract a flattened copy: devices, wells and taps from different tiles extract as
    # one piece and parasitics see the whole routing. The copy is named <top>_flat.
    return f"gds read {gds}\nload {top}\nflatten {top}_flat\nload {top}_flat\nselect top cell\n"


def _fixed_width(path):
    """magic cannot recover sky130's fixed-width poly-resistor ids from GDS (res0p35.. are
    magic-only idtypes), so it extracts the generic model with w=; name the variant."""
    def fix(m):
        w = m.group(2)
        return f"{m.group(1)}_{w.replace('.', 'p')}" if w in ("0.35", "0.69", "1.41", "2.85", "5.73") \
            else m.group(0)
    path.write_text(re.sub(r"(sky130_fd_pr__res_x?high_po)\s+w=(\S+)", fix, path.read_text()))


def ports_of(src, top):
    for line in src.read_text().splitlines():
        tok = line.split()
        if len(tok) > 1 and tok[0].lower() == ".subckt" and tok[1] == top:
            return [t for t in tok[2:] if "=" not in t]
    sys.exit(f"no .subckt {top} in {src}")


def drc(block, gds):
    out = gds.parent / "drc.lyrdb"
    subprocess.run([_tool("klayout"), "-b", "-r", str(TECH / "klayout" / "drc" / f"{PDK}_mr.drc"),
                    "-rd", f"input={gds}", "-rd", f"top_cell={block}", "-rd", f"report={out}",
                    "-rd", "feol=true", "-rd", "beol=true", "-rd", "offgrid=true",
                    "-rd", "thr=4"], check=True, capture_output=True)
    root = ET.parse(out).getroot()
    rules = Counter(i.findtext("category").strip("'") for i in root.iter("item"))
    log = magic(_load(gds, block) + "drc style drc(full)\ndrc check\ndrc catchup\ndrc count total\n"
                "puts \"MAGICDRC [drc listall why]\"", gds.parent)
    m = re.search(r"Total DRC errors found:\s*(\d+)", log)
    why = log[log.find("MAGICDRC"):].splitlines()[0] if "MAGICDRC" in log else ""
    print(f"drc {block}: klayout {sum(rules.values())} violations "
          f"{dict(rules) or ''} | magic {m.group(1) if m else '?'} {why[9:200]}")
    return sum(rules.values()) == 0


def lvs(block, gds):
    d, src = gds.parent, ANALOG / block / "netlist" / f"{block}.spice"
    magic(_load(gds, block) + "extract do local\nextract all\next2spice lvs\n"
          f"ext2spice -o {block}_lvs.spice", d)
    _fixed_width(d / f"{block}_lvs.spice")
    r = subprocess.run([_tool("netgen"), "-batch", "lvs", f"{d / (block + '_lvs.spice')} {block}_flat",
                        f"{src} {block}", str(TECH / "netgen" / f"{PDK}_setup.tcl"),
                        str(d / "lvs.out")], capture_output=True, text=True, cwd=d)
    text = (d / "lvs.out").read_text() if (d / "lvs.out").exists() else r.stdout
    ok = "Circuits match uniquely" in text and "Netlists do not match" not in text
    final = [ln for ln in text.splitlines() if "Final result" in ln or "do not match" in ln]
    print(f"lvs {block}: {'MATCH' if ok else 'MISMATCH'} — {final[-1].strip() if final else ''}"
          f" ({d / 'lvs.out'})")
    return ok


def pex(block, gds):
    d, src = gds.parent, ANALOG / block / "netlist" / f"{block}.spice"
    ports = ports_of(src, block)
    magic(_load(gds, block) + "extract do local\nextract all\next2spice lvs\next2spice cthresh 0\n"
          f"ext2spice -o {block}_ext.spice", d)
    _fixed_width(d / f"{block}_ext.spice")
    text = (d / f"{block}_ext.spice").read_text()
    head = re.search(rf"^\.subckt\s+{block}_flat\b(.*)$", text, re.M | re.I)
    if not head:
        sys.exit(f"pex: magic wrote no .subckt {block} (labels missing?)")
    got = head.group(1).split()
    missing = [p for p in ports if p not in got]
    if missing:
        sys.exit(f"pex: ports {missing} not labelled in the layout (magic ports: {got})")
    extra = [p for p in got if p not in ports]
    # extra magic ports (substrate node, unlabelled pins) become internal nets
    text = text[:head.start()] + f".subckt {block} {' '.join(ports)}" + text[head.end():]
    text = re.sub(rf"^\.ends\s+{block}_flat\b", f".ends {block}", text, flags=re.M | re.I)
    out = d / f"{block}_pex.spice"
    out.write_text(f"* {block} post-layout (substrate2 generator) — analog/common/layout/verify.py\n"
                   + text)
    body = text[text.find(f".subckt {block}"):]
    n_dev = len(re.findall(r"^X\S*\s", body, re.M))
    caps = [float(c) for c in re.findall(r"^C\S*\s+\S+\s+\S+\s+(\S+?)f?F?\s*$", body, re.M | re.I)
            if re.fullmatch(r"[\d.eE+-]+", c)]
    print(f"pex {block}: {n_dev} devices, {len(caps)} parasitic caps, total {sum(caps):.2f} fF"
          + (f", internalised {extra}" if extra else "") + f" -> {out}")
    return True


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4) or sys.argv[1] not in ("drc", "lvs", "pex"):
        sys.exit(__doc__)
    step, blk = sys.argv[1], sys.argv[2]
    g = Path(sys.argv[3]).resolve() if len(sys.argv) == 4 else \
        ANALOG / blk / "output" / "gen" / f"{blk}.gds"
    if not g.exists():
        sys.exit(f"{g} missing — make gen first")
    sys.exit(0 if {"drc": drc, "lvs": lvs, "pex": pex}[step](blk, g) else 1)
