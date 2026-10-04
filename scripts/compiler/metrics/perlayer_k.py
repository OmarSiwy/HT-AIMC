"""Heterogeneous per-tensor cascade depth K (law:cascade placement).

The O2 cascade projection assumed ONE global K. The paper's law:cascade
sets K* PER SNR budget:  K* = min{10^((SNRs-SNRt)/10), ln(1+eps)/eg}.
Attention-class tensors and FFN-class tensors have different budgets, so a
per-tensor K schedule runs deep K on the FFN bulk (~95% of the 10944
passes/token: 10368 FFN vs 576 attn) and shallow K on attention WITHOUT
violating any layer's SNR budget.

Physics is NOT reimplemented here — every K, SNR and pass-time comes from
analog/schematics/specs.py (specs.k_star / cascade_snr_db / conv_time).
Pass counts + tensor classes come from the compiler's own manifest
(scripts/compiler/out/manifest.json: per-tensor passes_per_token, 576 attn / 10368
ffn, summing to 10944 — the counted A5 tiling).

Per-tensor SNR budget (STATUS anchors, documented):
  SNRt (end-to-end target, shared) = 28 dB.
  SNRs (per-stage analog CSNR, per tensor CLASS):
     attention-class 34 dB  -> K* random-term = 10^0.6 = 4.0
     FFN-class       38 dB  -> K* random-term = 10^1.0 = 10, gain-capped 6.6
  (The compiler's manifest carries per-tensor sqnr_w_db, but that is the
  INT4 weight-quant CSNR, not the analog per-stage CSNR the cascade budget
  is about; the SNRs anchors are the measured-class analog numbers from
  specs.SNR_S_DB / STATUS. Attention 34/28 reproduces specs' K*=4 anchor.)

K_layer = largest K with cascade_snr_db(K, SNRs) >= SNRt.  This is the
budget-respecting FLOOR: cascade_snr_db includes BOTH the random sqrt(K)
term AND the (1+eg)^K gain-compounding term, so it lands one below the
random-only k_star (attention K=3 not 4; FFN K=7, gain-term-bound).

Schedule (merged-window S5 + ping-pong S6 + cascade, projected, same
runtime substitutions as pdk_projections.py):
   pass(K) = max(T_in=136*t_q, T_conv/K) + 4*t_q     [CASCADE.md law]
   token time = sum_tensor passes_tensor * pass(K_tensor)

Run: PYTHONPATH=analog/schematics python3 scripts/compiler/metrics/perlayer_k.py
Emits scripts/compiler/out/perlayer_k_schedule.json + prints the projection table.
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, "analog", "docs"))
sys.path.insert(0, HERE)
import specs                                    # noqa: E402
import pdk_projections as pj                    # noqa: E402
from pdk_specs import Sky130          # noqa: E402
from pdk_specs import Asap7Proj   # noqa: E402
from pdk_specs import TsmcN4Proj  # noqa: E402

MANIFEST = os.path.join(ROOT, "scripts", "compiler", "out", "manifest.json")
OUT = os.path.join(ROOT, "scripts", "compiler", "out", "perlayer_k_schedule.json")

# per-tensor-class SNR budget (STATUS anchors) — see module docstring
SNR_T_DB = 28.0                                  # shared end-to-end target
SNR_S_DB = {"attn": 34.0, "ffn": 38.0}           # per-stage analog CSNR/class
SOHU_TOKS_DIE = pj.SOHU_TOKS_DIE                  # 62,500 (vendor, 70B)


def tensor_class(name):
    return "ffn" if name.startswith("ffn") else "attn"


def k_for_budget(snr_s_db, snr_t_db=SNR_T_DB, eg=specs.EG_SERVO):
    """Largest K whose full cascade SNR (random sqrt(K) + (1+eg)^K gain)
    still clears the target. specs.cascade_snr_db is the physics; this is
    the clamp. K=1 is the floor (a single window always clears the budget
    the tile already meets)."""
    k = 1
    while specs.cascade_snr_db(k + 1, snr_s_db=snr_s_db, eg=eg) >= snr_t_db:
        k += 1
    return k


def k_schedule(mats):
    """K_layer per tensor = the SNR-budget floor for its class. The swing
    bind (specs.cascade_k_swing: K-window charge on fixed C_int) is checked
    but does NOT clamp here — statistically the K-sum grows sqrt(K)*sigma and
    fits the C_int for K <= ~(MAC_MAX/CODE_MAX)^2*K ~ 6-7 with the running-sum
    guard tb_cascade uses (STATUS "swing vs SNR vs gain"); the SNR budget
    binds first at these K. Guaranteed-worst-case headroom needs C_int'=K*C_int
    (specs note)."""
    return {n: k_for_budget(SNR_S_DB[tensor_class(n)]) for n in mats}


def pass_time_K(pdk, tq, K):
    """Merged-window + ping-pong cascade pass at depth K (CASCADE.md law).
    T_in = 136*t_q merged window; one conversion amortized over K."""
    return max(136 * tq, specs.conv_time(pdk) / K) + 4 * tq


def _setup_pdk(pdk, tq):
    """Same runtime substitutions pdk_projections.evaluate uses (specs.py
    has no per-PDK TQ_SIM / SAR hook yet)."""
    if getattr(pdk, "cal_proj", None):
        specs._CAL[pdk.name] = pdk.cal_proj
    specs.TQ_SIM = 10e-9
    sky = Sky130()
    tau_ref, sar_ref = specs.tau_absorb(sky), specs.sar_time(sky)
    specs.TQ_SIM = tq
    tau = specs.tau_absorb(pdk)
    specs.sar_time = lambda p=None, s=sar_ref * tau / tau_ref: s


def project(mats, total_passes):
    """tok/s/die for the heterogeneous schedule vs uniform K=4 / K=14 /
    Sohu, at each PDK and scale. Returns rows for the .md + the schedule."""
    sched = k_schedule(mats)
    die = pj.DIE_MM2 * pj.FILL
    rows = []
    for label, pdk, tq0 in (("sky130 (real t_q)", Sky130(), 200e-12),
                            ("asap7_proj", Asap7Proj(), None),
                            ("tsmc_n4_proj", TsmcN4Proj(), None)):
        saved = (specs.TQ_SIM, specs.sar_time)
        try:
            tq = tq0 or pdk.t_q_grid
            _setup_pdk(pdk, tq)
            tiles = int(die / pj.TILE_MM2[pdk.name])
            for scale, npt in (("7B", int(7e9 / 256)),
                               ("70B", int(70e9 / 256))):
                f = npt / total_passes
                passes = {n: mats[n]["passes_per_token"] * f for n in mats}
                het = tiles / sum(passes[n] * pass_time_K(pdk, tq, sched[n])
                                  for n in passes)
                u4 = tiles / (npt * pass_time_K(pdk, tq, 4))
                u14 = tiles / (npt * pass_time_K(pdk, tq, 14))
                avg_k = sum(passes.values()) / sum(passes[n] / sched[n]
                                                   for n in passes)
                rows.append({
                    "pdk": label, "scale": scale, "avg_k": avg_k,
                    "het": het, "u4": u4, "u14": u14,
                    "het_vs_u4": het / u4, "het_vs_sohu": het / SOHU_TOKS_DIE,
                })
        finally:
            specs.TQ_SIM, specs.sar_time = saved
    return sched, rows


def eg_sweep(mats, total_passes, egs=(0.003, 0.002, 0.0015, 0.001),
             pdk_label="tsmc_n4_proj", scale="7B"):
    """ADDITIVE (task #21): tok/s/die at N4/7B as the servoed gain error eg
    sweeps. Re-runs k_for_budget per class with the given eg (the gain term
    ln(1+eps)/eg loosens as eg shrinks) and re-projects. Default output is
    NOT affected — main()'s avg-K=6.54 / 60,328 anchor uses specs.EG_SERVO
    and is untouched. Returns rows [{eg, avg_k, ffn_k, attn_k, het_toks,
    vs_sohu}], plus the uniform-K=14 ceiling for reference.

    HONEST NOTE the number shows: FFN K is ALSO capped by the RANDOM sqrt(K)
    term (SNRs=38 -> random cap K=10), so eg->0 tops FFN at K=9, NOT K=14.
    The uniform-K=14 (1.95x) point needs a HIGHER per-stage SNRs, not just a
    tighter servo — see SERVO_EG.md."""
    pdk = {"tsmc_n4_proj": TsmcN4Proj(), "asap7_proj": Asap7Proj(),
           "sky130 (real t_q)": Sky130()}[pdk_label]
    tq0 = 200e-12 if pdk_label.startswith("sky130") else None
    die = pj.DIE_MM2 * pj.FILL
    npt = int(7e9 / 256) if scale == "7B" else int(70e9 / 256)
    saved = (specs.TQ_SIM, specs.sar_time)
    rows = []
    try:
        tq = tq0 or pdk.t_q_grid
        _setup_pdk(pdk, tq)
        tiles = int(die / pj.TILE_MM2[pdk.name])
        f = npt / total_passes
        passes = {n: mats[n]["passes_per_token"] * f for n in mats}
        u14 = tiles / (npt * pass_time_K(pdk, tq, 14))
        for eg in egs:
            sched = {n: k_for_budget(SNR_S_DB[tensor_class(n)], eg=eg)
                     for n in mats}
            het = tiles / sum(passes[n] * pass_time_K(pdk, tq, sched[n])
                              for n in passes)
            avg_k = sum(passes.values()) / sum(passes[n] / sched[n]
                                               for n in passes)
            rows.append({
                "eg": eg, "avg_k": avg_k,
                "ffn_k": sched["ffn_gate"], "attn_k": sched["attn_q"],
                "het_toks": het, "vs_sohu": het / SOHU_TOKS_DIE,
                "u14_toks": u14, "u14_vs_sohu": u14 / SOHU_TOKS_DIE,
            })
    finally:
        specs.TQ_SIM, specs.sar_time = saved
    return rows


def main():
    mats = json.load(open(MANIFEST))["matrices"]
    total = sum(mats[n]["passes_per_token"] for n in mats)
    sched, rows = project(mats, total)

    # what binds each class: random term (k_star int) vs gain term
    binds = {}
    for c, s in SNR_S_DB.items():
        rand = 10.0 ** ((s - SNR_T_DB) / 10.0)
        gain = math.log(1.02) / specs.EG_SERVO
        binds[c] = "gain (1+eg)^K" if gain < rand else "random sqrt(K)"

    out = {
        "note": "heterogeneous per-tensor cascade depth K (law:cascade "
                "placement). K_layer respects each tensor's SNR budget "
                "(cascade_snr_db(K) >= SNRt); FFN-deep + attention-shallow. "
                "PROJECTED (merged-window + ping-pong schedule, same PDK "
                "substitutions as pdk_projections.py).",
        "snr_target_db": SNR_T_DB,
        "snr_source_db_by_class": SNR_S_DB,
        "eg_servo": specs.EG_SERVO,
        "binds_by_class": binds,
        "k_by_tensor": sched,
        "cascade_snr_db_by_tensor": {
            n: round(specs.cascade_snr_db(
                sched[n], snr_s_db=SNR_S_DB[tensor_class(n)]), 2)
            for n in sched},
        "passes_per_token_by_tensor": {n: mats[n]["passes_per_token"]
                                       for n in sched},
        "total_passes_per_token": total,
        "sohu_toks_die": SOHU_TOKS_DIE,
        "projection": rows,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w"), indent=1)
    print(f"wrote {OUT}")
    print(f"K schedule (SNRt={SNR_T_DB} dB): "
          + ", ".join(f"{n}={sched[n]}" for n in sched))
    print(f"binds: attn={binds['attn']}, ffn={binds['ffn']}")
    print(f"\n{'PDK':18s}{'scale':6s}{'avgK':>6s}"
          f"{'het':>12s}{'u=4':>12s}{'u=14':>12s}"
          f"{'het/u4':>8s}{'het/Sohu':>10s}")
    for r in rows:
        print(f"{r['pdk']:18s}{r['scale']:6s}{r['avg_k']:6.2f}"
              f"{r['het']:12,.0f}{r['u4']:12,.0f}{r['u14']:12,.0f}"
              f"{r['het_vs_u4']:7.2f}x{r['het_vs_sohu']:9.2f}x")
    return out


if __name__ == "__main__":
    main()
