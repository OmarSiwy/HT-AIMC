"""Self-timed sequencer + t_q tap chain — topology + sizing. Prints the bare deck.

AnalogIOC components/async_ctrl, device for device. `async_ctrl` turns a GO edge into the
column phases: xbar_rst pulse (reset delay chain) -> settle (settle delay chain) ->
adc_go; adc_done is buffered back out as latch_out / done. `tq_chain` is the t_q PWM
grid (tap k rises k*t_q after `in`); analogioc instantiates it next to async_ctrl.
`muller_c` is in AnalogIOC's deck but instantiated nowhere — ported for deck parity.

Sizing (spec: analog/async_ctrl/docs/architecture.md). All logic, no gm/ID coordinate
(every device switches rail to rail, VGS = VDD):
  inverter  Wn = min W, L = min L. Wp = Wn * sqrt(r), r = J_D,n / J_D,p at |VGS| = VDD
            from the gm/ID tables: the minimum-average-delay P/N ratio for a chain of
            identical inverters (Rabaey, Digital ICs, sec. 5.4). AnalogIOC: 0.42/0.84.
  nand2     2-stack pull-down doubled (Wn = 2 * inverter Wn) for inverter-equal fall;
            parallel pull-up = inverter Wp. AnalogIOC: 0.84/0.84.
  loads     reset/settle chains: specs.design() c_load_delay per inverter.
            tq_chain: inverters TQ_M x wider (matching, see TQ_M); C per inverter from
            the t_q target, t_stage = 2 inverters,
                t_inv = K_RAMP * C * (VDD/2) / I_on,  I_on = J_D(VGS=VDD) * W
            averaged over one fall + one rise. AnalogIOC: 550 fF (hand-calibrated).
  muller_c  series stacks doubled (2 x inverter W); keepers min W at 4 x min L (~1/4 of
            the stack drive, so the stack always wins); feedback inverter = inverter.
"""
import sys
from pathlib import Path

A = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(A / "docs"), str(A / "common")]
import gmid  # noqa: E402
import specs  # noqa: E402
from devices import deck, fet, mim_cap  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402

import spicerack as ps  # noqa: E402

PORTS = ["go", "adc_done", "xbar_rst", "adc_go", "latch_out", "done", "vdd", "vss"]
# ponytail: calibration knob. Inner chain stages see the previous stage's slow ramp, not
# a step: measured/step-model delay = 10.15 ns / 6.15 ns on AnalogIOC's 550 fF chain.
K_RAMP = 1.65
KEEPER_L = 4           # muller keeper L in units of min L (drive ~1/4 of the stack)
# tq_chain inverters at TQ_M x the logic inverter width, for matching (Pelgrom:
# sigma ~ 1/sqrt(WL)). tb_async_ctrl_mc at 1x: stage sigma 3.1%, worst 3-stage spread
# 10.15% of 30 samples (spec 10%); 2x area -> / sqrt(2). C_tq follows the drive.
TQ_M = 2


def tq_ports(n_taps=None):
    n_taps = n_taps or specs.design()["tq_n_taps"]
    return ["in"] + [f"tap{k + 1}" for k in range(n_taps)] + ["vdd", "vss"]


def i_on(dev, W, pdk):
    """Saturation drive [A] at |VGS| = VDD (mid-VDS gm/ID table slice)."""
    t = gmid.load_table(dev, pdk.min_l)
    return float(gmid.pchip(t["VGS"], t["ID_per_W"], pdk.vdd)) * W


def sizes(pdk=None):
    """{device: (W, L)} in um and {load: C} in F, from the active PDK."""
    pdk = pdk or get_pdk()
    L, wn = pdk.min_l, pdk.min_w
    r = i_on("nfet", 1.0, pdk) / i_on("pfet", 1.0, pdk)
    wp = round(wn * r ** 0.5, 2)
    # t_stage = K_RAMP * C * VDD/2 * (1/I_n + 1/I_p)  ->  C for t_stage = TQ_SIM
    c_tq = specs.TQ_SIM / (K_RAMP * pdk.vdd / 2 * (1 / i_on("nfet", TQ_M * wn, pdk)
                                                  + 1 / i_on("pfet", TQ_M * wp, pdk)))
    return {
        "inv_n": (wn, L), "inv_p": (wp, L),
        "tq_n": (TQ_M * wn, L), "tq_p": (TQ_M * wp, L),
        "nand_n": (2 * wn, L), "nand_p": (wp, L),
        "mul_n": (2 * wn, L), "mul_p": (2 * wp, L),
        "keep_n": (wn, KEEPER_L * L), "keep_p": (wn, KEEPER_L * L),
        "c_delay": specs.design(pdk)["c_load_delay"],
        "c_tq": round(c_tq, 17),
    }


def inv(s, name, out, inp, sz, pdk, kind="inv"):
    fet(s, f"{name}_n", out, inp, "vss", "vss", "nfet", *sz[f"{kind}_n"], pdk=pdk)
    fet(s, f"{name}_p", out, inp, "vdd", "vdd", "pfet", *sz[f"{kind}_p"], pdk=pdk)


