"""Rank-1 signed LoRA sidecar — topology + sizing. Prints the bare .subckt deck.

Adds  Delta mac_j = rho * B_j * sum_i A_i * s_i * m_i  in charge onto tile column j
(colb<j> tied to its integrator virtual ground), the golden.tile_mvm(lora=...) term,
with signed A, B (sign-magnitude 4b codes) and signed x (x_neg). Ported from AnalogIOC
components/lora_sidecar (unsigned |x|, LO window only) and extended — see
analog/lora_sidecar/docs/architecture.md for why each change was needed.

Every cell is a gain_cell_array 2T cell (write switch + read device, storage = the read
device's own gate) whose source sits at vss: the cells are always on and their drain
current is STEERED, never switched (a switched source on a long read device bootstraps
the floating gate and the cell turns itself off). Unused current goes to the `vcm` dump.

  A row i     Ap_i holds |A_i| if A_i > 0, An_i if A_i < 0 (the other cell holds 0).
              While xen_i: Ap -> colp, An -> coln (x_neg_i swaps them); else -> vcm.
  integrate   two OTA integrators on colp / coln (C_int each): Q_P - Q_N = A.x (signed).
  V -> T      ramp_en: equal ramp currents pull vaxp, vaxn down to vth = vcm - V_PED;
              comparators cp / cn flag each crossing (each ramp stops at its own).
              pos = ramp_en.cn./cp (P holds more), neg = ramp_en.cp./cn; the window lasts
              |Q_P - Q_N| / I_ramp, and the comparator delays cancel (no x=0 baseline).
  B column j  bpd, bpm hold |B_j| if B_j > 0, bnd, bnm if B_j < 0. Direct cells (d) sink
              from colb_j (+), mirror cells (m) feed a PMOS mirror that sources into it (-):
              pos: bpd(+) and bnm(-);  neg: bpm(-) and bnd(+)  =>  sign(B) * sign(A.x).
              The two cells of a window sum on one node, steered as a whole; mirrors carry
              a standing bias (taken back off the output) so they never idle.
  write       per side one write_dac (vref = vcm, the cell write ceiling) driven by the
              magnitude m: code = 8 + m (m > 0) or 0, i.e. b2..b0 = m, b3 = OR(m); the sign
              bit routes the level to the + or - cell bus and grounds the other.

Ports: xen0..15 xneg0..15 colb0..15 wa_sel0..15 wb_sel0..15 da0..3 db0..3
       rst ramp_en vaxp vaxn vcm vb_ramp vb_nc vb_pc vb_tail vdd vss
(d3 / db3 = sign, d0..2 = magnitude; xen/xneg/rst/ramp_en/*_sel are vdd logic.)

Sizing — specs.lora_* laws (full-scale cell current, C_int, ramp current) plus:
  cell read   VGS = V_W (the write ceiling) carries lora_i_cell(); W = I/J_D(V_W, L), L
              stepped in Lmin multiples until W >= min_w and the MEASURED sigma(VGS)
              (docs/mismatch.py) keeps sigma(I)/I <= CELL_SIGMA at full scale.
  cell write  gain_cell_array.write_size() unchanged (its R_on / leakage budgets).
  ramp        PMOS at gm/ID = SRC_GMID (strong inversion: low sensitivity to Vt, Vdsat
              ~ 0.4 V fits the ~0.9 V across it); L stepped until the measured pair
              mismatch meets RAMP_SIGMA (a P/N ramp mismatch d leaks d*Q_common: 0.5 code
              of lora_mac_max at 1 sigma).
  mirror      PMOS at gm/ID = MIRROR_GMID (its diode node is the mirrored cell's drain,
              see MIRROR_GMID) carrying (1 + MB_FRAC) lora_i_cell(), same search against
              MIRROR_SIGMA; its standing bias MB_FRAC lora_i_cell() comes from NMOS on
              vb_tail (L stepped until min_w carries it at the tail's VGS, and MB_SIGMA).
  V_PED       3 sigma of (integrator - comparator) OTA offset: both sides always start
              uncrossed, so an empty side still runs the same pedestal as a full one.
  switches    steering TGs: R_on * I <= V_STEER (drain stays on its virtual ground);
              reset TG: measured R_on(vcm) on every corner, see reset_size().
  logic       min-width N, equal-drive P (write_dac rule) at Lmin: window edges matter.
"""
import json
import math
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

A = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(A / "docs"), str(A / "common")] + [
    str(A / b / "netlist") for b in ("cmos_switch", "gain_cell_array", "write_dac", "ota")]
import cmos_switch  # noqa: E402
import gain_cell_array as gca  # noqa: E402
import gmid  # noqa: E402
import mismatch  # noqa: E402
import ota  # noqa: E402
import specs  # noqa: E402
import write_dac  # noqa: E402
from devices import deck, fet, mim_cap, poly_res  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402

import spicerack as ps  # noqa: E402

N = specs.N_ROWS                 # rank-1 over the 16 tile rows / data columns
PORTS = ([f"xen{i}" for i in range(N)] + [f"xneg{i}" for i in range(N)]
         + [f"colb{j}" for j in range(N)] + [f"wa_sel{i}" for i in range(N)]
         + [f"wb_sel{j}" for j in range(N)] + [f"da{b}" for b in range(4)]
         + [f"db{b}" for b in range(4)]
         + ["rst", "ramp_en", "vaxp", "vaxn", "vcm", "vb_ramp", "vb_nc", "vb_pc",
            "vb_tail", "vdd", "vss"])
CELL_SIGMA = 0.01               # sigma(I)/I of one cell at full scale
MIRROR_SIGMA = 0.02             # sigma of a B mirror's gain (diode vs output)
MB_FRAC = 1 / 8                 # mirror standing bias I_MB / lora_i_cell()
MB_SIGMA = 0.1                  # sigma of the bias pair: its error is MB_FRAC of that
RAMP_SIGMA = 0.5 / specs.lora_mac_max()   # sigma of the P/N ramp ratio (see docstring)
SRC_GMID = 5.0                  # ramp PMOS: strong inversion, Vdsat ~ 0.4 V
MIRROR_GMID = 10.0              # B mirror PMOS: the diode sits VSG below vdd and is the
                                # mirrored cell's drain; at 10 (sky130 VSG 1.21 V, node
                                # 0.59 V) the cell (Vdsat ~ 2/5.4 = 0.37 V) stays saturated
V_STEER = 20e-3                 # max drop across a steering switch
T_RST = 4 * specs.TQ_SIM        # INTERFACE.md section 6.2 I1: integrator reset phase
FANOUT = 4                      # logic stage effort
DIV_I = specs.I_SIDE            # vth divider current (from vcm)
K_LADDER = (1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64, 96, 128, 192)   # L / Lmin steps


def _ladder(pdk):
    return [round(k * pdk.min_l, 3) for k in K_LADDER]


def cell_read_size(pdk=None):
    """(W, L) um of the sidecar cell's read device."""
    pdk = pdk or get_pdk()
    vw, i = cmos_switch.v_write(pdk), specs.lora_i_cell(pdk)
    for L in _ladder(pdk):
        t = gmid.load_table("nfet", L, pdk)
        W = round(i / float(gmid.pchip(t["VGS"], t["ID_per_W"], vw)), 2)
        if W < pdk.min_w:
            continue            # min_w would overshoot the full-scale current
        gm_id = float(gmid.pchip(t["VGS"], t["gm_ID"], vw))
        if gm_id * mismatch.sigma_vgs("nfet", W, L, i, pdk) * 1e-3 <= CELL_SIGMA:
            return W, L
    raise ValueError(f"no read device up to L={_ladder(pdk)[-1]} um meets CELL_SIGMA")


