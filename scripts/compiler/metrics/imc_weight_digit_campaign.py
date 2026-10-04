"""Exact W8 digit representations: static charge/area/noise tradeoffs only."""
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT / "scripts"))
import numpy as np
from compiler.metrics import imc_fixed_charge_campaign as base
from compiler.metrics import imc_charge_guard_campaign as guard

OUT=ROOT/'build/campaign/weight_digits'
FORMATS=('signed_magnitude','balanced','shared_offset')


def digits(w,mode):
    w=np.asarray(w,dtype=np.int16)
    if mode=='signed_magnitude':return np.sign(w)*(abs(w)%16),np.sign(w)*(abs(w)//16),0
    if mode=='balanced':
        high=(w+8)//16
        return w-16*high,high,0
    return w%16-8,w//16,8


def distribution(x):
    return dict(zip(('min','p5','p50','p95','max'),np.percentile(x,[0,5,50,95,100]).tolist()))


def selfcheck():
    w=np.arange(-128,128,dtype=np.int16)
    rng=np.random.default_rng(39106)
    x=rng.integers(-511,512,(17,256))
    for mode in FORMATS:
        low,high,offset=digits(w,mode)
        assert np.array_equal(low+16*high+offset,w)
        assert np.array_equal(x@low+16*(x@high)+offset*x.sum(axis=1),x@w)
        assert max(abs(low).max(),abs(high).max())<=15
    low,high,_=digits(w,'balanced')
    assert low.min()==-8 and low.max()==7 and high.min()==-8 and high.max()==8
    low,high,_=digits(w,'shared_offset')
    assert low.min()==-8 and low.max()==7 and high.min()==-8 and high.max()==7
    # Centering signed magnitude needs a column-dependent sign-weighted sum.
    w=np.array([[-1,1],[1,1]])
    a=np.array([3,5]);s=np.sign(w)
    wrong=a@(s*(abs(w)%16-8))+16*(a@(s*(abs(w)//16)))+8*a.sum()
    assert not np.array_equal(wrong,a@w)


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    _,_,_,weights,sources=base.load()
    sources.update({str(Path(__file__).resolve()):base.fingerprint(__file__),
                    str(Path(guard.__file__).resolve()):base.fingerprint(guard.__file__)})
    paths={name:ROOT/f'build/campaign/system_audit/physical_fixture/{name}/fixture.npz' for name in ('p50','p95')}
    sources.update({str(p):base.fingerprint(p) for p in paths.values()})
    protocol=dict(sources=sources,formats=list(FORMATS),Cu_fF=4,overhead_fF=120,
                  local_rows=256,pooling_groups=4,guard_bits=[14,13],DAC_unit_fF=3.75,
                  scope='Exact identity and all210 real W8 static loads, existing calibration/development fixture charges; no new model quality evaluation',
                  noise='Conditional independent stage charge variance proportionalC; read charge sigma proportionalC; high slice reconstruction multiplies by16',
                  correction='Shared-offset uses floor(q/16) high and q%16−8 low; exact digital8*sum(x) once per group, before per-output dw',
                  area='Connected array+holder+fine-DAC excess only; switches/storage/reserve/routing unpriced')
    encoded=(json.dumps(protocol,indent=2)+'\n').encode();pp=OUT/'protocol.json'
    if pp.exists():assert pp.read_bytes()==encoded
    else:pp.write_bytes(encoded)
    (OUT/f'source_{base.fingerprint(__file__)}.py').write_bytes(Path(__file__).read_bytes())
    selfcheck();rows=[];fixture_rows=[];representation=[]
    for mode in FORMATS:
        coefficient_count=0;abs_sum=np.zeros(2);zero_count=np.zeros(2,dtype=np.int64)
        sign_disagree=0;endpoint_count=np.zeros(2,dtype=np.int64)
        for _,w,_ in weights.values():
            ds=digits(w,mode)[:2];coefficient_count+=w.size
            sign_disagree+=int(np.count_nonzero((ds[0]*ds[1]<0)))
            for b,d in enumerate(ds):
                abs_sum[b]+=abs(d).sum();zero_count[b]+=np.count_nonzero(d==0)
                endpoint_count[b]+=np.count_nonzero(abs(d)==8)
        representation.append(dict(format=mode,weights=coefficient_count,mean_abs_digits=(abs_sum/coefficient_count).tolist(),
                                   zero_fraction=(zero_count/coefficient_count).tolist(),opposite_slice_sign_fraction=sign_disagree/coefficient_count,
                                   magnitude8_fraction=(endpoint_count/coefficient_count).tolist()))
        for pooled in (False,True):
            raw=[[],[]];units_by_bank=[[],[]]
            input_sum_adds=0;input_sum_groups=0;max_group_rows=0
            for _,w,_ in weights.values():
                dlow,dhigh,offset=digits(w,mode)
                for first in range(0,len(w),1024 if pooled else 256):
                    stop=min(first+(1024 if pooled else 256),len(w))
                    input_sum_adds+=max(stop-first-1,0) if offset else 0
                    input_sum_groups+=bool(offset);max_group_rows=max(max_group_rows,stop-first)
                    for b,d in enumerate((dlow,dhigh)):
                        u=np.array([abs(d[g:min(g+256,stop)]).sum(axis=0) for g in range(first,stop,256)])
                        units_by_bank[b].append(u)
                        raw[b].extend((120+4*u).sum(axis=0))
            raw=np.array(raw)
            for policy in ('raw','host','distributed'):
                caps=[[],[]];cap_proxy=0;pad=0;fragments=0
                for b in range(2):
                    for u in units_by_bank[b]:
                        if policy=='raw':
                            c=120+4*u;cap_proxy+=2*c.sum()
                        else:
                            c,st=guard.geometry(u,b,policy,4)
                            cap_proxy+=st['connected_array_holder_and_DAC_excess_fF'];pad+=st['two_sided_padding_fF']
                            fragments+=st['coarse_switch_fragments']
                        caps[b].extend(c.sum(axis=0))
                caps=np.array(caps)
                rows.append(dict(format=mode,pooled=pooled,policy=policy,
                    connected_array_holder_DAC_fF=float(cap_proxy),two_sided_padding_fF=float(pad),coarse_switch_fragments=int(fragments),
                    low_cap_fF=distribution(caps[0]),high_cap_fF=distribution(caps[1]),
                    mean_native_charge_thermal_variance_coefficient_fF=float(np.mean(caps[0]+256*caps[1])),
                    mean_native_read_noise_variance_coefficient_fF2=float(np.mean(caps[0]**2+256*caps[1]**2)),
                    exact_input_sum_adds_per_token=int(input_sum_adds),shared_input_sum_groups_per_token=int(input_sum_groups),
                    maximum_signed_sum_bits=int(np.ceil(np.log2(max_group_rows*511+1)))+1,
                    corrected_sum_extra_bits=3 if mode=='shared_offset' else 0))
        for name,path in paths.items():
            f=np.load(path);w=f['Wq'].astype(np.int16);low,high,offset=digits(w,mode)
            for prefix in ('cal_',''):
                q=f[prefix+'xq'].astype(np.int64);B=f[prefix+'B_common'];charge=[]
                for bank,d in enumerate((low,high)):
                    Q=1.8*(q@d.T)/np.exp2(B[:,None]);C=120+4*abs(d).sum(axis=1)
                    charge.append(Q)
                    fixture_rows.append(dict(format=mode,fixture=name,corpus='calibration' if prefix else 'development',bank=bank,
                        C_fF=C.tolist(),charge_fC=Q.tolist(),max_abs_charge_fC=float(abs(Q).max()),
                        held_V=(Q/C[None,:]).tolist()))
                assert np.array_equal(q@low.T+16*(q@high.T)+offset*q.sum(axis=1)[:,None],q@w.T)
    assert all(base.fingerprint(p)==h for p,h in sources.items()) and pp.read_bytes()==encoded
    result=dict(protocol_sha256=hashlib.sha256(encoded).hexdigest(),representation=representation,static=rows,fixtures=fixture_rows,
                classification='VERIFIED exact digit identities and conditional static/noise coefficients; quality/circuitPPA unverified')
    (OUT/'results.json').write_text(json.dumps(result,indent=2)+'\n')
    for r in representation:print(r,flush=True)
    for r in rows:
        if r['policy']=='distributed':print(r['format'],'pool',r['pooled'],'C',r['connected_array_holder_DAC_fF'],
            'thermal',r['mean_native_charge_thermal_variance_coefficient_fF'],'read',r['mean_native_read_noise_variance_coefficient_fF2'],flush=True)
    print('PASS: all signedW8 identities, shared correction counterexample, frozen fullweight geometry and fixture charge')


if __name__=='__main__':main()
