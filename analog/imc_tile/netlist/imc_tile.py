"""Transistor-level ASAP7 netlist of the upgraded IMC tile (BS6H drive, E-trim SAR, AdcShare 3), in SpiceRack.

    python3 netlist/imc_tile.py --emit     .spice decks       -> output/netlist/
    python3 netlist/imc_tile.py --draw     cktImg schematics  -> output/schematics/   (cells by stage, block views)
    python3 netlist/imc_tile.py --sim      ESPice checks on a reduced tile, PASS/FAIL  -> output/spice/

The spec is docs/src/content/Project/ARCH_CHOSEN.md (B1-B5); the behaviour each block must reproduce is the
golden (scripts/golden/imc_tile.py) and the Verilog-A models (va/). Devices go through analog/common/devices.fet
(W -> fins), models from $ASAP7_ROOT/models/espice/asap7.lib. The SAR logic stays Verilog-A
(va/imc_sar_logic.va); everything else is transistors, MOM caps (ideal C, as the PDK declares) and the
interconnect elements named as such (R_PDN, row strap, rail wire).

Subcircuits (ports in order; `*@` lines place them for cktImg):
  gc3t   gain bit: write FET (SRAM-Vt) + SRAM-Vt inverter -> s, sb                      (B1, N3_r2 gc3t)
  xp     crosspoint bit: TG from the line to the unit-cap bottom plate + NMOS ground leg   (B1/B3)
  smx    sign mux: the side's line = rp (w >= 0) or rn (w < 0)                              (sign steering)
  half   one column side of one weight: 8 gc3t + smx + 7 xp + 7 MOM units (MSB 1/2/4 x cu_msb, LSB 1..8 x cu_lsb)
  wcell  one W8 weight: two halves, the - side on the swapped rails
  rdrv   bit-serial row driver: NAND2 + 4096-fin-class inverter per rail on the tile supply vdr (BS6H);
         bs6h_cc adds the constant-charge dummy
  bsw    bootstrapped NMOS share switch (constant V_GS)                                    (B3, V7)
  bank   one accumulation bank of one column side: share switches, LSB acc + merge cap (1:16), the MSB acc
         as 12 step caps = the C-DAC of the direct SAR (bottoms GND while accumulating, driven from the
         converter's lines when enabled), bank reset
  col    one column pair: 4 top-plate resets + 4 banks (2 sides x 2 ping-pong banks)
  ctl    bank decode: sh/mg/br per bank from phi_sh, phi_mrg, phi_brst and bank
  dtf    fast double-tail comparator (minimum: in 16, tail 8; COMPARATOR_ALT dt_mr8)
  dtq    quiet tail-starved double-tail, three x2 slices on shared Di/latch, slices 2-3 clocked by the trim bit
  sarm   StrongARM (COMPARATOR = "strongarm", replaced)
  bpd2_f 3-level bottom-plate driver pair (f fins, sized with its step): c -> VCM; else d -> (+ VREF, - GND)
  refbuf class-A two-stage Miller follower for VCM                                         (B5)
  conv   one converter: column/bank mux, comparators, 12 bpd2, the Verilog-A SAR logic
  tile   ROWS x COLS: row drivers, the array, columns, ceil(COLS / ADC_SHARE) converters, ctl
  tiles  N_TILES tiles on their R_PDN, the shared VCM buffer
Labels in every printed number: M measured (this ESPice run), D derived, P projected.
"""
import argparse
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
BLK = HERE.parent
ROOT = BLK.parents[1]
sys.path[:0] = [str(ROOT / "analog/common"), str(ROOT / "analog/docs"), str(ROOT / "scripts"), str(BLK / "test")]
import spicerack as ps                    # noqa: E402
from devices import fet, mim_cap          # noqa: E402
from pdk_specs import get_pdk             # noqa: E402
from golden import imc_tile as G          # noqa: E402

# ----------------------------------------------------------------------------- configuration
ROWS, COLS, SLICES = 8, 256, 2          # P (ARCH B1): R8 x C256 differential, 2 slices (MSB 3 b, LSB 4 b)
N_TILES = 2
DRIVE_MODE = "bs6h"                     # "bs6h" | "bs6h_cc" (constant-charge dummies, fallback)
ADC_SHARE = 3                           # columns per converter (arch_eval pick, architecture.md section 1)
COMPARATOR = "etrim"                    # "etrim" | "dt_x2" (fallback D) | "strongarm" (replaced)
VDD = 0.7
CORNER = "tt"                           # tt | ss | ff
TRIM = None                             # quiet-class slices 2-3: None = on at SS only (E-trim)
R_PDN = 0.4                             # ohm per full 256-column tile (DRIVE_ALT spec)
SHARE_SW = "bsw"                        # "bsw": bootstrapped NMOS (ARCH B3); "tg": transmission gate (V7 fallback)
GC_BUF = True                           # a second inverter drives the crosspoint gates (gc5t). False = N3_r2's gc3t,
                                        # which gates the TG NMOS with the floating storage node: 3.3 % plate error
VCM = VDD / 2                           # C-DAC mid level (refbuf)
CU_MSB, CU_LSB = 1.0e-15, 0.25e-15      # P MOM6 units
C_DEC_VCM = 20e-12                      # D VCM decap per tile (MOS cap area of B5)
FINS = dict(                            # fins per device class
    gc_w=1, gc_inv=1,                   # gain bit: SRAM-Vt write FET and inverter (N3_r2)
    xp_tg=2, xp_gnd=1, smx=4,           # crosspoint TG / ground leg, sign-mux TG (sized for 0.1 % in the BS6H slot)
    drv=4096, pre=512, sgi=8,           # row driver per full 256-col row (N2_r2 lead: 128 x 32 fins)
    tprst=64, sw=32, boot=4, mrg=4, brst=4,  # top-plate reset (64: the half-tick reset must clear 56 fF, else the
                                             # plane radix drifts), share switch (sf32), bootstrap, merge, bank reset
    den=32, dpd=8, mux=4,               # DAC enable TG and idle pull-down of the 1024-LSB step cap (both scaled with
                                        # the step, >= 1), comparator mux TG
    bpd=32, bpi=4,                      # bottom-plate driver switches of the 1024 step (scaled, >= 4), inverters
    logic=2,                            # local logic gates
    ctl=512,                            # ctl output buffers per full 256-col tile (1,024 share switches per line)
    ota_in=8, ota_ld=4, ota_tail=8, ota_out=32, ota_sink=16,
)
CMP = {  # COMPARATOR_ALT measured sizes (fins, Di cap fF)
    "dtf": dict(fin=16, tail=8, rst=2, cdi=2.0, mr=8, ln=2, lp=2, t2=8),
    "dtq": dict(fin=32, tail=4, rst=4, cdi=4.0, mr=16, ln=4, lp=4, t2=16),
    "sarm": dict(fin=16, tail=8, ln=4, lp=4, rst=2, cp=2.0),
}
SIG_REF = {"dtf": (1.82e-3, 1.64e-3, 2.02e-3), "dtq": (0.654e-3, 0.609e-3, 0.701e-3)}   # M, COMPARATOR_ALT (tt)
STEPS = [int(s) for s in G.P(comparator=COMPARATOR if COMPARATOR != "strongarm" else "etrim").sar_sched()[0]]
if COMPARATOR != "etrim":
    STEPS = [2 ** b for b in range(10, -1, -1)] + [0]     # binary: 11 caps used, 12th unused (kept for one netlist)
OUT = BLK / "output"
LOCK = os.environ.get("SPICE_LOCK", "/tmp/claude-1000/-home-omare-Documents-Projects-Trial-ResearchBoutros/"
                      "4a1145dd-b047-4b63-8a63-c5c6ca9a51fb/scratchpad/spice.lock")
PDK = get_pdk("asap7")
TICK = 1.132e-9 / 8                     # DLL tick (golden t_tick)
N_STEP = 12


def sc(cols=None):
    """Width scale of a reduced tile: row loads and drivers scale with the columns, R_PDN inversely."""
    return (cols or COLS) / 256


# ----------------------------------------------------------------------------- builders
SUBS = {}          # name -> (Subcircuit, ports, sides)


def sub(name, ports, sides):
    """A Subcircuit plus its cktImg port sides {left/right/top/bottom: [ports]}."""
    s = ps.Subcircuit(name, ports)
    for side, pl in sides.items():
        s.raw_spice(f"*@ {side} {' '.join(pl)}")
    SUBS[name] = (s, ports, sides)
    return s


def m(s, name, d, g, src, b, kind, fins):
    fet(s, name, d, g, src, b, kind, fins * PDK.w_fin, PDK.min_l)


def inv(s, name, a, y, vdd, vss, fins, kind="nfet"):
    m(s, name + "p", y, a, vdd, vdd, "pfet" if kind == "nfet" else "pfet_hvt", fins)
    m(s, name + "n", y, a, vss, vss, kind, fins)


def nand2(s, name, a, b, y, vdd, vss, fins):
    m(s, name + "pa", y, a, vdd, vdd, "pfet", fins)
    m(s, name + "pb", y, b, vdd, vdd, "pfet", fins)
    m(s, name + "na", y, a, name + "_x", vss, "nfet", 2 * fins)
    m(s, name + "nb", name + "_x", b, vss, vss, "nfet", 2 * fins)


def and2(s, name, a, b, y, vdd, vss, fins):
    nand2(s, name, a, b, name + "_y", vdd, vss, fins)
    inv(s, name + "i", name + "_y", y, vdd, vss, fins)


def tg(s, name, a, b, gn, gp, vdd, vss, fins):
    m(s, name + "n", a, gn, b, vss, "nfet", fins)
    m(s, name + "p", a, gp, b, vdd, "pfet", fins)


def cap(s, name, p, n, c):
    mim_cap(s, name, p, n, c, pdk=PDK)


def wire(s, kind, name, a, b, val):
    """Interconnect element (not a device): R_PDN, row strap, rail wire."""
    s.raw_spice(f"{kind}{name} {a} {b} {val:.6g}")


