"""lora_sidecar testbench harness: one transient per testbench, phases on the INTERFACE.md
schedule, charge per column read from the colb clamps.

The DUT (bench.dut, $DUT va|sch|pex) sits in a wrapper with the bias the macro must
supply: the OTA rails from ota_bench.bias_network (replica bias) and vb_ramp from a
diode replica of the ramp PMOS carrying specs.lora_i_ramp() (a fixed voltage drifts with
Vt over PVT, like the OTA tail). colb<j> are ideal vcm clamps — stand-ins for the tile
column integrators' virtual grounds; the charge a column sinks, over q_unit, is its
Delta mac (positive = V_out up, same polarity as the tile cells).

Codes are sign-magnitude: value v in -7..7 -> (v < 0) << 3 | |v| (golden lora_quant's
W_MAX = 7 grid). A calibration (calibrate()) measures the level table levels[m] (cell
current at magnitude m over m = 7, from the B currents inside a long window) and rho,
the per-chip knob, from two reference passes; verification passes then compare against
scripts/golden/model.py with those numbers.

Timing (INTERFACE.md section 6.2 and 7.2, sim grid): write select high WR = 120 ns with
the code set 1 clk (20 ns) before and held 1 clk after, T_WSETTLE after a write burst;
per pass rst T_RST = 4 t_q,
gap T_RG = 1 t_q, window (LO 16 x t_q, HI 8 x 16 t_q; xen high for the first t_q of every
cycle k < m_i), gap T_RAMP0 = 4 t_q, ramp_en T_RAMPW, settle T_SETTLE_L = 10 t_q.
T_RAMPW here is what the block needs (1.5 x the longest window plus both pedestals, on
the t_q grid); the macro's 50 t_q is longer.
"""
import math
import os
import sys
from pathlib import Path

import numpy as np

A = Path(__file__).resolve().parents[2]
ROOT = A.parent
sys.path[:0] = [str(A / "docs"), str(A / "common"), str(A / "lora_sidecar" / "netlist"),
                str(A / "ota" / "netlist"), str(A / "ota" / "test"), str(ROOT / "scripts")]
import lora_sidecar as L  # noqa: E402
import specs  # noqa: E402
from bench import dut, dut_kind  # noqa: E402
from devices import fet  # noqa: E402
from golden import model as G  # noqa: E402
from ota_bench import REF_CURRENT, bias_network  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402

import spicerack as ps  # noqa: E402

BLOCK = "lora_sidecar"
PDK = get_pdk()
VDD = PDK.vdd
VCM = specs.VCM_FRAC * VDD
N = L.N
WMAX = 2 ** specs.LORA_MAG_BITS - 1
TQ = specs.TQ_SIM
TR = 0.2e-9                      # logic edge
T_CLK = 20e-9                    # LibreLane CLOCK_PERIOD (INTERFACE T_CLK_MAX)
T_WR = 120e-9                    # WR_CYCLES x T_clk (INTERFACE 7.2 step 6)
T_SLOT = T_WR + 2 * T_CLK
T_WSETTLE = 1e-6                 # after the last write of a burst, before a pass: a newly
                                 # written B mirror settles (1.3 % short 150 ns after its
                                 # write slot, tb_lora_sidecar storage check)
T_RST, T_RG, T_RAMP0, T_SETTLE = 4 * TQ, TQ, 4 * TQ, 10 * TQ
SZ = L.sizes(PDK)
T_PED = SZ["v_ped"] * specs.lora_c_int(PDK) / specs.lora_i_ramp(PDK)
T_RAMPW = math.ceil(1.5 * (specs.lora_t_b_max(PDK) + 2 * T_PED) / TQ) * TQ
Q_UNIT = specs.q_unit(PDK)
TIGHT = dict(reltol=1e-4, abstol=1e-12, vntol=1e-6, method="gear")
CAL_ROWS = 4                     # rows 0..3 hold A = +7: the calibration reference
CAL_X = 15                       # LO nibble on them: sum level*m = 60 = LORA_AX_MAX


