"""Fixed per-cap numerator mismatch in full-depth programmable-load sensitivity.

Ideal holder matching/column normalization is retained. This omits radix error
from unmatched holders and is not a full physical mismatch/yield prediction.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT / "scripts"))
from compiler.metrics import imc_programmable_digit_campaign as nominal
from compiler.metrics.imc_fixed_cap_mismatch import coefficient_variance,PDK
legacy=nominal.legacy
np=nominal.np
LABELS={}
CACHE={}
DIE=1
OUT=ROOT/'build/campaign/fixed_mismatch_quality/die1'
original_load=legacy.load


def errors(w,fmt):
    label=LABELS[id(w)]
    key=label,fmt,DIE
    if key not in CACHE:
        seed=int.from_bytes(hashlib.sha256(f'cap_mismatch:{DIE}:{label}:{fmt}'.encode()).digest()[:8],'little')
        rng=np.random.default_rng(seed);out=[]
        for digit in nominal.digits(w,fmt)[:2]:
            _,sigma,selected=coefficient_variance(digit)
            error=np.sum(rng.standard_normal(selected.shape)*sigma*selected,axis=-1)*np.sign(digit)
            out.append(error.astype(np.float32))
        CACHE[key]=out
    return CACHE[key]


def scenes(q,w,dx,pooled,fmt):
    banks=nominal.loading.scenes(q,w,dx,pooled,fmt)
    groups=(q.shape[1]+255)//256
    for bank,error in zip(banks,errors(w,fmt)):
        for scene,first in zip(bank,range(0,groups,4 if pooled else 1)):
            last=min(first+(4 if pooled else 1),groups)
            correction=q[:,first*256:last*256].astype(np.float32)@error[first*256:last*256]
            scene['Q_per_Cu']+=.45*correction/np.exp2(scene['B'][:,None])
    return banks


def selfcheck():
    nominal.selfcheck()
    w=np.arange(-127,128,dtype=np.int16).reshape(255,1);LABELS[id(w)]='selfcheck'
    q=np.ones((3,255),dtype=np.int16);dx=np.ones((3,1))
    for fmt in ('balanced9','signed8'):
        a=scenes(q,w,dx,False,fmt);b=scenes(q,w,dx,False,fmt)
        assert all(np.array_equal(x['Q_per_Cu'],y['Q_per_Cu']) for aa,bb in zip(a,b) for x,y in zip(aa,bb))
        del CACHE['selfcheck',fmt,DIE]
        c=scenes(q,w,dx,False,fmt)
        assert all(np.array_equal(x['Q_per_Cu'],y['Q_per_Cu']) for aa,bb in zip(a,c) for x,y in zip(aa,bb))
    LABELS.clear();CACHE.clear()
    print('PASS immutable per-physical-cap/per-die error across calls and deterministic cache reconstruction',flush=True)


def freeze():
    p=json.loads((nominal.OUT/'protocol.json').read_text())
    p['sources'][str(Path(__file__))]=legacy.base.fingerprint(__file__)
    p['sources'][str(PDK)]=legacy.base.fingerprint(PDK)
    p['sources'][str(ROOT/'scripts/compiler/metrics/imc_fixed_cap_mismatch.py')]=legacy.base.fingerprint(ROOT/'scripts/compiler/metrics/imc_fixed_cap_mismatch.py')
    p['formats']=['balanced9','signed8']
    p['modes']=[['fixed_mismatch_only',0,False,None],['fixed_mismatch_read20',20,True,60001],['fixed_mismatch_read20',20,True,60002]]
    p['status']='Frozen fixed-cap mismatch sensitivity; nominal ADC calibration retained'
    p['mismatch']=dict(die=DIE,seed_policy='SHA256(die,layer/tensor label,format), independent Gaussian perphysicalbinarycap; fixed across all input calls and both passages',
        geometry='Square4/8/16/32fF TT C=2u²+.76u, relative sigma=.028/u, mf1',
        scope='Numerator coefficient error only. Nominal loading and ideal matched holder normalization retained; holder/array radix mismatch, internal-mode/parasitic/ADC/state mismatch omitted. No siliconyieldclaim.',
        calibration='Frozen nominal measured-loading ADC depth/range; no perweight or percolumn mismatch calibration')
    OUT.mkdir(parents=True,exist_ok=True)
    path=OUT/'protocol.json';text=json.dumps(p,indent=2)+'\n'
    if path.exists():assert path.read_text()==text
    else:path.write_text(text)
    src=nominal.OUT/'calibration_Cu4.json';dst=OUT/src.name
    if src.exists():
        assert json.loads(src.read_text())['complete']
        if dst.exists():assert src.read_bytes()==dst.read_bytes()
        else:dst.write_bytes(src.read_bytes())
    return p


def load():
    value=original_load()
    for (layer,name),(_,w,_) in value[3].items():LABELS[id(w)]=f'{layer}:{name}'
    return value


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--die',type=int,choices=(1,2),default=1);ap.add_argument('--selfcheck',action='store_true');ap.add_argument('--freeze',action='store_true');a=ap.parse_args()
    DIE=a.die;OUT=ROOT/f'build/campaign/fixed_mismatch_quality/die{DIE}'
    legacy.digits,legacy.radix=nominal.digits,nominal.radix
    legacy.OUT,legacy.prepare,legacy.scenes=OUT,nominal.reset.prepare,scenes
    legacy.selfcheck,legacy.freeze,legacy.load=selfcheck,freeze,load
    if a.selfcheck:selfcheck()
    elif a.freeze:freeze()
    else:legacy.evaluate(4)
