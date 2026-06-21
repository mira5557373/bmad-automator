"""Tests for the baseline-commit lie detector (Phase 1)."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from story_automator.core.lie_detector import detect_baseline_drift


def _init_repo(path: Path) -> str:
    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "t@t.com"],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "T"],
        capture_output=True, check=True,
    )
    (path / "a").write_text("1\n")
    subprocess.run(
        ["git", "-C", str(path), "add", "."], capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", "init"],
        capture_output=True, check=True,
    )
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def _add_commit(path: Path, filename: str) -> str:
    (path / filename).write_text("more\n")
    subprocess.run(
        ["git", "-C", str(path), "add", "."], capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", filename],
        capture_output=True, check=True,
    )
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


class LieDetectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="sa-lie-")
        self.repo = Path(self.tmpdir) / "repo"
        self.repo.mkdir()
        self.baseline = _init_repo(self.repo)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_head_matches_expected_passes(self) -> None:
        outcome = detect_baseline_drift(
            self.repo, expected_sha=self.baseline,
        )
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.reason, "")

    def test_short_sha_also_matches(self) -> None:
        outcome = detect_baseline_drift(
            self.repo, expected_sha=self.baseline[:8],
        )
        self.assertTrue(outcome.ok)

    def test_head_at_baseline_when_commit_expected_is_drift(self) -> None:
        # Session was told to commit something on top of baseline, but
        # never actually committed — HEAD is still baseline.
        expected = "deadbeef" * 5  # any non-baseline sha
        outcome = detect_baseline_drift(
            self.repo,
            expected_sha=expected,
            baseline_sha=self.baseline,
        )
        self.assertFalse(outcome.ok)
        self.assertTrue(outcome.retryable)
        self.assertEqual(outcome.reason, "baseline_drift")
        self.assertTrue(outcome.fixable)

    def test_head_on_unexpected_third_commit_not_fixable(self) -> None:
        new_sha = _add_commit(self.repo, "b")
        # Session reported some other commit; HEAD is new_sha which is
        # neither baseline nor expected.
        outcome = detect_baseline_drift(
            self.repo,
            expected_sha="cafef00d" * 5,
            baseline_sha=self.baseline,
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.reason, "unexpected_head")
        self.assertFalse(outcome.fixable)
        # Not at baseline so caller can't trivially retry — must escalate
        # via a different path (re-prompt, not auto-fix).
        self.assertTrue(outcome.retryable)  # retryable but not fixable
        self.assertNotEqual(new_sha, self.baseline)  # sanity

    def test_head_matches_after_commit(self) -> None:
        new_sha = _add_commit(self.repo, "c")
        outcome = detect_baseline_drift(
            self.repo,
            expected_sha=new_sha,
            baseline_sha=self.baseline,
        )
        self.assertTrue(outcome.ok)

    def test_git_unavailable_escalates(self) -> None:
        # Not a git repo → rev_parse_head raises GitError → escalate.
        with tempfile.TemporaryDirectory() as not_a_repo:
            outcome = detect_baseline_drift(
                not_a_repo, expected_sha="abc1234567",
            )
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.severity, "CRITICAL")
        self.assertFalse(outcome.retryable)
        self.assertIn("git_unavailable", outcome.reason)

    def test_baseline_sha_optional(self) -> None:
        # No baseline provided → drift is reported as unexpected_head.
        outcome = detect_baseline_drift(
            self.repo, expected_sha="deadbeef" * 5,
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.reason, "unexpected_head")


if __name__ == "__main__":
    unittest.main()
