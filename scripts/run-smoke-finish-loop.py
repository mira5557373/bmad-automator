#!/usr/bin/env python3
from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import argparse
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "skills" / "bmad-story-automator" / "src"))

from story_automator.commands.basic import cmd_commit_story  # noqa: E402
from story_automator.commands.orchestrator import cmd_orchestrator_helper  # noqa: E402
from story_automator.commands.state import cmd_build_state_doc, cmd_state_metrics, cmd_validate_state  # noqa: E402
from story_automator.commands.tmux import cmd_tmux_wrapper  # noqa: E402


class FinishSmokeError(Exception):
    pass


class FinishLoopSmokeRunner:
    def __init__(self, *, target_repo: Path | None = None, allow_unsafe_repo: bool = False) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name) / "finish-smoke"
        self.output = self.project / "_bmad-output" / "story-automator"
        self.artifacts = self.project / "_bmad-output" / "implementation-artifacts"
        self.target_repo = target_repo
        self.allow_unsafe_repo = allow_unsafe_repo
        self.results: dict[str, object] = {}

    def close(self) -> None:
        self.tmp.cleanup()

    def run(self) -> dict[str, object]:
        host = self._host_sentinel()
        self._install_fixture()
        self._init_git()
        state_file = self._build_state()
        commit_repo = self._resolve_commit_repo()
        marker = self._create_marker(state_file)
        commits = []
        for story_id in ("1.1", "1.2", "2.1"):
            commits.append(self._finish_story(state_file, story_id, commit_repo))
            self._maybe_run_retro(state_file, story_id)
        self._complete_and_wrap(state_file, marker)
        self._assert_host_unchanged(host)
        return self._write_report(state_file, commits, commit_repo)

    def _install_fixture(self) -> None:
        skills = self.project / ".agents" / "skills"
        skills.mkdir(parents=True)
        shutil.copytree(REPO_ROOT / "skills" / "bmad-story-automator", skills / "bmad-story-automator")
        shutil.copytree(REPO_ROOT / "skills" / "bmad-story-automator-review", skills / "bmad-story-automator-review")
        for name in ("bmad-create-story", "bmad-dev-story", "bmad-retrospective", "bmad-qa-generate-e2e-tests"):
            folder = skills / name
            folder.mkdir()
            (folder / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
            (folder / "workflow.md").write_text(f"# {name}\n", encoding="utf-8")
            (folder / "checklist.md").write_text("# checklist\n", encoding="utf-8")
        self.artifacts.mkdir(parents=True)
        self._write_sprint({"1.1": "done", "1.2": "ready-for-dev", "2.1": "ready-for-dev"})
        for story_id in ("1.1", "1.2", "2.1"):
            self._write_story(story_id, "done" if story_id == "1.1" else "ready-for-dev")
        self._write_epic_file("1", ["1.1", "1.2"])
        self._write_epic_file("2", ["2.1"])

    def _init_git(self) -> None:
        self._git("init")
        self._git("config", "user.email", "smoke@example.invalid")
        self._git("config", "user.name", "Finish Smoke")
        (self.project / "README.md").write_text("# Finish smoke repo\n", encoding="utf-8")
        self._git("add", "README.md")
        self._git("commit", "-m", "chore: seed smoke repo")

    def _build_state(self) -> Path:
        config = {
            "epic": "multi",
            "epicName": "Finish Loop Smoke",
            "storyRange": ["1.1", "1.2", "2.1"],
            "status": "IN_PROGRESS",
            "currentStory": "1.1",
            "currentStep": "step-03a-execute-review",
            "aiCommand": "codex exec",
            "customInstructions": "Finish-loop deterministic smoke.",
            "overrides": {"skipAutomate": False, "maxParallel": 1},
            "agentConfig": {"defaultPrimary": "codex", "defaultFallback": False, "perTask": {"retro": {"primary": "claude", "fallback": False}}},
        }
        template = self.project / ".agents" / "skills" / "bmad-story-automator" / "templates" / "state-document.md"
        payload = self._json(*self._call(cmd_build_state_doc, ["--template", str(template), "--output-folder", str(self.output), "--config-json", json.dumps(config)]))
        self._expect(payload["ok"] is True, f"build state failed: {payload}")
        state = Path(str(payload["path"]))
        for story_id in ("1.1", "1.2", "2.1"):
            self._replace_progress(state, story_id, "done", "done", "-", "-", "-", "in-progress")
        return state

    def _finish_story(self, state: Path, story_id: str, commit_repo: Path) -> dict[str, object]:
        self._state_update(state, currentStory=story_id, currentStep="step-03a-execute-review")
        automate = "done" if story_id != "1.2" else "skip"
        self._replace_progress(state, story_id, "done", "done", automate, "-", "-", "in-progress")
        incomplete = None
        if story_id == "1.2":
            self._write_story(story_id, "in-progress")
            incomplete = self._json(*self._call(cmd_orchestrator_helper, ["verify-code-review", story_id]))
            self._expect(incomplete["verified"] is False and incomplete["reason"] == "workflow_not_complete", f"incomplete review not surfaced: {incomplete}")
        self._write_story(story_id, "done")
        review = self._json(*self._call(cmd_orchestrator_helper, ["verify-step", "review", story_id, "--state-file", str(state)]))
        self._expect(review["verified"] is True, f"review verification failed: {review}")
        self._replace_progress(state, story_id, "done", "done", automate, "done", "-", "in-progress")
        change = commit_repo / f"story-{story_id.replace('.', '-')}.txt"
        change.write_text(f"implemented {story_id} at {self._iso_now()}\n", encoding="utf-8")
        commit = self._json(*self._call(cmd_commit_story, ["--repo", str(commit_repo), "--story", story_id, "--title", f"Finish smoke {story_id}"]))
        self._expect(commit["ok"] is True and self._git("rev-parse", "HEAD", cwd=commit_repo).stdout.strip() == commit["commit"], f"commit failed: {commit}")
        self._write_sprint_status(story_id, "done")
        final = self._json(*self._call(cmd_orchestrator_helper, ["story-file-status", story_id]))
        sprint = self._json(*self._call(cmd_orchestrator_helper, ["sprint-status", "get", story_id]))
        self._expect(final["status"] == "done" and sprint["done"] is True, f"final source check failed: {final} {sprint}")
        self._replace_progress(state, story_id, "done", "done", automate, "done", "done", "done")
        self._append_log(state, f"Story {story_id}: complete (commit + sprint-status verified)")
        return {"story": story_id, "commit": commit["commit"], "automate": automate, "review": review, "incompleteReview": incomplete}

    def _maybe_run_retro(self, state: Path, story_id: str) -> None:
        epic = story_id.split(".", 1)[0]
        last = self._json(*self._call(cmd_orchestrator_helper, ["check-epic-complete", epic, story_id, "--state-file", str(state)]))
        stories = self._json(*self._call(cmd_orchestrator_helper, ["get-epic-stories", epic, "--state-file", str(state)]))
        status = self._json(*self._call(cmd_orchestrator_helper, ["sprint-status", "check-epic", epic]))
        if not (last.get("isLastStory") and status.get("allStoriesDone")):
            return
        retro_agent = self._json(*self._call(cmd_orchestrator_helper, ["retro-agent", "--state-file", str(state)]))
        code, retro_cmd = self._call(cmd_tmux_wrapper, ["build-cmd", "retro", epic, "--agent", str(retro_agent["primary"])])
        self._expect(code == 0 and "retrospective" in retro_cmd.lower(), f"retro build-cmd failed: {retro_cmd}")
        self._append_log(state, f"Epic {epic} retrospective: skipped (reason: deterministic_smoke_runner)")
        self._upsert_retro_state(state, epic, "skipped", "deterministic_smoke_runner")
        self.results.setdefault("retrospectives", {})[f"epic-{epic}"] = {"status": "skipped", "reason": "deterministic_smoke_runner", "stories": stories["stories"]}

    def _complete_and_wrap(self, state: Path, marker: Path) -> None:
        self._state_update(state, status="EXECUTION_COMPLETE", currentStep="step-04-wrapup")
        self._append_log(state, "All stories complete - execution finished")
        metrics = self._json(*self._call(cmd_state_metrics, ["--state", str(state)]))
        self._expect(metrics["total"] == 3 and metrics["storiesCompleted"] == 3, f"metrics failed: {metrics}")
        learnings = self.output / "learnings.md"
        learnings.write_text(f"## Run: {self._iso_now()}\n\n- Finish-loop smoke completed.\n", encoding="utf-8")
        self._state_update(state, status="COMPLETE")
        self._append_log(state, "State document finalized")
        code, _ = self._call(cmd_orchestrator_helper, ["marker", "remove"])
        self._expect(code == 0 and not marker.exists(), "marker not removed on wrapup")
        validation = self._json(*self._call(cmd_validate_state, ["--state", str(state)]))
        self._expect(validation["issueCount"] == 0, f"final state invalid: {validation}")
        self.results["wrapup"] = {"metrics": metrics, "learnings": str(learnings.relative_to(self.project)), "markerRemoved": True}

    def _resolve_commit_repo(self) -> Path:
        target = (self.target_repo or self.project).resolve()
        if self._repo_allowed(target):
            self.results["targetGuard"] = {
                "unsafeHostRejected": self._guard_rejects(REPO_ROOT),
                "target": self._repo_descriptor(target),
            }
            return target
        if self.allow_unsafe_repo:
            self.results["targetGuard"] = {"unsafeOverrideUsed": True, "target": self._repo_descriptor(target)}
            return target
        raise FinishSmokeError(f"unsafe commit repo outside smoke workspace: {target}")

    def _guard_rejects(self, repo: Path) -> bool:
        return not self._repo_allowed(repo.resolve())

    def _repo_allowed(self, repo: Path) -> bool:
        smoke_root = self.project.resolve()
        return repo == smoke_root or smoke_root in repo.parents

    def _create_marker(self, state: Path) -> Path:
        marker_info = self._json(*self._call(cmd_orchestrator_helper, ["marker", "path"]))
        marker = Path(str(marker_info["file"]))
        self._call(cmd_orchestrator_helper, ["marker", "create", "--epic", "multi", "--story", "1.1", "--remaining", "3", "--state-file", str(state), "--project-slug", "finish-smoke", "--pid", "456"])
        self._expect(marker.exists(), "marker create failed")
        return marker

    def _write_report(self, state: Path, commits: list[dict[str, object]], commit_repo: Path) -> dict[str, object]:
        persisted = self._persist_diagnostics(state, commit_repo)
        report = REPO_ROOT / ".smoke" / "FINISH_LOOP_SMOKE_REPORT.json"
        report.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "createdAt": self._iso_now(),
            "project": self._ephemeral_project_descriptor(),
            "commitRepo": self._repo_descriptor(commit_repo),
            "stateFile": persisted["stateFile"],
            "diagnostics": persisted,
            "commits": commits,
            **self.results,
            "report": str(report),
        }
        report.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        self.results["diagnostics"] = persisted
        self.results["report"] = str(report)
        return payload

    def _persist_diagnostics(self, state: Path, commit_repo: Path) -> dict[str, object]:
        dest = REPO_ROOT / ".smoke" / "finish-loop-diagnostics"
        shutil.rmtree(dest, ignore_errors=True)
        dest.mkdir(parents=True)
        state_dest = dest / state.name
        state_dest.write_text(state.read_text(encoding="utf-8"), encoding="utf-8")
        log = self._git("log", "--oneline", "-5", cwd=commit_repo).stdout
        (dest / "git-log.txt").write_text(log, encoding="utf-8")
        return {
            "folder": str(dest),
            "stateFile": str(state_dest),
            "gitLog": str(dest / "git-log.txt"),
            "gitLogRepo": self._repo_descriptor(commit_repo),
        }

    def _ephemeral_project_descriptor(self) -> dict[str, object]:
        return {
            "kind": "ephemeral",
            "name": "finish-loop smoke fixture",
            "retained": False,
        }

    def _repo_descriptor(self, repo: Path) -> dict[str, object]:
        resolved = repo.resolve()
        if self._repo_allowed(resolved):
            return {
                "kind": "ephemeral",
                "name": "finish-loop commit repo",
                "retained": False,
            }
        return {"kind": "external", "path": str(resolved)}

    def _host_sentinel(self) -> dict[str, str]:
        return {
            "head": self._run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT).stdout.strip(),
            "status": self._run(["git", "status", "--porcelain"], cwd=REPO_ROOT).stdout,
        }

    def _assert_host_unchanged(self, before: dict[str, str]) -> None:
        after = self._host_sentinel()
        self._expect(after == before, f"host repo changed: before={before} after={after}")
        self.results["hostIsolation"] = {"headUnchanged": True, "statusUnchanged": True}

    def _write_sprint(self, statuses: dict[str, str]) -> None:
        rows = "\n".join(f"{story}: {status}" for story, status in statuses.items())
        (self.artifacts / "sprint-status.yaml").write_text(rows + "\n", encoding="utf-8")

    def _write_sprint_status(self, story_id: str, status: str) -> None:
        sprint = self.artifacts / "sprint-status.yaml"
        text = sprint.read_text(encoding="utf-8")
        text = text.replace(f"{story_id}: ready-for-dev", f"{story_id}: {status}").replace(f"{story_id}: in-progress", f"{story_id}: {status}")
        sprint.write_text(text, encoding="utf-8")

    def _write_story(self, story_id: str, status: str) -> None:
        path = self.artifacts / f"{story_id.replace('.', '-')}-finish-smoke.md"
        path.write_text(f"---\nTitle: Story {story_id}\nStatus: {status}\n---\n\n# Story {story_id}\n", encoding="utf-8")

    def _write_epic_file(self, epic: str, stories: list[str]) -> None:
        lines = [f"# Epic {epic}", ""]
        for story in stories:
            lines.append(f"### Story {story}: Finish smoke {story}")
        (self.artifacts / f"epic-{epic}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _replace_progress(self, state: Path, story_id: str, *cells: str) -> None:
        row = f"| {story_id} | " + " | ".join(cells) + " |"
        text = state.read_text(encoding="utf-8")
        import re

        state.write_text(re.sub(rf"(?m)^\| {re.escape(story_id)} \|.*$", row, text), encoding="utf-8")

    def _append_log(self, state: Path, message: str) -> None:
        state.write_text(state.read_text(encoding="utf-8") + f"\n- **[{self._iso_now()}]** {message}\n", encoding="utf-8")

    def _state_update(self, state: Path, **fields: object) -> None:
        for key, value in fields.items():
            payload = self._json(*self._call(cmd_orchestrator_helper, ["state-update", str(state), "--set", f"{key}={value}"]))
            self._expect(payload["ok"] is True, f"state update failed {key}: {payload}")

    def _upsert_retro_state(self, state: Path, epic: str, status: str, reason: str) -> None:
        text = state.read_text(encoding="utf-8")
        block = (
            f"\nretrospectives.epic-{epic}:\n"
            f"  status: {status}\n"
            f"  reason: {reason}\n"
            f"  timestamp: {self._iso_now()}\n"
        )
        marker = "---"
        parts = text.split(marker, 2)
        self._expect(len(parts) == 3, "state frontmatter missing for retro update")
        front = re.sub(rf"\nretrospectives\.epic-{re.escape(epic)}:\n(?:  .*\n)*", "\n", parts[1])
        state.write_text(f"{marker}{front.rstrip()}{block}{marker}{parts[2]}", encoding="utf-8")

    def _git(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return self._run(["git", *args], cwd=cwd or self.project)

    def _run(self, args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=True)

    def _call(self, fn, args: list[str]) -> tuple[int, str]:
        old_env = os.environ.copy()
        os.environ["PROJECT_ROOT"] = str(self.project)
        os.environ["BMAD_RUNTIME_PROVIDER"] = "codex"
        out = io.StringIO()
        try:
            with redirect_stdout(out):
                code = fn(args)
            return code, out.getvalue()
        finally:
            os.environ.clear()
            os.environ.update(old_env)

    def _json(self, code: int, raw: str) -> dict[str, object]:
        self._expect(code in {0, 1}, f"unexpected exit {code}: {raw}")
        return json.loads(raw)

    def _expect(self, condition: bool, message: str) -> None:
        if not condition:
            raise FinishSmokeError(message)

    def _iso_now(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run deterministic finish-loop smoke.")
    parser.add_argument("--target-repo", default="", help="Commit target repo. Defaults to the temp smoke repo.")
    parser.add_argument("--allow-unsafe-repo", action="store_true", help="Allow committing outside the smoke workspace for manual debugging.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    runner = FinishLoopSmokeRunner(
        target_repo=Path(args.target_repo) if args.target_repo else None,
        allow_unsafe_repo=bool(args.allow_unsafe_repo),
    )
    try:
        summary = runner.run()
    except (FinishSmokeError, OSError, subprocess.CalledProcessError, ValueError, json.JSONDecodeError) as exc:
        print(f"finish-loop smoke failed: {exc}", file=sys.stderr)
        return 1
    finally:
        runner.close()
    print("finish-loop smoke ok")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