def nand2(s, name, out, a, b, sz, pdk):
    """AnalogIOC nand2 minus its 1 fF ideal cap on the stack node (a convergence stub,
    not layout-realisable: below the MIM minimum)."""
    fet(s, f"{name}_p1", out, a, "vdd", "vdd", "pfet", *sz["nand_p"], pdk=pdk)
    fet(s, f"{name}_p2", out, b, "vdd", "vdd", "pfet", *sz["nand_p"], pdk=pdk)
    fet(s, f"{name}_n1", out, a, f"{name}_mid", "vss", "nfet", *sz["nand_n"], pdk=pdk)
    fet(s, f"{name}_n2", f"{name}_mid", b, "vss", "vss", "nfet", *sz["nand_n"], pdk=pdk)


def delay_chain(name, n_stages, sz, pdk, caps=True, c=None, kind="inv"):
    """n_stages loaded inverters, in -> out (inverting when n_stages is odd). Each
    inverter is sz[kind_n/kind_p] loaded with `c` (default sz["c_delay"])."""
    s = ps.Subcircuit(name, ["in", "out", "vdd", "vss"])
    for i in range(n_stages):
        src = "in" if i == 0 else f"d{i - 1}"
        dst = "out" if i == n_stages - 1 else f"d{i}"
        inv(s, f"{i}", dst, src, sz, pdk, kind)
        if caps:
            mim_cap(s, f"load{i}", dst, "vss", c or sz["c_delay"], pdk=pdk)
    return s


def tq_chain(pdk=None, n_taps=None, caps=True):
    """t_q grid: each tap = 2 loaded inverters after the previous (input polarity)."""
    pdk = pdk or get_pdk()
    sz = sizes(pdk)
    ports = tq_ports(n_taps)
    s = ps.Subcircuit("tq_chain", ports)
    prev = "in"
    for tap in ports[1:-2]:
        mid = f"{tap}_m"
        for src, dst in ((prev, mid), (mid, tap)):
            inv(s, f"tq_{dst}", dst, src, sz, pdk, kind="tq")
            if caps:
                mim_cap(s, f"load_{dst}", dst, "vss", sz["c_tq"], pdk=pdk)
        prev = tap
    return s


def muller_c(pdk=None):
    pdk = pdk or get_pdk()
    sz = sizes(pdk)
    s = ps.Subcircuit("muller_c", ["a", "b", "out", "vdd", "vss"])
    fet(s, "p1", "out", "a", "n1p", "vdd", "pfet", *sz["mul_p"], pdk=pdk)
    fet(s, "p2", "n1p", "b", "vdd", "vdd", "pfet", *sz["mul_p"], pdk=pdk)
    fet(s, "p3", "out", "out_b", "vdd", "vdd", "pfet", *sz["keep_p"], pdk=pdk)
    fet(s, "n1", "out", "a", "n1n", "vss", "nfet", *sz["mul_n"], pdk=pdk)
    fet(s, "n2", "n1n", "b", "vss", "vss", "nfet", *sz["mul_n"], pdk=pdk)
    fet(s, "n3", "out", "out_b", "vss", "vss", "nfet", *sz["keep_n"], pdk=pdk)
    inv(s, "fb", "out_b", "out", sz, pdk)
    return s


def children(pdk=None, caps=True):
    """Subckts async_ctrl's deck defines ahead of it (AnalogIOC generate() order).
    caps=False drops the MIM load caps (Philis deck, see __main__)."""
    pdk = pdk or get_pdk()
    sz, d = sizes(pdk), specs.design(pdk)
    return [delay_chain("rst_delay", d["n_rst_stages"], sz, pdk, caps),
            delay_chain("settle_delay", d["n_settle_stages"], sz, pdk, caps),
            tq_chain(pdk, caps=caps), muller_c(pdk)]


def build(pdk=None):
    pdk = pdk or get_pdk()
    sz = sizes(pdk)
    s = ps.Subcircuit("async_ctrl", PORTS)
    inv(s, "inv_go1", "go_b", "go", sz, pdk)
    inv(s, "inv_go2", "go_buf", "go_b", sz, pdk)
    # reset phase: xbar_rst = go_buf AND NOT(go delayed by the reset chain)
    s.X("rst_dly", "rst_delay", "go_buf", "rst_dly_raw", "vdd", "vss")
    inv(s, "inv_rd1", "rst_dly_b", "rst_dly_raw", sz, pdk)
    inv(s, "inv_rd2", "rst_delayed", "rst_dly_b", sz, pdk)
    nand2(s, "nand_rst", "rst_nand", "go_buf", "rst_dly_b", sz, pdk)
    inv(s, "inv_rst", "xbar_rst", "rst_nand", sz, pdk)
    # settle phase
    s.X("settle_dly", "settle_delay", "rst_delayed", "stl_dly_raw", "vdd", "vss")
    inv(s, "inv_sd1", "stl_dly_b", "stl_dly_raw", sz, pdk)
    inv(s, "inv_sd2", "settle_delayed", "stl_dly_b", sz, pdk)
    # adc phase
    inv(s, "inv_ag1", "adc_go_b", "settle_delayed", sz, pdk)
    inv(s, "inv_ag2", "adc_go", "adc_go_b", sz, pdk)
    # done
    inv(s, "inv_ld1", "latch_b", "adc_done", sz, pdk)
    inv(s, "inv_ld2", "latch_out", "latch_b", sz, pdk)
    inv(s, "inv_dn1", "done_b", "latch_out", sz, pdk)
    inv(s, "inv_dn2", "done", "done_b", sz, pdk)
    return s


