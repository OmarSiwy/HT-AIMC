#!/usr/bin/env python3
"""Compiler tests against the REAL model file
(PYTHONPATH=scripts python3 scripts/compiler/test_compile.py). Prints PASS/FAIL.
"""

import json
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compiler.gguf_reader import GGUF, tokenize_greedy, write_fixture_gguf, \
    _bytes_to_unicode  # noqa: E402
from compiler import compile as CC  # noqa: E402
from golden import model as G  # noqa: E402

rng = np.random.default_rng(3)


def test_reader_real_file():
    g = GGUF(str(CC.MODEL))
    assert g.meta["general.architecture"] == "llama"
    assert g.meta["llama.block_count"] == 30
    assert g.meta["llama.embedding_length"] == 576
    assert g.meta["llama.attention.head_count"] == 9
    assert g.meta["llama.attention.head_count_kv"] == 3
    assert g.meta["llama.feed_forward_length"] == 1536
    assert g.meta["llama.vocab_size"] == 49152
    assert len(g.meta["tokenizer.ggml.tokens"]) == 49152
    wq = g.array("blk.0.attn_q.weight")           # Q8_0 dequant
    assert wq.shape == (576, 576) and np.isfinite(wq).all()
    assert 0.05 < wq.std() < 1.0 and np.abs(wq).max() < 20
    wk = g.array("blk.0.attn_k.weight")
    assert wk.shape == (192, 576)
    nrm = g.array("blk.0.attn_norm.weight")       # F32 passthrough
    assert nrm.shape == (576,) and nrm.dtype == np.float32
    emb = g.array("token_embd.weight")
    assert emb.shape == (49152, 576) and 0.01 < emb.std() < 1.0


def test_fixture_roundtrip():
    w8 = rng.normal(0, 1, (8, 64)).astype(np.float32)
    wf = rng.normal(0, 1, (4, 16)).astype(np.float32)
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "fix.gguf"
        write_fixture_gguf(p, {"a.q8": (w8, "q8_0"), "b.f32": (wf, "f32")},
                           meta={"general.architecture": "llama", "n": 3,
                                 "toks": ["x", "yz"]})
        g = GGUF(str(p))
        assert g.meta["general.architecture"] == "llama"
        assert g.meta["n"] == 3 and g.meta["toks"] == ["x", "yz"]
        assert np.array_equal(g.array("b.f32"), wf)
        got = g.array("a.q8")
        d8 = np.max(np.abs(w8.reshape(-1, 32)), axis=1) / 127.0
        step = np.repeat(d8, 32).reshape(w8.shape)
        # quantization d/2 plus f16 storage of the scale (<= d*127/2048)
        assert np.all(np.abs(got - w8) <= step * (0.5 + 127 / 2048) + 1e-6)


def test_tokenizer():
    g = GGUF(str(CC.MODEL))
    vocab = g.meta["tokenizer.ggml.tokens"]
    prompt = "The quick brown fox jumps over the lazy dog"
    ids = tokenize_greedy(prompt, vocab)
    assert ids and all(0 <= i < 49152 for i in ids)
    # surface forms re-join exactly to the byte-encoded prompt
    b2u = _bytes_to_unicode()
    enc = "".join(b2u[b] for b in prompt.encode())
    assert "".join(vocab[i] for i in ids) == enc
    assert vocab[ids[0]] == "The"


def _short_run():
    if not hasattr(_short_run, "res"):
        out = Path(tempfile.mkdtemp(prefix="analogioc_compile_test_"))
        _short_run.res = CC.run(prompt="The quick fox", out=out, quiet=True)
        _short_run.out = out
    return _short_run.res, _short_run.out


def test_fast_pipeline_is_bit_true():
    res, _ = _short_run()
    for name in ("attn_k", "attn_o", "ffn_down"):
        C = res["mats"][name]
        xq = res["stream"][name][-1]
        p = CC.layer_passes(C, xq)
        acc, n, _ = G.mvm_layer(C["Wq"], xq, C["D"])
        assert np.array_equal(p["acc"], acc), name       # vectorized == loop
        assert n == CC.count_passes(C["Wq"].shape)
        out8 = G.requant_int8(acc, C["scale"], C["shift"], C["offset"])
        assert np.array_equal(p["out8"], out8)


