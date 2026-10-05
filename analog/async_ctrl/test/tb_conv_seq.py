"""conv_seq: the per-column handshake translator against INTERFACE.md §6.2 I6, §6.3, §6.4.

conv_seq (transistor level, netlist/async_ctrl.spice) between Verilog-A stand-ins: two
dual-rail comparators (rtl_standin.sa1/sa2) on its strobes and the tile_fsm side
(rtl_standin.rtl). The converter chop is ideal PWL on the §6.1 grid. Two conversions:
  A: sign +, 2 crossings, pkt_d = 1, fine 10      B: sign +, 1 crossing, pkt_d = 3, fine 5
Checks (contract rows):
  I0     before sgo every output is 0
  I6     sign strobe rises inside phi1 (chop offset), sign/sgd/sdone/col_sign after it
  C0     pacing: cb_ack fall -> next clk_c rise >= T_PACE (2 T_CLK_MAX)
  C2     cb_cross settled >= T_BUNDLE before cb_req rises, held until cb_ack falls;
         decisions = crossings + 1, pattern 1..1 0
  C3     fire = pkt_d chop cycles per crossing, every fire edge in the all-off gap;
         run falls at the no-cross cb_ack
  C4     cb_req falls only after the packet
  F1-F5  acq first >= T_ACQ1, later >= T_ACQ; acq fall -> clk_f rise >= T_HOLD; clk_f
         10-90 % edges >= T_FEDGE, high >= T_FHI; cmp_result settled >= T_BUNDLE before
         cmp_ack rises; cmp_ack falls after cmp_req; awake = ota_en | acq; fine code
DUT=va: no golden model of conv_seq (the contract's behavioural model is the macro's
analogioc_beh.v) — skipped.
"""
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
VDD = PDK.vdd
VTH = VDD / 2
TQ = specs.TQ_SIM
T_START = 5e-9
T_SGO = 50e-9
EDGE = 0.1e-9
# §6.1 converter chop, cycle t0 = T_START + k*TQ
PHI1 = (0.3e-9, 1.9e-9)
PHI2 = (2.5e-9, TQ - 0.5e-9)
GAP = (-0.5e-9, 0.3e-9)          # around each t0
CASES = {"A": (2, 1, 10), "B": (1, 3, 5)}      # n_cross, pkt_d, fine
SIGS = ["phi1", "phi2", "sgo", "clk_c", "c1p", "c1n", "sgd", "sdone", "sign", "col_sign",
        "coarse_en", "cb_req", "cb_cross", "cb_ack", "fire", "run", "cmp_req", "acq",
        "clk_f", "c2p", "c2n", "cmp_result", "cmp_ack", "ota_en", "awake", "busy",
        "b3", "b2", "b1", "b0", "rtl_done"]


def chop_pwl(on, off, end):
    pts, t0 = [(0, 0.0)], T_START
    while t0 + on < end:
        pts += [(t0 + on, 0.0), (t0 + on + EDGE, VDD), (t0 + off, VDD), (t0 + off + EDGE, 0.0)]
        t0 += TQ
    return pts


def run(n_cross, pkt_d, fine, end=2.0e-6, corner="", temp=None):
    top = ps.Subcircuit("tb_conv_seq")
    top.include(str(dut_path("async_ctrl", "sch")))
    top.X("xdut", "conv_seq", *ac.CONV_SEQ_PORTS)
    rs.rtl(top)
    rs.sa1(top, n_cross)
    rs.sa2(top, fine)
    tb = ps.Testbench(top)
    tb.use_pdk(PDK.model_library(corner or os.environ.get("CORNER", "")))
    tb.temperature = float(temp if temp is not None else os.environ.get("SIM_TEMP", 27))
    tb.V(name="sup", positive="vdd", negative="0", value=VDD)
    tb.V(name="ss", positive="vss", negative="0", value=0.0)
    tb.V(name="rst", positive="rst_n", negative="0", value=VDD)
    for b in range(3):
        tb.V(name=f"pd{b}", positive=f"pkt_d{b}", negative="0",
             value=VDD if (pkt_d >> b) & 1 else 0.0)
    tb.PieceWiseLinearVoltageSource(name="sgo", positive="sgo", negative="0",
                                    values=[(0, 0.0), (T_SGO, 0.0), (T_SGO + EDGE, VDD)])
    tb.PieceWiseLinearVoltageSource(name="phi1", positive="phi1", negative="0",
                                    values=chop_pwl(*PHI1, end))
    tb.PieceWiseLinearVoltageSource(name="phi2", positive="phi2", negative="0",
                                    values=chop_pwl(*PHI2, end))
    tb.save(*(f"V({x})" for x in SIGS))
    d = tb.transient(step_time=0.2e-9, end_time=end)
    return d.time, {x: d[x] for x in SIGS}


