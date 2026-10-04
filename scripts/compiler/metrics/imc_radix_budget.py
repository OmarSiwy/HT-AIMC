"""Exact radix identities and conditional error budgets; no SPICE.

Fixed inputs/weights come from the existing compiler. Calibration is first six
saved positions; evaluation is last three. Synthetic full-range stress is a
separate, explicitly labeled dataset. No model-quality or chip-energy claim.
"""
import hashlib
import json
import math
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "build/research/imc_radix_budget.json"
KT = 1.380649e-23 * 300.15


def bit_planes(x):
    x = np.asarray(x, dtype=np.int64)
    assert np.all((-128 <= x) & (x <= 127))
    return np.stack([np.sign(x) * ((np.abs(x) >> b) & 1) for b in range(8)])


def digit_count(x, dynamic):
    if not dynamic:
        return np.full(len(x), 8, dtype=int)
    return np.array([int(np.max(np.abs(row))).bit_length() for row in x])


def accumulate(w, x, gain, carr, cacc, dynamic=False, ratio_error=0.0,
               reset_v=0.0, plane_gain=None, reset_each=False):
    planes = bit_planes(x) @ w.T
    counts = digit_count(x, dynamic)
    a = cacc * (1 + ratio_error) / (cacc * (1 + ratio_error) + carr)
    h = np.full((len(x), len(w)), reset_v, dtype=float)
    gains = np.ones(8) if plane_gain is None else np.asarray(plane_gain)
    for b in range(8):
        active = counts > b
        if reset_each:
            h[active] = reset_v
        h[active] = a * h[active] + (1-a) * gain * gains[b] * planes[b, active]
    h[counts == 0] = 0
    recovered = h * (2.0 ** counts)[:, None] / gain
    return recovered, h, counts


def affine_fit(observed, exact, ncal):
    a, b = observed[:ncal], exact[:ncal]
    ac, bc = a-a.mean(0), b-b.mean(0)
    var = np.sum(ac**2, axis=0)
    slope = np.divide(np.sum(ac*bc, axis=0), var, out=np.ones_like(var), where=var > 1e-20)
    intercept = b.mean(0) - slope*a.mean(0)
    return observed*slope+intercept


def error_stats(observed, exact, ncal):
    e, ref = observed[ncal:]-exact[ncal:], exact[ncal:]
    mse, signal = float(np.mean(e**2)), float(np.mean(ref**2))
    return dict(rms_MAC=math.sqrt(mse), max_MAC=float(np.max(abs(e))),
                SNR_db=10*math.log10(max(signal,1e-30)/max(mse,1e-30)))


def full_subset_plane_counts():
    """Held-out xq[6:9], every row group and output tile; no selected-block bias."""
    names=("attn_q","attn_k","attn_v","attn_o","ffn_gate","ffn_up","ffn_down")
    records=[]
    for rows in (16,64,128):
        group=[]
        for name in names:
            with np.load(ROOT/f"scripts/compiler/out/programming/{name}.npz") as z:
                nout,nin=z["Wq"].shape
            with np.load(ROOT/f"scripts/compiler/out/acts/{name}.npz") as z:
                x=z["xq"][6:9].astype(np.int64)
            nrow=math.ceil(nin/rows)
            padded=np.pad(x,((0,0),(0,nrow*rows-nin)))
            b=digit_count(padded.reshape(-1,rows),True).reshape(len(x),nrow)
            used_rows=np.minimum(rows,nin-np.arange(nrow)*rows)
            output_tiles=math.ceil(nout/16)
            data_cols=output_tiles*16
            separate=int(b.sum())*data_cols
            final=int(np.count_nonzero(b))*data_cols
            p=dict(tensor=name,rows=rows,input_channels=nin,output_channels=nout,
                   heldout_tokens=len(x),output_tile_columns=16,
                   mean_B_including_zero=float(b.mean()),max_B=int(b.max()),
                   B_histogram={str(k):int(np.count_nonzero(b==k)) for k in range(9)},
                   useful_MAC_weighted_mean_B=float(np.sum(b*used_rows[None,:])/(len(x)*nin)),
                   separate_data_ADC_events=separate,final_data_ADC_events=final,
                   separate_checksum_ADC_events=int(b.sum())*output_tiles,
                   final_checksum_ADC_events=int(np.count_nonzero(b))*output_tiles,
                   fixed8_data_ADC_events=8*len(x)*nrow*data_cols,
                   useful_MACs=len(x)*nin*nout)
            assert separate <= p["fixed8_data_ADC_events"]
            assert final <= separate
            group.append(p)
        sep=sum(p["separate_data_ADC_events"] for p in group)
        fin=sum(p["final_data_ADC_events"] for p in group)
        fixed=sum(p["fixed8_data_ADC_events"] for p in group)
        records.append(dict(rows=rows,per_tensor=group,
            separate_data_ADC_events=sep,final_data_ADC_events=fin,
            separate_checksum_ADC_events=sum(p["separate_checksum_ADC_events"] for p in group),
            final_checksum_ADC_events=sum(p["final_checksum_ADC_events"] for p in group),
            fixed8_data_ADC_events=fixed,
            dynamic_separate_vs_fixed8_events=sep/fixed,
            separate_vs_final_event_ratio=sep/fin,
            data_ADC_weighted_mean_B_including_zero=sep/(fixed/8),
            useful_MAC_weighted_mean_B=sum(p["useful_MAC_weighted_mean_B"]*p["useful_MACs"] for p in group)
                /sum(p["useful_MACs"] for p in group),
            maximum_B=max(p["max_B"] for p in group)))
    return records


