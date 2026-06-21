import copy
import unittest

from story_automator.core.profile_calibrator import (
    CalibrationProposal,
    apply_calibrations,
    propose_all_calibrations,
    propose_burnin_calibrations,
    propose_timeout_calibrations,
)


_BASE_PROFILE = {
    "version": {"breaking": 1, "feature": 0},
    "id": "test",
    "matrix": {
        "P0": {"coverage_pct": 100, "levels": ["unit"]},
        "P1": {"coverage_pct": 90, "levels": ["unit"]},
        "P2": {"coverage_pct": 50, "levels": ["unit"]},
        "P3": {"coverage_pct": 20, "levels": ["smoke"]},
    },
    "categories": {"code": ["correctness", "security"], "system": []},
    "categories_na": [],
    "rules": {},
    "timeouts": {"security": 300},
    "cost_tier": {},
    "forbidden_until": {},
    "invariants": {},
    "toolchain": {},
    "seed_template": {},
    "snapshot": {"relativeDir": "_bmad-output/story-automator/profile-snapshots"},
}


class CalibrationProposalTests(unittest.TestCase):
    def test_dataclass_fields(self) -> None:
        p = CalibrationProposal(
            category="security",
            field_path="timeouts.security",
            old_value=300,
            new_value=450,
            rationale="timeout rate 40%",
            confidence=0.85,
            change_type="feature",
        )
        self.assertEqual(p.category, "security")
        self.assertEqual(p.change_type, "feature")


class ProposeTimeoutCalibrationsTests(unittest.TestCase):
    def test_no_timeouts_no_proposals(self) -> None:
        metrics = {
            "timeout_categories": [],
            "per_category": {},
        }
        proposals = propose_timeout_calibrations(metrics, _BASE_PROFILE)
        self.assertEqual(proposals, [])

    def test_timeout_category_gets_increase_proposal(self) -> None:
        metrics = {
            "timeout_categories": ["security"],
            "per_category": {
                "security": {
                    "timeout_count": 4,
                    "pass_count": 1,
                    "fail_count": 4,
                    "concerns_count": 0,
                    "na_count": 0,
                },
            },
        }
        proposals = propose_timeout_calibrations(metrics, _BASE_PROFILE)
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0].category, "security")
        self.assertGreater(proposals[0].new_value, 300)
        self.assertEqual(proposals[0].change_type, "feature")

    def test_timeout_increase_capped(self) -> None:
        metrics = {
            "timeout_categories": ["security"],
            "per_category": {
                "security": {
                    "timeout_count": 10, "pass_count": 0,
                    "fail_count": 10, "concerns_count": 0, "na_count": 0,
                },
            },
        }
        proposals = propose_timeout_calibrations(metrics, _BASE_PROFILE)
        self.assertLessEqual(proposals[0].new_value, 600)


class ProposeBurninCalibrationsTests(unittest.TestCase):
    def test_no_flaky_no_proposals(self) -> None:
        metrics = {"flaky_categories": [], "per_category": {}}
        proposals = propose_burnin_calibrations(metrics, _BASE_PROFILE)
        self.assertEqual(proposals, [])

    def test_flaky_category_proposes_burnin_increase(self) -> None:
        profile = copy.deepcopy(_BASE_PROFILE)
        profile["rules"]["test_quality"] = {"burn_in_runs": 5, "max_flaky": 0}
        metrics = {
            "flaky_categories": ["correctness"],
            "per_category": {"correctness": {
                "pass_count": 5, "fail_count": 5,
                "concerns_count": 0, "na_count": 0, "timeout_count": 0,
            }},
        }
        proposals = propose_burnin_calibrations(metrics, profile)
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0].field_path, "rules.test_quality.burn_in_runs")
        self.assertGreater(proposals[0].new_value, 5)
        self.assertEqual(proposals[0].change_type, "breaking")

    def test_burnin_capped_at_max(self) -> None:
        profile = copy.deepcopy(_BASE_PROFILE)
        profile["rules"]["test_quality"] = {"burn_in_runs": 18, "max_flaky": 0}
        metrics = {
            "flaky_categories": ["correctness"],
            "per_category": {"correctness": {
                "pass_count": 5, "fail_count": 5,
                "concerns_count": 0, "na_count": 0, "timeout_count": 0,
            }},
        }
        proposals = propose_burnin_calibrations(metrics, profile)
        if proposals:
            self.assertLessEqual(proposals[0].new_value, 20)


