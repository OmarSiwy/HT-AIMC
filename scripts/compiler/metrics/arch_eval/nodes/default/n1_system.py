"""N1 system & memory: residency vs streaming, dies, fabric, KV, concurrency.

"streaming": each die is a full replica with its own HBM stack (ARCH_METRIC default
memory); weights are re-streamed from HBM and rewritten into double-buffered arrays
once per prefill wave and once per decode step (shared by the B concurrent streams).
KV lives in the same stack. Per-die metrics do not depend on the replica count, so dies=1.
"resident": one weight copy spread over ceil(tiles needed / tiles per die) dies,
layer-pipelined over the die-to-die link; KV in each die's HBM. Write once (27n2: the
one-time programming is amortized away and not charged).
Concurrency B is chosen by metric.py under KV capacity, the per-stream floor and the
power cap.
"""
OPTIONS = {
    "streaming": dict(params=dict(mode="streaming", double_buffer=True),
                      provenance="ARCH_METRIC default memory (HBM3-class, 819 GB/s, 24 GB, 4 pJ/bit)"),
    "resident": dict(params=dict(mode="resident", double_buffer=False),
                     provenance="ARCH_METRIC die-to-die 2 TB/s, 0.5 pJ/bit"),
}
DEFAULT = "resident"
SWEEP = {}   # B is swept by metric.py; KV bits live in n4_formats


def plan(p, wl, tile, die, knobs):
    need = die["tiles_needed"]
    if p["mode"] == "resident":
        return dict(mode="resident", dies=max(1, -(-need // die["n_tiles"])))
    return dict(mode="streaming", dies=1)