def src_size(i, sigma_pair, gm_id=SRC_GMID, pdk=None):
    """(W, L) um of a PMOS current source at `gm_id` carrying i whose pair mismatch
    sigma(dI/I) = gm/ID * sqrt(2) * sigma(VGS) <= sigma_pair."""
    pdk = pdk or get_pdk()
    for L in _ladder(pdk):
        W = round(i / float(gmid.J_D(gm_id, L, "pfet", pdk)), 2)
        if W < pdk.min_w:
            continue
        # Pelgrom (pdk.a_vt, a pair) under-reads the PDK's mismatch at every geometry
        # measured so far: a size it already fails is not worth 30 mismatch runs
        if gm_id * pdk.a_vt / math.sqrt(W * L) * 1e-3 > sigma_pair:
            continue
        if gm_id * math.sqrt(2) * mismatch.sigma_vgs("pfet", W, L, i, pdk) * 1e-3 \
                <= sigma_pair:
            return W, L
    raise ValueError(f"no PMOS source for {i:.3g} A meets {sigma_pair:.3g}")


def mbias_size(i, pdk=None):
    """(W, L) um of the mirror-bias NMOS: gate on vb_tail (VGS of the OTA tail at its
    gm/ID coordinate), L stepped until W >= min_w carries i, then until the measured
    pair mismatch sigma(dI/I) = gm/ID sqrt(2) sigma(VGS) <= MB_SIGMA."""
    pdk = pdk or get_pdk()
    gm_t, k_t, _ = specs.OTA_COORDS["ota_tail"]
    vgs = float(gmid.VGS(gm_t, specs.ota_L("ota_tail", pdk), "nfet", pdk))
    for L in _ladder(pdk):
        t = gmid.load_table("nfet", L, pdk)
        W = round(i / float(gmid.pchip(t["VGS"], t["ID_per_W"], vgs)), 2)
        if W < pdk.min_w:
            continue
        g = float(gmid.pchip(t["VGS"], t["gm_ID"], vgs))
        if g * pdk.a_vt / math.sqrt(W * L) * 1e-3 > MB_SIGMA:
            continue
        if g * math.sqrt(2) * mismatch.sigma_vgs("nfet", W, L, i, pdk) * 1e-3 <= MB_SIGMA:
            return W, L
    raise ValueError(f"no mirror-bias NMOS for {i:.3g} A")


CHAR = Path(__file__).resolve().parent / "char"


def reset_size(pdk=None):
    """(w_n, w_p) um of the integrator reset TG at Lmin. The reset must take vax from the
    far end of its swing (V_SWING) to within V_PED/2 of vcm in T_RST on every corner x
    temperature: R_on(vcm) <= T_RST / (C_int ln(2 V_SWING / V_PED)). A TG at mid-rail has
    no closed-form R_on (the NMOS is near threshold, the PMOS barely on), so R_on(vcm) is
    measured per width on every corner (cmos_switch's dead-zone bench, cached in
    char/<pdk>.json) and W_n is the narrowest that meets it; W_p = W_n * un/up."""
    pdk = pdk or get_pdk()
    r_max = T_RST / (specs.lora_c_int(pdk) * math.log(2 * specs.V_SWING / v_ped(pdk)))
    widths = [round(pdk.min_w * 2 ** k, 2) for k in range(8)]
    key = {"widths": widths, "corners": list(pdk.corners), "temps": list(cmos_switch.TEMPS),
           "v": cmos_switch.v_write(pdk)}
    path = CHAR / f"{pdk.name}.json"
    got = json.loads(path.read_text()) if path.exists() else {}
    if got.get("key") != key:
        runs = [(c, t) for c in pdk.corners for t in cmos_switch.TEMPS]
        with ThreadPoolExecutor(len(runs)) as ex:
            res = list(ex.map(lambda ct: cmos_switch._r_on_at(pdk, *ct, widths), runs))
        got = {"key": key, "r_on": {f"{c}@{t}": r for (c, t), r in zip(runs, res)}}
        CHAR.mkdir(exist_ok=True)
        path.write_text(json.dumps(got, indent=1) + "\n")
    for k, w in enumerate(widths):
        if max(r[k] for r in got["r_on"].values()) <= r_max:
            return w, round(w * pdk.un_cox / pdk.up_cox, 2)
    raise ValueError(f"no reset TG up to {widths[-1]} um meets {r_max:.3g} ohm")


