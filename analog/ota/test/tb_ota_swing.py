"""OTA output linear range, SVT vs LVT, + tau_absorb in the integrator configuration.

Spec rows (analog/ota/docs/architecture.md):
  usable single-sided output range (open-loop A0 >= 200) >= 0.9 * specs.V_SWING
  tau_absorb (integrator config, small packet) <= coarse_cadence / K_SETTLE
  informational, DUT=sch nominal only: AnalogIOC's hypothesis that an LVT rebuild at the same
  (gm/ID, L, ID) keeps >= 90 % of the SVT range (reported, not gated: the block is SVT)

Method (AnalogIOC's, kept): a unity-gain buffer sweep reports the INPUT common-mode limit,
not the output range. In the column integrator inp sits at vcm and inn is the virtual
ground, so pin both inputs at vcm, force `out` with a swept source and read
A0(Vout) = Gm / g_out. g_out = |dIo/dVout|; Gm = dIo/dVin from a second sweep with inp
raised by DV_GM (AnalogIOC probed the input device's gm — this runs on every DUT source).

LVT: W re-solved at the same gm/ID coordinate from a live DC sweep of each LVT device
(docs/gmid.py has SVT tables only), bias rails shifted by the measured dVGS, tail trimmed
to the SVT tail current. AnalogIOC's per-device OFF-leakage printout is not ported (a
device characterisation, not an OTA metric).

Adapted from AnalogIOC analog/testbenches/tb_ota_swing.py (ngspice batch -> SpiceRack).
"""
import os
import sys
from pathlib import Path

import numpy as np

A = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(A / "docs"), str(A / "common"), str(A / "ota" / "netlist"),
               str(Path(__file__).parent)]
import ota  # noqa: E402
import specs  # noqa: E402
from bench import Report, dut_kind  # noqa: E402
from ota_bench import REF_CURRENT, ota_testbench  # noqa: E402
from devices import deck, fet  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402

import spicerack as ps  # noqa: E402

PDK = get_pdk()
VDD = PDK.vdd
VCM = specs.VCM_FRAC * VDD
TIGHT = dict(reltol=1e-4, abstol=1e-12, vntol=1e-6, method="gear")
A0_MIN = 200                        # SIZING.md loop-gain law
DV_GM = 1e-3
V_SWEEP = (0.2, VDD - 0.1, 0.005)   # forced output, AnalogIOC 0.2..1.7 V


def lvt_tb(sz, b, name="ota_lvt"):
    """Testbench around an LVT build of the OTA (same wrapper nets as bench.dut), bias
    rails as fixed sources `b` (AnalogIOC's method; nominal corner only)."""
    top = ps.Subcircuit(f"tb_{name}")
    top.raw_spice(deck(ota.build(name=name, nfet="nfet_lvt", pfet="pfet_lvt", sz=sz)).rstrip())
    top.X("xdut", name, *ota.PORTS)
    tb = ps.Testbench(top)
    tb.use_pdk(PDK.model_library())
    tb.temperature = 27.0
    tb.V(name="sup", positive="vdd", negative="0", value=VDD)
    tb.V(name="ss", positive="vss", negative="0", value=0.0)
    for k, v in b.items():
        tb.V(name=k, positive=k, negative="0", value=v)
    return tb


def open_loop_tb(make, vinp):
    tb = make()
    tb.options(**TIGHT)
    tb.V(name="p", positive="inp", negative="0", value=vinp)
    tb.V(name="n", positive="inn", negative="0", value=VCM)
    tb.V(name="o", positive="out", negative="0", value=VCM)
    return tb


def swing(make, ref=0.0):
    """(Vout, A0(Vout), I_tail at vcm, Gm at vcm). `ref`: bias current also in vss."""
    lo, hi, st = V_SWEEP
    r0 = open_loop_tb(make, VCM).dc(Vo=slice(lo, hi, st))
    r1 = open_loop_tb(make, VCM + DV_GM).dc(Vo=slice(lo, hi, st))
    v = np.array(r0.sweep)
    io0, io1 = np.array(r0["i(vo)"]), np.array(r1["i(vo)"])
    g_out = np.abs(np.gradient(io0, v))
    gm = np.abs(io1 - io0) / DV_GM
    k0 = int(np.argmin(np.abs(v - VCM)))
    return v, gm / np.maximum(g_out, 1e-15), float(np.abs(r0["i(vss)"])[k0]) - ref, gm[k0]


