"""Separate W8 and A11 contributions to the ideal-readout diagnostic floor."""
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
from compiler.metrics import imc_ideal_adc_ceiling as ceiling
base, nominal, np = ceiling.base, ceiling.nominal, ceiling.np
OUT = ROOT/'build/campaign/quantization_floor'


def main():
    _, old, net, weights, sources = base.load()
    for f in (Path(__file__), Path(ceiling.__file__), ceiling.OUT/'result.json'):
        sources[str(f)] = base.fingerprint(f)
    protocol = dict(sources=sources,status='Frozen quantization-factor diagnostics before results',
        modes=['W8_only','A11_only','W8_A11_control'],
        scope='Exact arithmetic diagnostic only; no ADC/mismatch/noise or PPA. Weight-only removes activation quantization; activation-only uses original floating/dequantized model weights. Smoothing and original quantizer scales retained. No hardware storage or precision advantage credited.')
    OUT.mkdir(parents=True,exist_ok=True)
    path=OUT/'protocol.json';text=json.dumps(protocol,indent=2)+'\n'
    if path.exists():assert path.read_text()==text
    else:path.write_text(text)
    sources[str(path)]=base.fingerprint(path)
    nominal.legacy.digits,nominal.legacy.radix=nominal.digits,nominal.radix
    results=[];path=OUT/'result.json';assert not path.exists()
    for src in old['sources']:
        note=Path(src['path']);assert base.fingerprint(note)==src['sha256']
        ids=base.tokenize_greedy(note.read_text(),net.vocab)[:512]
        net.mvm=None;ev=base.Eval(net,ids)
        for mode in protocol['modes']:
            def compute(li,name,a,w,clean):
                scale,wq,dw=weights[li,name]
                if mode=='W8_only':return ((a/scale)@wq.astype(np.float32)*dw).astype(np.float32)
                q,dx,_=base.quantize(a/scale,'common',11)
                if mode=='A11_only':
                    reconstructed=np.empty_like(a)
                    for g,start in enumerate(range(0,a.shape[1],256)):
                        reconstructed[:,start:start+256]=q[:,start:start+256]*dx[:,g,None]*scale[None,start:start+256]
                    return (reconstructed@w).astype(np.float32)
                banks=nominal.loading.scenes(q,wq,dx,False,'signed8')
                return ((ceiling.exact_read(banks[0])+8*ceiling.exact_read(banks[1]))*dw).astype(np.float32)
            net.mvm=compute;r=ev.score(net(ids));r.update(source=note.name,mode=mode)
            r['joint_pass']=r['kl']<=.01 and r['ppl_ratio']<=1.01
            results.append(r);print(r,flush=True)
    original=json.loads((ceiling.OUT/'result.json').read_text())
    for r in results:
        if r['mode']=='W8_A11_control':
            target=next(x for x in original['results'] if x['source']==r['source'])
            assert all(r[k]==target[k] for k in ('kl','ppl','ppl_ratio','argmax','top5'))
    assert all(base.fingerprint(f)==h for f,h in sources.items())
    path.write_text(json.dumps(dict(complete=True,protocol=protocol,sources=sources,results=results,
        status='PASS exact combined-control reproduction and source audit; quality classification per row'),indent=2)+'\n')
    print('PASS exact combined-control reproduction and source audit',flush=True)


if __name__=='__main__':main()
