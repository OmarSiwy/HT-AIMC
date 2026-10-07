"""N4 number formats & operand encoding.

Default W4A8: the repo's INT4-weight x INT8-activation contract (scripts/golden/model.py).
Weight slices follow the pass-count law in scripts/compiler/formats.py (n_slices:
sign rides the differential pair, 4 magnitude bits per slice). Input planes: the
measured sky130 dynamic high-bit-skipping schedule averages 6 planes per A8 word
(7/6/5, IMC_SIZING_RESEARCH.md) -> abits - 2 (derived).
"""
from compiler.formats import n_slices

OPTIONS = {
    "w4a8": dict(params=dict(wbits=4, abits=8, kv_bits=16),
                 provenance="repo contract INT4xINT8 (golden/model.py); measured sky130"),
    "w8a8": dict(params=dict(wbits=8, abits=8, kv_bits=16), provenance="two W4 slices (formats.n_slices)"),
    "w4a4": dict(params=dict(wbits=4, abits=4, kv_bits=16), provenance="projected; quality unverified"),
}
DEFAULT = "w4a8"
SWEEP = dict(wbits=[2, 4, 8], abits=[4, 6, 8], kv_bits=[4, 8, 16])


def fmt(p):
    wb, ab = int(p["wbits"]), int(p["abits"])
    planes = p.get("input_planes") or (ab - 2 if ab >= 6 else ab)
    return dict(wbits=wb, abits=ab, slices=n_slices(wb), input_planes=planes,
                kv_bits=int(p.get("kv_bits", 16)), bits_product=wb * ab)
