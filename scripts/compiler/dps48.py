"""DPS rank-48 bilinear lowering (task B, compile.py --dps48).

THE ALGORITHM: Dumas-Pernet-Sedoglavic's rank-48 non-commutative scheme for
4x4 matrix multiplication over any ring with 1/2 (arXiv:2506.13242; the
paper's sec_strassen Table 'DPS rank-48': passes x0.75, net random tax
+0.13 dB, bias S1 18.1 dB, DR 4 bits / 2 RMS). The explicit decomposition
is NOT in the arXiv abstract/paper body; it was retrieved from Sedoglavic's
fast-matrix-multiplication catalogue (https://fmm.univ-lille.fr/4x4x4.html,
file 4x4x4_tensor.mpl.bz2) and verified EXACTLY against the <4,4,4> matmul
tensor in rational arithmetic before embedding (re-verified by verify() /
test_dps.py). Coefficient structure, as embedded:
  U (A-side / weights)     in {-1, 0, +1}, up to 16 terms per product
  V (B-side / activations) in {-1, 0, +1}, up to 16 terms per product
  W (C-side / outputs)     in {+-1/2, +-1/4, +-1/8} (exact shifts digitally)
Convention (verified): C[i][j] = sum_m W_m[j][i] * (sum_ab U_m[a,b] A[a,b])
* (sum_cd V_m[c,d] B[c,d]). WT8 below stores 8 * W_m^T so the C-side
recombination is integer; the global /8 folds into the requant shift.

THE MAPPING (paper sec_strassen asymmetry):
  A-side combos are FREE at runtime: each product's combined 16x16 tile is
    programmed once as differential cap codes. Combined entries span up to
    16*7 = 112 > the 4b cap range, so each product tile is rounded by a
    per-product power-of-2 shift s_a (Ahat = round(A/2^s_a), |Ahat| <= 15;
    2^s_a returns exactly in the digital recombination). This rounding is
    the documented folded-combo tax, measured in the manifest.
  B-side combos are cheap digital INT adds before PWM: b = sum V*xq spans
    up to 16*127; a per-(product, super-column) shift s_b sized on the REAL
    calibration stream brings |b| <= 255 = the native 2-nibble PWM range
    (runtime: round-half-away shift + clip, like any activation quant).
  C-side recombination is digital adds after conversion:
    acc[token f, tile 4gi+e] += WT8[m,e,f] * (y14_m << (s_a + s_b)),
    y_hat = acc * D_dps/8 * dw * dx  (the /8 lives in the requant shift).
Tokens run in groups of 4 (the j-axis of the <4,4,4> block product);
remainder tokens run the frozen classical schedule. Storage: 48/16 = 3x
programmed tiles per super-block ((R/4)^l of law:bilinear).

Golden reference: golden.model.mvm_dps48_group (bit-true, same rails).
Everything here is flag-gated: the default compile path never imports this.

Run: python3 scripts/compiler/compile.py --dps48   -> scripts/compiler/out_dps48/
"""

import json
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from golden import model as G                                    # noqa: E402

TILE = 16
RANK = 48