# ============================================================================
# Macro wrapper cells: conv_seq (x17) and tile_seq (x1), analog/analogioc/docs/
# INTERFACE.md D2 and §6. Static CMOS from this deck's cells only: min inverter,
# nand2/nor2 (plus NOR set-reset latches and master-slave flops built from them),
# muller_c, loaded-inverter delay elements, tq_chain. No device here has a gm/ID
# coordinate: everything switches rail to rail.
# ============================================================================
# Contract minimum times (INTERFACE.md §4, §6.3, §6.4):
T_CLK_MAX = 20e-9           # LibreLane CLOCK_PERIOD
T_PACE = 2 * T_CLK_MAX      # C0/C5 pacing after cb_ack fall (also covers T_ABS, conv_seq)
T_BUNDLE = 2e-9             # a datum settles this long before its qualifying edge
T_ACQ = 14e-9               # F1, later trials
T_ACQ1 = 2 * specs.T_ACQ    # F1, first trial: OTA settle + parked-wake recovery
T_HOLD = 15e-9              # F2, acq fall -> clk_f rise
T_FHI = 4e-9                # F3, clk_f high minimum
T_FEDGE = 2e-9              # F3, clk_f 10-90 % edges (SA2 kick scales with slew, origin A6)
# Integrate sequence lengths in t_q ticks (§6.2 I3, I5).
N_LO, N_HI, HI_DIV = 16, 8, 16          # LO: 16 cycles of t_q; HI: 8 cycles of 16 t_q
N_SETTLE = 8                            # I5b
N_RAMP0, N_RAMPW, N_SETTLE_L = 4, 50, 10   # I5a
# Chop offsets from the gap start (the "tick" = phi2 fall). §6.1 in its own frame:
# phi1 [t0+0.3, t0+1.9], phi1e to t0+2.1, phi2 [t0+2.5, t0+Tc-0.5], gap from t0-0.5.
CHOP_UNIT = 0.2e-9                      # delay-line cell; every offset is a multiple
CHOP_TAPS = {"phi1_on": 4, "phi1_off": 12, "phi1e_off": 13, "phi2_on": 15}
DLY_PAIRS = 4       # nand/inv pairs per minimum-time element (falling input resets
                    # every pair at once: re-arm in ~1/DLY_PAIRS of the delay)
# ponytail: calibration knobs (measured):
T_FAST = 0.72       # fastest corner (ff/-40 C) over tt delay of this deck's chains,
                    # tb_async_ctrl corners (settle 34.6 / 48.1 ns): a minimum time t
                    # holds on every corner when the element is sized for t/T_FAST at tt
CHOP_CAL = 1.0      # chop line cell: measured / model delay (tb_tile_seq, tt)
CLOSE_CAL = 1.0     # ring closure gate: measured / model delay (tb_tile_seq, tt)


def i_on_l(dev, W, L, pdk):
    """Saturation drive [A] at |VGS| = VDD for width W, length L (gm/ID table)."""
    t = gmid.load_table(dev, L, pdk)
    return float(gmid.pchip(t["VGS"], t["ID_per_W"], pdk.vdd)) * W


def t_gate(c, wn, wp, L, pdk):
    """Loaded-gate delay [s], mean of fall and rise (tq_chain's K_RAMP model)."""
    return K_RAMP * c * pdk.vdd / 4 * (1 / i_on_l("nfet", wn, L, pdk)
                                       + 1 / i_on_l("pfet", wp, L, pdk))


def dly_cell(t_min, pdk):
    """{L, wn, wp, c}: gate sizing of a minimum-time element whose tt delay over
    2*DLY_PAIRS loaded gates is t_min/T_FAST. L steps up from min_l in doublings until
    the per-gate load fits specs.design() c_load_delay (MIM area per ns falls with drive)."""
    t_g = t_min / T_FAST / (2 * DLY_PAIRS)
    c_max = specs.design(pdk)["c_load_delay"]
    for k in (1, 2, 4, 8, 16, 32):
        L = round(k * pdk.min_l, 3)
        wn = pdk.min_w
        wp = round(wn * (i_on_l("nfet", 1, L, pdk) / i_on_l("pfet", 1, L, pdk)) ** 0.5, 2)
        c = t_g / t_gate(1.0, wn, wp, L, pdk)
        if c <= c_max:
            return {"L": L, "wn": wn, "wp": wp, "c": c}
    raise ValueError(f"no delay cell for {t_min * 1e9:.1f} ns within 32*Lmin")


def dly(name, t_min, pdk):
    """`.subckt <name> in out vdd vss`: rising edge delayed >= t_min on every corner;
    a falling `in` resets every stage at once (stage = nand(in, prev) + inverter), so the
    element re-arms right after its input drops."""
    d = dly_cell(t_min, pdk)
    s = ps.Subcircuit(name, ["in", "out", "vdd", "vss"])
    prev = "in"
    for k in range(DLY_PAIRS):
        u, o = f"u{k}", ("out" if k == DLY_PAIRS - 1 else f"d{k}")
        fet(s, f"{u}_p1", u, "in", "vdd", "vdd", "pfet", d["wp"], d["L"], pdk=pdk)
        fet(s, f"{u}_p2", u, prev, "vdd", "vdd", "pfet", d["wp"], d["L"], pdk=pdk)
        fet(s, f"{u}_n1", u, "in", f"{u}_m", "vss", "nfet", 2 * d["wn"], d["L"], pdk=pdk)
        fet(s, f"{u}_n2", f"{u}_m", prev, "vss", "vss", "nfet", 2 * d["wn"], d["L"], pdk=pdk)
        fet(s, f"{o}_n", o, u, "vss", "vss", "nfet", d["wn"], d["L"], pdk=pdk)
        fet(s, f"{o}_p", o, u, "vdd", "vdd", "pfet", d["wp"], d["L"], pdk=pdk)
        mim_cap(s, f"c{u}", u, "vss", d["c"], pdk=pdk)
        mim_cap(s, f"c{o}", o, "vss", d["c"], pdk=pdk)
        prev = o
    return s


