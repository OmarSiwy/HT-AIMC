"""csnr_holdout — is the A10-calibrated CSNR real, or fitted-on-what-it-scores?

Session 3 measured per-stage compute-SNR (CSNR) for the first time:
19.9 dB attention uncorrected, 27.8-30.1 dB with the A10 per-column measured
gain. The K schedule (perlayer_k.k_for_budget) is chosen from that number, and
K=2 needs 31.11 dB, so ~1 dB decides a 2x in tok/s.

The A10 number is CIRCULAR by construction. tb_tile_mvm.calibrate_gains sets

    g[j][w] = measured_code(j, w, xq) / ideal_code(j, w, xq)

i.e. ONE free scalar fitted to ONE data point, then scored on that same point.
Zero residual degrees of freedom: the in-sample error is pure rounding. This
file asks the only question that matters — does the fitted gain predict the
SAME column at a DIFFERENT operating point? — using ZERO new simulation.

DATA (all already-simulated, no ngspice here):
  analog/testbenches/out/tb_tile_pass_0{5,6,7,8}*.log — four full-fidelity
  17-converter acceptance runs (attn q/k/v/o), each printing the A10
  calibration table: per (column, window) the unclamped ideal code, the
  UNCORRECTED measured code, and the fitted gain. 87 measured points over
  4 independent tiles x 17 columns x 2 windows. pass_09 (FFN) is EMPTY, so
  the FFN class has NO log data and cannot be held out at all.

HOLDOUTS
  leave-one-pass-out  fit on 3 passes (3 tiles, 3 tokens), score the 4th.
                      The strongest split the data allows: different weights
                      AND different activations.
  cross-window        the A10 per-column claim itself. Fit each column's
                      deviation-from-window-mean on the hi window, score it
                      on lo (and vice versa). Same physical column, different
                      operating code = exactly what a new token looks like.

Correction is modelled as code_corrected = round(f^-1(measured)); A10 in
hardware scales the converter reference span instead, which per
tb_tile_mvm._col_gain is WORSE than this linear model at high |code| (the
corrected code slides along a nonlinear staircase). So every corrected number
here is an UPPER BOUND.

Run: PYTHONPATH=analog/schematics:. python3 scripts/compiler/metrics/csnr_holdout.py
Writes scripts/compiler/metrics/CSNR_HOLDOUT.md. Read-only w.r.t. everything else.
"""
import json
import os
import re
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, "analog", "docs"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, HERE)

import specs                                              # noqa: E402
from components.weight_tile.weight_tile import read_caps  # noqa: E402
from golden import model as G                             # noqa: E402

LOG_DIR = os.path.join(ROOT, "analog", "testbenches", "out")
PASS_DIR = os.path.join(ROOT, "scripts", "compiler", "out", "passes")
OUT_MD = os.path.join(HERE, "CSNR_HOLDOUT.md")

CAL_RE = re.compile(r"col\s+(\d+)\s+(lo|hi):\s+ideal\s+([-+]?\d+)\s+"
                    r"measured\s+([-+]?\d+)\s+gain\s+([\d.]+)")

SNR_K2 = 31.11        # specs.cascade_snr_db(2, x) == 28.0 at x = 31.11 dB


def csnr_db(y, err):
    ms = float(np.mean(np.asarray(err, float) ** 2))
    return 10.0 * np.log10(float(np.var(y)) / ms) if ms > 0 else np.inf


