"""Level-1 cross-bank combine tree: group node = logsumexp of logsumexps, group weights,
group (m, l, o) vs golden.group_combine inside the CHIP2_SPEC T5 budget.

Spec rows (analog/softmax_combine/docs/architecture.md):
  group node carries ln l_group: one (slope, const) line fits the golden logsumexp of
    4 bank-V_ls pairs with worst residual < RESID_MAX nat        (AnalogIOC 0.02 nat)
  B5 rescale pair (rescale, gated by the two shifted bank V_ls) ratio == group-stage
    weight ratio within XCHK_TOL                                  (AnalogIOC 2 %)
  flat group: l and o within T5_BUDGET of golden, m error in [M_ERR_LO, M_ERR_HI] mV
  golden associativity (flat == pairwise) and analog o/l within T5_BUDGET

Flow (AnalogIOC tb_combine_tree.py, ngspice batch -> SpiceRack):
  1. two level-0 banks (translinear_softmax, stimulus) of 8 scores: settled V_ls
     (shared-source node), softmax branch currents, branch beta self-fit;
  2. the DUT (softmax_combine) driven by the level-shifted bank V_ls: group node and
     group weights g_b = igrp_b / sum igrp;
  3. group (m, l, o) rebuilt from the bank partials and g_b (kappa-calibrated to the
     V_ls log scale), compared with golden.group_combine.
Bias is current-referenced (as rescale / the system: one vb_tail for every stage):
vb_tail is servoed on the DUT so sum igrp = I_B at equal gates, and the same vb_tail
drives the banks and the B5 pair. Loads hold every output at VCM_FRAC * VDD.
The level shift (AnalogIOC 0.47 V typed) is derived: the score CM minus the mean bank V_ls,
a common offset on both gates that cancels in every ratio.
"""
import math
import os
import sys
from pathlib import Path

import numpy as np

A = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(A / "docs"), str(A / "common"), str(A / "softmax_combine" / "netlist"),
                str(A / "rescale" / "netlist"), str(A / "translinear_softmax" / "netlist"),
                str(A.parent / "scripts")]
from bench import Report, testbench  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402
import specs  # noqa: E402
import rescale  # noqa: E402
from softmax_combine import PORTS  # noqa: E402
import golden.model as G  # noqa: E402

import spicerack as ps  # noqa: E402

VDD = get_pdk().vdd
VOUT = specs.VCM_FRAC * VDD          # column-side load potential (A6), AnalogIOC 0.9 V
I_B = specs.I_B
SCORE_BOTTOM, SCORE_TOP = rescale.score_window()
SCORE_CM = (SCORE_BOTTOM + SCORE_TOP) / 2        # AnalogIOC 0.75 V
T_WIN = 3e-6                         # evaluation window (AnalogIOC)
N_BANK = 8

RESID_MAX = 0.02                     # nat
XCHK_TOL = 0.02
T5_BUDGET = 0.025                    # CHIP2_SPEC T5: 1.4 % * sqrt(2) + margin
M_ERR_LO, M_ERR_HI = -5.0, 80.0      # mV

# AnalogIOC's two banks (0.6-0.85 V window, CM 0.75), re-centred on this PDK's score CM.
# Bank 1 has the higher max, so both rescales are exercised.
_AnalogIOC_CM = 0.75
BANKS = [SCORE_CM + np.array(b) - _AnalogIOC_CM for b in (
    [0.77, 0.74, 0.76, 0.73, 0.75, 0.72, 0.74, 0.73],
    [0.76, 0.80, 0.74, 0.75, 0.73, 0.74, 0.72, 0.75])]
VALS = [   # per-bank token values (d_v = 3) for the o partials
    np.array([[1.0, -0.5, 0.2], [0.3, 0.8, -0.1], [-0.4, 0.6, 0.9],
              [0.7, -0.2, 0.5], [0.1, 0.4, -0.6], [-0.3, 0.2, 0.8],
              [0.5, -0.7, 0.1], [0.2, 0.3, -0.4]]),
    np.array([[-0.2, 0.9, 0.3], [0.6, -0.4, 0.7], [0.1, 0.5, -0.8],
              [-0.5, 0.2, 0.4], [0.8, -0.1, 0.6], [0.3, 0.7, -0.2],
              [-0.6, 0.4, 0.1], [0.2, -0.3, 0.5]]),
]


def supplies(tb, vbt):
    tb.options(reltol=1e-4, abstol=1e-12, vntol=1e-6, method="gear")
    tb.V(name="sup", positive="vdd", negative="0", value=VDD)
    tb.V(name="ss", positive="vss", negative="0", value=0.0)
    tb.V(name="bt", positive="vb_tail", negative="0", value=vbt)


def stimulus(sub, name, ports, inst):
    """Testbench around a sibling block's build() (always its schematic), nets = ports."""
    top = ps.Subcircuit(f"tb_{inst}")
    top.X(inst, name, *ports)
    tb = ps.Testbench(top)
    tb.add_subcircuit(sub)
    tb.use_pdk(get_pdk().model_library(os.environ.get("CORNER", "")))
    tb.temperature = float(os.environ.get("TEMP", 27))
    return tb