class Logic:
    """Static CMOS gates appended to one Subcircuit, auto-named (nets `n_<k>`), sized by
    sizes(): inverter, nand2 (n stack doubled), nor2 (p stack doubled). `cells` collects
    the child subckts (delay elements) the gates instantiate."""

    def __init__(self, s, pdk, cells):
        self.s, self.pdk, self.cells, self.k = s, pdk, cells, 0
        sz = sizes(pdk)
        (self.wn, self.L), (self.wp, _) = sz["inv_n"], sz["inv_p"]

    def net(self, out=None):
        if out:
            return out
        self.k += 1
        return f"n_{self.k}"

    def _f(self, name, d, g, s_, b, kind, w):
        fet(self.s, name, d, g, s_, b, kind, w, self.L, pdk=self.pdk)

    def inv(self, a, out=None, k=1):
        o = self.net(out)
        self._f(f"{o}_n", o, a, "vss", "vss", "nfet", round(k * self.wn, 2))
        self._f(f"{o}_p", o, a, "vdd", "vdd", "pfet", round(k * self.wp, 2))
        return o

    def nand(self, a, b, out=None):
        o = self.net(out)
        self._f(f"{o}_p1", o, a, "vdd", "vdd", "pfet", self.wp)
        self._f(f"{o}_p2", o, b, "vdd", "vdd", "pfet", self.wp)
        self._f(f"{o}_n1", o, a, f"{o}_x", "vss", "nfet", 2 * self.wn)
        self._f(f"{o}_n2", f"{o}_x", b, "vss", "vss", "nfet", 2 * self.wn)
        return o

    def nor(self, a, b, out=None):
        o = self.net(out)
        self._f(f"{o}_p1", o, a, f"{o}_x", "vdd", "pfet", 2 * self.wp)
        self._f(f"{o}_p2", f"{o}_x", b, "vdd", "vdd", "pfet", 2 * self.wp)
        self._f(f"{o}_n1", o, a, "vss", "vss", "nfet", self.wn)
        self._f(f"{o}_n2", o, b, "vss", "vss", "nfet", self.wn)
        return o

    def and_(self, a, b, out=None):
        return self.inv(self.nand(a, b), out)

    def or_(self, a, b, out=None):
        return self.inv(self.nor(a, b), out)

    def _tree(self, op, xs, out):
        xs = list(xs)
        while len(xs) > 2:
            xs = [op(*xs[i:i + 2]) if i + 1 < len(xs) else xs[i]
                  for i in range(0, len(xs), 2)]
        return op(*xs, out)

    def or_n(self, xs, out=None):
        return self._tree(self.or_, xs, out)

    def and_n(self, xs, out=None):
        return self._tree(self.and_, xs, out)

    def xor(self, a, b, out=None):
        x = self.nand(a, b)
        return self.nand(self.nand(a, x), self.nand(b, x), out)

    def mux(self, sel, a, b, selb=None, out=None):
        """sel ? a : b"""
        selb = selb or self.inv(sel)
        return self.nand(self.nand(sel, a), self.nand(selb, b), out)

    def maj(self, x, y, z, out=None):
        """(x&y) | (z&(x|y)): one bit of a ripple magnitude comparator."""
        return self.nand(self.nand(x, y), self.nand(z, self.or_(x, y)), out)

    def rsl(self, S, R, out=None):
        """Set-reset latch, reset priority: Q = !R & (S | Q). Two NOR2."""
        q, t = self.net(out), self.net()
        self.nor(S, q, t)
        self.nor(R, t, q)
        return q

    def crs(self, a, b, r, out=None):
        """Muller C-element with reset: rises on a&b, falls on !a&!b or r."""
        return self.rsl(self.and_(a, b), self.or_(self.nor(a, b), r), out)

    def buf(self, a, out=None, load=1):
        """Non-inverting buffer for `load` gate inputs, fanout ~4 per stage."""
        k2 = max(1, round(load / 4))
        return self.inv(self.inv(a, k=max(1, round(k2 ** 0.5))), out, k=k2)

    def delay(self, a, t_min, tag, out=None):
        """Minimum-time element (dly) on `a`; one subckt per tag."""
        name = f"dly_{tag}"
        if name not in self.cells:
            self.cells[name] = dly(name, t_min, self.pdk)
        o = self.net(out)
        self.s.X(f"x{o}", name, a, o, "vdd", "vss")
        return o

    def clkbus(self, ck, n_ff):
        """Non-overlapping master/slave enables for n_ff flops on clock `ck`: master open
        while !ck & !ckd, slave while ck & ckd (ckd = ck through 4 inverters).
        Returns the active-low enables {"mb", "sb"} the flops take."""
        ckd = ck
        for _ in range(4):
            ckd = self.inv(ckd)
        k = max(1, round(n_ff / 2))
        return {"mb": self.inv(self.nor(ck, ckd), k=k),
                "sb": self.inv(self.inv(self.nand(ck, ckd)), k=k)}

    def dff(self, d, bus, r=None, out=None):
        """Rising-edge master-slave D flop from NOR2 latches; r = async reset to 0."""
        db = self.inv(d)
        rm = self.nor(d, bus["mb"])
        rm = self.or_(rm, r) if r else rm
        m, tm = self.net(), self.net()
        self.nor(self.nor(db, bus["mb"]), m, tm)
        self.nor(rm, tm, m)
        rq = self.nor(m, bus["sb"])
        rq = self.or_(rq, r) if r else rq
        q, tq = self.net(out), self.net()
        self.nor(self.nor(tm, bus["sb"]), q, tq)
        self.nor(rq, tq, q)
        return q


