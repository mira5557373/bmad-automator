from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from story_automator.core import install_paths, seed_files


@dataclass
class _Profile:
    cli_id: str


class InstallPathsTests(unittest.TestCase):
    def test_skill_tree_dirs_constant_covers_known_clis(self) -> None:
        self.assertEqual(install_paths.SKILL_TREE_DIRS["claude-code"], ".claude/skills")
        self.assertEqual(install_paths.SKILL_TREE_DIRS["codex"], ".agents/skills")
        self.assertEqual(install_paths.SKILL_TREE_DIRS["gemini-cli"], ".gemini/skills")

    def test_mcp_seed_dirs_constant_covers_known_clis(self) -> None:
        self.assertEqual(install_paths.MCP_SEED_DIRS["claude-code"], ".claude/mcp_servers")
        self.assertEqual(install_paths.MCP_SEED_DIRS["codex"], ".agents/mcp_servers")
        self.assertEqual(install_paths.MCP_SEED_DIRS["gemini-cli"], ".gemini/mcp_servers")

    def test_install_path_for_returns_pathlib_path(self) -> None:
        path = install_paths.install_path_for("claude-code")
        self.assertIsInstance(path, Path)
        self.assertEqual(path, Path(".claude/skills"))

    def test_mcp_seed_path_for_returns_pathlib_path(self) -> None:
        path = install_paths.mcp_seed_path_for("codex")
        self.assertIsInstance(path, Path)
        self.assertEqual(path, Path(".agents/mcp_servers"))

    def test_install_path_for_rejects_unknown_cli(self) -> None:
        with self.assertRaises(KeyError):
            install_paths.install_path_for("rogue-cli")

    def test_mcp_seed_path_for_rejects_unknown_cli(self) -> None:
        with self.assertRaises(KeyError):
            install_paths.mcp_seed_path_for("rogue-cli")

    def test_skill_and_mcp_dir_maps_share_known_ids(self) -> None:
        self.assertEqual(
            set(install_paths.SKILL_TREE_DIRS.keys()),
            set(install_paths.MCP_SEED_DIRS.keys()),
        )


class SeedFilesTests(unittest.TestCase):
    def test_seed_worktree_creates_skill_and_mcp_dirs_for_claude_code(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            wt = Path(raw)
            seed_files.seed_worktree(wt, _Profile(cli_id="claude-code"))
            self.assertTrue((wt / ".claude" / "skills").is_dir())
            self.assertTrue((wt / ".claude" / "mcp_servers").is_dir())

    def test_seed_worktree_creates_dirs_for_codex(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            wt = Path(raw)
            seed_files.seed_worktree(wt, _Profile(cli_id="codex"))
            self.assertTrue((wt / ".agents" / "skills").is_dir())
            self.assertTrue((wt / ".agents" / "mcp_servers").is_dir())

    def test_seed_worktree_creates_dirs_for_gemini_cli(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            wt = Path(raw)
            seed_files.seed_worktree(wt, _Profile(cli_id="gemini-cli"))
            self.assertTrue((wt / ".gemini" / "skills").is_dir())
            self.assertTrue((wt / ".gemini" / "mcp_servers").is_dir())

    def test_seed_worktree_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            wt = Path(raw)
            seed_files.seed_worktree(wt, _Profile(cli_id="claude-code"))
            # Second call must not raise even though directories exist.
            seed_files.seed_worktree(wt, _Profile(cli_id="claude-code"))
            self.assertTrue((wt / ".claude" / "skills").is_dir())

    def test_seed_worktree_rejects_unknown_cli_id(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            wt = Path(raw)
            with self.assertRaises(seed_files.SeedFilesError):
                seed_files.seed_worktree(wt, _Profile(cli_id="rogue-cli"))

    def test_seed_worktree_rejects_missing_worktree_path(self) -> None:
        missing = Path(tempfile.gettempdir()) / "definitely-not-a-real-worktree-xyz-123"
        if missing.exists():
            self.skipTest("collision with existing temp path")
        with self.assertRaises(seed_files.SeedFilesError):
            seed_files.seed_worktree(missing, _Profile(cli_id="claude-code"))

    def test_seed_files_error_is_ioerror_subclass(self) -> None:
        self.assertTrue(issubclass(seed_files.SeedFilesError, IOError))

    def test_seed_worktree_accepts_string_path(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            seed_files.seed_worktree(raw, _Profile(cli_id="claude-code"))
            self.assertTrue((Path(raw) / ".claude" / "skills").is_dir())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
