"""Charge-domain capacitive weight tile, programmable — topology + sizing. Prints the bare
.subckt deck.

Ported device for device from AnalogIOC components/weight_tile (generate()), made
reprogrammable per analog/analogioc/docs/INTERFACE.md §7 (D7, D10, D11). A crosspoint is
a differential pair of 4b binary-weighted cap banks, W = C+ - C-: the C+ bank of row i
hangs on the row driver's `outa` line, the C- bank on `outb` (pwm_driver: the four sign
combinations of W*x come from which chop phase the bottom edge lands in). Every bank top
is wired the same: a TG to vcm during phi1 (recharge), a TG to the column rail
(integrator virtual ground) during phi2 (transfer), a top-plate ballast to vss, and a
complementary-clocked S=D=rail dummy pair. Per chop cycle a bank moves code*C_u*VDD onto
its rail with the sign of W*x; 1 MAC code unit = specs.c_u()*VDD.

Weights are runtime state (§7.2). Every bank has all four bit caps; each bit cap's
bottom plate goes through its own selector — a TG to the row line (n gate Q, p gate QB)
and an nfet to vss (gate QB) — driven by a write-only 6T bitcell (`<name>_cell`: two
cross-coupled inverters, two access nfets on BL/BLB, no read port). The top-plate cap is
15 C_u + C_BALL for every code, and the switch sits on the bottom plate, static during
integration. Writes go one row at a time: `wwl<i>` (buffered, one WL per row) latches
`wd<8j+k>` into column j's bit k: k = 0..3 Cp[k], k = 4..7 Cn[k-4] (bitline driver per
wd bit: BL = wd, BLB = !wd, shared by the column's rows). Q = 1 puts that cap on the row.

    build(n_rows, n_cols)  ports xin_p_r<i> xin_n_r<i>.. col<j>.. wwl<i>.. wd<k>.. phi1 phi1e
                           phi2 vcm vdd vss — analogioc instantiates build(16, 17) and
                           wires w_wl/w_data straight through (§7.5).
    build()                the canonical deck (netlist/weight_tile.spice, layout, DUT=sch):
                           one crosspoint, R = C = 1.
    row_word(cp, cn)       the wd bits of one row: cp/cn the per-column codes.
    --no-caps              the same deck without MIM caps, for Philis (several MIM caps
                           hang its feedback extraction; pex.py re-adds them).

Sizing (spec: analog/weight_tile/docs/architecture.md). Switches, logic and a latch, no
gm/ID coordinate — every FET is driven rail to rail:
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
  gate    per bank, code-zero clock gate on the transfer switch: en = NAND4(QB) (code
          != 0), st = phi2_i & en (NAND2 + inverter), stb = !st one inverter later; st/stb
          drive the transfer TG and its dummies. The n gate must lead the p gate as
          phi2_i -> phi2_b_i did (the reverse order: null -4 LSB, 32:32 column -13 LSB),
          and the injection balance wants fast local edges: st/stb inverters at ST_DRIVE x
          logic, measured on the 32:32 column 1x -2.74, 2x -1.77, 4x -1.14 LSB (old shared
          drive, fixed-code tile: -0.05). A static enable TG in series with st instead
          (shared drive kept) measured null +2.0 LSB, 32:32 +4.9 LSB. The local drive
          also makes every bank's edges the same in a 1-column test tile and in the full
          16 x 17 tile. Without the gate every bank of a column (32) dumps
          its top onto the column each phi2 whatever its code: 32 x (15 C_u + C_BALL) of
          switched capacitance that returns the OTA's virtual-ground residual to vcm every
          cycle — measured a lone W = 13 bank reading 63 % of its charge. sv stays clocked
          (an idle top only ever sees vcm and its grounded bit caps).
  sel     bottom-plate selector TG + pull-down: min W/L. Its R_on into <= 8 C_u is a
          ps-scale time constant; anything larger only adds row-line drain load
          (specs.c_row(), t_q_floor) and Q/QB gate load.
  cell    write-only 6T. No read, so no beta ratio: pull-down and access nfets at min W/L
          (least leakage, least BL/WL load). Writeability is the pull-up ratio: the
          access nfet must drag Q below the other inverter's trip point against the
          pull-up pfet. The pfet is min W and its L steps in min_l units from 2 min_l
          (INTERFACE §7.2) until the worst write margin over every corner x TEMPS clears
          wm_min(): Pelgrom sigmas of the access + pull-up Vth mismatch, as many as the
          tile write yield YIELD over all 8*N_ROWS*N_COLS bits needs. Write margin = the
          BL level at which a cell holding 1 flips with WL = BLB = VDD (BL ramped down),
          measured on the PDK's own models (char/<pdk>.json). A longer pull-up L also
          cuts the pfet's leakage.
  wlbuf   per row: inv (logic) -> inv (drive). Drive: 10-90 % edge inside WRITE_EDGE
          into the row's 2*8*N_COLS access gates + the row wire; floored at logic.
  bldrv   per wd bit: inv -> BLB, inv -> BL, both drive stages: the same edge into
          N_ROWS access drains (pdk.cd_n_ff_um) + the column wire.
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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from statistics import NormalDist

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

N_BITS = specs.W_BITS
CODE_MAX = 2 ** N_BITS - 1
CELL_BITS = 2 * N_BITS   # w_data bits per crosspoint: Cp[3:0], Cn[3:0] (INTERFACE §7.1)
# Chop grid (AnalogIOC _conv_common, sim grid): phi1 falls at t0+2.1 ns, phi2 rises at
# t0+2.5 ns. The buffered tile clocks must finish an edge inside half that gap.
PHI_GAP = 0.4e-9
PHI_EDGE = PHI_GAP / 2
PHI1_W = 1.6e-9          # phi1 high time: the vcm recharge window
EDGE_SWING = 0.8         # 10-90 %
VFLY_MIN_FRAC = 0.25     # a floating top stays above VCM/4 (clear of the body diode)
Q_BURST_UNITS = 34       # real worst same-sign units per chop cycle (A5's 11 passes)
LIN_ERR = 0.005          # pair transfer nonlinearity allowed at the rail bounce
# Weight write (INTERFACE §7.3): WL high -> bit stored inside T_WRITE_CELL at the worst
# corner; the WL/BL drivers get a quarter of it for their edge, the cell the rest.
T_WRITE_CELL = 2e-9
WRITE_EDGE = T_WRITE_CELL / 4
YIELD = 0.999            # tile write yield: all 8*N_ROWS*N_COLS bits writeable
TEMPS = (-40, 27, 125)
ST_DRIVE = 4.0           # per-bank st/stb inverters, in logic sizes (measured, see gate)
L_PU_MIN, L_PU_MAX = 2, 8          # pull-up L search, in min_l units
WM_RAMP = (1e-9, 100e-9)           # BL ramp start, duration (quasi-static vs the cell)
CHAR = Path(__file__).resolve().parent / "char"


def _cached(pdk, section, key, measure):
    """char/<pdk>.json[section], re-measured when its key changes."""
    path = CHAR / f"{pdk.name}.json"
    got = json.loads(path.read_text()) if path.exists() else {}
    if got.get(section, {}).get("key") != key:
        got[section] = dict(measure(), key=key)
        CHAR.mkdir(exist_ok=True)
        path.write_text(json.dumps(got, indent=1) + "\n")
    return got[section]


def _char(pdk):
    """{cg_n, cg_p}: gate capacitance [fF per um of W] at L = min, channel on, measured
    on the PDK's own models."""
    def measure():
        w, L = 10.0, pdk.min_l
        lines = [f"* weight_tile char {pdk.name}", pdk.lib_line(pdk.typical)]
        lines += [pdk.fet_card.format(name="gn", d="0", g="gn", s="0", b="0", model=pdk.nfet,
                                      w=pdk.um(w), l=pdk.um(L), extra=""),
                  f"Vgn gn 0 DC {pdk.vdd} AC 1", f"Vhi hi 0 {pdk.vdd}",
                  pdk.fet_card.format(name="gp", d="hi", g="gp", s="hi", b="hi",
                                      model=pdk.pfet, w=pdk.um(w), l=pdk.um(L), extra=""),
                  "Vgp gp 0 DC 0 AC 1", ".control", "ac lin 1 1meg 1meg"]
        lines += [f"let {n} = abs(i({v}))/(2*3.14159265*1e6)\nprint {n}"
                  for n, v in (("cgn", "Vgn"), ("cgp", "Vgp"))]
        r = ngspice(lines + [".endc"])
        return {"cg_n": r["cgn"] * 1e15 / w, "cg_p": r["cgp"] * 1e15 / w}
    return _cached(pdk, "gate", {"variant": pdk.variant, "min_l": pdk.min_l, "vdd": pdk.vdd},
                   measure)