def linear_range(v, a0, a0_min):
    """Contiguous interval around VCM with A0 >= a0_min -> (lo, hi, single-sided)."""
    ok = a0 >= a0_min
    k = int(np.argmin(np.abs(v - VCM)))
    if not ok[k]:
        return None, None, 0.0
    lo = hi = k
    while lo > 0 and ok[lo - 1]:
        lo -= 1
    while hi < len(ok) - 1 and ok[hi + 1]:
        hi += 1
    return float(v[lo]), float(v[hi]), float(min(VCM - v[lo], v[hi] - VCM))


def tau_absorb():
    """Integrator config: inp = vcm, C_int out->vg, C_par_vg on vg, kick-filter C on
    out. A small charge packet on vg (a big one slews); fit the 50 %..5 % decay of
    v(out) — the loop pole the coarse cadence is built on."""
    cal = specs.cal()
    t0, t_end, q = 50e-9, 400e-9, 3e-15 * VDD
    tb = ota_testbench()
    tb.options(**TIGHT)
    tb.V(name="cm", positive="inp", negative="0", value=VCM)
    tb.V(name="vg", positive="inn", negative="vg", value=0.0)
    tb.C(name="int", positive="out", negative="vg", value=specs.c_int())
    # DC path for the op: R*C_int = 200 ms >> the ~30 ns pole under test
    tb.R(name="f", positive="out", negative="vg", value=1e9)
    tb.C(name="par", positive="vg", negative="0", value=cal["c_par_vg"])
    tb.C(name="filt", positive="out", negative="0", value=specs.kick_filter()[1])
    tb.PieceWiseLinearCurrentSource(
        name="inj", positive="0", negative="vg",
        values=[(0, 0), (t0, 0), (t0 + 0.1e-9, q / 1e-9), (t0 + 1.1e-9, q / 1e-9),
                (t0 + 1.2e-9, 0), (t_end, 0)])
    tb.save("V(out)")
    r = tb.transient(step_time=0.05e-9, end_time=t_end)
    t, v = np.array(r.time), np.array(r["out"])
    m = t > t0 + 2e-9
    v0, vf = v[m][0], v[-1]
    rel = np.abs(v[m] - vf) / max(abs(v0 - vf), 1e-12)
    good = (rel < 0.5) & (rel > 0.05)
    if good.sum() < 10:
        return None
    return float(-1.0 / np.polyfit(t[m][good], np.log(rel[good]), 1)[0])


def gmid_point(kind, L, target):
    """(|VGS|, J_D [A/um]) at gm/ID = target on the inversion side, from a live DC sweep
    of a W = 10 um device at |VDS| = VDD/2 (AnalogIOC gmid_point)."""
    pol = 1 if kind.startswith("nfet") else -1
    top = ps.Subcircuit(f"gmid_{kind}")
    fet(top, "m1", "d", "g", "0", "0", kind, 10.0, L)
    tb = ps.Testbench(top)
    tb.use_pdk(PDK.model_library())
    tb.V(name="g", positive="g", negative="0", value=0.0)
    tb.V(name="d", positive="d", negative="0", value=pol * VDD / 2)
    r = tb.dc(Vg=slice(0.0, pol * VDD, pol * 0.005))
    vgs, i_d = np.abs(np.array(r.sweep)), np.abs(np.array(r["i(vd)"]))
    gmid = np.gradient(i_d, vgs) / np.maximum(i_d, 1e-15)
    k = int(np.argmax(np.where(i_d > 1e-11, gmid, 0)))   # past the leakage floor
    k += int(np.argmin(np.abs(gmid[k:] - target)))
    return float(vgs[k]), float(i_d[k] / 10.0)