# ----------------------------------------------------------------------------- B1 / B3 array
def build_array(cols):
    s = sub("gc3t", ["wwl", "wbl", "s", "sb", "vdd", "vss"],
            dict(left=["wwl", "wbl"], right=["s", "sb"], top=["vdd"], bottom=["vss"]))
    st = "m" if GC_BUF else "s"                                            # the storage node
    m(s, "w", "wbl", "wwl", st, "vss", "nfet_hvt", FINS["gc_w"])           # write FET (WWL 1.0 V write, -0.15 V hold)
    inv(s, "i", st, "sb", "vdd", "vss", FINS["gc_inv"], kind="nfet_hvt")  # S-bar for the crosspoint
    if GC_BUF:
        inv(s, "j", "sb", "s", "vdd", "vss", FINS["gc_inv"])               # full-swing S, isolated from the rails

    s = sub("xp", ["l", "bp", "s", "sb", "vdd", "vss"],
            dict(left=["l", "s", "sb"], right=["bp"], top=["vdd"], bottom=["vss"]))
    tg(s, "t", "l", "bp", "s", "sb", "vdd", "vss", FINS["xp_tg"])          # '1': plate follows the line
    m(s, "g", "bp", "sb", "vss", "vss", "nfet", FINS["xp_gnd"])            # '0': plate to ground

    s = sub("smx", ["rp", "rn", "s", "sb", "l", "vdd", "vss"],
            dict(left=["rp", "rn", "s", "sb"], right=["l"], top=["vdd"], bottom=["vss"]))
    tg(s, "p", "rp", "l", "sb", "s", "vdd", "vss", FINS["smx"])            # w >= 0: rp
    tg(s, "n", "rn", "l", "s", "sb", "vdd", "vss", FINS["smx"])            # w < 0: rn

    w = [f"w{b}" for b in range(8)]
    s = sub("half", ["wwl", *w, "rp", "rn", "tm", "tl", "vdd", "vss"],
            dict(left=["wwl", *w, "rp", "rn"], right=["tm", "tl"], top=["vdd"], bottom=["vss"]))
    for b in range(8):
        s.X(f"g{b}", "gc3t", "wwl", f"w{b}", f"s{b}", f"sb{b}", "vdd", "vss")
    s.X("m", "smx", "rp", "rn", "s7", "sb7", "l", "vdd", "vss")
    for b in range(7):                       # bits 0-3 LSB slice (1..8 x cu_lsb), 4-6 MSB slice (1..4 x cu_msb)
        s.X(f"x{b}", "xp", "l", f"bp{b}", f"s{b}", f"sb{b}", "vdd", "vss")
        cap(s, f"u{b}", f"bp{b}", "tm" if b >= 4 else "tl", (2 ** (b - 4)) * CU_MSB if b >= 4 else (2 ** b) * CU_LSB)

    s = sub("wcell", ["wwl", *w, "rp", "rn", "tmp", "tmn", "tlp", "tln", "vdd", "vss"],
            dict(left=["wwl", *w, "rp", "rn"], right=["tmp", "tmn", "tlp", "tln"], top=["vdd"], bottom=["vss"]))
    s.X("p", "half", "wwl", *w, "rp", "rn", "tmp", "tlp", "vdd", "vss")
    s.X("n", "half", "wwl", *w, "rn", "rp", "tmn", "tln", "vdd", "vss")    # - side follows the other rail


# ----------------------------------------------------------------------------- B2 row drive
def build_rdrv(cols):
    k = sc(cols)
    f, fp = max(1, round(FINS["drv"] * k)), max(1, round(FINS["pre"] * k))
    cc = DRIVE_MODE == "bs6h_cc"
    s = sub("rdrv", ["d", "sg", "en", "rp", "rn", "vdr", "vdd", "vss"],
            dict(left=["d", "sg", "en"], right=["rp", "rn"], top=["vdr", "vdd"], bottom=["vss"]))
    inv(s, "s", "sg", "sgb", "vdd", "vss", FINS["sgi"])
    nand2(s, "ap", "d", "sgb", "xp", "vdd", "vss", fp)                     # rp carries the bit when x >= 0
    nand2(s, "an", "d", "sg", "xn", "vdd", "vss", fp)                      # rn when x < 0
    for r, x, rail in (("p", "xp", "rp"), ("n", "xn", "rn")):
        inv(s, "o" + r, x, "o" + r, "vdr", "vss", f)                      # the rail inverter on the tile supply
        wire(s, "R", "s" + r, "o" + r, rail, 46.0 / 128 / k)             # segment strap (N2_r2 lead, DRIVE_ALT E1)
        wire(s, "C", "w" + r, rail, "vss", 0.3e-12 * k)                  # rail wire
    if cc:   # constant-charge dummy: charges c_row from vdr while en and the bit is 0 (N2_r2)
        inv(s, "db", "d", "db", "vdd", "vss", FINS["sgi"])
        nand2(s, "ad", "en", "db", "xd", "vdd", "vss", fp)
        inv(s, "od", "xd", "dm", "vdr", "vss", f)
        cap(s, "dm", "dm", "vss", 7.17e-12 * k)
    return s


