"""Frozen group64/128 W8 with stored FP16 scales and exact ADC diagnostic."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT / "scripts"))
from compiler.metrics import imc_original_q8_groups as original
base,np=original.base,original.np
OUT=ROOT/'build/campaign/group_size_ceiling_v2'


def quantize(w,group):
    ni,no=w.shape;ng=(ni+group-1)//group
    padded=np.pad(w,((0,ng*group-ni),(0,0))).reshape(ng,group,no)
    d=(abs(padded).max(axis=1)/127).astype(np.float16).astype(np.float32)
    d=np.where(d>0,d,np.float32(2**-24))
    q=np.clip(np.rint(padded/d[:,None,:]),-127,127).astype(np.int8)
    return q,d


def compute(a,q,d,group):
    qa,_,dx=base.quantize(a,'common',11)
    qa=np.pad(qa,((0,0),(0,q.shape[0]*group-a.shape[1]))).reshape(len(a),-1,group)
    partial=np.matmul(qa.transpose(1,0,2).astype(np.float32),q.astype(np.float32)).transpose(1,0,2)
    return np.sum(partial*d[None,:,:]*dx[:,::group,None],axis=1)


def main():
    _,old,net,frozen,sources=base.load()
    for f in (Path(__file__),Path(original.__file__)):
        sources[str(f)]=base.fingerprint(f)
    p=dict(status='Frozen before quality',groups=[64,128],sources=sources,
        quantizer='Unsmoothed pergroup/output maxabs/127 rounded to FP16, then W8 RTN on that stored scale. Ragged groups zero-padded. Common A11 input scale unchanged.',
        scope='Exact ADC and arithmetic, no mismatch/noise/PPA. Two existing exposed512-token passages only. Original Q8_0 reference; no calibration or heldout fitting.')
    OUT.mkdir(parents=True,exist_ok=True);path=OUT/'protocol.json';text=json.dumps(p,indent=2)+'\n'
    if path.exists():assert path.read_text()==text
    else:path.write_text(text)
    sources[str(path)]=base.fingerprint(path)
    path=OUT/'result.json';assert not path.exists();results=[]
    rng=np.random.default_rng(541);a=rng.normal(size=(3,1536));a[:,1024:]*=10;w=rng.normal(size=(1536,5))
    for group in p['groups']:
        q,d=quantize(w,group);qa,_,dx=base.quantize(a,'common',11)
        direct=(qa.astype(np.float32)*dx)@(q*d[:,None,:]).reshape(-1,5)[:1536]
        assert np.allclose(compute(a,q,d,group),direct,rtol=2e-5,atol=2e-5)
    print('PASS ragged-group reconstruction and independent dense product oracle',flush=True)
    weights={g:{label:quantize(net.L[label[0]][label[1]],g) for label in frozen} for g in p['groups']}
    for src in old['sources']:
        note=Path(src['path']);assert base.fingerprint(note)==src['sha256']
        ids=base.tokenize_greedy(note.read_text(),net.vocab)[:512]
        net.mvm=None;ev=base.Eval(net,ids)
        for group in p['groups']:
            def mvm(li,name,a,w,clean):
                q,d=weights[group][li,name]
                return compute(a,q,d,group).astype(np.float32)
            net.mvm=mvm;r=ev.score(net(ids));r.update(source=note.name,group=group)
            r['joint_pass']=r['kl']<=.01 and r['ppl_ratio']<=1.01
            results.append(r);print(r,flush=True)
    assert all(base.fingerprint(f)==h for f,h in sources.items())
    path.write_text(json.dumps(dict(complete=True,protocol=p,sources=sources,results=results),indent=2)+'\n')
    print('PASS group-size ideal readout diagnostic and source audit',flush=True)


if __name__=='__main__':main()
