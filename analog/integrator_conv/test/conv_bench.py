"""One column conversion through the contract handshakes (INTERFACE.md §6), shared by
tb_integrator_conv, tb_eventrate and tb_integrator_conv_mc.

Fixture (AnalogIOC tb_integrator_conv, re-cut to the macro boundary):
  signal    a REAL 1x1 weight_tile (Cp = w, Cn = 0) on vg, so the charge per code is the
            tile's own; row 0 driven by an A5 envelope of `nib` cycles (xin_n if neg)
  timing    ideal PWL for what tile_seq makes (§6.2): rst high until T_RST, LO window of
            16 t_q chop cycles (tile chop parked tphi1 = tphi1e = 1, tphi2 = 0 outside
            it), settle N_SETTLE t_q, then sgo. Converter chop phi1/phi1e/phi2 always on.
  wrapper   conv_seq at transistor level (async_ctrl deck), pkt_d = D
  rail      rtl_standin.va (tile_fsm/event_ctrl/sar_ctrl stand-in, 2FF latency at
            T_CLK_MAX)
  refs      4 rstring_ladders, static codes, between the §2 ideal rails (thr: vcm +-
            15.5 D u_cal, sar: vcm +- 16 D u_cal fine_ref_trim); OTA replica bias
            (ota_bench.bias_network); split supplies vdd/vdd_ota/vdd_cmp/vdd_pkt
Result per point: code = sign * min(16 * crossings + fine, 127) with crossings counted on
the cb_req/cb_cross handshake, fine = the stand-in's kept SAR bits, sign = col_sign;
energy = vdd_cmp + vdd_pkt (AnalogIOC's accounting: comparators, packet driver + bank)
over the coarse phase (sgo -> first cmp_req) and the fine phase (-> last cmp_ack fall).
Results are cached per (DUT, CORNER, SIM_TEMP, seed) under output/tb so tb_eventrate
reuses tb_integrator_conv's points.
"""
import functools
import hashlib
import inspect
import json
import os
import sys
import threading
from pathlib import Path

A = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(A / "docs"), str(A / "common")] + [
    str(A / b / "netlist") for b in ("integrator_conv", "weight_tile", "rstring_ladder",
                                     "async_ctrl")] + [
    str(A / "ota" / "test"), str(A / "async_ctrl" / "test"), str(A.parent / "scripts")]
import async_ctrl as ac  # noqa: E402
import integrator_conv as icv  # noqa: E402
import rstring_ladder  # noqa: E402
import rtl_standin  # noqa: E402
import specs  # noqa: E402
import weight_tile as wt  # noqa: E402
from bench import dut, dut_kind, dut_path  # noqa: E402
from devices import deck  # noqa: E402
from golden.model import eventrate_convert  # noqa: E402
from ota_bench import bias_network  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402

import spicerack as ps  # noqa: E402

PDK = get_pdk()
VDD = PDK.vdd
VCM = specs.VCM_FRAC * VDD
TQ = specs.TQ_SIM
D = 1
UD = D * specs.u_cal()
UDF = UD * specs.fine_ref_trim()
T_START = 5e-9                     # chop grid origin, cycle t0 = T_START + k*TQ
T_RST = 4 * TQ                     # I1 (sim)
K_WIN = 5                          # window = cycles K_WIN .. K_WIN+15 (rst gap >= 1 t_q)
T_WIN = T_START + K_WIN * TQ
T_WEND = T_WIN + ac.N_LO * TQ
T_SGO = T_WEND + ac.N_SETTLE * TQ  # I5b
EDGE = 0.1e-9
OUT = A / "integrator_conv" / "output" / "tb"
REFS = [("thrp", "thr_p", VCM, VCM + 15.5 * UD, 15), ("thrn", "thr_n", VCM - 15.5 * UD, VCM, 0),
        ("sarp", "sar_p", VCM, VCM + 16 * UDF, 15), ("sarn", "sar_n", VCM - 16 * UDF, VCM, 0)]
SIGS = ["out", "vg", "cb_req", "cb_cross", "cb_ack", "cmp_req", "cmp_ack", "col_sign",
        "sgd", "fire", "run", "clk_c", "b3", "b2", "b1", "b0", "rtl_done", "acq", "awake"]


def _write(text, tag):
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"{tag}_{hashlib.sha1(text.encode()).hexdigest()[:10]}.spice"
    if not p.exists():
        p.write_text(text)
    return p