def adc_budget(w, x, gain, carr, ncal, dynamic, bits, span, read_noise, sharing_noise):
    exact = x @ w.T
    _, h, count = accumulate(w, x, gain, carr, carr, dynamic)
    step = np.asarray(span) / 2**bits
    code = np.floor(h / step + .5)
    clipped = (code < -(2**(bits-1))) | (code > 2**(bits-1)-1)
    quant = np.clip(code, -(2**(bits-1)), 2**(bits-1)-1) * step
    scale = (2.0 ** count)[:, None] / gain
    converted = quant * scale
    q_mse = (converted-exact)**2
    sum4 = (4.0**count-1)/3
    # Independent voltage errors: ADC after last hold, sharing after each mean.
    # This additive error budget omits noise-dependent clipping/quantizer bias.
    read_coefficient=scale**2*(count>0)[:,None]
    noise_var = read_noise**2 * read_coefficient + (4*sum4)[:,None] * sharing_noise**2 / gain**2
    noise_var[count == 0] = 0
    expected_mse = float(np.mean((q_mse + noise_var)[ncal:]))
    signal = float(np.mean(exact[ncal:]**2))
    share_mse=float(np.mean(((4*sum4)[:,None]*sharing_noise**2/gain**2)[ncal:]))
    read_allowance=signal/10**(36.74/10)-float(q_mse[ncal:].mean())-share_mse
    return dict(dynamic_MSB_skip=dynamic, ADC_bits=bits, span_V=np.asarray(span).tolist(),
                read_noise_V=read_noise, sharing_noise_V=np.asarray(sharing_noise).tolist(),
                mean_digits=float(count[ncal:].mean()),
                final_ADC_events=int(np.count_nonzero(count[ncal:])*len(w)),
                separate_ADC_events=int(np.sum(count[ncal:])*len(w)),
                heldout_clipped=int(np.sum(clipped[ncal:])),
                quantization_rms_MAC=float(np.sqrt(np.mean(q_mse[ncal:]))),
                sharing_rms_MAC=math.sqrt(share_mse),
                ADC_noise_max_uV_for_illustrative_36p74=(math.sqrt(read_allowance/float(np.mean(read_coefficient[ncal:])))*1e6
                    if read_allowance>0 else None),
                conditional_rms_MAC=math.sqrt(expected_mse),
                conditional_SNR_db=10*math.log10(max(signal,1e-30)/max(expected_mse,1e-30)),
                output_rms_mV=float(np.sqrt(np.mean(h[ncal:]**2))*1000))


