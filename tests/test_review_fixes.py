# tests/test_review_fixes.py
"""Regressions for the final-review findings: recoverable inputs must produce a
structured error / honored contract, never escape to the internal_error backstop
or crash the stop hook."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from story_automator.commands import basic
from story_automator.commands.telemetry_report import cmd_telemetry_report
from story_automator.commands.trust_verify import cmd_trust_verify
from story_automator.core import run_identity


def _run(fn, args) -> tuple[int, dict]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = fn(args)
    return code, json.loads(buf.getvalue())


class TelemetryReportMalformedEventTests(unittest.TestCase):
    def test_valid_json_but_malformed_event_is_corrupt_telemetry(self) -> None:
        # BUG-1: a valid-JSON line missing event_type raises ValueError/TypeError
        # from parse_event, which previously escaped the JSONDecodeError-only
        # handler and was misreported as internal_error.
        with tempfile.TemporaryDirectory() as d:
            events = Path(d) / "events.jsonl"
            events.write_text('{"foo": 1}\n', encoding="utf-8")
            code, payload = _run(cmd_telemetry_report, ["--events", str(events)])
            self.assertEqual(code, 1)
            self.assertEqual(payload["error"], "corrupt_telemetry")


class TrustVerifyUnreadableInputTests(unittest.TestCase):
    def test_gaps_path_is_a_directory_yields_structured_error(self) -> None:
        # BUG-3: a directory --gaps raises IsADirectoryError/PermissionError
        # (OSError, not FileNotFoundError) which previously hit internal_error.
        with tempfile.TemporaryDirectory() as d:
            code, payload = _run(
                cmd_trust_verify, ["--gaps", d, "--spec", "s.md", "--diff", "x.diff"]
            )
            self.assertEqual(code, 1)
            self.assertEqual(payload["error"], "gaps_unreadable")


class StopHookNonDictMarkerTests(unittest.TestCase):
    def _stop_hook(self, marker_body: str) -> tuple[int, str]:
        with tempfile.TemporaryDirectory() as d:
            marker = Path(d) / ".story-automator-active"
            marker.write_text(marker_body, encoding="utf-8")
            buf = io.StringIO()
            with (
                mock.patch.object(basic, "active_marker_path", return_value=marker),
                mock.patch("sys.stdin", io.StringIO("")),
                mock.patch.dict("os.environ", {"STORY_AUTOMATOR_CHILD": ""}, clear=False),
                contextlib.redirect_stdout(buf),
            ):
                code = basic.cmd_stop_hook([])
            return code, buf.getvalue()

    def test_non_dict_marker_allows_stop_without_crash(self) -> None:
        # BUG-4: valid JSON but not an object (e.g. an array/number/string).
        for body in ("[]", "123", '""'):
            code, out = self._stop_hook(body)
            self.assertEqual(code, 0, f"body={body!r}")
            self.assertNotIn("block", out)


class RunIdentityResolveFailureTests(unittest.TestCase):
    def test_marker_path_resolution_oserror_returns_empty(self) -> None:
        # Self-found: active_marker_path() can raise OSError (e.g. os.getcwd on a
        # deleted cwd); current_run_id must still return "" rather than break an
        # emit. It is now inside the guarded try.
        with mock.patch.object(
            run_identity, "active_marker_path", side_effect=OSError("cwd gone")
        ):
            self.assertEqual(run_identity.current_run_id("/whatever"), "")


if __name__ == "__main__":
    unittest.main()