def pulses(on, off, t_from, t_to, period=TQ, pre=0.0, post=0.0):
    """PWL high [t0+on, t0+off] per cycle t0 in [t_from, t_to); level pre/post outside."""
    pts, t0 = [(0, pre)], t_from
    while t0 < t_to - 1e-12:
        pts += [(t0 + on, pre if t0 == t_from else 0.0), (t0 + on + EDGE, VDD),
                (t0 + off, VDD), (t0 + off + EDGE, 0.0)]
        t0 += period
    if post:
        pts += [(t_to - 0.5e-9, 0.0), (t_to - 0.5e-9 + EDGE, post)]
    return pts


_LOCK = threading.Lock()


@functools.lru_cache(maxsize=None)
def _common():
    """(ladder deck, va params): sized once per process (the sizing runs ngspice
    measurements; parallel points share them)."""
    sz = icv.sizes(PDK)
    return (_write(deck(*rstring_ladder.build()), "ladder"),
            dict(c_int=sz["c_int"], c_pkt=sz["c_pkt"], c_ball=sz["c_ball"], r_kf=sz["r_kf"],
                 c_kf=sz["c_kf"], acq_gain=specs.fine_ref_trim()))


@functools.lru_cache(maxsize=None)
def _tile(w):
    return _write(wt.text([[w]], [[0]]), "tile")


def bench(w, nib, neg, end, corner="", temp=None, seed=None):
    kind = dut_kind()
    with _LOCK:
        (ladder, va), tile = _common(), _tile(w)
    top = dut("integrator_conv", icv.PORTS, kind, **(va if kind == "va" else {}))
    top.include(str(tile))
    top.X("xtile", "weight_tile", "xin_p_r0", "xin_n_r0", "vg", "tphi1", "tphi1e", "tphi2",
          "vcm", "vdd", "vss")
    top.include(str(ladder))
    for tag, out, lo, hi, code in REFS:
        top.V(name=f"lr{tag}n", positive=f"vrn_{tag}", negative="vss", value=lo)
        top.V(name=f"lr{tag}p", positive=f"vrp_{tag}", negative="vss", value=hi)
        top.X(f"xlad_{tag}", "rstring_ladder",
              *[("vdd" if (code >> b) & 1 else "vss") for b in range(4)],
              out, f"vrn_{tag}", f"vrp_{tag}", "vdd", "vss")
    top.include(str(dut_path("async_ctrl", "sch")))
    top.X("xseq", "conv_seq", *ac.CONV_SEQ_PORTS)
    bias_network(top)
    rtl_standin.rtl(top)
    tb = ps.Testbench(top)
    tb.use_pdk(PDK.model_library(corner or os.environ.get("CORNER", "")))
    tb.temperature = float(temp if temp is not None else os.environ.get("SIM_TEMP", 27))
    if seed is not None:
        tb.options(seed=seed)
    for name, net in (("sup", "vdd"), ("supo", "vdd_ota"), ("supc", "vdd_cmp"),
                      ("supp", "vdd_pkt"), ("rstn", "rst_n")):
        tb.V(name=name, positive=net, negative="0", value=VDD)
    tb.V(name="ss", positive="vss", negative="0", value=0.0)
    tb.V(name="cm", positive="vcm", negative="0", value=VCM)
    for b in range(3):
        tb.V(name=f"pd{b}", positive=f"pkt_d{b}", negative="0",
             value=VDD if (D >> b) & 1 else 0.0)
    tb.PieceWiseLinearVoltageSource(name="rst", positive="rst", negative="0",
                                    values=[(0, VDD), (T_RST, VDD), (T_RST + EDGE, 0.0)])
    tb.PieceWiseLinearVoltageSource(name="sgo", positive="sgo", negative="0",
                                    values=[(0, 0.0), (T_SGO, 0.0), (T_SGO + EDGE, VDD)])
    # §6.1 chop: converter always, tile in the window only (parked outside)
    for name, on, off in (("phi1", 0.3e-9, 1.9e-9), ("phi1e", 0.3e-9, 2.1e-9),
                          ("phi2", 2.5e-9, TQ - 0.5e-9)):
        tb.PieceWiseLinearVoltageSource(name=name, positive=name, negative="0",
                                        values=pulses(on, off, T_START, end))
        park = 0.0 if name == "phi2" else VDD
        tb.PieceWiseLinearVoltageSource(name="t" + name, positive="t" + name, negative="0",
                                        values=pulses(on, off, T_WIN, T_WEND, pre=park,
                                                      post=park))
    env = [(0, 0.0)] if not nib else [(0, 0.0), (T_WIN - 0.2e-9, 0.0), (T_WIN - 0.1e-9, VDD),
                                      (T_WIN + nib * TQ - 0.2e-9, VDD),
                                      (T_WIN + nib * TQ - 0.1e-9, 0.0)]
    tb.PieceWiseLinearVoltageSource(name="xp", positive="xin_p_r0", negative="0",
                                    values=[(0, 0.0)] if neg else env)
    tb.PieceWiseLinearVoltageSource(name="xn", positive="xin_n_r0", negative="0",
                                    values=env if neg else [(0, 0.0)])
    tb.options(reltol=1e-3, abstol=1e-11, vntol=1e-5, method="gear")   # AnalogIOC TIGHT
    tb.save(*(f"V({x})" for x in SIGS), "I(Vsupc)", "I(Vsupp)")
    return tb


