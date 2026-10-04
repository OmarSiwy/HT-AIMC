"""Native-charge pooling: exact controls, acquisition-aware budgets and scale alignment.

All circuit performance here is conditional. Monte Carlo is a linear capacitor
noise model, not foundry device mismatch or transient-noise SPICE.
"""
import hashlib
import json
import math
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
KT = 1.380649e-23*300.15


def radix_charge(w, x, c, bits, ratio=None):
    """x[sample,group,row], nominal array C[group], optional holder/array ratio."""
    rho = np.full(len(c), .5) if ratio is None else ratio/(1+ratio)
    q = np.zeros(x.shape[:2])
    for b in range(int(np.max(bits))):
        p = (np.sign(x)*((np.abs(x)>>b)&1)*w).sum(2)
        active = b < bits
        q[:,active] = rho[active]*(q[:,active]+p[:,active])
    return q


def algebra_controls():
    rng=np.random.default_rng(97110)
    w=rng.integers(-7,8,(8,16))
    x=rng.integers(-128,128,(4096,8,16))
    c=rng.uniform(100,2000,8)*1e-15
    exact=(w*x).sum(2)
    q=radix_charge(w,x,c,np.full(8,8))
    assert np.array_equal(q*256,exact)
    h=q/c
    recovered=(h@c)
    assert np.max(abs(recovered-exact.sum(1)/256)) < 1e-12
    # Equal-voltage copying is a different operator; even fitted scalar fails.
    copied=h.sum(1)
    gain,offset=np.polyfit(copied[:512],exact[:512].sum(1),1)
    wrong_error=copied[512:]*gain+offset-exact[512:].sum(1)
    assert np.sqrt(np.mean(wrong_error**2)) > 100
    # Power-of-two scales can be embedded in the number of halving operations.
    exponents=np.array([-3,-2,-1,0,1,2,3,0])
    b0=int(np.max(exponents+8))
    aligned_bits=b0-exponents
    aligned=radix_charge(w,x,c,aligned_bits).sum(1)*2**b0
    target=exact@np.exp2(exponents)
    assert np.max(abs(aligned-target)) < 1e-10
    bad=q.sum(1)*256
    assert np.sqrt(np.mean((bad-target)**2)) > 1000
    ratio_cases=[]
    for epsilon in (0,.001,.01,.03):
        qp=radix_charge(w,x,c,np.full(8,8),np.full(8,1+epsilon)).sum(1)
        g,o=np.polyfit(qp[:512],exact[:512].sum(1),1)
        e=qp[512:]*g+o-exact[512:].sum(1)
        ratio_cases.append(dict(holder_ratio_error=epsilon,rms_MAC=float(np.sqrt(np.mean(e**2)))))
    assert ratio_cases[0]["rms_MAC"] < 1e-9
    assert ratio_cases[2]["rms_MAC"] > 1
    return dict(samples=len(x),unequal_C_exact_max_MAC=float(np.max(abs(recovered*256-exact.sum(1)))),
        equal_voltage_copy_rms_MAC=float(np.sqrt(np.mean(wrong_error**2))),
        unaligned_scale_rms_MAC=float(np.sqrt(np.mean((bad-target)**2))),
        exponent_hybrid_max_MAC=float(np.max(abs(aligned-target))),
        exponents=exponents.tolist(),hybrid_bits=aligned_bits.tolist(),ratio_cases=ratio_cases)


