from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from story_automator.commands.orchestrator import cmd_orchestrator_helper
from story_automator.commands.state import cmd_build_state_doc, cmd_sprint_compare
from story_automator.commands.tmux import _build_cmd, _render_step_prompt, _verify_monitor_completion, cmd_monitor_session
from story_automator.commands.validate_story_creation import cmd_validate_story_creation
from story_automator.core.review_verify import verify_code_review_completion
from story_automator.core.runtime_policy import PolicyError
from story_automator.core.sprint import sprint_status_get
from story_automator.core.story_keys import normalize_story_key, sprint_status_file
from story_automator.core.success_verifiers import create_story_artifact, epic_complete, review_completion


REPO_ROOT = Path(__file__).resolve().parents[1]


class SuccessVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tmp.name)
        self.output_dir = self.project_root / "_bmad-output" / "story-automator"
        self.artifacts_dir = self.project_root / "_bmad-output" / "implementation-artifacts"
        self.docs_artifacts_dir = self.project_root / "docs" / "bmad" / "implementation-artifacts"
        self._install_bundle()
        self._install_required_skills()

    def tearDown(self) -> None:
        self.tmp.cleanup()

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

    def test_config_implementation_artifacts_points_to_docs_bmad(self) -> None:
        self._write_bmad_config("implementation_artifacts: docs/bmad/implementation-artifacts\n")
        self._write_docs_story("1-2-docs", status="draft")
        self._write_docs_sprint_status("1-2-docs: done\n")

        self.assertEqual(Path(sprint_status_file(str(self.project_root))), self.docs_artifacts_dir / "sprint-status.yaml")
        self.assertEqual(normalize_story_key(str(self.project_root), "1.2").key, "1-2-docs")
        self.assertTrue(sprint_status_get(str(self.project_root), "1.2").done)

    def test_config_preserves_hash_inside_quoted_artifacts_path(self) -> None:
        self._write_bmad_config('implementation_artifacts: "docs/#draft/implementation-artifacts" # local folder\n')
        artifacts_dir = self.project_root / "docs" / "#draft" / "implementation-artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        story = artifacts_dir / "1-2-docs.md"
        story.write_text("---\nStatus: draft\nTitle: Story\n---\n", encoding="utf-8")
        payload = create_story_artifact(project_root=str(self.project_root), story_key="1.2", contract={})
        self.assertTrue(payload["verified"])
        self.assertEqual(payload["matches"], [str(story)])

    def test_config_rejects_artifacts_path_outside_project(self) -> None:
        self._write_bmad_config("implementation_artifacts: ../outside/implementation-artifacts\n")
        with self.assertRaisesRegex(ValueError, "BMAD config implementation_artifacts"):
            create_story_artifact(project_root=str(self.project_root), story_key="1.2", contract={})

    def test_config_output_folder_points_to_docs_bmad(self) -> None:
        self._write_bmad_config("output_folder: docs/bmad\n")
        self._write_docs_story("1-2-docs", status="draft")
        payload = create_story_artifact(project_root=str(self.project_root), story_key="1.2", contract={})
        self.assertTrue(payload["verified"])
        self.assertEqual(payload["actualMatches"], 1)
        self.assertEqual(payload["matches"], [str(self.docs_artifacts_dir / "1-2-docs.md")])

    def test_config_supports_output_folder_placeholder(self) -> None:
        self._write_bmad_config("output_folder: docs/bmad\nimplementation_artifacts: '{output_folder}/implementation-artifacts'\n")
        self._write_docs_story("1-2-docs", status="draft")
        payload = create_story_artifact(project_root=str(self.project_root), story_key="1.2", contract={})
        self.assertTrue(payload["verified"])
        self.assertEqual(payload["matches"], [str(self.docs_artifacts_dir / "1-2-docs.md")])

    def test_config_supports_project_root_placeholder_in_artifacts_path(self) -> None:
        self._write_bmad_config('implementation_artifacts: "{project-root}/_bmad-output/implementation-artifacts"\n')
        story = self._write_story("1-2-real", status="ready")

        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(["story-file-status", "1.2"])

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["file"], str(story))
        self.assertEqual(payload["status"], "ready")

    def test_docs_bmad_detected_without_config(self) -> None:
        self._write_docs_story("1-2-docs", status="draft")
        self._write_docs_sprint_status("1-2-docs: done\n")
        self.assertEqual(normalize_story_key(str(self.project_root), "1.2").key, "1-2-docs")
        self.assertTrue(epic_complete(project_root=str(self.project_root), story_key="1.2")["verified"])

    def test_empty_legacy_dir_does_not_block_docs_fallback(self) -> None:
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self._write_docs_story("1-2-docs", status="draft")
        self._write_docs_sprint_status("1-2-docs: done\n")

        self.assertEqual(normalize_story_key(str(self.project_root), "1.2").key, "1-2-docs")
        self.assertTrue(epic_complete(project_root=str(self.project_root), story_key="1.2")["verified"])

    def test_validate_story_creation_count_override_skips_invalid_default_config(self) -> None:
        self._write_bmad_config("implementation_artifacts: ../outside/implementation-artifacts\n")
        custom = self.project_root / "custom-artifacts"
        custom.mkdir(parents=True, exist_ok=True)
        (custom / "1-2-custom.md").write_text("---\nStatus: draft\nTitle: Story\n---\n", encoding="utf-8")

        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_validate_story_creation(["count", "1.2", "--artifacts-dir", str(custom)])

        self.assertEqual(code, 0)
        self.assertEqual(stdout.getvalue().strip(), "1")

    def test_create_story_artifact_uses_legacy_root_when_glob_matches_legacy_story(self) -> None:
        self._write_bmad_config("implementation_artifacts: docs/bmad/implementation-artifacts\n")
        legacy_story = self._write_story("1-2-legacy", status="draft")

        payload = create_story_artifact(
            project_root=str(self.project_root),
            story_key="1.2",
            contract={"config": {"glob": "_bmad-output/implementation-artifacts/{story_prefix}-*.md", "expectedMatches": 1}},
        )

        self.assertTrue(payload["verified"])
        self.assertEqual(payload["matches"], [str(legacy_story)])

    def test_legacy_artifacts_take_precedence_over_docs_bmad_without_config(self) -> None:
        self._write_story("1-2-legacy", status="draft")
        self._write_docs_story("1-2-docs", status="draft")
        self.assertEqual(normalize_story_key(str(self.project_root), "1.2").key, "1-2-legacy")

    def test_legacy_root_sprint_status_fallback_is_preserved(self) -> None:
        legacy = self.project_root / "_bmad-output" / "sprint-status.yaml"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text("1-2-legacy: done\n", encoding="utf-8")
        self.assertEqual(Path(sprint_status_file(str(self.project_root))), legacy)
        self.assertEqual(normalize_story_key(str(self.project_root), "1.2").key, "1-2-legacy")

    def test_story_file_status_uses_resolved_artifacts_dir(self) -> None:
        self._write_bmad_config("implementation_artifacts: docs/bmad/implementation-artifacts\n")
        story = self._write_docs_story("1-2-docs", status="ready")
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(["story-file-status", "1.2"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["file"], str(story))
        self.assertEqual(payload["status"], "ready")

    def test_story_file_status_returns_json_error_for_invalid_artifacts_config(self) -> None:
        self._write_bmad_config("implementation_artifacts: ../outside/implementation-artifacts\n")
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(["story-file-status", "1.2"])
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["ok"])
        self.assertIn("BMAD config implementation_artifacts", payload["error"])

    def test_validate_story_creation_count_uses_resolved_artifacts_dir(self) -> None:
        self._write_bmad_config("implementation_artifacts: docs/bmad/implementation-artifacts\n")
        self._write_docs_story("1-2-docs", status="draft")
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_validate_story_creation(["count", "1.2"])
        self.assertEqual(code, 0)
        self.assertEqual(stdout.getvalue().strip(), "1")

    def test_validate_story_creation_count_rejects_missing_artifacts_dir_value(self) -> None:
        stderr = io.StringIO()
        with patch_env(self.project_root), redirect_stderr(stderr):
            code = cmd_validate_story_creation(["count", "1.2", "--artifacts-dir"])
        self.assertEqual(code, 1)
        self.assertEqual(stderr.getvalue().strip(), "--artifacts-dir requires a value")

    def test_validate_story_creation_count_rejects_empty_artifacts_dir_value(self) -> None:
        stderr = io.StringIO()
        with patch_env(self.project_root), redirect_stderr(stderr):
            code = cmd_validate_story_creation(["count", "1.2", "--artifacts-dir", ""])
        self.assertEqual(code, 1)
        self.assertEqual(stderr.getvalue().strip(), "--artifacts-dir requires a value")

    def test_validate_story_creation_count_rejects_flag_like_artifacts_dir_value(self) -> None:
        stderr = io.StringIO()
        with patch_env(self.project_root), redirect_stderr(stderr):
            code = cmd_validate_story_creation(["count", "1.2", "--artifacts-dir", "--state-file"])
        self.assertEqual(code, 1)
        self.assertEqual(stderr.getvalue().strip(), "--artifacts-dir requires a value")

    def test_validate_story_creation_count_rejects_unknown_argument(self) -> None:
        stderr = io.StringIO()
        with patch_env(self.project_root), redirect_stderr(stderr):
            code = cmd_validate_story_creation(["count", "1.2", "--unknown"])
        self.assertEqual(code, 1)
        self.assertEqual(stderr.getvalue().strip(), "unsupported count argument: --unknown")

    def test_validate_story_creation_prefix_skips_invalid_artifacts_config(self) -> None:
        self._write_bmad_config("implementation_artifacts: ../outside/implementation-artifacts\n")
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_validate_story_creation(["prefix", "1.2"])
        self.assertEqual(code, 0)
        self.assertEqual(stdout.getvalue().strip(), "1-2")

    def test_validate_story_creation_check_returns_compat_schema_for_invalid_artifacts_config(self) -> None:
        self._write_bmad_config("implementation_artifacts: ../outside/implementation-artifacts\n")
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_validate_story_creation(["check", "1.2"])
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["valid"])
        self.assertIn("BMAD config implementation_artifacts", payload["reason"])

    def test_validate_story_creation_count_returns_controlled_error_for_invalid_artifacts_config(self) -> None:
        self._write_bmad_config("implementation_artifacts: ../outside/implementation-artifacts\n")
        stderr = io.StringIO()
        with patch_env(self.project_root), redirect_stderr(stderr):
            code = cmd_validate_story_creation(["count", "1.2"])
        self.assertEqual(code, 1)
        self.assertIn("BMAD config implementation_artifacts", stderr.getvalue())

    def test_step_prompt_uses_resolved_artifacts_dir(self) -> None:
        self._write_bmad_config("implementation_artifacts: docs/bmad/implementation-artifacts\n")
        template = self.project_root / "prompt.md"
        template.write_text("Story file: `{{implementation_artifacts}}/{{story_prefix}}-*.md`", encoding="utf-8")
        with patch_env(self.project_root):
            prompt = _render_step_prompt({"prompt": {"templatePath": str(template)}, "assets": {"files": {}}}, "1.2", "1-2", "")
        self.assertIn("docs/bmad/implementation-artifacts/1-2-*.md", prompt)
        self.assertNotIn("_bmad-output/implementation-artifacts", prompt)

    def test_resume_step_uses_configured_sprint_status_path(self) -> None:
        self._write_bmad_config("implementation_artifacts: docs/bmad/implementation-artifacts\n")
        state_file = self._build_state()
        self._write_docs_sprint_status("1.2: done\n")
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_sprint_compare(["--state", str(state_file), "--sprint", str(self.docs_artifacts_dir / "sprint-status.yaml")])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["incomplete"], [])

    def test_monitoring_fallback_uses_implementation_artifacts_placeholder(self) -> None:
        fallback = (self.project_root / ".claude" / "skills" / "bmad-story-automator" / "data" / "monitoring-fallback.md").read_text(encoding="utf-8")
        self.assertIn("ls {{implementation_artifacts}}/{story_prefix}-*.md", fallback)
        self.assertNotIn("ls _bmad-output/implementation-artifacts/{story_prefix}-*.md", fallback)

    def test_check_blocking_uses_configured_artifacts_epic_file(self) -> None:
        self._write_bmad_config("implementation_artifacts: docs/bmad/implementation-artifacts\n")
        self.docs_artifacts_dir.mkdir(parents=True, exist_ok=True)
        (self.docs_artifacts_dir / "epic-1-docs.md").write_text(
            "### Story 1.1:\n**Dependencies**: none\n\n### Story 1.2:\n**Dependencies**: none\n",
            encoding="utf-8",
        )
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(["check-blocking", "1.1"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["blocking"])
        self.assertEqual(payload["reason"], "no_dependents_found")
        self.assertEqual(payload["source"], "epic_file")

    def test_get_epic_stories_uses_configured_artifacts_epic_file(self) -> None:
        self._write_bmad_config("implementation_artifacts: docs/bmad/implementation-artifacts\n")
        self.docs_artifacts_dir.mkdir(parents=True, exist_ok=True)
        (self.docs_artifacts_dir / "epic-1-docs.md").write_text(
            "### Story 1.1:\n\n### Story 1.2:\n",
            encoding="utf-8",
        )
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(["get-epic-stories", "1"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["stories"], ["1.1", "1.2"])
        self.assertEqual(payload["source"], "epic_file")

    def test_build_cmd_returns_controlled_error_for_invalid_artifacts_config(self) -> None:
        self._write_bmad_config("implementation_artifacts: ../outside/implementation-artifacts\n")
        stderr = io.StringIO()
        with patch_env(self.project_root), redirect_stderr(stderr):
            code = _build_cmd(["review", "1.2"])
        self.assertEqual(code, 1)
        self.assertIn("BMAD config implementation_artifacts", stderr.getvalue())

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

    def test_review_wrapper_uses_pinned_state_snapshot(self) -> None:
        self._write_story("1-2-example", status="approved")
        state_file = self._build_state()
        self._write_override(
            {
                "steps": {
                    "review": {
                        "success": {
                            "config": {"doneValues": ["approved"], "sourceOrder": ["story-file"], "syncSprintStatus": False}
                        }
                    }
                }
            }
        )
        payload = verify_code_review_completion(str(self.project_root), "1.2", state_file=state_file)
        self.assertFalse(payload["verified"])
        self.assertEqual(payload["reason"], "workflow_not_complete")

    def test_review_wrapper_ignores_unrelated_missing_assets(self) -> None:
        shutil.rmtree(self.project_root / ".claude" / "skills" / "bmad-create-story")
        self._write_story("1-2-example", status="done")
        payload = verify_code_review_completion(str(self.project_root), "1.2")
        self.assertTrue(payload["verified"])
        self.assertEqual(payload["source"], "story-file")

    def test_monitor_dispatch_uses_review_verifier_from_contract(self) -> None:
        self._write_story("1-2-example", status="done")
        result = _verify_monitor_completion(
            "review",
            project_root=str(self.project_root),
            story_key="1.2",
            output_file="/tmp/session.txt",
        )
        self.assertIsNotNone(result)
        payload, verifier = result or ({}, "")
        self.assertEqual(verifier, "review_completion")
        self.assertTrue(payload["verified"])

    def test_monitor_dispatch_skips_story_keyed_verifier_without_story_key(self) -> None:
        result = _verify_monitor_completion(
            "review",
            project_root=str(self.project_root),
            story_key="",
            output_file="/tmp/session.txt",
        )
        self.assertIsNotNone(result)
        payload, verifier = result or ({}, "")
        self.assertEqual(verifier, "review_completion")
        self.assertFalse(payload["verified"])
        self.assertEqual(payload["reason"], "story_key_required")

    def test_monitor_dispatch_rejects_missing_verifier_in_contract(self) -> None:
        self._write_override({"steps": {"review": {"success": {"verifier": ""}}}})
        result = _verify_monitor_completion(
            "review",
            project_root=str(self.project_root),
            story_key="1.2",
            output_file="/tmp/session.txt",
        )
        self.assertIsNotNone(result)
        payload, verifier = result or ({}, "")
        self.assertEqual(verifier, "")
        self.assertFalse(payload["verified"])
        self.assertEqual(payload["reason"], "verifier_contract_invalid")

    def test_monitor_session_reports_incomplete_when_verifier_missing(self) -> None:
        self._write_override({"steps": {"review": {"success": {"verifier": ""}}}})
        stdout = io.StringIO()
        statuses = [
            {"todos_done": 1, "todos_total": 1, "session_state": "completed"},
            {"active_task": "/tmp/session.txt"},
        ]
        with patch_env(self.project_root), patch("story_automator.commands.tmux.time.sleep"), patch(
            "story_automator.commands.tmux.session_status", side_effect=statuses
        ), redirect_stdout(stdout):
            code = cmd_monitor_session(["fake-session", "--json", "--workflow", "review", "--story-key", "1.2"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["final_state"], "incomplete")
        self.assertEqual(payload["exit_reason"], "verifier_contract_invalid")
        self.assertFalse(payload["output_verified"])

    def test_monitor_dispatch_rejects_verifier_side_file_error(self) -> None:
        with patch("story_automator.commands.tmux.run_success_verifier", side_effect=FileNotFoundError("missing.json")):
            result = _verify_monitor_completion(
                "review",
                project_root=str(self.project_root),
                story_key="1.2",
                output_file="/tmp/session.txt",
            )
        self.assertIsNotNone(result)
        payload, verifier = result or ({}, "")
        self.assertEqual(verifier, "review_completion")
        self.assertFalse(payload["verified"])
        self.assertEqual(payload["reason"], "verifier_contract_invalid")

    def test_monitor_session_reports_incomplete_when_verifier_raises_file_error(self) -> None:
        stdout = io.StringIO()
        statuses = [
            {"todos_done": 1, "todos_total": 1, "session_state": "completed"},
            {"active_task": "/tmp/session.txt"},
        ]
        with patch_env(self.project_root), patch("story_automator.commands.tmux.time.sleep"), patch(
            "story_automator.commands.tmux.session_status", side_effect=statuses
        ), patch("story_automator.commands.tmux.run_success_verifier", side_effect=FileNotFoundError("missing.json")), redirect_stdout(stdout):
            code = cmd_monitor_session(["fake-session", "--json", "--workflow", "review", "--story-key", "1.2"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["final_state"], "incomplete")
        self.assertEqual(payload["exit_reason"], "verifier_contract_invalid")
        self.assertFalse(payload["output_verified"])

    def test_monitor_session_timeout_keeps_output_unverified_without_verifier_result(self) -> None:
        stdout = io.StringIO()
        with patch_env(self.project_root), patch(
            "story_automator.commands.tmux.session_status", return_value={"active_task": "/tmp/session.txt"}
        ), redirect_stdout(stdout):
            code = cmd_monitor_session(["fake-session", "--json", "--max-polls", "0"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["final_state"], "timeout")
        self.assertEqual(payload["exit_reason"], "max_polls_exceeded")
        self.assertFalse(payload["output_verified"])

    def test_monitor_session_runtime_agent_uses_resolved_provider_flags(self) -> None:
        calls: list[dict[str, object]] = []

        def fake_session_status(*args: object, **kwargs: object) -> dict[str, object]:
            calls.append({"args": args, **kwargs})
            return {"active_task": "/tmp/session.txt"}

        stdout = io.StringIO()
        with patch_env(self.project_root), patch("story_automator.commands.tmux.runtime_provider", return_value="codex"), patch(
            "story_automator.commands.tmux.session_status", side_effect=fake_session_status
        ), redirect_stdout(stdout):
            code = cmd_monitor_session(["fake-session", "--json", "--max-polls", "0", "--agent", "runtime"])

        self.assertEqual(code, 0)
        self.assertTrue(calls)
        self.assertTrue(calls[0]["codex"])

    def test_monitor_session_infers_claude_from_legacy_ai_command(self) -> None:
        stdout = io.StringIO()
        with patch_env(self.project_root, extra={"AI_COMMAND": "claude --print"}), patch(
            "story_automator.commands.tmux.session_status",
            return_value={"active_task": "/tmp/session.txt", "todos_done": 0, "todos_total": 0, "wait_estimate": 5, "session_state": "not_found"},
        ) as session_status_mock, redirect_stdout(stdout):
            code = cmd_monitor_session(["fake-session", "--json", "--max-polls", "1"])
        self.assertEqual(code, 0)
        self.assertFalse(session_status_mock.call_args.kwargs["codex"])

    def test_monitor_dispatch_allows_session_exit_without_story_key(self) -> None:
        result = _verify_monitor_completion(
            "dev",
            project_root=str(self.project_root),
            story_key="",
            output_file="/tmp/session.txt",
        )
        self.assertIsNotNone(result)
        payload, verifier = result or ({}, "")
        self.assertEqual(verifier, "session_exit")
        self.assertTrue(payload["verified"])

    def test_verify_step_create_uses_shared_verifier(self) -> None:
        self._write_story("1-2-example", status="draft")
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(["verify-step", "create", "1.2"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["verified"])
        self.assertEqual(payload["source"], "artifact_glob")

    def test_verify_step_create_uses_policy_with_resolved_artifacts_dir(self) -> None:
        self._write_bmad_config("implementation_artifacts: docs/bmad/implementation-artifacts\n")
        self._write_docs_story("1-2-docs", status="draft")
        self._write_docs_sprint_status("1-2-docs: done\n")
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(["verify-step", "create", "1.2"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["verified"])
        self.assertEqual(payload["matches"], [str(self.docs_artifacts_dir / "1-2-docs.md")])

    def test_verify_step_create_uses_pinned_snapshot(self) -> None:
        self._write_story("1-2-example", status="draft")
        state_file = self._build_state()
        self._write_override({"steps": {"create": {"success": {"config": {"expectedMatches": 2}}}}})
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(["verify-step", "create", "1.2", "--state-file", str(state_file)])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["verified"])
        self.assertEqual(payload["expectedMatches"], 1)

    def test_verify_step_create_returns_json_on_verification_failure(self) -> None:
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(["verify-step", "create", "1.2"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["verified"])
        self.assertEqual(payload["reason"], "unexpected_story_artifact_count")

    def test_validate_story_creation_check_uses_shared_verifier(self) -> None:
        self._write_story("1-2-example", status="draft")
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_validate_story_creation(["check", "1.2"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["valid"])
        self.assertTrue(payload["verified"])
        self.assertEqual(payload["created_count"], 1)
        self.assertEqual(payload["expected"], 1)

    def test_validate_story_creation_check_uses_policy_with_resolved_artifacts_dir(self) -> None:
        self._write_bmad_config("implementation_artifacts: docs/bmad/implementation-artifacts\n")
        self._write_docs_story("1-2-docs", status="draft")
        self._write_docs_sprint_status("1-2-docs: done\n")
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_validate_story_creation(["check", "1.2"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["valid"])
        self.assertEqual(payload["matches"], [str(self.docs_artifacts_dir / "1-2-docs.md")])

    def test_validate_story_creation_check_uses_pinned_snapshot(self) -> None:
        self._write_story("1-2-example", status="draft")
        state_file = self._build_state()
        self._write_override({"steps": {"create": {"success": {"config": {"expectedMatches": 2}}}}})
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_validate_story_creation(["check", "1.2", "--state-file", str(state_file)])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["valid"])
        self.assertEqual(payload["expected"], 1)

    def test_validate_story_creation_check_uses_before_after_delta(self) -> None:
        self._write_story("1-2-existing", status="draft")
        self._write_story("1-2-new", status="draft")
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_validate_story_creation(["check", "1.2", "--before", "1", "--after", "2"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["valid"])
        self.assertEqual(payload["created_count"], 1)
        self.assertEqual(payload["before"], 1)
        self.assertEqual(payload["after"], 2)

    def test_validate_story_creation_positional_mode_forwards_state_file(self) -> None:
        self._write_story("1-2-example", status="draft")
        state_file = self._build_state()
        self._write_override({"steps": {"create": {"success": {"config": {"expectedMatches": 2}}}}})
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_validate_story_creation(["1.2", "0", "1", "--state-file", str(state_file)])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["valid"])
        self.assertEqual(payload["expected"], 1)
        self.assertEqual(payload["created_count"], 1)

    def test_validate_story_creation_check_returns_compat_schema_on_policy_error(self) -> None:
        self._write_override({"steps": {"create": {"success": {"config": {"expectedMatches": "abc"}}}}})
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_validate_story_creation(["check", "1.2"])
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["valid"])
        self.assertEqual(payload["expected"], 1)
        self.assertEqual(payload["created_count"], 0)
        self.assertEqual(payload["prefix"], "1-2")
        self.assertEqual(payload["source"], "")
        self.assertEqual(payload["pattern"], "")
        self.assertEqual(payload["matches"], [])

    def test_validate_story_creation_check_returns_compat_schema_on_missing_state_file(self) -> None:
        stdout = io.StringIO()
        missing = self.project_root / "missing-state.md"
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_validate_story_creation(["check", "1.2", "--state-file", str(missing)])
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["valid"])
        self.assertIn("missing-state.md", payload["reason"])

    def test_review_wrapper_normalizes_directory_state_file(self) -> None:
        payload = verify_code_review_completion(str(self.project_root), "1.2", state_file=self.project_root)
        self.assertFalse(payload["verified"])
        self.assertEqual(payload["reason"], "review_contract_invalid")
        self.assertIn("state file unreadable", str(payload.get("error")))

    def test_validate_story_creation_check_returns_compat_schema_on_directory_state_file(self) -> None:
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_validate_story_creation(["check", "1.2", "--state-file", str(self.project_root)])
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["valid"])
        self.assertIn("state file unreadable", payload["reason"])

    def test_review_wrapper_honors_empty_injected_contract(self) -> None:
        self._write_story("1-2-example", status="done")
        self._write_override(
            {
                "steps": {
                    "review": {
                        "success": {
                            "config": {"doneValues": ["approved"], "sourceOrder": ["story-file"], "syncSprintStatus": False}
                        }
                    }
                }
            }
        )
        payload = verify_code_review_completion(str(self.project_root), "1.2", success_contract={})
        self.assertTrue(payload["verified"])
        self.assertEqual(payload["source"], "story-file")

    def test_review_wrapper_normalizes_policy_error(self) -> None:
        payload = verify_code_review_completion(
            str(self.project_root),
            "1.2",
            success_contract={"doneValues": [], "sourceOrder": ["story-file"]},
        )
        self.assertFalse(payload["verified"])
        self.assertEqual(payload["reason"], "review_contract_invalid")

    def test_verify_step_rejects_incomplete_state_file_flag(self) -> None:
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(["verify-step", "create", "1.2", "--state-file"])
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["verified"])
        self.assertEqual(payload["reason"], "verifier_contract_invalid")
        self.assertEqual(payload["error"], "--state-file requires a value")

    def test_verify_code_review_rejects_incomplete_state_file_flag(self) -> None:
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(["verify-code-review", "1.2", "--state-file"])
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["verified"])
        self.assertEqual(payload["reason"], "review_contract_invalid")
        self.assertEqual(payload["error"], "--state-file requires a value")

    def test_validate_story_creation_check_returns_compat_schema_on_bad_counts(self) -> None:
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_validate_story_creation(["check", "1.2", "--before", "x", "--after", "1"])
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["valid"])
        self.assertEqual(payload["reason"], "before/after must be integers")
        self.assertEqual(payload["expected"], 1)
        self.assertEqual(payload["created_count"], 0)

    def test_validate_story_creation_check_returns_compat_schema_on_partial_counts(self) -> None:
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_validate_story_creation(["check", "1.2", "--before", "1"])
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["valid"])
        self.assertEqual(payload["reason"], "both --before and --after are required together")
        self.assertEqual(payload["prefix"], "1-2")

    def test_validate_story_creation_check_returns_compat_schema_on_trailing_before_flag(self) -> None:
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_validate_story_creation(["check", "1.2", "--before"])
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["valid"])
        self.assertEqual(payload["reason"], "--before requires a value")

    def test_validate_story_creation_check_returns_compat_schema_on_empty_counts(self) -> None:
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_validate_story_creation(["check", "1.2", "--before", "", "--after", ""])
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["valid"])
        self.assertEqual(payload["reason"], "before/after must be integers")

    def test_validate_story_creation_check_returns_compat_schema_on_unsupported_artifacts_dir(self) -> None:
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_validate_story_creation(["check", "1.2", "--artifacts-dir", str(self.project_root / "tmp")])
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["valid"])
        self.assertIn("no longer supports --artifacts-dir overrides", payload["reason"])

    def test_validate_story_creation_check_rejects_artifacts_dir_in_delta_mode(self) -> None:
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_validate_story_creation(["check", "1.2", "--before", "0", "--after", "1", "--artifacts-dir", str(self.project_root / "tmp")])
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["valid"])
        self.assertIn("no longer supports --artifacts-dir overrides", payload["reason"])
        self.assertEqual(payload["created_count"], 1)
        self.assertEqual(payload["before"], 0)
        self.assertEqual(payload["after"], 1)

    def test_validate_story_creation_positional_mode_rejects_artifacts_dir_with_delta_fields(self) -> None:
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_validate_story_creation(["1.2", "0", "1", "--artifacts-dir", str(self.project_root / "tmp")])
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["valid"])
        self.assertIn("no longer supports --artifacts-dir overrides", payload["reason"])
        self.assertEqual(payload["created_count"], 1)
        self.assertEqual(payload["before"], 0)
        self.assertEqual(payload["after"], 1)

    def test_validate_story_creation_positional_mode_returns_compat_schema_on_bad_counts(self) -> None:
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_validate_story_creation(["1.2", "x", "1"])
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["valid"])
        self.assertEqual(payload["reason"], "before/after must be integers")

    def test_validate_story_creation_positional_mode_returns_compat_schema_on_missing_after(self) -> None:
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_validate_story_creation(["1.2", "0"])
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["valid"])
        self.assertEqual(payload["reason"], "both --before and --after are required together")

    def test_validate_story_creation_positional_mode_returns_compat_schema_on_missing_counts(self) -> None:
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_validate_story_creation(["1.2"])
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["valid"])
        self.assertEqual(payload["reason"], "both --before and --after are required together")

    def test_validate_story_creation_positional_mode_returns_compat_schema_on_extra_token(self) -> None:
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_validate_story_creation(["1.2", "0", "1", "junk"])
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["valid"])
        self.assertEqual(payload["reason"], "unsupported check argument: junk")
        self.assertEqual(payload["created_count"], 1)
        self.assertEqual(payload["before"], 0)
        self.assertEqual(payload["after"], 1)

    def test_validate_story_creation_positional_mode_returns_compat_schema_on_incomplete_state_file(self) -> None:
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_validate_story_creation(["1.2", "0", "1", "--state-file"])
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["valid"])
        self.assertEqual(payload["reason"], "--state-file requires a value")
        self.assertEqual(payload["created_count"], 1)
        self.assertEqual(payload["before"], 0)
        self.assertEqual(payload["after"], 1)

    def test_validate_story_creation_check_preserves_delta_on_incomplete_state_file(self) -> None:
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_validate_story_creation(["check", "1.2", "--before", "0", "--after", "1", "--state-file"])
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["valid"])
        self.assertEqual(payload["reason"], "--state-file requires a value")
        self.assertEqual(payload["created_count"], 1)
        self.assertEqual(payload["before"], 0)
        self.assertEqual(payload["after"], 1)

    def test_validate_story_creation_check_preserves_delta_on_trailing_before_flag(self) -> None:
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_validate_story_creation(["check", "1.2", "--before", "0", "--after", "1", "--before"])
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["valid"])
        self.assertEqual(payload["reason"], "--before requires a value")
        self.assertEqual(payload["created_count"], 1)
        self.assertEqual(payload["before"], 0)
        self.assertEqual(payload["after"], 1)

    def test_validate_story_creation_positional_mode_preserves_delta_on_trailing_before_flag(self) -> None:
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_validate_story_creation(["1.2", "0", "1", "--before"])
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["valid"])
        self.assertEqual(payload["reason"], "--before requires a value")
        self.assertEqual(payload["created_count"], 1)
        self.assertEqual(payload["before"], 0)
        self.assertEqual(payload["after"], 1)

    def test_validate_story_creation_check_returns_compat_failure_without_exception(self) -> None:
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_validate_story_creation(["check", "1.2"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["valid"])
        self.assertEqual(payload["created_count"], 0)
        self.assertEqual(payload["reason"], "No story file created - session may have failed")

    def test_validate_story_creation_positional_mode_returns_delta_failure_without_exception(self) -> None:
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_validate_story_creation(["1.2", "1", "3"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["valid"])
        self.assertEqual(payload["created_count"], 2)
        self.assertEqual(payload["reason"], "RUNAWAY CREATION: 2 files created instead of 1")

    def test_validate_story_creation_check_preserves_zero_expected_matches(self) -> None:
        self._write_override({"steps": {"create": {"success": {"config": {"expectedMatches": 0}}}}})
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_validate_story_creation(["check", "1.2"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["valid"])
        self.assertEqual(payload["expected"], 0)
        self.assertEqual(payload["created_count"], 0)

    def test_create_story_artifact_rejects_invalid_expected_matches(self) -> None:
        with self.assertRaises(PolicyError):
            create_story_artifact(
                project_root=str(self.project_root),
                story_key="1.2",
                contract={"config": {"expectedMatches": "abc"}},
            )

    def test_create_story_artifact_rejects_boolean_expected_matches(self) -> None:
        with self.assertRaises(PolicyError):
            create_story_artifact(
                project_root=str(self.project_root),
                story_key="1.2",
                contract={"config": {"expectedMatches": False}},
            )

    def _build_state(self) -> Path:
        stdout = io.StringIO()
        template = self.project_root / ".claude" / "skills" / "bmad-story-automator" / "templates" / "state-document.md"
        with patch_env(self.project_root), redirect_stdout(stdout):
            cmd_build_state_doc(
                [
                    "--template",
                    str(template),
                    "--output-folder",
                    str(self.output_dir),
                    "--config-json",
                    json.dumps(
                        {
                            "epic": "1",
                            "epicName": "Epic 1",
                            "storyRange": ["1.2"],
                            "status": "READY",
                            "aiCommand": "claude --dangerously-skip-permissions",
                        }
                    ),
                ]
            )
        return Path(json.loads(stdout.getvalue())["path"])

    def _install_bundle(self) -> None:
        source_skill = REPO_ROOT / "skills" / "bmad-story-automator"
        source_review = REPO_ROOT / "skills" / "bmad-story-automator-review"
        target_root = self.project_root / ".claude" / "skills"
        target_root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_skill, target_root / "bmad-story-automator")
        shutil.copytree(source_review, target_root / "bmad-story-automator-review")

    def _install_required_skills(self) -> None:
        self._make_skill(
            "bmad-create-story",
            extras={"discover-inputs.md": "# discover\n", "checklist.md": "# checklist\n", "template.md": "# template\n"},
        )
        self._make_skill("bmad-dev-story", extras={"checklist.md": "# checklist\n"})
        self._make_skill("bmad-retrospective")
        self._make_skill("bmad-qa-generate-e2e-tests", extras={"checklist.md": "# checklist\n"})

    def _make_skill(self, name: str, *, extras: dict[str, str] | None = None) -> None:
        skill_dir = self.project_root / ".claude" / "skills" / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
        (skill_dir / "workflow.md").write_text(f"# {name}\n", encoding="utf-8")
        for rel, content in (extras or {}).items():
            (skill_dir / rel).write_text(content, encoding="utf-8")

    def _write_story(self, stem: str, *, status: str) -> Path:
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        path = self.artifacts_dir / f"{stem}.md"
        path.write_text(f"---\nStatus: {status}\nTitle: Story\n---\n", encoding="utf-8")
        return path

    def _write_docs_story(self, stem: str, *, status: str) -> Path:
        self.docs_artifacts_dir.mkdir(parents=True, exist_ok=True)
        path = self.docs_artifacts_dir / f"{stem}.md"
        path.write_text(f"---\nStatus: {status}\nTitle: Story\n---\n", encoding="utf-8")
        return path

    def _write_sprint_status(self, content: str) -> None:
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        (self.artifacts_dir / "sprint-status.yaml").write_text(content, encoding="utf-8")

    def _write_docs_sprint_status(self, content: str) -> None:
        self.docs_artifacts_dir.mkdir(parents=True, exist_ok=True)
        (self.docs_artifacts_dir / "sprint-status.yaml").write_text(content, encoding="utf-8")

    def _write_bmad_config(self, content: str) -> None:
        config_dir = self.project_root / "_bmad" / "bmm"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "config.yaml").write_text(content, encoding="utf-8")

    def _write_review_contract(self, payload: dict[str, object]) -> Path:
        path = self.project_root / "review-contract.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def _write_override(self, payload: dict[str, object]) -> None:
        override_dir = self.project_root / "_bmad" / "bmm"
        override_dir.mkdir(parents=True, exist_ok=True)
        (override_dir / "story-automator.policy.json").write_text(json.dumps(payload), encoding="utf-8")


class patch_env:
    def __init__(self, project_root: Path, extra: dict[str, str] | None = None) -> None:
        self.project_root = str(project_root)
        self.extra = extra or {}
        self.previous: dict[str, str | None] = {}

    def __enter__(self) -> None:
        import os

        self.previous["PROJECT_ROOT"] = os.environ.get("PROJECT_ROOT")
        os.environ["PROJECT_ROOT"] = self.project_root
        for key, value in self.extra.items():
            self.previous[key] = os.environ.get(key)
            os.environ[key] = value

    def __exit__(self, *_: object) -> None:
        import os

        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
