from __future__ import annotations

import io
import json
import sys
import unittest
import unittest.mock as mock


def _capture(callable_, *args, **kwargs):
    """Run ``callable_(*args, **kwargs)`` with stdout redirected to a
    string buffer and return ``(exit_code, parsed_json)``."""
    buf = io.StringIO()
    with mock.patch.object(sys, "stdout", buf):
        code = callable_(*args, **kwargs)
    text = buf.getvalue().strip()
    payload = json.loads(text) if text else {}
    return code, payload


class CmdCeilingCheckSurfaceTests(unittest.TestCase):
    def test_command_module_is_importable(self) -> None:
        from story_automator.commands.ceiling_check import (  # noqa: F401
            cmd_ceiling_check,
        )

    def test_cli_registers_ceiling_check_subcommand(self) -> None:
        from story_automator import cli

        err = io.StringIO()
        out = io.StringIO()
        with (
            mock.patch.object(sys, "stderr", err),
            mock.patch.object(sys, "stdout", out),
        ):
            cli.main(["ceiling-check"])
        self.assertNotIn("Unknown command: ceiling-check", err.getvalue())


class CmdCeilingCheckFlagParseTests(unittest.TestCase):
    def test_missing_gate_returns_structured_error(self) -> None:
        from story_automator.commands.ceiling_check import cmd_ceiling_check

        code, payload = _capture(cmd_ceiling_check, [])
        self.assertEqual(code, 1)
        self.assertFalse(payload.get("ok"))
        self.assertEqual(payload.get("error"), "missing_gate")

    def test_invalid_gate_returns_structured_error(self) -> None:
        from story_automator.commands.ceiling_check import cmd_ceiling_check

        code, payload = _capture(
            cmd_ceiling_check, ["--gate", "bogus", "--events", "events.jsonl"]
        )
        self.assertEqual(code, 1)
        self.assertEqual(payload.get("error"), "invalid_gate")

    def test_missing_events_path_returns_structured_error(self) -> None:
        from story_automator.commands.ceiling_check import cmd_ceiling_check

        code, payload = _capture(cmd_ceiling_check, ["--gate", "init"])
        self.assertEqual(code, 1)
        self.assertEqual(payload.get("error"), "missing_events")


if __name__ == "__main__":
    unittest.main()
