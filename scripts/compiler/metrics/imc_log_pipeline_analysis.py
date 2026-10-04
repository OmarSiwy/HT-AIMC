"""Self-check log/charge arithmetic and conditional IMC budgets, not a chip model.

Quantization experiments use synthetic signed dots and equal magnitude-code
counts. Noise experiments use stated Gaussian log errors, not foundry Monte
Carlo. Device simulations and layout must independently validate the budgets.
"""
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
SEED = 260910
K = 1.380649e-23
Q = 1.602176634e-19
TEMP = 300.15
S = 1 / 26  # Assumed local inverse gm/ID [V], not a PDK fit.


def arithmetic():
    rng = np.random.default_rng(SEED)
    x, w = np.exp(rng.uniform(-math.log(128), 0, (2, 8192)))
    ordinary = np.exp((S * np.log(x) + S * np.log(w)) / (2 * S))
    corrected = np.exp((2 * S * np.log(x) + 2 * S * np.log(w)) / (2 * S))
    assert np.allclose(ordinary, np.sqrt(x * w), rtol=1e-13)
    assert np.max(abs(ordinary - x * w)) > .24
    assert np.max(abs(corrected / (x * w) - 1)) < 3e-15
    # An unequal sharing ratio changes operand exponents independently.
    a = .51
    unequal = np.exp(2 * (a * np.log(x) + (1 - a) * np.log(w)))
    assert np.max(abs(unequal / (x * w) - 1)) > .09
    # Native bottom-plate voltage stacking attenuates the moved input by C/(C+Cp).
    cp_over_c = .05
    lam = 1 / (1 + cp_over_c)
    stack = np.exp(np.log(x) + lam * np.log(w))
    assert np.allclose(stack, x * w**lam)
    assert np.max(abs(stack / (x * w) - 1)) > .25
    pair_a, pair_b = np.array([1., 4.]), np.array([2., 2.])
    assert sum(np.log(pair_a)) == sum(np.log(pair_b))
    assert sum(pair_a) != sum(pair_b)
    # Sign/zero-aware expansion can recover a signed dot; pooling logs cannot.
    xs, ws = rng.integers(-128, 128, (2, 1024, 128)) / 128
    active = (xs != 0) & (ws != 0)
    decoded = np.zeros_like(xs)
    decoded[active] = np.sign(xs[active] * ws[active]) * np.exp(
        np.log(abs(xs[active])) + np.log(abs(ws[active])))
    exact = (xs * ws).sum(1)
    assert np.max(abs(decoded.sum(1) - exact)) < 5e-14
    return dict(samples=len(x), corrected_product_relative_max=float(np.max(abs(corrected / (x*w) - 1))),
        unchanged_slope_absolute_max=float(np.max(abs(ordinary - x*w))),
        cap_share_fraction=a, unequal_share_relative_max=float(np.max(abs(unequal/(x*w)-1))),
        stack_Cp_over_C=cp_over_c, stack_relative_max=float(np.max(abs(stack/(x*w)-1))),
        pooled_log_counterexample=dict(products_a=pair_a.tolist(), products_b=pair_b.tolist(),
            common_log_sum=float(np.log(pair_a).sum()), sum_a=float(pair_a.sum()), sum_b=float(pair_b.sum())),
        signed_dot_absolute_max=float(np.max(abs(decoded.sum(1)-exact))))


def cancellation():
    rng = np.random.default_rng(SEED + 1)
    sigma = .01
    records = []
    draws = 200_000
    for residual in (1., .1, .001, 0.):
        p = np.array([1., -(1-residual)])
        y = float(p.sum())
        for rho in (0., .5, 1.):
            eta = sigma * (math.sqrt(rho)*rng.normal(size=(draws, 1))
                + math.sqrt(1-rho)*rng.normal(size=(draws, 2)))
            out = np.exp(eta - sigma*sigma/2) @ p
            variance = (float(p@p)*(math.exp(sigma*sigma)-math.exp(rho*sigma*sigma))
                + y*y*math.expm1(rho*sigma*sigma))
            measured = float(np.var(out))
            if variance:
                assert abs(measured/variance-1) < .018
            else:
                assert np.max(abs(out)) == 0
            records.append(dict(sum=y, rho=rho, kappa1=float(abs(p).sum()/abs(y)) if y else None,
                kappa2=float(np.linalg.norm(p)/abs(y)) if y else None,
                predicted_rms=math.sqrt(variance), measured_rms=math.sqrt(measured),
                predicted_relative_rms=math.sqrt(variance)/abs(y) if y else None))
    return dict(log_error_sigma=sigma, draws_per_case=draws,
        scope="Mean-corrected lognormal errors with equicorrelation rho; no device-noise model", cases=records)