def code(v):
    return (8 if v < 0 else 0) | abs(int(v))


def eff(v, levels):
    """Golden effective weight of signed code value(s) v: sign * 7 * levels[|v|]."""
    v = np.asarray(v)
    return np.sign(v) * WMAX * np.asarray(levels)[np.abs(v)]


def va_dut():
    """DUT=va: the block's golden is its four child Verilog-A modules (va/<child>.va, 1:1
    with the netlist subckts), wired by the netlist's own instances() list. ESPice takes at
    most 64 unknowns per Verilog-A device (its Jacobian rows are u64 masks): one module
    for the whole sidecar has 201. vt gets the PDK-derived parameters."""
    vcm = specs.VCM_FRAC * PDK.vdd
    vt = {"cint": specs.lora_c_int(PDK), "iramp": specs.lora_i_ramp(PDK),
          "vped": SZ["v_ped"], "rdiv": vcm / L.DIV_I}
    top = ps.Subcircuit(f"tb_{BLOCK}")
    for child in ("arow", "bcol", "wbus", "vt"):
        m = f"{BLOCK}_{child}"
        top.veriloga(str(A / BLOCK / "va" / f"{m}.va"))
        par = " ".join(f"{k}={v}" for k, v in vt.items()) if child == "vt" else ""
        top.raw_spice(f".model {m}_va {m} {par}".rstrip())
    for inst, sub, nets in L.instances(BLOCK):
        top.raw_spice(f"N{inst} {' '.join(nets)} {sub}_va")
    return top


