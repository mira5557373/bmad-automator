"""B3 — Pre-commit gate file existence + content tests.

Verifies that the opt-in pre-commit gate ships the expected artifacts
under ``.githooks/`` and ``scripts/``. The hook itself is bash; these
tests check the **contracts** (executable bit, key invocations,
escape-hatch presence) without actually invoking the hook (that would
recursively run the full suite during the suite).
"""
from __future__ import annotations

import os
import stat
import subprocess
import unittest
from pathlib import Path


def _repo_root() -> Path:
    # tests/ → repo root.
    return Path(__file__).resolve().parents[1]


class PreCommitHookFileExistsAndIsExecutableTests(unittest.TestCase):
    """The hook file must exist and carry the user-executable bit."""

    def test_pre_commit_hook_file_exists_and_is_executable(self) -> None:
        hook = _repo_root() / ".githooks" / "pre-commit"
        self.assertTrue(
            hook.is_file(),
            f".githooks/pre-commit must exist at {hook}",
        )
        # gap B-M9 — st_mode & S_IXUSR is portable across Windows
        # git-bash; os.access(X_OK) is not reliable there.
        mode = hook.stat().st_mode
        self.assertTrue(
            mode & stat.S_IXUSR,
            f".githooks/pre-commit must be user-executable (mode={oct(mode)})",
        )


class PreCommitHookSkipBannerSmokeTests(unittest.TestCase):
    """Positive control — running the hook with the skip env var exits 0."""

    def test_skip_env_var_exits_zero_with_banner(self) -> None:
        hook = _repo_root() / ".githooks" / "pre-commit"
        if not hook.is_file():
            self.skipTest("hook not present")
        env = dict(os.environ)
        env["BMAD_SKIP_PRECOMMIT"] = "1"
        result = subprocess.run(
            ["bash", str(hook)],
            cwd=str(_repo_root()),
            env=env,
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(
            result.returncode, 0,
            f"hook with BMAD_SKIP_PRECOMMIT=1 must exit 0; stderr={result.stderr}",
        )
        self.assertIn("SKIPPING", result.stderr)


class PreCommitHookContainsExpectedInvocationsTests(unittest.TestCase):
    """The hook file must reference the documented invocations."""

    def test_pre_commit_hook_contains_unittest_and_ruff_invocations(
        self,
    ) -> None:
        hook = _repo_root() / ".githooks" / "pre-commit"
        text = hook.read_text(encoding="utf-8")
        self.assertIn("m unittest discover -s tests", text)
        self.assertIn("ruff check", text)
        self.assertIn("BMAD_SKIP_PRECOMMIT", text)
        # gap B-M4 — M11 vocabulary gate must be wired in so the
        # "would have caught D-04" claim is actually true.
        self.assertIn("m11-vocabulary-gates.sh", text)


class InstallHooksScriptTests(unittest.TestCase):
    """scripts/install-hooks.sh must exist, be executable, set hookspath."""

    def test_install_hooks_script_sets_core_hookspath(self) -> None:
        script = _repo_root() / "scripts" / "install-hooks.sh"
        self.assertTrue(script.is_file())
        mode = script.stat().st_mode
        self.assertTrue(mode & stat.S_IXUSR)
        text = script.read_text(encoding="utf-8")
        self.assertIn("git config core.hooksPath .githooks", text)


class UninstallHooksScriptTests(unittest.TestCase):
    """gap B-M5 — uninstall script for recoverability."""

    def test_uninstall_hooks_script_exists_and_unsets_hookspath(self) -> None:
        script = _repo_root() / "scripts" / "uninstall-hooks.sh"
        self.assertTrue(
            script.is_file(),
            "scripts/uninstall-hooks.sh must exist for recoverability",
        )
        mode = script.stat().st_mode
        self.assertTrue(mode & stat.S_IXUSR)
        text = script.read_text(encoding="utf-8")
        self.assertIn("git config --unset core.hooksPath", text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
