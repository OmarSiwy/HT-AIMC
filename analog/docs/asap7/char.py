"""ASAP7 characterisation for analog IMC (ESPice, BSIM-CMG via VerA). Method + results: CHAR.md.

    python3 analog/docs/asap7/char.py <stage> [...]     stages: gmid inv leak sw cmp lib const
Each stage measures with the PDK's own cards (pdk_specs.Asap7.model_lines), merges its
numbers into results.json (next to this file) and asserts its self-checks (exit 1 on FAIL).
Every espice call must run under the machine-wide SPICE lock: wrap the whole invocation in
`flock -w 900 <lock> timeout 1200 ...` (see CHAR.md). `lib` reads the ASAP7 liberty and `const`
(both no SPICE) fold results.json and the literature/DRM-derived entries into
scripts/compiler/metrics/arch_eval/asap7_constants.json.
"""
import json
import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
os.environ.setdefault("PDK", "asap7")
from gmid import _espice  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402

P = get_pdk("asap7")
VDD = P.vdd
L = "21n"                       # ASAP7 has one drawn gate length
RES = HERE / "results.json"
FLAVORS = ("rvt", "lvt", "slvt")
OK = True


def check(label, passed, detail=""):
    global OK
    OK &= bool(passed)
    print(f"  {'PASS' if passed else 'FAIL'}  {label}" + (f"  ({detail})" if detail else ""))


def lib(corner="tt", temp=27):
    return "\n".join(P.model_lines(corner)) + f"\n.temp {temp}\n"


def save(key, val):
    d = json.loads(RES.read_text()) if RES.exists() else {}
    d[key] = val
    RES.write_text(json.dumps(d, indent=1, sort_keys=True))


# ── (2) gm/ID tables ────────────────────────────────────────────────────────
def gmid(n=71, f=1e6, vds=VDD / 2):
    """Per device flavour, NFIN 1-4, VGS 0..VDD at |VDS| = VDD/2, TT 27 C. DC deck for ID;
    one AC deck with a device copy per (nfin, VGS) for gm (ac on gate), gds (ac on drain)
    and Cgg (= Im(i_gate)/w with drain/source AC-grounded)."""
    out = HERE / "gmid"
    out.mkdir(exist_ok=True)
    vgs = np.linspace(0, VDD, n)
    summary = {}
    for pol, ch in ((1, "nmos"), (-1, "pmos")):
        for fl in FLAVORS:
            m = f"{ch}_{fl}"
            dc = lib() + "vg g 0 0\n" + "".join(
                f"vd{k} d{k} 0 {pol * vds}\nM{k} d{k} g 0 0 {m} L={L} NFIN={k}\n" for k in (1, 2, 3, 4))
            r = _espice(dc + f".dc vg 0 {pol * VDD} {pol * VDD / (n - 1)}\n")
            ac = lib() + "".join(
                f"vga{k}_{i} ga{k}_{i} 0 {pol * v} ac 1\nvda{k}_{i} da{k}_{i} 0 {pol * vds}\n"
                f"Ma{k}_{i} da{k}_{i} ga{k}_{i} 0 0 {m} L={L} NFIN={k}\n"
                f"vgb{k}_{i} gb{k}_{i} 0 {pol * v}\nvdb{k}_{i} db{k}_{i} 0 {pol * vds} ac 1\n"
                f"Mb{k}_{i} db{k}_{i} gb{k}_{i} 0 0 {m} L={L} NFIN={k}\n"
                for k in (1, 2, 3, 4) for i, v in enumerate(vgs)) + f".ac lin 1 {f:g} {f:g}\n"
            a = _espice(ac)
            for k in (1, 2, 3, 4):
                i_d = np.abs(r[f"i(vd{k})"])
                gm = np.array([abs(a[f"i(vda{k}_{i})"][0].real) for i in range(n)])
                gds = np.array([abs(a[f"i(vdb{k}_{i})"][0].real) for i in range(n)])
                cgg = np.array([abs(a[f"i(vga{k}_{i})"][0].imag) / (2 * np.pi * f) for i in range(n)])
                keep = vgs > 0
                tab = np.column_stack([vgs, gm / i_d, i_d / k, gm / gds, cgg / k,
                                       gm / (2 * np.pi * cgg), i_d, gm, gds])[keep]
                hdr = (f"ASAP7 {m} L=21nm NFIN={k} |VDS|={vds:g} V tt 27C, ESPice BSIM-CMG "
                       f"(gm,gds,Cgg from AC at {f:g} Hz). MEASURED.\n"
                       "VGS_V,gm_id_per_V,id_per_fin_A,gm_gds,cgg_per_fin_F,ft_Hz,id_A,gm_S,gds_S")
                np.savetxt(out / f"{m}_nfin{k}.csv", tab, delimiter=",", header=hdr, fmt="%.6e")
                if k == 1:
                    j = int(np.argmin(abs(vgs - VDD)))
                    summary[m] = {"gm_id_max": float(np.nanmax(tab[:, 1])),
                                  "id_per_fin_vdd_uA": float(i_d[j] * 1e6),
                                  "cgg_per_fin_vdd_aF": float(cgg[j] * 1e18),
                                  "ft_peak_GHz": float(np.nanmax(tab[:, 5]) / 1e9),
                                  "gm_gds_at_gmid10": float(np.interp(-10, -tab[:, 1], tab[:, 3])),
                                  "ft_at_gmid10_GHz": float(np.interp(-10, -tab[:, 1], tab[:, 5]) / 1e9),
                                  "vgs_at_gmid10": float(np.interp(-10, -tab[:, 1], tab[:, 0]))}
                    # Vt by max-gm linear extrapolation of the DC curve at VDS = VDD/2
                    g = np.gradient(i_d, vgs)
                    jm = int(np.argmax(g))
                    summary[m]["vt_lin_extrap_V"] = float(vgs[jm] - i_d[jm] / g[jm])
                else:   # per-fin quantities are fin-count independent (FinFET quantisation)
                    t1 = np.loadtxt(out / f"{m}_nfin1.csv", delimiter=",")
                    jj = int(np.argmin(abs(t1[:, 0] - VDD)))
                    check(f"{m} id/fin NFIN={k} == NFIN=1 within 2 %",
                          abs(tab[jj, 2] / t1[jj, 2] - 1) < 0.02, f"{tab[jj, 2] / t1[jj, 2] - 1:+.2%}")
            s = summary[m]
            print(f"  {m:10s} gm/ID max {s['gm_id_max']:5.1f}  Id/fin {s['id_per_fin_vdd_uA']:6.1f} uA  "
                  f"Cgg/fin {s['cgg_per_fin_vdd_aF']:5.1f} aF  fT pk {s['ft_peak_GHz']:6.0f} GHz  "
                  f"gm/gds@10 {s['gm_gds_at_gmid10']:5.1f}  Vt {s['vt_lin_extrap_V']:.3f} V")
            check(f"{m} gm/ID max 20-40 /V (SS 60-70 mV/dec)", 20 < s["gm_id_max"] < 40)
    check("Vt order rvt > lvt > slvt (nmos)", summary["nmos_rvt"]["vt_lin_extrap_V"] >
          summary["nmos_lvt"]["vt_lin_extrap_V"] > summary["nmos_slvt"]["vt_lin_extrap_V"])
    save("gmid", summary)


