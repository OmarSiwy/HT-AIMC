"""Original group32 weights, paid ADC selection and fixed-cap/read-noise model."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT / "scripts"))
from compiler.metrics import imc_original_q8_groups as original
from compiler.metrics import imc_programmable_digit_campaign as nominal
from compiler.metrics.imc_fixed_cap_mismatch import coefficient_variance,PDK
base,np,legacy=original.base,original.np,nominal.legacy
OUT=ROOT/'build/campaign/raw32_precision'
CU=4
ERRORS={}


def freeze():
    _,old,net,frozen,sources=base.load()
    for f in (Path(__file__),Path(original.__file__),Path(nominal.__file__),PDK,
              ROOT/'scripts/compiler/metrics/imc_fixed_cap_mismatch.py',nominal.loading.MEASURED):
        sources[str(f)]=base.fingerprint(f)
    p=dict(status='Frozen raw32 physical-budget model before ADC calibration or quality',sources=sources,
        Cu_fF=CU,additional_read_noise_uV=40,ADC_bits=list(range(8,15)),spans_V=[.03125,.0625,.125,.25,.5,1.],
        input_modes=['none','group32_power2'],sharing_modes=['resident','reuse8'],seeds=[61001,61002],dies=[1,2],
        calibration='Old27h3 clean128 inputs only. One depth/span perMVM/bank across all32-row groups. Minimize actual summed scaled ADC error plus independent kT/C and40uV read variance. No heldout fitting or mismatch calibration.',
        weights='Original Q8_0 int8 codes and FP16 scale per32 rows/output. Scale applied to each group before digital merging. Group smoothing optionally folds one fixed power-of-two exponent perinputgroup.',
        loading='Measured Cu4 unsigned programming C(code),120fF column floor per32-row group, actual native distributed-CDAC host padding. Ideal matched holder perphase and ideal signal transfer. Dynamic programming/radix/sign/PEX unverified.',
        noise='Stationary kT/C reset/share perholder plus40uV additional read RMS; independent fresh draws pergroup conversion. Fixed PDK numerator errors reused across alltokens/passages. No holder/parasitic/ADC mismatch, calibration correction or row-DAC error.',
        sharing='Resident: independent perweight capacitors. Reuse8: each logical256-row tile uses32 physical sites, site(row)=floor(row/256)*32+row%32; up to8 SRAM weights/site, final raggedtile retains32 sites. Fixed errors shared across phases; requires paid perphase holder matching. Native ADC choices unchanged between these modes.',
        scheduling='Two bank conversions per32-row/output partial. No analog merging across unequal FP16 scales. Counts distinguish logicalgroup service from physicalsite count; no latency/energy or reservoir duplication inferred without a service schedule.',
        evaluation='Two existing exposed512-token passages; mismatch-only diagnostic and two declared kT/C+40uV noise seeds perdie/mode. No yield or SoTA qualification.')
    OUT.mkdir(parents=True,exist_ok=True);path=OUT/'protocol.json';text=json.dumps(p,indent=2)+'\n'
    if path.exists():assert path.read_text()==text
    else:path.write_text(text)
    sources[str(path)]=base.fingerprint(path)
    return p,old,net,original.raw_weights(net,frozen),sources


def product(q,w):
    return np.matmul(q.transpose(1,0,2).astype(np.float32),w.astype(np.float32)).transpose(1,0,2).astype(float)


def fixed_errors(record,label,die,sharing):
    key=label,die,sharing
    if key not in ERRORS:
        seed=int.from_bytes(hashlib.sha256(f'raw32_cap:{die}:{label}'.encode()).digest()[:8],'little')
        rng=np.random.default_rng(seed);digits=nominal.digits(record['q'],'signed8')[:2]
        ni,no=record['q'].shape[0]*32,record['q'].shape[-1]
        index=np.arange(ni) if sharing=='resident' else (np.arange(ni)//256)*32+np.arange(ni)%32
        errors=[]
        for digit in digits:
            _,sigma,selected=coefficient_variance(digit)
            z=rng.standard_normal((ni,no,4))[index].reshape(selected.shape)
            errors.append((np.sum(z*sigma*selected,axis=-1)*np.sign(digit)).astype(np.float32))
        ERRORS[key]=errors
    return ERRORS[key]


def scenes(a,record,mode,label=None,die=0,sharing='resident'):
    q,dx,sg=original.inputs(a,record,mode)
    B=np.ceil(np.log2(np.max(abs(q.astype(float)),axis=2)+1)).astype(int)
    scale=dx[:,:,None]*sg[None,:,None]*record['d'][None,:,:]
    digits=nominal.digits(record['q'],'signed8')[:2]
    errors=fixed_errors(record,label,die,sharing) if die else [0,0]
    banks=[]
    for digit,error in zip(digits,errors):
        exact=product(q,digit)
        actual=exact if not die else exact+product(q,error)
        banks.append(dict(Q=CU*.45*actual/np.exp2(B[:,:,None]),
            target=np.sum(exact*scale,axis=1),factor=np.exp2(B[:,:,None])/(CU*.45)*scale,
            active=B>0,B=B,units=nominal.loading.CAPS[abs(digit)].sum(axis=1)/CU))
    return banks


def prepare(scene,bits):
    caps,stats=legacy.geometry(scene['units'].reshape(1,-1),CU,bits)
    C=caps.reshape(scene['units'].shape)
    var=base.KT*1e15*C+(C*40e-6)**2
    proxy=float(np.mean(np.sum(var[None,:,:]*scene['factor']**2*scene['active'][:,:,None],axis=1)))
    return C,stats,proxy


def read(scene,bits,span,C,rng=None,noise=False):
    Q=scene['Q']
    if noise:
        var=base.KT*1e15*C+(C*40e-6)**2
        Q=Q+rng.standard_normal(Q.shape)*np.sqrt(var)[None,:,:]
    step=3.75*CU/4/16*span
    raw=np.floor(Q/step+.5)
    clipped=(raw < -2**(bits-1)) | (raw > 2**(bits-1)-1)
    converted=np.clip(raw,-2**(bits-1),2**(bits-1)-1)*step
    converted*=scene['active'][:,:,None]
    out=np.sum(converted*scene['factor'],axis=1)
    count=dict(conversions=int(scene['active'].sum())*Q.shape[-1],
        clips=int(np.count_nonzero(clipped&scene['active'][:,:,None])),
        column_plane_events=int(scene['B'].sum())*Q.shape[-1])
    count['ADC_decisions']=bits*count['conversions']
    count.update(ADC_bits=bits,span_V=span,deltaQ_fC=step,
        native_LSB_uV_min=float(step/C.max()*1e6),native_LSB_uV_max=float(step/C.min()*1e6),
        minimum_holder_fF=float(C.min()),maximum_holder_fF=float(C.max()),
        maximum_calculated_abs_native_V=float(np.max(abs(scene['Q'])/C[None,:,:])))
    return out,count


def selfcheck():
    rng=np.random.default_rng(914120)
    q=rng.integers(-50,51,(4,3,32));w=rng.integers(-127,128,(3,32,5))
    assert np.allclose(product(q,w),np.stack([q[:,g]@w[g] for g in range(3)],axis=1))
    units=np.ones((3,5))*5
    for bits in (8,10,12):
        flat,_=legacy.geometry(units.reshape(1,-1),CU,bits)
        for g in range(3):
            separate,_=legacy.geometry(units[g:g+1],CU,bits)
            assert np.array_equal(flat.reshape(3,5)[g],separate[0])
    r=dict(q=np.ones((8,32,5),dtype=np.int8));e=fixed_errors(r,'selfcheck',1,'reuse8')
    assert all(np.array_equal(a,b) for a,b in zip(e,fixed_errors(r,'selfcheck',1,'reuse8')))
    assert np.array_equal(e[0][0],e[0][7])
    B=np.full((4,3),6);dx=rng.uniform(.01,.1,(4,3));dw=rng.uniform(.01,.1,(3,5))
    s=dict(Q=rng.uniform(-20,20,(4,3,5)),B=B,active=B>0,units=units,
           factor=np.exp2(B[:,:,None])/(CU*.45)*dx[:,:,None]*dw[None,:,:])
    C,_,_=prepare(s,12);actual,_=read(s,12,.5,C);expected=np.zeros_like(actual)
    for g in range(3):
        old=dict(Q=s['Q'][:,g],C=C[g],B=B[:,g],dx=dx[:,g],active=s['active'][:,g])
        got,_,_=legacy.read([old],CU,12,.5)
        expected+=got*dw[g]
    assert np.allclose(actual,expected,rtol=1e-12,atol=1e-12)
    ERRORS.clear()
    print('PASS partial products, group geometry, shared-site errors and legacy-read scaled-sum oracle',flush=True)


def calibrate():
    selfcheck();p,_,net,raw,sources=freeze()
    output=OUT/'calibration.json';assert not output.exists()
    note=next((Path.home()/'Documents/Projects/OmarSiwy.github.io/Notes/Circuit Design/Analog Design/Analog Compute').glob('27h3 *.md'))
    sources[str(note)]=base.fingerprint(note)
    ids=base.tokenize_greedy(note.read_text(),net.vocab)[:128];inputs={}
    def capture(li,name,a,w,clean):inputs[li,name]=a.copy();return clean
    net.mvm=capture;net(ids);net.mvm=None;assert len(inputs)==210
    records=[];started=time.perf_counter()
    for mode in p['input_modes']:
        for label,record in raw.items():
            for bank,s in enumerate(scenes(inputs[label],record,mode)):
                grid=[]
                for bits in p['ADC_bits']:
                    C,stats,proxy=prepare(s,bits)
                    for span in p['spans_V']:
                        got,counts=read(s,bits,span,C)
                        mse=float(np.mean((got-s['target'])**2))
                        grid.append(dict(bits=bits,span=span,deterministic_MSE=mse,noise_variance=proxy,total=mse+proxy,
                            connected_C_fF=stats['connected_C_fF'],clips=counts['clips'],
                            minimum_holder_fF=counts['minimum_holder_fF'],maximum_holder_fF=counts['maximum_holder_fF'],
                            native_LSB_uV_min=counts['native_LSB_uV_min'],native_LSB_uV_max=counts['native_LSB_uV_max'],
                            maximum_calculated_abs_native_V=counts['maximum_calculated_abs_native_V']))
                best=min(grid,key=lambda x:(x['total'],x['bits'],x['span']))
                records.append(dict(mode=mode,layer=label[0],tensor=label[1],bank=bank,selected=best,grid=grid))
            if (label[0]+1)%5==0 and label[1]==base.TENSORS[-1]:print('calibrated',mode,label[0]+1,flush=True)
    assert all(base.fingerprint(f)==h for f,h in sources.items())
    output.write_text(json.dumps(dict(complete=True,protocol=p,sources=sources,records=records,runtime_s=time.perf_counter()-started),indent=2)+'\n')
    print('PASS frozen raw32 ADC calibration and source audit',flush=True)


def evaluate(die):
    selfcheck();p,old,net,raw,sources=freeze()
    cp=OUT/'calibration.json';cal=json.loads(cp.read_text());assert cal['complete']
    assert all(base.fingerprint(f)==h for f,h in cal['sources'].items())
    sources[str(cp)]=base.fingerprint(cp)
    choices={(r['mode'],r['layer'],r['tensor'],r['bank']):r['selected'] for r in cal['records']}
    output=OUT/f'quality_die{die}.json';assert not output.exists();results=[]
    report=dict(complete=False,die=die,protocol=p,sources=sources,results=results)
    for src in old['sources']:
        note=Path(src['path']);assert base.fingerprint(note)==src['sha256']
        ids=base.tokenize_greedy(note.read_text(),net.vocab)[:512]
        net.mvm=None;ev=base.Eval(net,ids)
        for mode in p['input_modes']:
            for sharing in p['sharing_modes']:
                for seed in [None]+p['seeds']:
                    rng=np.random.default_rng(seed);details=[];started=time.perf_counter()
                    def compute(li,name,a,w,clean):
                        banks=[]
                        for bank,s in enumerate(scenes(a,raw[li,name],mode,(li,name),die,sharing)):
                            setting=choices[mode,li,name,bank];n,span=setting['bits'],setting['span']
                            C,stats,_=prepare(s,n);got,counts=read(s,n,span,C,rng,seed is not None)
                            details.append(dict(layer=li,tensor=name,bank=bank,**stats,**counts));banks.append(got)
                        return (banks[0]+8*banks[1]).astype(np.float32)
                    net.mvm=compute;r=ev.score(net(ids))
                    r.update(source=note.name,input_mode=mode,sharing=sharing,seed=seed,
                        noise='fixed_mismatch_only' if seed is None else 'fixed_mismatch_kTC_read40',
                        runtime_s=time.perf_counter()-started,details=details)
                    r['joint_pass']=r['kl']<=.01 and r['ppl_ratio']<=1.01
                    for k in ('conversions','ADC_decisions','clips','column_plane_events','connected_C_fF','two_sided_padding_fF'):
                        r[k]=sum(d[k] for d in details)
                    results.append(r);output.write_text(json.dumps(report,indent=2)+'\n')
                    print(die,note.name[:8],mode,sharing,seed,{k:r[k] for k in ('kl','ppl_ratio','joint_pass','clips')},flush=True)
    assert all(base.fingerprint(f)==h for f,h in sources.items())
    report['complete']=True;output.write_text(json.dumps(report,indent=2)+'\n')
    print('PASS raw32 complete-depth model and source audit',flush=True)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--calibrate',action='store_true');ap.add_argument('--die',type=int,choices=(1,2))
    ap.add_argument('--selfcheck',action='store_true');a=ap.parse_args()
    if a.selfcheck:selfcheck()
    elif a.calibrate:calibrate()
    else:assert a.die is not None;evaluate(a.die)
