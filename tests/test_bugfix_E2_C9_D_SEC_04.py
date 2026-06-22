"""Regression test for bug E2_C9_D-SEC-04.

``claude_code_invoker`` previously mutated ``os.environ`` with BMAD_AUTO_*
keys and never restored them. The same parent process was therefore
contaminated across sequential dispatcher invocations, breaking
session-attribution and any cleanup code that reads ``os.environ``
between sessions.

The fix: snapshot prior values, propagate BMAD_AUTO_* to the subprocess
spawn through the parent env (so ``tmux new-session -e`` sees them),
then restore the parent env in a ``finally`` block — including removing
keys that did not previously exist.
"""
from __future__ import annotations

import os
import unittest
from typing import Any
from unittest import mock

from story_automator.core import cli_dispatcher_invokers as invokers
from story_automator.core.cli_dispatcher import SessionIntent
from story_automator.core.cli_profile import claude_default


_BMAD_KEYS = (
    "BMAD_AUTO_STORY_KEY",
    "BMAD_AUTO_PHASE",
    "BMAD_AUTO_CLI_ID",
    "BMAD_AUTO_COMMIT_SHA",
    "BMAD_AUTO_TASK_ID",
)


def _intent(story_key: str = "STORY-1", phase: str = "dev-running") -> SessionIntent:
    return SessionIntent(
        story_key=story_key,
        phase=phase,
        baseline_sha="b" * 40,
        prompt="/skill do-thing",
        workspace="/tmp/ws",
        timeout_s=1800.0,
    )


def _stub_targets() -> dict[str, mock.Mock]:
    return {
        "_spawn_session_hook": mock.Mock(return_value=("ok", 0)),
        "_session_status_hook": mock.Mock(
            return_value={"status": "completed", "session_state": "success"}
        ),
        "_verify_output_hook": mock.Mock(return_value="/tmp/output.txt"),
        "_read_output_hook": mock.Mock(return_value="done"),
        "_git_head_hook": mock.Mock(return_value="a" * 40),
        "_clock_hook": mock.Mock(return_value=0.0),
        "_sleep_hook": mock.Mock(),
        "_kill_session_hook": mock.Mock(),
    }


class BugfixE2C9DSEC04Tests(unittest.TestCase):
    """Parent ``os.environ`` must not be contaminated across invocations."""

    def setUp(self) -> None:
        # Snapshot any pre-existing values and clear so each test starts
        # from a known state. Restore in tearDown.
        self._saved: dict[str, str | None] = {
            k: os.environ.pop(k, None) for k in _BMAD_KEYS
        }

    def tearDown(self) -> None:
        for k in _BMAD_KEYS:
            os.environ.pop(k, None)
        for k, v in self._saved.items():
            if v is not None:
                os.environ[k] = v

    def _patch_hooks(self, targets: dict[str, Any]) -> list[Any]:
        patchers: list[Any] = []
        for name, value in targets.items():
            p = mock.patch.object(invokers, name, value)
            p.start()
            patchers.append(p)
        return patchers

    def _stop(self, patchers: list[Any]) -> None:
        for p in patchers:
            p.stop()

    # ----------------------------------------------------------------
    # Test 1: env is restored to "absent" after the call when the keys
    # were absent beforehand.
    # ----------------------------------------------------------------
    def test_env_keys_are_removed_after_call_when_absent_beforehand(self) -> None:
        for k in _BMAD_KEYS:
            self.assertNotIn(k, os.environ)
        patchers = self._patch_hooks(_stub_targets())
        try:
            invokers.claude_code_invoker(
                profile=claude_default(), intent=_intent(),
            )
        finally:
            self._stop(patchers)
        # After the call the keys must be back to absent — no contamination.
        for k in _BMAD_KEYS:
            self.assertNotIn(
                k, os.environ,
                msg=f"{k} leaked into os.environ across invocation",
            )

    # ----------------------------------------------------------------
    # Test 2: pre-existing values are restored verbatim, not clobbered.
    # ----------------------------------------------------------------
    def test_preexisting_env_values_are_restored(self) -> None:
        os.environ["BMAD_AUTO_STORY_KEY"] = "OUTER-STORY"
        os.environ["BMAD_AUTO_PHASE"] = "outer-phase"
        os.environ["BMAD_AUTO_CLI_ID"] = "outer-cli"
        os.environ["BMAD_AUTO_COMMIT_SHA"] = "outer-sha"
        os.environ["BMAD_AUTO_TASK_ID"] = "outer-task"
        patchers = self._patch_hooks(_stub_targets())
        try:
            invokers.claude_code_invoker(
                profile=claude_default(),
                intent=_intent(story_key="INNER", phase="inner-phase"),
            )
        finally:
            self._stop(patchers)
        # The original outer values are restored — not the inner ones.
        self.assertEqual(os.environ["BMAD_AUTO_STORY_KEY"], "OUTER-STORY")
        self.assertEqual(os.environ["BMAD_AUTO_PHASE"], "outer-phase")
        self.assertEqual(os.environ["BMAD_AUTO_CLI_ID"], "outer-cli")
        self.assertEqual(os.environ["BMAD_AUTO_COMMIT_SHA"], "outer-sha")
        self.assertEqual(os.environ["BMAD_AUTO_TASK_ID"], "outer-task")

    # ----------------------------------------------------------------
    # Test 3: env IS set at the moment spawn_session_hook is invoked
    # (so the child subprocess inherits BMAD_AUTO_*) — the fix must not
    # break the forwarding contract.
    # ----------------------------------------------------------------
    def test_env_keys_visible_to_spawn_hook(self) -> None:
        observed: dict[str, str | None] = {}

        def _spy(*_args: Any, **_kwargs: Any) -> tuple[str, int]:
            for k in _BMAD_KEYS:
                observed[k] = os.environ.get(k)
            return ("ok", 0)

        targets = _stub_targets()
        targets["_spawn_session_hook"] = mock.Mock(side_effect=_spy)
        patchers = self._patch_hooks(targets)
        try:
            invokers.claude_code_invoker(
                profile=claude_default(),
                intent=_intent(story_key="STORY-X", phase="dev-running"),
            )
        finally:
            self._stop(patchers)
        # Inside spawn_session_hook, BMAD_AUTO_* are set on os.environ so
        # run_cmd's subprocess.run inherits them via os.environ.copy().
        self.assertEqual(observed["BMAD_AUTO_STORY_KEY"], "STORY-X")
        self.assertEqual(observed["BMAD_AUTO_PHASE"], "dev-running")
        self.assertEqual(observed["BMAD_AUTO_CLI_ID"], "claude-code")

    # ----------------------------------------------------------------
    # Test 4: env is restored even if spawn_session_hook raises.
    # ----------------------------------------------------------------
    def test_env_restored_on_spawn_exception(self) -> None:
        targets = _stub_targets()
        targets["_spawn_session_hook"] = mock.Mock(
            side_effect=RuntimeError("boom"),
        )
        patchers = self._patch_hooks(targets)
        try:
            with self.assertRaises(RuntimeError):
                invokers.claude_code_invoker(
                    profile=claude_default(), intent=_intent(),
                )
        finally:
            self._stop(patchers)
        # Even after an exception the keys do not leak.
        for k in _BMAD_KEYS:
            self.assertNotIn(
                k, os.environ,
                msg=f"{k} leaked into os.environ after spawn exception",
            )


if __name__ == "__main__":
    unittest.main()
