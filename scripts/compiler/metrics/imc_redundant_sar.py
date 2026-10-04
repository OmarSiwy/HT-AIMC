"""Adversarial arithmetic check of a 6-coarse/5-fine redundant 10-bit SAR.

This is a proposed algorithm, not the physical null-SAR implementation. All
analog values use integer ticks (1/256 final LSB); no favorable random noise
draws, SPICE, measured comparator aperture, or physical energy model is used.
"""
import json
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parents[3]
TICKS = 256
FULL = 1024
COARSE = (512, 256, 128, 64, 32, 16)
FINE = (16, 8, 4, 2, 1)


def outcomes(x, weights, error=0, both_zero_outcomes=False):
    """All reachable retained codes; accept iff x >= trial + e, |e|<=error.

    x/error are ticks; weights/codes are final LSBs. Normally equality accepts.
    both_zero_outcomes additionally permits rejection at zero differential.
    Each unique binary path has a unique retained code, so none are merged.
    """
    states = [0]
    for weight in weights:
        next_states = []
        for code in states:
            trial = code + weight
            delta = x - trial*TICKS
            if delta >= -error:
                next_states.append(trial)
            if delta < error or (both_zero_outcomes and delta == error):
                next_states.append(code)
        states = next_states
    return states


def path_intervals(error):
    """Exact half-open real-input interval for each of all 64 coarse paths.

    Endpoints are ticks, but interval intersection proves the property for
    every real input, including fractions absent from the finite sweep.
    """
    states = [(0, 0, FULL*TICKS)]
    for weight in COARSE:
        next_states = []
        for code, lower, upper in states:
            trial = code + weight
            accepted = (trial, max(lower, trial*TICKS-error), upper)
            rejected = (code, lower, min(upper, trial*TICKS+error))
            for state in (accepted, rejected):
                if state[1] < state[2]:
                    next_states.append(state)
        states = next_states
    assert len(states) == 64
    for code, lower, upper in states:
        assert lower == max(0, code*TICKS-error)
        assert upper == min(FULL*TICKS, (code+16)*TICKS+error)
    return [dict(coarse=code, input_lower_lsb=lo/TICKS,
                 input_upper_exclusive_lsb=hi/TICKS)
            for code, lo, hi in sorted(states)]


def saturate(code):
    return min(FULL-1, max(0, code))


def quiet_fine(residue):
    """Five exact comparisons of u=residue+8 on [0,32), then signed correction."""
    return outcomes(residue+8*TICKS, FINE)[0]-8


def exhaustive_coarse_check(error, both_zero_outcomes=False):
    paths, maximum_error, maximum_plain_error = 0, 0, 0
    residue_min, residue_max = FULL*TICKS, -FULL*TICKS
    first_failure = None
    for x in range(FULL*TICKS):
        target = x//TICKS
        for coarse in outcomes(x, COARSE, error, both_zero_outcomes):
            paths += 1
            residue = x-coarse*TICKS
            residue_min, residue_max = min(residue_min, residue), max(residue_max, residue)
            got = saturate(coarse+quiet_fine(residue))
            difference = abs(got-target)
            maximum_error = max(maximum_error, difference)
            # Existing nonredundant 6+4 scheme cannot correct a wrong coarse bin.
            plain = saturate(coarse+outcomes(residue, FINE[1:])[0])
            maximum_plain_error = max(maximum_plain_error, abs(plain-target))
            if difference and first_failure is None:
                first_failure = dict(x_lsb=x/TICKS, coarse=coarse,
                                     residue_lsb=residue/TICKS, got=got, target=target)
    return dict(error_bound_lsb=error/TICKS, both_zero_outcomes=both_zero_outcomes,
                inputs=FULL*TICKS, adversarial_coarse_paths=paths,
                observed_residue_min_lsb=residue_min/TICKS,
                observed_residue_max_lsb=residue_max/TICKS,
                max_code_error=maximum_error,
                nonredundant_6_plus_4_max_code_error=maximum_plain_error,
                first_failure=first_failure)


def fine_error_check():
    """Reserve range margin, then expose the fine comparator's own error.

    All coarse/fine decision outcomes are enumerated. Handoff perturbations
    use both bounded endpoints (not an exhaustive continuous handoff sweep).
    """
    coarse_error, fine_error, handoff_error = 1920, 64, 32  # 7.5, .25, .125 LSB.
    assert coarse_error+fine_error+handoff_error < 8*TICKS
    paths, maximum_error, first_failure = 0, 0, None
    for x in range(FULL*TICKS):
        target = x//TICKS
        for coarse in outcomes(x, COARSE, coarse_error):
            for handoff in (-handoff_error, handoff_error):
                u = x-coarse*TICKS+8*TICKS+handoff
                assert fine_error < u < 32*TICKS-fine_error
                for fine in outcomes(u, FINE, fine_error):
                    paths += 1
                    # The usual final-step invariant includes fine error.
                    assert -fine_error <= u-fine*TICKS < TICKS+fine_error
                    got = saturate(coarse+fine-8)
                    difference = abs(got-target)
                    maximum_error = max(maximum_error, difference)
                    if difference and first_failure is None:
                        first_failure = dict(x_lsb=x/TICKS, coarse=coarse,
                                             handoff_lsb=handoff/TICKS,
                                             fine_shifted_code=fine, got=got, target=target)
    assert maximum_error == 1 and first_failure is not None
    return dict(coarse_bound_lsb=coarse_error/TICKS, fine_bound_lsb=fine_error/TICKS,
                handoff_endpoint_bound_lsb=handoff_error/TICKS,
                unused_range_margin_lsb=(8*TICKS-coarse_error-fine_error-handoff_error)/TICKS,
                inputs=FULL*TICKS, adversarial_complete_paths=paths,
                max_code_error=maximum_error, first_failure=first_failure,
                handoff_coverage="Both endpoints; intermediate perturbations covered by residual bound, not enumerated")


