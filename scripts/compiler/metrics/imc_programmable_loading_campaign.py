"""Bounded Cu4 system sensitivity to measured unsigned programming-bank loading.

Not a signed array or multi-node noise proof: replaces each digit's ideal active
capacitance with its measured 1kHz AC port loading, preserving ideal signal charge.
"""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT / "scripts"))
from compiler.metrics import imc_reset_noise_campaign as reset
legacy=reset.legacy
np=reset.np
OUT=ROOT/'build/campaign/programmable_loading_precision'
MEASURED=ROOT/'build/campaign/programmable_cap/w042_tt27_s8_step1/analysis_v2.json'
original_scenes=legacy.scenes


def table():
    data=json.loads(MEASURED.read_text())
    assert data['unit_fF']==4 and data['width_um']==.42
    rows={r['code']:r for r in data['rows'] if r['mode']=='bypass'}
    compiled={r['code']:r for r in data['rows'] if r['mode']=='compiled'}
    assert set(rows)==set(range(16))
    values=[]
    for code in range(16):
        c=compiled[code]['port_loading'][0]
        assert c['frequency_Hz']==1000 and np.isclose(c['effective_cap_fF'],4*code,atol=1e-10)
        entry=rows[code]['port_loading'][0]
        assert entry['frequency_Hz']==1000
        values.append(entry['effective_cap_fF'])
    return np.array(values)


CAPS=table()


def scenes(q,w,dx,pooled,format):
    banks=original_scenes(q,w,dx,pooled,format)
    for bank,d in zip(banks,legacy.digits(w,format)[:2]):
        groups=(q.shape[1]+255)//256
        for s,first in zip(bank,range(0,groups,4 if pooled else 1)):
            effective=[]
            for g in range(first,min(first+(4 if pooled else 1),groups)):
                code=np.abs(d[g*256:(g+1)*256].astype(np.int16))
                effective.append(CAPS[code].sum(axis=0)/4)
            s['units']=np.array(effective)
    return banks


def selfcheck():
    reset.selfcheck()
    q=np.ones((2,257),dtype=np.int16);w=np.zeros((257,3),dtype=np.int16);dx=np.ones((2,2))
    for pooled in (False,True):
        bs=scenes(q,w,dx,pooled,'balanced9')
        assert all(np.all(s['Q_per_Cu']==0) for b in bs for s in b)
        for b in bs:
            assert np.allclose(sum(s['units'].sum(axis=0) for s in b)*4,257*CAPS[0])
    print('PASS measured compiled AC oracle, zero-weight loading, ragged pooled mapping',flush=True)


def freeze():
    p=json.loads((reset.OUT/'protocol.json').read_text())
    p['sources'][str(Path(__file__))]=legacy.base.fingerprint(__file__)
    p['sources'][str(MEASURED)]=legacy.base.fingerprint(MEASURED)
    p['Cu_fF']=[4]
    p['status']='Frozen unsigned programming-port sensitivity before quality evaluation'
    p['programming_model']=dict(frequency_Hz=1000,effective_C_fF_by_unsigned_code=CAPS.tolist(),
        mapped='Each actual magnitude digit0..15 uses measured bypass C(code); original120fF column floor retained; matched ideal holder resized to total effective C.',
        exclusions='Sign mux, SRAM state, array transients, frequency dispersion, hidden-mode thermal covariance, mismatch and dynamic radix errors absent. Signal charge still ideal Cu*digit. kT/C effective-cap noise is a sensitivity assumption, not proven network noise.',
        storage='Measured4bit bank installs60fF+16MOS even for0; this full4bit fixture is applied equally to both banks. Minimal3bit banks would require separate measurement. Installed SRAM/sign/clock/layout area unpriced.')
    OUT.mkdir(parents=True,exist_ok=True)
    text=json.dumps(p,indent=2)+'\n';path=OUT/'protocol.json'
    if path.exists():assert path.read_text()==text
    else:path.write_text(text)
    src=reset.OLD/'calibration_Cu4.json';dst=OUT/src.name
    if dst.exists():assert dst.read_bytes()==src.read_bytes()
    else:dst.write_bytes(src.read_bytes())
    return p


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--selfcheck',action='store_true');ap.add_argument('--freeze',action='store_true');a=ap.parse_args()
    legacy.OUT,legacy.prepare,legacy.selfcheck,legacy.freeze=OUT,reset.prepare,selfcheck,freeze
    if a.selfcheck:selfcheck()
    elif a.freeze:freeze()
    else:
        # Original arithmetic check uses ideal scenes, then installs measured load.
        selfcheck()
        legacy.selfcheck=lambda:None
        legacy.scenes=scenes
        legacy.evaluate(4)
