"""Frozen-calibration outlier routing and exact radix arithmetic; no SPICE.

All seven complete compiler matrices are evaluated. Static channel choices use
positions 0:6 only; positions 6:9 are scored. Dynamic routing is an upper control
for reducing max activation magnitude with exactly k excluded input channels.
"""
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
from compiler.metrics.imc_radix_budget import accumulate, digit_count

OUT = ROOT / "build/research/imc_outlier_planes.json"
NAMES = ("attn_q", "attn_k", "attn_v", "attn_o", "ffn_gate", "ffn_up", "ffn_down")
NCAL = 6
READ_NOISE = 200e-6


def selected_channels(x, count, policy):
    """Stable index tie-break; selection never examines weights or test errors."""
    if policy == "static":
        priority = np.max(np.abs(x[:NCAL]), axis=0)
        chosen = np.argsort(-priority, kind="stable")[:count]
        return np.broadcast_to(chosen, (len(x), count))
    assert policy == "dynamic"
    return np.argsort(-np.abs(x), axis=1, kind="stable")[:, :count]


def partition(x, chosen):
    precise = np.zeros_like(x)
    np.put_along_axis(precise, chosen, np.take_along_axis(x, chosen, axis=1), axis=1)
    analog = x - precise
    assert np.array_equal(analog + precise, x)
    return analog, precise


def selfcheck():
    # Every signed8 code, including -128, and zero/canceling reductions.
    x = np.column_stack((np.arange(-128, 128), np.zeros(256, dtype=int)))
    w = np.array([[7, -7], [-7, 7], [0, 0]])
    for policy in ("static", "dynamic"):
        for k in (0, 1, 2):
            picked = selected_channels(x, k, policy)
            a, d = partition(x, picked)
            got, _, _ = accumulate(w, a, np.full(3, .01), np.full(3, 2e-13),
                                   np.full(3, 2e-13), dynamic=True)
            assert np.allclose(got + d @ w.T, x @ w.T, atol=1e-10)
    cancel = np.array([[127, 127], [-128, -128], [0, 0]])
    assert np.array_equal(cancel @ np.array([[1, -1]]).T, np.zeros((3, 1)))
    tie = np.array([[3, -3, 1]] * 9)
    assert np.array_equal(selected_channels(tie, 1, "static")[:, 0], np.zeros(9))
    before = selected_channels(tie, 1, "static").copy()
    tie[NCAL:, 2] = -128
    assert np.array_equal(before, selected_channels(tie, 1, "static"))


def histogram(values):
    return {str(i): int(np.count_nonzero(values == i)) for i in range(9)}


