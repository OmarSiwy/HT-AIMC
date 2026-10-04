"""tb_csnr — the tile's share of the per-stage compute-SNR budget (law:csnr).

    CSNR = Var(y_ideal) / E[(y_hat - y_ideal)^2]   over the 16 data columns of a real
    A5 pass (attention-class pass_05, FFN-class pass_09), y = mac_lo / D.

Ported from AnalogIOC analog/testbenches/tb_csnr.py, the parts that run without the
column converter:
  budget   (b) kT/C bank sampling and (e) unit-cap mismatch, analytic per column
           (a .tran is noiseless and tt carries no cap mismatch), CSNR per pass.
           Spec row: kT/C keeps CSNR >= specs.SNR_S_DB + 6 dB (a quarter of the stage's
           error power at most). The mismatch term is reported, not gated: A_c is a
           projection (no sky130 cap-matching figure) — and it lands below SNR_S_DB
           (docs/architecture.md, findings).
  isolate  1-column synthetic tiles at a controlled unit count (AnalogIOC
           diag_multibank.synth_col), measured on the raw integrator node after the
           window: nominal / ideal OTA (A = 1e6 VCVS) / no C_RAIL, and the absorb curve.
           Spec row: with an ideal virtual ground the tile delivers >= 98 % of the
           ideal charge at every unit count (the multi-bank deficit belongs to the
           amplifier loop, not the tile).
Not ported (need integrator_conv, not migrated, or AnalogIOC's out/*.log acceptance
runs): logs, uncorr, lever, gainsweep, and the default verdict "measured converter
CSNR >= SNR_S_DB".

    python3 tb_csnr.py [budget|isolate [4,11,21]]      # default: both
"""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from tile import T_START, TQ, VDD, at, clocks, drive, testbench  # noqa: E402
from bench import Report  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402
import specs  # noqa: E402
import weight_tile as wt  # noqa: E402

sys.path.insert(0, str(HERE.parents[2] / "scripts"))
from golden import model as G  # noqa: E402

PASSES = ["pass_05_typ_attn_q", "pass_09_typ_ffn_gate"]
A_C_PCT_UM = 1.0         # MIM Pelgrom A_c (%*um): no sky130 figure published; PROJECTED
TILE_SHARE_DB = 6.0      # tile terms may use a quarter of the stage's error power
EFF_IDEAL_MIN = 0.98
JOBS = int(os.environ.get("JOBS", 3))


def pass_data(pname):
    """(Cp, Cn, chk, xlo, D, mac_lo) for one A5 pass."""
    d = HERE / "data" / pname
    exp = json.loads((d / "expected.json").read_text())
    Cp, Cn, chk = wt.read_caps(d / "caps.spice")
    sign, _hi, lo = G.pwm_nibbles(np.array(exp["xq"], dtype=np.int64))
    xlo = (sign * lo).astype(np.int64)
    return Cp, Cn, chk, xlo, int(exp["D"]), (Cp.astype(np.int64) - Cn) @ xlo


def csnr_db(y, err):
    ms = float(np.mean(np.asarray(err, float) ** 2))
    return 10 * np.log10(float(np.var(y)) / ms) if ms > 0 else np.inf


def analytic_budget(pname):
    """(b) kT/C and (e) Pelgrom mismatch, LSB rms per data column."""
    sz, pdk = wt.sizes(), get_pdk()
    c_u, c_ball = sz["c_u"], sz["c_ball"]
    Cp, Cn, _, xlo, D, _ = pass_data(pname)
    area_um2 = c_u * 1e15 / pdk.mim_ff_um2
    s_rel = A_C_PCT_UM / 100 / np.sqrt(area_um2)
    kt, mm = [], []
    for j in range(16):
        v_kt = v_mm = 0.0
        for i in range(16):
            n_i = int(abs(xlo[i]))
            for units in (int(Cp[j, i]), int(Cn[j, i])):
                if units:
                    v_kt += specs.KB_T * (units * c_u + c_ball) * n_i   # per recharge
                    v_mm += units * (s_rel * n_i) ** 2
        kt.append(np.sqrt(v_kt) / (c_u * VDD) / D)
        mm.append(np.sqrt(v_mm) / D)
    return np.array(kt), np.array(mm)