def charge_path_check():
    """One ideal signed charge-injection realization; no current/energy model."""
    paths = []
    for shifted_code in range(32):
        residue = (shifted_code-8)*TICKS+TICKS//4
        trial, previous, movements, decisions = 8, 0, [], []
        for step in (8, 4, 2, 1, 0):
            movements.append(trial-previous)
            accepted = residue >= trial*TICKS
            decisions.append(int(accepted))
            previous = trial
            if step:
                trial += step if accepted else -step
        correction = trial if decisions[-1] else trial-1
        assert correction == shifted_code-8 == quiet_fine(residue)
        assert sum(abs(v) for v in movements) == 23
        assert max(abs(v) for v in movements) == 8
        paths.append(dict(shifted_code=shifted_code, correction_lsb=correction,
                          trial_movements_lsb=movements, decisions=decisions,
                          final_trial_lsb=trial))
    return dict(paths=paths, correction_code_range_lsb=[-8, 23],
                analog_residue_interval_lsb="[-8,24)",
                initial_trial_lsb=8, later_movement_magnitudes_lsb=[8, 4, 2, 1],
                total_absolute_ideal_packet_units=23,
                nonredundant_fine_absolute_packet_units=15,
                physical_final_code_update_included=False,
                unit_charge_examples_fC={str(cap_fF): cap_fF*.5/FULL
                                         for cap_fF in (768, 3628)})


def selfcheck():
    ideal = exhaustive_coarse_check(8*TICKS)
    assert ideal["max_code_error"] == 0
    assert ideal["nonredundant_6_plus_4_max_code_error"] == 8
    assert ideal["observed_residue_min_lsb"] == -8
    assert ideal["observed_residue_max_lsb"] == 24-1/TICKS
    intervals = path_intervals(8*TICKS)

    # Physical zero-differential ties and an excessive coarse error are controls
    # which MUST fail exact reconstruction, not hidden by favorable randomness.
    ties = exhaustive_coarse_check(8*TICKS, both_zero_outcomes=True)
    excessive = exhaustive_coarse_check(10*TICKS)
    assert ties["max_code_error"] == 1
    assert excessive["max_code_error"] == 2

    # Explicit signed/clamped assembly, including beyond the nominal input range.
    boundaries = []
    for x in (-16*TICKS, -1, 0, 1, FULL*TICKS-1, FULL*TICKS, (FULL+16)*TICKS):
        results = sorted({saturate(c+quiet_fine(x-c*TICKS))
                          for c in outcomes(x, COARSE, 8*TICKS)})
        assert results == [saturate(x//TICKS)]
        boundaries.append(dict(x_lsb=x/TICKS, output=results[0]))
    # Fixed fine offset survives overlap, but is a global shift in this ideal
    # linear model if no fine range clipping occurs; periodic DNL is not implied.
    for x in range(FULL*TICKS):
        for c in outcomes(x, COARSE, 7*TICKS):
            got = saturate(c+quiet_fine(x-c*TICKS+TICKS//4))
            assert got == saturate((x+TICKS//4)//TICKS)

    return dict(status="PASS", scope="Ideal arithmetic; no physical ADC or energy qualification",
                coverage="All 1024 codes x all 256 fractions k/256; all allowed decision paths",
                tie_convention="Accept iff x >= trial + e; |e| <= epsilon",
                exact_fine=ideal, all_real_input_path_intervals=intervals,
                both_zero_outcomes_negative_control=ties,
                excessive_coarse_error_negative_control=excessive,
                fine_and_handoff_errors=fine_error_check(), boundary_controls=boundaries,
                charge_control=charge_path_check(),
                fixed_fine_offset_control="+0.25 LSB gives floor(x+0.25), not removed by overlap",
                cost_condition="6*E_coarse + E_added_handoff_control_and_DAC < 5*E_quiet",
                latency_condition="6*T_coarse + T_added_handoff_control_and_DAC < 5*T_quiet",
                limitations=["Bounded errors are not Gaussian standard deviations",
                             "At physical ties, inclusive 8-LSB coarse bound is insufficient for exactness",
                             "Fine noise, gain/offset, reference settling and switching need their own budgets",
                             "Actual floating-node capacitance and connected-switch charge remain unmodeled"])


if __name__ == "__main__":
    started = time.perf_counter()
    try:
        result = selfcheck()
    except AssertionError:
        print("FAIL: redundant SAR arithmetic invariant/control")
        raise
    result["elapsed_s"] = time.perf_counter()-started
    destination = ROOT/"build/research/imc_redundant_sar.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2)+"\n")
    print(f"PASS: {result['exact_fine']['inputs']} inputs, "
          f"{result['exact_fine']['adversarial_coarse_paths']} coarse paths, "
          f"zero ideal reconstruction error; negative controls preserved "
          f"({result['elapsed_s']:.2f} s). {destination}")