# ── (3) FO4 inverter: delay and energy vs VDD and corner ────────────────────
def _cross(t, v, lvl, rising, after):
    i = np.where((t[:-1] > after) & ((v[:-1] < lvl) == rising) & ((v[1:] >= lvl) == rising))[0]
    if not len(i):
        return np.nan
    i = i[0]
    return t[i] + (lvl - v[i]) * (t[i + 1] - t[i]) / (v[i + 1] - v[i])


def inv_fo4(vdd, corner="tt", fl="rvt", nf=1):
    """Min inverter (nf+nf fins) chain s1 -> DUT -> s3, each node loaded by FO4 (DUT/s3 + 3
    dummies). DUT on its own supply: E_cycle = vdd * integral(i) over one period in steady
    state = charge of its output node (4 gate loads + own drain) + short-circuit."""
    n, p = f"nmos_{fl}", f"pmos_{fl}"
    per = 400e-12 * (0.7 / vdd) ** 3        # long enough at 0.45 V ss
    def inv(name, a, y, sup):
        return (f"Mp{name} {y} {a} {sup} {sup} {p} L={L} NFIN={nf}\n"
                f"Mn{name} {y} {a} 0 0 {n} L={L} NFIN={nf}\n")
    d = lib(corner) + f"vdd vdd 0 {vdd}\nvdut vdut 0 {vdd}\n"
    d += f"vin in 0 pulse(0 {vdd} {per / 10:g} {per / 50:g} {per / 50:g} {per / 2:g} {per:g})\n"
    d += inv("s0", "in", "a", "vdd") + inv("s1", "a", "n1", "vdd") + inv("dut", "n1", "n2", "vdut")
    d += inv("s3", "n2", "n3", "vdd") + inv("s4", "n3", "n4", "vdd")
    for k in range(3):
        d += inv(f"d1{k}", "n1", f"x1{k}", "vdd") + inv(f"d2{k}", "n2", f"x2{k}", "vdd")
        d += inv(f"d3{k}", "n3", f"x3{k}", "vdd")
    r = _espice(d + f".tran {per / 2000:g} {2.1 * per:g}\n")
    t, v1, v2 = r["time"], r["v(n1)"], r["v(n2)"]
    h = vdd / 2
    t0 = per * 1.05
    a = _cross(t, v1, h, True, t0); b = _cross(t, v2, h, False, a)       # n1 rise -> n2 fall
    c = _cross(t, v1, h, False, b); e = _cross(t, v2, h, True, c)       # n1 fall -> n2 rise
    m = (t >= per) & (t <= 2 * per)
    q = np.trapezoid(-r["i(vdut)"][m], t[m])          # charge drawn from vdut in one period
    return {"tphl_ps": (b - a) * 1e12, "tplh_ps": (e - c) * 1e12, "fo4_ps": (b - a + e - c) / 2 * 1e12,
            "E_cycle_fJ": abs(q) * vdd * 1e15, "E_trans_fJ": abs(q) * vdd / 2 * 1e15}


def inv():
    out = {}
    for c in ("tt", "ff", "ss"):
        for v in ((0.45, 0.5, 0.6, 0.7) if c == "tt" else (0.5, 0.7)):
            k = f"{c}@{v}"
            out[k] = inv_fo4(v, c)
            o = out[k]
            print(f"  {k:8s} FO4 {o['fo4_ps']:6.2f} ps (hl {o['tphl_ps']:.2f} lh {o['tplh_ps']:.2f})  "
                  f"E/transition {o['E_trans_fJ']:.3f} fJ")
    out["tt@0.7_slvt"] = inv_fo4(0.7, "tt", "slvt")
    print(f"  slvt tt@0.7 FO4 {out['tt@0.7_slvt']['fo4_ps']:.2f} ps")
    t = out["tt@0.7"]
    check("FO4 tt 0.7 V in 3-20 ps", 3 < t["fo4_ps"] < 20, f"{t['fo4_ps']:.2f}")
    check("FO4 slower at lower VDD", out["tt@0.45"]["fo4_ps"] > out["tt@0.5"]["fo4_ps"] > t["fo4_ps"])
    check("ss slower than ff", out["ss@0.7"]["fo4_ps"] > t["fo4_ps"] > out["ff@0.7"]["fo4_ps"])
    check("E ~ V^2 (0.5 vs 0.7 within 30 %)",
          abs(out["tt@0.5"]["E_trans_fJ"] / t["E_trans_fJ"] / (0.5 / 0.7) ** 2 - 1) < 0.3)
    save("inv", out)


# ── leakage and on-current per fin ──────────────────────────────────────────
def leak():
    out = {}
    for c, tc in (("tt", 27), ("ff", 27), ("ss", 27), ("tt", 85)):
        d = lib(c, tc) + "vx x 0 0\n"
        for pol, ch in ((1, "nmos"), (-1, "pmos")):
            for fl in FLAVORS + ("sram",):
                m = f"{ch}_{fl}"
                d += (f"voff_{m} doff_{m} 0 {pol * VDD}\nMoff_{m} doff_{m} 0 0 0 {m} L={L} NFIN=1\n"
                      f"von_{m} don_{m} 0 {pol * VDD}\nvgon_{m} gon_{m} 0 {pol * VDD}\n"
                      f"Mon_{m} don_{m} gon_{m} 0 0 {m} L={L} NFIN=1\n")
        r = _espice(d + ".dc vx 0 0 1\n")
        out[f"{c}@{tc}C"] = {m: {"ioff_nA": float(abs(r[f"i(voff_{m})"][0]) * 1e9),
                                "ion_uA": float(abs(r[f"i(von_{m})"][0]) * 1e6)}
                            for m in [f"{ch}_{fl}" for ch in ("nmos", "pmos") for fl in FLAVORS + ("sram",)]}
        for m, v in out[f"{c}@{tc}C"].items():
            print(f"  {c}@{tc}C {m:10s} Ion {v['ion_uA']:6.1f} uA/fin  Ioff {v['ioff_nA']:9.4f} nA/fin")
    t = out["tt@27C"]
    check("Ioff slvt > lvt > rvt (nmos)", t["nmos_slvt"]["ioff_nA"] > t["nmos_lvt"]["ioff_nA"] > t["nmos_rvt"]["ioff_nA"])
    check("Ioff hotter > 27 C", out["tt@85C"]["nmos_rvt"]["ioff_nA"] > t["nmos_rvt"]["ioff_nA"])
    save("leak", out)


