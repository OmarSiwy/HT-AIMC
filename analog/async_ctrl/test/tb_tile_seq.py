"""tile_seq: integrate sequencer, chop ring, envelopes, sidecar phases vs INTERFACE.md
§6.1 / §6.2 (timing table I0..I8).

tile_seq (transistor level) with Verilog-A stand-ins around it (seq_drv.va): a rail stand-in that raises integ_req
(4-phase, n_pass passes back to back) and 17 column stand-ins whose sdone_j follows sgo
after 2 + 0.3 j ns. Static x_mag / x_neg / win_hi / lora_en; output nets loaded with the
macro's gate load. Runs:
  LO    win_hi 0, lora_en 0, m_i = i, x_neg_i = i odd, two passes
  HI    win_hi 1, lora_en 0, m_i = i mod 8, one pass
  LORA  win_hi 0, lora_en 1, m_i = 15 - i, one pass
  then a late busy pulse on column 3 restarts the stopped ring.
Checks (rows):
  I0  before integ_req: rst 1, tile chop parked, envelopes / ramp_en / sgo / integ_ack 0,
      ring stopped
  I1  second pass: rst high >= 20 ns from integ_req; sgo cleared
  I2  rst fall -> window >= 1 ns
  I3  N tile cycles (16 LO / 8 HI), Tc = t_q / 16 t_q; row i: m_i cycles on the right
      line, xrd_en = envelope & lora_en; envelope edges inside the all-off gap
  I4  tile chop parked <= 0.8 ns after the last cycle end (spec 0.4, reported)
  I5  sgo 8 t_q after the window; LoRA: ramp_en 4 t_q after, 50 t_q wide
      (>= 250 ns), sgo 10 t_q after it
  I7  integ_ack >= T_BUNDLE after the last sdone;  I8 integ_ack falls after integ_req
  6.1 chop offsets from the gap start 0.8 / 2.4 / 2.6 / 3.0 ns +-0.1 (tt 27 C only;
      every corner: phases never overlap); converter chop period t_q +-30 % (tt)
  ring stops when idle, restarts on busy
DUT=va: no golden model of tile_seq — skipped.
"""
import hashlib
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

A = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(A / "docs"), str(A / "common"), str(A / "async_ctrl" / "netlist"),
                str(Path(__file__).resolve().parent)]
import async_ctrl as ac  # noqa: E402
import rtl_standin as rs  # noqa: E402
import specs  # noqa: E402
from bench import Report, dut_kind, dut_path  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402

import spicerack as ps  # noqa: E402

PDK = get_pdk()
VDD, VTH = PDK.vdd, PDK.vdd / 2
TQ = specs.TQ_SIM
R, NC = specs.N_ROWS, specs.N_COLS
T_RST_N = 10e-9         # seq_rst_n released (power-up reset)
T_REQ = 20e-9
C_GATE = 2e-15          # per driven gate input
RUNS = {k: v for k, v in {"LO": dict(hi=0, lora=0, mag=lambda i: i, n_pass=2, end=1.25e-6),
        "HI": dict(hi=1, lora=0, mag=lambda i: i % 8, n_pass=1, end=1.9e-6),
        "LORA": dict(hi=0, lora=1, mag=lambda i: 15 - i, n_pass=1, end=1.3e-6)}.items()
        if k in os.environ.get("TILE_RUNS", "LO,HI,LORA").split(",")}
NOMINAL = os.environ.get("CORNER", PDK.typical) == PDK.typical and \
    float(os.environ.get("SIM_TEMP", 27)) == 27


def run(hi, lora, mag, n_pass, end, corner="", temp=None):
    """(t, {net: v}), cached under output/tb by deck hash + backend/corner/temp/run."""
    key = hashlib.sha1((dut_path("async_ctrl", "sch").read_text() + Path(__file__).read_text()
                        + (A / "async_ctrl" / "test" / "seq_drv.va").read_text()).encode())
    tag = "_".join([os.environ.get("SPICERACK_BACKEND", "ngspice"),
                    corner or os.environ.get("CORNER", PDK.typical),
                    str(temp if temp is not None else os.environ.get("SIM_TEMP", 27)),
                    f"hi{hi}_lora{lora}_n{n_pass}", key.hexdigest()[:10]])
    cache = A / "async_ctrl" / "output" / "tb" / f"tile_seq_{tag}.json"
    if cache.exists():
        got = json.loads(cache.read_text())
        return got["t"], got["w"]
    t, w = _run(hi, lora, mag, n_pass, end, corner, temp)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"t": t, "w": w}))
    return t, w