class ProposeAllCalibrationsTests(unittest.TestCase):
    def test_combines_timeout_and_burnin(self) -> None:
        profile = copy.deepcopy(_BASE_PROFILE)
        profile["rules"]["test_quality"] = {"burn_in_runs": 5, "max_flaky": 0}
        metrics = {
            "timeout_categories": ["security"],
            "flaky_categories": ["correctness"],
            "per_category": {
                "security": {
                    "timeout_count": 4, "pass_count": 1,
                    "fail_count": 4, "concerns_count": 0, "na_count": 0,
                },
                "correctness": {
                    "pass_count": 5, "fail_count": 5,
                    "concerns_count": 0, "na_count": 0, "timeout_count": 0,
                },
            },
        }
        proposals = propose_all_calibrations(metrics, profile)
        categories = [p.category for p in proposals]
        self.assertIn("security", categories)

    def test_empty_metrics_empty_proposals(self) -> None:
        metrics = {
            "timeout_categories": [],
            "flaky_categories": [],
            "per_category": {},
        }
        proposals = propose_all_calibrations(metrics, _BASE_PROFILE)
        self.assertEqual(proposals, [])


class ApplyCalibrationsTests(unittest.TestCase):
    def test_apply_feature_change(self) -> None:
        profile = copy.deepcopy(_BASE_PROFILE)
        proposal = CalibrationProposal(
            category="security",
            field_path="timeouts.security",
            old_value=300, new_value=450,
            rationale="timeout rate", confidence=0.85,
            change_type="feature",
        )
        updated, applied, deferred = apply_calibrations(profile, [proposal])
        self.assertEqual(updated["timeouts"]["security"], 450)
        self.assertEqual(len(applied), 1)
        self.assertEqual(len(deferred), 0)

    def test_defer_breaking_change_by_default(self) -> None:
        profile = copy.deepcopy(_BASE_PROFILE)
        profile["rules"]["test_quality"] = {"burn_in_runs": 5}
        proposal = CalibrationProposal(
            category="correctness",
            field_path="rules.test_quality.burn_in_runs",
            old_value=5, new_value=7,
            rationale="flaky", confidence=0.8,
            change_type="breaking",
        )
        updated, applied, deferred = apply_calibrations(profile, [proposal])
        self.assertEqual(updated["rules"]["test_quality"]["burn_in_runs"], 5)
        self.assertEqual(len(applied), 0)
        self.assertEqual(len(deferred), 1)

    def test_apply_breaking_when_allowed(self) -> None:
        profile = copy.deepcopy(_BASE_PROFILE)
        profile["rules"]["test_quality"] = {"burn_in_runs": 5}
        proposal = CalibrationProposal(
            category="correctness",
            field_path="rules.test_quality.burn_in_runs",
            old_value=5, new_value=7,
            rationale="flaky", confidence=0.8,
            change_type="breaking",
        )
        updated, applied, deferred = apply_calibrations(
            profile, [proposal], auto_apply_breaking=True,
        )
        self.assertEqual(updated["rules"]["test_quality"]["burn_in_runs"], 7)
        self.assertEqual(len(applied), 1)

    def test_original_not_mutated(self) -> None:
        profile = copy.deepcopy(_BASE_PROFILE)
        proposal = CalibrationProposal(
            category="security",
            field_path="timeouts.security",
            old_value=300, new_value=450,
            rationale="timeout", confidence=0.85,
            change_type="feature",
        )
        original = copy.deepcopy(profile)
        apply_calibrations(profile, [proposal])
        self.assertEqual(profile, original)

    def test_empty_proposals(self) -> None:
        profile = copy.deepcopy(_BASE_PROFILE)
        updated, applied, deferred = apply_calibrations(profile, [])
        self.assertEqual(updated, profile)
        self.assertEqual(applied, [])
        self.assertEqual(deferred, [])


if __name__ == "__main__":
    unittest.main()