def main():
    # Exhaustive signed scalar identity, including -128, plus exact cancellation.
    vals = np.arange(-128,128).reshape(-1,1)
    for dynamic in (False, True):
        y, _, _ = accumulate(np.array([[7]]), vals, np.array([.01]),
                             np.array([200e-15]), np.array([200e-15]), dynamic)
        assert np.allclose(y[:,0], 7*vals[:,0], atol=1e-10)
        z, _, _ = accumulate(np.array([[1,-1]]),np.array([[127,127],[-128,-128]]),
                             np.array([.01]),np.array([200e-15]),np.array([200e-15]),dynamic)
        assert np.allclose(z,0)
    # Non-unit capacitor ratio: independent closed-form impulse coefficients.
    impulses=(2**np.arange(8)).reshape(-1,1)
    impulses[-1,0]=-128
    y,_,_=accumulate(np.array([[1]]),impulses,np.array([.01]),
                     np.array([200e-15]),np.array([200e-15]),ratio_error=.01)
    a=1.01/2.01
    assert np.allclose(y[:,0],np.sign(impulses[:,0])*256*(1-a)*a**(7-np.arange(8)))
    datasets, fingerprints = [], {}
    for name in ("attn_q", "attn_k", "attn_v", "attn_o", "ffn_gate", "ffn_up", "ffn_down"):
        wp = ROOT / f"scripts/compiler/out/programming/{name}.npz"
        xp = ROOT / f"scripts/compiler/out/acts/{name}.npz"
        for p in (wp,xp):
            fingerprints[str(p.relative_to(ROOT))] = hashlib.sha256(p.read_bytes()).hexdigest()
        with np.load(wp) as f:
            w = f["Wq"][:8].astype(np.int64)
        with np.load(xp) as f:
            x = f["xq"].astype(np.int64)
        datasets.append((name,w[:,:16],x[:,:16],6))
        if name == "ffn_down":
            # Same first 128 channels as the nominal physical replay; ADC only
            # remains an analytical budget, with calibration on positions 0:6.
            datasets.append(("ffn_down_128row_replay",w[:,:128],x[:,:128],6))
    rng = np.random.default_rng(941)
    datasets.append(("synthetic_full_range",rng.integers(-7,8,(8,16)),
                     rng.integers(-128,128,(640,16)),128))
    records = []
    for name,w,x,ncal in datasets:
        carr = (120 + 4*np.sum(np.abs(w),axis=1))*1e-15
        gain = 4e-15*.45/carr
        exact = x@w.T
        record = dict(dataset=name,ncal=ncal,ntest=len(x)-ncal,
                      weight_shape=list(w.shape),weights=w.tolist(),
                      Carray_fF=(carr*1e15).tolist(),gain_mV_MAC=(gain*1e3).tolist(),
                      maximum_activation=int(np.max(np.abs(x[ncal:]))),
                      test_digit_counts=digit_count(x[ncal:],True).tolist(),
                      ratio_sweep=[], plane_gain_sweep=[], reset_sweep=[], ADC_sweep=[])
        for dynamic in (False,True):
            base,h,count = accumulate(w,x,gain,carr,carr,dynamic)
            assert np.allclose(base,exact,atol=1e-9)
            broken,_,_ = accumulate(w,x,gain,carr,carr,dynamic,reset_each=True)
            if name == "synthetic_full_range":
                assert error_stats(broken,exact,ncal)["rms_MAC"] > 100
            for delta in (-.03,-.01,-.003,0,.003,.01,.03):
                y,_,_ = accumulate(w,x,gain,carr,carr,dynamic,ratio_error=delta)
                record["ratio_sweep"].append(dict(dynamic=dynamic,ratio_error=delta,
                    raw=error_stats(y,exact,ncal),
                    calibrated=error_stats(affine_fit(y,exact,ncal),exact,ncal)))
            y,_,_ = accumulate(w,x,gain,carr,np.full(8,carr.mean()),dynamic)
            record["ratio_sweep"].append(dict(dynamic=dynamic,ratio_error="one_mean_Cacc",
                raw=error_stats(y,exact,ncal),
                calibrated=error_stats(affine_fit(y,exact,ncal),exact,ncal)))
            for e in (.001,.01):
                for mode,pg in (("common",np.full(8,1+e)),
                                ("bit_gradient",1+e*(np.arange(8)-3.5))):
                    y,_,_ = accumulate(w,x,gain,carr,carr,dynamic,plane_gain=pg)
                    record["plane_gain_sweep"].append(dict(dynamic=dynamic,error=e,mode=mode,
                        calibrated=error_stats(affine_fit(y,exact,ncal),exact,ncal)))
            for reset in (1e-4,1e-3):
                y,_,_ = accumulate(w,x,gain,carr,carr,dynamic,reset_v=reset)
                active=count>0
                assert np.allclose((y-base)[active],reset/gain,atol=1e-9)
                record["reset_sweep"].append(dict(dynamic=dynamic,reset_V=reset,
                                                error=error_stats(y,exact,ncal)))
            # A static column range fitted only to calibration, with 20% guard.
            cal_span=np.maximum(2.4*np.max(abs(h[:ncal]),axis=0),1e-4)
            for bits in (8,9,10,11):
                for label,span in (("1V",1.0),("half_V",.5),("calibration_static",cal_span)):
                    for read,share in ((0.,np.zeros(8)),(.0002,np.sqrt(KT/(2*carr)))):
                        v=adc_budget(w,x,gain,carr,ncal,dynamic,bits,span,read,share)
                        record["ADC_sweep"].append(dict(range_policy=label,**v))
        records.append(record)
    ratios=[]
    s4=sum(4**b for b in range(8))
    assert s4==21845
    for c in (200,300,500):
        sh=math.sqrt(KT/(2*c*1e-15))
        ref=s4*(.0002**2+(1/512)**2/12)
        for bits in (9,10,11):
            variance=65536*(.0002**2+(1/2**bits)**2/12)+4*s4*sh**2
            ratios.append(dict(Cacc_fF=c,final_bits=bits,vs_separate9bit_variance=variance/ref))
    result=dict(scope="behavioral arithmetic and conditional error budget; no physical accumulator or full-model validation",
                noise_scope="independent additive quantization/read/share errors; share variance kT/(2C) is a topology-dependent assumption; real plane noise, covariance and noise-dependent clipping are omitted",
                fingerprints=fingerprints,records=records,noise_comparison=ratios,
                equal_noise_final_vs_separate_variance=65536/s4,
                required_final_noise_ratio=math.sqrt(s4)/256,
                extra_effective_bits=math.log2(256/math.sqrt(s4)),checks="PASS")
    result["full_compiled_subset_plane_counts"]=full_subset_plane_counts()
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,indent=2)+"\n")
    print(f"PASS: {len(records)} datasets, exhaustive signed-code identity and reset/cancellation controls; {OUT}")
    down=next(p for p in records if p["dataset"]=="ffn_down")
    for p in down["ADC_sweep"]:
        if p["ADC_bits"]==9 and p["range_policy"]=="1V" and p["read_noise_V"]:
            print("ffn_down",json.dumps(p))


if __name__ == "__main__":
    main()
