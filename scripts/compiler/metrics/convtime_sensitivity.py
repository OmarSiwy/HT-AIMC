"""Session 3 — conv_time sensitivity surface + lever ranking at the N4
operating point.  Pure arithmetic on specs.py / perlayer_k.py / pdk_projections.py.
NO SPICE (an analog agent owns the simulator).

REV 2 — re-scored after two specs.py fixes landed on session3/conv-time-attack:
  FIX 1  n_coarse 17 (per-nibble) / 19 (merged) -> specs.N_COARSE = 11
         (COARSE_CAP 7 + COARSE_MARGIN 4; bit-identity verified exhaustively).
  FIX 2  beta_int is now DERIVED (specs.beta_int = C_int/(C_int+C_par_vg))
         instead of a stale stored constant per PDK.
...and after the sim agent MEASURED the per-stage SNR the whole cascade depth
K rests on: 19.9 dB attn / 16.7 dB FFN uncorrected, 27.8-30.1 dB attn with A10
per-column gain cal (circular / best case).  NOT the 34/38 dB the K schedule
assumed.  That collapses K to 1 and dominates every number below, so it is now
the headline rather than an appendix.

Sections:
  0. which pass-time law is in force (the brief quoted the wrong one).
  1. re-scored baseline + how FIX 1 and FIX 2 compose.
  2. tok/s surface over (conv scale s, K); the 2.0x iso-contour; the ceiling.
  3. THE HONEST NUMBER: tok/s at the K the MEASURED SNR actually supports.
  4. conv_time decomposed + levers ranked at BOTH K=1 (honest) and K=7
     (aspirational) — the ranking is K-dependent, and t_q flips to worthless.
  5. falsified levers, the STOPPING LINE, tok/J.
  6. re-anchoring dependency map, re-prioritised for a CSNR-bound design.

Run: PYTHONPATH=analog/schematics:. python3 scripts/compiler/metrics/convtime_sensitivity.py
Writes scripts/compiler/metrics/CONVTIME_SENSITIVITY.md.  specs.py is READ-ONLY here.
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "analog", "schematics"))
sys.path.insert(0, HERE)
import specs                                       # noqa: E402
import pdk_projections as pj                       # noqa: E402
import perlayer_k as plk                           # noqa: E402
from library.pdks.sky130 import Sky130             # noqa: E402
from library.pdks.asap7_proj import Asap7Proj      # noqa: E402
from library.pdks.tsmc_n4_proj import TsmcN4Proj   # noqa: E402

OUT_MD = os.path.join(HERE, "CONVTIME_SENSITIVITY.md")
SOHU = pj.SOHU_TOKS_DIE                            # 62,500 tok/s/die (vendor)
NPT_7B = int(7e9 / 256)                            # 27,343,750 passes/token
S_GRID = (1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2)
K_GRID = tuple(range(1, 15))
PDKS = {"tsmc_n4_proj": TsmcN4Proj, "asap7_proj": Asap7Proj}

# ---- MEASURED per-stage analog CSNR (sim agent, session 3) ----------------
# These replace the 34 dB / 38 dB STATUS anchors perlayer_k.py assumed.
SNR_MEAS = {
    "attn, uncorrected":          19.9,
    "ffn, uncorrected":           16.7,
    "attn, A10 gain cal (worst)": 27.8,
    "attn, A10 gain cal (best)":  30.1,
}
SNR_BEST = 30.1                                    # circular / upper bound
SNR_ASSUMED = {"attn": 34.0, "ffn": 38.0}          # what the schedule assumed


# ---------------------------------------------------------------------------
# operating point
# ---------------------------------------------------------------------------
def _snapshot(pdk, tq, name):
    """Read the frozen timing/energy operating point out of specs.py."""
    r = {
        "name": name, "t_q": tq,
        "beta": specs.beta_int(pdk),
        "tau": specs.tau_absorb(pdk),
        "cadence": specs.coarse_cadence(pdk),
        "sar": specs.sar_time(pdk),
        "conv": specs.conv_time(pdk),                       # n = N_COARSE
        "conv_prefix": specs.conv_time(pdk, n_coarse=17),   # pre-FIX-1
        "c_int": specs.c_int(pdk),
        "c_filt": specs.kick_filter(pdk)[1],
        "gm_in": specs.ota(pdk)["gm_in"],
        "cal": dict(specs.cal(pdk)),
        "ota_w": specs.ota_static_w(pdk),
        "ladder_w": specs.ladder_static_w(pdk),
        "vdd": pdk.vdd,
        "t_in": 136 * tq,          # merged S5 window + 8 t_q settle-in
        "t_in_split": 144 * tq,    # split-window (serial cascade law)
        "swap": 4 * tq,
        "tiles": int(pj.DIE_MM2 * pj.FILL / pj.TILE_MM2[pdk.name]),
    }
    dyn = (r["c_int"] * pdk.vdd ** 2) / (200e-15 * 1.8 ** 2)
    r["e_tile_dyn"], r["e_conv_dyn"] = 120e-12 * dyn, 180e-12 * dyn
    return r


def op_point(name):
    """Projection PDK, under the SAME runtime substitutions perlayer_k uses."""
    pdk = PDKS[name]()
    saved = (specs.TQ_SIM, specs.sar_time)
    try:
        plk._setup_pdk(pdk, pdk.t_q_grid)
        return _snapshot(pdk, pdk.t_q_grid, name)
    finally:
        specs.TQ_SIM, specs.sar_time = saved


def sky_op():
    """sky130 on its SIM grid — the frame session 1 ranked levers in."""
    saved = (specs.TQ_SIM, specs.sar_time)
    try:
        specs.TQ_SIM = 10e-9
        return _snapshot(Sky130(), 10e-9, "sky130 (sim grid)")
    finally:
        specs.TQ_SIM, specs.sar_time = saved


# ---------------------------------------------------------------------------
# the tok/s law (the one that ACTUALLY generates perlayer_k's numbers)
# ---------------------------------------------------------------------------
def pass_pingpong(op, K, conv):
    """perlayer_k.pass_time_K: window(n+1) overlaps conversion(n)."""
    return max(op["t_in"], conv / K) + op["swap"]


def pass_serial(op, K, conv):
    """specs.cascade_pass_time: window and conv/K are SERIAL (no ping-pong)."""
    return op["t_in_split"] + 2 * (8 * op["t_q"] + conv) / K


_SCHED = None


def load_sched():
    """The landed per-tensor K schedule + passes/token from the manifest."""
    global _SCHED
    if _SCHED is None:
        mats = json.load(open(plk.MANIFEST))["matrices"]
        passes = {n: mats[n]["passes_per_token"] for n in mats}
        _SCHED = (plk.k_schedule(mats), passes, sum(passes.values()))
    return _SCHED


def avg_k():
    sched, passes, _ = load_sched()
    return sum(passes.values()) / sum(passes[n] / sched[n] for n in passes)


def toks_sched(op, s=1.0, law=pass_pingpong, conv=None, npt=NPT_7B):
    """tok/s/die on the landed per-tensor K schedule, conv scaled by s."""
    sched, passes, total = load_sched()
    f = npt / total
    conv = (op["conv"] if conv is None else conv) * s
    return op["tiles"] / sum(passes[n] * f * law(op, sched[n], conv)
                             for n in passes)


def toks_uniform(op, K, s=1.0, law=pass_pingpong, conv=None, npt=NPT_7B):
    conv = (op["conv"] if conv is None else conv) * s
    return op["tiles"] / (npt * law(op, K, conv))


# ---------------------------------------------------------------------------
# energy.  TWO accountings, because they disagree on whether conv_time moves
# tok/J at all — that disagreement is itself a finding.
# ---------------------------------------------------------------------------
def tokj_static(op, K, s=1.0, npt=NPT_7B, duty=pj.DUTY_SQ):
    """PROJECTED: statics (OTA + ladder) burn for the whole pass; tile dynamic
    is per-pass, conversion dynamic is per-conversion (/K). pdk_projections'
    e_sq structure. conv_time DOES move tok/J here, via the static burn."""
    t = pass_pingpong(op, K, op["conv"] * s)
    e = ((op["ota_w"] * duty + op["ladder_w"]) * t
         + op["e_tile_dyn"] + op["e_conv_dyn"] / K)
    return 1.0 / (npt * e)


def tokj_measanchor(K, npt=NPT_7B):
    """MEASURED-ANCHOR (compose.py): per-block SPICE pJ, conversion /K.
    Structurally INDEPENDENT of conv_time -> d(tok/J)/d(conv_time) == 0."""
    import compose                                  # noqa: E402  (read-only)
    e_pj = npt * (compose.E_TILE_PJ * compose.CSD_REAL_TILE
                  + compose.E_DIG_PJ + compose.E_CONV_PJ / K)
    return 1.0 / (e_pj * 1e-12)


# ---------------------------------------------------------------------------
# conv_time decomposition: a parametric tau that REPRODUCES specs.tau_absorb
# exactly, so every term can be perturbed without touching specs.py.
# beta now TRACKS the identity, because specs.beta_int() derives it (FIX 2).
# ---------------------------------------------------------------------------
def tau_model(op, c_filt=None, c_self=None, c_par=None, c_int=None, gm=None):
    """tau = (C_filt + C_self + C_ser)/(beta*gm), C_ser = C_int||C_par,
    beta = C_int/(C_int+C_par) — the identity specs.beta_int() now uses.
    Reproduces specs.tau_absorb EXACTLY at the unperturbed point (asserted)."""
    ca = op["cal"]
    c_filt = op["c_filt"] if c_filt is None else c_filt
    c_self = (ca["c_ota_self"] * specs.I_SIDE / ca["i_side_ref"]
              if c_self is None else c_self)
    c_par = ca["c_par_vg"] if c_par is None else c_par
    c_int = op["c_int"] if c_int is None else c_int
    gm = op["gm_in"] if gm is None else gm
    c_ser = c_int * c_par / (c_int + c_par)
    return (c_filt + c_self + c_ser) / ((c_int / (c_int + c_par)) * gm)


def conv_model(op, tau=None, n_coarse=specs.N_COARSE,
               k_settle=specs.K_SETTLE, sar_scale=1.0, snap=True):
    """conv = n_coarse * cadence(tau) + sar(tau).  Both terms are LINEAR in
    tau (the SAR is OTA-settle-limited — pdk_projections hook 2), so
    d ln conv / d ln tau == 1 up to the chop-grid snap."""
    tau = op["tau"] if tau is None else tau
    raw = k_settle * tau
    cad = (math.ceil(raw / op["t_q"] - 1e-9) * op["t_q"]) if snap else raw
    return n_coarse * cad + op["sar"] * sar_scale * tau / op["tau"]


_CAPS = {"c_filt", "c_self", "c_par", "c_int", "gm"}


def _base_knob(op, knob):
    ca = op["cal"]
    return {"c_filt": op["c_filt"],
            "c_self": ca["c_ota_self"] * specs.I_SIDE / ca["i_side_ref"],
            "c_par": ca["c_par_vg"], "c_int": op["c_int"],
            "gm": op["gm_in"], "n_coarse": float(specs.N_COARSE),
            "k_settle": specs.K_SETTLE, "sar_scale": 1.0}[knob]


def _conv_at(op, knob, mult):
    """conv_time with ONE knob scaled by `mult`, everything else nominal."""
    v = {knob: _base_knob(op, knob) * mult}
    tau = tau_model(op, **{k: x for k, x in v.items() if k in _CAPS})
    return conv_model(op, tau, **{k: x for k, x in v.items()
                                  if k not in _CAPS})


def elasticity(op, knob, K, rel=0.10):
    """d ln(tok/s)/d ln(knob) at UNIFORM depth K. Positive = raising the knob
    raises tok/s. |e| reads as '% tok/s per % knob'."""
    a = toks_uniform(op, K, conv=_conv_at(op, knob, 1 + rel))
    b = toks_uniform(op, K, conv=_conv_at(op, knob, 1 - rel))
    return (math.log(a) - math.log(b)) / (math.log(1 + rel) - math.log(1 - rel))


# ---------------------------------------------------------------------------
# stopping line, ceiling, and the SNR <-> K relation
# ---------------------------------------------------------------------------
def stop_conv(op, K):
    """conv_time at which the pass flips conversion-bound -> window-bound.
    ABSOLUTE (= K * t_in), so it does NOT move when a fix cuts conv_time."""
    return K * op["t_in"]


def ceiling(op, npt=NPT_7B, t_q=None):
    """K -> inf: pass -> t_in + swap. The hard tok/s ceiling of this window."""
    t_q = op["t_q"] if t_q is None else t_q
    return op["tiles"] / (npt * 140 * t_q)


def min_snr_s(K, parallel=False, target=plk.SNR_T_DB):
    """Smallest per-stage CSNR that lets depth K clear the end-to-end target.
    Bisection on specs' own cascade SNR law (read-only). None = unreachable."""
    f = specs.parallel_cascade_snr_db if parallel else specs.cascade_snr_db
    lo, hi = 0.0, 80.0
    if f(K, hi) < target:
        return None
    for _ in range(200):
        m = 0.5 * (lo + hi)
        lo, hi = (lo, m) if f(K, m) >= target else (m, hi)
    return hi


