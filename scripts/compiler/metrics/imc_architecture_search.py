"""Constrained IMC architecture screening and inverse design budgets.

No device simulation and no deployment compiler mutation. Run in the existing
NumPy environment; frozen compiler artifacts supply operand activity only.
All rates are analytical ceilings, not simulated generated-token throughput.
"""
import hashlib
import itertools
import json
import math
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "build/research/imc_architecture_search"
NAMES = ("attn_q", "attn_k", "attn_v", "attn_o", "ffn_gate", "ffn_up", "ffn_down")
KB = 1.380649e-23
VDD = 1.8
TQ = 10e-9
CU_FF = 0.15
DENSITY_FF_UM2 = 2.0
I_COLUMN = 12e-6
E_INT_PJ = 820.83
E_CONV_PJ = 1061.59 + 283.51
E_DIGITAL_PJ = 24.6
T_CONV_OLD = 1.26e-6
# Residuals reproduce the old measured phase totals. Their extrapolation is
# explicitly a coarse model: clock, reference and activity terms are not split.
E_INT_RESIDUAL = E_INT_PJ - 17 * I_COLUMN * VDD * 160 * TQ * 1e12
E_ADC_RESIDUAL = E_CONV_PJ / 34 - I_COLUMN * VDD * T_CONV_OLD * 1e12
SYSTEM = dict(dies=8, die_mm2=400, usable_fraction=0.7, power_w=400,
              external_Bps=1e12, fabric_Bps=32e12, attention_MACps=1e12,
              kv_capacity_bytes=32 * 2**30)
# Llama 3 Table 3 dimensions; its rounded 128,000 vocabulary is intentional.
MODELS = {"8B-class": dict(layers=32, d=4096, f=14336, hq=32, hkv=8, vocab=128000),
          "70B-class": dict(layers=80, d=8192, f=28672, hq=64, hkv=8, vocab=128000)}
ENCODINGS = {"weighted_nibbles": (2, 144), "equal_nibbles": (2, 32),
             "binary_digits": (8, 8)}


def weight_digit_units(w, wbits):
    return sum((w >> b) & ((1 << wbits) - 1) for b in range(0, 4, wbits))


def activity():
    """Actual absolute capacitor-code transfers, not an assumed sparsity gain."""
    totals = {(enc, wb): 0.0 for enc in ENCODINGS for wb in (2, 4)}
    denomin = 0
    weight_sum = 0.0
    digit_sum = {wb: 0.0 for wb in (2, 4)}
    fingerprints = {}
    per_tensor = []
    for name in NAMES:
        paths = [ROOT / f"scripts/compiler/out/programming/{name}.npz",
                 ROOT / f"scripts/compiler/out/acts/{name}.npz"]
        for p in paths:
            fingerprints[str(p.relative_to(ROOT))] = hashlib.sha256(p.read_bytes()).hexdigest()
        with np.load(paths[0]) as z:
            w = np.abs(z["Wq"].astype(np.int64))
        with np.load(paths[1]) as z:
            x = np.abs(z["xq"][:6].astype(np.int64))
        reps = {"weighted_nibbles": x,
                "equal_nibbles": x % 16 + x // 16,
                "binary_digits": sum((x >> b) & 1 for b in range(8))}
        denom = x.shape[0] * w.size
        denomin += denom
        weight_sum += x.shape[0] * float(w.sum())
        for wb in digit_sum:
            digit_sum[wb] += x.shape[0] * float(weight_digit_units(w, wb).sum())
        per_tensor.append({"tensor": name, "mean_abs_weight": float(w.mean()),
                           "mean_repetitions": {k: float(v.mean()) for k, v in reps.items()}})
        for enc, wb in totals:
            wd = weight_digit_units(w, wb)
            totals[enc, wb] += float(np.sum(reps[enc] @ wd.T))
    averaged = {f"{enc}/w{wb}": val / denomin for (enc, wb), val in totals.items()}
    averaged["mean_abs_weight"] = weight_sum / denomin
    averaged.update({f"mean_digit_units/w{wb}": total / denomin for wb, total in digit_sum.items()})
    return averaged, per_tensor, fingerprints


