"""Tests for re.sub replacement safety with unicode / backslash content.

The CLI uses re.sub to write config values into state documents.
When json.dumps encodes non-ASCII characters it produces \\uXXXX
sequences.  Before the lambda fix, those were interpreted as regex
back-references and raised re.error.  These tests confirm that the
lambda form is safe.
"""

from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from story_automator.commands.orchestrator import cmd_orchestrator_helper
from story_automator.commands.state import cmd_build_state_doc


REPO_ROOT = Path(__file__).resolve().parents[1]


class _FixtureMixin:
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tmp.name)
        self.output_dir = self.project_root / "_bmad-output" / "story-automator"
        self._install_bundle()
        self._install_required_skills()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _install_bundle(self) -> None:
        source_skill = REPO_ROOT / "skills" / "bmad-story-automator"
        source_review = REPO_ROOT / "skills" / "bmad-story-automator-review"
        target_root = self.project_root / ".claude" / "skills"
        target_root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_skill, target_root / "bmad-story-automator")
        shutil.copytree(source_review, target_root / "bmad-story-automator-review")

    def _install_required_skills(self) -> None:
        for name in ("bmad-create-story", "bmad-dev-story", "bmad-retrospective", "bmad-qa-generate-e2e-tests"):
            skill_dir = self.project_root / ".claude" / "skills" / name
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
            (skill_dir / "workflow.md").write_text(f"# {name}\n", encoding="utf-8")
        (self.project_root / ".claude" / "skills" / "bmad-create-story" / "discover-inputs.md").write_text("# discover\n", encoding="utf-8")
        (self.project_root / ".claude" / "skills" / "bmad-create-story" / "checklist.md").write_text("# checklist\n", encoding="utf-8")
        (self.project_root / ".claude" / "skills" / "bmad-create-story" / "template.md").write_text("# template\n", encoding="utf-8")
        (self.project_root / ".claude" / "skills" / "bmad-dev-story" / "checklist.md").write_text("# checklist\n", encoding="utf-8")
        (self.project_root / ".claude" / "skills" / "bmad-qa-generate-e2e-tests" / "checklist.md").write_text("# checklist\n", encoding="utf-8")

    def _build_state(self, config: dict | None = None) -> Path:
        stdout = io.StringIO()
        template = self.project_root / ".claude" / "skills" / "bmad-story-automator" / "templates" / "state-document.md"
        with patch_env(self.project_root), redirect_stdout(stdout):
            cmd_build_state_doc(
                [
                    "--template",
                    str(template),
                    "--output-folder",
                    str(self.output_dir),
                    "--config-json",
                    json.dumps(config or self._default_config()),
                ]
            )
        return Path(json.loads(stdout.getvalue())["path"])

    def _default_config(self) -> dict:
        return {
            "epic": "1",
            "epicName": "Epic 1",
            "storyRange": ["1.1"],
            "status": "READY",
            "aiCommand": "claude --dangerously-skip-permissions",
        }


class StateBuildUnicodeTests(_FixtureMixin, unittest.TestCase):
    def test_custom_instructions_with_chinese_characters(self) -> None:
        config = self._default_config()
        config["customInstructions"] = "请使用中文编写代码注释"
        state_file = self._build_state(config)
        text = state_file.read_text(encoding="utf-8")
        self.assertIn("请使用中文编写代码注释", text)

    def test_custom_instructions_with_mixed_unicode(self) -> None:
        config = self._default_config()
        config["customInstructions"] = "Use 日本語コメント for docs"
        state_file = self._build_state(config)
        text = state_file.read_text(encoding="utf-8")
        self.assertIn("customInstructions:", text)
        self.assertIn("日本語コメント", text)

    def test_replacement_value_with_chinese_epic_name(self) -> None:
        config = self._default_config()
        config["epicName"] = "用户认证模块"
        state_file = self._build_state(config)
        text = state_file.read_text(encoding="utf-8")
        self.assertIn("用户认证模块", text)

    def test_replacement_value_with_backslash_in_string(self) -> None:
        config = self._default_config()
        config["epicName"] = r"path\to\file"
        state_file = self._build_state(config)
        text = state_file.read_text(encoding="utf-8")
        self.assertIn(r"\to", text)


class StateUpdateUnicodeTests(_FixtureMixin, unittest.TestCase):
    def test_state_update_with_unicode_value(self) -> None:
        state_file = self._build_state()
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(
                ["state-update", str(state_file), "--set", "aiCommand=claude 中文测试"]
            )
        self.assertEqual(code, 0)
        updated = state_file.read_text(encoding="utf-8")
        self.assertIn("中文测试", updated)

    def test_state_update_with_backslash_value(self) -> None:
        state_file = self._build_state()
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(
                ["state-update", str(state_file), "--set", r"aiCommand=claude \new"]
            )
        self.assertEqual(code, 0)
        updated = state_file.read_text(encoding="utf-8")
        self.assertIn(r"\new", updated)


class patch_env:
    def __init__(self, project_root: Path) -> None:
        self.project_root = str(project_root)
        self.previous = None

    def __enter__(self) -> None:
        import os
        self.previous = os.environ.get("PROJECT_ROOT")
        os.environ["PROJECT_ROOT"] = self.project_root

    def __exit__(self, exc_type, exc, tb) -> None:
        import os
        if self.previous is None:
            os.environ.pop("PROJECT_ROOT", None)
        else:
            os.environ["PROJECT_ROOT"] = self.previous


if __name__ == "__main__":
    unittest.main()
