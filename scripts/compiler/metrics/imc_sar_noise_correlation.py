"""Diagnostic: shared read noise versus independent noise at each SAR comparison."""
import argparse
import json
from pathlib import Path
import numpy as np


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output',type=Path);args=parser.parse_args()
    rng=np.random.default_rng(912616);rows=[];samples=200000
    for b in [10,12,13]:
        for delta in [.15,.3,.6,1.,2.,4.]:
            low=-2**(b-1);high=2**(b-1)-1
            q=rng.uniform(low*.8*delta,high*.8*delta,samples)
            common=rng.standard_normal(samples)
            ys=np.clip(np.floor((q+common)/delta+.5),low,high)*delta
            lo=np.full(samples,low,dtype=int);hi=np.full(samples,high,dtype=int)
            for _ in range(b):
                mid=(lo+hi)//2;up=q+rng.standard_normal(samples)>=(mid+.5)*delta
                lo=np.where(up,mid+1,lo);hi=np.where(up,hi,mid)
            assert np.array_equal(lo,hi)
            ei=lo*delta-q;es=ys-q
            rows.append(dict(bits=b,delta_over_sigma=delta,
                             one_sample_RMS_over_sigma=float(np.sqrt(np.mean(es**2))),
                             independent_decisions_RMS_over_sigma=float(np.sqrt(np.mean(ei**2))),
                             independent_mean_error_over_sigma=float(np.mean(ei)),
                             independent_abs_p999_over_sigma=float(np.quantile(abs(ei),.999))))
    result=dict(status='SPECULATIVE receiver model diagnostic, not hardware noise prediction',seed=912616,samples_per_case=samples,
                scope='Ideal balanced threshold search, white gaussian unit RMS decision noise, uniform interior input excludes endpoints; thermal sample noise omitted equally. Real receiver temporal covariance and gain/settling unknown. No frozen quality model altered.',rows=rows)
    assert not args.output.exists();args.output.write_text(json.dumps(result,indent=2)+'\n')
    print('PASS balanced SAR tree terminates in b comparisons for all declared samples; no hardware claim')


if __name__=='__main__':main()
