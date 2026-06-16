# tests/test_wire_epic_agents.py
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from story_automator.commands import orchestrator_epic_agents as epic_agents
from story_automator.core.telemetry_emitter import TelemetryEmitter


def _patched_emitter_factory(tmp: Path):
    emitter = TelemetryEmitter(tmp / "events.jsonl")

    def factory(_project_root):
        return emitter

    return emitter, factory


def _read_lines(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class CheckBlockingWiringTests(unittest.TestCase):
    def test_escalation_triggered_emit_includes_epic_story_severity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            _, factory = _patched_emitter_factory(tmp)
            epic_file = tmp / "epic-7.md"
            epic_file.write_text(
                "### Story 7.3: Build X\n"
                "Dependencies: 7.1, 7.2\n"
                "### Story 7.1: Foundation\n"
                "Dependencies: none\n",
                encoding="utf-8",
            )
            with (
                mock.patch.object(
                    epic_agents, "emitter_for_project_root", side_effect=factory
                ),
                mock.patch.object(
                    epic_agents, "get_project_root", return_value=str(tmp)
                ),
                mock.patch.object(
                    epic_agents, "find_epic_file", return_value=str(epic_file)
                ),
            ):
                rc = epic_agents.check_blocking_action(["7.1"])
            self.assertEqual(rc, 0)
            events = _read_lines(tmp / "events.jsonl")
            triggered = [e for e in events if e["event_type"] == "escalation_triggered"]
            self.assertEqual(len(triggered), 1)
            ev = triggered[0]
            self.assertEqual(ev["epic"], "7")
            self.assertEqual(ev["story_key"], "7.1")
            self.assertEqual(ev["severity"], "warning")
            self.assertIn("blocked by", ev["message"])


class AgentsResolveRetryWiringTests(unittest.TestCase):
    def test_retry_attempt_emitted_on_attempt_two(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            _, factory = _patched_emitter_factory(tmp)
            agents_file = tmp / "agents.md"
            agents_file.write_text(
                "```json\n"
                + json.dumps(
                    {
                        "stories": [
                            {
                                "storyId": "4.2",
                                "complexity": "medium",
                                "tasks": {
                                    "dev": {
                                        "primary": "claude",
                                        "fallback": "false",
                                        "model": "sonnet",
                                    }
                                },
                            }
                        ]
                    }
                )
                + "\n```\n",
                encoding="utf-8",
            )
            with (
                mock.patch.object(
                    epic_agents, "emitter_for_project_root", side_effect=factory
                ),
                mock.patch.object(
                    epic_agents, "get_project_root", return_value=str(tmp)
                ),
            ):
                rc = epic_agents.agents_resolve_action(
                    [
                        "--agents-file",
                        str(agents_file),
                        "--story",
                        "4.2",
                        "--task",
                        "dev",
                        "--attempt",
                        "2",
                        "--prev-error-class",
                        "test_fail",
                    ]
                )
            self.assertEqual(rc, 0)
            events = _read_lines(tmp / "events.jsonl")
            retries = [e for e in events if e["event_type"] == "retry_attempt"]
            self.assertEqual(len(retries), 1)
            ev = retries[0]
            self.assertEqual(ev["epic"], "4")
            self.assertEqual(ev["story_key"], "4.2")
            self.assertEqual(ev["attempt_num"], 2)
            self.assertEqual(ev["agent"], "claude")
            self.assertEqual(ev["model"], "sonnet")
            self.assertEqual(ev["prev_error_class"], "test_fail")

    def test_no_retry_attempt_emitted_on_attempt_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            _, factory = _patched_emitter_factory(tmp)
            agents_file = tmp / "agents.md"
            agents_file.write_text(
                "```json\n"
                + json.dumps(
                    {
                        "stories": [
                            {
                                "storyId": "4.2",
                                "complexity": "medium",
                                "tasks": {
                                    "dev": {"primary": "claude", "fallback": "false"}
                                },
                            }
                        ]
                    }
                )
                + "\n```\n",
                encoding="utf-8",
            )
            with (
                mock.patch.object(
                    epic_agents, "emitter_for_project_root", side_effect=factory
                ),
                mock.patch.object(
                    epic_agents, "get_project_root", return_value=str(tmp)
                ),
            ):
                epic_agents.agents_resolve_action(
                    [
                        "--agents-file",
                        str(agents_file),
                        "--story",
                        "4.2",
                        "--task",
                        "dev",
                        "--attempt",
                        "1",
                    ]
                )
            events = _read_lines(tmp / "events.jsonl")
            self.assertEqual(
                [e for e in events if e["event_type"] == "retry_attempt"], []
            )


class RetroAgentWiringTests(unittest.TestCase):
    def test_retro_fired_emit_uses_frontmatter_agentConfig(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            _, factory = _patched_emitter_factory(tmp)
            state_file = tmp / "state.md"
            state_file.write_text(
                "---\n"
                "epic: 9\n"
                "agentConfig:\n"
                "  epic: 9\n"
                "  storiesCompleted: 3\n"
                "  totalCostUsd: 2.50\n"
                "  durationSeconds: 360.0\n"
                "---\n# state\n",
                encoding="utf-8",
            )
            with (
                mock.patch.object(
                    epic_agents, "emitter_for_project_root", side_effect=factory
                ),
                mock.patch.object(
                    epic_agents, "get_project_root", return_value=str(tmp)
                ),
            ):
                rc = epic_agents.retro_agent_action(["--state-file", str(state_file)])
            self.assertEqual(rc, 0)
            events = _read_lines(tmp / "events.jsonl")
            retros = [e for e in events if e["event_type"] == "retro_fired"]
            self.assertEqual(len(retros), 1)
            ev = retros[0]
            self.assertEqual(ev["epic"], "9")
            self.assertEqual(ev["stories_completed"], 3)
            self.assertEqual(ev["total_cost_usd"], 2.5)
            self.assertEqual(ev["duration_s"], 360.0)


if __name__ == "__main__":
    unittest.main()