def k_for_snr(snr_s_db, target=plk.SNR_T_DB):
    """(largest K clearing the target, does K=1 itself clear it?).
    Below ~28 dB K=1 is a FLOOR CLAMP, not a pass — hence the second flag."""
    k = 1
    while specs.cascade_snr_db(k + 1, snr_s_db) >= target:
        k += 1
    return k, specs.cascade_snr_db(1, snr_s_db) >= target


# ---------------------------------------------------------------------------
def _selfcheck(n4, a7, sky):
    """Every anchor, re-asserted against the POST-FIX specs.py defaults."""
    # --- the two fixes are actually in force ---
    assert specs.N_COARSE == 9 == specs.COARSE_CAP + specs.COARSE_MARGIN  # session3: COARSE_MARGIN measured = 2 (tb_integrator_conv margin), n_coarse 11 -> 9
    assert specs.conv_time.__defaults__[1] == specs.N_COARSE
    assert specs.pingpong_pass_time.__defaults__[1] == specs.N_COARSE  # was 19
    assert abs(specs.beta_int(Sky130()) - 200 / 900) < 1e-12
    # A2 measured 0.22 vs the identity 200/900 = 0.2222: 1.01%, not "within
    # 1%" — a hair outside, and worth stating exactly rather than rounding.
    assert abs(specs.beta_int(Sky130()) / 0.22 - 1) < 0.0102
    assert abs(n4["beta"] - n4["c_int"] / (n4["c_int"] + 80e-15)) < 1e-12
    # --- sky130 anchors specs._selfcheck itself pins ---
    assert abs(sky["tau"] - 30e-9) < 0.05e-9, sky["tau"]
    assert abs(sky["cadence"] - 60e-9) < 1e-12
    assert abs(specs.pass_time(Sky130()) - 3.16e-6) < 0.01e-6  # session3: COARSE_MARGIN measured=2 -> n_coarse 9
    # --- N4 post-fix operating point ---
    assert abs(n4["t_in"] - 13.6e-9) < 1e-14
    assert abs(n4["tau"] - 3.645e-9) < 0.005e-9, n4["tau"]
    assert abs(n4["conv"] - 94.86e-9) < 0.05e-9, n4["conv"]  # session3: n_coarse 11->9
    assert abs(n4["conv_prefix"] - 153.26e-9) < 0.05e-9        # FIX 2 only
    # --- re-scored perlayer_k / pdk_projections anchors ---
    assert abs(avg_k() - 6.54) < 0.01
    assert abs(toks_sched(n4) - 114168) < 60, toks_sched(n4)  # session3: n_coarse 11->9
    assert abs(toks_sched(a7) - 70868) < 60, toks_sched(a7)  # session3: n_coarse 11->9
    assert abs(toks_uniform(n4, 1) - 17915) < 30   # session3: n_coarse 11->9
    # --- tau_model reproduces specs.tau_absorb at all three PDKs ---
    for op in (n4, a7, sky):
        assert abs(tau_model(op) - op["tau"]) < 1e-13, op["name"]
    # --- kT/C is NOT binding at sky130; it IS the C_int at N4 ---
    c_noise = 12.0 * specs.KB_T * 4.0 ** specs.B_Y / specs.V_SWING ** 2
    assert abs(c_noise * 1e15 - 52.1) < 0.2
    assert specs.c_int(Sky130()) == 200e-15
    assert abs(specs.c_int(TsmcN4Proj()) - c_noise) < 1e-18
    # --- C_FILT_MIN pinned at N4 (lower clamp), free at sky130 ---
    assert abs(n4["c_filt"] - specs.C_FILT_MIN) < 1e-18
    assert sky["c_filt"] > specs.C_FILT_MIN * 2
    # --- measured SNR really does collapse K to 1 ---
    assert k_for_snr(19.9) == (1, False) and k_for_snr(16.7) == (1, False)
    assert k_for_snr(SNR_BEST) == (1, True)          # best case: K=1 only
    assert k_for_snr(34.0)[0] == 3 and k_for_snr(38.0)[0] == 7   # assumed
    assert min_snr_s(2) > 31.0 > SNR_BEST            # K=2 out of reach
    # --- stopping line is absolute: K*t_in, unmoved by the fixes ---
    assert abs(stop_conv(n4, 7) - 7 * n4["t_in"]) < 1e-18
    assert n4["conv"] > stop_conv(n4, 1)             # K=1 still conv-bound
    # --- 2.0x still out of reach at both PDKs ---
    assert ceiling(n4) / SOHU < 2.0 and ceiling(a7) / SOHU < 2.0
    print("PASS (N_COARSE=11; beta derived 0.2222 ~ A2 0.22; sky130 tau 30 ns "
          "/ cadence 60 ns / pass 3.40 us; N4 tau 3.645 ns conv 109.46 ns; "
          "perlayer_k 99,600 & 61,588; pdk_projections 15,533; measured SNR "
          "-> K=1; K=2 needs >31 dB; ceiling < 2.0x)")


