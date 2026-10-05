"""Fixed-per-cell MIM coefficient-error sensitivity; not empirical silicon yield."""
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT / "scripts"))
import numpy as np
from compiler.metrics.imc_programmable_digit_campaign import digits,radix,FORMATS

PDK=Path.home()/'.ciel/sky130A/libs.ref/sky130_fd_pr/spice/sky130_fd_pr__cap_mim_m3_1.model.spice'
HIST=ROOT/'build/campaign/weight_digits/radix_screen.json'


def coefficient_variance(codes,unit=4.):
    """Binary square capacitors, TT C=2*u^2+.76*u fF, u=w-.025 um."""
    codes=np.abs(np.asarray(codes,dtype=np.int64))
    assert np.all(codes<=15)
    caps=unit*2.**np.arange(4)
    effective_side=(-.76+np.sqrt(.76**2+8*caps))/4
    sigma_frac=.028/effective_side
    bit_sigma_digit=caps*sigma_frac/unit
    selected=(codes[...,None] & (1<<np.arange(4)))!=0
    return np.sum(selected*bit_sigma_digit**2,axis=-1),bit_sigma_digit,selected


def main():
    text=PDK.read_text();assert '0.01*2.8*(carea + cperim)/sqrt(wc*lc*mf)' in text
    h=np.array(json.loads(HIST.read_text())['histogram'],dtype=np.int64)
    qvalues=np.arange(-128,128,dtype=np.int16)
    assert h[0]==0
    rng=np.random.default_rng(830117)
    q=rng.choice(qvalues,size=(512,256),p=h/h.sum())
    rows=[];unit_caps=4*2.**np.arange(4)
    side=(-.76+np.sqrt(.76**2+8*unit_caps))/4
    for fmt in FORMATS:
        lo,hi,_=digits(q,fmt);r=radix(fmt)
        delta=[];variances=[]
        for bank in (lo,hi):
            var,sigma,selected=coefficient_variance(bank)
            error=np.sum(rng.standard_normal(selected.shape)*sigma*selected,axis=-1)*np.sign(bank)
            delta.append(error);variances.append(var)
        error=delta[0]+r*delta[1]
        variance=variances[0]+r*r*variances[1]
        expected=float(variance.mean());observed=float(np.mean(error**2))
        standard_error=float(np.sqrt(2*np.sum(variance**2))/variance.size)
        z=(observed-expected)/standard_error
        assert abs(z)<6, (fmt,z)
        # Reuse the SAME physical errors on every activation; no redraw per MVM.
        activation=rng.integers(-127,128,256)
        first=error@activation;second=error@activation
        assert np.array_equal(first,second)
        actual=q+error
        gain=np.sum(actual*q,axis=1)/np.sum(q.astype(float)**2,axis=1)
        calibrated=actual/gain[:,None]-q
        active=h>0;ql,qh,_=digits(qvalues[active],fmt)
        vl,_,_=coefficient_variance(ql);vh,_,_=coefficient_variance(qh)
        histogram_variance=float(h[active]@(vl+r*r*vh)/h.sum())
        histogram_signal=float(h@(qvalues.astype(float)**2)/h.sum())
        rows.append(dict(format=fmt,exact_histogram_coefficient_error_RMS=histogram_variance**.5,
            exact_histogram_weight_signal_RMS=histogram_signal**.5,
            exact_histogram_white_activation_error_SNR_dB=float(10*np.log10(histogram_signal/histogram_variance)),
            monte_carlo_variance_z=z,Monte_Carlo_fixed_die_weight_error_RMS=observed**.5,
            ideal_per_column_gain_calibrated_error_RMS=float(np.sqrt(np.mean(calibrated**2))),
            maximum_abs_fixed_weight_error=float(abs(error).max())))
    out=ROOT/'build/campaign/fixed_cap_mismatch';out.mkdir(parents=True,exist_ok=True)
    path=out/'coefficient_sensitivity.json';assert not path.exists()
    path.write_text(json.dumps(dict(status='PASS_PDK_COEFFICIENT_SENSITIVITY_NOT_SILICON_YIELD',
        sources={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [PDK,HIST,Path(__file__)]},
        model='Independent Gaussian per physical binary capacitor; mf1; cap sizes4/8/16/32fF; TT square electrical dimensions inferred from C=2u²+.76u. No process common-mode, correlation, parasitic/state/holder/DAC mismatch or input-dependent radix error.',
        calibration='Ideal per-column multiplicative gain obtained from exact weight vectors is an optimistic bound, not actual calibration implementation.',
        seed=830117,columns=512,rows_per_column=256,variance_gate='abs(z)<6 predeclared; heterogeneous independent Gaussian exact variance',
        cap_nominal_fF=unit_caps.tolist(),drawn_square_side_um=(side+.025).tolist(),relative_sigma=(.028/side).tolist(),rows=rows),indent=2)+'\n')
    print('PASS fixed-per-cap repeated-MVM identity, exact histogram variance, Gaussian variance control')
    for row in rows:print(row)


if __name__=='__main__':main()
