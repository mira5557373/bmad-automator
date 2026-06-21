from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from story_automator.core.risk_profile import (
    DEFAULT_RISK_THRESHOLDS,
    VALID_RISK_CATEGORIES,
    RiskProfileError,
    aggregate_risk_priority,
    has_unmitigated_risk_9,
    compute_risk_profile_ref,
    load_risk_profile,
    make_risk_entry,
    persist_risk_profile,
    risk_profile_exists,
    risk_profile_to_evidence,
    risk_score_to_priority,
    validate_risk_entry,
    validate_risk_profile,
)


class RiskCategoriesTests(unittest.TestCase):
    def test_all_six_categories_present(self) -> None:
        self.assertEqual(
            VALID_RISK_CATEGORIES,
            frozenset({"TECH", "SEC", "PERF", "DATA", "BUS", "OPS"}),
        )


class ValidateRiskEntryTests(unittest.TestCase):
    def test_valid_entry(self) -> None:
        entry = {
            "category": "SEC", "probability": 3, "impact": 3,
            "score": 9, "rationale": "critical auth flow",
        }
        validate_risk_entry(entry)

    def test_invalid_category(self) -> None:
        entry = {
            "category": "UNKNOWN", "probability": 1, "impact": 1,
            "score": 1,
        }
        with self.assertRaises(RiskProfileError):
            validate_risk_entry(entry)

    def test_probability_out_of_range(self) -> None:
        for bad in (0, 4, -1):
            with self.assertRaises(RiskProfileError):
                validate_risk_entry({
                    "category": "TECH", "probability": bad,
                    "impact": 1, "score": bad,
                })

    def test_impact_out_of_range(self) -> None:
        for bad in (0, 4, -1):
            with self.assertRaises(RiskProfileError):
                validate_risk_entry({
                    "category": "TECH", "probability": 1,
                    "impact": bad, "score": bad,
                })

    def test_score_must_equal_probability_times_impact(self) -> None:
        with self.assertRaises(RiskProfileError):
            validate_risk_entry({
                "category": "TECH", "probability": 2,
                "impact": 3, "score": 5,
            })

    def test_missing_category_raises(self) -> None:
        with self.assertRaises(RiskProfileError):
            validate_risk_entry({"probability": 1, "impact": 1, "score": 1})

    def test_boolean_probability_rejected(self) -> None:
        with self.assertRaises(RiskProfileError):
            validate_risk_entry({
                "category": "TECH", "probability": True,
                "impact": 1, "score": 1,
            })

    def test_rationale_must_be_string_if_present(self) -> None:
        with self.assertRaises(RiskProfileError):
            validate_risk_entry({
                "category": "TECH", "probability": 1,
                "impact": 1, "score": 1, "rationale": 42,
            })


class ValidateRiskProfileTests(unittest.TestCase):
    def test_valid_profile(self) -> None:
        entries = [
            {"category": "SEC", "probability": 3, "impact": 3, "score": 9},
            {"category": "TECH", "probability": 2, "impact": 2, "score": 4},
        ]
        validate_risk_profile(entries)

    def test_empty_raises(self) -> None:
        with self.assertRaises(RiskProfileError):
            validate_risk_profile([])

    def test_duplicate_category_raises(self) -> None:
        entries = [
            {"category": "SEC", "probability": 3, "impact": 3, "score": 9},
            {"category": "SEC", "probability": 1, "impact": 1, "score": 1},
        ]
        with self.assertRaises(RiskProfileError):
            validate_risk_profile(entries)

    def test_non_list_raises(self) -> None:
        with self.assertRaises(RiskProfileError):
            validate_risk_profile("not a list")


class MakeRiskEntryTests(unittest.TestCase):
    def test_computes_score(self) -> None:
        entry = make_risk_entry("PERF", 2, 3, rationale="latency risk")
        self.assertEqual(entry["score"], 6)
        self.assertEqual(entry["category"], "PERF")
        self.assertEqual(entry["rationale"], "latency risk")

    def test_invalid_category_raises(self) -> None:
        with self.assertRaises(RiskProfileError):
            make_risk_entry("INVALID", 1, 1)

    def test_score_range_1_to_9(self) -> None:
        entry_min = make_risk_entry("TECH", 1, 1)
        entry_max = make_risk_entry("TECH", 3, 3)
        self.assertEqual(entry_min["score"], 1)
        self.assertEqual(entry_max["score"], 9)


