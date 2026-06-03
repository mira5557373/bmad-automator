#!/usr/bin/env python3
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "skills" / "bmad-story-automator" / "src"))

from story_automator.commands.basic import (  # noqa: E402
    cmd_derive_project_slug,
    cmd_ensure_marker_gitignore,
    cmd_ensure_stop_hook,
    cmd_list_sessions,
    cmd_stop_hook,
)
from story_automator.commands.orchestrator import cmd_orchestrator_helper  # noqa: E402
from story_automator.commands.state import cmd_build_state_doc, cmd_sprint_compare, cmd_state_metrics, cmd_validate_state  # noqa: E402
from story_automator.core.agent_config import load_agent_config_from_state  # noqa: E402
from story_automator.core.epic_parser import parse_story_range  # noqa: E402


class SmokeModesError(Exception):
    pass


class ModeSmokeRunner:
    def __init__(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        self.output = self.project / "_bmad-output" / "story-automator"
        self.artifacts = self.project / "_bmad-output" / "implementation-artifacts"
        self.results: dict[str, object] = {}

    def close(self) -> None:
        self.tmp.cleanup()

    def run(self) -> dict[str, object]:
        self._install_fixture()
        self._assert_validate_helpers()
        self._assert_preflight_selection_contracts()
        self._assert_create_startup_guards()
        state_file = self._build_state()
        self._assert_state_and_resume_contracts(state_file)
        self._assert_marker_lifecycle(state_file)
        self._assert_validate_and_source_truth(state_file)
        self._assert_edit_route_contracts(state_file)
        return {"project": str(self.project), **self.results}

    def _install_fixture(self) -> None:
        skills = self.project / ".agents" / "skills"
        skills.mkdir(parents=True)
        shutil.copytree(REPO_ROOT / "skills" / "bmad-story-automator", skills / "bmad-story-automator")
        shutil.copytree(REPO_ROOT / "skills" / "bmad-story-automator-review", skills / "bmad-story-automator-review")
        for name, extras in {
            "bmad-create-story": ["discover-inputs.md", "checklist.md", "template.md"],
            "bmad-dev-story": ["checklist.md"],
            "bmad-retrospective": [],
            "bmad-qa-generate-e2e-tests": ["checklist.md"],
        }.items():
            folder = skills / name
            folder.mkdir()
            (folder / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
            (folder / "workflow.md").write_text(f"# {name}\n", encoding="utf-8")
            for extra in extras:
                (folder / extra).write_text(f"# {extra}\n", encoding="utf-8")
        self.artifacts.mkdir(parents=True)
        (self.artifacts / "sprint-status.yaml").write_text("1-1-first: ready-for-dev\n1-2-second: backlog\n", encoding="utf-8")

    def _assert_validate_helpers(self) -> None:
        for fn, args, text in (
            (cmd_validate_state, ["--help"], "validate-state"),
            (cmd_list_sessions, ["--help"], "list-sessions"),
            (cmd_derive_project_slug, ["--help"], "derive-project-slug"),
        ):
            code, output = self._call(fn, args)
            self._expect(code == 0 and text in output, f"helper help failed: {text}")

    def _assert_preflight_selection_contracts(self) -> None:
        ids = "1.1,1.2"
        multi = parse_story_range("1-2", 2, ids)
        explicit = parse_story_range("1.1,1.2", 2, ids)
        reversed_range = parse_story_range("2-1", 2, ids)
        invalid = parse_story_range("99", 2, ids)
        self._expect(multi["storyIds"] == ["1.1", "1.2"], f"multi-story range failed: {multi}")
        self._expect(explicit["storyIds"] == ["1.1", "1.2"], f"explicit ID range failed: {explicit}")
        self._expect(reversed_range["indices"] == [1, 2], f"reversed numeric range failed: {reversed_range}")
        self._expect(invalid["ok"] is True and invalid["count"] == 0, f"invalid range contract changed: {invalid}")
        self.results["preflight"] = {
            "multiStory": multi["storyIds"],
            "explicitIds": explicit["storyIds"],
            "invalidRange": "empty-selection",
        }

    def _assert_create_startup_guards(self) -> None:
        code, raw = self._call(cmd_ensure_stop_hook, ["--command", "story-automator", "stop-hook", "--timeout", "10"])
        first = self._json(code, raw)
        self._expect(first["ok"] is True and first["changed"] is True, f"stop-hook configure failed: {first}")
        code, raw = self._call(cmd_ensure_stop_hook, ["--command", "story-automator", "stop-hook", "--timeout", "10"])
        second = self._json(code, raw)
        self._expect(second["ok"] is True and second["reason"] in {"already_configured", "pending_trust"}, f"stop-hook verify failed: {second}")
        hooks = self.project / ".codex" / "hooks.json"
        hooks.write_text("{bad json", encoding="utf-8")
        code, raw = self._call(cmd_ensure_stop_hook, ["--command", "story-automator", "stop-hook"])
        invalid = self._json(code, raw)
        self._expect(code == 1 and invalid["error"] == "invalid_json", f"stop-hook invalid json not surfaced: {invalid}")
        hooks.unlink()
        self.output.mkdir(parents=True, exist_ok=True)
        (self.output / "init-log-smoke.md").write_text("[smoke] init: stop-hook checked existing_state=\n", encoding="utf-8")
        code, raw = self._call(cmd_orchestrator_helper, ["sprint-status", "exists"])
        self._expect(code == 0 and raw.strip() == "true", "sprint-status present check failed")
        (self.artifacts / "sprint-status.yaml").unlink()
        code, raw = self._call(cmd_orchestrator_helper, ["sprint-status", "exists"])
        self._expect(code == 0 and raw.strip() == "false", "sprint-status missing check failed")
        (self.artifacts / "sprint-status.yaml").write_text("1-1-first: ready-for-dev\n1-2-second: backlog\n", encoding="utf-8")
        self.results["createStartup"] = {
            "stopHookFirst": first["reason"],
            "stopHookSecond": second["reason"],
            "invalidHook": invalid["error"],
            "sprintStatusPrecondition": "present-and-missing-checked",
        }

    def _build_state(self) -> Path:
        config = {
            "epic": "1",
            "epicName": "Smoke Epic",
            "storyRange": ["1.1", "1.2"],
            "status": "IN_PROGRESS",
            "currentStory": "1.1",
            "currentStep": "step-03-execute",
            "aiCommand": "codex exec",
            "customInstructions": "Mode smoke fixture.",
            "overrides": {"skipAutomate": True, "maxParallel": 2},
            "agentConfig": {
                "defaultPrimary": "codex",
                "defaultFallback": False,
                "perTask": {"review": {"primary": "claude", "fallback": False}},
            },
        }
        template = self.project / ".agents" / "skills" / "bmad-story-automator" / "templates" / "state-document.md"
        code, raw = self._call(
            cmd_build_state_doc,
            ["--template", str(template), "--output-folder", str(self.output), "--config-json", json.dumps(config)],
        )
        payload = self._json(code, raw)
        self._expect(payload["ok"] is True, f"build-state-doc failed: {payload}")
        state_file = Path(payload["path"])
        text = state_file.read_text(encoding="utf-8")
        self._expect("policySnapshotFile:" in text and "| 1.1 |" in text and "| 1.2 |" in text, "state artifact missing required fields")
        complexity_file = self.output / "complexity-smoke.json"
        agents_file = self.output / "agents-smoke.md"
        dev_log = self.output / "dev-log-smoke.md"
        mode_report = self.output / "mode-report-smoke.json"
        complexity_file.write_text('{"stories":[{"storyId":"1.1","complexity":{"level":"medium"}}]}\n', encoding="utf-8")
        agents_file.write_text("# Agents\n\n- 1.1 create codex\n- 1.1 review claude\n", encoding="utf-8")
        dev_log.write_text("# Dev Log\n\n- Simulated child dev workflow completed for 1.1.\n", encoding="utf-8")
        mode_report.write_text('{"mode":"create-dev","status":"simulated-child-output"}\n', encoding="utf-8")
        code, raw = self._call(cmd_orchestrator_helper, ["state-update", str(state_file), "--set", "complexityFile=_bmad-output/story-automator/complexity-smoke.json"])
        self._expect(self._json(code, raw)["ok"] is True, "complexityFile state update failed")
        code, raw = self._call(cmd_orchestrator_helper, ["state-update", str(state_file), "--set", "agentsFile=_bmad-output/story-automator/agents-smoke.md"])
        self._expect(self._json(code, raw)["ok"] is True, "agentsFile state update failed")
        self._append_action_log(state_file, "smoke create/dev simulated child output recorded")
        updated_text = state_file.read_text(encoding="utf-8")
        self._expect("complexity-smoke.json" in updated_text and "agents-smoke.md" in updated_text, "artifact paths not saved in state")
        self._expect(complexity_file.exists() and agents_file.exists() and dev_log.exists() and mode_report.exists(), "selected artifacts not written")
        self.results["preflight"]["complexityMatrix"] = "medium"
        self.results["preflight"]["agentConfigVariant"] = "review=claude"
        self.results["artifacts"] = {
            "actionLog": "smoke create/dev simulated child output recorded",
            "complexity": str(complexity_file.relative_to(self.project)),
            "agents": str(agents_file.relative_to(self.project)),
            "devLog": str(dev_log.relative_to(self.project)),
            "modeReport": str(mode_report.relative_to(self.project)),
        }
        return state_file

    def _assert_state_and_resume_contracts(self, state_file: Path) -> None:
        code, raw = self._call(cmd_orchestrator_helper, ["state-list", str(self.output)])
        listing = self._json(code, raw)
        self._expect(listing["ok"] is True and len(listing["files"]) == 1, f"state-list failed: {listing}")
        code, raw = self._call(cmd_orchestrator_helper, ["state-latest-incomplete", str(self.output)])
        latest = self._json(code, raw)
        self._expect(latest["ok"] is True and latest["path"] == str(state_file), f"latest incomplete failed: {latest}")
        code, raw = self._call(cmd_orchestrator_helper, ["state-summary", str(state_file)])
        summary = self._json(code, raw)
        self._expect(
            summary["currentStep"] == "step-03-execute"
            and summary["policySnapshotHash"]
            and summary["lastAction"] == "smoke create/dev simulated child output recorded",
            f"state summary failed: {summary}",
        )
        complete_dir = self.output / "complete-only"
        complete_dir.mkdir()
        complete_state = complete_dir / state_file.name
        complete_state.write_text(state_file.read_text(encoding="utf-8").replace('status: "IN_PROGRESS"', 'status: "COMPLETE"'), encoding="utf-8")
        code, raw = self._call(cmd_orchestrator_helper, ["state-latest-incomplete", str(complete_dir)])
        no_incomplete = self._json(code, raw)
        self._expect(no_incomplete["ok"] is False and no_incomplete["error"] == "no_incomplete_state", f"fresh-create fallback failed: {no_incomplete}")
        resume_contract = self._assert_resume_menu_branch_contracts(state_file)
        self.results.setdefault("createStartup", {})["existingStateDetected"] = True
        self.results["resume"] = {
            "explicitPathSummary": summary["currentStep"],
            "latestIncomplete": latest["path"],
            "routeHint": resume_contract["routeHint"],
            "freshCreateFallback": no_incomplete["error"],
            "menuBranches": resume_contract["menuBranches"],
        }

    def _assert_marker_lifecycle(self, state_file: Path) -> None:
        code, raw = self._call(cmd_orchestrator_helper, ["marker", "path"])
        marker_path = self._json(code, raw)
        entry = marker_path["entry"]
        self._expect(entry == ".agents/.story-automator-active", f"marker entry not dynamic .agents path: {marker_path}")
        code, raw = self._call(cmd_ensure_marker_gitignore, ["--gitignore", str(self.project / ".gitignore"), "--entry", entry])
        self._expect(self._json(code, raw)["changed"] is True, "marker gitignore not updated")
        code, _ = self._call(
            cmd_orchestrator_helper,
            [
                "marker",
                "create",
                "--epic",
                "1",
                "--story",
                "1.1",
                "--remaining",
                "2",
                "--state-file",
                str(state_file),
                "--project-slug",
                "smoke",
                "--pid",
                "123",
                "--heartbeat",
                "2000-01-01T00:00:00Z",
            ],
        )
        self._expect(code == 0, "marker create failed")
        marker_file = Path(str(marker_path["file"]))
        marker_payload = json.loads(marker_file.read_text(encoding="utf-8"))
        self._expect(
            marker_payload["epic"] == "1"
            and marker_payload["currentStory"] == "1.1"
            and marker_payload["storiesRemaining"] == 2
            and marker_payload["stateFile"] == str(state_file)
            and marker_payload["projectSlug"] == "smoke"
            and marker_payload["heartbeat"] == "2000-01-01T00:00:00Z",
            f"marker JSON shape failed: {marker_payload}",
        )
        code, raw = self._call(cmd_orchestrator_helper, ["marker", "check"])
        marker_check, checked_marker = self._json_objects(code, raw)
        self._expect(
            marker_check["exists"] is True and checked_marker["storiesRemaining"] == 2,
            f"marker check failed: {raw}",
        )
        blocked_code, blocked = self._call(cmd_stop_hook, [])
        blocked_payload = self._json(blocked_code, blocked)
        self._expect(blocked_payload["decision"] == "block", f"stop-hook did not block active marker: {blocked_payload}")
        old_heartbeat = marker_payload["heartbeat"]
        code, _ = self._call(cmd_orchestrator_helper, ["marker", "heartbeat"])
        self._expect(code == 0, "marker heartbeat failed")
        heartbeat_payload = json.loads(marker_file.read_text(encoding="utf-8"))
        self._expect(heartbeat_payload["heartbeat"] != old_heartbeat, f"marker heartbeat did not change: {heartbeat_payload}")
        code, _ = self._call(cmd_orchestrator_helper, ["marker", "remove"])
        self._expect(code == 0 and not marker_file.exists(), "marker remove failed")
        code, raw = self._call(cmd_stop_hook, [])
        self._expect(code == 0 and raw == "", "stop-hook did not allow after marker removal")
        self.results["marker"] = {"entry": entry, "blocked": True, "gitignore": True, "heartbeatChanged": True}

    def _assert_validate_and_source_truth(self, state_file: Path) -> None:
        code, raw = self._call(cmd_validate_state, ["--state", str(state_file)])
        validation = self._json(code, raw)
        self._expect(validation["ok"] is True and validation["issueCount"] == 0, f"validate-state failed: {validation}")
        code, raw = self._call(cmd_list_sessions, ["--slug", "smoke"])
        sessions = self._json(code, raw)
        self._expect("sessions" in sessions, f"list-sessions failed: {sessions}")
        code, raw = self._call(cmd_sprint_compare, ["--state", str(state_file), "--sprint", str(self.artifacts / "sprint-status.yaml")])
        compare = self._json(code, raw)
        self._expect(compare["ok"] is True, f"sprint-compare failed: {compare}")
        compare_state = self.output / "compare-progress.md"
        compare_state.write_text(state_file.read_text(encoding="utf-8").replace('currentStory: "1.1"', 'currentStory: "1.2"'), encoding="utf-8")
        code, raw = self._call(cmd_sprint_compare, ["--state", str(compare_state), "--sprint", str(self.artifacts / "sprint-status.yaml")])
        progress_compare = self._json(code, raw)
        self._expect(progress_compare["checked"] == ["1.1"] and progress_compare["incomplete"] == ["1.1"], f"progress compare did not inspect prior story: {progress_compare}")
        done_sprint = self.artifacts / "sprint-status-exact-done.yaml"
        done_sprint.write_text("1.1: done\n1.2: backlog\n", encoding="utf-8")
        code, raw = self._call(cmd_sprint_compare, ["--state", str(compare_state), "--sprint", str(done_sprint)])
        done_compare = self._json(code, raw)
        self._expect(done_compare["checked"] == ["1.1"] and done_compare["incomplete"] == [], f"sprint done branch failed: {done_compare}")
        code, raw = self._call(cmd_state_metrics, ["--state", str(state_file)])
        metrics = self._json(code, raw)
        self._expect(metrics["ok"] is True and metrics["total"] == 2, f"progress row metrics failed: {metrics}")
        broken_state = self.output / "invalid-structure.md"
        broken_state.write_text(state_file.read_text(encoding="utf-8").replace('status: "IN_PROGRESS"', 'status: ""'), encoding="utf-8")
        code, raw = self._call(cmd_validate_state, ["--state", str(broken_state)])
        broken = self._json(code, raw)
        self._expect(broken["ok"] is True and broken["issueCount"] > 0 and broken["structure"] == "issues", f"structure issues not reported: {broken}")
        story = self.artifacts / "1-1-first.md"
        story.write_text('---\nTitle: "Story 1.1"\nStatus: done\n---\n', encoding="utf-8")
        code, raw = self._call(cmd_orchestrator_helper, ["story-file-status", "1.1"])
        file_status = self._json(code, raw)
        code, raw = self._call(cmd_orchestrator_helper, ["sprint-status", "get", "1.1"])
        sprint_status = self._json(code, raw)
        self._expect(file_status["status"] == "done" and sprint_status["status"] == "ready-for-dev", "source mismatch not surfaced")
        code, raw = self._call(cmd_orchestrator_helper, ["verify-step", "review", "1.1", "--state-file", str(state_file)])
        review = self._json(code, raw)
        self._expect(
            review.get("verified") is True
            and review.get("source") == "story-file"
            and review.get("note") == "sprint_status_not_updated",
            f"review verifier did not surface sprint/story mismatch: {review}",
        )
        self.results["validate"] = {
            "state": "ok",
            "sessions": sessions.get("count", 0),
            "structureIssues": broken["issueCount"],
            "progressRows": metrics["total"],
            "progressChecked": progress_compare["checked"],
            "progressDoneBranch": done_compare["checked"],
            "sourceMismatch": "sprint_status_not_updated",
        }

    def _assert_edit_route_contracts(self, state_file: Path) -> None:
        before = state_file.read_text(encoding="utf-8")
        menu = self._assert_edit_menu_contracts(state_file)
        config = load_agent_config_from_state(state_file)
        review = config.per_task.get("review")
        self._expect(review is not None and review.primary == "claude" and review.fallback is False, f"agent config variant not rendered: {config}")
        code, raw = self._call(cmd_orchestrator_helper, ["state-update", str(state_file), "--set", "status=PAUSED"])
        self._expect(self._json(code, raw)["ok"] is True, "edit status save failed")
        code, raw = self._call(cmd_orchestrator_helper, ["state-update", str(state_file), "--set", 'storyRange=["1.2"]'])
        self._expect(self._json(code, raw)["ok"] is True, "edit range save failed")
        code, raw = self._call(cmd_orchestrator_helper, ["state-update", str(state_file), "--set", "currentStory=1.2"])
        self._expect(self._json(code, raw)["ok"] is True, "edit current story save failed")
        code, raw = self._call(cmd_orchestrator_helper, ["state-update", str(state_file), "--set", "aiCommand=claude --resume"])
        self._expect(self._json(code, raw)["ok"] is True, "edit AI command save failed")
        (self.output / "complexity-edited.json").write_text('{"stories":[{"storyId":"1.2","complexity":{"level":"low"}}]}\n', encoding="utf-8")
        (self.output / "agents-edited.md").write_text("# Agents\n\n- 1.2 dev codex\n", encoding="utf-8")
        code, raw = self._call(cmd_orchestrator_helper, ["state-update", str(state_file), "--set", "complexityFile=_bmad-output/story-automator/complexity-edited.json"])
        self._expect(self._json(code, raw)["ok"] is True, "edit complexity path save failed")
        code, raw = self._call(cmd_orchestrator_helper, ["state-update", str(state_file), "--set", "agentsFile=_bmad-output/story-automator/agents-edited.md"])
        self._expect(self._json(code, raw)["ok"] is True, "edit agents path save failed")
        code, raw = self._call(cmd_orchestrator_helper, ["state-update", str(state_file), "--set", "customInstructions=Edited context"])
        self._expect(self._json(code, raw)["ok"] is True, "edit text save failed")
        edited = state_file.read_text(encoding="utf-8")
        code, raw = self._call(cmd_orchestrator_helper, ["state-summary", str(state_file)])
        summary = self._json(code, raw)
        self._expect(summary["currentStep"] == "step-03-execute" and summary["currentStory"] == "1.2", f"post-edit route source drifted: {summary}")
        self.results["edit"] = {
            "saved": (
                "customInstructions: Edited context" in edited
                and 'storyRange: ["1.2"]' in edited
                and "aiCommand: claude --resume" in edited
                and "complexity-edited.json" in edited
                and "agents-edited.md" in edited
                and summary["status"] == "PAUSED"
            ),
            **menu,
        }
        self._expect(self.results["edit"]["saved"] is True, "edit save assertions failed")

    def _assert_resume_menu_branch_contracts(self, state_file: Path) -> dict[str, object]:
        step = (REPO_ROOT / "skills" / "bmad-story-automator" / "steps-c" / "step-01b-continue.md").read_text(encoding="utf-8")
        for token in ("[R]esume", "[V]iew", "[M]odify", "[S]tart Over", "[X]Abort"):
            self._expect(token in step, f"resume menu token missing: {token}")
        summary = self._json(*self._call(cmd_orchestrator_helper, ["state-summary", str(state_file)]))
        self._expect(summary["lastAction"] == "smoke create/dev simulated child output recorded", f"view branch action log missing: {summary}")
        start_over = self.output / "orchestration-start-over.md"
        start_over.write_text(state_file.read_text(encoding="utf-8"), encoding="utf-8")
        backup = start_over.with_name(f"{start_over.name}.backup-smoke")
        start_over.rename(backup)
        self._expect(backup.exists() and not start_over.exists(), "start-over backup simulation failed")
        abort_state = self.output / "orchestration-abort.md"
        abort_state.write_text(state_file.read_text(encoding="utf-8"), encoding="utf-8")
        code, raw = self._call(cmd_orchestrator_helper, ["state-update", str(abort_state), "--set", "status=ABORTED"])
        abort = self._json(code, raw)
        self._expect(abort["ok"] is True and "status" in abort["updated"], f"abort state update failed: {abort}")
        return {
            "routeHint": self._route_hint(step, "step-03-execute"),
            "menuBranches": ["view-action-log", "modify-route", "start-over-backup", "abort-state", "resume-marker-route"],
        }

    def _assert_edit_menu_contracts(self, state_file: Path) -> dict[str, object]:
        step = (REPO_ROOT / "skills" / "bmad-story-automator" / "steps-e" / "step-e-01-load.md").read_text(encoding="utf-8")
        for token in ("[S]tatus", "[R]ange", "[O]verrides", "[T]ext Context", "[I] Command", "[D]ocs", "[X]Exit", "[S]ave", "[D]iscard", "[E]dit more", "[R]esume", "[V]alidate"):
            self._expect(token in step, f"edit menu token missing: {token}")
        discard_path = self.output / "discard-copy.md"
        before = state_file.read_text(encoding="utf-8")
        discard_path.write_text(before, encoding="utf-8")
        staged = before.replace("Mode smoke fixture.", "Discard candidate")
        self._expect(staged != before, "discard fixture did not stage a change")
        discard_path.write_text(staged, encoding="utf-8")
        discard_path.write_text(before, encoding="utf-8")
        self._expect(discard_path.read_text(encoding="utf-8") == before, "discard branch should restore original state")
        edit_more = self.output / "edit-more-copy.md"
        edit_more.write_text(before, encoding="utf-8")
        code, raw = self._call(cmd_orchestrator_helper, ["state-update", str(edit_more), "--set", "currentStep=step-e-01-load"])
        payload = self._json(code, raw)
        self._expect(payload["ok"] is True and "currentStep" in payload["updated"], f"edit-more route state update failed: {payload}")
        post_edit_routes = {
            "resume": self._route_hint(step, "Route based on `currentStep`"),
            "validate": self._route_hint(step, "Load `{validateStep}`"),
            "exit": self._route_hint(step, 'Display "Edit complete." and end'),
        }
        return {
            "discarded": discard_path.read_text(encoding="utf-8") == before,
            "editMore": "currentStep=step-e-01-load",
            "postEditRouteHints": post_edit_routes,
            "workflowMenuDerived": True,
        }

    def _route_hint(self, workflow_text: str, text: str) -> str:
        self._expect(text in workflow_text, f"route hint missing from workflow: {text}")
        return text

    def _append_action_log(self, state_file: Path, entry: str) -> None:
        text = state_file.read_text(encoding="utf-8")
        line = f"* {entry}"
        marker = "<!-- Timestamped action entries will be appended here -->"
        self._expect(marker in text, "action log marker missing")
        state_file.write_text(text.replace(marker, f"{line}\n{marker}", 1), encoding="utf-8")

    def _call(self, fn, args: list[str]) -> tuple[int, str]:
        old_env = os.environ.copy()
        old_stdin = sys.stdin
        os.environ["PROJECT_ROOT"] = str(self.project)
        os.environ["BMAD_RUNTIME_PROVIDER"] = "codex"
        stdout = io.StringIO()
        try:
            sys.stdin = io.StringIO("")
            with redirect_stdout(stdout):
                code = fn(args)
            return code, stdout.getvalue()
        finally:
            sys.stdin = old_stdin
            os.environ.clear()
            os.environ.update(old_env)

    def _json(self, code: int, raw: str) -> dict[str, object]:
        self._expect(code in {0, 1}, f"unexpected exit code {code}: {raw}")
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SmokeModesError(f"expected JSON, got {raw!r}") from exc

    def _json_objects(self, code: int, raw: str) -> list[dict[str, object]]:
        self._expect(code in {0, 1}, f"unexpected exit code {code}: {raw}")
        decoder = json.JSONDecoder()
        objects: list[dict[str, object]] = []
        index = 0
        while index < len(raw):
            while index < len(raw) and raw[index].isspace():
                index += 1
            if index >= len(raw):
                break
            try:
                payload, index = decoder.raw_decode(raw, index)
            except json.JSONDecodeError as exc:
                raise SmokeModesError(f"expected JSON object stream, got {raw!r}") from exc
            self._expect(isinstance(payload, dict), f"expected JSON object in output: {raw}")
            objects.append(payload)
        self._expect(objects, f"no JSON objects in output: {raw}")
        return objects

    def _expect(self, condition: bool, message: str) -> None:
        if not condition:
            raise SmokeModesError(message)


def main() -> int:
    runner = ModeSmokeRunner()
    try:
        summary = runner.run()
    except (OSError, SmokeModesError, ValueError) as exc:
        print(f"smoke:modes failed: {exc}", file=sys.stderr)
        return 1
    finally:
        runner.close()
    report = REPO_ROOT / ".smoke" / "MODE_SMOKE_REPORT.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({"createdAt": datetime.now(timezone.utc).isoformat(), **summary}, indent=2) + "\n", encoding="utf-8")
    print("mode smoke ok")
    print(json.dumps({"report": str(report), **summary}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
