#!/usr/bin/env python3
"""A5b format-universal compiler tests
(PYTHONPATH=scripts python3 scripts/compiler/test_formats.py). Prints PASS/FAIL.

(a) registry round-trips/monotonicity/extremes for every format (+ explicit
    fp8 e5m2 inf/nan and e4m3 448/NaN policy, subnormals);
(b) INT4/INT8 identity regression: the general lowering reproduces A5's
    legacy path bit-identically (quant fns, compile_matrix fields, MVM);
(c) format matrix on the REAL SmolLM2 blk.0 head-0 Wq slice: golden MVM vs
    float64 reference >= documented SQNR floor, pass counts match the law;
(d) main() also re-runs the existing test_golden.py + test_compile.py suites.
"""

import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compiler.formats import FORMATS, lower_tensor, lower_acts, \
    passes_per_tile, n_slices, n_nibbles, slice_digits, \
    csd_digits, csd_caps, charge_cost  # noqa: E402
from compiler import compile as CC  # noqa: E402
from compiler import gguf_reader as GR  # noqa: E402
from golden import model as G  # noqa: E402

rng = np.random.default_rng(11)


# ---------------------------------------------------------------------------
# (a) registry property tests
# ---------------------------------------------------------------------------

def test_registry_roundtrip():
    for name, f in FORMATS.items():
        if f.kind == "int":
            codes = np.arange(-int(f.max_finite), int(f.max_finite) + 1)
            vals = f.decode(codes)
            assert np.array_equal(f.encode(vals), codes), name
        else:
            if f.bits <= 8:
                vals = f.decode(np.arange(1 << f.bits, dtype=np.uint64))
                vals = np.unique(vals[np.isfinite(vals)])
            else:  # sample the wide formats incl. subnormal/normal boundary
                vals = np.unique(np.concatenate([
                    f.snap(rng.normal(0, s, 500)) for s in
                    (1e-30, 1e-6, 1.0, 1e6)] + [np.array([0.0, f.max_finite])]))
                vals = vals[np.isfinite(vals)]
            back = f.decode(f.encode(vals))
            assert np.array_equal(back, vals), (name, vals[back != vals][:5])
        # monotone non-decreasing snap on a dense input sweep
        x = np.linspace(-f.max_finite * 1.2, f.max_finite * 1.2, 4001)
        s = f.snap(x) if f.kind == "float" else f.decode(f.encode(x))
        assert np.all(np.diff(s) >= 0), name
        # extremes: saturating encode, exact max/min decode
        top = f.decode(f.encode(np.array([1e300, -1e300])))
        assert top[0] == f.max_finite and top[1] == -f.max_finite, name


def test_specials_policy():
    # fp8_e5m2: OCP/IEEE inf+nan. s.11111.00 = +-inf, s.11111.mm!=0 = NaN
    f = FORMATS["fp8_e5m2"]
    assert f.decode(np.array([0x7C]))[0] == np.inf
    assert f.decode(np.array([0xFC]))[0] == -np.inf
    assert np.isnan(f.decode(np.array([0x7D, 0x7E, 0x7F, 0xFD]))).all()
    assert f.decode(np.array([0x7B]))[0] == 57344.0 == f.max_finite
    # saturating encode: inf/big -> max_finite code (never inf), NaN -> 0
    assert f.decode(f.encode(np.array([np.inf])))[0] == 57344.0
    assert f.decode(f.encode(np.array([np.nan])))[0] == 0.0
    # fp8_e4m3: OCP no inf; only s.1111.111 is NaN; 0x7E = 448 is a number
    f = FORMATS["fp8_e4m3"]
    assert np.isnan(f.decode(np.array([0x7F, 0xFF]))).all()
    assert f.decode(np.array([0x7E]))[0] == 448.0 == f.max_finite
    assert not np.isinf(f.decode(np.arange(256, dtype=np.uint64))).any()
    assert f.decode(f.encode(np.array([1e9])))[0] == 448.0
    # subnormals round-trip (smallest positive of several formats)
    for name, tiny in [("fp4_e2m1", 0.5), ("fp6_e2m3", 0.125),
                       ("fp8_e4m3", 2.0 ** -9), ("fp8_e5m2", 2.0 ** -16),
                       ("fp16", 2.0 ** -24), ("fp32", 2.0 ** -149)]:
        f = FORMATS[name]
        assert f.decode(f.encode(np.array([tiny])))[0] == tiny, name
    # fp2 is ternary; fp3_e2m0 is the {0,+-.5,+-1,+-2} set
    t2 = FORMATS["fp2"]._table
    assert set(t2[np.isfinite(t2)].tolist()) == {-1.0, 0.0, 1.0}
    assert set(FORMATS["fp3_e2m0"]._table.tolist()) == \
        {0.0, 0.5, 1.0, 2.0, -0.5, -1.0, -2.0}