def macro(rows, cols, share, bits, encoding, wbits, activities, old=False):
    digits, cycles = ENCODINGS[encoding]
    slices = math.ceil(4 / wbits)
    physical_cols = cols + 1  # one checksum; its representability is a separate gate
    adcs = math.ceil(physical_cols / share)
    rounds = math.ceil(physical_cols / adcs)
    code_cap = ((1 << wbits) - 1) * CU_FF
    # Coherent full-scale row growth, not an unqualified sqrt(N) signal model.
    ci = max(200 * rows / 16 * code_cap / (15 * CU_FF),
             12 * KB * 300.15 * 4**bits / 0.25**2 * 1e15)
    cp = 500 + rows * 2 * (4 + code_cap)
    # (A/beta + Cp)/gm. A is back-solved to the 30-ns/200-fF/700-fF anchor.
    a_ff = (30e-9 * 72e-6 * 1e15 - 700) * 200 / 900
    tau = (a_ff * (ci + cp) / ci + cp) * 1e-15 / 72e-6
    cadence = math.ceil(2 * tau / TQ - 1e-10) * TQ
    fine = (bits - 4) / 4 * 240e-9 * tau / 30e-9
    conv = T_CONV_OLD if old else 9 * cadence + fine
    integrate = slices * (cycles + 8 * digits) * TQ
    latency = integrate + slices * digits * rounds * conv
    adc_events = physical_cols * digits * slices
    int_static = physical_cols * I_COLUMN * VDD * integrate * 1e12
    transfer_ratio = activities[f"{encoding}/w{wbits}"] / activities["weighted_nibbles/w4"]
    int_dynamic = E_INT_RESIDUAL * rows / 16 * physical_cols / 17 * transfer_ratio
    # Waiting column integrators remain biased. Converter sharing cannot
    # silently assume ideal disconnect/hold or erase conversion services.
    conv_static = physical_cols * I_COLUMN * VDD * (latency - integrate) * 1e12
    conv_dynamic = adc_events * E_ADC_RESIDUAL * bits / 8
    digital = E_DIGITAL_PJ * cols / 16 * slices * digits / 2
    energy = int_static + int_dynamic + conv_static + conv_dynamic + digital
    # Programmable worst-case two-bank reservation, including top ballast.
    bank_ff = slices * rows * physical_cols * 2 * (4 + code_cap)
    col_ff = physical_cols * (500 + ci + (200 if share > 1 else 0))
    # Two 5-pF local fine-reference reservoirs per ADC, from current generator.
    adc_ff = adcs * 10000
    cap_area = (bank_ff + col_ff + adc_ff) / DENSITY_FF_UM2
    digital_area = 24712 * cols / 16
    # FEOL/BEOL can overlap: max is a necessary lower bound, not their sum.
    area_lower = max(cap_area, digital_area) / 1e6
    # Total span is +/-4 sigma at the original 16-row W4/200-fF point.
    # Track actual Cint, including the thermal floor, rather than granting
    # larger capacitors free signal amplitude. Per-slice normalized signal
    # scales with digit range; reconstruction covariance remains unvalidated.
    gain = code_cap / (15 * CU_FF) * 200 / ci
    q_snr = (10 * math.log10(12 * 4**bits / 64) + 10 * math.log10(rows / 16)
             + 20 * math.log10(gain))
    target = 36.74  # sensitivity study point; not a universal quality criterion
    residual_budget = 10**(-target / 10) - 10**(-q_snr / 10)
    required_analog = -10 * math.log10(residual_budget) if residual_budget > 0 else None
    return dict(id=f"r{rows}c{cols}q{share}b{bits}_{encoding}_w{wbits}", rows=rows,
                cols=cols, share=share, bits=bits, encoding=encoding, weight_bits_per_slice=wbits,
                slices=slices, adcs=adcs, rounds=rounds, adc_events=adc_events,
                integration_ns=integrate * 1e9, latency_ns=latency * 1e9,
                conversion_ns=conv * 1e9, energy_pj=energy,
                energy_fj_per_MAC=energy * 1000 / (rows * cols),
                component_pj=dict(integrator=int_static, switched_residual=int_dynamic,
                                  conversion_hold=conv_static, conversion_residual=conv_dynamic,
                                  digital=digital),
                cint_ff=ci, capacitor_plate_area_um2=cap_area,
                macro_area_lower_mm2=area_lower,
                area_um2_per_weight_lower=area_lower * 1e6 / (rows * cols),
                config_bits_lower=4 * rows * cols,
                independent_differential_config_bits=8 * rows * cols,
                quant_snr_screen_db=q_snr, required_analog_snr_db=required_analog,
                necessary_quant_gate=residual_budget > 0,
                quality_verified=False, layout_verified=False)


