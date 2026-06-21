import unittest

from story_automator.core.profile_calibrator import (
    CalibrationProposal,
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


if __name__ == "__main__":
    unittest.main()