def v_ped(pdk=None):
    """Comparator pedestal [V]: 3 sigma of the integrator-minus-comparator OTA offset."""
    pdk = pdk or get_pdk()
    w, L = ota.sizes(pdk)["ota_in"]
    return round(3 * math.sqrt(2) * mismatch.pair_offset("nfet", w, L, specs.I_SIDE, pdk)
                 * 1e-3, 3)


def sizes(pdk=None):
    pdk = pdk or get_pdk()
    vcm = specs.VCM_FRAC * pdk.vdd
    vped = v_ped(pdk)
    r_div = vcm / DIV_I
    wn = pdk.min_w
    wp = round(wn * write_dac.j_on("nfet", pdk, pdk.min_l) / write_dac.j_on("pfet", pdk,
                                                                         pdk.min_l), 2)
    i_cell, i_ramp = specs.lora_i_cell(pdk), specs.lora_i_ramp(pdk)
    return {
        "cell": {"write": gca.write_size(pdk), "read": cell_read_size(pdk), "c_store": 0},
        "ramp": src_size(i_ramp, RAMP_SIGMA, SRC_GMID, pdk),
        "mirror": src_size(i_cell * (1 + MB_FRAC), MIRROR_SIGMA, MIRROR_GMID, pdk),
        "mbias": mbias_size(i_cell * MB_FRAC, pdk),
        "sw": cmos_switch.sizes(r_on=V_STEER / i_cell, pdk=pdk),
        "rsw": cmos_switch.sizes(r_on=V_STEER / i_ramp, pdk=pdk),
        "rst": dict(zip(("w_n", "w_p"), reset_size(pdk)), l_n=pdk.min_l, l_p=pdk.min_l),
        "c_int": specs.lora_c_int(pdk),
        "v_ped": vped,
        "r_top": r_div * vped / vcm, "r_bot": r_div * (1 - vped / vcm),
        "logic": (wn, wp, pdk.min_l),
    }


def bias(pdk=None):
    """{port: V}: vb_ramp puts lora_i_ramp() through the ramp PMOS at SRC_GMID. A fixed
    voltage drifts with Vt over PVT; the testbenches drive it from a diode replica of the
    ramp device carrying lora_i_ramp() (the bias contract, like the OTA's)."""
    pdk = pdk or get_pdk()
    L = sizes(pdk)["ramp"][1]
    return {"vb_ramp": round(pdk.vdd - float(gmid.VGS(SRC_GMID, L, "pfet", pdk)), 3)}