def test_pass_law():
    # identity anchor + slice/nibble arithmetic
    assert n_slices(4) == 1 and n_nibbles(8) == 2 and passes_per_tile(4, 8) == 1
    assert passes_per_tile(5, 8) == 1          # differential sign is free
    assert passes_per_tile(8, 8) == 2 and passes_per_tile(8, 4) == 2
    assert passes_per_tile(8, 12) == 4         # 3 nibbles -> 2 rounds
    assert passes_per_tile(2, 2) == 1
    M = rng.integers(-127, 128, (8, 8))
    d = slice_digits(M, 2)
    assert np.array_equal(d[0] + 16 * d[1], M) and np.all(np.abs(d) <= 15)


# ---------------------------------------------------------------------------
# (b) INT4/INT8 identity regression
# ---------------------------------------------------------------------------

def test_identity_lowering():
    W = rng.normal(0, 1, (64, 48))
    W[5] = 0.0                                       # dead-channel edge
    Wq, dw = G.quant_w_int4(W)
    L = lower_tensor(W, "int4")
    assert np.array_equal(L["M"], Wq) and np.array_equal(L["w_scale"], dw)
    assert L["S"] == 1 and L["sig"] == [1] and np.all(L["exp"] == 0)
    assert np.array_equal(L["slices"][0], Wq) and L["e_min"] == 0
    X = rng.normal(0, 2, 48)
    xq, dx = G.quant_x_int8(X)
    A = lower_acts(X, "int8")
    assert np.array_equal(A["xq"], xq) and A["dx"] == dx
    assert A["b_x"] == 8 and A["n_nib"] == 2
    # general golden MVM == legacy golden MVM, bit-identical
    for D in (1, 3, 7):
        a0, n0, _ = G.mvm_layer(Wq, xq, D)
        a1, n1, _ = G.mvm_lowered(L["slices"], L["sig"], L["exp"],
                                  L["e_min"], xq, D)
        assert np.array_equal(a0, a1) and n0 == n1, D


def test_identity_compile_matrix():
    m = _model()
    A_in = _cal()["A_in"]
    W = m["Wq"]                                      # real 64x576 head slice
    C0 = CC.compile_matrix("wq", W, A_in)            # frozen A5 path
    C1 = CC.compile_matrix_fmt("wq", W, A_in, "int4", "int8")
    assert np.array_equal(C0["Wq"], C1["Lw"]["M"])
    assert np.array_equal(C0["Wq"], C1["Lw"]["slices"][0])
    assert np.array_equal(C0["dw"], C1["Lw"]["w_scale"])
    assert np.array_equal(C0["smooth"], C1["smooth"])
    assert C0["D"] == C1["D"] and C0["dx_in"] == C1["La"]["dx"]
    assert C0["dy"] == C1["dy"]
    assert np.array_equal(C0["scale"], C1["scale"])
    assert np.array_equal(C0["shift"], C1["shift"])
    # and the vectorized general pipeline reproduces the legacy per-pass acc
    xq = C1["La"]["xq"][-1]
    p0 = CC.layer_passes(C0, xq)
    p1 = CC.layer_passes_fmt(C1, xq)
    assert np.array_equal(p0["acc"], p1["acc"])
    assert np.array_equal(p0["out8"], p1["out8"])


# ---------------------------------------------------------------------------
# (c) format matrix on the real head-0 Wq slice
# ---------------------------------------------------------------------------

# floors: measured mvm_sqnr minus ~2 dB margin (regression tripwires, not
# theory). The ~25 dB ceiling across all >=8b-eff sources is the B_y=8 CSNR
# ceiling; fp2/fp3 land at ternary-weight fidelity.
GRID_FLOORS = {                    # measured on real Wq (see docstring):
    ("int4", "int8"): 18.5,        # 20.8 dB
    ("int8", "int8"): 17.0,        # 19.1 dB (S=2 hi-slice conv noise)
    ("fp2", "fp3"): 1.5,           # 3.3 dB  (ternary weights)
    ("fp4", "int8"): 14.5,         # 16.6 dB
    ("fp6_e2m3", "fp6_e3m2"): 15.0,  # 17.3 dB
    ("fp8_e4m3", "fp8_e5m2"): 22.5,  # 24.6 dB
    ("fp8_e5m2", "int8"): 21.0,    # 23.0 dB
    ("fp16", "fp16"): 22.5,        # 24.6 dB  <- the B_y=8 CSNR ceiling
    ("fp32", "fp32"): 22.5,        # 24.7 dB
    ("bf16", "int8"): 22.5,        # 24.5 dB
}


