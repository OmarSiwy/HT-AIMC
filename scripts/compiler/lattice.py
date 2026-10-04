"""CSNR lattice-threshold schedule (task C, compile.py --lattice).

Paper L6 / law:csnr: the ideal pre-ADC signal is a discrete (N+1)-point
lattice of achievable MAC values, not a continuum. Placing converter
comparator thresholds MID-LATTICE (at the midpoints between adjacent
achievable values) rather than on the uniform (k+1/2)*D grid lets the
converter DELETE analog noise below half the local lattice pitch: up to
+6 dB / -3 converter bits when the pitch >> sigma_a. The gain dies when N
or sigma collapses the pitch to the converter LSB (measured: gain tracks
pitch/sigma_a; positive while pitch/sigma_a >~ 3, gone below ~2).

WHAT THIS EMITS (golden-validated, SPICE wiring OUT OF SCOPE):
Per matrix, per output column, the compiler computes the achievable MAC
lattice from the REAL INT4 weights x the real INT8 activation stream, then
derives the mid-lattice comparator boundaries and expresses them as
R-string ladder tap placements (analog/schematics/components/rstring_ladder:
4b code b3..b0 -> tap_k = vrn + k*(vrp-vrn)/15, k=0..15; monotone by
construction). Boundaries live in code units; the converter maps a code-unit
boundary `c` to the tap voltage vcm + c*u (u = D*C_u*VDD/C_int volts/unit,
integrator_conv). Because the R-string has only 16 taps between its two
rails, the schedule sizes (vrn, vrp) rails per (matrix, column block) to the
tensor's active lattice span and picks the nearest tap code per boundary --
the ladder's non-uniform-capable tap mux (CONTRACT: 'non-uniform-capable
R-string ladder + tap mux') selects the coarse threshold and SAR reference
taps per decision from this schedule.

HANDOFF INTERFACE (documented in FORMATS.md 'lattice thresholds'):
out_lattice/threshold_schedule.json carries, per matrix:
  D, u_per_code_note, per column-block: {vrn_code, vrp_code, lattice (sorted
  achievable macs), boundaries (mid-lattice, code units), tap_codes (4b per
  boundary, nearest ladder tap), pitch, sigma_break (the sigma_a at which
  the modeled lattice gain crosses 0)}.
The analog converter (A3) consumes tap_codes for its coarse comparator +
SAR reference taps; the code-unit -> volt map is vcm + code*u.

Run: python3 scripts/compiler/compile.py --lattice   -> scripts/compiler/out_lattice/
"""

import json
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from golden import model as G                                    # noqa: E402

TILE = 16
LADDER_TAPS = 16           # 4b R-string: k = 0..15


def _tap_code(boundaries, vrn_code, vrp_code):
    """Nearest 4b ladder tap (0..15) for each boundary in code units, given
    the block's rails [vrn_code, vrp_code]. tap_k = vrn + k*(vrp-vrn)/15."""
    span = max(vrp_code - vrn_code, 1e-9)
    k = np.rint((np.asarray(boundaries, float) - vrn_code) / span * (LADDER_TAPS - 1))
    return np.clip(k, 0, LADDER_TAPS - 1).astype(int)


