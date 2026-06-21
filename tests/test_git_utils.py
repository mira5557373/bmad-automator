"""Tests for git_utils helpers (Phase 1 baseline-commit primitives)."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from story_automator.core.git_utils import (
    GitError,
    has_changes_since,
    rev_parse_head,
    same_commit,
    untracked_files,
    worktree_clean,
)


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
    (path / "src.py").write_text("x = 1\n")
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


def _commit_all(path: Path, message: str) -> str:
    subprocess.run(
        ["git", "-C", str(path), "add", "."], capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", message],
        capture_output=True, check=True,
    )
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


class _RepoFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="sa-git-utils-")
        self.repo = Path(self.tmpdir) / "repo"
        self.repo.mkdir()
        self.sha = _init_repo(self.repo)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)


class RevParseHeadTests(_RepoFixture):
    def test_returns_full_sha(self) -> None:
        head = rev_parse_head(self.repo)
        self.assertEqual(head, self.sha)
        self.assertEqual(len(head), 40)

    def test_not_a_repo_raises_giterror(self) -> None:
        with tempfile.TemporaryDirectory() as not_a_repo:
            with self.assertRaises(GitError):
                rev_parse_head(not_a_repo)


class SameCommitTests(unittest.TestCase):
    SHA = "1234567890abcdef1234567890abcdef12345678"

    def test_identical_full_shas(self) -> None:
        self.assertTrue(same_commit(self.SHA, self.SHA))

    def test_prefix_matches_full(self) -> None:
        self.assertTrue(same_commit(self.SHA, self.SHA[:7]))
        self.assertTrue(same_commit(self.SHA[:7], self.SHA))

    def test_different_shas(self) -> None:
        other = "fedcba9876543210" * 2 + "abcd1234"
        self.assertFalse(same_commit(self.SHA, other))

    def test_short_strings_use_strict_equality(self) -> None:
        # <7 chars falls back to ==; "abc" != "abd"
        self.assertFalse(same_commit("abc", "abd"))
        self.assertTrue(same_commit("abc", "abc"))

    def test_8char_vs_full_matches(self) -> None:
        self.assertTrue(same_commit(self.SHA, self.SHA[:8]))


class HasChangesSinceTests(_RepoFixture):
    def test_clean_worktree_no_changes(self) -> None:
        self.assertFalse(has_changes_since(self.repo, self.sha))

    def test_tracked_modification_detected(self) -> None:
        (self.repo / "src.py").write_text("x = 2\n")
        self.assertTrue(has_changes_since(self.repo, self.sha))

    def test_untracked_file_detected(self) -> None:
        (self.repo / "new.py").write_text("y = 1\n")
        self.assertTrue(has_changes_since(self.repo, self.sha))

    def test_gitignored_file_not_a_change(self) -> None:
        (self.repo / ".gitignore").write_text("ignored.txt\n")
        _commit_all(self.repo, "add gitignore")
        new_baseline = rev_parse_head(self.repo)
        (self.repo / "ignored.txt").write_text("noise\n")
        self.assertFalse(has_changes_since(self.repo, new_baseline))


class UntrackedFilesTests(_RepoFixture):
    def test_clean_worktree_empty_set(self) -> None:
        self.assertEqual(untracked_files(self.repo), set())

    def test_lists_untracked_files(self) -> None:
        (self.repo / "a.py").write_text("a\n")
        (self.repo / "b.py").write_text("b\n")
        self.assertEqual(untracked_files(self.repo), {"a.py", "b.py"})

    def test_respects_gitignore(self) -> None:
        (self.repo / ".gitignore").write_text("skip.txt\n")
        _commit_all(self.repo, "add gitignore")
        (self.repo / "skip.txt").write_text("noise\n")
        (self.repo / "keep.py").write_text("k\n")
        self.assertEqual(untracked_files(self.repo), {"keep.py"})


class WorktreeCleanTests(_RepoFixture):
    def test_fresh_init_is_clean(self) -> None:
        self.assertTrue(worktree_clean(self.repo))

    def test_tracked_change_dirties_worktree(self) -> None:
        (self.repo / "src.py").write_text("x = 999\n")
        self.assertFalse(worktree_clean(self.repo))

    def test_untracked_dirties_worktree(self) -> None:
        (self.repo / "u.py").write_text("u\n")
        self.assertFalse(worktree_clean(self.repo))


if __name__ == "__main__":
    unittest.main()