CONV_SEQ_PORTS = ["rst_n", "sgo", "phi1", "phi2", "coarse_en", "cb_ack", "cmp_req",
                  "ota_en", "pkt_d0", "pkt_d1", "pkt_d2", "c1p", "c1n", "c2p", "c2n",
                  "sdone", "col_sign", "cb_req", "cb_cross", "cmp_ack", "cmp_result",
                  "busy", "run", "fire", "sign", "sgd", "clk_c", "acq", "clk_f", "awake",
                  "vdd", "vss"]


def clkf_driver(pdk):
    """(L, wn, wp, C) of the clk_f output inverter: 10-90 % edges >= T_FEDGE on every
    corner, edge ~ 0.8*VDD*C / I_on of the stronger device."""
    d = dly_cell(T_FEDGE, pdk)
    i_max = max(i_on_l("nfet", d["wn"], d["L"], pdk), i_on_l("pfet", d["wp"], d["L"], pdk))
    return d["L"], d["wn"], d["wp"], T_FEDGE / T_FAST * i_max / (0.8 * pdk.vdd)


def conv_seq(pdk=None, cells=None):
    """Per-column handshake translator (INTERFACE.md §6.2 I6, §6.3, §6.4).

    State lives in NOR set-reset latches and phi2-fall flops; all of it resets while
    rst_n & sgo is low (sgo = tile_seq's sign-phase level, cleared at the next
    integ_req). The comparators are dual rail: precharge = both 1, a decision = one 0,
    completion = nand(c?p, c?n). Strobes are held until completion, so a slow decision
    delays the handshake instead of corrupting it."""
    pdk = pdk or get_pdk()
    cells = {} if cells is None else cells
    s = ps.Subcircuit("conv_seq", CONV_SEQ_PORTS)
    g = Logic(s, pdk, cells)
    nA = g.nand("rst_n", "sgo")                 # conversion reset
    # a decision = one rail low while the other is still high: the StrongARM's common-
    # mode dip before regeneration (both rails falling together) never registers
    p = g.nor("c1p", g.inv("c1n"))              # SA1: out > vinn
    n = g.nor("c1n", g.inv("c1p"))              # SA1: out < vinn
    cc = g.or_(p, n)                            # SA1 completion
    sgdb = g.inv("sgd")
    # I6 sign strobe: sign := c1n, then sgd once the strobe is low and SA1 precharged
    g.rsl(g.and_(p, sgdb), g.or_(g.and_(n, sgdb), nA), "sign")
    s_got = g.rsl(g.and_(cc, sgdb), nA)
    s_req = g.nor(nA, s_got)
    quiet = g.nor(cc, "clk_c")
    g.rsl(g.and_(s_got, quiet), nA, "sgd")
    g.inv(sgdb, "sdone")
    g.nor("sign", sgdb, "col_sign")             # 1 = negative; 0 until sgd
    # C0..C2 coarse decision
    c_got, acked = "c_got", "acked"
    c_gotb = g.inv(c_got)
    # T_PACE after cb_ack fall, and after the sign strobe (out recovers from its kick)
    idle = g.and_(c_gotb, "sgd")
    ready = g.and_(idle, g.delay(idle, T_PACE, "pace"))
    cbab = g.inv("cb_ack")
    cs = g.rsl(g.and_(g.and_(ready, "coarse_en"), g.and_("sgd", cbab)), g.or_(nA, c_got))
    signb = g.inv("sign")
    x = g.mux("sign", p, n, signb)              # cmp == sign: a crossing
    y = g.mux("sign", n, p, signb)
    g.rsl(g.and_(x, "sgd"), g.or_(g.and_(y, "sgd"), nA), "cb_cross")
    g.rsl(g.and_(cc, cs), g.or_(nA, g.and_(acked, cbab)), c_got)
    g.rsl(g.and_("cb_ack", c_got), c_gotb, acked)
    # SA1 strobe: rises at the next phi1 rise, falls at a phi1 fall after completion
    # arm: request seen with phi1 low (so the strobe waits for a full phi1 rise), dropped
    # with the request; strobe: rises with phi1 while armed, falls once disarmed and
    # phi1 is low (a decision landing after phi1 fell ends it at once)
    req = g.or_(s_req, cs)
    arm = g.rsl(g.and_(req, g.inv("phi1")), g.or_(g.inv(req), nA))
    g.buf(g.crs(arm, "phi1", nA), "clk_c", load=4)
    # C2 bundle -> cb_req; C3 packet; C4 cb_req fall when it is over
    q = g.and_(c_got, quiet)
    qd = g.and_(q, g.delay(q, T_BUNDLE, "bundle"))
    qdb = g.inv(qd)
    crossb = g.inv("cb_cross")
    f_arm = g.and_(g.and_("cb_ack", "cb_cross"), c_got)
    # fire: pkt_d chop cycles from the next gap, counted by phi2-fall flops
    bus = g.clkbus(g.inv("phi2"), 4)
    rc = c_gotb
    z = g.nor(g.or_("pkt_d0", "pkt_d1"), "pkt_d2")       # pkt_d = 0 means 1
    dd = [g.or_("pkt_d0", z), "pkt_d1", "pkt_d2"]
    nq = ["fn0", "fn1", "fn2"]
    lt = g.and_(g.inv(nq[0]), dd[0])
    for k in (1, 2):
        lt = g.maj(g.inv(nq[k]), dd[k], lt)                # fired so far < D
    fire_d = g.and_(f_arm, lt)
    g.dff(fire_d, bus, rc, "fire")
    carry = fire_d
    for k in range(3):
        g.dff(g.xor(nq[k], carry), bus, rc, nq[k])
        if k < 2:
            carry = g.and_(nq[k], carry)
    fired = g.and_(f_arm, g.inv(lt))
    pk_done = g.and_(c_got, g.or_(g.and_("cb_ack", crossb), fired))
    done_c = g.rsl(pk_done, qdb)
    g.nor(qdb, done_c, "cb_req")
    # run: packet chop live from the first coarse strobe to a no-cross / coarse_en low
    stop = g.or_(g.and_(g.and_("cb_ack", c_got), crossb),
                 g.and_(ready, g.inv("coarse_en")))
    g.rsl(cs, g.or_(nA, stop), "run")
    # F1..F5 SAR trial
    nf = g.rsl("cmp_ack", nA)                   # a trial completed: later ones T_ACQ
    acq_done = g.and_("cmp_req", g.mux(nf, g.delay("cmp_req", T_ACQ, "acq"),
                                       g.delay("cmp_req", T_ACQ1, "acq1")))
    g.nor(g.inv("cmp_req"), acq_done, "acq")
    fs = g.and_(acq_done, g.delay(acq_done, T_HOLD, "hold"))
    p2 = g.nor("c2p", g.inv("c2n"))             # SA2: ct > vcm
    n2 = g.nor("c2n", g.inv("c2p"))
    cf = g.or_(p2, n2)                          # SA2 completion
    f_got = g.rsl(g.and_(cf, fs), g.inv("cmp_req"))
    # clk_f has been high T_FHI (timed from clk_f itself, sticky for the trial)
    fhi = g.rsl(g.delay(g.inv(g.inv("clk_f")), T_FHI, "fhi"), g.inv("cmp_req"))
    freq = g.and_(fs, g.nand(f_got, fhi))
    L, wn, wp, c = clkf_driver(pdk)
    fb = g.inv(freq)
    fet(s, "clk_f_n", "clk_f", fb, "vss", "vss", "nfet", wn, L, pdk=pdk)
    fet(s, "clk_f_p", "clk_f", fb, "vdd", "vdd", "pfet", wp, L, pdk=pdk)
    mim_cap(s, "clk_f_c", "clk_f", "vss", c, pdk=pdk)
    g.rsl(g.mux("sign", n2, p2, signb),                    # result = sign ? c2p : c2n
          g.or_(g.mux("sign", p2, n2, signb), nA), "cmp_result")
    fq = g.and_(f_got, g.nor(cf, freq))
    g.and_(g.and_(fq, g.delay(fq, T_BUNDLE, "bundle")), "cmp_req", "cmp_ack")
    g.or_("ota_en", "acq", "awake")
    g.or_("coarse_en", "cmp_req", "busy")
    return s


