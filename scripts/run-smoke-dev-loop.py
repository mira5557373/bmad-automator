#!/usr/bin/env python3
"""Run deterministic two-story Story Automator dev-loop smoke checks."""

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
from smoke_prep.process import SmokeError, ensure_tool
from smoke_prep.workspace import resolve_workspace


STORY_IDS = ("1.1", "1.2")
OUTPUT_FOLDER = Path("_bmad-output/story-automator")
IMPLEMENTATION_FOLDER = Path("_bmad-output/implementation-artifacts")
DEV_LOOP_FOLDER = OUTPUT_FOLDER / "dev-loop"
EPIC_FILE = Path("_bmad-output/planning-artifacts/epics.md")
SPRINT_STATUS = IMPLEMENTATION_FOLDER / "sprint-status.yaml"
SKILL_ROOT = Path(".claude/skills/bmad-story-automator")
HELPER = SKILL_ROOT / "scripts/story-automator"
RULES = SKILL_ROOT / "data/complexity-rules.json"
STATE_TEMPLATE = SKILL_ROOT / "templates/state-document.md"
AGENT_CONFIG = {"defaultPrimary": "codex", "defaultFallback": False}
PARSED_DEV = {
    "status": "SUCCESS",
    "tests_passed": True,
    "build_passed": True,
    "summary": "Deterministic smoke simulated a successful dev-story session.",
    "next_action": "proceed",
}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run deterministic two-story dev-loop smoke checks against prepared gunz.",
    )
    parser.add_argument("--workspace", default=".smoke", help="Repo-relative workspace from smoke:prepare.")
    parser.add_argument(
        "--stories",
        default=",".join(STORY_IDS),
        choices=[",".join(STORY_IDS)],
        help="Story IDs to exercise. Fixed to 1.1,1.2 for this smoke.",
    )
    parser.add_argument("--keep-artifacts", action="store_true", help="Do not clear prior generated dev-loop artifacts.")
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
        runner = DevLoopSmokeRunner(root=root, workspace=workspace, project=project, story_ids=list(STORY_IDS))
        summary = runner.run(reset_artifacts=not args.keep_artifacts)
    except (OSError, subprocess.CalledProcessError, SmokeError, ValueError) as exc:
        print(f"dev-loop smoke failed: {exc}", file=sys.stderr)
        return 1

    print("")
    print("dev-loop smoke ok")
    print(json.dumps(summary, indent=2))
    return 0


