"""Fast, evidence-labelled IMC system testbench; no SPICE rerun.

Run with the repo's Nix Python environment. Outputs stay in build/research.
The default composes separate W4 array and SAR fixtures into a CONDITIONAL
W8 two-bank macro, with serial bank service. Unknown costs remain unknown.
This is a schedule/cost model, not an integrated transistor or token simulation.
"""
import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
from compiler.metrics.imc_architecture_search import MODELS, model_counts, shapes
DEFAULT = {
    "model": "8B-class", "weight_bits": 8, "activation_bits": 8,
    "context": 2048, "batch": 1, "kv_bits": 16,
    "physical_macros": 1, "adcs_per_macro": 8, "weight_mode": "streamed",
    "array_artifact": "build/sim/imc_sizing_research.json",
    "adc_artifact": "build/sim/imc_null_sar_vcm_refs2_calibrated_suite.json",
    "adc_regression_artifacts": [
        f"build/sim/imc_null_sar_vcm_refs2_calibrated_seed{seed}_{corner}.json"
        for seed in (9952, 9953) for corner in ("tt", "ss")],
    "extra_macro_pj": None, "extra_macro_ns": None,
    "weight_programming_pj_per_byte": None, "weight_programming_Bps": None,
    "external_memory_pj_per_byte": None, "external_Bps": None,
    "fabric_pj_per_byte": None, "fabric_Bps": None,
    "attention_fj_per_mac": None, "attention_MACps": None,
    "nonlinear_pj_per_token": None, "nonlinear_ns_per_token": None,
    "startup_pj": None, "startup_ns": None,
    "leakage_w": None, "maintenance_w": None, "power_limit_w": None,
    "weight_capacity_bytes": None, "kv_capacity_bytes": None,
    "model_quality_pass": None,
}
SOURCE_URL = "https://www.mythic.ai/m-1"
MYTHIC_SOURCES = {
    "product_brief": "https://mythic.ai/wp-content/uploads/2022/03/M1076-AMP-Product-Brief-v1.0-1.pdf",
    "cto_talk": "https://events.vtools.ieee.org/m/307323",
    "isscc_press_kit": "https://www.isscc.org/s/ISSCC2022PressKit.pdf",
    "analog_charge_patent": "https://patents.google.com/patent/US10255205B1/en",
}
VALIDATION_STIMULUS_SHA256 = "06b511201b35093edf36343247d3ee7576bedb1c82064f6b8c41f2f912a20ed8"


def metrics(macs, seconds, joules, tokens=None):
    """All four metrics use exactly the same work/time/energy boundary."""
    if not all(math.isfinite(v) and v > 0 for v in (macs, seconds, joules)):
        raise ValueError("MACs, duration and energy must be finite and positive")
    result = dict(TOPS=2 * macs / seconds / 1e12, power_W=joules / seconds,
                  TOPS_per_W=2 * macs / joules / 1e12,
                  fJ_per_MAC=joules / macs * 1e15)
    if tokens is not None:
        if not math.isfinite(tokens) or tokens <= 0:
            raise ValueError("Token count must be finite and positive")
        result.update(tok_per_s=tokens / seconds, tok_per_J=tokens / joules)
    return result


def read_artifact(name):
    path = ROOT / name
    data = path.read_bytes()
    return json.loads(data), dict(path=str(path), sha256=hashlib.sha256(data).hexdigest())


def full_cycles(r):
    return (r["warmup_frames"] == 1 and r["closing_frames"] == 1
            and r["simulated_frames"] == r["frames"] + 2)