# -- static CMOS on a Subcircuit ------------------------------------------------------
class Logic:
    def __init__(self, s, sz, pdk):
        self.s, self.pdk = s, pdk
        self.wn, self.wp, self.L = sz["logic"]

    def _n(self, n, d, g, src, k=1):
        fet(self.s, n, d, g, src, "vss", "nfet", self.wn * k, self.L, pdk=self.pdk)

    def _p(self, n, d, g, src, k=1):
        fet(self.s, n, d, g, src, "vdd", "pfet", self.wp * k, self.L, pdk=self.pdk)

    def inv(self, n, out, a, k=1):
        self._n(f"{n}_n", out, a, "vss", k)
        self._p(f"{n}_p", out, a, "vdd", k)

    def nand(self, n, out, *ins):
        """NAND of 2-3 inputs; N stack widened by its height (equal pull-down)."""
        h = len(ins)
        prev = "vss"
        for k, a in enumerate(ins):
            mid = out if k == h - 1 else f"{n}_m{k}"
            self._n(f"{n}_n{k}", mid, a, prev, h)
            prev = mid
            self._p(f"{n}_p{k}", out, a, "vdd")

    def nor(self, n, out, *ins):
        """NOR of 2-3 inputs; P stack widened by its height."""
        h = len(ins)
        prev = "vdd"
        for k, a in enumerate(ins):
            mid = out if k == h - 1 else f"{n}_m{k}"
            self._p(f"{n}_p{k}", mid, a, prev, h)
            prev = mid
            self._n(f"{n}_n{k}", out, a, "vss")

    def buf_pair(self, n, out, out_b, a_b, load_w):
        """From the weak complement a_b drive out / out_b into `load_w` um of gate width,
        stage effort FANOUT: a_b -> a1 -> out_b (big); a1 -> a2 -> out (big)."""
        big = max(1.0, load_w / (self.wn + self.wp) / FANOUT)
        mid = max(1.0, math.sqrt(big))
        self.inv(f"{n}_1", f"{n}_a1", a_b, mid)
        self.inv(f"{n}_2", f"{n}_a2", f"{n}_a1", mid)
        self.inv(f"{n}_3", out_b, f"{n}_a1", big)
        self.inv(f"{n}_4", out, f"{n}_a2", big)


# -- subcircuits ----------------------------------------------------------------------
def children(name="lora_sidecar", pdk=None):
    """Every child subckt, children first (uniquely named copies, AnalogIOC style)."""
    pdk = pdk or get_pdk()
    sz = sizes(pdk)

    def tg(sub, d):
        return cmos_switch.build(sub, d["w_n"], d["l_n"], d["w_p"], d["l_p"], pdk=pdk)

    subs = [gca.gain_cell_subckt(f"{name}_cell", caps=False, pdk=pdk, sz=sz["cell"]),
            *write_dac.children(f"{name}_dac", pdk), write_dac.build(f"{name}_dac", pdk),
            ota.build(pdk, name=f"{name}_ota"),
            cmos_switch.build(f"{name}_wsw", pdk=pdk),        # write bus (DAC tap role)
            tg(f"{name}_sw", sz["sw"]), tg(f"{name}_rsw", sz["rsw"]),
            tg(f"{name}_rstsw", sz["rst"])]
    return subs + [arow(name, sz, pdk), bcol(name, sz, pdk), wbus(name, sz, pdk),
                   vt(name, sz, pdk)]


def arow(name, sz, pdk):
    """`<name>_arow xen xneg wsel wdp wdn colp coln vcm vdd vss`: A cells of one row."""
    s = ps.Subcircuit(f"{name}_arow", ["xen", "xneg", "wsel", "wdp", "wdn", "colp", "coln",
                                       "vcm", "vdd", "vss"])
    g = Logic(s, sz, pdk)
    g.inv("ixen", "xen_b", "xen")
    g.inv("ixng", "xneg_b", "xneg")
    g.nor("nep", "ep", "xen_b", "xneg")       # straight: xen & !xneg
    g.nor("nen", "en", "xen_b", "xneg_b")     # swapped:  xen & xneg
    g.inv("iep", "ep_b", "ep")
    g.inv("ien", "en_b", "en")
    sw = f"{name}_sw"
    for cell, wd, straight, swapped in (("ap", "wdp", "colp", "coln"),
                                        ("an", "wdn", "coln", "colp")):
        s.X(cell, f"{name}_cell", wd, "wsel", "vss", f"d_{cell}", "vss")
        s.X(f"{cell}_s", sw, f"d_{cell}", straight, "ep", "ep_b", "vdd", "vss")
        s.X(f"{cell}_x", sw, f"d_{cell}", swapped, "en", "en_b", "vdd", "vss")
        s.X(f"{cell}_d", sw, f"d_{cell}", "vcm", "xen_b", "xen", "vdd", "vss")
    return s


