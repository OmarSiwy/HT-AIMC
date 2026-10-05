"""gm/ID lookups for sizing, backed by GmIDVisualizer LUTs of the active PDK.

Recipe (per device): pick (gm/ID, L) from the device's role, then
    gm (from the spec) -> ID = gm / (gm/ID) -> W = ID / J_D(gm/ID, L)

API (dev is "nfet" or "pfet", L in um):
    gm_ID(vgs, L, dev)          gm/ID at a gate overdrive |VGS|
    J_D(gm_id, L, dev)          drain current density ID/W [A/um]
    VGS(gm_id, L, dev)          |VGS| [V]
    gm_gds(gm_id, L, dev)       intrinsic gain
    W_for_gm(gm, gm_id, L, dev) width [um] for a target gm [S]
    ft(gm_id, L, dev)           transit frequency gm/(2pi*Cgg) [Hz]

Tables: analog/docs/gmid_tables/<pdk>/<dev>_L<L>.csv, generated on first use and
committed, so a PDK hotswap regenerates them once (typical corner, 27C):
  planar PDKs   GmIDVisualizer (mid-VDS slice, W=10um). Needs `libGmIDVisualizer.so` via
                $GMID_LIB (or next to `gmid_runner` on PATH) and `ngspice` on PATH.
  FinFET PDKs   (pdk.w_fin) ESPice directly: GmIDVisualizer writes `W=` cards and drives
                ngspice, and BSIM-CMG takes NFIN and needs OSDI there. One DC sweep gives
                ID; one AC deck holding a device copy per VGS gives gm, gds and Cgg
                (= Im(i_gate)/w, BSIM-CMG's terminal charges include the overlaps).
                10 fins (W = 10*w_fin), VDS = VDD/2. Needs `espice` on PATH.

Self-check: python3 analog/docs/gmid.py
"""
import ctypes as C
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pdk_specs import get_pdk, pdk_root  # noqa: E402

TABLE_ROOT = Path(__file__).resolve().parent / "gmid_tables"
COLS = ("VGS", "gm_ID", "ID_per_W", "gm", "gds", "gm_gds", "cgg")
_cache = {}


# ── GmIDVisualizer C FFI ────────────────────────────────────────────────────
class _Pt(C.Structure):
    _fields_ = [("x", C.c_double), ("y", C.c_double)]


class _Plot(C.Structure):
    _fields_ = [("svg_path", C.c_char * 1024), ("title", C.c_char * 128),
                ("x_label", C.c_char * 64), ("y_label", C.c_char * 64),
                ("lut", C.POINTER(_Pt)), ("lut_len", C.c_int)]


class _Res(C.Structure):
    _fields_ = [("plots", C.POINTER(_Plot)), ("plot_count", C.c_int),
                ("error", C.c_char * 512)]


def _lib():
    path = os.environ.get("GMID_LIB")
    if not path and shutil.which("gmid_runner"):
        path = str(Path(shutil.which("gmid_runner")).resolve().parent / "libGmIDVisualizer.so")
    if not path or not Path(path).exists():
        raise FileNotFoundError("libGmIDVisualizer.so not found: set $GMID_LIB "
                                "(https://github.com/OmarSiwy/GmIDVisualizer)")
    lib = C.CDLL(path)
    lib.gmid_characterise.restype = C.POINTER(_Res)
    lib.gmid_characterise.argtypes = [C.c_char_p] * 5 + [
        C.c_double, C.c_double, C.c_int, C.c_double, C.c_double, C.c_int,
        C.c_double, C.c_double, C.c_double]
    lib.gmid_free_result.argtypes = [C.POINTER(_Res)]
    return lib


def _device_model_file(pdk, dev):
    """The model file GmIDVisualizer includes: the PDK's declared per-device file when it
    has one (sky130: its lib's scale=1u breaks GmIDVisualizer's W=10u), else the
    pdk_specs wrapper for the typical corner (lib section + setup + params)."""
    model = pdk.nfet if dev == "nfet" else pdk.pfet
    if pdk.gmid_device_file:
        return model, pdk_root() / pdk.variant / pdk.gmid_device_file.format(
            model=model, corner=pdk.typical)
    return model, pdk.model_file(pdk.typical)


