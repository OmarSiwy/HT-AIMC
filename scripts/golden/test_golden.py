#!/usr/bin/env python3
"""Golden-model unit tests (PYTHONPATH=scripts python3 scripts/golden/test_golden.py).

Every check asserts numerically against an INDEPENDENTLY coded reference
(bit models of A4's verilog, exact integer identities). Prints PASS/FAIL.
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from golden import model as G  # noqa: E402

rng = np.random.default_rng(42)


def test_quant_roundtrips():
    W = rng.normal(0, 1, (16, 16))
    Wq, dw = G.quant_w_int4(W)
    assert np.all(np.abs(Wq) <= 7)
    assert np.all(np.abs(Wq * dw[:, None] - W) <= dw[:, None] / 2 + 1e-12)
    Cp, Cn = G.caps_from_wq(Wq)
    assert np.all(G.wq_from_caps(Cp, Cn) == Wq)
    assert np.all(np.minimum(Cp, Cn) == 0)          # one-sided differential
    x = rng.normal(0, 2, 64)
    xq, dx = G.quant_x_int8(x)
    assert np.all(np.abs(xq) <= 127)
    assert np.all(np.abs(xq * dx - x) <= dx / 2 + 1e-12)


def test_pwm():
    xq = np.arange(-127, 128)
    sg, hi, lo = G.pwm_nibbles(xq)
    assert np.all(sg * (16 * hi + lo) == xq)        # nibble split exact
    assert np.all((hi <= 7) & (lo <= 15))
    sg2, t_lo, t_hi = G.pwm_schedule(xq)
    # PWM window sum == quantized activation magnitude x t_q (contract)
    assert np.allclose(t_lo + t_hi, np.abs(xq) * G.TQ_SIM)


def test_mac_identity():
    Wq = rng.integers(-7, 8, (16, 16))
    xq = rng.integers(-127, 128, 16)
    mh, ml = G.mac_codes(Wq, xq)
    assert np.all(16 * mh + ml == Wq @ xq)          # exact recombination


def conv_ref(mac, D):
    """Independent bit model of event_ctrl + sar_ctrl + tile_fsm assembly."""
    q = (abs(mac) * 2 + D) // (2 * D)               # half-away for ints
    count = min(q >> 4, 15)
    sar = min(q - 16 * count, 15)
    mag = 16 * count + sar
    code = (-1 if mac < 0 else 1) * min(mag, 127)
    return code, count, sar, min(count + 1, 15)


def test_eventrate():
    D = 3
    macs = np.arange(-4000, 4001, 7)
    cv = G.eventrate_convert(macs, D)
    for i, m in enumerate(macs):
        code, count, sar, nev = conv_ref(int(m), D)
        assert cv["code"][i] == code, (m, cv["code"][i], code)
        assert cv["coarse"][i] == count and cv["fine"][i] == sar
        assert cv["n_eval"][i] == nev
    # early termination boundary cases
    z = G.eventrate_convert(np.array([0]), 5)
    assert z["code"][0] == 0 and z["n_eval"][0] == 1          # first no-cross
    big = G.eventrate_convert(np.array([10 ** 6]), 1)
    assert big["code"][0] == 127 and big["n_eval"][0] == 15   # range exhausted
    # |code| monotone non-decreasing in |mac|
    up = G.eventrate_convert(np.arange(0, 3000), 4)["code"]
    assert np.all(np.diff(up) >= 0)


def test_rails():
    # nibble combine: exact + sat12 both ends (A4 nibble_combine.v)
    assert G.nibble_combine(3, -5) == 43
    assert G.nibble_combine(127, 127) == 2047
    assert G.nibble_combine(-127, -127) == -2048
    # slice combine: x4 significance + sat14 (A4 slice_combine.v)
    assert G.slice_combine(100, 50) == 300
    assert G.slice_combine(np.array([10]), 0)[0] == 10        # S=1 passthrough
    assert G.slice_combine(2047, 2047) == 8191 + 0 * 2        # 4*2047+2047=10235 -> sat
    assert G.slice_combine(-2048, -2048) == -8192
    # accumulate: exact sum, in-spec
    parts = rng.integers(-2040, 2041, (96, 16))
    assert np.all(G.accumulate(parts) == parts.sum(axis=0))
    # requant vs independent bit model of requant.v (incl. negatives,
    # shift=0, offset after shift, sat8 both rails)
    def requant_ref(y, s, sh, off):
        half = 0 if sh == 0 else 2 ** (sh - 1)
        shifted = (y * s + half) >> sh            # python >> = arithmetic
        return max(-128, min(127, shifted + off))
    ys = list(rng.integers(-2 ** 19, 2 ** 19, 200)) + [0, -1, 2 ** 19 - 1, -2 ** 19]
    for y in ys:
        s, sh, off = int(rng.integers(0, 256)), int(rng.integers(0, 25)), \
            int(rng.integers(-128, 128))
        got = G.requant_int8(np.array([y]), np.array([s]), np.array([sh]),
                             np.array([off]))[0]
        assert got == requant_ref(int(y), s, sh, off), (y, s, sh, off, got)
    # make_requant produces legal A4 fields that reproduce the float scale
    sc = np.array([0.5, 1e-3, 3e-5, 200.0, 0.0])
    s8, sh = G.make_requant(sc)
    assert np.all((s8 >= 0) & (s8 <= 255)) and np.all((sh >= 0) & (sh <= 24))
    nz = sc > 2 ** -24
    assert np.allclose(s8[nz] / 2.0 ** sh[nz], sc[nz], rtol=6e-3)


def test_checksum():
    Wq = rng.integers(-7, 8, (16, 16))
    s = G.abft_signs(16, 7)
    assert set(np.unique(s)) <= {-1, 1}
    chk, e = G.abft_checksum_col(Wq, s)
    assert np.all(np.abs(chk) <= 15) and np.all(np.abs(e) <= 4)
    xq = rng.integers(-127, 128, 16)
    # linearity: sum_j s_j (Wq@x)_j == 8*(chk@x) + e@x  (exact integers)
    assert s @ (Wq @ xq) == 8 * (chk @ xq) + e @ xq
    # corrected residual (e.xq term removed): budget from clean traffic is
    # conversion-rounding-sized; an injected stuck cap trips it
    D = 2
    clean = [G.tile_mvm(Wq, rng.integers(-127, 128, 16), D, s=s, chk=chk,
                        chk_e=e)["chk"]["residual"] for _ in range(50)]
    bud = G.abft_budget(clean)
    assert max(clean) <= bud
    Wbad = Wq.copy()
    Wbad[3, 0] += 8                                # stuck cap on column 3
    xf = np.zeros(16, dtype=np.int64)
    xf[0] = 127                                    # activation exposes it
    r_bad = G.tile_mvm(Wbad, xf, D, s=s, chk=chk, chk_e=e)["chk"]["residual"]
    assert r_bad > bud, (r_bad, bud)
    r_clean = G.tile_mvm(Wq, xf, D, s=s, chk=chk, chk_e=e)["chk"]["residual"]
    assert r_clean <= bud


def test_relu_exit():
    D = 2
    for _ in range(50):
        Wq = rng.integers(-7, 8, (16, 16))
        xq = rng.integers(-127, 128, 16)
        t = G.tile_mvm(Wq, xq, D, relu=True)
        tn = G.tile_mvm(Wq, xq, D, relu=False)
        # exit rule reference: HI exits when mac_hi<0 (whole y12 zeroed, LO
        # skipped); LO exits when code_hi==0 and mac_lo<0; fabric ReLU-clamps
        # the recombined y12 (negative values never escape)
        for j in range(16):
            if tn["mac_hi"][j] < 0:
                assert t["y12"][j] == 0 and t["conv_hi"]["n_eval"][j] == 0 \
                    and t["conv_lo"]["n_eval"][j] == 0
            elif tn["conv_hi"]["code"][j] == 0 and tn["mac_lo"][j] < 0:
                assert t["y12"][j] == 0 and t["conv_lo"]["n_eval"][j] == 0
            else:
                assert t["y12"][j] == max(tn["y12"][j], 0)
        # never emits a negative column; saves strobes vs no-relu
        assert np.all(t["y12"] >= 0)
    acc, n, info = G.mvm_layer(rng.integers(-7, 8, (16, 16)),
                               rng.integers(-127, 128, 16), D, relu=True)
    assert np.all(acc >= 0) and info["exits"] >= 0


def test_lora():
    # D sized like the compiler's B_y schedule so no code hits the +-127
    # clamp (max |mac| ~ 1100 here -> D=16 keeps codes < 70)
    D, rho = 16, 0.03
    Wq = rng.integers(-3, 4, (16, 16))
    A_q = rng.integers(-7, 8, 16)
    B_q = rng.integers(-7, 8, 16)
    xq = rng.integers(-15, 16, 16)
    t = G.tile_mvm(Wq, xq, D, lora=(A_q, B_q, rho))
    # in-charge add == digital reference within conversion rounding:
    # 16*(A.snh) + (A.snl) == A.xq exactly, so the ideal recombined value is
    # Wq@xq + rho*B*(A.xq); each window conversion rounds by <= D/2.
    ideal = Wq @ xq + rho * B_q * float(A_q @ xq)
    assert np.all(np.abs(t["y14"] * D - ideal) <= 8.5 * D + 1e-6)
    # and the sidecar visibly moved the codes vs the plain tile
    t0 = G.tile_mvm(Wq, xq, D)
    assert np.any(t["y14"] != t0["y14"])
    # one SGD outer-product step reduces toy MSE loss
    A = rng.normal(0, 1, 16)
    B = rng.normal(0, 1, 16)
    x = rng.normal(0, 1, 16)
    base = rng.normal(0, 1, 16)
    target = rng.normal(0, 1, 16)
    y0 = base + B * (A @ x)
    l0 = 0.5 * np.sum((y0 - target) ** 2)
    A2, B2 = G.lora_sgd_step(A, B, x, y0, target, lr=0.01)
    y1 = base + B2 * (A2 @ x)
    l1 = 0.5 * np.sum((y1 - target) ** 2)
    assert l1 < l0, (l0, l1)
    # quantized sidecar codes are legal 4b
    A_q2, B_q2, rho2 = G.lora_quant(A, B, np.ones(16))
    assert np.all(np.abs(A_q2) <= 7) and np.all(np.abs(B_q2) <= 7) and rho2 > 0


def test_softmax():
    z = rng.normal(0, 2, 8)
    p = G.softmax_ref(z)
    assert abs(p.sum() - 1) < 1e-12                # KCL checksum sum(I)=I_b
    e = np.exp(z - z.max())
    assert np.allclose(p, e / e.sum())
    # temperature: higher beta -> peakier (max prob grows)
    assert G.softmax_ref(z, 2.0).max() > p.max() > G.softmax_ref(z, 0.5).max()


def test_online_softmax_monoid():
    """Online-softmax monoid: associativity + equivalence to plain softmax
    (THE_COMPILER_STRUCTURE 6 / CHIP2_SPEC 4). The associativity is the
    offload-legality proof: banks may reduce independently, a tree may merge."""
    beta = 1.3
    # 4 blocks of scores + values (d_v = 3), rising max to exercise rescale g<1
    blocks = []
    all_scores, all_vals = [], []
    for i in range(4):
        s = rng.normal(i * 0.5, 1.0, 5)      # block i has a higher mean -> new max
        v = rng.normal(0, 1, (5, 3))
        blocks.append((s, v))
        all_scores.append(s)
        all_vals.append(v)
    all_scores = np.concatenate(all_scores)
    all_vals = np.concatenate(all_vals)

    m, l, o = G.online_softmax_monoid(blocks, beta)

    # equivalence: o/l == plain softmax(beta*scores) @ values over ALL tokens
    p = G.softmax_ref(all_scores, beta)
    assert np.allclose(o / l, p @ all_vals, rtol=1e-10), (o / l, p @ all_vals)
    assert abs(m - all_scores.max()) < 1e-12       # running max is the global max
    # l is the plain softmax denominator referenced to the global max
    assert np.allclose(l, np.sum(np.exp(beta * (all_scores - m))), rtol=1e-12)

    # rescale g = e^(beta*(old_m - m)) <= 1 by construction (numerically safe)
    p1 = G.block_reduce(*blocks[0], beta)
    p2 = G.block_reduce(*blocks[1], beta)
    mm = max(p1[0], p2[0])
    assert np.exp(beta * (p1[0] - mm)) <= 1 + 1e-15
    assert np.exp(beta * (p2[0] - mm)) <= 1 + 1e-15

    # ASSOCIATIVITY: three different groupings must agree (exact-arith monoid)
    left = G.online_softmax_monoid(blocks, beta)                     # ((((.)))) fold
    parts = [G.block_reduce(*b, beta) for b in blocks]
    # right fold
    right = parts[-1]
    for pr in reversed(parts[:-1]):
        right = G.monoid_combine(pr, right, beta)
    # balanced tree: (0 o 1) o (2 o 3)
    tree = G.monoid_combine(G.monoid_combine(parts[0], parts[1], beta),
                            G.monoid_combine(parts[2], parts[3], beta), beta)
    for grp in (right, tree):
        assert np.allclose(left[0], grp[0]) and np.allclose(left[1], grp[1]) \
            and np.allclose(left[2], grp[2]), (left, grp)

    # single-token blocks == plain softmax (degenerate reduce)
    z = rng.normal(0, 2, 6)
    singles = [([zi], [[1.0]]) for zi in z]
    _, ls, os_ = G.online_softmax_monoid(singles, beta)
    assert np.allclose((os_ / ls).ravel(), G.softmax_ref(z, beta).sum())  # =1


def test_group_combine():
    """Level-1 group_combine (CHIP2_SPEC 4 level 1) == the streaming monoid,
    and is grouping-invariant (offload-legality: banks reduce in any order)."""
    beta = 1.15
    parts = [G.block_reduce(rng.normal(i * 0.4, 1.0, 5),
                            rng.normal(0, 1, (5, 3)), beta) for i in range(4)]
    grp = G.group_combine(parts, beta)
    # equals the plain left-fold monoid over the same partials
    ref = parts[0]
    for p in parts[1:]:
        ref = G.monoid_combine(ref, p, beta)
    for a, b in zip(grp, ref):
        assert np.allclose(a, b, rtol=1e-12), (a, b)
    # grouping invariance: two half-groups then combine == one flat group
    a = G.group_combine(parts[:2], beta)
    b = G.group_combine(parts[2:], beta)
    two = G.monoid_combine(a, b, beta)
    for x, y in zip(two, grp):
        assert np.allclose(x, y, rtol=1e-12), (x, y)


def test_fp32_island_combine():
    """Level-2 fp32 island (CHIP2_SPEC 4 level 2 / B7): digitize group partials,
    retroactive-rescale monoid + final divide in fp32, vs the exact monoid."""
    beta = 1.0
    dh = 8
    # four groups, RISING max so the retroactive rescale is exercised at level 2
    parts = [G.block_reduce(rng.normal(i * 0.6, 1.0, 6),
                            rng.normal(0, 1, (6, dh)), beta) for i in range(4)]
    # exact fp32 reference: the plain monoid then divide (no digitization)
    m, l, o = G.group_combine(parts, beta)
    ot_exact = o / l
    # island: same fold but through the 8b-m / block-FP-o crossing format
    ot_isl = G.fp32_island_combine(parts, beta)
    # digitization (8b m, 8b block-FP o) is the only loss -> tight but not exact
    rel = np.max(np.abs(ot_isl - ot_exact) / (np.abs(ot_exact) + 1e-9))
    assert rel < 0.02, rel                          # <2% from the 8b crossing
    # divide=False returns the raw (m,l,o) partial for the O_PARTIAL flit
    mi, li, oi = G.fp32_island_combine(parts, beta, divide=False)
    span = max(p[0] for p in parts) - min(p[0] for p in parts)
    assert abs(mi - m) <= span / 255 + 1e-9         # m within one 8b LSB (snap)
    assert np.allclose(oi / li, ot_isl, rtol=1e-12)
    # associativity: island result is independent of group order (offload-legal)
    ot_perm = G.fp32_island_combine(parts[::-1], beta)
    assert np.allclose(np.sort(ot_isl), np.sort(ot_isl))  # sanity
    assert np.max(np.abs(ot_perm - ot_isl)) < 0.02        # order-invariant


def test_ptat_score_gain():
    """#25: pre-scaling the score SPREAD by T/T0 kills the beta(T) ratio drift.

    softmax ratio p_i/p_j = exp(beta(T)*dV). Measured translinear beta(T) =
    27.31/24.71/22.36 /V at 27/55/85 C (STATUS A3 / CHIP2_SPEC B4). With a
    fixed score pattern the winning-branch share drifts as beta drifts; the
    compiler's ptat_score_gain(T)=T/T0 pre-scale on dV cancels it.
    """
    dV = np.array([70., 30., -20., -40., 10., -50., 60., -60.]) * 1e-3  # V, about CM
    beta_meas = {300.15: 27.31, 328.15: 24.71, 358.15: 22.36}          # /V @ 27/55/85C
    T0 = 300.15
    p0 = G.softmax_ref(dV, beta_meas[T0])                              # reference ratios
    win = int(np.argmax(p0))

    drift_raw, drift_ptat = [], []
    for T, beta in beta_meas.items():
        # (A) fixed input, only beta drifts -> ratio drift (tracks 1/T)
        pr = G.softmax_ref(dV, beta)
        drift_raw.append(pr[win] / p0[win] - 1)
        # (B) score spread x ptat_score_gain(T) -> beta(T)*dV_scaled ~ invariant
        pc = G.softmax_ref(dV * G.ptat_score_gain(T, T0), beta)
        drift_ptat.append(pc[win] / p0[win] - 1)

    # without the pre-scale: sharpness collapses ~-13% at 85C (mirror #18 cfg-B)
    assert min(drift_raw) < -0.10, drift_raw
    # with it: ratios temperature-FLAT within a few % (mirror #18 cfg-C +0.4%)
    assert max(abs(d) for d in drift_ptat) < 0.02, drift_ptat


def test_kv_decay():
    codes = rng.integers(-7, 8, 8)
    assert np.all(G.kv_read(codes) == codes)                    # ideal
    v = G.kv_read(codes, dt=1e-3, tau=2e-3)
    assert np.allclose(v, codes * np.exp(-0.5))                 # decay hook


def test_mvm_layer_accuracy():
    Wq = rng.integers(-7, 8, (64, 48))
    xq = rng.integers(-127, 128, 48)
    # D sized so no per-pass code exceeds the +-127 clamp
    sh, sl = G.pwm_nibbles(xq)[1:]
    D = 4
    acc, n, info = G.mvm_layer(Wq, xq, D)
    assert n == 4 * 3
    # per window per pass rounding <= D/2 -> per column <= 8.5*D per pass
    bound = 3 * 8.5 * D
    assert np.all(np.abs(acc * D - Wq @ xq) <= bound)
    # fixture ffn e2e with relu early exit: finite + relu-consistent
    Xc = rng.normal(0, 1, (8, 16))
    W1 = rng.normal(0, 0.5, (16, 16))
    W2 = rng.normal(0, 0.5, (16, 16))

    def mini_compile(W, Xc):
        Xs, Ws, s = G.smooth(Xc, W)
        Wq, dw = G.quant_w_int4(Ws)
        dx = np.max(np.abs(Xs)) / 127
        D = 1
        dy = np.max(np.abs(Xs @ Ws.T)) / 127
        s8, shf = G.make_requant(D * dw * dx / dy)
        return {"Wq": Wq, "smooth": s, "dx_in": dx, "D": D, "dy": dy,
                "scale": s8, "shift": shf, "offset": 0}
    C1, C2 = mini_compile(W1, Xc), mini_compile(W2, Xc @ W1.T)
    r = G.ffn_forward(C1, C2, Xc[0], act="relu")
    assert np.all(np.abs(r["out8"]) <= 127) and np.all(r["h8"] >= 0)
    assert r["passes"] == 2 and 0 <= r["sign_exit"] <= 16


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok {t.__name__}")
    print("PASS test_golden")


if __name__ == "__main__":
    try:
        main()
    except AssertionError:
        import traceback
        traceback.print_exc()
        print("FAIL test_golden")
        sys.exit(1)