class RiskScoreToPriorityTests(unittest.TestCase):
    def test_score_9_is_p0(self) -> None:
        self.assertEqual(risk_score_to_priority(9), "P0")

    def test_scores_6_7_8_are_p1(self) -> None:
        for score in (6, 7, 8):
            self.assertEqual(risk_score_to_priority(score), "P1", f"score={score}")

    def test_scores_3_4_5_are_p2(self) -> None:
        for score in (3, 4, 5):
            self.assertEqual(risk_score_to_priority(score), "P2", f"score={score}")

    def test_scores_1_2_are_p3(self) -> None:
        for score in (1, 2):
            self.assertEqual(risk_score_to_priority(score), "P3", f"score={score}")

    def test_custom_thresholds(self) -> None:
        custom = {7: "P0", 4: "P1", 2: "P2", 1: "P3"}
        self.assertEqual(risk_score_to_priority(9, thresholds=custom), "P0")
        self.assertEqual(risk_score_to_priority(5, thresholds=custom), "P1")
        self.assertEqual(risk_score_to_priority(3, thresholds=custom), "P2")
        self.assertEqual(risk_score_to_priority(1, thresholds=custom), "P3")

    def test_out_of_range_raises(self) -> None:
        with self.assertRaises(RiskProfileError):
            risk_score_to_priority(0)
        with self.assertRaises(RiskProfileError):
            risk_score_to_priority(10)

    def test_default_thresholds_has_four_entries(self) -> None:
        self.assertEqual(len(DEFAULT_RISK_THRESHOLDS), 4)


class AggregateRiskPriorityTests(unittest.TestCase):
    def test_worst_priority_wins(self) -> None:
        entries = [
            make_risk_entry("TECH", 1, 1),   # score=1 → P3
            make_risk_entry("SEC", 3, 3),    # score=9 → P0
            make_risk_entry("PERF", 2, 2),   # score=4 → P2
        ]
        self.assertEqual(aggregate_risk_priority(entries), "P0")

    def test_single_entry(self) -> None:
        entries = [make_risk_entry("DATA", 2, 1)]  # score=2 → P3
        self.assertEqual(aggregate_risk_priority(entries), "P3")

    def test_all_low_risk(self) -> None:
        entries = [
            make_risk_entry("TECH", 1, 1),  # P3
            make_risk_entry("OPS", 1, 2),   # P3
        ]
        self.assertEqual(aggregate_risk_priority(entries), "P3")

    def test_empty_raises(self) -> None:
        with self.assertRaises(RiskProfileError):
            aggregate_risk_priority([])


class HasUnmitigatedRisk9Tests(unittest.TestCase):
    def test_no_score_9(self) -> None:
        entries = [make_risk_entry("TECH", 2, 3)]  # score=6
        self.assertFalse(has_unmitigated_risk_9(entries))

    def test_score_9_without_rationale(self) -> None:
        entries = [make_risk_entry("SEC", 3, 3)]  # score=9, no rationale
        self.assertTrue(has_unmitigated_risk_9(entries))

    def test_score_9_with_rationale(self) -> None:
        entries = [make_risk_entry("SEC", 3, 3, rationale="mitigated by WAF")]
        self.assertFalse(has_unmitigated_risk_9(entries))

    def test_mixed_some_mitigated(self) -> None:
        entries = [
            make_risk_entry("SEC", 3, 3, rationale="mitigated"),
            make_risk_entry("DATA", 3, 3),  # score=9, no rationale
        ]
        self.assertTrue(has_unmitigated_risk_9(entries))


class PersistRiskProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.entries = [
            make_risk_entry("SEC", 3, 3, rationale="auth flow"),
            make_risk_entry("TECH", 2, 2),
        ]

    def test_persist_creates_file(self) -> None:
        path = persist_risk_profile(self.tmp, "E1-001", self.entries)
        self.assertTrue(path.is_file())
        data = json.loads(path.read_text())
        self.assertEqual(data["target_id"], "E1-001")
        self.assertEqual(len(data["entries"]), 2)
        self.assertIn("created_at", data)

    def test_persist_validates_entries(self) -> None:
        with self.assertRaises(RiskProfileError):
            persist_risk_profile(self.tmp, "E1-001", [])

    def test_persist_path_under_gate_risk(self) -> None:
        path = persist_risk_profile(self.tmp, "E1-001", self.entries)
        self.assertIn("_bmad/gate/risk", path.as_posix())
        self.assertEqual(path.name, "E1-001.json")

    def test_persist_overwrites_existing(self) -> None:
        persist_risk_profile(self.tmp, "E1-001", self.entries)
        new_entries = [make_risk_entry("OPS", 1, 1)]
        path = persist_risk_profile(self.tmp, "E1-001", new_entries)
        data = json.loads(path.read_text())
        self.assertEqual(len(data["entries"]), 1)
        self.assertEqual(data["entries"][0]["category"], "OPS")


class LoadRiskProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.entries = [make_risk_entry("SEC", 3, 2)]

    def test_load_returns_persisted_data(self) -> None:
        persist_risk_profile(self.tmp, "E1-001", self.entries)
        data = load_risk_profile(self.tmp, "E1-001")
        self.assertEqual(data["target_id"], "E1-001")
        self.assertEqual(len(data["entries"]), 1)

    def test_load_missing_raises(self) -> None:
        with self.assertRaises(RiskProfileError):
            load_risk_profile(self.tmp, "no-such")

    def test_load_corrupt_raises(self) -> None:
        risk_dir = Path(self.tmp) / "_bmad" / "gate" / "risk"
        risk_dir.mkdir(parents=True)
        (risk_dir / "bad.json").write_text("not json")
        with self.assertRaises(RiskProfileError):
            load_risk_profile(self.tmp, "bad")


class RiskProfileExistsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    def test_exists_after_persist(self) -> None:
        entries = [make_risk_entry("TECH", 1, 1)]
        persist_risk_profile(self.tmp, "E1-001", entries)
        self.assertTrue(risk_profile_exists(self.tmp, "E1-001"))

    def test_not_exists_initially(self) -> None:
        self.assertFalse(risk_profile_exists(self.tmp, "E1-001"))


class RiskProfileToEvidenceTests(unittest.TestCase):
    def test_basic_evidence_record(self) -> None:
        entries = [
            make_risk_entry("SEC", 3, 3, rationale="critical"),
            make_risk_entry("TECH", 2, 1),
        ]
        evidence = risk_profile_to_evidence(entries, "E1-001")
        self.assertEqual(evidence["category"], "readiness")
        self.assertEqual(evidence["status"], "ok")
        self.assertFalse(evidence["deterministic"])
        self.assertIn("confidence", evidence)
        self.assertEqual(evidence["metrics"]["priority"], "P0")
        self.assertEqual(evidence["metrics"]["max_score"], 9)
        self.assertEqual(evidence["metrics"]["entry_count"], 2)

    def test_evidence_flags_unmitigated_risk_9(self) -> None:
        entries = [make_risk_entry("SEC", 3, 3)]
        evidence = risk_profile_to_evidence(entries, "E1-001")
        self.assertTrue(evidence["metrics"]["unmitigated_risk_9"])

    def test_evidence_with_custom_confidence(self) -> None:
        entries = [make_risk_entry("TECH", 1, 1)]
        evidence = risk_profile_to_evidence(entries, "E1-001", confidence=3)
        self.assertEqual(evidence["confidence"], 3)

    def test_collector_name(self) -> None:
        entries = [make_risk_entry("DATA", 2, 2)]
        evidence = risk_profile_to_evidence(entries, "E1-001")
        self.assertEqual(evidence["collector"], "risk_assessment")
        self.assertEqual(evidence["tool"], "tea_risk")