def budgets():
    # Illustrative reuse of measured COLUMN capacitor values; not measured row groups.
    c=np.array([568,484,304,600,516,336,444,424])*1e-15
    cb=948e-15
    ct=float(c.sum()+cb)
    ideal_r=ct/np.linalg.norm(c)
    loaded_r=ct/np.linalg.norm(c+cb)
    alpha=4e-15*.45/256
    f=(1+2*4.**-8)/3
    rng=np.random.default_rng(97111)
    # Independent pre-reset capacitors, then conserved charge average.
    initial=rng.normal(size=(200000,9))*np.sqrt(KT*np.r_[c,cb])
    common=initial.sum(1)/ct
    measured=float(np.var(common))
    expected=KT/ct
    assert abs(measured/expected-1)<.015
    # Independent differential-mode equilibrium noise for the lumped two-node
    # circuit. Internal Johnson currents sum to zero; a bus-only sample sees them.
    dv=rng.normal(0,math.sqrt(KT*(1/c.sum()+1/cb)),len(common))
    bus=common-c.sum()/ct*dv
    assert abs(np.var(bus)/(KT/cb)-1)<.015
    # Optimally allocated thermal ADC energy: Cauchy-Schwarz lower bound equality.
    cn=c/c.sum()
    sigma2=1/cn
    eps2=float(np.sum(cn**2*sigma2))
    separate_min=float(np.sum(1/sigma2))
    pooled_min=float(cn.sum()**2/eps2)
    assert abs(separate_min-pooled_min)<1e-12
    threshold=math.sqrt(8.) # equal C: pooled load wins RMS if Cb/C >= sqrt(K)
    schedules=[]
    for g in (1,2,4,8):
        rounds=32//g
        for adc_ns in (295,341):
            for join_ns in ((0,) if g==1 else (40,100)):
                # Fixed full8-plane timing, two W4 banks; no unsupported overlap.
                time_ns=2*(488+join_ns+rounds*adc_ns)
                tops=2*76*1024**2/(time_ns*1e-9)/1e12
                schedules.append(dict(pool_groups=g,ADC_ns=adc_ns,join_ns=join_ns,
                    ADC_rounds_per_slice=rounds,group_ns=time_ns,conditional_TOPS=tops))
    r=dict(capacitors_fF=(c*1e15).tolist(),cap_scope="illustrative eight prior column caps, not measured row-group layout",
        read_load_fF=948,pooled_gain_uV_per_MAC=alpha/ct*1e6,
        ideal_source_ADC_noise_tightening=ideal_r,ideal_source_extra_bits=math.log2(ideal_r),
        passive_loaded_ADC_noise_tightening=loaded_r,passive_loaded_extra_bits=math.log2(loaded_r),
        optimal_thermal_energy_ratio_unloaded=pooled_min/separate_min,
        optimal_thermal_energy_ratio_both_loaded=(ct/(c.sum()+8*cb))**2,
        loaded_energy_ratio_scope="decision-noise component with fixed passive Cb and independently scalable E=a/sigmaV^2; excludes acquisition noise floor and Cb resizing",
        equal_cap_load_threshold_Cb_over_C=threshold,
        common_charge_noise_uV=math.sqrt(expected)*1e6,
        bus_wideband_noise_uV=math.sqrt(KT/cb)*1e6,
        differential_bus_noise_uV=math.sqrt(KT*c.sum()/(cb*ct))*1e6,
        reset_only_optimistic_noise_MAC=math.sqrt(KT*(f*c.sum()+cb))/alpha,
        thermalized_common_noise_MAC=math.sqrt(KT*ct)/alpha,
        comparator_100uV_noise_MAC=100e-6*ct/alpha,
        monte_carlo_samples=len(common),common_mode_variance_ratio=measured/expected,
        bus_variance_ratio=float(np.var(bus)/(KT/cb)),schedules=schedules,
        max_total_W8_group_ns_for_25TOPS=2*76*1024**2/25e12*1e9)
    return r


def saved_operands():
    records=[]
    for name in ("attn_q","attn_k","attn_v","attn_o","ffn_gate","ffn_up","ffn_down"):
        wp=ROOT/f"scripts/compiler/out/programming/{name}.npz"
        xp=ROOT/f"scripts/compiler/out/acts/{name}.npz"
        with np.load(wp) as z:
            w=z["Wq"].astype(np.int64)
            # Existing saved compiler path has scalar dx_in, per-output dw.
            assert z["dx_in"].shape==() and z["dw"].shape==(len(w),)
        with np.load(xp) as z:
            x=z["xq"][6:9].astype(np.int64)
        padded=np.pad(x,((0,0),(0,(-x.shape[1])%1024))).reshape(len(x),-1,8,128)
        local=np.ceil(np.log2(np.max(abs(padded),axis=3)+1)).astype(int)
        common=local.max(2)
        active=np.max(abs(padded),axis=3)>0
        local_planes=int(local.sum())
        common_planes=int((common[:,:,None]*active).sum())
        # Charge invariance for every saved output, including last partial group.
        groups=math.ceil(w.shape[1]/128)
        wg=np.pad(w,((0,0),(0,groups*128-w.shape[1]))).reshape(len(w),groups,128)
        xg=np.pad(x,((0,0),(0,groups*128-x.shape[1]))).reshape(len(x),groups,128)
        s=np.einsum("sgr,ogr->sog",xg,wg)
        assert np.array_equal(s.sum(2),x@w.T)
        records.append(dict(tensor=name,input_rows=w.shape[1],outputs=len(w),
            scalar_activation_scale=True,column_weight_scale=True,
            local_group_planes=local_planes,common_exponent_planes=common_planes,
            extra_plane_fraction=common_planes/local_planes-1,
            mean_absolute_W4=float(np.mean(abs(w))),
            exact_partial_reconstruction=True,
            sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (wp,xp)}))
    return records


def main():
    result=dict(status="VERIFIED",scope="algebra and conditional numerical models, not architecture validation",
        algebra=algebra_controls(),budgets=budgets(),saved_compiler=saved_operands(),
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    out=ROOT/"build/research/imc_native_charge_analysis.json"
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2)+"\n")
    print("PASS exact charge/radix identities; rejection controls; 200000-draw noise covariance; optimum energy equality; seven compiler tensors")
    print(out)
    print(json.dumps({"algebra":result["algebra"],"budgets":result["budgets"]},indent=2))


if __name__=="__main__":
    main()
