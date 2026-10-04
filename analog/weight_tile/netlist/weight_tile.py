"""Charge-domain capacitive weight tile — topology + sizing. Prints the bare .subckt deck.

Ported device for device from AnalogIOC components/weight_tile (generate()). A crosspoint
is a differential pair of 4b binary-weighted cap banks, W = C+ - C-: the C+ bank of row
i hangs on the row driver's `outa` line, the C- bank on `outb` (pwm_driver: the four
sign combinations of W*x come from which chop phase the bottom edge lands in). Every
bank top is wired the same: a TG to vcm during phi1 (recharge), a TG to the column rail
(integrator virtual ground) during phi2 (transfer), a top-plate ballast to vss, and a
complementary-clocked S=D=rail dummy pair. Per chop cycle a bank moves code*C_u*VDD onto
its rail with the sign of W*x; 1 MAC code unit = specs.c_u()*VDD. Weight codes are
compile-time constants (A5's caps.spice, read_caps()): a zero bit has no capacitor.

    build(Cp, Cn, chk)   AnalogIOC generate(): Cp/Cn (n_cols, n_rows) ints 0..15, chk the
                         signed checksum column. Ports xin_p_r{i} xin_n_r{i}.. col{j}..
                         phi1 phi1e phi2 vcm vdd vss.
    build()              the canonical deck (netlist/weight_tile.spice, layout, DUT=sch):
                         one crosspoint, both banks at code 15 — every device a
                         crosspoint can own. Testbenches program other codes by leaving
                         bit caps out (test/tile.py).
    --no-caps            the same deck without MIM caps, for Philis (several MIM caps
                         hang its feedback extraction; pex.py re-adds them).

Sizing (spec: analog/weight_tile/docs/architecture.md). Switches and logic, no gm/ID
coordinate — every FET is driven rail to rail:
  tg      top-plate TGs. R_on budget: the vcm clamp recharges the largest bank
          (15 C_u + C_BALL) to B_Y bits inside the phi1 window. Square-law triode at the
          vcm level with W_p = W_n: equal widths balance the n/p channel injection at a
          mid-rail top plate (AnalogIOC's reason). Floored at min_w. AnalogIOC 0.42/0.42.
  dummy   S=D=rail half-charge dummies: W = W_tg/2 (a dummy absorbs half the channel
          charge of the switch it mirrors), floored at min_w. AnalogIOC 0.42/0.15 both.
  phibuf  phi1/phi2 true/complement buffers (inv -> inv -> inv). The last two stages each
          drive a full tile's worth of switch gates: 10-90 % edge inside PHI_EDGE on
          N_ROWS*N_COLS*2 banks' gate load, on-current density from pwm_driver.j_on,
          gate capacitance measured on the PDK (char/<pdk>.json). First stage: geometric
          mean of logic (min_w, P for equal current) and drive — equal fanout. Its delay
          is a race: the vcm clamp must open (phi1_i falls) before the pwm_driver's
          N-style bottom edge (outb rises off phi1's fall); a min-size first stage into
          the drive stage lost ~40 % of every N-style transfer to vcm (null +31 LSB).
          AnalogIOC 0.42/0.84, 4/8, 4/8.
  C_u     specs.c_u() (swing law). C_BALL: a floating top must not fly past VFLY_MIN
          when a code-15 bottom plate steps by VDD. C_RAIL: the real worst same-sign
          burst Q_BURST must bounce the rail less than the OTA input pair's 0.5 %
          linear range. AnalogIOC 4 fF / 500 fF.
Every cap goes through devices.mim_cap (area + perimeter). C_u, its binary bits and
C_BALL sit below sky130's MIM minimum: exact in simulation, warned about, and a
MOM/fringe cap in silicon (AnalogIOC used ideal C).
"""
import json
import math
import sys
from pathlib import Path

A = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(A / "docs"), str(A / "common"), str(A / "cmos_switch" / "netlist"),
                str(A / "pwm_driver" / "netlist")]
import cmos_switch  # noqa: E402
import pwm_driver  # noqa: E402
import specs  # noqa: E402
from devices import deck, fet, mim_cap  # noqa: E402
from pdk_char import ngspice  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402

import spicerack as ps  # noqa: E402

N_BITS = 4
CODE_MAX = 2 ** N_BITS - 1
# Chop grid (AnalogIOC _conv_common, sim grid): phi1 falls at t0+2.1 ns, phi2 rises at
# t0+2.5 ns. The buffered tile clocks must finish an edge inside half that gap.
PHI_GAP = 0.4e-9
PHI_EDGE = PHI_GAP / 2
PHI1_W = 1.6e-9          # phi1 high time: the vcm recharge window
EDGE_SWING = 0.8         # 10-90 %
VFLY_MIN_FRAC = 0.25     # a floating top stays above VCM/4 (clear of the body diode)
Q_BURST_UNITS = 34       # real worst same-sign units per chop cycle (A5's 11 passes)
LIN_ERR = 0.005          # pair transfer nonlinearity allowed at the rail bounce
CHAR = Path(__file__).resolve().parent / "char"