def edges(t, v, rising=True, level=VDD / 2):
    return [t[i] for i in range(1, len(t))
            if ((v[i - 1] < level <= v[i]) if rising else (v[i - 1] > level >= v[i]))]


def _key(mac, seed):
    """Cache key: backend/DUT/corner/temp/point plus a hash of what the simulation sees:
    the converter deck, conv_seq's part of the async_ctrl deck (tile_seq edits don't
    invalidate converter points), the rail stand-in and the fixture code."""
    h = hashlib.sha1()
    ac_deck = dut_path("async_ctrl", "sch").read_text()
    h.update(dut_path("integrator_conv").read_bytes())
    h.update(ac_deck[ac_deck.index(".subckt dly_pace"):ac_deck.index(".ends conv_seq")].encode())
    h.update((rtl_standin.HERE / "rtl_standin.va").read_bytes())
    for f in (pulses, bench, run_point, _common, _tile):
        h.update(inspect.getsource(f).encode())
    h.update(repr((D, T_RST, K_WIN, REFS, SIGS)).encode())
    return "_".join([os.environ.get("SPICERACK_BACKEND", "ngspice"), dut_kind(),
                     os.environ.get("CORNER", PDK.typical),
                     os.environ.get("SIM_TEMP", "27"), f"m{mac}", f"s{seed}",
                     h.hexdigest()[:10]])


def run_point(w, nib, neg, seed=None, corner=""):
    """{mac, code, count, fine, n_dec, e_coarse_pJ, e_fine_pJ, exp...}; cached."""
    mac = -w * nib if neg else w * nib
    cache = OUT / "points" / f"{_key(mac, seed)}{'_' + corner if corner else ''}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    exp = {k: int(v[0]) for k, v in eventrate_convert([mac], D).items()}
    end = T_SGO + (exp["coarse"] + 2) * 220e-9 + 1.3e-6
    d = bench(w, nib, neg, end, corner=corner, seed=seed).transient(step_time=0.5e-9,
                                                                    end_time=end)
    t = [float(x) for x in d.time]
    v = {x: [float(y) for y in d[x]] for x in SIGS}
    reqs = edges(t, v["cb_req"])

    def at(x, tt):
        k = min(range(len(t)), key=lambda i: abs(t[i] - tt))
        return v[x][k] > VDD / 2
    count = int(sum(at("cb_cross", x + 0.2e-9) for x in reqs))
    acks_f = edges(t, v["cmp_ack"], rising=False)
    done = len(acks_f) == 4
    fine = int(sum((1 << k) * at(f"b{k}", t[-1]) for k in range(4)))
    sgn = -1 if at("col_sign", t[-1]) else 1
    mag = 16 * count + fine
    code = sgn * min(mag, 127) if mag else 0
    t_f0 = (edges(t, v["cmp_req"]) or [t[-1]])[0]
    t_f1 = (acks_f[-1] + 5e-9) if done else t[-1]
    i_tot = [float(a + b) for a, b in zip(_cur(d, "vsupc"), _cur(d, "vsupp"))]

    def energy(a, b):
        e = 0.0
        for i in range(1, len(t)):
            if a <= t[i] <= b:
                e += -(i_tot[i] + i_tot[i - 1]) / 2 * (t[i] - t[i - 1]) * VDD
        return e * 1e12
    res = {"mac": mac, "code": code, "count": count, "fine": fine, "sign": sgn,
           "n_dec": len(reqs), "fine_done": done, "exp_code": exp["code"],
           "exp_count": exp["coarse"], "exp_fine": exp["fine"], "exp_n_eval": exp["n_eval"],
           "e_coarse_pJ": round(energy(T_SGO, t_f0), 4), "e_fine_pJ": round(energy(t_f0, t_f1), 4),
           "t_conv_ns": round((t_f1 - T_SGO) * 1e9, 1)}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(res))
    return res


def _cur(d, src):
    for k in (f"i({src})", f"{src}#branch"):
        try:
            return list(d[k])
        except (KeyError, IndexError, Exception):
            continue
    raise KeyError(src)
