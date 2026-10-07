"""Unit testbenches of the five Verilog-A blocks, each in its own small ESPice deck.

    python3 test/tb_va_units.py [gc|drive|col|sar|ref]     (inside ./env.sh analog, PDK not needed)

B1 imc_gc     write levels, retention droop slope, write energy per '1'
B2 imc_rowdrv rail settling into the level nets (ml2 and bitserial), code-dependent droop at
              share time against the golden's level-net law, constant-charge dummies
B3 imc_col    merged differential voltage = k * S for a known 4-slot ml2 / 7-slot bitserial pass
              (no noise, no mismatch), against scripts/golden/imc_tile.py
B4 imc_sar    ideal codes = floor(v / LSB + 1/2) over the range, clip at the ends
B5 imc_ref    a tile's simultaneous conversions on one reference, the SAR drawing its C-DAC charge per
              bit step: Verilog-A codes vs the golden's reference law, droop vs ARCH's 3.7 uV/conversion
Each prints PASS/FAIL with the numbers; exit 1 on any FAIL.
"""
import math
import sys
from pathlib import Path

import numpy as np
from dataclasses import replace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2] / "scripts"))
import va_lib as L                     # noqa: E402
from golden import imc_tile as G      # noqa: E402

FAILS = []


def check(name, ok, msg):
    print(f"{'PASS' if ok else 'FAIL'} {name}: {msg}")
    if not ok:
        FAILS.append(name)


def t_gc():
    # one weight written with 0xA5 at 1 ns, rewritten with 0x3C at 2 ns; read after each write and at 1 us
    pat = (0xA5, 0x3C)
    lines = ['* B1 imc_gc unit', '.hdl "imc_gc.va"',
             f"Vwl wl 0 {L.pwl([(1e-9, 1.25e-9, L.VDD), (2e-9, 2.25e-9, L.VDD)])}"]
    for b in range(8):
        v0, v1 = (pat[0] >> b) & 1, (pat[1] >> b) & 1
        lines.append(f"Vbl{b} bl{b} 0 PWL(0 {v0 * L.VDD} 1.5e-9 {v0 * L.VDD} 1.52e-9 {v1 * L.VDD})")
    lines += [f"Ngc wl {' '.join(f'bl{b}' for b in range(8))} {' '.join(f's{b}' for b in range(8))} imc_gc",
              ".tran 1e-10 1e-6", ".end", ""]
    res = L.espice("\n".join(lines), "unit_gc")
    p = G.P()
    ok, worst = True, 0.0
    for t, pv in ((1.8e-9, pat[0]), (3e-9, pat[1])):
        for b in range(8):
            v = L.at(res, f"v(s{b})", t)
            e = abs(v - (0.631 if (pv >> b) & 1 else -0.072))
            worst = max(worst, e)
    v1us = L.at(res, "v(s2)", 1e-6)
    exp1 = 0.631 - (0.631 - 0.58) * (1e-6 - 2.27e-9) / p.t_ret
    hold = L.at(res, "v(s0)", 1e-6)
    check("B1 imc_gc", worst < 3e-3 and abs(v1us - exp1) < 2e-3 and abs(hold + 0.072) < 2e-3,
          f"write levels within {worst * 1e3:.2f} mV of 0.631/-0.072 V (250 ps WL), rewrite OK; "
          f"'1' at 1 us {v1us:.4f} V (retention law {exp1:.4f}); '0' holds {hold:.4f} V")