def bcol(name, sz, pdk):
    """`<name>_bcol wsel wdp wdn colb pos pos_b neg neg_b vcm vb_tail vdd vss`: B cells
    of one column. Each window has one summing node steered to colb or the vcm dump:
    pos node = bpd (sink, +) + mirrored bnm (source, -); neg node = bnd + mirrored bpm.
    A mirror runs on a standing bias I_MB (an NMOS copy of the OTA tail on vb_tail) that
    a matched NMOS takes back off its output: the diode never idles, so a B write
    settles in ~C/gm(I_MB), not in a slew of the gate on the cell current alone."""
    s = ps.Subcircuit(f"{name}_bcol", ["wsel", "wdp", "wdn", "colb", "pos", "pos_b", "neg",
                                       "neg_b", "vcm", "vb_tail", "vdd", "vss"])
    sw, (wm, lm), (wb, lb) = f"{name}_sw", sz["mirror"], sz["mbias"]
    for win, direct, mirrored, d_bus, m_bus in (("pos", "bpd", "bnm", "wdp", "wdn"),
                                                ("neg", "bnd", "bpm", "wdn", "wdp")):
        node, m = f"n_{win}", f"m_{mirrored}"
        s.X(direct, f"{name}_cell", d_bus, "wsel", "vss", node, "vss")
        s.X(mirrored, f"{name}_cell", m_bus, "wsel", "vss", m, "vss")
        fet(s, f"{mirrored}_md", m, m, "vdd", "vdd", "pfet", wm, lm, pdk=pdk)
        fet(s, f"{mirrored}_mo", node, m, "vdd", "vdd", "pfet", wm, lm, pdk=pdk)
        fet(s, f"{mirrored}_bi", m, "vb_tail", "vss", "vss", "nfet", wb, lb, pdk=pdk)
        fet(s, f"{mirrored}_bo", node, "vb_tail", "vss", "vss", "nfet", wb, lb, pdk=pdk)
        s.X(f"{win}_c", sw, node, "colb", win, f"{win}_b", "vdd", "vss")
        s.X(f"{win}_d", sw, node, "vcm", f"{win}_b", win, "vdd", "vss")
    return s


def wbus(name, sz, pdk):
    """`<name>_wbus d0 d1 d2 d3 wdp wdn vref vdd vss`: write DAC + sign routing."""
    s = ps.Subcircuit(f"{name}_wbus", ["d0", "d1", "d2", "d3", "wdp", "wdn", "vref", "vdd",
                                       "vss"])
    g = Logic(s, sz, pdk)
    g.nor("nor3", "nz_b", "d0", "d1", "d2")
    g.inv("inz", "nz", "nz_b")                # b3 = m != 0  ->  code 8 + m
    g.inv("isg", "d3_b", "d3")
    s.X("dac", f"{name}_dac", "d0", "d1", "d2", "nz", "dac", "vref", "vdd", "vss")
    wsw = f"{name}_wsw"
    s.X("tp", wsw, "dac", "wdp", "d3_b", "d3", "vdd", "vss")
    s.X("tn", wsw, "dac", "wdn", "d3", "d3_b", "vdd", "vss")
    wn = sz["logic"][0]
    fet(s, "gp", "wdp", "d3", "vss", "vss", "nfet", wn, pdk.min_l, pdk=pdk)
    fet(s, "gn", "wdn", "d3_b", "vss", "vss", "nfet", wn, pdk.min_l, pdk=pdk)
    return s


