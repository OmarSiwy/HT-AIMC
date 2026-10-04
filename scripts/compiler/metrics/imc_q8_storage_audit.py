"""Audit original Q8_0 grouping versus the campaign's smoothed column grid."""
import hashlib
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
from compiler.metrics import imc_ideal_adc_ceiling as ceiling
base, np = ceiling.base, ceiling.np
OUT = ROOT/'build/campaign/q8_storage_audit'


def main():
    _,_,net,weights,sources=base.load()
    sources[str(Path(__file__))]=base.fingerprint(__file__)
    records=[];hist=np.zeros(256,dtype=np.int64)
    totals=dict(weights=0,original_groups32=0,output_columns=0,scale64_pairs=0,
                exactly_equal_adjacent_scales=0,dyadic_adjacent_scales=0)
    errors={k:0. for k in ('current_smoothed_column','unsmoothed_column','unsmoothed_group64','unsmoothed_group128')}
    signal=0.
    for li,layer in enumerate(net.L):
        for name in base.TENSORS:
            tensor=f'blk.{li}.{name}.weight'
            ttype,ne,off=net.g.tensors[tensor]
            assert ttype==8 and ne[0]%64==0
            net.g.f.seek(net.g.data_start+off)
            blocks=np.frombuffer(net.g.f.read(int(np.prod(ne))//32*34),dtype=np.uint8).reshape(ne[1],ne[0]//32,34)
            d=blocks[:,:,:2].copy().view('<f2').astype(np.float32).reshape(ne[1],ne[0]//32)
            q=blocks[:,:,2:].copy().view(np.int8)
            restored=(q.astype(np.float32)*d[:,:,None]).reshape(ne[1],ne[0]).T
            assert np.array_equal(restored,layer[name])
            hist+=np.bincount(q.astype(np.int16).ravel()+128,minlength=256)
            assert np.all(d>0)
            left,right=d[:,::2],d[:,1::2]
            ratio=left.astype(float)/right
            dyadic=ratio==np.exp2(np.rint(np.log2(ratio)))
            counts=dict(weights=int(q.size),original_groups32=int(d.size),output_columns=int(ne[1]),
                scale64_pairs=int(left.size),exactly_equal_adjacent_scales=int(np.count_nonzero(left==right)),
                dyadic_adjacent_scales=int(np.count_nonzero(dyadic)))
            for k,v in counts.items():totals[k]+=v
            scale,wq,dw=weights[li,name]
            reference=layer[name].astype(float)
            reconstructions={'current_smoothed_column':wq.astype(float)*dw[None,:]/scale[:,None]}
            for label,group in [('unsmoothed_column',len(reference)),('unsmoothed_group64',64),('unsmoothed_group128',128)]:
                got=np.empty_like(reference)
                for start in range(0,len(reference),group):
                    w=reference[start:start+group]
                    step=np.maximum(abs(w).max(axis=0)/127,1e-30)
                    got[start:start+group]=np.clip(np.rint(w/step),-127,127)*step
                reconstructions[label]=got
            local={k:float(np.sum((value-reference)**2)) for k,value in reconstructions.items()}
            for k,v in local.items():errors[k]+=v
            signal+=float(np.sum(reference**2))
            records.append(dict(layer=li,tensor=name,shape=list(reference.shape),**counts,squared_weight_error=local))
    assert all(base.fingerprint(f)==h for f,h in sources.items())
    out=dict(complete=True,sources=sources,status='PASS original integer/FP16 block reconstruction bit-exact for all210 MVM tensors',
        code_histogram=hist.tolist(),minimum_code=int(np.flatnonzero(hist)[0]-128),maximum_code=int(np.flatnonzero(hist)[-1]-128),
        totals=totals,original_scale_bytes=2*totals['original_groups32'],original_bits_per_weight=8.5,
        campaign_column_scale_bytes=4*totals['output_columns'],
        weight_error_NRMSE={k:float(np.sqrt(v/signal)) for k,v in errors.items()},
        scope='Weight-matrix moments only, not activation-weighted or full-model quality. Exact group32 preservation uses original codes/scales and has zero extra weight error. Group64/128 RTN values are sensitivity reconstructions, not trained or hardware-validated candidates.',records=records)
    OUT.mkdir(parents=True,exist_ok=True);path=OUT/'result.json';assert not path.exists()
    path.write_text(json.dumps(out,indent=2)+'\n')
    print(out['status']);print(totals);print('codes',out['minimum_code'],out['maximum_code']);print(out['weight_error_NRMSE'])


if __name__=='__main__':main()
