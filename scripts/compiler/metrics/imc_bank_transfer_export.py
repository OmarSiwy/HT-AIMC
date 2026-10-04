"""Export measured clamped-bank charge separately from column admittance.

Two exposed stimuli define a diagnostic affine fit; remaining stimuli test
that fit. This is not independent calibration, an array model or a noise test.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def affine_residual(x, y):
    assert len(x) == len(y) and len(x) > 2 and x[0] != x[1]
    slope = (y[1] - y[0]) / (x[1] - x[0])
    intercept = y[0] - slope * x[0]
    return slope, intercept, y - (slope * x + intercept)


def export(source, output):
    assert not output.exists(), f"Preserve evidence: {output}"
    data = json.loads(source.read_text())
    x = np.array(data['amplitudes_V'])
    assert data['quadrature_protocol_v2']['oracle_pass']
    rows = []
    for row in data['rows']:
        q = np.array(row['charge_fC'])
        slope, offset, residual = affine_residual(x, q)
        expected = (data.get('sign') or 1) * row['code'] * data['unit_fF']
        norm = max(row['code'], 1) * data['unit_fF'] * .45
        rows.append(dict(mode=row['mode'], code=row['code'],
            charge_fC=q.tolist(), column_admittance=row['port_loading'],
            ideal_signal_coefficient_fF=expected,
            diagnostic_signal_coefficient_fF=float(slope),
            diagnostic_offset_fC=float(offset),
            diagnostic_residual_fC=residual.tolist(),
            diagnostic_held_max_residual_fraction_FS=float(max(abs(residual[2:])) / norm),
            original_max_error_fraction_FS=row['max_error_fraction_per_weight_FS']))
    result = dict(source=str(source), source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        source_deck_sha256=data['deck_sha256'], source_physical_gates=data['pass_by_mode'],
        amplitudes_V=x.tolist(), bits=data['bits'], sign=data['sign'],
        sign_routing=data['sign_routing'], coupon_projection=data['coupon_projection'],
        width_n_um=data['width_um'], width_p_um=data['width_p_um'],
        corner=data['corner'], temp_C=data['temp_C'], column_bias_V=data.get('column_bias_V',.9), rows=rows,
        diagnostic_fit_indices=[0, 1], diagnostic_check_indices=list(range(2, len(x))),
        scope='Measured integrated charge and AC column loading are separate observables. '
              'All stimuli were previously exposed; affine fit is diagnostic only. '
              'Clamped columns, ideal drivers, no array loading, sampled noise or independent calibration. '
              'Do not replace the charge numerator with total column capacitance.')
    output.write_text(json.dumps(result, indent=2) + '\n')
    for mode in ('grounded', 'bypass'):
        worst = max((r for r in rows if r['mode'] == mode),
                    key=lambda r: r['diagnostic_held_max_residual_fraction_FS'])
        print(mode, 'diagnostic residual FS', worst['diagnostic_held_max_residual_fraction_FS'],
              'code', worst['code'])


if __name__ == '__main__':
    x = np.array([.4, -.1, .2, -.3])
    slope, offset, residual = affine_residual(x, -12 * x + .03)
    assert np.isclose(slope, -12) and np.isclose(offset, .03)
    assert np.max(abs(residual)) < 1e-14
    y = -12 * x + .03
    y[2] += .007
    assert np.isclose(affine_residual(x, y)[2][2], .007)
    print('PASS affine coefficient, offset and held-stimulus residual self-check')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    export(**vars(parser.parse_args()))
