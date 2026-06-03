from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from story_automator.commands.orchestrator import cmd_orchestrator_helper
from story_automator.commands.state import cmd_sprint_compare
from story_automator.commands.tmux import _build_cmd, _render_step_prompt
from story_automator.commands.validate_story_creation import cmd_validate_story_creation
from story_automator.core.artifact_paths import implementation_artifacts_relpath
from story_automator.core.runtime_policy import PolicyError
from story_automator.core.sprint import sprint_status_get
from story_automator.core.story_keys import normalize_story_key, sprint_status_file
from story_automator.core.success_verifiers import create_story_artifact, epic_complete, review_completion
from tests.success_verifier_case import SuccessVerifierCase, patch_env


class ArtifactPathTests(SuccessVerifierCase):
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

    def test_config_artifacts_relpath_is_canonical(self) -> None:
        self._write_bmad_config("implementation_artifacts: docs/../docs/bmad/implementation-artifacts\n")
        self.assertEqual(implementation_artifacts_relpath(self.project_root), "docs/bmad/implementation-artifacts")

    def test_config_ignores_nested_output_folder(self) -> None:
        self._write_bmad_config("output_folder: docs/bmad\nagentConfig:\n  output_folder: bad\n")
        self._write_docs_story("1-2-docs", status="draft")

        payload = create_story_artifact(project_root=str(self.project_root), story_key="1.2", contract={})

        self.assertTrue(payload["verified"])
        self.assertEqual(payload["matches"], [str(self.docs_artifacts_dir / "1-2-docs.md")])

    def test_config_ignores_nested_implementation_artifacts(self) -> None:
        self._write_bmad_config("output_folder: docs/bmad\nagentConfig:\n  implementation_artifacts: bad/nested-artifacts\n")
        self._write_docs_story("1-2-docs", status="draft")

        payload = create_story_artifact(project_root=str(self.project_root), story_key="1.2", contract={})

        self.assertTrue(payload["verified"])
        self.assertEqual(payload["matches"], [str(self.docs_artifacts_dir / "1-2-docs.md")])

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

    def test_configured_sprint_status_does_not_fallback_to_legacy_root(self) -> None:
        self._write_bmad_config("implementation_artifacts: docs/bmad/implementation-artifacts\n")
        self._write_docs_story("1-2-docs", status="review")
        legacy = self.project_root / "_bmad-output" / "sprint-status.yaml"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text("1-2-docs: done\n", encoding="utf-8")

        self.assertEqual(Path(sprint_status_file(str(self.project_root))), self.docs_artifacts_dir / "sprint-status.yaml")
        payload = review_completion(
            project_root=str(self.project_root),
            story_key="1.2",
            contract={"doneValues": ["done"], "sourceOrder": ["sprint-status.yaml", "story-file"], "syncSprintStatus": False},
        )

        self.assertFalse(payload["verified"])
        self.assertEqual(payload["story_file_status"], "review")
        self.assertEqual(payload["sprint_status"], "unknown")

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

    def test_story_file_status_rejects_missing_explicit_full_key_sibling(self) -> None:
        self._write_story("multi-leg-3-aaa", status="done")

        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(["story-file-status", "multi-leg-3-zzz"])

        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "story file not found")
        self.assertEqual(payload["prefix"], "multi-leg-3")

    def test_story_file_status_returns_json_error_for_invalid_artifacts_config(self) -> None:
        self._write_bmad_config("implementation_artifacts: ../outside/implementation-artifacts\n")
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(["story-file-status", "1.2"])
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["ok"])
        self.assertIn("BMAD config implementation_artifacts", payload["error"])

    def test_story_file_status_returns_json_error_for_unreadable_artifacts_config(self) -> None:
        self._write_bmad_config("implementation_artifacts: docs/bmad/implementation-artifacts\n")
        stdout = io.StringIO()
        with patch("story_automator.core.artifact_paths.read_text", side_effect=PermissionError("config unreadable")):
            with patch_env(self.project_root), redirect_stdout(stdout):
                code = cmd_orchestrator_helper(["story-file-status", "1.2"])
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["ok"])
        self.assertIn("config unreadable", payload["error"])

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

    def test_validate_story_creation_handles_unreadable_artifacts_config(self) -> None:
        self._write_bmad_config("implementation_artifacts: docs/bmad/implementation-artifacts\n")
        with patch("story_automator.core.artifact_paths.read_text", side_effect=PermissionError("config unreadable")):
            stderr = io.StringIO()
            with patch_env(self.project_root), redirect_stderr(stderr):
                count_code = cmd_validate_story_creation(["count", "1.2"])
            self.assertEqual(count_code, 1)
            self.assertIn("config unreadable", stderr.getvalue())

            stdout = io.StringIO()
            with patch_env(self.project_root), redirect_stdout(stdout):
                check_code = cmd_validate_story_creation(["check", "1.2"])
            self.assertEqual(check_code, 1)
            check_payload = json.loads(stdout.getvalue())
            self.assertFalse(check_payload["valid"])
            self.assertIn("config unreadable", check_payload["reason"])

            stderr = io.StringIO()
            with patch_env(self.project_root), redirect_stderr(stderr):
                list_code = cmd_validate_story_creation(["list", "1.2"])
            self.assertEqual(list_code, 1)
            self.assertIn("config unreadable", stderr.getvalue())

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

    def test_monitoring_fallback_resolves_story_file_from_helper(self) -> None:
        fallback = (self.project_root / ".claude" / "skills" / "bmad-story-automator" / "data" / "monitoring-fallback.md").read_text(encoding="utf-8")
        self.assertIn('if story_status=$("$scripts" orchestrator-helper story-file-status "{story_key}"); then', fallback)
        self.assertIn('orchestrator-helper story-file-status "{story_key}"', fallback)
        self.assertIn("jq -er 'select(.ok == true) | .file'", fallback)
        self.assertIn('if status=$("$scripts" orchestrator-helper sprint-status get "{story_key}"); then', fallback)
        self.assertIn("is_done=false", fallback)
        self.assertIn('story_file=""', fallback)
        self.assertNotIn('dirname "$implementation_artifacts_path"', fallback)
        self.assertNotIn('find "$implementation_artifacts_dir"', fallback)
        self.assertNotIn("{{implementation_artifacts}}", fallback)
        self.assertNotIn("ls {{implementation_artifacts}}/{story_prefix}-*.md", fallback)
        self.assertNotIn("ls _bmad-output/implementation-artifacts/{story_prefix}-*.md", fallback)

    def test_resume_step_resolves_sprint_status_path_from_helper(self) -> None:
        step = (self.project_root / ".claude" / "skills" / "bmad-story-automator" / "steps-c" / "step-01b-continue.md").read_text(encoding="utf-8")
        self.assertIn('defaultSprintStatusFile: ""', step)
        self.assertIn('orchestrator-helper sprint-status path', step)
        self.assertIn("jq -er 'select(.ok == true) | .path'", step)
        self.assertIn("exit 1", step)
        self.assertNotIn("  HALT", step)
        self.assertIn('--sprint "$defaultSprintStatusFile"', step)
        self.assertNotIn("{implementation_artifacts}/sprint-status.yaml", step)
        self.assertNotIn('defaultSprintStatusFile: "{output_folder}/implementation-artifacts/sprint-status.yaml"', step)

    def test_sprint_status_helpers_return_json_error_for_invalid_artifacts_config(self) -> None:
        self._write_bmad_config("implementation_artifacts: ../outside/implementation-artifacts\n")
        for args in (["sprint-status", "path"], ["sprint-status", "get", "1.2"], ["sprint-status", "exists"], ["sprint-status", "check-epic", "1"]):
            with self.subTest(args=args):
                stdout = io.StringIO()
                with patch_env(self.project_root), redirect_stdout(stdout):
                    code = cmd_orchestrator_helper(args)
                self.assertEqual(code, 1)
                payload = json.loads(stdout.getvalue())
                self.assertFalse(payload["ok"])
                self.assertIn("BMAD config implementation_artifacts", payload["error"])

    def test_commit_ready_returns_json_error_for_invalid_artifacts_config(self) -> None:
        self._write_bmad_config("implementation_artifacts: ../outside/implementation-artifacts\n")
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(["commit-ready", "1.2"])
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["ready"])
        self.assertEqual(payload["story"], "1.2")
        self.assertIn("BMAD config implementation_artifacts", payload["reason"])

    def test_normalize_key_returns_json_error_for_invalid_artifacts_config(self) -> None:
        self._write_bmad_config("implementation_artifacts: ../outside/implementation-artifacts\n")
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(["normalize-key", "1.2"])
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["input"], "1.2")
        self.assertIn("BMAD config implementation_artifacts", payload["error"])

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

    def test_check_blocking_returns_json_error_for_invalid_artifacts_config(self) -> None:
        self._write_bmad_config("implementation_artifacts: ../outside/implementation-artifacts\n")
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(["check-blocking", "1.1"])
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["ok"])
        self.assertIn("BMAD config implementation_artifacts", payload["error"])

    def test_get_epic_stories_returns_json_error_for_invalid_artifacts_config(self) -> None:
        self._write_bmad_config("implementation_artifacts: ../outside/implementation-artifacts\n")
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(["get-epic-stories", "1"])
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["ok"])
        self.assertIn("BMAD config implementation_artifacts", payload["error"])

    def test_build_cmd_returns_controlled_error_for_invalid_artifacts_config(self) -> None:
        self._write_bmad_config("implementation_artifacts: ../outside/implementation-artifacts\n")
        stderr = io.StringIO()
        with patch_env(self.project_root), redirect_stderr(stderr):
            code = _build_cmd(["review", "1.2"])
        self.assertEqual(code, 1)
        self.assertIn("BMAD config implementation_artifacts", stderr.getvalue())
