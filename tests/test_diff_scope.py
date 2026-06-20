from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from story_automator.core.diff_scope import (
    DiffScopeError,
    compute_changed_files,
)


def _init_repo(path: Path) -> str:
    """Create a git repo with one commit, return SHA."""
    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "t@t.com"],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "T"],
        capture_output=True, check=True,
    )
    (path / "initial.txt").write_text("init\n")
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


def _add_commit(path: Path, filename: str, content: str) -> str:
    """Add a file and commit, return SHA."""
    (path / filename).write_text(content)
    subprocess.run(
        ["git", "-C", str(path), "add", filename],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", f"add {filename}"],
        capture_output=True, check=True,
    )
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


class ComputeChangedFilesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="sa-diff-test-")
        self.repo = Path(self.tmpdir) / "repo"
        self.repo.mkdir()
        self.base_sha = _init_repo(self.repo)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_detects_added_file(self) -> None:
        sha2 = _add_commit(self.repo, "new.py", "x = 1\n")
        changed = compute_changed_files(self.repo, self.base_sha, sha2)
        self.assertIn("new.py", changed)

    def test_detects_modified_file(self) -> None:
        (self.repo / "initial.txt").write_text("modified\n")
        subprocess.run(
            ["git", "-C", str(self.repo), "add", "."],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-m", "modify"],
            capture_output=True, check=True,
        )
        sha2 = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        changed = compute_changed_files(self.repo, self.base_sha, sha2)
        self.assertIn("initial.txt", changed)

    def test_empty_diff(self) -> None:
        changed = compute_changed_files(
            self.repo, self.base_sha, self.base_sha,
        )
        self.assertEqual(changed, set())

    def test_multiple_files(self) -> None:
        _add_commit(self.repo, "a.py", "a\n")
        sha2 = _add_commit(self.repo, "b.ts", "b\n")
        changed = compute_changed_files(self.repo, self.base_sha, sha2)
        self.assertIn("a.py", changed)
        self.assertIn("b.ts", changed)

    def test_invalid_baseline_raises(self) -> None:
        with self.assertRaises(DiffScopeError):
            compute_changed_files(self.repo, "deadbeef" * 5)

    def test_not_a_git_repo_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(DiffScopeError):
                compute_changed_files(td, "abc123")

    def test_default_current_sha_is_head(self) -> None:
        _add_commit(self.repo, "head.py", "h\n")
        changed = compute_changed_files(self.repo, self.base_sha)
        self.assertIn("head.py", changed)


if __name__ == "__main__":
    unittest.main()