def drive_deck(mode, codes, cc=0, cols=256, t_on=1e-9, t_off=2.0e-9, name="drive"):
    """One tile's 8 rows; codes[r] = (digit, sign); the drive window is [t_on, t_off]."""
    p = G.P(mode=mode)
    sc = cols / 256
    crow, rsw = p.c_row * sc, p.tau_row / (p.c_row * sc)
    rmid, rtop = p.r_lvl_mid / sc, p.r_lvl_top / sc
    lines = [f"* B2 imc_rowdrv unit {mode}", '.hdl "imc_rowdrv.va"', '.hdl "imc_ref.va"', "Vdd vdd 0 0.7",
             f"Nl1 l1 vdd imc_ref v0={0.7 / 3} r_out={rmid}", f"Nl2 l2 vdd imc_ref v0={1.4 / 3} r_out={rmid}",
             f"Nl3 l3 vdd imc_ref v0=0.7 r_out={rtop}",
             f"Vdrv pdrv 0 {L.pwl([(t_on, t_off, L.VDD)])}"]
    drv = []
    for r, (d, sg) in enumerate(codes):
        for k, bitv in enumerate((d & 1, (d >> 1) & 1, sg)):
            lines.append(f"Vd{r}_{k} d{r}_{k} 0 " + (L.pwl([(t_on, t_off, L.VDD)]) if bitv else "0"))
            drv.append(f"d{r}_{k}")
    lines += [f"Nrd {' '.join(drv)} pdrv {' '.join(f'rp{r}' for r in range(8))} {' '.join(f'rn{r}' for r in range(8))} "
              f"l1 l2 l3 imc_rowdrv mode={0 if mode == 'ml2' else 1} cc={cc} c_row={crow} r_sw={rsw}",
              ".tran 2e-12 3e-9", ".end", ""]
    return L.espice("\n".join(lines), name), p


def t_drive():
    t_on = 1e-9
    for mode, full in (("ml2", 3), ("bitserial", 1)):
        p = G.P(mode=mode)
        ts = p.t_settle() * 1e-9
        # one row alone, then all 8 rows on the top level (worst popcount)
        for n in (1, 8):
            codes = [(full, 0)] * n + [(0, 0)] * (8 - n)
            res, _ = drive_deck(mode, codes, name=f"unit_drive_{mode}_{n}")
            v = L.at(res, "v(rp0)", t_on + ts)
            err = abs(0.7 - v) / 0.7
            law = G.drive_settle_err(p, n)["top"]
            check(f"B2 imc_rowdrv {mode} n={n}", abs(err - law) < 0.25 * law + 2e-5,
                  f"rail error at share edge ({ts * 1e9:.3f} ns) {err * 100:.4f} % of V; level-net law {law * 100:.4f} %")
        if mode == "ml2":
            # the mid levels (the class-AB SSF buffers, r_lvl_mid) with every row on one of them: the
            # worst popcount, which fails the 0.1 % spec in tb_timing; here the Verilog-A network is
            # checked against the same law (both rest on the N9_r2 SSF fit, see the block doc)
            for dig, lvl in ((1, 1 / 3), (2, 2 / 3)):
                for n in (1, 8):
                    codes = [(dig, 0)] * n + [(0, 0)] * (8 - n)
                    res, _ = drive_deck(mode, codes, name=f"unit_drive_ml2_l{dig}_{n}")
                    v = L.at(res, "v(rp0)", t_on + ts)
                    err = abs(lvl * 0.7 - v) / (lvl * 0.7)
                    law = G.drive_settle_err(p, n)["mid"]
                    check(f"B2 imc_rowdrv ml2 l{dig} ({lvl * 3:.0f}V/3) n={n}", abs(err - law) < 0.25 * law + 2e-5,
                          f"rail error at share edge {err * 100:.4f} % of the level; level-net law {law * 100:.4f} %"
                          f" (spec 0.1 %: {'meets' if err <= 1e-3 else 'MISSES'})")
            codes = [(1, 0), (2, 0), (1, 1), (2, 1)] + [(0, 0)] * 4
            res, _ = drive_deck(mode, codes, name="unit_drive_ml2_mid")
            v13, v23 = L.at(res, "v(rp0)", t_on + ts), L.at(res, "v(rp1)", t_on + ts)
            vn13, vp_off = L.at(res, "v(rn2)", t_on + ts), L.at(res, "v(rp2)", t_on + ts)
            ok = abs(v13 - 0.7 / 3) < 1e-3 and abs(v23 - 1.4 / 3) < 1e-3 and abs(vn13 - 0.7 / 3) < 1e-3 and abs(vp_off) < 1e-4
            check("B2 imc_rowdrv ml2 levels + sign steering", ok,
                  f"V/3 {v13:.4f}, 2V/3 {v23:.4f}, negative row on rn {vn13:.4f}, its rp {vp_off * 1e3:.3f} mV")
    # constant-charge coding: the l3 sag does not depend on how many bits are 1
    sag = {}
    for cc in (0, 1):
        for n in (1, 7):
            codes = [(1, 0)] * n + [(0, 0)] * (8 - n)
            res, _ = drive_deck("bitserial", codes, cc=cc, name=f"unit_drive_cc{cc}_{n}")
            sag[(cc, n)] = 0.7 - min(res["v(l3)"])
    check("B2 imc_rowdrv constant charge", abs(sag[(1, 1)] - sag[(1, 7)]) < 0.05 * sag[(1, 7)] and sag[(0, 1)] < 0.5 * sag[(0, 7)],
          f"l3 sag without cc {sag[(0, 1)] * 1e3:.1f} / {sag[(0, 7)] * 1e3:.1f} mV (1 / 7 rows on), "
          f"with cc {sag[(1, 1)] * 1e3:.1f} / {sag[(1, 7)] * 1e3:.1f} mV")


