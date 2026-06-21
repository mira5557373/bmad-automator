from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from story_automator.core.integration.worktree_baseline import (
    DEFAULT_PARENT_REF_CANDIDATES,
    WorktreeBaselineError,
    capture_baseline_commit,
    find_worktree_root,
    is_worktree,
    resolve_parent_ref,
    worktree_baseline_metadata,
)


def _run(*args: str, cwd: str | Path) -> str:
    res = subprocess.run(
        args,
        cwd=str(cwd),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e"},
    )
    return res.stdout.strip()


def _init_repo(path: Path) -> None:
    _run("git", "init", "--initial-branch=main", "-q", cwd=path)
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    _run("git", "add", "README.md", cwd=path)
    _run("git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "init", cwd=path)


class IsWorktreeTests(unittest.TestCase):
    def test_main_checkout_is_not_a_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_repo(repo)
            # Main checkout — .git is a directory, not a file.
            self.assertFalse(is_worktree(repo))

    def test_linked_worktree_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_repo(repo)
            wt = Path(tmp) / "wt-feat"
            _run("git", "-c", "commit.gpgsign=false", "worktree", "add", "-b", "feat", str(wt), cwd=repo)
            self.assertTrue(is_worktree(wt))

    def test_non_git_dir_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(WorktreeBaselineError):
                is_worktree(tmp)


class FindWorktreeRootTests(unittest.TestCase):
    def test_finds_root_from_nested_subdir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_repo(repo)
            wt = Path(tmp) / "wt-x"
            _run("git", "-c", "commit.gpgsign=false", "worktree", "add", "-b", "x", str(wt), cwd=repo)
            nested = wt / "a" / "b"
            nested.mkdir(parents=True)
            self.assertEqual(find_worktree_root(nested).resolve(), wt.resolve())

    def test_non_git_path_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(WorktreeBaselineError):
                find_worktree_root(tmp)


class ResolveParentRefTests(unittest.TestCase):
    def test_picks_main_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_repo(repo)
            wt = Path(tmp) / "wt"
            _run("git", "-c", "commit.gpgsign=false", "worktree", "add", "-b", "feat-a", str(wt), cwd=repo)
            ref = resolve_parent_ref(wt)
            self.assertIn(ref, DEFAULT_PARENT_REF_CANDIDATES)
            self.assertEqual(ref, "main")

    def test_picks_master_when_main_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _run("git", "init", "--initial-branch=master", "-q", cwd=repo)
            (repo / "README.md").write_text("x\n", encoding="utf-8")
            _run("git", "add", "README.md", cwd=repo)
            _run("git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "init", cwd=repo)
            wt = Path(tmp) / "wt"
            _run("git", "-c", "commit.gpgsign=false", "worktree", "add", "-b", "feat-b", str(wt), cwd=repo)
            ref = resolve_parent_ref(wt)
            self.assertEqual(ref, "master")

    def test_explicit_override_passes_through(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_repo(repo)
            wt = Path(tmp) / "wt"
            _run("git", "-c", "commit.gpgsign=false", "worktree", "add", "-b", "feat-c", str(wt), cwd=repo)
            ref = resolve_parent_ref(wt, override="main")
            self.assertEqual(ref, "main")

    def test_unknown_override_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_repo(repo)
            wt = Path(tmp) / "wt"
            _run("git", "-c", "commit.gpgsign=false", "worktree", "add", "-b", "feat-d", str(wt), cwd=repo)
            with self.assertRaises(WorktreeBaselineError):
                resolve_parent_ref(wt, override="does-not-exist")

    def test_no_default_branch_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            # Use a branch name that is NOT in DEFAULT_PARENT_REF_CANDIDATES
            # so the fallback chain must fail.
            _run("git", "init", "--initial-branch=develop", "-q", cwd=repo)
            (repo / "f").write_text("x", encoding="utf-8")
            _run("git", "add", "f", cwd=repo)
            _run("git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "i", cwd=repo)
            wt = Path(tmp) / "wt"
            _run("git", "-c", "commit.gpgsign=false", "worktree", "add", "-b", "feat-e", str(wt), cwd=repo)
            with self.assertRaises(WorktreeBaselineError):
                resolve_parent_ref(wt)


class CaptureBaselineCommitTests(unittest.TestCase):
    def test_baseline_equals_parent_tip_when_worktree_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_repo(repo)
            parent_sha = _run("git", "rev-parse", "HEAD", cwd=repo)
            wt = Path(tmp) / "wt"
            _run("git", "-c", "commit.gpgsign=false", "worktree", "add", "-b", "feat-1", str(wt), cwd=repo)
            baseline = capture_baseline_commit(wt)
            self.assertEqual(baseline, parent_sha)
            self.assertEqual(len(baseline), 40)

    def test_baseline_is_merge_base_after_divergence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_repo(repo)
            base_sha = _run("git", "rev-parse", "HEAD", cwd=repo)
            wt = Path(tmp) / "wt"
            _run("git", "-c", "commit.gpgsign=false", "worktree", "add", "-b", "feat-2", str(wt), cwd=repo)
            # Advance main with a new commit.
            (repo / "main.txt").write_text("m\n", encoding="utf-8")
            _run("git", "add", "main.txt", cwd=repo)
            _run("git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "main-c2", cwd=repo)
            # Advance the worktree branch.
            (wt / "wt.txt").write_text("w\n", encoding="utf-8")
            _run("git", "add", "wt.txt", cwd=wt)
            _run("git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "feat-c1", cwd=wt)
            baseline = capture_baseline_commit(wt)
            self.assertEqual(baseline, base_sha)

    def test_baseline_explicit_parent_ref(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_repo(repo)
            _run("git", "-c", "commit.gpgsign=false", "branch", "release", cwd=repo)
            release_sha = _run("git", "rev-parse", "release", cwd=repo)
            wt = Path(tmp) / "wt"
            _run("git", "-c", "commit.gpgsign=false", "worktree", "add", "-b", "feat-3", str(wt), cwd=repo)
            baseline = capture_baseline_commit(wt, parent_ref="release")
            self.assertEqual(baseline, release_sha)

    def test_non_worktree_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_repo(repo)
            # Calling on the main checkout itself is rejected — it's not a worktree.
            with self.assertRaises(WorktreeBaselineError):
                capture_baseline_commit(repo)


class WorktreeBaselineMetadataTests(unittest.TestCase):
    def test_metadata_payload_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_repo(repo)
            wt = Path(tmp) / "wt"
            _run("git", "-c", "commit.gpgsign=false", "worktree", "add", "-b", "feat-meta", str(wt), cwd=repo)
            payload = worktree_baseline_metadata(wt)
            self.assertEqual(payload["isolation"], "worktree")
            self.assertEqual(payload["parent_ref"], "main")
            self.assertEqual(payload["worktree_branch"], "feat-meta")
            self.assertEqual(len(payload["baseline_commit"]), 40)
            self.assertEqual(len(payload["worktree_head"]), 40)
            self.assertEqual(payload["worktree_root"], str(wt.resolve()))
            # Tip of feat-meta starts at same commit as main, so head==baseline.
            self.assertEqual(payload["baseline_commit"], payload["worktree_head"])

    def test_metadata_after_divergence_records_distinct_head(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_repo(repo)
            wt = Path(tmp) / "wt"
            _run("git", "-c", "commit.gpgsign=false", "worktree", "add", "-b", "feat-meta2", str(wt), cwd=repo)
            (wt / "n.txt").write_text("n", encoding="utf-8")
            _run("git", "add", "n.txt", cwd=wt)
            _run("git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "feat-c1", cwd=wt)
            payload = worktree_baseline_metadata(wt)
            self.assertNotEqual(payload["baseline_commit"], payload["worktree_head"])
            # Baseline is the merge-base — which equals the parent_ref tip
            # because the worktree branch only added commits on its own side.
            parent_tip = _run("git", "rev-parse", "main", cwd=repo)
            self.assertEqual(payload["baseline_commit"], parent_tip)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
