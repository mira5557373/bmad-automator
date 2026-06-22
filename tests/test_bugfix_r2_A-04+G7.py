"""Regression tests for bug A-04+G7 (collector_checkout SHA validation).

Original defect (in create_collector_checkout):
    actual_sha.startswith(commit_sha[:7])

- Refname inputs (HEAD, main, tags) NEVER match: e.g. "HEAD"[:7] == "HEAD"
  and an actual SHA never starts with "HEAD", so a perfectly valid worktree
  is rejected with a misleading "checkout SHA mismatch" error AFTER
  needlessly spawning git and creating/destroying a worktree.
- Short prefixes weaken the SHA-equality comparison to as little as 28
  bits (`commit_sha[:7]`), so a maliciously-crafted SHA collision in the
  prefix would not be detected.

The fix:
- Reject refnames at the entry point via `re.fullmatch(r'[0-9a-f]{4,40}')`.
- Resolve the input via `git rev-parse <sha>^{commit}` in the parent repo
  to a full 40-char SHA *before* invoking `git worktree add`.
- Compare `actual_sha == resolved_sha` for full equality after checkout.
"""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from story_automator.core.collector_checkout import (
    CollectorCheckoutError,
    cleanup_collector_checkout,
    create_collector_checkout,
)


def _init_test_repo(path: Path) -> str:
    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@test.com"],
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test"],
        capture_output=True,
        check=True,
    )
    (path / "marker.txt").write_text("initial")
    subprocess.run(
        ["git", "-C", str(path), "add", "."], capture_output=True, check=True
    )
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", "init"],
        capture_output=True,
        check=True,
    )
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


class BugfixR2_A04G7_RefnameRejectedAtEntry(unittest.TestCase):
    """Refname inputs must be rejected at the entry point — before
    `git worktree add` is invoked.  The old code would speculatively
    create a worktree, then trip on the bogus startswith() check."""

    def setUp(self) -> None:
        self.repo_dir = Path(tempfile.mkdtemp(prefix="sa-bugfix-r2-"))
        self.sha = _init_test_repo(self.repo_dir)

    def tearDown(self) -> None:
        subprocess.run(
            ["git", "-C", str(self.repo_dir), "worktree", "prune"],
            capture_output=True,
        )
        import shutil

        shutil.rmtree(self.repo_dir, ignore_errors=True)

    def _assert_no_worktree_add(self, refname: str) -> None:
        real_run = subprocess.run
        seen_worktree_add = {"yes": False}

        def tracking_run(*args, **kwargs):  # type: ignore[no-untyped-def]
            argv = args[0] if args else kwargs.get("args")
            if (
                isinstance(argv, list)
                and "worktree" in argv
                and "add" in argv
            ):
                seen_worktree_add["yes"] = True
            return real_run(*args, **kwargs)

        with patch(
            "story_automator.core.collector_checkout.subprocess.run",
            side_effect=tracking_run,
        ):
            with self.assertRaises(CollectorCheckoutError):
                create_collector_checkout(self.repo_dir, refname)
        self.assertFalse(
            seen_worktree_add["yes"],
            f"refname {refname!r} should be rejected before git worktree add",
        )

    def test_refname_HEAD_rejected_at_entry(self) -> None:
        self._assert_no_worktree_add("HEAD")

    def test_refname_main_rejected_at_entry(self) -> None:
        self._assert_no_worktree_add("main")

    def test_tag_name_rejected_at_entry(self) -> None:
        subprocess.run(
            ["git", "-C", str(self.repo_dir), "tag", "v1.0"],
            capture_output=True,
            check=True,
        )
        self._assert_no_worktree_add("v1.0")


class BugfixR2_A04G7_FullShaEqualityVerified(unittest.TestCase):
    """After checkout, the verifier must compare full SHAs — not a 7-char
    prefix that only validates 28 bits.  We patch `git rev-parse HEAD`
    inside the worktree to return a SHA that shares the first 7 chars
    with the expected SHA but diverges afterwards; the old prefix check
    would accept this, the fixed equality check must reject it.
    """

    def setUp(self) -> None:
        self.repo_dir = Path(tempfile.mkdtemp(prefix="sa-bugfix-r2-"))
        self.sha = _init_test_repo(self.repo_dir)

    def tearDown(self) -> None:
        subprocess.run(
            ["git", "-C", str(self.repo_dir), "worktree", "prune"],
            capture_output=True,
        )
        import shutil

        shutil.rmtree(self.repo_dir, ignore_errors=True)

    def test_full_sha_required_not_prefix(self) -> None:
        real_run = subprocess.run

        # Build a fake SHA that shares the first 7 chars but differs after.
        colliding = self.sha[:7] + ("0" * 33)
        # Ensure it's actually different from the real SHA.
        if colliding == self.sha:
            colliding = self.sha[:7] + ("1" * 33)

        def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
            argv = args[0] if args else kwargs.get("args")
            # Intercept the verification call: rev-parse HEAD inside checkout.
            if (
                isinstance(argv, list)
                and argv[:2] == ["git", "rev-parse"]
                and "HEAD" in argv
                and kwargs.get("cwd")
                and "sa-collector-" in str(kwargs.get("cwd"))
            ):
                class _R:
                    returncode = 0
                    stdout = colliding + "\n"
                    stderr = ""

                return _R()
            return real_run(*args, **kwargs)

        with patch(
            "story_automator.core.collector_checkout.subprocess.run",
            side_effect=fake_run,
        ):
            with self.assertRaises(CollectorCheckoutError) as ctx:
                create_collector_checkout(self.repo_dir, self.sha)
        msg = str(ctx.exception).lower()
        self.assertTrue(
            "mismatch" in msg or "sha" in msg,
            f"expected SHA-mismatch error, got: {ctx.exception}",
        )


class BugfixR2_A04G7_ShortHexPrefixStillSupported(unittest.TestCase):
    """A genuine short hex prefix (>=4 chars) must still resolve and yield
    a worktree whose HEAD equals the resolved full SHA."""

    def setUp(self) -> None:
        self.repo_dir = Path(tempfile.mkdtemp(prefix="sa-bugfix-r2-"))
        self.sha = _init_test_repo(self.repo_dir)

    def tearDown(self) -> None:
        subprocess.run(
            ["git", "-C", str(self.repo_dir), "worktree", "prune"],
            capture_output=True,
        )
        import shutil

        shutil.rmtree(self.repo_dir, ignore_errors=True)

    def test_short_hex_prefix_resolves(self) -> None:
        short = self.sha[:8]
        checkout = create_collector_checkout(self.repo_dir, short)
        try:
            self.assertTrue(checkout.is_dir())
            result = subprocess.run(
                ["git", "-C", str(checkout), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(result.stdout.strip(), self.sha)
        finally:
            cleanup_collector_checkout(checkout, self.repo_dir)


if __name__ == "__main__":
    unittest.main()