def _model():
    if not hasattr(_model, "m"):
        _model.m = CC.load_model()
    return _model.m


def _cal():
    if not hasattr(_cal, "c"):
        m = _model()
        ids = GR.tokenize_greedy("The quick fox", m["vocab"])
        E = m["embd"][ids].astype(np.float64)
        _cal.c = {"ids": ids,
                  "A_in": CC.rms_rows(E, m["attn_norm"], m["rms_eps"])}
    return _cal.c


def test_format_matrix_real_wq():
    m, A_in = _model(), _cal()["A_in"]
    W = m["Wq"]
    print()
    for (wf, af), floor in GRID_FLOORS.items():
        C = CC.compile_matrix_fmt("wq", W, A_in, wf, af)
        Lw, La = C["Lw"], C["La"]
        xq = La["xq"][-1]
        p = CC.layer_passes_fmt(C, xq)
        # golden general MVM (loop) == vectorized pipeline, bit-identical
        acc, n_passes, _ = G.mvm_lowered(Lw["slices"], Lw["sig"], Lw["exp"],
                                         Lw["e_min"], xq, C["D"], La["n_nib"])
        assert np.array_equal(acc, p["acc"]), (wf, af)
        # pass counts obey the law
        law = CC.count_passes(W.shape) * passes_per_tile(Lw["b_eff"], La["b_x"])
        assert n_passes == law, (wf, af, n_passes, law)
        # fidelity floor vs float64 reference (smoothed domain)
        y_ref = C["Ws"] @ C["Xs"][-1]
        y_hat = acc * C["D"] * Lw["w_scale"] * np.exp2(Lw["e_min"]) * La["dx"]
        e = y_ref - y_hat
        sq = 10 * np.log10(np.mean(y_ref ** 2) / np.mean(e ** 2))
        print(f"    {wf:9s} x {af:9s}: b_eff={Lw['b_eff']} S={Lw['S']} "
              f"D={C['D']:3d} passes/tok={law:4d} wSQNR={Lw['sqnr_db']:5.1f} "
              f"mvmSQNR={sq:5.1f} dB (floor {floor}) over8={Lw['over_by8']}")
        assert sq >= floor, (wf, af, sq, floor)
        # over_by8 flag fires exactly for >8b per-element sources
        assert Lw["over_by8"] == (FORMATS[wf].sig_bits > 8), (wf, af)


def test_multi_nibble_rounds():
    # b_x = 12 (flagged wider-than-native): 3 nibbles -> 2 rounds, odd last
    W = rng.normal(0, 1, (16, 16))
    X = rng.normal(0, 1, 16) * np.exp(rng.normal(0, 2, 16))
    L = lower_tensor(W, "int4")
    A = lower_acts(X, "fp16", target_bits=12)
    assert A["b_x"] == 12 and A["n_nib"] == 3
    assert np.all(np.abs(A["xq"]) <= 2047)
    sg, rounds = G.pwm_nibble_rounds(A["xq"], 3)
    assert len(rounds) == 2 and rounds[1][1] is None
    recon = sg * sum((16 ** k) * ((np.abs(A["xq"]) >> (4 * k)) & 15)
                     for k in range(3))
    assert np.array_equal(recon, A["xq"])
    D = max(1, G.conv_scale_D(L["slices"][0] @ (sg * rounds[0][0])))
    acc, n, _ = G.mvm_lowered(L["slices"], L["sig"], L["exp"], L["e_min"],
                              A["xq"], D, n_nib=3)
    assert n == 1 * 2                                 # S=1 x 2 rounds
    # reconstruction bound: per-window conversion rounding <= D/2 per column
    # entry, weighted by nibble significance sum (1+16+256)
    ideal = L["M"] @ A["xq"]
    bound = 8.5 * D * (1 + 16 + 256)
    assert np.all(np.abs(acc * D - ideal) <= bound)


# ---------------------------------------------------------------------------
# task A: CSD weight recoding
# ---------------------------------------------------------------------------