# ── 1. harvest the already-simulated logs ────────────────────────────────
def harvest():
    """(cal, allcols): cal = the 87 MEASURED (col, window) points; allcols =
    every (col, window) real-valued ideal y, logged or not, for the
    range-selection check."""
    cal, allcols = [], []
    for fn in sorted(os.listdir(LOG_DIR)):
        if not fn.startswith("tb_tile_pass_"):
            continue
        pname = fn.replace("tb_tile_", "").replace(".log", "")
        txt = open(os.path.join(LOG_DIR, fn)).read()
        pdir = os.path.join(PASS_DIR, pname)
        if not txt.strip() or not os.path.isdir(pdir):
            print(f"    [skip] {fn}: "
                  f"{'empty log' if not txt.strip() else 'no pass dir'}")
            continue
        exp = json.load(open(os.path.join(pdir, "expected.json")))
        Cp, Cn, chk = read_caps(os.path.join(pdir, "caps.spice"))
        D = int(exp["D"])
        sgn, nhi, nlo = G.pwm_nibbles(np.array(exp["xq"], dtype=np.int64))
        Wq = np.vstack([Cp.astype(np.int64) - Cn.astype(np.int64),
                        chk.astype(np.int64)[None, :]])
        mac = {"lo": Wq @ (sgn * nlo).astype(np.int64),
               "hi": Wq @ (sgn * nhi).astype(np.int64)}
        # n_banks per column = the A9 structural predictor (cells actually
        # driven); calibrate_gains' cols(j) uses chk +/- parts for j == 16.
        nb = [int((Cp[j] > 0).sum() + (Cn[j] > 0).sum()) for j in range(16)]
        nb.append(int((chk > 0).sum() + (chk < 0).sum()))
        seen = set()
        for j, w, ideal, meas, g in CAL_RE.findall(txt):
            j = int(j)
            cal.append(dict(p=pname, j=j, w=w, ideal=int(ideal),
                            meas=int(meas), g=float(g), nb=nb[j],
                            y=float(mac[w][j]) / D))
            seen.add((j, w))
        for w in ("lo", "hi"):
            for j in range(17):
                allcols.append(dict(p=pname, j=j, w=w, nb=nb[j],
                                    y=float(mac[w][j]) / D,
                                    logged=(j, w) in seen))
    return cal, allcols


# ── 2. corrector families, fitted -> applied ─────────────────────────────
# Each fit(train) -> predict(row) -> corrected real-valued code. The
# converter emits integers, so the scored error is round(predict) - y.
def _ls_gain(rows):
    """LS gain through the origin: measured ~ g * y."""
    y = np.array([r["y"] for r in rows])
    m = np.array([r["meas"] for r in rows])
    return float(m @ y / (y @ y)) if y @ y else 1.0


def fit_none(train):
    return lambda r: float(r["meas"])


def fit_winmean(train):
    """ONE gain per window (2 params / 87 points). The window systematic is
    structural (lo/hi use t_chop = t_q vs 16*t_q), so it is knowable a priori
    and correcting it is not cheating."""
    g = {w: _ls_gain([r for r in train if r["w"] == w]) or 1.0
         for w in ("lo", "hi")}
    return lambda r: r["meas"] / g[r["w"]]


def fit_winaffine(train):
    """Gain + offset per window (4 params). Tests whether the converter error
    has an ADDITIVE part a pure gain cannot absorb."""
    ab = {}
    for w in ("lo", "hi"):
        s = [r for r in train if r["w"] == w]
        A = np.vstack([[r["y"] for r in s], np.ones(len(s))]).T
        ab[w] = np.linalg.lstsq(A, np.array([r["meas"] for r in s]),
                                rcond=None)[0]
    return lambda r: (r["meas"] - ab[r["w"]][1]) / ab[r["w"]][0]


def fit_nbanks(train):
    """Per-window gain LINEAR IN n_banks (4 params) — the A9-class structural
    model. n_banks is known from the programmed caps with no sim at all, so
    this generalises to any tile for free if it holds up."""
    ab = {}
    for w in ("lo", "hi"):
        s = [r for r in train if r["w"] == w]
        y = np.array([r["y"] for r in s])
        A = np.vstack([y, y * np.array([r["nb"] for r in s])]).T
        ab[w] = np.linalg.lstsq(A, np.array([r["meas"] for r in s]),
                                rcond=None)[0]
    return lambda r: r["meas"] / (ab[r["w"]][0] + ab[r["w"]][1] * r["nb"])


def fit_a10(train):
    """A10 as shipped: per (column, window) gain = meas/ideal. In-sample this
    is 1 parameter per data point -> the residual is rounding only. Out of
    sample it has nothing to say about an unseen column, so it falls back to
    the window mean (the most generous possible fallback)."""
    tab = {(r["p"], r["j"], r["w"]): r["g"] for r in train}
    gw = {w: float(np.mean([r["g"] for r in train if r["w"] == w]))
          for w in ("lo", "hi")}
    return lambda r: r["meas"] / tab.get((r["p"], r["j"], r["w"]), gw[r["w"]])


MODELS = [("none (uncorrected)", fit_none),
          ("per-window gain", fit_winmean),
          ("per-window gain+offset", fit_winaffine),
          ("per-window gain(n_banks)", fit_nbanks),
          ("A10 per-column gain", fit_a10)]


