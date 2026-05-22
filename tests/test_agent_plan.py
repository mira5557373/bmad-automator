from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from story_automator.commands.orchestrator import cmd_orchestrator_helper
from story_automator.core.agent_plan import load_agents_plan, load_agents_plan_for_resolution, load_complexity_payload, validate_agents_plan_payload, validate_complexity_payload


class AgentPlanValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tmp.name)
        self.state_file = self.project_root / "state.md"
        self.state_file.write_text('---\nepic: "1"\nepicName: "Epic 1"\n---\n', encoding="utf-8")
        self.complexity_file = self.project_root / "complexity.json"
        self.agents_file = self.project_root / "agents.md"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_complexity_payload_reports_field_paths(self) -> None:
        issues = validate_complexity_payload({"stories": [{"storyId": "", "complexity": {"level": "huge"}}]})

        self.assertEqual([issue.field for issue in issues], ["stories[0].storyId", "stories[0].complexity.level"])
        self.assertTrue(all(issue.source == "agent-plan" for issue in issues))

    def test_complexity_loader_accepts_unknown_fields_and_default_level(self) -> None:
        self.complexity_file.write_text(json.dumps({"stories": [{"storyId": "1.1", "extra": True}]}), encoding="utf-8")

        payload, issues = load_complexity_payload(str(self.complexity_file))

        self.assertEqual(issues, [])
        self.assertEqual(payload["stories"][0]["storyId"], "1.1")

    def test_agents_plan_payload_requires_all_task_selections(self) -> None:
        issues = validate_agents_plan_payload({"stories": [{"storyId": "1.1", "tasks": {"create": {"primary": "claude"}}}]})

        fields = [issue.field for issue in issues]
        self.assertIn("stories[0].tasks.dev", fields)
        self.assertIn("stories[0].tasks.auto", fields)
        self.assertIn("stories[0].tasks.review", fields)

    def test_agents_plan_loader_extracts_markdown_json_block(self) -> None:
        self.agents_file.write_text("```json\n" + json.dumps(self._agents_payload()) + "\n```\n", encoding="utf-8")

        payload, issues = load_agents_plan(str(self.agents_file))

        self.assertEqual(issues, [])
        self.assertEqual(payload["stories"][0]["storyId"], "1.1")

    def test_agents_plan_resolution_loader_accepts_partial_requested_task(self) -> None:
        self.agents_file.write_text(json.dumps({"stories": [{"storyId": "1.1", "tasks": {"create": {"primary": "codex", "fallback": False}}}]}), encoding="utf-8")

        payload, issues = load_agents_plan_for_resolution(str(self.agents_file), "1.1", "create")

        self.assertEqual(issues, [])
        self.assertEqual(payload["stories"][0]["tasks"]["create"]["primary"], "codex")

    def test_agents_build_rejects_invalid_complexity_payload_with_structured_issues(self) -> None:
        self.complexity_file.write_text(json.dumps({"stories": [{"storyId": "1.1", "complexity": {"level": "giant"}}]}), encoding="utf-8")
        code, payload = self._helper(
            [
                "agents-build",
                "--state-file",
                str(self.state_file),
                "--complexity-file",
                str(self.complexity_file),
                "--output",
                str(self.agents_file),
                "--config-json",
                "{}",
            ]
        )

        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "invalid_complexity_json")
        self.assertEqual(payload["structuredIssues"][0]["field"], "stories[0].complexity.level")

    def test_agents_build_rejects_non_object_agent_config(self) -> None:
        self.complexity_file.write_text(json.dumps({"stories": [{"storyId": "1.1"}]}), encoding="utf-8")

        code, payload = self._helper(
            [
                "agents-build",
                "--state-file",
                str(self.state_file),
                "--complexity-file",
                str(self.complexity_file),
                "--output",
                str(self.agents_file),
                "--config-json",
                "[]",
            ]
        )

        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "invalid_agent_config")
        self.assertEqual(payload["structuredIssues"][0]["type"], "ValueError")

    def test_agents_build_rejects_non_object_complexity_overrides(self) -> None:
        self.complexity_file.write_text(json.dumps({"stories": [{"storyId": "1.1"}]}), encoding="utf-8")

        for config in ({"complexityOverrides": "bad"}, {"complexityOverrides": None}):
            with self.subTest(config=config):
                code, payload = self._helper(
                    [
                        "agents-build",
                        "--state-file",
                        str(self.state_file),
                        "--complexity-file",
                        str(self.complexity_file),
                        "--output",
                        str(self.agents_file),
                        "--config-json",
                        json.dumps(config),
                    ]
                )

                self.assertEqual(code, 1)
                self.assertEqual(payload["error"], "invalid_agent_config")
                self.assertIn("complexityOverrides", payload["structuredIssues"][0]["message"])

    def test_agents_build_rejects_invalid_nested_complexity_overrides(self) -> None:
        self.complexity_file.write_text(json.dumps({"stories": [{"storyId": "1.1"}]}), encoding="utf-8")

        for config in (
            {"complexityOverrides": {"medium": "bad"}},
            {"complexityOverrides": {"medium": {"retro": "bad"}}},
            {"complexityOverrides": {"medium": {"retro": {"primary": ["codex"]}}}},
            {"complexityOverrides": {"medium": {"retro": {"fallback": []}}}},
            {"complexityOverrides": {"medium": {"retro": {"fallback": True}}}},
        ):
            with self.subTest(config=config):
                code, payload = self._helper(
                    [
                        "agents-build",
                        "--state-file",
                        str(self.state_file),
                        "--complexity-file",
                        str(self.complexity_file),
                        "--output",
                        str(self.agents_file),
                        "--config-json",
                        json.dumps(config),
                    ]
                )

                self.assertEqual(code, 1)
                self.assertEqual(payload["error"], "invalid_agent_config")
                self.assertIn("complexityOverrides", payload["structuredIssues"][0]["message"])

    def test_agents_build_and_resolve_preserve_success_shapes(self) -> None:
        self.complexity_file.write_text(json.dumps({"stories": [{"storyId": "1.1", "title": "Story", "complexity": {"level": "HIGH"}}]}), encoding="utf-8")

        code, payload = self._helper(
            [
                "agents-build",
                "--state-file",
                str(self.state_file),
                "--complexity-file",
                str(self.complexity_file),
                "--output",
                str(self.agents_file),
                "--config-json",
                json.dumps({"defaultPrimary": "codex", "defaultFallback": False}),
            ]
        )
        self.assertEqual(code, 0)
        self.assertEqual(payload, {"ok": True, "path": str(self.agents_file), "stories": 1})

        code, payload = self._helper(["agents-resolve", "--agents-file", str(self.agents_file), "--story", "1.1", "--task", "dev"])
        self.assertEqual(code, 0)
        self.assertEqual(payload["primary"], "codex")
        self.assertEqual(payload["fallback"], "false")
        self.assertEqual(payload["complexity"], "high")

    def test_agents_build_treats_null_primary_as_unset(self) -> None:
        self.complexity_file.write_text(json.dumps({"stories": [{"storyId": "1.1", "title": "Story", "complexity": {"level": "medium"}}]}), encoding="utf-8")

        code, _ = self._helper(
            [
                "agents-build",
                "--state-file",
                str(self.state_file),
                "--complexity-file",
                str(self.complexity_file),
                "--output",
                str(self.agents_file),
                "--config-json",
                json.dumps({"defaultPrimary": "codex", "perTask": {"dev": {"primary": None}}}),
            ]
        )

        self.assertEqual(code, 0)
        code, payload = self._helper(["agents-resolve", "--agents-file", str(self.agents_file), "--story", "1.1", "--task", "dev"])
        self.assertEqual(code, 0)
        self.assertEqual(payload["primary"], "codex")

    def test_agents_resolve_allows_partial_direct_agents_file(self) -> None:
        self.agents_file.write_text(json.dumps({"stories": [{"storyId": "1.1", "tasks": {"create": {"primary": "codex", "fallback": False}}}]}), encoding="utf-8")

        code, payload = self._helper(["agents-resolve", "--agents-file", str(self.agents_file), "--story", "1.1", "--task", "create"])

        self.assertEqual(code, 0)
        self.assertEqual(payload["primary"], "codex")
        self.assertEqual(payload["fallback"], "false")

    def test_agents_resolve_rejects_malformed_requested_task_with_structured_issues(self) -> None:
        self.agents_file.write_text(json.dumps({"stories": [{"storyId": "1.1", "tasks": {"create": {"primary": ""}}}]}), encoding="utf-8")

        code, payload = self._helper(["agents-resolve", "--agents-file", str(self.agents_file), "--story", "1.1", "--task", "create"])

        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "invalid_agents_json")
        fields = [issue["field"] for issue in payload["structuredIssues"]]
        self.assertIn("stories[0].tasks.create.primary", fields)

    def test_agents_resolve_uses_validated_payload_without_rereading(self) -> None:
        self.agents_file.write_text(json.dumps({"stories": [{"storyId": "1.1", "tasks": {"dev": {"primary": "codex", "fallback": False}}}]}), encoding="utf-8")

        def mutate_if_reread(path: str | Path) -> str:
            self.agents_file.write_text(
                json.dumps({"stories": [{"storyId": "1.1", "tasks": {"dev": {"primary": "claude", "fallback": False}}}]}),
                encoding="utf-8",
            )
            return Path(path).read_text(encoding="utf-8")

        with patch("story_automator.core.agent_config.read_text", side_effect=mutate_if_reread):
            code, payload = self._helper(["agents-resolve", "--agents-file", str(self.agents_file), "--story", "1.1", "--task", "dev"])

        self.assertEqual(code, 0)
        self.assertEqual(payload["primary"], "codex")

    def _agents_payload(self) -> dict[str, object]:
        tasks = {task: {"primary": "claude", "fallback": False} for task in ("create", "dev", "auto", "review")}
        return {"stories": [{"storyId": "1.1", "complexity": "medium", "tasks": tasks}]}

    def _helper(self, args: list[str]) -> tuple[int, dict[str, object]]:
        stdout = io.StringIO()
        with patch.dict("os.environ", {"PROJECT_ROOT": str(self.project_root)}), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(args)
        return code, json.loads(stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
