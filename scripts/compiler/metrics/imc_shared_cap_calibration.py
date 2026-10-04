"""Fixed shared-site mismatch and legal pre-sum redundant programming screen.

This is a coefficient/covariance experiment, not an inference or circuit pass.
"""
import hashlib
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
import numpy as np
from compiler.metrics.imc_fixed_cap_mismatch import coefficient_variance, HIST, PDK
from compiler.metrics.imc_redundant_weight_calibration import cap_error


def main():
    out = ROOT/'build/campaign/shared_cap_calibration'
    out.mkdir(parents=True, exist_ok=True)
    path = out/'result.json'; assert not path.exists()
    h = np.array(json.loads(HIST.read_text())['histogram'])
    rng = np.random.default_rng(913411)
    weights = rng.choice(np.arange(-128, 128), size=(256, 256), p=h/h.sum())
    assert weights.min() >= -127
    q = weights.ravel()
    low0 = np.sign(q)*(abs(q)%8); high0 = (q-low0)//8
    x = rng.standard_normal((128, 256))
    probes = {'white': x, 'coherent': np.ones((1, 256))}
    _, sigma, _ = coefficient_variance([15])
    rows = []
    for die in (1, 2):
        # S uses a nested subset of the same physical-site normal draws.
        rd = np.random.default_rng(913500+die)
        physical = rd.standard_normal((2, 256, 256, 4))*sigma
        measurement = rd.standard_normal(physical.shape)*2.**np.arange(4)
        for S in (1, 4, 8, 16):
            sites = 256//S
            def expand(a):
                return np.tile(a[:, :sites], (1, S, 1, 1)).reshape(2, -1, 4)
            true = expand(physical)
            baseline = cap_error(low0, true[0])+8*cap_error(high0, true[1])
            assert np.array_equal(true.reshape(2, S, sites, 256, 4)[:, 0],
                                  true.reshape(2, S, sites, 256, 4)[:, -1])
            candidates = []
            for high in (np.floor_divide(q, 8), np.floor_divide(q, 8)+1):
                low = q-8*high
                valid = (abs(low)<=7)&(abs(high)<=15)
                candidates.append((low, high, valid,
                    cap_error(low, true[0])+8*cap_error(high, true[1])))
            for cal in (0., .001, .005):
                measured = true+cal*expand(measurement)
                scores = [np.where(valid, abs(cap_error(lo, measured[0])+
                          8*cap_error(hi, measured[1])), np.inf)
                          for lo, hi, valid, _ in candidates]
                choice = np.argmin(scores, axis=0)
                lo, hi, error = [np.where(choice==0, candidates[0][k], candidates[1][k])
                                 for k in (0, 1, 3)]
                assert np.array_equal(lo+8*hi, q)
                if cal == 0: assert np.all(abs(error)<=abs(baseline)+1e-12)
                record = dict(die=die,sharing=S,relative_cap_calibration_RMS=cal,
                    fixed_coefficient_RMS=float(np.sqrt(np.mean(error**2))),
                    baseline_fixed_coefficient_RMS=float(np.sqrt(np.mean(baseline**2))),
                    code_changed_fraction=float(np.mean((lo!=low0)|(hi!=high0))),
                    mean_active_units=float(np.mean(abs(lo)+abs(hi))))
                for name, activation in probes.items():
                    exact = activation@weights
                    delta = activation@error.reshape(weights.shape)
                    assert np.array_equal(delta, activation@error.reshape(weights.shape))
                    record[name+'_relative_MVM_RMS'] = float(np.linalg.norm(delta)/np.linalg.norm(exact))
                    record[name+'_baseline_relative_MVM_RMS'] = float(np.linalg.norm(activation@baseline.reshape(weights.shape))/np.linalg.norm(exact))
                rows.append(record)
    # A shared gain's covariance depends on the signed sum at that site.
    # N aligned equal contributions give S times independent-site variance.
    covariance = []
    for S in (1, 4, 8, 16):
        aligned = np.ones((256//S, S))
        alternating = np.tile([1., -1.], 128).reshape(256//S, S)
        independent = float(np.sum(aligned**2))
        shared = float(np.sum(aligned.sum(axis=1)**2))
        assert shared/independent == S
        covariance.append(dict(sharing=S,aligned_variance_ratio=shared/independent,
            alternating_variance=float(np.sum(alternating.sum(axis=1)**2))))
    ppa = []
    for S in (1, 4, 8, 16):
        ppa.append(dict(sharing=S,physical_sites_per_256row_column=256//S,
            SRAM_bits_per_stored_weight=8,additional_choice_bits_per_stored_weight=1,
            magnitude_caps_fF_per_weight_min22=88/S,
            magnitude_caps_fF_per_weight_measured_two4bit=120/S,
            conservative_matched_holder_fF_per_weight=88/S+240/256,
            bank_conversions_per_256row_column=2*S,
            binary_activation_plane_slots_per_256row_block=9*S,
            weight_payload_bits_per_256row_column=8*256,
            offline_calibration_bit_coefficients_per_256row_column=8*256//S,
            column_ADC_count_if_parallel_banks=2,
            scope='No SRAM/decoder/mux/ADC/holder layout area or energy inferred from these counts. Holder entry is all-code capacity plus two120fF column floors; actual codes/ADC padding require allocation.'))
    sources = [Path(__file__), HIST, PDK, ROOT/'scripts/compiler/metrics/imc_fixed_cap_mismatch.py',
               ROOT/'scripts/compiler/metrics/imc_redundant_weight_calibration.py']
    path.write_text(json.dumps(dict(status='PASS_FIXED_SITE_AND_EXACT_CODE_CHECKS_NOT_SYSTEM_OR_HARDWARE_VALIDATION',
        sources={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        seed=913411,weight_source='Independent samples from exact106M-weight histogram; not actual layer ordering or full-network activations',
        schedule='Each256-row block is split into S phases. Phase s programs256/S reused sites, executes nine binary activation planes with two parallel magnitude banks, converts each bank, and adds phase results digitally. No gain correction after mixed-site sums.',
        calibration='Isolate one physical site and bit during a dedicated calibration read. Eight measured bit coefficients per site guide exact redundant radix8 programming. Fixed measurement error per physical bit, shared across both candidate encodings and every use. Inference stores code/choice only; no per-weight error oracle.',
        limitations='Numerator errors only; ideal calibration access/normalization assumed. Achieving the stated coefficient-measurement error needs a physical calibration experiment. No holder/radix/switch-state/ADC/row-DAC mismatch, read noise, dynamic noise, settling or full-depth quality included. S1 is paired with this frozen sample, not earlier unrelated dies.',
        rows=rows,covariance_controls=covariance,counts=ppa),indent=2)+'\n')
    print('PASS shared physical-site reuse, exact legal programming, fixed measurement error, oracle coefficient bound and covariance counterexamples')
    for row in rows:
        if row['relative_cap_calibration_RMS']==.005: print(row)


if __name__ == '__main__': main()
