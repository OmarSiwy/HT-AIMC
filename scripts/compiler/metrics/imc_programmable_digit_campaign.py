"""Fresh matched ADC calibration for exact W8 digits with measured Cu4 loading."""
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
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT / "scripts"))
from compiler.metrics import imc_programmable_loading_campaign as loading
legacy=loading.legacy
reset=loading.reset
np=loading.np
BASE_DIGITS=legacy.digits
OUT=ROOT/'build/campaign/programmable_digit_precision'
FORMATS=['signed_magnitude','balanced9','signed8','saturated_balanced8']


def radix(fmt):
    return 8 if fmt in ('signed8','saturated_balanced8') else 9 if fmt=='balanced9' else 16


def digits(w,fmt):
    if fmt in ('signed_magnitude','balanced9'):return BASE_DIGITS(w,fmt)
    w=np.asarray(w,dtype=np.int16)
    assert np.all((w>=-127)&(w<=127)), 'Frozen symmetric W8 support excludes -128'
    if fmt=='signed8':high=np.sign(w)*(abs(w)//8)
    else:
        assert fmt=='saturated_balanced8'
        high=np.clip((w+4)//8,-15,15)
    return w-8*high,high,0


def selfcheck():
    q=np.arange(-127,128,dtype=np.int16)
    for fmt in FORMATS:
        lo,hi,_=digits(q,fmt)
        assert np.array_equal(lo.astype(np.int64)+radix(fmt)*hi,q)
        assert max(abs(lo).max(),abs(hi).max())<=15
    rng=np.random.default_rng(88141)
    a=rng.integers(-511,512,(7,257),dtype=np.int16)
    w=rng.integers(-127,128,(257,5),dtype=np.int16)
    dx=np.ones((7,2))
    for fmt in FORMATS:
        for pooled in (False,True):
            bs=loading.scenes(a,w,dx,pooled,fmt)
            expected=sum(radix(fmt)**i*sum(s['Q_per_Cu']*np.exp2(s['B'][:,None])/.45 for s in bank) for i,bank in enumerate(bs))
            assert np.allclose(expected,a.astype(float)@w,atol=1e-7)
    print('PASS exact symmetric W8 digit reconstruction and measured-load ragged matrix identity',flush=True)


def freeze():
    p=json.loads((loading.OUT/'protocol.json').read_text())
    for module in (loading,reset,legacy):p['sources'][str(Path(module.__file__))]=legacy.base.fingerprint(module.__file__)
    p['sources'][str(Path(__file__))]=legacy.base.fingerprint(__file__)
    p['formats']=FORMATS
    p['calibration']='Fresh per-MVM/bank/format ADC depth+span; old27h3 clean128 tokens only; measured unsignedC(code), corrected lumped kT/C and read20 proxy.'
    p['status']='Frozen before new digit calibration and quality; observed symmetric W8 support only'
    p['policies']=['min_error']
    p['reconstruction']='Original L+16H; balanced9 L+9H; signed8 and saturatedbalanced8 L+8H. Extra9H add remains charged; saturatedcarry decode unpriced.'
    OUT.mkdir(parents=True,exist_ok=True)
    path=OUT/'protocol.json';text=json.dumps(p,indent=2)+'\n'
    if path.exists():assert path.read_text()==text
    else:path.write_text(text)
    return p


def calibrate():
    selfcheck();p,_,net,weights,sources=legacy.load()
    output=OUT/'calibration_Cu4.json';assert not output.exists()
    note=next((Path.home()/'Documents/Projects/OmarSiwy.github.io/Notes/Circuit Design/Analog Design/Analog Compute').glob('27h3 *.md'))
    sources[str(note)]=legacy.base.fingerprint(note)
    ids=legacy.base.tokenize_greedy(note.read_text(),net.vocab)[:128]
    activations={}
    def capture(li,name,a,w,y):activations[li,name]=a.copy();return y
    net.mvm=capture;net(ids);net.mvm=None;assert len(activations)==210
    records=[];started=time.perf_counter()
    for fmt in p['formats']:
        for arch in p['architectures']:
            for (li,name),(scale,w,dw) in weights.items():
                q,dx,_=legacy.base.quantize(activations[li,name]/scale,arch['kind'],arch['A'])
                for bank,bs in enumerate(loading.scenes(q,w,dx,arch['pooled'],fmt)):
                    target=sum(s['Q_per_Cu']*np.exp2(s['B'][:,None])/.45*s['dx'][:,None] for s in bs)
                    grid=[]
                    for bits in p['ADC_bits']:
                        prepared=reset.prepare(bs,4,bits)
                        noise=legacy.noise_proxy(prepared,dw,20)
                        for span in p['Vspan_V']:
                            got,counts,_=legacy.read(prepared,4,bits,span,stats=True)
                            error=float(np.mean(((got-target)*dw)**2))
                            grid.append(dict(bits=bits,span=span,deterministic_MSE=error,noise_variance_proxy=noise,total_proxy=error+noise,
                                             clips=counts['clips'],connected_C_fF=counts['connected_C_fF']))
                    best=min(grid,key=lambda g:(g['total_proxy'],g['bits'],g['span']))
                    records.append(dict(format=fmt,architecture=arch['label'],layer=li,tensor=name,bank=bank,selected={'min_error':best},grid=grid))
                if (li+1)%5==0 and name==legacy.base.TENSORS[-1]:print('calibration',fmt,arch['label'],li+1,flush=True)
    assert all(legacy.base.fingerprint(f)==h for f,h in sources.items())
    output.write_text(json.dumps(dict(complete=True,Cu_fF=4,protocol=p,sources=sources,records=records,
        calibration_token_ids_sha256=hashlib.sha256(np.array(ids,dtype='<i4').tobytes()).hexdigest(),runtime_s=time.perf_counter()-started),indent=2)+'\n')
    print('PASS frozen measured-loading corrected-noise ADC calibration',flush=True)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--selfcheck',action='store_true');ap.add_argument('--freeze',action='store_true');ap.add_argument('--calibrate',action='store_true');a=ap.parse_args()
    legacy.OUT,legacy.digits,legacy.radix=OUT,digits,radix
    legacy.prepare,legacy.scenes,legacy.selfcheck,legacy.freeze=reset.prepare,loading.scenes,selfcheck,freeze
    if a.selfcheck:selfcheck()
    elif a.freeze:freeze()
    elif a.calibrate:calibrate()
    else:legacy.evaluate(4)
