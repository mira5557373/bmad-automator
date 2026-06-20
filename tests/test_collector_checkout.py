from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from story_automator.core.collector_checkout import (
    CollectorCheckoutError,
    cleanup_collector_checkout,
    collector_checkout,
    create_collector_checkout,
)


def _init_test_repo(path: Path) -> str:
    """Create a minimal git repo with one commit, return the SHA."""
    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@test.com"],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test"],
        capture_output=True, check=True,
    )
    marker = path / "marker.txt"
    marker.write_text("initial")
    subprocess.run(
        ["git", "-C", str(path), "add", "."],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", "init"],
        capture_output=True, check=True,
    )
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


class CreateCollectorCheckoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_dir = Path(tempfile.mkdtemp(prefix="sa-test-repo-"))
        self.sha = _init_test_repo(self.repo_dir)

    def tearDown(self) -> None:
        subprocess.run(
            ["git", "-C", str(self.repo_dir), "worktree", "prune"],
            capture_output=True,
        )
        import shutil
        shutil.rmtree(self.repo_dir, ignore_errors=True)

    def test_creates_checkout_at_sha(self) -> None:
        checkout = create_collector_checkout(self.repo_dir, self.sha)
        try:
            self.assertTrue(checkout.is_dir())
            result = subprocess.run(
                ["git", "-C", str(checkout), "rev-parse", "HEAD"],
                capture_output=True, text=True,
            )
            self.assertTrue(result.stdout.strip().startswith(self.sha[:7]))
        finally:
            cleanup_collector_checkout(checkout, self.repo_dir)

    def test_checkout_has_repo_contents(self) -> None:
        checkout = create_collector_checkout(self.repo_dir, self.sha)
        try:
            self.assertTrue((checkout / "marker.txt").exists())
            self.assertEqual((checkout / "marker.txt").read_text(), "initial")
        finally:
            cleanup_collector_checkout(checkout, self.repo_dir)

    def test_empty_sha_raises(self) -> None:
        with self.assertRaises(CollectorCheckoutError):
            create_collector_checkout(self.repo_dir, "")

    def test_invalid_sha_raises(self) -> None:
        with self.assertRaises(CollectorCheckoutError):
            create_collector_checkout(self.repo_dir, "deadbeef" * 5)

    def test_not_a_git_repo_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(CollectorCheckoutError):
                create_collector_checkout(td, "abc123")


class CleanupCollectorCheckoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_dir = Path(tempfile.mkdtemp(prefix="sa-test-repo-"))
        self.sha = _init_test_repo(self.repo_dir)

    def tearDown(self) -> None:
        subprocess.run(
            ["git", "-C", str(self.repo_dir), "worktree", "prune"],
            capture_output=True,
        )
        import shutil
        shutil.rmtree(self.repo_dir, ignore_errors=True)

    def test_removes_checkout_dir(self) -> None:
        checkout = create_collector_checkout(self.repo_dir, self.sha)
        self.assertTrue(checkout.is_dir())
        cleanup_collector_checkout(checkout, self.repo_dir)
        self.assertFalse(checkout.exists())

    def test_cleanup_nonexistent_no_error(self) -> None:
        cleanup_collector_checkout(Path("/nonexistent/path"), self.repo_dir)


class CollectorCheckoutContextManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_dir = Path(tempfile.mkdtemp(prefix="sa-test-repo-"))
        self.sha = _init_test_repo(self.repo_dir)

    def tearDown(self) -> None:
        subprocess.run(
            ["git", "-C", str(self.repo_dir), "worktree", "prune"],
            capture_output=True,
        )
        import shutil
        shutil.rmtree(self.repo_dir, ignore_errors=True)

    def test_yields_checkout_path(self) -> None:
        with collector_checkout(self.repo_dir, self.sha) as checkout:
            self.assertTrue(checkout.is_dir())
            self.assertTrue((checkout / "marker.txt").exists())

    def test_cleans_up_on_exit(self) -> None:
        with collector_checkout(self.repo_dir, self.sha) as checkout:
            path = checkout
        self.assertFalse(path.exists())

    def test_cleans_up_on_exception(self) -> None:
        path = None
        with self.assertRaises(ValueError):
            with collector_checkout(self.repo_dir, self.sha) as checkout:
                path = checkout
                raise ValueError("boom")
        self.assertIsNotNone(path)
        self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
