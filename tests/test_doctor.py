"""Tests for the ``story-automator doctor`` preflight command (F-013)."""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout

from story_automator.commands.doctor import cmd_doctor

_EXPECTED_CHECKS = {
    "python", "dependencies", "tmux", "agents", "git", "disk",
    "audit_key", "config", "file_descriptors", "profile",
}


def _run(args: list[str]) -> tuple[int, dict, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cmd_doctor(args)
    return code, json.loads(out.getvalue()), err.getvalue()


class DoctorCommandTests(unittest.TestCase):
    def test_emits_valid_json_with_all_checks(self) -> None:
        code, payload, _ = _run([])
        self.assertIn(code, (0, 1))
        self.assertIsInstance(payload["ok"], bool)
        names = {c["name"] for c in payload["checks"]}
        self.assertEqual(names, _EXPECTED_CHECKS)
        for check in payload["checks"]:
            self.assertIn(check["status"], ("ok", "warn", "fail"))

    def test_dependencies_present_in_test_env(self) -> None:
        # filelock + psutil are installed wherever the suite runs.
        _code, payload, _ = _run([])
        deps = next(c for c in payload["checks"] if c["name"] == "dependencies")
        self.assertEqual(deps["status"], "ok")

    def test_summary_counts_match_checks_and_drive_exit_code(self) -> None:
        code, payload, _ = _run([])
        summary = payload["summary"]
        self.assertEqual(
            summary["ok"] + summary["warn"] + summary["fail"], len(payload["checks"])
        )
        self.assertEqual(code, 0 if summary["fail"] == 0 else 1)
        self.assertEqual(payload["ok"], summary["fail"] == 0)

    def test_human_flag_writes_summary_to_stderr(self) -> None:
        _code, _payload, err = _run(["--human"])
        self.assertIn("dependencies", err)

    def test_help(self) -> None:
        out = io.StringIO()
        with redirect_stdout(out):
            code = cmd_doctor(["--help"])
        self.assertEqual(code, 0)
        self.assertIn("doctor", out.getvalue())

    def test_profile_check_present(self) -> None:
        _code, payload, _ = _run([])
        profile_check = next(
            c for c in payload["checks"] if c["name"] == "profile"
        )
        self.assertIn(profile_check["status"], ("ok", "warn"))
        self.assertIn("profile", profile_check["detail"].lower())

    def test_registered_in_cli_dispatch(self) -> None:
        from story_automator.cli import main

        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["doctor"])
        self.assertNotIn("Unknown command", err.getvalue())
        self.assertIn(code, (0, 1))
        self.assertIn("checks", json.loads(out.getvalue()))


if __name__ == "__main__":
    unittest.main()