def quantization():
    rng = np.random.default_rng(SEED + 2)
    records = []
    for distribution in ("uniform", "log_uniform"):
        values = (rng.uniform(1/128, 1, (2, 8192, 128)) if distribution == "uniform"
            else np.exp(rng.uniform(-math.log(128), 0, (2, 8192, 128))))
        values *= rng.choice([-1, 1], values.shape)
        values[rng.random(values.shape) < .05] = 0
        ref = (values[0]*values[1]).sum(1)
        linear = np.sign(values)*np.round(abs(values)*255)/255
        logq = np.zeros_like(values)
        mask = values != 0
        # Both encodings: sign plus 8 magnitude bits, one zero + 255 nonzero levels.
        code = np.round(np.log(abs(values[mask])*128) * 254/math.log(128))
        logq[mask] = np.sign(values[mask])*np.exp(code*math.log(128)/254)/128
        for encoding, decoded in (("linear", linear), ("log", logq)):
            delta = (decoded[0]*decoded[1]).sum(1)-ref
            nrms = float(np.linalg.norm(delta)/np.linalg.norm(ref))
            records.append(dict(distribution=distribution, encoding=encoding, output_normalized_rms=nrms,
                output_CSNR_dB=-20*math.log10(nrms), output_max_absolute=float(np.max(abs(delta))),
                operand_normalized_rms=float(np.linalg.norm(decoded-values)/np.linalg.norm(values)),
                nonzero_operand_relative_rms=float(np.sqrt(np.mean((decoded[mask]/values[mask]-1)**2)))))
    return dict(dots=8192, terms_per_dot=128, sign_bits=1, magnitude_bits=8,
        exact_zero_probability=.05, nonzero_range=[1/128, 1],
        scope="Synthetic distributions; input quantization only, no analog error, calibration or output ADC", cases=records)


