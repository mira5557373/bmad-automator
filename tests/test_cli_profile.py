from __future__ import annotations

import sys
import tempfile
import unittest
from collections.abc import Mapping
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "bmad-story-automator" / "src"))

from story_automator.core.cli_profile import (  # noqa: E402
    KNOWN_CLI_IDS,
    KNOWN_HOOK_DIALECTS,
    CLIProfile,
    CLIProfileError,
    claude_default,
    load_cli_profile,
)


GOOD_TOML = """\
cli_id = "claude-code"
binary = "claude"
prompt_template = "{prompt}"
bypass_flags = ["--dangerously-skip-permissions"]
hook_dialect = "claude"
skill_tree_dir = ".claude/skills"
mcp_seed_files = [".claude/settings.json", ".mcp.json"]

[canonical_event_map]
SessionStart = "session_start"
Stop = "stop"
"""


def _write(tmp: Path, name: str, body: str) -> Path:
    path = tmp / name
    path.write_text(body, encoding="utf-8")
    return path


class CLIProfileSchemaTests(unittest.TestCase):
    def test_known_cli_ids_closed_set(self) -> None:
        self.assertEqual(
            tuple(KNOWN_CLI_IDS),
            ("claude-code", "codex", "gemini-cli"),
        )

    def test_known_hook_dialects_closed_set(self) -> None:
        self.assertEqual(
            tuple(KNOWN_HOOK_DIALECTS),
            ("claude", "codex", "gemini", "none"),
        )

    def test_cliprofile_is_frozen_dataclass(self) -> None:
        profile = claude_default()
        with self.assertRaises(FrozenInstanceError):
            profile.binary = "other"  # type: ignore[misc]

    def test_cliprofile_field_names(self) -> None:
        names = {f.name for f in fields(CLIProfile)}
        self.assertEqual(
            names,
            {
                "cli_id",
                "binary",
                "prompt_template",
                "bypass_flags",
                "hook_dialect",
                "canonical_event_map",
                "skill_tree_dir",
                "mcp_seed_files",
            },
        )

    def test_cli_profile_error_is_value_error(self) -> None:
        self.assertTrue(issubclass(CLIProfileError, ValueError))


class ClaudeDefaultTests(unittest.TestCase):
    def test_claude_default_basic_fields(self) -> None:
        profile = claude_default()
        self.assertEqual(profile.cli_id, "claude-code")
        self.assertEqual(profile.binary, "claude")
        self.assertIn("--dangerously-skip-permissions", profile.bypass_flags)
        self.assertEqual(profile.hook_dialect, "claude")
        self.assertEqual(profile.skill_tree_dir, ".claude/skills")

    def test_claude_default_uses_tuples_for_sequences(self) -> None:
        profile = claude_default()
        self.assertIsInstance(profile.bypass_flags, tuple)
        self.assertIsInstance(profile.mcp_seed_files, tuple)

    def test_claude_default_event_map_is_mapping(self) -> None:
        profile = claude_default()
        self.assertIsInstance(profile.canonical_event_map, Mapping)
        # SessionStart should be a recognised canonical event mapping in the
        # claude default profile.
        self.assertIn("SessionStart", profile.canonical_event_map)

    def test_claude_default_event_map_is_immutable(self) -> None:
        profile = claude_default()
        with self.assertRaises(TypeError):
            profile.canonical_event_map["NewEvent"] = "x"  # type: ignore[index]


class LoadCLIProfileTests(unittest.TestCase):
    def test_load_good_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            profile_path = _write(tmp_path, "claude.toml", GOOD_TOML)
            profile = load_cli_profile(profile_path)
        self.assertEqual(profile.cli_id, "claude-code")
        self.assertEqual(profile.binary, "claude")
        self.assertEqual(profile.prompt_template, "{prompt}")
        self.assertEqual(profile.bypass_flags, ("--dangerously-skip-permissions",))
        self.assertEqual(profile.hook_dialect, "claude")
        self.assertEqual(profile.skill_tree_dir, ".claude/skills")
        self.assertEqual(
            profile.mcp_seed_files,
            (".claude/settings.json", ".mcp.json"),
        )
        self.assertEqual(
            profile.canonical_event_map,
            {"SessionStart": "session_start", "Stop": "stop"},
        )

    def test_load_accepts_string_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            profile_path = _write(tmp_path, "claude.toml", GOOD_TOML)
            profile = load_cli_profile(str(profile_path))
        self.assertEqual(profile.cli_id, "claude-code")

    def test_load_missing_file_raises(self) -> None:
        with self.assertRaises(CLIProfileError):
            load_cli_profile("/nonexistent/path/profile.toml")

    def test_load_invalid_toml_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            profile_path = _write(tmp_path, "bad.toml", "cli_id = \nbinary =")
            with self.assertRaises(CLIProfileError):
                load_cli_profile(profile_path)

    def test_load_unknown_cli_id_raises(self) -> None:
        body = GOOD_TOML.replace(
            'cli_id = "claude-code"', 'cli_id = "not-a-cli"'
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            profile_path = _write(tmp_path, "x.toml", body)
            with self.assertRaises(CLIProfileError):
                load_cli_profile(profile_path)

    def test_load_unknown_hook_dialect_raises(self) -> None:
        body = GOOD_TOML.replace(
            'hook_dialect = "claude"', 'hook_dialect = "bogus"'
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            profile_path = _write(tmp_path, "x.toml", body)
            with self.assertRaises(CLIProfileError):
                load_cli_profile(profile_path)

    def test_load_missing_required_field_raises(self) -> None:
        body = "\n".join(
            line for line in GOOD_TOML.splitlines() if not line.startswith("binary ")
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            profile_path = _write(tmp_path, "x.toml", body + "\n")
            with self.assertRaises(CLIProfileError):
                load_cli_profile(profile_path)

    def test_load_defaults_optional_lists(self) -> None:
        body = """\
cli_id = "codex"
binary = "codex"
prompt_template = "{prompt}"
hook_dialect = "none"
skill_tree_dir = ".agents/skills"

[canonical_event_map]
"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            profile_path = _write(tmp_path, "codex.toml", body)
            profile = load_cli_profile(profile_path)
        self.assertEqual(profile.bypass_flags, ())
        self.assertEqual(profile.mcp_seed_files, ())
        self.assertEqual(profile.canonical_event_map, {})

    def test_loaded_profile_is_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            profile_path = _write(tmp_path, "claude.toml", GOOD_TOML)
            profile = load_cli_profile(profile_path)
        with self.assertRaises(FrozenInstanceError):
            profile.cli_id = "codex"  # type: ignore[misc]

    def test_load_rejects_absolute_skill_tree_dir(self) -> None:
        body = GOOD_TOML.replace(
            'skill_tree_dir = ".claude/skills"',
            'skill_tree_dir = "/abs/skills"',
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            profile_path = _write(tmp_path, "x.toml", body)
            with self.assertRaises(CLIProfileError):
                load_cli_profile(profile_path)

    def test_load_rejects_absolute_mcp_seed_files(self) -> None:
        body = GOOD_TOML.replace(
            'mcp_seed_files = [".claude/settings.json", ".mcp.json"]',
            'mcp_seed_files = ["/etc/passwd"]',
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            profile_path = _write(tmp_path, "x.toml", body)
            with self.assertRaises(CLIProfileError):
                load_cli_profile(profile_path)


if __name__ == "__main__":
    unittest.main()
