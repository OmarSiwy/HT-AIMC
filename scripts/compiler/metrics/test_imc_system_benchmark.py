"""Cached-artifact adapter controls; no SPICE or new circuit evidence.

Requires the benchmark's cached array and five-case ADC development artifacts.
Synthetic regression records below test parser coverage only, and stay in memory.
Run with the repository's Nix Python environment.
"""
import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
from compiler.metrics import imc_system_benchmark as benchmark


class EvidenceAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.array, _ = benchmark.read_artifact(benchmark.DEFAULT["array_artifact"])
        cls.adc, _ = benchmark.read_artifact(benchmark.DEFAULT["adc_artifact"])

    def load(self, adc=None, array=None, regressions=None, missing=()):
        regressions = regressions or {}
        config = dict(benchmark.DEFAULT, adc_regression_artifacts=list(regressions) + list(missing))
        documents = {
            config["array_artifact"]: self.array if array is None else array,
            config["adc_artifact"]: self.adc if adc is None else adc,
            **regressions,
        }
        existing = {ROOT / name for name in documents}

        def read(name):
            return copy.deepcopy(documents[name]), {"path": name, "sha256": "in-memory-test"}

        with patch.object(benchmark, "read_artifact", side_effect=read), \
                patch.object(Path, "exists", lambda path: path in existing):
            return benchmark.load_evidence(config)[0]

    def regression_documents(self):
        # Reusing cached shared cases deliberately does not establish fresh-input
        # accuracy; these records only exercise seed/corner coverage bookkeeping.
        return {
            f"test_regression_{seed}_{corner}.json": {
                "config": copy.deepcopy(self.adc["config"]), "random_seed": seed,
                "cases": [copy.deepcopy(next(c for c in self.adc["cases"]
                          if c["label"] == "shared_reference" and c["result"]["corner"] == corner))],
            }
            for seed in (9952, 9953) for corner in ("tt", "ss")
        }

    def assert_suite_not_pass(self, adc):
        try:
            evidence = self.load(adc=adc)
        except ValueError:
            return
        self.assertTrue(all(e["adc_development_suite"] != "PASS" for e in evidence))

    def test_clean_fixture_uses_positive_delivery_and_full_cycle(self):
        for e in self.load():
            d = next(c["result"] for c in self.adc["cases"]
                     if c["label"] == "validation" and c["result"]["corner"] == e["corner"])
            self.assertEqual(e["adc_development_suite"], "PASS")
            self.assertEqual(e["adc_regression_status"], "INCOMPLETE")
            self.assertAlmostEqual(e["adc_pj"] * 1000, d["energy"]["d"]["total_fJ_per_conversion"])
            self.assertNotEqual(e["adc_pj"] * 1000, d["energy"]["p"]["total_fJ_per_conversion"])
            self.assertEqual(e["adc_ns"], d["whole_cycle_ns"])
            self.assertGreater(e["adc_ns"], d["conversion_interval_ns"])
            projected = benchmark.evaluate(benchmark.DEFAULT, e)
            self.assertEqual(projected["acceptance"], "NOT VALIDATED")
            self.assertIsNone(projected["validated_chip_metrics"])
            self.assertFalse(projected["matched_Mythic_victory"])

    def test_corrupt_suite_signatures_never_pass(self):
        mutations = {
            "duplicate TT shared": lambda a: a["cases"].__setitem__(3, copy.deepcopy(a["cases"][2])),
            "missing SS shared": lambda a: a["cases"].pop(3),
            "wrong negative label": lambda a: a["cases"][4].__setitem__("label", "unrelated_failure"),
            "no bridge fault": lambda a: a["cases"][4]["result"].__setitem__("bridge_error", 0),
            "shared wrong PVT": lambda a: a["cases"][3]["result"].__setitem__("temp_C", 27),
            "failed shared accuracy": lambda a: a["cases"][3]["result"].__setitem__("numerical_accuracy_pass", False),
            "failed physical feedback": lambda a: a["cases"][2]["result"].__setitem__("feedback_pass", False),
            "negative control unexpectedly passes": lambda a: a["cases"][4]["result"].__setitem__("numerical_accuracy_pass", True),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                adc = copy.deepcopy(self.adc)
                mutate(adc)
                self.assert_suite_not_pass(adc)

    def test_every_case_requires_ten_decisions_and_paid_reset_boundaries(self):
        for index in range(len(self.adc["cases"])):
            for field, value in (("physical_decisions", 9), ("warmup_frames", 0),
                                 ("closing_frames", 0), ("simulated_frames", 1)):
                with self.subTest(case=index, field=field):
                    adc = copy.deepcopy(self.adc)
                    adc["cases"][index]["result"][field] = value
                    self.assert_suite_not_pass(adc)

    def test_invalid_validation_pvt_hash_and_phase_energy_raise(self):
        for field, value in (("temp_C", 85), ("stimulus_sha256", "changed-stimulus")):
            with self.subTest(field=field):
                adc = copy.deepcopy(self.adc)
                adc["cases"][0]["result"][field] = value
                with self.assertRaises(ValueError):
                    self.load(adc=adc)
        adc = copy.deepcopy(self.adc)
        adc["cases"][0]["result"]["energy"]["d"]["total_fJ_per_conversion"] += 100
        with self.assertRaises(ValueError):
            self.load(adc=adc)
        array = copy.deepcopy(self.array)
        array["share_settling_repair"][0]["temp_C"] = -40
        with self.assertRaises(ValueError):
            self.load(array=array)

    def test_signed_net_or_nonpositive_energy_cannot_replace_delivery(self):
        for variant in ("signed_net", "zero", "negative"):
            with self.subTest(variant=variant):
                adc = copy.deepcopy(self.adc)
                energy = adc["cases"][0]["result"]["energy"]
                if variant == "signed_net":
                    energy["d"] = copy.deepcopy(energy["p"])
                else:
                    factor = 0 if variant == "zero" else -1
                    for key, value in energy["d"].items():
                        energy["d"][key] = ({k: factor * v for k, v in value.items()}
                                            if isinstance(value, dict) else factor * value)
                with self.assertRaises(ValueError):
                    self.load(adc=adc)

    def test_missing_and_duplicate_regressions_cannot_complete_coverage(self):
        documents = self.regression_documents()
        missing_name = next(iter(documents))
        incomplete = dict(documents)
        del incomplete[missing_name]
        duplicate = copy.deepcopy(documents)
        duplicate[missing_name] = copy.deepcopy(documents[list(documents)[1]])
        for records, missing in (({}, ()), (incomplete, ()),
                                 (incomplete, (missing_name,)), (duplicate, ())):
            with self.subTest(paths=list(records), missing=missing):
                evidence = self.load(regressions=records, missing=missing)
                self.assertTrue(all(e["adc_regression_status"] == "INCOMPLETE" for e in evidence))
                if missing:
                    self.assertIn("MISSING", [c["status"] for c in evidence[0]["adc_regression_checks"]])

    def test_regression_failure_survives_complete_coverage(self):
        documents = self.regression_documents()
        self.assertTrue(all(e["adc_regression_status"] == "PASS" for e in self.load(regressions=documents)))
        for field in ("numerical_accuracy_pass", "feedback_pass"):
            with self.subTest(field=field):
                failed = copy.deepcopy(documents)
                next(iter(failed.values()))["cases"][0]["result"][field] = False
                self.assertTrue(all(e["adc_regression_status"] == "FAIL" for e in self.load(regressions=failed)))

    def test_regression_must_match_candidate_and_physical_fixture(self):
        for field, value in (("temp_C", 85), ("bridge_error", .3), ("physical_decisions", 9),
                             ("warmup_frames", 0), ("closing_frames", 0), ("simulated_frames", 1)):
            with self.subTest(field=field):
                documents = self.regression_documents()
                next(iter(documents.values()))["cases"][0]["result"][field] = value
                with self.assertRaises(ValueError):
                    self.load(regressions=documents)
        documents = self.regression_documents()
        next(iter(documents.values()))["config"]["reference_trim_uv"] += 100
        with self.assertRaises(ValueError):
            self.load(regressions=documents)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(EvidenceAdapterTests))
    print("PASS: cached evidence adapter controls" if result.wasSuccessful() else "FAIL: evidence adapter controls")
    raise SystemExit(0 if result.wasSuccessful() else 1)