# ── (4) switch Ron / Coff per fin ───────────────────────────────────────────
def sw(f=1e6):
    vg = [0.45, 0.5, 0.6, 0.7, 0.8, 0.9]
    out = {}
    for fl in FLAVORS:
        m = f"nmos_{fl}"
        d = lib() + "vx x 0 0\n"
        for i, g in enumerate(vg):
            for j, vs in enumerate((0.0, VDD / 2)):
                d += (f"vg{i}_{j} g{i}_{j} 0 {g}\nvs{i}_{j} s{i}_{j} 0 {vs}\nvd{i}_{j} d{i}_{j} 0 {vs + 0.01}\n"
                      f"M{i}_{j} d{i}_{j} g{i}_{j} s{i}_{j} 0 {m} L={L} NFIN=1\n")
        r = _espice(d + ".dc vx 0 0 1\n")
        ron = {f"vg={g}": {f"vs={vs:g}": 0.01 / abs(r[f"i(vd{i}_{j})"][0]) for j, vs in enumerate((0.0, VDD / 2))}
               for i, g in enumerate(vg)}
        # off: gate 0, drain at VDD/2 driven ac; Cdd = total, Cds = through-switch feedthrough
        a = _espice(lib() + f"vd d 0 {VDD / 2} ac 1\nvs s 0 0\nM1 d 0 s 0 {m} L={L} NFIN=1\n.ac lin 1 {f:g} {f:g}\n")
        cdd = abs(a["i(vd)"][0].imag) / (2 * np.pi * f)
        cds = abs(a["i(vs)"][0].imag) / (2 * np.pi * f)
        out[m] = {"ron_ohm_fin": ron, "coff_dd_aF_fin": cdd * 1e18, "coff_ds_aF_fin": cds * 1e18,
                  "ron_coff_fs": ron["vg=0.7"]["vs=0"] * cdd * 1e15}
        print(f"  {m}: Ron(vg .7, vs 0) {ron['vg=0.7']['vs=0']:7.0f} ohm/fin  Ron(vs VDD/2) "
              f"{ron['vg=0.7']['vs=0.35']:7.0f}  Coff dd {cdd * 1e18:.1f} aF  ds {cds * 1e18:.1f} aF  "
              f"RonCoff {out[m]['ron_coff_fs']:.1f} fs")
        print("     Ron vs VG (vs=0):", {k: round(v["vs=0"]) for k, v in ron.items()})
    # transmission gate (1+1 fin RVT) Ron across the input range at VDD
    vin = np.linspace(0, VDD, 15)
    d = lib() + "vx x 0 0\nvdd vdd 0 0.7\n" + "".join(
        f"vs{i} s{i} 0 {v}\nvd{i} d{i} 0 {v + 0.005}\nMn{i} d{i} vdd s{i} 0 nmos_rvt L={L} NFIN=1\n"
        f"Mp{i} d{i} 0 s{i} vdd pmos_rvt L={L} NFIN=1\n" for i, v in enumerate(vin))
    r = _espice(d + ".dc vx 0 0 1\n")
    tg = [0.005 / abs(r[f"i(vd{i})"][0]) for i in range(len(vin))]
    out["tg_rvt_1p1"] = {"vin": vin.tolist(), "ron_ohm": tg, "ron_max_ohm": max(tg)}
    print(f"  TG 1n+1p RVT Ron max {max(tg):.0f} ohm (min {min(tg):.0f})")
    check("Ron falls with gate drive", out["nmos_rvt"]["ron_ohm_fin"]["vg=0.9"]["vs=0"] <
          out["nmos_rvt"]["ron_ohm_fin"]["vg=0.5"]["vs=0"])
    save("sw", out)


# ── (5) StrongARM comparator ────────────────────────────────────────────────
KT = 1.380649e-23 * 300.15
CMP_SIZE = {"in": 4, "tail": 4, "ln": 2, "lp": 2, "rst": 1}   # fins, RVT; inverter 1+1 loads