def load_evidence(config):
    array, array_source = read_artifact(config["array_artifact"])
    adc, adc_source = read_artifact(config["adc_artifact"])
    sources = [array_source, adc_source]
    regression_cases, regression_checks = set(), []
    for name in config["adc_regression_artifacts"]:
        if not (ROOT / name).exists():
            regression_checks.append(dict(path=name, status="MISSING"))
            continue
        reg, source = read_artifact(name)
        sources.append(source)
        if reg["config"] != adc["config"]:
            raise ValueError(f"Regression uses a different circuit configuration: {name}")
        checks = []
        for c in reg["cases"]:
            r = c["result"]
            if (c["label"] != "shared_reference" or r["columns"] != 8 or r["frames"] != 3
                    or r["physical_decisions"] != 10 or r["bridge_error"] != 0
                    or not c["expected_accuracy_pass"]
                    or not full_cycles(r)
                    or r["temp_C"] != {"tt": 27, "ss": 85}.get(r["corner"])):
                raise ValueError(f"Unexpected regression stimulus dimensions: {name}")
            regression_cases.add((reg["random_seed"], r["corner"]))
            checks.append(bool(r["numerical_accuracy_pass"] and r["feedback_pass"]))
        regression_checks.append(dict(path=name, status="PASS" if checks and all(checks) else "FAIL"))
    required = {(seed, corner) for seed in (9952, 9953) for corner in ("tt", "ss")}
    regression_status = ("FAIL" if any(r["status"] == "FAIL" for r in regression_checks)
                         else "PASS" if required <= regression_cases else "INCOMPLETE")
    records = []
    # The declared twelve-input validation is a stable comparison set. Do not
    # choose the smallest energy across stimuli or hide a failing suite member.
    cases = adc["cases"]
    expected_cases = {
        ("validation", "tt", 27, 1, 12, 0, True),
        ("validation", "ss", 85, 1, 12, 0, True),
        ("shared_reference", "tt", 27, 8, 3, 0, True),
        ("shared_reference", "ss", 85, 8, 3, 0, True),
        ("bad_bridge", "tt", 27, 1, 2, .3, False),
    }
    observed_cases = {(c["label"], c["result"]["corner"], c["result"]["temp_C"],
                       c["result"]["columns"], c["result"]["frames"],
                       c["result"]["bridge_error"], c["expected_accuracy_pass"]) for c in cases}
    suite_complete = (len(cases) == 5 and observed_cases == expected_cases
                      and all(c["result"]["physical_decisions"] == 10 for c in cases))
    suite_pass = all(c["result"]["numerical_accuracy_pass"] == c["expected_accuracy_pass"]
                     and c["result"]["feedback_pass"] and full_cycles(c["result"]) for c in cases)
    for corner, temp in (("tt", 27), ("ss", 85)):
        a = next(r for r in array["share_settling_repair"] if r["corner"] == corner)
        matches = [c["result"] for c in cases if c["label"] == "validation"
                   and c["result"]["corner"] == corner]
        if len(matches) != 1:
            raise ValueError(f"Expected one declared {corner} ADC validation case")
        d = matches[0]
        if d["columns"] != 1 or d["frames"] != 12 or d["physical_decisions"] != 10 or d["bridge_error"] != 0:
            raise ValueError("Expected the twelve-input ten-decision ADC comparison fixture")
        if d["stimulus_sha256"] != VALIDATION_STIMULUS_SHA256:
            raise ValueError("ADC validation does not use the frozen twelve-input stimulus")
        if not full_cycles(d):
            raise ValueError("ADC full-cycle boundary requires a warmup and closing frame")
        if a["temp_C"] != temp or d["temp_C"] != temp:
            raise ValueError("Array/ADC PVT mismatch")
        if (a["rows"], a["columns"]) != (128, 8) or not a["accumulate"]:
            raise ValueError("This adapter requires the 128x8 retained-charge fixture")
        ar = a["accumulator_replay"]
        if ar["physical_ADC_conversions"] != 0:
            raise ValueError("Array energy now includes ADCs: avoid counting them twice")
        energy = d["energy"]["d"]  # positive source delivery, not signed net energy
        delivered = [energy["total_fJ_per_conversion"]] + [v for phase in energy.values()
                     if isinstance(phase, dict) for v in phase.values()]
        if (energy["total_fJ_per_conversion"] <= 0 or
                any(not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in delivered)):
            raise ValueError("Positive-delivery energy must be finite and nonnegative")
        phases = [v["total_fJ_per_conversion"] for v in energy.values() if isinstance(v, dict)]
        if not math.isclose(sum(phases), energy["total_fJ_per_conversion"], rel_tol=1e-10):
            raise ValueError("ADC phase energy does not sum to the full cycle")
        records.append(dict(
            corner=corner, temp_C=temp, rows=128, cols=8,
            array_fj_per_mac=a["A8_interface_fJ_per_MAC"],
            array_ns=a["A8_interface_ns"],
            array_plane_ns=a["cycle_ns"],
            array_accuracy_pass=bool(a["transfer_pass"] and a["accumulator_transfer_pass"]
                                    and ar["rms_error_MAC"] < .25 and ar["max_error_MAC"] < 1),
            adc_pj=energy["total_fJ_per_conversion"] / 1000,
            adc_ns=d["whole_cycle_ns"], adc_max_error_LSB=d["max_raw_error_LSB"],
            adc_accuracy_pass=bool(d["numerical_accuracy_pass"] and d["feedback_pass"]),
            adc_development_suite=("PASS" if suite_pass else "FAIL") if suite_complete else "INCOMPLETE",
            adc_regression_status=regression_status, adc_regression_checks=regression_checks,
            adc_stimulus_sha256=d["stimulus_sha256"],
            adc_energy_boundary=d["energy_boundary"],
            array_energy_boundary=array["energy_boundary"],
            array_evidence=a["artifact"], adc_evidence=d["artifact"],
        ))
    return records, sources


def validate_config(c):
    if set(c) != set(DEFAULT):
        raise ValueError(f"Unknown/missing configuration keys: {set(c) ^ set(DEFAULT)}")
    if c["model"] not in MODELS or c["weight_mode"] not in ("resident", "streamed"):
        raise ValueError("Unknown model or weight mode")
    if c["weight_bits"] not in (4, 8) or c["activation_bits"] != 8:
        raise ValueError("Only W4A8 evidence / W8A8 two-bank projection is supported")
    for key in ("physical_macros", "adcs_per_macro", "context", "batch", "kv_bits"):
        if type(c[key]) is not int or c[key] <= 0:
            raise ValueError(f"{key} must be a positive integer")
    if c["adcs_per_macro"] > 8:
        raise ValueError("At most eight ADCs serve this eight-column macro")
    if not isinstance(c["adc_regression_artifacts"], list) or not all(isinstance(s, str) for s in c["adc_regression_artifacts"]):
        raise ValueError("adc_regression_artifacts must be a list of paths")
    for key, value in c.items():
        if key.endswith(("_pj", "_ns", "_w", "_bytes", "_Bps", "_MACps", "_per_byte", "_per_mac", "_per_token")) and value is not None:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{key} must be a finite nonnegative number or null")
            if key.endswith(("_Bps", "_MACps")) and value == 0:
                raise ValueError(f"{key} must be positive or null")
    if c["model_quality_pass"] is not None and type(c["model_quality_pass"]) is not bool:
        raise ValueError("model_quality_pass must be true, false or null")


