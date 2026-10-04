"""Original Q8_0 group codes/scales and exact-readout grouping diagnostic."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT / "scripts"))
from compiler.metrics import imc_ideal_adc_ceiling as ceiling
base,np=ceiling.base,ceiling.np
OUT=ROOT/'build/campaign/original_q8_groups'


def raw_weights(net, frozen):
    result={}
    for label,(smooth,_,_) in frozen.items():
        li,name=label;ttype,ne,off=net.g.tensors[f'blk.{li}.{name}.weight']
        assert ttype==8 and ne[0]%32==0
        net.g.f.seek(net.g.data_start+off)
        raw=np.frombuffer(net.g.f.read(int(np.prod(ne))//32*34),dtype=np.uint8).reshape(ne[1],ne[0]//32,34)
        d=raw[:,:,:2].copy().view('<f2').astype(np.float32).reshape(ne[1],ne[0]//32).T.copy()
        q=raw[:,:,2:].copy().view(np.int8).transpose(1,2,0).copy()
        assert np.array_equal((q*d[:,None,:]).reshape(ne[0],ne[1]),net.L[li][name])
        assert np.max(abs(q.astype(np.int16)))<=127
        sg=np.exp2(np.rint(np.mean(np.log2(smooth.reshape(-1,32).astype(float)),axis=1))).astype(np.float32)
        result[label]=dict(q=q,d=d,group_smoothing=sg)
    return result


def inputs(a, record, mode):
    group_s=record['group_smoothing'] if mode=='group32_power2' else np.ones(len(record['q']),dtype=np.float32)
    scaled=a/np.repeat(group_s,32)
    q,_,expanded=base.quantize(scaled,'common',11)
    return q.reshape(len(a),-1,32),expanded[:,::32],group_s


def main():
    _,old,net,frozen,sources=base.load();raw=raw_weights(net,frozen)
    for f in (Path(__file__),ROOT/'build/campaign/q8_storage_audit/result.json'):
        sources[str(f)]=base.fingerprint(f)
    p=dict(status='Frozen original-Q8 group32 diagnostic before evaluation',sources=sources,
        modes=['none','group32_power2'],
        normalization='Group32 FP16 scales applied before merging. Optional common-per-input-group power-of-two smoothing is rounded geometric mean of existing frozen32 input scales; folded into digital group exponent. No new evaluation fitting.',
        scope='Ideal exact ADC/arithmetic; no mismatch/noise or PPA. Native group32 hardware and paid scale/conversion counts are separate studies.')
    OUT.mkdir(parents=True,exist_ok=True);path=OUT/'protocol.json';text=json.dumps(p,indent=2)+'\n'
    if path.exists():assert path.read_text()==text
    else:path.write_text(text)
    sources[str(path)]=base.fingerprint(path)
    results=[];path=OUT/'result.json';assert not path.exists()
    for src in old['sources']:
        note=Path(src['path']);assert base.fingerprint(note)==src['sha256']
        ids=base.tokenize_greedy(note.read_text(),net.vocab)[:512]
        net.mvm=None;ev=base.Eval(net,ids)
        for mode in p['modes']:
            def compute(li,name,a,w,clean):
                r=raw[li,name];q,dx,sg=inputs(a,r,mode)
                partial=np.einsum('tgi,gij->tgj',q.astype(np.float32),r['q'].astype(np.float32),optimize=True)
                return np.sum(partial*dx[:,:,None]*sg[None,:,None]*r['d'][None,:,:],axis=1).astype(np.float32)
            net.mvm=compute;r=ev.score(net(ids));r.update(source=note.name,mode=mode)
            r['joint_pass']=r['kl']<=.01 and r['ppl_ratio']<=1.01;results.append(r);print(r,flush=True)
    assert all(base.fingerprint(f)==h for f,h in sources.items())
    path.write_text(json.dumps(dict(complete=True,protocol=p,sources=sources,results=results,
        status='PASS exact raw-weight reconstruction and source audit; ideal-readout quality only'),indent=2)+'\n')
    print('PASS original Q8 group32 diagnostic and source audit',flush=True)


if __name__=='__main__':main()
