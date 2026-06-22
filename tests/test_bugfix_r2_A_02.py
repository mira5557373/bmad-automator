"""Regression test for bug-r2 A-02: scalability collectors reference
missing check scripts (``scale_lint_check.py`` and
``capacity_plan_check.py``).

Before the fix the two missing files caused every gate run on a
scalability-applicable change to FAIL with ``[Errno 2] No such file``,
because the Python interpreter's exit code 2 was mapped to
``status="violation"`` by the collector runner — silently dragging the
whole category to FAIL on every run.

The fix ships the missing check scripts on disk under
``core/checks/``.  These tests pin the on-disk presence of those scripts
and their basic CLI contract (usage exit, default-extensions exit).
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


_CHECKS_DIR = (
    Path(__file__).resolve().parent.parent
    / "skills"
    / "bmad-story-automator"
    / "src"
    / "story_automator"
    / "core"
    / "checks"
)


class ScalabilityCheckScriptsExistOnDiskTests(unittest.TestCase):
    """The scalability collector build_cmd functions point at two
    sibling check scripts.  Before the fix neither existed on disk."""

    def test_scale_lint_check_script_exists(self) -> None:
        script = _CHECKS_DIR / "scale_lint_check.py"
        self.assertTrue(
            script.is_file(),
            f"scale_lint_check.py missing on disk at {script}",
        )

    def test_capacity_plan_check_script_exists(self) -> None:
        script = _CHECKS_DIR / "capacity_plan_check.py"
        self.assertTrue(
            script.is_file(),
            f"capacity_plan_check.py missing on disk at {script}",
        )

    def test_scale_lint_runs_clean_on_empty_tree(self) -> None:
        script = _CHECKS_DIR / "scale_lint_check.py"
        if not script.is_file():
            self.skipTest("scale_lint_check.py not present (pre-fix state)")
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [sys.executable, str(script), tmpdir],
                capture_output=True,
                text=True,
                timeout=10,
            )
        # Clean tree => exit 0 (no scalability findings).
        self.assertEqual(
            result.returncode,
            0,
            f"expected exit 0 on empty tree, got {result.returncode}: "
            f"{result.stdout!r} / {result.stderr!r}",
        )


if __name__ == "__main__":
    unittest.main()
