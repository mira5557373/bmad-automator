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


class ApplyRemediationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.story_path = Path(self.tmp) / "E1-001.md"
        self.story_path.write_text(
            "---\nStatus: in-progress\n---\n\n## Tasks\n- [ ] Existing\n",
            encoding="utf-8",
        )

    def test_writes_tasks_to_story(self) -> None:
        from story_automator.core.gate_ops import apply_remediation
        route_result = {
            "action": "remediate",
            "remediation_tasks": [
                {"title": "[AI-Review] Fix correctness: low coverage",
                 "category": "correctness", "gate_id": "g1", "rationale": "cov 40<80"},
            ],
            "review_continuation": {
                "action": "review_continuation",
                "story_key": "E1-001",
                "gate_id": "g1",
                "cycle": 1,
                "failing_categories": ["correctness"],
            },
        }
        result = apply_remediation(self.story_path, route_result)
        self.assertTrue(result["applied"])
        self.assertEqual(result["tasks_written"], 1)
        self.assertIn("review_continuation", result)
        content = self.story_path.read_text(encoding="utf-8")
        self.assertIn("[AI-Review] Fix correctness", content)

    def test_rejects_non_remediate_action(self) -> None:
        from story_automator.core.gate_ops import apply_remediation
        with self.assertRaises(ValueError):
            apply_remediation(self.story_path, {"action": "done"})

    def test_noop_with_empty_tasks(self) -> None:
        from story_automator.core.gate_ops import apply_remediation
        route_result = {
            "action": "remediate",
            "remediation_tasks": [],
            "review_continuation": {"action": "review_continuation"},
        }
        result = apply_remediation(self.story_path, route_result)
        self.assertTrue(result["applied"])
        self.assertEqual(result["tasks_written"], 0)

    def test_multiple_tasks_written(self) -> None:
        from story_automator.core.gate_ops import apply_remediation
        route_result = {
            "action": "remediate",
            "remediation_tasks": [
                {"title": "[AI-Review] Fix correctness", "category": "correctness",
                 "gate_id": "g1", "rationale": "r"},
                {"title": "[AI-Review] Fix security", "category": "security",
                 "gate_id": "g1", "rationale": "r"},
            ],
            "review_continuation": {"action": "review_continuation"},
        }
        result = apply_remediation(self.story_path, route_result)
        self.assertEqual(result["tasks_written"], 2)
        content = self.story_path.read_text(encoding="utf-8")
        self.assertIn("[AI-Review] Fix correctness", content)
        self.assertIn("[AI-Review] Fix security", content)


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


class GateSummaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    def _create_gate(self, gate_id: str, overall: str = "PASS",
                     duration_ms: int | None = None) -> None:
        gate = make_gate_file(
            gate_id=gate_id,
            target={"kind": "story", "id": f"s-{gate_id}"},
            commit_sha="abc",
            profile={"id": "test", "version": 1, "hash": "aabb"},
            factory_version="1.15.0",
            categories={"c": {"verdict": overall, "required": {}, "actual": {}, "rationale": "ok"}},
            overall=overall,
        )
        if duration_ms is not None:
            gate["duration_ms"] = duration_ms
        persist_gate_file(self.tmp, gate)

    def test_empty_project(self) -> None:
        from story_automator.core.gate_ops import gate_summary
        result = gate_summary(self.tmp)
        self.assertEqual(result["total_verdicts"], 0)
        self.assertIsNone(result["avg_duration_ms"])

    def test_counts_by_verdict(self) -> None:
        from story_automator.core.gate_ops import gate_summary
        self._create_gate("g1", "PASS")
        self._create_gate("g2", "PASS")
        self._create_gate("g3", "FAIL")
        result = gate_summary(self.tmp)
        self.assertEqual(result["total_verdicts"], 3)
        self.assertEqual(result["by_verdict"]["PASS"], 2)
        self.assertEqual(result["by_verdict"]["FAIL"], 1)

    def test_includes_parked_count(self) -> None:
        from story_automator.core.gate_ops import gate_summary
        from story_automator.core.gate_status import park_story
        park_story(self.tmp, "g1", "E1-001", "exhausted", "FAIL")
        result = gate_summary(self.tmp)
        self.assertEqual(result["parked_count"], 1)

    def test_includes_debt_count(self) -> None:
        from story_automator.core.gate_ops import gate_summary
        from story_automator.core.gate_status import record_mitigation_debt
        record_mitigation_debt(self.tmp, "g1", "E1-001", ["security"])
        result = gate_summary(self.tmp)
        self.assertEqual(result["mitigation_debt_count"], 1)

    def test_avg_duration_computed(self) -> None:
        from story_automator.core.gate_ops import gate_summary
        self._create_gate("g1", "PASS", duration_ms=1000)
        self._create_gate("g2", "PASS", duration_ms=3000)
        result = gate_summary(self.tmp)
        self.assertEqual(result["avg_duration_ms"], 2000)

    def test_avg_duration_none_without_data(self) -> None:
        from story_automator.core.gate_ops import gate_summary
        self._create_gate("g1", "PASS")
        result = gate_summary(self.tmp)
        self.assertIsNone(result["avg_duration_ms"])


if __name__ == "__main__":
    unittest.main()
