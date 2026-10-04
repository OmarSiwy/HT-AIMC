"""Frozen W8 representation/ADC-precision comparison on the campaign corpus."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT / "scripts"))
import numpy as np
from compiler.metrics import imc_fixed_charge_campaign as base
from compiler.metrics import imc_charge_guard_campaign as guard
from compiler.metrics.imc_weight_digit_campaign import digits

OUT=ROOT/'build/campaign/balanced_precision'


def geometry(units,cu,bits):
    """Generalized frozen integer-unit distributed-CDAC allocation."""
    u=3.75*cu/4;target=2**(bits-4)
    caps=120+cu*units.astype(float)
    available=np.floor(caps/u+1e-12).astype(int)
    missing=np.maximum(target-available.sum(axis=0),0)
    remainder=caps[0]-available[0]*u
    pad=np.where(missing>0,missing*u-remainder,0.)
    caps[0]+=pad;available=np.floor(caps/u+1e-12).astype(int);available[0]-=1
    fragments=np.zeros(caps.shape[1],dtype=int)
    for bit in range(bits-5,-1,-1):
        required=np.full(caps.shape[1],2**bit,dtype=int)
        for g in range(len(caps)):
            take=np.minimum(required,available[g]);available[g]-=take;required-=take
            fragments+=take>0
        assert not np.any(required)
    assert np.all(pad>=0)
    return caps,dict(connected_C_fF=float(2*caps.sum()+caps.shape[1]*(16+1/15)*u),
                     two_sided_padding_fF=float(2*pad.sum()),coarse_switch_fragments=int(fragments.sum()),
                     maximum_joined_fF=float(caps.sum(axis=0).max()),maximum_padding_fF=float(pad.max()))


def scenes(q,w,dx,pooled,format):
    all_digits=digits(w,format)[:2];banks=[[],[]]
    groups=(q.shape[1]+255)//256
    for first in range(0,groups,4 if pooled else 1):
        last=min(first+(4 if pooled else 1),groups)
        B=np.ceil(np.log2(np.max(abs(q[:,first*256:last*256].astype(float)),axis=1)+1)).astype(int)
        scale=dx[:,first]
        if pooled:assert np.array_equal(dx[:,first:last],np.broadcast_to(scale[:,None],dx[:,first:last].shape))
        for bank,d in enumerate(all_digits):
            partial=np.zeros((len(q),w.shape[1]));units=[]
            for g in range(first,last):
                local=d[g*256:(g+1)*256]
                units.append(abs(local).sum(axis=0,dtype=float))
                partial+=(q[:,g*256:(g+1)*256].astype(np.float32)@local.astype(np.float32)).astype(float)
            banks[bank].append(dict(Q_per_Cu=.45*partial/np.exp2(B[:,None]),B=B,dx=scale,active=B>0,units=np.array(units)))
    return banks


def prepare(bank,cu,bits):
    prepared=[]
    for s in bank:
        caps,stats=geometry(s['units'],cu,bits);C=caps.sum(axis=0)
        factor=np.exp2(s['B'])/(cu*.45)*s['dx']
        thermal=base.KT*1e15*C[None,:]/2*(1-4.**(-s['B'][:,None]))/(1-.25)
        prepared.append(dict(Q=cu*s['Q_per_Cu'],C=C,factor=factor,thermal=thermal,
                             active=s['active'],B=s['B'],dx=s['dx'],groups=len(caps),static=stats))
    return prepared


def read(prepared,cu,bits,span,read_uv=0,thermal=False,rng=None,stats=False):
    step=3.75*cu/4/16*span;out=np.zeros_like(prepared[0]['Q'])
    count=Counter();maximum={};boundaries=[]
    for s in prepared:
        Q=s['Q']
        if thermal or read_uv:
            var=(s['C'][None,:]*read_uv*1e-6)**2+(s['thermal'] if thermal else 0)
            Q=Q+rng.standard_normal(Q.shape)*np.sqrt(var)
        code=np.floor(Q/step+.5)
        clipped=(code < -2**(bits-1)) | (code > 2**(bits-1)-1)
        reconstructed=np.clip(code,-2**(bits-1),2**(bits-1)-1)*step*np.exp2(s['B'][:,None])/(cu*.45)*s['dx'][:,None]
        reconstructed[~s['active']]=0;out+=reconstructed
        if stats:
            columns=Q.shape[1];conversions=int(s['active'].sum())*columns
            count.update(conversions=conversions,ADC_decisions=bits*conversions,
                         clips=int(np.count_nonzero(clipped&s['active'][:,None])),
                         column_plane_events=int(s['B'].sum())*s['groups']*columns)
            for key,value in s['static'].items():
                if key.startswith('maximum_'):maximum[key]=max(maximum.get(key,0),value)
                else:count[key]+=value
            maximum['maximum_abs_charge_fC']=max(maximum.get('maximum_abs_charge_fC',0),float(abs(Q).max()))
            boundaries.append(clipped&s['active'][:,None])
    return out,dict(count,**maximum,ADC_bits=bits,Vspan_V=span,deltaQ_fC=step),boundaries


def noise_proxy(prepared,dw,read_uv):
    variance=np.zeros_like(prepared[0]['Q'])
    for s in prepared:
        contribution=(s['thermal']+(s['C'][None,:]*read_uv*1e-6)**2)*s['factor'][:,None]**2
        contribution[~s['active']]=0;variance+=contribution
    return float(np.mean(variance*dw[None,:]**2))


def selfcheck():
    rng=np.random.default_rng(93941)
    q=rng.integers(-511,512,(11,1093),dtype=np.int16);w=rng.integers(-127,128,(1093,7),dtype=np.int16)
    dx=np.ones((len(q),5))
    for pooled in (False,True):
        for format in ('signed_magnitude','balanced'):
            bs=scenes(q,w,dx,pooled,format)
            ideal=sum(16**i*sum((s['Q_per_Cu']*np.exp2(s['B'][:,None])/.45 for s in bank)) for i,bank in enumerate(bs))
            assert np.allclose(ideal,q.astype(float)@w,atol=1e-7)
            for b,bank in enumerate(bs):
                prepared=prepare(bank,4,guard.BITS[b]);got,_,_=read(prepared,4,guard.BITS[b],.5,20,True,np.random.default_rng(5))
                reference,_,_,_=guard.read(bank,b,'distributed',4,.5,20,True,np.random.default_rng(5))
                assert np.array_equal(got,reference)
    for groups in (1,3,4):
        units=rng.integers(0,3500,(groups,19))
        for cu in (4,8):
            for b,n in enumerate(guard.BITS):
                c,_=geometry(units,cu,n);r,_=guard.geometry(units,b,'distributed',cu)
                assert np.array_equal(c,r)
    print('PASS exact balanced/original sums, ragged groups, frozen guard geometry and seeded noise/quantizer parity',flush=True)


def freeze():
    OUT.mkdir(parents=True,exist_ok=True)
    arch=json.loads((guard.OUT/'protocol.json').read_text())['architectures']
    files=[Path(__file__),Path(base.__file__),Path(guard.__file__),ROOT/'scripts/compiler/metrics/imc_weight_digit_campaign.py']
    protocol=dict(status='Frozen before new calibration or quality evaluation',sources={str(p):base.fingerprint(p) for p in files},
      formats=['signed_magnitude','balanced'],architectures=arch,Cu_fF=[4,8],ADC_bits=[10,11,12,13,14],
      Vspan_V=[.0625,.125,.25,.5,1.,1.25],policies=['min_error','economy10'],calibration_read_uv=20,
      calibration='Old27h3 clean Q8_0 first128 tokens only; independent per-MVM/slice/format/Cu choices',
      selection='Proxy=exact noiseless quantization/clipping MSE plus independent thermal/read20 output variance, weighted by dw; min_error minimizes proxy; economy10 minimizes bits then proxy within1.10*minimum. High-slice16 significance is common to all choices within that bank.',
      proxy_limit='Selection proxy omits noise-quantization/clipping interaction. Final quality explicitly draws noise before actual finite quantization; proxy itself is not a quality claim.',
      modes=[['quantization_only',0,False,None],['read20',20,True,60001],['read20',20,True,60002]],
      physical='Integer distributed native-cap allocation; all extra matched array/holder C and coarse fragments paid; fine excess retained. No ideal stack gain, row DAC noise, mismatch, added reference/reset covariance or transistor validity.',
      scheduling='One depth perMVM/slice across all columns. Record round*depth sum, per-MVM lockstepmax-depth cost and global14 fixed-depth control. No concurrency benefit from average bits.',
      storage='Maximum required depth recorded; disconnected programmable capacitor reserve, exact sign/carry decoder and physical ADC control/reference storage are unpriced.',
      evaluation='Same two exposed first512-token passages; require KL<=.01 and PPLratio<=1.01 for both seeds/passages; reserved untouched. New quality begins only after frozen Cu8 guard completes.')
    data=(json.dumps(protocol,indent=2)+'\n').encode();path=OUT/'protocol.json'
    if path.exists():assert path.read_bytes()==data,'Protocol changed'
    else:path.write_bytes(data)
    snapshot=OUT/f'source_{base.fingerprint(__file__)}.py'
    if snapshot.exists():assert snapshot.read_bytes()==Path(__file__).read_bytes()
    else:snapshot.write_bytes(Path(__file__).read_bytes())
    return protocol


def load():
    p=freeze();_,old,net,weights,sources=base.load()
    sources.update(p['sources']);sources[str(OUT/'protocol.json')]=base.fingerprint(OUT/'protocol.json')
    assert all(base.fingerprint(f)==h for f,h in sources.items())
    return p,old,net,weights,sources


def calibrate(cu):
    selfcheck();p,_,net,weights,sources=load();assert cu in p['Cu_fF']
    output=OUT/f'calibration_Cu{cu}.json';assert not output.exists()
    note=next((Path.home()/'Documents/Projects/OmarSiwy.github.io/Notes/Circuit Design/Analog Design/Analog Compute').glob('27h3 *.md'))
    sources[str(note)]=base.fingerprint(note);ids=base.tokenize_greedy(note.read_text(),net.vocab)[:128]
    activations={}
    def capture(li,name,a,w,y):activations[li,name]=a.copy();return y
    net.mvm=capture;net(ids);net.mvm=None;assert len(activations)==210
    records=[];started=time.perf_counter()
    for format in p['formats']:
        for arch in p['architectures']:
            for (li,name),(s,w,dw) in weights.items():
                q,dx,_=base.quantize(activations[li,name]/s,arch['kind'],arch['A'])
                for bank,bs in enumerate(scenes(q,w,dx,arch['pooled'],format)):
                    target=sum(scene['Q_per_Cu']*np.exp2(scene['B'][:,None])/.45*scene['dx'][:,None] for scene in bs)
                    grid=[]
                    for bits in p['ADC_bits']:
                        prepared=prepare(bs,cu,bits);noise=noise_proxy(prepared,dw,p['calibration_read_uv'])
                        for span in p['Vspan_V']:
                            got,counts,_=read(prepared,cu,bits,span,stats=True)
                            error=float(np.mean(((got-target)*dw)**2))
                            grid.append(dict(bits=bits,span=span,deterministic_MSE=error,noise_variance_proxy=noise,
                                             total_proxy=error+noise,clips=counts['clips'],connected_C_fF=counts['connected_C_fF']))
                    best=min(grid,key=lambda g:(g['total_proxy'],g['bits'],g['span']))
                    cheap=min((g for g in grid if g['total_proxy']<=1.1*best['total_proxy']+1e-30),
                              key=lambda g:(g['bits'],g['total_proxy'],g['span']))
                    records.append(dict(format=format,architecture=arch['label'],layer=li,tensor=name,bank=bank,
                                        selected={'min_error':best,'economy10':cheap},grid=grid))
                if (li+1)%5==0 and name==base.TENSORS[-1]:print('calibration',cu,format,arch['label'],li+1,flush=True)
    assert all(base.fingerprint(f)==h for f,h in sources.items())
    output.write_text(json.dumps(dict(complete=True,Cu_fF=cu,protocol=p,sources=sources,records=records,
                                     calibration_token_ids_sha256=hashlib.sha256(np.array(ids,dtype='<i4').tobytes()).hexdigest(),
                                     runtime_s=time.perf_counter()-started),indent=2)+'\n')
    print('PASS frozen independent representation/precision/range calibration',cu,flush=True)


def evaluate(cu):
    selfcheck();p,old,net,weights,sources=load();assert cu in p['Cu_fF']
    prior=guard.OUT/'distributed_Cu8.json';assert json.loads(prior.read_text())['complete']
    cp=OUT/f'calibration_Cu{cu}.json';cal=json.loads(cp.read_text())
    assert cal['complete'] and all(base.fingerprint(f)==h for f,h in cal['sources'].items())
    sources[str(cp)]=base.fingerprint(cp);sources[str(prior)]=base.fingerprint(prior)
    choices={(r['format'],r['architecture'],r['layer'],r['tensor'],r['bank']):r['selected'] for r in cal['records']}
    output=OUT/f'quality_Cu{cu}.json';assert not output.exists()
    results=[];report=dict(complete=False,Cu_fF=cu,protocol=p,sources=sources,results=results,
                          classification='Conditional complete-depth W8 model with finite ADC/noise; no silicon/fullPPA/novelty claim')
    for src in old['sources']:
        note=Path(src['path']);assert base.fingerprint(note)==src['sha256']
        ids=base.tokenize_greedy(note.read_text(),net.vocab)[:512];net.mvm=None;ev=base.Eval(net,ids)
        for format in p['formats']:
            for arch in p['architectures']:
                for policy in p['policies']:
                    for mode,read_uv,thermal,seed in p['modes']:
                        rng=np.random.default_rng(seed);tensors=[];started=time.perf_counter()
                        def compute(li,name,a,w,clean):
                            scale,wq,dw=weights[li,name];q,dx,_=base.quantize(a/scale,arch['kind'],arch['A'])
                            parts=[];counts=[]
                            for bank,bs in enumerate(scenes(q,wq,dx,arch['pooled'],format)):
                                setting=choices[format,arch['label'],li,name,bank][policy];n,span=setting['bits'],setting['span']
                                got,c,flags=read(prepare(bs,cu,n),cu,n,span,read_uv,thermal,rng,stats=True)
                                schedule=guard.stalls(flags,arch['pooled'])
                                c.update(conditional_ADC_rounds=schedule['conditional_ADC_rounds'],
                                         conditional_round_decisions=n*schedule['conditional_ADC_rounds'],
                                         conditional_rounds_with_clip=schedule['conditional_rounds_with_boundary'])
                                counts.append(c);parts.append(got)
                            depth=max(c['ADC_bits'] for c in counts);rounds=sum(c['conditional_ADC_rounds'] for c in counts)
                            tensors.append(dict(layer=li,tensor=name,banks=counts,max_ADC_bits=depth,
                                per_MVM_max_depth_round_decisions=depth*rounds,global14_round_decisions=14*rounds))
                            return ((parts[0]+16*parts[1])*dw).astype(np.float32)
                        net.mvm=compute;quality=ev.score(net(ids));assert len(tensors)==210
                        keys=('conversions','ADC_decisions','clips','column_plane_events','connected_C_fF','two_sided_padding_fF',
                              'coarse_switch_fragments','conditional_ADC_rounds','conditional_round_decisions','conditional_rounds_with_clip')
                        totals={k:sum(b[k] for t in tensors for b in t['banks']) for k in keys}
                        totals.update(per_MVM_max_depth_round_decisions=sum(t['per_MVM_max_depth_round_decisions'] for t in tensors),
                                      global14_round_decisions=sum(t['global14_round_decisions'] for t in tensors),
                                      maximum_ADC_bits=max(t['max_ADC_bits'] for t in tensors),
                                      maximum_joined_fF=max(b['maximum_joined_fF'] for t in tensors for b in t['banks']))
                        histogram=Counter()
                        for t in tensors:
                            for b in t['banks']:histogram[b['ADC_bits']]+=b['conversions']
                        r=dict(source=note.name,format=format,architecture=arch['label'],policy=policy,mode=mode,seed=seed,
                               **quality,**totals,conversion_depth_histogram=dict(histogram),tensors=tensors,
                               runtime_s=time.perf_counter()-started,joint_pass=quality['kl']<=.01 and quality['ppl_ratio']<=1.01)
                        results.append(r);output.write_text(json.dumps(report,indent=2)+'\n')
                        print(cu,note.stem[:8],format,arch['label'],policy,mode,seed,
                              {k:r[k] for k in ('kl','ppl_ratio','joint_pass','ADC_decisions','clips')},flush=True)
        net.mvm=None;assert np.array_equal(net(ids),ev.ref)
    assert all(base.fingerprint(f)==h for f,h in sources.items())
    report['complete']=True;output.write_text(json.dumps(report,indent=2)+'\n')
    print('PASS frozen representation/precision evaluation',cu,'quality',sum(r['joint_pass'] for r in results),'/',len(results),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freeze',action='store_true');parser.add_argument('--selfcheck',action='store_true')
    parser.add_argument('--calibrate',action='store_true');parser.add_argument('--cu',type=int,choices=(4,8),default=4)
    a=parser.parse_args()
    if a.freeze:freeze()
    elif a.selfcheck:selfcheck()
    elif a.calibrate:calibrate(a.cu)
    else:evaluate(a.cu)