def evaluate(name, w, x, rows, policy, count):
    nt = len(x) - NCAL
    nout, nin = w.shape
    precise_sum = np.zeros((len(x), nout), dtype=np.int64)
    analog_sum = np.zeros_like(precise_sum)
    block_records = []
    coefficient = np.zeros((nt, nout))
    held_square = 0.0
    chosen_weights = precise_macs = nonzero_precise_macs = 0
    mean_b_numerator = mean_base_numerator = 0
    analog_events = 0
    for first in range(0, nin, rows):
        wb, xb = w[:, first:first+rows], x[:, first:first+rows]
        nr = xb.shape[1]
        k = min(count, nr)
        chosen = selected_channels(xb, k, policy)
        xa, xd = partition(xb, chosen)
        ya, yd = xa @ wb.T, xd @ wb.T
        assert np.array_equal(ya + yd, xb @ wb.T)
        analog_sum += ya
        precise_sum += yd
        base_b = digit_count(xb, True)[NCAL:]
        b = digit_count(xa, True)[NCAL:]
        assert np.all(b <= base_b)
        if policy == "dynamic" and k < nr:
            remaining_max = np.sort(np.abs(xb[NCAL:]), axis=1)[:, nr-k-1]
            assert np.array_equal(np.max(np.abs(xa[NCAL:]), axis=1), remaining_max)

        # Reuse the exact equal-cap radix identity: h = gain*y / 2**B.
        # Excluded physical weight caps remain connected to zero-excited rows;
        # array capacitance and the matched accumulator therefore stay fixed.
        carr = (120 + 4 * np.sum(np.abs(wb), axis=1)) * 1e-15
        gain = 4e-15 * .45 / carr
        h = gain * ya[NCAL:] / (2.0**b[:, None])
        assert np.allclose(h * (2.0**b[:, None]) / gain, ya[NCAL:], atol=1e-9)
        scale = (2.0**b[:, None]) / gain
        coefficient += scale**2 * (b > 0)[:, None]
        held_square += float(np.sum(h**2))
        analog_events += int(np.count_nonzero(b)) * nout
        chosen_weights += k*nout
        precise_macs += nt*k*nout
        nonzero_precise_macs += int(np.count_nonzero(xd[NCAL:]))*nout
        mean_b_numerator += int(b.sum())*nr*nout
        mean_base_numerator += int(base_b.sum())*nr*nout
        block_records.append(dict(first_channel=first, actual_rows=nr,
            chosen_local_indices=(chosen[0].tolist() if policy == "static" else chosen[NCAL:].tolist()),
            heldout_base_B=base_b.tolist(), heldout_analog_B=b.tolist(),
            heldout_scale_gain=(2.0**(base_b-b)).tolist()))
    exact = x @ w.T
    assert np.array_equal(analog_sum + precise_sum, exact)
    useful = nt*nin*nout
    coeff_sum = float(coefficient.sum())
    signal_sum = float(np.sum(exact[NCAL:].astype(float)**2))
    bvals = np.array([d["heldout_analog_B"] for d in block_records])
    basevals = np.array([d["heldout_base_B"] for d in block_records])
    reads = precise_macs  # Worst-case selected values processed, including zero.
    address_bits = math.ceil(math.log2(rows))
    return dict(tensor=name, rows=rows, policy=policy, selected_rows_per_block=count,
        input_channels=nin, output_channels=nout, heldout_tokens=nt,
        block_count=len(block_records), useful_MACs=useful,
        precise_MACs=precise_macs, nonzero_activation_precise_MACs=nonzero_precise_macs,
        precise_MAC_fraction=precise_macs/useful,
        useful_MAC_weighted_mean_B=mean_b_numerator/useful,
        baseline_useful_MAC_weighted_mean_B=mean_base_numerator/useful,
        B_histogram=histogram(bvals), B_drop_histogram=histogram(basevals-bvals),
        block_token_fraction_B_reduced=float(np.mean(bvals < basevals)),
        block_token_fraction_gain_at_least_two=float(np.mean(basevals-bvals >= 1)),
        gain_proxy_mean=float(np.mean(2.0**(basevals-bvals))),
        read_noise_coefficient_sum=coeff_sum, exact_output_square_sum=signal_sum,
        output_value_count=nt*nout, final_data_ADC_events=analog_events,
        held_voltage_rms_mV=math.sqrt(held_square/(nt*nout*len(block_records)))*1e3,
        adc_read_only_200uV_output_rms_MAC=math.sqrt(READ_NOISE**2*coeff_sum/(nt*nout)),
        adc_read_only_200uV_SNR_dB=10*math.log10(signal_sum/(READ_NOISE**2*coeff_sum)),
        adc_read_only_allowance_uV_for_illustrative_36p74=1e6*math.sqrt(signal_sum/(10**3.674*coeff_sum)),
        static_duplicate_weight_bits=(chosen_weights*4 if policy == "static" else 0),
        dynamic_full_weight_read_access_bits=(w.size*4 if policy == "dynamic" and count else 0),
        precise_weight_read_bits_all_test_tokens=reads*4,
        static_index_metadata_bits=(len(block_records)*count*address_bits if policy == "static" else 0),
        dynamic_index_bits_all_test_tokens=(nt*len(block_records)*count*address_bits if policy == "dynamic" else 0),
        blocks=block_records)


