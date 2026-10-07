"""A Design: {node id -> option name} plus a flat params dict (JSON-serializable).

Effective params = each chosen option's "params" merged in node order (n1..n10),
then design["params"] on top. Param names are global: a design param overrides
any option param of the same name.
"""
import json

NODES = ("n1_system", "n2_domain", "n3_cell", "n4_formats", "n5_array",
         "n6_readout", "n7_dataflow", "n8_quality", "n9_circuits", "n10_wildcards")


def make(nodes=None, params=None, name="design"):
    return dict(name=name, nodes=dict(nodes or {}), params=dict(params or {}))


def load(path):
    with open(path) as f:
        d = json.load(f)
    return make(d.get("nodes"), d.get("params"), d.get("name", str(path)))


def dump(design, path):
    with open(path, "w") as f:
        json.dump(design, f, indent=1, sort_keys=True)