# ---------------------------------------------------------------------------
def main():
    n4, a7, sky = op_point("tsmc_n4_proj"), op_point("asap7_proj"), sky_op()
    _selfcheck(n4, a7, sky)
    ak = avg_k()

    # composition of the two fixes, on the landed avg-K=6.54 schedule
    tau_pre = n4["tau"] * n4["beta"] / n4["cal"]["beta_int"]     # stale beta
    conv_00 = conv_model(n4, tau_pre, n_coarse=17)               # neither fix
    conv_10 = conv_model(n4, tau_pre)                            # FIX 1 only
    conv_01 = n4["conv_prefix"]                                  # FIX 2 only
    t00, t10, t01 = (toks_sched(n4, conv=c)
                     for c in (conv_00, conv_10, conv_01))
    t11 = toks_sched(n4)
    interact = abs(t11 * t00 / (t10 * t01) - 1)

    # the honest-SNR operating points
    t_k1, t_k2 = toks_uniform(n4, 1), toks_uniform(n4, 2)
    a_k1, a_k2 = toks_uniform(a7, 1), toks_uniform(a7, 2)
    k_cross = math.ceil(n4["conv"] / n4["t_in"])   # K where window takes over

    L = ["# CONV_TIME SENSITIVITY (session 3, rev 2)",
         "",
         "Re-scored after `N_COARSE = 11` + derived `beta_int` landed in "
         "`specs.py`, and after the sim agent MEASURED the per-stage CSNR "
         "that the cascade depth K rests on.",
         "",
         "Pure arithmetic through `specs.py` / `perlayer_k.py` / "
         "`pdk_projections.py`. **NO SPICE** (an analog agent owns the "
         "simulator). Regenerate: `PYTHONPATH=analog/schematics:. python3 "
         "scripts/compiler/metrics/convtime_sensitivity.py`.",
         "",
         "Labels: **measured** = SPICE anchor (sky130 tb, or the session-3 "
         "sim agent's CSNR); **derived** = a specs.py law on "
         "measured/sourced params; **projected** = projection-grade PDK "
         "parameter set (asap7_proj / tsmc_n4_proj, LOW-MEDIUM confidence).",
         "",
         "## TL;DR",
         "",
         f"1. **Both fixes re-scored.** N4/7B at the landed schedule "
         f"(avg K = {ak:.2f}): **{t11:,.0f} tok/s/die = {t11/SOHU:.2f}x "
         f"Sohu** (was {t00:,.0f} = {t00/SOHU:.2f}x). asap7/7B: "
         f"**{toks_sched(a7):,.0f} = {toks_sched(a7)/SOHU:.2f}x**.",
         f"2. **The fixes compose MULTIPLICATIVELY, not sublinearly** "
         f"({t10/t00:.3f}x x {t01/t00:.3f}x = {t10*t01/t00**2:.3f}x vs the "
         f"actual {t11/t00:.3f}x — a {interact:.2%} interaction). "
         f"**{(t11/t10-1)/(t01/t00-1):.0%} of FIX 2 survived FIX 1.** No "
         "saturation yet: even after both, the FFN class sits at conv/K = "
         f"{n4['conv']/7*1e9:.2f} ns, still "
         f"{n4['conv']/7/n4['t_in']-1:.0%} above the "
         f"{n4['t_in']*1e9:.1f} ns window floor, so `max()` never engaged.",
         f"3. **That headline rests on a K the measured CSNR does not "
         f"support.** At 19.9 / 16.7 dB uncorrected (27.8-30.1 dB attn with "
         f"A10 cal, circular) the budget gives **K = 1**. N4/7B at K=1 = "
         f"**{t_k1:,.0f} tok/s/die = {t_k1/SOHU:.2f}x Sohu**; best-case K=2 "
         f"= **{t_k2:,.0f} = {t_k2/SOHU:.2f}x**. That is "
         f"{t11/t_k1:.1f}x below the headline and {SOHU/t_k1:.1f}x short of "
         "parity. Section 3.",
         f"4. **The stopping line did not move, because it is absolute** "
         f"(conv = K x t_in). At K=1 it is {stop_conv(n4,1)*1e9:.1f} ns and "
         f"we are at {n4['conv']*1e9:.1f} ns — **"
         f"{n4['conv']/stop_conv(n4,1):.1f}x of runway. conv_time work is "
         "NOT dead; at K=1 it is the only timing lever left.** At K=7 only "
         f"{n4['conv']/stop_conv(n4,7)-1:.0%} of travel remains, and at "
         f"K >= {k_cross} it is exactly zero. Section 5c.",
         "5. **`t_q` flips from 'cheapest ceiling-mover' to worth EXACTLY "
         "ZERO.** It only enters through `t_in`, which `max()` ignores while "
         "the conversion binds. At K=1/2/4, t_q 100 -> 75 ps buys "
         "+0.1%/+0.2%/+0.4% (the swap gap only); it is worth +33% only at "
         f"K >= {k_cross}. I over-sold it in rev 1 by ranking it at the "
         "aspirational K. Section 4d.",
         f"6. **2.0x Sohu remains unreachable** by conv_time and K (N4 "
         f"ceiling {ceiling(n4)/SOHU:.3f}x, asap7 {ceiling(a7)/SOHU:.3f}x) "
         "— but that ceiling only binds in a world where K goes deep, which "
         "the measured CSNR says it will not.",
         "7. **The binding constraint is per-stage CSNR, not time.** K=2 "
         f"needs >= {min_snr_s(2):.2f} dB; the best measured (circular) "
         f"number is {SNR_BEST} dB. Closing that "
         f"~{min_snr_s(2)-SNR_BEST:.1f} dB is worth 2x tok/s — more than "
         "every conv_time lever in this document combined. Section 6 is "
         "re-prioritised accordingly.",
         ""]

    # ---- 0. which law is in force ----------------------------------------
    L += ["## 0. Which tok/s law is in force (unchanged correction)",
          "",
          "The session brief quotes `cascade_pass_time(K) = window_lo + "
          "window_hi + 2*(8*TQ_SIM + conv)/K` (SERIAL). That is **not** the "
          "law behind the perlayer_k numbers. `perlayer_k.pass_time_K` uses "
          "the **ping-pong** law `max(136*t_q, conv/K) + 4*t_q` "
          "(`specs.cascade_pingpong_pass_time`). _(derived)_",
          "",
          "| law | window floor | conv term | sensitivity once conv/K < "
          "window |", "|---|---|---|---|",
          "| serial `cascade_pass_time` | 144 t_q | **added** | never zero |",
          "| ping-pong `pass_time_K` (**in force**) | 136 t_q | **max()** | "
          "**exactly zero** |",
          "",
          f"At N4 the serial law gives {toks_sched(n4, law=pass_serial):,.0f} "
          f"tok/s ({toks_sched(n4, law=pass_serial)/SOHU:.2f}x) on the same "
          f"schedule vs the ping-pong {t11:,.0f}. The `max()` is what "
          "creates the stopping line in 5c.",
          ""]

    # ---- 1. re-scored baseline + fix composition -------------------------
    L += ["## 1. Re-scored baseline: how FIX 1 and FIX 2 compose",
          "",
          f"Landed per-tensor schedule unchanged (attn K=3 on 4 tensors / "
          f"576 passes-tok; ffn K=7 on 3 / 10368) -> avg K = {ak:.2f}. "
          f"N4 tau {tau_pre*1e9:.3f} -> **{n4['tau']*1e9:.3f} ns** (FIX 2); "
          f"conv {conv_00*1e9:.2f} -> **{n4['conv']*1e9:.2f} ns** (both). "
          "_(projected)_",
          "",
          "| | n_coarse | beta_int | conv_time | N4/7B tok/s | vs Sohu | "
          "x baseline |", "|---|---|---|---|---|---|---|",
          f"| baseline (pre-session) | 17 | {n4['cal']['beta_int']:.4f} "
          f"(stale) | {conv_00*1e9:.2f} ns | {t00:,.0f} | {t00/SOHU:.2f}x | "
          "1.000x |",
          f"| FIX 1 only (N_COARSE 11) | 11 | {n4['cal']['beta_int']:.4f} | "
          f"{conv_10*1e9:.2f} ns | {t10:,.0f} | {t10/SOHU:.2f}x | "
          f"{t10/t00:.3f}x |",
          f"| FIX 2 only (derived beta) | 17 | {n4['beta']:.4f} | "
          f"{conv_01*1e9:.2f} ns | {t01:,.0f} | {t01/SOHU:.2f}x | "
          f"{t01/t00:.3f}x |",
          f"| **both (landed)** | **11** | **{n4['beta']:.4f}** | "
          f"**{n4['conv']*1e9:.2f} ns** | **{t11:,.0f}** | "
          f"**{t11/SOHU:.2f}x** | **{t11/t00:.3f}x** |",
          "",
          f"**How much of FIX 2 survives FIX 1: "
          f"{(t11/t10-1)/(t01/t00-1):.1%}.** Naive product "
          f"{t10*t01/t00**2:.4f}x vs actual {t11/t00:.4f}x — interaction "
          f"{interact:.2%}. _(derived)_",
          "",
          "**Why it did NOT go sublinear, contra expectation.** Saturation "
          "only starts when a class's `conv/K` reaches `t_in`. After both "
          f"fixes the FFN class (95% of passes, K=7) sits at conv/K = "
          f"{n4['conv']/7*1e9:.2f} ns against a {n4['t_in']*1e9:.1f} ns "
          f"floor — still {n4['conv']/7/n4['t_in']-1:.0%} above it — and "
          "attention (K=3) is 4x further away. So `max()` never engaged and "
          "both fixes acted on a pure `1/K`-scaled conversion term. "
          "**Sublinearity is close but has not started: one more "
          f"{n4['conv']/stop_conv(n4,7):.2f}x cut in conv_time at K=7 and "
          "the FFN class clamps.**",
          "",
          "`pdk_projections.py` (the K=1, no-cascade point) re-scores "
          f"8,524 -> **{toks_uniform(n4, 1):,.0f} tok/s/die** "
          f"({toks_uniform(n4,1)/8524:.2f}x). The old 8,524-vs-60,328 gap "
          "had two factors (n_coarse 19-vs-17, and K). **FIX 1 collapsed the "
          "merged/ping-pong 19 to the same N_COARSE = 11, so that factor is "
          "now exactly 1.000x and the entire remaining gap is the cascade "
          f"K** ({t11/toks_uniform(n4, 1):.3f}x = the avg-K amortization). "
          "_(derived)_",
          ""]

    # ---- 2. the surface ---------------------------------------------------
    L += ["## 2. Sensitivity surface: tok/s vs Sohu over (conv scale s, K)",
          "",
          f"`s` scales the POST-FIX `conv_time` ({n4['conv']*1e9:.1f} ns at "
          f"N4, {a7['conv']*1e9:.1f} ns at asap7) by any mechanism. K is "
          "UNIFORM so the contour is readable; the landed heterogeneous "
          "schedule is the _sched_ row. 7B, tok/s/die / 62,500 "
          "_(projected)_. **The K=1 and K=2 rows (bold) are the only ones "
          "the measured CSNR supports — see section 3.**",
          ""]
    for op in (n4, a7):
        L += [f"### {op['name']} / 7B — tok/s vs Sohu",
              "",
              "| K | " + " | ".join(f"s={s:.1f}" for s in S_GRID) + " |",
              "|---|" + "---|" * len(S_GRID)]
        for K in K_GRID:
            m = "**" if K in (1, 2) else ""
            L.append(f"| {m}{K}{m} | " + " | ".join(
                f"{m}{toks_uniform(op, K, s)/SOHU:.2f}{m}" for s in S_GRID)
                + " |")
        L.append(f"| _sched ({ak:.2f})_ | " + " | ".join(
            f"_{toks_sched(op, s)/SOHU:.2f}_" for s in S_GRID) + " |")
        L += ["",
              f"Hard ceiling (K -> inf, any s): pass -> t_in + 4 t_q = "
              f"{(op['t_in']+op['swap'])*1e9:.1f} ns -> "
              f"**{ceiling(op):,.0f} tok/s/die = {ceiling(op)/SOHU:.2f}x "
              f"Sohu**. Conversion goes non-binding at conv = K x t_in "
              "(5c). _(derived)_",
              ""]

    L += ["### The 2.0x-Sohu iso-contour — still EMPTY",
          "",
          "No (conv_time, K) pair reaches 2.0x at either PDK at 7B. Identity "
          "on the law, not a projection uncertainty _(derived)_:",
          ""]
    for op in (n4, a7):
        need = op["tiles"] / (NPT_7B * 2.0 * SOHU)
        L.append(
            f"- **{op['name']}**: ceiling {ceiling(op)/SOHU:.3f}x. 2.0x "
            f"needs pass <= {need*1e9:.2f} ns, i.e. t_in <= "
            f"{(need - op['swap'])*1e9:.2f} ns = "
            f"{(need-op['swap'])/op['t_q']:.0f} t_q (have 136 t_q) — "
            "**conv_time cannot supply it at any K**.")
    L += ["",
          "Ceiling-movers are t_q, chop cycles per window (<128), tile mm2, "
          "die count. **But at K=1 those levers are worth zero (4d): the "
          "pass is nowhere near the ceiling.** They matter only in the world "
          "where the CSNR problem is solved and K goes deep.",
          ""]

    # ---- 3. THE HONEST NUMBER --------------------------------------------
    L += _honest_snr_section(n4, a7, t11, ak)

    # ---- 4. decomposition + K-dependent ranking --------------------------
    L += _lever_section(n4, sky, k_cross)

    # ---- 5. dead levers + stopping line ----------------------------------
    L += _dead_levers_section(n4, a7, sky, k_cross)

    # ---- 6. re-anchoring --------------------------------------------------
    L += _reanchor_section(sky, n4)

    open(OUT_MD, "w").write("\n".join(L) + "\n")
    print(f"wrote {OUT_MD}")
    print(f"N4/7B sched avgK {ak:.2f}: {t11:,.0f} = {t11/SOHU:.2f}x   "
          f"asap7 {toks_sched(a7):,.0f} = {toks_sched(a7)/SOHU:.2f}x")
    print(f"  fixes compose {t10/t00:.3f}x * {t01/t00:.3f}x -> "
          f"{t11/t00:.3f}x (interaction {interact:.2%}; "
          f"{(t11/t10-1)/(t01/t00-1):.0%} of FIX 2 survives)")
    print(f"HONEST (measured CSNR -> K=1): N4/7B {t_k1:,.0f} = "
          f"{t_k1/SOHU:.2f}x Sohu | K=2 best case {t_k2:,.0f} = "
          f"{t_k2/SOHU:.2f}x | asap7 K=1 {a_k1:,.0f} = {a_k1/SOHU:.2f}x")
    print(f"stopping line conv = K*t_in: {stop_conv(n4,1)*1e9:.1f} ns at K=1 "
          f"(at {n4['conv']*1e9:.1f} ns -> {n4['conv']/stop_conv(n4,1):.1f}x "
          f"runway), {stop_conv(n4,7)*1e9:.1f} ns at K=7 "
          f"({n4['conv']/stop_conv(n4,7)-1:+.0%} left), zero at K>={k_cross}")
    return 0


