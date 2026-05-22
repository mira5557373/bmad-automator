from __future__ import annotations

import io
import json
import tempfile
import textwrap
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from story_automator.commands.orchestrator_epic_agents import check_epic_complete_action, get_epic_stories_action
from story_automator.core.sprint import sprint_status_epic, sprint_status_get
from story_automator.core.story_keys import normalize_story_key


class NormalizeStoryKeyTests(unittest.TestCase):
    """Coverage for normalize_story_key, focused on non-numeric epic keys
    (e.g. ``multi-leg.3``) that previously returned ``None`` and broke every
    downstream helper (verify-step, story-file-status, sprint-status, commit-ready).
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tmp.name)
        (self.project_root / "_bmad-output" / "implementation-artifacts").mkdir(parents=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    # --- Numeric epics (regression coverage for the pre-existing path) ---

    def test_numeric_dotted_id(self) -> None:
        result = normalize_story_key(str(self.project_root), "1.2")
        assert result is not None
        self.assertEqual(result.id, "1.2")
        self.assertEqual(result.prefix, "1-2")

    def test_numeric_dashed_prefix(self) -> None:
        result = normalize_story_key(str(self.project_root), "1-2")
        assert result is not None
        self.assertEqual(result.id, "1.2")
        self.assertEqual(result.prefix, "1-2")

    def test_numeric_full_key(self) -> None:
        result = normalize_story_key(str(self.project_root), "1-2-user-authentication")
        assert result is not None
        self.assertEqual(result.id, "1.2")
        self.assertEqual(result.prefix, "1-2")
        self.assertEqual(result.key, "1-2-user-authentication")

    # --- Non-numeric epic keys (the regression this patch restores) ---

    def test_non_numeric_dotted_id(self) -> None:
        result = normalize_story_key(str(self.project_root), "multi-leg.3")
        assert result is not None, "multi-leg.3 must normalize (was None pre-patch)"
        self.assertEqual(result.id, "multi-leg.3")
        self.assertEqual(result.prefix, "multi-leg-3")

    def test_non_numeric_dashed_prefix(self) -> None:
        result = normalize_story_key(str(self.project_root), "multi-leg-3")
        assert result is not None, "multi-leg-3 must normalize (was None pre-patch)"
        self.assertEqual(result.id, "multi-leg.3")
        self.assertEqual(result.prefix, "multi-leg-3")

    def test_non_numeric_full_key(self) -> None:
        result = normalize_story_key(
            str(self.project_root),
            "multi-leg-3-lossless-quantity-serialization",
        )
        assert result is not None, "multi-leg-3-... must normalize (was None pre-patch)"
        self.assertEqual(result.id, "multi-leg.3")
        self.assertEqual(result.prefix, "multi-leg-3")
        self.assertEqual(result.key, "multi-leg-3-lossless-quantity-serialization")

    def test_compound_epic_name(self) -> None:
        # The rpartition logic must split on the last '-' to keep the compound epic name intact.
        result = normalize_story_key(str(self.project_root), "aerofoil-original-5")
        assert result is not None
        self.assertEqual(result.id, "aerofoil-original.5")
        self.assertEqual(result.prefix, "aerofoil-original-5")

    def test_compound_epic_name_with_numeric_segment_full_key(self) -> None:
        result = normalize_story_key(str(self.project_root), "release-2026-1-ship")
        assert result is not None
        self.assertEqual(result.id, "release-2026.1")
        self.assertEqual(result.prefix, "release-2026-1")
        self.assertEqual(result.key, "release-2026-1-ship")

    def test_numeric_leading_title_full_key_uses_first_story_boundary(self) -> None:
        result = normalize_story_key(str(self.project_root), "multi-leg-3-2026-release")
        assert result is not None
        self.assertEqual(result.id, "multi-leg.3")
        self.assertEqual(result.prefix, "multi-leg-3")
        self.assertEqual(result.key, "multi-leg-3-2026-release")

    def test_compound_epic_name_with_numeric_segment_uses_story_sized_suffix(self) -> None:
        result = normalize_story_key(str(self.project_root), "phase-2-1-title")
        assert result is not None
        self.assertEqual(result.id, "phase-2.1")
        self.assertEqual(result.prefix, "phase-2-1")
        self.assertEqual(result.key, "phase-2-1-title")

    # --- Key resolution via filesystem and sprint-status ---

    def test_resolves_key_from_artifact_glob_non_numeric(self) -> None:
        artifacts = self.project_root / "_bmad-output" / "implementation-artifacts"
        (artifacts / "multi-leg-3-lossless-quantity-serialization.md").write_text("", encoding="utf-8")
        result = normalize_story_key(str(self.project_root), "multi-leg.3")
        assert result is not None
        self.assertEqual(result.key, "multi-leg-3-lossless-quantity-serialization")

    def test_resolves_key_from_sprint_status_non_numeric(self) -> None:
        sprint_status = self.project_root / "_bmad-output" / "implementation-artifacts" / "sprint-status.yaml"
        sprint_status.write_text(
            textwrap.dedent(
                """\
                development_status:
                  multi-leg-3-lossless-quantity-serialization: done
                  multi-leg-4-strict-asset-precision-registration: ready-for-dev
                """
            ),
            encoding="utf-8",
        )
        result = normalize_story_key(str(self.project_root), "multi-leg.4")
        assert result is not None
        self.assertEqual(result.key, "multi-leg-4-strict-asset-precision-registration")

    def test_sprint_status_get_resolves_non_numeric_dotted_id(self) -> None:
        sprint_status = self.project_root / "_bmad-output" / "implementation-artifacts" / "sprint-status.yaml"
        sprint_status.write_text(
            textwrap.dedent(
                """\
                development_status:
                  multi-leg-4-strict-asset-precision-registration: done
                """
            ),
            encoding="utf-8",
        )
        result = sprint_status_get(str(self.project_root), "multi-leg.4")
        self.assertTrue(result.found)
        self.assertEqual(result.story, "multi-leg-4-strict-asset-precision-registration")
        self.assertEqual(result.status, "done")
        self.assertTrue(result.done)

    def test_check_epic_complete_accepts_non_numeric_epic(self) -> None:
        sprint_status = self.project_root / "_bmad-output" / "implementation-artifacts" / "sprint-status.yaml"
        sprint_status.write_text(
            textwrap.dedent(
                """\
                development_status:
                  multi-leg-3-lossless-quantity-serialization: done
                  multi-leg-4-strict-asset-precision-registration: done
                  multi-leg-ui-99-unrelated: done
                """
            ),
            encoding="utf-8",
        )
        stdout = io.StringIO()
        with patch.dict("os.environ", {"PROJECT_ROOT": str(self.project_root)}), redirect_stdout(stdout):
            exit_code = check_epic_complete_action(["multi-leg", "multi-leg.4"])
        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["epic"], "multi-leg")
        self.assertTrue(payload["isLastStory"])
        self.assertEqual(payload["lastInEpic"], "multi-leg-4-strict-asset-precision-registration")

    def test_sprint_status_epic_rejects_overlapping_non_numeric_epic_prefix(self) -> None:
        sprint_status = self.project_root / "_bmad-output" / "implementation-artifacts" / "sprint-status.yaml"
        sprint_status.write_text(
            textwrap.dedent(
                """\
                development_status:
                  multi-leg-4-strict-asset-precision-registration: done
                  multi-leg-ui-99-unrelated: done
                """
            ),
            encoding="utf-8",
        )
        stories, done = sprint_status_epic(str(self.project_root), "multi-leg")
        self.assertEqual(stories, ["multi-leg-4-strict-asset-precision-registration"])
        self.assertEqual(done, 1)

    def test_sprint_status_epic_accepts_numeric_segment_in_epic(self) -> None:
        sprint_status = self.project_root / "_bmad-output" / "implementation-artifacts" / "sprint-status.yaml"
        sprint_status.write_text(
            textwrap.dedent(
                """\
                development_status:
                  phase-2-1-title: done
                  phase-20-1-unrelated: done
                """
            ),
            encoding="utf-8",
        )
        stories, done = sprint_status_epic(str(self.project_root), "phase-2")
        self.assertEqual(stories, ["phase-2-1-title"])
        self.assertEqual(done, 1)

    def test_get_epic_stories_state_file_accepts_non_numeric_full_keys(self) -> None:
        state_file = self.project_root / "state.md"
        state_file.write_text(
            textwrap.dedent(
                """\
                ---
                storyRange:
                  - multi-leg-3-lossless-quantity-serialization
                  - multi-leg-4-strict-asset-precision-registration
                ---
                """
            ),
            encoding="utf-8",
        )
        stdout = io.StringIO()
        with patch.dict("os.environ", {"PROJECT_ROOT": str(self.project_root)}), redirect_stdout(stdout):
            exit_code = get_epic_stories_action(["multi-leg", "--state-file", str(state_file)])
        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["epic"], "multi-leg")
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["source"], "state_file")

    # --- Rejection paths ---

    def test_unrecognized_format_returns_none(self) -> None:
        self.assertIsNone(normalize_story_key(str(self.project_root), "garbage"))
        self.assertIsNone(normalize_story_key(str(self.project_root), ""))
        self.assertIsNone(normalize_story_key(str(self.project_root), "1"))
        # Leading digit is not a valid non-numeric epic prefix.
        self.assertIsNone(normalize_story_key(str(self.project_root), "9multi.1"))


if __name__ == "__main__":
    unittest.main()