def budget(r):
    print(f"  reset kT/C on C_int {specs.c_int() * 1e15:.0f} fF: "
          f"{np.sqrt(specs.KB_T / specs.c_int()) / specs.u1():.3f} LSB  [(b)]")
    for pname in PASSES:
        kt, mm = analytic_budget(pname)
        y = pass_data(pname)[5] / pass_data(pname)[4]
        print(f"  {pname} (16 cols, Var(y) {np.var(y):.0f}): (b) kT/C {np.sqrt(np.mean(kt ** 2)):.3f} "
              f"LSB rms -> {csnr_db(y, kt):.1f} dB [ESTIMATE]; (e) Pelgrom C_u "
              f"{specs.c_u() * 1e15:.2f} fF, A_c {A_C_PCT_UM} %um: {np.sqrt(np.mean(mm ** 2)):.3f} "
              f"LSB rms -> {csnr_db(y, mm):.1f} dB [PROJECTED]")
        r.check(f"{pname}: kT/C CSNR >= SNR_S_DB + {TILE_SHARE_DB:.0f} dB",
                csnr_db(y, kt) >= specs.SNR_S_DB + TILE_SHARE_DB,
                f"{csnr_db(y, kt):.1f} dB vs {specs.SNR_S_DB + TILE_SHARE_DB:.0f} dB")
        print(f"  info  (e) mismatch CSNR {csnr_db(y, mm):.1f} dB vs SNR_S_DB {specs.SNR_S_DB:.0f}"
              f" (CSNR ~ C_u: x{10 ** ((specs.SNR_S_DB + TILE_SHARE_DB - csnr_db(y, mm)) / 10):.1f}"
              f" C_u to clear SNR_S_DB + {TILE_SHARE_DB:.0f} dB)")


def synth_col(n_banks, q, wb=3, net_frac=0.45):
    """(cp, cn, xq, mac): 16-row column, n_banks units at wb per row, net ~net_frac
    positive, nibble q on every active row (AnalogIOC diag_multibank verbatim)."""
    ws, rem = [], n_banks
    while rem > 0:
        ws.append(min(wb, rem))
        rem -= ws[-1]
    assert len(ws) <= 16
    want, net = int(round(net_frac * n_banks)), 0
    cp, cn, xq = [0] * 16, [0] * 16, [0] * 16
    for i, w in enumerate(ws):
        sgn = 1 if net < want else -1
        (cp if sgn > 0 else cn)[i] = w
        net += sgn * w
        xq[i] = q
    return cp, cn, xq, q * net


def eff_point(n_banks, q, wb, **col):
    """(mac, efficiency, absorb curve {ns after window: eff}) on the raw integrator node."""
    cp, cn, xq, mac = synth_col(n_banks, q, wb)
    t_win = T_START + 16 * TQ
    t_end = t_win + 8 * TQ + 1e-9
    tb = testbench(cp, cn, **col)
    clocks(tb, TQ, t_end)
    drive(tb, xq)
    tb.save("V(vout)")
    d = tb.transient(step_time=0.1e-9, end_time=t_end)
    v0 = at(d, "vout", T_START - 1e-9)
    ideal = mac * specs.u_cal()
    curve = {x: (at(d, "vout", t_win + x * 1e-9) - v0) / ideal for x in (0, 10, 20, 40, 60, 80)}
    return mac, (at(d, "vout", t_end - 5e-9) - v0) / ideal, curve


def isolate(r, banks="4,11,21"):
    grid = [(int(b), 3 if int(b) <= 16 else 5, 6 if int(b) <= 16 else 5)
            for b in banks.split(",")]
    variants = {"nominal": {}, "idealOTA": {"ideal_ota": True}, "noCRAIL": {"rail": False}}
    with ThreadPoolExecutor(JOBS) as ex:
        fut = {(v, nb): ex.submit(eff_point, nb, q, wb, **kw)
               for v, kw in variants.items() for nb, wb, q in grid}
    print(f"    {'variant':<10}{'units':>7}{'mac':>6}{'efficiency':>12}  absorb eff(t after window, ns)")
    for (v, nb), f in fut.items():
        mac, e, curve = f.result()
        print(f"    {v:<10}{nb:>7}{mac:>6}{e:>12.4f}  " +
              " ".join(f"{x}:{c:.3f}" for x, c in curve.items()))
    worst = min(fut["idealOTA", nb].result()[1] for nb, _, _ in grid)
    r.check(f"ideal virtual ground: delivery >= {EFF_IDEAL_MIN:.0%} at every unit count",
            worst >= EFF_IDEAL_MIN, f"worst {worst:.4f}")
    for nb, _, _ in grid:
        b = fut["nominal", nb].result()[1]
        print(f"    units={nb}: (d) ideal OTA {fut['idealOTA', nb].result()[1] - b:+.4f}, "
              f"(c) no C_RAIL {fut['noCRAIL', nb].result()[1] - b:+.4f} vs nominal {b:.4f}")


def main():
    a = sys.argv[1:]
    r = Report("weight_tile csnr")
    if not a or a[0] == "budget":
        budget(r)
    if not a or a[0] == "isolate":
        isolate(r, *a[1:])
    r.done()


if __name__ == "__main__":
    main()
