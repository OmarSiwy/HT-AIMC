"""One calibrated input direction per MVM for fixed-cap error correction.

Floating sidecar factors and noiseless128-token calibration are explicit bounds;
additional physical sidecar precision, latency, energy and PVT are unverified.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT / "scripts"))
from compiler.metrics import imc_mismatch_offset_quality as offset
from compiler.metrics.imc_fixed_cap_mismatch import coefficient_variance
fixed=offset.fixed
nominal=fixed.nominal
legacy=fixed.legacy
np=fixed.np
FACTORS={}
DIE=1
OUT=ROOT/'build/campaign/mismatch_rank1_quality/die1'


class RankNet(offset.BaseNet):
    def __call__(self,*args,**kwargs):
        original=self.mvm
        if original is not None and FACTORS:
            def corrected(layer,name,a,w,clean):
                got=original(layer,name,a,w,clean)
                c=offset.CURRENT
                arch=f"common_A{c['A']}_{'pooled' if c['pooled'] else 'separate'}"
                prefix=offset.key(layer,name,c['format'],arch)
                vin,vout,bias=(FACTORS[prefix+suffix] for suffix in (':in',':out',':bias'))
                return (got-(a@vin)[:,None]*vout[None,:]-bias).astype(np.float32)
            self.mvm=corrected
        try:return super().__call__(*args,**kwargs)
        finally:self.mvm=original


def selfcheck():
    fixed.selfcheck()
    original=offset.BaseNet.__call__
    try:
        def fake(self,x):return x if self.mvm is None else self.mvm(0,'probe',x,None,x)
        offset.BaseNet.__call__=fake
        model=object.__new__(RankNet)
        x=np.array([[1.,2.],[3.,4.]],dtype=np.float32)
        vin=np.array([.25,.5],dtype=np.float32);vout=np.array([2.,-1.],dtype=np.float32);bias=np.array([.5,-.25],dtype=np.float32)
        prefix=offset.key(0,'probe','signed8','common_A10_separate')
        FACTORS.update({prefix+':in':vin,prefix+':out':vout,prefix+':bias':bias})
        offset.CURRENT.update(A=10,pooled=False,format='signed8')
        callback=lambda *args:2*args[2]+(args[2]@vin)[:,None]*vout+bias
        model.mvm=callback
        assert np.array_equal(model(x),2*x) and model.mvm is callback
        model.mvm=None;assert np.array_equal(model(x),x)
    finally:
        offset.BaseNet.__call__=original;FACTORS.clear();offset.CURRENT.clear()
    print('PASS rank1 correction before downstream use, clean-reference identity and hook restoration',flush=True)


def freeze():
    p=json.loads((ROOT/f'build/campaign/mismatch_offset_quality/die{DIE}/protocol.json').read_text())
    p['sources'][str(Path(__file__))]=legacy.base.fingerprint(__file__)
    for module in (offset,fixed,nominal):p['sources'][str(Path(module.__file__))]=legacy.base.fingerprint(module.__file__)
    p['status']='Frozen rank1+offset calibration before full-depth heldout quality'
    p['rank1_calibration']=dict(rank=1,data='Old27h3 first128 clean tokens only; same physicaldie errors as fixed-mismatch and offset controls',
        basis='Leading centered clean-input direction weighted by exact per-row mean PDK coefficient variance; fixed per-MVM/format before ADC-error regression',
        regression='FiniteADC+fixedcap output residual versus cleanMVM; scalar leastsquares feature slope with relative ridge1e-6 and meanoffset; no heldout fitting',
        hardware='One input projection, one outerproduct and outputadd perMVM. Float32 storedfactors; physicalsidecar precision/delay/power and calibration noise/energy unverified.',
        limitation='Only numerator mismatch and nominal effective loading; no holder/radix/parasitic/ADC/state mismatch or output-head error injection')
    OUT.mkdir(parents=True,exist_ok=True);path=OUT/'protocol.json';text=json.dumps(p,indent=2)+'\n'
    if path.exists():assert path.read_text()==text
    else:path.write_text(text)
    src=nominal.OUT/'calibration_Cu4.json';dst=OUT/src.name
    if dst.exists():assert dst.read_bytes()==src.read_bytes()
    else:dst.write_bytes(src.read_bytes())
    return p


def load():
    value=fixed.load();p,_,net,weights,sources=value
    fp=OUT/'rank1.npz';meta=OUT/'rank1.json'
    if fp.exists():
        data=json.loads(meta.read_text());assert data['complete']
        assert all(legacy.base.fingerprint(f)==h for f,h in data['sources'].items())
        with np.load(fp) as z:FACTORS.update({k:z[k] for k in z.files})
    else:
        assert not meta.exists()
        note=next((Path.home()/'Documents/Projects/OmarSiwy.github.io/Notes/Circuit Design/Analog Design/Analog Compute').glob('27h3 *.md'))
        ids=legacy.base.tokenize_greedy(note.read_text(),net.vocab)[:128]
        inputs={};targets={}
        def capture(li,name,a,w,y):inputs[li,name]=a.copy();targets[li,name]=y.copy();return y
        net.mvm=capture;net(ids);net.mvm=None;assert len(inputs)==210
        cal=json.loads((nominal.OUT/'calibration_Cu4.json').read_text())
        choices={(r['format'],r['architecture'],r['layer'],r['tensor'],r['bank']):r['selected']['min_error'] for r in cal['records']}
        factors={};records=[];basis={}
        for fmt in p['formats']:
            for arch in p['architectures']:
                for label,(scale,w,dw) in weights.items():
                    li,name=label;A=inputs[label].astype(float)
                    if (fmt,label) not in basis:
                        lo,hi,_=nominal.digits(w,fmt);vl,_,_=coefficient_variance(lo);vh,_,_=coefficient_variance(hi)
                        variance=((vl+nominal.radix(fmt)**2*vh)*dw[None,:]**2/scale[:,None]**2).mean(axis=1)
                        root=np.sqrt(variance);mean=A.mean(axis=0);X=(A-mean)*root
                        ev,U=np.linalg.eigh(X@X.T);assert ev[-1]>0
                        u=X.T@U[:,-1]/np.sqrt(ev[-1]);assert np.isclose(u@u,1.,atol=1e-8)
                        vin=root*u;z=(A-mean)@vin
                        basis[fmt,label]=vin,mean,z
                    vin,mean,z=basis[fmt,label]
                    q,dx,_=offset.QUANTIZE(inputs[label]/scale,arch['kind'],arch['A']);parts=[]
                    for bank,bs in enumerate(fixed.scenes(q,w,dx,arch['pooled'],fmt)):
                        setting=choices[fmt,arch['label'],li,name,bank]
                        got,_,_=legacy.read(nominal.reset.prepare(bs,4,setting['bits']),4,setting['bits'],setting['span'])
                        parts.append(got)
                    actual=((parts[0]+nominal.radix(fmt)*parts[1])*dw).astype(np.float32)
                    error=actual.astype(float)-targets[label]
                    constant=error.mean(axis=0);vout=z@error/((z@z)*(1+1e-6))
                    bias=constant-(mean@vin)*vout
                    residual=error-(A@vin)[:,None]*vout-bias
                    assert np.sum(residual**2)<=np.sum((error-constant)**2)*(1+1e-8)+1e-20
                    prefix=offset.key(li,name,fmt,arch['label'])
                    for suffix,v in ((':in',vin),(':out',vout),(':bias',bias)):factors[prefix+suffix]=v.astype(np.float32)
                    ni,no=w.shape
                    records.append(dict(format=fmt,architecture=arch['label'],layer=li,tensor=name,
                        error_RMS=float(np.sqrt(np.mean(error**2))),offset_RMS=float(np.sqrt(np.mean((error-constant)**2))),
                        rank1_RMS=float(np.sqrt(np.mean(residual**2))),correction_MACs=ni+no,coefficients=ni+2*no))
                print('rank1 calibration',DIE,fmt,arch['label'],flush=True)
        np.savez_compressed(fp,**factors);cal_sources=dict(sources)
        for f in (note,nominal.OUT/'calibration_Cu4.json',fp):cal_sources[str(f)]=legacy.base.fingerprint(f)
        meta.write_text(json.dumps(dict(complete=True,sources=cal_sources,die=DIE,records=records,
            calibration_ids_sha256=hashlib.sha256(np.array(ids,dtype='<i4').tobytes()).hexdigest()),indent=2)+'\n')
        FACTORS.update(factors)
    sources[str(fp)]=legacy.base.fingerprint(fp);sources[str(meta)]=legacy.base.fingerprint(meta)
    return value


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--die',type=int,choices=(1,2),default=1);ap.add_argument('--selfcheck',action='store_true');ap.add_argument('--freeze',action='store_true');a=ap.parse_args()
    DIE=a.die;OUT=ROOT/f'build/campaign/mismatch_rank1_quality/die{DIE}';fixed.DIE=DIE
    legacy.digits,legacy.radix=nominal.digits,nominal.radix
    legacy.OUT,legacy.prepare,legacy.scenes=OUT,nominal.reset.prepare,offset.scenes
    legacy.selfcheck,legacy.freeze,legacy.load=selfcheck,freeze,load
    legacy.base.Net,legacy.base.quantize=RankNet,offset.quantize
    if a.selfcheck:selfcheck()
    elif a.freeze:freeze()
    else:legacy.evaluate(4)