class Run:
    """Stimulus schedule (PWL per control net) + the passes to measure."""

    def __init__(self):
        self.t = 50e-9
        self.pts = {n: [(0.0, 0.0)] for n in
                    [f"xen{i}" for i in range(N)] + [f"xneg{i}" for i in range(N)]
                    + [f"wa_sel{i}" for i in range(N)] + [f"wb_sel{j}" for j in range(N)]
                    + [f"da{b}" for b in range(4)] + [f"db{b}" for b in range(4)]
                    + ["ramp_en"]}
        self.pts["rst"] = [(0.0, VDD)]
        self.passes = []

    def _set(self, net, t, v):
        p = self.pts[net]
        if p[-1][1] != v:
            p += [(t, p[-1][1]), (t + TR, v)]

    def program(self, a=None, b=None):
        """Write signed values {row: v} into A and {col: v} into B, one A and one B cell
        per slot (two DACs, two select lines)."""
        a, b = sorted((a or {}).items()), sorted((b or {}).items())
        for k in range(max(len(a), len(b))):
            t0 = self.t
            for side, items in (("a", a), ("b", b)):
                if k < len(items):
                    idx, v = items[k]
                    for bit in range(4):
                        self._set(f"d{side}{bit}", t0, VDD * ((code(v) >> bit) & 1))
                    self._set(f"w{side}_sel{idx}", t0 + T_CLK, VDD)
                    self._set(f"w{side}_sel{idx}", t0 + T_CLK + T_WR, 0.0)
            self.t = t0 + T_SLOT
        self.t += T_WSETTLE

    def lora_pass(self, xq, window="lo", tag=""):
        """One integrate + V->T pass of signed INT8 activations xq (golden pwm_nibbles:
        this window's nibble drives xen, the sign drives xneg)."""
        sign, hi, lo = G.pwm_nibbles(np.asarray(xq))
        m = lo if window == "lo" else hi
        n_cyc, tc = (16, TQ) if window == "lo" else (8, 16 * TQ)
        t0 = self.t
        for i in range(N):
            self._set(f"xneg{i}", t0, VDD if sign[i] < 0 else 0.0)
        self._set("rst", t0 + TQ, VDD)
        self._set("rst", t0 + TQ + T_RST, 0.0)
        tw = t0 + TQ + T_RST + T_RG
        for i in range(N):
            if window == "lo" and m[i]:
                self._set(f"xen{i}", tw, VDD)
                self._set(f"xen{i}", tw + m[i] * TQ, 0.0)
            for k in range(m[i] if window == "hi" else 0):
                self._set(f"xen{i}", tw + k * tc, VDD)
                self._set(f"xen{i}", tw + k * tc + TQ, 0.0)
        tr = tw + n_cyc * tc + T_RAMP0
        self._set("ramp_en", tr, VDD)
        self._set("ramp_en", tr + T_RAMPW, 0.0)
        self.t = tr + T_RAMPW + T_SETTLE
        self.passes.append({"tag": tag, "xq": np.asarray(xq), "window": window, "tw": tw,
                            "tr": tr, "t1": self.t})
        return self.passes[-1]

    def simulate(self, corner="", seed=None):
        # ponytail: LORA_NPZ=<file> replays a saved run (analysis debugging, ~8 min/sim)
        npz = os.environ.get("LORA_NPZ")
        if npz and os.path.exists(npz):
            d = np.load(npz)
            for k in ("time", "isink", "vaxp", "vaxn", "ivdd", "ivcm"):
                setattr(self, k, d[k])
            return self
        self._simulate(corner, seed)
        if npz:
            np.savez(npz, time=self.time, isink=self.isink, vaxp=self.vaxp, vaxn=self.vaxn,
                     ivdd=self.ivdd, ivcm=self.ivcm)
        return self

    def _simulate(self, corner, seed):
        top = va_dut() if dut_kind() == "va" else dut(BLOCK, L.PORTS)
        bias_network(top, PDK)
        fet(top, "rep_ramp", "vb_ramp", "vb_ramp", "vdd", "vdd", "pfet", *SZ["ramp"], pdk=PDK)
        top.I(name="ref_ramp", positive="vb_ramp", negative="vss",
              value=specs.lora_i_ramp(PDK))
        tb = ps.Testbench(top)
        tb.use_pdk(PDK.model_library(corner or os.environ.get("CORNER", "")))
        tb.temperature = float(os.environ.get("SIM_TEMP", 27))
        tb.options(**TIGHT)
        if seed is not None:
            tb.options(seed=seed)
        tb.V(name="sup", positive="vdd", negative="0", value=VDD)
        tb.V(name="ss", positive="vss", negative="0", value=0.0)
        tb.V(name="cm", positive="vcm", negative="0", value=VCM)
        for j in range(N):
            tb.V(name=f"cb{j}", positive=f"colb{j}", negative="0", value=VCM)
        t_end = self.t + 20e-9
        for net, p in self.pts.items():
            tb.PieceWiseLinearVoltageSource(name=f"s_{net}", positive=net, negative="0",
                                            values=p + [(t_end, p[-1][1])])
        probes = [f"I(Vcb{j})" for j in range(N)] + ["V(vaxp)", "V(vaxn)", "I(Vsup)",
                                                     "I(Vcm)"]
        tb.save(*probes)
        d = tb.transient(step_time=0.1e-9, end_time=t_end, max_time=0.5e-9)
        self.time = np.array(d.time)
        self.isink = np.array([-np.array(d[f"i(vcb{j})"]) for j in range(N)])
        self.vaxp, self.vaxn = np.array(d["vaxp"]), np.array(d["vaxn"])
        self.ivdd, self.ivcm = -np.array(d["i(vsup)"]), -np.array(d["i(vcm)"])
        return self

    # -- measurements ------------------------------------------------------------------
    def _win(self, t0, t1):
        return (self.time >= t0) & (self.time <= t1)

    def dmac(self, p, cal=None):
        """Delta mac per column [code units] of pass p: sunk charge / q_unit; with `cal`,
        minus the per-chip window pedestal c0 if the pass opened a B window."""
        w = self._win(p["tr"], p["t1"])
        d = np.trapezoid(self.isink[:, w], self.time[w], axis=1) / Q_UNIT
        if cal is not None and self.window(p) is not None:
            d = d - cal["c0"]
        return d

    def window(self, p):
        """(t0, t1) of pass p's B window from the column currents (half of the peak of
        their summed magnitude), or None when no window opened."""
        w = self._win(p["tr"], p["t1"])
        s = np.abs(self.isink[:, w]).sum(axis=0)
        if s.max() < 1e-9:
            return None
        act = self.time[w][s > 0.5 * s.max()]
        return act[0], act[-1]

    def plateau(self, p, frac=0.25):
        """Mean colb current per column over the middle of pass p's B window."""
        t0, t1 = self.window(p)
        w = self._win(t0 + frac * (t1 - t0), t1 - frac * (t1 - t0))
        return self.isink[:, w].mean(axis=1)

    def slope(self, p):
        """Ramp rate |dV/dt| of the larger integrator: fit from 5 ns after ramp_en (past
        the switch kick) until 10 mV above vth."""
        i = np.argmin(np.abs(self.time - (p["tr"] - 2e-9)))
        v = self.vaxp if self.vaxp[i] >= self.vaxn[i] else self.vaxn
        w = self._win(p["tr"] + 5e-9, p["t1"]) & (v > VCM - SZ["v_ped"] + 10e-3)
        w &= np.cumprod(w | (self.time < p["tr"] + 5e-9)).astype(bool)   # first stretch
        return abs(np.polyfit(self.time[w], v[w], 1)[0])

    def ax_swing(self, p):
        """(vaxp - vcm, vaxn - vcm) at the end of the window."""
        i = np.argmin(np.abs(self.time - (p["tr"] - 2e-9)))
        return self.vaxp[i] - VCM, self.vaxn[i] - VCM

    def energy(self, t0, t1):
        w = self._win(t0, t1)
        return (np.trapezoid(self.ivdd[w], self.time[w]) * VDD
                + np.trapezoid(self.ivcm[w], self.time[w]) * VCM)