def strongarm(dv, corner="tt", vdd=VDD, vcm=0.55, fclk=1e9, ncyc=10, z=None, cpq=0.0):
    """StrongARM (Razavi SSC-M 2015 form): tail, input pair, NMOS+PMOS cross-coupled latch,
    4 reset PMOS on P,Q,X,Y; X,Y each drive an inverter (its own supply). Input sign
    alternates every cycle. Returns energy/decision, decision delays, and the
    integration-phase quantities the noise formula (note 19p) needs."""
    z = z or CMP_SIZE
    T = 1 / fclk
    n, p = "nmos_rvt", "pmos_rvt"
    d = lib(corner) + f"vdd vdd 0 {vdd}\nvdo vdo 0 {vdd}\n"
    tr = 2e-12                                              # 2 ps clock edges
    d += f"vclk clk 0 pulse(0 {vdd} {T / 2:g} {tr:g} {tr:g} {T / 2 - tr:g} {T:g})\n"
    d += (f"vip inp 0 pulse({vcm - dv / 2} {vcm + dv / 2} 0 {T / 100:g} {T / 100:g} {T - T / 100:g} {2 * T:g})\n"
          f"vin inn 0 pulse({vcm + dv / 2} {vcm - dv / 2} 0 {T / 100:g} {T / 100:g} {T - T / 100:g} {2 * T:g})\n")
    d += f"vt tl tlm 0\nMt tlm clk 0 0 {n} L={L} NFIN={z['tail']}\n"
    d += f"M1 P inp tl 0 {n} L={L} NFIN={z['in']}\nM2 Q inn tl 0 {n} L={L} NFIN={z['in']}\n"
    d += f"M3 X Y P 0 {n} L={L} NFIN={z['ln']}\nM4 Y X Q 0 {n} L={L} NFIN={z['ln']}\n"
    d += f"M5 X Y vdd vdd {p} L={L} NFIN={z['lp']}\nM6 Y X vdd vdd {p} L={L} NFIN={z['lp']}\n"
    d += f"cp P 0 {cpq:g}\ncq Q 0 {cpq:g}\n" if cpq else ""      # MOM caps (ideal C) for noise
    d += "".join(f"Mr{k} {k} clk vdd vdd {p} L={L} NFIN={z['rst']}\n" for k in "PQXY")
    d += "".join(f"Mo{k}p o{k} {k} vdo vdo {p} L={L} NFIN=1\nMo{k}n o{k} {k} 0 0 {n} L={L} NFIN=1\n" for k in "XY")
    r = _espice(d + f".tran {T / 10000:g} {ncyc * T:g}\n")
    t, x, y, P_, clk = r["time"], r["v(x)"], r["v(y)"], r["v(p)"], r["v(clk)"]
    E = []; td = []; ok = True; integ = []
    for c in range(2, ncyc - 1):
        m = (t >= c * T) & (t < (c + 1) * T)
        E.append(-np.trapezoid(r["i(vdd)"][m], t[m]) * vdd)
        tc = _cross(t, clk, vdd / 2, True, c * T)
        diff = x - y
        k = (t > c * T + T / 2) & (t < c * T + T)            # evaluate phase from the clock edge start
        dk = diff[k]
        jj = np.where(np.abs(dk) > vdd / 2)[0]
        if not len(jj):
            ok = False; continue
        td.append(t[k][jj[0]] - tc)                          # from clock 50 %
        sign_in = 1 if (c % 2 == 0) else -1                  # inp high in even cycles
        # inp > inn -> P falls faster -> X low, Y high -> diff < 0
        ok &= bool(np.sign(dk[jj[0]]) == -sign_in)
        # integration phase: P falls from VDD; slope + tail current while P in (vdd-0.05, vdd-vt)
        ki = k & (P_ < vdd - 0.03) & (P_ > vdd - 0.2)
        if ki.sum() > 3:
            slope = -np.polyfit(t[ki], P_[ki], 1)[0]
            iss = float(np.mean(np.abs(r["i(vt)"][ki])))
            vtl = float(np.mean(r["v(tl)"][ki]))
            integ.append((slope, iss, vtl))
    slope, iss, vtl = np.mean(integ, axis=0)
    return {"E_dec_fJ": float(np.mean(E) * 1e15), "t_dec_ps": float(np.mean(td) * 1e12),
            "all_correct": bool(ok), "dP_dt_V_per_ns": float(slope * 1e-9), "Iss_uA": float(iss * 1e6),
            "C1_fF": float(iss / 2 / slope * 1e15), "vgs_in": float(vcm - vtl)}


def cmp():
    out = {}
    for c in ("tt", "ff", "ss"):
        for dv in ((1e-3, 50e-3) if c == "tt" else (1e-3,)):
            k = f"{c}_dv{dv * 1e3:g}mV"
            out[k] = strongarm(dv, c)
            o = out[k]
            print(f"  {k:12s} E/dec {o['E_dec_fJ']:6.2f} fJ  t_dec {o['t_dec_ps']:6.1f} ps  correct {o['all_correct']}"
                  f"  Iss {o['Iss_uA']:.1f} uA  C1 {o['C1_fF']:.3f} fF  VGS_in {o['vgs_in']:.3f}")
    big = {"in": 16, "tail": 8, "ln": 4, "lp": 4, "rst": 2}
    out["imc_tt_dv1mV"] = strongarm(1e-3, z=big, cpq=2e-15)
    o = out["imc_tt_dv1mV"]
    print(f"  imc-grade (in 16 fins, +2 fF on P/Q) E/dec {o['E_dec_fJ']:.2f} fJ  t_dec {o['t_dec_ps']:.1f} ps  "
          f"correct {o['all_correct']}  C1 {o['C1_fF']:.3f} fF")
    # noise (note 19p): vn^2 = 2kT*gamma*Iss/(gm*C1*Vthn) = 4kT*gamma/((gm/Id)*C1*Vthn), plus
    # reset kT/C1 on P,Q referred through the phase gain A = (gm/Id)*Vthn (note 19p1)
    vth = json.loads(RES.read_text())["gmid"]["nmos_rvt"]["vt_lin_extrap_V"]
    for name, key, nin in (("min", "tt_dv1mV", CMP_SIZE["in"]), ("imc", "imc_tt_dv1mV", big["in"])):
        t = out[key]
        tab = np.loadtxt(HERE / "gmid" / f"nmos_rvt_nfin{min(nin, 4)}.csv", delimiter=",")
        gmid_in = float(np.interp(t["vgs_in"], tab[:, 0], tab[:, 1]))
        C1 = t["C1_fF"] * 1e-15
        res = {}
        for gamma in (1.0, 1.5):
            vn_int = np.sqrt(4 * KT * gamma / (gmid_in * C1 * vth))
            vn_rst = np.sqrt(2 * KT / C1) / (gmid_in * vth)
            res[f"gamma{gamma:g}"] = float(np.hypot(vn_int, vn_rst) * 1e3)
        # offset (no mismatch models): Pelgrom sigma(dVT) = Avt/sqrt(Weff*L), input pair only
        weff = nin * P.w_fin
        off = {f"avt{a:g}": float(a / np.sqrt(weff * P.min_l)) for a in (1.0, 1.3, 1.5)}
        out[f"noise_{name}"] = {"gm_id_in": gmid_in, "vthn": vth, "C1_fF": t["C1_fF"], "vn_in_rms_mV": res,
                                "label": "derived (note 19p formula on measured Iss, C1, gm/ID)"}
        out[f"offset_{name}"] = dict(off, label="projected (literature Avt over Weff*L; pair only, latch adds)")
        print(f"  {name}: gm/ID_in {gmid_in:.1f}  vn_in {res} mV rms   offset sigma {off} mV")
    check("all decisions correct at 1 mV (tt/ff/ss)", all(out[k]["all_correct"] for k in out if k.endswith("dv1mV")))
    check("E/decision 0.1-50 fJ", 0.1 < t["E_dec_fJ"] < 50, f"{t['E_dec_fJ']:.2f}")
    check("smaller input -> slower decision", out["tt_dv1mV"]["t_dec_ps"] > out["tt_dv50mV"]["t_dec_ps"])
    save("cmp", out)


# ── DFF / gate area and energy from the ASAP7 liberty (no SPICE) ────────────
LIBDIR = Path(os.environ.get("ASAP7_LIBERTY",
              "/nix/store/b7bw499jgql9p2n7hz2fbx5hk4zicyz0-source/test/asap7"))