def shapes(model):
    d, f, kv = model["d"], model["f"], model["d"] // model["hq"] * model["hkv"]
    return [(d, d), (d, kv), (d, kv), (d, d), (d, f), (d, f), (f, d)]


def model_counts(m, p):
    layer_shapes = shapes(m)
    matrices = [(a, b, m["layers"]) for a, b in layer_shapes] + [(m["d"], m["vocab"], 1)]
    tiles = macs = fabric = 0
    for a, b, repeat in matrices:
        nr, nc = math.ceil(a / p["rows"]), math.ceil(b / p["cols"])
        tiles += repeat * nr * nc
        macs += repeat * a * b
        # Multicast leaf input bytes + row-partial reduction leaf bytes.
        # This aggregate is not an off-chip traffic count or a bisection bound.
        fabric += repeat * (a * nc + nr * b * 4)
    embedding_tiles = math.ceil(m["d"] / p["rows"]) * math.ceil(m["vocab"] / p["cols"])
    return dict(tiles=tiles, macs=macs, stored_tiles=tiles + embedding_tiles,
                stored_weights=macs + m["d"] * m["vocab"], fabric_bytes=fabric)


def system_point(m, p, context, concurrency, kv_mode):
    c = model_counts(m, p)
    dh = m["d"] // m["hq"]
    kv_bits = 4 if kv_mode == "analog4_shadow" else 16
    kv_one = 2 * m["layers"] * m["hkv"] * dh * context * kv_bits / 8
    kv_total = kv_one * concurrency
    refresh = -0.027 * math.log(1 - 1 / 16)
    refresh_Bps = kv_total / refresh if kv_mode == "analog4_shadow" else 0
    # Full context banks, parallel K/V and width, one column write per 150 ns.
    refresh_duty = context * 150e-9 / refresh if kv_mode == "analog4_shadow" else 0
    attention = 2 * m["layers"] * m["hq"] * dh * context
    weight_latency = (4 * m["layers"] + 1) * p["latency_ns"] * 1e-9
    latency = weight_latency + attention / SYSTEM["attention_MACps"]
    energy = c["tiles"] * p["energy_pj"] * 1e-12
    # All excluded terms are nonnegative: energy/rates remain optimistic.
    rates = dict(weight_stage=1e9 / p["latency_ns"], concurrency=concurrency / latency,
                 attention=SYSTEM["attention_MACps"] / attention,
                 power=SYSTEM["power_w"] / energy,
                 fabric=SYSTEM["fabric_Bps"] / c["fabric_bytes"])
    if kv_mode == "digital16":
        rates["kv_reads"] = SYSTEM["external_Bps"] / kv_one
    else:
        rates["kv_write"] = concurrency * max(0, 1 - refresh_duty) / 150e-9
        rates["shadow_refresh"] = max(0, SYSTEM["external_Bps"] - refresh_Bps) / (kv_one / context)
    area = c["stored_tiles"] * p["macro_area_lower_mm2"]
    die_area = SYSTEM["die_mm2"] * SYSTEM["usable_fraction"]
    capacity_fit = area <= SYSTEM["dies"] * die_area
    rate = min(rates.values())
    binding = min(rates, key=rates.get)
    nonmemory = min(rates[k] for k in rates if k not in ("kv_reads", "kv_write", "shadow_refresh", "fabric"))
    memory_margin = (min([v for k, v in rates.items() if k in ("kv_reads", "kv_write", "shadow_refresh", "fabric")])
                     / nonmemory)
    reasons = []
    if not capacity_fit:
        reasons.append("resident_weight_area_lower_bound")
    if kv_total > SYSTEM["kv_capacity_bytes"]:
        reasons.append("KV_capacity")
    if refresh_duty >= 1:
        reasons.append("KV_refresh_write_occupancy")
    if refresh_Bps >= SYSTEM["external_Bps"]:
        reasons.append("KV_shadow_bandwidth")
    if not p["necessary_quant_gate"]:
        reasons.append("quantization_screen")
    if memory_margin < 1.2:
        reasons.append("memory_service_margin")
    return dict(macro=p["id"], context=context, concurrency=concurrency, kv_mode=kv_mode,
                **c, resident_dies_lower=math.ceil(area / die_area), resident_area_lower_mm2=area,
                conditional_rate_ceiling_toks=rate, estimated_mvm_energy_J=energy,
                conditional_mvm_tokJ=1 / energy,
                conditional_token_latency_ms=latency * 1e3, rates=rates, binding=binding,
                KV_bytes=kv_total, refresh_Bps=refresh_Bps, refresh_duty=refresh_duty,
                memory_service_margin=memory_margin, necessary_failures=reasons,
                modeled_memory_clear=memory_margin >= 1.2 and not reasons,
                full_compute_bound_verified=False)


