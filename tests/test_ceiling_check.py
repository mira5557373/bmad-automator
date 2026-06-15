from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

from story_automator.core.common import compact_json, ensure_dir
from story_automator.core.telemetry_events import StoryCompleted


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


class CmdCeilingCheckNoConfigTests(unittest.TestCase):
    def test_no_workflow_returns_allow_no_ceilings_sentinel(self) -> None:
        from story_automator.commands.ceiling_check import cmd_ceiling_check

        code, payload = _capture(
            cmd_ceiling_check,
            ["--gate", "init", "--events", "events.jsonl"],
        )
        self.assertEqual(code, 0)
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("verdict"), "ALLOW")
        self.assertEqual(payload.get("reason"), "no_ceilings_configured")
        self.assertIn("bypass_allowed", payload)
        self.assertIsInstance(payload["bypass_allowed"], bool)


def _write_workflow(tmp: str, ceilings: list[dict]) -> Path:
    path = Path(tmp) / "workflow.json"
    path.write_text(
        compact_json({"policy": {"cost_ceilings": ceilings}}),
        encoding="utf-8",
    )
    return path


def _write_ledger(tmp: str, events: list[object]) -> Path:
    ensure_dir(tmp)
    path = Path(tmp) / "events.jsonl"
    body = "\n".join(compact_json(ev.to_dict()) for ev in events)
    if events:
        body += "\n"
    path.write_text(body, encoding="utf-8")
    return path


def _completed(cost: float, ts: str = "2026-06-15T00:00:00Z") -> StoryCompleted:
    return StoryCompleted(
        timestamp=ts,
        run_id="r1",
        epic="E1",
        story_key="S1",
        duration_s=1.0,
        cost_usd=cost,
        tokens_in=0,
        tokens_out=0,
        attempts=1,
    )


class CmdCeilingCheckAllowTests(unittest.TestCase):
    def test_allow_when_spend_below_warn(self) -> None:
        from story_automator.commands.ceiling_check import cmd_ceiling_check

        with tempfile.TemporaryDirectory() as tmp:
            wf = _write_workflow(
                tmp,
                [
                    {
                        "name": "per_run_cap",
                        "window": "per_run",
                        "limit_usd": 10.0,
                        "warn_at": 0.8,
                        "gate_names": ["init"],
                    }
                ],
            )
            ledger = _write_ledger(tmp, [_completed(1.0)])
            code, payload = _capture(
                cmd_ceiling_check,
                [
                    "--gate",
                    "init",
                    "--events",
                    str(ledger),
                    "--workflow",
                    str(wf),
                    "--now",
                    "2026-06-15T00:00:00Z",
                ],
            )
        self.assertEqual(code, 0)
        self.assertEqual(payload["verdict"], "ALLOW")
        self.assertIn("per_run_cap", payload["reason"])
        self.assertIn("spent=1.0000", payload["reason"])
        self.assertIn("limit=10.0000", payload["reason"])


if __name__ == "__main__":
    unittest.main()
