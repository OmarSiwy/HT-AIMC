"""Mixed-signal co-simulation: imc_driver RTL driving the Verilog-A tiles in ESPice (open loop).

    python3 test/tb_cosim.py [ml2|bitserial] [ideal|full] [job ...]

The driver runs the systolic reference's jobs (jobs.py: random GEMM / GEMV, extremes, the SmolLM2
attn_q slice) on 2 tiles of 8 rows x 8 columns: weights streamed just in time from the HBM model,
activations skewed one pass per tile, phases from the tick counter, codes from the Verilog-A SARs
into the RTL calibration + 24-b chain + requant.

Why open loop: ESPice compiles each device with 64-bit unknown masks, so a VerA .v device takes at
most 64 pins in this build (VerA's own limit is 256); the driver needs 192 tile pins at this size.
The tile's inputs (weights, rows, phases) never depend on its outputs, so the loop is cut exactly:
  (1) driver RTL + ideal tiles in iverilog -> pin trace (and the ideal-golden self-check)
  (2) ESPice: the Verilog-A tiles driven by PWL sources from the trace -> every SAR round's code
  (3) driver RTL again, tiles replaced by those codes round by round -> chain outputs

  ideal  noise and mismatch off in every model: the outputs must match the bit-true golden
         (scripts/golden/imc_tile.py) within one code per K-chunk (the drive network still settles)
  full   every error term on (the .va defaults = the golden's P): error against the systolic
         array's exact INT8 result, and against the golden's analog-error model on the same job
         (rms ratio within 0.75-1.33 per job; tb_va_snr does the pooled 0.5 dB comparison)
  The C-DAC reference carries the full tile's converter load (r_ref / sc, c_ref * sc) when the ref
  term is on, and is a stiff source otherwise.
Energy: the supplies of the level nets and references are integrated (physical), plus the event
energies the models book on their emon pins (gain-cell writes, column switches, conversions).
"""
import importlib.util
import math
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "digital/imc_driver/test"))
import va_lib as L          # noqa: E402
import gen                  # noqa: E402
import jobs as J            # noqa: E402
from golden import imc_tile as G   # noqa: E402

_spec = importlib.util.spec_from_file_location("imc_driver_tests", ROOT / "digital/imc_driver/test/run_tests.py")
DRV = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(DRV)       # the driver's iverilog runner (sysreference has a run_tests too)
FAILS = []
# kind "dyn": the per-event (fresh) terms only; the frozen static draws (unit caps, C-DAC, ratios) off
DYN = ("ktc", "cmp", "drive", "share", "ref")
T_READ = 1.3e-9 + 60e-12            # SAR t_conv + transition: when a round's code is read


def check(name, ok, msg):
    print(f"{'PASS' if ok else 'FAIL'} {name}: {msg}", flush=True)
    if not ok:
        FAILS.append(name)


def pin_names(cfg):
    """Tile-facing pins in the trace's bit order (LSB first)."""
    R, C, N = cfg.rows, cfg.cols, cfg.ntiles
    return ([f"drv_{k}" for k in range(N * R * 3)] + [f"wl_{k}" for k in range(N * R)] +
            [f"wbl_{k}" for k in range(C * 8)] + ["phi_drv", "phi_rst", "phi_sh", "phi_mrg", "phi_samp", "sar_clk"])


def pwl_sources(cfg, trace, tr=30e-12):
    """Pin trace -> one PWL voltage source per pin (0/VDD, tr ramps); also the sar_clk rise times."""
    names = pin_names(cfg)
    hist = {n: [(0.0, 0.0)] for n in names}
    prev, rises = 0, []
    for line in Path(trace).read_text().split("\n"):
        if not line.strip():
            continue
        t_ns, h = line.split()
        t, v = float(t_ns) * 1e-9, int(h.replace("x", "0").replace("z", "0"), 16)
        ch = v ^ prev
        for k, n in enumerate(names):
            if (ch >> k) & 1:
                b = (v >> k) & 1
                hist[n] += [(t, (1 - b) * L.VDD), (t + tr, b * L.VDD)]
                if n == "sar_clk" and b:
                    rises.append(t)
        prev = v
    src = [f"V{n} {n} 0 0" if len(pts) == 1 else
           f"V{n} {n} 0 PWL({' '.join(f'{t:.6e} {v:.4g}' for t, v in pts)})" for n, pts in hist.items()]
    return src, rises


