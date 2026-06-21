"""End-to-end integration tests for the learning loop pipeline."""
import copy
import tempfile
import unittest
from unittest.mock import patch

from story_automator.core.gate_history import (
    count_gate_history,
    load_gate_history,
    prune_gate_history,
)
from story_automator.core.learning_loop import (
    record_gate_for_learning,
    run_learning_loop,
)
from story_automator.core.profile_versioning import (
    bump_profile_version,
    compute_breaking_hash,
    is_breaking_change,
    parse_profile_version,
)


def _make_gate_file(
    gate_id="g-001", overall="PASS",
    categories=None, profile_id="default",
):
    return {
        "gate_id": gate_id, "schema_version": 1,
        "target": {"kind": "story", "id": "E1-001"},
        "tier": "code", "commit_sha": "abc123",
        "scanner_data_snapshot": "",
        "profile": {"id": profile_id, "version": 1, "hash": "aabb"},
        "factory_version": "1.15.0", "risk_profile_ref": "",
        "categories": categories or {
            "correctness": {"verdict": "PASS", "rationale": "ok"},
        },
        "overall": overall, "waivers": [],
        "evidence_bundle_hash": "eebb",
    }


def _make_profile():
    return {
        "version": 1, "id": "default",
        "snapshot": {"relativeDir": "_bmad-output/story-automator/profile-snapshots"},
        "matrix": {
            "P0": {"coverage_pct": 100, "levels": ["unit"]},
            "P1": {"coverage_pct": 90, "levels": ["unit"]},
            "P2": {"coverage_pct": 50, "levels": ["unit"]},
            "P3": {"coverage_pct": 20, "levels": ["smoke"]},
        },
        "categories": {
            "code": ["correctness", "security", "performance"],
            "system": [],
        },
        "categories_na": [],
        "rules": {"test_quality": {"burn_in_runs": 5, "max_flaky": 0}},
        "timeouts": {"security": 300, "performance": 600},
        "cost_tier": {}, "forbidden_until": {},
        "invariants": {}, "toolchain": {}, "seed_template": {},
    }


class LearningLoopIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.patcher = patch(
            "story_automator.core.gate_history.assert_host_context",
        )
        self.patcher.start()

    def tearDown(self) -> None:
        self.patcher.stop()
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_full_pipeline_with_timeouts(self) -> None:
        """Simulate repeated timeouts -> learning loop proposes timeout increase."""
        profile = _make_profile()
        for i in range(5):
            gf = _make_gate_file(
                gate_id=f"g-{i}",
                overall="FAIL",
                categories={
                    "correctness": {"verdict": "PASS", "rationale": "ok"},
                    "performance": {
                        "verdict": "FAIL",
                        "rationale": "TIMEOUT: lighthouse exceeded 600s",
                    },
                },
            )
            record_gate_for_learning(self.tmp, gf, story_key=f"E1-{i:03d}")

        result = run_learning_loop(self.tmp, profile=profile)
        self.assertEqual(result["metrics"]["total_gates"], 5)
        self.assertIn("performance", result["metrics"]["timeout_categories"])
        timeout_proposals = [
            p for p in result["calibrations_applied"]
            if "timeout" in p.field_path
        ]
        self.assertGreater(len(timeout_proposals), 0)

    def test_full_pipeline_with_flaky(self) -> None:
        """Simulate flaky tests -> learning loop proposes burn-in increase."""
        profile = _make_profile()
        verdicts = ["PASS", "FAIL", "PASS", "FAIL", "PASS", "FAIL", "PASS"]
        for i, v in enumerate(verdicts):
            gf = _make_gate_file(
                gate_id=f"g-{i}", overall=v,
                categories={
                    "correctness": {"verdict": v, "rationale": ""},
                },
            )
            record_gate_for_learning(self.tmp, gf, story_key=f"E1-{i:03d}")

        result = run_learning_loop(self.tmp, profile=profile)
        self.assertIn("correctness", result["metrics"]["flaky_categories"])
        self.assertGreater(len(result["calibrations_deferred"]), 0)

    def test_retrospective_output_is_valid_markdown(self) -> None:
        for i in range(3):
            gf = _make_gate_file(gate_id=f"g-{i}")
            record_gate_for_learning(self.tmp, gf, story_key=f"E1-{i:03d}")
        result = run_learning_loop(self.tmp, profile=_make_profile())
        md = result["retrospective_md"]
        self.assertIn("##", md)
        self.assertIn("Gate Quality Summary", md)

    def test_profile_versioning_roundtrip(self) -> None:
        """Feature bump -> different hash -> same breaking hash."""
        profile = _make_profile()
        profile["version"] = {"breaking": 1, "feature": 0}
        bumped = bump_profile_version(profile, "feature")
        pv = parse_profile_version(bumped)
        self.assertEqual(pv.feature, 1)
        self.assertFalse(is_breaking_change(profile, bumped))
        self.assertEqual(
            compute_breaking_hash(profile),
            compute_breaking_hash(bumped),
        )

    def test_breaking_change_different_breaking_hash(self) -> None:
        profile = _make_profile()
        modified = copy.deepcopy(profile)
        modified["matrix"]["P0"]["coverage_pct"] = 95
        self.assertTrue(is_breaking_change(profile, modified))
        self.assertNotEqual(
            compute_breaking_hash(profile),
            compute_breaking_hash(modified),
        )

    def test_history_pruning_preserves_recent(self) -> None:
        for i in range(10):
            gf = _make_gate_file(gate_id=f"g-{i:03d}")
            record_gate_for_learning(self.tmp, gf, story_key=f"E1-{i:03d}")
        pruned = prune_gate_history(self.tmp, max_records=5)
        self.assertEqual(pruned, 5)
        self.assertEqual(count_gate_history(self.tmp), 5)
        remaining = load_gate_history(self.tmp)
        gate_ids = [r["gate_id"] for r in remaining]
        self.assertIn("g-009", gate_ids)
        self.assertNotIn("g-000", gate_ids)

    def test_empty_history_produces_no_calibrations(self) -> None:
        result = run_learning_loop(self.tmp, profile=_make_profile())
        self.assertEqual(result["calibrations_applied"], [])
        self.assertEqual(result["calibrations_deferred"], [])


if __name__ == "__main__":
    unittest.main()
