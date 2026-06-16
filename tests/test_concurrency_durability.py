# tests/test_concurrency_durability.py
"""Wave B: atomicity, durability, and duplicate-run/session guards."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from story_automator.commands import orchestrator
from story_automator.core import common, tmux_runtime
from story_automator.core.runtime_layout import active_marker_path
from story_automator.core.telemetry_emitter import TelemetryEmitter


def _run_cmd(fn, args: list[str]) -> tuple[int, dict]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = fn(args)
    return code, json.loads(buffer.getvalue())


class AtomicStateUpdateTests(unittest.TestCase):
    def test_state_update_persists_change_via_atomic_write(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            state = Path(d) / "orchestration-1.md"
            state.write_text("---\nstatus: active\nlastUpdated: old\n---\n", encoding="utf-8")
            with mock.patch.object(orchestrator, "audit_state_change", lambda *a, **k: None):
                code, payload = _run_cmd(
                    orchestrator._state_update, [str(state), "--set", "status=done"]
                )
            self.assertEqual(code, 0)
            self.assertIn("status", payload["updated"])
            self.assertIn("status: done", state.read_text(encoding="utf-8"))

    def test_state_update_uses_atomic_write_not_plain_write_text(self) -> None:
        # Lock in that the write goes through the atomic path (temp+fsync+replace).
        with tempfile.TemporaryDirectory() as d:
            state = Path(d) / "orchestration-1.md"
            state.write_text("---\nstatus: active\n---\n", encoding="utf-8")
            with (
                mock.patch.object(orchestrator, "audit_state_change", lambda *a, **k: None),
                mock.patch.object(orchestrator, "atomic_write") as atomic,
            ):
                _run_cmd(orchestrator._state_update, [str(state), "--set", "status=done"])
            self.assertTrue(atomic.called)


class FsyncDirTests(unittest.TestCase):
    def test_fsync_dir_is_safe_on_real_and_missing_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            common.fsync_dir(d)  # real dir: must not raise
            common.fsync_dir(Path(d) / "does-not-exist")  # missing: must not raise


class MarkerCreateLivenessGuardTests(unittest.TestCase):
    def _create(self, tmp: Path) -> tuple[int, dict | None]:
        emitter = TelemetryEmitter(tmp / "events.jsonl")
        buffer = io.StringIO()
        with (
            mock.patch.object(orchestrator, "get_project_root", return_value=str(tmp)),
            mock.patch.object(
                orchestrator, "emitter_for_project_root", side_effect=lambda _r: emitter
            ),
            contextlib.redirect_stdout(buffer),
        ):
            code = orchestrator._marker(
                [
                    "create", "--epic", "1", "--story", "1.1",
                    "--remaining", "2", "--pid", "4242",
                    "--state-file", str(tmp / "state.md"),
                ]
            )
        out = buffer.getvalue().strip()
        payload = None
        # create success prints "Marker created: ..."; refusal prints JSON.
        if out.startswith("{"):
            payload = json.loads(out.splitlines()[0])
        return code, payload

    def test_refuses_create_when_a_live_marker_already_exists(self) -> None:
        from story_automator.core.common import iso_now

        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            marker = active_marker_path(str(tmp))
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(
                json.dumps({"epic": "1", "pid": 999, "heartbeat": iso_now()}),
                encoding="utf-8",
            )
            code, payload = self._create(tmp)
            self.assertEqual(code, 1)
            self.assertEqual(payload["error"], "run_already_active")

    def test_allows_create_over_a_stale_marker(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            marker = active_marker_path(str(tmp))
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(
                json.dumps({"epic": "1", "pid": 999, "heartbeat": "2000-01-01T00:00:00Z"}),
                encoding="utf-8",
            )
            code, _ = self._create(tmp)
            self.assertEqual(code, 0)
            fresh = json.loads(marker.read_text(encoding="utf-8"))
            self.assertEqual(fresh["epic"], "1")
            self.assertEqual(fresh["storiesRemaining"], 2)

    def test_allows_create_over_a_corrupt_marker(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            marker = active_marker_path(str(tmp))
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text("{ corrupt", encoding="utf-8")
            code, _ = self._create(tmp)
            self.assertEqual(code, 0)


class DuplicateSpawnGuardTests(unittest.TestCase):
    def test_spawn_refused_when_session_already_exists(self) -> None:
        with (
            mock.patch.object(tmux_runtime, "tmux_has_session", return_value=True),
            mock.patch.object(tmux_runtime, "cleanup_runtime_artifacts") as cleanup,
            mock.patch.object(tmux_runtime, "_spawn_runner") as runner,
            mock.patch.object(tmux_runtime, "_spawn_legacy") as legacy,
        ):
            output, code = tmux_runtime.spawn_session("sess-1", "cmd", "claude")
        self.assertEqual(code, 1)
        self.assertIn("already exists", output)
        # The live session's artifacts must never be touched on a refused spawn.
        cleanup.assert_not_called()
        runner.assert_not_called()
        legacy.assert_not_called()

    def test_spawn_proceeds_when_no_existing_session(self) -> None:
        with (
            mock.patch.object(tmux_runtime, "tmux_has_session", return_value=False),
            mock.patch.object(
                tmux_runtime, "_resolve_spawn_mode", return_value="runner"
            ),
            mock.patch.object(
                tmux_runtime, "_spawn_runner", return_value=("spawned\n", 0)
            ),
            mock.patch.object(tmux_runtime, "_emit_tmux_spawned"),
        ):
            output, code = tmux_runtime.spawn_session("sess-2", "cmd", "claude")
        self.assertEqual(code, 0)
        self.assertIn("spawned", output)


if __name__ == "__main__":
    unittest.main()