def _espice(deck: str) -> dict:
    """Run an ESPice deck, return {column: np.array} (complex columns as complex)."""
    exe = shutil.which("espice")
    if not exe:
        raise FileNotFoundError("espice not on PATH — run ./env.sh analog")
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "c.sp").write_text("* gmid.py\n" + deck + ".end\n")   # line 1 = title
        r = subprocess.run([exe, "c.sp", "-r", "c.csv", "--format=csv"], cwd=d,
                           capture_output=True, text=True, timeout=1800)
        if r.returncode:
            raise RuntimeError(f"espice failed:\n{r.stderr[-1500:]}")
        names = (Path(d) / "c.csv").read_text().splitlines()[0].split(",")
        data = np.loadtxt(Path(d) / "c.csv", delimiter=",", skiprows=1, ndmin=2)
    cols = {n: data[:, i] for i, n in enumerate(names)}
    for n in [n for n in names if n.endswith("_re")]:
        cols[n[:-3]] = cols.pop(n) + 1j * cols.pop(n[:-3] + "_im")
    return cols


def characterise_espice(dev, L, pdk=None, nfin=10, n=141, f=1e6):
    """FinFET table for (dev, L) from ESPice (see module doc). Returns its path."""
    pdk = pdk or get_pdk()
    model = pdk.nfet if dev == "nfet" else pdk.pfet
    pol = 1.0 if dev == "nfet" else -1.0
    vds, W = pol * pdk.vdd / 2, nfin * pdk.w_fin
    card = f"{model} L={pdk.um(L)} NFIN={nfin}"
    lib = "\n".join(pdk.model_lines(pdk.typical)) + "\n.temp 27\n"
    vgs = np.linspace(0.0, pdk.vdd, n)
    dc = _espice(lib + f"vg g 0 0\nvd d 0 {vds}\nM1 d g 0 0 {card}\n"
                 f".dc vg 0 {pol * pdk.vdd} {pol * pdk.vdd / (n - 1)}\n")
    i_d = np.abs(dc["i(vd)"])
    ac = lib + "".join(
        f"vga{k} ga{k} 0 {pol * v} ac 1\nvda{k} da{k} 0 {vds}\nMa{k} da{k} ga{k} 0 0 {card}\n"
        f"vgb{k} gb{k} 0 {pol * v}\nvdb{k} db{k} 0 {vds} ac 1\nMb{k} db{k} gb{k} 0 0 {card}\n"
        for k, v in enumerate(vgs)) + f".ac lin 1 {f:g} {f:g}\n"
    r = _espice(ac)
    gm = np.array([abs(r[f"i(vda{k})"][0].real) for k in range(n)])
    gds = np.array([abs(r[f"i(vdb{k})"][0].real) for k in range(n)])
    cgg = np.array([abs(r[f"i(vga{k})"][0].imag) / (2 * np.pi * f) for k in range(n)])
    keep = i_d > 0
    table = np.column_stack([vgs, gm / np.where(keep, i_d, 1), i_d / W, gm, gds,
                             gm / np.maximum(gds, 1e-30), cgg])[keep & (vgs > 0)]
    out = TABLE_ROOT / pdk.name
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{dev}_L{L:g}.csv"
    hdr = (f"{model} L={L}um NFIN={nfin} (W={W:g}um) VDS={abs(vds):g}V {pdk.typical} 27C "
           f"(ESPice, gm/gds/cgg from AC at {f:g} Hz)\n" + ", ".join(COLS))
    np.savetxt(path, table, delimiter=",", header=hdr, fmt="%.6e")
    return path