def test_csd_recode():
    # NAF properties on the full int16 range: reconstruction, digit set,
    # no two adjacent nonzeros
    M = np.arange(-(1 << 15), (1 << 15) + 1)
    P = csd_digits(M)
    assert np.all(np.isin(P, (-1, 0, 1)))
    assert np.array_equal(sum((1 << k) * P[k] for k in range(P.shape[0])), M)
    assert np.all(P[:-1] * P[1:] == 0), "adjacent nonzero digits"
    # cap mapping: Cp - Cn == M through the slice significances, codes 4b,
    # no shared bit
    cc = csd_caps(M)
    rec = sum(s * (cc["Cp"][i] - cc["Cn"][i]) for i, s in enumerate(cc["sig"]))
    assert np.array_equal(rec, M)
    assert np.all((cc["Cp"] <= 15) & (cc["Cn"] <= 15))
    assert np.all(cc["Cp"] & cc["Cn"] == 0)
    # int4 weights stay single-slice; the NAF carry needs the extra slice
    # exactly at 4S-bit magnitudes (slice digits +-15 -> +16 -1)
    assert csd_caps(np.arange(-7, 8))["S_csd"] == 1
    assert csd_caps(np.array([15]))["S_csd"] == 2
    assert csd_caps(np.array([-15]))["S_csd"] == 2


def test_csd_real_wq():
    """--csd on the real head-0 Wq slice: bit-equal MVM, measured density."""
    m, A_in = _model(), _cal()["A_in"]
    C0 = CC.compile_matrix("wq", m["Wq"], A_in)
    C1 = CC.compile_matrix("wq", m["Wq"], A_in, csd=True)
    # everything except the C+/C- split is untouched
    assert np.array_equal(C0["Wq"], C1["Wq"]) and C0["D"] == C1["D"]
    assert np.array_equal(G.wq_from_caps(C1["Cp"], C1["Cn"]), C0["Wq"])
    assert not np.array_equal(C1["Cp"], C0["Cp"])    # the recode did happen
    # CSD-aware tile MVM is bit-equal to the one-sided tile MVM on real
    # tiles x the real last-token activations (full tile grid)
    xq = G.quant_in(C0, A_in[-1])
    for ct, rt, js, ks in G.iter_tile_passes(*C0["Wq"].shape):
        t0 = G.tile_mvm(C0["Wq"][js, ks], xq[ks], C0["D"])
        t1 = G.tile_mvm_caps(C1["Cp"][js, ks], C1["Cn"][js, ks],
                             xq[ks], C1["D"])
        assert np.array_equal(t0["y12"], t1["y12"]), (ct, rt)
        assert np.array_equal(t0["y14"], t1["y14"]), (ct, rt)
    # measured density + charge on the real matrix (report, with tripwires:
    # CSD never increases digit count, never decreases value units)
    duty = np.abs(xq) / 255.0
    base = charge_cost(C0["Cp"], C0["Cn"], duty)
    new = charge_cost(C1["Cp"], C1["Cn"], duty)
    print(f"\n    csd real Wq: density {base['density']:.3f} -> "
          f"{new['density']:.3f}, cells charge {base['cells']:.1f} -> "
          f"{new['cells']:.1f} ({100*(1-new['cells']/base['cells']):+.1f}% "
          f"drop), value charge {100*(new['value']/base['value']-1):+.1f}%")
    assert new["cells_static"] <= base["cells_static"]
    assert new["value_static"] >= base["value_static"]
    assert new["density"] <= base["density"]


# ---------------------------------------------------------------------------
# (item 4) K-quant dequant vs scalar transcription of ggml C
# ---------------------------------------------------------------------------

def _scale_min_k4(j, sc):
    if j < 4:
        return sc[j] & 63, sc[j + 4] & 63
    return (sc[j + 4] & 15) | ((sc[j - 4] >> 6) << 4), \
           (sc[j + 4] >> 4) | ((sc[j] >> 6) << 4)


