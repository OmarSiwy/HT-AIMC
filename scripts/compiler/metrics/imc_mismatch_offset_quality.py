"""Fixed-cap mismatch with old-corpus per-output offset calibration.

Uses finite nominal ADC settings and one fixed capacitor realization. Floating
calibration constants and noiseless calibration averages are optimistic bounds.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT / "scripts"))
from compiler.metrics import imc_fixed_mismatch_quality as fixed
nominal=fixed.nominal
legacy=fixed.legacy
np=fixed.np
BaseNet=legacy.base.Net
QUANTIZE=legacy.base.quantize
CURRENT={}
BIAS={}
OUT=ROOT/'build/campaign/mismatch_offset_quality/die1'
DIE=1


def quantize(a,kind,bits):
    CURRENT['A']=bits;CURRENT['kind']=kind
    return QUANTIZE(a,kind,bits)


def scenes(q,w,dx,pooled,fmt):
    CURRENT['format']=fmt;CURRENT['pooled']=pooled
    return fixed.scenes(q,w,dx,pooled,fmt)


def key(layer,name,fmt,arch):
    return f'{layer}:{name}:{fmt}:{arch}'


class CalibratedNet(BaseNet):
    def __call__(self,*args,**kwargs):
        original=self.mvm
        if original is not None and BIAS:
            def corrected(layer,name,a,w,clean):
                got=original(layer,name,a,w,clean)
                assert CURRENT['kind']=='common'
                arch=f"common_A{CURRENT['A']}_{'pooled' if CURRENT['pooled'] else 'separate'}"
                correction=BIAS[key(layer,name,CURRENT['format'],arch)]
                return (got-correction).astype(np.float32)
            self.mvm=corrected
        try:return super().__call__(*args,**kwargs)
        finally:self.mvm=original


def selfcheck():
    fixed.selfcheck()
    x=np.array([[1.,2.],[3.,4.]])
    y=x+np.array([.125,-.25]);offset=(y-x).mean(axis=0)
    assert np.array_equal(y-offset,x)
    print('PASS fixed per-output offset arithmetic; calibration data remain separate',flush=True)


def freeze():
    p=json.loads((ROOT/f'build/campaign/fixed_mismatch_quality/die{DIE}/protocol.json').read_text())
    p['sources'][str(Path(__file__))]=legacy.base.fingerprint(__file__)
    p['sources'][str(Path(fixed.__file__))]=legacy.base.fingerprint(fixed.__file__)
    p['status']='Frozen per-output mismatch offset calibration before heldout quality'
    p['offset_calibration']=dict(data='Old27h3 first128 clean tokens only; finite ADC plus fixed cap realization, no transient noise during calibration',
        target='Mean per-MVM output error versus original clean float32 MVM on captured clean activations. One constant/output/architecture/format/die; reused across both512-token passages.',
        implementation='Float32 stored constants and one post-MVM subtraction are modeled. Finite calibration noise, measurement time/energy, fixed-point constant quantization and circuit implementation unverified.',
        limitation='Corrects constant bias only, not arbitrary perweight errors or signal-dependent holder radix. Each candidate carries only its own constants; alternatives are not simultaneously installed.')
    OUT.mkdir(parents=True,exist_ok=True)
    path=OUT/'protocol.json';text=json.dumps(p,indent=2)+'\n'
    if path.exists():assert path.read_text()==text
    else:path.write_text(text)
    src=nominal.OUT/'calibration_Cu4.json';dst=OUT/src.name
    if dst.exists():assert dst.read_bytes()==src.read_bytes()
    else:dst.write_bytes(src.read_bytes())
    return p


def load():
    value=fixed.load();p,_,net,weights,sources=value
    fp=OUT/'offsets.npz';meta=OUT/'offsets.json'
    if fp.exists():
        data=json.loads(meta.read_text());assert data['complete']
        assert all(legacy.base.fingerprint(f)==h for f,h in data['sources'].items())
        with np.load(fp) as saved:BIAS.update({k:saved[k] for k in saved.files})
    else:
        assert not meta.exists()
        note=next((Path.home()/'Documents/Projects/OmarSiwy.github.io/Notes/Circuit Design/Analog Design/Analog Compute').glob('27h3 *.md'))
        ids=legacy.base.tokenize_greedy(note.read_text(),net.vocab)[:128]
        activations={};targets={}
        def capture(li,name,a,w,y):activations[li,name]=a.copy();targets[li,name]=y.copy();return y
        net.mvm=capture;net(ids);net.mvm=None;assert len(activations)==210
        cal=json.loads((nominal.OUT/'calibration_Cu4.json').read_text())
        choices={(r['format'],r['architecture'],r['layer'],r['tensor'],r['bank']):r['selected']['min_error'] for r in cal['records']}
        offsets={};rows=[]
        for fmt in p['formats']:
            for arch in p['architectures']:
                for (li,name),(scale,w,dw) in weights.items():
                    q,dx,_=QUANTIZE(activations[li,name]/scale,arch['kind'],arch['A'])
                    parts=[]
                    for bank,bs in enumerate(fixed.scenes(q,w,dx,arch['pooled'],fmt)):
                        setting=choices[fmt,arch['label'],li,name,bank]
                        got,_,_=legacy.read(nominal.reset.prepare(bs,4,setting['bits']),4,setting['bits'],setting['span'])
                        parts.append(got)
                    actual=((parts[0]+nominal.radix(fmt)*parts[1])*dw).astype(np.float32)
                    error=actual-targets[li,name]
                    bias=np.mean(error.astype(np.float64),axis=0).astype(np.float32)
                    offsets[key(li,name,fmt,arch['label'])]=bias
                    rows.append(dict(format=fmt,architecture=arch['label'],layer=li,tensor=name,
                        outputs=len(bias),offset_RMS=float(np.sqrt(np.mean(bias.astype(float)**2))),
                        error_RMS_before=float(np.sqrt(np.mean(error.astype(float)**2))),
                        error_RMS_after=float(np.sqrt(np.mean((error-bias).astype(float)**2)))))
                print('offset calibration',DIE,fmt,arch['label'],flush=True)
        np.savez_compressed(fp,**offsets)
        cal_sources=dict(sources)
        for f in [note,nominal.OUT/'calibration_Cu4.json',fp]:cal_sources[str(f)]=legacy.base.fingerprint(f)
        meta.write_text(json.dumps(dict(complete=True,sources=cal_sources,die=DIE,records=rows,
            constants_per_candidate=sum(r['outputs'] for r in rows if r['format']==p['formats'][0] and r['architecture']==p['architectures'][0]['label']),
            calibration_ids_sha256=hashlib.sha256(np.array(ids,dtype='<i4').tobytes()).hexdigest()),indent=2)+'\n')
        BIAS.update(offsets)
    sources[str(fp)]=legacy.base.fingerprint(fp);sources[str(meta)]=legacy.base.fingerprint(meta)
    return value


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--die',type=int,choices=(1,2),default=1);ap.add_argument('--selfcheck',action='store_true');ap.add_argument('--freeze',action='store_true');a=ap.parse_args()
    DIE=a.die;OUT=ROOT/f'build/campaign/mismatch_offset_quality/die{DIE}';fixed.DIE=DIE
    legacy.digits,legacy.radix=nominal.digits,nominal.radix
    legacy.OUT,legacy.prepare,legacy.scenes=OUT,nominal.reset.prepare,scenes
    legacy.selfcheck,legacy.freeze,legacy.load=selfcheck,freeze,load
    legacy.base.Net,legacy.base.quantize=CalibratedNet,quantize
    if a.selfcheck:selfcheck()
    elif a.freeze:freeze()
    else:legacy.evaluate(4)