def pareto(points, objectives):
    """Small bounded O(n^2) screen; all objective coordinates are minimized."""
    return [p for p in points if not any(
        all(q[k] <= p[k] for k in objectives) and any(q[k] < p[k] for k in objectives)
        for q in points)]


def inverse_budgets(activities):
    rows = []
    for eta, r, enc, wb, cu, voltage, other in itertools.product(
            (8.33, 40.2, 100, 120, 250), (16, 64, 128, 256), ENCODINGS, (2, 4),
            (0.15, 4.0), (1.8, 0.4), (0.0, 10.0)):
        digits = ENCODINGS[enc][0]
        slices = math.ceil(4 / wb)
        # Signal-capacitor CV^2 only. No ballast, gates, SRAM, clock, ADC, links.
        switch_fj = cu * voltage**2 * activities[f"{enc}/w{wb}"]
        adc_per_mac = digits * slices * 65 / (r * 64)
        budget = 2000 / eta - switch_fj - other
        rows.append(dict(target_TOPSW=eta, rows=r, cols=64, encoding=enc,
                         weight_bits_per_slice=wb, unit_cap_ff=cu, voltage_swing=voltage,
                         other_fj_per_MAC=other, switch_only_fj_per_MAC=switch_fj,
                         ADC_pj_max=max(0, budget / adc_per_mac / 1000),
                         rows_min_for_1pJ_ADC=(1000 * digits * slices * 65 / 64 / budget
                                              if budget > 0 else None),
                         max_code_weighted_transfers_with_free_ADC=max(0, (2000 / eta - other) / (cu * voltage**2)),
                         max_mean_input_repetitions_if_uncorrelated=max(0, (2000 / eta - other)
                             / (cu * voltage**2 * activities[f"mean_digit_units/w{wb}"])),
                         possible_even_with_free_ADC=budget > 0))
    return rows


