"""N7.1 — feature-flagged migration of commands/tmux.py spawn_session through cli_dispatcher.

These tests exercise the BMAD_AUTO_USE_CLI_DISPATCHER feature-flag dispatch
in :mod:`story_automator.commands.tmux`. The flag controls whether the
legacy ``spawn_session`` direct call is used (default, off) or whether the
call is routed through :func:`cli_dispatcher.dispatch_session` (opt-in).

Both code paths must yield the legacy ``(out, code)`` tuple the existing
``_spawn`` caller expects.
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from story_automator.commands import tmux as tmux_cmd
from story_automator.core.cli_dispatcher import DispatchResult, SessionIntent


def _clear_flag_env() -> dict[str, str]:
    """Remove BMAD_AUTO_USE_CLI_DISPATCHER from os.environ for a clean test."""
    saved = {}
    if "BMAD_AUTO_USE_CLI_DISPATCHER" in os.environ:
        saved["BMAD_AUTO_USE_CLI_DISPATCHER"] = os.environ["BMAD_AUTO_USE_CLI_DISPATCHER"]
        del os.environ["BMAD_AUTO_USE_CLI_DISPATCHER"]
    return saved


def _restore_flag_env(saved: dict[str, str]) -> None:
    for k, v in saved.items():
        os.environ[k] = v
    if not saved and "BMAD_AUTO_USE_CLI_DISPATCHER" in os.environ:
        del os.environ["BMAD_AUTO_USE_CLI_DISPATCHER"]


class FeatureFlagDispatchTests(unittest.TestCase):
    """The flag controls which spawn path runs; both return (out, code)."""

    def setUp(self) -> None:
        self._saved = _clear_flag_env()

    def tearDown(self) -> None:
        _restore_flag_env(self._saved)
        if "BMAD_AUTO_USE_CLI_DISPATCHER" in os.environ:
            del os.environ["BMAD_AUTO_USE_CLI_DISPATCHER"]

    def test_flag_off_uses_legacy_spawn_session(self) -> None:
        """Default (flag absent): legacy spawn_session is called, dispatcher is NOT."""
        with patch.object(tmux_cmd, "spawn_session", return_value=("ok", 0)) as legacy, patch(
            "story_automator.commands.tmux.dispatch_session"
        ) as dispatcher:
            out, code = tmux_cmd._spawn_via_runtime(
                session="sa-test-1",
                command="echo hi",
                agent="claude",
                root="/tmp/proj",
                story_key="1.2",
                phase="dev-running",
            )
        self.assertEqual((out, code), ("ok", 0))
        self.assertEqual(legacy.call_count, 1)
        self.assertEqual(dispatcher.call_count, 0)

    def test_flag_on_uses_cli_dispatcher(self) -> None:
        """When BMAD_AUTO_USE_CLI_DISPATCHER=1: dispatcher is called, legacy is NOT."""
        os.environ["BMAD_AUTO_USE_CLI_DISPATCHER"] = "1"
        fake = DispatchResult(
            ok=True,
            cli_id="claude-code",
            head_sha="abc",
            stop_reason="stop-hook",
            verify_outcome={},
            session_id="sa-test-2",
            stderr_tail="",
        )
        with patch.object(tmux_cmd, "spawn_session") as legacy, patch(
            "story_automator.commands.tmux.dispatch_session", return_value=fake
        ) as dispatcher, patch(
            "story_automator.commands.tmux._git_head_sha", return_value="base-sha"
        ):
            out, code = tmux_cmd._spawn_via_runtime(
                session="sa-test-2",
                command="echo hi",
                agent="claude",
                root="/tmp/proj",
                story_key="1.2",
                phase="dev-running",
            )
        self.assertEqual(code, 0)
        self.assertEqual(legacy.call_count, 0)
        self.assertEqual(dispatcher.call_count, 1)
        # The dispatcher was called positionally with a SessionIntent.
        intent = dispatcher.call_args.args[0] if dispatcher.call_args.args else dispatcher.call_args.kwargs["intent"]
        self.assertIsInstance(intent, SessionIntent)

    def test_flag_on_returns_out_code_tuple_shape(self) -> None:
        """The flag-on path must return a (str, int) tuple — same shape as legacy."""
        os.environ["BMAD_AUTO_USE_CLI_DISPATCHER"] = "true"
        fake = DispatchResult(
            ok=True,
            cli_id="claude-code",
            head_sha="abc",
            stop_reason="stop-hook",
            verify_outcome={},
            session_id="sa-x",
            stderr_tail="",
        )
        with patch.object(tmux_cmd, "spawn_session"), patch(
            "story_automator.commands.tmux.dispatch_session", return_value=fake
        ), patch("story_automator.commands.tmux._git_head_sha", return_value=""):
            result = tmux_cmd._spawn_via_runtime(
                session="sa-x",
                command="cmd",
                agent="claude",
                root="/tmp/proj",
                story_key="1.2",
                phase="dev-running",
            )
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        out, code = result
        self.assertIsInstance(out, str)
        self.assertIsInstance(code, int)

    def test_flag_on_baseline_drift_returns_nonzero_code(self) -> None:
        """When dispatcher reports baseline drift (ok=False), code != 0."""
        os.environ["BMAD_AUTO_USE_CLI_DISPATCHER"] = "1"
        fake = DispatchResult(
            ok=False,
            cli_id="claude-code",
            head_sha="base-sha",
            stop_reason="lie-detector",
            verify_outcome={"reason": "baseline_drift"},
            session_id="sa-drift",
            stderr_tail="no commits past baseline",
        )
        with patch.object(tmux_cmd, "spawn_session"), patch(
            "story_automator.commands.tmux.dispatch_session", return_value=fake
        ), patch("story_automator.commands.tmux._git_head_sha", return_value="base-sha"):
            out, code = tmux_cmd._spawn_via_runtime(
                session="sa-drift",
                command="cmd",
                agent="claude",
                root="/tmp/proj",
                story_key="1.2",
                phase="dev-running",
            )
        self.assertNotEqual(code, 0)

    def test_flag_on_passes_workspace_correctly(self) -> None:
        """SessionIntent.workspace must equal the root passed in."""
        os.environ["BMAD_AUTO_USE_CLI_DISPATCHER"] = "yes"
        fake = DispatchResult(
            ok=True,
            cli_id="claude-code",
            head_sha="abc",
            stop_reason="stop-hook",
            verify_outcome={},
            session_id="sa-w",
            stderr_tail="",
        )
        with patch.object(tmux_cmd, "spawn_session"), patch(
            "story_automator.commands.tmux.dispatch_session", return_value=fake
        ) as dispatcher, patch(
            "story_automator.commands.tmux._git_head_sha", return_value=""
        ):
            tmux_cmd._spawn_via_runtime(
                session="sa-w",
                command="cmd",
                agent="claude",
                root="/home/user/myproj",
                story_key="1.2",
                phase="dev-running",
            )
        intent = dispatcher.call_args.args[0] if dispatcher.call_args.args else dispatcher.call_args.kwargs["intent"]
        self.assertEqual(intent.workspace, "/home/user/myproj")

    def test_flag_on_passes_command_as_prompt(self) -> None:
        """SessionIntent.prompt must equal the command passed in."""
        os.environ["BMAD_AUTO_USE_CLI_DISPATCHER"] = "1"
        fake = DispatchResult(
            ok=True,
            cli_id="claude-code",
            head_sha="abc",
            stop_reason="stop-hook",
            verify_outcome={},
            session_id="sa-p",
            stderr_tail="",
        )
        with patch.object(tmux_cmd, "spawn_session"), patch(
            "story_automator.commands.tmux.dispatch_session", return_value=fake
        ) as dispatcher, patch(
            "story_automator.commands.tmux._git_head_sha", return_value=""
        ):
            tmux_cmd._spawn_via_runtime(
                session="sa-p",
                command="my-prompt-text",
                agent="claude",
                root="/tmp/proj",
                story_key="1.2",
                phase="dev-running",
            )
        intent = dispatcher.call_args.args[0] if dispatcher.call_args.args else dispatcher.call_args.kwargs["intent"]
        self.assertEqual(intent.prompt, "my-prompt-text")

    def test_flag_truthy_variants_all_enable(self) -> None:
        """Any of '1', 'true', 'True', 'yes', 'YES' must enable the dispatcher path."""
        fake = DispatchResult(
            ok=True,
            cli_id="claude-code",
            head_sha="abc",
            stop_reason="stop-hook",
            verify_outcome={},
            session_id="sa-t",
            stderr_tail="",
        )
        for value in ("1", "true", "True", "TRUE", "yes", "YES", "Yes"):
            os.environ["BMAD_AUTO_USE_CLI_DISPATCHER"] = value
            with patch.object(tmux_cmd, "spawn_session") as legacy, patch(
                "story_automator.commands.tmux.dispatch_session", return_value=fake
            ) as dispatcher, patch(
                "story_automator.commands.tmux._git_head_sha", return_value=""
            ):
                tmux_cmd._spawn_via_runtime(
                    session="sa-t",
                    command="cmd",
                    agent="claude",
                    root="/tmp/proj",
                    story_key="1.2",
                    phase="dev-running",
                )
            self.assertEqual(
                legacy.call_count, 0, msg=f"value={value!r} should enable dispatcher"
            )
            self.assertEqual(
                dispatcher.call_count, 1, msg=f"value={value!r} should enable dispatcher"
            )

    def test_flag_falsy_variants_all_disable(self) -> None:
        """'0', 'false', '', and absent must disable the dispatcher path."""
        # Test explicit falsy strings.
        for value in ("0", "false", "False", "no", "NO", ""):
            os.environ["BMAD_AUTO_USE_CLI_DISPATCHER"] = value
            with patch.object(tmux_cmd, "spawn_session", return_value=("ok", 0)) as legacy, patch(
                "story_automator.commands.tmux.dispatch_session"
            ) as dispatcher:
                tmux_cmd._spawn_via_runtime(
                    session="sa-f",
                    command="cmd",
                    agent="claude",
                    root="/tmp/proj",
                    story_key="1.2",
                    phase="dev-running",
                )
            self.assertEqual(
                legacy.call_count, 1, msg=f"value={value!r} should disable dispatcher"
            )
            self.assertEqual(
                dispatcher.call_count, 0, msg=f"value={value!r} should disable dispatcher"
            )
        # Test absence (env var unset).
        if "BMAD_AUTO_USE_CLI_DISPATCHER" in os.environ:
            del os.environ["BMAD_AUTO_USE_CLI_DISPATCHER"]
        with patch.object(tmux_cmd, "spawn_session", return_value=("ok", 0)) as legacy, patch(
            "story_automator.commands.tmux.dispatch_session"
        ) as dispatcher:
            tmux_cmd._spawn_via_runtime(
                session="sa-f",
                command="cmd",
                agent="claude",
                root="/tmp/proj",
                story_key="1.2",
                phase="dev-running",
            )
        self.assertEqual(legacy.call_count, 1)
        self.assertEqual(dispatcher.call_count, 0)

    def test_flag_on_handles_dispatcher_error(self) -> None:
        """DispatcherError must surface as a non-zero exit code with the error in stderr."""
        from story_automator.core.cli_dispatcher import DispatcherError

        os.environ["BMAD_AUTO_USE_CLI_DISPATCHER"] = "1"
        with patch.object(tmux_cmd, "spawn_session"), patch(
            "story_automator.commands.tmux.dispatch_session",
            side_effect=DispatcherError("boom"),
        ), patch("story_automator.commands.tmux._git_head_sha", return_value=""):
            out, code = tmux_cmd._spawn_via_runtime(
                session="sa-err",
                command="cmd",
                agent="claude",
                root="/tmp/proj",
                story_key="1.2",
                phase="dev-running",
            )
        self.assertNotEqual(code, 0)
        self.assertIn("boom", out)

    def test_flag_on_intent_carries_story_key_and_phase(self) -> None:
        """SessionIntent must thread story_key and phase from caller."""
        os.environ["BMAD_AUTO_USE_CLI_DISPATCHER"] = "1"
        fake = DispatchResult(
            ok=True,
            cli_id="claude-code",
            head_sha="abc",
            stop_reason="stop-hook",
            verify_outcome={},
            session_id="sa-meta",
            stderr_tail="",
        )
        with patch.object(tmux_cmd, "spawn_session"), patch(
            "story_automator.commands.tmux.dispatch_session", return_value=fake
        ) as dispatcher, patch(
            "story_automator.commands.tmux._git_head_sha", return_value=""
        ):
            tmux_cmd._spawn_via_runtime(
                session="sa-meta",
                command="cmd",
                agent="claude",
                root="/tmp/proj",
                story_key="3.4",
                phase="review-running",
            )
        intent = dispatcher.call_args.args[0] if dispatcher.call_args.args else dispatcher.call_args.kwargs["intent"]
        self.assertEqual(intent.story_key, "3.4")
        self.assertEqual(intent.phase, "review-running")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