def chop_gen(pdk=None):
    """`.subckt chop_gen p phi1r phi1er phi2r ck vdd vss`: every edge of p is a tick.
    e(x) = p xor p_delayed(x) is high for x after a tick; phi1r = e(2.4) & !e(0.8),
    phi1er = e(2.6) & !e(0.8), phi2r = !e(3.0) (falls at the tick), ck = e(0.8) (rises
    at the tick). The delays are taps of one line of identical CHOP_UNIT cells (2 loaded
    inverters, every cell buffered so all see the same load); p is buffered the same way,
    so the xor delay cancels out of every offset."""
    pdk = pdk or get_pdk()
    s = ps.Subcircuit("chop_gen", ["p", "phi1r", "phi1er", "phi2r", "ck", "vdd", "vss"])
    g = Logic(s, pdk, {})
    c = CHOP_CAL * CHOP_UNIT / 2 / t_gate(1.0, g.wn, g.wp, g.L, pdk)
    pb = g.inv("p")
    prev, taps = "p", {}
    for k in range(1, max(CHOP_TAPS.values()) + 1):
        mid = g.inv(prev)
        mim_cap(s, f"cm{k}", mid, "vss", c, pdk=pdk)
        prev = g.inv(mid, f"dl{k}")
        mim_cap(s, f"cd{k}", prev, "vss", c, pdk=pdk)
        taps[k] = g.inv(prev)
    e = {name: g.xor(pb, taps[k]) for name, k in CHOP_TAPS.items()}
    on_b = g.inv(e["phi1_on"])
    g.and_(e["phi1_off"], on_b, "phi1r")
    g.and_(e["phi1e_off"], on_b, "phi1er")
    g.inv(e["phi2_on"], "phi2r")
    g.inv(on_b, "ck")
    return s


