"""Matched frozen-ADC control with complete ideal reset/share thermal variance.

Reuses the exact radix9 evaluation engine. Old calibrations and runs are immutable;
this isolates one correction, and does not claim the old choices remain optimal.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys

os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
os.environ.setdefault('OMP_NUM_THREADS', '1')
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
import numpy as np
from compiler.metrics import imc_radix9_precision_campaign as legacy

OLD = legacy.OUT
OUT = ROOT / 'build/campaign/reset_noise_precision'
original_prepare = legacy.prepare
original_selfcheck = legacy.selfcheck


def prepare(bank, cu, bits):
    prepared = original_prepare(bank, cu, bits)
    for s in prepared:
        # Independent reset-equilibrated equal array/holder caps retain kT/C.
        # Sum independent holder charges when pooling: Var(Qsum)=kT*sum(C).
        s['thermal'] = np.broadcast_to(legacy.base.KT * 1e15 * s['C'][None, :], s['Q'].shape)
    return prepared


def selfcheck():
    # Preserve the old seeded quantizer identity, then verify the new covariance.
    legacy.prepare = original_prepare
    try:
        original_selfcheck()
    finally:
        legacy.prepare = prepare
    for ratio in (2, 3, 8):
        ca = 7.3
        ch = ca / (ratio - 1)
        r = ch / (ca + ch)
        kt = 1.0
        innovation = (1-r)**2 * kt/ca + kt * ca/(ch*(ca+ch))
        assert np.isclose(r*r*kt/ch + innovation, kt/ch)
        cold = 0.0
        for b in range(1, 12):
            cold = r*r*cold + innovation
            assert np.isclose(cold, kt/ch*(1-r**(2*b)))
    bank = [dict(units=np.array([[5., 11.], [7., 19.]]), B=np.array([0, 1, 9]),
                 dx=np.ones(3), active=np.array([False, True, True]), Q_per_Cu=np.zeros((3, 2)))]
    p = prepare(bank, 4, 10)[0]
    assert np.allclose(p['thermal'], legacy.base.KT*1e15*p['C'][None, :], rtol=1e-14, atol=0)
    print('PASS complete reset/share covariance and independent pooled charge variance', flush=True)


def freeze():
    OUT.mkdir(parents=True, exist_ok=True)
    old_protocol = OLD/'protocol.json'
    p = json.loads(old_protocol.read_text())
    p['sources'][str(old_protocol)] = legacy.base.fingerprint(old_protocol)
    p['sources'][str(Path(__file__))] = legacy.base.fingerprint(__file__)
    p['policies'] = ['min_error']
    p['status'] = 'Frozen matched control before corrected-noise quality evaluation'
    p['calibration'] = 'UNCHANGED old sharing-only min_error ADC choices; isolates reset noise correction, not reoptimized'
    p['physical'] = ('Fully equilibrated initial holder and independent fresh array reset; isolated equal-C sharing; '
                     'stationary Var(Vholder)=kT/C, independent group charges summed. '
                     'Row/reference noise, shared supply covariance, finite-settling noise, programming parasitics, '
                     'mismatch, transistor/PEX validity remain unverified.')
    p['thermal_derivation'] = 'Var_next=Var_old/4+kT/(4C)+kT/(2C); initial kT/C gives stationary kT/C'
    p['evaluation'] = 'Same two exposed first512-token passages and seeds60001/60002; gates unchanged; reserved untouched'
    data = json.dumps(p, indent=2)+'\n'
    path = OUT/'protocol.json'
    if path.exists():
        assert path.read_text() == data, 'Frozen protocol changed'
    else:
        path.write_text(data)
    for cu in p['Cu_fF']:
        src, dst = OLD/f'calibration_Cu{cu}.json', OUT/f'calibration_Cu{cu}.json'
        if dst.exists():
            assert src.read_bytes() == dst.read_bytes()
        else:
            shutil.copyfile(src, dst)
    return p


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cu', type=int, choices=(4, 8), default=4)
    parser.add_argument('--selfcheck', action='store_true')
    parser.add_argument('--freeze', action='store_true')
    args = parser.parse_args()
    legacy.OUT, legacy.prepare, legacy.selfcheck, legacy.freeze = OUT, prepare, selfcheck, freeze
    if args.selfcheck:
        selfcheck()
    elif args.freeze:
        freeze()
    else:
        legacy.evaluate(args.cu)
