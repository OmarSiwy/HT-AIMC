"""Run one testbench across every PDK corner x temperature (signoff ladder rung 4).

    python3 analog/common/corners.py analog/<block>/test/tb_x.py [--temps -40,27,125]

The testbench is unchanged — it reads $CORNER/$SIM_TEMP through bench.testbench(). $DUT is
passed through, so `DUT=pex corners.py ...` runs corners on the post-layout netlist.
Exits non-zero if any corner fails, and prints a corner x temp grid. CORNERS_JOBS=n runs
n corners in parallel (default 1).
"""
import argparse
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "docs"))
from pdk_specs import get_pdk  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tb")
    ap.add_argument("--temps", default="-40,27,125")
    ap.add_argument("--corners", default=",".join(get_pdk().corners))
    a = ap.parse_args()
    temps = [t for t in a.temps.split(",")]
    runs = [(c, t) for c in a.corners.split(",") for t in temps]

    def one(ct):
        env = dict(os.environ, CORNER=ct[0], SIM_TEMP=ct[1])
        return subprocess.run([sys.executable, a.tb], env=env, capture_output=True, text=True)

    # CORNERS_JOBS=n runs n corners side by side (slow transient benches); default serial
    with ThreadPoolExecutor(int(os.environ.get("CORNERS_JOBS", 1))) as ex:
        res = list(ex.map(one, runs))
    grid, ok = {}, True
    for (c, t), p in zip(runs, res):
        grid[c, t] = p.returncode == 0
        ok &= grid[c, t]
        if p.returncode:
            print(f"--- FAIL {c} {t}C ---\n" + "\n".join(
                ln for ln in p.stdout.splitlines() if "FAIL" in ln) + p.stderr[-800:])
    print(f"\n{Path(a.tb).stem}  DUT={os.environ.get('DUT', 'sch')}")
    print("corner " + "".join(f"{t:>8}" for t in temps))
    for c in a.corners.split(","):
        print(f"{c:<7}" + "".join(f"{'PASS' if grid[c, t] else 'FAIL':>8}" for t in temps))
    print(f"CORNERS: {'PASS' if ok else 'FAIL'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
