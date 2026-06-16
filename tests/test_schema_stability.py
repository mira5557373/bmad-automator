# tests/test_schema_stability.py
"""Wave J: session-state schemaVersion is quarantined, not silently downgraded."""

from __future__ import annotations

import json
import tempfile
import unittest
from unittest import mock

from story_automator.core import tmux_runtime


def _write_state(session: str, root: str, version) -> None:
    paths = tmux_runtime.session_paths(session, root)
    paths.state.parent.mkdir(parents=True, exist_ok=True)
    payload = {"last_todos_done": 0, "last_todos_total": 0}
    if version is not None:
        payload["schemaVersion"] = version
    paths.state.write_text(json.dumps(payload), encoding="utf-8")


class StatusModeSchemaTests(unittest.TestCase):
    def _mode(self, session: str, root: str) -> str:
        # mode=None + no SA_TMUX_RUNTIME env -> "auto" -> reaches the schema gate.
        with mock.patch.dict("os.environ", {"SA_TMUX_RUNTIME": "auto"}, clear=False):
            return tmux_runtime._status_mode(session, root, None)

    def test_current_version_is_runner(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            _write_state("sa-1-1-1-curr", d, tmux_runtime.STATE_SCHEMA_VERSION)
            self.assertEqual(self._mode("sa-1-1-1-curr", d), "runner")

    def test_absent_version_is_legacy(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            _write_state("sa-1-1-1-leg", d, None)
            self.assertEqual(self._mode("sa-1-1-1-leg", d), "legacy")

    def test_future_version_is_read_best_effort_with_warning_not_legacy(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            _write_state("sa-1-1-1-fut", d, tmux_runtime.STATE_SCHEMA_VERSION + 5)
            with self.assertLogs("story_automator.core.tmux_runtime", level="WARNING") as logs:
                mode = self._mode("sa-1-1-1-fut", d)
            # Must NOT silently downgrade a newer-format state to the legacy reader.
            self.assertEqual(mode, "runner")
            self.assertTrue(any("newer than supported" in m for m in logs.output))


if __name__ == "__main__":
    unittest.main()
