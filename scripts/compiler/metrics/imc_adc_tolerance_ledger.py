"""Offline per-bank ADC cost frontier inside a frozen five-percent error budget."""
import hashlib
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'build/campaign/group128_precision_r50'


def cost(row):
    return row['connected_C_fF']+row['reference_holder_C_fF'],row['ADC_decisions']


def summarize(rows):
    settings={}
    for r in rows:
        key=(r['bits'],r['span']);settings[key]=settings.get(key,0)+r['conversions']/128
    return dict(connected_plus_reference_C_fF=sum(cost(r)[0] for r in rows),
        decisions_per_token=sum(r['ADC_decisions'] for r in rows)/128,
        conversions_per_token=sum(r['conversions'] for r in rows)/128,
        calibration_clips=sum(r['clips'] for r in rows),
        summed_perbank_proxy=sum(r['total'] for r in rows),
        settings=[dict(bits=b,span=s,conversions_per_token=n) for (b,s),n in sorted(settings.items())])


def main():
    path=OUT/'calibration.json';cal=json.loads(path.read_text());assert cal['complete']
    rows=[]
    for record in cal['records']:
        best=record['selected'];allowed=[r for r in record['grid'] if r['total']<=1.05*best['total']]
        frontier=[r for r in allowed if not any(all(a<=b for a,b in zip(cost(other),cost(r))) and cost(other)!=cost(r) for other in allowed)]
        # Depth and paid holder allocation are monotonic; tie-break by actual calibrated error.
        candidate=min(frontier,key=lambda r:(cost(r)[1],cost(r)[0],r['total'],r['span']))
        assert candidate['total']<=1.05*best['total']
        assert all(a<=b for a,b in zip(cost(candidate),cost(best)))
        rows.append(dict(layer=record['layer'],tensor=record['tensor'],bank=record['bank'],
            original=best,candidate=candidate,proxy_ratio=candidate['total']/best['total'],
            changed=candidate!=best,frontier=frontier))
    result=dict(status='Offline candidate ledger only; requires fresh complete-depth quality and source-frozen protocol before use',
        calibration_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        constraint='Each MVM/bank calibrated deterministic MSE plus declared2kT/C+50uV variance <=1.05*its frozen best. This is not a five-percent full-network KL/PPL guarantee.',
        costs='ADC decisions and computational connectedC plus independent reference-holderC. Fine reference granularity, span-dependent DAC switching/reference generation, clock and comparator energy are not fully priced.',
        tie_break='Minimum decisions then minimum paidC then minimum calibration proxy. Thus reference span not chosen arbitrarily at equal hardware cost.',
        original=summarize([r['original'] for r in rows]),candidate=summarize([r['candidate'] for r in rows]),
        changed_banks=sum(r['changed'] for r in rows),max_proxy_ratio=max(r['proxy_ratio'] for r in rows),rows=rows)
    output=OUT/'adc_tolerance_1p05.json';assert not output.exists();output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('rows',)},indent=2))
    print('PASS per-bank tolerance, paid cost dominance and frozen calibration ledger')


if __name__=='__main__':main()