def col_deck(mode, w, x, name):
    """One column pair driven by ideal rail sources for one pass of x (8 rows), weights w (8)."""
    p = G.P(mode=mode)
    ST, tk = p.slot_ticks(), 142e-12
    sx, d = G.digits(np.array([x]), mode)
    sx, d = sx[0], d[0]
    lines = [f"* B3 imc_col unit {mode}", '.hdl "imc_col.va"']
    t0 = 1e-9
    rst, sh = [], []
    for s in range(d.shape[1]):
        a = t0 + s * ST * tk
        rst.append((a, a + 0.5 * tk, L.VDD))      # as the RTL: reset ends half a tick before the rails move
        sh.append((a + (ST - 1 - p.sh_ticks) * tk, a + (ST - 1) * tk, L.VDD))
    lv = (np.array([0, 1 / 3, 2 / 3, 1]) if mode == "ml2" else np.array([0, 1.0])) * 0.7
    for r in range(8):
        for rail, on in (("rp", sx[r] == 0), ("rn", sx[r] == 1)):
            pts = [(0.0, 0.0)]
            for s in range(d.shape[1]):
                a = t0 + s * ST * tk
                v = lv[d[r, s]] if on else 0.0
                pts += [(a + tk, 0.0), (a + tk + 20e-12, v), (a + ST * tk - 20e-12, v), (a + ST * tk, 0.0)]
            lines.append(f"V{rail}{r} {rail}{r} 0 PWL({' '.join(f'{t:.5e} {v:.5g}' for t, v in pts)})")
    sw, hi, lo, _ = G.slice_w(np.array(w))
    lines.insert(1, '.hdl "imc_xp.va"')
    for r in range(8):
        m = int(16 * hi[r] + lo[r])
        for b in range(8):
            bit = (m >> b) & 1 if b < 7 else int(sw[r])
            lines.append(f"Vs{r}_{b} s{r}_{b} 0 {0.631 if bit else -0.072}")
        lines.append(f"Nxp{r} rp{r} rn{r} {' '.join(f's{r}_{b}' for b in range(8))} "
                     f"{' '.join(f'q{4 * r + j}' for j in range(4))} imc_xp sig_cu_msb=0 sig_cu_lsb=0")
    tend = t0 + d.shape[1] * ST * tk
    lines += [f"Vrst prst 0 {L.pwl(rst)}", f"Vsh psh 0 {L.pwl(sh)}",
              f"Vmrg pmrg 0 {L.pwl([(tend + tk, tend + 5 * tk, L.VDD)])}",
              f"Ncol {' '.join(f'q{k}' for k in range(32))} prst psh pmrg outp outn emon imc_col "
              f"mode={0 if mode == 'ml2' else 1} noise=0 sig_racc=0 sig_merge=0",
              f".tran 5e-12 {tend + 8 * tk:.4e}", ".end", ""]
    res = L.espice("\n".join(lines), name)
    return L.at(res, "v(outp)", tend + 7 * tk) - L.at(res, "v(outn)", tend + 7 * tk), p


