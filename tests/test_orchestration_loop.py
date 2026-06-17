# tests/test_orchestration_loop.py
"""Tier-1 end-to-end orchestration-loop integration test.

Drives the real CLI command spine for a 2-story run with the tmux / agent / git
boundary mocked: marker create -> (per story) monitor-session ->
verify-code-review -> commit-ready -> state-update -> marker remove. Asserts the
assembled product behaves correctly end to end -- the telemetry stream is
run_id-correlated, the marker lifecycle and heartbeat refresh work, and the
state document transitions atomically. No tmux, no Claude, no cost; CI-able.
"""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from story_automator.commands import orchestrator
from story_automator.commands import tmux as tmux_cmd
from story_automator.core.run_identity import current_run_id
from story_automator.core.runtime_layout import active_marker_path
from story_automator.core.telemetry_emitter import TelemetryEmitter
from story_automator.core.telemetry_reader import TelemetryReader


def _silent(fn, *args):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args)


class OrchestrationLoopIntegrationTests(unittest.TestCase):
    def test_two_story_run_spine_is_correlated_and_consistent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            emitter = TelemetryEmitter(tmp / "telemetry" / "events.jsonl")

            def factory(_root):
                return emitter

            state_file = tmp / "orchestration-8.md"
            state_file.write_text(
                "---\n"
                "epic: \"8\"\n"
                "status: in_progress\n"
                "currentStory: \"8.1\"\n"
                "storyRange: [\"8.1\", \"8.2\"]\n"
                "---\n# Orchestration State\n",
                encoding="utf-8",
            )

            completed_status = {
                "session_state": "completed",
                "todos_done": 1,
                "todos_total": 1,
                "active_task": "out",
                "wait_estimate": 0,
            }
            fake_done = mock.MagicMock(done=True, status="done")

            with (
                # tmux/agent boundary
                mock.patch.object(tmux_cmd, "session_status", return_value=completed_status),
                mock.patch.object(
                    tmux_cmd, "_verify_monitor_completion",
                    return_value=({"verified": True}, "session_exit"),
                ),
                mock.patch.object(tmux_cmd, "get_project_root", return_value=str(tmp)),
                # git boundary (commit-ready) + verifier
                mock.patch.object(orchestrator, "sprint_status_get", return_value=fake_done),
                mock.patch.object(orchestrator, "run_cmd", return_value=("M f.py\n", 0)),
                mock.patch.object(
                    orchestrator, "verify_code_review_completion",
                    return_value={"verified": True, "cycle": 1, "issuesFound": 0},
                ),
                # shared telemetry sink + project root (cmd_monitor_session
                # itself emits no telemetry; the orchestrator commands do)
                mock.patch.object(orchestrator, "emitter_for_project_root", side_effect=factory),
                mock.patch.object(orchestrator, "get_project_root", return_value=str(tmp)),
            ):
                # --- run start: create the active marker (emits StoryStarted) ---
                rc = _silent(
                    orchestrator._marker,
                    ["create", "--epic", "8", "--story", "8.1",
                     "--remaining", "2", "--pid", "4242",
                     "--state-file", str(state_file)],
                )
                self.assertEqual(rc, 0)
                expected_run_id = current_run_id(str(tmp))
                self.assertTrue(expected_run_id.startswith("run-"))

                # --- per-story loop for 8.1 and 8.2 ---
                for story in ("8.1", "8.2"):
                    # monitor the child session to completion (real poll loop;
                    # session_status is mocked completed). This also refreshes
                    # the marker heartbeat each tick.
                    rc = _silent(
                        tmux_cmd.cmd_monitor_session,
                        [f"sess-{story}", "--json", "--agent", "claude",
                         "--workflow", "review", "--story-key", story,
                         "--max-polls", "2", "--initial-wait", "0",
                         "--project-root", str(tmp)],
                    )
                    self.assertEqual(rc, 0)
                    # review verification (emits ReviewCycle)
                    self.assertEqual(_silent(orchestrator._verify_code_review, [story]), 0)
                    # commit-ready (emits StoryCompleted)
                    self.assertEqual(_silent(orchestrator._commit_ready, [story]), 0)
                    # persist the state transition atomically
                    self.assertEqual(
                        _silent(orchestrator._state_update,
                                [str(state_file), "--set", f"currentStory={story}"]),
                        0,
                    )
                    # heartbeat refresh keeps the marker live
                    self.assertEqual(_silent(orchestrator._marker, ["heartbeat"]), 0)

                # --- run end: remove the marker ---
                self.assertEqual(_silent(orchestrator._marker, ["remove"]), 0)

            # marker is gone after the run
            self.assertFalse(active_marker_path(str(tmp)).exists())

            # state doc was updated atomically and is intact
            state_text = state_file.read_text(encoding="utf-8")
            self.assertIn("currentStory: 8.2", state_text)

            # the telemetry stream is complete and run_id-correlated
            events = list(TelemetryReader(tmp / "telemetry" / "events.jsonl").iter_events())
            types = [type(e).__name__ for e in events]
            self.assertEqual(types.count("StoryStarted"), 1)
            self.assertEqual(types.count("ReviewCycle"), 2)
            self.assertEqual(types.count("StoryCompleted"), 2)
            run_ids = {e.run_id for e in events if e.run_id}
            self.assertEqual(
                run_ids, {expected_run_id},
                "every emitted event must share the one marker-derived run_id",
            )


if __name__ == "__main__":
    unittest.main()