# 48 products: 'U(16) V(16) WT8(16)' row-major 4x4; U,V chars +/-/0;
# WT8 chars: 1/2/4 = +1/+2/+4, a/b/c = -1/-2/-4 (WT8[i][j] = 8*W[j][i]).
_TABLE = """\
-+++-++++----+++ 00000000-000-000 000000002b02b20b
-000+000+000-000 0+0+0-0-00000000 c00c400400000000
00+000-000-000-0 0+0000000+000000 00000c4000000c40
00--00--00+-00+- 000000000++0+0-0 0c220c22002b002b
---++++----+---+ +0--+0--00000000 0000000000020002
++-+--+---+-++-+ 00000+0+00000+0+ 00002b200000b2b0
000+000-000-000- 00000-0000000+00 040c00000c040000
---++++----++++- +00-0000+00-0000 0000000b0000000b
00++00--+-00+-00 --++++--+---+--- 1aa1a11a1a111a11
+000+000+000-000 0+++00000---0000 4004000040040000
---++++-+++----+ 00000+0+00000-0- 000b000000020000
0+0+-0+00+0+-0+0 ---++---+++-+--- 2b11001a2b11001a
00+000-000+000+0 +0--0000-0++0000 0c4000000c400000
00+000+000-000-0 00000000+0-0-0+0 04c004c000000000
-0-0-0+0+0+0-0+0 0+000000-0000000 2b22bb2bb2bbbb2b
--+-++-+--+-++-+ +00-0000-00+0000 b2b00000b2b00000
++00++00-+00-+00 0--0+0-000000000 00b200b240224022
-+++-++++---+--- 0000+0-00000+0-0 00002b020000b20b
0+0+-0+00-0-+0-0 +---++-+-+++++-+ 00a1b2aa001a2b11
-+---+--+-+++-++ 0000-0+00000+0-0 0020000000b00000
00+000-000-000+0 000000000+0+0+0+ 000000000c4004c0
+0+00-0++0+00-0+ +++--++++++-+--- 001a00aa001a00aa
000-000+000-000- 0000+0--0000+0-- 0000040c00000c04
+-++-+--+-+++-++ +0---0++00000000 00b0002000000000
++00--0000+-00+- ++--++---++++--- a1aa1a11a1a1a1a1
+-+++-+++-++-+-- 000000000---0--- 0000000000b00020
0+000+000+000+00 0--00--000000000 00000000c0c0c0c0
00--00---+00+-00 -++++----------- 1a111a111aa1a11a
+----+++-+++-+++ 0-000+0000000000 2b02b20b00000000
000+000+000+000+ 000000000--00++0 040c040c00000000
0+000-000+000-00 +00--00+00000000 c0c0404000000000
-0-00+0-+0+00-0+ -+++--+--+++++-+ 00aa001a001100a1
--+-++-+++-+++-+ 0-000-0000000000 000000002b202b20
00++00--00-+00+- 00000000+00-0-0- 002b00b20c2204bb
++00++0000+-00-+ +---+---++++---- 1a1a1a1a1a11a1aa
+-+++-+++-+++-++ 0--000000--00000 000000b0000000b0
0-000-000-000+00 00000---00000--- 000040400000c0c0
0+0+0+0-0+0+0-0+ 0000+0--00000--- b2bb222bb2bbbbb2
0-000-000+000-00 0000+0000000-000 c0c0000040400000
++00--00-+00+-00 -00+0-0-00000000 c0bb4022002b00b2
+---+---+---+--- 0++000000--00000 b20b0000b20b0000
000+000-000+000- 00000000+00-+00- 00000000040c0c04
-000-000+000-000 +0000000+0000000 0000c00c0000c00c
+0+0+0-0+0+0-0+0 -0++00000---0000 bb2b2b22bb2bb2bb
--+---+-++-+--+- 00000000-000+000 b2b0b2b000000000
+++-+++-+++----+ 000000000---0+++ 000b000b00000000
-000-000+000+000 +0-0+0-000000000 0000000040044004
0+0+0+0-0-0-0+0- 00000+000000+000 222bb2bbbbb2b2bb"""

_SIGN = {"+": 1, "-": -1, "0": 0}
_W8 = {"0": 0, "1": 1, "2": 2, "4": 4, "a": -1, "b": -2, "c": -4}


