# tests/test_cli_ergonomics.py
"""Wave G: version surface, discoverable unknown-command errors, and a
JSON-safe marker check line."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from story_automator import __version__, cli
from story_automator.commands import orchestrator
from story_automator.core.runtime_layout import active_marker_path


def _capture(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


class VersionSurfaceTests(unittest.TestCase):
    def test_version_flag(self) -> None:
        code, out, _ = _capture(["--version"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {"ok": True, "version": __version__})

    def test_short_version_flag(self) -> None:
        code, out, _ = _capture(["-v"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["version"], __version__)

    def test_version_subcommand(self) -> None:
        code, out, _ = _capture(["version"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["version"], __version__)


class UnknownCommandDiscoverabilityTests(unittest.TestCase):
    def test_near_miss_suggests_match(self) -> None:
        code, _, err = _capture(["versionn"])  # typo of "version"
        self.assertEqual(code, 1)
        self.assertIn("Did you mean", err)
        self.assertIn("version", err)

    def test_trust_verify_hyphen_hint(self) -> None:
        code, _, err = _capture(["trust-verify"])
        self.assertEqual(code, 1)
        self.assertIn("trust_verify", err)


class MarkerCheckJsonTests(unittest.TestCase):
    def test_marker_check_line_is_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            marker = active_marker_path(str(tmp))
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text('{"epic": "1"}\n', encoding="utf-8")
            out = io.StringIO()
            with (
                mock.patch.object(orchestrator, "get_project_root", return_value=str(tmp)),
                contextlib.redirect_stdout(out),
            ):
                code = orchestrator._marker(["check"])
            self.assertEqual(code, 0)
            # The first stdout line must parse as JSON even when the marker path
            # contains backslashes (Windows) or other JSON-special characters.
            first_line = out.getvalue().splitlines()[0]
            parsed = json.loads(first_line)
            self.assertTrue(parsed["exists"])
            self.assertIn("file", parsed)


if __name__ == "__main__":
    unittest.main()
