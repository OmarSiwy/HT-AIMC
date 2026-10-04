"""Held-out test of selective digital protection, reusing the depth-study net.

Research only: FP32-dequantized Q8_0 or naive RTN INT4 weights, simulated
additive output noise, greedy tokenizer. NOT the complete deployed chip path.
Two unseen local notes x two seeds; no original depth-study passage reused.
Artifacts go to build/research/. Runtime needs numpy and the local GGUF.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time

os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
import numpy as np
from compiler.metrics.depth_budget import Net, Eval, TENSORS, tokenize_greedy


NOTES = Path.home() / "Documents/Projects/OmarSiwy.github.io/Notes/Circuit Design/Analog Design/Analog Compute"
CONFIGS = ("all_analog", "protect_hot_tensor", "protect_sham_tensor", "protect_all_down")


class MaskedNoise:
    """Paired standardized random draws across configurations.

Net currently visits all seven MVMs in each layer in TENSORS order. Recheck
that order if its forward changes; count assertions only catch missing calls.
Later noise scales can differ because protection changes the activations.
Ideal protected outputs model an optimistic digital island, whose energy and
latency must be paid separately. All other MVMs retain the requested noise.
"""
    def __init__(self, seed, config):
        self.rng = np.random.default_rng(seed)
        self.config = config
        self.calls = 0

    def normal(self, loc, scale, size):
        layer, slot = divmod(self.calls, len(TENSORS))
        tensor = TENSORS[slot]
        self.calls += 1
        noise = self.rng.normal(loc, scale, size)
        if protected(layer, tensor, self.config):
            noise.fill(0.0)
        return noise


def protected(layer, tensor, config):
    return tensor == "ffn_down" and (
        config == "protect_all_down"
        or (config == "protect_hot_tensor" and layer == 11)
        or (config == "protect_sham_tensor" and layer == 10)
    )


def self_check():
    assert TENSORS == ("attn_q", "attn_k", "attn_v", "attn_output", "ffn_gate", "ffn_up", "ffn_down")
    a, b = MaskedNoise(1, "all_analog"), MaskedNoise(1, "protect_hot_tensor")
    for call in range(210):
        x, y = a.normal(0, 1, (2, 3)), b.normal(0, 1, (2, 3))
        if call == 11 * 7 + 6:
            assert np.count_nonzero(y) == 0 and np.count_nonzero(x) > 0
        else:
            assert np.array_equal(x, y)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true", help="64-token screening: one note, one seed, one noise level, Q8 only")
    args = parser.parse_args()
    started = time.perf_counter()
    self_check()
    net = Net()
    total_macs = sum(net.L[i][t].size for i in range(net.NL) for t in TENSORS)
    cost = {
        config: sum(net.L[i][t].size for i in range(net.NL) for t in TENSORS
                    if protected(i, t, config)) / total_macs
        for config in CONFIGS
    }
    paths = [next(NOTES.glob(prefix + " *.md")) for prefix in ("27l1", "27h1")]
    if args.quick:
        paths = paths[:1]
    tokens = 64 if args.quick else 256
    seeds = (70,) if args.quick else (70, 71)
    snrs = (36.74,) if args.quick else (28.45, 36.74)
    weight_modes = ("dequantized_Q8_0",) if args.quick else ("dequantized_Q8_0", "naive_RTN_INT4")
    rows, references = [], []
    # These sources were not used to choose layer 11 or ffn_down; those choices
    # were fixed by the old README/AGENTS depth_budget experiment.
    for weight_mode in weight_modes:
        if weight_mode == "naive_RTN_INT4":
            for layer in net.L:
                for name in TENSORS:
                    w = layer[name]
                    step = np.maximum(np.max(np.abs(w), axis=0, keepdims=True) / 7, 1e-30)
                    layer[name] = np.ascontiguousarray(np.clip(np.rint(w / step), -7, 7) * step)
        for path in paths:
            ids = tokenize_greedy(path.read_text(), net.vocab)[:tokens]
            assert len(ids) == tokens
            ev = Eval(net, ids)
            null = ev.score(net(ids))
            assert abs(null["kl"]) < 1e-12
            references.append({"weights": weight_mode, "source": path.name, "PPL": ev.ppl})
            print(f"reference {weight_mode} {path.name[:5]} PPL={ev.ppl:.4f}", flush=True)
            for snr in snrs:
                for config in CONFIGS:
                    for seed in seeds:
                        noise = MaskedNoise(seed, config)
                        logits = net(ids, snr, range(net.NL), noise)
                        assert noise.calls == net.NL * len(TENSORS)
                        metrics = ev.score(logits)
                        row = {"weights": weight_mode, "source": path.name, "snr_dB": snr,
                               "config": config, "seed": seed, **metrics}
                        rows.append(row)
                    latest = rows[-len(seeds):]
                    print(f"  {snr:5.2f} {config:22s} KL={np.mean([r['kl'] for r in latest]):.5f} "
                          f"PPL_ratio={np.mean([r['ppl_ratio'] for r in latest]):.4f}", flush=True)
    suffix = "_quick" if args.quick else ""
    out = ROOT / f"build/research/imc_precision_experiment{suffix}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "scope": f"Full 30-layer SmolLM2-135M; {len(paths)} held-out technical notes x {tokens} tokens x {len(seeds)} seeds; simulated errors",
        "screening_only": args.quick,
        "runtime_s": time.perf_counter() - started,
        "limitations": "Greedy tokenizer; protected math ideal; marginal noise vs each weight-mode reference; no analog KV errors, PVT, energy or timing simulation",
        "numerical_checks": "PASS: zero-noise reference, mask placement, paired draws, 210 MVM calls",
        "MVM_MACs_per_token_excluding_LM_head": total_macs,
        "protected_MVM_MAC_fraction": cost, "references": references, "rows": rows,
    }, indent=2) + "\n")
    print(f"PASS numerical checks; hypothesis outcomes in {out}", flush=True)


if __name__ == "__main__":
    main()
