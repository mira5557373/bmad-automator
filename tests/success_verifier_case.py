from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from story_automator.commands.state import cmd_build_state_doc


REPO_ROOT = Path(__file__).resolve().parents[1]


class SuccessVerifierCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tmp.name)
        self.output_dir = self.project_root / "_bmad-output" / "story-automator"
        self.artifacts_dir = self.project_root / "_bmad-output" / "implementation-artifacts"
        self.docs_artifacts_dir = self.project_root / "docs" / "bmad" / "implementation-artifacts"
        self._install_bundle()
        self._install_required_skills()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _build_state(self) -> Path:
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
                    json.dumps(
                        {
                            "epic": "1",
                            "epicName": "Epic 1",
                            "storyRange": ["1.2"],
                            "status": "READY",
                            "aiCommand": "claude --dangerously-skip-permissions",
                        }
                    ),
                ]
            )
        return Path(json.loads(stdout.getvalue())["path"])

    def _install_bundle(self) -> None:
        source_skill = REPO_ROOT / "skills" / "bmad-story-automator"
        source_review = REPO_ROOT / "skills" / "bmad-story-automator-review"
        target_root = self.project_root / ".claude" / "skills"
        target_root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_skill, target_root / "bmad-story-automator")
        shutil.copytree(source_review, target_root / "bmad-story-automator-review")

    def _install_required_skills(self) -> None:
        self._make_skill(
            "bmad-create-story",
            extras={"discover-inputs.md": "# discover\n", "checklist.md": "# checklist\n", "template.md": "# template\n"},
        )
        self._make_skill("bmad-dev-story", extras={"checklist.md": "# checklist\n"})
        self._make_skill("bmad-retrospective")
        self._make_skill("bmad-qa-generate-e2e-tests", extras={"checklist.md": "# checklist\n"})

    def _make_skill(self, name: str, *, extras: dict[str, str] | None = None) -> None:
        skill_dir = self.project_root / ".claude" / "skills" / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
        (skill_dir / "workflow.md").write_text(f"# {name}\n", encoding="utf-8")
        for rel, content in (extras or {}).items():
            (skill_dir / rel).write_text(content, encoding="utf-8")

    def _write_story(self, stem: str, *, status: str) -> Path:
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        path = self.artifacts_dir / f"{stem}.md"
        path.write_text(f"---\nStatus: {status}\nTitle: Story\n---\n", encoding="utf-8")
        return path

    def _write_docs_story(self, stem: str, *, status: str) -> Path:
        self.docs_artifacts_dir.mkdir(parents=True, exist_ok=True)
        path = self.docs_artifacts_dir / f"{stem}.md"
        path.write_text(f"---\nStatus: {status}\nTitle: Story\n---\n", encoding="utf-8")
        return path

    def _write_sprint_status(self, content: str) -> None:
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        (self.artifacts_dir / "sprint-status.yaml").write_text(content, encoding="utf-8")

    def _write_docs_sprint_status(self, content: str) -> None:
        self.docs_artifacts_dir.mkdir(parents=True, exist_ok=True)
        (self.docs_artifacts_dir / "sprint-status.yaml").write_text(content, encoding="utf-8")

    def _write_bmad_config(self, content: str) -> None:
        config_dir = self.project_root / "_bmad" / "bmm"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "config.yaml").write_text(content, encoding="utf-8")

    def _write_review_contract(self, payload: dict[str, object]) -> Path:
        path = self.project_root / "review-contract.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def _write_override(self, payload: dict[str, object]) -> None:
        override_dir = self.project_root / "_bmad" / "bmm"
        override_dir.mkdir(parents=True, exist_ok=True)
        (override_dir / "story-automator.policy.json").write_text(json.dumps(payload), encoding="utf-8")


class patch_env:
    def __init__(self, project_root: Path, extra: dict[str, str] | None = None) -> None:
        self.project_root = str(project_root)
        self.extra = extra or {}
        self.previous: dict[str, str | None] = {}

    def __enter__(self) -> None:
        self.previous["PROJECT_ROOT"] = os.environ.get("PROJECT_ROOT")
        os.environ["PROJECT_ROOT"] = self.project_root
        for key, value in self.extra.items():
            self.previous[key] = os.environ.get(key)
            os.environ[key] = value

    def __exit__(self, *_: object) -> None:
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