def group_bench(vbt, gates):
    tb = testbench("softmax_combine", PORTS)
    supplies(tb, vbt)
    for b, v in enumerate(gates):
        if v is not None:
            tb.V(name=f"ls{b}", positive=f"vls{b}", negative="0", value=v)
        tb.V(name=f"ig{b}", positive=f"igrp{b}", negative="0", value=VOUT)
    return tb


def bias():
    """vb_tail where sum igrp = I_B with both gates at the score CM (log-interpolated)."""
    v0 = rescale.vb_tail()
    r = group_bench(v0, [SCORE_CM, SCORE_CM]).dc(Vbt=slice(v0 - 0.25, v0 + 0.25, 0.005))
    vs, i = list(r.sweep), [a + b for a, b in zip(r["i(vig0)"], r["i(vig1)"])]
    for k in range(1, len(vs)):
        if i[k - 1] < I_B <= i[k]:
            f = math.log(I_B / i[k - 1]) / math.log(i[k] / i[k - 1])
            return vs[k - 1] + f * (vs[k] - vs[k - 1])
    raise RuntimeError(f"I_B not reached over vb_tail sweep ({i[0]:.2e}..{i[-1]:.2e} A)")


def settled(tb, *probes):
    tb.save(*probes)
    return tb.transient(step_time=5e-9, end_time=T_WIN)


def energy(r):
    return VDD * float(np.trapezoid([abs(x) for x in r["i(vsup)"]], r.time))


def bank_run(pat, vbt):
    """Level-0 bank (translinear_softmax schematic): settled V_ls, branch currents,
    branch-beta self-fit (ln iout vs score), energy over T_WIN."""
    from translinear_softmax import PORTS as SM_PORTS, build as sm_build
    tb = stimulus(sm_build(), "translinear_softmax", SM_PORTS, "sm")
    supplies(tb, vbt)
    for i in range(N_BANK):
        tb.V(name=f"in{i}", positive=f"vin{i}", negative="0", value=float(pat[i]))
        tb.V(name=f"o{i}", positive=f"iout{i}", negative="0", value=VOUT)
    node = "xsm.s"                  # the bank's shared-source node (AnalogIOC name "s")
    r = settled(tb, f"V({node})", "I(vsup)", *(f"I(vo{i})" for i in range(N_BANK)))
    im = np.array([abs(r[f"i(vo{i})"][-1]) for i in range(N_BANK)])
    beta = np.linalg.lstsq(np.vstack([pat, np.ones(N_BANK)]).T, np.log(im), rcond=None)[0][0]
    return {"vls": r[node][-1], "iout": im, "beta": beta, "energy": energy(r), "pat": pat}


def group_run(gates, vbt):
    """DUT: (group node V, group weights g_b = igrp_b / sum, energy over T_WIN)."""
    r = settled(group_bench(vbt, gates), "V(vls_group)", "I(vsup)", "I(vig0)", "I(vig1)")
    igrp = np.array([abs(r[f"i(vig{b})"][-1]) for b in range(len(gates))])
    return r["vls_group"][-1], igrp / igrp.sum(), energy(r)


def rescale_g(vhi, vlo, vbt):
    """B5 pair (rescale schematic): g = ilo / ihi for gates (vhi, vlo)."""
    tb = stimulus(rescale.build(), "rescale", rescale.PORTS, "rs")
    supplies(tb, vbt)
    tb.V(name="hi", positive="vhi", negative="0", value=vhi)
    tb.V(name="lo", positive="vlo", negative="0", value=vlo)
    tb.V(name="ih", positive="ihi", negative="0", value=VOUT)
    tb.V(name="il", positive="ilo", negative="0", value=VOUT)
    r = settled(tb, "I(vih)", "I(vil)")
    return r["i(vil)"][-1] / r["i(vih)"][-1]


def bank_partial(bank, vals, beta, beta_ls, c_cal):
    """Level-0 analog partial (m, l, o) from the bank readouts (AnalogIOC idiom):
    m = block max; l = exp(beta_ls*V_ls - beta*m) * C; o = l * (softmax weights @ vals)."""
    m = float(np.max(bank["pat"]))
    l = np.exp(beta_ls * bank["vls"] - beta * m) * c_cal
    w = bank["iout"] / np.sum(bank["iout"])
    return m, l, (w @ vals) * l