# -- calibration -----------------------------------------------------------------------
CAL_B = [1, 2, 3, 4, 5, 6, 7, -1, -2, -3, -4, -5, -6, -7, 7, -7]   # every level, both signs


def cal_program(run, a_rest=None):
    """Program the calibration reference: A rows 0..CAL_ROWS-1 = +7 (others from
    a_rest), B = CAL_B."""
    a = {i: WMAX for i in range(CAL_ROWS)}
    a.update(a_rest or {})
    run.program(a, dict(enumerate(CAL_B)))


def cal_passes(run):
    """The two reference passes: +CAL_X / -CAL_X on the reference rows (P / N side)."""
    x = np.zeros(N, int)
    x[:CAL_ROWS] = CAL_X
    return run.lora_pass(x, "lo", "cal+"), run.lora_pass(-x, "lo", "cal-")


def calibrate(run, pp, pn, b_codes=CAL_B):
    """Level table, mirror gain, rho and the window pedestal c0 from the two reference
    passes. c0 is the charge the colb steering switch leaves on a column each time a B
    window opens and closes (same on every column, any B): fitted with rho as
    Delta mac = rho * B_eff * (A_eff . x) + c0 and subtracted like a zero point.

    levels[m] = direct-cell (sink) current at |B| = m over that at 7, from the plateau
    of the long reference window (pos window: bpd for B > 0; neg window: bnd for B < 0);
    km = mirror-path current over the direct one at the same level; rho = least-squares
    Delta mac = rho * B_eff * (A_eff . x) over both passes and all columns, and rho_phys
    = dV_ax I_B7 / (W_MAX^2 sum(m) slope q_unit) from the integrator swing and ramp rate
    (C_int cancels) as a cross-check."""
    b = np.array(b_codes)
    ip, ineg = run.plateau(pp), run.plateau(pn)
    # pos window (A.x > 0): B > 0 -> bpd sinks, B < 0 -> bnm sources;
    # neg window (A.x < 0): B < 0 -> bnd sinks, B > 0 -> bpm sources
    direct = np.where(b > 0, ip, ineg)
    mirror = np.where(b > 0, -ineg, -ip)
    lv = np.zeros(WMAX + 1)
    km = []
    for m in range(1, WMAX + 1):
        sel = np.abs(b) == m
        lv[m] = direct[sel].mean()
        km.append(mirror[sel].mean() / lv[m])
    i7 = lv[WMAX]
    levels = lv / i7
    beff = eff(b, levels)
    x = np.zeros(N)
    x[:CAL_ROWS] = CAL_X
    ax = WMAX * levels[WMAX] * x.sum()           # A_eff . x of the + pass
    g = np.concatenate([beff * ax, -beff * ax])
    meas = np.concatenate([run.dmac(pp), run.dmac(pn)])
    (rho, c0), *_ = np.linalg.lstsq(np.column_stack([g, np.ones_like(g)]), meas, rcond=None)
    dv = run.ax_swing(pp)[0]
    rho_phys = dv * i7 / (WMAX ** 2 * x.sum() * run.slope(pp) * Q_UNIT)
    return {"levels": [float(v) for v in levels], "km": [float(k) for k in km],
            "rho": float(rho), "c0": float(c0), "rho_phys": float(rho_phys),
            "i_b7": float(i7), "slope": float(run.slope(pp)), "dv_ax": float(dv),
            "resid": float(np.max(np.abs(meas - rho * g - c0)))}


