"""R-string ladder + tap mux: monotone taps, tap accuracy, static power, CDAC kick hold.

Spec rows (analog/rstring_ladder/docs/architecture.md):
  16 taps strictly monotone over the 0.8 V converter test band around vcm
  |tap error| < 2 mV (AnalogIOC tb_rstring)
  string power <= specs.P_LADDER_BUDGET at that band (the r_seg() sizing law)
  kick: a C_KICK_CDAC load precharged V_KICK below mid tap 7 (worst Thevenin) is slammed
        onto `out` through a TG (the CDAC's sampling switch, KICK_SCALE x the mux TG);
        `out` must spend < T_KICK outside +-V_TAP_TOL of its pre-kick value.

Adapted from AnalogIOC analog/testbenches/tb_rstring.py (ngspice batch -> SpiceRack).
AnalogIOC's kick run used `uic` + an .ic per tap; here the OP sets the decaps and only the
CDAC node is forced (.ic without uic), which holds on every DUT.
"""
import sys
from pathlib import Path

A = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(A / "docs"), str(A / "common"), str(A / "rstring_ladder" / "netlist"),
                str(A / "cmos_switch" / "netlist")]
import cmos_switch  # noqa: E402
import rstring_ladder as rl  # noqa: E402
import specs  # noqa: E402
from bench import Report, testbench  # noqa: E402
from devices import deck  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402

PORTS = rl.PORTS
VDD = get_pdk().vdd
VCM = specs.VCM_FRAC * VDD
BAND = 0.8          # V, specs.r_seg()'s worst rail-to-rail converter band
VRN, VRP = VCM - BAND / 2, VCM + BAND / 2
T_SLOT = 100e-9
C_LOAD = 20e-15
ERR_MAX = 2e-3
K_KICK = 7          # mid-string tap: worst Thevenin 15R/4
T_KICK_AT = 50e-9
# golden model parameters from the same derivations as the netlist
VA = dict(rseg=specs.r_seg(), rout=rl.r_mux_budget() / rl.CORNER_GUARD)
TIGHT = dict(reltol=1e-4, abstol=1e-12, vntol=1e-6, method="gear")


def rails(tb, vrn, vrp):
    tb.options(**TIGHT)
    tb.V(name="sup", positive="vdd", negative="0", value=VDD)
    tb.V(name="ss", positive="vss", negative="0", value=0.0)
    tb.V(name="rp", positive="vrp", negative="0", value=vrp)
    tb.V(name="rn", positive="vrn", negative="0", value=vrn)


def code_pwl(bit, codes, t_slot):
    pts = [(0, VDD if codes[0] >> bit & 1 else 0.0)]
    for k, code in enumerate(codes[1:], 1):
        v = VDD if code >> bit & 1 else 0.0
        if v != pts[-1][1]:
            pts += [(k * t_slot, pts[-1][1]), (k * t_slot + 0.5e-9, v)]
    return pts + [(len(codes) * t_slot, pts[-1][1])]


def sweep(vrn=VRN, vrp=VRP, corner="", seed=None):
    """Codes 0..15, one slot each -> (settled out per code [V], string current [A])."""
    tb = testbench("rstring_ladder", PORTS, corner=corner, **VA)
    if seed is not None:
        tb.options(seed=seed)
    rails(tb, vrn, vrp)
    codes = list(range(rl.N_TAPS))
    for b in range(rl.N_BITS):
        tb.PieceWiseLinearVoltageSource(name=f"b{b}", positive=f"b{b}", negative="0",
                                        values=code_pwl(b, codes, T_SLOT))
    tb.C(name="load", positive="out", negative="0", value=C_LOAD)
    tb.save("V(out)", "I(Vrp)")
    d = tb.transient(step_time=0.5e-9, end_time=len(codes) * T_SLOT)
    t = d.time

    def at(sig, tq):
        return sig[min(range(len(t)), key=lambda i: abs(t[i] - tq))]
    finals = [at(d["out"], (k + 1) * T_SLOT - 2e-9) for k in codes]
    return finals, abs(at(d["i(vrp)"], T_SLOT - 2e-9))    # code 0: no DC through the mux


def kick():
    """-> (pre-kick out [V], peak disturbance [V], time outside +-V_TAP_TOL [s])."""
    tg = rl.sizes()["tg"]
    ksw = cmos_switch.build("kick_sw", w_n=round(rl.KICK_SCALE * tg["w_n"], 2), l_n=tg["l_n"],
                            w_p=round(rl.KICK_SCALE * tg["w_p"], 2), l_p=tg["l_p"])
    tb = testbench("rstring_ladder", PORTS, **VA)
    rails(tb, VRN, VRP)
    for b in range(rl.N_BITS):
        tb.V(name=f"b{b}", positive=f"b{b}", negative="0", value=VDD * (K_KICK >> b & 1))
    tb.extra_line(deck(ksw).rstrip())
    tb.extra_line("Xksw out cnode kick kick_b vdd vss kick_sw")
    edge = [(0, 0), (T_KICK_AT, 0), (T_KICK_AT + 0.2e-9, VDD), (120e-9, VDD)]
    tb.PieceWiseLinearVoltageSource(name="kick", positive="kick", negative="0", values=edge)
    tb.PieceWiseLinearVoltageSource(name="kickb", positive="kick_b", negative="0",
                                    values=[(t, VDD - v) for t, v in edge])
    tb.C(name="cdac", positive="cnode", negative="0", value=specs.C_KICK_CDAC)
    tb.initial_condition(cnode=VRN + K_KICK * (VRP - VRN) / 15 - specs.V_KICK)
    tb.save("V(out)", "V(cnode)")
    d = tb.transient(step_time=0.05e-9, end_time=120e-9)
    t, v = d.time, d["out"]
    v0 = v[min(range(len(t)), key=lambda i: abs(t[i] - (T_KICK_AT - 1e-9)))]
    post = [(ti, abs(vi - v0)) for ti, vi in zip(t, v) if ti > T_KICK_AT]
    out = [ti for ti, dv in post if dv > specs.V_TAP_TOL]
    return v0, max(dv for _, dv in post), (out[-1] - T_KICK_AT) if out else 0.0


def main():
    r = Report("rstring_ladder")
    lsb = (VRP - VRN) / 15
    finals, i_str = sweep()
    err = [f - (VRN + k * lsb) for k, f in enumerate(finals)]
    for k, (f, e) in enumerate(zip(finals, err)):
        print(f"    tap {k:2d}: {f * 1e3:8.2f} mV (err {e * 1e3:+.3f} mV)")
    r.check("16 taps strictly monotone", all(b > a for a, b in zip(finals, finals[1:])))
    worst = max(abs(e) for e in err)
    r.check(f"|tap error| < {ERR_MAX * 1e3:.0f} mV", worst < ERR_MAX, f"worst {worst * 1e3:.3f} mV")
    p = i_str * (VRP - VRN)
    r.check("string power <= P_LADDER_BUDGET", p <= specs.P_LADDER_BUDGET,
            f"{p * 1e6:.2f} uW, budget {specs.P_LADDER_BUDGET * 1e6:.1f} uW")
    v0, peak, t_out = kick()
    r.check(f"kick held: < {rl.T_KICK * 1e9:.0f} ns outside +-{specs.V_TAP_TOL * 1e3:.1f} mV",
            t_out < rl.T_KICK, f"tap7 {v0 * 1e3:.2f} mV, peak {peak * 1e3:.2f} mV, "
            f"outside {t_out * 1e9:.2f} ns")
    r.done()


if __name__ == "__main__":
    main()
