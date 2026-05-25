from __future__ import annotations

import io
import json
import tempfile
import textwrap
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from story_automator.commands.orchestrator_epic_agents import (
    check_blocking_action,
    check_epic_complete_action,
    get_epic_stories_action,
)


class OrchestratorEpicAgentsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tmp.name)
        (self.project_root / "_bmad-output" / "implementation-artifacts").mkdir(parents=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run_action(self, action, args: list[str]) -> tuple[int, dict]:
        stdout = io.StringIO()
        with patch.dict("os.environ", {"PROJECT_ROOT": str(self.project_root)}), redirect_stdout(stdout):
            exit_code = action(args)
        return exit_code, json.loads(stdout.getvalue())

    def test_check_epic_complete_accepts_non_numeric_epic(self) -> None:
        self._write_sprint_status(
            """
            development_status:
              multi-leg-3-lossless-quantity-serialization: done
              multi-leg-4-strict-asset-precision-registration: done
              multi-leg-ui-99-unrelated: done
            """
        )
        exit_code, payload = self._run_action(check_epic_complete_action, ["multi-leg", "multi-leg.4"])
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["epic"], "multi-leg")
        self.assertTrue(payload["isLastStory"])
        self.assertEqual(payload["lastInEpic"], "multi-leg-4-strict-asset-precision-registration")

    def test_check_epic_complete_uses_epic_hint_for_numeric_title_segments(self) -> None:
        state_file = self._write_state(
            """
            storyRange:
              - multi-leg-3-2026-release
              - multi-leg-4-next
            """
        )
        exit_code, payload = self._run_action(
            check_epic_complete_action,
            ["multi-leg", "multi-leg-4-next", "--state-file", str(state_file)],
        )
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["isLastStory"])
        self.assertEqual(payload["lastInEpic"], "multi-leg-4-next")
        self.assertEqual(payload["epicStoryCount"], 2)

    def test_check_epic_complete_accepts_no_hyphen_epic_numeric_title_segments(self) -> None:
        state_file = self._write_state(
            """
            storyRange:
              - alpha-1-2026-release
              - alpha-2-next
            """
        )
        exit_code, payload = self._run_action(
            check_epic_complete_action,
            ["alpha", "alpha-2-next", "--state-file", str(state_file)],
        )
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["isLastStory"])
        self.assertEqual(payload["lastInEpic"], "alpha-2-next")
        self.assertEqual(payload["epicStoryCount"], 2)

    def test_check_epic_complete_deduplicates_state_file_aliases(self) -> None:
        state_file = self._write_state(
            """
            storyRange:
              - multi-leg.3
              - multi-leg-3-lossless-quantity-serialization
              - multi-leg-4-next
            """
        )
        exit_code, payload = self._run_action(
            check_epic_complete_action,
            ["multi-leg", "multi-leg-4-next", "--state-file", str(state_file)],
        )
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["isLastStory"])
        self.assertEqual(payload["epicStoryCount"], 2)

    def test_check_blocking_accepts_non_numeric_story_headers(self) -> None:
        self._write_epic_file(
            """
            ### Story multi-leg.4: Later
            Dependencies: multi-leg.3
            """
        )
        exit_code, payload = self._run_action(check_blocking_action, ["multi-leg.3"])
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["blocking"])
        self.assertEqual(payload["dependents"], ["multi-leg.4"])

    def test_check_blocking_does_not_match_story_prefix_substrings(self) -> None:
        self._write_epic_file(
            """
            ### Story multi-leg.4: Later
            Dependencies: multi-leg.30
            """
        )
        exit_code, payload = self._run_action(check_blocking_action, ["multi-leg.3"])
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["blocking"])
        self.assertEqual(payload["dependents"], [])

    def test_get_epic_stories_state_file_accepts_non_numeric_full_keys(self) -> None:
        state_file = self._write_state(
            """
            storyRange:
              - multi-leg-3-lossless-quantity-serialization
              - multi-leg-4-strict-asset-precision-registration
            """
        )
        exit_code, payload = self._run_action(get_epic_stories_action, ["multi-leg", "--state-file", str(state_file)])
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["epic"], "multi-leg")
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["source"], "state_file")

    def test_get_epic_stories_state_file_accepts_numeric_title_segments(self) -> None:
        state_file = self._write_state(
            """
            storyRange:
              - multi-leg-3-2026-release
              - multi-leg-ui-99-unrelated
            """
        )
        exit_code, payload = self._run_action(get_epic_stories_action, ["multi-leg", "--state-file", str(state_file)])
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["stories"], ["multi-leg-3-2026-release"])
        self.assertEqual(payload["count"], 1)

    def test_get_epic_stories_state_file_accepts_bare_dashed_keys(self) -> None:
        state_file = self._write_state(
            """
            storyRange:
              - multi-leg-3
              - multi-leg-4-next
            """
        )
        exit_code, payload = self._run_action(get_epic_stories_action, ["multi-leg", "--state-file", str(state_file)])
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["stories"], ["multi-leg-3", "multi-leg-4-next"])
        self.assertEqual(payload["count"], 2)

    def _write_sprint_status(self, content: str) -> None:
        path = self.project_root / "_bmad-output" / "implementation-artifacts" / "sprint-status.yaml"
        path.write_text(textwrap.dedent(content), encoding="utf-8")

    def _write_state(self, content: str) -> Path:
        path = self.project_root / "state.md"
        path.write_text(f"---\n{textwrap.dedent(content)}---\n", encoding="utf-8")
        return path

    def _write_epic_file(self, content: str) -> None:
        path = self.project_root / "_bmad-output" / "implementation-artifacts" / "epic-multi-leg-test.md"
        path.write_text(textwrap.dedent(content), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
