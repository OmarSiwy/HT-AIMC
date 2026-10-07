"""N10 wildcards: anything outside N1-N9.

`apply(p, tile)` may rewrite the composed tile dict (keys documented in README.md);
the default is the identity. CANDIDATES maps a name to a whole design
(design.make(...) dict) for search.py to score alongside the node sweep.
"""
OPTIONS = {"none": dict(params={}, provenance="identity")}
DEFAULT = "none"
SWEEP = {}
CANDIDATES = {}


def apply(p, tile):
    return tile
