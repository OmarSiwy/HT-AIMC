"""Check completed pulse evidence in an otherwise incomplete bank transient.

A completed error witness can falsify a gate. An incomplete trace cannot
qualify the whole stimulus sequence, even when every completed pulse passes.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def audit(reference, partial, output):
    assert not output.exists(), f"Preserve evidence: {output}"
    ref = json.loads(reference.read_text())
    manifest = partial / 'manifest.json'
    meta = json.loads(manifest.read_text())
    for key in ('bits', 'width_um', 'width_p_um', 'corner', 'temp_C', 'unit_fF',
                'settle_ns', 'slot_ns', 'stop_ns', 'amplitudes_V',
                'coupon_projection', 'sign', 'sign_mux_scale', 'sign_routing'):
        assert ref[key] == meta[key], f'Different fixture: {key}'
    assert ref.get('column_bias_V', .9) == meta.get('column_bias_V', .9)
    assert meta['step_ps'] < ref['step_ps']
    raw = np.loadtxt(partial / 'transient.csv')
    fields = [(mode, code) for mode in ('compiled', 'grounded', 'bypass')
              for code in range(2 ** meta['bits'])]
    assert raw.shape[1] == len(fields) + 7 and np.all(np.isfinite(raw))
    t = raw[:, 0]
    assert np.all(np.diff(t) >= 0) and t[-1] < meta['stop_ns'] * 1e-9 - 1e-12
    records = []
    for index, amplitude in enumerate(meta['amplitudes_V']):
        start = (index * meta['slot_ns'] + 2) * 1e-9
        end = (index * meta['slot_ns'] + 2.2 + meta['settle_ns'] - .01) * 1e-9
        if t[-1] < end:
            break
        grid = np.r_[start, t[(t > start) & (t < end)], end]
        for j, ((mode, code), original) in enumerate(zip(fields, ref['rows'], strict=True)):
            assert (mode, code) == (original['mode'], original['code'])
            charge = np.trapezoid(np.interp(grid, t, raw[:, 5 + j]), grid) * 1e15
            ideal = (meta.get('sign') or 1) * amplitude * code * meta['unit_fF']
            norm = max(code, 1) * meta['unit_fF'] * .45
            records.append(dict(pulse=index, mode=mode, code=code,
                amplitude_V=amplitude, charge_fC=float(charge),
                error_fraction_FS=float(abs(charge - ideal) / norm),
                original_error_fraction_FS=abs(original['error_fC'][index]) / norm,
                timestep_difference_fraction_FS=float(abs(charge - original['charge_fC'][index]) / norm)))
    assert records
    oracle = max(r['error_fraction_FS'] for r in records if r['mode'] == 'compiled')
    difference = max(r['timestep_difference_fraction_FS'] for r in records)
    witnesses = [r for r in records if r['mode'] != 'compiled'
                 and r['error_fraction_FS'] > .001
                 and r['original_error_fraction_FS'] > .001]
    numerical = oracle <= .0001 and difference <= .0001
    result = dict(reference=str(reference), partial=str(partial),
        reference_sha256=hashlib.sha256(reference.read_bytes()).hexdigest(),
        manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        last_time_s=float(t[-1]), completed_pulses=1 + max(r['pulse'] for r in records),
        oracle_max_fraction_FS=oracle, timestep_difference_max_fraction_FS=difference,
        prefix_numerical_pass=numerical, repeated_failure_witnesses=witnesses,
        physical_failure_supported=bool(numerical and witnesses), whole_sequence_qualified=False,
        scope=__doc__, records=records)
    output.write_text(json.dumps(result, indent=2) + '\n')
    print('PASS' if numerical else 'FAIL', 'PREFIX NUMERICAL CONTROL',
          'repeated physical failures', len(witnesses), 'whole sequence remains incomplete')
    assert numerical, 'Prefix numerical budget failed; evidence retained'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reference', type=Path)
    parser.add_argument('partial', type=Path)
    parser.add_argument('output', type=Path)
    audit(**vars(parser.parse_args()))
