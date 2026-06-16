# tests/test_wire_tmux_runtime.py
from __future__ import annotations

import json
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

from story_automator.core import tmux_runtime
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


class StoryKeyFromSessionNameTests(unittest.TestCase):
    def test_extracts_dotted_story_id_from_runner_session_name(self) -> None:
        self.assertEqual(
            tmux_runtime._story_key_from_session_name(
                "sa-acme-251215-104500-e2-s2-7-dev"
            ),
            "2.7",
        )

    def test_extracts_with_cycle_suffix(self) -> None:
        self.assertEqual(
            tmux_runtime._story_key_from_session_name(
                "sa-acme-251215-104500-e10-s10-12-review-r2"
            ),
            "10.12",
        )

    def test_returns_empty_for_unparseable_name(self) -> None:
        self.assertEqual(tmux_runtime._story_key_from_session_name("manual"), "")

    def test_returns_empty_for_empty_string(self) -> None:
        self.assertEqual(tmux_runtime._story_key_from_session_name(""), "")

    def test_slug_containing_similar_fragment_does_not_win(self) -> None:
        # Project slug "my-e2-s1-1-tool" would tempt a greedy re.search; the
        # anchored regex must skip it and pick the real suffix at end-of-string.
        self.assertEqual(
            tmux_runtime._story_key_from_session_name(
                "sa-my-e2-s1-1-tool-251215-104500-e9-s9-4-dev"
            ),
            "9.4",
        )


class EmitTmuxSpawnedWiringTests(unittest.TestCase):
    def test_emit_spawned_populates_story_key_from_session_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            emitter, factory = _patched_emitter_factory(tmp)
            with (
                mock.patch.object(
                    tmux_runtime, "emitter_for_project_root", side_effect=factory
                ),
                mock.patch.object(tmux_runtime, "_session_pid", return_value="99"),
                mock.patch.object(tmux_runtime, "run_cmd", return_value=("200x50", 0)),
            ):
                tmux_runtime._emit_tmux_spawned(
                    "sa-acme-251215-104500-e4-s4-9-dev", project_root=str(tmp)
                )
            events = _read_lines(tmp / "events.jsonl")
            self.assertEqual(len(events), 1)
            ev = events[0]
            self.assertEqual(ev["event_type"], "tmux_session_spawned")
            self.assertEqual(ev["session_name"], "sa-acme-251215-104500-e4-s4-9-dev")
            self.assertEqual(ev["story_key"], "4.9")
            self.assertEqual(ev["pid"], 99)
            self.assertEqual(ev["pane_geometry"], "200x50")


class EmitTmuxCompletedWiringTests(unittest.TestCase):
    def test_emit_completed_populates_story_key_and_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            _, factory = _patched_emitter_factory(tmp)
            state = {"exitCode": 0, "durationSeconds": 12.5}
            with mock.patch.object(
                tmux_runtime, "emitter_for_project_root", side_effect=factory
            ):
                tmux_runtime._emit_tmux_completed(
                    "sa-acme-251215-104500-e5-s5-2-review",
                    state,
                    str(tmp),
                )
            events = _read_lines(tmp / "events.jsonl")
            self.assertEqual(len(events), 1)
            ev = events[0]
            self.assertEqual(ev["event_type"], "tmux_session_completed")
            self.assertEqual(ev["story_key"], "5.2")
            self.assertEqual(ev["exit_code"], 0)
            self.assertEqual(ev["duration_s"], 12.5)


class EmitTmuxCrashedWiringTests(unittest.TestCase):
    def test_emit_crashed_populates_story_key_and_capture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            _, factory = _patched_emitter_factory(tmp)
            state = {"exitCode": 137, "lastCaptureChars": 1024}
            with mock.patch.object(
                tmux_runtime, "emitter_for_project_root", side_effect=factory
            ):
                tmux_runtime._emit_tmux_crashed(
                    "sa-acme-251215-104500-e6-s6-1-create",
                    state,
                    str(tmp),
                )
            events = _read_lines(tmp / "events.jsonl")
            self.assertEqual(len(events), 1)
            ev = events[0]
            self.assertEqual(ev["event_type"], "tmux_session_crashed")
            self.assertEqual(ev["story_key"], "6.1")
            self.assertEqual(ev["exit_code"], 137)
            self.assertEqual(ev["last_capture_chars"], 1024)
