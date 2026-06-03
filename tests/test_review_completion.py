from __future__ import annotations

import unittest

from story_automator.core.runtime_policy import PolicyError
from story_automator.core.success_verifiers import review_completion
from tests.success_verifier_case import SuccessVerifierCase


class ReviewCompletionTests(SuccessVerifierCase):

    def test_review_completion_uses_contract_done_values(self) -> None:
        self._write_story("1-2-example", status="approved")
        contract = self._write_review_contract(
            {"doneValues": ["approved"], "sourceOrder": ["story-file"], "syncSprintStatus": False}
        )
        payload = review_completion(
            project_root=str(self.project_root),
            story_key="1.2",
            contract={"contractPath": str(contract)},
        )
        self.assertTrue(payload["verified"])
        self.assertEqual(payload["source"], "story-file")
        self.assertNotIn("note", payload)

    def test_review_completion_prefers_full_key_duplicate_sprint_status(self) -> None:
        self._write_sprint_status("multi-leg.3: ready-for-dev\nmulti-leg-3-lossless: done\n")
        payload = review_completion(
            project_root=str(self.project_root),
            story_key="multi-leg.3",
            contract={
                "doneValues": ["done"],
                "sourceOrder": ["sprint-status.yaml"],
                "syncSprintStatus": False,
            },
        )
        self.assertTrue(payload["verified"])
        self.assertEqual(payload["story"], "multi-leg-3-lossless")
        self.assertEqual(payload["sprint_status"], "done")

    def test_review_completion_prefers_requested_full_key_over_sibling_status(self) -> None:
        self._write_sprint_status("multi-leg-3-old: done\nmulti-leg-3-new: ready-for-dev\n")
        payload = review_completion(
            project_root=str(self.project_root),
            story_key="multi-leg-3-old",
            contract={
                "doneValues": ["done"],
                "sourceOrder": ["sprint-status.yaml"],
                "syncSprintStatus": False,
            },
        )
        self.assertTrue(payload["verified"])
        self.assertEqual(payload["story"], "multi-leg-3-old")
        self.assertEqual(payload["sprint_status"], "done")

    def test_review_completion_does_not_verify_requested_full_key_from_sibling_status(self) -> None:
        self._write_sprint_status("multi-leg-3-old: done\n")
        self._write_story("multi-leg-3-new", status="ready-for-dev")
        payload = review_completion(
            project_root=str(self.project_root),
            story_key="multi-leg-3-new",
            contract={
                "doneValues": ["done"],
                "sourceOrder": ["sprint-status.yaml", "story-file"],
                "syncSprintStatus": False,
            },
        )
        self.assertFalse(payload["verified"])
        self.assertEqual(payload["story"], "multi-leg-3-new")
        self.assertEqual(payload["sprint_status"], "not_found")

    def test_review_completion_rejects_longer_epic_artifact_for_dotted_id(self) -> None:
        self._write_story("release-2026-phase-2-1-title", status="done")
        payload = review_completion(
            project_root=str(self.project_root),
            story_key="release.2026",
            contract={
                "doneValues": ["done"],
                "sourceOrder": ["story-file"],
                "syncSprintStatus": False,
            },
        )
        self.assertFalse(payload["verified"])
        self.assertEqual(payload["story"], "release-2026")
        self.assertEqual(payload["story_file_status"], "unknown")

    def test_review_completion_rejects_short_numeric_longer_epic_status_for_dotted_id(self) -> None:
        self._write_sprint_status("release-3-phase-2-1-title: done\n")
        payload = review_completion(
            project_root=str(self.project_root),
            story_key="release.3",
            contract={
                "doneValues": ["done"],
                "sourceOrder": ["sprint-status.yaml"],
                "syncSprintStatus": False,
            },
        )
        self.assertFalse(payload["verified"])
        self.assertEqual(payload["story"], "release-3")
        self.assertEqual(payload["sprint_status"], "not_found")

    def test_review_completion_resolves_four_digit_story_with_numeric_later_title_segment(self) -> None:
        self._write_sprint_status("multi-leg-2026-part-2-fix: done\n")
        payload = review_completion(
            project_root=str(self.project_root),
            story_key="multi-leg.2026",
            contract={
                "doneValues": ["done"],
                "sourceOrder": ["sprint-status.yaml"],
                "syncSprintStatus": False,
            },
        )
        self.assertTrue(payload["verified"])
        self.assertEqual(payload["story"], "multi-leg-2026-part-2-fix")
        self.assertEqual(payload["sprint_status"], "done")

    def test_review_completion_resolves_four_digit_story_file_with_numeric_later_title_segment(self) -> None:
        self._write_story("multi-leg-2026-part-2-fix", status="done")
        payload = review_completion(
            project_root=str(self.project_root),
            story_key="multi-leg.2026",
            contract={
                "doneValues": ["done"],
                "sourceOrder": ["story-file"],
                "syncSprintStatus": False,
            },
        )
        self.assertTrue(payload["verified"])
        self.assertEqual(payload["story"], "multi-leg-2026-part-2-fix")
        self.assertEqual(payload["story_file_status"], "done")

    def test_review_completion_reports_sprint_selected_story(self) -> None:
        self._write_story("multi-leg-3-old", status="approved")
        self._write_sprint_status("multi-leg-3-new: done\n")
        payload = review_completion(
            project_root=str(self.project_root),
            story_key="multi-leg.3",
            contract={
                "doneValues": ["done"],
                "sourceOrder": ["sprint-status.yaml"],
                "syncSprintStatus": False,
            },
        )
        self.assertTrue(payload["verified"])
        self.assertEqual(payload["story"], "multi-leg-3-new")
        self.assertEqual(payload["sprint_status"], "done")

    def test_review_completion_uses_sprint_selected_story_file(self) -> None:
        self._write_story("multi-leg-3-old", status="done")
        self._write_story("multi-leg-3-new", status="ready-for-dev")
        self._write_sprint_status("multi-leg-3-new: ready-for-dev\n")
        payload = review_completion(
            project_root=str(self.project_root),
            story_key="multi-leg.3",
            contract={
                "doneValues": ["done"],
                "sourceOrder": ["story-file"],
                "syncSprintStatus": False,
            },
        )
        self.assertFalse(payload["verified"])
        self.assertEqual(payload["story"], "multi-leg-3-new")
        self.assertEqual(payload["story_file_status"], "ready-for-dev")

    def test_review_completion_does_not_fallback_to_stale_story_file_when_sprint_selects_missing_story(self) -> None:
        self._write_story("multi-leg-3-aaa", status="done")
        self._write_sprint_status("multi-leg-3-new: ready-for-dev\n")
        payload = review_completion(
            project_root=str(self.project_root),
            story_key="multi-leg.3",
            contract={
                "doneValues": ["done"],
                "sourceOrder": ["story-file"],
                "syncSprintStatus": False,
            },
        )
        self.assertFalse(payload["verified"])
        self.assertEqual(payload["story"], "multi-leg-3-new")
        self.assertEqual(payload["story_file_status"], "unknown")

    def test_review_completion_uses_story_file_only_for_compound_numeric_epic(self) -> None:
        self._write_story("phase-2-1-title", status="done")
        payload = review_completion(
            project_root=str(self.project_root),
            story_key="phase-2.1",
            contract={"sourceOrder": ["story-file"], "syncSprintStatus": False},
        )
        self.assertTrue(payload["verified"])
        self.assertEqual(payload["story"], "phase-2-1-title")
        self.assertEqual(payload["story_file_status"], "done")

    def test_review_completion_rejects_missing_explicit_full_key_sibling_file(self) -> None:
        self._write_story("multi-leg-3-old", status="done")
        payload = review_completion(
            project_root=str(self.project_root),
            story_key="multi-leg-3-new",
            contract={"sourceOrder": ["story-file"], "syncSprintStatus": False},
        )
        self.assertFalse(payload["verified"])
        self.assertEqual(payload["story"], "multi-leg-3-new")
        self.assertEqual(payload["story_file_status"], "unknown")

    def test_review_completion_reports_story_file_selected_by_sprint_status(self) -> None:
        self._write_story("multi-leg-3-a-old", status="ready-for-dev")
        self._write_story("multi-leg-3-z-new", status="done")
        self._write_sprint_status("multi-leg-3-z-new: ready-for-dev\n")
        payload = review_completion(
            project_root=str(self.project_root),
            story_key="multi-leg.3",
            contract={
                "doneValues": ["done"],
                "sourceOrder": ["story-file"],
                "syncSprintStatus": False,
            },
        )
        self.assertTrue(payload["verified"])
        self.assertEqual(payload["story"], "multi-leg-3-z-new")
        self.assertEqual(payload["story_file_status"], "done")

    def test_review_completion_uses_requested_full_key_when_sprint_status_is_alias(self) -> None:
        self._write_story("multi-leg-3-z-new", status="done")
        self._write_sprint_status("multi-leg.3: ready-for-dev\n")
        payload = review_completion(
            project_root=str(self.project_root),
            story_key="multi-leg-3-z-new",
            contract={
                "doneValues": ["done"],
                "sourceOrder": ["story-file"],
                "syncSprintStatus": False,
            },
        )
        self.assertTrue(payload["verified"])
        self.assertEqual(payload["story"], "multi-leg-3-z-new")
        self.assertEqual(payload["story_file_status"], "done")

    def test_review_completion_uses_requested_full_key_without_sprint_status(self) -> None:
        self._write_story("multi-leg-3-a-old", status="ready-for-dev")
        self._write_story("multi-leg-3-z-new", status="done")
        payload = review_completion(
            project_root=str(self.project_root),
            story_key="multi-leg-3-z-new",
            contract={
                "doneValues": ["done"],
                "sourceOrder": ["story-file"],
                "syncSprintStatus": False,
            },
        )
        self.assertTrue(payload["verified"])
        self.assertEqual(payload["story"], "multi-leg-3-z-new")
        self.assertEqual(payload["story_file_status"], "done")

    def test_review_completion_resolves_numeric_title_segment(self) -> None:
        self._write_sprint_status("multi-leg-3-2026-release: done\n")
        payload = review_completion(
            project_root=str(self.project_root),
            story_key="multi-leg.3",
            contract={
                "doneValues": ["done"],
                "sourceOrder": ["sprint-status.yaml"],
                "syncSprintStatus": False,
            },
        )
        self.assertTrue(payload["verified"])
        self.assertEqual(payload["story"], "multi-leg-3-2026-release")
        self.assertEqual(payload["sprint_status"], "done")

    def test_review_completion_rejects_invalid_contract(self) -> None:
        contract = self._write_review_contract({"sourceOrder": ["bad-source"]})
        with self.assertRaises(PolicyError):
            review_completion(
                project_root=str(self.project_root),
                story_key="1.2",
                contract={"contractPath": str(contract)},
            )

    def test_review_completion_rejects_empty_contract_lists(self) -> None:
        with self.assertRaises(PolicyError):
            review_completion(
                project_root=str(self.project_root),
                story_key="1.2",
                contract={"doneValues": [], "sourceOrder": []},
            )

    def test_review_completion_rejects_whitespace_only_done_values(self) -> None:
        with self.assertRaises(PolicyError):
            review_completion(
                project_root=str(self.project_root),
                story_key="1.2",
                contract={"doneValues": ["   "], "sourceOrder": ["story-file"]},
            )


if __name__ == "__main__":
    unittest.main()
