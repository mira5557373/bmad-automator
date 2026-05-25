from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from story_automator.core.sprint import sprint_status_epic, sprint_status_get
from story_automator.core.story_keys import normalize_story_key, normalize_story_key_for_epic


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
        self._write_sprint_status("release-2026-1-ship: done\nrelease-2026-2-next: ready-for-dev\n")
        result = normalize_story_key(str(self.project_root), "release-2026-1-ship")
        assert result is not None
        self.assertEqual(result.id, "release-2026.1")
        self.assertEqual(result.prefix, "release-2026-1")
        self.assertEqual(result.key, "release-2026-1-ship")

    def test_compound_epic_name_with_story_number_above_99(self) -> None:
        self._write_sprint_status("release-2026-123-ship: done\nrelease-2026-124-next: ready-for-dev\n")
        result = normalize_story_key(str(self.project_root), "release-2026-123-ship")
        assert result is not None
        self.assertEqual(result.id, "release-2026.123")
        self.assertEqual(result.prefix, "release-2026-123")
        self.assertEqual(result.key, "release-2026-123-ship")

    def test_numeric_leading_title_full_key_treats_year_as_title_segment(self) -> None:
        result = normalize_story_key(str(self.project_root), "multi-leg-3-2026-release")
        assert result is not None
        self.assertEqual(result.id, "multi-leg.3")
        self.assertEqual(result.prefix, "multi-leg-3")
        self.assertEqual(result.key, "multi-leg-3-2026-release")

    def test_numeric_leading_title_full_key_treats_short_number_as_title_segment(self) -> None:
        result = normalize_story_key(str(self.project_root), "multi-leg-3-42-release")
        assert result is not None
        self.assertEqual(result.id, "multi-leg.3")
        self.assertEqual(result.prefix, "multi-leg-3")
        self.assertEqual(result.key, "multi-leg-3-42-release")

    def test_numeric_leading_title_full_key_treats_story_one_as_story_number(self) -> None:
        result = normalize_story_key(str(self.project_root), "multi-leg-1-2026-release")
        assert result is not None
        self.assertEqual(result.id, "multi-leg.1")
        self.assertEqual(result.prefix, "multi-leg-1")
        self.assertEqual(result.key, "multi-leg-1-2026-release")

    def test_numeric_leading_title_full_key_treats_story_two_as_story_number(self) -> None:
        result = normalize_story_key(str(self.project_root), "multi-leg-2-42-release")
        assert result is not None
        self.assertEqual(result.id, "multi-leg.2")
        self.assertEqual(result.prefix, "multi-leg-2")
        self.assertEqual(result.key, "multi-leg-2-42-release")

    def test_numeric_title_segment_after_story_two_stays_title_segment(self) -> None:
        result = normalize_story_key(str(self.project_root), "multi-leg-2-part-3-fix")
        assert result is not None
        self.assertEqual(result.id, "multi-leg.2")
        self.assertEqual(result.prefix, "multi-leg-2")
        self.assertEqual(result.key, "multi-leg-2-part-3-fix")

    def test_epic_hint_accepts_numeric_segments_later_in_title(self) -> None:
        result = normalize_story_key_for_epic(str(self.project_root), "multi-leg", "multi-leg-3-part-2-fix")
        assert result is not None
        self.assertEqual(result.id, "multi-leg.3")
        self.assertEqual(result.prefix, "multi-leg-3")
        self.assertEqual(result.key, "multi-leg-3-part-2-fix")

    def test_numeric_leading_title_full_key_uses_epic_hint_when_available(self) -> None:
        result = normalize_story_key_for_epic(str(self.project_root), "multi-leg", "multi-leg-3-2026-release")
        assert result is not None
        self.assertEqual(result.id, "multi-leg.3")
        self.assertEqual(result.prefix, "multi-leg-3")
        self.assertEqual(result.key, "multi-leg-3-2026-release")

    def test_no_hyphen_epic_hint_accepts_numeric_leading_title_segments(self) -> None:
        result = normalize_story_key_for_epic(str(self.project_root), "alpha", "alpha-1-2026-release")
        assert result is not None
        self.assertEqual(result.id, "alpha.1")
        self.assertEqual(result.prefix, "alpha-1")
        self.assertEqual(result.key, "alpha-1-2026-release")

    def test_compound_epic_name_with_numeric_segment_uses_story_sized_suffix(self) -> None:
        self._write_sprint_status("phase-2-1-title: done\nphase-2-2-next: ready-for-dev\n")
        result = normalize_story_key(str(self.project_root), "phase-2-1-title")
        assert result is not None
        self.assertEqual(result.id, "phase-2.1")
        self.assertEqual(result.prefix, "phase-2-1")
        self.assertEqual(result.key, "phase-2-1-title")

    def test_compound_epic_name_with_numeric_segment_above_two_uses_known_epic(self) -> None:
        self._write_sprint_status("phase-3-1-title: done\nphase-3-2-next: ready-for-dev\n")
        result = normalize_story_key(str(self.project_root), "phase-3-1-title")
        assert result is not None
        self.assertEqual(result.id, "phase-3.1")
        self.assertEqual(result.prefix, "phase-3-1")
        self.assertEqual(result.key, "phase-3-1-title")

    def test_compound_epic_name_with_two_digit_numeric_segment_uses_known_epic(self) -> None:
        self._write_sprint_status("phase-10-1-title: done\nphase-10-2-next: ready-for-dev\n")
        result = normalize_story_key(str(self.project_root), "phase-10-1-title")
        assert result is not None
        self.assertEqual(result.id, "phase-10.1")
        self.assertEqual(result.prefix, "phase-10-1")
        self.assertEqual(result.key, "phase-10-1-title")

    def test_compound_epic_name_with_hyphen_and_numeric_segment(self) -> None:
        self._write_sprint_status("web-app-2-1-title: done\nweb-app-2-2-next: ready-for-dev\n")
        result = normalize_story_key(str(self.project_root), "web-app-2-1-title")
        assert result is not None
        self.assertEqual(result.id, "web-app-2.1")
        self.assertEqual(result.prefix, "web-app-2-1")
        self.assertEqual(result.key, "web-app-2-1-title")

    def test_compound_epic_name_with_hyphen_and_numeric_segment_above_two(self) -> None:
        self._write_sprint_status("web-app-3-1-title: done\nweb-app-3-2-next: ready-for-dev\n")
        result = normalize_story_key(str(self.project_root), "web-app-3-1-title")
        assert result is not None
        self.assertEqual(result.id, "web-app-3.1")
        self.assertEqual(result.prefix, "web-app-3-1")
        self.assertEqual(result.key, "web-app-3-1-title")

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
        self._write_sprint_status(
            """
            development_status:
              multi-leg-4-strict-asset-precision-registration: done
            """
        )
        result = sprint_status_get(str(self.project_root), "multi-leg.4")
        self.assertTrue(result.found)
        self.assertEqual(result.story, "multi-leg-4-strict-asset-precision-registration")
        self.assertEqual(result.status, "done")
        self.assertTrue(result.done)

    def test_sprint_status_get_falls_back_to_status_prefix_when_artifact_slug_differs(self) -> None:
        artifacts = self.project_root / "_bmad-output" / "implementation-artifacts"
        (artifacts / "1-2-old-title.md").write_text("", encoding="utf-8")
        self._write_sprint_status(
            """
            development_status:
              1-2-new-title: done
            """
        )
        result = sprint_status_get(str(self.project_root), "1.2")
        self.assertTrue(result.found)
        self.assertEqual(result.story, "1-2-new-title")
        self.assertEqual(result.status, "done")
        self.assertTrue(result.done)

    def test_sprint_status_epic_rejects_overlapping_non_numeric_epic_prefix(self) -> None:
        self._write_sprint_status(
            """
            development_status:
              multi-leg-4-strict-asset-precision-registration: done
              multi-leg-ui-99-unrelated: done
            """
        )
        stories, done = sprint_status_epic(str(self.project_root), "multi-leg")
        self.assertEqual(stories, ["multi-leg-4-strict-asset-precision-registration"])
        self.assertEqual(done, 1)

    def test_sprint_status_epic_accepts_numeric_segment_in_epic(self) -> None:
        self._write_sprint_status(
            """
            development_status:
              phase-2-1-title: done
              phase-20-1-unrelated: done
            """
        )
        stories, done = sprint_status_epic(str(self.project_root), "phase-2")
        self.assertEqual(stories, ["phase-2-1-title"])
        self.assertEqual(done, 1)

    def test_sprint_status_epic_rejects_short_numeric_segment_epic_prefix(self) -> None:
        (self.project_root / "_bmad-output" / "implementation-artifacts" / "epic-phase-2.md").write_text(
            "",
            encoding="utf-8",
        )
        self._write_sprint_status(
            """
            development_status:
              phase-2-1-title: done
            """
        )
        stories, done = sprint_status_epic(str(self.project_root), "phase")
        self.assertEqual(stories, [])
        self.assertEqual(done, 0)

    def test_sprint_status_epic_rejects_hyphenated_known_longer_epic_prefix(self) -> None:
        self._write_sprint_status(
            """
            development_status:
              web-app-3-1-title: done
              web-app-3-2-next: done
            """
        )
        stories, done = sprint_status_epic(str(self.project_root), "web-app")
        self.assertEqual(stories, [])
        self.assertEqual(done, 0)

        stories, done = sprint_status_epic(str(self.project_root), "web-app-3")
        self.assertEqual(stories, ["web-app-3-1-title", "web-app-3-2-next"])
        self.assertEqual(done, 2)

    def test_sprint_status_epic_accepts_numeric_segment_in_title(self) -> None:
        self._write_sprint_status(
            """
            development_status:
              multi-leg-3-2026-release: done
              multi-leg-4-next: done
            """
        )
        stories, done = sprint_status_epic(str(self.project_root), "multi-leg")
        self.assertEqual(stories, ["multi-leg-3-2026-release", "multi-leg-4-next"])
        self.assertEqual(done, 2)

    def test_sprint_status_epic_accepts_short_numeric_segment_in_title(self) -> None:
        self._write_sprint_status(
            """
            development_status:
              multi-leg-3-part-2-fix: done
              multi-leg-4-next: done
            """
        )
        stories, done = sprint_status_epic(str(self.project_root), "multi-leg")
        self.assertEqual(stories, ["multi-leg-3-part-2-fix", "multi-leg-4-next"])
        self.assertEqual(done, 2)

    def test_sprint_status_epic_deduplicates_normalized_story_ids(self) -> None:
        self._write_sprint_status(
            """
            development_status:
              multi-leg.3: done
              multi-leg-3-lossless-quantity-serialization: done
              multi-leg-4-strict-asset-precision-registration: ready-for-dev
            """
        )
        stories, done = sprint_status_epic(str(self.project_root), "multi-leg")
        self.assertEqual(stories, ["multi-leg-3-lossless-quantity-serialization", "multi-leg-4-strict-asset-precision-registration"])
        self.assertEqual(done, 1)

    def test_sprint_status_epic_prefers_full_key_duplicate_status(self) -> None:
        self._write_sprint_status(
            """
            development_status:
              multi-leg.3: ready-for-dev
              multi-leg-3-lossless-quantity-serialization: done
              multi-leg-4-strict-asset-precision-registration: done
            """
        )
        stories, done = sprint_status_epic(str(self.project_root), "multi-leg")
        self.assertEqual(stories, ["multi-leg-3-lossless-quantity-serialization", "multi-leg-4-strict-asset-precision-registration"])
        self.assertEqual(done, 2)

    # --- Rejection paths ---

    def test_unrecognized_format_returns_none(self) -> None:
        self.assertIsNone(normalize_story_key(str(self.project_root), "garbage"))
        self.assertIsNone(normalize_story_key(str(self.project_root), ""))
        self.assertIsNone(normalize_story_key(str(self.project_root), "1"))
        # Leading digit is not a valid non-numeric epic prefix.
        self.assertIsNone(normalize_story_key(str(self.project_root), "9multi.1"))

    def _write_sprint_status(self, content: str) -> None:
        path = self.project_root / "_bmad-output" / "implementation-artifacts" / "sprint-status.yaml"
        path.write_text(textwrap.dedent(content), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
