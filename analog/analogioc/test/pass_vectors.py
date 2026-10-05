"""Compiler tile pass -> analogioc test vectors (INTERFACE.md §10).

    python3 pass_vectors.py <pass_dir> <out_dir>    writes weights.hex + vectors.json

weights.hex: 16 lines, line i = row i's 136-bit row word (34 hex digits, §7.1 w_data
format: column j at [8j+7:8j], Cp low nibble, Cn high nibble, j = 16 checksum).
vectors.json: the pass, its rail config and the golden expectation (golden.model, bit-true).

Importable: the digital tbs (digital/analogioc/test/test_analogioc.py) build the same
vectors in-process, including whole-matrix tiles from programming/<m>.npz (§7.4).
ponytail: refs.json (ladder rails for D) is left to the analog tb, which owns specs.py.
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
from golden import model as G  # noqa: E402

OUT = ROOT / "scripts/compiler/out"


def row_words(Cp, Cn, chk):
    """Cp/Cn indexed [j][i] (16 cols x 16 rows), chk[i] -> 16 row words (ints).
    Column 16 is the differential split of chk: Cp = max(chk, 0), Cn = max(-chk, 0)."""
    words = []
    for i in range(16):
        w = 0
        for j in range(17):
            if j < 16:
                cp, cn = int(Cp[j][i]), int(Cn[j][i])
            else:
                cp, cn = max(int(chk[i]), 0), max(-int(chk[i]), 0)
            assert 0 <= cp <= 15 and 0 <= cn <= 15
            w |= (cp | cn << 4) << (8 * j)
        words.append(w)
    return words


def expect(Cp, Cn, chk, chk_e, s, xq, D, budget, rq, relu=False):
    """Golden observation points of one pass (golden.tile_mvm_caps), with the rail
    values the RTL exposes when cfg_tile_cnt = 1."""
    Cp, Cn, chk, chk_e, s, xq = (np.asarray(a, dtype=np.int64) for a in (Cp, Cn, chk, chk_e, s, xq))
    t = G.tile_mvm_caps(Cp, Cn, xq, D, s=s, chk=chk, chk_e=chk_e, relu=relu)
    c = t["chk"]
    y12 = t["y12"]
    corr = int(G._half_up_div(int(np.dot(chk_e, xq)), D))
    resid = int(np.dot(s, y12)) - (c["y12"] << G.CHK_SHIFT) - corr   # signed, rail order
    if not relu:
        assert abs(resid) == c["residual"]
    q = G.requant_int8(G.slice_combine(y12), rq["scale"], rq["shift"], rq["offset"])
    return {
        "code_hi": [int(v) for v in t["conv_hi"]["code"]] + [int(c["conv_hi"]["code"][0])],
        "code_lo": [int(v) for v in t["conv_lo"]["code"]] + [int(c["conv_lo"]["code"][0])],
        "y12": [int(v) for v in y12], "y12_chk": int(c["y12"]),
        "corr": corr, "residual": resid, "flag": int(abs(resid) > budget),
        "q": [int(v) for v in q],
    }


def requant_fields(dig, matrix, ct):
    r = dig["matrices"][matrix]["requant"]
    sl = slice(ct * 16, ct * 16 + 16)
    return {k: list(r[k][sl]) for k in ("scale", "shift", "offset")}


def pass_vectors(pass_dir, dig=None, relu=False):
    """One representative pass directory -> vectors dict (§10), checked against the
    compiler's own expected.json."""
    pass_dir = Path(pass_dir)
    e = json.loads((pass_dir / "expected.json").read_text())
    dig = dig or json.loads((pass_dir.parents[1] / "digital_config.json").read_text())
    rq = requant_fields(dig, e["matrix"], e["ct"])
    ex = expect(e["Cp"], e["Cn"], e["chk"], e["chk_e"], e["s"], e["xq"], e["D"], e["budget"], rq, relu)
    if not relu:
        x = e["expected"]
        assert ex["code_hi"][:16] == x["code_hi"] and ex["code_lo"][:16] == x["code_lo"]
        assert ex["y12"] == x["y12"] and ex["y12_chk"] == x["chk_y12"]
        assert abs(ex["residual"]) == x["abft_residual"]
    return {
        "tag": e["tag"], "matrix": e["matrix"], "ct": e["ct"], "rt": e["rt"],
        "D": e["D"], "budget": e["budget"], "s": e["s"], "chk_e": e["chk_e"],
        "xq": e["xq"], "relu": int(relu), "requant": rq,
        "Cp": e["Cp"], "Cn": e["Cn"], "chk": e["chk"],
        "weights": row_words(e["Cp"], e["Cn"], e["chk"]),
        "expected": ex,
    }


def matrix_tile(npz, c, r):
    """(Cp, Cn, chk, chk_e) of tile (c, r) of programming/<m>.npz, Cp/Cn as [j][i]."""
    js, ks = slice(c * 16, c * 16 + 16), slice(r * 16, r * 16 + 16)
    return npz["Cp"][js, ks], npz["Cn"][js, ks], npz["chk"][c, r], npz["e4"][c, r]


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    v = pass_vectors(sys.argv[1])
    out = Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    (out / "weights.hex").write_text("".join(f"{w:034x}\n" for w in v["weights"]))
    (out / "vectors.json").write_text(json.dumps(v, indent=1))
    print(f"pass_vectors: {v['tag']} -> {out}")
