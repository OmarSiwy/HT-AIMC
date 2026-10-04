#!/usr/bin/env python3
"""Task B tests: DPS rank-48 bilinear lowering
(python3 scripts/compiler/test_dps.py). Prints PASS/FAIL.

(a) embedded decomposition verifies exactly against the <4,4,4> matmul
    tensor (Brent equations, integer arithmetic) + float64 matmul identity;
(b) golden recombination structure is exact (no-conversion path == 8*Wq@X);
(c) REAL Wq head-0 slice, two-part honest tax: the exact-arithmetic
    algorithm tax is ~0 dB (confirms the paper's +0.13 dB), but the INT4-cap
    folded-combo re-quant tax is large (net-negative verdict); pass count
    == 48*Gi*Gk (x0.75 law);
(d) full run_dps48 emission: exact prompt pass counts + config consistency.
"""

import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compiler import dps48 as DP  # noqa: E402
from compiler import compile as CC  # noqa: E402
from compiler import gguf_reader as GR  # noqa: E402
from golden import model as G  # noqa: E402

rng = np.random.default_rng(3)


def test_tensor_verifies():
    assert DP.verify()
    # coefficient sets as documented (paper table: DR 4 bits, W = shifts)
    assert set(np.unique(DP.U)) <= {-1, 0, 1}
    assert set(np.unique(DP.V)) <= {-1, 0, 1}
    assert set(np.unique(DP.WT8)) <= {-4, -2, -1, 0, 1, 2, 4}


def test_float64_matmul_identity():
    # exact in float64: integer entries, dyadic output coefficients
    for _ in range(20):
        A = rng.integers(-99, 100, (4, 4)).astype(np.float64)
        B = rng.integers(-99, 100, (4, 4)).astype(np.float64)
        prods = np.einsum("mab,ab->m", DP.U, A) \
            * np.einsum("mcd,cd->m", DP.V, B)
        C = np.einsum("mij,m->ij", DP.WT8, prods) / 8.0
        assert np.array_equal(C, A @ B)


def test_recombination_exact():
    # golden exact path (conversion bypassed, no operand rounding) is the
    # pure bilinear identity: acc == 8 * xq4 @ Wq.T
    O, I = 64, 128                      # Gi=1, Gk=2
    Wq = rng.integers(-7, 8, (O, I))
    xq4 = rng.integers(-127, 128, (4, I))
    Gi, Gk = O // 64, I // 64
    W6 = Wq.reshape(Gi, 4, 16, Gk, 4, 16)
    A = np.einsum("mab,gaoxbi->gxmoi", DP.U, W6)      # unrounded combos
    s_a = np.zeros((Gi, Gk, 48), dtype=np.int64)
    s_b = np.zeros((Gk, 48), dtype=np.int64)
    acc, npass, _ = G.mvm_dps48_group(A, s_a, s_b, DP.V, DP.WT8, xq4, 1,
                                      exact=True)
    assert np.array_equal(acc, 8 * (xq4 @ Wq.T))
    assert npass == 48 * Gi * Gk


def _model():
    if not hasattr(_model, "m"):
        _model.m = CC.load_model()
    return _model.m


