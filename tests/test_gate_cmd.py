"""Tests for gate CLI commands: status, resume, invalidate, dispatch."""
from __future__ import annotations

import json
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from story_automator.commands.gate_cmd import (
    _resolve_audit_args,
    gate_dispatch,
    gate_invalidate_action,
    gate_readiness_action,
    gate_resume_action,
    gate_status_action,
)
from story_automator.core.evidence_io import persist_gate_file, write_gate_marker
from story_automator.core.gate_schema import make_gate_file
from story_automator.core.gate_status import park_story


class GateStatusActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    @patch("story_automator.commands.gate_cmd._project_root")
    def test_empty_status(self, mock_root) -> None:
        mock_root.return_value = self.tmp
        with patch("sys.stdout", new_callable=StringIO) as out:
            code = gate_status_action([])
        output = json.loads(out.getvalue())
        self.assertEqual(code, 0)
        self.assertTrue(output["ok"])
        self.assertEqual(output["parked"], [])
        self.assertFalse(output["in_progress"])

    @patch("story_automator.commands.gate_cmd._project_root")
    def test_status_with_reason_filter(self, mock_root) -> None:
        mock_root.return_value = self.tmp
        park_story(self.tmp, "g1", "E1-001", "exhausted", "FAIL")
        with patch("sys.stdout", new_callable=StringIO) as out:
            gate_status_action(["--state=exhausted"])
        output = json.loads(out.getvalue())
        self.assertEqual(len(output["parked"]), 1)

    @patch("story_automator.commands.gate_cmd._project_root")
    def test_status_shows_in_progress(self, mock_root) -> None:
        mock_root.return_value = self.tmp
        write_gate_marker(self.tmp, "g1", "abc123")
        with patch("sys.stdout", new_callable=StringIO) as out:
            gate_status_action([])
        output = json.loads(out.getvalue())
        self.assertTrue(output["in_progress"])
        self.assertEqual(output["in_progress_gate_id"], "g1")


class GateResumeActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    @patch("story_automator.commands.gate_cmd._project_root")
    def test_resume_existing(self, mock_root) -> None:
        mock_root.return_value = self.tmp
        park_story(self.tmp, "g1", "E1-001", "exhausted", "FAIL")
        with patch("sys.stdout", new_callable=StringIO) as out:
            code = gate_resume_action(["g1"])
        output = json.loads(out.getvalue())
        self.assertEqual(code, 0)
        self.assertTrue(output["ok"])
        self.assertEqual(output["story_key"], "E1-001")

    @patch("story_automator.commands.gate_cmd._project_root")
    def test_resume_nonexistent(self, mock_root) -> None:
        mock_root.return_value = self.tmp
        with patch("sys.stdout", new_callable=StringIO) as out:
            code = gate_resume_action(["no-such"])
        output = json.loads(out.getvalue())
        self.assertEqual(code, 1)
        self.assertFalse(output["ok"])

    def test_resume_missing_arg(self) -> None:
        with patch("sys.stdout", new_callable=StringIO) as out:
            code = gate_resume_action([])
        self.assertEqual(code, 1)
        json.loads(out.getvalue())


class GateInvalidateActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    def _create_gate(self, gate_id: str, target_id: str) -> None:
        gate = make_gate_file(
            gate_id=gate_id,
            target={"kind": "story", "id": target_id},
            commit_sha="abc",
            profile={"id": "t", "version": 1, "hash": "x"},
            factory_version="1.15.0",
            categories={"c": {"verdict": "PASS", "required": {}, "actual": {}, "rationale": "ok"}},
            overall="PASS",
        )
        persist_gate_file(self.tmp, gate)

    @patch("story_automator.commands.gate_cmd._project_root")
    def test_invalidate_by_target(self, mock_root) -> None:
        mock_root.return_value = self.tmp
        self._create_gate("g1", "story-1")
        self._create_gate("g2", "story-1")
        with patch("sys.stdout", new_callable=StringIO) as out:
            code = gate_invalidate_action(["story-1"])
        output = json.loads(out.getvalue())
        self.assertEqual(code, 0)
        self.assertTrue(output["ok"])
        self.assertEqual(output["invalidated_count"], 2)

    @patch("story_automator.commands.gate_cmd._project_root")
    def test_invalidate_no_matches(self, mock_root) -> None:
        mock_root.return_value = self.tmp
        with patch("sys.stdout", new_callable=StringIO) as out:
            code = gate_invalidate_action(["no-match"])
        output = json.loads(out.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(output["invalidated_count"], 0)

    def test_invalidate_missing_arg(self) -> None:
        with patch("sys.stdout", new_callable=StringIO) as out:
            code = gate_invalidate_action([])
        self.assertEqual(code, 1)
        json.loads(out.getvalue())


class GateDispatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    @patch("story_automator.commands.gate_cmd._project_root")
    def test_dispatch_status(self, mock_root) -> None:
        mock_root.return_value = self.tmp
        with patch("sys.stdout", new_callable=StringIO) as out:
            code = gate_dispatch(["status"])
        self.assertEqual(code, 0)
        output = json.loads(out.getvalue())
        self.assertTrue(output["ok"])

    def test_dispatch_no_subcommand_shows_usage(self) -> None:
        code = gate_dispatch([])
        self.assertEqual(code, 1)

    def test_dispatch_unknown_subcommand(self) -> None:
        code = gate_dispatch(["unknown"])
        self.assertEqual(code, 1)


class GateReadinessActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.profile_path = Path(self.tmp) / "skills" / "bmad-story-automator" / "data" / "profiles"
        self.profile_path.mkdir(parents=True)

    @patch("story_automator.commands.gate_cmd._project_root")
    @patch("story_automator.commands.gate_cmd.load_effective_profile")
    def test_needs_risk_exit_1(self, mock_profile, mock_root) -> None:
        mock_root.return_value = self.tmp
        mock_profile.return_value = {
            "id": "test", "version": 1,
            "matrix": {
                "P0": {"coverage_pct": 100, "levels": []},
                "P1": {"coverage_pct": 90, "levels": []},
                "P2": {"coverage_pct": 50, "levels": []},
                "P3": {"coverage_pct": 20, "levels": []},
            },
            "categories": {"code": [], "system": []},
            "categories_na": [],
            "forbidden_until": {},
        }
        with patch("sys.stdout", new_callable=StringIO) as out:
            code = gate_readiness_action(["E1-001"])
        output = json.loads(out.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(output["verdict"], "NEEDS_RISK")

    @patch("story_automator.commands.gate_cmd._project_root")
    @patch("story_automator.commands.gate_cmd.load_effective_profile")
    def test_ready_exit_0(self, mock_profile, mock_root) -> None:
        mock_root.return_value = self.tmp
        mock_profile.return_value = {
            "id": "test", "version": 1,
            "matrix": {
                "P0": {"coverage_pct": 100, "levels": []},
                "P1": {"coverage_pct": 90, "levels": []},
                "P2": {"coverage_pct": 50, "levels": []},
                "P3": {"coverage_pct": 20, "levels": []},
            },
            "categories": {"code": [], "system": []},
            "categories_na": [],
            "forbidden_until": {},
        }
        from story_automator.core.risk_profile import make_risk_entry, persist_risk_profile
        persist_risk_profile(self.tmp, "E1-001", [make_risk_entry("TECH", 1, 1)])
        with patch("sys.stdout", new_callable=StringIO) as out:
            code = gate_readiness_action(["E1-001"])
        output = json.loads(out.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(output["verdict"], "READY")

    @patch("story_automator.commands.gate_cmd._project_root")
    def test_missing_story_id_exit_2(self, mock_root) -> None:
        mock_root.return_value = self.tmp
        code = gate_readiness_action([])
        self.assertEqual(code, 2)

    @patch("story_automator.commands.gate_cmd._project_root")
    @patch("story_automator.commands.gate_cmd.load_effective_profile")
    @patch("story_automator.commands.gate_cmd.run_readiness_gate")
    @patch("story_automator.commands.gate_cmd._resolve_audit_args")
    def test_audit_args_forwarded_to_readiness_gate(
        self, mock_audit, mock_gate, mock_profile, mock_root,
    ) -> None:
        mock_root.return_value = self.tmp
        mock_profile.return_value = {
            "id": "test", "version": 1,
            "matrix": {
                "P0": {"coverage_pct": 100, "levels": []},
                "P1": {"coverage_pct": 90, "levels": []},
                "P2": {"coverage_pct": 50, "levels": []},
                "P3": {"coverage_pct": 20, "levels": []},
            },
            "categories": {"code": [], "system": []},
            "categories_na": [],
            "forbidden_until": {},
        }
        audit_policy = {"security": {"audit_trail": True}}
        audit_path = Path(self.tmp) / "audit.jsonl"
        mock_audit.return_value = (audit_policy, audit_path)
        mock_gate.return_value = {"verdict": "NEEDS_RISK", "priority": ""}
        with patch("sys.stdout", new_callable=StringIO):
            gate_readiness_action(["E1-001"])
        _, kwargs = mock_gate.call_args
        self.assertEqual(kwargs["audit_policy"], audit_policy)
        self.assertEqual(kwargs["audit_path"], audit_path)


class ResolveAuditArgsTests(unittest.TestCase):
    def test_returns_none_pair_when_policy_unavailable(self) -> None:
        policy, path = _resolve_audit_args("/nonexistent/project")
        self.assertIsNone(policy)
        self.assertIsNone(path)


if __name__ == "__main__":
    unittest.main()
