# tests/test_tmux_integration.py
"""Tier-2 real-tmux integration: exercise the actual tmux_runtime machinery
against a live tmux server with a STUB command (no claude, no cost). Guarded by
skipUnless(tmux) so it runs in Linux/macOS CI (which install tmux) and skips on
hosts without tmux (e.g. Windows). Complements the mocked-tmux orchestration
spine test in test_orchestration_loop.py.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

from story_automator.core import tmux_runtime as T


@unittest.skipUnless(shutil.which("tmux") and shutil.which("bash"), "requires real tmux + bash")
class TmuxRealIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="tmux-itest-")
        self.session = f"sa-itest-{os.getpid()}"
        self.addCleanup(self._kill)
        if T.tmux_has_session(self.session):
            T.tmux_kill_session(self.session)

    def _kill(self) -> None:
        try:
            if T.tmux_has_session(self.session):
                T.tmux_kill_session(self.session)
        except Exception:
            pass

    def test_real_tmux_spawn_status_capture_scrub_dupguard_kill(self) -> None:
        with mock.patch.dict(
            "os.environ",
            {"PROJECT_ROOT": self.tmp, "BMAD_AUDIT_KEY": "super-secret-test-key"},
            clear=False,
        ):
            # spawn a stub agent (NOT claude) into real tmux
            out, code = T.spawn_session(
                self.session,
                "printf 'STUB_AGENT_OUTPUT\\n'; sleep 30",
                "claude",
                project_root=self.tmp,
            )
            self.assertEqual(code, 0, f"spawn failed: {out!r}")
            self.assertTrue(T.tmux_has_session(self.session))

            time.sleep(1.5)  # let the pane produce output

            # status probe against real tmux (the PROBE_TIMEOUT control-plane path)
            st = T.session_status(self.session, full=True, codex=False, project_root=self.tmp)
            self.assertIsInstance(st, dict)
            self.assertIn("session_state", st)

            # the audit HMAC key must never leak into the child pane env
            leaked = T.tmux_show_environment(self.session, "BMAD_AUDIT_KEY")
            self.assertNotEqual(leaked, "super-secret-test-key")

            # duplicate-spawn guard refuses without disturbing the live session
            out2, code2 = T.spawn_session(self.session, "echo dup", "claude", project_root=self.tmp)
            self.assertEqual(code2, 1)
            self.assertIn("already exists", out2)
            self.assertTrue(T.tmux_has_session(self.session))

            # kill cleans up
            T.tmux_kill_session(self.session)
            time.sleep(0.3)
            self.assertFalse(T.tmux_has_session(self.session))


if __name__ == "__main__":
    unittest.main()