def main():
    selfcheck()
    records, fingerprints = [], {}
    for name in NAMES:
        wp, xp = (ROOT/f"scripts/compiler/out/{folder}/{name}.npz" for folder in ("programming", "acts"))
        for p in (wp, xp):
            fingerprints[str(p.relative_to(ROOT))] = hashlib.sha256(p.read_bytes()).hexdigest()
        with np.load(wp) as z:
            w = z["Wq"].astype(np.int64)
        with np.load(xp) as z:
            x = z["xq"].astype(np.int64)
        assert x.shape == (9, w.shape[1])
        assert np.all((-128 <= x) & (x <= 127)) and np.all((-7 <= w) & (w <= 7))
        for rows in (16, 64, 128):
            baseline = evaluate(name, w, x, rows, "static", 0)
            records.append(baseline)
            for policy in ("static", "dynamic"):
                for count in (1, 2, 4):
                    r = evaluate(name, w, x, rows, policy, count)
                    r["read_noise_tolerance_gain_vs_baseline"] = math.sqrt(
                        baseline["read_noise_coefficient_sum"]/r["read_noise_coefficient_sum"])
                    records.append(r)
    summaries = []
    for rows in (16, 64, 128):
        base = [r for r in records if r["rows"] == rows and not r["selected_rows_per_block"]]
        base_coeff = sum(r["read_noise_coefficient_sum"] for r in base)
        for policy, count in [("static", 0)] + [(p, k) for p in ("static", "dynamic") for k in (1, 2, 4)]:
            group = [r for r in records if (r["rows"], r["policy"], r["selected_rows_per_block"]) == (rows, policy, count)]
            total = sum(r["useful_MACs"] for r in group)
            coeff = sum(r["read_noise_coefficient_sum"] for r in group)
            gain = math.sqrt(base_coeff/coeff)
            summaries.append(dict(rows=rows, policy=policy, selected_rows_per_block=count,
                precise_MAC_fraction=sum(r["precise_MACs"] for r in group)/total,
                useful_MAC_weighted_mean_B=sum(r["useful_MAC_weighted_mean_B"]*r["useful_MACs"] for r in group)/total,
                read_noise_tolerance_gain_vs_baseline=gain,
                illustrative_134uV_scaled_allowance_uV=134*gain,
                meets_134_to_200uV_variance_ratio_screen=gain >= 200/134,
                static_duplicate_weight_bits=sum(r["static_duplicate_weight_bits"] for r in group),
                dynamic_full_weight_read_access_bits=sum(r["dynamic_full_weight_read_access_bits"] for r in group),
                precise_weight_read_bits_all_test_tokens=sum(r["precise_weight_read_bits_all_test_tokens"] for r in group),
                static_index_metadata_bits=sum(r["static_index_metadata_bits"] for r in group),
                dynamic_index_bits_all_test_tokens=sum(r["dynamic_index_bits_all_test_tokens"] for r in group)))
    report = dict(scope="Exact integer routing and ideal equal-cap radix identities on frozen layer-0 artifacts; no SPICE or model-quality validation.",
        calibration="Static largest calibration max(abs(x)) on positions0:6; stable channel-index tie-break. All fixed policies reported on6:9; no held-out winner selected.",
        relative_screen_scope="200/134 is a unitless improvement heuristic. The134uV reference arose from a different16x8 FFN-down fixture with other modeled noise; multiplying it by a pooled R128 read-only gain does not establish an absolute ADC allowance. Pooled coefficients use raw integer-output units, not dequantized or quality-weighted errors.",
        noise_scope="Independent final-ADC voltage noise only, summed across input blocks. No quantization, share/reset/filter noise, mismatch, clipping, offset or circuit parasitics. Readout allowances are optimistic conditional screens, not measured ADC performance.",
        physical_scope="4fF unit, .45V excitation,120fF fixed load, Cacc=Carray per output. Selected rows remain physically present with zero excitation. Dynamic weights require random access or a digital shadow of the entire matrix; static duplicate bits are lower-bound W4 payloads.",
        metadata_scope="Index payloads only. Excludes selectors, runtime magnitude comparisons, B metadata, checksum/regeneration, alignment, buffering, fanout, control, digital-adder cost and conversion of analog integer scale.",
        fingerprints=fingerprints, records=records, summaries=summaries, checks="PASS")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2)+"\n")
    print(f"PASS: {len(records)} full-tensor cases, signed8 radix/residual identities and calibration isolation; {OUT}")
    for s in summaries:
        if s["rows"] == 128:
            print(json.dumps(s))


if __name__ == "__main__":
    main()
