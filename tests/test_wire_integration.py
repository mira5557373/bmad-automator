# tests/test_wire_integration.py
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from story_automator.commands import orchestrator
from story_automator.core import tmux_runtime
from story_automator.core.telemetry_emitter import TelemetryEmitter
from story_automator.core.telemetry_reader import TelemetryReader


class WiredEmitsFlowThroughReaderTests(unittest.TestCase):
    def test_review_cycle_and_tmux_emits_appear_in_reader(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            telem_path = tmp / "events.jsonl"
            emitter = TelemetryEmitter(telem_path)

            def factory(_project_root):
                return emitter

            with (
                mock.patch.object(
                    orchestrator, "emitter_for_project_root", side_effect=factory
                ),
                mock.patch.object(
                    orchestrator, "get_project_root", return_value=str(tmp)
                ),
                mock.patch.object(
                    orchestrator,
                    "verify_code_review_completion",
                    return_value={"verified": True, "cycle": 1, "issuesFound": 0},
                ),
                mock.patch.object(
                    tmux_runtime, "emitter_for_project_root", side_effect=factory
                ),
            ):
                orchestrator._verify_code_review(["2.5"])
                tmux_runtime._emit_tmux_completed(
                    "sa-acme-251215-104500-e2-s2-5-dev",
                    {"exitCode": 0, "durationSeconds": 4.0},
                    str(tmp),
                )

            reader = TelemetryReader(telem_path)
            types = [type(ev).__name__ for ev in reader.iter_events()]
            self.assertIn("ReviewCycle", types)
            self.assertIn("TmuxSessionCompleted", types)

    def test_attempts_by_story_aggregation_sees_wired_retry(self) -> None:
        from story_automator.commands import orchestrator_epic_agents as epic_agents
        import json

        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            telem_path = tmp / "events.jsonl"
            emitter = TelemetryEmitter(telem_path)

            def factory(_project_root):
                return emitter

            agents_file = tmp / "agents.md"
            agents_file.write_text(
                "```json\n"
                + json.dumps(
                    {
                        "stories": [
                            {
                                "storyId": "1.1",
                                "complexity": "low",
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
                for attempt in (2, 3):
                    epic_agents.agents_resolve_action(
                        [
                            "--agents-file",
                            str(agents_file),
                            "--story",
                            "1.1",
                            "--task",
                            "dev",
                            "--attempt",
                            str(attempt),
                        ]
                    )

            reader = TelemetryReader(telem_path)
            self.assertEqual(reader.attempts_by_story(), {("1", "1.1"): 2})


if __name__ == "__main__":
    unittest.main()