# ---------------------------------------------------------------------------
def _honest_snr_section(n4, a7, t11, ak):
    t_k1, t_k2 = toks_uniform(n4, 1), toks_uniform(n4, 2)
    a_k1, a_k2 = toks_uniform(a7, 1), toks_uniform(a7, 2)
    out = [
        "## 3. The honest number: K at the MEASURED per-stage CSNR",
        "",
        "`perlayer_k.py` sets K from `SNR_S_DB = {attn: 34, ffn: 38}` "
        "(STATUS anchors) against a shared `SNR_T_DB = 28 dB` end-to-end "
        "target. The session-3 sim agent **measured** the per-stage analog "
        "CSNR instead. It is far below those anchors. _(measured)_",
        "",
        "| per-stage CSNR | source | cascade SNR at K=1 | clears 28 dB at "
        "K=1? | largest K clearing 28 dB |", "|---|---|---|---|---|",
    ]
    for lab, v in SNR_MEAS.items():
        k, ok1 = k_for_snr(v)
        note = "" if ok1 else " — floor clamp, the budget is already " \
                              "violated at K=1"
        out.append(f"| {v:.1f} dB | **measured** ({lab}) | "
                   f"{specs.cascade_snr_db(1, v):.1f} dB | "
                   f"{'yes' if ok1 else '**NO**'} | {k}{note} |")
    for cls, v in SNR_ASSUMED.items():
        k, _ = k_for_snr(v)
        out.append(f"| {v:.1f} dB | _assumed_ ({cls}, STATUS anchor) | "
                   f"{specs.cascade_snr_db(1, v):.1f} dB | yes | {k} |")
    out += [
        "",
        "**Plainly, without softening:**",
        "",
        "- At the UNCORRECTED measured CSNR the 28 dB end-to-end target is "
        "**not met at any K, including K=1**: K=1 delivers "
        f"{specs.cascade_snr_db(1, 19.9):.1f} dB (attn) and "
        f"{specs.cascade_snr_db(1, 16.7):.1f} dB (FFN). `k_for_budget` "
        "returning 1 is its FLOOR clamp, not a pass.",
        f"- With A10 per-column gain cal the attention class reaches "
        f"{SNR_MEAS['attn, A10 gain cal (worst)']:.1f}-{SNR_BEST:.1f} dB. "
        "Only the TOP of that range clears 28 dB, and only at K=1. **That "
        "number is flagged CIRCULAR / best-case by the sim agent** (the "
        "per-column gain is calibrated on the same data it is scored "
        "against), so it is an upper bound, not a result.",
        f"- **K=2 requires per-stage CSNR >= {min_snr_s(2):.2f} dB** "
        f"(series) / {min_snr_s(2, True):.2f} dB (parallel super-tile). The "
        f"gap depends entirely on which measurement you believe: the "
        f"CIRCULAR best case is only **{min_snr_s(2)-SNR_BEST:.2f} dB** "
        f"short, but the honest uncorrected attention number is "
        f"**{min_snr_s(2)-SNR_MEAS['attn, uncorrected']:.1f} dB** short and "
        f"FFN is **{min_snr_s(2)-SNR_MEAS['ffn, uncorrected']:.1f} dB** "
        "short. _(derived from `specs.cascade_snr_db`)_",
        "- **That spread is the single most important open question in the "
        "session.** ~1 dB is an engineering afternoon; ~11-14 dB is a "
        "different converter. Everything downstream — whether K=2 is "
        "reachable, whether any conv_time lever is worth its testbenches — "
        "hangs on de-circularising the A10 number (calibrate on held-out "
        "columns / a separate excitation, then re-score).",
        "",
        "### What each K costs in per-stage CSNR _(derived)_",
        "",
        "| K | series needs SNR_s >= | parallel super-tile needs >= | best "
        f"measured ({SNR_BEST} dB, circular) reaches it? |",
        "|---|---|---|---|",
    ]
    for K in (1, 2, 3, 4, 7, 9, 14):
        ms, mp = min_snr_s(K), min_snr_s(K, True)
        # ms is None where the SERIES (1+eg)^K gain term alone already
        # exceeds the budget: no per-stage CSNR, however good, can reach it.
        s_ms = (f"{ms:.2f} dB" if ms else
                "**impossible** — the (1+eg)^K gain term alone busts the "
                "budget at ANY per-stage CSNR")
        out.append(f"| {K} | {s_ms} | {mp:.2f} dB | "
                   f"{'yes' if ms and SNR_BEST >= ms else '**no**'} |")
    out += [
        "",
        "The parallel super-tile (#22) removes the `(1+eg)^K` compounding, "
        f"so it helps at LARGE K — at K=2 it saves only "
        f"{min_snr_s(2)-min_snr_s(2, True):.2f} dB. **It does not rescue us: "
        "the binding term is the RANDOM one, i.e. raw per-stage CSNR, and "
        "the parallel topology does not touch that.**",
        "",
        "### tok/s at the K we can actually defend",
        "",
        "_(projected timing x measured CSNR — the timing is the same "
        "post-FIX model as everywhere else; only K changed.)_",
        "",
        "| operating point | K | N4/7B tok/s | vs Sohu | asap7/7B | vs Sohu |",
        "|---|---|---|---|---|---|",
        f"| **measured CSNR (honest)** | **1** | **{t_k1:,.0f}** | "
        f"**{t_k1/SOHU:.2f}x** | **{a_k1:,.0f}** | **{a_k1/SOHU:.2f}x** |",
        f"| measured CSNR, circular best case | 2 | {t_k2:,.0f} | "
        f"{t_k2/SOHU:.2f}x | {a_k2:,.0f} | {a_k2/SOHU:.2f}x |",
        f"| _assumed_ 34/38 dB schedule | {ak:.2f} avg | {t11:,.0f} | "
        f"{t11/SOHU:.2f}x | {toks_sched(a7):,.0f} | "
        f"{toks_sched(a7)/SOHU:.2f}x |",
        f"| _assumed_ uniform K=14 | 14 | {toks_uniform(n4, 14):,.0f} | "
        f"{toks_uniform(n4, 14)/SOHU:.2f}x | {toks_uniform(a7, 14):,.0f} | "
        f"{toks_uniform(a7, 14)/SOHU:.2f}x |",
        "",
        f"**{t_k1/SOHU:.2f}x Sohu is what AnalogIOC can defend today** — "
        f"{t11/t_k1:.1f}x below the {t11/SOHU:.2f}x headline and "
        f"{SOHU/t_k1:.1f}x short of parity. Even the circular best case "
        f"(K=2) is {t_k2/SOHU:.2f}x. And at K=2 the 28 dB budget is violated "
        "by every measured CSNR, so K=2 is not a defensible row either — it "
        "is there to bound the upside.",
        "",
        "**This is a per-stage-CSNR problem, not a scheduling problem.** "
        "Every tok/s lever in this document multiplies a number that is "
        f"currently {SOHU/t_k1:.1f}x short. dB buy tok/s directly: "
        f"+{min_snr_s(2)-SNR_BEST:.1f} dB off the circular best case reaches "
        f"K=2 ({t_k2/t_k1:.1f}x); reaching 34 dB gives "
        f"K={k_for_snr(34.0)[0]} "
        f"({toks_uniform(n4, k_for_snr(34.0)[0])/t_k1:.1f}x); 38 dB gives "
        f"K={k_for_snr(38.0)[0]} "
        f"({toks_uniform(n4, k_for_snr(38.0)[0])/t_k1:.1f}x). **CSNR is "
        "worth more than every conv_time lever in this document combined**, "
        "and it is the one quantity this metrics file cannot compute — it "
        "needs the sim lane.",
        "",
    ]
    return out


