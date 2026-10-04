"""Same-capacitor oracle test of exact radix8 carry selection for fixed mismatch."""
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT / "scripts"))
import numpy as np
from compiler.metrics.imc_fixed_cap_mismatch import coefficient_variance,HIST,PDK


def cap_error(code,physical):
    magnitude=abs(code)
    return np.sign(code)*np.sum(physical*((magnitude[:,None] & (1<<np.arange(4)))!=0),axis=1)


def main():
    h=np.array(json.loads(HIST.read_text())['histogram']);qvals=np.arange(-128,128,dtype=np.int16)
    rng=np.random.default_rng(821530);q=rng.choice(qvals,size=131072,p=h/h.sum())
    _,sigma,_=coefficient_variance(np.array([15]))
    low_error=rng.standard_normal((len(q),4))*sigma
    high_error=rng.standard_normal((len(q),4))*sigma
    high0=np.sign(q)*(abs(q)//8);low0=q-8*high0
    original_error=cap_error(low0,low_error)+8*cap_error(high0,high_error)
    # floor/ceil quotient cover all exact representations with |low|<=7.
    choices=[]
    for high in (np.floor_divide(q,8),np.floor_divide(q,8)+1):
        low=q-8*high;valid=(abs(low)<=7)&(abs(high)<=15)
        assert np.all(low+8*high==q)
        true_error=cap_error(low,low_error)+8*cap_error(high,high_error)
        choices.append((low,high,valid,true_error))
    assert np.all(choices[0][2]|choices[1][2])
    rows=[]
    for cal_relative in (0.,.001,.005,.01,.02):
        # One fixed measurement error per capacitor, shared by candidate codes.
        measured_low=low_error+rng.standard_normal(low_error.shape)*cal_relative*2.**np.arange(4)
        measured_high=high_error+rng.standard_normal(high_error.shape)*cal_relative*2.**np.arange(4)
        scores=[np.where(valid,abs(cap_error(low,measured_low)+8*cap_error(high,measured_high)),np.inf) for low,high,valid,_ in choices]
        select=np.argmin(np.array(scores),axis=0)
        chosen=np.where(select==0,choices[0][3],choices[1][3])
        lo=np.where(select==0,choices[0][0],choices[1][0]);hi=np.where(select==0,choices[0][1],choices[1][1])
        assert np.array_equal(lo+8*hi,q) and abs(lo).max()<=7 and abs(hi).max()<=15
        if cal_relative==0:assert np.all(abs(chosen)<=abs(original_error)+1e-12)
        rows.append(dict(calibration_cap_relative_RMS=cal_relative,error_RMS=float(np.sqrt(np.mean(chosen**2))),
            ratio_to_same_cap_signed8=float(np.sqrt(np.mean(chosen**2)/np.mean(original_error**2))),
            code_changed_fraction=float(np.mean((lo!=low0)|(hi!=high0))),mean_active_units=float(np.mean(abs(lo)+abs(hi))),
            opposite_sign_fraction=float(np.mean(lo*hi<0)),maximum_abs_error=float(abs(chosen).max())))
    out=ROOT/'build/campaign/redundant_weight_calibration';out.mkdir(parents=True,exist_ok=True);p=out/'result.json';assert not p.exists()
    p.write_text(json.dumps(dict(status='PASS_EXACT_CODE_SAME_PHYSICAL_CAP_ORACLE_BOUND',
        sources={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in [HIST,PDK,Path(__file__)]},seed=821530,cells=len(q),
        baseline_signed8_RMS=float(np.sqrt(np.mean(original_error**2))),baseline_mean_active_units=float(np.mean(abs(low0)+abs(high0))),
        fraction_with_two_legal_codes=float(np.mean(choices[0][2]&choices[1][2])),
        scope='Observed−127..127 only. Same fixed independent physicalbinarycaperrors evaluated for both exactcodes. Per-cell calibration/oracle choice is additional stored information, not free. No holder/radix/parasitic/ADC mismatch or siliconyield proof.',
        rows=rows),indent=2)+'\n')
    print('PASS exact reconstruction, legal22-unit banks, same-cap oracle neverworse perweight')
    print('baseline RMS',float(np.sqrt(np.mean(original_error**2))))
    for row in rows:print(row)


if __name__=='__main__':main()