def budgets():
    c = 20e-15
    fanout = 1024
    t = 100e-9
    eps = .01
    load = fanout*c
    # Diode ODE: z'=z(1-z)/tau, z=Iout/Iin. Exact step settling to relative eps.
    fall_factor = math.log((1-1/128)*(1+eps)/eps)
    rise_factor = math.log((128-1)*(1-eps)/eps)
    min_i = load*S*fall_factor/t
    near_i = load*S*math.log(1/eps)/t
    near_gm = near_i/S
    var = K*TEMP/(2*c*S*S)
    precision = []
    for target in (.01, .001):
        qshot = Q/target**2
        a = 3.356e-3
        precision.append(dict(relative_rms=target,
            each_sample_C_fF=K*TEMP/(2*S*S*math.log1p(target*target))*1e15,
            four_independent_threshold_devices_each_WL_um2=(2*a/(S*target))**2,
            one_independent_threshold_device_WL_um2=(a/(S*target))**2,
            single_branch_shot_Q_fC=qshot*1e15, single_branch_shot_I_nA=qshot/t*1e9,
            single_branch_shot_E_fJ=1.8*qshot*1e15))
    lnrange = math.log(128**2)
    temp_ratio = TEMP/(85+273.15)
    hold_t = 1e-6
    return dict(assumptions=dict(T_K=TEMP, exp_slope_V=S, gm_over_ID_per_V=1/S,
            sample_C_fF=c*1e15, row_fanout=fanout, deadline_ns=t*1e9, current_settle_error=eps),
        row_load_pF=load*1e12, row_small_signal_gm_mS=near_gm*1e3,
        row_small_signal_Imin_uA=near_i*1e6, row_exact_fall_Imin_uA=min_i*1e6,
        row_128to1_fall_tau_count=fall_factor, row_1to128_rise_tau_count=rise_factor,
        row_Imax_mA=128*min_i*1e3,
        row_static_min_energy_pJ=1.8*min_i*t*1e12, row_static_max_energy_pJ=1.8*128*min_i*t*1e12,
        row_static_min_energy_per_MAC_fJ=1.8*min_i*t/fanout*1e15,
        row_static_max_energy_per_MAC_fJ=1.8*128*min_i*t/fanout*1e15,
        shared_double_slope_sampling_log_sigma=math.sqrt(var),
        shared_double_slope_sampling_product_CV=math.sqrt(math.expm1(var)),
        shared_double_slope_sampling_product_mean_bias=math.expm1(var/2),
        independent_single_slope_stack_required_C_ratio=4,
        beta_tolerance_for_1percent_product=math.log1p(.01)/lnrange,
        beta_tolerance_mantissa_pair=math.log1p(.01)/math.log(4),
        full_range_worst_error_at_beta_plus_1percent=1-math.exp(-.01*lnrange),
        full_range_worst_error_at_beta_minus_1percent=math.exp(.01*lnrange)-1,
        double_slope_full_operand_span_V=2*S*math.log(128),
        double_slope_mantissa_span_V=2*S*math.log(2),
        stored_27C_voltage_read_85C_beta=temp_ratio,
        stored_27C_voltage_read_85C_min_product_ratio=math.exp((1-temp_ratio)*lnrange),
        ideal_dynamic_reference_cancels_common_T=True,
        drain_factor_error_at_4UT=math.exp(-4),
        drain_VDS_for_0p1percent_at_27C_mV=(K*TEMP/Q)*math.log(1000)*1e3,
        drain_VDS_for_0p1percent_at_85C_mV=(K*(85+273.15)/Q)*math.log(1000)*1e3,
        holder_leakage_pA_for_1percent_1us=eps*S*c/hold_t*1e12,
        regeneration_tau_ps=100, regeneration_sigma_t_ps_for_1percent=.01*100,
        precision=precision,
        scope="Conditional device equations; current costs assume static diode drives full load; Vth term alone is not a PDK Monte Carlo")