def _sigma_break(macs, D, pitch, rng, n=400, hi=8.0):
    """The sigma_a (in code units) where the modeled lattice CSNR gain over
    the uniform converter crosses 0 -- i.e. where the pitch collapses and the
    lattice stops deleting noise. Bisection on injected Gaussian noise using
    the golden converter models. Returns None if lattice never beats uniform
    (dense-lattice dead regime) or beats it everywhere up to `hi`."""
    if macs.size <= 2:
        return None
    thr = G.lattice_thresholds(macs, D)
    # deterministic ideal sample set: sweep the achievable values themselves
    ideal = np.repeat(macs, max(1, n // macs.size))

    def gain(sig):
        noisy = ideal + rng.normal(0, sig, ideal.shape)
        return (G.csnr_db(ideal, G.convert_lattice(noisy, macs, thr))
                - G.csnr_db(ideal, G.convert_uniform(noisy, D)))

    lo, hival = 0.05, hi
    if gain(lo) <= 0:
        return None                        # dead already at tiny noise
    if gain(hival) > 0:
        return float(hival)                # still winning at hi (rare)
    for _ in range(24):
        mid = 0.5 * (lo + hival)
        if gain(mid) > 0:
            lo = mid
        else:
            hival = mid
    return float(0.5 * (lo + hival))


def lattice_schedule(Wq, xq_stream, D, cols_per_block=TILE, seed=7):
    """Per-column-block lattice threshold schedule for one compiled matrix.

    Wq (O, I) INT4; xq_stream list/array (T, I) real INT8 activations; D the
    converter LSB. Blocks are single output columns tiled over the input
    row-tiles the same way the fabric accumulates -- here we take the WHOLE
    row (all row-tiles summed) as the lattice of the final column value,
    which is what the readout converter actually digitizes. Returns a list of
    per-block dicts (see module docstring)."""
    rng = np.random.default_rng(seed)
    X = np.asarray(np.stack(list(xq_stream)), dtype=np.int64)     # (T, I)
    O = Wq.shape[0]
    blocks = []
    for j in range(0, O, cols_per_block):
        cols = Wq[j:j + cols_per_block]                          # (b, I)
        macs, pitch = G.output_lattice(cols, X)
        thr = G.lattice_thresholds(macs, D)
        vrn_c, vrp_c = int(macs.min()), int(macs.max())
        taps = _tap_code(thr, vrn_c, vrp_c)
        sb = _sigma_break(macs, D, pitch, rng)
        blocks.append({
            "col_start": int(j), "col_stop": int(min(j + cols_per_block, O)),
            "vrn_code": vrn_c, "vrp_code": vrp_c,
            "pitch": int(pitch), "n_lattice": int(macs.size),
            "lattice": macs.tolist(),
            "boundaries": [float(x) for x in thr],
            "tap_codes": taps.tolist(),
            "sigma_break": (None if sb is None else round(sb, 3)),
        })
    return blocks


def csnr_gain_curve(Wq, xq_stream, D, sigmas, seed=11):
    """Measured lattice-vs-uniform CSNR gain (dB) over an injected-Gaussian
    analog-noise sweep, pooled over all output columns of a matrix. The
    task-C evidence: where the gain lives and where it dies. Returns dict
    sigma -> {uniform_db, lattice_db, gain_db, mean_pitch}."""
    rng = np.random.default_rng(seed)
    X = np.asarray(np.stack(list(xq_stream)), dtype=np.int64)
    ideal = X @ Wq.T                                             # (T, O)
    # per-column lattice + mid-lattice thresholds
    cols_macs, cols_thr, pitches = [], [], []
    for j in range(Wq.shape[0]):
        macs, pitch = G.output_lattice(Wq[j], X)
        cols_macs.append(macs)
        cols_thr.append(G.lattice_thresholds(macs, D))
        pitches.append(pitch)
    out = {}
    for s in sigmas:
        noisy = ideal + rng.normal(0, s, ideal.shape)
        y_lat = np.empty_like(ideal)
        for j in range(Wq.shape[0]):
            y_lat[:, j] = G.convert_lattice(noisy[:, j], cols_macs[j],
                                            cols_thr[j])
        y_uni = G.convert_uniform(noisy, D)
        gu = G.csnr_db(ideal, y_uni)
        gl = G.csnr_db(ideal, y_lat)
        out[float(s)] = {"uniform_db": round(gu, 3), "lattice_db": round(gl, 3),
                         "gain_db": round(gl - gu, 3),
                         "mean_pitch": round(float(np.mean(pitches)), 3)}
    return out


def run_lattice(prompt=None, out=None, model_path=None, quiet=False,
                sigmas=(0.25, 0.5, 1.0, 2.0, 4.0, 8.0)):
    """Compile the real model, emit the per-tensor lattice threshold schedule
    + a measured CSNR gain curve per matrix. Reuses the frozen classical
    compile for calibrated weights + the real activation streams."""
    from compiler import compile as CC
    t0 = time.time()
    log = (lambda *a: None) if quiet else print
    prompt = prompt or CC.PROMPT
    out = Path(out) if out else CC.OUT.parent / "out_lattice"
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        res = CC.run(prompt=prompt, out=Path(td),
                     model_path=model_path or CC.MODEL, quiet=True)
    mats, stream, ids = res["mats"], res["stream"], res["ids"]
    log(f"[lattice] classical baseline compiled ({time.time() - t0:.1f}s)")

    sched, curves = {}, {}
    for n, C in mats.items():
        sched[n] = lattice_schedule(C["Wq"], stream[n], C["D"])
        curves[n] = csnr_gain_curve(C["Wq"], stream[n], C["D"], sigmas)
        best = max(v["gain_db"] for v in curves[n].values())
        # where it dies: first sigma (ascending) with gain <= 0.05 dB
        die = next((s for s in sorted(curves[n]) if curves[n][s]["gain_db"]
                    <= 0.05), None)
        log(f"[lattice] {n}: peak gain {best:+.2f} dB, "
            f"dies ~sigma {die}, mean pitch "
            f"{curves[n][min(curves[n])]['mean_pitch']} "
            f"({time.time() - t0:.1f}s)")

    (out / "threshold_schedule.json").write_text(json.dumps({
        "note": "CSNR lattice thresholds (task C, law:csnr). Boundaries and "
                "rails in CONVERTER CODE UNITS; ladder maps code c -> tap "
                "voltage vcm + c*u, u = D*C_u*VDD/C_int volts/unit "
                "(integrator_conv). tap_codes are 4b R-string taps "
                "(rstring_ladder: tap_k = vrn + k*(vrp-vrn)/15). SPICE wiring "
                "out of scope -- golden-validated emission only.",
        "ladder_taps": LADDER_TAPS,
        "matrices": {n: {"D": mats[n]["D"], "blocks": sched[n]}
                     for n in mats},
    }, indent=1))
    (out / "csnr_gain.json").write_text(json.dumps({
        "note": "measured lattice-vs-uniform CSNR (dB) under injected "
                "Gaussian analog noise sigma_a (code units), pooled over "
                "output columns. gain_db > 0 = lattice deletes noise; dies as "
                "sigma_a collapses the lattice pitch (law:csnr).",
        "sigmas": list(sigmas),
        "matrices": curves,
    }, indent=1))
    log(f"[lattice] wrote {out} ({time.time() - t0:.1f}s)")
    return {"schedule": sched, "curves": curves, "mats": mats,
            "stream": stream, "ids": ids, "out_dir": out}


if __name__ == "__main__":
    run_lattice()