# ----------------------------------------------------------------------------- B3 column
def build_bsw():
    s = sub("bsw", ["a", "b", "ck", "vdd", "vss"], dict(left=["a", "ck"], right=["b"], top=["vdd"], bottom=["vss"]))
    inv(s, "i", "ck", "ckb", "vdd", "vss", FINS["boot"])
    if SHARE_SW == "tg":                                                   # NMOS + PMOS halves of the sf32 switch
        tg(s, "t", "a", "b", "ck", "ckb", "vdd", "vss", FINS["sw"] // 2)
        return
    m(s, "m", "a", "g", "b", "vss", "nfet", FINS["sw"])                    # the switch, V_GS = VDD when on
    m(s, "c1", "cn", "ckb", "vss", "vss", "nfet", FINS["boot"])            # off: Cb bottom to ground
    m(s, "c2", "cp", "ck", "vdd", "vdd", "pfet", FINS["boot"])             # off: Cb top to VDD
    m(s, "g0", "g", "ckb", "vss", "vss", "nfet", FINS["boot"])             # off: gate low
    m(s, "t1", "cn", "g", "a", "vss", "nfet", FINS["boot"])                # on: Cb bottom follows the input
    m(s, "t2", "g", "ckb", "cp", "vdd", "pfet", FINS["boot"])              # on: Cb top onto the gate
    cap(s, "b", "cp", "cn", 20e-15)                                        # >> the 32-fin gate: V_GS ~ 0.65 V


def build_col():
    """C_slice 56 / 30 fF: C_acc = C_slice (bit-serial r_acc 1); LSB acc = C_rest + C_m, C_m = rho C_msb."""
    c_msb, c_lsb = ROWS * 7 * CU_MSB, ROWS * 15 * CU_LSB
    rho = (1 / 16) * (CU_MSB / c_msb) / (CU_LSB / c_lsb)
    cm = rho * c_msb
    dk = [f"d{k}" for k in range(N_STEP)]
    s = sub("bank", ["tm", "tl", "sh", "mg", "br", "en", *dk, "a", "vdd", "vss"],
            dict(left=["tm", "tl", "sh", "mg", "br", "en"], right=["a"], bottom=["vss", *dk], top=["vdd"]))
    for x, y in (("sh", "shb"), ("mg", "mgb"), ("en", "enb")):
        inv(s, "i" + x, x, y, "vdd", "vss", FINS["logic"])
    s.X("sm", "bsw", "tm", "a", "sh", "vdd", "vss")                        # MSB slice -> MSB acc (the C-DAC node)
    s.X("sl", "bsw", "tl", "bl", "sh", "vdd", "vss")                       # LSB slice -> LSB acc
    tg(s, "ml", "bl", "mm", "mgb", "mg", "vdd", "vss", FINS["mrg"])        # C_m is part of the LSB acc ...
    tg(s, "mm", "mm", "a", "mg", "mgb", "vdd", "vss", FINS["mrg"])         # ... and joins the MSB acc at the merge
    cap(s, "m", "mm", "vss", cm)
    cap(s, "r", "bl", "vss", c_lsb - cm)
    tot = sum(STEPS)
    for k, st in enumerate(STEPS):                                         # MSB acc = the step caps (direct SAR)
        if st == 0:
            continue
        cap(s, f"d{k}", "a", f"b{k}", c_msb * st / tot)
        tg(s, f"e{k}", f"b{k}", f"d{k}", "en", "enb", "vdd", "vss", step_fins(st, FINS["den"]))
        m(s, f"p{k}", f"b{k}", "enb", "vss", "vss", "nfet", step_fins(st, FINS["dpd"]))   # idle: bottom at GND
    for x in ("a", "bl", "mm"):
        m(s, "r" + x, x, "br", "vss", "vss", "nfet", FINS["brst"])

    dp, dn = [f"dp{k}" for k in range(N_STEP)], [f"dn{k}" for k in range(N_STEP)]
    ports = ["tmp", "tmn", "tlp", "tln", "rst", "sh0", "sh1", "mg0", "mg1", "br0", "br1", "e0", "e1",
             *dp, *dn, "a0p", "a0n", "a1p", "a1n", "vdd", "vss"]
    s = sub("col", ports, dict(left=["tmp", "tmn", "tlp", "tln", "rst", "sh0", "sh1", "mg0", "mg1", "br0", "br1", "e0", "e1"],
                               right=["a0p", "a0n", "a1p", "a1n"], bottom=["vss", *dp, *dn], top=["vdd"]))
    for t in ("tmp", "tmn", "tlp", "tln"):
        m(s, "r" + t, t, "rst", "vss", "vss", "nfet", FINS["tprst"])       # top-plate reset every slot
    for b in (0, 1):
        for side, d in (("p", dp), ("n", dn)):
            s.X(f"k{b}{side}", "bank", f"tm{side}", f"tl{side}", f"sh{b}", f"mg{b}", f"br{b}", f"e{b}", *d,
                f"a{b}{side}", "vdd", "vss")


def build_ctl(cols):
    """Per-bank phases; the output inverters drive a whole tile row of switches (sized with the columns)."""
    fo = max(4, round(FINS["ctl"] * sc(cols)))
    s = sub("ctl", ["sh", "mrg", "brst", "bank", "sh0", "sh1", "mg0", "mg1", "br0", "br1", "vdd", "vss"],
            dict(left=["sh", "mrg", "brst", "bank"], right=["sh0", "sh1", "mg0", "mg1", "br0", "br1"],
                 top=["vdd"], bottom=["vss"]))
    inv(s, "b", "bank", "bankb", "vdd", "vss", FINS["logic"])
    for y, a, b in (("sh0", "sh", "bankb"), ("sh1", "sh", "bank"), ("mg0", "mrg", "bank"), ("mg1", "mrg", "bankb"),
                    ("br0", "brst", "bankb"), ("br1", "brst", "bank")):
        nand2(s, y, a, b, y + "b", "vdd", "vss", max(2, fo // 4))
        inv(s, y + "o", y + "b", y, "vdd", "vss", fo)


# ----------------------------------------------------------------------------- B4 converter
def build_cmp():
    c = CMP["dtf"]
    s = sub("dtf", ["inp", "inn", "clk", "clkb", "oa", "ob", "vdd", "vss"],
            dict(left=["inp", "inn", "clk", "clkb"], right=["oa", "ob"], top=["vdd"], bottom=["vss"]))
    _dt_core(s, c, [("clk", 1)])
    c = CMP["dtq"]
    s = sub("dtq", ["inp", "inn", "clk", "clkb", "trim", "oa", "ob", "vdd", "vss"],
            dict(left=["inp", "inn", "clk", "clkb", "trim"], right=["oa", "ob"], top=["vdd"], bottom=["vss"]))
    and2(s, "tr", "clk", "trim", "clkt", "vdd", "vss", 4)
    _dt_core(s, c, [("clk", 1), ("clkt", 2), ("clkt", 3)])
    c = CMP["sarm"]
    s = sub("sarm", ["inp", "inn", "clk", "clkb", "oa", "ob", "vdd", "vss"],
            dict(left=["inp", "inn", "clk", "clkb"], right=["oa", "ob"], top=["vdd"], bottom=["vss"]))
    m(s, "t", "tl", "clk", "vss", "vss", "nfet", c["tail"])
    m(s, "1", "P", "inp", "tl", "vss", "nfet", c["fin"])
    m(s, "2", "Q", "inn", "tl", "vss", "nfet", c["fin"])
    m(s, "3", "X", "Y", "P", "vss", "nfet", c["ln"])
    m(s, "4", "Y", "X", "Q", "vss", "nfet", c["ln"])
    m(s, "5", "X", "Y", "vdd", "vdd", "pfet", c["lp"])
    m(s, "6", "Y", "X", "vdd", "vdd", "pfet", c["lp"])
    cap(s, "p", "P", "vss", c["cp"] * 1e-15)
    cap(s, "q", "Q", "vss", c["cp"] * 1e-15)
    for k in "PQXY":
        m(s, "r" + k, k, "clk", "vdd", "vdd", "pfet", c["rst"])
    inv(s, "oa", "X", "oa", "vdd", "vss", 1)       # X falls when inp > inn: oa = !X rises (logic reads oa > ob)
    inv(s, "ob", "Y", "ob", "vdd", "vss", 1)


def _dt_core(s, c, tails):
    """Double-tail (Schinkel 2007), dt.py: input pairs per slice on shared Di (d1/d2), PMOS-tailed latch."""
    for ck, i in tails:
        m(s, f"s{i}", f"tl{i}", ck, "vss", "vss", "nfet", c["tail"])
        m(s, f"a{i}", "d1", "inp", f"tl{i}", "vss", "nfet", c["fin"])
        m(s, f"b{i}", "d2", "inn", f"tl{i}", "vss", "nfet", c["fin"])
    m(s, "r1", "d1", "clk", "vdd", "vdd", "pfet", c["rst"])
    m(s, "r2", "d2", "clk", "vdd", "vdd", "pfet", c["rst"])
    cap(s, "1", "d1", "vss", c["cdi"] * 1e-15)
    cap(s, "2", "d2", "vss", c["cdi"] * 1e-15)
    m(s, "t2", "t2", "clkb", "vdd", "vdd", "pfet", c["t2"])
    m(s, "ra", "oa", "d1", "vss", "vss", "nfet", c["mr"])
    m(s, "rb", "ob", "d2", "vss", "vss", "nfet", c["mr"])
    m(s, "na", "oa", "ob", "vss", "vss", "nfet", c["ln"])
    m(s, "nb", "ob", "oa", "vss", "vss", "nfet", c["ln"])
    m(s, "pa", "oa", "ob", "t2", "vdd", "pfet", c["lp"])
    m(s, "pb", "ob", "oa", "t2", "vdd", "pfet", c["lp"])
    inv(s, "xa", "oa", "xa", "vdd", "vss", 1)      # output inverters (dt.py), the load the latch drives
    inv(s, "xb", "ob", "xb", "vdd", "vss", 1)


def step_fins(st, top):
    """Switch fins for a step cap: the 1024-LSB cap gets `top` (tau ~10 ps on 27.6 fF), scaled down with
    the step, at least 1 (the DAC settles inside t_dac 45 ps; redundancy absorbs the early residue)."""
    return max(1, round(top * st / 1024))


def bpd_names():
    return sorted({f"bpd2_{max(4, step_fins(st, FINS['bpd']))}" for st in STEPS if st})


def build_bpd2(name):
    s = sub(name, ["c", "d", "op", "on", "vcm", "vref", "vdd", "vss"],
            dict(left=["c", "d"], right=["op", "on"], top=["vref", "vcm", "vdd"], bottom=["vss"]))
    f, fi = int(name.split("_")[1]), FINS["bpi"]
    inv(s, "c", "c", "cb", "vdd", "vss", fi)
    inv(s, "d", "d", "db", "vdd", "vss", fi)
    for o, hi, lo in (("op", "d", "db"), ("on", "db", "d")):              # + side: d -> VREF; - side the reverse
        tg(s, o + "m", o, "vcm", "c", "cb", "vdd", "vss", f)
        nand2(s, o + "h", "cb", hi, o + "hb", "vdd", "vss", fi)          # VREF when !c & hi
        m(s, o + "r", o, o + "hb", "vref", "vdd", "pfet", f)
        and2(s, o + "l", "cb", lo, o + "lo", "vdd", "vss", fi)          # GND when !c & lo
        m(s, o + "g", o, o + "lo", "vss", "vss", "nfet", f)


def build_refbuf():
    s = sub("refbuf", ["vin", "out", "ib", "vdd", "vss"], dict(left=["vin", "ib"], right=["out"], top=["vdd"], bottom=["vss"]))
    m(s, "b0", "ib", "ib", "vss", "vss", "nfet", FINS["ota_tail"])          # bias mirror input (ib sinks the bias)
    m(s, "t", "tl", "ib", "vss", "vss", "nfet", FINS["ota_tail"])
    # the PMOS output stage inverts, so the feedback goes to the diode side of the mirror
    m(s, "1", "x", "out", "tl", "vss", "nfet", FINS["ota_in"])             # - input (unity-gain feedback)
    m(s, "2", "y", "vin", "tl", "vss", "nfet", FINS["ota_in"])             # + input
    m(s, "3", "x", "x", "vdd", "vdd", "pfet", FINS["ota_ld"])
    m(s, "4", "y", "x", "vdd", "vdd", "pfet", FINS["ota_ld"])
    m(s, "o", "out", "y", "vdd", "vdd", "pfet", FINS["ota_out"])           # class-A output stage
    m(s, "k", "out", "ib", "vss", "vss", "nfet", FINS["ota_sink"])
    cap(s, "c", "y", "out", 60e-15)                                        # Miller


def build_conv(draw=False):
    AS = ADC_SHARE
    ins = [f"a{c}{b}{sd}" for c in range(AS) for b in (0, 1) for sd in "pn"]
    ens = [f"e{c}_{b}" for c in range(AS) for b in (0, 1)]
    dp, dn = [f"dp{k}" for k in range(N_STEP)], [f"dn{k}" for k in range(N_STEP)]
    s = sub("conv", [*ins, "samp", "sclk", "bank", "trim", *ens, *dp, *dn, "cv", "vcm", "vref", "vdd", "vss"],
            dict(left=[*ins, "samp", "sclk", "bank", "trim"], right=[*ens, "cv"], bottom=["vss", *dp, *dn],
                 top=["vref", "vcm", "vdd"]))
    for e in ens:
        inv(s, "i" + e, e, e + "b", "vdd", "vss", FINS["logic"])
    for c in range(AS):
        for b in (0, 1):
            for sd in "pn":
                tg(s, f"x{c}{b}{sd}", f"a{c}{b}{sd}", "c" + sd, f"e{c}_{b}", f"e{c}_{b}b", "vdd", "vss", FINS["mux"])
    red, nf = G.SAR_OPT[COMPARATOR][:2]
    trim = TRIM if TRIM is not None else CORNER == "ss"
    if COMPARATOR == "strongarm":
        s.X("f", "sarm", "cp", "cn", "cf", "cfb", "fa", "fb", "vdd", "vss")
        nf = 13
        s.raw_spice("Rqa qa vss 1e9\nRqb qb vss 1e9")
    else:
        s.X("f", "dtf", "cp", "cn", "cf", "cfb", "fa", "fb", "vdd", "vss")
        s.X("q", "dtq", "cp", "cn", "cq", "cqb", "trim", "qa", "qb", "vdd", "vss")
    for k in range(N_STEP):
        st = STEPS[k] or 1
        # the drawing shows one driver symbol for every step (an arrayed instance); sizes are in the netlist
        drv = "bpd2_4" if draw else f"bpd2_{max(4, step_fins(st, FINS['bpd']))}"
        s.X(f"b{k}", drv, f"c{k}", f"d{k}", f"dp{k}", f"dn{k}", "vcm", "vref", "vdd", "vss")
    cl = [f"c{k}" for k in range(N_STEP)] + [f"d{k}" for k in range(N_STEP)]
    pins = ["samp", "sclk", "bank", "fa", "fb", "qa", "qb", "cf", "cfb", "cq", "cqb", *cl, *ens, "cv"]
    if draw:
        s.X("l", "imc_sar_logic", *pins)
    else:
        s.raw_spice(f"Nl {' '.join(pins)} imc_sar_logic AS={AS} red={red} n_fast={nf}")
    return trim


def logic_stub():
    """cktImg draws the Verilog-A logic as a block: a body-less subckt with its port sides."""
    AS = ADC_SHARE
    ens = [f"e{c}_{b}" for c in range(AS) for b in (0, 1)]
    cl = [f"c{k}" for k in range(N_STEP)] + [f"d{k}" for k in range(N_STEP)]
    ports = ["samp", "sclk", "bank", "fa", "fb", "qa", "qb", "cf", "cfb", "cq", "cqb", *cl, *ens, "cv"]
    return (f".subckt imc_sar_logic {' '.join(ports)}\n*@ left samp sclk bank fa fb qa qb\n"
            f"*@ right cf cfb cq cqb {' '.join(ens)} cv\n*@ bottom {' '.join(cl)}\n.ends\n")


# ----------------------------------------------------------------------------- composition
def tile_ports(rows, cols):
    return ([f"wwl{r}" for r in range(rows)] + [f"w{c}_{b}" for c in range(cols) for b in range(8)] +
            [f"d{r}" for r in range(rows)] + [f"sg{r}" for r in range(rows)] +
            ["en", "rst", "sh", "mrg", "brst", "bank", "samp", "sclk", "trim"] +
            [f"cv{j}" for j in range(-(-cols // ADC_SHARE))] + ["vdr", "vcm", "vref", "vdd", "vss"])


def core_ports(rows, cols):
    return [x for x in tile_ports(rows, cols) if not x.startswith("cv") and x not in ("samp", "sclk", "trim", "vcm", "vref")]


def build_rows(rows):
    p = [f"d{r}" for r in range(rows)] + [f"sg{r}" for r in range(rows)] + ["en"] + \
        [f"rp{r}" for r in range(rows)] + [f"rn{r}" for r in range(rows)] + ["vdr", "vdd", "vss"]
    s = sub("rows", p, dict(left=p[:2 * rows + 1], right=p[2 * rows + 1:4 * rows + 1], top=["vdr", "vdd"], bottom=["vss"]))
    for r in range(rows):
        s.X(f"d{r}", "rdrv", f"d{r}", f"sg{r}", "en", f"rp{r}", f"rn{r}", "vdr", "vdd", "vss")


def build_arr(rows, cols):
    tp = [f"{k}{c}" for k in ("tmp", "tmn", "tlp", "tln") for c in range(cols)]
    p = ([f"wwl{r}" for r in range(rows)] + [f"w{c}_{b}" for c in range(cols) for b in range(8)] +
         [f"rp{r}" for r in range(rows)] + [f"rn{r}" for r in range(rows)] + tp + ["vdd", "vss"])
    s = sub("arr", p, dict(left=p[:-(len(tp) + 2)], right=tp, top=["vdd"], bottom=["vss"]))
    for r in range(rows):
        for c in range(cols):
            s.X(f"x{r}_{c}", "wcell", f"wwl{r}", *[f"w{c}_{b}" for b in range(8)], f"rp{r}", f"rn{r}",
                f"tmp{c}", f"tmn{c}", f"tlp{c}", f"tln{c}", "vdd", "vss")


CTRL = ["rst", "sh0", "sh1", "mg0", "mg1", "br0", "br1"]


def build_cgrp(n, name):
    """n columns and the converter that serves them (n = ADC_SHARE, fewer for a last partial group)."""
    tp = [f"{k}{c}" for k in ("tmp", "tmn", "tlp", "tln") for c in range(n)]
    p = tp + CTRL + ["samp", "sclk", "bank", "trim", "cv", "vcm", "vref", "vdd", "vss"]
    s = sub(name, p, dict(left=tp + CTRL + ["samp", "sclk", "bank", "trim"], right=["cv"], top=["vcm", "vref", "vdd"],
                          bottom=["vss"]))
    dp, dn = [f"dp{k}" for k in range(N_STEP)], [f"dn{k}" for k in range(N_STEP)]
    for c in range(n):
        s.X(f"c{c}", "col", f"tmp{c}", f"tmn{c}", f"tlp{c}", f"tln{c}", *CTRL, f"e{c}_0", f"e{c}_1", *dp, *dn,
            f"a{c}0p", f"a{c}0n", f"a{c}1p", f"a{c}1n", "vdd", "vss")
    ins = [f"a{c}{b}{sd}" if c < n else "vss" for c in range(ADC_SHARE) for b in (0, 1) for sd in "pn"]
    ens = [f"e{c}_{b}" for c in range(ADC_SHARE) for b in (0, 1)]
    s.X("v", "conv", *ins, "samp", "sclk", "bank", "trim", *ens, *dp, *dn, "cv", "vcm", "vref", "vdd", "vss")


def build_tile(rows, cols, converters=True, name="tile"):
    """converters=False: the core the MAC benches drive (no converters; the columns' bank nodes stay internal)."""
    nconv = -(-cols // ADC_SHARE)
    p = tile_ports(rows, cols) if converters else core_ports(rows, cols)
    cvs = [f"cv{j}" for j in range(nconv)] if converters else []
    ctl = ["en", "rst", "sh", "mrg", "brst", "bank"] + (["samp", "sclk", "trim"] if converters else [])
    s = sub(name, p, dict(left=[x for x in p if x.startswith(("wwl", "w", "d", "sg"))] + ctl, right=cvs,
                          top=["vdr", "vcm", "vref", "vdd"] if converters else ["vdr", "vdd"], bottom=["vss"]))
    rp, rn = [f"rp{r}" for r in range(rows)], [f"rn{r}" for r in range(rows)]
    tp = [f"{k}{c}" for k in ("tmp", "tmn", "tlp", "tln") for c in range(cols)]
    s.X("rows", "rows", *[f"d{r}" for r in range(rows)], *[f"sg{r}" for r in range(rows)], "en", *rp, *rn, "vdr", "vdd", "vss")
    s.X("arr", "arr", *[f"wwl{r}" for r in range(rows)], *[f"w{c}_{b}" for c in range(cols) for b in range(8)],
        *rp, *rn, *tp, "vdd", "vss")
    s.X("ctl", "ctl", "sh", "mrg", "brst", "bank", *CTRL[1:], "vdd", "vss")
    if not converters:                           # no converter: enables and DAC lines idle at ground
        for c in range(cols):
            s.X(f"c{c}", "col", f"tmp{c}", f"tmn{c}", f"tlp{c}", f"tln{c}", *CTRL, "vss", "vss",
                *["vss"] * (2 * N_STEP), f"a{c}0p", f"a{c}0n", f"a{c}1p", f"a{c}1n", "vdd", "vss")
        return s
    for j in range(nconv):
        cs = range(j * ADC_SHARE, min(cols, (j + 1) * ADC_SHARE))
        s.X(f"g{j}", "cgrp" if len(cs) == ADC_SHARE else "cgrp_p",
            *[f"{k}{c}" for k in ("tmp", "tmn", "tlp", "tln") for c in cs], *CTRL, "samp", "sclk", "bank", "trim",
            f"cv{j}", "vcm", "vref", "vdd", "vss")
    return s


def build_tiles(rows, cols, ntiles):
    pt = tile_ports(rows, cols)
    shared = [x for x in pt if not x.startswith("cv") and x not in ("vdr", "vcm", "vref", "vdd", "vss")]
    nconv = -(-cols // ADC_SHARE)
    outs = [f"t{t}cv{j}" for t in range(ntiles) for j in range(nconv)]
    # ponytail: every tile gets the same weights / rows here; the system feeds each its own (the RTL's job)
    s = sub("tiles", [*shared, *outs, "vref", "vbias", "ib", "vdd", "vss"],
            dict(left=shared, right=outs, top=["vref", "vbias", "ib", "vdd"], bottom=["vss"]))
    s.X("ref", "refbuf", "vbias", "vcm", "ib", "vdd", "vss")
    cap(s, "vcm", "vcm", "vss", C_DEC_VCM * ntiles)
    for t in range(ntiles):
        wire(s, "R", f"pdn{t}", "vdd", f"vdr{t}", R_PDN / sc(cols))
        s.X(f"t{t}", "tile", *shared, *[f"t{t}cv{j}" for j in range(nconv)], f"vdr{t}", "vcm", "vref", "vdd", "vss")
    return s


def build_all(rows=ROWS, cols=COLS, ntiles=N_TILES, draw=False):
    SUBS.clear()
    build_array(cols)
    build_rdrv(cols)
    build_bsw()
    build_col()
    build_ctl(cols)
    build_cmp()
    for n in bpd_names():
        build_bpd2(n)
    build_refbuf()
    trim = build_conv(draw)
    build_rows(rows)
    build_arr(rows, cols)
    build_cgrp(ADC_SHARE, "cgrp")
    if cols % ADC_SHARE:
        build_cgrp(cols % ADC_SHARE, "cgrp_p")
    build_tile(rows, cols)
    build_tiles(rows, cols, ntiles)
    return trim


def text(names=None, draw=False):
    """`.subckt` text of the named subcircuits (all, children first, by default)."""
    c = ps.Circuit("deck")
    for n in (names or list(SUBS)):
        c.subcircuit(SUBS[n][0])
    t = str(c)
    t = t[t.index(".subckt"): t.rindex(".ends") + 5] + "\n"
    if draw:
        t = logic_stub() + t
    return t


def hdl():
    return '.hdl "imc_sar_logic.va"\n'


def lib(corner=CORNER):
    return "\n".join(PDK.model_lines(corner)) + f"\n.temp {dict(tt=27, ss=100, ff=85)[corner]}\n"


# ----------------------------------------------------------------------------- --emit
def emit():
    d = OUT / "netlist"
    d.mkdir(parents=True, exist_ok=True)
    trim = build_all()
    head = (f"* imc_tile transistor-level netlist (netlist/imc_tile.py): ROWS {ROWS} COLS {COLS} N_TILES {N_TILES} "
            f"{DRIVE_MODE} {COMPARATOR} AdcShare {ADC_SHARE} {CORNER} R_PDN {R_PDN} ohm, quiet-class trim {int(trim)}\n")
    (d / "imc_tile.spice").write_text(head + hdl() + text())
    n = text().count("\nM")
    print(f"wrote {d / 'imc_tile.spice'} ({n} MOSFET cards in the subcircuit bodies)")


# ----------------------------------------------------------------------------- --draw
_IDX = __import__("re").compile(r"^(.*?)(\d+)$")


def _spans(toks, lo=2):
    """Maximal runs name<i>, name<i+1>, ... (>= lo long, no leading zeros): [(start, end, bus token)]."""
    out, i = [], 0
    while i < len(toks):
        mt = _IDX.match(toks[i])
        j = i + 1
        if mt and mt.group(2) == str(int(mt.group(2))):
            while j < len(toks):
                mj = _IDX.match(toks[j])
                if not (mj and mj.group(1) == mt.group(1) and mj.group(2) == str(int(mt.group(2)) + j - i)):
                    break
                j += 1
        if mt and j - i >= lo:
            out.append((i, j, f"{mt.group(1)}<{mt.group(2)}:{int(mt.group(2)) + j - i - 1}>"))
        i = max(j, i + 1)
    return out


def _bus(toks, spans):
    """toks with each span [(i, j, token)] replaced by its bus token."""
    out, i = [], 0
    for a, b, t in spans:
        out += toks[i:a] + [t]
        i = b
    return out + toks[i:]


def _arrays(body):
    """Merge X instances of one master whose nets differ only by the instance's index (an arrayed
    instance), when no other line uses those indexed nets one by one."""
    groups = {}
    for ln in body:
        t = ln.split()
        mt = _IDX.match(t[0]) if ln.startswith("X") else None
        if mt:
            groups.setdefault((mt.group(1), t[-1], len(t)), []).append((int(mt.group(2)), t))
    out = list(body)
    for (pre, master, _), g in groups.items():
        g.sort()
        ks = [k for k, _ in g]
        if len(g) < 3 or ks != list(range(ks[0], ks[0] + len(g))):
            continue
        nets, members = [], set()
        for pos in range(1, len(g[0][1]) - 1):
            col = [t[pos] for _, t in g]
            if len(set(col)) == 1:
                nets.append(col[0])
                continue
            ms = [_IDX.match(c) for c in col]
            if not all(ms) or len({x.group(1) for x in ms}) != 1 or [int(x.group(2)) for x in ms] != ks:
                break
            nets.append(f"{ms[0].group(1)}<{ks[0]}:{ks[-1]}>")
            members |= set(col)
        else:
            names = {t[0] for _, t in g}
            rest = [ln.split() for ln in out if ln.split() and ln.split()[0] not in names]
            # another card may use the members only as a whole run (it is drawn as the same bus)
            used = {tok for t in rest for tok in _bus(t[1:], _spans(t[1:]))}
            if used & members:
                continue
            first = " ".join(g[0][1])
            out = [ln for ln in out if ln.split()[0] not in names or ln == first]
            out[out.index(first)] = f"X{pre[1:]}<{ks[0]}:{ks[-1]}> {' '.join(nets)} {master}"
    return out


def _members(tok):
    mt = __import__("re").match(r"^(.*)<(\d+):(\d+)>$", tok)
    return {f"{mt.group(1)}{k}" for k in range(int(mt.group(2)), int(mt.group(3)) + 1)} if mt else {tok}


def draw_deck(name):
    """cktImg deck of one subckt: its children as port-only stubs; index runs drawn as buses where every
    use of those nets bundles them the same way (port spans every instance fills with a run, arrayed
    instances), else as single nets."""
    import re
    blocks = {}
    for blk in re.findall(r"^\.subckt.*?^\.ends", logic_stub() + text(), re.S | re.M):
        ls = [ln for ln in blk.splitlines()[:-1] if ln.strip()]
        blocks[ls[0].split()[1]] = ls
    ls = blocks[name]
    body = _arrays([ln for ln in ls[1:] if not ln.startswith("*@")])
    xs = [ln.split() for ln in body if ln.startswith("X")]
    other = [ln.split() for ln in body if not ln.startswith("X")]
    masters = sorted({t[-1] for t in xs})
    cand = {}
    for master in masters:
        ports = blocks[master][0].split()[2:]
        insts = [t for t in xs if t[-1] == master]
        cand[master] = [sp for sp in _spans(ports)
                        if all(any(a == sp[0] and b == sp[1] for a, b, _ in _spans(t[1:-1])) for t in insts)]
    hports = ls[0].split()[2:]
    hspans = _spans(hports)
    while True:      # drop spans until every net is bundled the same way everywhere it is used
        uses = []    # (owner, span, token over the nets)
        for master in masters:
            for t in (t for t in xs if t[-1] == master):
                for sp in cand[master]:
                    tok = [x for x in _spans(t[1:-1]) if x[0] == sp[0] and x[1] == sp[1]][0][2]
                    uses.append((master, sp, tok))
        uses += [(None, sp, sp[2]) for sp in hspans]
        bundled = {}
        for _, _, tok in uses:
            for mbr in _members(tok):
                bundled.setdefault(mbr, set()).add(tok)
        single = {tok for t in xs for tok in t[1:-1] if "<" in tok} | set()
        for t in xs:
            covered = set()
            for master_sp in cand.get(t[-1], []):
                covered |= set(range(1 + master_sp[0], 1 + master_sp[1]))
            single |= {t[i] for i in range(1, len(t) - 1) if i not in covered}
        single |= {tok for t in other for tok in t[1:]}
        hcov = set()
        for sp in hspans:
            hcov |= set(range(sp[0], sp[1]))
        single |= {hports[i] for i in range(len(hports)) if i not in hcov}
        bad = {tok for mbr, toks in bundled.items() for tok in toks if len(toks) > 1 or mbr in single}
        bad |= {tok for tok in single if "<" in tok for t2 in [tok] if any(m_ in bundled and tok not in bundled[m_] for m_ in _members(tok))}
        if not bad:
            break
        for master, sp, tok in uses:
            if tok in bad:
                if master is None:
                    hspans = [x for x in hspans if x != sp]
                else:
                    cand[master] = [x for x in cand[master] if x != sp]
    out = []
    for master in masters:
        ports = blocks[master][0].split()[2:]
        spans = cand[master]
        out.append(" ".join([".subckt", master, *_bus(ports, spans)]))
        names = {sp[2] for sp in spans}
        for ln in blocks[master][1:]:
            if ln.startswith("*@"):
                p = ln.split()
                out.append(" ".join(p[:2] + _bus(p[2:], [x for x in _spans(p[2:]) if x[2] in names])))
        out.append(".ends")
        for t in (t for t in xs if t[-1] == master):
            sp_i = [x for x in _spans(t[1:-1]) if any(x[0] == a and x[1] == b for a, b, _ in spans)]
            body[body.index(" ".join(t))] = " ".join([t[0], *_bus(t[1:-1], sp_i), t[-1]])
    hdr = " ".join([".subckt", name, *_bus(hports, hspans)])
    keep = {sp[2] for sp in hspans}
    hints = [" ".join(p[:2] + _bus(p[2:], [x for x in _spans(p[2:]) if x[2] in keep]))
             for p in (ln.split() for ln in ls[1:] if ln.startswith("*@"))]
    return "\n".join(out + [hdr, *hints, *body, ".ends"]) + "\n"


# The views: (file, subckt, options). cktImg lays a deck out well when it reads like a textbook stage (supply on
# top, signal left to right); a switch network, a gate array or a latch loop it scatters, and a port it cannot
# tell from an internal net it leaves unmarked. So each view is a stage of one subckt, drawn with:
#   keep   regex over the cards drawn (a stage, or a representative slice of a repeated structure)
#   label  nets named at every pin instead of wired (clocks, phases, logic inputs)
#   fb     {card: [net]}: that card's pin on the net named, not wired (a latch's cross-coupling, a follower's loop)
#   role   {net: "i" | "o" | "s"}: a stage's boundary nets as input / output / supply terminals
#   tg     an nmos + pmos pair on the same two nets drawn as one transmission gate (cktImg's switch symbol)
#   block  a block view: nets an instance shares with the same neighbours (same direction) become one bus,
#          vdd / vss stay off the blocks
#   note   the caption: what the slice stands for
# Ports take their role from the subckt's *@ side (left in, right out, top supply). Only the drawing changes: the
# names cktImg reads roles from are restored in the JSON and SVG, and the netlists above are untouched.
_LATCH = dict(lata=(r"Mt2|M[pnr]a|Mxa[pn]", dict(d1="i", oa="o", xa="o"), {"Mpa": ["ob"], "Mna": ["ob"]}),
              latb=(r"M[pnr]b|Mxb[pn]", dict(t2="s", d2="i", ob="o", xb="o"), {"Mpb": ["oa"], "Mnb": ["oa"]}))
DRAW = [
    ("gc3t", "gc3t", {}),
    ("xp", "xp", {}),
    ("smx", "smx", {}),
    ("rdrv", "rdrv", dict(keep=r"M(s|ap)\w*|Mop\w|Rsp|Cwp", label="d sg sgb", note="rp rail; rn is the same on sg")),
    ("bsw", "bsw", {}),
    ("bank.share", "bank", dict(keep=r"Xs[ml]|Mr(a|bl|mm)", label="sh br", role=dict(a="o", bl="o", mm="o"))),
    ("bank.merge", "bank", dict(keep=r"Mm[lm][np]|C[mr]", tg=1, label="mg mgb", role=dict(bl="i", a="o"))),
    ("bank.step", "bank", dict(keep=r"Cd0|M[ep]0[np]?", tg=1, label="en enb", role=dict(a="o"),
                               note="step 0 (1024 LSB) of 12")),
    ("ctl", "ctl", dict(keep=r"Mb[pn]|Msh[01]\w*", label="bank bankb sh", note="sh0, sh1; mg and br alike")),
    *[(f"{c}.pre", c, dict(keep=r"Ms1|M[ab]1|Mr[12]|C[12]", label="clk", role=dict(d1="o", d2="o"),
                           note="" if c == "dtf" else "slice 1 of 3; 2-3 on clkt")) for c in ("dtf", "dtq")],
    ("dtq.trim", "dtq", dict(keep=r"Mtr\w*", role=dict(clkt="o"))),
    *[(f"{c}.{h}", c, dict(keep=k, label="clkb", role=r, fb=f)) for c in ("dtf", "dtq") for h, (k, r, f) in _LATCH.items()],
    ("bpd2.out", "bpd2_32", dict(keep=r"Mop[mrg][np]?", tg=1, label="c cb", role=dict(ophb="i", oplo="i"),
                                 note="op side of the 1024-LSB step; on swaps d, db; 16 / 8 / 4 fins below")),
    ("bpd2.dec", "bpd2_32", dict(keep=r"Mop[hl]\w*", label="c cb d db", role=dict(ophb="o", oplo="o"))),
    ("mux", "conv", dict(keep=r"Mx00\w*", tg=1, label="e0_0 e0_0b", role=dict(cp="o", cn="o"),
                         note=f"column 0, bank 0 of {ADC_SHARE} x 2")),
    ("refbuf", "refbuf", dict(fb={"M1": ["out"]})),
    ("half", "half", dict(block=1, keep=r"Xg[067]|Xm|Xx[06]|Cu[06]", note="bits 0 and 6 of 0-6, and the sign bit 7")),
    ("wcell", "wcell", dict(block=1)),
    ("col", "col", dict(block=1)),
    ("conv", "conv", dict(block=1, keep=r"X\S*|Mx00\w*", tg=1, label="e0_0 e0_0b cf cfb cq cqb",
                          note=f"mux of column 0, bank 0 of {ADC_SHARE} x 2")),
    ("cgrp", "cgrp", dict(block=1)),
    ("rows", "rows", dict(block=1, note=f"2 of {ROWS} rows")),
    ("arr", "arr", dict(block=1, note=f"2 of {ROWS} rows x {ADC_SHARE} of {COLS} columns")),
    ("tile", "tile", dict(block=1, note=f"2 of {ROWS} rows x {ADC_SHARE} of {COLS} columns, 1 converter")),
    ("tiles", "tiles", dict(block=1, note="2 of the die's tiles")),
]
_ROLE = dict(i="in_", o="out_", s="vdd_", l="vb_")      # name prefixes cktImg reads roles from


def _cards(src):
    """{subckt: (ports, {port: side}, [card tokens])} of a deck."""
    import re
    out = {}
    for blk in re.findall(r"^\.subckt.*?^\.ends", src, re.S | re.M):
        ls = [ln.split() for ln in blk.splitlines()[:-1] if ln.strip()]
        sides = {x: ln[1] for ln in ls[1:] if ln[0] == "*@" for x in ln[2:]}
        out[ls[0][1]] = (ls[0][2:], sides, [t for t in ls[1:] if not t[0].startswith("*")])
    return out


def _nn(t):
    """Net count of a card."""
    return 4 if t[0][0] in "MmSs" else 2 if t[0][0] in "CcRr" else len(t) - 2


def _tgs(body):
    """nmos + pmos on the same two nets -> one switch card S<name> a b gn gp."""
    out, done = [], set()
    for t in body:
        if t[0] in done:
            continue
        u = next((u for u in body if t[0][0] == "M" and "nmos" in t[5] and u[0][0] == "M" and "pmos" in u[5]
                  and u[0] not in done and {u[1], u[3]} == {t[1], t[3]}), None)
        out.append(["S" + t[0][1:-1], t[1], t[3], t[2], u[2], "tg"] if u else t)
        done |= {t[0], u[0]} if u else {t[0]}
    return out


def _bundle(S, name, body):
    """Block view: nets with the same users (instance and direction, or the top) become one bus token."""
    import re
    ports, sides, _ = S[name]
    users = {}
    for t in body:
        if t[0][0] in "Xx":
            cp, cs, _ = S[t[-1]]
            for mp, n in zip(cp, t[1:-1]):
                users.setdefault(n, set()).add((t[0], cs.get(mp) == "right"))
        else:
            for n in t[1:1 + _nn(t)]:
                users.setdefault(n, set()).add(t[0])
    for p in ports:
        users.setdefault(p, set()).add("top")
    groups = {}
    for n, u in users.items():
        if n not in ("vdd", "vss", "vdr", "vcm", "vref") and all(isinstance(x, tuple) or x == "top" for x in u):
            groups.setdefault(frozenset(u), []).append(n)
    order = [n for t in body for n in t[1:1 + _nn(t)]] + list(ports)
    tok = {}
    for g in groups.values():
        if len(g) < 2:
            continue
        g.sort(key=order.index)
        idx = {re.search(r"(<.*>|\d*)$", m).group(1) for m in g}       # one shared index stays on the token
        bases = list(dict.fromkeys(re.sub(r"\d+$", "", re.sub(r"_?<.*>$|\d+$", "", m)) or m for m in g))
        t, k = "/".join(bases) + (idx.pop() if len(idx) == 1 else ""), 2
        while t in tok.values():
            t, k = "/".join(bases) + f"_{k}", k + 1
        tok.update({m: t for m in g})
    nb, stubs = [], {}
    for t in body:
        k = _nn(t)
        if t[0][0] not in "Xx":
            nb.append([t[0]] + [tok.get(n, n) for n in t[1:1 + k]] + t[1 + k:])
            continue
        cp, cs, _ = S[t[-1]]
        pins = {}                       # net token -> the master's ports on it (the block's pin name)
        for mp, n in zip(cp, t[1:-1]):
            if n not in ("vdd", "vss"):
                pins.setdefault(tok.get(n, n), []).append(mp)
        names = ["/".join(dict.fromkeys(re.sub(r"<.*>$", "", x) for x in v)) for v in pins.values()]
        if len(set(names)) < len(names):
            names = ["/".join(v) for v in pins.values()]
        master = t[-1]
        while master in stubs and stubs[master][0] != names:
            master += "'"
        stubs[master] = (names, {nm: cs.get(v[0], "left") for nm, v in zip(names, pins.values())})
        nb.append([t[0], *pins, master])
    tp = list(dict.fromkeys(tok.get(p, p) for p in ports))
    return nb, tp, {tok.get(p, p): sides.get(p, "left") for p in ports}, stubs


def view_deck(sub, src, keep=None, label="", fb=None, role=None, tg=False, block=False, note=""):
    """The cktImg deck of one view (from `src`, the deck's subckts), {drawn name: netlist name}, {port: role}."""
    import re
    S = _cards(draw_deck(sub) if block else src)
    ports, sides, body = S[sub]
    body = [list(t) for t in body if not keep or re.fullmatch(keep, t[0])]
    if tg:
        body = _tgs(body)
    for t in body:
        k = _nn(t)
        t[1:1 + k] = ["vb_" + x if x in (fb or {}).get(t[0], ()) else x for x in t[1:1 + k]]
    stubs = {t[-1]: S[t[-1]][:2] for t in body if t[0][0] in "Xx"}
    if block:
        body, ports, sides, stubs = _bundle(S, sub, body)
    used = {n for t in body for n in t[1:1 + _nn(t)]}
    roles = {p: {"left": "i", "right": "o", "top": "s"}.get(sides.get(p), "i") for p in ports if p != "vss"}
    roles.update({n: "l" for n in label.split()}, **(role or {}))
    ren = {n: _ROLE[roles[n]] + n for n in used if n in roles and not (roles[n] == "s" and n.startswith("vdd"))}
    out = []
    for master, (cp, cs) in stubs.items():
        out.append(f".subckt {master} {' '.join(cp)}")
        out += [f"*@ {sd} {' '.join(p for p in cp if cs.get(p) == sd)}" for sd in ("left", "right", "top", "bottom")
                if any(cs.get(p) == sd for p in cp)]
        out.append(".ends")
    out.append(f".subckt {sub}_view {' '.join(ren.get(p, p) for p in ports if p in used)}")
    for t in body:
        k = _nn(t)
        if t[0][0] == "M":          # bulk on the source: cktImg counts the hidden bulk as a supply path
            t = t[:4] + [t[3]] + t[5:]
        out.append(" ".join([t[0]] + [ren.get(x, x) for x in t[1:1 + k]] + t[1 + k:]))
    out.append(".ends")
    back = {v: k for k, v in ren.items()} | {"vb_" + n: n for ns in (fb or {}).values() for n in ns}
    return "\n".join(out) + "\n", back, {n: roles[n] for n in ren}


def draw():
    import re
    d = OUT / "schematics"
    d.mkdir(parents=True, exist_ok=True)
    ck = shutil.which("cktimg-json")
    if not ck:
        sys.exit("cktimg-json not on PATH (run inside ./env.sh analog)")
    for f in [*d.glob("*.spice"), *d.glob("*.json"), *d.glob("*.svg")]:
        f.unlink()
    esc = lambda x: x.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")   # noqa: E731
    index = {}
    # cells at the full tile's sizing; block views at a drawable size (2 rows x one converter's columns, 2 tiles)
    built = None
    for view, sub, opt in sorted(DRAW, key=lambda v: bool(v[2].get("block"))):
        if built != bool(opt.get("block")):
            built = bool(opt.get("block"))
            build_all(rows=2, cols=ADC_SHARE, ntiles=2, draw=True) if built else build_all(draw=True)
            src = logic_stub() + text()
        deck, back, ports = view_deck(sub, src, **opt)
        (d / f"{view}.spice").write_text(deck)
        r = subprocess.run([ck, "--svg", str(d / f"{view}.svg"), str(d / f"{view}.spice"), str(d / f"{view}.json")],
                           capture_output=True, text=True)
        if r.returncode:
            print(f"FAIL {view}.svg: {r.stderr[-400:]}")
            continue
        g = json.loads((d / f"{view}.json").read_text())
        g["nets"] = [back.get(n, n) for n in g["nets"]]
        for x in [*g["wires"], *g["labels"]]:
            x["net"] = back.get(x["net"], x["net"])
        for dev in g["devices"]:
            for pin in dev["pins"]:
                pin["net"] = back.get(pin["net"], pin["net"])
        (d / f"{view}.json").write_text(json.dumps(g))
        svg = (d / f"{view}.svg").read_text()
        for a, b in back.items():
            svg = svg.replace(f">{esc(a)}<", f">{esc(b)}<")
        note = " · ".join(x for x in (f"{sub} (netlist/imc_tile.py)", opt.get("note")) if x)
        svg = re.sub(r"(<text[^>]*>)(</text>\s*</svg>)", lambda mt: mt.group(1) + esc(note) + mt.group(2), svg)
        (d / f"{view}.svg").write_text(svg)
        size = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg)
        index[view] = dict(subckt=sub, note=opt.get("note", ""), block=bool(opt.get("block")), ports=ports,
                           size=[float(size.group(1)), float(size.group(2))])
        print(f"OK   {view}.svg {float(size.group(1)):.0f} x {float(size.group(2)):.0f}")
    (d / "views.json").write_text(json.dumps(index, indent=1))


# ----------------------------------------------------------------------------- --sim
def espice(deck, name, cols, timeout=900):
    """Run under the shared lock with a 4 GB cap; return {column: np.array}."""
    d = OUT / "spice" / name
    d.mkdir(parents=True, exist_ok=True)
    shutil.copy(BLK / "va" / "imc_sar_logic.va", d)
    (d / "deck.sp").write_text(deck)
    cmd = ["flock", "-w", "900", LOCK, "systemd-run", "--user", "--scope", "-q", "-p", "MemoryMax=4G",
           "-E", "ZP_TRAN_STATS=1", "timeout", str(timeout), "espice", "deck.sp", "--format=csv", "-r", "out.csv"]
    r = subprocess.run(cmd, cwd=d, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"espice {name} failed ({r.returncode}):\n{r.stderr[-2500:]}{r.stdout[-800:]}")
    h = open(d / "out.csv").readline().strip().split(",")
    want = ["time"] + [c.lower() for c in cols]
    a = np.loadtxt(d / "out.csv", delimiter=",", skiprows=1, usecols=[h.index(c) for c in want])
    (d / "out.csv").unlink()
    return {c: a[:, i] for i, c in enumerate(want)}


def at(res, node, t):
    return float(np.interp(t, res["time"], res[node.lower()]))


def pwl(name, pts, grid=2e-12):
    """PWL with its corners on the tstep grid: a corner between grid points can collapse the step
    (TOOL_ISSUES, ESPice TimestepTooSmall); moving an edge by < 1 ps changes nothing here."""
    out, last = [], -1.0
    for t, v in pts:
        t = max(round(t / grid) * grid, last + grid if last >= 0 else 0.0)
        out.append((t, v))
        last = t
    return f"V{name} {name} 0 PWL(" + " ".join(f"{t:.6e} {v:.4g}" for t, v in out) + ")"


def logic(name, windows, tr=15e-12):
    """0/VDD source high in [(t0, t1)]."""
    pts = [(0.0, 0.0)]
    for t0, t1 in windows:
        pts += [(t0, 0.0), (t0 + tr, VDD), (t1, VDD), (t1 + tr, 0.0)]
    return pwl(name, pts)


FAILS = []


def check(name, ok, msg):
    print(f"{'PASS' if ok else 'FAIL'} {name}: {msg}", flush=True)
    if not ok:
        FAILS.append(name)


def bench_core(rows, cols, W, X_passes, name):
    """Reduced tile core (rows, array, columns, ctl; no converters) on the RTL's BS6H pin schedule:
    write W, then one bit-serial pass per X on banks 0, 1, 0 ... each merged under the next pass.
    Returns the ESPice result and the times at which each pass's merged bank is read."""
    build_all(rows=rows, cols=cols, ntiles=1)
    k = sc(cols)
    tk = TICK
    st = 6
    lines = ["* imc_tile --sim core", lib(), f"vdd vdd 0 {VDD}", f"Rpdn vdd vdr {R_PDN / k:.6g}",
             logic("en", [])]
    # write: one row per 150 ps, WWL 1.0 V write / -0.15 V hold (N3_r2)
    sw, hi, lo, _ = G.slice_w(W)
    mag = 16 * hi + lo
    t0 = 0.2e-9
    for r in range(rows):
        a = t0 + r * 150e-12
        lines.append(pwl(f"wwl{r}", [(0, -0.15), (a, -0.15), (a + 15e-12, 1.0), (a + 110e-12, 1.0), (a + 125e-12, -0.15)]))
    for c in range(cols):
        for b in range(8):
            pts = [(0.0, 0.0)]
            for r in range(rows):
                bit = ((mag[r, c] >> b) & 1) if b < 7 else sw[r, c]
                a = t0 + r * 150e-12
                pts += [(a - 20e-12, pts[-1][1]), (a - 5e-12, VDD * bit)]
            lines.append(pwl(f"w{c}_{b}", pts))
    tp0 = t0 + rows * 150e-12 + 0.3e-9
    # passes: slot s of pass p at a = tp0 + (p*7 + s) * 6 tk (merge hidden: no gap between passes). Pin
    # timing of imc_seq: the bank flips at the next pass's start (one tick after the hand-off), phi_mrg is
    # high for 2 ticks from there, phi_brst resets the new bank in its slot-0 tick 1, before the first share
    drv = {f"d{r}": [] for r in range(rows)}
    sgn = {f"sg{r}": [] for r in range(rows)}
    rst, sh, brst, bank, mrg = [], [], [], [], []
    reads = []
    for pi, X in enumerate(X_passes):
        sx, dg = G.digits(np.asarray(X)[None, :], "bitserial")
        for s_ in range(7):
            a = tp0 + (pi * 7 + s_) * st * tk
            rst.append((a, a + 0.5 * tk))
            sh.append((a + 2 * tk, a + 5 * tk))
            if s_ == 0:
                brst.append((a + tk, a + 2 * tk))
            for r in range(rows):
                if dg[0, r, s_]:
                    drv[f"d{r}"].append((a + tk, a + st * tk - 0.5 * tk))
                if sx[0, r]:
                    sgn[f"sg{r}"].append((a + tk, a + st * tk - 0.5 * tk))
        e = tp0 + (pi + 1) * 7 * st * tk                     # end of the pass: the next pass on the other bank
        if pi % 2 == 1:
            bank.append((e - 7 * st * tk, e))                # pass p accumulates on bank p % 2
        mrg.append((e, e + 2 * tk))                          # phi_mrg under the next pass's first slot
        reads.append(e + 3 * tk)
    tend = reads[-1] + tk
    for nm, w in {**drv, **sgn}.items():
        lines.append(logic(nm, w))
    lines += [logic("rst", rst), logic("sh", sh), logic("brst", brst), logic("bank", bank), logic("mrg", mrg)]
    build_tile(rows, cols, converters=False, name="tcore")
    lines.append(text(["gc3t", "xp", "smx", "half", "wcell", "rdrv", "rows", "arr", "bsw", "bank", "col", "ctl", "tcore"]))
    lines.append("Xt " + " ".join("0" if x == "vss" else x for x in core_ports(rows, cols)) + " tcore")
    probes = [f"xt.a{c}{b}{sd}" for c in range(cols) for b in (0, 1) for sd in "pn"]
    probes += ["xt.rp0", "vdr", "xt.xarr.xx0_0.xp.bp6", f"xt.xarr.xx{rows - 1}_0.xp.bp6"]
    # tstep 2p: with 1p, a PWL corner half-way between grid points (the tick is 141.5 ps) collapses the step
    # to 2.6e-23 s and ESPice stops (analog/docs/TOOL_ISSUES.md)
    lines += [".save " + " ".join(f"v({x})" for x in probes) + " i(vdd)", ".options method=gear", f".tran 2p {tend:.4e}", ".end", ""]
    res = espice("\n".join(lines), name, [f"v({x})" for x in probes] + ["i(vdd)"])
    return res, reads, tp0


def sim_mac():
    """(1) one bit-serial MAC pass per bank against the golden's merged column voltage (k S)."""
    rng = np.random.default_rng(7)
    rows, cols = 8, 4
    W = rng.integers(-127, 128, (rows, cols))
    Xs = [rng.integers(-127, 128, rows) for _ in range(3)]
    res, reads, _ = bench_core(rows, cols, W, Xs, "mac")
    p = G.P(cols=cols)
    meas, exp = [], []
    for pi, (X, tr) in enumerate(zip(Xs, reads)):
        b = pi % 2
        S = np.clip(X, -127, 127) @ np.clip(W, -127, 127)
        for c in range(cols):
            meas.append(at(res, f"v(xt.a{c}{b}p)", tr) - at(res, f"v(xt.a{c}{b}n)", tr))
            exp.append(p.k() * S[c])
    meas, exp = np.array(meas), np.array(exp)
    A = np.vstack([exp, np.ones_like(exp)]).T
    (g, o), *_ = np.linalg.lstsq(A, meas, rcond=None)
    resid = meas - (g * exp + o)
    fs = p.k() * 8 * 127 * 127
    check("MAC pass (8 x 4 transistor tile, 3 passes on banks 0/1/0)",
          0.80 < g < 1.05 and np.sqrt(np.mean(resid ** 2)) < 2e-3 * fs,
          f"merged V_diff (M) vs golden k S (D, k {p.k() * 1e6:.3f} uV/MAC): gain {g:.4f}, offset {o * 1e3:.2f} mV, "
          f"rms residual after gain/offset {np.sqrt(np.mean(resid ** 2)) * 1e6:.0f} uV = "
          f"{np.sqrt(np.mean(resid ** 2)) / fs * 100:.3f} % FS (gate 0.2 %); worst |V - k S| "
          f"{np.max(np.abs(meas - exp)) * 1e3:.2f} mV over {meas.size} column-passes")
    return dict(gain=g, offset=o, resid=float(np.sqrt(np.mean(resid ** 2))))


def sim_settle():
    """(2) plate settling at the 6-tick share edge, 8 rows on V (all bits 1, x = 127): the worst popcount."""
    rows, cols = 8, 4
    W = np.full((rows, cols), 127)
    res, reads, tp0 = bench_core(rows, cols, W, [np.full(rows, 127)], "settle")
    t_edge = tp0 + 5 * TICK                     # slot 0 share edge (rails up at tp0 + 1 tick)
    out = {}
    for r in (0, 7):
        v = at(res, f"v(xt.xarr.xx{r}_0.xp.bp6)", t_edge)
        out[r] = (VDD - v) / VDD
    e = max(out.values())
    rail = (VDD - at(res, "v(xt.rp0)", t_edge)) / VDD
    win = (res["time"] > tp0) & (res["time"] < tp0 + 6 * TICK)
    vmin = float(np.min(res["v(vdr)"][win]))
    # when does the plate reach 0.1 %? (rail time to 0.1 %)
    tt, vb = res["time"][win], res["v(xt.xarr.xx0_0.xp.bp6)"][win]
    ok_t = tt[(VDD - vb) / VDD <= 1e-3]
    t01 = (ok_t[0] - tp0 - TICK) * 1e9 if ok_t.size else float("nan")
    check("plate settling, 8 rows on V, 6-tick share edge", e <= 1e-3,
          f"MSB-unit bottom plate error (M) {out[0] * 100:.4f} % (row 0) / {out[7] * 100:.4f} % (row 7) of V at "
          f"{4 * TICK * 1e9:.3f} ns of rail time vs 0.1 % (DRIVE_ALT E3 at R_PDN {R_PDN} ohm: 0.078 %, M); the row rail "
          f"itself {rail * 100:.4f} %; the plate reaches 0.1 % after {t01:.3f} ns of rail time; tile supply min "
          f"{vmin:.4f} V; cell {'gc5t (buffered)' if GC_BUF else 'gc3t'}, xp_tg {FINS['xp_tg']} / smx {FINS['smx']} fins")
    return dict(err=e, rail=rail, t01_ns=t01, vmin=vmin, xp_tg=FINS["xp_tg"], smx=FINS["smx"], gc_buf=GC_BUF)


def sim_cmp_noise(n=200):
    """(3) .trannoise of the fast and quiet comparators (this netlist's subckts), probit at constant dv."""
    from statistics import NormalDist
    build_all(rows=2, cols=ADC_SHARE, ntiles=1)
    out = {}
    for cls, dv in (("dtf", 2.0e-3), ("dtq", 0.75e-3)):
        T = 1e-9
        ports = "inp inn clk clkb" + (" trim" if cls == "dtq" else "") + " oa ob vdd 0"
        deck = ["* comparator noise", lib(), f"vdd vdd 0 {VDD}", "vtrim trim 0 0",
                f"vclk clk 0 PULSE(0 {VDD} {T / 2:g} 2p 2p {T / 2 - 2e-12:g} {T:g})",
                f"vclkb clkb 0 PULSE({VDD} 0 {T / 2:g} 2p 2p {T / 2 - 2e-12:g} {T:g})",
                f"vip inp 0 {0.55 + dv / 2}", f"vin inn 0 {0.55 - dv / 2}", text(["dtf", "dtq"]),
                f"X1 {ports} {cls}", ".save v(oa) v(ob)", f".trannoise 0.5e-12 {n * T:g}", ".end", ""]
        r = espice("\n".join(deck), f"noise_{cls}", ["v(oa)", "v(ob)"], timeout=1800)
        t, a, b = r["time"], r["v(oa)"], r["v(ob)"]
        ok = tot = 0
        for k_ in range(1, n - 1):
            w = (t > k_ * T + 0.9 * T) & (t < (k_ + 1) * T - 0.02 * T)
            if w.any():
                ok += np.mean(a[w] - b[w]) > 0
                tot += 1
        pc = ok / tot
        z = NormalDist().inv_cdf(min(max(pc, 0.5 + 1e-6), 1 - 0.5 / tot))
        sp = math.sqrt(pc * (1 - pc) / tot)
        band = [dv / NormalDist().inv_cdf(min(max(pc + x, 0.5 + 1e-6), 1 - 1e-6)) for x in (sp, -sp)]
        sig = dv / z
        ref, lo, hi = SIG_REF[cls]
        agree = band[0] <= hi * 1.1 and band[1] >= lo * 0.9
        check(f"comparator noise {cls}", agree,
              f"sigma (M, {tot} decisions at {dv * 1e3:.2f} mV, P = {pc:.3f}) {sig * 1e3:.3f} mV, band "
              f"{band[0] * 1e3:.3f}-{band[1] * 1e3:.3f} vs COMPARATOR_ALT {ref * 1e3:.3f} ({lo * 1e3:.3f}-{hi * 1e3:.3f}) mV (M)")
        out[cls] = dict(sigma=sig, band=band, p=pc, n=tot)
    return out


def sim_conv():
    """(4) full conversions: one column's bank pair preset to known V+/V-, converted by the transistor converter
    (bank C-DAC, bpd2, comparators, refbuf VCM, Verilog-A SAR logic); codes against the ideal-cap law."""
    build_all(rows=2, cols=ADC_SHARE, ntiles=1)
    AS = ADC_SHARE
    vins = [(0.30, 0.10), (0.12, 0.27), (0.05, 0.05), (0.62, 0.02), (0.02, 0.45), (0.35, 0.30), (0.20, 0.21),
            (0.08, 0.58)]
    T_conv = 13 * TICK * 1.3
    lines = ["* imc_tile --sim conversion", lib(), hdl(), f"vdd vdd 0 {VDD}", f"vref vref 0 {VDD}",
             f"vbias vbias 0 {VCM}", "iib vdd ib 20u",
             text(["bsw", "bank", "dtf", "dtq", "sarm", *bpd_names(), "refbuf", "conv"]),
             "Xr vbias vcm ib vdd 0 refbuf", f"Cvcm vcm 0 {C_DEC_VCM:g}", "vtrim trim 0 0"]
    t = 2e-9
    samp, sclk, pre, bank = [], [], [], []
    pvp, pvn = [(0.0, vins[0][0])], [(0.0, vins[0][1])]
    reads = []
    for i, (vp, vn) in enumerate(vins):
        # phi_samp first: it ends the previous round (enables off, bank bottoms back to GND, the state the bank
        # accumulates in), then the preset sets the bank's top plates, then sar_clk starts the conversion
        samp.append((t, t + 0.1e-9))
        pre.append((t + 0.2e-9, t + 0.5e-9))                   # preset switch closed
        pvp += [(t, vp), (t + 0.6e-9, vp)]
        pvn += [(t, vn), (t + 0.6e-9, vn)]
        sclk.append((t + 0.7e-9, t + 0.7e-9 + 6 * TICK))
        reads.append(t + 0.7e-9 + T_conv)
        t += 0.7e-9 + T_conv + 0.3e-9
    bank.append((0, t + 1e-9))                                 # bank 1 accumulating: bank 0 is converted
    pre_pts = [(0.0, 0.0)]                                     # bench preset switch, gate boosted to 1.4 V
    for t0_, t1_ in pre:
        pre_pts += [(t0_, 0.0), (t0_ + 15e-12, 1.4), (t1_, 1.4), (t1_ + 15e-12, 0.0)]
    lines += [pwl("vp", pvp), pwl("vn", pvn), pwl("pre", pre_pts), logic("samp", samp), logic("sclk", sclk),
              logic("bank", bank)]
    # one column, bank 0 (+/-): the banks' share/merge/reset idle; the preset NMOS sets the DAC nodes
    for sd, src in (("p", "vp"), ("n", "vn")):
        lines.append(f"Xb{sd} 0 0 0 0 0 e0_0 " + " ".join(f"d{sd}{k}" for k in range(N_STEP)) + f" a00{sd} vdd 0 bank")
        lines.append(f"Mpre{sd} a00{sd} pre {src} 0 nmos_lvt L={PDK.min_l}u NFIN=16")
    ins = [f"a00{sd}" if (c, b) == (0, 0) else "0" for c in range(AS) for b in (0, 1) for sd in "pn"]
    ens = [f"e{c}_{b}" for c in range(AS) for b in (0, 1)]
    lines.append("Xc " + " ".join(ins) + " samp sclk bank trim " + " ".join(ens) + " " +
                 " ".join(f"dp{k}" for k in range(N_STEP)) + " " + " ".join(f"dn{k}" for k in range(N_STEP)) +
                 " cv vcm vref vdd 0 conv")
    lines += [".save v(cv) v(a00p) v(a00n) v(vcm) i(vref)", ".options method=gear", f".tran 2p {t:.4e}", ".end", ""]
    res = espice("\n".join(lines), "conv", ["v(cv)", "v(a00p)", "v(a00n)", "v(vcm)", "i(vref)"])
    c_dac = ROWS * 7 * CU_MSB
    lsb = VDD * (c_dac / sum(STEPS)) / c_dac                    # D: ideal caps, no parasitics on the node
    codes = np.array([round(at(res, "v(cv)", tr) * 1e3) for tr in reads])
    vd = np.array([vp - vn for vp, vn in vins])
    ideal = np.clip(np.floor(vd / lsb + 0.5), -2048, 2047)
    A = np.vstack([vd / lsb, np.ones_like(vd)]).T
    (g, o), *_ = np.linalg.lstsq(A, codes, rcond=None)
    resid = codes - (g * vd / lsb + o)
    check("full conversions (transistor bank C-DAC + E-trim converter)",
          0.80 < g < 1.05 and np.sqrt(np.mean(resid ** 2)) <= 4,
          f"codes (M) {codes.tolist()} for V_diff {[round(x, 3) for x in vd]} V; ideal-cap law (D, LSB "
          f"{lsb * 1e6:.1f} uV) {ideal.astype(int).tolist()}; fit gain {g:.4f} (node parasitics), offset {o:.1f} LSB, "
          f"residual rms {np.sqrt(np.mean(resid ** 2)):.2f} LSB (gate 4: 12 b at the 9.63 ENOB target), worst "
          f"{np.max(np.abs(resid)):.2f} LSB; VCM {at(res, 'v(vcm)', reads[-1]):.4f} V; reference charge per conversion "
          f"{np.trapezoid(-res['i(vref)'], res['time']) / len(vins) * 1e15:.1f} fC")
    return dict(codes=codes.tolist(), vdiff=vd.tolist(), gain=g, offset=o, resid_rms=float(np.sqrt(np.mean(resid ** 2))),
                resid_max=float(np.max(np.abs(resid))))


def sim(which, tag=""):
    tests = dict(mac=sim_mac, settle=sim_settle, noise=sim_cmp_noise, conv=sim_conv)
    out = {}
    for k in which or tests:
        out[k + tag] = tests[k]()
    rj = OUT / "spice" / "results.json"
    rj.parent.mkdir(parents=True, exist_ok=True)
    prev = json.loads(rj.read_text()) if rj.exists() else {}
    rj.write_text(json.dumps({**prev, **out}, indent=1, default=float))
    print("ALL SPICE CHECKS PASS" if not FAILS else f"SPICE CHECKS FAILED: {FAILS}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--emit", action="store_true")
    ap.add_argument("--draw", action="store_true")
    ap.add_argument("--sim", nargs="*", help="mac settle noise conv (default: all)")
    ap.add_argument("--fins", default="", help="sizing override, e.g. xp_tg=4,smx=8")
    ap.add_argument("--gc3t", action="store_true", help="unbuffered gain cell (N3_r2 gc3t) on the crosspoint gates")
    ap.add_argument("--tgshare", action="store_true", help="transmission-gate share switch instead of the bootstrap")
    a = ap.parse_args()
    GC_BUF = GC_BUF and not a.gc3t
    SHARE_SW = "tg" if a.tgshare else SHARE_SW
    FINS.update({k: int(v) for k, v in (kv.split("=") for kv in a.fins.split(",") if kv)})
    rc = 0
    if a.emit:
        emit()
    if a.draw:
        draw()
    if a.sim is not None:
        rc = sim(a.sim, ("" if GC_BUF else "_gc3t") + ("_tg" if SHARE_SW == "tg" else "") + (f"_{a.fins}" if a.fins else ""))
    if not (a.emit or a.draw or a.sim is not None):
        build_all()
        print(hdl() + text())
    sys.exit(rc)