def cell(name="weight_tile_cell", l_pu=None, pdk=None):
    """Write-only 6T bitcell: `.subckt <name> q qb wl bl blb vdd vss`."""
    pdk = pdk or get_pdk()
    w, L = pdk.min_w, pdk.min_l
    l_pu = l_pu or cell_sizes(pdk)["pu"][1]
    s = ps.Subcircuit(name, ["q", "qb", "wl", "bl", "blb", "vdd", "vss"])
    for out, inp in (("q", "qb"), ("qb", "q")):
        fet(s, f"pd_{out}", out, inp, "vss", "vss", "nfet", w, L, pdk=pdk)
        fet(s, f"pu_{out}", out, inp, "vdd", "vdd", "pfet", w, l_pu, pdk=pdk)
    fet(s, "ax_q", "bl", "wl", "q", "vss", "nfet", w, L, pdk=pdk)
    fet(s, "ax_qb", "blb", "wl", "qb", "vss", "nfet", w, L, pdk=pdk)
    return s


def _write_margin(pdk, corner, temp, ks):
    """Write margin [V] per pull-up L = k*min_l on one corner/temperature (None: the
    cell never flips, even at BL = 0)."""
    vdd, (t0, tr) = pdk.vdd, WM_RAMP
    lines = [f"* weight_tile write margin {corner} {temp}C", pdk.lib_line(corner),
             f".temp {temp}", f"Vdd vdd 0 {vdd}",
             f"Vbl bl 0 PWL(0 {vdd} {t0} {vdd} {t0 + tr} 0)"]
    for k in ks:
        lines += deck(cell(f"c{k}", round(k * pdk.min_l, 3), pdk)).splitlines()
        lines += [f"Xc{k} q{k} qb{k} vdd bl vdd vdd 0 c{k}"]
    lines += [".ic " + " ".join(f"v(q{k})={vdd} v(qb{k})=0" for k in ks),
              ".control", f"tran {tr / 2e4} {t0 + tr}"]
    for k in ks:
        lines += [f"meas tran t{k} WHEN v(q{k})={vdd / 2} FALL=1",
                  f"let wm{k} = {vdd}*(1-(t{k}-{t0})/{tr})", f"print wm{k}"]
    r = ngspice(lines + [".endc"])
    return [r.get(f"wm{k}") for k in ks]