def _char(pdk):
    """{cg_n, cg_p}: gate capacitance [fF per um of W] at L = min, channel on, measured
    on the PDK's own models; cached in char/<pdk>.json."""
    path = CHAR / f"{pdk.name}.json"
    key = {"variant": pdk.variant, "min_l": pdk.min_l, "vdd": pdk.vdd}
    if path.exists():
        got = json.loads(path.read_text())
        if got["key"] == key:
            return got
    w, L = 10.0, pdk.min_l
    lines = [f"* weight_tile char {pdk.name}", pdk.lib_line(pdk.typical)]
    lines += [pdk.fet_card.format(name="gn", d="0", g="gn", s="0", b="0", model=pdk.nfet,
                                  w=pdk.um(w), l=pdk.um(L), extra=""),
              f"Vgn gn 0 DC {pdk.vdd} AC 1", f"Vhi hi 0 {pdk.vdd}",
              pdk.fet_card.format(name="gp", d="hi", g="gp", s="hi", b="hi", model=pdk.pfet,
                                  w=pdk.um(w), l=pdk.um(L), extra=""),
              "Vgp gp 0 DC 0 AC 1", ".control", "ac lin 1 1meg 1meg"]
    lines += [f"let {n} = abs(i({v}))/(2*3.14159265*1e6)\nprint {n}"
              for n, v in (("cgn", "Vgn"), ("cgp", "Vgp"))]
    r = ngspice(lines + [".endc"])
    got = {"key": key, "cg_n": r["cgn"] * 1e15 / w, "cg_p": r["cgp"] * 1e15 / w}
    CHAR.mkdir(exist_ok=True)
    path.write_text(json.dumps(got, indent=1) + "\n")
    return got


def sizes(pdk=None):
    """{"tg": (W, L), "dummy": (W, L), "taper"/"drive": (Wn, Wp), "L": L, caps [F]}."""
    pdk = pdk or get_pdk()
    L, vdd = pdk.min_l, pdk.vdd
    vcm = specs.VCM_FRAC * vdd
    c_u = specs.c_u(pdk)
    # C_BALL: top at vcm, bottom steps VDD with the top floating (+ ballast):
    #   vcm - VDD * C15/(C15 + Cb) >= VFLY_MIN_FRAC*vcm
    c15 = CODE_MAX * c_u
    c_ball = c15 * (vdd / ((1 - VFLY_MIN_FRAC) * vcm) - 1)
    # C_RAIL: pair output ~ tanh(v/(2/(gm/ID))) is LIN_ERR-linear for x^2/3 < LIN_ERR.
    gmid_in = specs.OTA_COORDS["ota_in"][0]
    v_bounce = math.sqrt(3 * LIN_ERR) * 2 / gmid_in
    c_rail = Q_BURST_UNITS * c_u * vdd / v_bounce
    # TG: recharge c15 + c_ball to B_Y bits in PHI1_W, W_p = W_n, square law at vcm.
    r_on = PHI1_W / ((specs.B_Y + 1) * math.log(2) * (c15 + c_ball))
    g_per_w = 1e-6 * (pdk.un_cox * (vdd - vcm - pdk.vth_n) + pdk.up_cox * (vcm - pdk.vth_p)) / L
    w_tg = max(pdk.min_w, round(1 / (r_on * g_per_w), 2))
    w_dum = max(pdk.min_w, round(w_tg / 2, 2))
    # phi buffers: each line carries one n + one p gate per bank (TG + dummy).
    ch = _char(pdk)
    n_banks = 2 * specs.N_ROWS * specs.N_COLS
    c_line = n_banks * (ch["cg_n"] * w_tg + ch["cg_p"] * max(w_tg, w_dum)) * 1e-15
    i_on = EDGE_SWING * vdd * c_line / PHI_EDGE
    jn, jp = pwm_driver.j_on("nfet", pdk), pwm_driver.j_on("pfet", pdk)
    logic, drive = (pdk.min_w, pdk.min_w * jn / jp), (i_on / jn, i_on / jp)
    return {"L": L, "tg": (w_tg, L), "dummy": (w_dum, L),
            "taper": tuple(round(math.sqrt(a * b), 2) for a, b in zip(logic, drive)),
            "drive": tuple(round(w, 2) for w in drive),
            "c_u": c_u, "c_ball": c_ball, "c_rail": c_rail}


def ports(n_rows, n_cols):
    return ([p for i in range(n_rows) for p in (f"xin_p_r{i}", f"xin_n_r{i}")]
            + [f"col{j}" for j in range(n_cols)] + ["phi1", "phi1e", "phi2", "vcm", "vdd", "vss"])


def tg(name="weight_tile", pdk=None):
    """The tile's own top-plate TG (a parametrised cmos_switch)."""
    pdk = pdk or get_pdk()
    (w, L) = sizes(pdk)["tg"]
    return cmos_switch.build(f"{name}_tg", w_n=w, l_n=L, w_p=w, l_p=L, pdk=pdk)