def edges(t, v, rising=True, level=VTH):
    out = []
    for i in range(1, len(t)):
        a, b = v[i - 1], v[i]
        if (a < level <= b) if rising else (a > level >= b):
            out.append(t[i - 1] + (level - a) / (b - a) * (t[i] - t[i - 1]))
    return out


def at(t, v, x):
    k = min(range(len(t)), key=lambda i: abs(t[i] - x))
    return v[k] > VTH


def in_gap(x):
    k = round((x - T_START) / TQ)
    t0 = T_START + k * TQ
    return t0 + GAP[0] - 0.05e-9 <= x <= t0 + GAP[1] + 0.05e-9


def check(r, tag, n_cross, pkt_d, fine, t, w):
    E = {k: edges(t, w[k]) for k in w}
    F = {k: edges(t, w[k], rising=False) for k in w}
    outs = ["clk_c", "sgd", "sdone", "col_sign", "cb_req", "cb_cross", "cmp_ack",
            "cmp_result", "run", "fire", "acq", "clk_f"]
    pre = [k for k in outs if any(T_START < x < T_SGO for x in E[k]) or at(t, w[k], T_SGO - 1e-9)]
    r.check(f"{tag} I0: outputs 0 before sgo", not pre, f"high: {pre}" if pre else "")
    # I6 sign strobe
    s0 = E["clk_c"][0]
    p1 = max(x for x in E["phi1"] if x <= s0 + 1e-12)
    r.check(f"{tag} I6: sign strobe inside phi1", s0 - p1 < PHI1[1] - PHI1[0],
            f"clk_c - phi1 rise {(s0 - p1) * 1e9:.2f} ns")
    sgd = E["sgd"][0]
    r.check(f"{tag} I6: sign 1, col_sign 0, sdone with sgd",
            at(t, w["sign"], sgd + 1e-9) and not at(t, w["col_sign"], sgd + 2e-9)
            and abs(E["sdone"][0] - sgd) < 0.5e-9,
            f"sign strobe {s0 * 1e9:.1f} ns -> sgd {(sgd - s0) * 1e9:.2f} ns later")
    # coarse decisions
    reqs, acks_f = E["cb_req"], F["cb_ack"]
    pattern = [int(at(t, w["cb_cross"], x)) for x in reqs]
    r.check(f"{tag} C2: decisions = crossings + 1, pattern", pattern == [1] * n_cross + [0],
            f"{pattern}")
    setup = min(x - max([c for c in E["cb_cross"] + F["cb_cross"] if c < x], default=0)
                for x in reqs)
    r.check(f"{tag} C2: cb_cross settled >= T_BUNDLE before cb_req", setup >= ac.T_BUNDLE,
            f"min {setup * 1e9:.2f} ns")
    held = all(not any(rq < c < af for c in E["cb_cross"] + F["cb_cross"])
               for rq, af in zip(reqs, acks_f))
    r.check(f"{tag} C2: cb_cross held until cb_ack falls", held)
    strobes = [x for x in E["clk_c"] if x > s0 + 1e-9]
    pace = [min([s for s in strobes if s > af], default=1) - af for af in acks_f]
    pace = [p for p in pace if p < 1]
    r.check(f"{tag} C0: pacing >= T_PACE", all(p >= ac.T_PACE for p in pace),
            f"min {min(pace) * 1e9:.1f} ns" if pace else "single decision")
    fw = [(a, b) for a, b in zip(E["fire"], F["fire"])]
    r.check(f"{tag} C3: one packet per crossing", len(fw) == n_cross, f"{len(fw)} packets")
    widths = [round((b - a) / TQ, 2) for a, b in fw]
    r.check(f"{tag} C3: packet = pkt_d chop cycles", all(abs(x - pkt_d) < 0.1 for x in widths),
            f"{widths} cycles")
    r.check(f"{tag} C3: fire edges in the gap", all(in_gap(x) for e in fw for x in e),
            " ".join(f"{(x - T_START) % TQ * 1e9:.2f}" for e in fw for x in e) + " ns into cycle")
    req_f = F["cb_req"]
    r.check(f"{tag} C4: cb_req falls after its packet",
            all(any(rf > b for rf in req_f if rf > a) for a, b in fw))
    last_ack = E["cb_ack"][-1]
    run_f = F["run"]
    r.check(f"{tag} C3: run on from the first coarse strobe, off at the no-cross ack",
            run_f and abs(run_f[-1] - last_ack) < 3e-9 and E["run"][0] < reqs[0],
            f"run fall {(run_f[-1] - last_ack) * 1e9:.2f} ns after cb_ack" if run_f else "never")
    # fine
    acq = list(zip(E["acq"], F["acq"]))
    aw = [b - a for a, b in acq]
    r.check(f"{tag} F1: 4 trials, acq first >= T_ACQ1, later >= T_ACQ",
            len(aw) == 4 and aw[0] >= ac.T_ACQ1 and min(aw[1:]) >= ac.T_ACQ,
            " ".join(f"{x * 1e9:.1f}" for x in aw) + " ns")
    hold = [min(c for c in E["clk_f"] if c > b) - b for a, b in acq]
    r.check(f"{tag} F2: acq fall -> clk_f >= T_HOLD", min(hold) >= ac.T_HOLD,
            f"min {min(hold) * 1e9:.1f} ns")
    r10 = edges(t, w["clk_f"], True, 0.1 * VDD)
    r90 = edges(t, w["clk_f"], True, 0.9 * VDD)
    f90 = edges(t, w["clk_f"], False, 0.9 * VDD)
    f10 = edges(t, w["clk_f"], False, 0.1 * VDD)
    ed = [b - a for a, b in zip(r10, r90)] + [b - a for a, b in zip(f90, f10)]
    r.check(f"{tag} F3: clk_f 10-90 % edges >= T_FEDGE", len(ed) == 8 and min(ed) >= ac.T_FEDGE,
            f"{len(ed)} edges, min {min(ed, default=0) * 1e9:.2f} ns")
    hi = [b - a for a, b in zip(E["clk_f"], F["clk_f"])]
    r.check(f"{tag} F3: clk_f high >= T_FHI", len(hi) == 4 and min(hi) >= ac.T_FHI,
            f"min {min(hi, default=0) * 1e9:.2f} ns")
    res_ch = E["cmp_result"] + F["cmp_result"]
    st = min(x - max([c for c in res_ch if c < x], default=0) for x in E["cmp_ack"])
    r.check(f"{tag} F4: cmp_result settled >= T_BUNDLE before cmp_ack", st >= ac.T_BUNDLE,
            f"min {st * 1e9:.2f} ns")
    r.check(f"{tag} F5: cmp_ack falls after cmp_req",
            all(any(a > q for q in F["cmp_req"]) for a in F["cmp_ack"]) and len(F["cmp_ack"]) == 4)
    code = sum((1 << k) * at(t, w[f"b{k}"], t[-1]) for k in range(4))
    r.check(f"{tag} fine code", code == fine, f"{code} (want {fine})")
    bad = [x for x in t[::50] if at(t, w["awake"], x) != (at(t, w["ota_en"], x) or at(t, w["acq"], x))
           and not any(abs(x - e) < 1e-9 for e in E["acq"] + F["acq"] + E["ota_en"] + F["ota_en"])]
    r.check(f"{tag} awake = ota_en | acq", not bad)


def main():
    r = Report("conv_seq")
    if dut_kind() == "va":
        print("  SKIP  no Verilog-A model of conv_seq (macro behaviour: analogioc_beh.v)")
        r.done()
    with ThreadPoolExecutor(len(CASES)) as ex:
        res = {k: ex.submit(run, *v) for k, v in CASES.items()}
        for k, (n_cross, pkt_d, fine) in CASES.items():
            check(r, k, n_cross, pkt_d, fine, *res[k].result())
    r.done()


if __name__ == "__main__":
    main()
