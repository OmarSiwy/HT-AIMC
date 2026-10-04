"""Paid group128 FP16 scales, fixed physical sites and differential-holder noise."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT / "scripts"))
from compiler.metrics import imc_raw32_precision as raw32
from compiler.metrics import imc_group_size_ceiling as grouped
base,np=raw32.base,raw32.np
OUT=ROOT/'build/campaign/group128_precision_r50'
GROUP=128
ERRORS={}


def freeze():
    _,old,net,frozen,sources=base.load()
    for f in (Path(__file__),Path(raw32.__file__),Path(grouped.__file__),
              Path(raw32.original.__file__),Path(raw32.nominal.__file__),raw32.PDK,
              ROOT/'scripts/compiler/metrics/imc_fixed_cap_mismatch.py',raw32.nominal.loading.MEASURED):
        sources[str(f)]=base.fingerprint(f)
    p=dict(status='Frozen before calibration or quality',group_rows=GROUP,Cu_fF=4,
        thermal_multiplier=2,additional_read_noise_uV=50,seeds=[61001,61002],dies=[1,2],
        sharing_modes=['resident','reuse2'],ADC_bits=list(range(8,15)),spans_V=[.03125,.0625,.125,.25,.5,1.],sources=sources,
        representation='Unsmoothed W8 group128 maxabs/127 rounded to storedFP16 before integer RTN. Common A11 activation scales recovered before partial sums. Ragged final group has only actual connected rows.',
        calibration='Old27h3 clean128 only; one ADC depth/span per MVM/bank minimizes output-scaled summed quantization error plus2kT/C and50uV variance. No mismatch correction or evaluation fitting.',
        mismatch='Fixed PDK numerator errors only; nominal C(code), holder match and CDAC. Resident sites independent perweight. Reuse2 shares physical128-row sites across each256-row tile; ragged sites retained. No perweight calibration.',
        noise='Two independent equal computational/reference holders C have differential2kT/C; scalar signal gain normalization unchanged. Additional50uV differential read target unqualified by hardware. No reference coupling/covariance/ADC/holder mismatch.',
        hardware='Measured Cu4 TT W.42 unsigned C(code),120fF pergroup floor and paid distributed-CDAC padding. Sign programming, matched sharing radix, reference fixture, dynamic B control and PVT unverified. Installed second-reference-holder C counted separately.',
        evaluation='Two exposed512-token passages; two fixed dies and two declared noise seeds. Mismatch-only diagnostic retains same finite ADC. No yield/SoTA claim.')
    OUT.mkdir(parents=True,exist_ok=True);path=OUT/'protocol.json';text=json.dumps(p,indent=2)+'\n'
    if path.exists():assert path.read_text()==text
    else:path.write_text(text)
    sources[str(path)]=base.fingerprint(path)
    weights={label:dict(zip(('q','d'),grouped.quantize(net.L[label[0]][label[1]],GROUP)),ni=net.L[label[0]][label[1]].shape[0]) for label in frozen}
    return p,old,net,weights,sources


def errors(record,label,die,sharing):
    key=label,die,sharing
    if key not in ERRORS:
        rng=np.random.default_rng(int.from_bytes(hashlib.sha256(f'group128_cap:{die}:{label}'.encode()).digest()[:8],'little'))
        q=record['q'];nr=q.shape[0]*GROUP;no=q.shape[-1]
        idx=np.arange(nr) if sharing=='resident' else np.arange(nr)//256*GROUP+np.arange(nr)%GROUP
        result=[]
        for digit in raw32.nominal.digits(q,'signed8')[:2]:
            _,sigma,selected=raw32.coefficient_variance(digit)
            z=rng.standard_normal((nr,no,4))[idx].reshape(selected.shape)
            result.append((np.sum(z*sigma*selected,axis=-1)*np.sign(digit)).astype(np.float32))
        ERRORS[key]=result
    return ERRORS[key]


def scenes(a,record,label=None,die=0,sharing='resident'):
    q,_,expanded=base.quantize(a,'common',11)
    q=np.pad(q,((0,0),(0,record['q'].shape[0]*GROUP-a.shape[1]))).reshape(len(a),-1,GROUP)
    B=np.ceil(np.log2(np.max(abs(q.astype(float)),axis=2)+1)).astype(int)
    scale=expanded[:,::GROUP,None]*record['d'][None,:,:]
    digits=raw32.nominal.digits(record['q'],'signed8')[:2]
    err=errors(record,label,die,sharing) if die else [0,0]
    valid=np.arange(record['q'].shape[0]*GROUP).reshape(-1,GROUP)<record['ni']
    for digit,error in zip(digits,err):
        exact=raw32.product(q,digit);actual=exact if not die else exact+raw32.product(q,error)
        yield dict(Q=4*.45*actual/np.exp2(B[:,:,None]),target=np.sum(exact*scale,axis=1),
            factor=np.exp2(B[:,:,None])/(4*.45)*scale,active=B>0,B=B,
            units=(raw32.nominal.loading.CAPS[abs(digit)]*valid[:,:,None]).sum(axis=1)/4)


def prepare(s,bits):
    C,stats,_=raw32.prepare(s,bits)
    var=2*base.KT*1e15*C+(C*50e-6)**2
    proxy=float(np.mean(np.sum(var[None,:,:]*s['factor']**2*s['active'][:,:,None],axis=1)))
    stats['reference_holder_C_fF']=float(C.sum())
    return C,stats,proxy


def read(s,bits,span,C,rng=None,noise=False):
    if noise:
        s=dict(s,Q=s['Q']+rng.standard_normal(s['Q'].shape)*np.sqrt(2*base.KT*1e15*C+(C*50e-6)**2)[None,:,:])
    return raw32.read(s,bits,span,C)


def selfcheck():
    rng=np.random.default_rng(775);w=rng.normal(size=(576,5));q,d=grouped.quantize(w,GROUP)
    record=dict(q=q,d=d,ni=576);a=rng.normal(size=(3,576));banks=list(scenes(a,record))
    actual=banks[0]['target']+8*banks[1]['target'];expected=grouped.compute(a,q,d,GROUP)
    assert np.allclose(actual,expected,rtol=2e-5,atol=2e-5)
    digit=raw32.nominal.digits(q,'signed8')[0]
    assert np.allclose(banks[0]['units'][-1],raw32.nominal.loading.CAPS[abs(digit[-1,:64])].sum(axis=0)/4)
    r=dict(q=np.ones((4,GROUP,5),np.int8),ni=512);e=errors(r,'test',1,'reuse2')
    assert np.array_equal(e[0][0],e[0][1]) and np.array_equal(e[0][2],e[0][3])
    assert not np.array_equal(e[0][0],e[0][2]);ERRORS.clear()
    print('PASS ragged physical loading, group scale recovery and reuse2 correlation',flush=True)


def calibrate():
    selfcheck();p,_,net,weights,sources=freeze();output=OUT/'calibration.json';assert not output.exists()
    note=next((Path.home()/'Documents/Projects/OmarSiwy.github.io/Notes/Circuit Design/Analog Design/Analog Compute').glob('27h3 *.md'))
    sources[str(note)]=base.fingerprint(note);inputs={}
    def capture(li,name,a,w,clean):inputs[li,name]=a.copy();return clean
    net.mvm=capture;net(base.tokenize_greedy(note.read_text(),net.vocab)[:128]);net.mvm=None
    records=[]
    for label,record in weights.items():
        for bank,s in enumerate(scenes(inputs[label],record)):
            grid=[]
            for bits in p['ADC_bits']:
                C,stats,proxy=prepare(s,bits)
                for span in p['spans_V']:
                    got,count=read(s,bits,span,C);mse=float(np.mean((got-s['target'])**2))
                    grid.append(dict(bits=bits,span=span,deterministic_MSE=mse,noise_variance=proxy,total=mse+proxy,**stats,**count))
            records.append(dict(layer=label[0],tensor=label[1],bank=bank,selected=min(grid,key=lambda r:(r['total'],r['bits'],r['span'])),grid=grid))
        if (label[0]+1)%5==0 and label[1]==base.TENSORS[-1]:print('calibrated',label[0]+1,flush=True)
    assert all(base.fingerprint(f)==h for f,h in sources.items())
    output.write_text(json.dumps(dict(complete=True,protocol=p,sources=sources,records=records),indent=2)+'\n')
    print('PASS group128 ADC calibration and source audit',flush=True)


def evaluate(die):
    selfcheck();p,old,net,weights,sources=freeze();cp=OUT/'calibration.json';cal=json.loads(cp.read_text())
    assert cal['complete'] and all(base.fingerprint(f)==h for f,h in cal['sources'].items())
    sources[str(cp)]=base.fingerprint(cp);choices={(r['layer'],r['tensor'],r['bank']):r['selected'] for r in cal['records']}
    output=OUT/f'quality_die{die}.json';assert not output.exists();results=[];report=dict(complete=False,die=die,protocol=p,sources=sources,results=results)
    for src in old['sources']:
        note=Path(src['path']);assert base.fingerprint(note)==src['sha256'];ids=base.tokenize_greedy(note.read_text(),net.vocab)[:512]
        net.mvm=None;ev=base.Eval(net,ids)
        for sharing in p['sharing_modes']:
            for seed in [None]+p['seeds']:
                rng=np.random.default_rng(seed);details=[];started=time.perf_counter()
                def compute(li,name,a,w,clean):
                    banks=[]
                    for bank,s in enumerate(scenes(a,weights[li,name],(li,name),die,sharing)):
                        setting=choices[li,name,bank];n,span=setting['bits'],setting['span'];C,stats,_=prepare(s,n)
                        got,count=read(s,n,span,C,rng,seed is not None);details.append(dict(layer=li,tensor=name,bank=bank,**stats,**count));banks.append(got)
                    return (banks[0]+8*banks[1]).astype(np.float32)
                net.mvm=compute;r=ev.score(net(ids));r.update(source=note.name,sharing=sharing,seed=seed,runtime_s=time.perf_counter()-started,details=details)
                r['joint_pass']=r['kl']<=.01 and r['ppl_ratio']<=1.01
                for k in ('conversions','ADC_decisions','clips','column_plane_events','connected_C_fF','two_sided_padding_fF','reference_holder_C_fF'):r[k]=sum(d[k] for d in details)
                results.append(r);output.write_text(json.dumps(report,indent=2)+'\n');print(die,note.name[:8],sharing,seed,{k:r[k] for k in ('kl','ppl_ratio','joint_pass')},flush=True)
    assert all(base.fingerprint(f)==h for f,h in sources.items());report['complete']=True;output.write_text(json.dumps(report,indent=2)+'\n')
    print('PASS group128 physical-budget model and source audit',flush=True)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--calibrate',action='store_true');ap.add_argument('--die',type=int,choices=(1,2));a=ap.parse_args()
    if a.calibrate:calibrate()
    else:assert a.die is not None;evaluate(a.die)