class DevLoopSmokeRunner:
    def __init__(self, *, root: Path, workspace: Path, project: Path, story_ids: list[str]) -> None:
        self.root = root
        self.workspace = workspace
        self.project = project
        self.story_ids = story_ids
        self.run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.env = {**os.environ, "PROJECT_ROOT": str(project)}
        self.helper = project / HELPER

    def run(self, *, reset_artifacts: bool) -> dict[str, Any]:
        self._assert_prepared()
        if reset_artifacts:
            self._reset_generated_artifacts()

        epic = self._helper_json("parse-epic", "--file", str(EPIC_FILE))
        story_count = int(epic.get("count") or 0)
        ids_csv = ",".join(str(story.get("storyId")) for story in epic.get("stories", []) if isinstance(story, dict))
        selected = self._helper_json("parse-story-range", "--input", ",".join(self.story_ids), "--total", str(story_count), "--ids", ids_csv)
        if selected.get("storyIds") != self.story_ids:
            raise SmokeError(f"story range did not select exactly {self.story_ids}: {selected}")

        stories = [self._parse_story(story_id) for story_id in self.story_ids]
        state_path = self._build_state(epic, selected)
        complexity_path = self._write_complexity(state_path, stories)
        agents_path = self._build_agents(state_path, complexity_path)
        self._set_state_fields(
            state_path,
            agentsFile=str(agents_path),
            complexityFile=str(complexity_path),
            status="IN_PROGRESS",
            currentStory=self.story_ids[0],
            currentStep="step-03-execute",
            lastUpdated=self._iso_now(),
        )

        results = []
        for index, story in enumerate(stories, start=1):
            results.append(self._run_story_dev_loop(index, len(stories), state_path, story))

        self._set_state_fields(state_path, currentStep="step-03a-execute-review", lastUpdated=self._iso_now())
        self._append_state_log(state_path, "Dev loop complete, proceeding to review phase")

        state_validation = self._helper_json("validate-state", "--state", str(state_path))
        if state_validation.get("ok") is not True or state_validation.get("issueCount") != 0:
            raise SmokeError(f"state validation failed: {state_validation}")
        report_path = self._write_report(state_path, complexity_path, agents_path, results, state_validation)
        return {"project": str(self.project), "report": str(report_path), "stories": results, "state_file": str(state_path)}

    def _assert_prepared(self) -> None:
        for rel in (HELPER, EPIC_FILE, RULES, STATE_TEMPLATE, SPRINT_STATUS):
            path = self.project / rel
            if not path.is_file():
                raise SmokeError(f"prepared smoke file missing: {path}")
        self._run(str(self.helper), "--help")
        self._run(str(self.helper), "tmux-wrapper", "build-cmd", "--help")
        self._run(str(self.helper), "orchestrator-helper", "--help")

    def _reset_generated_artifacts(self) -> None:
        shutil.rmtree(self.project / OUTPUT_FOLDER, ignore_errors=True)
        (self.project / DEV_LOOP_FOLDER).mkdir(parents=True, exist_ok=True)
        for story_id in self.story_ids:
            for path in (self.project / IMPLEMENTATION_FOLDER).glob(f"{self._story_prefix(story_id)}-*.md"):
                path.unlink()
        sprint = self.project / SPRINT_STATUS
        text = sprint.read_text(encoding="utf-8")
        text = re.sub(r"(?m)^(\s*epic-1:\s*).*$", r"\1backlog", text)
        for story_id in self.story_ids:
            text = re.sub(rf"(?m)^(\s*{re.escape(self._story_slug(story_id))}:\s*).*$", r"\1backlog", text)
        sprint.write_text(text, encoding="utf-8")

    def _parse_story(self, story_id: str) -> dict[str, Any]:
        story = self._helper_json("parse-story", "--epic", str(EPIC_FILE), "--story", story_id, "--rules", str(RULES))
        if not isinstance(story.get("complexity"), dict):
            raise SmokeError(f"parse-story did not return complexity for {story_id}")
        return story

    def _build_state(self, epic: dict[str, Any], selected: dict[str, Any]) -> Path:
        config = {
            "epic": "1",
            "epicName": epic.get("epicTitle", ""),
            "storyRange": selected.get("storyIds", []),
            "status": "READY",
            "currentStory": None,
            "currentStep": "preflight",
            "aiCommand": "codex exec --full-auto",
            "customInstructions": "Deterministic smoke for two-story dev loop.",
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

    def _write_complexity(self, state_path: Path, stories: list[dict[str, Any]]) -> Path:
        path = OUTPUT_FOLDER / f"complexity-dev-loop-{state_path.stem}.json"
        summaries = [{"storyId": item["storyId"], "title": item["title"], "complexity": item["complexity"]} for item in stories]
        (self.project / path).write_text(json.dumps({"stories": summaries}, indent=2) + "\n", encoding="utf-8")
        return path

    def _build_agents(self, state_path: Path, complexity_path: Path) -> Path:
        path = OUTPUT_FOLDER / "agents" / f"agents-dev-loop-{state_path.stem}.md"
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

    def _run_story_dev_loop(self, index: int, total: int, state_path: Path, story: dict[str, Any]) -> dict[str, Any]:
        story_id = str(story["storyId"])
        self._set_state_fields(state_path, currentStory=story_id, currentStep="step-03-execute", lastUpdated=self._iso_now())
        self._append_progress_row(state_path, story_id)
        self._append_state_log(state_path, f"Starting story {story_id}")

        create_agent = self._helper_json("orchestrator-helper", "agents-resolve", "--state-file", str(state_path), "--story", story_id, "--task", "create")
        dev_agent = self._helper_json("orchestrator-helper", "agents-resolve", "--state-file", str(state_path), "--story", story_id, "--task", "dev")
        dev_cmd = self._run(
            str(self.helper),
            "tmux-wrapper",
            "build-cmd",
            "dev",
            story_id,
            "--agent",
            str(dev_agent.get("primary") or "codex"),
            "--state-file",
            str(state_path),
        ).stdout.strip()
        if "codex exec" not in dev_cmd and "claude" not in dev_cmd:
            raise SmokeError(f"dev build-cmd did not produce an agent command for {story_id}")

        story_path = self._write_story_artifact(story, "ready-for-dev")
        self._update_sprint_status(story_id, "ready-for-dev")
        create_validation = self._helper_json("orchestrator-helper", "verify-step", "create", story_id, "--state-file", str(state_path))
        if create_validation.get("verified") is not True:
            raise SmokeError(f"create verifier failed for {story_id}: {create_validation}")
        self._replace_progress_row(state_path, story_id, "done", "-", "-", "-", "-", "in-progress")

        dev_log = self._write_dev_log(story_id, dev_cmd)
        parsed_dev = dict(PARSED_DEV)
        if parsed_dev["next_action"] != "proceed":
            raise SmokeError(f"dev parser fixture did not proceed for {story_id}")
        story_path = self._write_story_artifact(story, "done")
        self._write_story_dev_record(story_path, dev_log)
        self._update_sprint_status(story_id, "done")
        self._replace_progress_row(state_path, story_id, "done", "done", "-", "-", "-", "in-progress")

        file_status = self._helper_json("orchestrator-helper", "story-file-status", story_id)
        sprint_status = self._helper_json("orchestrator-helper", "sprint-status", "get", story_id)
        if file_status.get("status") != "done" or sprint_status.get("status") != "done":
            raise SmokeError(f"dev status transition failed for {story_id}: {file_status} {sprint_status}")
        return {
            "story": story_id,
            "index": index,
            "total": total,
            "story_file": str(story_path),
            "dev_log": str(dev_log),
            "create_agent": create_agent,
            "dev_agent": dev_agent,
            "parsed_dev": parsed_dev,
            "file_status": file_status,
            "sprint_status": sprint_status,
        }

    def _write_story_artifact(self, story: dict[str, Any], status: str) -> Path:
        folder = self.project / IMPLEMENTATION_FOLDER
        folder.mkdir(parents=True, exist_ok=True)
        story_id = str(story["storyId"])
        title = str(story.get("title") or "Story")
        path = folder / f"{self._story_slug(story_id)}.md"
        criteria = story.get("acceptanceCriteria")
        ac_lines = [str(item) for item in criteria] if isinstance(criteria, list) else []
        content = [
            "---",
            f"Title: Story {story_id}: {title}",
            f"Status: {status}",
            "---",
            "",
            f"# Story {story_id}: {title}",
            "",
            f"Status: {status}",
            "",
            "<!-- Deterministic dev-loop smoke artifact. Live implementation quality is out of scope. -->",
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
            f"- Deterministic dev-loop smoke marked story {status}.",
            "",
            "### File List",
            "",
            f"- `{IMPLEMENTATION_FOLDER / path.name}`",
            "",
        ]
        path.write_text("\n".join(content), encoding="utf-8")
        return path.relative_to(self.project)

    def _write_dev_log(self, story_id: str, dev_cmd: str) -> Path:
        path = DEV_LOOP_FOLDER / f"dev-{self._story_prefix(story_id)}-{self.run_id}.log"
        payload = dict(PARSED_DEV)
        lines = [
            f"[{self._iso_now()}] dev-story {story_id}",
            f"COMMAND={dev_cmd}",
            f"SUCCESS story={story_id} tests=true build=true",
            json.dumps(payload, separators=(",", ":")),
            "",
        ]
        (self.project / path).write_text("\n".join(lines), encoding="utf-8")
        return path

    def _write_story_dev_record(self, story_path: Path, dev_log: Path) -> None:
        path = self.project / story_path
        text = path.read_text(encoding="utf-8")
        text += f"\n### Debug Log References\n\n- `{dev_log}`\n"
        path.write_text(text, encoding="utf-8")

    def _update_sprint_status(self, story_id: str, status: str) -> None:
        sprint = self.project / SPRINT_STATUS
        text = sprint.read_text(encoding="utf-8")
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        text = re.sub(r"(?m)^# last_updated:.*$", f"# last_updated: {today}", text)
        text = re.sub(r"(?m)^last_updated:.*$", f"last_updated: {today}", text)
        text = re.sub(r"(?m)^(\s*epic-1:\s*).*$", r"\1in-progress", text)
        text = re.sub(rf"(?m)^(\s*{re.escape(self._story_slug(story_id))}:\s*).*$", rf"\1{status}", text)
        sprint.write_text(text, encoding="utf-8")

    def _append_progress_row(self, state_path: Path, story_id: str) -> None:
        state = self.project / state_path
        text = state.read_text(encoding="utf-8")
        if re.search(rf"(?m)^\| {re.escape(story_id)} \|", text):
            return
        row = f"| {story_id} | - | - | - | - | - | in-progress |"
        text = text.replace("<!-- Progress rows will be appended here -->", f"<!-- Progress rows will be appended here -->\n{row}")
        state.write_text(text, encoding="utf-8")

    def _replace_progress_row(self, state_path: Path, story_id: str, *cells: str) -> None:
        state = self.project / state_path
        row = f"| {story_id} | " + " | ".join(cells) + " |"
        text = state.read_text(encoding="utf-8")
        text = re.sub(rf"(?m)^\| {re.escape(story_id)} \|.*$", row, text)
        state.write_text(text, encoding="utf-8")

    def _set_state_fields(self, state_path: Path, **fields: object) -> None:
        for key, value in fields.items():
            result = self._helper_json("orchestrator-helper", "state-update", str(state_path), "--set", f"{key}={value}")
            if result.get("ok") is not True:
                raise SmokeError(f"state-update failed for {key}: {result}")

    def _append_state_log(self, state_path: Path, message: str) -> None:
        state = self.project / state_path
        text = state.read_text(encoding="utf-8")
        text += f"\n- **[{self._iso_now()}]** {message}\n"
        state.write_text(text, encoding="utf-8")

    def _write_report(
        self,
        state_path: Path,
        complexity_path: Path,
        agents_path: Path,
        results: list[dict[str, Any]],
        state_validation: dict[str, Any],
    ) -> Path:
        report = self.workspace / "AUTOMATED_DEV_LOOP_SMOKE_REPORT.md"
        lines = [
            "# Automated Story Automator Dev Loop Smoke",
            "",
            f"- Timestamp: {self._iso_now()}",
            f"- Project: `{self.project}`",
            f"- Stories: `{', '.join(self.story_ids)}`",
            f"- Scope: deterministic dev-loop plumbing; live implementation quality is not asserted.",
            "",
            "## Artifacts",
            "",
            f"- `{state_path}`",
            f"- `{complexity_path}`",
            f"- `{agents_path}`",
            f"- `{DEV_LOOP_FOLDER}`",
            "",
            "## Verification",
            "",
            f"- State: `{json.dumps(state_validation, separators=(',', ':'))}`",
        ]
        for result in results:
            lines.extend(
                [
                    "",
                    f"### Story {result['story']}",
                    "",
                    f"- Story file: `{result['story_file']}`",
                    f"- Dev log: `{result['dev_log']}`",
                    f"- Dev parser fixture: `{json.dumps(result['parsed_dev'], separators=(',', ':'))}`",
                    f"- Story file status: `{json.dumps(result['file_status'], separators=(',', ':'))}`",
                    f"- Sprint status: `{json.dumps(result['sprint_status'], separators=(',', ':'))}`",
                ]
            )
        report.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return report

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
        return subprocess.run(list(args), cwd=self.project, env=self.env, text=True, capture_output=True, check=True)

    @staticmethod
    def _story_prefix(story_id: str) -> str:
        return story_id.replace(".", "-")

    def _story_slug(self, story_id: str) -> str:
        status = self._helper_json("orchestrator-helper", "sprint-status", "get", story_id)
        story_key = str(status.get("story") or "")
        if story_key:
            return story_key
        parsed = self._helper_json("parse-story", "--epic", str(EPIC_FILE), "--story", story_id, "--rules", str(RULES))
        return f"{self._story_prefix(story_id)}-{_slugify(str(parsed.get('title') or 'story'))}"

    @staticmethod
    def _iso_now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _slugify(value: str) -> str:
    return "-".join(part for part in re.split(r"[^A-Za-z0-9]+", value.lower()) if part) or "story"


if __name__ == "__main__":
    raise SystemExit(main())
