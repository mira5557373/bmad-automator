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
import os
import pathlib
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
        #
        # Explicitly set PYTHONPATH on the child env so the subprocess does
        # not silently rely on the parent's launch convention. Without this,
        # invocations where the parent uses sys.path injection (e.g. a
        # future conftest.py adding skills/.../src) but no PYTHONPATH env
        # var would surface here as a confusing "No module named
        # story_automator" subprocess failure.
        pkg_src_dir = pathlib.Path(cli.__file__).resolve().parent.parent
        child_env = {**os.environ, "PYTHONPATH": str(pkg_src_dir)}
        result = subprocess.run(
            [sys.executable, "-m", "story_automator", "lineage", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
            env=child_env,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"stdout={result.stdout!r} stderr={result.stderr!r}",
        )
        # Help text lands somewhere — argparse prints to stdout.
        self.assertTrue(result.stdout, "expected help text on stdout")

    def test_repo_root_path_arithmetic_resolves_to_this_file(self) -> None:
        # Regression fence for the off-by-one in
        # test_python_dash_m_lineage_help_robust_when_parent_uses_sys_path:
        # the path arithmetic used to walk one too many `.parent`s, landing
        # one level ABOVE the actual repo root. tests_dir then pointed at a
        # non-existent directory and the driver subprocess silently fell
        # back to its inherited cwd to import `tests`, defeating the
        # cwd-independence guarantee the robust-test was meant to assert.
        # Pin the arithmetic by proving the resolved tests_dir contains
        # *this* file regardless of the caller's cwd.
        pkg_src_dir = pathlib.Path(cli.__file__).resolve().parent.parent
        repo_root = pkg_src_dir.parent.parent.parent
        tests_dir = repo_root / "tests"
        this_file = tests_dir / "test_lineage_cli_top_level.py"
        self.assertTrue(
            tests_dir.is_dir(),
            f"computed tests_dir does not exist: {tests_dir}",
        )
        self.assertTrue(
            this_file.is_file(),
            f"computed tests_dir does not contain this test file: {this_file}",
        )
        # And the resolved path must match the path of this very module so
        # we're not just landing on a sibling `tests/` directory by luck.
        self.assertEqual(
            this_file.resolve(),
            pathlib.Path(__file__).resolve(),
        )

    def test_python_dash_m_lineage_help_robust_when_parent_uses_sys_path(
        self,
    ) -> None:
        # Regression fence for "subprocess test inherits PYTHONPATH from
        # parent without explicitly setting it". The original bug: the
        # subprocess.run inside test_python_dash_m_lineage_help_succeeds
        # passed NO env= kwarg, so the child inherited the parent's env.
        # That works under `PYTHONPATH=... python -m unittest ...` but
        # silently breaks under pytest+conftest.py scenarios where the
        # parent uses sys.path injection (process-internal) and the
        # PYTHONPATH env var is unset.
        #
        # This test simulates that parent scenario directly: it spawns a
        # fresh parent python whose PYTHONPATH is stripped from the env,
        # then sys.path.inserts the package src and shells out to
        # `python -m story_automator lineage --help`. On the pre-fix code
        # (no env=) the inner subprocess fails with "No module named
        # story_automator" because sys.path mutations do not propagate
        # across the process boundary. On the fixed code (env=child_env
        # with PYTHONPATH set explicitly) the inner subprocess succeeds.
        pkg_src_dir = pathlib.Path(cli.__file__).resolve().parent.parent
        # pkg_src_dir = .../bmad-automator/skills/bmad-story-automator/src
        # Walk: src -> bmad-story-automator -> skills -> bmad-automator (repo root)
        repo_root = pkg_src_dir.parent.parent.parent
        tests_dir = repo_root / "tests"

        # Driver script: this is the "parent" that mimics a pytest/conftest
        # sys.path injection style (no PYTHONPATH env var, but the package
        # is on sys.path because the parent injected it).
        driver = (
            "import os, sys, unittest\n"
            "os.environ.pop('PYTHONPATH', None)\n"
            f"sys.path.insert(0, {str(pkg_src_dir)!r})\n"
            f"sys.path.insert(0, {str(tests_dir.parent)!r})\n"
            "loader = unittest.TestLoader()\n"
            "from tests import test_lineage_cli_top_level as m\n"
            "suite = loader.loadTestsFromName(\n"
            "    'EntryPointModuleTests.test_python_dash_m_lineage_help_succeeds',\n"
            "    m,\n"
            ")\n"
            "runner = unittest.TextTestRunner(verbosity=0)\n"
            "result = runner.run(suite)\n"
            "sys.exit(0 if result.wasSuccessful() else 1)\n"
        )
        # Strip PYTHONPATH from the driver's env so it has to rely on its
        # own sys.path injection — matching the conftest.py scenario.
        driver_env = {
            k: v for k, v in os.environ.items() if k != "PYTHONPATH"
        }
        result = subprocess.run(
            [sys.executable, "-c", driver],
            capture_output=True,
            text=True,
            timeout=60,
            env=driver_env,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"driver stdout={result.stdout!r} stderr={result.stderr!r}",
        )


if __name__ == "__main__":
    unittest.main()