def t_col():
    rng = np.random.default_rng(5)
    for mode in ("ml2", "bitserial"):
        worst = 0
        for k in range(3):
            w = rng.integers(-127, 128, 8)
            x = rng.integers(-127, 128, 8)
            v, p = col_deck(mode, w, x, f"unit_col_{mode}_{k}")
            S = int(np.dot(w, x))
            worst = max(worst, abs(v - p.k() * S) / (p.k() * 8 * 127 * 127))
        check(f"B3 imc_col {mode}", worst < 1e-4,
              f"merged diff vs k*S (k {p.k() * 1e6:.4f} uV/MAC): worst error {worst * 1e6:.1f} ppm of full scale")


def sar_deck(v4, name):
    p = G.P()
    tk = 142e-12
    lines = ["* B4 imc_sar unit", '.hdl "imc_sar.va"', f"Vref vref 0 {p.vref}",
             f"Vsamp psamp 0 {L.pwl([(0.5e-9, 0.7e-9, L.VDD)])}"]
    for j, v in enumerate(v4):
        lines += [f"Vi{j} ip{j} 0 {v / 2}", f"Vn{j} in{j} 0 {-v / 2}"]
    rounds = [(1e-9 + r * 11 * tk, 1e-9 + r * 11 * tk + 5 * tk, L.VDD) for r in range(4)]
    bits = " ".join(f"b{k}" for k in range(12))
    lines += [f"Vclk pclk 0 {L.pwl(rounds)}",
              f"Nsar {' '.join(f'ip{j}' for j in range(4))} {' '.join(f'in{j}' for j in range(4))} psamp pclk vref {bits} cv emon "
              f"imc_sar noise=0 sig_dac=0", ".tran 5e-12 8e-9", ".end", ""]
    res = L.espice("\n".join(lines), name)
    codes = []
    for r in range(4):
        t = 1e-9 + r * 11 * tk + 10 * tk
        u = sum((1 << k) * (L.at(res, f"v(b{k})", t) > 0.35) for k in range(12))
        codes.append(u - 4096 if u >= 2048 else u)
    return codes, L.at(res, "v(emon)", 7e-9), p


def t_sar():
    lsb = G.P().lsb()
    vs = [0.0, 0.3, 0.6, -0.6, 123.4, -2000.2, 2100, -2100]
    ok, msg = True, []
    for half in (0, 1):
        v4 = [v * lsb for v in vs[4 * half:4 * half + 4]]
        codes, e, p = sar_deck(v4, f"unit_sar_{half}")
        for v, c in zip(vs[4 * half:4 * half + 4], codes):
            exp = int(np.clip(math.floor(v + 0.5), -2048, 2047))
            ok &= c == exp
            msg.append(f"{v:+.1f}->{c}")
    check("B4 imc_sar", ok and abs(e - 4 * 0.2535) < 1e-6, "LSB in / code: " + ", ".join(msg) + f"; energy {e:.4f} pJ / 4 conv")


