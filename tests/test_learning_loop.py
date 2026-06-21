import tempfile
import unittest
from unittest.mock import patch

from story_automator.core.learning_loop import (
    record_gate_for_learning,
    run_learning_loop,
)


def _make_gate_file(
    gate_id="g-001", overall="PASS", profile_id="default",
    profile_hash="aabb", categories=None,
):
    return {
        "gate_id": gate_id,
        "schema_version": 1,
        "target": {"kind": "story", "id": "E1-001"},
        "tier": "code",
        "commit_sha": "abc123",
        "scanner_data_snapshot": "",
        "profile": {"id": profile_id, "version": 1, "hash": profile_hash},
        "factory_version": "1.15.0",
        "risk_profile_ref": "",
        "categories": categories or {
            "correctness": {"verdict": "PASS", "rationale": "ok"},
        },
        "overall": overall,
        "waivers": [],
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
        "categories": {"code": ["correctness"], "system": []},
        "categories_na": [], "rules": {}, "timeouts": {},
        "cost_tier": {}, "forbidden_until": {},
        "invariants": {}, "toolchain": {}, "seed_template": {},
    }


class RecordGateForLearningTests(unittest.TestCase):
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

    def test_records_to_history(self) -> None:
        gf = _make_gate_file()
        path = record_gate_for_learning(self.tmp, gf, story_key="E1-001")
        self.assertTrue(path.is_file())


class RunLearningLoopTests(unittest.TestCase):
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

    def test_empty_history_returns_summary(self) -> None:
        result = run_learning_loop(self.tmp, profile=_make_profile())
        self.assertEqual(result["metrics"]["total_gates"], 0)
        self.assertEqual(result["calibrations_applied"], [])

    def test_with_history_computes_metrics(self) -> None:
        for i in range(3):
            record_gate_for_learning(
                self.tmp, _make_gate_file(gate_id=f"g-{i}"),
                story_key=f"E1-{i:03d}",
            )
        result = run_learning_loop(self.tmp, profile=_make_profile())
        self.assertEqual(result["metrics"]["total_gates"], 3)

    def test_returns_retrospective_markdown(self) -> None:
        record_gate_for_learning(
            self.tmp, _make_gate_file(), story_key="E1-001",
        )
        result = run_learning_loop(self.tmp, profile=_make_profile())
        self.assertIn("Gate Quality Summary", result["retrospective_md"])


if __name__ == "__main__":
    unittest.main()