def _parse():
    U = np.zeros((RANK, 4, 4), dtype=np.int64)
    V = np.zeros((RANK, 4, 4), dtype=np.int64)
    WT8 = np.zeros((RANK, 4, 4), dtype=np.int64)
    for m, line in enumerate(_TABLE.splitlines()):
        u, v, w = line.split()
        for p in range(16):
            U[m, p // 4, p % 4] = _SIGN[u[p]]
            V[m, p // 4, p % 4] = _SIGN[v[p]]
            WT8[m, p // 4, p % 4] = _W8[w[p]]
    return U, V, WT8


U, V, WT8 = _parse()


def verify():
    """Exact Brent-equation check of the embedded tensor (integer arithmetic,
    the /8 carried as a x8 on the expected tensor). Raises on any deviation."""
    T = np.einsum("mab,mcd,mif->abcdif", U, V, WT8)
    i_, k_, j_ = np.meshgrid(np.arange(4), np.arange(4), np.arange(4),
                             indexing="ij")
    exp = np.zeros((4, 4, 4, 4, 4, 4), dtype=np.int64)
    exp[i_, k_, k_, j_, i_, j_] = 8       # C[i,j] = sum_k A[i,k] B[k,j]
    assert np.array_equal(T, exp), "rank-48 tensor does not verify"
    return True


# ---------------------------------------------------------------------------
# lowering
# ---------------------------------------------------------------------------

def _min_shift(maxabs, limit):
    """Smallest s >= 0 with round_half_away(maxabs / 2^s) <= limit
    (elementwise; monotone in |x| so it bounds every entry)."""
    s = np.zeros(np.shape(maxabs), dtype=np.int64)
    for _ in range(8):
        bad = G._half_up_div(maxabs, 1 << s) > limit
        if not np.any(bad):
            return s
        s += bad
    raise AssertionError("shift search did not converge")


def lower_matrix_dps(C, stream_xq):
    """Lower one compiled matrix (compile.compile_matrix dict) through the
    rank-48 scheme against its REAL activation stream.

    Returns dict(Ahat (Gi,Gk,48,16,16) |.|<=15, Cp, Cn, s_a (Gi,Gk,48),
    s_b (Gk,48), D_dps, scale/shift (requant with the /8 folded), Gi, Gk,
    n_groups, tax bookkeeping fields).
    """
    Wq = C["Wq"]
    O, I = Wq.shape
    Oc, Rc = O // TILE, I // TILE
    assert Oc % 4 == 0 and Rc % 4 == 0, \
        "real-model tile grids are 4-aligned (4/36/96)"
    Gi, Gk = Oc // 4, Rc // 4
    W6 = Wq.reshape(Gi, 4, TILE, Gk, 4, TILE)
    # A-side: folded weight combos, per-product power-of-2 renormalization
    A = np.einsum("mab,gaoxbi->gxmoi", U, W6)          # (Gi,Gk,48,16,16)
    s_a = _min_shift(np.abs(A).max(axis=(3, 4)), G.CAP_MAX)
    Ahat = G._half_up_div(A, (1 << s_a)[..., None, None])
    Cp, Cn = G.caps_from_wq(Ahat)
    # B-side: per-(super-column, product) shift sized on the real stream
    XQ = np.stack(stream_xq)                            # (T, I)
    T = XQ.shape[0]
    n_groups = T // 4
    maxb = np.zeros((Gk, RANK), dtype=np.int64)
    for g in range(n_groups):
        X6 = XQ[4 * g:4 * g + 4].reshape(4, Gk, 4, TILE)
        b = np.einsum("mcd,dxci->xmi", V, X6)
        maxb = np.maximum(maxb, np.abs(b).max(axis=2))
    s_b = _min_shift(maxb, 255)
    # D sizing: +-4 sigma over every (product, nibble-window) mac of the
    # real calibration groups (same law as the classical conv_scale_D)
    macs = []
    for g in range(n_groups):
        X6 = XQ[4 * g:4 * g + 4].reshape(4, Gk, 4, TILE)
        b = np.einsum("mcd,dxci->xmi", V, X6)
        bh = np.clip(G._half_up_div(b, 1 << s_b[:, :, None]), -255, 255)
        sg, hi, lo = G.pwm_nibbles(bh)
        for n in (sg * hi, sg * lo):
            macs.append(np.einsum("gxmoi,xmi->gxmo", Ahat, n).ravel())
    D_dps = G.conv_scale_D(np.concatenate(macs))
    scale, shift = G.make_requant(
        D_dps * C["dw"] * C["dx_in"] / (C["dy"] * 8.0))
    return {"Ahat": Ahat, "Cp": Cp, "Cn": Cn, "s_a": s_a, "s_b": s_b,
            "D_dps": D_dps, "scale": scale, "shift": shift,
            "Gi": Gi, "Gk": Gk, "n_groups": n_groups,
            "s_a_max": int(s_a.max()), "s_b_max": int(s_b.max())}


def pass_counts(shapes, T):
    """EXACT tile-pass accounting: 4-token groups run 48*Gi*Gk passes per
    super-block grid; the T mod 4 remainder tokens run classical Oc*Rc."""
    per = {}
    for n, (O, I) in shapes.items():
        Oc, Rc = O // TILE, I // TILE
        grp = RANK * (Oc // 4) * (Rc // 4)
        per[n] = {"per_4tok_group": grp, "classical_per_token": Oc * Rc,
                  "prompt_total": (T // 4) * grp + (T % 4) * Oc * Rc}
    tot_grp = sum(v["per_4tok_group"] for v in per.values())
    tot_cls = sum(v["classical_per_token"] for v in per.values())
    return {
        "per_matrix": per,
        "per_4tok_group_total": tot_grp,
        "classical_per_token_total": tot_cls,
        "steady_state_per_token": tot_grp / 4.0,
        "ratio_vs_classical": tot_grp / (4.0 * tot_cls),
        "prompt_tokens": T,
        "prompt_total": (T // 4) * tot_grp + (T % 4) * tot_cls,
        "prompt_total_classical": T * tot_cls,
        "law": "48/64 per 4x4x4 super-block of (col-tile group, row-tile "
               "group, token group); remainder tokens classical",
    }


# ---------------------------------------------------------------------------
# full flow: compile the real model through the rank-48 schedule
# ---------------------------------------------------------------------------

def run_dps48(prompt=None, out=None, model_path=None, quiet=False):
    from compiler import compile as CC
    t0 = time.time()
    log = (lambda *a: None) if quiet else print
    prompt = prompt or CC.PROMPT
    out = Path(out) if out else CC.OUT.parent / "out_dps48"
    (out / "programming").mkdir(parents=True, exist_ok=True)
    verify()
    # frozen classical compile (to a scratch dir) supplies the calibrated
    # matrices + the bit-true real activation streams
    with tempfile.TemporaryDirectory() as td:
        res = CC.run(prompt=prompt, out=Path(td),
                     model_path=model_path or CC.MODEL, quiet=True)
    mats, stream = res["mats"], res["stream"]
    ids = res["ids"]
    T = len(ids)
    log(f"[dps48] classical baseline compiled ({time.time() - t0:.1f}s)")

    m = CC.load_model(model_path or CC.MODEL)
    fid, low = {}, {}
    for n, C in mats.items():
        L = lower_matrix_dps(C, stream[n])
        low[n] = L
        # fidelity on the last FULL token group, quantized golden path
        g = L["n_groups"] - 1
        xq4 = np.stack(stream[n][4 * g:4 * g + 4])
        acc, npass, _ = G.mvm_dps48_group(
            L["Ahat"], L["s_a"], L["s_b"], V, WT8, xq4, L["D_dps"])
        assert npass == RANK * L["Gi"] * L["Gk"]
        y_dps = acc * (L["D_dps"] / 8.0) * C["dw"][None, :] * C["dx_in"]
        # references: float64 (smoothed domain) + classical quantized path
        sq_c, sq_d = [], []
        Xs_ref, W_ref = _smoothed_ref(m, C, n, res)
        for f in range(4):
            t = 4 * g + f
            y_ref = W_ref @ Xs_ref[t]
            acc_c, _, _ = G.mvm_layer(C["Wq"], stream[n][t], C["D"])
            y_cls = acc_c * C["D"] * C["dw"] * C["dx_in"]
            sq_c.append(_sqnr(y_ref, y_cls))
            sq_d.append(_sqnr(y_ref, y_dps[f]))
        fid[n] = {"mvm_sqnr_classical_db": round(float(np.mean(sq_c)), 2),
                  "mvm_sqnr_dps48_db": round(float(np.mean(sq_d)), 2),
                  "snr_tax_db": round(float(np.mean(sq_c) - np.mean(sq_d)), 2),
                  "D_classical": C["D"], "D_dps": L["D_dps"],
                  "s_a_max": L["s_a_max"], "s_b_max": L["s_b_max"]}
        np.savez_compressed(
            out / "programming" / f"{n}.npz",
            Ahat=L["Ahat"].astype(np.int8), Cp=L["Cp"], Cn=L["Cn"],
            s_a=L["s_a"].astype(np.uint8), s_b=L["s_b"].astype(np.uint8),
            U=U, V=V, WT8=WT8, D_dps=L["D_dps"],
            scale=L["scale"], shift=L["shift"],
            Wq=C["Wq"], D_classical=C["D"], scale_classical=C["scale"],
            shift_classical=C["shift"], smooth=C["smooth"],
            dw=C["dw"], dx_in=C["dx_in"], dy=C["dy"])
        log(f"[dps48] {n}: D {C['D']}->{L['D_dps']} "
            f"SQNR {fid[n]['mvm_sqnr_classical_db']}->"
            f"{fid[n]['mvm_sqnr_dps48_db']} dB "
            f"(tax {fid[n]['snr_tax_db']:+.2f}) ({time.time() - t0:.1f}s)")

    shapes = {n: mats[n]["Wq"].shape for n in mats}
    pc = pass_counts(shapes, T)
    (out / "passes.json").write_text(json.dumps(pc, indent=1))
    dig = {
        "note": "DPS rank-48 recombination schedule (task B). Per product m "
                "of each (gi,gk) super-block: B-side digital pre-adds "
                "b = sum_cd V[m,c,d]*xq[token d, block 4gk+c], then "
                "b_hat = clip(round_half_away(b / 2^s_b[gk,m]), +-255) "
                "drives the standard 2-nibble PWM pass on the programmed "
                "combo tile Ahat[gi,gk,m]; C-side digital post-adds "
                "acc[token f, tile 4gi+e] += WT8[m,e,f] * "
                "(y14 << (s_a[gi,gk,m]+s_b[gk,m])). Requant scale folds "
                "D_dps*dw*dx/(dy*8) (the /8 = the scheme's fractional "
                "output coefficients). Remainder (T mod 4) tokens run the "
                "frozen classical schedule with the classical requant.",
        "abft": None,
        "abft_note": "checksum column disabled under --dps48: the audit "
                     "relation holds per programmed COMBO matrix, but the "
                     "chk-cap range (CHK_SHIFT=3, +-15) cannot carry the "
                     "combined-tile column sums; end-to-end Freivalds probe "
                     "on the recombination tree is the paper's upgrade path.",
        "matrices": {},
    }
    for n, L in low.items():
        O, I = mats[n]["Wq"].shape
        sh_span = L["s_a_max"] + L["s_b_max"]
        comb = 8191 * (1 << sh_span) * int(np.abs(WT8).sum(axis=0).max())
        req = int(np.ceil(np.log2(comb * max(L["Gk"], 1)))) + 1
        dig["matrices"][n] = {
            "shape": [O, I], "Gi": L["Gi"], "Gk": L["Gk"],
            "D_dps": L["D_dps"], "s_b": L["s_b"].tolist(),
            "shift_span_max": sh_span, "required_acc_bits": req,
            "requant_dps": {"scale": L["scale"].tolist(),
                            "shift": L["shift"].tolist()},
            "requant_classical": {"scale": mats[n]["scale"].tolist(),
                                  "shift": mats[n]["shift"].tolist()},
        }
    (out / "digital_config.json").write_text(json.dumps(dig, indent=1))
    manifest = {
        "model": str(model_path or CC.MODEL), "prompt": prompt,
        "token_ids": ids, "flow": "DPS rank-48 bilinear lowering (task B)",
        "decomposition": {
            "name": "DPS rank-48 <4,4,4>", "rank": RANK,
            "source": "arXiv:2506.13242 (Dumas-Pernet-Sedoglavic); tensor "
                      "file from https://fmm.univ-lille.fr/4x4x4.html, "
                      "verified exactly (verify() Brent equations)",
            "coeffs": {"U": "{-1,0,+1}", "V": "{-1,0,+1}",
                       "W": "{+-1/2,+-1/4,+-1/8}"},
        },
        "fidelity": fid,
        "pass_counts": {k: pc[k] for k in
                        ("per_4tok_group_total", "steady_state_per_token",
                         "ratio_vs_classical", "prompt_total",
                         "prompt_total_classical")},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    log(f"[dps48] wrote {out} ({time.time() - t0:.1f}s); "
        f"{pc['prompt_total']} passes for the prompt vs "
        f"{pc['prompt_total_classical']} classical "
        f"(steady-state {pc['ratio_vs_classical']:.4f}x)")
    return {"low": low, "fid": fid, "passes": pc, "manifest": manifest,
            "mats": mats, "stream": stream, "out_dir": out}


def _smoothed_ref(m, C, name, res):
    """Float64 reference (smoothed domain) for one matrix: W*smooth and the
    per-token smoothed inputs, reconstructed from the compile products."""
    Xs = np.stack([xq * C["dx_in"] for xq in res["stream"][name]])
    key = {"attn_q": "Wq", "attn_k": "Wk", "attn_v": "Wv", "attn_o": "Wo",
           "ffn_gate": "Wg", "ffn_up": "Wu", "ffn_down": "Wd"}[name]
    return Xs, m[key].astype(np.float64) * C["smooth"][None, :]


def _sqnr(ref, hat):
    e = ref - hat
    return 10 * np.log10(np.mean(ref ** 2) / np.mean(e ** 2)) \
        if np.any(e) else np.inf


if __name__ == "__main__":
    run_dps48()
