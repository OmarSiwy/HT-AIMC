"""Paired grounded G32 quality with fixed physical DAC and fewer decisions."""
import argparse
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT / "scripts"))
from compiler.metrics import imc_grounded_group32_precision as original
base,np=original.base,original.np
OUT=ROOT/'build/campaign/grounded_group32_early_stop_r50'
LEDGER=original.OUT/'adc_fixed_dac_early_stop_1p05.json'


def selfcheck():
    # Independent b-comparison binary decision tree. Every retained threshold is
    # an integer code of the ORIGINAL fine DAC when at least one bit is omitted.
    tested=0
    for n in range(9,15):
        for b in range(8,n):
            m=2**(n-b); lo0=-2**(b-1);hi0=2**(b-1)-1
            for k in range(lo0-1,hi0+2):
                for epsilon in (-.125,0,.125):
                    q=(k+.5)*m+epsilon
                    lo,hi=lo0,hi0;decisions=0
                    while lo<hi:
                        mid=(lo+hi)//2;threshold=(mid+.5)*m
                        assert threshold==int(threshold)
                        if q>=threshold:lo=mid+1
                        else:hi=mid
                        decisions+=1
                    expected=int(np.clip(np.floor(q/m+.5),lo0,hi0))
                    assert lo==expected and decisions==b
                    tested+=1
    print(f'PASS {tested} independent SAR threshold/endpoint/tie checks; original fine-grid thresholds, exactly b comparisons',flush=True)


def evaluate(die):
    selfcheck();original.selfcheck()
    p,old,net,weights,sources=original.freeze()
    calpath=original.OUT/'calibration.json';cal=json.loads(calpath.read_text())
    assert cal['complete'] and all(base.fingerprint(f)==h for f,h in cal['sources'].items())
    ledger=json.loads(LEDGER.read_text());assert ledger['calibration_sha256']==base.fingerprint(calpath)
    for f in (Path(__file__),LEDGER,calpath):sources[str(f)]=base.fingerprint(f)
    choices={(r['layer'],r['tensor'],r['bank']):r for r in ledger['rows']}
    protocol=dict(p,change='Only effective SAR decisions/quantum change. Original physical N,C,Vref and all noise/mismatch draws retained. Midpoint thresholds are integer codes on original fine DAC. Switch ordering/reset/physical transient unverified.',parent_calibration=str(calpath),early_stop_ledger=str(LEDGER))
    OUT.mkdir(parents=True,exist_ok=True);pp=OUT/'protocol.json';text=json.dumps(protocol,indent=2)+'\n'
    if pp.exists():assert pp.read_text()==text
    else:pp.write_text(text)
    sources[str(pp)]=base.fingerprint(pp)
    output=OUT/f'quality_die{die}.json';assert not output.exists()
    results=[];report=dict(complete=False,die=die,protocol=protocol,sources=sources,results=results)
    for src in old['sources']:
        note=Path(src['path']);assert base.fingerprint(note)==src['sha256']
        ids=base.tokenize_greedy(note.read_text(),net.vocab)[:512]
        net.mvm=None;ev=base.Eval(net,ids)
        for sharing in p['sharing_modes']:
            for seed in [None]+p['seeds']:
                rng=np.random.default_rng(seed);details=[];started=time.perf_counter()
                def compute(li,name,a,w,clean):
                    banks=[]
                    for bank,s in enumerate(original.scenes(a,weights[li,name],(li,name),die,sharing)):
                        setting=choices[li,name,bank];oldsetting=setting['original'];candidate=setting['candidate']
                        C,stats,_=original.prepare(s,oldsetting['bits'])
                        got,count=original.read(s,candidate['effective_bits'],candidate['equivalent_grid_span'],C,rng,seed is not None)
                        count.update(physical_ADC_bits=oldsetting['bits'],physical_reference_span_V=oldsetting['span'],equivalent_quantizer_span_V=count.pop('span_V'))
                        details.append(dict(layer=li,tensor=name,bank=bank,**stats,**count));banks.append(got)
                    return (banks[0]+8*banks[1]).astype(np.float32)
                net.mvm=compute;r=ev.score(net(ids));r.update(source=note.name,sharing=sharing,seed=seed,runtime_s=time.perf_counter()-started,details=details)
                r['joint_pass']=r['kl']<=.01 and r['ppl_ratio']<=1.01
                for k in ('conversions','ADC_decisions','clips','column_plane_events','connected_C_fF','two_sided_padding_fF','reference_holder_C_fF'):r[k]=sum(d[k] for d in details)
                results.append(r);output.write_text(json.dumps(report,indent=2)+'\n')
                print(die,note.name[:8],sharing,seed,{k:r[k] for k in ('kl','ppl_ratio','joint_pass')},flush=True)
    assert all(base.fingerprint(f)==h for f,h in sources.items())
    report['complete']=True;output.write_text(json.dumps(report,indent=2)+'\n')
    print('PASS fixed-DAC early-stop source audit and complete quality cohort',flush=True)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--die',type=int,choices=(1,2));ap.add_argument('--selfcheck',action='store_true');a=ap.parse_args()
    if a.selfcheck:selfcheck()
    else:assert a.die is not None;evaluate(a.die)