def test_real_wq_snr_and_passes():
    """The honest DPS-48 characterization on the real head-0 Wq slice.

    Decomposes the tax into (i) the ALGORITHM tax measured in exact integer
    arithmetic -- no operand quantization -- which the paper claims is ~+0.13
    dB, and (ii) the INT4-CAP tax that appears once the folded A-side combos
    (sums of up to 16 INT4 weights, |.| up to ~35 vs a single weight's 7) are
    re-quantized to 4-bit differential cap codes via the per-product shift s_a
    (and the B-side shift s_b). (i) is nearly free -- it confirms the paper.
    (ii) is large and is the REAL hardware verdict: a single 4-bit slice
    cannot hold ~2 extra bits of combo range, so DPS-48 at INT4 is
    net-negative (see FORMATS.md 'DPS-48 verdict'). The x0.75 pass win is
    real but does not buy back the precision -- restoring it needs a second
    slice, i.e. 2*48/64 = 1.5x passes, erasing the win.
    """
    m = _model()
    ids = GR.tokenize_greedy(CC.PROMPT, m["vocab"])
    assert len(ids) >= 8
    E = m["embd"][ids].astype(np.float64)
    A_in = CC.rms_rows(E, m["attn_norm"], m["rms_eps"])
    C = CC.compile_matrix("attn_q", m["Wq"], A_in)
    stream = [G.quant_in(C, A_in[t]) for t in range(len(ids))]
    L = DP.lower_matrix_dps(C, stream)
    assert L["Gi"] == 1 and L["Gk"] == 9
    W_ref = m["Wq"].astype(np.float64) * C["smooth"][None, :]
    Gi, Gk = L["Gi"], L["Gk"]
    W6 = C["Wq"].reshape(Gi, 4, 16, Gk, 4, 16)
    A_unr = np.einsum("mab,gaoxbi->gxmoi", DP.U, W6)   # unrounded combos
    zi = np.zeros((Gi, Gk, 48), dtype=np.int64)
    zk = np.zeros((Gk, 48), dtype=np.int64)
    tax_algo, tax_int4 = [], []
    for g in range(2):
        xq4 = np.stack(stream[4 * g:4 * g + 4])
        # (i) exact-arithmetic algorithm path: no s_a/s_b, no conversion
        acc_e, ne, _ = G.mvm_dps48_group(A_unr, zi, zk, DP.V, DP.WT8,
                                         xq4, 1, exact=True)
        assert ne == 48 * Gi * Gk == 432
        # (ii) full INT4 hardware path
        acc, npass, info = G.mvm_dps48_group(
            L["Ahat"], L["s_a"], L["s_b"], DP.V, DP.WT8, xq4, L["D_dps"])
        assert npass == 48 * Gi * Gk == 432        # x0.75 vs classical 576
        assert info["conversions"] == 2 * 16 * npass
        y_dps = acc * (L["D_dps"] / 8.0) * C["dw"][None, :] * C["dx_in"]
        y_exact = acc_e / 8.0 * C["dw"][None, :] * C["dx_in"]
        for f in range(4):
            t = 4 * g + f
            y_ref = W_ref @ (stream[t] * C["dx_in"])
            acc_c, ncls, _ = G.mvm_layer(C["Wq"], stream[t], C["D"])
            assert ncls == 144                        # classical/token = 4*36
            y_cls = acc_c * C["D"] * C["dw"] * C["dx_in"]
            sq_c = DP._sqnr(y_ref, y_cls)
            tax_algo.append(sq_c - DP._sqnr(y_ref, y_exact[f]))
            tax_int4.append(sq_c - DP._sqnr(y_ref, y_dps[f]))
    algo = float(np.mean(tax_algo))
    int4 = float(np.mean(tax_int4))
    print(f"\n    dps48 real Wq: algorithm tax (exact arith) {algo:+.2f} dB "
          f"(paper ~+0.13); INT4-cap tax {int4:+.2f} dB "
          f"(folded-combo re-quant); passes 432 vs 576 (x0.75). "
          f"Verdict: net-negative at INT4 -- see FORMATS.md.")
    # (i) the algorithm itself matches the paper's exact-arithmetic promise:
    assert abs(algo) <= 0.5, "exact-arithmetic algorithm tax should be ~0"
    # (ii) the INT4-cap tax is real, large, and the documented dead-end:
    assert int4 >= 3.0, "expected the large folded-combo INT4 tax to persist"


def test_run_emission():
    with tempfile.TemporaryDirectory() as td:
        r = DP.run_dps48(out=Path(td) / "o", quiet=True)
        pc = r["passes"]
        # exact prompt accounting: 9 tokens = 2 groups + 1 classical
        assert pc["per_4tok_group_total"] == 32832        # 48 * 684
        assert pc["classical_per_token_total"] == 10944
        assert pc["prompt_total"] == 2 * 32832 + 10944 == 76608
        assert pc["prompt_total_classical"] == 9 * 10944 == 98496
        assert pc["ratio_vs_classical"] == 0.75
        # the INT4-cap folded-combo tax is real and positive on every real
        # matrix (net-negative verdict, FORMATS.md); combo tiles stay in range
        for n, f in r["fid"].items():
            assert f["snr_tax_db"] > 0.0, (n, f)
        for n, L in r["low"].items():
            assert np.all(np.abs(L["Ahat"]) <= 15)
            assert np.all(G.wq_from_caps(L["Cp"], L["Cn"]) == L["Ahat"])
        assert (Path(td) / "o" / "digital_config.json").exists()
        print("    dps48 e2e: " + ", ".join(
            f"{n} tax {f['snr_tax_db']:+.2f}dB" for n, f in r["fid"].items()))


def main():
    for t in (test_tensor_verifies, test_float64_matmul_identity,
              test_recombination_exact, test_real_wq_snr_and_passes,
              test_run_emission):
        t()
        print(f"  ok {t.__name__}")
    print("PASS test_dps")


if __name__ == "__main__":
    try:
        main()
    except AssertionError:
        import traceback
        traceback.print_exc()
        print("FAIL test_dps")
        sys.exit(1)
