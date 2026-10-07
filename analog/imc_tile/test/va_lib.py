"""Shared plumbing for the imc_tile testbenches: ESPice runs (serialized, memory-capped), CSV reads,
and PWL builders. Decks are written as text here (the co-sim precedent, digital/analogioc/build/cosim):
they carry a VerA .v device and vector Verilog-A ports, which this file spells out directly."""
import csv
import os
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
BLK = HERE.parent
VA = BLK / "va"
OUT = BLK / "output"
LOCK = os.environ.get("SPICE_LOCK", "/tmp/claude-1000/-home-omare-Documents-Projects-Trial-ResearchBoutros/"
                      "4a1145dd-b047-4b63-8a63-c5c6ca9a51fb/scratchpad/spice.lock")
VDD = 0.7
VTH = VDD / 2


def espice(deck, name, timeout=900):
    """Write deck to output/<name>/deck.sp, copy the models, run ESPice under the shared lock with
    a 4 GB cap. Returns {column: [values]} from the CSV rawfile."""
    d = OUT / name
    d.mkdir(parents=True, exist_ok=True)
    for f in VA.glob("*.va"):
        shutil.copy(f, d / f.name)
    (d / "deck.sp").write_text(deck)
    cmd = ["espice", "deck.sp", "--format=csv", "-r", "out.csv"]
    # The lock is taken here, per ESPice run. Do NOT wrap the benches in an outer `flock` on the same
    # file: the inner flock then waits forever (found by review). An outer holder sets SPICE_LOCK_HELD=1.
    if os.environ.get("SPICE_LOCK_HELD") == "1" and shutil.which("systemd-run"):
        cmd = ["systemd-run", "--user", "--scope", "-q", "-p", "MemoryMax=4G", "timeout", str(timeout)] + cmd
    elif shutil.which("systemd-run") and shutil.which("flock"):
        cmd = ["flock", "-w", "3600", LOCK, "systemd-run", "--user", "--scope", "-q", "-p", "MemoryMax=4G",
               "timeout", str(timeout)] + cmd
    r = subprocess.run(cmd, cwd=d, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"espice failed ({r.returncode}) in {d}:\n{r.stderr[-3000:]}{r.stdout[-1500:]}")
    return read_csv(d / "out.csv")


def read_csv(path):
    with open(path) as f:
        rows = csv.reader(f)
        head = next(rows)
        cols = {h: [] for h in head}
        for row in rows:
            for h, v in zip(head, row):
                cols[h].append(float(v))
    return cols


def at(res, node, t):
    """Value of column `node` at time t (linear interpolation)."""
    ts, vs = res["time"], res[node]
    for i in range(1, len(ts)):
        if ts[i] >= t:
            f = (t - ts[i - 1]) / max(ts[i] - ts[i - 1], 1e-30)
            return vs[i - 1] + f * (vs[i] - vs[i - 1])
    return vs[-1]


def pwl(points, tr=20e-12):
    """[(t_start, t_end, level)] high windows -> PWL(...) of a 0/VDD logic signal."""
    out = [(0.0, 0.0)]
    for t0, t1, lv in points:
        out += [(t0, 0.0), (t0 + tr, lv), (t1, lv), (t1 + tr, 0.0)]
    s = " ".join(f"{t:.4e} {v:.4g}" for t, v in out)
    return f"PWL({s})"
