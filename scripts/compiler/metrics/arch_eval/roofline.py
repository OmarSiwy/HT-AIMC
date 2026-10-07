"""Roofline of the analog IMC design against the lever-matched systolic baseline, per die.

    python3 scripts/compiler/metrics/arch_eval/roofline.py [design.json] [-o docs/architecture/roofline]

One panel per condition set (ARCH, Sohu). Roofs: HBM bandwidth x intensity, the tiles' peak at
the peak-tok/s operating point, and the power roof (die power cap x TOPS/W). Points: prefill,
one decode step and the whole wave. The grey curve is decode intensity as the batch grows; it
levels off because every stream reads its own KV cache. Writes <out>.pdf and <out>.png.
"""
import argparse
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from arch_eval import ROOT, cli, design, metric, model  # noqa: E402

HERE = Path(__file__).parent


def machine(s, k):
    pk = s["peak"]
    n = pk["dies"] * k.get("system_dies", 1)
    pts = {ph: (v["ops"] / v["bytes"], v["ops"] / v["s"] / n / 1e12) for ph, v in pk["phases"].items()}
    ops = sum(v["ops"] * (1 if ph == "prefill" else 128) for ph, v in pk["phases"].items())
    pts["wave"] = (ops / (pk["hbm_Bps_die"] * n * pk["T_wave_s"]), ops / pk["T_wave_s"] / n / 1e12)
    t = cli.table(s, k)
    return dict(peak=t["peak_tops"] + 2 * s["tile"]["rail"]["att_mac_per_s"] / 1e12, bw=k["hbm_Bps"],
                power=k["power_cap_W_per_mm2"] * k["die_mm2"] * s["tops_w"], pts=pts, B=pk["B"], tok_s=s["tok_s_die"],
                tops_w=s["tops_w"], pre_frac=pk["T_prefill_s"] / pk["T_wave_s"])