def test_kquants():
    # ggml C promotes the fp16 scale to float BEFORE multiplying
    f16 = lambda u: float(np.frombuffer(bytes(u), dtype="<f2")[0])  # noqa: E731
    # Q4_K
    blk = rng.integers(0, 256, 144, dtype=np.uint8)
    blk[0:2] = np.frombuffer(np.float16(0.11).tobytes(), np.uint8)
    blk[2:4] = np.frombuffer(np.float16(0.03).tobytes(), np.uint8)
    d, dmin, sc, qs = f16(blk[0:2]), f16(blk[2:4]), blk[4:16], blk[16:144]
    ref = np.zeros(256, np.float32)
    for j in range(4):
        s1, m1 = _scale_min_k4(2 * j, sc)
        s2, m2 = _scale_min_k4(2 * j + 1, sc)
        for l in range(32):
            ref[64 * j + l] = d * s1 * (qs[32 * j + l] & 15) - dmin * m1
            ref[64 * j + 32 + l] = d * s2 * (qs[32 * j + l] >> 4) - dmin * m2
    got = GR._dequant_q4k(blk[None, :])
    assert np.allclose(got, ref, rtol=1e-6), "q4_k"
    # Q5_K
    blk = rng.integers(0, 256, 176, dtype=np.uint8)
    blk[0:2] = np.frombuffer(np.float16(0.07).tobytes(), np.uint8)
    blk[2:4] = np.frombuffer(np.float16(0.02).tobytes(), np.uint8)
    d, dmin, sc = f16(blk[0:2]), f16(blk[2:4]), blk[4:16]
    qh, qs = blk[16:48], blk[48:176]
    ref = np.zeros(256, np.float32)
    for j in range(4):
        s1, m1 = _scale_min_k4(2 * j, sc)
        s2, m2 = _scale_min_k4(2 * j + 1, sc)
        u1, u2 = 1 << (2 * j), 1 << (2 * j + 1)
        for l in range(32):
            ref[64 * j + l] = d * s1 * ((qs[32 * j + l] & 15)
                                        + (16 if qh[l] & u1 else 0)) - dmin * m1
            ref[64 * j + 32 + l] = d * s2 * ((qs[32 * j + l] >> 4)
                                             + (16 if qh[l] & u2 else 0)) - dmin * m2
    got = GR._dequant_q5k(blk[None, :])
    assert np.allclose(got, ref, rtol=1e-6), "q5_k"
    # Q6_K
    blk = rng.integers(0, 256, 210, dtype=np.uint8)
    blk[208:210] = np.frombuffer(np.float16(0.05).tobytes(), np.uint8)
    ql, qh = blk[0:128], blk[128:192]
    sc = blk[192:208].view(np.int8)
    d = f16(blk[208:210])
    ref = np.zeros(256, np.float32)
    for n in range(2):
        qlh, qhh, sch = ql[64 * n:], qh[32 * n:], sc[8 * n:]
        for l in range(32):
            is_ = l // 16
            lo0, lo32, h = int(qlh[l]), int(qlh[32 + l]), int(qhh[l])
            q1 = ((lo0 & 15) | ((h & 3) << 4)) - 32
            q2 = ((lo32 & 15) | (((h >> 2) & 3) << 4)) - 32
            q3 = ((lo0 >> 4) | (((h >> 4) & 3) << 4)) - 32
            q4 = ((lo32 >> 4) | (((h >> 6) & 3) << 4)) - 32
            ref[128 * n + l] = d * sch[is_] * q1
            ref[128 * n + 32 + l] = d * sch[is_ + 2] * q2
            ref[128 * n + 64 + l] = d * sch[is_ + 4] * q3
            ref[128 * n + 96 + l] = d * sch[is_ + 6] * q4
    got = GR._dequant_q6k(blk[None, :])
    assert np.allclose(got, ref, rtol=1e-6), "q6_k"


# ---------------------------------------------------------------------------
# (d) existing suites stay green
# ---------------------------------------------------------------------------

def test_existing_suites():
    here = Path(__file__).resolve().parent
    for script in (here.parent / "golden" / "test_golden.py",
                   here / "test_compile.py"):
        r = subprocess.run([sys.executable, str(script)],
                           capture_output=True, text=True)
        assert r.returncode == 0 and "PASS" in r.stdout, \
            (script.name, r.stdout[-2000:], r.stderr[-2000:])


def main():
    tests = [test_registry_roundtrip, test_specials_policy, test_pass_law,
             test_identity_lowering, test_identity_compile_matrix,
             test_format_matrix_real_wq, test_multi_nibble_rounds,
             test_csd_recode, test_csd_real_wq,
             test_kquants, test_existing_suites]
    for t in tests:
        t()
        print(f"  ok {t.__name__}")
    print("PASS test_formats")


if __name__ == "__main__":
    try:
        main()
    except AssertionError:
        import traceback
        traceback.print_exc()
        print("FAIL test_formats")
        sys.exit(1)
