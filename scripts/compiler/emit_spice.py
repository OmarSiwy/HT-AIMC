"""ngspice include-file emitters for compiled tile passes (A2/A3 consume).

Formats documented in FORMATS.md. Two file kinds:
  .param include : one `.param name=value` per line (cap codes, D, timing).
  PWL include    : independent voltage sources driving the differential row
                   inputs with the PWM schedule of one nibble window.
Everything is literal numbers (no ngspice expressions) so any simulator in
the flake (ngspice 43 / Xyce / VACASK) parses it.
"""

import json
import numpy as np

VDD = 1.8
T_EDGE = 0.1e-9   # PWL rise/fall; symmetric, so pulse charge = width * VDD
T_START = 5e-9    # settle time before the PWM window opens


def _f(x):
    """Compact spice float."""
    return f"{float(x):.6g}"


def emit_params(path, params, comment=""):
    """Write a .param include file: params = dict name -> number."""
    lines = [f"* {comment}"] if comment else []
    lines += [f".param {k}={_f(v)}" for k, v in params.items()]
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def emit_caps(path, Cp, Cn, chk=None, comment=""):
    """Cap-code .param include for one 16x16(+chk) tile.

    Names: wcp_r{i}c{j} / wcn_r{i}c{j}, i=row 0..15, j=col 0..15; the
    checksum column (differential, signed chk -> Cp/Cn split) is column 16.
    """
    p = {}
    O, I = np.asarray(Cp).shape
    for i in range(I):
        for j in range(O):
            p[f"wcp_r{i}c{j}"] = int(Cp[j, i])
            p[f"wcn_r{i}c{j}"] = int(Cn[j, i])
    if chk is not None:
        for i in range(I):
            p[f"wcp_r{i}c16"] = int(max(chk[i], 0))
            p[f"wcn_r{i}c16"] = int(max(-chk[i], 0))
    emit_params(path, p, comment)


def pwl_pulse(width, v_hi=VDD, t0=T_START, t_edge=T_EDGE):
    """PWL point list for one rectangular pulse (flat 0 if width <= 0)."""
    if width <= 0:
        return [(0.0, 0.0)]
    return [(0.0, 0.0), (t0, 0.0), (t0 + t_edge, v_hi),
            (t0 + t_edge + width, v_hi), (t0 + 2 * t_edge + width, 0.0)]


def emit_pwm(path, xq, window, t_q, vdd=VDD, comment=""):
    """PWL sources for one nibble window ('lo' -> lo*t_q, 'hi' -> hi*16*t_q).

    Row i drives nodes xin_p_r{i} (positive sign) / xin_n_r{i} (negative);
    the unused rail is held at 0 by its own flat source. Sources are named
    vxin_p_r{i} / vxin_n_r{i}.
    """
    xq = np.asarray(xq, dtype=np.int64)
    sign = np.where(xq < 0, -1, 1)
    m = np.abs(xq)
    nib = (m & 15) if window == "lo" else (m >> 4)
    unit = t_q if window == "lo" else 16.0 * t_q
    lines = [f"* PWM {window} window: pulse width = nibble * {_f(unit)} s"
             + (f" ({comment})" if comment else "")]
    for i, (sg, n) in enumerate(zip(sign, nib)):
        for rail, active in (("p", sg > 0), ("n", sg < 0)):
            pts = pwl_pulse(float(n) * unit) if active and n > 0 else [(0.0, 0.0)]
            flat = " ".join(f"{_f(t)} {_f(v)}" for t, v in pts)
            lines.append(f"vxin_{rail}_r{i} xin_{rail}_r{i} 0 PWL({flat})")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def emit_pass_dir(dirpath, p, t_q):
    """Write one representative tile pass: caps/params/pwm includes + expected.json.

    p: dict from compile.py (Wq/Cp/Cn/chk/s/xq/D/budget + expected obs points).
    """
    dirpath.mkdir(parents=True, exist_ok=True)
    emit_caps(dirpath / "caps.spice", p["Cp"], p["Cn"], p["chk"],
              comment=f"pass {p['tag']} {p['matrix']} tile(c={p['ct']},r={p['rt']})")
    emit_pwm(dirpath / "pwm_lo.spice", p["xq"], "lo", t_q, comment=p["tag"])
    emit_pwm(dirpath / "pwm_hi.spice", p["xq"], "hi", t_q, comment=p["tag"])
    emit_params(dirpath / "params.spice", {
        "t_q": t_q, "vdd": VDD, "t_start": T_START, "t_edge": T_EDGE,
        "t_win_lo": T_START + 16 * t_q + 2 * T_EDGE,
        "t_win_hi": T_START + 128 * t_q + 2 * T_EDGE,
        "dcode": p["D"], "abft_budget": p["budget"],
    }, comment=f"pass {p['tag']}")
    with open(dirpath / "expected.json", "w") as f:
        json.dump(p, f, indent=1, default=_json_np)


def _json_np(o):
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    raise TypeError(type(o))