def evaluate(c, e):
    """Serial matrices, batched tile waves; no free bank/ADC overlap."""
    validate_config(c)
    m = MODELS[c["model"]]
    counts = model_counts(m, e)
    rows, cols = e["rows"], e["cols"]
    slices = c["weight_bits"] // 4
    batch, macros = c["batch"], c["physical_macros"]
    adc_rounds = math.ceil(cols / c["adcs_per_macro"])
    # Two coefficient banks per W8 macro share the readout; their memory,
    # selection and changed electrical loading are NOT measured by the W4 probe.
    tile_ns = slices * (e["array_ns"] + adc_rounds * e["adc_ns"])
    tile_pj = slices * (rows * cols * e["array_fj_per_mac"] / 1000 + cols * e["adc_pj"])
    known = lambda key: 0 if c[key] is None else c[key]
    tile_ns += known("extra_macro_ns")
    tile_pj += known("extra_macro_pj")
    matrices = [(a, b, m["layers"]) for a, b in shapes(m)] + [(m["d"], m["vocab"], 1)]
    # Load one tile group, reuse its weights for every batch input, then move
    # to the next group. Pooling batch*tiles would imply free weight copies.
    waves = sum(rep * batch * math.ceil(math.ceil(a / rows) * math.ceil(b / cols) / macros)
                for a, b, rep in matrices)
    # Edge tiles pay for every physical column. Useful work never includes
    # padded rows, extra weight slices, ADC decisions, or activation planes.
    services = counts["tiles"] * cols * slices
    compute_s = waves * tile_ns * 1e-9
    kv_width = m["d"] // m["hq"] * m["hkv"]
    kv_write = 2 * m["layers"] * kv_width * c["kv_bits"] / 8
    kv_read = kv_write * c["context"]
    attention = 2 * m["layers"] * m["d"] * c["context"]
    programming_bytes = (counts["tiles"] * rows * cols * c["weight_bits"] / 8
                         if c["weight_mode"] == "streamed" else 0)
    external_bytes = programming_bytes + batch * (kv_read + kv_write + m["d"] * c["weight_bits"] / 8)
    fabric_bytes = batch * counts["fabric_bytes"]
    components = dict(
        array_and_adc_J=batch * counts["tiles"] * tile_pj * 1e-12,
        programming_J=programming_bytes * known("weight_programming_pj_per_byte") * 1e-12,
        external_memory_J=external_bytes * known("external_memory_pj_per_byte") * 1e-12,
        fabric_J=fabric_bytes * known("fabric_pj_per_byte") * 1e-12,
        attention_J=batch * attention * known("attention_fj_per_mac") * 1e-15,
        nonlinear_J=batch * known("nonlinear_pj_per_token") * 1e-12,
        startup_J=known("startup_pj") * 1e-12,
    )
    # This first executable schedule serializes these services. No claim that
    # real hardware cannot overlap them; no overlap is needed for this estimate.
    durations = dict(
        weight_compute=compute_s,
        attention=(batch * attention / c["attention_MACps"] if c["attention_MACps"] else 0),
        nonlinear=batch * known("nonlinear_ns_per_token") * 1e-9,
        external_memory=(external_bytes / c["external_Bps"] if c["external_Bps"] else 0),
        fabric=(fabric_bytes / c["fabric_Bps"] if c["fabric_Bps"] else 0),
        programming=(programming_bytes / c["weight_programming_Bps"] if c["weight_programming_Bps"] else 0),
        startup=known("startup_ns") * 1e-9,
    )
    seconds = sum(durations.values())
    dynamic_j = sum(components.values())
    static_w = known("leakage_w") + known("maintenance_w")
    cap = c["power_limit_w"]
    power_fail = cap is not None and cap <= static_w
    if cap is not None and not power_fail:
        seconds = max(seconds, dynamic_j / (cap - static_w))
    durations["power_throttle"] = seconds - sum(durations.values())
    components["static_and_maintenance_J"] = static_w * seconds
    joules = sum(components.values())
    missing = [k for k, v in c.items() if v is None and k != "power_limit_w"]
    if c["weight_mode"] == "resident":
        missing = [k for k in missing if not k.startswith("weight_programming_")]
    kv_required = batch * (kv_read + kv_write)
    weight_required = ((counts["stored_tiles"] if c["weight_mode"] == "resident" else macros)
                       * rows * cols * c["weight_bits"] / 8)
    def capacity_gate(key, required):
        return "UNKNOWN" if c[key] is None else ("PASS" if c[key] >= required else "FAIL")
    memory_rates = {
        "external": (batch * c["external_Bps"] / external_bytes if c["external_Bps"] else None),
        "fabric": (batch * c["fabric_Bps"] / fabric_bytes if c["fabric_Bps"] else None),
        "programming": (batch * c["weight_programming_Bps"] / programming_bytes
                        if programming_bytes and c["weight_programming_Bps"] else None),
    }
    relevant = [v for k, v in memory_rates.items() if k != "programming" or programming_bytes]
    memory_seconds = sum(durations[k] for k in ("external_memory", "fabric", "programming"))
    # Match the chosen serialized schedule, rather than granting overlap in
    # the bottleneck gate after serializing the same services in token time.
    margin = compute_s / memory_seconds if all(v is not None for v in relevant) else None
    gates = dict(
        array_fixture="PASS" if e["array_accuracy_pass"] else "FAIL",
        adc_fixture="PASS" if e["adc_accuracy_pass"] else "FAIL",
        adc_development_suite=e["adc_development_suite"],
        adc_reserved_validation=e["adc_regression_status"],
        weight_capacity=capacity_gate("weight_capacity_bytes", weight_required),
        kv_capacity=capacity_gate("kv_capacity_bytes", kv_required),
        resident_mapping=("FAIL" if c["weight_mode"] == "resident" and macros < counts["stored_tiles"] else "PASS"),
        memory_service_margin="UNKNOWN" if margin is None else ("PASS" if margin >= 1.2 else "FAIL"),
        power_limit="FAIL" if power_fail else "PASS",
        complete_cost_model="PASS" if not missing else "UNKNOWN",
        model_quality="UNKNOWN" if c["model_quality_pass"] is None else ("PASS" if c["model_quality_pass"] else "FAIL"),
        # Cannot be waived by entering optimistic numbers in a config file.
        integrated_macro="UNVALIDATED", physical_noise_and_mismatch="UNVALIDATED",
        extracted_layout="UNVALIDATED", complete_token_execution="UNVALIDATED",
    )
    return dict(
        corner=e["corner"], precision=f"W{c['weight_bits']}A8",
        classification="CONDITIONAL PARTIAL-COST PROJECTION; NOT A CHIP RESULT",
        native_weight_MACs_per_token=counts["macs"], attention_MACs_per_token=attention,
        padded_MAC_slots_per_token=counts["tiles"] * rows * cols,
        ADC_services_per_token=services, weight_slices=slices,
        model_counts=counts, weight_capacity_required_bytes=weight_required,
        KV_capacity_required_bytes=kv_required, external_bytes_per_batch=external_bytes,
        fabric_leaf_bytes_per_batch=fabric_bytes, programming_bytes_per_batch=programming_bytes,
        macro_cycle_ns=tile_ns, macro_energy_pj=tile_pj,
        array_fixture_metrics=metrics(rows * cols, e["array_ns"] * 1e-9,
                                      rows * cols * e["array_fj_per_mac"] * 1e-15),
        macro_projection=metrics(rows * cols, tile_ns * 1e-9, tile_pj * 1e-12),
        matrix_waves_per_batch=waves, compute_schedule_tok_per_s=batch / compute_s,
        batch_seconds=seconds, batch_energy_J=joules,
        known_cost_projection=metrics(batch * counts["macs"], seconds, joules, batch),
        energy_components=components, serialized_service_seconds=durations,
        memory_rate_limits_tok_per_s=memory_rates, memory_margin_vs_weight_compute=margin,
        dominant_known_service=max(durations, key=durations.get),
        unknown_inputs=missing, gates=gates, acceptance="NOT VALIDATED",
        validated_chip_metrics=None, matched_Mythic_victory=False,
    )