class ComputeRiskProfileRefTests(unittest.TestCase):
    def test_deterministic_ref(self) -> None:
        entries = [make_risk_entry("SEC", 3, 2)]
        ref1 = compute_risk_profile_ref(entries, "E1-001")
        ref2 = compute_risk_profile_ref(entries, "E1-001")
        self.assertEqual(ref1, ref2)
        self.assertTrue(len(ref1) > 0)

    def test_different_entries_different_ref(self) -> None:
        e1 = [make_risk_entry("SEC", 3, 2)]
        e2 = [make_risk_entry("SEC", 1, 1)]
        self.assertNotEqual(
            compute_risk_profile_ref(e1, "E1-001"),
            compute_risk_profile_ref(e2, "E1-001"),
        )


class ResolveTeaRiskInputsTests(unittest.TestCase):
    def test_valid_tea_output(self) -> None:
        from story_automator.core.risk_profile import resolve_tea_risk_inputs
        tea = {
            "risk": [
                {"category": "SEC", "probability": 3, "impact": 3, "score": 9, "rationale": "auth"},
                {"category": "TECH", "probability": 1, "impact": 1, "score": 1},
            ],
            "test_design": {"strategy": "risk-based"},
        }
        entries = resolve_tea_risk_inputs(tea)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["category"], "SEC")

    def test_missing_risk_key_raises(self) -> None:
        from story_automator.core.risk_profile import resolve_tea_risk_inputs
        with self.assertRaises(RiskProfileError):
            resolve_tea_risk_inputs({"test_design": {}})

    def test_non_dict_raises(self) -> None:
        from story_automator.core.risk_profile import resolve_tea_risk_inputs
        with self.assertRaises(RiskProfileError):
            resolve_tea_risk_inputs("not a dict")

    def test_invalid_risk_entries_raises(self) -> None:
        from story_automator.core.risk_profile import resolve_tea_risk_inputs
        with self.assertRaises(RiskProfileError):
            resolve_tea_risk_inputs({"risk": "not a list"})

    def test_empty_risk_list_raises(self) -> None:
        from story_automator.core.risk_profile import resolve_tea_risk_inputs
        with self.assertRaises(RiskProfileError):
            resolve_tea_risk_inputs({"risk": []})


class RiskProfileEdgeCaseTests(unittest.TestCase):
    def test_all_categories_covered(self) -> None:
        entries = [
            make_risk_entry(cat, 1, 1)
            for cat in sorted(VALID_RISK_CATEGORIES)
        ]
        validate_risk_profile(entries)
        self.assertEqual(len(entries), 6)

    def test_single_entry_min_score(self) -> None:
        entry = make_risk_entry("TECH", 1, 1)
        self.assertEqual(entry["score"], 1)
        self.assertEqual(risk_score_to_priority(1), "P3")

    def test_single_entry_max_score(self) -> None:
        entry = make_risk_entry("SEC", 3, 3)
        self.assertEqual(entry["score"], 9)
        self.assertEqual(risk_score_to_priority(9), "P0")

    def test_persist_and_load_roundtrip(self) -> None:
        tmp = tempfile.mkdtemp()
        entries = [
            make_risk_entry("TECH", 2, 3, rationale="complex migration"),
            make_risk_entry("SEC", 3, 3, rationale="auth rewrite"),
            make_risk_entry("PERF", 1, 2),
        ]
        persist_risk_profile(tmp, "E2-005", entries)
        loaded = load_risk_profile(tmp, "E2-005")
        self.assertEqual(len(loaded["entries"]), 3)
        for orig, loaded_entry in zip(entries, loaded["entries"]):
            self.assertEqual(orig["category"], loaded_entry["category"])
            self.assertEqual(orig["score"], loaded_entry["score"])

    def test_evidence_confidence_range(self) -> None:
        entries = [make_risk_entry("DATA", 2, 2)]
        for confidence in (1, 5, 10):
            evidence = risk_profile_to_evidence(entries, "E1-001", confidence=confidence)
            self.assertEqual(evidence["confidence"], confidence)

    def test_evidence_invalid_confidence_raises(self) -> None:
        from story_automator.core.gate_schema import GateSchemaError
        entries = [make_risk_entry("DATA", 2, 2)]
        with self.assertRaises(GateSchemaError):
            risk_profile_to_evidence(entries, "E1-001", confidence=0)
        with self.assertRaises(GateSchemaError):
            risk_profile_to_evidence(entries, "E1-001", confidence=11)


if __name__ == "__main__":
    unittest.main()