def golden_dmac(a_vals, b_vals, xq, cal, window="lo"):
    """scripts/golden/model.py LoRA term of one window: tile_mvm with a zero tile."""
    t = G.tile_mvm(np.zeros((N, N), int), np.asarray(xq), 1,
                   lora=(eff(a_vals, cal["levels"]), eff(b_vals, cal["levels"]), cal["rho"]))
    return t["mac_lo" if window == "lo" else "mac_hi"]


def tol(gold):
    """Per-column acceptance: max(TOL_ABS code units, TOL_REL of the reading)."""
    return np.maximum(TOL_ABS, TOL_REL * np.abs(gold))


TOL_ABS = 1.0        # one converter LSB (D = 1)
SWING_MAX = 1.5 * specs.V_SWING   # A integrator: the LORA_AX_MAX budget is set at the
                                  # nominal cell current (V_SWING); fast corners carry up
                                  # to ~1.2x more (per-chip budget = cal i_b7), inside the
                                  # OTA's measured +-370 mV range (ota doc)
TOL_REL = 0.05       # architecture.md section 4: outer-product column error <= 5 %


def ax_budget_ok(a_vals, xq, levels, window="lo"):
    """Compiler constraint: per side sum(level * nibble) <= LORA_AX_MAX."""
    sign, hi, lo = G.pwm_nibbles(np.asarray(xq))
    m = lo if window == "lo" else hi
    a = np.asarray(a_vals)
    s = np.sign(a) * sign
    lvl = np.asarray(levels)[np.abs(a)] * m
    return max(lvl[s > 0].sum(), lvl[s < 0].sum()) <= specs.LORA_AX_MAX


def coherent_x(rng, a, levels, rows=range(N)):
    """INT8 x with sign(x_i) = sign(A_i) (no cancellation in A.x), row by row while both
    windows stay inside the LORA_AX_MAX budget: the large-signal verification vector."""
    x = np.zeros(N, int)
    for i in rows:
        if a[i] == 0:
            continue
        x[i] = int(np.sign(a[i])) * (16 * int(rng.integers(3, 8)) + int(rng.integers(8, 16)))
        if not (ax_budget_ok(a, x, levels, "lo") and ax_budget_ok(a, x, levels, "hi")):
            x[i] = 0
    return x


def random_case(rng, levels, a_fixed=None, rows=range(N), hi=False):
    """Random signed A (rows), B and INT8 x whose LO (and HI) window meet the budget."""
    while True:
        a = np.zeros(N, int)
        a[list(rows)] = rng.integers(-WMAX, WMAX + 1, len(rows))
        if a_fixed:
            for i, v in a_fixed.items():
                a[i] = v
        b = rng.integers(-WMAX, WMAX + 1, N)
        x = np.zeros(N, int)
        x[list(rows)] = rng.integers(-127 if hi else -15, 128 if hi else 16, len(rows))
        if ax_budget_ok(a, x, levels, "lo") and (not hi or ax_budget_ok(a, x, levels, "hi")):
            return a, b, x