def main():
    r = Report("softmax_combine tb_combine_tree")
    vbt = bias()
    print(f"  vb_tail for I_B = {I_B * 1e9:.0f} nA: {vbt:.3f} V (gm/ID design {rescale.vb_tail():.3f} V)")

    # ---- level 0: both banks, beta and the V_ls slope ------------------------------
    banks = [bank_run(p, vbt) for p in BANKS]
    beta = float(np.mean([b["beta"] for b in banks]))
    vls = np.array([b["vls"] for b in banks])
    gold_ls = np.array([np.log(np.sum(np.exp(beta * p))) for p in BANKS])
    beta_ls = np.linalg.lstsq(np.vstack([vls, np.ones(len(vls))]).T, gold_ls, rcond=None)[0][0]
    print(f"  bank V_ls = {', '.join(f'{v * 1e3:.1f}' for v in vls)} mV; branch beta = "
          f"{beta:.2f} /V, V_ls slope beta_ls = {beta_ls:.2f} /V (kappa {beta_ls / beta:.3f})")
    m0 = float(np.max(BANKS[0]))
    c_cal = G.block_reduce(BANKS[0], None, beta)[1] / np.exp(beta_ls * banks[0]["vls"] - beta * m0)
    parts_an = [bank_partial(b, VALS[i], beta, beta_ls, c_cal) for i, b in enumerate(banks)]
    parts_gold = [G.block_reduce(BANKS[i], VALS[i], beta) for i in range(len(BANKS))]

    # ---- level 1: the DUT -------------------------------------------------------------
    shift = SCORE_CM - float(np.mean(vls))      # AnalogIOC VLS_SHIFT = 0.47 V (typed)
    print(f"  level shift = {shift * 1e3:.1f} mV (score CM - mean bank V_ls)")
    vls_group, gw, e_grp = group_run(list(vls + shift), vbt)
    m_group = float(max(np.max(p) for p in BANKS))

    cal = [(vls[0], vls[1]), (vls[0] - 0.01, vls[1]), (vls[0], vls[1] - 0.015),
           (vls[0] + 0.008, vls[1] - 0.006)]
    v_cal = [group_run([a + shift, b + shift], vbt)[0] for a, b in cal]
    g_cal = [np.log(np.sum(np.exp(beta_ls * np.array(p)))) for p in cal]
    s, c0 = np.linalg.lstsq(np.vstack([v_cal, np.ones(len(v_cal))]).T, g_cal, rcond=None)[0]
    resid = float(np.max(np.abs(np.array(g_cal) - (s * np.array(v_cal) + c0))))
    r.check("group node carries logsumexp-of-logsumexps", resid < RESID_MAX,
            f"slope {s:.2f} /V, worst residual {resid:.4f} nat < {RESID_MAX}")

    # group weights: branch-beta scale -> the l scale (kappa power law, AnalogIOC)
    gw_raw = gw.copy()
    kappa = beta_ls / beta
    gw = gw ** kappa / np.sum(gw ** kappa)
    print(f"  g_b raw = {', '.join(f'{x:.4f}' for x in gw_raw)}; kappa-corrected = "
          f"{', '.join(f'{x:.4f}' for x in gw)}")
    ol_bank = np.array([p[2] / p[1] for p in parts_an])
    l_bank_gf = np.array([p[1] * np.exp(beta * (p[0] - m_group)) for p in parts_an])
    ol_group = gw @ ol_bank
    l_group = float(np.mean(l_bank_gf / gw))
    o_group = l_group * ol_group

    rp = rescale_g(vls[1] + shift, vls[0] + shift, vbt)
    ratio = gw_raw[0] / gw_raw[1]
    r.check(f"B5 rescale pair == group-stage weight within {XCHK_TOL:.0%}",
            abs(rp - ratio) / ratio < XCHK_TOL,
            f"pair {rp:.4f} vs group {ratio:.4f} ({abs(rp - ratio) / ratio * 100:.2f} %)")

    # ---- group (m, l, o) vs golden ----------------------------------------------------
    gold = G.group_combine(parts_gold, beta)
    l_rel = abs(l_group - gold[1]) / gold[1]
    o_rel = float(np.max(np.abs(o_group - gold[2]) / (np.abs(gold[2]) + 1e-9)))
    m_err = (m_group - gold[0]) * 1e3
    r.check(f"flat group (m, l, o) within T5 {T5_BUDGET:.1%}",
            l_rel <= T5_BUDGET and o_rel <= T5_BUDGET and M_ERR_LO <= m_err <= M_ERR_HI,
            f"m err {m_err:+.1f} mV, l {l_rel * 100:.2f} %, o max {o_rel * 100:.2f} %")
    pair = G.monoid_combine(parts_gold[0], parts_gold[1], beta)
    assoc = bool(np.allclose(gold[1], pair[1]) and np.allclose(gold[2], pair[2]))
    ol_gold = gold[2] / gold[1]
    ol_rel = float(np.max(np.abs(ol_group - ol_gold) / (np.abs(ol_gold) + 1e-9)))
    r.check(f"associativity + analog o/l within T5 {T5_BUDGET:.1%}",
            assoc and ol_rel <= T5_BUDGET, f"flat == pairwise: {assoc}, o/l {ol_rel * 100:.2f} %")

    # ---- reported, not asserted (AnalogIOC) ---------------------------------------------
    print(f"  energy: bank {np.mean([b['energy'] for b in banks]) * 1e12:.2f} pJ, group "
          f"{e_grp * 1e12:.2f} pJ per {T_WIN * 1e6:.0f} us; group node {vls_group * 1e3:.1f} mV")
    print(f"  log-axis growth ln(G)/beta: G=2 {math.log(2) / beta * 1e3:.0f} mV, "
          f"G=16 {math.log(16) / beta * 1e3:.0f} mV (window 120 mV)")
    r.done()


if __name__ == "__main__":
    main()