def characterise(dev, L, pdk=None):
    """Run GmIDVisualizer for (dev, L) and write the table CSV. Returns its path."""
    pdk = pdk or get_pdk()
    if pdk.w_fin:
        return characterise_espice(dev, L, pdk)
    model, mfile = _device_model_file(pdk, dev)
    pol = 1.0 if dev == "nfet" else -1.0     # PMOS: sweep VGS/VDS negative
    out = TABLE_ROOT / pdk.name
    out.mkdir(parents=True, exist_ok=True)
    work = out / "work"
    lib = _lib()
    rp = lib.gmid_characterise(str(mfile).encode(), model.encode(), b"mosfet",
                               str(work).encode(), None,
                               0.0, pol * pdk.vdd, 181, pol * 0.05, pol * pdk.vdd, 18,
                               10.0, float(L), 27.0)
    r = rp.contents
    try:
        if r.error:
            raise RuntimeError(f"GmIDVisualizer: {r.error.decode()}")
        luts = [np.array([[r.plots[i].lut[j].x, r.plots[i].lut[j].y]
                          for j in range(r.plots[i].lut_len)]) for i in range(r.plot_count)]
    finally:
        lib.gmid_free_result(rp)
    if not len(luts[0]):
        raise RuntimeError(f"GmIDVisualizer returned an empty LUT for {model} L={L}")
    # plots: 0 gmid->jd, 1 gmid->gm, 2 gmid->gds, 3 gmid->av, 4 vgs->gmid,
    # 6 gmid->cgg [F at W=10um, incl. overlaps] (same order)
    if len(luts) < 7:
        raise RuntimeError("GmIDVisualizer too old: no cgg plot (need >= c3e0091)")
    table = np.column_stack([np.abs(luts[4][:, 0]), luts[0][:, 0], luts[0][:, 1],
                             luts[1][:, 1], luts[2][:, 1], luts[3][:, 1], luts[6][:, 1]])
    table = table[np.argsort(table[:, 0])]
    path = out / f"{dev}_L{L:g}.csv"
    hdr = (f"{model} L={L}um W=10um VDS=mid-sweep {pdk.typical} 27C (GmIDVisualizer)\n"
           + ", ".join(COLS))
    np.savetxt(path, table, delimiter=",", header=hdr, fmt="%.6e")
    shutil.rmtree(work, ignore_errors=True)
    return path


def load_table(dev, L, pdk=None):
    pdk = pdk or get_pdk()
    key = (pdk.name, dev, float(L))
    if key not in _cache:
        path = TABLE_ROOT / pdk.name / f"{dev}_L{L:g}.csv"
        # tables written before the cgg column have 6 columns: regenerate once
        if not path.exists() or np.loadtxt(path, delimiter=",", ndmin=2).shape[1] != len(COLS):
            characterise(dev, L, pdk)
        _cache[key] = dict(zip(COLS, np.loadtxt(path, delimiter=",").T))
    return _cache[key]


# ── monotone cubic (Fritsch–Carlson), from AnalogIOC sizing/lookup.py ──────────
def pchip(x, y, xq):
    """Monotone cubic hermite interpolation; x strictly increasing; clamps xq to the
    table (edges are the leakage floor / oxide limit — extrapolating is meaningless)."""
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    h = np.diff(x)
    d = np.diff(y) / h
    m = np.empty_like(y)
    m[0], m[-1] = d[0], d[-1]
    inner = np.sign(d[:-1]) * np.sign(d[1:]) > 0
    w1 = 2 * h[1:] + h[:-1]
    w2 = h[1:] + 2 * h[:-1]
    harm = np.where(inner, (w1 + w2) / (w1 / np.where(d[:-1] == 0, 1, d[:-1])
                                        + w2 / np.where(d[1:] == 0, 1, d[1:])), 0.0)
    m[1:-1] = np.where(inner, harm, 0.0)
    xq = np.clip(np.asarray(xq, float), x[0], x[-1])
    i = np.clip(np.searchsorted(x, xq) - 1, 0, len(h) - 1)
    t = (xq - x[i]) / h[i]
    h00 = (1 + 2 * t) * (1 - t) ** 2
    h10 = t * (1 - t) ** 2
    h01 = t ** 2 * (3 - 2 * t)
    h11 = t ** 2 * (t - 1)
    return h00 * y[i] + h10 * h[i] * m[i] + h01 * y[i + 1] + h11 * h[i] * m[i + 1]


def _monotone_branch(tab):
    """From the LAST gm/ID local maximum onward, strictly decreasing vs VGS (below the
    peak the leakage floor is not invertible). Returned ascending in gm/ID."""
    g = tab["gm_ID"]
    i0 = int(np.argmax(g))
    maxima = np.where((g[1:-1] >= g[:-2]) & (g[1:-1] > g[2:]))[0] + 1
    if len(maxima):
        i0 = max(i0, int(maxima[-1]))
    keep = [i0]
    for i in range(i0 + 1, len(g)):
        if g[i] < g[keep[-1]] - 1e-9:
            keep.append(i)
    keep = np.array(keep)[::-1]
    return {c: tab[c][keep] for c in COLS}


