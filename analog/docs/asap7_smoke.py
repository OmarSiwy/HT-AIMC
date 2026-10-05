"""ASAP7 on ESPice: smoke checks of the BSIM-CMG models (seconds, once VerA has compiled
the model; the first run ever compiles it, ~4 min, cached in ~/.cache/espice).

    python3 analog/docs/asap7_smoke.py         (needs espice on PATH and $ASAP7_ROOT)

  1. Id-Vg, 1 fin, |VDS| = 0.7 V, TT 25 C, all 8 devices: Idsat and Ioff against the
     published ASAP7 tables (Clark et al., Microelectronics J. 53 (2016), Tables 3/4):
     Idsat within 15 %, Ioff within 5x, SS 58-70 mV/dec
  2. corners: Idsat(FF) > Idsat(TT) > Idsat(SS); Id-Vd of nmos/pmos_rvt saturates
  3. NFIN=10 equals NFIN=5 NF=2 (devices.fet folds m into NF)
  4. inverter (2+2 fins, RVT) at 0.7 V: DC transfer (VM, gain) and transient delay into
     1 and 3 fF -> t_inv_ps_per_ff; off-FET drain cap per um of W -> cd_n/p_ff_um
  5. if `ngspice` is on PATH: the same Id-Vg and transfer curve from ngspice with the
     OSDI build of the same BSIM-CMG source ($ASAP7_ROOT/models/osdi), must agree
Prints PASS/FAIL per check and exits non-zero on any failure.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gmid import _espice  # noqa: E402
from pdk_specs import asap7_root, get_pdk  # noqa: E402

P = get_pdk("asap7")
VDD = P.vdd
# MEJ Tables 3/4, per fin, TT 25 C: (Idsat uA, Ioff nA)
PUB = {"nmos_sram": (28.57, 0.001), "nmos_rvt": (37.85, 0.019), "nmos_lvt": (45.19, 0.242),
       "nmos_slvt": (50.79, 2.444), "pmos_sram": (26.90, 0.004), "pmos_rvt": (32.88, 0.023),
       "pmos_lvt": (39.88, 0.230), "pmos_slvt": (45.60, 2.410)}
ok = True


def check(label, passed, detail=""):
    global ok
    ok &= bool(passed)
    print(f"  {'PASS' if passed else 'FAIL'}  {label}" + (f"  ({detail})" if detail else ""))


def lib(corner="tt", temp=27):
    return "\n".join(P.model_lines(corner)) + f"\n.temp {temp}\n"


def idvg(models, corner="tt", temp=25, n=71):
    """{model: |Id|(VGS)} at |VDS| = VDD, 1 fin; one deck, every device on gate g."""
    deck = lib(corner, temp) + "vg g 0 0\negn gn 0 g 0 1\negp gp 0 g 0 -1\n"
    for m in models:
        s = 1 if m.startswith("n") else -1
        deck += f"vd_{m} d_{m} 0 {s * VDD}\nM_{m} d_{m} g{'n' if s > 0 else 'p'} 0 0 {m} " \
                f"L={P.um(P.min_l)} NFIN=1\n"
    r = _espice(deck + f".dc vg 0 {VDD} {VDD / (n - 1)}\n")
    return r["v(v-sweep)"], {m: np.abs(r[f"i(vd_{m})"]) for m in models}


def inverter(load_ff=0.0, tran=False):
    deck = lib() + f"vdd vdd 0 {VDD}\nMp out in vdd vdd {P.pfet} L={P.um(P.min_l)} NFIN=2\n" \
        f"Mn out in 0 0 {P.nfet} L={P.um(P.min_l)} NFIN=2\n"
    if not tran:
        return _espice(deck + "vin in 0 0\n.dc vin 0 0.7 0.005\n")
    return _espice(deck + f"vin in 0 pulse(0 {VDD} 10p 5p 5p 100p 200p)\ncl out 0 {load_ff}f\n"
                   ".tran 0.1p 220p\n")


def tpd(r):
    """Mean of the falling (input rise) and rising output 50 % delays, s."""
    t, vi, vo = r["time"], r["v(in)"], r["v(out)"]
    half = VDD / 2

    def cross(v, rising, after):
        i = np.where((t[:-1] > after) & ((v[:-1] < half) == rising)
                     & ((v[1:] >= half) == rising))[0][0]
        return t[i] + (half - v[i]) * (t[i + 1] - t[i]) / (v[i + 1] - v[i])
    t_in_r = cross(vi, True, 0)
    t_in_f = cross(vi, False, t_in_r)
    return ((cross(vo, False, t_in_r) - t_in_r) + (cross(vo, True, t_in_f) - t_in_f)) / 2


def drain_cap(model, f=1e6, nfin=10):
    """Off-FET drain cap per um of W (fF/um), drain at VDD/2, gate = source = bulk."""
    s = 1 if model.startswith("n") else -1
    r = _espice(lib() + f"vd d 0 {s * VDD / 2} ac 1\nM1 d 0 0 0 {model} L={P.um(P.min_l)} "
                f"NFIN={nfin}\n.ac lin 1 {f:g} {f:g}\n")
    return abs(r["i(vd)"][0].imag) / (2 * np.pi * f) / (nfin * P.w_fin) * 1e15


def ngspice(deck, vecs):
    """Run deck under ngspice with the OSDI BSIM-CMG (OSDI devices are N cards in ngspice);
    wrdata `vecs` -> array (x, v1, v2...)."""
    osdi = asap7_root() / "models" / "osdi" / "bsimcmg.osdi"
    with tempfile.TemporaryDirectory() as d:
        body, analysis = deck
        (Path(d) / "c.sp").write_text(
            "* ngspice ref\n" + body + f".control\npre_osdi {osdi}\n{analysis}\n"
            f"wrdata {d}/o.txt {' '.join(vecs)}\n.endc\n.end\n")
        r = subprocess.run(["ngspice", "-b", "c.sp"], cwd=d, capture_output=True, text=True,
                           timeout=300)
        if not (Path(d) / "o.txt").exists():
            raise RuntimeError("ngspice wrote nothing:\n" + (r.stdout + r.stderr)[-1500:])
        a = np.loadtxt(Path(d) / "o.txt", ndmin=2)
    return np.column_stack([a[:, 0]] + [a[:, 2 * i + 1] for i in range(len(vecs))])


def main():
    print(f"== ASAP7 smoke (ESPice, BSIM-CMG via VerA, $ASAP7_ROOT={asap7_root()}) ==")
    vg, ids = idvg(list(PUB))
    print(f"  {'device':<10}{'Idsat uA':>10}{'(pub)':>8}{'Ioff pA':>10}{'(pub)':>8}{'SS mV/dec':>11}")
    for m, (isat_pub, ioff_pub) in PUB.items():
        i = ids[m]
        isat, ioff = i[-1] * 1e6, i[0] * 1e12
        # steepest subthreshold slope (below 1e-7 A; the SRAM floor at VGS=0 is GIDL)
        sub = (i[1:] < 1e-7) & (i[:-1] > 0)
        ss = 1e3 * np.min(np.diff(vg)[sub] / np.diff(np.log10(i))[sub])
        print(f"  {m:<10}{isat:>10.2f}{isat_pub:>8.2f}{ioff:>10.2f}{ioff_pub * 1e3:>8.1f}"
              f"{ss:>11.1f}")
        check(f"{m} Idsat within 15 % of MEJ", abs(isat / isat_pub - 1) < 0.15,
              f"{isat / isat_pub - 1:+.1%}")
        # 5x: nmos_sram's Ioff is GIDL-limited at 4.9x the paper (which predates the
        # 160803 cards); every other device is within 0.5-1x
        check(f"{m} Ioff within 5x of MEJ", 1 / 5 < ioff / (ioff_pub * 1e3) < 5,
              f"x{ioff / (ioff_pub * 1e3):.2f}")
        check(f"{m} SS 58-70 mV/dec", 58 < ss < 70, f"{ss:.1f}")

    isat = {c: idvg(["nmos_rvt", "pmos_rvt"], c)[1] for c in ("ff", "ss")}
    for m in ("nmos_rvt", "pmos_rvt"):
        ff, tt, ss = isat["ff"][m][-1], ids[m][-1], isat["ss"][m][-1]
        check(f"{m} corners FF > TT > SS", ff > tt > ss,
              f"{ff * 1e6:.1f} / {tt * 1e6:.1f} / {ss * 1e6:.1f} uA")

    for m, s in (("nmos_rvt", 1), ("pmos_rvt", -1)):
        r = _espice(lib() + f"vg g 0 {s * VDD}\nvd d 0 0\nM1 d g 0 0 {m} L={P.um(P.min_l)} "
                    f"NFIN=1\n.dc vd 0 {s * VDD} {s * VDD / 70}\n")
        i = np.abs(r["i(vd)"])
        check(f"{m} Id-Vd monotone and saturating", np.all(np.diff(i) > 0) and i[-1] / i[35] < 1.3,
              f"Id(0.7)/Id(0.35) = {i[-1] / i[35]:.2f}")

    r = _espice(lib() + "vg g 0 0.5\nvd1 d1 0 0.5\nvd2 d2 0 0.5\n"
                f"M1 d1 g 0 0 nmos_rvt L={P.um(P.min_l)} NFIN=10\n"
                f"M2 d2 g 0 0 nmos_rvt L={P.um(P.min_l)} NFIN=5 NF=2\n.dc vg 0.5 0.5 0.1\n")
    a, b = abs(r["i(vd1)"][0]), abs(r["i(vd2)"][0])
    check("NFIN=10 == NFIN=5 NF=2", abs(a / b - 1) < 0.02, f"{a * 1e6:.2f} vs {b * 1e6:.2f} uA")

    dc = inverter()
    vi, vo = dc["v(v-sweep)"], dc["v(out)"]
    vm = float(np.interp(0, -(vo - vi), vi))
    gain = float(np.max(-np.gradient(vo, vi)))
    check("inverter VM near VDD/2", 0.25 < vm < 0.45, f"VM = {vm:.3f} V")
    check("inverter peak gain > 5", gain > 5, f"{gain:.1f}")
    check("inverter rails", vo[0] > VDD - 0.01 and vo[-1] < 0.01, f"{vo[0]:.3f} / {vo[-1]:.4f} V")
    t1, t3 = tpd(inverter(1.0, True)), tpd(inverter(3.0, True))
    slope = (t3 - t1) / 2 * 1e12
    check("inverter tpd 1-30 ps into 1 fF", 1e-12 < t1 < 30e-12, f"{t1 * 1e12:.2f} ps")
    print(f"  info  t_inv_ps_per_ff = {slope:.2f}  (tpd 1 fF {t1 * 1e12:.2f} ps, "
          f"3 fF {t3 * 1e12:.2f} ps; 2+2-fin RVT)")
    cdn, cdp = drain_cap("nmos_rvt"), drain_cap("pmos_rvt")
    print(f"  info  cd_n_ff_um = {cdn:.3f}  cd_p_ff_um = {cdp:.3f}  (off, drain at VDD/2)")

    if shutil.which("ngspice"):
        ng = Path(asap7_root()) / "models" / "ngspice" / "asap7.lib"
        body = f'.lib "{ng}" tt\n.temp 25\nvg g 0 0\negp gp 0 g 0 -1\n' \
            f"vdn dn 0 {VDD}\nNn dn g 0 0 nmos_rvt L=21n NFIN=1\n" \
            f"vdp dp 0 {-VDD}\nNp dp gp 0 0 pmos_rvt L=21n NFIN=1\n"
        ref = ngspice((body, f"dc vg 0 {VDD} {VDD / 70}"), ["i(vdn)", "i(vdp)"])
        for col, m in ((1, "nmos_rvt"), (2, "pmos_rvt")):
            on = abs(ref[-1, col]) / ids[m][-1] - 1
            off = abs(ref[0, col]) / ids[m][0] - 1
            check(f"{m} ESPice == ngspice+OSDI", abs(on) < 1e-3 and abs(off) < 0.05,
                  f"Idsat {on:+.1e}, Ioff {off:+.1e}")
        body = f'.lib "{ng}" tt\nvdd vdd 0 {VDD}\nvin in 0 0\n' \
            "Np out in vdd vdd pmos_rvt L=21n NFIN=2\nNn out in 0 0 nmos_rvt L=21n NFIN=2\n"
        ref = ngspice((body, "dc vin 0 0.7 0.005"), ["v(out)"])
        err = float(np.max(np.abs(ref[:, 1] - vo)))
        check("inverter transfer ESPice == ngspice+OSDI", err < 1e-3, f"max |dV| = {err:.1e} V")
    else:
        print("  info  ngspice not on PATH: OSDI cross-check skipped "
              "(nix shell nixpkgs#ngspice)")
    print(f"  OVERALL: {'PASS' if ok else 'FAIL'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    os.environ.setdefault("PDK", "asap7")
    main()
