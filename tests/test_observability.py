# tests/test_observability.py
"""Wave D: run_id correlation on tmux lifecycle events, live duration/capture
fields, and a best-effort guarded telemetry emit."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from story_automator.commands import orchestrator
from story_automator.core import tmux_runtime
from story_automator.core.common import iso_now
from story_automator.core.run_identity import current_run_id
from story_automator.core.runtime_layout import active_marker_path


class _RecordingEmitter:
    def __init__(self) -> None:
        self.events: list = []

    def emit(self, event) -> None:
        self.events.append(event)


class TmuxLifecycleRunIdTests(unittest.TestCase):
    def _emit_completed(self, tmp: Path, state: dict):
        rec = _RecordingEmitter()
        with mock.patch.object(
            tmux_runtime, "emitter_for_project_root", side_effect=lambda _r: rec
        ):
            tmux_runtime._emit_tmux_completed("sa-1-2-review", state, str(tmp))
        return rec.events[0]

    def test_completed_event_carries_marker_derived_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            marker = active_marker_path(str(tmp))
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(
                json.dumps({"createdAt": iso_now(), "epic": "2", "pid": 5}),
                encoding="utf-8",
            )
            event = self._emit_completed(tmp, {"exitCode": 0})
            self.assertTrue(event.run_id.startswith("run-"))
            self.assertEqual(event.run_id, current_run_id(str(tmp)))

    def test_completed_event_run_id_empty_without_marker(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            event = self._emit_completed(Path(d), {"exitCode": 0})
            self.assertEqual(event.run_id, "")


class DurationAndCaptureFieldsTests(unittest.TestCase):
    def test_duration_derived_from_start_finish_stamps(self) -> None:
        rec = _RecordingEmitter()
        state = {
            "exitCode": 0,
            "startedAt": "2026-06-16T10:00:00Z",
            "finishedAt": "2026-06-16T10:01:40Z",  # +100s
        }
        with mock.patch.object(
            tmux_runtime, "emitter_for_project_root", side_effect=lambda _r: rec
        ):
            tmux_runtime._emit_tmux_completed("sa-1-2-dev", state, None)
        self.assertEqual(rec.events[0].duration_s, 100.0)

    def test_explicit_duration_seconds_is_preferred(self) -> None:
        rec = _RecordingEmitter()
        state = {"exitCode": 0, "durationSeconds": 42.0, "startedAt": "x", "finishedAt": "y"}
        with mock.patch.object(
            tmux_runtime, "emitter_for_project_root", side_effect=lambda _r: rec
        ):
            tmux_runtime._emit_tmux_completed("sa-1-2-dev", state, None)
        self.assertEqual(rec.events[0].duration_s, 42.0)

    def test_last_capture_chars_derived_from_output_artifact(self) -> None:
        rec = _RecordingEmitter()
        session = "sa-zz-9-9-review"
        paths = tmux_runtime.session_paths(session, None)
        paths.output.parent.mkdir(parents=True, exist_ok=True)
        paths.output.write_text("hello world", encoding="utf-8")  # 11 chars
        try:
            with mock.patch.object(
                tmux_runtime, "emitter_for_project_root", side_effect=lambda _r: rec
            ):
                tmux_runtime._emit_tmux_crashed(session, {"exitCode": 1}, None)
            self.assertEqual(rec.events[0].last_capture_chars, 11)
        finally:
            paths.output.unlink(missing_ok=True)

    def test_emit_tmux_crashed_survives_non_utf8_output(self) -> None:
        # Regression: agent died and dumped raw bytes (e.g. binary buffer, latin-1
        # paste, half-decoded utf-16). _emit_tmux_crashed must not raise — that
        # would turn a child crash into a gate-routing crash and orphan the run.
        rec = _RecordingEmitter()
        session = "sa-yy-8-8-review"
        paths = tmux_runtime.session_paths(session, None)
        paths.output.parent.mkdir(parents=True, exist_ok=True)
        # Write bytes that are NOT valid UTF-8 (lone continuation byte 0x80, etc.)
        paths.output.write_bytes(b"\x80\xff\xfe\x80hello\xc3\x28")
        try:
            with mock.patch.object(
                tmux_runtime, "emitter_for_project_root", side_effect=lambda _r: rec
            ):
                # Must not raise UnicodeDecodeError
                tmux_runtime._emit_tmux_crashed(session, {"exitCode": 1}, None)
            self.assertEqual(len(rec.events), 1)
            # last_capture_chars should be 0 (best-effort, swallowed) — the
            # critical invariant is that the crash event was emitted.
            self.assertEqual(rec.events[0].last_capture_chars, 0)
        finally:
            paths.output.unlink(missing_ok=True)


class OutputTextDecodingTests(unittest.TestCase):
    def test_output_text_returns_empty_for_non_utf8_file(self) -> None:
        # Regression: _output_text feeds session_status / _todo_counts; raising
        # UnicodeDecodeError here would crash the heartbeat loop and block gate
        # routing. The function must fail closed, returning "" on bad bytes.
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "output.bin"
            bad.write_bytes(b"\x80\xff\xfe\x80not utf-8\xc3\x28")
            # Must not raise
            self.assertEqual(tmux_runtime._output_text(bad), "")

    def test_output_text_returns_empty_for_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(tmux_runtime._output_text(Path(d) / "missing"), "")


class GuardedEmitTests(unittest.TestCase):
    def test_emit_safe_swallows_oserror(self) -> None:
        boom = mock.MagicMock()
        boom.emit.side_effect = OSError("disk full")
        with (
            mock.patch.object(orchestrator, "_telemetry_emitter", return_value=boom),
            self.assertLogs("story_automator.commands.orchestrator", level="WARNING") as logs,
        ):
            orchestrator._emit_safe(object())  # must not raise
        self.assertTrue(any("telemetry emit failed" in m for m in logs.output))


if __name__ == "__main__":
    unittest.main()
