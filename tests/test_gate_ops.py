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


if __name__ == "__main__":
    unittest.main()
