"""Yosys + ASAP7 (RVT, TT 0.7 V 25C) synthesis sweep of sa_top.

usage: synth_sweep.py <asap7 platform dir> <out dir>

Hierarchical synthesis (no flatten): each unique PE variant is mapped once, so the
128x128 array (16k PEs) synthesizes in minutes; `stat -top` sums the hierarchy.
Cell area only (no placement utilization, no wires): ORFS P&R gives the real die area.
Writes <out>/<name>.json = {name, params, area_um2, cells, flops, area_by_module}.
"""
import gzip
import json
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SYSREF = Path(__file__).resolve().parents[1]
SRC = sorted(str(p) for p in (SYSREF / "src").glob("*.sv"))

CONFIGS = {f"s{n}": dict(Rows=n, Cols=n, AccDepth=n) for n in (8, 16, 32, 64, 128)}
CONFIGS["s16_nopipe"] = dict(Rows=16, Cols=16, AccDepth=16, PipeMul=0)
CONFIGS["s16_booth"] = dict(Rows=16, Cols=16, AccDepth=16, _booth=1)
CONFIGS["s16_int4w"] = dict(Rows=16, Cols=16, AccDepth=16, WW=4)
CONFIGS["s32_booth"] = dict(Rows=32, Cols=32, AccDepth=32, _booth=1)


def libs(platform, out):
    """Unzip the TT RVT libs once; return (all libs, sequential lib)."""
    lib_dir = Path(platform) / "lib" / "NLDM"
    paths = []
    for name in ("AO_RVT_TT_nldm_211120", "INVBUF_RVT_TT_nldm_220122",
                 "OA_RVT_TT_nldm_211120", "SIMPLE_RVT_TT_nldm_211120", "SEQ_RVT_TT_nldm_220123"):
        src = lib_dir / f"asap7sc7p5t_{name}.lib"
        dst = out / src.name
        if not dst.exists():
            if src.exists():
                shutil.copy(src, dst)
            else:
                with gzip.open(str(src) + ".gz", "rb") as f, open(dst, "wb") as g:
                    shutil.copyfileobj(f, g)
        paths.append(str(dst))
    return paths, paths[-1]


def run(name, params, lib_paths, seq_lib, out, period_ps=400):
    booth = params.pop("_booth", 0)
    chp = " ".join(f"-set {k} {v}" for k, v in params.items())
    libargs = " ".join(f"-liberty {p}" for p in lib_paths)
    # ponytail: dont-use list mirrors the ORFS asap7 platform (x1p/xp drive strengths, ICG/SDF)
    dont = "-dont_use *x1p*_ASAP7* -dont_use *xp*_ASAP7* -dont_use SDF* -dont_use ICG*"
    script = f"""
read_liberty -lib {' '.join(lib_paths)}
read_verilog -defer -sv {' '.join(SRC)}
chparam {chp} sa_top
hierarchy -top sa_top
synth -top sa_top {'-booth' if booth else ''}
dfflibmap -liberty {seq_lib} {dont}
abc -D {period_ps} {libargs} {dont}
opt_clean -purge
tee -o {out}/{name}.stat.json stat -json -top sa_top {libargs}
"""
    (out / f"{name}.ys").write_text(script)
    subprocess.run(["yosys", "-q", "-l", str(out / f"{name}.log"), "-s", str(out / f"{name}.ys")],
                   check=True)
    st = json.loads((out / f"{name}.stat.json").read_text())
    top = st["design"]
    mods = st["modules"]
    flops = 0
    for cell, cnt in top.get("num_cells_by_type", {}).items():
        if cell.startswith(("DFF", "SDF", "ASYNC_DFF")):
            flops += cnt
    res = dict(name=name, params=params, booth=bool(booth),
               area_um2=top["area"], cells=top["num_cells"], flops=flops,
               area_by_module={m.strip("\\"): v.get("area") for m, v in mods.items()})
    (out / f"{name}.json").write_text(json.dumps(res, indent=1))
    print(f"{name:12s} area {top['area']:12.1f} um2  cells {top['num_cells']:8d}  flops {flops}")
    return res


def main():
    platform, out = sys.argv[1], Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    lib_paths, seq = libs(platform, out)
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = [ex.submit(run, n, dict(p), lib_paths, seq, out) for n, p in CONFIGS.items()]
        for f in futs:
            f.result()


if __name__ == "__main__":
    main()
