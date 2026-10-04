"""Frozen old-input subspaces: expected fixed-cap error and paid rank overhead.

This is an ensemble linear-error oracle, not full nonlinear model quality.
"""
import hashlib
import json
import os
from pathlib import Path
import sys
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT / "scripts"))
import numpy as np
from compiler.metrics import imc_fixed_charge_campaign as base
from compiler.metrics.imc_programmable_digit_campaign import digits,radix
from compiler.metrics.imc_fixed_cap_mismatch import coefficient_variance,PDK

OUT=ROOT/'build/campaign/mismatch_subspace_screen'


def capture(net,ids):
    inputs={}
    def hook(li,name,a,w,y):inputs[li,name]=a.copy();return y
    net.mvm=hook
    try:net(ids)
    finally:net.mvm=None
    assert len(inputs)==210
    return inputs


def main():
    OUT.mkdir(parents=True,exist_ok=True);path=OUT/'result.json';assert not path.exists()
    _,old,net,weights,sources=base.load()
    note=next((Path.home()/'Documents/Projects/OmarSiwy.github.io/Notes/Circuit Design/Analog Design/Analog Compute').glob('27h3 *.md'))
    for p in (note,Path(__file__),PDK):sources[str(p)]=base.fingerprint(p)
    protocol=dict(formats=['balanced9','signed8'],ranks=[0,1,4,8,16],calibration='old27h3 first128 clean tokens',
        evaluation='Two previously exposed512-token passages; clean input trajectories, not mismatch-perturbed network trajectories; reserved untouched',
        oracle='Mean offset plus perfect correction of the top rank-r directions of calibration inputs weighted by PDK fixed-weight variance. Correction coefficients assume known physical errors; hardware measurement, quantization and nonlinear feedback are not validated.',
        sources=sources)
    pp=OUT/'protocol.json';assert not pp.exists();pp.write_text(json.dumps(protocol,indent=2)+'\n')
    cal=capture(net,base.tokenize_greedy(note.read_text(),net.vocab)[:128]);basis={};shapes={}
    for fmt in protocol['formats']:
        for label,(scale,w,dw) in weights.items():
            lo,hi,_=digits(w,fmt);vl,_,_=coefficient_variance(lo);vh,_,_=coefficient_variance(hi)
            variance=((vl+radix(fmt)**2*vh)*dw[None,:]**2/scale[:,None]**2).mean(axis=1)
            root=np.sqrt(variance);mean=cal[label].astype(float).mean(axis=0)
            X=(cal[label].astype(float)-mean)*root
            eigen,vectors=np.linalg.eigh(X@X.T)
            top=np.argsort(eigen)[-16:][::-1];lam=eigen[top]
            assert np.all(lam>0)
            U=X.T@vectors[:,top]/np.sqrt(lam)[None,:]
            assert np.allclose(U.T@U,np.eye(16),atol=1e-7)
            basis[fmt,label]=(root,mean,U);shapes[label]=w.shape
        print('PASS calibrated weighted subspace',fmt,flush=True)
    results=[]
    for src in old['sources']:
        p=Path(src['path']);assert base.fingerprint(p)==src['sha256']
        inputs=capture(net,base.tokenize_greedy(p.read_text(),net.vocab)[:512])
        for fmt in protocol['formats']:
            for label,A in inputs.items():
                root,mean,U=basis[fmt,label]
                A=A.astype(float);raw=float(np.sum((A*root)**2))
                centered=(A-mean)*root;energy=float(np.sum(centered**2));scores=centered@U
                captured=np.sum(scores**2,axis=0)
                for rank in protocol['ranks']:
                    residual=energy-float(captured[:rank].sum())
                    assert residual>=-1e-8*max(energy,1)
                    ni,no=shapes[label]
                    results.append(dict(source=p.name,format=fmt,layer=label[0],tensor=label[1],rank=rank,
                        baseline_expected_error_energy=raw,residual_expected_error_energy=max(residual,0.),
                        error_energy_ratio=max(residual,0.)/raw,
                        correction_MACs_per_token=rank*(ni+no),matrix_MACs_per_token=ni*no,
                        stored_float32_coefficients=rank*(ni+no)+no))
            print('PASS heldout input-subspace energy',p.name[:12],fmt,flush=True)
    assert all(base.fingerprint(p)==h for p,h in sources.items())
    path.write_text(json.dumps(dict(complete=True,protocol=protocol,results=results),indent=2)+'\n')
    print('PASS weighted orthonormality, nonnegative residual and unchanged source fingerprints',flush=True)


if __name__=='__main__':main()
