# tests/test_security_audit_key.py
"""Wave E: the audit HMAC signing key must never reach a spawned child shell."""

from __future__ import annotations

import unittest
from unittest import mock

from story_automator.core import tmux_runtime


def _new_session_args(calls) -> list[str] | None:
    for call in calls:
        args = list(call.args)
        if "new-session" in args:
            return args
    return None


class AuditKeyScrubTests(unittest.TestCase):
    def _spawn_and_capture(self, spawn_mode: str) -> list[str]:
        calls = []

        def fake_run_cmd(*args, **kwargs):
            calls.append(mock.call(*args, **kwargs))
            return ("", 0)

        with (
            mock.patch.object(tmux_runtime, "tmux_has_session", return_value=False),
            mock.patch.object(tmux_runtime, "_resolve_spawn_mode", return_value=spawn_mode),
            mock.patch.object(tmux_runtime, "command_exists", return_value=True),
            mock.patch.object(tmux_runtime, "resolve_command_shell", return_value="/bin/bash"),
            mock.patch.object(tmux_runtime.shutil, "which", return_value="/bin/bash"),
            mock.patch.object(tmux_runtime, "run_cmd", side_effect=fake_run_cmd),
            mock.patch.object(tmux_runtime, "tmux_display", return_value=""),
            mock.patch.object(tmux_runtime, "cleanup_runtime_artifacts"),
            mock.patch.object(tmux_runtime, "cleanup_stale_terminal_artifacts"),
            mock.patch.object(tmux_runtime, "_write_private_text"),
            mock.patch.object(tmux_runtime, "_emit_tmux_spawned"),
        ):
            tmux_runtime.spawn_session("sess-x", "echo hi", "claude", project_root="/tmp/proj")
        args = _new_session_args(calls)
        self.assertIsNotNone(args, f"no tmux new-session call captured ({spawn_mode})")
        return args

    def test_runner_spawn_scrubs_audit_key(self) -> None:
        args = self._spawn_and_capture("runner")
        self.assertIn("BMAD_AUDIT_KEY=", args)

    def test_legacy_spawn_scrubs_audit_key(self) -> None:
        args = self._spawn_and_capture("legacy")
        self.assertIn("BMAD_AUDIT_KEY=", args)

    def test_scrub_value_reads_as_absent_to_audit_loader(self) -> None:
        # tmux -e VAR= sets it empty; the audit loader treats empty as absent.
        from story_automator.core.audit import load_key_from_env

        self.assertIsNone(load_key_from_env({"BMAD_AUDIT_KEY": ""}))


if __name__ == "__main__":
    unittest.main()