def _run(hi, lora, mag, n_pass, end, corner="", temp=None):
    top = ps.Subcircuit("tb_tile_seq")
    top.include(str(dut_path("async_ctrl", "sch")))
    top.X("xdut", "tile_seq", *ac.tile_seq_ports())
    rs.seq_drv(top, n_pass, T_REQ, NC)
    tb = ps.Testbench(top)
    tb.use_pdk(PDK.model_library(corner or os.environ.get("CORNER", "")))
    tb.temperature = float(temp if temp is not None else os.environ.get("SIM_TEMP", 27))
    tb.V(name="sup", positive="vdd", negative="0", value=VDD)
    tb.V(name="ss", positive="vss", negative="0", value=0.0)
    tb.PieceWiseLinearVoltageSource(name="rstn", positive="seq_rst_n", negative="0",
                                    values=[(0, 0.0), (T_RST_N, 0.0), (T_RST_N + 0.1e-9, VDD)])
    tb.V(name="hi", positive="win_hi", negative="0", value=VDD * hi)
    tb.V(name="lora", positive="lora_en", negative="0", value=VDD * lora)
    for i in range(R):
        for k in range(4):
            tb.V(name=f"m{i}_{k}", positive=f"x_mag{4 * i + k}", negative="0",
                 value=VDD * ((mag(i) >> k) & 1))
        tb.V(name=f"ng{i}", positive=f"x_neg{i}", negative="0", value=VDD * (i % 2))
    t_b = end - 250e-9
    for j in range(NC):
        vals = [(0, 0.0)] if j != 3 else [(0, 0.0), (t_b, 0.0), (t_b + 0.1e-9, VDD),
                                          (t_b + 100e-9, VDD), (t_b + 100.1e-9, 0.0)]
        tb.PieceWiseLinearVoltageSource(name=f"bz{j}", positive=f"busy{j}", negative="0",
                                        values=vals)
    loads = {"phi1": 3 * NC, "phi1e": NC, "phi2": 2 * NC, "tphi1": 3 * R + 2,
             "tphi1e": 2 * R, "tphi2": 2, "rst": 2 * NC + 4, "sgo": 2 * NC, "ramp_en": R}
    loads.update({f"xin_{p}_r{i}": 2 for i in range(R) for p in "pn"})
    for net, n in loads.items():
        tb.C(name=f"l_{net}", positive=net, negative="0", value=n * C_GATE)
    sigs = (["integ_req", "integ_ack", "rst", "sgo", "phi1", "phi1e", "phi2", "tphi1",
             "tphi1e", "tphi2", "ramp_en", "sdone16", "busy3", "xxdut.adc_done",
             "xxdut.sg", "xxdut.s1", "xxdut.w2", "xxdut.p_tile"]
            + [f"xin_{p}_r{i}" for i in range(R) for p in "pn"]
            + [f"xrd_en{i}" for i in range(R)])
    tb.save(*(f"V({x})" for x in sigs))
    d = tb.transient(step_time=0.2e-9, end_time=end)
    return [float(x) for x in d.time], {x: [float(y) for y in d[x]] for x in sigs}


def edges(t, v, rising=True):
    out = []
    for i in range(1, len(t)):
        a, b = v[i - 1], v[i]
        if (a < VTH <= b) if rising else (a > VTH >= b):
            out.append(t[i - 1] + (VTH - a) / (b - a) * (t[i] - t[i - 1]))
    return out


def level(t, v, x):
    k = min(range(len(t)), key=lambda i: abs(t[i] - x))
    return v[k] > VTH


def offsets(t, w, p1, p1e, p2, t_from, t_to):
    """Per cycle (from each p2 fall): (p1 rise, p1 fall, p1e fall, p2 rise) offsets."""
    E = {k: edges(t, w[k]) for k in (p1, p2)}
    F = {k: edges(t, w[k], False) for k in (p1, p1e, p2)}
    rows = []
    for g in [x for x in F[p2] if t_from <= x <= t_to]:
        nxt = lambda lst: min([x for x in lst if x > g], default=None)   # noqa: E731
        o = [nxt(E[p1]), nxt(F[p1]), nxt(F[p1e]), nxt(E[p2])]
        if None not in o and o[3] - g < 5e-9:
            rows.append([x - g for x in o])
    return rows