def _libtext(name):
    import gzip
    f = LIBDIR / name
    return gzip.open(f, "rt").read() if f.suffix == ".gz" else f.read_text()


def _block(text, head, nxt):
    i = text.index(head)
    j = text.find(nxt, i + len(head))
    return text[i:j if j > 0 else None]


def _pin_energy(cell, pin, slew_i=1, load_i=0):
    """Mean (rise+fall)/2 internal energy, fJ, of each internal_power group under `pin`, at
    input slew index_1[slew_i] (10 ps) and load index_2[load_i] (0.72 fF) where 2-D."""
    import re
    blk = _block(cell, f"pin ({pin})", "\n    pin (")
    out = []
    for g in blk.split("internal_power ()")[1:]:
        e = []
        for kind in ("rise_power", "fall_power"):
            m = re.search(kind + r"\s*\(([^)]*)\)\s*\{(.*?)\}", g, re.S)
            vals = re.search(r"values \(\s*\\?(.*?)\);", m.group(2), re.S).group(1)
            rows = [[float(x) for x in r.split(",")] for r in re.findall(r'"([^"]*)"', vals)]
            e.append(rows[0][0] if len(rows[0]) == 1 and len(rows) == 1 else
                     (rows[slew_i][load_i] if len(rows) > 1 else rows[0][slew_i]))
        out.append(e)
    return out


def lib():
    import re
    out = {}
    for corner, f, v in (("ff", "asap7sc7p5t_SEQ_RVT_FF_nldm_220123.lib", None),
                         ("ss", "asap7sc7p5t_SEQ_RVT_SS_nldm_220123.lib", None)):
        t = _libtext(f)
        v = float(re.search(r"nom_voltage : ([\d.]+)", t).group(1))
        temp = float(re.search(r"nom_temperature : ([\d.-]+)", t).group(1))
        c = _block(t, "cell (DFFHQNx1_ASAP7_75t_R)", "\n  cell (")
        area = float(re.search(r"area : ([\d.]+)", c).group(1))
        clk = _pin_energy(c, "CLK")            # D static: clock tree inside the flop
        qn = _pin_energy(c, "QN")              # CLK -> QN output toggle (data captured)
        e_clk = float(np.mean([sum(x) for x in clk]))          # rise+fall = one clock cycle
        e_q = float(np.mean([np.mean(x) for x in qn]))         # one output transition
        cin = float(re.search(r"pin \(CLK\).*?capacitance : ([\d.]+)", c, re.S).group(1))
        out[f"dff_{corner}"] = {"V": v, "T_C": temp, "area_um2": area, "E_clk_cycle_fJ": e_clk,
                                "E_q_toggle_fJ": e_q, "clk_cap_fF": cin}
        print(f"  DFFHQNx1 {corner} {v} V {temp:g} C: area {area} um2  E_clk/cycle {e_clk:.3f} fJ  "
              f"E_Q toggle {e_q:.3f} fJ  Cclk {cin:.3f} fF")
    # TT 0.7 V is not in the test set: E/V^2 (an effective C) from FF and SS averaged, x 0.7^2
    ce = np.mean([(out[k]["E_clk_cycle_fJ"] + 0.5 * out[k]["E_q_toggle_fJ"]) / out[k]["V"] ** 2
                  for k in ("dff_ff", "dff_ss")])
    out["dff_tt_interp"] = {"E_cycle_alpha0.5_fJ": float(ce * VDD ** 2), "V": VDD,
                            "method": "mean over FF(0.77V,0C)/SS(0.63V,100C) of E/V^2, x 0.7^2"}
    print(f"  DFF TT 0.7 V (interp): {ce * VDD ** 2:.3f} fJ / cycle at data activity 0.5 (+ clock pin load)")
    for cell, f in (("INVx1_ASAP7_75t_R", "asap7sc7p5t_INVBUF_RVT_TT_nldm_220122.lib.gz"),
                    ("NAND2xp33_ASAP7_75t_R", "asap7sc7p5t_SIMPLE_RVT_FF_nldm_211120.lib.gz"),
                    ("NAND2x1_ASAP7_75t_R", "asap7sc7p5t_SIMPLE_RVT_FF_nldm_211120.lib.gz")):
        c = _block(_libtext(f), f"cell ({cell})", "\n  cell (")
        a = float(re.search(r"area : ([\d.]+)", c).group(1))
        cap = float(re.search(r"pin \(A\).*?capacitance : ([\d.]+)", c, re.S).group(1))
        out[cell] = {"area_um2": a, "cin_A_fF": cap}
        print(f"  {cell}: area {a} um2  Cin(A) {cap} fF")
    # liberty FO4 cross-check: INVx1 TT 0.7 V driving 4x its own Cin, 20 ps input slew (row 2)
    c = _block(_libtext("asap7sc7p5t_INVBUF_RVT_TT_nldm_220122.lib.gz"), "cell (INVx1_ASAP7_75t_R)", "\n  cell (")
    loads = [0.72, 1.44, 2.88, 5.76, 11.52, 23.04, 46.08]
    cl = 4 * out["INVx1_ASAP7_75t_R"]["cin_A_fF"]
    def row(kind):
        m = re.search(kind + r"\s*\([^)]*\)\s*\{.*?values \(\s*\\?(.*?)\);", c, re.S)
        r = [[float(x) for x in q.split(",")] for q in re.findall(r'"([^"]*)"', m.group(1))]
        return float(np.interp(cl, loads, r[2]))
    fo4 = (row("cell_rise") + row("cell_fall")) / 2
    e_int = [row("rise_power"), row("fall_power")]     # first rise/fall groups = A->Y
    e_tr = 0.5 * cl * VDD ** 2 + (e_int[0] + e_int[1]) / 2
    out["INVx1_lib_fo4"] = {"fo4_ps": fo4, "E_trans_fJ": e_tr, "C_load_fF": cl,
                            "method": "NLDM TT 0.7 V 25C, 20 ps slew, load 4*Cin; E = CV^2/2 + mean internal"}
    print(f"  INVx1 liberty FO4 {fo4:.2f} ps   E/transition {e_tr:.3f} fJ  (CL {cl:.2f} fF)")
    check("DFF area > NAND2 area", out["dff_ff"]["area_um2"] > out["NAND2xp33_ASAP7_75t_R"]["area_um2"])
    save("lib", out)


# ── fold everything into asap7_constants.json (no SPICE) ────────────────────
CONST = HERE.parents[2] / "scripts" / "compiler" / "metrics" / "arch_eval" / "asap7_constants.json"
EPS0_FF_UM = 8.854e-3          # fF/um
K_LOWK = 2.7                   # MEJ 4.4 / pdk_specs: ILD k assumed for the MOM estimate


