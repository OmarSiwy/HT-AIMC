"""Optimistic grounded3+4-bit group32, paid differential noise and original Q8_0."""
import argparse
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT / "scripts"))
from compiler.metrics import imc_raw32_precision as raw32
from compiler.metrics import imc_group128_precision as differential
base,np=raw32.base,raw32.np
OUT=ROOT/'build/campaign/grounded_group32_r50'
LOW=ROOT/'build/campaign/programmable_cap/wn050_wp070_bits3_tt27_fresh_step1_r1/result.json'
HIGH=ROOT/'build/campaign/programmable_cap/wn050_wp070_tt27_fresh_step1_r1/result.json'
prepare,read=differential.prepare,differential.read


def freeze():
    _,old,net,frozen,sources=base.load()
    for f in (Path(__file__),Path(raw32.__file__),Path(differential.__file__),
              Path(raw32.original.__file__),Path(raw32.nominal.__file__),raw32.PDK,
              ROOT/'scripts/compiler/metrics/imc_fixed_cap_mismatch.py',raw32.nominal.loading.MEASURED,LOW,HIGH):
        sources[str(f)]=base.fingerprint(f)
    for path,expected in ((LOW,28.),(HIGH,60.)):
        data=json.loads(path.read_text());rows=[r for r in data['rows'] if r['mode']=='grounded']
        assert len(rows)==(8 if expected==28 else 16)
        assert all(r['port_loading'][0]['frequency_Hz']==1000 and np.isclose(r['port_loading'][0]['effective_cap_fF'],expected,atol=1e-7) for r in rows)
    p=dict(status='Frozen optimistic grounded quality before calibration',group_rows=32,Cu_fF=4,
        thermal_multiplier=2,additional_read_noise_uV=50,seeds=[61001,61002],dies=[1,2],
        sharing_modes=['resident','reuse8'],ADC_bits=list(range(8,15)),spans_V=[.03125,.0625,.125,.25,.5,1.],sources=sources,
        representation='Exact original Q8_0 group32 integer codes and FP16 scales, no smoothing, common A11. Digital group scale before merging. Low3bit7Cu/high4bit15Cu constanttotal.',
        calibration='Old27h3 clean128 only; perMVM/bank depth/span min summed scaled quantization error plus2kT/C+50uV. No evaluation or mismatch fitting.',
        loading='Grounded unsigned TT AC supports28/60fF perrow. Column120fF perbank; low1016/high2040fF beforeCDAC padding. Nominal signal and reference holders match computationalC; no code-dependent idle TG drain at floatingcolumn in this optimistic model.',
        mismatch='Exact same fixed numerator-error draws and resident/reuse8 indices as oldraw32. No actualdenominator/holder/radix error or calibrated correction.',
        hardware='Unsigned3+4bit grounded AC only; selected complete signedtopology, columnloading, finitegaincalibration, noise covariance and PVT unverified.2kT/C assumes independent equal signal/referenceholders; additional50uV readtarget remains unqualified.',
        costs='22Cu/site magnitude storage, signalarray+holderC andfineDAC inconnectedC, extra referenceholderC separate;6.4times original256rowbankreads, paidgroupFP16scales, reuse8 phaseprogramming/SRAM and dynamicBcontrol.',
        evaluation='Two exposed512tokenpassages, two fixed dies, two noise seeds each; mismatch-only diagnostic. No yield or SoTA.')
    OUT.mkdir(parents=True,exist_ok=True);path=OUT/'protocol.json';text=json.dumps(p,indent=2)+'\n'
    if path.exists():assert path.read_text()==text
    else:path.write_text(text)
    sources[str(path)]=base.fingerprint(path)
    return p,old,net,raw32.original.raw_weights(net,frozen),sources


def scenes(a,record,label=None,die=0,sharing='resident'):
    for bank,s in enumerate(raw32.scenes(a,record,'none',label,die,sharing)):
        yield dict(s,units=np.full(s['units'].shape,32*(7 if bank==0 else 15),dtype=float))


def selfcheck():
    r=dict(q=np.ones((8,32,5),np.int8),d=np.ones((8,5)),group_smoothing=np.ones(8))
    a=np.ones((3,256));banks=list(scenes(a,r));control=raw32.scenes(a,r,'none')
    for bank,s in enumerate(banks):
        assert np.array_equal(s['Q'],control[bank]['Q']) and np.array_equal(s['factor'],control[bank]['factor'])
        C,stats,_=prepare(s,12)
        assert np.all(C==(1016 if bank==0 else 2040))
        assert stats['reference_holder_C_fF']==C.sum()
    print('PASS unchanged signal/group scales and paid grounded signal/reference capacitance',flush=True)


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
    print('PASS grounded group32 ADC calibration and source audit',flush=True)


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
    print('PASS grounded group32 physical-budget model and source audit',flush=True)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--calibrate',action='store_true');ap.add_argument('--die',type=int,choices=(1,2));a=ap.parse_args()
    if a.calibrate:calibrate()
    else:assert a.die is not None;evaluate(a.die)