def write_margins(pdk=None):
    """{"k": [...], "wm": {"<corner>@<temp>": [...]}} — write margin per pull-up L on
    every corner x TEMPS, measured once per PDK and cached."""
    pdk = pdk or get_pdk()
    ks = list(range(L_PU_MIN, L_PU_MAX + 1))

    def measure():
        runs = [(c, t) for c in pdk.corners for t in TEMPS]
        with ThreadPoolExecutor(len(runs)) as ex:
            res = list(ex.map(lambda ct: _write_margin(pdk, *ct, ks), runs))
        return {"k": ks, "wm": {f"{c}@{t}": r for (c, t), r in zip(runs, res)}}
    key = {"variant": pdk.variant, "min_l": pdk.min_l, "min_w": pdk.min_w, "vdd": pdk.vdd,
           "ks": ks, "corners": list(pdk.corners), "temps": list(TEMPS),
           "ramp": list(WM_RAMP)}
    return _cached(pdk, "write_margin", key, measure)


def wm_min(l_pu, pdk=None):
    """Write-margin floor [V]: z Pelgrom sigmas of the access nfet + pull-up pfet Vth
    mismatch (pdk.a_vt is the pair coefficient: one device sigma = a_vt/sqrt(2WL)),
    z such that every one of the tile's bits writes with probability YIELD."""
    pdk = pdk or get_pdk()
    n_bits = CELL_BITS * specs.N_ROWS * specs.N_COLS
    z = NormalDist().inv_cdf(1 - (1 - YIELD) / n_bits)
    w, L = pdk.min_w, pdk.min_l
    return z * pdk.a_vt * 1e-3 * math.sqrt(1 / (2 * w * L) + 1 / (2 * w * l_pu))


def cell_sizes(pdk=None):
    """{"pd"/"ax"/"pu": (W, L), "wm": worst-corner write margin, "wm_min": its floor}."""
    pdk = pdk or get_pdk()
    w, L = pdk.min_w, pdk.min_l
    m = write_margins(pdk)
    for i, k in enumerate(m["k"]):
        l_pu = round(k * L, 3)
        worst = min((r[i] if r[i] is not None else -pdk.vdd) for r in m["wm"].values())
        if worst >= wm_min(l_pu, pdk):
            return {"pd": (w, L), "ax": (w, L), "pu": (w, l_pu), "wm": worst,
                    "wm_min": wm_min(l_pu, pdk)}
    raise ValueError(f"{pdk.name}: no pull-up L up to {L_PU_MAX} min_l meets the write "
                     "margin: widen the search or the access device")


