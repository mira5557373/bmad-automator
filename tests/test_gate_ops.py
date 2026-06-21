from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from story_automator.core.gate_ops import list_verdicts
from story_automator.core.gate_schema import make_gate_file
from story_automator.core.evidence_io import persist_gate_file


class ListVerdictsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    def _create_gate(self, gate_id: str, target_id: str = "s1",
                     overall: str = "PASS") -> None:
        gate = make_gate_file(
            gate_id=gate_id,
            target={"kind": "story", "id": target_id},
            commit_sha="abc",
            profile={"id": "test", "version": 1, "hash": "aabb"},
            factory_version="1.15.0",
            categories={"correctness": {"verdict": overall, "required": {}, "actual": {}, "rationale": "ok"}},
            overall=overall,
        )
        persist_gate_file(self.tmp, gate)

    def test_empty_project_returns_empty(self) -> None:
        self.assertEqual(list_verdicts(self.tmp), [])

    def test_returns_all_verdicts(self) -> None:
        self._create_gate("g1", "s1", "PASS")
        self._create_gate("g2", "s2", "FAIL")
        result = list_verdicts(self.tmp)
        self.assertEqual(len(result), 2)

    def test_excludes_invalidated(self) -> None:
        self._create_gate("g1", "s1", "PASS")
        inv_path = Path(self.tmp) / "_bmad" / "gate" / "verdicts" / "g1.invalidated.json"
        src_path = Path(self.tmp) / "_bmad" / "gate" / "verdicts" / "g1.json"
        src_path.rename(inv_path)
        result = list_verdicts(self.tmp)
        self.assertEqual(len(result), 0)

    def test_filter_by_target(self) -> None:
        self._create_gate("g1", "s1", "PASS")
        self._create_gate("g2", "s2", "PASS")
        result = list_verdicts(self.tmp, target_filter="s1")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["gate_id"], "g1")

    def test_filter_by_verdict(self) -> None:
        self._create_gate("g1", "s1", "PASS")
        self._create_gate("g2", "s2", "FAIL")
        result = list_verdicts(self.tmp, verdict_filter="FAIL")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["gate_id"], "g2")

    def test_summary_contains_expected_keys(self) -> None:
        self._create_gate("g1", "s1", "PASS")
        result = list_verdicts(self.tmp)
        self.assertIn("gate_id", result[0])
        self.assertIn("target", result[0])
        self.assertIn("overall", result[0])
        self.assertIn("commit_sha", result[0])
        self.assertIn("factory_version", result[0])
        self.assertIn("profile_id", result[0])


class GateDoctorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    def test_healthy_empty_project(self) -> None:
        from story_automator.core.gate_ops import gate_doctor
        result = gate_doctor(self.tmp)
        self.assertTrue(result["healthy"])
        self.assertEqual(result["issues"], [])

    def test_healthy_with_valid_verdict(self) -> None:
        from story_automator.core.gate_ops import gate_doctor
        gate = make_gate_file(
            gate_id="g1",
            target={"kind": "story", "id": "s1"},
            commit_sha="abc",
            profile={"id": "test", "version": 1, "hash": "aabb"},
            factory_version="1.15.0",
            categories={"c": {"verdict": "PASS", "required": {}, "actual": {}, "rationale": "ok"}},
            overall="PASS",
        )
        persist_gate_file(self.tmp, gate)
        result = gate_doctor(self.tmp)
        self.assertTrue(result["healthy"])

    def test_detects_orphan_marker(self) -> None:
        from story_automator.core.gate_ops import gate_doctor
        from story_automator.core.evidence_io import write_gate_marker
        write_gate_marker(self.tmp, "g-orphan", "abc")
        result = gate_doctor(self.tmp)
        self.assertFalse(result["healthy"])
        issues = [i["type"] for i in result["issues"]]
        self.assertIn("orphan_marker", issues)

    def test_detects_orphan_evidence(self) -> None:
        from story_automator.core.gate_ops import gate_doctor
        evidence_dir = Path(self.tmp) / "_bmad" / "gate" / "evidence" / "orphan-gate"
        evidence_dir.mkdir(parents=True)
        (evidence_dir / "data.json").write_text("{}")
        result = gate_doctor(self.tmp)
        self.assertFalse(result["healthy"])
        issues = [i["type"] for i in result["issues"]]
        self.assertIn("orphan_evidence", issues)

    def test_detects_invalid_verdict_json(self) -> None:
        from story_automator.core.gate_ops import gate_doctor
        verdicts_dir = Path(self.tmp) / "_bmad" / "gate" / "verdicts"
        verdicts_dir.mkdir(parents=True)
        (verdicts_dir / "bad.json").write_text("not json{{{")
        result = gate_doctor(self.tmp)
        self.assertFalse(result["healthy"])
        issues = [i["type"] for i in result["issues"]]
        self.assertIn("invalid_verdict", issues)

    def test_reports_check_counts(self) -> None:
        from story_automator.core.gate_ops import gate_doctor
        result = gate_doctor(self.tmp)
        self.assertIn("checks", result)
        self.assertIsInstance(result["checks"], list)


if __name__ == "__main__":
    unittest.main()