def panel(ax, title, a, b, curve, asym, b_kv, b_why):
    x = np.logspace(-0.5, 6.3, 400)
    top = max(a["peak"], b["peak"], a["power"], b["power"])
    for m, c, ls, name in ((a, "#1f6fd1", "-", "analog IMC"), (b, "#e07b1a", "--", "systolic (matched)")):
        ax.plot(x, np.minimum(m["peak"], m["bw"] * x / 1e12), c=c, ls=ls, lw=2,
                label=f"{name}: {m['peak']:,.0f} TOPS, {m['bw'] / 1e9:,.0f} GB/s")
        ax.axhline(m["power"], c=c, ls=":", lw=1.2)
        mk = dict(prefill="o", decode="s", wave="*")
        for ph, (xi, yi) in m["pts"].items():
            ax.plot(xi, yi, mk[ph], ms=11 if ph == "wave" else 8, mfc=c if m is a else "none", mec=c, mew=1.8)
            if m is a:
                ax.annotate(ph if ph != "decode" else "decode step", (xi, yi), textcoords="offset points",
                            xytext=(8, -12), fontsize=8)
    Bs = np.logspace(0, np.log10(b_kv * 16), 200)
    ax.plot(curve[0], curve[1], c="0.45", lw=1, zorder=0)
    for bb in (1, 16, 128, b_kv):
        i = np.argmin(abs(Bs - bb))
        ax.plot(curve[0][i], curve[1][i], ".", c="0.3")
        ax.annotate(f"B={bb}" + (f" ({b_why})" if bb == b_kv else ""), (curve[0][i], curve[1][i]),
                    textcoords="offset points", xytext=(-6, 6), ha="right", fontsize=7, c="0.3")
    ax.axvline(asym, c="0.45", ls=":", lw=1)
    ax.text(asym * 0.9, top * 0.02, f"decode limit\nB → ∞: {asym:,.0f} ops/B", c="0.3", ha="right", fontsize=7)
    ridge = a["peak"] * 1e12 / a["bw"]
    ax.axvline(ridge, c="#1f6fd1", ls="-.", lw=0.8)
    ax.text(ridge * 1.1, top * 0.02, f"ridge\n{ridge:,.0f} ops/B", c="#1f6fd1", fontsize=7)
    ax.set(xscale="log", yscale="log", xlim=(x[0], x[-1]), ylim=(top * 1e-4, top * 2.5), title=title,
           xlabel="arithmetic intensity (ops per HBM byte)", ylabel="TOPS per die")
    ax.grid(True, which="both", lw=0.3, alpha=0.5)
    rows = [("", "analog", "systolic"), ("roof, TOPS", a["peak"], b["peak"]), ("power roof", a["power"], b["power"]),
            ("prefill", a["pts"]["prefill"][1], b["pts"]["prefill"][1]),
            ("decode step", a["pts"]["decode"][1], b["pts"]["decode"][1]),
            ("tok/s", a["tok_s"], b["tok_s"]), ("TOPS/W", a["tops_w"], b["tops_w"]),
            ("prefill time", f"{a['pre_frac']:.0%}", f"{b['pre_frac']:.0%}")]
    f = lambda v: v if isinstance(v, str) else (f"{v:,.3g}" if v < 100 else f"{v:,.0f}")  # noqa: E731
    txt = "\n".join(f"{r[0]:<12}{f(r[1]):>8}{f(r[2]):>9}" + ("" if not i else
                    f"  {r[1] / r[2]:.2f}x" if i < 7 else "") for i, r in enumerate(rows))
    ax.text(0.985, 0.03, txt, transform=ax.transAxes, ha="right", va="bottom", family="monospace", fontsize=7.5,
            bbox=dict(fc="white", ec="0.7", lw=0.6))
    ax.legend(loc="upper left", fontsize=8, title="roofs (solid/dashed), power roof dotted", title_fontsize=7)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("design", nargs="?", default=str(HERE / "designs/notes_native.json"))
    ap.add_argument("-o", "--out", default=str(ROOT / "docs/architecture/roofline"))
    a = ap.parse_args(argv)
    d = design.load(a.design)
    fig, axes = plt.subplots(1, 2, figsize=(15, 6.2))
    for ax, cond in zip(axes, ("arch", "sohu")):
        k = metric.knobs_for(cond)
        s = model.evaluate(d, k)
        wb, base = cli.matched_baseline(d, s, cond, k)
        # per-stream KV bytes per step: two batches at the same operating point
        ctx = model.Ctx(d, k)
        p1, p2 = (model.system_point(ctx, s["tile"], s["die"], s["plan"], B) for B in (1, 2))
        kv = p2["phases"]["decode"]["bytes"] - p1["phases"]["decode"]["bytes"]
        w = p1["phases"]["decode"]["bytes"] - kv
        ops1 = p1["phases"]["decode"]["ops"]
        Bs = np.logspace(0, np.log10(s["peak"]["B"] * 16), 200)
        I = ops1 * Bs / (w + Bs * kv)
        curve = (I, np.minimum(cli.table(s, k)["peak_tops"], k["hbm_Bps"] * I / 1e12))
        A, Bm = machine(s, k), machine(base, k)
        name = "ARCH: Llama-3-8B, 512/128, 100 mm², 1 HBM3 stack" if cond == "arch" else \
            f"Sohu: Llama-3-70B FP8, 2048/128, B=1000, {k['die_mm2']:,.0f} mm², 4.8 TB/s (per die of 8)"
        panel(ax, f"{name}\nanalog {d['name']} vs systolic W{wb} (same weight and KV formats)", A, Bm, curve,
              ops1 / kv, s["peak"]["B"], "fixed batch" if k.get("batch") else "KV limit")
        print(f"{cond}: analog peak {A['peak']:.0f} TOPS, systolic {Bm['peak']:.0f}; "
              + "; ".join(f"{ph} I={v[0]:.4g} ops/B, {v[1]:.4g} TOPS" for ph, v in A["pts"].items())
              + f"; decode asymptote {ops1 / kv:.0f} ops/B")
    fig.suptitle("Roofline per die, projected (arch_eval). Filled = analog IMC, hollow = systolic. "
                 "o prefill, □ one decode step, ★ whole wave. Compute roof = tiles + attention rail", fontsize=10)
    fig.tight_layout()
    for ext in ("pdf", "png"):
        fig.savefig(f"{a.out}.{ext}", dpi=160)
    print(f"wrote {a.out}.pdf/.png")


if __name__ == "__main__":
    main()
