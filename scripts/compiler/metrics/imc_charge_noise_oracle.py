"""Unbounded charge codes with the frozen N12 holder/noise model.

This is an optimistic accuracy target. Overflow-correction hardware, its extra
capacitance/noise/energy and its service time do not exist in this oracle.
"""
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT / "scripts"))
from compiler.metrics import imc_fixed_charge_campaign as base
import numpy as np

OUT=ROOT/'build/campaign/charge_noise_oracle'


def read(bank,span,read_uv,thermal,rng):
    result=np.zeros(bank[0]['Q_per_Cu'].shape,dtype=float)
    for scene in bank:
        # Reuse the original complete noise/capacitor calculation with only its
        # quantizer disabled. Single-scene inverse scaling recovers noisy Q.
        exact,counts=base.reconstruct([scene],4,12,span,read_uv,thermal,rng,ideal=True)
        factor=np.exp2(scene['B'][:,None])/(4*.45)*scene['dx'][:,None]
        Q=exact/factor
        step=3.75/16*span
        result+=np.floor(Q/step+.5)*step*factor
    return result


def selfcheck():
    rng=np.random.default_rng(93821)
    q=rng.integers(-511,512,(13,730),dtype=np.int16)
    w=rng.integers(-127,128,(730,5),dtype=np.int16)
    dx=np.full((13,3),.03125)
    for pooled in (False,True):
        for bank in base.scenes(q,w,dx,pooled):
            # A large reference span suppresses clipping, so original and
            # unbounded quantizers must agree with the same complete noise.
            actual=read(bank,8.,20,True,np.random.default_rng(812))
            expected,counts=base.reconstruct(bank,4,12,8.,20,True,np.random.default_rng(812))
            assert counts['clips']==0 and np.allclose(actual,expected,atol=1e-10,rtol=1e-12)
    print('PASS: seeded noisy separate/pooled reconstruction parity in nonclipping control',flush=True)


def main():
    selfcheck();protocol=OUT/'protocol.json';p=json.loads(protocol.read_text())
    output=OUT/'results.json';assert not output.exists()
    _,old,net,weights,sources=base.load()
    ranges={}
    for directory in ('fixed_charge','fixed_charge_a11'):
        path=ROOT/f'build/campaign/{directory}/calibration.json';cal=json.loads(path.read_text())
        assert cal['complete'] and all(base.fingerprint(f)==h for f,h in cal['sources'].items())
        sources[str(path)]=base.fingerprint(path)
        ranges.update({(r['architecture'],r['layer'],r['tensor'],r['bank']):r['selected_Vspan_V']
                       for r in cal['records'] if r['ADC_bits']==12})
    for path in (Path(__file__),protocol):sources[str(path)]=base.fingerprint(path)
    (OUT/f'source_{base.fingerprint(__file__)}.py').write_bytes(Path(__file__).read_bytes())
    results=[];report=dict(protocol=p,sources=sources,results=results,complete=False,
        classification='Optimistic noise target with unbounded ADC codes; no actual overflow correction or PPA')
    for src in old['sources']:
        path=Path(src['path']);assert base.fingerprint(path)==src['sha256']
        ids=base.tokenize_greedy(path.read_text(),net.vocab)[:512]
        net.mvm=None;ev=base.Eval(net,ids)
        for arch in p['architectures']:
            for mode,read_uv,seed in p['modes']:
                rng=np.random.default_rng(seed);started=time.perf_counter()
                def compute(li,name,a,w,clean):
                    s,wq,dw=weights[li,name]
                    q,dx,_=base.quantize(a/s,arch['kind'],arch['A'])
                    bs=base.scenes(q,wq,dx,arch['pooled'])
                    parts=[read(b,ranges[arch['label'],li,name,bank],read_uv,True,rng)
                           for bank,b in enumerate(bs)]
                    return ((parts[0]+16*parts[1])*dw).astype(np.float32)
                net.mvm=compute;metrics=ev.score(net(ids))
                results.append(dict(source=path.name,architecture=arch['label'],mode=mode,
                    read_uV=read_uv,seed=seed,**metrics,
                    joint_pass=metrics['kl']<=.01 and metrics['ppl_ratio']<=1.01,
                    runtime_s=time.perf_counter()-started))
                output.write_text(json.dumps(report,indent=2)+'\n')
                print(path.stem[:12],arch['label'],mode,seed,
                      {k:results[-1][k] for k in ('kl','ppl_ratio','joint_pass')},flush=True)
        net.mvm=None;assert np.array_equal(net(ids),ev.ref)
    assert all(base.fingerprint(f)==h for f,h in sources.items())
    report['complete']=True;output.write_text(json.dumps(report,indent=2)+'\n')
    print('PASS: frozen unbounded noise target execution; not an overflow circuit',flush=True)


if __name__=='__main__':main()
