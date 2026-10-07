"""Accuracy (V2-style) on the behavioural model: class-weighted per-pass SNR_eff against G2 (39.78 dB).

    python3 test/tb_accuracy.py            # 24 K-chunks per row, writes output/accuracy.json
    python3 test/tb_accuracy.py quick      # 6 K-chunks

Full 8 x 256 tiles, the golden's analog-error model (scripts/golden/imc_tile.py, the same laws and
parameters as the Verilog-A models; tb_va_snr and tb_cosim cross-check the two). The signal is the
per-pass column partial sum S = sum_8 w x of real operands: SmolLM2-135M blk.0 attn_q,
Hadamard-rotated, in the two operand formats the architecture documents name:
  tokact  INT8 per-token x and per-output-channel INT8 w (n4 w8a8_lead_tokact, ARCH_CHOSEN's
          interface: what the systolic reference computes). THIS IS THE ARCHITECTURE AS SPECIFIED.
  block8  every 8-row block of x and w rescaled to full scale (the n5 'block' rho the ARCH SNR
          budget is computed with). An architecture change: a dequant multiply per conversion and a
          per-block x quantizer, neither in the RTL; pooling (B4's K = 4) is incompatible with it.
Each K-chunk runs on its own tile draw (seed). Error terms are switched on one at a time over the
ideal quantizer, then all together. The ARCH section 2 terms the models do not simulate are booked at
their budget (golden BOOKED_DB). Class weight (N8): quantization, comparator and C-DAC count 3 dB less.
Gates per row: G2 (class-weighted >= 39.78 dB, with the 90 % bootstrap interval over chunks), and
V2's per-term rule (every modelled term within 0.5 dB of its ARCH budget, golden BUDGET_DB).
Adversarial rows: every row on the same drive level in every slot (the worst popcount), which the
rotated data almost never produce.
"""
import json
import math
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import jobs as J                       # noqa: E402
from golden import imc_tile as G      # noqa: E402

TARGET = 39.78
W_ADC = 10 ** -0.3


