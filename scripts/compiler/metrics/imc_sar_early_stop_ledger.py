"""Frozen-calibration ledger for fewer SAR decisions with the original physical DAC."""
import argparse
import hashlib
import json
import math
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    path = args.directory / 'calibration.json'
    cal = json.loads(path.read_text())
    assert cal['complete']
    rows = []
    for record in cal['records']:
        original = record['selected']
        n = original['bits']
        candidates = []
        missing = []
        for b in range(8, n + 1):
            factor = 2 ** (n - b)
            span = original['span'] * factor
            equivalent = next((r for r in record['grid']
                               if r['bits'] == b and r['span'] == span), None)
            if equivalent is None:
                missing.append(b)
                continue
            total = equivalent['deterministic_MSE'] + original['noise_variance']
            candidate = dict(effective_bits=b, physical_bits=n,
                             physical_reference_span=original['span'],
                             equivalent_grid_span=span,
                             deltaQ_fC=original['deltaQ_fC'] * factor,
                             total=total, clips=equivalent['clips'],
                             decisions=original['conversions'] * b)
            assert math.isclose(2**b * candidate['deltaQ_fC'], 2**n * original['deltaQ_fC'])
            if total <= 1.05 * original['total']:
                candidates.append(candidate)
        selected = min(candidates, key=lambda r: (r['effective_bits'], r['total']))
        rows.append(dict(layer=record['layer'], tensor=record['tensor'], bank=record['bank'],
                         original=original, candidate=selected, unexplored_depths=missing))
    before = sum(r['original']['ADC_decisions'] for r in rows) / 128
    after = sum(r['candidate']['decisions'] for r in rows) / 128
    result = dict(status='SPECULATIVE implementation; VERIFIED offline arithmetic and cost accounting only',
                  calibration_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                  source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  protocol='Each bank deterministic calibration MSE plus ORIGINAL noise <=1.05 times original total. No full-network quality guarantee. Existing grid only; unexplored depths are not rejected.',
                  quantizer='clip(floor(Q/delta+0.5), -2^(b-1), 2^(b-1)-1)*delta. Ties round toward positive infinity. Positive endpoint is nominal half-range minus delta; endpoint clipping must be preserved. A physical early-stop SAR needs the corresponding half-coarse-LSB threshold/centering, not merely truncating a full-resolution output.',
                  hardware='Original physical DAC bits, connected C, reference holder C, Vref and reference CV^2 proxy unchanged. Only comparator/logic decisions reduced. No reference-energy, area, conversion-clock or full-converter claim; threshold centering and omitted-bit reset activity remain unverified.',
                  original_decisions_per_token=before, candidate_decisions_per_token=after,
                  decision_reduction_fraction=1-after/before,
                  original_proxy=sum(r['original']['total'] for r in rows),
                  candidate_proxy=sum(r['candidate']['total'] for r in rows),
                  original_clips=sum(r['original']['clips'] for r in rows),
                  candidate_clips=sum(r['candidate']['clips'] for r in rows),
                  changed_banks=sum(r['candidate']['effective_bits'] != r['original']['bits'] for r in rows),
                  unchanged_connected_plus_reference_C_fF=sum(r['original']['connected_C_fF']+r['original']['reference_holder_C_fF'] for r in rows),
                  rows=rows)
    output = args.directory / 'adc_fixed_dac_early_stop_1p05.json'
    assert not output.exists()
    output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k != 'rows'}, indent=2))
    print('PASS fixed full range, preserved physical noise/capacitance and per-bank five-percent proxy bound')


if __name__ == '__main__':
    main()