def gm_ID(vgs, L, dev="nfet"):
    tab = load_table(dev, L)
    return pchip(tab["VGS"], tab["gm_ID"], vgs)


def _inv_lookup(gm_id, L, dev, col, log=False, pdk=None):
    br = _monotone_branch(load_table(dev, L, pdk))
    y = np.log10(br[col]) if log else br[col]
    v = pchip(br["gm_ID"], y, gm_id)
    return 10 ** v if log else v


def J_D(gm_id, L, dev="nfet", pdk=None):
    """Drain current density ID/W [A/um] at (gm/ID, L). Log-interpolated."""
    return _inv_lookup(gm_id, L, dev, "ID_per_W", log=True, pdk=pdk)


def VGS(gm_id, L, dev="nfet", pdk=None):
    return _inv_lookup(gm_id, L, dev, "VGS", pdk=pdk)


def gm_gds(gm_id, L, dev="nfet", pdk=None):
    return _inv_lookup(gm_id, L, dev, "gm_gds", pdk=pdk)


def ft(gm_id, L, dev="nfet", pdk=None):
    """Transit frequency gm/(2pi*Cgg) [Hz] at (gm/ID, L). Cgg is the total gate
    capacitance (BSIM cgg + overlaps); W cancels. Log-interpolated like J_D."""
    br = _monotone_branch(load_table(dev, L, pdk))
    if not (br["cgg"] > 0).all():
        raise RuntimeError(f"no cgg in the {dev} L={L} table (model reports none)")
    return 10 ** pchip(br["gm_ID"], np.log10(br["gm"] / (2 * np.pi * br["cgg"])), gm_id)


def W_for_gm(gm, gm_id, L, dev="nfet", pdk=None):
    """Width [um] to realise gm [S] at (gm/ID, L): W = (gm/gm_ID) / J_D."""
    return (gm / gm_id) / J_D(gm_id, L, dev, pdk)


if __name__ == "__main__":
    # ASAP7 has one drawn gate length: check at it rather than a model-only 2*Lmin
    L2 = get_pdk().min_l if get_pdk().w_fin else 2 * get_pdk().min_l
    for dev in ("nfet", "pfet"):
        j12, v12 = J_D(12.0, L2, dev), VGS(12.0, L2, dev)
        rt = float(gm_ID(v12, L2, dev))
        assert abs(rt - 12.0) < 0.3, f"{dev} round-trip gm_ID(VGS(12))={rt}"
        assert 1e-7 < j12 < 1e-4, f"{dev} J_D(12) = {j12}"
        assert J_D(8.0, L2, dev) > J_D(15.0, L2, dev)
        assert ft(8.0, L2, dev) > ft(15.0, L2, dev) > 1e8, f"{dev} ft(8,15)"
        print(f"{dev}: VGS(12,L={L2:g})={v12:.3f} V  J_D(12)={j12*1e6:.2f} uA/um  "
              f"gm/gds(12)={gm_gds(12.0, L2, dev):.0f}  ft(12)={ft(12.0, L2, dev)/1e9:.2f} GHz  "
              f"round-trip={rt:.2f}")
    # AnalogIOC's own sky130 tables (ngspice, VDS=0.9V) gave these; GmIDVisualizer must agree
    for (g, L, dev), ref in ({} if get_pdk().name != "sky130" else {(12, 0.3, "nfet"): 11.0e-6, (10, 0.3, "nfet"): 16.1e-6,
                             (10, 0.5, "pfet"): 2.29e-6}).items():
        j = float(J_D(g, L, dev))
        assert abs(j / ref - 1) < 0.10, f"J_D({g},{L},{dev})={j:.3e} vs AnalogIOC {ref:.3e}"
        print(f"  J_D({g},{L},{dev}) = {j*1e6:.2f} uA/um (AnalogIOC {ref*1e6:.2f})")
    print("GMID SELF-CHECK: PASS")