def mom_density(w_um, s_um, ar=2.0):
    """Lateral interdigitated-finger density of one layer, fF/um^2: eps*t/s per gap, one gap
    per pitch. t = ar*w (MEJ 4.4: metal aspect ratio 2:1). No fringe / no plate term."""
    return K_LOWK * EPS0_FF_UM * ar * w_um / s_um / (w_um + s_um)


def vt_cc(m, icc_per_fin=None):
    """Constant-current Vt from the measured table (VDS = VDD/2): VGS where ID/fin =
    100 nA * Weff/L (the usual 100 nA*W/L criterion with Weff = w_fin)."""
    icc = icc_per_fin or 100e-9 * P.w_fin / P.min_l
    t = np.loadtxt(HERE / "gmid" / f"{m}_nfin1.csv", delimiter=",")
    return float(np.interp(np.log(icc), np.log(t[:, 2]), t[:, 0]))


def const():
    R = json.loads(RES.read_text())
    g, iv, lk, swr, cm, lb = R["gmid"], R["inv"], R["leak"], R["sw"], R["cmp"], R["lib"]
    C = {}
    def put(k, v, unit, label, src):
        C[k] = {"value": float(v), "unit": unit, "label": label, "source": src}
    M = "analog/docs/asap7/char.py"
    put("vdd_nom", VDD, "V", "projected", "ASAP7 nominal VDD (Clark et al., MEJ 53 (2016) Sec. 3)")
    kT = 1.380649e-23 * 300
    put("kT_300K_J", kT, "J", "derived", "Boltzmann k * 300 K")
    put("kTC_noise_uV_rms_at_1fF", np.sqrt(kT / 1e-15) * 1e6, "uV", "derived", "sqrt(kT/C), C = 1 fF, 300 K")
    # FO4 / inverter
    src_inv = (f"{M} inv: ESPice BSIM-CMG, TT 27C, RVT 1+1-fin inverter chain, FO4 = 4 identical inverter "
               "loads, no wiring/cell parasitics. Liberty INVx1 (cell parasitics) is ~1.85x slower and ~5x "
               "the energy: use *_lib for digital estimates")
    put("fo4_delay_ps", iv["tt@0.7"]["fo4_ps"], "ps", "measured", src_inv)
    put("inv_switch_energy_fJ", iv["tt@0.7"]["E_trans_fJ"], "fJ", "measured",
        src_inv + "; E per output transition = vdd*Q(one period)/2, includes 4 gate loads + own drain + short-circuit")
    for v in (0.45, 0.5, 0.6, 0.7):
        put(f"fo4_delay_ps@{v}", iv[f"tt@{v}"]["fo4_ps"], "ps", "measured", src_inv)
        put(f"inv_switch_energy_fJ@{v}", iv[f"tt@{v}"]["E_trans_fJ"], "fJ", "measured", src_inv)
    for c in ("ff", "ss"):
        put(f"fo4_delay_ps_{c}", iv[f"{c}@0.7"]["fo4_ps"], "ps", "measured", src_inv + f"; {c} corner")
        put(f"inv_switch_energy_fJ_{c}", iv[f"{c}@0.7"]["E_trans_fJ"], "fJ", "measured", src_inv + f"; {c} corner")
    put("fo4_delay_ps_slvt", iv["tt@0.7_slvt"]["fo4_ps"], "ps", "measured", src_inv + "; SLVT devices")
    li = lb["INVx1_lib_fo4"]
    put("fo4_delay_ps_lib", li["fo4_ps"], "ps", "derived",
        "asap7sc7p5t INVBUF RVT TT 0.7V 25C NLDM: INVx1 at 20 ps slew into 4*Cin(A)=2.48 fF, mean rise/fall")
    put("inv_switch_energy_fJ_lib", li["E_trans_fJ"], "fJ", "derived",
        "same NLDM: CL*V^2/2 + mean internal energy, INVx1 FO4")
    # DFF / gates
    put("dff_energy_fJ", lb["dff_tt_interp"]["E_cycle_alpha0.5_fJ"], "fJ", "derived",
        "DFFHQNx1_ASAP7_75t_R liberty: (E_clk(rise+fall) + 0.5*E_Q toggle) per cycle at 10 ps slew / 0.72 fF, "
        "TT 0.7V INTERPOLATED as mean E/V^2 of FF(0.77V,0C) and SS(0.63V,100C), x 0.49 (no TT SEQ lib in set); "
        "excludes the clock-net load 0.5 fF*V^2")
    put("dff_area_um2", lb["dff_ff"]["area_um2"], "um2", "derived", "DFFHQNx1_ASAP7_75t_R liberty area (1x)")
    put("dff_clk_cap_fF", lb["dff_ff"]["clk_cap_fF"], "fF", "derived", "DFFHQNx1 CLK pin cap, FF liberty")
    put("nand2_area_um2", lb["NAND2xp33_ASAP7_75t_R"]["area_um2"], "um2", "derived",
        "NAND2xp33_ASAP7_75t_R liberty area (NAND2x1: %.5f)" % lb["NAND2x1_ASAP7_75t_R"]["area_um2"])
    put("inv_x1_area_um2", lb["INVx1_ASAP7_75t_R"]["area_um2"], "um2", "derived", "INVx1_ASAP7_75t_R liberty area")
    # SRAM (MEJ 5.2: 111 bitcell = 8-fin cell height, 2 CPP wide)
    put("sram6t_bitcell_um2", 2 * 0.054 * 8 * 0.027, "um2", "derived",
        "MEJ Sec. 5.2/Fig. 7: '111' 6T cell is 8 fins tall (8*27 nm) x 2 CPP (2*54 nm). Commercial N7 HD 6T "
        "is ~0.027 um2 (projected cross-check). The 112 cell (2-fin PD) is larger, height not stated")
    put("sram8t_bitcell_um2", 3 * 0.054 * 8 * 0.027, "um2", "projected",
        "6T 111 cell + 2-transistor read port as one extra CPP column (assumption, not drawn): 3 CPP x 8 fins; "
        "literature 8T/6T area ratio 1.3-1.5 (note 27i7)")
    # capacitors
    d = {"M1-M3": mom_density(0.018, 0.018), "M4-M5": mom_density(0.024, 0.024), "M6-M7": mom_density(0.032, 0.032)}
    stack_min = 3 * d["M1-M3"] + 2 * d["M4-M5"]
    d2 = {"M2-M3": mom_density(0.018, 0.054), "M4-M5": mom_density(0.024, 0.072)}
    stack_2x = 2 * d2["M2-M3"] + 2 * d2["M4-M5"]
    put("mom_cap_density_fF_per_um2", 2.0, "fF/um2", "derived",
        "lateral eps*t/(s*p), k=%.1f, AR 2:1 (MEJ 4.4), pitches MEJ Table 1: M1-M5 at min pitch %.2f fF/um2 "
        "(upper bound, M1 unusable over cells); M2-M5 at width w, space 3w %.2f; design value 2.0 = between, "
        "matches pdk_specs.Asap7.mim_ff_um2. Lit. cross-check: FinFET-node MOM 2-4 fF/um2 (projected)"
        % (K_LOWK, stack_min, stack_2x))
    put("mom_cap_density_min_pitch_M1_M5_fF_per_um2", stack_min, "fF/um2", "derived", "as above, upper bound")
    put("unit_cap_min_fF", 0.2, "fF", "projected",
        "practical MOM unit: below ~0.2 fF routing/fringe parasitics and edge LER dominate (sub-fF MOM "
        "matching data: Omran et al. TCAS-I 2016; Tripathi & Murmann TCAS-I 2014). kT/C at 0.2 fF = 144 uV")
    put("cap_match_sigma_pct_at_1fF", 0.5, "%", "projected",
        "MOM sigma(dC/C) ~0.3-1 % at ~1 fF in 32-40 nm measurements (Omran 2016, Tripathi & Murmann 2014); "
        "sigma = A_C/sqrt(area) (note 27i1); not measured for ASAP7 (no statistical BEOL)")
    put("avt_mV_um", P.a_vt, "mV*um", "projected",
        "no mismatch models in ASAP7; 7-16 nm FinFET literature ~1.0-1.5 mV*um over Weff*L "
        "(pdk_specs.Asap7Proj.a_vt, LOW confidence); Pelgrom law note 19l")
    # devices
    srcg = f"{M} gmid: ESPice BSIM-CMG TT 27C, L=21 nm, |VDS|=0.35 V, CSV analog/docs/asap7/gmid/"
    put("nfet_id_per_fin_uA", lk["tt@27C"]["nmos_rvt"]["ion_uA"], "uA", "measured",
        f"{M} leak: nmos_rvt VGS=VDS=0.7 V TT 27C (MEJ Table 3 Idsat 37.85)")
    for c in ("ff", "ss"):
        put(f"nfet_id_per_fin_uA_{c}", lk[f"{c}@27C"]["nmos_rvt"]["ion_uA"], "uA", "measured", f"{M} leak, {c}")
    put("pfet_id_per_fin_uA", lk["tt@27C"]["pmos_rvt"]["ion_uA"], "uA", "measured", f"{M} leak: pmos_rvt |VGS|=|VDS|=0.7")
    put("nfet_cgg_per_fin_aF", g["nmos_rvt"]["cgg_per_fin_vdd_aF"], "aF", "measured", srcg + "; at VGS=0.7, AC 1 MHz")
    put("nfet_gm_over_id_max_per_V", g["nmos_rvt"]["gm_id_max"], "1/V", "measured", srcg)
    put("nfet_ft_GHz", g["nmos_rvt"]["ft_peak_GHz"], "GHz", "measured", srcg + "; peak gm/(2 pi Cgg), intrinsic, no BEOL")
    put("nfet_ft_at_gmid10_GHz", g["nmos_rvt"]["ft_at_gmid10_GHz"], "GHz", "measured", srcg)
    put("nfet_gm_gds_at_gmid10", g["nmos_rvt"]["gm_gds_at_gmid10"], "V/V", "measured", srcg + " (intrinsic gain, L fixed at 21 nm)")
    put("pfet_gm_gds_at_gmid10", g["pmos_rvt"]["gm_gds_at_gmid10"], "V/V", "measured", srcg)
    srcs = f"{M} sw: nmos 1 fin, VD-VS = 10 mV, TT 27C"
    put("switch_ron_ohm_per_fin", swr["nmos_rvt"]["ron_ohm_fin"]["vg=0.7"]["vs=0"], "ohm", "measured",
        srcs + "; RVT VG=0.7 VS=0 (at VS=0.35: %.0f; LVT %.0f; SLVT %.0f). Saturates ~5 kohm at high drive "
        "(series S/D resistance)" % (swr["nmos_rvt"]["ron_ohm_fin"]["vg=0.7"]["vs=0.35"],
                                      swr["nmos_lvt"]["ron_ohm_fin"]["vg=0.7"]["vs=0"],
                                      swr["nmos_slvt"]["ron_ohm_fin"]["vg=0.7"]["vs=0"]))
    for vgk, ron in swr["nmos_rvt"]["ron_ohm_fin"].items():
        put(f"switch_ron_ohm_per_fin@{vgk[3:]}", ron["vs=0"], "ohm", "measured", srcs + "; RVT, VS=0")
    put("switch_coff_aF_per_fin", swr["nmos_rvt"]["coff_dd_aF_fin"], "aF", "measured",
        f"{M} sw: off device (VG=0) drain cap to AC ground at VD=0.35 V, 1 MHz. Drain-source feedthrough "
        "reads ~0 (BSIM-CMG cards carry no direct Cds)")
    put("tgate_ron_max_ohm_1n1p", swr["tg_rvt_1p1"]["ron_max_ohm"], "ohm", "measured", f"{M} sw: RVT 1+1 fin TG, worst over 0..VDD")
    put("nfet_ileak_per_fin_nA", lk["tt@27C"]["nmos_rvt"]["ioff_nA"], "nA", "measured",
        f"{M} leak: nmos_rvt VGS=0 VDS=0.7 TT 27C (MEJ Table 3: 0.019)")
    for c, key in (("ff", "ff@27C"), ("ss", "ss@27C"), ("85C", "tt@85C")):
        put(f"nfet_ileak_per_fin_nA_{c}", lk[key]["nmos_rvt"]["ioff_nA"], "nA", "measured", f"{M} leak, {key}")
    for fl in ("lvt", "slvt", "sram"):
        put(f"nfet_ileak_per_fin_nA_{fl}", lk["tt@27C"][f"nmos_{fl}"]["ioff_nA"], "nA", "measured", f"{M} leak, TT 27C")
    for fl in FLAVORS:
        put(f"vt_{fl}_V", g[f"nmos_{fl}"]["vt_lin_extrap_V"], "V", "measured",
            srcg + "; nmos max-gm linear extrapolation at VDS=0.35 V (MEJ Vtsat by const. current is lower)")
        put(f"vt_{fl}_cc_V", vt_cc(f"nmos_{fl}"), "V", "measured",
            srcg + "; constant current 100 nA*Weff/L per fin at VDS=0.35 V")
    put("wire_c_fF_per_um", 0.173323, "fF/um", "projected",
        "OpenROAD/ORFS asap7 setRC.tcl set_wire_rc -signal (correlation fit to its RCX, not PDK-extracted)")
    put("wire_r_ohm_per_um", 32.3151, "ohm/um", "projected", "same: 3.23151E-02 kohm/um signal wire")
    # comparator
    t = cm["tt_dv1mV"]
    srcc = (f"{M} cmp: StrongARM RVT (in 4, tail 4, latch 2n/2p, reset 1 fin), X/Y loaded by 1+1 inverters, "
            "1 GHz, VCM 0.55 V, 1 mV input, TT 27C, no layout parasitics")
    put("comparator_energy_fJ", t["E_dec_fJ"], "fJ", "measured", srcc)
    for c in ("ff", "ss"):
        put(f"comparator_energy_fJ_{c}", cm[f"{c}_dv1mV"]["E_dec_fJ"], "fJ", "measured", srcc + f"; {c}")
    put("comparator_tdec_ps_at_1mV", t["t_dec_ps"], "ps", "measured", srcc + "; clk 50% to |X-Y|>VDD/2")
    put("comparator_offset_sigma_mV", cm["offset_min"]["avt1.3"], "mV", "projected",
        "Pelgrom Avt=1.3 mV*um over Weff*L of the 4-fin input pair (latch adds); no ASAP7 mismatch models")
    put("comparator_noise_mV_rms", cm["noise_min"]["vn_in_rms_mV"]["gamma1"], "mV", "derived",
        "note 19p: vn^2 = 4kT*gamma/((gm/ID)*C1*Vthn) + reset kT/C1 (note 19p1), gamma=1 (1.5 -> %.2f), "
        "on measured Iss, C1=%.3f fF, gm/ID" % (cm["noise_min"]["vn_in_rms_mV"]["gamma1.5"], cm["noise_min"]["C1_fF"]))
    o = cm["imc_tt_dv1mV"]
    srci = f"{M} cmp: IMC-grade StrongARM (in 16 fins, tail 8, latch 4/4, +2 fF MOM on P/Q), TT, 1 mV"
    put("comparator_imc_energy_fJ", o["E_dec_fJ"], "fJ", "measured", srci)
    put("comparator_imc_noise_mV_rms", cm["noise_imc"]["vn_in_rms_mV"]["gamma1"], "mV", "derived", srci + "; note 19p")
    put("comparator_imc_offset_sigma_mV", cm["offset_imc"]["avt1.3"], "mV", "projected", srci + "; Pelgrom Avt=1.3")
    # SAR ADC
    B, r = 8, 1.0
    e8 = 100 * (B + np.log2(r)) + 1e-3 * r ** 2 * 4 ** B           # fJ, k1=100 fJ, k2=1 aJ
    put("sar_adc_fom_fJ_per_step", e8 / 2 ** B, "fJ/conv-step", "projected",
        "Gonugondla et al. 2022 column-ADC model E=k1(B+log2 r)+k2 r^2 4^B, k1=100 fJ, k2=1 aJ (note 27h1), "
        "B=8, r=1: %.0f fJ/conv; Murmann ADC survey SAR envelope ~1-5 fJ/step at 10-500 MS/s (cross-check)" % e8)
    cu = 0.2
    e_bot = 8 * o["E_dec_fJ"] + 0.3 * 2 ** B * cu * VDD ** 2 + 8 * 8 * lb["dff_tt_interp"]["E_cycle_alpha0.5_fJ"]
    put("sar_adc_energy_bottomup_8b_fJ", e_bot, "fJ", "derived",
        "8 x comparator_imc_energy + CDAC 0.3*256*0.2fF*V^2 + SAR logic 8 cycles x 8 DFF; no references, "
        "clock tree, wiring: a FLOOR, not a design (FoM %.2f fJ/step at 8 b)" % (e_bot / 2 ** B))
    CONST.parent.mkdir(parents=True, exist_ok=True)
    CONST.write_text(json.dumps(C, indent=1) + "\n")
    for k in ("vdd_nom", "fo4_delay_ps", "inv_switch_energy_fJ", "dff_energy_fJ", "sram6t_bitcell_um2",
              "mom_cap_density_fF_per_um2", "nfet_id_per_fin_uA", "switch_ron_ohm_per_fin",
              "comparator_energy_fJ", "comparator_noise_mV_rms", "sar_adc_fom_fJ_per_step",
              "sar_adc_energy_bottomup_8b_fJ", "vt_rvt_cc_V", "vt_lvt_cc_V", "vt_slvt_cc_V"):
        print(f"  {k:32s} {C[k]['value']:10.4g} {C[k]['unit']:8s} {C[k]['label']}")
    req = ("vdd_nom kT_300K_J fo4_delay_ps inv_switch_energy_fJ dff_energy_fJ dff_area_um2 nand2_area_um2 "
           "sram6t_bitcell_um2 sram8t_bitcell_um2 mom_cap_density_fF_per_um2 unit_cap_min_fF "
           "cap_match_sigma_pct_at_1fF avt_mV_um nfet_id_per_fin_uA nfet_cgg_per_fin_aF nfet_gm_over_id_max_per_V "
           "nfet_ft_GHz switch_ron_ohm_per_fin switch_coff_aF_per_fin nfet_ileak_per_fin_nA vt_rvt_V vt_lvt_V "
           "vt_slvt_V wire_c_fF_per_um wire_r_ohm_per_um comparator_energy_fJ comparator_offset_sigma_mV "
           "sar_adc_fom_fJ_per_step").split() + [f"{a}@{v}" for a in ("fo4_delay_ps", "inv_switch_energy_fJ")
                                                  for v in (0.45, 0.5, 0.6, 0.7)]
    miss = [k for k in req if k not in C]
    check("all required constants present", not miss, ",".join(miss))
    check("labels valid", all(v["label"] in ("measured", "derived", "projected") for v in C.values()))
    print(f"  {len(C)} constants -> {CONST}")


STAGES = {"gmid": gmid, "inv": inv, "leak": leak, "sw": sw, "cmp": cmp, "lib": lib, "const": const}

if __name__ == "__main__":
    for s in sys.argv[1:]:
        print(f"== {s} ==")
        STAGES[s]()
    print("OVERALL:", "PASS" if OK else "FAIL")
    sys.exit(0 if OK else 1)