def sizes(pdk=None):
    """{"tg"/"dummy"/"sel": (W, L), "taper"/"drive"/"wl_logic"/"wl_drive"/"bl_drive":
    (Wn, Wp), "cell": cell_sizes(), "L": L, caps and line loads [F]}."""
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
    # write drivers: a WL carries 2 access gates per bit of its row, a BL one access
    # drain per row; each line also runs XP_PITCH wire pitches per crosspoint.
    cs = cell_sizes(pdk)
    w_ax = cs["ax"][0]
    xp = specs.XP_PITCH * pdk.wire_pitch * specs.C_WIRE
    c_wl = specs.N_COLS * (2 * CELL_BITS * ch["cg_n"] * w_ax * 1e-15 + xp)
    c_bl = specs.N_ROWS * (pdk.cd_n_ff_um * w_ax * 1e-15 + xp)

    def driver(c):
        i = EDGE_SWING * vdd * c / WRITE_EDGE
        return tuple(round(max(a, b), 2) for a, b in zip(logic, (i / jn, i / jp)))
    return {"L": L, "tg": (w_tg, L), "dummy": (w_dum, L), "sel": (pdk.min_w, L),
            "taper": tuple(round(math.sqrt(a * b), 2) for a, b in zip(logic, drive)),
            "drive": tuple(round(w, 2) for w in drive),
            "logic": tuple(round(w, 2) for w in logic),
            "st_drive": tuple(round(ST_DRIVE * w, 2) for w in logic),
            "wl_logic": tuple(round(w, 2) for w in logic), "wl_drive": driver(c_wl),
            "bl_drive": driver(c_bl), "cell": cs, "c_wl": c_wl, "c_bl": c_bl,
            "c_u": c_u, "c_ball": c_ball, "c_rail": c_rail}


def ports(n_rows, n_cols):
    """INTERFACE §7.5 order: xin_p/n_r<i> col<j> wwl<i> wd<k> phi1 phi1e phi2 vcm vdd vss."""
    return ([p for i in range(n_rows) for p in (f"xin_p_r{i}", f"xin_n_r{i}")]
            + [f"col{j}" for j in range(n_cols)] + [f"wwl{i}" for i in range(n_rows)]
            + [f"wd{k}" for k in range(CELL_BITS * n_cols)]
            + ["phi1", "phi1e", "phi2", "vcm", "vdd", "vss"])


def row_word(cp, cn):
    """wd bits (list, wd0 first) of one row: column j's Cp at [8j+3:8j], Cn at
    [8j+7:8j+4] (w_data format, INTERFACE §7.1)."""
    return [(c >> b) & 1 for p, n in zip(cp, cn) for c in (int(p), int(n))
            for b in range(N_BITS)]


def tg(name="weight_tile", pdk=None):
    """The tile's own top-plate TG (a parametrised cmos_switch)."""
    pdk = pdk or get_pdk()
    (w, L) = sizes(pdk)["tg"]
    return cmos_switch.build(f"{name}_tg", w_n=w, l_n=L, w_p=w, l_p=L, pdk=pdk)


def bit(name="weight_tile", pdk=None):
    """One programmable bit: `.subckt <name>_bit bot row wl bl blb qb vdd vss` — the bit
    cap's bottom-plate selector (TG to row, pull-down to vss) on its 6T cell; qb out
    for the bank's code-zero gate."""
    pdk = pdk or get_pdk()
    w, L = sizes(pdk)["sel"]
    s = ps.Subcircuit(f"{name}_bit", ["bot", "row", "wl", "bl", "blb", "qb", "vdd", "vss"])
    s.X("c", f"{name}_cell", "q", "qb", "wl", "bl", "blb", "vdd", "vss")
    fet(s, "sn", "row", "q", "bot", "vss", "nfet", w, L, pdk=pdk)
    fet(s, "sp", "row", "qb", "bot", "vdd", "pfet", w, L, pdk=pdk)
    fet(s, "sg", "bot", "qb", "vss", "vss", "nfet", w, L, pdk=pdk)
    return s


