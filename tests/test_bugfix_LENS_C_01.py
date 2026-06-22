"""Regression tests for LENS-C-01.

The ``tmux name`` action documented as
``name <step> <epic> <story_id> [--cycle N]`` formerly read ``args[4]``
positionally as the cycle value. When the operator used the documented
flag form (``name dev 1 1.2 --cycle 3``), ``args[4]`` was the literal
string ``"--cycle"``, producing a session name ending in ``-r--cycle``
instead of ``-r3``. That broke spawn-then-name lookups (``spawn`` uses
the flag form internally, so subsequent ``name`` queries by the same
operator would not match).

The fix is to parse ``--cycle <value>`` from ``args[4:]`` like
:func:`_spawn` does, falling back to positional only when the flag is
absent (preserves legacy positional callers, if any).
"""
from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from story_automator.commands.tmux import cmd_tmux_wrapper


def _capture_name(args: list[str]) -> tuple[int, str]:
    """Run ``cmd_tmux_wrapper(args)`` capturing stdout. Returns (rc, out)."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cmd_tmux_wrapper(args)
    return rc, buf.getvalue().strip()


class TmuxNameCycleFlagTests(unittest.TestCase):
    """``tmux name`` must honour ``--cycle N`` per its documented synopsis."""

    def setUp(self) -> None:
        # Pin time + project slug so the assertion is deterministic on the
        # cycle portion only. ``generate_session_name`` reads both.
        slug_patcher = patch(
            "story_automator.core.tmux_runtime.project_slug",
            return_value="proj",
        )
        time_patcher = patch(
            "story_automator.core.tmux_runtime.time.strftime",
            return_value="260101-000000",
        )
        slug_patcher.start()
        time_patcher.start()
        self.addCleanup(slug_patcher.stop)
        self.addCleanup(time_patcher.stop)

    def test_flag_form_produces_r_suffix_with_cycle_value(self) -> None:
        """``name dev 1 1.2 --cycle 3`` must end in ``-r3``, not ``-r--cycle``."""
        rc, out = _capture_name(["name", "dev", "1", "1.2", "--cycle", "3"])
        self.assertEqual(rc, 0)
        self.assertTrue(
            out.endswith("-r3"),
            f"expected session name to end with -r3, got: {out!r}",
        )
        self.assertNotIn(
            "--cycle",
            out,
            "session name must never contain the literal --cycle flag",
        )

    def test_no_cycle_flag_omits_r_suffix(self) -> None:
        """Without ``--cycle``, the name must have no ``-rN`` suffix."""
        rc, out = _capture_name(["name", "dev", "1", "1.2"])
        self.assertEqual(rc, 0)
        # The name template ends ``-{step}`` when cycle is empty.
        self.assertTrue(
            out.endswith("-dev"),
            f"expected name to end with -dev when cycle omitted, got: {out!r}",
        )

    def test_name_matches_spawn_generated_name_for_same_inputs(self) -> None:
        """``spawn`` and ``name`` must agree on the session id for identical args.

        This is the operational scenario LENS-C-01 broke: an operator does
        ``spawn ... --cycle 3``, then later asks ``name ... --cycle 3`` to
        look up that same session. Before the fix, spawn produced ``-r3``
        and name produced ``-r--cycle`` — guaranteed mismatch.
        """
        # We can't run spawn end-to-end here (it'd shell out), but we can
        # exercise the same name-generation path spawn uses by importing it.
        from story_automator.core.tmux_runtime import generate_session_name

        spawn_name = generate_session_name("dev", "1", "1.2", "3")
        _, name_out = _capture_name(["name", "dev", "1", "1.2", "--cycle", "3"])
        self.assertEqual(spawn_name, name_out)


if __name__ == "__main__":
    unittest.main()