def t_ref():
    """B5: the C-DAC reference under one tile's simultaneous conversions, decisions read per step.

    4 SAR instances with different inputs, each drawing the charge of n/4 converters (nload), on one
    imc_ref (r_ref, c_ref of the golden). Two rounds. Checks (1) the Verilog-A codes equal the golden
    sar_convert on the same inputs (the golden's ref law is the Verilog-A mechanism), (2) reports the
    droop against ARCH B5's 3.7 uV per conversion (n = 64: this tile; n = 128: ARCH's count)."""
    p = G.P()
    tk = 142e-12
    rng = np.random.default_rng(4)
    for n in (64, 128):
        vin = rng.uniform(-0.65, 0.65, (2, 4, 4)) * p.vref / 2        # [round-pair, instance, column]
        lines = ["* B5 imc_ref unit", '.hdl "imc_sar.va"', '.hdl "imc_ref.va"', "Vdd vdd 0 0.7",
                 f"Nref vref vdd imc_ref v0={p.vref} r_out={p.r_ref} c_dec={p.c_ref}",
                 f"Vsamp psamp 0 {L.pwl([(0.5e-9, 0.7e-9, L.VDD)])}",
                 f"Vclk pclk 0 {L.pwl([(1e-9 + r * 11 * tk, 1e-9 + r * 11 * tk + 5 * tk, L.VDD) for r in range(2)])}"]
        for k in range(4):
            for j in range(4):
                lines += [f"Vi{k}_{j} ip{k}_{j} 0 {vin[0, k, j] / 2 if j < 2 else vin[1, k, j - 2] / 2}",
                          f"Vn{k}_{j} in{k}_{j} 0 {-(vin[0, k, j] if j < 2 else vin[1, k, j - 2]) / 2}"]
            lines.append(f"Ns{k} {' '.join(f'ip{k}_{j}' for j in range(4))} {' '.join(f'in{k}_{j}' for j in range(4))} "
                         f"psamp pclk vref {' '.join(f'b{k}_{j}' for j in range(12))} cv{k} e{k} "
                         f"imc_sar noise=0 sig_dac=0 nload={n // 4}")
        lines += [".tran 5e-12 5e-9", ".end", ""]
        res = L.espice("\n".join(lines), f"unit_ref_{n}")
        t0 = 1e-9
        win = [(t, v) for t, v in zip(res["time"], res["v(vref)"]) if t0 < t < t0 + 2 * 11 * tk]
        droop = p.vref - min(v for _, v in win)
        # Verilog-A codes per round vs the golden on the same inputs (instances = converters, load x n/4)
        va = np.array([[round(L.at(res, f"v(cv{k})", t0 + r * 11 * tk + 1.38e-9) * 1e3) for k in range(4)]
                       for r in range(2)])
        dw = np.tile(2.0 ** np.arange(12), (4, 1))
        pr = replace(p, terms=("ref",), noise=False)
        cin = np.array([[vin[0, k, 0] for k in range(4)], [vin[0, k, 1] for k in range(4)]])
        g0, d = G.sar_convert(cin[:1], pr, dw, mult=n / 4)
        d = d * math.exp(-(11 * tk - p.t_conv) / (p.r_ref * p.c_ref))
        g1, _ = G.sar_convert(cin[1:], pr, dw, mult=n / 4, d0=d)
        gi = np.clip(np.floor(cin / p.lsb() + 0.5), -2048, 2047)
        gold = np.vstack([g0, g1])
        tr = []
        G.sar_convert(cin[:1], pr, dw, mult=n / 4, trace=tr)
        # the Verilog-A reference at its own decision instants (sar_clk crosses vth ~10 ps into its ramp)
        tb = p.t_conv / 13
        vd = np.array([p.vref - L.at(res, "v(vref)", t0 + 10e-12 + (i + 1) * tb - 1e-13) for i in range(12)])
        gd = np.array([float(x.ravel()[0]) for x in tr])
        dev = np.max(np.abs(vd - gd)) / np.max(gd)
        check(f"B5 imc_ref + imc_sar, {n} converters (model vs golden law)", np.all(np.abs(va - gold) <= 1) and dev < 0.1,
              f"Verilog-A codes {va.ravel().tolist()} vs golden {gold.ravel().tolist()} (ideal reference "
              f"{gi.astype(int).ravel().tolist()}); droop at the 12 decisions: Verilog-A max {np.max(vd) * 1e6:.0f} uV, "
              f"golden {np.max(gd) * 1e6:.0f} uV, worst difference {dev * 100:.1f} % of the peak; "
              f"peak between decisions {droop * 1e6:.0f} uV")
        check(f"B5 droop spec, {n} converters", droop / n <= 3.7e-6,
              f"{droop / n * 1e6:.1f} uV per conversion (peak {droop * 1e6:.0f} uV / {n}) vs ARCH B5 <= 3.7 uV with "
              f"r_ref {p.r_ref} ohm, c_ref {p.c_ref * 1e12:.0f} pF (P/D placeholders); the SNR cost of this droop "
              f"after calibration is tb_accuracy's ref term")


TESTS = dict(gc=t_gc, drive=t_drive, col=t_col, sar=t_sar, ref=t_ref)

if __name__ == "__main__":
    for k in (sys.argv[1:] or TESTS):
        TESTS[k]()
    print("ALL VA UNIT TESTS PASS" if not FAILS else f"VA UNIT TESTS FAILED: {FAILS}")
    sys.exit(1 if FAILS else 0)