def passes(fmt, n_chunks, rot, adversarial=None, seed=0):
    X, W = rot["X"], rot["W"][:, :256]
    if fmt == "block8":
        X, W = G.block_scale(X, W, 8)
    ks = np.linspace(0, X.shape[1] // 8 - 1, n_chunks).astype(int)
    out = []
    rng = np.random.default_rng(seed)
    for k in ks:
        Xc = X[:, 8 * k:8 * k + 8]
        if adversarial:
            # ml2: |x| 85 puts every row on 2V/3 in all 4 slots, |x| 43 on V/3 in slots 1-3;
            # bit-serial: |x| 127 puts every row on V in all 7 slots. Random signs per row.
            mags = {"ml2": (85, 43), "bitserial": (127, 127)}[adversarial]
            m = np.array([mags[i % 2] for i in range(Xc.shape[0])])[:, None]
            Xc = m * rng.choice([-1, 1], Xc.shape)
        out.append((W[8 * k:8 * k + 8], Xc))
    return out


def chunk_stats(p, data):
    """Per chunk: error power per configuration (quant only, each term alone, all) and S moments."""
    cfgs = {"quant": replace(p, terms=(), noise=False)}
    for t in G.TERMS:
        cfgs[t] = replace(p, terms=(t,), noise=(t == "ktc"))
    cfgs["all"] = p
    rows = []
    for i, (W, X) in enumerate(data):
        r = {}
        for k, q in cfgs.items():
            _, S, e = G.pass_snr(q, W, X, seed=i)
            r[k] = float(np.sum(e.astype(float) ** 2))
        S = S.astype(float)
        r.update(n=S.size, s1=float(S.sum()), s2=float((S ** 2).sum()))
        rows.append(r)
    return rows


def summarize(rows):
    n = sum(r["n"] for r in rows)
    ps = sum(r["s2"] for r in rows) / n - (sum(r["s1"] for r in rows) / n) ** 2
    m = {k: sum(r[k] for r in rows) / n for k in ["quant", "all", *G.TERMS]}
    parts = {"quant": m["quant"]}
    for t in G.TERMS:
        parts[t] = max(m[t] - m["quant"], 1e-30 * ps)
    booked = {k: ps * 10 ** (-v / 10) for k, v in G.BOOKED_DB.items()}
    db = lambda v: 10 * math.log10(ps / v)
    w = sum(v * (W_ADC if k in G.ADC_CLASS else 1.0) for k, v in parts.items()) + sum(booked.values())
    adc = parts["quant"] + parts["cmp"] + parts["dac"]
    return dict(ps=ps, parts=parts, adc=adc, total=db(m["all"] + sum(booked.values())), weighted=db(w),
                total_sim=db(m["all"]))


def budget(p, data, n_boot=400):
    rows = chunk_stats(p, data)
    s = summarize(rows)
    rng = np.random.default_rng(1)
    boot = [summarize([rows[j] for j in rng.integers(0, len(rows), len(rows))])["weighted"] for _ in range(n_boot)]
    lo, hi = np.percentile(boot, [5, 95])
    db = lambda v: round(10 * math.log10(s["ps"] / v), 2)
    parts_db = {k: db(v) for k, v in s["parts"].items()}
    terms_v2 = dict(ktc=parts_db["ktc"], mismatch=parts_db["mismatch"], adc=db(s["adc"]),
                    ref=parts_db["ref"], drive=parts_db["drive"])
    v2_fail = [k for k, v in terms_v2.items() if v < G.BUDGET_DB[k] - 0.5]
    return dict(parts_db=parts_db, adc_db=db(s["adc"]), total_db=round(s["total"], 2),
                total_sim_db=round(s["total_sim"], 2), weighted_db=round(s["weighted"], 2),
                ci90=[round(lo, 2), round(hi, 2)], v2_fail=v2_fail, rms_S=math.sqrt(s["ps"]), n_chunks=len(rows))


def pooled_budget(p, data):
    """pool_k tiles charge-averaged before one conversion: S over pool_k chunks, all terms on."""
    e2, s2, n = 0.0, [], 0
    q0 = replace(p, terms=(), noise=False)
    eq2 = 0.0
    for i in range(0, len(data) - p.pool_k + 1, p.pool_k):
        grp = data[i:i + p.pool_k]
        S = sum(np.clip(X, -127, 127) @ np.clip(W, -127, 127) for W, X in grp)
        for q, acc in ((p, "all"), (q0, "q")):
            tiles = [G.Tile(q, seed=i + j) for j in range(p.pool_k)]
            v = sum(t.merged(W, X) for t, (W, X) in zip(tiles, grp)) / p.pool_k
            c = tiles[0].convert(v)
            e = c * q.lsb_mac * q.pool_k - S
            if acc == "all":
                e2 += float(np.sum(e ** 2)); n += e.size; s2.append(S.ravel().astype(float))
            else:
                eq2 += float(np.sum(e ** 2))
    ps = float(np.var(np.concatenate(s2)))
    booked = sum(ps * 10 ** (-v / 10) for v in G.BOOKED_DB.values())
    pq = eq2 / n
    w = pq * W_ADC + max(e2 / n - pq, 1e-30) + booked
    return dict(parts_db={"quant": round(10 * math.log10(ps / pq), 2)},
                total_db=round(10 * math.log10(ps / (e2 / n + booked)), 2),
                weighted_db=round(10 * math.log10(ps / w), 2), ci90=None, v2_fail=["not split"],
                rms_S=math.sqrt(ps), n_chunks=len(data))


CASES = [
    # (fmt, mode, overrides, note)
    ("tokact", "ml2", {}, "as specified (round-1 pick)"),
    ("tokact", "bitserial", {}, "as specified, round-2 drive"),
    ("tokact", "bitserial", dict(pool_k=4), "as specified incl. B4 pooling K=4"),
    ("block8", "ml2", {}, "variant"),
    ("block8", "bitserial", {}, "variant"),
    ("block8", "ml2", dict(r_lvl_mid=5.3), "class-A level buffers (E3, N2_r2)"),
    ("block8", "ml2", dict(merge_on_top=True), "merge on the column, no overlap"),
    ("block8", "bitserial", dict(merge_on_top=True), "merge on the column, no overlap"),
    ("block8", "bitserial", dict(cc=True), "constant-charge dummies"),
    ("block8", "bitserial", dict(sig_cmp=4.05e-3), "measured IMC StrongARM sigma (N9_r2, M)"),
    ("block8", "bitserial", dict(sig_cmp=462e-6), "N6_r2 residue-amp SAR: sqrt((4.05 mV/9.54)^2 + 182 uV^2) (D)"),
    ("block8", "bitserial", dict(lsb_mac=32), "ARCH LSB 172 uV (vref 0.705 V)"),
    ("block8", "bitserial", dict(r_ref=1e-9, c_ref=1.0), "ideal reference (what the B5 placeholder costs)"),
    ("block8", "ml2", {}, "ADVERSARIAL popcount"),
    ("block8", "bitserial", {}, "ADVERSARIAL popcount"),
]


def main(argv):
    quick = len(argv) > 1 and argv[1] == "quick"
    rot = J.real_rot_job()
    n_chunks = 6 if quick else 24
    rows = []
    for fmt, mode, kw, note in CASES:
        adv = mode if note.startswith("ADVERSARIAL") else None
        data = passes(fmt, n_chunks, rot, adversarial=adv)
        p = G.P(mode=mode, **kw)
        b = pooled_budget(p, data) if p.pool_k > 1 else budget(p, data)
        tag = ",".join(f"{k}={v}" for k, v in kw.items()) or "default"
        r = dict(fmt=fmt, mode=mode, cfg=tag, note=note, **b, margin_db=round(b["weighted_db"] - TARGET, 2))
        rows.append(r)
        g2 = r["margin_db"] >= 0 and (r["ci90"] is None or r["ci90"][0] >= TARGET)
        verdict = "PASS" if g2 and not r["v2_fail"] else ("MARGINAL" if r["margin_db"] >= 0 else "FAIL")
        r["verdict"] = verdict
        ci = f" [90 % {r['ci90'][0]:.2f}..{r['ci90'][1]:.2f}]" if r["ci90"] else ""
        print(f"{verdict:8s} {fmt:6s} {mode:9s} {tag:24s} SNR {b['total_db']:6.2f} dB, class-weighted "
              f"{b['weighted_db']:6.2f}{ci} vs {TARGET} (margin {r['margin_db']:+.2f}); V2 per-term fails "
              f"{r['v2_fail'] or 'none'} | " + " ".join(f"{k} {v:.1f}" for k, v in b["parts_db"].items())
              + (f" adc {b['adc_db']:.1f}" if "adc_db" in b else "") + f"  ({note})", flush=True)
    out = HERE.parent / "output" / ("accuracy_quick.json" if quick else "accuracy.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(rows, indent=1))
    spec = [r for r in rows if r["fmt"] == "tokact" and r["cfg"] in ("default", "pool_k=4")]
    var = [r for r in rows if r["fmt"] == "block8" and r["cfg"] == "default" and not r["note"].startswith("ADV")]
    print("ACCURACY, architecture as specified (tokact): " +
          ("PASS" if any(r["verdict"] == "PASS" for r in spec) else "FAIL in every drive mode"))
    print("ACCURACY, block8 variant at default parameters: " +
          ", ".join(f"{r['mode']} {r['verdict']}" for r in var))
    return 0 if any(r["verdict"] == "PASS" for r in spec) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