def sizing():
    sys.path.insert(0, str(ROOT/"analog/schematics"))
    from sizing.lookup import J_D, ft, gm_gds

    alpha = math.log(100)
    fixed_c, deadline = 200e-15, 100e-9
    rows = []
    for length in (.15, .3, .5, 1.):
        for g in (18., 22., 26.):
            jd, freq = float(J_D(g, length)), float(ft(g, length))
            cap_per_w = g*jd/(2*math.pi*freq)
            floor = alpha*cap_per_w/(g*jd)
            denom = deadline*g*jd-alpha*cap_per_w
            width = alpha*fixed_c/denom if denom > 0 else None
            if width:
                actual = alpha*(fixed_c+cap_per_w*width)/(g*jd*width)
                assert abs(actual/deadline-1) < 1e-14
            rows.append(dict(L_um=length, gm_over_ID=g, JD_nA_per_um=jd*1e9, ft_proxy_MHz=freq/1e6,
                Cgg_proxy_fF_per_um=cap_per_w*1e15, self_gate_settling_proxy_ns=floor*1e9,
                width_fixed_C_um=alpha*fixed_c/(deadline*g*jd), width_one_gate_C_proxy_um=width,
                gm_over_gds=float(gm_gds(g, length))))
    # Matched inverse square-law devices still fail logarithmic multiplication.
    a, b = .001, -.001
    out_log = 2*math.log(math.exp(a/2)+math.exp(b/2)-1)
    assert abs((out_log-a-b)/(a*b)+.5) < 1e-6
    h = math.log(2)/2
    corners = [(a, b) for a in (-h, h) for b in (-h, h)]
    strong_errors = [(math.exp(a/2)+math.exp(b/2)-1)**2/math.exp(a+b)-1 for a, b in corners]
    assert max(abs(v) for v in strong_errors) > .05
    coupled = []
    for cg_over_c in (0., .05, 1.):
        gx, gr, c = 2**-.5, 1., 1.
        cx = cr = cg_over_c*c
        aa = c*(cx+cr)+cx*cr
        bb = gx*(c+cr)+gr*(c+cx)
        tau = (bb+math.sqrt(bb*bb-4*aa*gx*gr))/(2*gx*gr)
        if cg_over_c:
            cm = np.array([[c+cx, -c], [-c, c+cr]])
            eigen_tau = 1/min(np.linalg.eigvals(np.linalg.solve(cm, np.diag([gx, gr]))))
            assert abs(tau/eigen_tau-1) < 1e-13
        else:
            assert abs(tau-(1+math.sqrt(2))) < 1e-14
        coupled.append(dict(grounded_C_each_over_state_C=cg_over_c, tau_over_C_over_Gref=tau))
    paths = [ROOT/"analog/schematics/sizing/lookup.py"] + [
        ROOT/f"analog/schematics/sizing/tables/nfet_L{l:g}.csv" for l in (.15, .3, .5, 1.)]
    return dict(scope="Archived TT27 VDS=.9 lookup, one-Cgg width-load proxy only; NOT tied-diode-node AC capacitance",
        fixed_load_fF=fixed_c*1e15, deadline_ns=deadline*1e9, relative_settle_error=.01, cases=rows,
        coupled_log_reference_poles=coupled,
        square_law_centered_mantissa_max_relative_error=max(abs(v) for v in strong_errors),
        lookup_source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})