def build(n_rows=1, n_cols=1, name="weight_tile", caps=True, pdk=None):
    """The tile Subcircuit (children: pwm_driver.build(), tg(name), cell(), bit(name))."""
    pdk = pdk or get_pdk()
    sz = sizes(pdk)
    s = ps.Subcircuit(name, ports(n_rows, n_cols))
    sw = f"{name}_tg"

    def inv(tag, out, inp, wn_wp):
        fet(s, f"{tag}n", out, inp, "vss", "vss", "nfet", wn_wp[0], sz["L"], pdk=pdk)
        fet(s, f"{tag}p", out, inp, "vdd", "vdd", "pfet", wn_wp[1], sz["L"], pdk=pdk)

    def nand(tag, out, ins):
        """Logic-size NAND: parallel pfets, series nfets."""
        wn, wp = sz["logic"]
        nodes = [out] + [f"{tag}_m{k}" for k in range(len(ins) - 1)] + ["vss"]
        for k, a in enumerate(ins):
            fet(s, f"{tag}p{k}", out, a, "vdd", "vdd", "pfet", wp, sz["L"], pdk=pdk)
            fet(s, f"{tag}n{k}", nodes[k], a, nodes[k + 1], "vss", "nfet", wn, sz["L"], pdk=pdk)

    def phi_buf(src, dst):
        """Buffered true/complement pair: dst_i, dst_b_i."""
        for tag, out, inp, stage in (("i1", f"{dst}_n1", src, "taper"),
                                     ("i2", f"{dst}_i", f"{dst}_n1", "drive"),
                                     ("i3", f"{dst}_b_i", f"{dst}_i", "drive")):
            inv(f"{name}_{dst}_{tag}", out, inp, sz[stage])

    phi_buf("phi1", "phi1")
    phi_buf("phi2", "phi2")
    for i in range(n_rows):
        s.X(f"drv{i}", "pwm_driver", f"xin_p_r{i}", f"xin_n_r{i}", "phi1", "phi1e",
            f"rowa{i}", f"rowb{i}", "vdd", "vss")
        inv(f"wl{i}_i1", f"wlb{i}", f"wwl{i}", sz["wl_logic"])
        inv(f"wl{i}_i2", f"wl{i}", f"wlb{i}", sz["wl_drive"])
    for k in range(CELL_BITS * n_cols):
        inv(f"bl{k}_i1", f"blb{k}", f"wd{k}", sz["bl_drive"])
        inv(f"bl{k}_i2", f"bl{k}", f"blb{k}", sz["bl_drive"])

    for j in range(n_cols):
        if caps:
            mim_cap(s, f"rail{j}", f"col{j}", "vss", sz["c_rail"], pdk=pdk)
        for i in range(n_rows):
            for pol, row, k0 in (("p", f"rowa{i}", CELL_BITS * j),
                                 ("n", f"rowb{i}", CELL_BITS * j + N_BITS)):
                tag, top = f"{pol}{i}_{j}", f"t{pol}{i}_{j}"
                for b in range(N_BITS):
                    if caps:
                        mim_cap(s, f"{tag}_b{b}", top, f"{tag}_bot{b}",
                                sz["c_u"] * (1 << b), pdk=pdk)
                    s.X(f"bit{tag}_{b}", f"{name}_bit", f"{tag}_bot{b}", row, f"wl{i}",
                        f"bl{k0 + b}", f"blb{k0 + b}", f"{tag}_qb{b}", "vdd", "vss")
                if caps:
                    mim_cap(s, f"ball{tag}", top, "vss", sz["c_ball"], pdk=pdk)
                # code-zero gate: a bank whose code is 0 never connects to its column
                # (AnalogIOC emitted no such bank). en = code != 0 = NAND(qb0..qb3);
                # st = phi2_i & en (NAND2 + inverter), stb = !st one inverter later —
                # the n gate leads the p gate as phi2_i -> phi2_b_i did.
                nand(f"en{tag}", f"{tag}_en", [f"{tag}_qb{b}" for b in range(N_BITS)])
                nand(f"g{tag}", f"{tag}_g", ["phi2_i", f"{tag}_en"])
                inv(f"gi{tag}", f"{tag}_st", f"{tag}_g", sz["st_drive"])
                inv(f"gb{tag}", f"{tag}_stb", f"{tag}_st", sz["st_drive"])
                s.X(f"sv{tag}", sw, top, "vcm", "phi1_i", "phi1_b_i", "vdd", "vss")
                s.X(f"st{tag}", sw, top, f"col{j}", f"{tag}_st", f"{tag}_stb", "vdd", "vss")
                fet(s, f"dun{tag}", f"col{j}", f"{tag}_stb", f"col{j}", "vss", "nfet",
                    *sz["dummy"], pdk=pdk)
                fet(s, f"dup{tag}", f"col{j}", f"{tag}_st", f"col{j}", "vdd", "pfet",
                    *sz["dummy"], pdk=pdk)
    return s


def text(n_rows=1, n_cols=1, name="weight_tile", caps=True, pdk=None):
    """Bare deck: children first (pwm_driver, TG, cell, bit), the tile last."""
    pdk = pdk or get_pdk()
    return deck(pwm_driver.build(pdk=pdk), tg(name, pdk), cell(f"{name}_cell", pdk=pdk),
                bit(name, pdk), build(n_rows, n_cols, name, caps, pdk))


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
