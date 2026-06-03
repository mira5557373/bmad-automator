from __future__ import annotations

import unittest

from story_automator.core.runtime_policy import PolicyError
from story_automator.core.success_verifiers import create_story_artifact, epic_complete
from tests.success_verifier_case import SuccessVerifierCase


class SuccessVerifierTests(SuccessVerifierCase):

    def test_create_story_artifact_matches_configured_glob(self) -> None:
        self._write_story("1-2-example", status="draft")
        payload = create_story_artifact(
            project_root=str(self.project_root),
            story_key="1.2",
            contract={"config": {"glob": "_bmad-output/implementation-artifacts/{story_prefix}-*.md", "expectedMatches": 1}},
        )
        self.assertTrue(payload["verified"])
        self.assertEqual(payload["actualMatches"], 1)

    def test_create_story_artifact_handles_single_story_compound_epic_key(self) -> None:
        self._write_sprint_status("phase-2-1-title: done\n")
        self._write_story("phase-2-1-title", status="draft")
        payload = create_story_artifact(
            project_root=str(self.project_root),
            story_key="phase-2-1-title",
            contract={"config": {"glob": "_bmad-output/implementation-artifacts/{story_prefix}-*.md", "expectedMatches": 1}},
        )
        self.assertTrue(payload["verified"])
        self.assertEqual(payload["story"], "phase-2-1-title")
        self.assertEqual(payload["actualMatches"], 1)

    def test_create_story_artifact_rejects_missing_explicit_full_key_sibling_file(self) -> None:
        self._write_story("multi-leg-3-old", status="draft")
        payload = create_story_artifact(
            project_root=str(self.project_root),
            story_key="multi-leg-3-new",
            contract={"config": {"expectedMatches": 1}},
        )
        self.assertFalse(payload["verified"])
        self.assertEqual(payload["story"], "multi-leg-3-new")
        self.assertEqual(payload["actualMatches"], 0)

    def test_create_story_artifact_rejects_glob_that_escapes_project_root(self) -> None:
        with self.assertRaisesRegex(PolicyError, "success.config.glob escapes project root"):
            create_story_artifact(
                project_root=str(self.project_root),
                story_key="1.2",
                contract={"config": {"glob": "../other/{story_prefix}-*.md", "expectedMatches": 1}},
            )

    def test_create_story_artifact_rejects_glob_outside_artifacts_dir(self) -> None:
        with self.assertRaisesRegex(PolicyError, "success.config.glob must stay within _bmad-output/implementation-artifacts"):
            create_story_artifact(
                project_root=str(self.project_root),
                story_key="1.2",
                contract={"config": {"glob": "docs/{story_prefix}-*.md", "expectedMatches": 1}},
            )

    def test_create_story_artifact_rejects_absolute_glob(self) -> None:
        with self.assertRaisesRegex(PolicyError, "success.config.glob must be relative to implementation artifacts"):
            create_story_artifact(
                project_root=str(self.project_root),
                story_key="1.2",
                contract={"config": {"glob": "/tmp/{story_prefix}-*.md", "expectedMatches": 1}},
            )

    def test_epic_complete_checks_sprint_status(self) -> None:
        self._write_sprint_status("1-1-story-one: done\n1-2-story-two: done\n")
        payload = epic_complete(project_root=str(self.project_root), story_key="1.2")
        self.assertTrue(payload["verified"])
        self.assertEqual(payload["doneStories"], 2)

    def test_epic_complete_accepts_bare_epic_id(self) -> None:
        self._write_sprint_status("1-1-story-one: done\n1-2-story-two: done\n")
        payload = epic_complete(project_root=str(self.project_root), story_key="1")
        self.assertTrue(payload["verified"])
        self.assertEqual(payload["epic"], "1")

    def test_epic_complete_accepts_bare_non_numeric_epic_id(self) -> None:
        self._write_sprint_status("multi-leg-1-story-one: done\nmulti-leg-2-story-two: done\n")
        payload = epic_complete(project_root=str(self.project_root), story_key="multi-leg")
        self.assertTrue(payload["verified"])
        self.assertEqual(payload["epic"], "multi-leg")
        self.assertEqual(payload["doneStories"], 2)

    def test_epic_complete_handles_numeric_leading_title_segments(self) -> None:
        self._write_sprint_status("multi-leg-3-2026-release: done\nmulti-leg-4-next: done\n")
        payload = epic_complete(project_root=str(self.project_root), story_key="multi-leg-3-2026-release")
        self.assertTrue(payload["verified"])
        self.assertEqual(payload["epic"], "multi-leg")
        self.assertEqual(payload["doneStories"], 2)

    def test_epic_complete_does_not_false_pass_story_one_title_segment(self) -> None:
        self._write_sprint_status("multi-leg-3-part-1-fix: done\nmulti-leg-4-next: ready-for-dev\n")
        payload = epic_complete(project_root=str(self.project_root), story_key="multi-leg-3-part-1-fix")
        self.assertFalse(payload["verified"])
        self.assertEqual(payload["epic"], "multi-leg")
        self.assertEqual(payload["totalStories"], 2)
        self.assertEqual(payload["doneStories"], 1)

    def test_epic_complete_normalizes_dashed_story_prefix_before_bare_epic(self) -> None:
        self._write_sprint_status("multi-leg-3-2026-release: done\nmulti-leg-4-next: ready-for-dev\n")
        payload = epic_complete(project_root=str(self.project_root), story_key="multi-leg-3")
        self.assertFalse(payload["verified"])
        self.assertEqual(payload["epic"], "multi-leg")
        self.assertEqual(payload["totalStories"], 2)
        self.assertEqual(payload["doneStories"], 1)

    def test_epic_complete_rejects_missing_explicit_full_key_sibling(self) -> None:
        self._write_sprint_status("multi-leg-3-old: done\n")
        payload = epic_complete(project_root=str(self.project_root), story_key="multi-leg-3-new")
        self.assertFalse(payload["verified"])
        self.assertEqual(payload["epic"], "multi-leg")
        self.assertEqual(payload["sprint_status"], "not_found")

    def test_epic_complete_handles_single_story_compound_epic_key(self) -> None:
        self._write_sprint_status("phase-2-1-title: done\n")
        payload = epic_complete(project_root=str(self.project_root), story_key="phase-2-1-title")
        self.assertTrue(payload["verified"])
        self.assertEqual(payload["epic"], "phase-2")
        self.assertEqual(payload["doneStories"], 1)


if __name__ == "__main__":
    unittest.main()
