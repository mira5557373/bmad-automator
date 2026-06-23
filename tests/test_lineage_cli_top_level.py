"""Top-level CLI registration tests for the `lineage` subcommand.

The orchestrator helper has dispatched to `lineage_dispatch` since
1796b08, but operators expect to invoke the query CLI directly from the
`story-automator` entry point. This module pins:

* `lineage` is reachable from the top-level command registry.
* `lineage --help` and `lineage <sub> --help` exit 0 with informative
  output (no "missing --project-root" emitted at the help path).
* Bogus subcommands fall back to the dispatcher's usage banner without
  crashing.
* All previously-registered top-level commands remain intact (regression
  fence against accidental registry shuffling).
"""
from __future__ import annotations

import contextlib
import io
import subprocess
import sys
import unittest

from story_automator import cli
from story_automator.commands.lineage_cmd import lineage_dispatch


def _capture(argv: list[str]) -> tuple[int, str, str]:
    """Run `cli.main(argv)` and capture (rc, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


class TopLevelRegistrationTests(unittest.TestCase):
    def test_lineage_in_top_level_command_registry(self) -> None:
        registry = cli._command_registry()
        self.assertIn("lineage", registry)
        # Must route to the same dispatcher the orchestrator helper uses.
        self.assertIs(registry["lineage"], lineage_dispatch)

    def test_existing_commands_still_registered(self) -> None:
        # Regression fence: registering `lineage` MUST NOT displace any
        # historically-shipped top-level command. Spot-check a representative
        # cross-section (helpers, parsers, gate-adjacent, telemetry).
        registry = cli._command_registry()
        for expected in (
            "version",
            "doctor",
            "audit-verify",
            "orchestrator-helper",
            "trust_verify",
            "telemetry-report",
            "ensure-stop-hook",
            "parse-epic",
            "validate-story-creation",
        ):
            self.assertIn(expected, registry, f"{expected} missing from registry")


class TopLevelHelpExitCodeTests(unittest.TestCase):
    """`--help` at every documented level returns exit 0."""

    def test_lineage_help_returns_zero_exit(self) -> None:
        rc, out, _err = _capture(["lineage", "--help"])
        self.assertEqual(rc, 0)
        # Help body must mention every subcommand so operators can
        # discover the surface from one place.
        body = out
        for sub in ("show", "entry", "stats", "verify", "orphans"):
            self.assertIn(sub, body, f"help missing subcommand: {sub}")

    def test_lineage_short_help_returns_zero_exit(self) -> None:
        rc, _out, _err = _capture(["lineage", "-h"])
        self.assertEqual(rc, 0)

    def test_lineage_show_help_returns_zero_exit(self) -> None:
        rc, out, _err = _capture(["lineage", "show", "--help"])
        self.assertEqual(rc, 0)
        self.assertIn("--project-root", out)

    def test_lineage_entry_help_returns_zero_exit(self) -> None:
        rc, out, _err = _capture(["lineage", "entry", "--help"])
        self.assertEqual(rc, 0)
        self.assertIn("--project-root", out)
        # `entry` accepts two positionals; help must surface them.
        self.assertIn("genre", out)
        self.assertIn("slug", out)

    def test_lineage_stats_help_returns_zero_exit(self) -> None:
        rc, out, _err = _capture(["lineage", "stats", "--help"])
        self.assertEqual(rc, 0)
        self.assertIn("--project-root", out)

    def test_lineage_verify_help_returns_zero_exit(self) -> None:
        rc, out, _err = _capture(["lineage", "verify", "--help"])
        self.assertEqual(rc, 0)
        self.assertIn("--project-root", out)

    def test_lineage_orphans_help_returns_zero_exit(self) -> None:
        rc, out, _err = _capture(["lineage", "orphans", "--help"])
        self.assertEqual(rc, 0)
        self.assertIn("--project-root", out)


class TopLevelHelpContentTests(unittest.TestCase):
    def test_lineage_help_contains_all_subcommand_names(self) -> None:
        rc, out, _err = _capture(["lineage", "--help"])
        self.assertEqual(rc, 0)
        for sub in ("show", "entry", "stats", "verify", "orphans"):
            self.assertIn(sub, out)

    def test_lineage_help_mentions_project_root(self) -> None:
        # Every subcommand requires --project-root; the top-level help
        # surface should hint at this so operators don't bounce off.
        rc, out, _err = _capture(["lineage", "--help"])
        self.assertEqual(rc, 0)
        # The description or epilog must reference project-root (case-
        # insensitive — the help banner is human-readable prose).
        self.assertIn("project-root", out.lower().replace("_", "-"))


class TopLevelInvalidSubcommandTests(unittest.TestCase):
    def test_lineage_invalid_subcommand_prints_help(self) -> None:
        # An unknown subcommand must NOT crash the dispatcher — it should
        # emit the usage banner and return non-zero (mirrors the
        # orchestrator-helper contract that the dispatcher already honors).
        rc, _out, err = _capture(["lineage", "not-a-real-sub"])
        self.assertNotEqual(rc, 0)
        # Usage banner contains the literal subcommand list.
        self.assertIn("show", err)


class EntryPointModuleTests(unittest.TestCase):
    """End-to-end smoke via `python -m story_automator lineage --help`."""

    def test_python_dash_m_lineage_help_succeeds(self) -> None:
        # The npm bin/ wrapper is a Node script; the actual Python entry
        # point is `python -m story_automator`. Exercise that path so we
        # know the registration sticks across a fresh process boundary
        # (catches accidental lazy-import deadlocks too).
        result = subprocess.run(
            [sys.executable, "-m", "story_automator", "lineage", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"stdout={result.stdout!r} stderr={result.stderr!r}",
        )
        # Help text lands somewhere — argparse prints to stdout.
        self.assertTrue(result.stdout, "expected help text on stdout")


if __name__ == "__main__":
    unittest.main()
