"""Falsifier: remove charge-code clipping at the same frozen charge quantum.

Unbounded codes are an oracle, not a circuit, precision or PPA claim. The clipped
control uses the unchanged phase2 implementation and old calibration ranges.
"""
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT / "scripts"))
from compiler.metrics import imc_fixed_charge_campaign as base
import numpy as np

OUT=ROOT/'build/campaign/charge_range_oracle'


def unbounded(bank,span):
    y=np.zeros(bank[0]['Q_per_Cu'].shape,dtype=float)
    for s in bank:
        Q=4*s['Q_per_Cu']
        step=3.75/16*span
        Q=np.floor(Q/step+.5)*step
        part=Q*np.exp2(s['B'][:,None])/(4*.45)*s['dx'][:,None]
        part[~s['active']]=0
        y+=part
    return y


def main():
    protocol=OUT/'protocol.json';p=json.loads(protocol.read_text())
    output=OUT/'results.json';assert not output.exists()
    _,old,net,weights,sources=base.load()
    calpath=ROOT/'build/campaign/fixed_charge/calibration.json'
    cal=json.loads(calpath.read_text())
    assert cal['complete'] and all(base.fingerprint(f)==h for f,h in cal['sources'].items())
    for path in (Path(__file__),protocol,calpath):sources[str(path)]=base.fingerprint(path)
    snapshot=OUT/f'source_{base.fingerprint(__file__)}.py'
    snapshot.write_bytes(Path(__file__).read_bytes())
    ranges={(r['architecture'],r['layer'],r['tensor'],r['bank']):r['selected_Vspan_V']
            for r in cal['records'] if r['ADC_bits']==12}
    results=[];report=dict(protocol=p,sources=sources,results=results,complete=False,
        classification='Unbounded-code diagnostic; physically unrealizable ADC range, no noise/PPA claim')
    for src in old['sources']:
        path=Path(src['path']);assert base.fingerprint(path)==src['sha256']
        ids=base.tokenize_greedy(path.read_text(),net.vocab)[:512]
        net.mvm=None;ev=base.Eval(net,ids)
        for arch in p['architectures']:
            for bounded in (True,False):
                started=time.perf_counter();tensors=[]
                def compute(li,name,a,w,clean):
                    s,wq,dw=weights[li,name]
                    q,dx,expanded=base.quantize(a/s,arch['kind'],arch['A'])
                    bs=base.scenes(q,wq,dx,arch['pooled']);parts=[];clips=0
                    for bank,b in enumerate(bs):
                        span=ranges[arch['label'],li,name,bank]
                        y,counts=base.reconstruct(b,4,12,span)
                        clips+=counts['clips']
                        parts.append(y if bounded else unbounded(b,span))
                    got=((parts[0]+16*parts[1])*dw).astype(np.float32)
                    exact=((q.astype(float)*expanded)@wq)*dw
                    tensors.append(dict(layer=li,tensor=name,would_clip=clips,
                        quantizer_MSE=float(np.mean((got-exact)**2)),
                        ideal_WA_signal_ms=float(np.mean(exact**2))))
                    return got
                net.mvm=compute;metrics=ev.score(net(ids));assert len(tensors)==210
                results.append(dict(source=path.name,architecture=arch['label'],bounded=bounded,
                    **metrics,joint_pass=metrics['kl']<=.01 and metrics['ppl_ratio']<=1.01,
                    would_clip=sum(t['would_clip'] for t in tensors),tensors=tensors,
                    runtime_s=time.perf_counter()-started))
                output.write_text(json.dumps(report,indent=2)+'\n')
                print(path.stem[:12],arch['label'],'bounded',bounded,
                      {k:results[-1][k] for k in ('kl','ppl_ratio','joint_pass','would_clip')},flush=True)
        net.mvm=None;assert np.array_equal(net(ids),ev.ref)
    assert all(base.fingerprint(f)==h for f,h in sources.items())
    report['complete']=True;output.write_text(json.dumps(report,indent=2)+'\n')
    print('PASS: immutable clipping falsifier; unbounded arithmetic is not a circuit',flush=True)


if __name__=='__main__':main()
