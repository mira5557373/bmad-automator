from __future__ import annotations

import io
import json
import shutil
import sys  # noqa: F401
import tempfile
import threading  # noqa: F401
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from story_automator.commands.state import cmd_build_state_doc

REPO_ROOT = Path(__file__).resolve().parents[1]


class _PatchEnv:
    def __init__(self, project_root: Path) -> None:
        self.project_root = str(project_root)
        self.previous: str | None = None

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


def _install_bundle(project_root: Path) -> None:
    source_skill = REPO_ROOT / "skills" / "bmad-story-automator"
    source_review = REPO_ROOT / "skills" / "bmad-story-automator-review"
    target_root = project_root / ".claude" / "skills"
    target_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_skill, target_root / "bmad-story-automator")
    shutil.copytree(source_review, target_root / "bmad-story-automator-review")


def _install_required_skills(project_root: Path) -> None:
    for name in (
        "bmad-create-story",
        "bmad-dev-story",
        "bmad-retrospective",
        "bmad-qa-generate-e2e-tests",
    ):
        skill_dir = project_root / ".claude" / "skills" / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
        (skill_dir / "workflow.md").write_text(f"# {name}\n", encoding="utf-8")
    (
        project_root / ".claude" / "skills" / "bmad-create-story" / "discover-inputs.md"
    ).write_text("# discover\n", encoding="utf-8")
    (
        project_root / ".claude" / "skills" / "bmad-create-story" / "checklist.md"
    ).write_text("# checklist\n", encoding="utf-8")
    (
        project_root / ".claude" / "skills" / "bmad-create-story" / "template.md"
    ).write_text("# template\n", encoding="utf-8")
    (
        project_root / ".claude" / "skills" / "bmad-dev-story" / "checklist.md"
    ).write_text("# checklist\n", encoding="utf-8")
    (
        project_root
        / ".claude"
        / "skills"
        / "bmad-qa-generate-e2e-tests"
        / "checklist.md"
    ).write_text("# checklist\n", encoding="utf-8")


def _config() -> dict[str, object]:
    return {
        "epic": "1",
        "epicName": "Epic 1",
        "storyRange": ["1.1"],
        "status": "READY",
        "aiCommand": "claude",
    }


class LegacyMarkerCleanupTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project_root = Path(self._tmp.name)
        self.output_dir = self.project_root / "_bmad-output" / "story-automator"
        _install_bundle(self.project_root)
        _install_required_skills(self.project_root)
        self.template = (
            self.project_root
            / ".claude"
            / "skills"
            / "bmad-story-automator"
            / "templates"
            / "state-document.md"
        )

    def test_build_state_doc_unlinks_legacy_marker_at_startup(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        legacy = self.output_dir / ".state-build.marker"
        legacy.write_text("stale legacy sentinel", encoding="utf-8")

        stdout = io.StringIO()
        with _PatchEnv(self.project_root), redirect_stdout(stdout):
            code = cmd_build_state_doc(
                [
                    "--template",
                    str(self.template),
                    "--output-folder",
                    str(self.output_dir),
                    "--config-json",
                    json.dumps(_config()),
                ]
            )

        self.assertEqual(code, 0)
        self.assertFalse(legacy.exists(), "legacy marker must be removed")

    def test_build_state_doc_succeeds_without_legacy_marker(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        # No legacy marker present — unlink must be missing_ok.
        stdout = io.StringIO()
        with _PatchEnv(self.project_root), redirect_stdout(stdout):
            code = cmd_build_state_doc(
                [
                    "--template",
                    str(self.template),
                    "--output-folder",
                    str(self.output_dir),
                    "--config-json",
                    json.dumps(_config()),
                ]
            )

        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
