#!/usr/bin/env python3
"""Run the pinned gunz Story Automator smoke deterministically."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from smoke_prep.config import repo_root
from smoke_prep.process import SmokeError, deterministic_smoke_env, ensure_tool
from smoke_prep.workspace import resolve_workspace


STORY_ID = "1.1"
OUTPUT_FOLDER = Path("_bmad-output/story-automator")
IMPLEMENTATION_FOLDER = Path("_bmad-output/implementation-artifacts")
EPIC_FILE = Path("_bmad-output/planning-artifacts/epics.md")
SPRINT_STATUS = IMPLEMENTATION_FOLDER / "sprint-status.yaml"
SKILL_ROOT = Path(".claude/skills/bmad-story-automator")
HELPER = SKILL_ROOT / "scripts/story-automator"
RULES = SKILL_ROOT / "data/complexity-rules.json"
STATE_TEMPLATE = SKILL_ROOT / "templates/state-document.md"
AGENT_CONFIG = {"defaultPrimary": "codex", "defaultFallback": False}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run deterministic Story Automator smoke checks against a prepared gunz repo.",
    )
    parser.add_argument(
        "--workspace",
        default=".smoke",
        help="Repo-relative smoke workspace produced by smoke:prepare.",
    )
    parser.add_argument(
        "--story",
        default=STORY_ID,
        choices=[STORY_ID],
        help="Story ID to exercise. Defaults to 1.1.",
    )
    parser.add_argument(
        "--keep-artifacts",
        action="store_true",
        help="Do not clear prior smoke-generated story/state artifacts before running.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    root = repo_root()
    try:
        ensure_tool("git")
        workspace = resolve_workspace(root, args.workspace)
        project = workspace / "gunz"
        if not project.is_dir():
            raise SmokeError(f"prepared project missing: {project}. Run smoke:prepare first.")
        runner = SmokeRunner(root=root, workspace=workspace, project=project, story_id=args.story)
        summary = runner.run(reset_artifacts=not args.keep_artifacts)
    except (OSError, subprocess.CalledProcessError, SmokeError, ValueError) as exc:
        print(f"smoke run failed: {exc}", file=sys.stderr)
        return 1

    print("")
    print("smoke run ok")
    print(json.dumps(summary, indent=2))
    return 0


class SmokeRunner:
    def __init__(self, *, root: Path, workspace: Path, project: Path, story_id: str) -> None:
        self.root = root
        self.workspace = workspace
        self.project = project
        self.story_id = story_id
        self.run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.env = deterministic_smoke_env(project)
        self.helper = project / HELPER

    def run(self, *, reset_artifacts: bool) -> dict[str, Any]:
        self._assert_prepared()
        if reset_artifacts:
            self._reset_generated_artifacts()

        hook = self._helper_json(
            "ensure-stop-hook",
            "--settings",
            ".claude/settings.json",
            "--command",
            ".claude/skills/bmad-story-automator/scripts/story-automator",
            "stop-hook",
            "--timeout",
            "10",
        )
        self._write_init_log(hook)

        epic = self._helper_json("parse-epic", "--file", str(EPIC_FILE))
        stories = epic.get("stories")
        if not isinstance(stories, list) or not stories:
            raise SmokeError("parse-epic returned no stories")
        ids_csv = ",".join(str(story.get("storyId")) for story in stories if isinstance(story, dict))
        story_count = int(epic.get("count") or len(stories))
        selected = self._helper_json("parse-story-range", "--input", self.story_id, "--total", str(story_count), "--ids", ids_csv)
        selected_ids = selected.get("storyIds")
        if selected_ids != [self.story_id]:
            raise SmokeError(f"story range did not select only {self.story_id}: {selected}")
        story = self._helper_json("parse-story", "--epic", str(EPIC_FILE), "--story", self.story_id, "--rules", str(RULES))
        complexity = story.get("complexity")
        if not isinstance(complexity, dict) or not complexity.get("level"):
            raise SmokeError("parse-story did not return complexity")

        before_count = self._story_count()
        preflight_path = self._write_preflight(epic, selected, story)
        state_path = self._build_state(epic, selected)
        complexity_path = self._write_complexity(state_path, story)
        agents_path = self._build_agents(state_path, complexity_path)
        self._finalize_state(state_path, agents_path, complexity_path)
        self._create_marker(state_path)
        story_path = self._write_story_artifact(story)
        self._update_sprint_status(story_path)
        after_count = self._story_count()

        state_validation = self._helper_json("validate-state", "--state", str(state_path))
        if state_validation.get("ok") is not True or state_validation.get("issueCount") != 0:
            raise SmokeError(f"state validation failed: {state_validation}")
        story_validation = self._helper_json(
            "validate-story-creation",
            "check",
            self.story_id,
            "--before",
            str(before_count),
            "--after",
            str(after_count),
            "--state-file",
            str(state_path),
        )
        if story_validation.get("verified") is not True:
            raise SmokeError(f"story validation failed: {story_validation}")
        sprint_status = self._helper_json("orchestrator-helper", "sprint-status", "get", self.story_id)
        if sprint_status.get("status") != "ready-for-dev":
            raise SmokeError(f"sprint status not ready-for-dev: {sprint_status}")

        report_path = self._write_report(
            state_path=state_path,
            preflight_path=preflight_path,
            complexity_path=complexity_path,
            agents_path=agents_path,
            story_path=story_path,
            story=story,
            state_validation=state_validation,
            story_validation=story_validation,
            sprint_status=sprint_status,
        )
        return {
            "project": str(self.project),
            "report": str(report_path),
            "story": self.story_id,
            "story_file": str(story_path),
            "state_file": str(state_path),
            "complexity": complexity,
            "sprint_status": sprint_status,
        }

    def _assert_prepared(self) -> None:
        for rel in (HELPER, EPIC_FILE, RULES, STATE_TEMPLATE, SPRINT_STATUS):
            path = self.project / rel
            if not path.is_file():
                raise SmokeError(f"prepared smoke file missing: {path}")
        self._run(str(self.helper), "--help")

    def _reset_generated_artifacts(self) -> None:
        shutil.rmtree(self.project / OUTPUT_FOLDER, ignore_errors=True)
        marker_info = self._marker_path_info()
        marker = Path(str(marker_info["file"]))
        marker.unlink(missing_ok=True)
        for path in (self.project / IMPLEMENTATION_FOLDER).glob(f"{self._story_prefix()}-*.md"):
            path.unlink()
        sprint = self.project / SPRINT_STATUS
        text = sprint.read_text(encoding="utf-8")
        text = re.sub(r"(?m)^(\s*epic-1:\s*).*$", r"\1backlog", text)
        text = re.sub(rf"(?m)^(\s*{re.escape(self._story_slug())}:\s*).*$", r"\1backlog", text)
        sprint.write_text(text, encoding="utf-8")

    def _write_init_log(self, hook: dict[str, Any]) -> None:
        folder = self.project / OUTPUT_FOLDER
        folder.mkdir(parents=True, exist_ok=True)
        changed = str(hook.get("changed", "")).lower()
        (folder / f"init-log-{self.run_id}.md").write_text(
            f"[{self._iso_now()}] init: stop-hook-changed={changed} existing_state=\n",
            encoding="utf-8",
        )

    def _write_preflight(self, epic: dict[str, Any], selected: dict[str, Any], story: dict[str, Any]) -> Path:
        path = self.project / OUTPUT_FOLDER / f"preflight-1-{self.run_id}.md"
        complexity = story["complexity"]
        content = [
            "# Preflight Snapshot",
            "",
            f"- Timestamp: {self.run_id}",
            f"- Epic path: {EPIC_FILE}",
            f"- Epic name: {epic.get('epicTitle')}",
            f"- Story count: {epic.get('count')}",
            f"- Selected count: {selected.get('count')}",
            f"- Selected IDs: {', '.join(selected.get('storyIds', []))}",
            "- Custom instructions:",
            "",
            "## Complexity Summary",
            f"- {self.story_id} | {complexity.get('level')} | score={complexity.get('score')}",
            "",
            "## Stories JSON",
            "```json",
            json.dumps([_story_summary(story)], indent=2),
            "```",
            "",
        ]
        path.write_text("\n".join(content), encoding="utf-8")
        return path.relative_to(self.project)

    def _build_state(self, epic: dict[str, Any], selected: dict[str, Any]) -> Path:
        config = {
            "epic": self.story_id.split(".", 1)[0],
            "epicName": epic.get("epicTitle", ""),
            "storyRange": selected.get("storyIds", []),
            "status": "READY",
            "currentStory": None,
            "currentStep": "preflight",
            "aiCommand": "codex exec --full-auto",
            "customInstructions": "",
            "overrides": {"skipAutomate": True, "maxParallel": 1},
            "agentConfig": AGENT_CONFIG,
        }
        result = self._helper_json(
            "build-state-doc",
            "--template",
            str(STATE_TEMPLATE),
            "--output-folder",
            str(OUTPUT_FOLDER),
            "--config-json",
            json.dumps(config),
        )
        path = str(result.get("path") or "")
        if not path:
            raise SmokeError(f"build-state-doc did not return a path: {result}")
        return Path(path)

    def _write_complexity(self, state_path: Path, story: dict[str, Any]) -> Path:
        path = OUTPUT_FOLDER / f"complexity-{state_path.stem}.json"
        (self.project / path).write_text(
            json.dumps({"stories": [_story_summary(story)]}, indent=2) + "\n",
            encoding="utf-8",
        )
        return path

    def _build_agents(self, state_path: Path, complexity_path: Path) -> Path:
        path = OUTPUT_FOLDER / "agents" / f"agents-{state_path.stem}.md"
        result = self._helper_json(
            "orchestrator-helper",
            "agents-build",
            "--state-file",
            str(state_path),
            "--complexity-file",
            str(complexity_path),
            "--output",
            str(path),
            "--config-json",
            json.dumps(AGENT_CONFIG),
        )
        if result.get("ok") is not True:
            raise SmokeError(f"agents-build failed: {result}")
        return path

    def _finalize_state(self, state_path: Path, agents_path: Path, complexity_path: Path) -> None:
        for key, value in (
            ("agentsFile", str(agents_path)),
            ("complexityFile", str(complexity_path)),
            ("status", "IN_PROGRESS"),
            ("currentStory", self.story_id),
            ("currentStep", "step-03-execute"),
            ("lastUpdated", self._iso_now()),
        ):
            result = self._helper_json("orchestrator-helper", "state-update", str(state_path), "--set", f"{key}={value}")
            if result.get("ok") is not True:
                raise SmokeError(f"state-update failed for {key}: {result}")

    def _create_marker(self, state_path: Path) -> None:
        marker_info = self._marker_path_info()
        self._helper_json("ensure-marker-gitignore", "--gitignore", ".gitignore", "--entry", str(marker_info["entry"]))
        slug = self._helper_json("derive-project-slug").get("slug") or "gunz"
        result = self._run(
            str(self.helper),
            "orchestrator-helper",
            "marker",
            "create",
            "--epic",
            "1",
            "--story",
            self.story_id,
            "--remaining",
            "1",
            "--state-file",
            str(state_path),
            "--project-slug",
            str(slug),
            "--pid",
            str(os.getpid()),
            "--heartbeat",
            self._iso_now(),
        )
        if "Marker created:" not in result.stdout:
            raise SmokeError(f"marker create failed: {result.stdout}")
        marker = Path(str(marker_info["file"]))
        if not marker.is_file():
            raise SmokeError(f"marker was not created at active path: {marker}")

    def _marker_path_info(self) -> dict[str, Any]:
        marker_info = self._helper_json("orchestrator-helper", "marker", "path")
        if not marker_info.get("file") or not marker_info.get("entry"):
            raise SmokeError(f"marker path helper returned incomplete payload: {marker_info}")
        return marker_info

    def _write_story_artifact(self, story: dict[str, Any]) -> Path:
        folder = self.project / IMPLEMENTATION_FOLDER
        folder.mkdir(parents=True, exist_ok=True)
        title = str(story.get("title") or "Story")
        criteria = story.get("acceptanceCriteria")
        ac_lines = [str(item) for item in criteria] if isinstance(criteria, list) else []
        path = folder / f"{self._story_slug()}.md"
        content = [
            f"# Story {self.story_id}: {title}",
            "",
            "Status: ready-for-dev",
            "",
            "<!-- Deterministic smoke artifact. Live create-story quality remains covered by manual/LLM smoke. -->",
            "",
            "## Story",
            "",
            str(story.get("description") or ""),
            "",
            "## Acceptance Criteria",
            "",
            *[f"- {line}" for line in ac_lines[:12]],
            "",
            "## Dev Agent Record",
            "",
            "### Completion Notes List",
            "",
            "- Deterministic smoke created this artifact without invoking a live LLM.",
            "",
            "### File List",
            "",
            f"- `{IMPLEMENTATION_FOLDER / path.name}`",
            "",
        ]
        path.write_text("\n".join(content), encoding="utf-8")
        return path.relative_to(self.project)

    def _update_sprint_status(self, story_path: Path) -> None:
        sprint = self.project / SPRINT_STATUS
        text = sprint.read_text(encoding="utf-8")
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        text = re.sub(r"(?m)^# last_updated:.*$", f"# last_updated: {today}", text)
        text = re.sub(r"(?m)^last_updated:.*$", f"last_updated: {today}", text)
        text = re.sub(r"(?m)^(\s*epic-1:\s*).*$", r"\1in-progress", text)
        text = re.sub(rf"(?m)^(\s*{re.escape(story_path.stem)}:\s*).*$", r"\1ready-for-dev", text)
        sprint.write_text(text, encoding="utf-8")

    def _write_report(
        self,
        *,
        state_path: Path,
        preflight_path: Path,
        complexity_path: Path,
        agents_path: Path,
        story_path: Path,
        story: dict[str, Any],
        state_validation: dict[str, Any],
        story_validation: dict[str, Any],
        sprint_status: dict[str, Any],
    ) -> Path:
        report = self.workspace / "AUTOMATED_SMOKE_REPORT.md"
        complexity = story["complexity"]
        lines = [
            "# Automated Story Automator Smoke",
            "",
            f"- Timestamp: {self._iso_now()}",
            f"- Project: `{self.project}`",
            f"- Story: `{self.story_id}`",
            f"- Story title: `{story.get('title')}`",
            f"- Complexity: `{complexity.get('level')}` score `{complexity.get('score')}`",
            "",
            "## Artifacts",
            "",
            f"- `{preflight_path}`",
            f"- `{state_path}`",
            f"- `{complexity_path}`",
            f"- `{agents_path}`",
            f"- `{story_path}`",
            f"- `{SPRINT_STATUS}`",
            "",
            "## Verification",
            "",
            f"- State: `{json.dumps(state_validation, separators=(',', ':'))}`",
            f"- Story creation: `{json.dumps(story_validation, separators=(',', ':'))}`",
            f"- Sprint status: `{json.dumps(sprint_status, separators=(',', ':'))}`",
            "",
        ]
        report.write_text("\n".join(lines), encoding="utf-8")
        return report

    def _story_count(self) -> int:
        result = self._run(str(self.helper), "validate-story-creation", "count", self.story_id)
        return int(result.stdout.strip())

    def _story_prefix(self) -> str:
        return self.story_id.replace(".", "-")

    def _story_slug(self) -> str:
        status = self._helper_json("orchestrator-helper", "sprint-status", "get", self.story_id)
        story_key = str(status.get("story") or "")
        if status.get("found") is True and story_key:
            return story_key
        parsed = self._helper_json("parse-story", "--epic", str(EPIC_FILE), "--story", self.story_id, "--rules", str(RULES))
        return f"{self._story_prefix()}-{_slugify(str(parsed.get('title') or 'story'))}"

    def _helper_json(self, *args: str) -> dict[str, Any]:
        result = self._run(str(self.helper), *args)
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise SmokeError(f"helper did not return json for {' '.join(args)}: {result.stdout}") from exc
        if payload.get("ok") is False:
            raise SmokeError(f"helper failed for {' '.join(args)}: {payload}")
        return payload

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            list(args),
            cwd=self.project,
            env=self.env,
            text=True,
            capture_output=True,
            check=True,
        )

    @staticmethod
    def _iso_now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _story_summary(story: dict[str, Any]) -> dict[str, Any]:
    return {
        "storyId": story.get("storyId"),
        "title": story.get("title"),
        "complexity": story.get("complexity"),
    }


def _slugify(value: str) -> str:
    return "-".join(part for part in re.split(r"[^A-Za-z0-9]+", value.lower()) if part) or "story"


if __name__ == "__main__":
    raise SystemExit(main())
