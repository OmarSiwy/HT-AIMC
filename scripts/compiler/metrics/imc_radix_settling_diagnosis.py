"""Read existing radix traces; predict a settling-tail correction, no SPICE.

Fits use only the six existing calibration words. The predicted held-out
correction assumes linear recurrence and unchanged switching edges; it is
an experiment-selection diagnostic, not a new circuit result.
"""
import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]


def diagnose(case):
    path = ROOT / case["artifact"] / "trace.csv"
    data = np.loadtxt(path)
    time_ns = data[:, 0] * 1e9
    replay = case["accumulator_replay"]
    bits = case["accumulation_bits"]
    actual_bits = replay["physical_share_operations_per_word"]
    zero_bits = sorted(set(actual_bits + [bits]))
    counts = np.r_[[bits] * 6, zero_bits, actual_bits]
    ends = np.cumsum(counts)
    starts = np.r_[0, ends[:-1]]
    ncal = 6 * bits
    slot = case["cycle_ns"]
    sample = 3 * case["evaluate_ns"] + 1.6
    frames = np.arange(len(case["inputs"])) * slot + sample

    def at(offset):
        return np.stack([np.interp(frames + offset, time_ns, data[:, k]) - .9
                         for k in range(9, 17)], axis=1)

    early, late = at(7) - at(6), at(7.9) - at(7)
    taus = np.linspace(.3, 6, 10000)
    ratios = (np.exp(-1 / taus) - np.exp(-1.9 / taus)) / (1 - np.exp(-1 / taus))
    fitted_tau = []
    for k in range(8):
        ratio = np.dot(early[:ncal, k], late[:ncal, k]) / np.dot(early[:ncal, k], early[:ncal, k])
        fitted_tau.append(float(taus[np.argmin(abs(ratios - ratio))]))
    tail = late / (np.exp(.9 / np.array(fitted_tau)) - 1)
    held = np.stack([np.interp(ends * slot - .1, time_ns, data[:, k]) - .9
                     for k in range(9, 17)], axis=1)
    plane = np.array(case["inputs"]) @ np.array(case["weights"]).T
    wanted = np.stack([(plane[a:b] * (2. ** np.arange(B))[:, None]).sum(0)
                       for a, b, B in zip(starts, ends, counts)])
    correction = np.stack([(tail[a:b] * (.5 ** np.arange(B - 1, -1, -1))[:, None]).sum(0)
                           for a, b, B in zip(starts, ends, counts)])
    results = []
    for fraction in (0, .5, 1):
        adjusted = held + fraction * correction
        normalized = np.stack([(row - adjusted[6 + zero_bits.index(B)]) * 2. ** (B - bits)
                               for row, B in zip(adjusted, counts)])
        for origin in (False, True):
            if origin:
                gain = (wanted[:6] * normalized[:6]).sum(0) / (wanted[:6] ** 2).sum(0)
                offset = np.zeros(8)
            else:
                gain, offset = np.array([np.polyfit(wanted[:6, k], normalized[:6, k], 1)
                                         for k in range(8)]).T
            error = (normalized - offset) / gain - wanted
            heldout = error[6 + len(zero_bits):]
            rms = float(np.sqrt(np.mean(heldout ** 2)))
            if fraction == 0 and not origin:
                assert abs(rms - replay["rms_error_MAC"]) < 1e-6
            results.append(dict(tail_correction_fraction=fraction, zero_anchored_gain=origin,
                heldout_rms_MAC=rms, heldout_max_MAC=float(np.max(abs(heldout))),
                calibration_rms_MAC=float(np.sqrt(np.mean(error[:6] ** 2)))))
    return dict(corner=case["corner"], rows=case["rows"], source=str(path.relative_to(ROOT)),
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(), calibration_planes=ncal,
        fitted_tail_tau_ns=fitted_tau, late_dVdt_rms_uV_ns=float(np.sqrt(np.mean((late / .9) ** 2)) * 1e6),
        extrapolated_tail_rms_uV=float(np.sqrt(np.mean(tail ** 2)) * 1e6), results=results)


if __name__ == "__main__":
    source = json.loads((ROOT / "build/sim/imc_sizing_research.json").read_text())
    result = dict(scope=__doc__, cases=[diagnose(c) for c in source["large_dynamic_accumulator"]],
                  checks="PASS: reconstructs both existing full-word RMS results before any correction")
    out = ROOT / "build/research/imc_radix_settling_diagnosis.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(result["checks"], out)