def mythic_resource_comparison(e):
    """Fixed M1076 resource screen, independent of the token-model scenario.

Match logical weight positions AND converter count. ADC sharing is a proposed
architecture, not a simulated mux/hold network. Preserve the failed ADC gate.
"""
    tiles, logical_rows, logical_cols, adcs_per_group = 76, 1024, 1024, 256
    rows, cols, slices = e["rows"], e["cols"], 2
    if logical_rows % rows or logical_cols % cols:
        raise ValueError("This exact resource mapping requires divisible tile dimensions")
    row_groups, col_groups = logical_rows // rows, logical_cols // cols
    macros_per_group = row_groups * col_groups
    partial_outputs = macros_per_group * cols
    rounds = math.ceil(partial_outputs / adcs_per_group)
    # Compute all row/column subarrays, then serialize their held partials into
    # the ADC pool. Start the next W4 bank only after this bank is digitized.
    group_ns = slices * (e["array_ns"] + rounds * e["adc_ns"])
    group_macs = logical_rows * logical_cols
    group_pj = slices * (group_macs * e["array_fj_per_mac"] / 1000
                        + partial_outputs * e["adc_pj"])
    all_weights, all_adcs = tiles * group_macs, tiles * adcs_per_group
    last_wait_ns = (rounds - 1) * e["adc_ns"]
    native = metrics(all_weights, group_ns * 1e-9, tiles * group_pj * 1e-12)
    full_a8_ns = 8 * e["array_plane_ns"]  # timing-only extension of the six-plane fixture
    full_a8_group_ns = slices * (full_a8_ns + rounds * e["adc_ns"])
    adc_only_ns = slices * rounds * e["adc_ns"]
    just_in_time_ns = slices * rounds * (e["array_ns"] + e["adc_ns"])
    # Fixed installed ADC count gives a useful inverse timing requirement.
    timing_targets = {}
    for tops in (16.6, 25, 100):
        required_group_ns = 2 * all_weights / (tops * 1e12) * 1e9
        timing_targets[str(tops)] = dict(
            required_group_ns=required_group_ns,
            ADC_ns_max_before_extra_overhead=(required_group_ns / slices - e["array_ns"]) / rounds)
    return dict(
        classification="EQUAL WEIGHT POSITIONS AND ADC COUNT; CONDITIONAL, NOT A VALIDATED CHIP",
        corner=e["corner"], baseline="Historical M1076; current M1 tile-count identity is not established",
        sources=MYTHIC_SOURCES,
        reference_resources=dict(compute_tiles=tiles, extra_control_and_IO_tiles=7,
            logical_rows_per_tile=logical_rows, logical_cols_per_tile=logical_cols,
            physical_flash_array_per_tile=[1024, 2048], weight_positions=all_weights,
            ADCs=all_adcs, ADC_bits=8, technology_nm=40),
        ours_resources=dict(groups=tiles, small_macros_per_group=macros_per_group,
            small_macros_total=tiles * macros_per_group,
            rows_per_small_macro=rows, cols_per_small_macro=cols,
            W4_banks_per_logical_W8_macro=slices, logical_weight_positions=all_weights,
            ADCs=all_adcs, ADC_bits=10, technology_nm=130),
        count_only_controls=dict(
            equal_weights_with_local_8ADCs=dict(macros=tiles * macros_per_group,
                ADCs=tiles * macros_per_group * cols,
                ADC_count_ratio=(tiles * macros_per_group * cols) / all_adcs),
            equal_ADCs_with_local_8ADCs=dict(macros=all_adcs // cols,
                weight_positions=(all_adcs // cols) * rows * cols,
                weight_capacity_fraction=((all_adcs // cols) * rows * cols) / all_weights)),
        row_groups=row_groups, col_groups=col_groups,
        partial_outputs_per_group_per_slice=partial_outputs,
        ADC_rounds_per_slice=rounds, ADC_services_per_group=slices * partial_outputs,
        native_MACs_per_group=group_macs,
        minimum_reconstruction_adds_per_group=(row_groups * slices - 1) * logical_cols,
        cycle_ns=group_ns, array_ns=e["array_ns"], ADC_ns=e["adc_ns"], last_output_wait_ns=last_wait_ns,
        mean_output_wait_ns=last_wait_ns / 2,
        measured_component_projection=native,
        full_range_A8_timing_only_projection=dict(array_ns=full_a8_ns,
            group_ns=full_a8_group_ns, TOPS=2 * all_weights / (full_a8_group_ns * 1e-9) / 1e12,
            energy_J=None, note="Eight magnitude planes include -128; no corresponding energy/accuracy measurement"),
        analog_storage_schedule_controls=dict(
            just_in_time_serial=dict(cycle_ns=just_in_time_ns,
                TOPS=2 * all_weights / (just_in_time_ns * 1e-9) / 1e12,
                energy_J=None,
                note="Compute 32 small macros, immediately convert 256 outputs; repeat 32 times per bank. Avoids the 9 us queue, but selection/readout are unvalidated."),
            ideal_ADC_service_limit=dict(cycle_ns=adc_only_ns,
                TOPS=2 * all_weights / (adc_only_ns * 1e-9) / 1e12,
                energy_J=None,
                note="Perfectly hidden array/hold overhead cannot exceed this rate at the fixed ADC count, service count and 295 ns conversion time. No buffering implementation is assumed validated.")),
        inverse_ADC_timing_targets=timing_targets,
        published_baselines=dict(
            product_headline=dict(TOPS=25, power_W=[3, 4], TOPS_per_W=[25 / 4, 25 / 3],
                fJ_per_MAC=[2000 / (25 / 3), 2000 / (25 / 4)]),
            isscc_8bit_press_disclosure=dict(TOPS=16.6, full_system_TOPS_per_W=3.3,
                ACiM_array_TOPS_per_W=5.2, implied_full_system_power_W=16.6 / 3.3,
                full_system_fJ_per_MAC=2000 / 3.3,
                note="Official preliminary press kit, paper15.8; not the 25-TOPS product operating point")),
        gates=dict(weight_position_count="PASS", ADC_count="PASS",
            array_fixture="PASS" if e["array_accuracy_pass"] else "FAIL",
            adc_fixture="PASS" if e["adc_accuracy_pass"] else "FAIL",
            adc_development=e["adc_development_suite"], adc_reserved=e["adc_regression_status"],
            programmable_weight_storage="UNVALIDATED", shared_mux_and_hold="UNVALIDATED",
            reconstructed_output_quality="UNVALIDATED", equal_area="UNVALIDATED",
            complete_power="UNVALIDATED", matched_end_to_end_workload="UNVALIDATED"),
        missing_costs=["32-to-1 readout mux per ADC, routing, acquisition and kickback",
            f"up to {last_wait_ns / 1000:.3f} us of charge retention at the current ADC period",
            "row-partial and W4-bank reconstruction, calibration/scaling and required checksums",
            "physical W8 storage, bank selection, initial programming and full-scale bank loading",
            "full-chip references, clock/control, distribution, regulation, leakage and wiring"],
        validated_chip_metrics=None, matched_Mythic_victory=False,
        matched_tok_per_s=None, matched_tok_per_J=None,
    )


def mythic_markdown(comparisons):
    a = comparisons[0]
    rr, ours = a["reference_resources"], a["ours_resources"]
    lines = ["# Mythic comparison with equal weight positions and ADC count", "",
        "This replaces macro-count-only comparisons. It is a proposed mapping of "
        "separate circuit fixtures; full-chip performance remains unvalidated.", "",
        "| Resource | Historical Mythic M1076 | AnalogIOC proposed mapping |",
        "|---|---:|---:|",
        f"| Logical weight positions | {rr['weight_positions']:,} | {ours['logical_weight_positions']:,} |",
        f"| ADCs | {rr['ADCs']:,} | {ours['ADCs']:,} |",
        "| Large groups | 76 compute tiles | 76 groups of small macros |",
        "| Logical matrix per group | 1,024×1,024 | 1,024×1,024 |",
        "| Small macros per group | Different architecture | 1,024 of 128×8 |",
        "| ADC resolution | 8 bits | 10 bits before reconstruction |",
        "| Process | 40 nm | sky130 |", "",
        f"[Mythic product brief]({MYTHIC_SOURCES['product_brief']}) establishes 76 tiles and the 25 TOPS / 3–4 W headline. "
        f"[Mythic CTO's IEEE talk]({MYTHIC_SOURCES['cto_talk']}) specifies 79.69M 8-bit weights and 19,456 ADCs. "
        "Logical dimensions count weights; the physical flash array has 1,024×2,048 cells per tile.", "",
        "With 8 local ADCs per small macro, matching only weights would grant AnalogIOC 622,592 ADCs "
        "(32× Mythic). Matching only ADC count would retain just 2,490,368 weight positions (1/32 Mythic). "
        "The comparison below shares 256 ADCs across each equivalent group.", "",
        "| Operating point / boundary | TOPS | W | TOPS/W | fJ/MAC |",
        "|---|---:|---:|---:|---:|",
        "| M1076 product headline | 25 | 3–4 | 6.25–8.33 | 240–320 |",
        "| ISSCC 8-bit full-system press disclosure | 16.6 | 5.03 implied | 3.3 | 606.1 |"]
    for r in comparisons:
        z = r["measured_component_projection"]
        lines.append(f"| AnalogIOC {r['corner'].upper()}, counted fixtures only | " +
                     " | ".join(f"{z[k]:.6g}" for k in ("TOPS", "power_W", "TOPS_per_W", "fJ_per_MAC")) + " |")
    lines += ["", f"The [official ISSCC preliminary press kit, page 46]({MYTHIC_SOURCES['isscc_press_kit']}) "
        "separates 8-bit full-system 3.3 TOPS/W from array-only 5.2 TOPS/W. These are a different "
        "disclosure/operating point from the product headline. Complete original benchmark settings "
        "and a matched output-quality result remain unavailable here.", "",
        "One proposed group has 8 row partitions × 128 output partitions = 1,024 small macros. "
        "Each W4 bank produces 8,192 partial outputs. The 256 ADCs need 32 rounds; two W4 banks run serially:", "",
        f"`2 × ({a['array_ns']:.0f} ns array + {a['ADC_rounds_per_slice']} × {a['ADC_ns']:.0f} ns ADC) = {a['cycle_ns'] / 1000:.3f} µs/group`", "",
        "That counts 1,048,576 useful W8A8 MACs per group, without counting slices or padding as extra work. "
        "At least 15,360 reconstruction additions per group remain unpriced, plus gain/scale correction. "
        f"The latest output waits {a['last_output_wait_ns'] / 1000:.3f} µs before service; retention through an integrated shared mux remains unvalidated.", "",
        f"The {a['array_ns']:.0f} ns array phase is the mean of three B7/B6/B5 input words. "
        f"Extending timing alone to eight planes gives {a['full_range_A8_timing_only_projection']['TOPS']:.3f} TOPS; "
        "this is not a measured full-range energy or accuracy point.", "",
        f"[Mythic's charge-accumulator patent]({MYTHIC_SOURCES['analog_charge_patent']}) "
        "discloses multilevel stored charge for input DACs and ADC feedback references. "
        "It supports investigating analog state storage, but does not establish a shipped "
        "output sample-and-hold or remove ADC services.", "",
        f"If hold/compute overhead were perfectly hidden, the same ADC service count and period "
        f"would limit this mapping to {a['analog_storage_schedule_controls']['ideal_ADC_service_limit']['TOPS']:.3f} TOPS. "
        f"Alternatively, computing and immediately converting small groups avoids the long queue "
        f"but gives {a['analog_storage_schedule_controls']['just_in_time_serial']['TOPS']:.3f} TOPS under a serial schedule. "
        "No energy, retention or noise result is assigned to either scheduling control.", "",
        "**Acceptance: NOT VALIDATED.** Equal counts do not prove equal area, ADC capability, "
        "output accuracy, power boundary or workload. The complete reserved ADC suite status "
        "is preserved below. A single 79.7M-weight device also cannot hold the prior 8B-class "
        "token scenario. Matched tok/s and tok/J remain unavailable.", "",
        "| Energy corner | Array fixture | ADC fixture | ADC development suite | Reserved suite across both corners | Full chip |", "|---|---|---|---|---|---|"]
    lines += [f"| {r['corner']} | {r['gates']['array_fixture']} | {r['gates']['adc_fixture']} | {r['gates']['adc_development']} | {r['gates']['adc_reserved']} | UNVALIDATED |" for r in comparisons]
    return "\n".join(lines) + "\n"


def self_check():
    # Independent dimensional example: 1e9 MAC in1ms using2mJ, ten tokens.
    x = metrics(1e9, 1e-3, 2e-3, 10)
    for key, expected in dict(TOPS=2, power_W=2, TOPS_per_W=1, fJ_per_MAC=2000,
                              tok_per_s=10000, tok_per_J=5000).items():
        assert math.isclose(x[key], expected), (key, x)
    for bad in (0, -1, float("nan"), float("inf")):
        try:
            metrics(1, 1, bad)
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid energy accepted")
    e = dict(rows=128, cols=8, array_ns=366, array_plane_ns=61, array_fj_per_mac=4.5,
             adc_ns=295, adc_pj=1.5, corner="tt", array_accuracy_pass=True,
             adc_accuracy_pass=True, adc_development_suite="PASS", adc_regression_status="INCOMPLETE")
    c = DEFAULT.copy()
    a = evaluate(c, e)
    assert a["native_weight_MACs_per_token"] == 7503609856
    assert a["ADC_services_per_token"] == a["model_counts"]["tiles"] * 16
    b = evaluate(dict(c, weight_bits=4), e)
    assert a["native_weight_MACs_per_token"] == b["native_weight_MACs_per_token"]
    assert math.isclose(a["macro_energy_pj"], 2 * b["macro_energy_pj"])
    assert math.isclose(a["macro_cycle_ns"], 2 * b["macro_cycle_ns"])
    shared = evaluate(dict(c, adcs_per_macro=1), e)
    assert shared["macro_energy_pj"] == a["macro_energy_pj"]
    assert shared["macro_cycle_ns"] > a["macro_cycle_ns"]
    assert a["gates"]["memory_service_margin"] == "UNKNOWN"
    toy = dict(layers=1, d=4, f=5, hq=2, hkv=1, vocab=7)
    # 4x4, 4x2 twice, 4x4, 4x5 twice, 5x4, 4x7: 136 useful
    # cells; 3x3 physical tiles reserve 30 tiles /270 slots incl edge padding.
    padded = model_counts(toy, dict(rows=3, cols=3))
    assert padded["macs"] == 136 and padded["tiles"] == 30
    batched = evaluate(dict(c, batch=8, physical_macros=8192), e)
    single = evaluate(dict(c, physical_macros=8192), e)
    assert batched["matrix_waves_per_batch"] == 8 * single["matrix_waves_per_batch"]
    assert batched["programming_bytes_per_batch"] == single["programming_bytes_per_batch"]
    assert a["validated_chip_metrics"] is None and not a["matched_Mythic_victory"]
    mem = evaluate(dict(c, external_Bps=1, fabric_Bps=1, weight_programming_Bps=1), e)
    assert mem["gates"]["memory_service_margin"] == "FAIL"
    assert mem["known_cost_projection"]["tok_per_s"] < a["known_cost_projection"]["tok_per_s"]
    # Each memory resource individually clears compute by1.25x; serialized
    # together they take2.4x compute and must fail the memory-clear gate.
    compute_s = a["serialized_service_seconds"]["weight_compute"]
    serial = evaluate(dict(c,
        external_Bps=a["external_bytes_per_batch"] / (.8 * compute_s),
        fabric_Bps=a["fabric_leaf_bytes_per_batch"] / (.8 * compute_s),
        weight_programming_Bps=a["programming_bytes_per_batch"] / (.8 * compute_s)), e)
    assert serial["gates"]["memory_service_margin"] == "FAIL"
    assert math.isclose(serial["memory_margin_vs_weight_compute"], 1 / 2.4)
    resident = evaluate(dict(c, weight_mode="resident", weight_capacity_bytes=1e12,
                             kv_capacity_bytes=1e12), e)
    assert resident["gates"]["resident_mapping"] == "FAIL"
    failed = evaluate(c, dict(e, adc_accuracy_pass=False))
    assert failed["gates"]["adc_fixture"] == "FAIL"
    # Power throttling extends both time and static energy consistently.
    p = evaluate(dict(c, leakage_w=.001, maintenance_w=.001, power_limit_w=.002001), e)
    assert math.isclose(p["known_cost_projection"]["power_W"], .002001)
    assert p["known_cost_projection"]["tok_per_J"] < a["known_cost_projection"]["tok_per_J"]
    for result in (a, b, shared, mem, p):
        z = result["known_cost_projection"]
        assert math.isclose(z["TOPS"] / z["power_W"], z["TOPS_per_W"])
        assert math.isclose(z["TOPS_per_W"] * z["fJ_per_MAC"], 2000)
        assert math.isclose(z["tok_per_s"] / z["power_W"], z["tok_per_J"])
        assert math.isclose(sum(result["serialized_service_seconds"].values()), result["batch_seconds"])
    r = mythic_resource_comparison(e)
    assert r["reference_resources"]["weight_positions"] == 79691776
    assert r["ours_resources"]["small_macros_total"] == 77824
    assert r["ours_resources"]["ADCs"] == 19456
    assert r["count_only_controls"]["equal_weights_with_local_8ADCs"]["ADC_count_ratio"] == 32
    assert r["count_only_controls"]["equal_ADCs_with_local_8ADCs"]["weight_capacity_fraction"] == 1 / 32
    assert r["ADC_rounds_per_slice"] == 32 and r["ADC_services_per_group"] == 16384
    assert r["cycle_ns"] == 19612 and r["last_output_wait_ns"] == 9145
    assert r["minimum_reconstruction_adds_per_group"] == 15360
    assert math.isclose(r["measured_component_projection"]["TOPS"], 8.126838262288395)
    assert r["full_range_A8_timing_only_projection"]["group_ns"] == 19856
    storage = r["analog_storage_schedule_controls"]
    assert storage["just_in_time_serial"]["cycle_ns"] == 42304
    assert storage["ideal_ADC_service_limit"]["cycle_ns"] == 18880
    assert storage["just_in_time_serial"]["TOPS"] < r["measured_component_projection"]["TOPS"] < storage["ideal_ADC_service_limit"]["TOPS"]
    assert r["validated_chip_metrics"] is None and r["matched_tok_per_s"] is None
    failed = mythic_resource_comparison(dict(e, array_accuracy_pass=False, adc_accuracy_pass=False))
    assert failed["gates"]["array_fixture"] == failed["gates"]["adc_fixture"] == "FAIL"
    # Sharing cannot remove work or conversion energy; it changes service time.
    assert math.isclose(r["measured_component_projection"]["fJ_per_MAC"], a["macro_projection"]["fJ_per_MAC"])
    # Reconstruct one1024-term dot from8row chunks and2banks:16inputs require15adds.
    pieces = [(j + 1, 2 * j - 3) for j in range(8)]
    combined = sum(lo + 16 * hi for lo, hi in pieces)
    assert combined == sum(lo for lo, hi in pieces) + 16 * sum(hi for lo, hi in pieces)


def markdown(report):
    c = report["config"]
    lines = ["# IMC system benchmark", "", report["classification"], "",
             "For the comparison with equal weight capacity and ADC count, read "
             "[mythic_comparison.md](mythic_comparison.md). The table below is the configured token-model scenario.", "",
             "Four metrics share the same native weight-MAC/time/energy totals. "
             "Token numbers are cost-model outputs, not generated-token measurements.", "",
             f"Scenario: {c['physical_macros']:,} logical 128×8 macros, {c['adcs_per_macro']} ADCs/macro, "
             f"W{c['weight_bits']}A8, {c['model']}, batch {c['batch']}, "
             f"context {c['context']:,}, KV{c['kv_bits']}, {c['weight_mode']} weights.", "",
             "| Corner | Conditional TOPS | Known-cost W | TOPS/W | fJ/MAC | tok/s | tok/J |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for r in report["results"]:
        z = r["known_cost_projection"]
        lines.append(f"| {r['corner']} | " + " | ".join(f"{z[k]:.6g}" for k in
                     ("TOPS", "power_W", "TOPS_per_W", "fJ_per_MAC", "tok_per_s", "tok_per_J")) + " |")
    lines += ["", "Missing inputs are omitted ONLY from the labelled partial-cost projection; "
              "they are never accepted as zero in the completeness gate.", "",
              "Mythic M1 vendor headline: 25 TOPS at 3–4 W, implying 6.25–8.33 TOPS/W "
              "and 240–320 fJ/MAC at 2 ops/MAC. Precision/workload boundaries are unmatched; "
              f"no victory ratio is calculated. [Source]({SOURCE_URL}).", ""]
    for r in report["results"]:
        lines += ["", f"## {r['corner']}: {r['acceptance']}", "",
                  f"Unknown inputs: {', '.join(r['unknown_inputs'])}.", "",
                  "| Gate | Status |", "|---|---|"]
        lines += [f"| {k} | {v} |" for k, v in r["gates"].items()]
    lines += ["", "Assumptions:", ""] + [f"- {s}" for s in report["assumptions"]]
    lines += ["", "Artifact fingerprints:", ""] + [f"- `{s['path']}`: `{s['sha256']}`" for s in report["sources"]]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="JSON overrides of the emitted inputs file")
    parser.add_argument("--out", type=Path, default=ROOT / "build/research/imc_system_benchmark")
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--require-validated", action="store_true", help="Exit1 until full-chip evidence gates pass")
    args = parser.parse_args()
    self_check()
    print("BENCHMARK ARITHMETIC AND NEGATIVE CONTROLS: PASS")
    if args.self_check:
        return
    config = DEFAULT.copy()
    if args.config:
        config.update(json.loads(args.config.read_text()))
    validate_config(config)
    evidence, sources = load_evidence(config)
    comparison = [mythic_resource_comparison(e) for e in evidence]
    report = dict(classification="CONDITIONAL PARTIAL-COST PROJECTION; NOT A CHIP RESULT",
                  config=config, sources=sources, circuit_evidence=evidence,
                  results=[evaluate(config, e) for e in evidence],
                  assumptions=[
                      "Native MAC=one weight multiply-accumulate; two operations/MAC. No precision-normalized inflation.",
                      "W8 uses two coefficient banks sharing the same ADCs, served serially. W8 bank loading/storage is unmeasured.",
                      "Array and ADC are separate fixtures with different acquisition loading; summing their energy is not an integrated measurement.",
                      "Array cost/time uses three specific B7/B6/B5 input words; no full-model activity or worst-case A8 timing qualification.",
                      "Matrices and tile waves execute serially; array then ADC, with no overlapping services or free programming.",
                      "All edge tiles pay full energy; fabric is aggregate multicast/reduction leaf traffic, not off-chip traffic or bisection bandwidth.",
                      "Llama-class dimensions include the full LM head and separate untied embedding storage; these are shape scenarios, not checkpoint runs.",
                      "KV full-context read and one append per token are counted. Attention MACs and nonlinear work are separate costs; reported TOPS counts weight MACs only.",
                      "Startup is charged per batch; null is unknown. No initial weight-programming, calibration or stored-charge energy is silently amortized away.",
                      "extra_macro costs must cover missing selection, reconstruction, reference/clock generation, regulation, wiring, and required checksum work.",
                      "Analog port positive delivery is a non-recovering source-energy proxy; complete-chip input power is unmeasured.",
                      "ADC energy is the twelve-input cohort mean, not a worst-case conversion bound. TT/SS are two sampled corners, not complete PVT qualification.",
                  ])
    args.out.mkdir(parents=True, exist_ok=True)
    for name, data in (("inputs.json", config), ("results.json", report)):
        (args.out / name).write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")
    (args.out / "results.md").write_text(markdown(report))
    (args.out / "mythic_comparison.json").write_text(json.dumps(dict(sources=sources, results=comparison), indent=2, allow_nan=False) + "\n")
    (args.out / "mythic_comparison.md").write_text(mythic_markdown(comparison))
    for r in report["results"]:
        print(f"{r['corner']}: {r['acceptance']}; ADC development={r['gates']['adc_development_suite']}; "
              f"ADC reserved={r['gates']['adc_reserved_validation']}; "
              f"memory={r['gates']['memory_service_margin']}; {len(r['unknown_inputs'])} unknown inputs")
    print(args.out / "results.md")
    print(args.out / "mythic_comparison.md")
    if args.require_validated:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
