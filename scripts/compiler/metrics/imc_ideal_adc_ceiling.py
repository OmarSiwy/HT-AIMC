"""W8 + common A11 quantization ceiling with mathematically exact ADC readout."""
import json
from pathlib import Path
import sys
import time
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
from compiler.metrics import imc_programmable_digit_campaign as nominal
base, np = nominal.legacy.base, nominal.np
OUT = ROOT/'build/campaign/ideal_adc_ceiling'


def exact_read(bank):
    return sum(s['Q_per_Cu']*np.exp2(s['B'][:,None])/.45*s['dx'][:,None] for s in bank)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    _, old, net, weights, sources = base.load()
    for f in (Path(__file__), Path(nominal.__file__), nominal.OUT/'quality_Cu4.json'):
        sources[str(f)] = base.fingerprint(f)
    p = dict(status='Frozen ideal ADC diagnostic before results',sources=sources,
        representation='Original fixed W8 quantization and common A11 activation quantizer; exact signed8 bank reconstruction',
        exclusions='No ADC rounding/clipping, capacitor error, read/thermal noise, loading, transfer error or physical PPA. Tied output head remains clean as in the existing pipeline.',
        evaluation='Two existing exposed first512-token passages. Same full-depth network and clean reference. This isolates combined W8/input quantization from finite ADC error, not W8 versus input individually.')
    path = OUT/'protocol.json'; text = json.dumps(p,indent=2)+'\n'
    if path.exists(): assert path.read_text()==text
    else: path.write_text(text)
    sources[str(path)] = base.fingerprint(path)
    nominal.legacy.digits, nominal.legacy.radix = nominal.digits, nominal.radix
    rng = np.random.default_rng(91403)
    q = rng.integers(-511,512,(4,257)); w = rng.integers(-127,128,(257,3)); dx = np.ones((4,2))
    banks = nominal.loading.scenes(q,w,dx,False,'signed8')
    assert np.allclose(exact_read(banks[0])+8*exact_read(banks[1]),q@w,atol=1e-8)
    results=[]; path=OUT/'result.json'; assert not path.exists()
    for src in old['sources']:
        note=Path(src['path']); assert base.fingerprint(note)==src['sha256']
        ids=base.tokenize_greedy(note.read_text(),net.vocab)[:512]
        net.mvm=None; ev=base.Eval(net,ids); start=time.perf_counter()
        def compute(li,name,a,w,clean):
            scale,wq,dw=weights[li,name]
            q,dx,_=base.quantize(a/scale,'common',11)
            banks=nominal.loading.scenes(q,wq,dx,False,'signed8')
            return ((exact_read(banks[0])+8*exact_read(banks[1]))*dw).astype(np.float32)
        net.mvm=compute
        quality=ev.score(net(ids)); quality['runtime_s']=time.perf_counter()-start
        quality['source']=note.name
        quality['joint_pass']=quality['kl']<=.01 and quality['ppl_ratio']<=1.01
        results.append(quality); print(quality,flush=True)
    assert all(base.fingerprint(f)==h for f,h in sources.items())
    path.write_text(json.dumps(dict(complete=True,protocol=p,sources=sources,results=results,
        status='PASS exact ragged matrix identity and source audit; quality gate separately reported'),indent=2)+'\n')
    print('PASS ideal ADC diagnostic and source audit',flush=True)


if __name__=='__main__':main()