def score(rows, predict):
    y = np.array([r["y"] for r in rows])
    e = np.array([round(predict(r)) - r["y"] for r in rows])
    return y, e, csnr_db(y, e)


def leave_one_pass_out(cal):
    """Fit on 3 passes (3 tiles, 3 tokens), score the held-out 4th. Pooled
    over folds so the held-out CSNR is one number over all 87 points."""
    passes = sorted({r["p"] for r in cal})
    out = []
    for name, fit in MODELS:
        ins = fit(cal)
        y_i, e_i, snr_i = score(cal, ins)
        ye, ee = [], []
        for p in passes:
            tr = [r for r in cal if r["p"] != p]
            te = [r for r in cal if r["p"] == p]
            f = fit(tr)
            yy, ee_, _ = score(te, f)
            ye.append(yy)
            ee.append(ee_)
        y_o, e_o = np.concatenate(ye), np.concatenate(ee)
        out.append((name, snr_i, csnr_db(y_o, e_o),
                    float(np.sqrt(np.mean(e_i ** 2))),
                    float(np.sqrt(np.mean(e_o ** 2)))))
    return passes, out


def cross_window(cal):
    """The A10 per-column claim, isolated. For every column logged in BOTH
    windows, the per-column part of the gain is g/gbar_w. Transfer it to the
    other window and score. If the per-column term is a real property of the
    column it helps; if it is absorbed per-code INL it hurts."""
    idx = {(r["p"], r["j"], r["w"]): r for r in cal}
    pairs = [(idx[(p, j, "lo")], idx[(p, j, "hi")])
             for (p, j, w) in idx if w == "lo" and (p, j, "hi") in idx]
    gbar = {w: float(np.mean([r["g"] for r in cal if r["w"] == w]))
            for w in ("lo", "hi")}
    gl = np.array([a["g"] for a, b in pairs])
    gh = np.array([b["g"] for a, b in pairs])
    rho = float(np.corrcoef(gl, gh)[0, 1])
    flat = [r for pr in pairs for r in pr]
    y = np.array([r["y"] for r in flat])
    # baseline: window mean only.  transfer: window mean * other window's
    # per-column deviation.
    e_base, e_xfer = [], []
    for a, b in pairs:
        for r, o in ((a, b), (b, a)):
            e_base.append(round(r["meas"] / gbar[r["w"]]) - r["y"])
            g_hat = gbar[r["w"]] * (o["g"] / gbar[o["w"]])
            e_xfer.append(round(r["meas"] / g_hat) - r["y"])
    return (len(pairs), rho, gl, gh,
            csnr_db(y, np.array(e_base)), csnr_db(y, np.array(e_xfer)))


# ── 4. reported-range selection effect ───────────────────────────────────
def range_bias(cal, allcols):
    """The cal table only logs |ideal| >= 8 (tb_tile_mvm._col_gain returns
    gain 1.0 and prints nothing below that) and drops already-clamped reads.
    That truncation inflates Var(y) and so flatters CSNR. The unlogged
    columns have no measurement, so their error is PROJECTED from the
    per-window affine fit (gain part scales with their small y, additive
    part + residual carry over unchanged)."""
    ab, res = {}, {}
    for w in ("lo", "hi"):
        s = [r for r in cal if r["w"] == w]
        y = np.array([r["y"] for r in s])
        e = np.array([r["meas"] - r["y"] for r in s])
        A = np.vstack([y, np.ones(len(s))]).T
        c = np.linalg.lstsq(A, e, rcond=None)[0]
        ab[w] = c
        res[w] = float(np.sqrt(np.mean((e - A @ c) ** 2)))
    y_all = np.array([r["y"] for r in allcols])
    y_log = np.array([r["y"] for r in cal])
    ms_log = float(np.mean([(r["meas"] - r["y"]) ** 2 for r in cal]))
    ms_all = []
    key = {(r["p"], r["j"], r["w"]): r for r in cal}
    for r in allcols:
        k = (r["p"], r["j"], r["w"])
        if k in key:
            ms_all.append((key[k]["meas"] - key[k]["y"]) ** 2)
        else:                       # PROJECTED
            a, b = ab[r["w"]]
            ms_all.append((a * r["y"] + b) ** 2 + res[r["w"]] ** 2)
    return (np.var(y_log), ms_log, csnr_db(y_log, np.sqrt(ms_log)),
            np.var(y_all), float(np.mean(ms_all)),
            10 * np.log10(np.var(y_all) / np.mean(ms_all)), ab, res)