def target_system_ceilings():
    """Conditional target arithmetic, not an achieved package or W8 macro."""
    records = []
    for name, m in MODELS.items():
        c = model_counts(m, dict(rows=128, cols=8))
        context = 4096
        attention = 2 * m["layers"] * m["d"] * context
        kv_one = 2 * m["layers"] * m["hkv"] * (m["d"] // m["hq"]) * context * 2
        # Explicitly serialized two-W4-plane W8 timing requirement; the second
        # plane's actual transfer, energy and ADC remain uncharacterized.
        service_s = 2 * 424e-9
        latency_s = (4 * m["layers"] + 1) * service_s + attention / SYSTEM["attention_MACps"]
        for eta in (100, 250):
            energy = c["macs"] * 2000 / eta * 1e-15
            for concurrency in (1, 64):
                rates = dict(power=SYSTEM["power_w"] / energy,
                    weight_stage=1/service_s, concurrency=concurrency/latency_s,
                    attention=SYSTEM["attention_MACps"]/attention,
                    fabric=SYSTEM["fabric_Bps"]/c["fabric_bytes"],
                    KV_reads=SYSTEM["external_Bps"]/kv_one)
                records.append(dict(model=name, target_TOPSW=eta, **c,
                    logical_MAC_fJ_target=2000/eta,
                    context=context, concurrency=concurrency,
                    target_MVM_energy_J=energy, ideal_MVM_tokJ=1/energy,
                    power_only_toks=rates["power"], conditional_rate_toks=min(rates.values()),
                    binding=min(rates,key=rates.get), rates=rates,
                    KV_bytes=kv_one*concurrency,
                    KV_capacity_fits=kv_one*concurrency<=SYSTEM["kv_capacity_bytes"],
                    resident_weight_capacity_verified=False,
                    scope="targets include all W8 weight-engine work, including both coefficient slices; rates assume an unvalidated 848-ns W8 service, resident independent resources and existing scenario capacities; attention/KV/nonlinear/link/leakage energy is unknown, so ideal_MVM_tokJ is not system tok/J"))
    return records


def requested_rate_budgets():
    """Invert resource requirements; no assumption of a 1-TMAC/s attention engine."""
    records = []
    for name, m in MODELS.items():
        c = model_counts(m, dict(rows=128, cols=8))
        for context, rate in itertools.product((4096, 32768), (10000, 100000, 500000)):
            attention = 2 * m["layers"] * m["d"] * context
            kv_values = 2 * m["layers"] * m["hkv"] * (m["d"] // m["hq"]) * context
            weight_power = {str(eta): c["macs"] * (2000/eta) * 1e-15 * rate for eta in (100, 250)}
            remaining = {eta: SYSTEM["power_w"] - power for eta, power in weight_power.items()}
            records.append(dict(model=name, context=context, requested_toks=rate,
                weight_MACs_per_token=c["macs"], attention_MACs_per_token=attention,
                required_attention_TMACps=attention*rate/1e12,
                KV_read_service_TBps={str(bits): kv_values*bits/8*rate/1e12 for bits in (16, 4)},
                KV_capacity_GiB={f"bits{bits}_B{batch}": kv_values*bits/8*batch/2**30
                                 for bits, batch in itertools.product((16, 4), (1, 64))},
                target_weight_power_W=weight_power, remaining_400W_for_all_other_work=remaining,
                max_attention_fJ_MAC_if_all_remaining_power={eta: max(0, power)/(attention*rate)*1e15
                    for eta, power in remaining.items()},
                max_KV_pJ_bit_if_all_remaining_power={f"TOPSW{eta}_bits{bits}": max(0, power)/(kv_values*bits*rate)*1e12
                    for (eta,power), bits in itertools.product(remaining.items(), (16,4))},
                max_weight_stage_ns_with_zero_attention_latency={f"B{batch}":
                    min(1/rate, batch/(rate*(4*m["layers"]+1)))*1e9 for batch in (1,64)},
                layout_and_full_compute_bound_verified=False))
    for p in records:
        assert math.isclose(p["KV_read_service_TBps"]["16"], 4*p["KV_read_service_TBps"]["4"])
        assert math.isclose(p["KV_capacity_GiB"]["bits16_B64"], 64*p["KV_capacity_GiB"]["bits16_B1"])
        assert math.isclose(p["target_weight_power_W"]["100"], 2.5*p["target_weight_power_W"]["250"])
        assert all(math.isclose(power+p["remaining_400W_for_all_other_work"][eta], 400)
                   for eta, power in p["target_weight_power_W"].items())
    return records


def checks(acts):
    assert weight_digit_units(7, 2) == 4 and weight_digit_units(7, 4) == 7
    assert acts["mean_digit_units/w2"] < acts["mean_digit_units/w4"] == acts["mean_abs_weight"]
    p = macro(16, 16, 1, 8, "weighted_nibbles", 4, acts, old=True)
    assert abs(p["energy_pj"] - 2190.53) < 1e-6
    assert abs(p["latency_ns"] - 4120) < 1e-6
    q = macro(16, 16, 4, 8, "weighted_nibbles", 4, acts, old=True)
    assert p["adc_events"] == q["adc_events"] == 34
    assert q["adcs"] < p["adcs"] and q["latency_ns"] > p["latency_ns"]
    assert q["energy_pj"] > p["energy_pj"]
    m = MODELS["8B-class"]
    a = system_point(m, p, 4096, 1, "digital16")
    b = system_point(m, p, 4096, 64, "digital16")
    assert a["macs"] == b["macs"] and a["tiles"] == b["tiles"]
    assert b["KV_bytes"] == 64 * a["KV_bytes"]
    assert a["rates"]["weight_stage"] == b["rates"]["weight_stage"]
    assert a["resident_dies_lower"] > 8
    k = system_point(m, p, 32768, 1, "analog4_shadow")
    assert k["refresh_duty"] > 1 and "KV_refresh_write_occupancy" in k["necessary_failures"]
    frontier = pareto([dict(x=1,y=2),dict(x=2,y=1),dict(x=2,y=2)], ("x","y"))
    assert len(frontier) == 2


def main():
    acts, tensor_activity, fingerprints = activity()
    checks(acts)
    macros = [macro(*args, acts) for args in itertools.product(
        (16, 32, 64, 128, 256), (16, 64, 128), (1, 4, 8), (6, 8, 10), ENCODINGS, (2, 4))]
    valid_quant = [p for p in macros if p["necessary_quant_gate"]]
    frontier = pareto(valid_quant, ("energy_fj_per_MAC", "latency_ns", "area_um2_per_weight_lower"))
    systems = []
    for name, m in MODELS.items():
        for p, context, concurrency, kv_mode in itertools.product(
                macros, (4096, 32768), (1, 64), ("digital16", "analog4_shadow")):
            systems.append(dict(model=name, **system_point(m, p, context, concurrency, kv_mode)))
    OUT.mkdir(parents=True, exist_ok=True)
    result = dict(scope="analytical necessary-condition screen; no validated chip frontier",
                  energy_scope="coarse conditional extrapolation; omitted positive terms do not make uncertain included terms rigorous lower bounds",
                  system_budgets=SYSTEM, models=MODELS, activity=acts,
                  tensor_activity=tensor_activity, fingerprints=fingerprints,
                  macros=macros, macro_necessary_quant_frontier=frontier,
                  systems=systems, inverse_budgets=inverse_budgets(acts),
                  validated_feasible_count=sum(p["quality_verified"] and p["layout_verified"]
                                               for p in macros), checks="PASS")
    result["inverse_residency"] = []
    for name, m in MODELS.items():
        count = model_counts(m, macros[0])["stored_weights"]
        area_per_weight = SYSTEM["dies"] * SYSTEM["die_mm2"] * SYSTEM["usable_fraction"] * 1e6 / count
        cap_per_weight = area_per_weight * DENSITY_FF_UM2
        result["inverse_residency"].append(dict(model=name, stored_weights=count,
            max_um2_per_weight=area_per_weight, max_cap_ff_per_weight=cap_per_weight,
            min_4fF_cap_sharing_in_SRAM_bits=4 * 4 / cap_per_weight,
            min_4fF_cap_sharing_in_SRAM_bits_W8=8 * 4 / cap_per_weight))
    result["W8_requirements"] = dict(
        physical_W4_planes=2, ADC_services_vs_W4=2,
        shared_periphery_latency_multiplier=2,
        independent_periphery_instances_multiplier=2,
        encoded_weight_bits=8, independent_differential_config_bits=16,
        energy_prediction=None,
        reason="W8 digit activity and actual slice-combine circuit must be characterized; W4 energy cannot simply be reused")
    result["target_system_ceilings"] = target_system_ceilings()
    result["requested_rate_budgets"] = requested_rate_budgets()
    result["requested_rate_scope"] = (
        "Necessary resource allocations at specified aggregate decode rates, not achieved throughput. "
        "KV service assumes ideal GQA reuse and one K/V read per token; aggregate at memory owners, not necessarily off-chip. "
        "Packed4-bit KV quality, metadata, refresh, new writes, softmax, links and leakage are unpriced. "
        "Weight power uses100/250-TOPSW complete-weight-engine allocations; whole-chip targets additionally require all other work. "
        "Maximum attention and KV energy allowances separately assign ALL residual power and cannot both be consumed.")
    for p in result["target_system_ceilings"]:
        assert math.isclose(p["target_MVM_energy_J"] * p["ideal_MVM_tokJ"], 1)
        assert p["conditional_rate_toks"] <= p["power_only_toks"]
    result["physical_radix_budget_scope"] = (
        "128x8 nominal W4 replay anchors: build/sim/imc_sizing_research.json large_reset_repair and large_dynamic_accumulator[0]; "
        "4-fF units, 0.42-um row/3.36-um matched-reset/6.72-um share TGs; "
        "zero physical ADC conversions. W8 duplicate-schedule cost is an assumption, not a measured W8 energy. "
        "Budgets omit checksum interface energy, references, SRAM, control, transport and leakage.")
    result["physical_radix_inverse_budgets"] = []
    anchors = (("fixed8", 5.140272329887878, 424), ("dynamic_7_6_5", 4.4999050551099415, 318))
    for anchor, logical_bits, eta, checksum in itertools.product(anchors, (4, 8), (100, 250), (False, True)):
        schedule, measured_w4_fj, measured_ns = anchor
        slices = logical_bits // 4
        interface_fj = slices * measured_w4_fj
        residual_fj = 2000/eta - interface_fj
        events_per_mac = slices * (9/8 if checksum else 1) / 128
        result["physical_radix_inverse_budgets"].append(dict(
            schedule=schedule, interface_service_ns=measured_ns*slices,
            logical_weight_bits=logical_bits, physical_slices=slices,
            interface_fj_per_logical_MAC=interface_fj, target_TOPSW=eta,
            checksum_conversion=checksum, ADC_max_pj=(residual_fj/events_per_mac/1000
                if residual_fj > 0 else None), possible_before_other_costs=residual_fj>0))
    result["capacitor_reuse_requirements"] = [dict(
        storage_bits_per_cap=s, logical_weight_bits=wb,
        capacitor_ff_per_weight=4 * wb / s,
        coefficient_groups_per_cap=s / wb,
        service_condition="sum of selected bank request rates times their plane service times must be below one; capacity sharing does not add compute ports")
        for s, wb in itertools.product((9, 32, 64), (4, 8))]
    (OUT / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    short = dict(macros=len(macros), systems=len(systems), frontier=len(frontier),
                 necessary_condition_passes=sum(not p["necessary_failures"] for p in systems),
                 lowest_energy_macro=min(valid_quant,key=lambda p:p["energy_fj_per_MAC"]),
                 activity=acts)
    (OUT / "summary.json").write_text(json.dumps(short, indent=2) + "\n")
    print("PASS", json.dumps(short, indent=2))


if __name__ == "__main__":
    main()
