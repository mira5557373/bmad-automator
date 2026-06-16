# tests/test_resilience.py
"""Wave C: crash detection, heartbeat refresh, and bounded control-plane probes."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from story_automator.commands import basic
from story_automator.commands import tmux as tmux_cmd
from story_automator.core import tmux_runtime
from story_automator.core.common import iso_now
from story_automator.core.runtime_layout import active_marker_path


def _run_stop_hook(marker_path: Path) -> tuple[int, str]:
    buf = io.StringIO()
    with (
        mock.patch.object(basic, "active_marker_path", return_value=marker_path),
        mock.patch("sys.stdin", io.StringIO("")),
        mock.patch.dict("os.environ", {"STORY_AUTOMATOR_CHILD": ""}, clear=False),
        contextlib.redirect_stdout(buf),
    ):
        code = basic.cmd_stop_hook([])
    return code, buf.getvalue()


class StopHookCrashDetectionTests(unittest.TestCase):
    def test_fresh_run_with_remaining_stories_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            marker = Path(d) / ".story-automator-active"
            marker.write_text(
                json.dumps({"storiesRemaining": 3, "heartbeat": iso_now()}),
                encoding="utf-8",
            )
            code, out = _run_stop_hook(marker)
            self.assertEqual(code, 0)
            self.assertIn('"decision": "block"', out)

    def test_stale_run_releases_stop_hook(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            marker = Path(d) / ".story-automator-active"
            marker.write_text(
                json.dumps(
                    {"storiesRemaining": 3, "heartbeat": "2000-01-01T00:00:00Z"}
                ),
                encoding="utf-8",
            )
            code, out = _run_stop_hook(marker)
            self.assertEqual(code, 0)
            # Crashed/stale supervisor -> allow the agent to stop (no block).
            self.assertNotIn("block", out)

    def test_missing_heartbeat_still_blocks(self) -> None:
        # Fail-safe: an undeterminable age must not be treated as crashed.
        with tempfile.TemporaryDirectory() as d:
            marker = Path(d) / ".story-automator-active"
            marker.write_text(json.dumps({"storiesRemaining": 1}), encoding="utf-8")
            code, out = _run_stop_hook(marker)
            self.assertEqual(code, 0)
            self.assertIn('"decision": "block"', out)


class MonitorHeartbeatRefreshTests(unittest.TestCase):
    def test_refresh_advances_heartbeat(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            marker = active_marker_path(str(tmp))
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(
                json.dumps({"epic": "1", "heartbeat": "2000-01-01T00:00:00Z"}),
                encoding="utf-8",
            )
            tmux_cmd._refresh_active_marker_heartbeat(str(tmp))
            payload = json.loads(marker.read_text(encoding="utf-8"))
            self.assertNotEqual(payload["heartbeat"], "2000-01-01T00:00:00Z")
            self.assertEqual(payload["epic"], "1")  # other fields preserved

    def test_refresh_is_noop_without_marker(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            # No marker written: must not raise and must not create one.
            tmux_cmd._refresh_active_marker_heartbeat(str(tmp))
            self.assertFalse(active_marker_path(str(tmp)).exists())

    def test_refresh_tolerates_corrupt_marker(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            marker = active_marker_path(str(tmp))
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text("{ corrupt", encoding="utf-8")
            tmux_cmd._refresh_active_marker_heartbeat(str(tmp))  # must not raise


class ProbeTimeoutTests(unittest.TestCase):
    def test_probe_timeout_is_bounded_well_under_default(self) -> None:
        from story_automator.core.utils import DEFAULT_COMMAND_TIMEOUT

        self.assertLess(tmux_runtime.PROBE_TIMEOUT, DEFAULT_COMMAND_TIMEOUT)
        self.assertGreater(tmux_runtime.PROBE_TIMEOUT, 0)

    def test_has_session_uses_probe_timeout(self) -> None:
        with (
            mock.patch.object(tmux_runtime, "command_exists", return_value=True),
            mock.patch.object(tmux_runtime, "run_cmd", return_value=("", 0)) as rc,
        ):
            tmux_runtime.tmux_has_session("sess")
        self.assertEqual(rc.call_args.kwargs.get("timeout"), tmux_runtime.PROBE_TIMEOUT)

    def test_display_uses_probe_timeout(self) -> None:
        with mock.patch.object(tmux_runtime, "run_cmd", return_value=("x", 0)) as rc:
            tmux_runtime.tmux_display("sess", "#{pane_width}")
        self.assertEqual(rc.call_args.kwargs.get("timeout"), tmux_runtime.PROBE_TIMEOUT)


if __name__ == "__main__":
    unittest.main()