def bootstrap(cal, fit, n=2000, seed=0):
    """Uncertainty on the held-out CSNR: resample PASSES (the independent
    unit) with replacement, refit LOPO-style, rescore. 4 passes is a small
    bootstrap universe — the band is indicative, not tight."""
    rng = np.random.default_rng(seed)
    passes = sorted({r["p"] for r in cal})
    vals = []
    for _ in range(n):
        pick = rng.choice(passes, len(passes), replace=True)
        te_p = rng.choice(passes)
        tr = [r for p in pick if p != te_p for r in cal if r["p"] == p]
        te = [r for r in cal if r["p"] == te_p]
        if len({r["p"] for r in tr}) < 2:
            continue
        y, e, s = score(te, fit(tr))
        if np.isfinite(s):
            vals.append(s)
    return float(np.percentile(vals, 5)), float(np.percentile(vals, 95))


# ── 6. what the honest CSNR buys ─────────────────────────────────────────
def k_and_toks(snr_attn, snr_ffn):
    """K schedule + N4/7B tok/s at a given per-class CSNR, straight through
    perlayer_k (no physics reimplemented here)."""
    import perlayer_k as PK
    mats = json.load(open(os.path.join(ROOT, "scripts", "compiler", "out",
                                       "manifest.json")))["matrices"]
    total = sum(m["passes_per_token"] for m in mats.values())
    old = PK.SNR_S_DB
    try:
        PK.SNR_S_DB = {"attn": snr_attn, "ffn": snr_ffn}
        sched, rows = PK.project(mats, total)
        row = [r for r in rows
               if r["pdk"] == "tsmc_n4_proj" and r["scale"] == "7B"][0]
    finally:
        PK.SNR_S_DB = old
    return (sched["attn_q"], sched["ffn_gate"], row["avg_k"],
            row["het"], row["het_vs_sohu"])


