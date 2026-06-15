# tests/test_wire_orchestrator.py
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from story_automator.commands import orchestrator
from story_automator.core.telemetry_emitter import TelemetryEmitter


def _patched_emitter_factory(tmp: Path):
    emitter = TelemetryEmitter(tmp / "events.jsonl")

    def factory(_project_root):
        return emitter

    return emitter, factory


def _read_lines(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class VerifyCodeReviewWiringTests(unittest.TestCase):
    def test_review_cycle_emit_derives_epic_from_story_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            _, factory = _patched_emitter_factory(tmp)
            with (
                mock.patch.object(
                    orchestrator, "emitter_for_project_root", side_effect=factory
                ),
                mock.patch.object(
                    orchestrator, "get_project_root", return_value=str(tmp)
                ),
                mock.patch.object(
                    orchestrator,
                    "verify_code_review_completion",
                    return_value={"verified": True, "cycle": 2, "issuesFound": 0},
                ),
            ):
                rc = orchestrator._verify_code_review(["1.3"])
            self.assertEqual(rc, 0)
            events = _read_lines(tmp / "events.jsonl")
            self.assertEqual(len(events), 1)
            ev = events[0]
            self.assertEqual(ev["event_type"], "review_cycle")
            self.assertEqual(ev["story_key"], "1.3")
            self.assertEqual(ev["epic"], "1")
            self.assertEqual(ev["cycle_num"], 2)
            self.assertFalse(ev["blocking"])


class CommitReadyWiringTests(unittest.TestCase):
    def test_story_completed_emit_derives_epic_from_story_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            _, factory = _patched_emitter_factory(tmp)
            fake_status = mock.MagicMock(done=True, status="done", story="2.4")
            with (
                mock.patch.object(
                    orchestrator, "emitter_for_project_root", side_effect=factory
                ),
                mock.patch.object(
                    orchestrator, "get_project_root", return_value=str(tmp)
                ),
                mock.patch.object(
                    orchestrator, "sprint_status_get", return_value=fake_status
                ),
                mock.patch.object(
                    orchestrator, "run_cmd", return_value=("M file.py\n", 0)
                ),
            ):
                rc = orchestrator._commit_ready(["2.4"])
            self.assertEqual(rc, 0)
            events = _read_lines(tmp / "events.jsonl")
            self.assertEqual(len(events), 1)
            ev = events[0]
            self.assertEqual(ev["event_type"], "story_completed")
            self.assertEqual(ev["story_key"], "2.4")
            self.assertEqual(ev["epic"], "2")


class EscalateSessionCrashWiringTests(unittest.TestCase):
    def test_session_crash_emit_extracts_story_and_epic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            _, factory = _patched_emitter_factory(tmp)
            fake_policy = {"max_retries": 2}
            with (
                mock.patch.object(
                    orchestrator, "emitter_for_project_root", side_effect=factory
                ),
                mock.patch.object(
                    orchestrator, "get_project_root", return_value=str(tmp)
                ),
                mock.patch.object(
                    orchestrator, "load_runtime_policy", return_value=fake_policy
                ),
                mock.patch.object(orchestrator, "crash_max_retries", return_value=2),
            ):
                rc = orchestrator._escalate(
                    ["session-crash", "retries=3 story=3.7 session=sess-abc"]
                )
            self.assertEqual(rc, 0)
            events = _read_lines(tmp / "events.jsonl")
            self.assertEqual(len(events), 1)
            ev = events[0]
            self.assertEqual(ev["event_type"], "story_failed")
            self.assertEqual(ev["story_key"], "3.7")
            self.assertEqual(ev["epic"], "3")
            self.assertEqual(ev["attempts"], 3)
            self.assertEqual(ev["final_session"], "sess-abc")
            self.assertEqual(ev["error_class"], "session_crash")


class MarkerCreateWiringTests(unittest.TestCase):
    def test_marker_create_emits_story_started_with_epic_and_story(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            _, factory = _patched_emitter_factory(tmp)
            with (
                mock.patch.object(
                    orchestrator, "emitter_for_project_root", side_effect=factory
                ),
                mock.patch.object(
                    orchestrator, "get_project_root", return_value=str(tmp)
                ),
            ):
                rc = orchestrator._marker(
                    [
                        "create",
                        "--epic",
                        "8",
                        "--story",
                        "8.4",
                        "--remaining",
                        "3",
                        "--state-file",
                        str(tmp / "state.md"),
                    ]
                )
            self.assertEqual(rc, 0)
            events = _read_lines(tmp / "events.jsonl")
            started = [e for e in events if e["event_type"] == "story_started"]
            self.assertEqual(len(started), 1)
            ev = started[0]
            self.assertEqual(ev["epic"], "8")
            self.assertEqual(ev["story_key"], "8.4")
            # agent/model/complexity intentionally empty at marker site
            # (spawn-time population is M03+ scope per spec lines 8-9)
            self.assertEqual(ev["agent"], "")
            self.assertEqual(ev["model"], "")
            self.assertEqual(ev["complexity"], "")


if __name__ == "__main__":
    unittest.main()
