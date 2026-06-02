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

    def test_check_epic_complete_does_not_satisfy_missing_full_key_with_sibling(self) -> None:
        self._write_sprint_status("multi-leg-3-old: done\n")
        exit_code, payload = self._run_action(check_epic_complete_action, ["multi-leg", "multi-leg-3-new"])
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["isLastStory"])
        self.assertEqual(payload["lastInEpic"], "multi-leg-3-old")

    def test_check_epic_complete_rejects_story_prefix_as_epic_hint(self) -> None:
        self._write_sprint_status(
            """
            development_status:
              multi-leg-3-42-release: ready-for-dev
              multi-leg-4-next: done
            """
        )
        exit_code, payload = self._run_action(check_epic_complete_action, ["multi-leg-3", "multi-leg-3-42-release"])
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["isLastStory"])
        self.assertEqual(payload["reason"], "story_not_in_epic")

    def test_check_epic_complete_returns_json_error_for_invalid_artifacts_config(self) -> None:
        self._write_bmad_config("implementation_artifacts: ../outside/implementation-artifacts\n")

        exit_code, payload = self._run_action(check_epic_complete_action, ["1", "1.1"])

        self.assertEqual(exit_code, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["epic"], "1")
        self.assertEqual(payload["storyId"], "1.1")
        self.assertIn("BMAD config implementation_artifacts", payload["error"])

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

    def test_check_blocking_does_not_match_sibling_full_key_dependency(self) -> None:
        self._write_epic_file(
            """
            ### Story multi-leg.4: Later
            Dependencies: multi-leg-3-old
            """
        )
        exit_code, payload = self._run_action(check_blocking_action, ["multi-leg-3-new"])
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["blocking"])
        self.assertEqual(payload["dependents"], [])

    def test_check_blocking_does_not_treat_longer_dotted_epic_reference_as_current_epic(self) -> None:
        path = self.project_root / "_bmad-output" / "implementation-artifacts" / "epic-release.md"
        path.write_text(
            textwrap.dedent(
                """
                ### Story release.4: Later
                Dependencies: release-3-phase-2.1
                """
            ),
            encoding="utf-8",
        )
        exit_code, payload = self._run_action(check_blocking_action, ["release.3"])
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

    def test_get_epic_stories_state_file_ignores_malformed_dotted_entries(self) -> None:
        state_file = self._write_state(
            """
            storyRange:
              - multi-leg.foo
            """
        )
        exit_code, payload = self._run_action(get_epic_stories_action, ["multi-leg", "--state-file", str(state_file)])
        self.assertEqual(exit_code, 0)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["count"], 0)

    def test_get_epic_stories_accepts_exact_epic_file(self) -> None:
        path = self.project_root / "_bmad-output" / "implementation-artifacts" / "epic-multi-leg.md"
        path.write_text(
            textwrap.dedent(
                """
                ### Story multi-leg.3: Quantity
                ### Story multi-leg.4: Next
                """
            ),
            encoding="utf-8",
        )
        exit_code, payload = self._run_action(get_epic_stories_action, ["multi-leg"])
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["stories"], ["multi-leg.3", "multi-leg.4"])
        self.assertEqual(payload["source"], "epic_file")

    def test_get_epic_stories_epic_file_ignores_dependency_references(self) -> None:
        self._write_epic_file(
            """
            ### Story multi-leg.3: Quantity
            Dependencies: multi-leg.99
            """
        )
        exit_code, payload = self._run_action(get_epic_stories_action, ["multi-leg"])
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["stories"], ["multi-leg.3"])
        self.assertEqual(payload["count"], 1)

    def test_get_epic_stories_epic_file_accepts_full_key_headers(self) -> None:
        path = self.project_root / "_bmad-output" / "implementation-artifacts" / "epic-multi-leg.md"
        path.write_text(
            textwrap.dedent(
                """
                ### Story multi-leg-3-old: Old
                ### Story multi-leg-4-next: Next
                """
            ),
            encoding="utf-8",
        )
        exit_code, payload = self._run_action(get_epic_stories_action, ["multi-leg"])
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["stories"], ["multi-leg-3-old", "multi-leg-4-next"])
        self.assertEqual(payload["count"], 2)

    def test_get_epic_stories_epic_file_ignores_other_epic_full_key_headers(self) -> None:
        path = self.project_root / "_bmad-output" / "implementation-artifacts" / "epic-multi-leg.md"
        path.write_text(
            textwrap.dedent(
                """
                ### Story multi-leg.3: Good
                ### Story 1-2-unrelated: Other
                """
            ),
            encoding="utf-8",
        )
        exit_code, payload = self._run_action(get_epic_stories_action, ["multi-leg"])
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["stories"], ["multi-leg.3"])
        self.assertEqual(payload["count"], 1)

    def test_check_blocking_uses_single_story_compound_epic_key(self) -> None:
        path = self.project_root / "_bmad-output" / "implementation-artifacts" / "epic-phase-2-test.md"
        path.write_text(
            textwrap.dedent(
                """
                ### Story phase-2.2: Later
                Dependencies: phase-2-1-title
                """
            ),
            encoding="utf-8",
        )
        self._write_sprint_status(
            """
            development_status:
              phase-2-1-title: done
            """
        )
        exit_code, payload = self._run_action(check_blocking_action, ["phase-2-1-title"])
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["blocking"])
        self.assertEqual(payload["epic"], "phase-2")
        self.assertEqual(payload["dependents"], ["phase-2.2"])

    def test_check_blocking_accepts_exact_epic_file(self) -> None:
        path = self.project_root / "_bmad-output" / "implementation-artifacts" / "epic-multi-leg.md"
        path.write_text(
            textwrap.dedent(
                """
                ### Story multi-leg.4: Later
                Dependencies: multi-leg.3
                """
            ),
            encoding="utf-8",
        )
        exit_code, payload = self._run_action(check_blocking_action, ["multi-leg.3"])
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["blocking"])
        self.assertEqual(payload["dependents"], ["multi-leg.4"])
        self.assertEqual(payload["source"], "epic_file")

    def test_check_blocking_accepts_full_key_header_in_exact_epic_file(self) -> None:
        path = self.project_root / "_bmad-output" / "implementation-artifacts" / "epic-multi-leg.md"
        path.write_text(
            textwrap.dedent(
                """
                ### Story multi-leg-4-next: Later
                Dependencies: multi-leg.3
                """
            ),
            encoding="utf-8",
        )
        exit_code, payload = self._run_action(check_blocking_action, ["multi-leg.3"])
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["blocking"])
        self.assertEqual(payload["dependents"], ["multi-leg-4-next"])
        self.assertEqual(payload["source"], "epic_file")

    def test_check_blocking_accepts_full_key_header_in_suffixed_epic_file(self) -> None:
        self._write_epic_file(
            """
            ### Story multi-leg-4-next: Later
            Dependencies: multi-leg.3
            """
        )
        exit_code, payload = self._run_action(check_blocking_action, ["multi-leg.3"])
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["blocking"])
        self.assertEqual(payload["dependents"], ["multi-leg-4-next"])
        self.assertEqual(payload["source"], "epic_file")

    def test_check_blocking_ignores_longer_epic_file_matched_by_prefix_glob(self) -> None:
        path = self.project_root / "_bmad-output" / "implementation-artifacts" / "epic-multi-leg-ui.md"
        path.write_text(
            textwrap.dedent(
                """
                ### Story multi-leg-ui.1: UI
                Dependencies: multi-leg.3
                """
            ),
            encoding="utf-8",
        )
        exit_code, payload = self._run_action(check_blocking_action, ["multi-leg.3"])
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["blocking"])
        self.assertEqual(payload["dependents"], [])
        self.assertEqual(payload["reason"], "epic_file_not_found")

    def test_check_blocking_ignores_exact_epic_file_without_matching_story_headers(self) -> None:
        path = self.project_root / "_bmad-output" / "implementation-artifacts" / "epic-multi-leg.md"
        path.write_text(
            textwrap.dedent(
                """
                ### Story multi-leg-ui.1: UI
                Dependencies: multi-leg.3
                """
            ),
            encoding="utf-8",
        )
        exit_code, payload = self._run_action(check_blocking_action, ["multi-leg.3"])
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["blocking"])
        self.assertEqual(payload["dependents"], [])
        self.assertEqual(payload["reason"], "epic_file_not_found")

    def test_check_blocking_sorts_dependents_by_story_number(self) -> None:
        self._write_epic_file(
            """
            ### Story multi-leg.10: Later
            Dependencies: multi-leg.3
            ### Story multi-leg.2: Earlier
            Dependencies: multi-leg.3
            """
        )
        exit_code, payload = self._run_action(check_blocking_action, ["multi-leg.3"])
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["blocking"])
        self.assertEqual(payload["dependents"], ["multi-leg.2", "multi-leg.10"])

    def _write_sprint_status(self, content: str) -> None:
        path = self.project_root / "_bmad-output" / "implementation-artifacts" / "sprint-status.yaml"
        path.write_text(textwrap.dedent(content), encoding="utf-8")

    def _write_bmad_config(self, content: str) -> None:
        path = self.project_root / "_bmad" / "bmm" / "config.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
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
