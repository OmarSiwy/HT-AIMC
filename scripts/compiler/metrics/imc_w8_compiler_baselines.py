"""Same-storage W8 RTN/GPTQ compiler controls with exact ADC diagnostics."""
import hashlib
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT / "scripts"))
from compiler.metrics import imc_ideal_adc_ceiling as ceiling
from compiler.metrics import imc_grouped_w4 as gptq
base,nominal,np=ceiling.base,ceiling.nominal,ceiling.np
OUT=ROOT/'build/campaign/w8_compiler_baselines'


def main():
    gptq.selfcheck()
    _,old,net,weights,sources=base.load()
    note=next((Path.home()/'Documents/Projects/OmarSiwy.github.io/Notes/Circuit Design/Analog Design/Analog Compute').glob('27h3 *.md'))
    for f in (Path(__file__),Path(gptq.__file__),Path(ceiling.__file__),note,ceiling.OUT/'result.json'):
        sources[str(f)]=base.fingerprint(f)
    p=dict(status='Frozen before GPTQ calibration or new compiler quality',sources=sources,
        modes=['smoothed_RTN_control','unsmoothed_RTN','smoothed_GPTQ'],
        calibration='Old27h3 first128 clean tokens only; original frozen smoothing scales and per-output W8 step unchanged for GPTQ. Natural input order, static grid,1% mean-Hessian-diagonal damping, existing independently checked blocked GPTQ implementation. No activation-order or hyperparameter search.',
        hardware='All variants retain symmetric−127..127 W8 and signed8 two-bank encoding. No per-weight scale or correction sidecar. Ideal capacitors/readout and A11 common activation quantization only; physical loading/calibration/timing/area/noise untested for new codes.',
        evaluation='Both existing exposed512-token passages; clean original Q8_0 network reference; no evaluation-input calibration.')
    OUT.mkdir(parents=True,exist_ok=True)
    path=OUT/'protocol.json';text=json.dumps(p,indent=2)+'\n'
    if path.exists():assert path.read_text()==text
    else:path.write_text(text)
    sources[str(path)]=base.fingerprint(path)
    codes_path,meta_path=OUT/'gptq_codes.npz',OUT/'calibration.json'
    if codes_path.exists():
        meta=json.loads(meta_path.read_text());assert meta['complete']
        assert all(base.fingerprint(f)==h for f,h in meta['sources'].items())
        with np.load(codes_path) as z:codes={k:z[k] for k in z.files}
    else:
        assert not meta_path.exists()
        inputs={}
        def capture(li,name,a,w,clean):inputs[li,name]=a.copy();return clean
        net.mvm=capture
        ids=base.tokenize_greedy(note.read_text(),net.vocab)[:128]
        net(ids);net.mvm=None;assert len(inputs)==210
        codes={};records=[];started=time.perf_counter()
        for (li,name),(scale,q0,dw) in weights.items():
            w=net.L[li][name];a=inputs[li,name]/scale
            ws=(w*scale[:,None]).astype(np.float32)
            steps=np.tile(dw.astype(float),(len(w)+127)//128).reshape(-1,len(dw))
            H=gptq.hessian(a)
            q,reconstructed=gptq.quantize(ws,steps,H,rows=128,maximum=127)
            assert q.dtype==np.int8 and np.max(abs(q.astype(np.int16)))<=127
            assert np.allclose(reconstructed,q.astype(float)*dw[None,:],atol=1e-7,rtol=1e-6)
            codes[f'{li}:{name}']=q
            target=a@ws
            old_error=a@(q0.astype(np.float32)*dw)-target
            new_error=a@reconstructed-target
            records.append(dict(layer=li,tensor=name,code_changed_fraction=float(np.mean(q!=q0)),
                RTN_calibration_MSE=float(np.mean(old_error.astype(float)**2)),
                GPTQ_calibration_MSE=float(np.mean(new_error.astype(float)**2))))
            if (li+1)%5==0 and name==base.TENSORS[-1]:print('GPTQ calibrated layer',li+1,flush=True)
        np.savez_compressed(codes_path,**codes)
        cal_sources=dict(sources);cal_sources[str(codes_path)]=base.fingerprint(codes_path)
        meta_path.write_text(json.dumps(dict(complete=True,sources=cal_sources,records=records,
            runtime_s=time.perf_counter()-started,
            calibration_ids_sha256=hashlib.sha256(np.array(ids,dtype='<i4').tobytes()).hexdigest()),indent=2)+'\n')
    sources[str(codes_path)]=base.fingerprint(codes_path);sources[str(meta_path)]=base.fingerprint(meta_path)
    alternatives={}
    for label,(s,q,dw) in weights.items():
        one=np.ones_like(s);unq,undw=base.quantize_weight(net.L[label[0]][label[1]],one)
        alternatives[label]={'smoothed_RTN_control':(s,q,dw),'unsmoothed_RTN':(one,unq,undw),
                             'smoothed_GPTQ':(s,codes[f'{label[0]}:{label[1]}'],dw)}
    nominal.legacy.digits,nominal.legacy.radix=nominal.digits,nominal.radix
    result_path=OUT/'result.json';assert not result_path.exists();results=[]
    for src in old['sources']:
        note=Path(src['path']);assert base.fingerprint(note)==src['sha256']
        ids=base.tokenize_greedy(note.read_text(),net.vocab)[:512]
        net.mvm=None;ev=base.Eval(net,ids)
        for mode in p['modes']:
            def compute(li,name,a,w,clean):
                s,qw,dw=alternatives[li,name][mode]
                q,dx,_=base.quantize(a/s,'common',11)
                banks=nominal.loading.scenes(q,qw,dx,False,'signed8')
                return ((ceiling.exact_read(banks[0])+8*ceiling.exact_read(banks[1]))*dw).astype(np.float32)
            net.mvm=compute;r=ev.score(net(ids));r.update(source=note.name,mode=mode)
            r['joint_pass']=r['kl']<=.01 and r['ppl_ratio']<=1.01
            results.append(r);print(r,flush=True)
    prior=json.loads((ceiling.OUT/'result.json').read_text())
    for r in results:
        if r['mode']=='smoothed_RTN_control':
            target=next(t for t in prior['results'] if t['source']==r['source'])
            assert all(r[k]==target[k] for k in ('kl','ppl','ppl_ratio','argmax','top5'))
    assert all(base.fingerprint(f)==h for f,h in sources.items())
    result_path.write_text(json.dumps(dict(complete=True,protocol=p,sources=sources,results=results,
        status='PASS original-control reproduction and source audit; ideal-readout compiler quality only'),indent=2)+'\n')
    print('PASS compiler baseline controls and source audit',flush=True)


if __name__=='__main__':main()