def vt(name, sz, pdk):
    """`<name>_vt colp coln rst ramp_en vaxp vaxn pos pos_b neg neg_b vcm vb_ramp vb_nc
    vb_pc vb_tail vdd vss`: the two A integrators and the signed V->T window."""
    s = ps.Subcircuit(f"{name}_vt", ["colp", "coln", "rst", "ramp_en", "vaxp", "vaxn", "pos",
                                     "pos_b", "neg", "neg_b", "vcm", "vb_ramp", "vb_nc",
                                     "vb_pc", "vb_tail", "vdd", "vss"])
    g = Logic(s, sz, pdk)
    o, bias_ = f"{name}_ota", ("vb_nc", "vb_pc", "vb_tail", "vdd", "vss")
    g.inv("irst", "rst_b", "rst")
    wr, lr = sz["ramp"]
    for k in ("p", "n"):
        col, vax = f"col{k}", f"vax{k}"
        s.X(f"int{k}", o, "vcm", col, vax, *bias_)
        mim_cap(s, f"cint{k}", col, vax, sz["c_int"], pdk=pdk)
        s.X(f"rs{k}", f"{name}_rstsw", col, vax, "rst", "rst_b", "vdd", "vss")
        # comparator: high once vax falls below vth
        s.X(f"cmp{k}", o, "vth", vax, f"co{k}", *bias_)
        g.inv(f"ic1{k}", f"c{k}b", f"co{k}")
        g.inv(f"ic2{k}", f"c{k}", f"c{k}b")
        # ramp: always-on PMOS source, steered into col while ramp_en & not crossed
        fet(s, f"ramp{k}", f"r{k}", "vb_ramp", "vdd", "vdd", "pfet", wr, lr, pdk=pdk)
        g.nand(f"nr{k}", f"ren{k}_b", "ramp_en", f"c{k}b")
        g.inv(f"ir{k}", f"ren{k}", f"ren{k}_b")
        s.X(f"rc{k}", f"{name}_rsw", f"r{k}", col, f"ren{k}", f"ren{k}_b", "vdd", "vss")
        s.X(f"rd{k}", f"{name}_rsw", f"r{k}", "vcm", f"ren{k}_b", f"ren{k}", "vdd", "vss")
    poly_res(s, "rtop", "vcm", "vth", sz["r_top"], "vss", pdk=pdk)
    poly_res(s, "rbot", "vth", "vss", sz["r_bot"], "vss", pdk=pdk)
    mim_cap(s, "cth", "vth", "vss", sz["c_int"], pdk=pdk)
    # windows: pos = ramp_en & cn & !cp (P holds more charge), neg the mirror image
    g.nand("npos", "pos0_b", "ramp_en", "cn", "cpb")
    g.nand("nneg", "neg0_b", "ramp_en", "cp", "cnb")
    sw = sz["sw"]
    load = 2 * N * (sw["w_n"] + sw["w_p"])     # each window line: 2 TGs x N columns
    g.buf_pair("bpos", "pos", "pos_b", "pos0_b", load)
    g.buf_pair("bneg", "neg", "neg_b", "neg0_b", load)
    return s


def build(name="lora_sidecar", pdk=None):
    pdk = pdk or get_pdk()
    s = ps.Subcircuit(name, PORTS)
    for i in range(N):
        s.X(f"a{i}", f"{name}_arow", f"xen{i}", f"xneg{i}", f"wa_sel{i}", "wdap", "wdan",
            "colp", "coln", "vcm", "vdd", "vss")
    for j in range(N):
        s.X(f"b{j}", f"{name}_bcol", f"wb_sel{j}", "wdbp", "wdbn", f"colb{j}", "pos", "pos_b",
            "neg", "neg_b", "vcm", "vb_tail", "vdd", "vss")
    s.X("wa", f"{name}_wbus", "da0", "da1", "da2", "da3", "wdap", "wdan", "vcm", "vdd", "vss")
    s.X("wb", f"{name}_wbus", "db0", "db1", "db2", "db3", "wdbp", "wdbn", "vcm", "vdd", "vss")
    s.X("vt", f"{name}_vt", "colp", "coln", "rst", "ramp_en", "vaxp", "vaxn", "pos", "pos_b",
        "neg", "neg_b", "vcm", "vb_ramp", "vb_nc", "vb_pc", "vb_tail", "vdd", "vss")
    return s


if __name__ == "__main__":
    print(deck(*children(), build()), end="")