def check(r, tag, cfg, t, w):
    hi, lora, mag, n_pass = cfg["hi"], cfg["lora"], cfg["mag"], cfg["n_pass"]
    E = {k: edges(t, v) for k, v in w.items()}
    F = {k: edges(t, v, False) for k, v in w.items()}
    req0 = E["integ_req"][0]
    # I0
    idle = req0 - 1e-9
    bad = [k for k in ("sgo", "integ_ack", "ramp_en", "tphi2") + tuple(
        f"xin_{p}_r{i}" for i in range(R) for p in "pn") if level(t, w[k], idle)]
    bad += [k for k in ("rst", "tphi1", "tphi1e") if not level(t, w[k], idle)]
    bad += ["phi1 toggling"] if any(x < req0 for x in E["phi1"]) else []
    r.check(f"{tag} I0: idle state", not bad, f"wrong: {bad}" if bad else "")
    # window = tile cycles between the first tphi2 rise after the rst fall and the park
    rst_f = [x for x in F["rst"] if x > req0][0]
    win0 = [x for x in E["tphi2"] if x > rst_f][0]
    r.check(f"{tag} I2: rst fall -> window >= 1 ns", win0 - rst_f >= 1e-9,
            f"{(win0 - rst_f) * 1e9:.1f} ns")
    park = [x for x in E["tphi1"] if x > win0 and not level(t, w["tphi2"], x + 0.3e-9)
            and level(t, w["tphi1"], x + 3e-9) and all(not (x < y < x + 3e-9) for y in F["tphi1"])]
    cyc = [x for x in E["tphi2"] if win0 - 1e-12 <= x]
    last_end = [x for x in F["tphi2"] if x > win0]
    n_want = ac.N_HI if hi else ac.N_LO
    n_cyc = [x for x in cyc if x < (park[0] if park else t[-1])]
    tc = (n_cyc[-1] - n_cyc[0]) / (len(n_cyc) - 1) if len(n_cyc) > 1 else 0
    r.check(f"{tag} I3: {n_want} tile cycles", len(n_cyc) == n_want,
            f"{len(n_cyc)}, Tc {tc * 1e9:.2f} ns = {tc / TQ:.2f} t_q")
    wend = last_end[len(n_cyc) - 1] if len(last_end) >= len(n_cyc) else t[-1]
    pk = (park[0] - wend) if park else 1
    r.check(f"{tag} I4: tile chop parked <= 0.8 ns after the last cycle", pk <= 0.8e-9,
            f"{pk * 1e9:.2f} ns (spec 0.4)")
    wrong = []
    for i in range(R):
        on, off = (f"xin_n_r{i}", f"xin_p_r{i}") if i % 2 else (f"xin_p_r{i}", f"xin_n_r{i}")
        k = sum(level(t, w[on], x + 1e-9) for x in n_cyc)
        if k != mag(i) or E[off] or (sum(level(t, w[f"xrd_en{i}"], x + 1e-9) for x in n_cyc)
                                     != (mag(i) if lora else 0)):
            wrong.append((i, k))
    r.check(f"{tag} I3: row i high for m_i cycles on its line (+ xrd_en)", not wrong,
            f"bad rows {wrong}" if wrong else f"m = {[mag(i) for i in range(R)]}")
    gaps = [(f2, min([x for x in E["tphi1"] if x > f2], default=f2 + 1)) for f2 in F["tphi2"]]
    env_e = [x for i in range(R) for p in "pn" for x in E[f"xin_{p}_r{i}"] + F[f"xin_{p}_r{i}"]]
    out_gap = [x for x in env_e if not any(a < x < b for a, b in gaps)]
    def rel(x):
        f2 = max([g for g, _ in gaps if g <= x], default=None)
        return "?" if f2 is None else f"{(x - f2) * 1e9:+.2f}"
    r.check(f"{tag} I3: envelope edges inside the all-off gap", not out_gap,
            (f"{len(out_gap)} of {len(env_e)} outside, ns after tphi2 fall: "
             + " ".join(rel(x) for x in sorted(out_gap)[:8])) if out_gap
            else f"{len(env_e)} edges")
    # I5 (in ticks of the measured ring t_q)
    per = [b - a for a, b in zip(E["phi1"], E["phi1"][1:]) if b - a < 2 * TQ]
    tqm = sum(per) / len(per)
    sgo_r = [x for x in E["sgo"] if x > req0][0]
    if lora:
        ru, rd = E["ramp_en"][0], F["ramp_en"][0]
        r.check(f"{tag} I5a: ramp_en 4 t_q after the window, 50 t_q >= 250 ns, settle 10 t_q",
                abs((ru - wend) / tqm - ac.N_RAMP0) < 1.5 and abs((rd - ru) / tqm - ac.N_RAMPW) < 1.5
                and rd - ru >= 250e-9 and abs((sgo_r - rd) / tqm - ac.N_SETTLE_L) < 1.5,
                f"{(ru - wend) / tqm:.2f} / {(rd - ru) / tqm:.2f} ({(rd - ru) * 1e9:.0f} ns) / "
                f"{(sgo_r - rd) / tqm:.2f} t_q of {tqm * 1e9:.2f} ns")
    else:
        r.check(f"{tag} I5b: sgo 8 t_q after the window", abs((sgo_r - wend) / tqm - ac.N_SETTLE) < 1.5,
                f"{(sgo_r - wend) / tqm:.2f} t_q of {tqm * 1e9:.2f} ns")
    # I7 / I8
    acks, req_f, ack_f = E["integ_ack"], F["integ_req"], F["integ_ack"]
    sd = [x for x in E["sdone16"] if x < acks[0]][-1]
    r.check(f"{tag} I7: integ_ack >= T_BUNDLE after the last sdone", acks[0] - sd >= ac.T_BUNDLE,
            f"{(acks[0] - sd) * 1e9:.2f} ns")
    r.check(f"{tag} I8: integ_ack falls after integ_req", len(ack_f) == n_pass
            and all(a > q for a, q in zip(ack_f, req_f)), f"{len(acks)} handshakes")
    if n_pass > 1:
        req1 = E["integ_req"][1]
        rst_hi = [x for x in F["rst"] if x > req1][0] - req1
        sgo_c = [x for x in F["sgo"] if x > req1][0] - req1
        r.check(f"{tag} I1: second pass rst >= 20 ns, sgo cleared",
                rst_hi >= 20e-9 and sgo_c < 5e-9,
                f"rst {rst_hi * 1e9:.1f} ns, sgo low {sgo_c * 1e9:.2f} ns after integ_req")
    # §6.1 chop offsets
    want = [0.8e-9, 2.4e-9, 2.6e-9, 3.0e-9]
    for name, ph in (("converter", ("phi1", "phi1e", "phi2")), ("tile", ("tphi1", "tphi1e", "tphi2"))):
        rows = offsets(t, w, *ph, win0, wend - 1e-9)
        if not rows:
            r.check(f"{tag} 6.1 {name} chop offsets measured", False)
            continue
        worst = max(abs(x - y) for row in rows for x, y in zip(row, want))
        overlap = all(row[0] > 0 and row[2] < row[3] for row in rows)
        mean = [sum(c) / len(c) * 1e9 for c in zip(*rows)]
        detail = " / ".join(f"{m:.2f}" for m in mean) + f" ns, worst dev {worst * 1e12:.0f} ps"
        if NOMINAL:
            r.check(f"{tag} 6.1 {name} chop offsets 0.8/2.4/2.6/3.0 +-0.1 ns", worst <= 0.1e-9, detail)
        r.check(f"{tag} 6.1 {name} phases never overlap", overlap, detail)
    per = [b - a for a, b in zip(E["phi1"], E["phi1"][1:]) if b - a < 2 * TQ]
    tq = sum(per) / len(per)
    if NOMINAL:
        r.check(f"{tag} ring t_q within +-30 %", abs(tq / TQ - 1) < 0.3,
                f"{tq * 1e9:.2f} ns, cycle {min(per) * 1e9:.2f}..{max(per) * 1e9:.2f}")
    else:
        print(f"  info  ring t_q {tq * 1e9:.2f} ns ({min(per) * 1e9:.2f}..{max(per) * 1e9:.2f})")
    busy = E["busy3"][0]
    stopped = not any(ack_f[-1] + 8 * TQ < x < busy for x in E["phi1"])
    restarted = any(busy < x < busy + 50e-9 for x in E["phi1"])
    r.check(f"{tag} ring stops when idle, restarts on busy", stopped and restarted)


def main():
    r = Report("tile_seq")
    if dut_kind() == "va":
        print("  SKIP  no Verilog-A model of tile_seq (macro behaviour: analogioc_beh.v)")
        r.done()
    with ThreadPoolExecutor(len(RUNS)) as ex:
        res = {k: ex.submit(run, **v) for k, v in RUNS.items()}
        for k, cfg in RUNS.items():
            t, w = res[k].result()
            print(f"  {k} timeline: " + "  ".join(
                f"{n.split('.')[-1]} " + ",".join(f"{x * 1e9:.1f}" for x in edges(t, w[n])[:3])
                for n in ("integ_req", "xxdut.s1", "xxdut.w2", "xxdut.sg", "sgo", "sdone16",
                          "xxdut.adc_done", "integ_ack")))
            try:
                check(r, k, cfg, t, w)
            except (IndexError, ValueError, ZeroDivisionError) as e:
                r.check(f"{k} remaining checks (missing edges)", False, repr(e))
    r.done()


if __name__ == "__main__":
    main()