def deck(cfg, sources, tstop, kind, cc=0, seed0=0):
    """Per tile: the row drive, three level nets, the reference, 8 x COLS gain cells + crosspoints,
    COLS columns and COLS/AS SARs, all driven by the trace's PWL sources."""
    R, C, N, B, AS = cfg.rows, cfg.cols, cfg.ntiles, cfg.bits, cfg.adc_share
    p = cfg.params()
    sc = C / 256                                     # this tile is C of the 256 columns of a row
    crow, rsw = p.c_row * sc, p.tau_row / (p.c_row * sc)
    # kind: "ideal" (all off), "full" (all on) or "only:<term>" (one golden term on, the rest off)
    on = (lambda t: True) if kind == "full" else (lambda t: t in DYN) if kind == "dyn" else (lambda t: kind == f"only:{t}")
    nz = f"noise={int(on('ktc'))}"
    xp_sig = f"sig_cu_msb={p.sig_cu_msb * on('mismatch')} sig_cu_lsb={p.sig_cu_lsb * on('mismatch')}"
    col_sig = f"sig_racc={p.sig_racc * on('racc')} sig_merge={p.sig_merge * on('merge')}"
    sar_sig = f"noise={int(on('cmp'))} sig_dac={p.sig_dac_u * on('dac')} sig_cmp={p.sig_cmp * on('cmp')}"
    mode = 0 if cfg.mode == "ml2" else 1
    lines = [f"* GENERATED by tb_cosim.py: {N} x R{R} C{C} Verilog-A tiles ({cfg.mode}, {kind}) from the driver's pin trace"]
    lines += [f'.hdl "{m}.va"' for m in ("imc_gc", "imc_xp", "imc_col", "imc_rowdrv", "imc_sar", "imc_ref")]
    lines += [f"Vdd vdd 0 {p.vdd}", *sources]
    emon, pk = [], []
    for t in range(N):
        # level nets (tile-shared buffers) and the C-DAC reference; resistances are per full tile
        lines += [f"Nl1_{t} l1_{t} vdd imc_ref v0={p.vdd / 3} r_out={p.r_lvl_mid / sc}",
                  f"Nl2_{t} l2_{t} vdd imc_ref v0={2 * p.vdd / 3} r_out={p.r_lvl_mid / sc}",
                  f"Nl3_{t} l3_{t} vdd imc_ref v0={p.vdd} r_out={p.r_lvl_top / sc}",
                  # the C-DAC reference serves the full tile: r and C scaled so these C/AS converters see
                  # the droop of 256/AS (golden ref_cols); a stiff ideal source when the ref term is off
                  (f"Nvr_{t} vref_{t} vdd imc_ref v0={p.vref} r_out={p.r_ref / sc:.6g} c_dec={p.c_ref * sc:.6g}"
                   if on("ref") else f"Nvr_{t} vref_{t} vdd imc_ref v0={p.vref} r_out=1e-6")]
        drv = " ".join(f"drv_{(t * R + r) * 3 + k}" for r in range(R) for k in range(3))
        lines.append(f"Nrd_{t} {drv} phi_drv {' '.join(f'rp_{t}_{r}' for r in range(R))} "
                     f"{' '.join(f'rn_{t}_{r}' for r in range(R))} l1_{t} l2_{t} l3_{t} imc_rowdrv "
                     f"ROWS={R} mode={mode} cc={cc} c_row={crow:.6e} r_sw={rsw:.6e}")
        for c in range(C):
            q = []
            for r in range(R):
                nm = f"{t}_{c}_{r}"
                lines.append(f"Ngc_{nm} wl_{t * R + r} {' '.join(f'wbl_{c * 8 + b}' for b in range(8))} "
                             f"{' '.join(f's_{nm}_{b}' for b in range(8))} imc_gc")
                lines.append(f"Nxp_{nm} rp_{t}_{r} rn_{t}_{r} {' '.join(f's_{nm}_{b}' for b in range(8))} "
                             f"{' '.join(f'q_{nm}_{j}' for j in range(4))} imc_xp ROWS={R} seed={seed0 + 1000 * t + 10 * c + r + 1} {xp_sig}")
                q += [f"q_{nm}_{j}" for j in range(4)]
            lines.append(f"Ncol_{t}_{c} {' '.join(q)} phi_rst phi_sh phi_mrg op_{t}_{c} on_{t}_{c} ec_{t}_{c} imc_col "
                         f"ROWS={R} mode={mode} seed={seed0 + 7000 + 100 * t + c} {nz} {col_sig}")
            emon.append(f"ec_{t}_{c}")
        for j in range(C // AS):
            cols = range(j * AS, (j + 1) * AS)
            base = (t * (C // AS) + j) * B
            lines.append(f"Nsar_{t}_{j} {' '.join(f'op_{t}_{c}' for c in cols)} {' '.join(f'on_{t}_{c}' for c in cols)} "
                         f"phi_samp sar_clk vref_{t} {' '.join(f'code_{base + k}' for k in range(B))} cv_{t}_{j} es_{t}_{j} imc_sar "
                         f"BITS={B} AS={AS} seed={seed0 + 9000 + 10 * t + j} {sar_sig} vlogic={L.VDD}")
            pk.append(f"cv_{t}_{j}")
    # event energies: a B-source takes at most 8 probes, so they are booked in python from the
    # same counts and parameters the models use (tb_va_units checks the models book exactly these)
    lines += [".save " + " ".join(f"v({o})" for o in pk) + " i(vdd)", f".tran 10p {tstop:.4e}", ".end", ""]
    return "\n".join(lines)


def event_energy(cfg, job, A, n_rounds):
    """Energy the models book on emon: gain-cell '1' writes (both sides), column switches per
    column-pass, conversions per SAR round (imc_gc / imc_col / imc_sar defaults)."""
    Lay = A["L"]
    ones = sum(bin(int(w)).count("1") for w in Lay["w"])          # each row word written once
    passes = int(A["passes"])
    return (2 * ones * 0.52e-15 + passes * cfg.ntiles * cfg.cols * 67.6e-15 +
            n_rounds * cfg.ntiles * (cfg.cols // cfg.adc_share) * 253.5e-15)


def run_job(cfg, name, job, kind, cc=0, seed0=0):
    tag = f"{cfg.mode}_{kind}_{name}"
    okA, A = DRV.run(f"cosimA_{tag}", cfg, job, trace=True)
    src, rises = pwl_sources(cfg, A["dir"] / "pins.txt")
    res = L.espice(deck(cfg, src, rises[-1] + 2.5e-9, kind, cc, seed0), f"cosim_{tag}", timeout=900)
    N, NC, B = cfg.ntiles, cfg.cols // cfg.adc_share, cfg.bits
    rd = A["dir"].parent / f"cosimB_{tag}"
    rd.mkdir(parents=True, exist_ok=True)
    for t in range(N):
        rows = []
        for tr in rises:
            word = 0
            for j in range(NC):
                u = int(round(L.at(res, f"v(cv_{t}_{j})", tr + T_READ) * 1e3))
                word |= (u & ((1 << B) - 1)) << (j * B)
            rows.append(f"{word:x}")
        (rd / f"codes_{t}.hex").write_text("\n".join(rows) + "\n")
    _, Bres = DRV.run(f"cosimB_{tag}", cfg, job, replay=(str(rd), len(rises)))
    tm, i = res["time"], res["i(vdd)"]
    e_sup = -sum(0.5 * (i[k] + i[k - 1]) * (tm[k] - tm[k - 1]) for k in range(1, len(tm))) * cfg.params().vdd
    e_evt = event_energy(cfg, job, A, len(rises))
    cnt = dict(passes=int(A["passes"]), stall=A["stall"], ticks=int(A["log"].split("ticks=")[1].split()[0]),
               t_pass=A["t_pass"], okA=okA)
    return gen.layout(cfg, job), Bres["outs"], cnt, e_sup, e_evt


def evaluate(cfg, name, job, kind, Lay, outs, cnt, e_sup, e_evt):
    X, W = np.asarray(job["X"]), np.asarray(job["W"])
    C, Nout = cfg.cols, W.shape[1]
    acc = np.zeros((X.shape[0], Lay["Np"]), np.int64)
    got = set()
    for m, nb, a, y in outs:
        acc[m, nb * C:(nb + 1) * C] = a
        got.add((m, nb))
    ideal = np.zeros_like(acc)
    for m, nb, a, y in Lay["exp"]:
        ideal[m, nb * C:(nb + 1) * C] = a
    dcode = (acc - ideal)[:, :Nout]
    exact = np.clip(X, -127, 127) @ np.clip(W, -127, 127)
    err = acc[:, :Nout] * 64 - exact
    eq = ideal[:, :Nout] * 64 - exact                     # the ideal converter's own error
    snr = 10 * math.log10(np.var(exact) / max(np.mean(err ** 2), 1e-9))
    nch = Lay["Kp"] // cfg.rows
    passes = cnt["passes"]
    epass = (e_sup + e_evt) / passes / cfg.ntiles * (256 / C)
    print(f"  {name} {kind}: outputs {len(got)}/{len(Lay['exp'])}, passes {passes}, t_pass {cnt['t_pass']:.3f} ns, "
          f"stall after fill {cnt['stall']} | vs ideal golden: max |d| {np.max(np.abs(dcode))} codes over {nch} chunks, "
          f"{100 * np.mean(dcode == 0):.1f} % exact | vs systolic INT8: rms {np.sqrt(np.mean(err ** 2)):.1f} MAC "
          f"(ideal converter {np.sqrt(np.mean(eq ** 2)):.1f}), output SNR {snr:.1f} dB | energy per pass per "
          f"256-col tile {epass * 1e12:.1f} pJ (supplies {e_sup / passes / cfg.ntiles * 256 / C * 1e12:.1f}, "
          f"events {e_evt / passes / cfg.ntiles * 256 / C * 1e12:.1f})", flush=True)
    return dict(complete=len(got) == len(Lay["exp"]) and cnt["okA"], dmax=int(np.max(np.abs(dcode))),
                exact_frac=float(np.mean(dcode == 0)), nch=nch, snr=snr, err=err, eq=eq, exact=exact,
                epass=epass, e_sup=e_sup, e_evt=e_evt, cnt=cnt)


def golden_model_err(cfg, job, seeds=4, kind="full"):
    """The golden's analog-error model on the same job and configuration (different random draws)."""
    p = cfg.params()
    if kind == "dyn":
        p = replace(p, terms=DYN)
    if kind.startswith("only:"):
        t = kind[5:]
        p = replace(p, terms=(t,), noise=(t == "ktc"))
    X, W = np.asarray(job["X"]), np.asarray(job["W"])
    exact = np.clip(X, -127, 127) @ np.clip(W, -127, 127)
    e2 = []
    for s in range(seeds):
        tiles = [G.Tile(p, seed=100 * s + t) for t in range(cfg.ntiles)]
        acc, _ = G.gemm(X, W, p, tiles=tiles)
        e2.append(np.mean((acc * 64 - exact) ** 2))
    return float(np.sqrt(np.mean(e2)))


def cosim_jobs(rng):
    rot = J.real_rot_job(n_out=8)
    return [
        ("gemm_m4_k32", J.SR.rand_job(rng, 4, 32, 8)),
        ("gemv_k16", J.SR.rand_job(rng, 1, 16, 8)),
        ("extremes", dict(X=rng.choice([-128, 127, 0], (3, 16)), W=rng.choice([-128, 127], (16, 8)),
                          scale=np.full(8, 255), shift=rng.integers(0, 25, 8), offset=rng.integers(-128, 128, 8))),
        ("smollm2_attn_q_k32", dict(X=rot["X"][:, :32], W=rot["W"][:32, :8], scale=rot["scale"][:8],
                                    shift=rot["shift"][:8], offset=rot["offset"][:8])),
    ]


def main(argv):
    mode = argv[1] if len(argv) > 1 else "ml2"
    kind = argv[2] if len(argv) > 2 else "ideal"
    sel = argv[3:]
    cfg = replace(gen.Cfg(), mode=mode)
    rng = np.random.default_rng(7)
    for name, job in cosim_jobs(rng):
        if sel and name not in sel:
            continue
        r = evaluate(cfg, name, job, kind, *run_job(cfg, name, job, kind))
        if kind == "ideal":
            check(f"cosim {mode} ideal {name}", r["complete"] and r["dmax"] <= r["nch"],
                  f"chain outputs vs bit-true golden: max |d| {r['dmax']} codes ({100 * r['exact_frac']:.1f} % exact); "
                  f"driver schedule complete and self-checked: {r['complete']}")
        else:
            gm = golden_model_err(cfg, job, kind=kind)
            va = float(np.sqrt(np.mean(r["err"] ** 2)))
            # per job only 32-144 outputs (8-12 % rms sampling error): a sanity window; the precise
            # Verilog-A vs golden comparison is tb_va_snr (pooled outputs, SNR within 0.5 dB)
            check(f"cosim {mode} {kind} {name}", r["complete"] and 0.75 < va / gm < 1.33,
                  f"rms error vs exact INT8: Verilog-A {va:.1f} MAC, golden error model {gm:.1f} MAC "
                  f"(ratio {va / gm:.2f}); output SNR {r['snr']:.1f} dB")
    print("ALL COSIM CHECKS PASS" if not FAILS else f"COSIM CHECKS FAILED: {FAILS}")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