def test_pass_counts():
    res, _ = _short_run()
    per_tok = 0
    for name, C in res["mats"].items():
        O, I = C["Wq"].shape
        n_iter = len(list(G.iter_tile_passes(O, I)))
        assert n_iter == CC.count_passes((O, I)) == (O // 16) * (I // 16)
        per_tok += n_iter
    assert per_tok == 10944                       # exact, counted (mandate)


def test_e2e_real_model():
    res, out = _short_run()
    X = res["out"]
    assert np.isfinite(X).all() and 0 < np.abs(X).max() < 1e3
    man = json.loads((out / "manifest.json").read_text())
    dig = json.loads((out / "digital_config.json").read_text())
    pt = json.loads((out / "passes.json").read_text())
    assert pt["tile_passes_per_token_total"] == 10944
    assert len(man["files"]["rep_passes"]) >= 8
    for n, d in dig["matrices"].items():
        sc, sh = np.array(d["requant"]["scale"]), np.array(d["requant"]["shift"])
        assert np.all((sc >= 0) & (sc <= 255)) and np.all((sh >= 0) & (sh <= 24))
        assert sum(d["acc_rounds"]) == d["row_tiles"]
        assert max(d["acc_rounds"], default=1) <= 15          # bacc tile_cnt 4b
        assert d["abft"]["max_clean_residual"] <= d["abft"]["budget"]
    assert (out / "golden_trace.npz").exists()
    tr = np.load(out / "golden_trace.npz")
    assert np.allclose(tr["p"].sum(1), 1)                     # softmax KCL


def test_emitted_pass_files():
    res, out = _short_run()
    dirs = sorted((out / "passes").iterdir())
    assert len(dirs) >= 8
    for d in dirs:
        e = json.loads((d / "expected.json").read_text())
        xq = np.array(e["xq"])
        sg, hi, lo = np.array(e["pwm"]["sign"]), np.array(e["pwm"]["hi"]), \
            np.array(e["pwm"]["lo"])
        # PWM sums match quantized activations (contract test)
        assert np.all(sg * (16 * hi + lo) == xq)
        t_tot = np.array(e["pwm"]["t_lo_s"]) + np.array(e["pwm"]["t_hi_s"])
        assert np.allclose(t_tot, np.abs(xq) * G.TQ_SIM)
        # y12 recombination of the expected codes
        y12 = np.clip(16 * np.array(e["expected"]["code_hi"])
                      + np.array(e["expected"]["code_lo"]), -2048, 2047)
        assert np.array_equal(y12, np.array(e["expected"]["y12"]))
        assert e["expected"]["abft_residual"] <= e["budget"]
        # caps.spice params reproduce the signed tile weights
        caps = {}
        for ln in (d / "caps.spice").read_text().splitlines():
            if ln.startswith(".param"):
                k, v = ln.split()[1].split("=")
                caps[k] = int(v)
        Wt = np.array(e["Wq"])
        for i in range(16):
            for j in range(16):
                assert caps[f"wcp_r{i}c{j}"] - caps[f"wcn_r{i}c{j}"] == Wt[j, i]
            chk_i = caps[f"wcp_r{i}c16"] - caps[f"wcn_r{i}c16"]
            assert chk_i == e["chk"][i]
        # pwm files: 32 sources (16 rows x p/n rails)
        for w in ("pwm_lo.spice", "pwm_hi.spice"):
            srcs = [l for l in (d / w).read_text().splitlines()
                    if l.startswith("vxin_")]
            assert len(srcs) == 32


def main():
    tests = [test_reader_real_file, test_fixture_roundtrip, test_tokenizer,
             test_fast_pipeline_is_bit_true, test_pass_counts,
             test_e2e_real_model, test_emitted_pass_files]
    for t in tests:
        t()
        print(f"  ok {t.__name__}")
    print("PASS test_compile")


if __name__ == "__main__":
    try:
        main()
    except AssertionError:
        import traceback
        traceback.print_exc()
        print("FAIL test_compile")
        sys.exit(1)
