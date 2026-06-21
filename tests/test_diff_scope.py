from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from story_automator.core.diff_scope import (
    DEFAULT_FILE_CATEGORY_MAP,
    DiffScopeError,
    affected_categories,
    compute_changed_files,
    compute_diff_scope,
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

    def test_detects_deleted_file(self) -> None:
        _add_commit(self.repo, "doomed.py", "x = 1\n")
        sha_with_file = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        (self.repo / "doomed.py").unlink()
        subprocess.run(
            ["git", "-C", str(self.repo), "add", "doomed.py"],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-m", "delete doomed"],
            capture_output=True, check=True,
        )
        sha_deleted = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        changed = compute_changed_files(self.repo, sha_with_file, sha_deleted)
        self.assertIn("doomed.py", changed)

    def test_default_current_sha_is_head(self) -> None:
        _add_commit(self.repo, "head.py", "h\n")
        changed = compute_changed_files(self.repo, self.base_sha)
        self.assertIn("head.py", changed)


class AffectedCategoriesTests(unittest.TestCase):
    def test_python_file_maps_to_categories(self) -> None:
        result = affected_categories({"src/app.py"})
        self.assertIn("correctness", result)
        self.assertIn("static", result)
        self.assertIn("security", result)

    def test_typescript_file_maps_to_categories(self) -> None:
        result = affected_categories({"components/Button.tsx"})
        self.assertIn("correctness", result)
        self.assertIn("accessibility", result)

    def test_sql_file_maps_to_migrations(self) -> None:
        result = affected_categories({"db/migrate/001.sql"})
        self.assertIn("migrations", result)

    def test_markdown_maps_to_docs(self) -> None:
        result = affected_categories({"docs/README.md"})
        self.assertIn("docs", result)

    def test_unknown_extension_returns_empty(self) -> None:
        result = affected_categories({"data/binary.bin"})
        self.assertEqual(result, set())

    def test_multiple_files_union_categories(self) -> None:
        result = affected_categories({"app.py", "schema.sql"})
        self.assertIn("correctness", result)
        self.assertIn("migrations", result)

    def test_custom_map_overrides_default(self) -> None:
        custom: dict[str, frozenset[str]] = {
            "*.txt": frozenset({"custom"}),
        }
        result = affected_categories({"readme.txt"}, custom)
        self.assertEqual(result, {"custom"})

    def test_default_map_is_not_empty(self) -> None:
        self.assertGreater(len(DEFAULT_FILE_CATEGORY_MAP), 0)

    def test_path_based_pattern_matching(self) -> None:
        result = affected_categories({"Dockerfile"})
        self.assertIn("security", result)
        self.assertIn("supply_chain", result)

    def test_nested_path_matches_extension(self) -> None:
        result = affected_categories({"src/deep/nested/module.py"})
        self.assertIn("correctness", result)


class ComputeDiffScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="sa-scope-test-")
        self.repo = Path(self.tmpdir) / "repo"
        self.repo.mkdir()
        self.base_sha = _init_repo(self.repo)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_scope_includes_affected_categories(self) -> None:
        _add_commit(self.repo, "app.py", "x = 1\n")
        scope = compute_diff_scope(self.repo, self.base_sha)
        self.assertIn("correctness", scope)
        self.assertIn("static", scope)

    def test_scope_empty_when_no_changes(self) -> None:
        scope = compute_diff_scope(
            self.repo, self.base_sha, self.base_sha,
        )
        self.assertEqual(scope, set())

    def test_scope_with_custom_map(self) -> None:
        _add_commit(self.repo, "data.csv", "a,b\n")
        custom: dict[str, frozenset[str]] = {
            "*.csv": frozenset({"data_quality"}),
        }
        scope = compute_diff_scope(
            self.repo, self.base_sha, file_category_map=custom,
        )
        self.assertEqual(scope, {"data_quality"})


if __name__ == "__main__":
    unittest.main()