def lvt_design():
    """LVT sizes + bias at the SVT coordinates (AnalogIOC build("lvt"))."""
    b = dict(ota.bias())
    sz, dvgs = {}, {}
    for role, (g, _, typ) in specs.OTA_COORDS.items():
        L = specs.ota_L(role, PDK)
        i_d = 2 * specs.I_SIDE if role == "ota_tail" else specs.I_SIDE
        vgs_l, j_l = gmid_point(typ + "_lvt", L, g)
        vgs_s, _ = gmid_point(typ, L, g)
        # sky130 LVT devices bin from W = min_w (AnalogIOC: "could not find a valid
        # modelname" below it)
        sz[role] = (round(max(i_d / j_l, PDK.min_w), 2), L)
        dvgs[role] = vgs_l - vgs_s
    # rails translate node by node: vb_tail = VGS_tail; vb_nc = vcm - VGS_in + Vds_in
    # + VGS_nc; vb_pc = y - |VGS_pc| with y held
    b["vb_tail"] += dvgs["ota_tail"]
    b["vb_nc"] += dvgs["ota_ncasc"] - dvgs["ota_in"]
    b["vb_pc"] -= dvgs["ota_pcasc"]
    return sz, b


def trim_tail(sz, b, i_target):
    """vb_tail giving the measured LVT tail current i_target (matched-gm comparison)."""
    tb = open_loop_tb(lambda: lvt_tb(sz, b), VCM)
    r = tb.dc(Vvb_tail=slice(b["vb_tail"] - 0.2, b["vb_tail"] + 0.2, 0.002))
    i = np.abs(np.array(r["i(vss)"]))
    return float(np.array(r.sweep)[int(np.argmin(np.abs(i - i_target)))])


def report_range(tag, v, a0, itail, gm):
    k0 = int(np.argmin(np.abs(v - VCM)))
    print(f"  {tag}: I_tail {itail * 1e6:.2f} uA, Gm {gm * 1e6:.1f} uS, A0(vcm) {a0[k0]:.0f}")
    for a_min in (909, A0_MIN, 100):
        lo, hi, ss = linear_range(v, a0, a_min)
        print(f"    A0 >= {a_min:<4}: " + (f"[{lo:.3f}, {hi:.3f}] V -> +-{ss * 1e3:.0f} mV"
                                         if lo is not None else "EMPTY at vcm"))
    print("    A0 vs Vout: " + " ".join(
        f"{x:.2f}:{a0[int(np.argmin(np.abs(v - x)))]:.0f}"
        for x in (0.5, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3)))
    return linear_range(v, a0, A0_MIN)[2]


def main():
    r = Report("ota linear range + tau_absorb")
    v, a0, itail, gm = swing(ota_testbench, REF_CURRENT)
    ss = report_range(dut_kind(), v, a0, itail, gm)
    r.check(f"range (A0 >= {A0_MIN}) >= 0.9 * V_SWING", ss >= 0.9 * specs.V_SWING,
            f"+-{ss * 1e3:.0f} mV vs V_SWING {specs.V_SWING * 1e3:.0f} mV")

    ta = tau_absorb()
    budget = specs.coarse_cadence() / specs.K_SETTLE
    r.check(f"tau_absorb <= cadence/K_SETTLE = {budget * 1e9:.0f} ns",
            ta is not None and ta <= budget,
            f"{'n/a' if ta is None else f'{ta * 1e9:.1f} ns'}, "
            f"specs formula {specs.tau_absorb() * 1e9:.1f} ns")

    if dut_kind() != "sch" or "CORNER" in os.environ or "TEMP" in os.environ:
        print("  LVT vs SVT: skipped (informational, DUT=sch at the nominal corner only)")
        r.done()
    sz, bl = lvt_design()
    vb = trim_tail(sz, bl, itail)
    print(f"  LVT: W " + " ".join(f"{k[4:]}={w:.2f}" for k, (w, _) in sz.items())
          + f"  vb_tail {bl['vb_tail']:.3f} -> {vb:.3f} V (trimmed to SVT tail)")
    bl["vb_tail"] = vb
    vl, a0l, itl, gml = swing(lambda: lvt_tb(sz, bl))
    ssl = report_range("lvt", vl, a0l, itl, gml)
    # AnalogIOC asserted this as a hypothesis under test; the block is SVT, so the outcome
    # is reported, not gated (measured: refuted — LVT A0 is ~4x lower at these L).
    hyp = ssl > 0.9 * ss
    print(f"  {'HOLDS' if hyp else 'REFUTED'}  hypothesis: LVT keeps >= 90 % of SVT range "
          f"(+-{ssl * 1e3:.0f} vs +-{ss * 1e3:.0f} mV)  [informational]")
    r.done()


if __name__ == "__main__":
    main()
