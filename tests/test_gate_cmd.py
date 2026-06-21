"""Tests for gate CLI commands: status, resume, invalidate, dispatch."""
from __future__ import annotations

import json
import tempfile
import unittest
from io import StringIO
from unittest.mock import patch

from story_automator.commands.gate_cmd import (
    gate_dispatch,
    gate_invalidate_action,
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


if __name__ == "__main__":
    unittest.main()