def build(Cp=None, Cn=None, chk=None, name="weight_tile", caps=True, pdk=None):
    """The tile Subcircuit (children: pwm_driver.build(), tg(name)). Cp/Cn (n_cols,
    n_rows) codes; default one crosspoint with both banks at code 15."""
    pdk = pdk or get_pdk()
    Cp = [[CODE_MAX]] if Cp is None else [[int(v) for v in r] for r in Cp]
    Cn = [[CODE_MAX]] if Cn is None else [[int(v) for v in r] for r in Cn]
    n_cols, n_rows = len(Cp), len(Cp[0])
    assert (len(Cn), len(Cn[0])) == (n_cols, n_rows)
    cols = list(range(n_cols)) + ([n_cols] if chk is not None else [])
    sz = sizes(pdk)
    s = ps.Subcircuit(name, ports(n_rows, len(cols)))
    sw = f"{name}_tg"

    def phi_buf(src, dst):
        """Buffered true/complement pair: dst_i, dst_b_i."""
        for tag, out, inp, stage in (("i1", f"{dst}_n1", src, "taper"),
                                     ("i2", f"{dst}_i", f"{dst}_n1", "drive"),
                                     ("i3", f"{dst}_b_i", f"{dst}_i", "drive")):
            wn, wp = sz[stage]
            fet(s, f"{name}_{dst}_{tag}n", out, inp, "vss", "vss", "nfet", wn, sz["L"], pdk=pdk)
            fet(s, f"{name}_{dst}_{tag}p", out, inp, "vdd", "vdd", "pfet", wp, sz["L"], pdk=pdk)

    phi_buf("phi1", "phi1")
    phi_buf("phi2", "phi2")
    for i in range(n_rows):
        s.X(f"drv{i}", "pwm_driver", f"xin_p_r{i}", f"xin_n_r{i}", "phi1", "phi1e",
            f"rowa{i}", f"rowb{i}", "vdd", "vss")

    def bank(tag, top, row, code, col):
        for b in range(N_BITS):
            if caps and (code >> b) & 1:
                mim_cap(s, f"{tag}_b{b}", top, row, sz["c_u"] * (1 << b), pdk=pdk)
        if caps:
            mim_cap(s, f"ball{tag}", top, "vss", sz["c_ball"], pdk=pdk)
        s.X(f"sv{tag}", sw, top, "vcm", "phi1_i", "phi1_b_i", "vdd", "vss")
        s.X(f"st{tag}", sw, top, col, "phi2_i", "phi2_b_i", "vdd", "vss")
        fet(s, f"dun{tag}", col, "phi2_b_i", col, "vss", "nfet", *sz["dummy"], pdk=pdk)
        fet(s, f"dup{tag}", col, "phi2_i", col, "vdd", "pfet", *sz["dummy"], pdk=pdk)

    n_banks = 0
    for j in cols:
        if caps:
            mim_cap(s, f"rail{j}", f"col{j}", "vss", sz["c_rail"], pdk=pdk)
        for i in range(n_rows):
            if j < n_cols:
                cp, cn = Cp[j][i], Cn[j][i]
            else:
                cp, cn = max(int(chk[i]), 0), max(-int(chk[i]), 0)
            for pol, code, row in (("p", cp, f"rowa{i}"), ("n", cn, f"rowb{i}")):
                if code:
                    bank(f"{pol}{i}_{j}", f"t{pol}{i}_{j}", row, code, f"col{j}")
                    n_banks += 1
    s.raw_spice(f"* {n_banks} nonzero banks")
    return s


def text(Cp=None, Cn=None, chk=None, name="weight_tile", caps=True, pdk=None):
    """Bare deck: children first (pwm_driver, TG), the tile last."""
    pdk = pdk or get_pdk()
    return deck(pwm_driver.build(pdk=pdk), tg(name, pdk),
                build(Cp, Cn, chk, name, caps, pdk))


def read_caps(path):
    """A5's caps.spice params -> (Cp, Cn, chk): Cp/Cn (16 cols, 16 rows) in expected.json's
    Wq=(O,I) orientation, chk the signed per-row checksum column (c16). AnalogIOC verbatim."""
    import re
    import numpy as np
    Cp, Cn = np.zeros((16, 16), dtype=int), np.zeros((16, 16), dtype=int)
    chkp, chkn = np.zeros(16, dtype=int), np.zeros(16, dtype=int)
    for pol, r, c, v in re.findall(r"\.param\s+wc([pn])_r(\d+)c(\d+)\s*=\s*(\d+)",
                                   Path(path).read_text()):
        r, c, v = int(r), int(c), int(v)
        if c == 16:
            (chkp if pol == "p" else chkn)[r] = v
        else:
            (Cp if pol == "p" else Cn)[c, r] = v
    return Cp, Cn, chkp - chkn


if __name__ == "__main__":
    print(text(caps="--no-caps" not in sys.argv), end="")