def tile_seq_ports():
    R, NC = specs.N_ROWS, specs.N_COLS
    return (["seq_rst_n", "integ_req", "integ_ack", "win_hi", "lora_en"]
            + [f"x_mag{k}" for k in range(4 * R)] + [f"x_neg{i}" for i in range(R)]
            + [f"sdone{j}" for j in range(NC)] + [f"busy{j}" for j in range(NC)]
            + ["sgo", "rst", "phi1", "phi1e", "phi2", "tphi1", "tphi1e", "tphi2"]
            + [p for i in range(R) for p in (f"xin_p_r{i}", f"xin_n_r{i}")]
            + [f"xrd_en{i}" for i in range(R)] + ["ramp_en", "vdd", "vss"])


def ring_closure(pdk):
    """(Wn, Wp, C) of the ring's closing nand2(ring_en, tap4) -> tq_chain `in`: n stack at
    2x the tq inverter, p sized for equal rise/fall current, one full t_q per edge."""
    sz = sizes(pdk)
    wn = sz["tq_n"][0]
    i = i_on_l("nfet", wn, pdk.min_l, pdk)
    wp = round(wn * i_on_l("nfet", 1, pdk.min_l, pdk) / i_on_l("pfet", 1, pdk.min_l, pdk), 2)
    return 2 * wn, max(wp, sz["tq_p"][0]), CLOSE_CAL * specs.TQ_SIM * i / (K_RAMP * pdk.vdd / 2)