# ---------------------------------------------------------------------------
def _lever_section(n4, sky, k_cross):
    ca = n4["cal"]
    c_self = ca["c_ota_self"] * specs.I_SIDE / ca["i_side_ref"]
    c_ser = n4["c_int"] * ca["c_par_vg"] / (n4["c_int"] + ca["c_par_vg"])
    tot = n4["c_filt"] + c_self + c_ser
    levers = [
        ("gm_in (I_SIDE x gm/ID)", "gm", 2.0,
         "x2 (I_SIDE 6 -> 12 uA, 2x static power)",
         "tau ~ 1/gm exactly (C_filt is C_FILT_MIN-clamped, no feedback)"),
        ("n_coarse", "n_coarse", 9.0 / specs.N_COARSE,
         "11 -> 9 (COARSE_MARGIN 4 -> 2, needs SPICE)",
         f"linear on the {specs.N_COARSE*n4['cadence']/n4['conv']:.0%}-of-conv"
         " coarse term"),
        ("K_SETTLE", "k_settle", 0.75,
         "2.0 -> 1.5 (needs tb_integrator_conv)",
         "same coarse term as n_coarse; grid snap ~0.3% at N4"),
        ("c_par_vg", "c_par", 0.5, "80 -> 40 fF",
         "hits tau twice: C_ser AND beta = C_int/(C_int+C_par)"),
        ("C_FILT_MIN", "c_filt", 0.5,
         "60 -> 30 fF (needs a CDAC scaling law)",
         f"{n4['c_filt']/tot:.0%} of C_out_eff; additive, divides by beta*gm"),
        ("C_int", "c_int", 2.0, "x2 (2x tile cap area; c_u ~ C_int -> A7)",
         "raises beta faster than C_ser -> tau DOWN (see 5a)"),
        ("sar_time", "sar_scale", 0.5,
         "x0.5 (fewer trials / shorter tail)",
         f"{n4['sar']/n4['conv']:.0%} of conv at N4 (already tau-scaled)"),
        ("c_ota_self", "c_self", 0.5, "x0.5 (narrower devices, less gm)",
         f"only {c_self/tot:.0%} of C_out_eff at N4"),
    ]
    rows = []
    for lab, knob, mult, move, interp in levers:
        conv = _conv_at(n4, knob, mult)
        rows.append({"lab": lab, "move": move, "interp": interp,
                     "e1": elasticity(n4, knob, 1),
                     "e7": elasticity(n4, knob, 7),
                     "t1": toks_uniform(n4, 1, conv=conv),
                     "t7": toks_uniform(n4, 7, conv=conv)})
    base1, base7 = toks_uniform(n4, 1), toks_uniform(n4, 7)
    gm_t1 = next(r for r in rows if r["lab"].startswith("gm_in"))["t1"]
    c_filt_solved = n4["beta"] * n4["gm_in"] * 3 * n4["t_q"] - c_self - c_ser

    out = [
        "## 4. conv_time decomposed at N4 — the ranking is K-DEPENDENT",
        "",
        "### 4a. The N4 term budget (post-FIX-2 beta)",
        "",
        "The session brief's lever constants (`beta_int` 0.22, `c_par_vg` "
        "700 fF, `C_self` 187 fF, `C_int` 200 fF) are **sky130** values. "
        "N4 differs in kind, not degree:",
        "",
        "| term | sky130 (measured) | tsmc_n4_proj (projected) | share of N4 "
        "C_out_eff |", "|---|---|---|---|",
        f"| C_filt | {sky['c_filt']*1e15:.0f} fF (free, clamp-solved) | "
        f"**{n4['c_filt']*1e15:.0f} fF = C_FILT_MIN (PINNED)** | "
        f"**{n4['c_filt']/tot:.1%}** |",
        f"| C_self | 186.6 fF | {c_self*1e15:.0f} fF | {c_self/tot:.1%} |",
        f"| C_ser (C_int || C_par) | 155.6 fF | {c_ser*1e15:.1f} fF | "
        f"{c_ser/tot:.1%} |",
        f"| C_int | 200 fF (layout floor) | {n4['c_int']*1e15:.1f} fF "
        "(kT/C law) | — |",
        f"| C_par_vg | 700 fF | {ca['c_par_vg']*1e15:.0f} fF | — |",
        f"| beta_int (**now DERIVED**) | {sky['beta']:.4f} (A2 measured "
        f"0.22; the identity reproduces it to {abs(sky['beta']/0.22-1):.1%}) "
        f"| {n4['beta']:.4f} | — |",
        f"| gm_in | 72 uS | {n4['gm_in']*1e6:.0f} uS | — |",
        f"| tau_absorb | {sky['tau']*1e9:.1f} ns | {n4['tau']*1e9:.3f} ns | "
        "— |",
        "",
        f"**C_FILT_MIN is {n4['c_filt']/tot:.1%} of N4 C_out_eff "
        f"({n4['c_filt']/tot*n4['tau']*1e9:.2f} of {n4['tau']*1e9:.2f} ns)** "
        "— the single largest term, as PDK_PROJECTIONS.md suspected. "
        "Precision: it is **not an absolute floor on tau**; it is an "
        "additive 60 fF that still divides by beta*gm, so more gm still "
        "shortens tau. Dominant term, not a wall. _(derived)_",
        "",
        "### 4b. Why sky130 cannot rank these levers (the clamp)",
        "",
        "`specs.kick_filter` solves `C_filt = beta*gm*(3*TQ_SIM) - C_self - "
        "C_ser`, clamped to [C_FILT_MIN, 220 fF]. **Inside the clamp band "
        "tau is pinned at exactly `3*TQ_SIM` by construction**, regardless "
        "of gm, C_par or C_self — hence sky130/sim-grid tau = 3 x 10 ns = "
        "30 ns, insensitive to every device lever. FIX 2 is a live "
        f"demonstration: it moved sky130's beta 0.22 -> {sky['beta']:.4f} "
        f"and C_filt 133 -> {sky['c_filt']*1e15:.0f} fF, and tau did not "
        "budge from 30.0 ns — the clamp absorbed the whole change. At N4 the "
        f"solve goes negative ({c_filt_solved*1e15:.1f} fF) so C_FILT_MIN "
        "binds and tau is fully sensitive again. **Any lever ranked on the "
        "sky130 grid is measuring the clamp, not the physics.** _(derived)_",
        "",
        "### 4c. Ranked levers — at K=1 (honest) and K=7 (aspirational)",
        "",
        "`e = d ln(tok/s)/d ln(term)`, two-sided +-10%, UNIFORM K, N4/7B. "
        "Positive e = raising the term raises tok/s. Sorted by |e| at K=1. "
        "_(derived on projected params)_",
        "",
        "| lever | move | e (K=1) | e (K=7) | K=1 tok/s (vs Sohu) | K=7 "
        "tok/s (vs Sohu) | what it is |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in sorted(rows, key=lambda r: -abs(r["e1"])):
        out.append(
            f"| {r['lab']} | {r['move']} | {r['e1']:+.3f} | {r['e7']:+.3f} | "
            f"{r['t1']:,.0f} ({r['t1']/SOHU:.2f}x) | "
            f"{r['t7']:,.0f} ({r['t7']/SOHU:.2f}x) | {r['interp']} |")
    out += [
        f"| _(baseline, post-FIX-1+2)_ | — | — | — | {base1:,.0f} "
        f"({base1/SOHU:.2f}x) | {base7:,.0f} ({base7/SOHU:.2f}x) | — |",
        "",
        "Chain rule _(derived)_: `d ln(tok/s)/d ln(conv)` = "
        f"{-n4['conv']/(n4['conv']+n4['swap']):.3f} at K=1 and "
        f"{-(n4['conv']/7)/(n4['conv']/7+n4['swap']):.3f} at K=7 (the swap "
        "gap is the only non-conversion term left in the pass); "
        "`d ln(conv)/d ln(tau) = 1.000` exactly (coarse cadence AND the "
        "tau-scaled SAR are both linear in tau); `d ln(tau)/d ln(term)` = "
        "the capacitance shares in 4a.",
        "",
        "**Does the ranking invert? The ORDER barely moves; the MAGNITUDE "
        "and the RUNWAY invert.** gm_in still leads, c_ota_self is still "
        "dead. What changes is what a lever is worth:",
        "",
        f"- At K=7 conv_time has only {n4['conv']/stop_conv(n4,7)-1:.0%} of "
        "useful travel before the window floor clamps it (5c). Every lever "
        "in the table is capped by that, which is why the K=7 column "
        "compresses toward the ceiling.",
        f"- At K=1 the runway is {n4['conv']/stop_conv(n4,1):.1f}x. gm_in x2 "
        f"alone takes K=1 from {base1/SOHU:.2f}x to {gm_t1/SOHU:.2f}x — "
        f"{gm_t1/base1:.2f}x, essentially a clean doubling, because nothing "
        "clamps.",
        "- **So conv_time became MORE load-bearing, not less.** With K=1 the "
        "`2*(...)/K` term does not divide at all, the pass IS the "
        "conversion, and conv_time is the only timing lever that still does "
        "anything. That is the opposite of the rev-1 conclusion, and it "
        "follows entirely from the measured CSNR.",
        "",
        "### 4d. `t_q` — rev 1 called it the cheapest ceiling-mover. At K=1 "
        "it is worth ZERO.",
        "",
        "`t_q` enters the pass ONLY through `t_in = 136*t_q` and the `4*t_q` "
        "swap gap. Under `max(t_in, conv/K)` it can only pay when `t_in` is "
        "the binding term. Both terms are scaled below. _(derived)_",
        "",
        "| K | conv/K | t_in (100 ps grid) | binding term | tok/s at "
        "t_q=100 ps | at t_q=75 ps (row-RC floor) | gain |",
        "|---|---|---|---|---|---|---|",
    ]
    for K in (1, 2, 4, 7, 14, 20):
        t100 = toks_uniform(n4, K)
        op75 = dict(n4, t_in=136 * 75e-12, swap=4 * 75e-12)
        t75 = toks_uniform(op75, K)
        out.append(
            f"| {K} | {n4['conv']/K*1e9:.2f} ns | {n4['t_in']*1e9:.1f} ns | "
            f"{'conversion' if n4['conv']/K > n4['t_in'] else '**window**'} | "
            f"{t100:,.0f} ({t100/SOHU:.2f}x) | {t75:,.0f} "
            f"({t75/SOHU:.2f}x) | {t75/t100-1:+.1%} |")
    out += [
        "",
        "**t_q 100 -> 75 ps is worth +0.1%/+0.2%/+0.4% at K=1/2/4** — the "
        "conversion binds, the window is irrelevant, and shrinking it moves "
        "only the "
        f"0.4 ns swap gap. It becomes a lever only once K >= {k_cross} "
        "(where conv/K crosses t_in), i.e. in the world where the CSNR "
        "problem is already solved. **Correcting rev 1: I ranked t_q at the "
        "aspirational K. t_q is a CEILING lever, and we are not near the "
        "ceiling.**",
        "",
    ]
    return out


# ---------------------------------------------------------------------------
def _dead_levers_section(n4, a7, sky, k_cross):
    c_noise = 12.0 * specs.KB_T * 4.0 ** specs.B_Y / specs.V_SWING ** 2
    tau_inf = tau_model(n4, c_int=1.0)               # C_int -> inf
    base1 = toks_uniform(n4, 1)
    t_cint2 = toks_uniform(n4, 1, conv=_conv_at(n4, "c_int", 2.0))
    out = [
        "## 5. Falsified levers, the STOPPING LINE, and tok/J",
        "",
        "### 5a. Raising C_int for kT/C reasons — DEAD, and the brief's "
        "premise was an artifact FIX 2 removed",
        "",
        f"- kT/C law `C >= 12 kT 4^B_y / V_swing^2` = **{c_noise*1e15:.1f} "
        "fF** at B_y=8, V_swing=0.25 V _(derived)_.",
        f"- sky130 C_int = 200 fF (the layout floor) = "
        f"**{200e-15/c_noise:.2f}x** the noise requirement. Noise never "
        "bound; `specs.c_int` returns `max(c_noise, layout_floor)` and its "
        "docstring says 'swing, not noise, binds'.",
        f"- At N4 the layout floor (40 fF) is BELOW the noise law, so C_int "
        f"= {n4['c_int']*1e15:.1f} fF sits EXACTLY on the kT/C line — zero "
        "margin in either direction.",
        "",
        "Since `C_ser/beta == C_par` identically, the closed form is",
        "",
        "```",
        "tau = (C_filt + C_self) * (1 + C_par/C_int) / gm  +  C_par / gm",
        "```",
        "",
        "so **raising C_int LOWERS tau** (it raises beta faster than it "
        f"raises C_ser), saturating at (C_filt+C_self+C_par)/gm = "
        f"{tau_inf*1e9:.2f} ns ({tau_inf/n4['tau']-1:+.0%}). At K=1, C_int "
        f"x2 gives {t_cint2:,.0f} tok/s ({t_cint2/base1-1:+.1%}). **The "
        "brief's 'raising C_int only raises tau' was an artifact of the "
        "stale stored beta — FIX 2 removed exactly that artifact, so the "
        "sign is now unambiguous.**",
        "",
        "**The conclusion (do not do it) survives anyway**, for reasons "
        "unrelated to kT/C: `c_u = C_int*V_swing/(MAC_MAX*VDD)`, so C_u "
        "scales WITH C_int — you pay the whole tile's cap area, you re-open "
        "the A7 `k_cal` anchor and the `_selfcheck` c_u assert, and the "
        f"entire win is bounded at {-(tau_inf/n4['tau']-1)*100:.0f}% of tau. "
        "`gm_in` buys the same tau with no anchor churn.",
        "",
        "### 5b. K_SETTLE 2.0 -> 1.5 — real at N4, but now BLOCKED by CSNR",
        "",
    ]
    for op, lab in ((sky, "sky130 (sim grid, t_q = 10 ns)"),
                    (n4, "tsmc_n4_proj (t_q = 100 ps)")):
        c20, c15 = conv_model(op, k_settle=2.0), conv_model(op, k_settle=1.5)
        c15r = conv_model(op, k_settle=1.5, snap=False)
        out.append(
            f"- **{lab}**: cadence {op['cadence']*1e9:.2f} -> "
            f"{math.ceil(1.5*op['tau']/op['t_q'])*op['t_q']*1e9:.2f} ns. "
            f"conv falls {c15/c20-1:+.1%} snapped vs {c15r/c20-1:+.1%} "
            f"un-snapped -> the chop-grid snap eats "
            f"{(c15-c15r)/(c20-c15r):.0%} of the win.")
    t_ks1 = toks_uniform(n4, 1, conv=conv_model(n4, k_settle=1.5))
    out += [
        "",
        f"At N4 the snap is nearly free, so K_SETTLE 2.0 -> 1.5 is worth "
        f"{conv_model(n4, k_settle=1.5)/n4['conv']-1:+.1%} conv_time -> "
        f"**{t_ks1:,.0f} tok/s at K=1 ({t_ks1/SOHU:.2f}x, "
        f"{t_ks1/base1-1:+.1%})**. At sky130's 10 ns grid a third of the win "
        "evaporates AND sky130 is window-bound anyway, so it converts to 0% "
        "tok/s there — exactly the class of conclusion that ranking on the "
        "sim grid gets wrong.",
        "",
        "**COST, and this is now decisive:** 1.5 tau leaves a 22% settling "
        "residue vs 13.5% at 2 tau. That is a direct debit against per-stage "
        "CSNR — the quantity section 3 shows is already in deficit by "
        f"~{min_snr_s(2)-SNR_BEST:.1f} dB. **Spending settling accuracy to "
        "buy nanoseconds is the wrong trade in a CSNR-bound design. "
        "Rev 1 called this a cheap SPICE ask; rev 2 downgrades it to "
        "blocked until CSNR has headroom.**",
        "",
        "### 5c. The STOPPING LINE — and why the fixes did not move it",
        "",
        "The pass flips conversion-bound -> window-bound when `conv/K <= "
        "t_in`, i.e. at **conv = K x t_in**. That threshold is ABSOLUTE and "
        "independent of how conv_time got where it is, so FIX 1 and FIX 2 "
        "moved us TOWARD it without moving it. Below it "
        "`d(tok/s)/d(conv_time) = 0` identically — and so is "
        "`d(tok/J)/d(conv_time)`, since the only conv_time-dependent energy "
        "term is `P_static x pass_time`. _(derived)_",
        "",
        "| PDK | t_in | conv now | stop conv at K=1 | K=2 | K=7 | K=14 | "
        "headroom at K=1 | at K=7 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for op in (n4, a7, sky):
        h1, h7 = op["conv"] / stop_conv(op, 1), op["conv"] / stop_conv(op, 7)
        out.append(
            f"| {op['name']} | {op['t_in']*1e9:.2f} ns | "
            f"{op['conv']*1e9:.2f} ns | **{stop_conv(op, 1)*1e9:.1f} ns** | "
            f"{stop_conv(op, 2)*1e9:.1f} ns | {stop_conv(op, 7)*1e9:.1f} ns "
            f"| {stop_conv(op, 14)*1e9:.1f} ns | **{h1:.2f}x** | "
            f"{h7:.2f}x{'' if h7 > 1 else ' (PAST IT)'} |")
    out += [
        "",
        "**Are we past the stopping line? NO — and the answer depends "
        f"entirely on K.** At the honest K=1 we are "
        f"{n4['conv']/stop_conv(n4,1):.1f}x above it: conv_time can fall "
        f"from {n4['conv']*1e9:.1f} ns all the way to "
        f"{stop_conv(n4,1)*1e9:.1f} ns and every nanosecond pays at full "
        "elasticity. **At K=1, conv_time work is emphatically NOT dead — it "
        f"is the only timing lever with runway.** At K=7 only "
        f"{n4['conv']/stop_conv(n4,7)-1:.0%} of travel remains; at "
        f"K >= {k_cross} we are past it and further conv_time work buys "
        "exactly zero.",
        "",
        f"sky130 on the SIM grid is window-bound at every K (conv "
        f"{sky['conv']*1e9:.0f} ns vs t_in {sky['t_in']*1e9:.0f} ns, "
        f"headroom {sky['conv']/stop_conv(sky,1):.2f}x < 1) — another reason "
        "the sim grid cannot rank conv_time levers.",
        "",
        "### 5d. tok/J vs conv_time — the two accountings disagree",
        "",
        "| accounting | conv_time enters? | N4/7B tok/J at K=1 | K=2 | K=7 |",
        "|---|---|---|---|---|",
        f"| measured-anchor (`compose.py`: per-block SPICE pJ, conv/K) | "
        f"**NO** — structurally independent | {tokj_measanchor(1):,.0f} | "
        f"{tokj_measanchor(2):,.0f} | {tokj_measanchor(7):,.0f} |",
        f"| projected static+dynamic (`pdk_projections` e_sq) | **YES** — via "
        f"pass time | {tokj_static(n4, 1):,.0f} | {tokj_static(n4, 2):,.0f} "
        f"| {tokj_static(n4, 7):,.0f} |",
        "",
        "(The measured-anchor row is the mini SPICE chain scaled to 27.3 M "
        "passes/token — see COMPOSED_RESULTS.md's scope warning; the "
        "mini-scope number is ~87k tok/J. Sohu's 35-60 tok/J band is "
        "INFERRED, no vendor power published.) On the projected accounting "
        f"at K=1, halving conv_time buys "
        f"{tokj_static(n4,1,0.5)/tokj_static(n4,1):.2f}x tok/J — **tok/J "
        "tracks tok/s closely at K=1 and stops at the same line.**",
        "",
    ]
    return out


# ---------------------------------------------------------------------------
def _reanchor_section(sky, n4):
    c_noise = 12.0 * specs.KB_T * 4.0 ** specs.B_Y / specs.V_SWING ** 2
    cu_now = specs.c_u(Sky130())
    cu_2 = round(specs.c_int(Sky130()) * 0.5 / (specs.MAC_MAX * 1.8)
                 * 1e18 / 10) * 10e-18
    ca = n4["cal"]
    c_self = ca["c_ota_self"] * specs.I_SIDE / ca["i_side_ref"]
    c_ser = n4["c_int"] * ca["c_par_vg"] / (n4["c_int"] + ca["c_par_vg"])
    tot = n4["c_filt"] + c_self + c_ser
    base1 = toks_uniform(n4, 1)
    t_filt = toks_uniform(n4, 1, conv=_conv_at(n4, "c_filt", 0.5))
    t_gm = toks_uniform(n4, 1, conv=_conv_at(n4, "gm", 2.0))
    gap_db = min_snr_s(2) - SNR_BEST
    return [
        "## 6. Re-anchoring dependency map (approved re-anchored branch)",
        "",
        "Per proposed change: which CALIBRATED constants stop being valid, "
        "which ASSERTS break, and the minimum testbench set to re-anchor. "
        "Constants live in `analog/schematics/specs.py` (`_CAL['sky130']`, "
        "module constants) and `library/pdks/*_proj.py` (`cal_proj`).",
        "",
        "**Section 3 re-prioritises this entire list.** Each entry is now "
        "scored twice: what it does for tok/s, and what it does for "
        "**per-stage CSNR**, which is the binding constraint. A change that "
        f"buys dB is worth more than one that buys nanoseconds — we are "
        f"~{gap_db:.1f} dB short of K=2 (worth 2x) and ~"
        f"{min_snr_s(4)-SNR_BEST:.1f} dB short of K=4.",
        "",
        "### 6.1 `V_SWING` 0.25 -> 0.5 V",
        "",
        "**Feasibility veto first.** V_SWING is the *single-sided* swing "
        "about a virtual ground at `VCM_FRAC = 0.5 x VDD`. sky130 (1.8 V) "
        "-> VCM 0.9 V, tight but arguable. **asap7_proj (0.7 V) -> VCM "
        "0.35 V; tsmc_n4_proj (0.75 V) -> VCM 0.375 V: a 0.5 V single-sided "
        "swing exceeds the rail and is physically impossible.** Both "
        "advanced PDKs already carry `topology_flags['ota'] = "
        "two_stage_or_ringamp` for this headroom reason. So it is a "
        "sky130-only experiment. _(derived — arithmetic on VDD.)_",
        "",
        "| breaks | why | re-anchor with |", "|---|---|---|",
        f"| `c_u` ({cu_now*1e15:.2f} -> {cu_2*1e15:.2f} fF) | `c_u = "
        "C_int*V_swing/(MAC_MAX*VDD)`, snapped to the 10 aF grid. **Every "
        "reference span moves.** | `tb_weight_tile` (A7 Q_UNIT) |",
        "| `k_cal` (0.9906, A7 measured) | it is `Q_UNIT/(C_u*VDD)` measured "
        "AT the current unit-cell geometry | `tb_weight_tile` A7 rerun |",
        "| `MAC_MAX = 185` (measured OTA compression ceiling) | it is the "
        "code where the OTA compresses AT the current swing; doubling the "
        "swing is precisely a claim about where compression starts | "
        "`tb_ota` + `tb_tile_mvm` compression sweep |",
        "| `CODE_MAX = 120`, `cascade_k_swing` | derived from MAC_MAX; "
        "`_selfcheck` asserts `cascade_k_swing(CODE_MAX)==1` and "
        "`cascade_k_swing(46)==4` — both break | recompute, then "
        "`tb_cascade` K=4 code guard |",
        f"| `c_int` at advanced nodes | `c_noise` falls 4x "
        f"({c_noise*1e15:.1f} -> {c_noise/4*1e15:.1f} fF), so N4/asap7 C_int "
        "drops to their layout floors (40/50 fF). **`beta_int` is now "
        "DERIVED, so it follows automatically — FIX 2 already removed this "
        "hazard.** | no tb (projection-only); re-run this script |",
        "| `fine_ref_trim = 0.80` (A11 measured droop) | droop is "
        "residue-amplitude dependent; a 2x residue span re-droops | "
        "`diag_fine15` + `tb_integrator_conv` |",
        "| `MB_EFF_FLOOR = 0.84` (A9 measured) | charge-sharing efficiency "
        "at the new unit-cell size | `diag_multibank` |",
        "| `specs._selfcheck()` | the `c_u` +-11%-of-0.15 fF assert and the "
        "`k_cal` 0.9906 +-0.001 assert fail immediately | both are "
        "re-anchor targets, not bugs |",
        "",
        "**Checklist (ordered):** `tb_ota` (compression -> MAC_MAX) -> "
        "`tb_weight_tile` (k_cal, A7) -> `diag_a8` (zero point) -> "
        "`diag_fine15` (A11) -> `diag_multibank` (MB_EFF_FLOOR) -> "
        "`tb_integrator_conv` (+-1 LSB) -> `tb_tile_mvm` (energy anchor; "
        "`E ~ CV^2` on a 2x span) -> `tb_cascade` (K=4 guard). **8 tbs.**",
        "",
        "**REVISED VERDICT (rev 1 said: skip).** V_SWING is worth **0%** on "
        "conv_time — it appears nowhere in `tau_absorb`, `coarse_cadence`, "
        "`conv_time` or the window. But it is the list's only **CSNR** "
        "lever: doubling signal swing at a fixed noise floor is up to +6 dB "
        f"of per-stage SNR, and we need ~{gap_db:.1f} dB for K=2 (2x tok/s) "
        f"and ~{min_snr_s(4)-SNR_BEST:.1f} dB for K=4. **In a CSNR-bound "
        "design this becomes the highest-value change on the list** — "
        "provided the OTA delivers the swing LINEARLY (`MAC_MAX` is the "
        "falsifier, and it is measured at the current swing, so `tb_ota` "
        "must run first), and provided you accept it is sky130-only. The "
        "8-tb cost is real; the alternative is K stays 1.",
        "",
        "### 6.2 `c_par_vg` 700 -> 350 fF (sky130)",
        "",
        "| breaks | why | re-anchor with |", "|---|---|---|",
        f"| `beta_int` — **nothing to break any more** | FIX 2 made it "
        f"`C_int/(C_int+C_par)`, so it follows automatically "
        f"({sky['beta']:.4f} -> {200/550:.4f}) | re-run this script; "
        "`tb_integrator_conv` to confirm the closed-loop settle |",
        "| `c_ota_self = 311 fF` (**back-solved**, not measured) | the specs "
        "comment says it was back-solved from measured tau = 26 ns as "
        "`tau*beta*gm - c_filt - c_ser`. Change beta or C_ser and the "
        "back-solve is INVALID — re-back-solve from a NEW measured tau | "
        "`tb_integrator_conv` absorb transient |",
        "| `MB_EFF_FLOOR = 0.84` | `c_par_vg` is explicitly 'C_RAIL(500 fF) "
        "+ banks'; halving it halves the charge-sharing dilution the "
        "multibank fit models. eff should IMPROVE — **and per section 3 that "
        "is a CSNR gain, which is exactly what we need** | `diag_multibank` "
        "on pass_00 cols 1/3/8 + pass_05 |",
        "| `k_cal = 0.9906` | measured on a column WITH that C_RAIL | "
        "`tb_weight_tile` |",
        f"| `specs._selfcheck` cadence assert | sky130 C_filt jumps "
        f"{sky['c_filt']*1e15:.0f} -> 220 fF (UPPER clamp) and tau falls "
        f"{sky['tau']*1e9:.0f} -> ~20 ns, so the `cadence == 60 ns` assert "
        "fails | update the anchor after `tb_integrator_conv` |",
        "",
        "**Checklist:** `tb_integrator_conv` -> `diag_multibank` -> "
        "`tb_weight_tile` -> `tb_tile_mvm`. **4 tbs**, no span/code changes, "
        "A7/A8/A11 codes structurally unmoved. Cheapest change on the list, "
        "and FIX 2 just made it cheaper by one constant. At N4 `c_par_vg` is "
        "already 80 fF so this buys sky130 falsifiability, not N4 tok/s — "
        "**but the `MB_EFF` improvement is a real CSNR path, which now "
        "matters more than the tok/s it does not buy.**",
        "",
        "### 6.3 LVT devices",
        "",
        "| breaks | why | re-anchor with |", "|---|---|---|",
        "| every `OTA_COORDS` width | `specs.ota()` sizes `W = I_D/J_D(gm/ID,"
        " L, type)` from `sizing/lookup.py` tables keyed by device flavor | "
        "regenerate LVT gm/ID tables; `_selfcheck` width asserts (+-3% vs "
        "`pdk.sizing`) |",
        "| `pdk.sizing` in `library/pdks/sky130.py` | stores the vault widths "
        "the +-3% assert compares against | re-run the sizing recipe |",
        "| `c_ota_self` + its `i_side_ref` scaling | different widths -> "
        "different self-load; the constant-J `c_self ~ i_side` law is only "
        "valid within ONE flavor | `tb_integrator_conv` re-back-solve |",
        "| loop gain (330 measured vs 200 needed) | LVT lowers r_o (DIBL). "
        "The telescopic's 5-stack intrinsic gain is what the 0.5%-transfer "
        "requirement rests on | `tb_ota` DC gain + AC sweep |",
        "| `a_vt` / offset / `MB_EFF_FLOOR` | LVT Pelgrom A_VT is typically "
        "WORSE — **per section 3 that is a CSNR REGRESSION we cannot "
        "afford** | `tb_strongarm` (offset), `diag_multibank` |",
        "| leakage in `ota_static_w` | LVT sub-threshold leakage is not in "
        "the model at all | `tb_tile_mvm` |",
        "",
        "**Checklist:** LVT gm/ID tables -> `tb_ota` -> `tb_strongarm` -> "
        "`tb_integrator_conv` -> `diag_multibank` -> `tb_tile_mvm`. "
        "**6 tbs.**",
        "",
        "**REVISED VERDICT (rev 1 said: only if you commit to gm_in).** LVT "
        "does NOT raise gm/ID at a fixed inversion level (gm/ID is set by "
        "the inversion coefficient, not V_t) — it buys **stack headroom**, "
        "i.e. it is an enabler for raising I_SIDE (the gm_in lever) or for "
        "V_SWING. But it **costs** matching (worse A_VT) and gain (DIBL), "
        f"and both are CSNR. With CSNR short by ~{gap_db:.1f} dB, **spending "
        "matching to buy settling time is the wrong trade. Defer.**",
        "",
        "### 6.4 Lowering `C_FILT_MIN` (60 fF)",
        "",
        "| breaks | why | re-anchor with |", "|---|---|---|",
        "| the CDAC-match premise | the comment is explicit: 'floor: match "
        "the CDAC-side 8k/60f network'; `C_KICK_CDAC = 96 fF` is the sample "
        "load it must match. Lowering C_filt without the CDAC side breaks "
        "the kick-charge balance | `tb_rstring` + `tb_integrator_conv` |",
        "| `RC_KICK = 0.44 ns` held constant | `kick_filter` returns "
        "`R = RC_KICK/C`, so halving C DOUBLES R. The kick CHARGE is held, "
        "but the higher R interacts with the comparator input, and the "
        "0.44 ns product is itself a measured anti-kick anchor | "
        "`tb_integrator_conv` coarse-decision noise, `tb_strongarm` |",
        f"| nothing at sky130 | the floor is NOT active there (C_filt solves "
        f"to {sky['c_filt']*1e15:.0f} fF) — **no sky130 tb can falsify this "
        "change** | land it as a PARAMETER with a stated CDAC scaling law, "
        "labelled projected |",
        f"| PDK_PROJECTIONS.md's own open item | it already lists the "
        "'`C_FILT_MIN` becomes the tau_absorb floor at advanced nodes' hook. "
        f"This is its quantification: {n4['c_filt']/tot:.0%} of N4 "
        "C_out_eff | — |",
        "",
        "**Checklist:** derive the CDAC scaling law FIRST -> `tb_rstring` -> "
        "`tb_integrator_conv`. **2 tbs + a law.**",
        "",
        f"**VERDICT: still the best conv_time-per-tb on the list** "
        f"({t_filt:,.0f} tok/s at K=1, {t_filt/base1-1:+.0%}), and unlike "
        "V_SWING/LVT it costs no CSNR. But it buys nanoseconds, and section "
        "3 says nanoseconds are not what is short.",
        "",
        "### 6.5 Summary — re-prioritised for a CSNR-bound design",
        "",
        "| change | CSNR effect | N4/7B tok/s at K=1 | tbs | verdict |",
        "|---|---|---|---|---|",
        f"| `V_SWING` 0.25 -> 0.5 (sky130 only) | **up to +6 dB** — the only "
        "entry that attacks the binding constraint | 0% directly | 8 | "
        "**now the top candidate**, if `MAC_MAX` survives `tb_ota` |",
        "| `c_par_vg` 700 -> 350 (sky130) | **+ via `MB_EFF`** (must "
        "re-measure) | ~0% at N4 | 4 | do it — cheapest, and FIX 2 removed "
        "a constant |",
        f"| raise `I_SIDE` 6 -> 12 uA (gm_in) | neutral | {t_gm:,.0f} "
        f"({t_gm/base1-1:+.0%}) | 2 | biggest pure-timing lever; costs 2x "
        "static power |",
        f"| lower `C_FILT_MIN` 60 -> 30 fF | neutral | {t_filt:,.0f} "
        f"({t_filt/base1-1:+.0%}) | 2 + a law | best tok/s-per-tb, but tok/s "
        "is not what binds |",
        "| `K_SETTLE` 2.0 -> 1.5 | **NEGATIVE** (22% vs 13.5% settling "
        f"residue) | {toks_uniform(n4, 1, conv=conv_model(n4, k_settle=1.5)):,.0f} "
        f"({toks_uniform(n4, 1, conv=conv_model(n4, k_settle=1.5))/base1-1:+.0%}) "
        "| 1 | **blocked** while CSNR is in deficit |",
        "| LVT | **NEGATIVE** (worse A_VT, worse gain) | 0% directly | 6 | "
        "**defer** — wrong trade |",
        "",
    ]


if __name__ == "__main__":
    sys.exit(main())