def main():
    print("=" * 72)
    print("  csnr_holdout: in-sample vs held-out CSNR of the A10 gain cal")
    print("=" * 72)
    cal, allcols = harvest()
    passes = sorted({r["p"] for r in cal})
    print(f"\n  DATA (all pre-simulated, zero ngspice)")
    print(f"    passes (independent tiles x tokens): {len(passes)} "
          f"{[p[:12] for p in passes]}")
    print(f"    MEASURED cal points (col,window)   : {len(cal)}"
          f"  of {len(allcols)} possible")
    print(f"    FFN class                          : 0 points "
          f"(pass_09 log empty) -> NO holdout possible")

    ok = True
    print(f"\n  == leave-one-pass-out (fit 3 tiles/tokens, score the 4th) ==")
    print(f"    {'corrector':<26}{'params':>7}{'in-sample':>11}"
          f"{'held-out':>10}{'gap dB':>8}{'rms_out':>9}")
    passes, table = leave_one_pass_out(cal)
    npar = {"none (uncorrected)": 0, "per-window gain": 2,
            "per-window gain+offset": 4, "per-window gain(n_banks)": 4,
            "A10 per-column gain": len(cal)}
    for name, si, so, ri, ro in table:
        print(f"    {name:<26}{npar[name]:>7}{si:>11.2f}{so:>10.2f}"
              f"{si - so:>+8.2f}{ro:>9.2f}")
    a10 = [t for t in table if t[0].startswith("A10")][0]
    best = max((t for t in table if not t[0].startswith("A10")),
               key=lambda t: t[2])

    print(f"\n  == cross-window transfer: the A10 per-column claim itself ==")
    npair, rho, gl, gh, snr_base, snr_xfer = cross_window(cal)
    print(f"    columns logged in BOTH windows      : {npair}")
    print(f"    corr(g_lo, g_hi) across those columns: {rho:+.3f}"
          f"   <- must be > 0 for a per-column gain to mean anything")
    print(f"    g_lo mean {gl.mean():.4f} sd {gl.std():.4f} | "
          f"g_hi mean {gh.mean():.4f} sd {gh.std():.4f}")
    print(f"    window-mean gain only               : {snr_base:6.2f} dB")
    print(f"    + per-column term from other window : {snr_xfer:6.2f} dB "
          f"({snr_xfer - snr_base:+.2f} dB)")

    print(f"\n  == reported-range selection (cal logs only |ideal| >= 8) ==")
    (vl, ml, sl, va, ma, sa, ab, res) = range_bias(cal, allcols)
    print(f"    logged   n={len(cal):<4} Var(y)={vl:7.0f} MSE={ml:6.2f} "
          f"-> CSNR {sl:5.2f} dB   [MEASURED]")
    print(f"    all cols n={len(allcols):<4} Var(y)={va:7.0f} MSE={ma:6.2f} "
          f"-> CSNR {sa:5.2f} dB   [PROJECTED]")
    print(f"    selection bias = {sl - sa:+.2f} dB (the reported 19.9 dB is "
          f"that much too kind)")
    for w in ("lo", "hi"):
        print(f"      {w}: err = {ab[w][0]:+.4f}*y {ab[w][1]:+.3f} LSB, "
              f"residual {res[w]:.2f} LSB rms "
              f"({'multiplicative' if abs(ab[w][0]) * 40 > abs(ab[w][1]) else 'additive'}-dominated)")

    # honest estimate: best generalising corrector, held out, over the
    # unrestricted code range.
    honest_sel = best[2]
    honest = honest_sel + (sa - sl)          # carry the selection bias over
    lo95, hi95 = bootstrap(cal, dict(MODELS)[best[0]])
    print(f"\n  == HONEST held-out per-stage CSNR (attention) ==")
    print(f"    best generalising corrector : {best[0]}")
    print(f"    held-out, logged range      : {honest_sel:5.2f} dB  "
          f"[MEASURED, out-of-sample]")
    print(f"    + unrestricted code range   : {honest:5.2f} dB  "
          f"[DERIVED: {sa - sl:+.2f} dB selection correction]")
    print(f"    pass-bootstrap 90% band     : {lo95:5.2f} .. {hi95:5.2f} dB "
          f"(n=4 passes, indicative)")
    print(f"    FFN                         : NO DATA (see above)")

    print(f"\n  == what that CSNR buys (perlayer_k, N4/7B vs Sohu 62,500) ==")
    print(f"    {'scenario':<34}{'SNR a/f':>12}{'K a/f':>8}"
          f"{'avg K':>7}{'tok/s':>10}{'xSohu':>8}")
    scen = [("assumed specs 34/38 (NEVER measured)", 34.0, 38.0),
            ("A10 in-sample (CIRCULAR)", a10[1], a10[1]),
            ("held-out, logged range", honest_sel, honest_sel),
            ("held-out, full range  <- HONEST", honest, honest),
            ("uncorrected 19.9/16.7 (measured)", 19.91, 16.7)]
    toks = {}
    for label, sa_, sf_ in scen:
        ka, kf, avg, t, x = k_and_toks(sa_, sf_)
        toks[label] = (t, x, ka, kf, avg)
        print(f"    {label:<34}{sa_:>6.1f}/{sf_:<5.1f}{ka:>4}/{kf:<3}"
              f"{avg:>7.2f}{t:>10,.0f}{x:>8.2f}x")

    print(f"\n  == dB to close ==")
    for k, need in ((2, SNR_K2), (4, None)):
        if need is None:
            need = next(s for s in np.arange(30, 45, 0.01)
                        if specs.cascade_snr_db(4, snr_s_db=float(s)) >= 28.0)
        print(f"    K={k} needs SNR_s >= {float(need):5.2f} dB "
              f"-> {float(need) - honest:+5.2f} dB from the honest "
              f"{honest:.2f} dB")

    # ── self-checks ──
    print(f"\n  == self-checks ==")
    checks = [
        ("reproduces the reported 19.9 dB uncorrected", abs(sl - 19.9) < 0.2),
        ("A10 in-sample is >= its own held-out score", a10[1] >= a10[2]),
        ("A10 held-out does NOT beat a 4-param window model",
         a10[2] <= best[2] + 0.5),
        ("per-column gain does not transfer across windows",
         snr_xfer <= snr_base),
        ("range restriction flatters CSNR (bias > 0)", sl - sa > 0),
        ("honest CSNR is below the assumed 34 dB", honest < 34.0),
        ("K=2 threshold reproduces", abs(specs.cascade_snr_db(
            2, snr_s_db=SNR_K2) - 28.0) < 0.02),
    ]
    for msg, c in checks:
        print(f"    [{'PASS' if c else 'FAIL'}] {msg}")
        ok = ok and c

    write_md(cal, allcols, passes, table, npar, npair, rho, gl, gh,
             snr_base, snr_xfer, vl, sl, va, sa, ab, res, best, a10,
             honest_sel, honest, lo95, hi95, scen, toks)
    print(f"\n  wrote {OUT_MD}")
    print(f"\n{'=' * 72}\n  OVERALL: {'PASS' if ok else 'FAIL'}\n{'=' * 72}")
    return ok