def tile_seq(pdk=None, cells=None):
    """Integrate sequencer, chop ring, PWM envelopes, sidecar phases (§6.1, §6.2).

    Ring: tq_chain closed by one nand2(ring_en, tap4) sized for a full t_q per edge;
    every edge of its 5 nodes is a t_q tick and p = their parity. ring_en = integ_req |
    integ_ack | any busy. Converter chop = chop_gen(p).
    async_ctrl: go = integ_req & seq_rst_n, xbar_rst -> rst, adc_go -> window start
    (2-flop synchronised to the tick clock), adc_done = sign join & this-request flag.
    A counter on the tick clock runs the window (LO 16 x t_q, HI 8 x 16 t_q; row i's
    envelope is high for the first x_mag[4i+3:4i] tile cycles), then the post-window
    settle (with lora_en: ramp gap, ramp, settle) and raises sgo. The tile chop is
    chop_gen(p_tile), p_tile toggling at every tile tick, parked (tphi1 = tphi1e = 1,
    tphi2 = 0) outside the window. x_*/win_hi are not latched: the contract holds them
    until integ_ack rises, and nothing here reads them after that."""
    pdk = pdk or get_pdk()
    cells = {} if cells is None else cells
    R, NC = specs.N_ROWS, specs.N_COLS
    s = ps.Subcircuit("tile_seq", tile_seq_ports())
    g = Logic(s, pdk, cells)
    # async_ctrl, reset, sign-phase flags
    srb = g.inv("seq_rst_n")
    go = g.and_("integ_req", "seq_rst_n")
    rI = g.inv(go)                                         # integrate-phase reset
    s.X("seq", "async_ctrl", go, "adc_done", "xbar_rst", "adc_go", "latch_out",
        "integ_ack", "vdd", "vss")
    started = g.rsl("xbar_rst", srb)
    g.buf(g.or_("xbar_rst", g.inv(started)), "rst", load=2 * NC + 4)
    g.buf(g.rsl("sg", g.or_("xbar_rst", srb)), "sgo", load=2 * NC)
    ackp = g.rsl("sg", rI)
    # 17-way C-element join; C-elements with reset (seq_rst_n), so the tree powers up low
    # (a bare muller_c holds an arbitrary state and acked before the columns had)
    join = [f"sdone{j}" for j in range(NC)]
    while len(join) > 1:
        nxt = [g.crs(join[i], join[i + 1], srb) for i in range(0, len(join) - 1, 2)]
        join = nxt + ([join[-1]] if len(join) % 2 else [])
    g.and_(ackp, g.and_(join[0], g.delay(join[0], T_BUNDLE, "bundle")), "adc_done")
    # ring
    ren = g.or_n(["integ_req", "integ_ack"] + [f"busy{j}" for j in range(NC)])
    s.X("ring", "tq_chain", *tq_ports())
    wn, wp, c = ring_closure(pdk)
    fet(s, "close_p1", "in", ren, "vdd", "vdd", "pfet", wp, pdk.min_l, pdk=pdk)
    fet(s, "close_p2", "in", "tap4", "vdd", "vdd", "pfet", wp, pdk.min_l, pdk=pdk)
    fet(s, "close_n1", "in", ren, "close_x", "vss", "nfet", wn, pdk.min_l, pdk=pdk)
    fet(s, "close_n2", "close_x", "tap4", "vss", "vss", "nfet", wn, pdk.min_l, pdk=pdk)
    mim_cap(s, "close_c", "in", "vss", c, pdk=pdk)
    t = [g.inv(x) for x in ("in", "tap1", "tap2", "tap3", "tap4")]
    p = g.xor(g.xor(g.xor(t[0], t[1]), g.xor(t[2], t[3])), t[4], "p")
    s.X("cchop", "chop_gen", p, "c_phi1", "c_phi1e", "c_phi2", "c_ck", "vdd", "vss")
    g.buf("c_phi1", "phi1", load=3 * NC)
    g.buf("c_phi1e", "phi1e", load=NC)
    g.buf(g.and_(ren, "c_phi2"), "phi2", load=2 * NC)
    # tick-clock state machine
    bus = g.clkbus(g.inv(g.inv("c_ck")), 2 + 8 + 5 + 2 + R)
    s1 = g.dff(g.dff("adc_go", bus, rI), bus, rI, "s1")
    hib = g.inv("win_hi")
    cb = [f"cnt{k}" for k in range(8)]
    wend = g.mux("win_hi", cb[7], cb[4], hib)              # count == window length
    pw = "pw"
    clrb = g.nand(wend, g.inv(pw))                         # clear at the window end
    carry = g.and_(s1, g.inv("sg"))                        # stop at sign go
    for k in range(8):
        g.dff(g.and_(clrb, g.xor(cb[k], carry)), bus, rI, cb[k])
        if k < 7:
            carry = g.and_(cb[k], carry)
    w_d = g.and_(g.and_(s1, g.inv(wend)), g.inv(pw))
    w = g.dff(w_d, bus, rI, "w")
    g.dff(g.or_(pw, g.and_(s1, wend)), bus, rI, pw)
    blk0 = g.nor(g.or_(cb[0], cb[1]), g.or_(cb[2], cb[3]))
    ten = g.and_(s1, g.or_(hib, blk0))                     # tile tick: LO every t_q
    g.dff(g.xor("p_tile", ten), bus, rI, "p_tile")

    def eq(v):
        """count == v (7 bits); post-window the count at tick W+k is k-1."""
        return g.and_n([cb[b] if (v >> b) & 1 else g.inv(cb[b]) for b in range(7)])
    g.dff(g.or_("r_on", g.and_(g.and_(pw, "lora_en"), eq(N_RAMP0 - 1))), bus, rI, "r_on")
    g.dff(g.or_("r_off", g.and_(pw, eq(N_RAMP0 + N_RAMPW - 1))), bus, rI, "r_off")
    g.buf(g.and_("r_on", g.inv("r_off")), "ramp_en", load=R)
    hit = g.mux("lora_en", eq(N_RAMP0 + N_RAMPW + N_SETTLE_L - 1), eq(N_SETTLE - 1))
    g.dff(g.or_("sg", g.and_(pw, hit)), bus, rI, "sg")
    # envelopes: row i high while tile cycle < m_i (ripple-majority comparator)
    ct = [g.mux("win_hi", cb[4 + k], cb[k], hib) for k in range(3)] + [g.and_(hib, cb[3])]
    ctb = [g.inv(x) for x in ct]
    tenb = g.inv(ten)
    # envelope latch enable: the tile gap proper, after the raw tile phi2 has fallen and
    # before ck = e(0.8) ends (tile phi1 rises after it)
    een = g.and_("t_ck", g.inv("t_phi2"))
    for i in range(R):
        m = [f"x_mag{4 * i + k}" for k in range(4)]
        lt = g.and_(ctb[0], m[0])
        for k in (1, 2, 3):
            lt = g.maj(ctb[k], m[k], lt)
        env = g.dff(g.mux(ten, g.and_(w_d, lt), f"env{i}", tenb), bus, rI, f"env{i}")
        # change only inside the tile gap
        envb = g.inv(env)
        env = g.inv(g.inv(g.rsl(g.and_(env, een), g.or_(g.and_(envb, een), rI))))
        g.and_(env, g.inv(f"x_neg{i}"), f"xin_p_r{i}")
        g.and_(env, f"x_neg{i}", f"xin_n_r{i}")
        g.and_(env, "lora_en", f"xrd_en{i}")
    # tile chop from p_tile, parked outside the window. w2 opens with the first tile phi1
    # (after the chop's own xor path has settled: no runt tphi2, no tphi1 blip) and
    # closes with w (the window-end tick, when the chop has just ended tphi2 itself)
    s.X("tchop", "chop_gen", "p_tile", "t_phi1", "t_phi1e", "t_phi2", "t_ck", "vdd", "vss")
    wdl = g.rsl(g.and_(w, "t_phi1"), g.inv(w), "w2")
    wb = g.inv(wdl)
    g.buf(g.or_(wb, "t_phi1"), "tphi1", load=3 * R + 2)
    g.buf(g.or_(wb, "t_phi1e"), "tphi1e", load=2 * R)
    g.buf(g.and_(wdl, "t_phi2"), "tphi2", load=2)
    return s


def wrapper_cells(pdk=None):
    """The macro wrapper subckts, children first: delay elements, chop_gen, conv_seq,
    tile_seq (tile_seq instantiates async_ctrl, tq_chain and muller_c from children())."""
    pdk = pdk or get_pdk()
    cells = {}
    cs, ts = conv_seq(pdk, cells), tile_seq(pdk, cells)
    return list(cells.values()) + [chop_gen(pdk), cs, ts]


if __name__ == "__main__":
    # async_ctrl.py [tq_chain] [--no-caps]
    #   tq_chain   tq_chain alone as the top, for its own Philis run
    #   --no-caps  without the MIM load caps: Philis's feedback extraction never finishes
    #              on a deck with several cap_mim devices (>8 h at iteration 0), so the
    #              FETs are P&R'd alone and pex.py re-adds the caps from the full deck
    caps = "--no-caps" not in sys.argv
    print(deck(tq_chain(caps=caps)) if "tq_chain" in sys.argv
          else deck(*children(caps=caps), build()) if not caps
          # full deck: the macro wrapper cells too; async_ctrl stays last (Philis top)
          else deck(*children(), *wrapper_cells(), build()), end="")