def saved_passing_audit():
    """Independently recalculate saved scalar traces, when artifacts are present."""
    records = []
    pattern = "imc_log_charge_stack_*_c600p0_a*_e*_i256p8932070415464_w1p86_s97403*ref1p5.json"
    for path in sorted((ROOT/"build/sim").glob(pattern)):
        r = json.loads(path.read_text())
        wd = Path(r["artifacts"])
        deck = next(wd.glob("*.cir"))
        assert hashlib.sha256(deck.read_bytes()).hexdigest() == r["netlist_sha256"]
        assert hashlib.sha256((wd/"generator_snapshot.py").read_bytes()).hexdigest() == r["source_sha256"]
        text = deck.read_text()
        assert "Voffset vg gate 0" in text and "Cstate vg bottomnode 600.0f" in text
        # Circuit equations use PDK transistors; no behavioral nonlinear source.
        assert not any(line[:1].upper() in ("B", "E", "G") for line in text.splitlines() if line and line[0] != "*")
        raw = np.loadtxt(wd/"trace.csv")
        assert raw.shape[1] in (7, 12)
        data = raw if raw.shape[1] == 7 else np.column_stack([raw[:,0], raw[:,1::2]])
        time, io, power = data[:,0], data[:,5], data[:,6]
        xy = np.array(r["operands"])
        slot, acq, evaluation = (r[k]*1e-6 for k in ("word_us", "acquire_us", "evaluate_us"))
        times = np.arange(len(xy))*slot+acq+evaluation
        samples = np.interp(times, time, io)
        exact = xy.prod(1)
        error = samples/samples[0]/exact-1
        assert np.max(abs(samples-np.array(r["output_current_A"]))) < 1e-17
        windows, energy, read_energy, integrated, long_windows, ratio_extrema = [], [], [], [], [], []
        for i, endpoint in enumerate(times):
            start = endpoint-.1*evaluation
            ts = np.r_[start, time[(time>start)&(time<endpoint)], endpoint]
            ratios = np.interp(ts,time,io)/samples[0]/exact[i]
            windows.append(float(np.max(abs(ratios-1))))
            ratio_extrema.append((float(min(ratios)),float(max(ratios))))
            # Additional fixed 100ns diagnostic ends immediately before the
            # operate switch starts opening at word_end-102ns. No new circuit.
            late_start, late_end = endpoint-2e-9, endpoint+98e-9
            ts = np.r_[late_start,time[(time>late_start)&(time<late_end)],late_end]
            v = np.interp(ts,time,io)
            integrated.append(float(np.trapezoid(v,ts)/100e-9))
            long_windows.append(float(np.max(abs(v/samples[0]/exact[i]-1))))
            a, b = i*slot, (i+1)*slot
            ts = np.r_[a,time[(time>a)&(time<b)],b]
            energy.append(float(np.trapezoid(np.interp(ts,time,power),ts)))
            read_energy.append(float(.9*np.trapezoid(np.interp(ts,time,io),ts)))
        maximum = max(windows[1:])
        integrated_error = np.array(integrated)/integrated[0]/exact-1
        assert abs(maximum-r["read_window_max_relative_error"]) < 1e-10
        assert abs(np.mean(energy[1:])*1e12-r["delivered_mean_evaluation_pJ"]) < 1e-6
        prev = np.vstack([xy[:1],xy[:-1]])
        input_energy = 1.8*r["iref_nA"]*1e-9*(slot*(xy.sum(1)+r["reference_current_ratio"])
            +10e-9*(prev.sum(1)-xy.sum(1)))
        records.append(dict(file=str(path.relative_to(ROOT)), corner=r["corner"], temperature_C=r["temp_C"],
            word_us=r["word_us"], read_window_ns=.1*evaluation*1e9, window_max_relative_error=maximum,
            late_100ns_window_max_relative_error=max(long_windows[1:]),
            late_100ns_current_integral_max_relative_error=float(np.max(abs(integrated_error[1:]))),
            endpoint_relative_RMS=float(np.sqrt(np.mean(error[1:]**2))), repeated_reference_error=float(error[-1]),
            mean_complete_delivery_pJ=float(np.mean(energy[1:])*1e12),
            mean_ideal_input_branches_pJ=float(np.mean(input_energy[1:])*1e12),
            mean_fixed_0p9V_read_port_pJ=float(np.mean(read_energy[1:])*1e12),
            minimum_output_nA=float(min(samples)*1e9),
            calibration_output_nA=float(samples[0]*1e9),
            window_product_ratio_min=min(v[0] for v in ratio_extrema[1:]),
            window_product_ratio_max=max(v[1] for v in ratio_extrema[1:]),
            exp_shot_relative_RMS_100ns=math.sqrt(Q/(min(samples)*100e-9)),
            exp_shot_relative_RMS_read_window=math.sqrt(Q/(min(samples)*.1*evaluation)),
            snapshot_sha256=r["source_sha256"], netlist_sha256=r["netlist_sha256"],
            deterministic_window_pass=maximum<.01))
    reference = next((r for r in records if r["corner"] == "tt" and "_a1p5_e0p1_" in r["file"]
        and "_dt0p2_" in r["file"]), None)
    if reference:
        for r in records:
            ratio = r["calibration_output_nA"]/reference["calibration_output_nA"]
            r["frozen_TT_gain_window_max_relative_error"] = max(abs(ratio*r[k]-1) for k in
                ("window_product_ratio_min", "window_product_ratio_max"))
    return dict(scope="Saved-trace arithmetic/hash audit only; conditional single-branch shot model, no new SPICE/noise/PEX",
        frozen_TT_gain_reference=reference["file"] if reference else None, records=records)


def main():
    result = dict(status="VERIFIED", scope="Ideal algebra and explicitly conditional numerical models only",
        seed=SEED, arithmetic=arithmetic(), cancellation=cancellation(), quantization=quantization(), budgets=budgets(), sizing=sizing(),
        saved_passing_audit=saved_passing_audit(),
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    out = ROOT/"build/research/imc_log_pipeline_analysis.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2)+"\n")
    print("PASS log/charge identities and rejection controls; signed zeros; covariance; conditional sizing/noise budgets")
    print(out)
    print(json.dumps({k: result[k] for k in ("arithmetic", "quantization", "budgets")}, indent=2))


if __name__ == "__main__":
    main()