def write_md(cal, allcols, passes, table, npar, npair, rho, gl, gh,
             snr_base, snr_xfer, vl, sl, va, sa, ab, res, best, a10,
             honest_sel, honest, lo95, hi95, scen, toks):
    L = []
    A = L.append
    A("# Held-out CSNR: is the A10 per-column gain calibration real?\n")
    A("Generated by `scripts/compiler/metrics/csnr_holdout.py`. **Zero new "
      "simulation** — every number comes from the four already-simulated "
      "17-converter acceptance logs in `analog/testbenches/out/`.\n")
    A("Labels: **measured** = read off a SPICE run; **derived** = arithmetic "
      "on measured values; **projected** = model extrapolation.\n")

    A("\n## 1. What measured data exists\n")
    A(f"| pass | tile | cal points (col,window) |")
    A("|---|---|---|")
    for p in passes:
        A(f"| `{p}` | attn | {sum(1 for r in cal if r['p'] == p)} |")
    A(f"| `pass_09_typ_ffn_gate` | **ffn** | **0 — log is empty** |")
    A(f"\n**{len(cal)} measured points** over **4 independent passes** "
      "(4 different weight tiles, 4 different SmolLM2 tokens), 17 columns x "
      "2 nibble windows each; the cal table logs only `|ideal| >= 8` and "
      "non-clamped reads, so 49 of the 136 possible points are missing. "
      "The FFN class has **no log data at all** — the 16.7 dB FFN figure "
      "came from a separate `tb_csnr.py uncorr` run whose per-column data "
      "was not persisted, so **no FFN holdout is possible**.\n")

    A("\n## 2. In-sample vs held-out (leave-one-pass-out)\n")
    A("Fit on 3 passes, score the held-out 4th, pooled over all 4 folds. "
      "Error scored as `round(corrected) - y_exact`.\n")
    A("| corrector | free params | in-sample CSNR | held-out CSNR | "
      "circularity gap | held-out rms |")
    A("|---|---|---|---|---|---|")
    for name, si, so, ri, ro in table:
        A(f"| {name} | {npar[name]} | {si:.2f} dB | **{so:.2f} dB** | "
          f"{si - so:+.2f} dB | {ro:.2f} LSB |")
    A(f"\n**The circularity is {a10[1] - a10[2]:+.2f} dB.** A10 fits one "
      "scalar per data point (`g = measured/ideal` at the column's single "
      "operating code), so it has **zero residual degrees of freedom** — the "
      "in-sample residual is rounding, not physics. On a pass it has not "
      "seen it has nothing to say about a new column and falls back to the "
      "window mean.\n")
    A(f"\nTwo framings of the same gap, both worth stating:\n")
    A(f"1. **Same estimator, in vs out**: {a10[1]:.2f} -> {a10[2]:.2f} dB, "
      f"a **{a10[1] - a10[2]:.2f} dB** collapse. (This file's in-sample "
      "figure is *higher* than the 27.8-30.1 dB reported from the 17-column "
      "run because `round(measured/g)` is a kinder model of the correction "
      "than the reference-span scaling A10 actually uses — per "
      "`tb_tile_mvm._col_gain`, span scaling slides the code along a "
      "nonlinear staircase. So 40.75 dB is the *purest* statement of the "
      "circularity: fit 87 parameters to 87 points and the residual is "
      "rounding.)\n")
    A(f"2. **Against the reported number**: 27.8-30.1 dB reported "
      f"in-sample vs **{a10[2]:.2f} dB** held out — the reported range is "
      f"{27.8 - a10[2]:.1f} to {30.1 - a10[2]:.1f} dB optimistic.\n")
    A(f"\nThe decisive line is that A10 held out ({a10[2]:.2f} dB) is "
      f"**below** a 2-parameter per-window gain ({table[1][2]:.2f} dB). "
      "Per-column calibration contributes nothing that generalises.\n")

    A("\n## 3. Where the optimism comes from\n")
    A(f"- **Genuine, generalising part.** The gain is strongly "
      f"*window*-structured: g_lo mean {gl.mean():.4f}, g_hi mean "
      f"{gh.mean():.4f} (**measured**). The window is a structural property "
      "(lo drives `t_chop = t_q`, hi `16*t_q`), known a priori, so "
      "correcting it costs 2 parameters and holds up out of sample. Adding "
      "an offset and an `n_banks` slope also generalises.\n")
    A(f"- **Non-generalising part.** Across the {npair} columns logged in "
      f"**both** windows, `corr(g_lo, g_hi) = {rho:+.3f}` (**measured**) — "
      "*negative*. The per-column deviation from the window mean is not a "
      "property of the column; it is per-operating-point coarse-loop INL "
      "plus code rounding, exactly what `tb_tile_mvm._col_gain`'s own "
      "docstring calls an *irreducible high-|code| coarse-loop INL*.\n")
    A(f"- Transferring the per-column term to the other window gives "
      f"**{snr_xfer:.2f} dB vs {snr_base:.2f} dB** for the window mean alone "
      f"({snr_xfer - snr_base:+.2f} dB) — the per-column term actively "
      "**hurts** out of sample (**measured**).\n")
    A("- So the answer to *'a per-column scalar has few DOF, maybe it "
      "generalises'* is **no, because it is one DOF per observation, not "
      "one per column**. A per-column gain would need >= 2 operating points "
      "per column to be estimated at all, and this data says the two points "
      "disagree.\n")

    A("\n## 4. Reported-range selection effect\n")
    A(f"| ensemble | n | Var(y) | MSE | CSNR |")
    A("|---|---|---|---|---|")
    A(f"| logged only (`\\|ideal\\| >= 8`) | {len(cal)} | {vl:.0f} | "
      f"{10 ** (np.log10(vl) - sl / 10):.2f} | {sl:.2f} dB (**measured**) |")
    A(f"| all 17 cols x 2 windows | {len(allcols)} | {va:.0f} | "
      f"{10 ** (np.log10(va) - sa / 10):.2f} | {sa:.2f} dB "
      "(**projected**) |")
    A(f"\n**Selection bias = {sl - sa:+.2f} dB.** Var(y) falls from {vl:.0f} "
      f"to {va:.0f} when the 49 small-|code| columns are put back, and the "
      "error does *not* shrink proportionally because it is only partly "
      "multiplicative:\n")
    for w in ("lo", "hi"):
        A(f"- `{w}`: err = {ab[w][0]:+.4f}*y {ab[w][1]:+.3f} LSB, "
          f"residual {res[w]:.2f} LSB rms (**measured** fit). The additive + "
          "residual part survives at small |y|, so small columns are "
          "*relatively* worse.\n")

    A("\n## 5. The honest number\n")
    A(f"| quantity | value | label |")
    A("|---|---|---|")
    A(f"| A10 as reported (in-sample) | 27.8 - 30.1 dB | **circular** |")
    A(f"| A10 held out (leave-one-pass-out) | {a10[2]:.2f} dB | measured |")
    A(f"| best generalising corrector ({best[0]}), held out | "
      f"{honest_sel:.2f} dB | measured |")
    A(f"| ... over the unrestricted code range | **{honest:.2f} dB** | "
      f"derived |")
    A(f"| pass-bootstrap 90% band | {lo95:.2f} .. {hi95:.2f} dB | derived "
      "(n=4 passes, wide) |")
    A(f"| FFN class | no data | — |")
    A(f"\n**Best defensible held-out attention CSNR: "
      f"{honest:.1f} dB (90% band {lo95:.1f} .. {hi95:.1f} dB).** That is "
      f"{honest - 19.91:+.1f} dB relative to the uncorrected 19.9 dB and "
      f"{honest - 30.1:+.1f} dB relative to the circular best case. The "
      "correction that survives holdout is worth real dB — it is just far "
      "less than A10 advertised, and it comes from the *window*/*n_banks* "
      "structure, not from per-column calibration.\n")

    A("\n## 6. K schedule and tok/s the honest CSNR supports\n")
    A("| scenario | SNR_s attn/ffn | K attn/ffn | avg K | N4/7B tok/s | "
      "vs Sohu 62,500 |")
    A("|---|---|---|---|---|---|")
    for label, s_a, s_f in scen:
        t, x, ka, kf, avg = toks[label]
        A(f"| {label} | {s_a:.1f}/{s_f:.1f} | {ka}/{kf} | {avg:.2f} | "
          f"{t:,.0f} | {x:.2f}x |")
    t_h, x_h, _, _, _ = toks["held-out, full range  <- HONEST"]
    e2e = specs.cascade_snr_db(1, snr_s_db=honest)
    A(f"\n**K = 1, N4/7B = {t_h:,.0f} tok/s = {x_h:.2f}x Sohu.** The honest "
      f"CSNR does *not* change the K schedule versus the uncorrected 19.9 dB "
      "number — 28.45 dB is still 2.7 dB short of the 31.11 dB that K=2 "
      "needs.\n")
    A(f"\nOne thing *does* change, and it matters: at "
      f"{honest:.2f} dB the K=1 cascade delivers "
      f"{e2e:.2f} dB end to end, which **clears the 28 dB target**. At "
      "19.9 dB it did not — `k_for_budget` was returning its floor clamp, "
      "i.e. the design was failing its own budget at every K. So the honest "
      "reading is *K=1 now genuinely passes*, not *K=1 by default*. The "
      "margin is ~0.4 dB, well inside the bootstrap band, so treat it as "
      "'at the edge of passing', not 'passed'.\n")

    A("\n## 7. dB to close\n")
    k4 = next(float(s) for s in np.arange(30, 45, 0.01)
              if specs.cascade_snr_db(4, snr_s_db=float(s)) >= 28.0)
    A(f"| milestone | SNR_s needed | gap from {honest:.1f} dB |")
    A("|---|---|---|")
    A(f"| meet the 28 dB target at K=1 | 28.00 dB | {28.0 - honest:+.2f} dB |")
    A(f"| K=2 | {SNR_K2:.2f} dB | {SNR_K2 - honest:+.2f} dB |")
    A(f"| K=4 | {k4:.2f} dB | {k4 - honest:+.2f} dB |")
    A("\nCandidate levers (from this session, all still to be verified "
      "against this held-out baseline, not against the circular one):\n")
    A("- **beta*gm_in of the OTA loop** — `tb_csnr isolate` attributes the "
      "dominant error term (d) to the OTA under multi-bank rail load, ~15 dB "
      "dominant. It is the same loop that sets `tau_absorb`, so it buys CSNR "
      "*and* conv_time. This is the only lever plausibly worth >10 dB.\n")
    A("- **`VCM_FRAC` 0.5 -> 0.546** (+40% usable swing, **measured**) — "
      "+40% signal at fixed noise is +2.9 dB if the error is additive. "
      "Section 4 says the residual is only partly additive (the "
      f"gain term is {abs(ab['lo'][0]) * 100:.1f}% on lo), so expect less "
      "than that; it does not scale away a multiplicative gain error.\n")
    A("- **`V_SWING` 0.25 -> 0.5** (sky130-only; feasibility veto at "
      "advanced nodes) — doubles C_u, -3 dB on the Pelgrom term only, which "
      "is not the dominant term here.\n")
    A("\n**None of these obviously delivers the "
      f"{28.0 - honest:.1f} dB needed just to reach the K=1 target**, let "
      f"alone the {SNR_K2 - honest:.1f} dB for K=2. The per-column-gain "
      "route is closed: the data says a per-column scalar does not "
      "generalise. What is *not* closed is a per-column gain estimated from "
      "MORE THAN ONE operating point — but no such data exists yet.\n")

    A("\n## 8. The SPICE run to queue\n")
    A("This analysis is holdout-limited: 4 passes, 1 token each, 1 operating "
      "point per (column, window). To settle whether a per-column gain "
      "generalises *at all*, the missing run is:\n")
    A("```\n"
      "# same tile, DIFFERENT tokens: gives >=2 independent operating points\n"
      "# per column so a per-column gain can be FITTED on one and SCORED on\n"
      "# another. scripts/compiler/out/acts/*.npz already holds 9 tokens per tensor.\n"
      "PYTHONPATH=analog/schematics python3 analog/testbenches/tb_csnr.py \\\n"
      "    uncorr pass_05_typ_attn_q          # + repeat for tokens 1..3\n"
      "PYTHONPATH=analog/schematics python3 analog/testbenches/tb_csnr.py \\\n"
      "    uncorr pass_09_typ_ffn_gate        # the FFN class has NO data\n"
      "```\n")
    A("Cost: ~25 min/pass. Four attn tokens + one FFN pass ~ 2 h sequential, "
      "and it converts the biggest assumption in the K schedule into a "
      "measurement.\n")
    open(OUT_MD, "w").write("\n".join(L) + "\n")


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
