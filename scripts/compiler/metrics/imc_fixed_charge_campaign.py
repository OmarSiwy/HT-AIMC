"""Fixed-charge SAR model with independently calibrated separate/pool ranges.

New hypothesis after the immutable fixed-voltage experiment. No transistor PPA,
and no reserved-token evaluation. Both array and host holder receive any padding
needed to fit an in-place split CDAC; comparator voltage noise remains paid.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import sys
import time

os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
import numpy as np
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT / "scripts"))
from compiler.metrics.imc_scale_alignment_campaign import quantize,fingerprint
from compiler.metrics.imc_smooth_radix import quantize_weight
from compiler.metrics.depth_budget import Net,Eval,TENSORS,tokenize_greedy
from compiler.metrics.imc_radix_full_model import KT

OUT=ROOT/'build/campaign/fixed_charge'
PROTOCOL=OUT/'protocol.json'


def scenes(q,w,dx,pooled):
    """Charge per Cu and actual local coefficients, before any quantizer."""
    groups=(q.shape[1]+255)//256
    banks=[[],[]]
    for first in range(0,groups,4 if pooled else 1):
        last=min(first+(4 if pooled else 1),groups)
        B=np.ceil(np.log2(np.max(abs(q[:,first*256:last*256].astype(float)),axis=1)+1)).astype(int)
        scale=dx[:,first]
        if pooled:
            assert np.array_equal(dx[:,first:last],np.broadcast_to(scale[:,None],dx[:,first:last].shape))
        for bank,shift in enumerate((0,4)):
            units=[]; partial=np.zeros((len(q),w.shape[1]),dtype=float)
            for g in range(first,last):
                wb=w[g*256:(g+1)*256].astype(np.int16)
                digits=(np.sign(wb)*((abs(wb)>>shift)&15)).astype(np.float32)
                units.append(abs(digits).sum(axis=0,dtype=float))
                partial+=(q[:,g*256:(g+1)*256].astype(np.float32)@digits).astype(float)
            banks[bank].append(dict(Q_per_Cu=.45*partial/np.exp2(B[:,None]),B=B,
                                    dx=scale,active=B>0,units=np.array(units)))
    return banks


def reconstruct(bank,cu,nbits,vspan,read_uv=0,thermal=False,rng=None,ideal=False):
    """Return dequantized slice sum before dw and high-slice factor16."""
    shape=bank[0]['Q_per_Cu'].shape
    out=np.zeros(shape,dtype=float)
    count=Counter(conversions=0,ADC_decisions=0,clips=0,column_plane_events=0,
                  host_fit_violations=0,host_columns=0,connected_cap_proxy_fF=0.,
                  positive_matching_padding_fF=0.,maximum_original_host_fF=0.,
                  maximum_padded_host_fF=0.,maximum_joined_seen_fF=0.,
                  maximum_physical_DAC_fF=0.,maximum_matching_padding_fF=0.,
                  maximum_abs_charge_fC=0.,maximum_held_V=0.)
    unit=3.75*cu/4
    seen=2**(nbits-4)*unit
    physical=(2**(nbits-4)+16+1/15)*unit
    step=unit/16*vspan
    for s in bank:
        raw=120+cu*s['units']
        caps=raw.copy()
        padding=np.maximum(seen-raw[0],0.)
        caps[0]+=padding
        total=caps.sum(axis=0)
        Q=cu*s['Q_per_Cu']
        active=s['active']
        count.update(conversions=int(active.sum())*shape[1],
                     ADC_decisions=nbits*int(active.sum())*shape[1],
                     column_plane_events=int(s['B'].sum())*len(caps)*shape[1],
                     host_fit_violations=int(np.count_nonzero(padding)),host_columns=shape[1],
                     connected_cap_proxy_fF=float(2*caps.sum()+shape[1]*(physical-seen)),
                     positive_matching_padding_fF=float(2*padding.sum()))
        for key,value in [('maximum_original_host_fF',raw[0].max()),('maximum_padded_host_fF',caps[0].max()),
                          ('maximum_joined_seen_fF',total.max()),('maximum_physical_DAC_fF',physical),
                          ('maximum_matching_padding_fF',padding.max()),('maximum_abs_charge_fC',abs(Q).max()),
                          ('maximum_held_V',abs(Q/total[None,:]).max())]:
            count[key]=max(count[key],float(value))
        if thermal or read_uv:
            assert rng is not None
            # In fC^2: kT*C[F]*1e30 = kT*C[fF]*1e15.
            variance=np.broadcast_to((total[None,:]*read_uv*1e-6)**2,Q.shape).copy()
            if thermal:
                variance+=KT*1e15/2*total[None,:]*(1-4.**(-s['B'][:,None]))/(1-.25)
            Q=Q+rng.standard_normal(Q.shape)*np.sqrt(variance)
        if not ideal:
            code=np.floor(Q/step+.5)
            count['clips']+=int(np.count_nonzero(((code < -2**(nbits-1)) |
                                                (code > 2**(nbits-1)-1)) & active[:,None]))
            Q=np.clip(code,-2**(nbits-1),2**(nbits-1)-1)*step
        got=Q*np.exp2(s['B'][:,None])/(cu*.45)*s['dx'][:,None]
        got[~active]=0
        out+=got
    return out,dict(count,Cu_fF=cu,DAC_unit_fF=unit,ADC_bits=nbits,Vspan_V=vspan,
                    deltaQ_fC=step,ADC_charge_limits_fC=[-2**(nbits-1)*step,(2**(nbits-1)-1)*step])


def selfcheck():
    rng=np.random.default_rng(67011)
    a=rng.normal(size=(12,1157)).astype(np.float32);a[:,:256]*=12;a[0]=0
    w=rng.integers(-127,128,size=(1157,7),dtype=np.int16)
    for kind,bits,pool in [('local',9,False),('common',10,False),('common',10,True)]:
        q,dx,expanded=quantize(a,kind,bits)
        bs=scenes(q,w,dx,pool)
        for cu in (4,32):
            for n in (10,12):
                parts=[reconstruct(b,cu,n,.5,ideal=True)[0] for b in bs]
                assert np.allclose(parts[0]+16*parts[1],(q.astype(float)*expanded)@w,
                                   rtol=2e-12,atol=1e-7)
        # Scaling both Cu and DAC unit preserves every deterministic code.
        for b in bs:
            y4,_=reconstruct(b,4,12,.5)
            y32,_=reconstruct(b,32,12,.5)
            assert np.array_equal(y4,y32)
    q=np.full((1,512),511,dtype=np.int16)
    w=np.full((512,1),127,dtype=np.int16)
    bs=scenes(q,w,np.ones((1,2)),True)
    y,stats=reconstruct(bs[0],4,10,.5)
    assert stats['clips'] and stats['ADC_charge_limits_fC']==[-60.,59.8828125]
    # Capacitance/loading changes cannot change a noiseless fixed-charge code.
    altered=[dict(s,units=s['units']*10) for s in bs[0]]
    z,large=reconstruct(altered,4,10,.5)
    assert np.array_equal(y,z) and large['maximum_joined_seen_fF']>stats['maximum_joined_seen_fF']
    # Padding is nonnegative and counted on both matched sides.
    q=np.array([[0,1]],dtype=np.int16);w=np.array([[0],[1]],dtype=np.int16)
    b=scenes(q,w,np.ones((1,1)),False)[0]
    _,stats=reconstruct(b,4,12,.5)
    assert stats['host_fit_violations']==1 and stats['positive_matching_padding_fF']==2*(960-124)
    print('PASS: signed/ragged/scale identities, charge-vs-voltage cancellation, clipping and paid host padding',flush=True)


def load():
    protocol=json.loads(PROTOCOL.read_text())
    phase1=json.loads((ROOT/'build/campaign/scale_alignment/physical.json').read_text())
    assert phase1.get('complete'), 'Do not evaluate phase2 before immutable phase1 completes'
    old=json.loads((ROOT/protocol['sources_protocol']).read_text())
    paths=[Path(__file__),PROTOCOL,ROOT/protocol['sources_protocol'],ROOT/old['frozen_scales'],
           ROOT/old['model'],ROOT/'scripts/compiler/metrics/imc_scale_alignment_campaign.py',
           ROOT/'scripts/compiler/metrics/imc_smooth_radix.py',ROOT/'scripts/compiler/metrics/depth_budget.py',
           ROOT/'scripts/compiler/metrics/imc_radix_full_model.py',ROOT/'scripts/compiler/gguf_reader.py']
    sources={str(p):fingerprint(p) for p in paths}
    assert fingerprint(ROOT/old['frozen_scales'])==old['scales_sha256']
    net=Net();weights={};digest=hashlib.sha256()
    with np.load(ROOT/old['frozen_scales']) as f:
        for li,layer in enumerate(net.L):
            for name in TENSORS:
                s=f[f'{li}_{name}'].copy();q,dw=quantize_weight(layer[name],s)
                weights[li,name]=(s,q,dw)
                digest.update(f'{li}/{name}/{q.shape}\n'.encode());digest.update(q.tobytes())
    assert digest.hexdigest()==phase1['weight_code_sha256']
    snapshot=OUT/f'source_{sources[str(Path(__file__))]}.py'
    if not snapshot.exists():snapshot.write_bytes(Path(__file__).read_bytes())
    return protocol,old,net,weights,sources


def calibrate():
    selfcheck();p,old,net,weights,sources=load()
    output=OUT/'calibration.json';assert not output.exists(),f'Refusing overwrite: {output}'
    notes=Path.home()/'Documents/Projects/OmarSiwy.github.io/Notes/Circuit Design/Analog Design/Analog Compute'
    path=next(notes.glob(p['calibration']['note_prefix']+' *.md'))
    sources[str(path)]=fingerprint(path)
    ids=tokenize_greedy(path.read_text(),net.vocab)[:128]
    assert len(ids)==128
    activations={}
    def capture(li,name,a,w,y):activations[li,name]=a.copy();return y
    net.mvm=capture;net(ids);net.mvm=None
    assert len(activations)==210
    records=[];started=time.perf_counter()
    for arch in p['architectures']:
        for (li,name),(s,w,dw) in weights.items():
            q,dx,_=quantize(activations[li,name]/s,arch['kind'],arch['A'])
            bs=scenes(q,w,dx,arch['pooled'])
            for n in p['ADC_bits']:
                for bank,b in enumerate(bs):
                    target=reconstruct(b,4,n,.5,ideal=True)[0]*dw
                    grid=[]
                    for span in p['Vspan_grid_V']:
                        got,counts=reconstruct(b,4,n,span)
                        error=got*dw-target
                        grid.append(dict(Vspan_V=span,mse=float(np.mean(error**2)),
                                         clips=counts['clips'],conversions=counts['conversions'],
                                         max_charge_fC=counts['maximum_abs_charge_fC']))
                    best=min(grid,key=lambda x:x['mse'])
                    records.append(dict(architecture=arch['label'],layer=li,tensor=name,ADC_bits=n,
                                        bank=bank,selected_Vspan_V=best['Vspan_V'],grid=grid,
                                        target_mean_square=float(np.mean(target**2))))
            if (li+1)%5==0 and name==TENSORS[-1]:
                print('Calibration',arch['label'],li+1,'/30',flush=True)
    assert all(fingerprint(f)==h for f,h in sources.items())
    result=dict(complete=True,classification='Calibration-only frozen charge range selection; no new quality data',
                protocol=p,sources=sources,records=records,runtime_s=time.perf_counter()-started,
                calibration_token_ids_sha256=hashlib.sha256(np.array(ids,dtype='<i4').tobytes()).hexdigest())
    output.write_text(json.dumps(result,indent=2)+'\n')
    print('PASS frozen calibration:',output,flush=True)


def evaluate(n,cu):
    selfcheck();p,old,net,weights,sources=load()
    assert n in p['ADC_bits'] and cu in p['Cu_fF']
    calpath=OUT/'calibration.json';cal=json.loads(calpath.read_text())
    assert cal['complete'] and all(fingerprint(f)==h for f,h in cal['sources'].items())
    sources[str(calpath)]=fingerprint(calpath)
    ranges={(r['architecture'],r['layer'],r['tensor'],r['bank']):r['selected_Vspan_V']
            for r in cal['records'] if r['ADC_bits']==n}
    output=OUT/f'N{n}_Cu{cu}.json';assert not output.exists(),f'Refusing overwrite: {output}'
    modes=[('quantization_only',None,0,False)]+[(m,seed,v,True)
          for m,v in [('thermal_only',0),('read20',20),('read50',50)] for seed in p['noise']['seeds']]
    results=[];references=[];started=time.perf_counter()
    report=dict(complete=False,classification='Development conditional charge-ADC model; not physical validation',
                protocol=p,sources=sources,ADC_bits=n,Cu_fF=cu,results=results,references=references,
                modes=modes,limitations='Ideal matched padding and caps; no measured reset/reference/join noise, mismatch, MOS admittance, ADC offsets, driver energy or physical layout. Cap proxy excludes disconnected programming caps and SRAM. Float attention/KV/norm/LM head.')
    output.write_text(json.dumps(report,indent=2)+'\n')
    for src in old['sources']:
        path=Path(src['path']);assert fingerprint(path)==src['sha256']
        ids=tokenize_greedy(path.read_text(),net.vocab)[:512]
        assert len(ids)==512
        net.mvm=None;ev=Eval(net,ids)
        references.append(dict(source=path.name,sha256=src['sha256'],tokens=512,PPL=ev.ppl,
                               token_ids_sha256=hashlib.sha256(np.array(ids,dtype='<i4').tobytes()).hexdigest()))
        for arch in p['architectures']:
            for mode,seed,read,thermal in modes:
                tic=time.perf_counter();rng=np.random.default_rng(seed);tensors=[]
                def compute(li,name,a,w,clean):
                    s,wq,dw=weights[li,name]
                    q,dx,_=quantize(a/s,arch['kind'],arch['A'])
                    bs=scenes(q,wq,dx,arch['pooled'])
                    parts=[];counts=[]
                    for bank,b in enumerate(bs):
                        y,c=reconstruct(b,cu,n,ranges[arch['label'],li,name,bank],read,thermal,rng)
                        parts.append(y);counts.append(c)
                    got=((parts[0]+16*parts[1])*dw).astype(np.float32)
                    error=got.astype(float)-clean
                    tensors.append(dict(layer=li,tensor=name,banks=counts,
                                        MVM_mse=float(np.mean(error**2)),MVM_signal_ms=float(np.mean(clean.astype(float)**2))))
                    return got
                net.mvm=compute;metrics=ev.score(net(ids));assert len(tensors)==210
                totals={k:sum(b[k] for t in tensors for b in t['banks']) for k in
                        ('conversions','ADC_decisions','clips','column_plane_events','host_fit_violations',
                         'host_columns','connected_cap_proxy_fF','positive_matching_padding_fF')}
                maxima={k:max(b[k] for t in tensors for b in t['banks']) for k in
                        ('maximum_original_host_fF','maximum_padded_host_fF','maximum_joined_seen_fF',
                         'maximum_physical_DAC_fF','maximum_matching_padding_fF','maximum_abs_charge_fC','maximum_held_V')}
                r=dict(source=path.name,architecture=arch['label'],mode=mode,seed=seed,
                       **metrics,**totals,**maxima,tensors=tensors,runtime_s=time.perf_counter()-tic,
                       joint_pass=metrics['kl']<=.01 and metrics['ppl_ratio']<=1.01)
                results.append(r);report['runtime_s']=time.perf_counter()-started
                output.write_text(json.dumps(report,indent=2)+'\n')
                print(f"N{n} Cu{cu} {path.stem[:12]} {arch['label']} {mode} seed{seed} "
                      f"KL={metrics['kl']:.6g} PPL={metrics['ppl_ratio']:.7f} PASS={r['joint_pass']} "
                      f"clips={r['clips']} time={r['runtime_s']:.2f}s",flush=True)
        net.mvm=None;assert np.array_equal(net(ids),ev.ref)
    assert all(fingerprint(f)==h for f,h in sources.items())
    report['complete']=True
    output.write_text(json.dumps(report,indent=2)+'\n')
    print('PASS arithmetic/execution; quality',sum(r['joint_pass'] for r in results),'/',len(results),output,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selfcheck',action='store_true')
    parser.add_argument('--calibrate',action='store_true')
    parser.add_argument('--bits',type=int,choices=(10,11,12),default=12)
    parser.add_argument('--cu',type=int,choices=(4,8,16,32),default=4)
    args=parser.parse_args()
    if args.selfcheck:selfcheck()
    elif args.calibrate:calibrate()
    else:evaluate(args.bits,args.cu)
