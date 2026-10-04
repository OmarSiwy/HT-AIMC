#!/usr/bin/env python3
"""Frozen bounded Gaussian comparator-to-code experiment; no circuit claim."""
import hashlib
import json
import math
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'build/campaign/sar_noise_mapping'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def convert(x, bits, sigma, rho, rng, bounded=False):
    """Unit-LSB binary bisection, with shared + independent decision noise."""
    lo = np.zeros(len(x))
    hi = np.full(len(x), float(2**bits))
    common = rng.standard_normal(len(x)) * sigma * math.sqrt(rho)
    wrong = np.zeros(bits, dtype=np.int64)
    largest_noise = np.zeros(len(x))
    for bit in range(bits):
        midpoint = (lo + hi) / 2
        noise = (rng.uniform(-sigma, sigma, len(x)) if bounded else
                 common + rng.standard_normal(len(x)) * sigma * math.sqrt(1-rho))
        largest_noise = np.maximum(largest_noise, abs(noise))
        decision = x + noise >= midpoint
        wrong[bit] = np.count_nonzero(decision != (x >= midpoint))
        lo = np.where(decision, midpoint, lo)
        hi = np.where(decision, hi, midpoint)
        if bounded:
            assert np.all((x >= lo-sigma) & (x <= hi+sigma))
    output = (lo + hi) / 2
    # This pathwise bound applies also to unbounded Gaussian draws conditional
    # on their actually observed maximum absolute decision noise.
    assert np.all(abs(output-x) <= largest_noise+.5+1e-10)
    return output, wrong


def exact_probabilities(x, bits, sigma):
    """Enumerate all code paths using independent Gaussian CDF products."""
    probabilities = []
    for code in range(2**bits):
        low, high, probability = 0., float(2**bits), 1.
        for bit in range(bits):
            threshold = (low+high)/2
            high_decision = bool(code & (1 << (bits-1-bit)))
            p_high = .5 * math.erfc((threshold-x)/(sigma*math.sqrt(2)))
            probability *= p_high if high_decision else 1-p_high
            if high_decision:
                low = threshold
            else:
                high = threshold
        probabilities.append(probability)
    probabilities = np.array(probabilities)
    assert abs(probabilities.sum()-1) < 2e-14
    return probabilities


def selfcheck():
    rng = np.random.default_rng(975310)
    x = rng.uniform(0, 256, 10000)
    q, _ = convert(x, 8, 0, 0, rng)
    assert np.array_equal(q, np.floor(x)+.5)
    convert(x, 8, 13, 0, rng, bounded=True)
    # rho=1 is exactly a sampled additive-input perturbation, including rails.
    duplicate = np.random.default_rng(975311)
    expected = np.clip(np.floor(x+duplicate.standard_normal(len(x))*3), 0, 255)+.5
    q, _ = convert(x, 8, 3, 1, np.random.default_rng(975311))
    assert np.array_equal(q, expected)
    checks = []
    for value, sigma in ((7.5,.25), (8.,2.), (5.125,4.)):
        p = exact_probabilities(value, 4, sigma)
        sample, _ = convert(np.full(300000, value), 4, sigma, 0, rng)
        empirical = np.bincount(sample.astype(int), minlength=16)/len(sample)
        # Fixed before data: simultaneous generous seven-sigma bin check.
        tolerance = 7*np.sqrt(p*(1-p)/len(sample))+7/len(sample)
        assert np.all(abs(empirical-p) <= tolerance)
        checks.append(dict(input_LSB=value, sigma_LSB=sigma,
                           maximum_probability_error=float(abs(empirical-p).max())))
    return checks


def score(x, q, sigma):
    error = q-x
    ideal_error = np.floor(x)+.5-x
    excess = float(np.mean(error**2)-np.mean(ideal_error**2))
    return dict(bias_LSB=float(error.mean()), rms_total_LSB=float(np.sqrt(np.mean(error**2))),
                variance_centered_LSB2=float(np.var(error)), ideal_quantization_MSE_LSB2=float(np.mean(ideal_error**2)),
                excess_MSE_LSB2=excess,
                equivalent_excess_sigma_LSB=math.sqrt(excess) if excess >= 0 else None,
                excess_sigma_to_comparator_ratio=math.sqrt(excess)/sigma if excess >= 0 else None,
                absolute_error_p99_LSB=float(np.quantile(abs(error), .99)),
                absolute_error_p999_LSB=float(np.quantile(abs(error), .999)),
                absolute_error_max_LSB=float(abs(error).max()),
                changed_code_fraction=float(np.mean(q != np.floor(x)+.5)))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).read_bytes()
    protocol = dict(source_sha256=sha(source), seed=975312, samples_per_case=150000,
                    bits=14, sigma_LSB=[.1,.25,.5,1,2,4,8,16,32,64],
                    correlations=[0.,.5,1.],
                    input_patterns=['central_uniform','major_transition','code_center'],
                    input_definitions={'central_uniform':'Uniform[0.1*2^N,0.9*2^N]',
                                       'major_transition':'Constant 2^(N-1)',
                                       'code_center':'Constant 2^(N-1)+0.5'},
                    boundaries='Saturating unit-width bins; output at bin midpoint',
                    interpretation='Independent decision noise and correlated controls; no transistor or complete converter qualification',
                    source_reference='Liu 2017 CMU thesis chapter4; path probability independently implemented',
                    checks='Noiseless identity; shared-noise identity; bounded-noise invariant; 3 exact 4-bit probability comparisons with frozen7sigma tolerance')
    encoded = (json.dumps(protocol, indent=2)+'\n').encode()
    ppath = OUT/'protocol.json'
    if ppath.exists():
        assert ppath.read_bytes() == encoded, 'Frozen protocol changed'
    else:
        ppath.write_bytes(encoded)
    (OUT/f'source_{sha(source)}.py').write_bytes(source)
    checks = selfcheck()
    rows = []
    rng = np.random.default_rng(protocol['seed'])
    bits, n = protocol['bits'], protocol['samples_per_case']
    for pattern in protocol['input_patterns']:
        x = (rng.uniform(.1*2**bits, .9*2**bits, n) if pattern == 'central_uniform' else
             np.full(n, 2**(bits-1)+(0.5 if pattern == 'code_center' else 0)))
        for sigma in protocol['sigma_LSB']:
            for rho in protocol['correlations']:
                q, wrong = convert(x, bits, sigma, rho, rng)
                rows.append(dict(pattern=pattern, sigma_LSB=sigma, correlation=rho,
                                 incorrect_decisions_by_bit=wrong.tolist(), **score(x,q,sigma)))
    assert Path(__file__).read_bytes() == source and ppath.read_bytes() == encoded
    result = dict(protocol_sha256=sha(encoded), protocol=protocol, checks=checks, results=rows,
                  classification='VERIFIED mathematical Gaussian model; comparator physics and system transfer unverified')
    (OUT/'results.json').write_text(json.dumps(result, indent=2)+'\n')
    for row in rows:
        if row['pattern'] == 'central_uniform' and row['correlation'] == 0:
            print(json.dumps({k:row[k] for k in ('sigma_LSB','rms_total_LSB','excess_sigma_to_comparator_ratio','absolute_error_p999_LSB')}), flush=True)
    print('PASS: frozen noise mapping, exact path probabilities, shared-noise control, bounded-error invariant')


if __name__ == '__main__':
    main()
