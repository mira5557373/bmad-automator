"""Tests for gate_remediation: [AI-Review] tasks, edit-authorization, BMAD-native writes."""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from story_automator.core.gate_remediation import (
    EDITABLE_SECTIONS,
    EditAuthorizationError,
    prepare_remediation_tasks,
    request_review_continuation,
    validate_edit_authorization,
    write_remediation_to_story,
)
from story_automator.core.gate_schema import make_gate_file


def _gate_with_failures(failing: dict[str, str], overall: str = "FAIL") -> dict:
    cats = {}
    for cat, verdict in failing.items():
        cats[cat] = {
            "verdict": verdict,
            "required": {"coverage_pct": 80},
            "actual": {"coverage_pct": 40},
            "evidence": [],
            "rationale": f"{cat} failed",
        }
    return make_gate_file(
        gate_id="gate-rem-1",
        target={"kind": "story", "id": "s1"},
        commit_sha="abc123",
        profile={"id": "test", "version": 1, "hash": "aabb"},
        factory_version="1.15.0",
        categories=cats,
        overall=overall,
    )


class EditableSectionsTests(unittest.TestCase):
    def test_required_sections_present(self) -> None:
        for section in (
            "Tasks", "Subtasks", "Dev Agent Record",
            "File List", "Change Log", "Status",
        ):
            self.assertIn(section, EDITABLE_SECTIONS)

    def test_baseline_commit_editable(self) -> None:
        self.assertIn("baseline_commit", EDITABLE_SECTIONS)

    def test_disallowed_sections_absent(self) -> None:
        for section in ("Acceptance Criteria", "Architecture", "Requirements", "Risk"):
            self.assertNotIn(section, EDITABLE_SECTIONS)


class ValidateEditAuthorizationTests(unittest.TestCase):
    def test_allowed_sections_pass(self) -> None:
        validate_edit_authorization({"Tasks", "Status"})

    def test_disallowed_section_raises(self) -> None:
        with self.assertRaises(EditAuthorizationError) as ctx:
            validate_edit_authorization({"Tasks", "Architecture"})
        self.assertIn("Architecture", str(ctx.exception))

    def test_empty_set_passes(self) -> None:
        validate_edit_authorization(set())


class PrepareRemediationTasksTests(unittest.TestCase):
    def test_creates_tasks_for_failing_categories(self) -> None:
        gate = _gate_with_failures({
            "correctness": "FAIL",
            "security": "FAIL",
            "static": "PASS",
        })
        tasks = prepare_remediation_tasks(gate)
        task_cats = {t["category"] for t in tasks}
        self.assertIn("correctness", task_cats)
        self.assertIn("security", task_cats)
        self.assertNotIn("static", task_cats)

    def test_tasks_have_ai_review_tag(self) -> None:
        gate = _gate_with_failures({"correctness": "FAIL"})
        tasks = prepare_remediation_tasks(gate)
        self.assertTrue(len(tasks) >= 1)
        for task in tasks:
            self.assertIn("[AI-Review]", task["title"])

    def test_tasks_include_gate_id(self) -> None:
        gate = _gate_with_failures({"correctness": "FAIL"})
        tasks = prepare_remediation_tasks(gate)
        self.assertEqual(tasks[0]["gate_id"], "gate-rem-1")

    def test_tasks_include_rationale(self) -> None:
        gate = _gate_with_failures({"correctness": "FAIL"})
        tasks = prepare_remediation_tasks(gate)
        self.assertTrue(tasks[0]["rationale"])

    def test_no_tasks_when_no_failures(self) -> None:
        gate = _gate_with_failures({"correctness": "PASS"}, overall="PASS")
        tasks = prepare_remediation_tasks(gate)
        self.assertEqual(tasks, [])


class WriteRemediationToStoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.story_path = Path(self.tmpdir) / "E1-001.md"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_story(self, content: str) -> None:
        self.story_path.write_text(content, encoding="utf-8")

    def test_appends_tasks_to_tasks_section(self) -> None:
        self._write_story(
            "---\nStatus: in-progress\n---\n\n"
            "## Tasks\n- [ ] Existing task\n\n## Architecture\nDo not touch.\n"
        )
        tasks = [
            {"title": "[AI-Review] Fix correctness: coverage below threshold",
             "category": "correctness", "gate_id": "g1", "rationale": "cov 40<80"},
        ]
        write_remediation_to_story(self.story_path, tasks)
        content = self.story_path.read_text(encoding="utf-8")
        self.assertIn("[AI-Review] Fix correctness", content)
        self.assertIn("- [ ] Existing task", content)
        self.assertIn("Do not touch.", content)

    def test_creates_tasks_section_if_absent(self) -> None:
        self._write_story(
            "---\nStatus: in-progress\n---\n\n## Architecture\nStuff.\n"
        )
        tasks = [
            {"title": "[AI-Review] Fix security: SAST findings",
             "category": "security", "gate_id": "g1", "rationale": "sast high"},
        ]
        write_remediation_to_story(self.story_path, tasks)
        content = self.story_path.read_text(encoding="utf-8")
        self.assertIn("## Tasks", content)
        self.assertIn("[AI-Review] Fix security", content)

    def test_does_not_modify_disallowed_sections(self) -> None:
        original = (
            "---\nStatus: in-progress\n---\n\n"
            "## Architecture\nOriginal architecture.\n\n"
            "## Tasks\n- [ ] Existing\n"
        )
        self._write_story(original)
        tasks = [
            {"title": "[AI-Review] Fix correctness",
             "category": "correctness", "gate_id": "g1", "rationale": "r"},
        ]
        write_remediation_to_story(self.story_path, tasks)
        content = self.story_path.read_text(encoding="utf-8")
        self.assertIn("Original architecture.", content)

    def test_handles_frontmatter_only_file(self) -> None:
        self._write_story("---\nStatus: in-progress\n---\n")
        tasks = [
            {"title": "[AI-Review] Fix correctness",
             "category": "correctness", "gate_id": "g1", "rationale": "r"},
        ]
        write_remediation_to_story(self.story_path, tasks)
        content = self.story_path.read_text(encoding="utf-8")
        self.assertIn("## Tasks", content)
        self.assertIn("[AI-Review] Fix correctness", content)

    def test_noop_on_empty_tasks(self) -> None:
        original = "---\nStatus: done\n---\n\n## Tasks\n- [x] Done\n"
        self._write_story(original)
        write_remediation_to_story(self.story_path, [])
        content = self.story_path.read_text(encoding="utf-8")
        self.assertEqual(content, original)


class RequestReviewContinuationTests(unittest.TestCase):
    def test_returns_descriptor(self) -> None:
        desc = request_review_continuation(
            story_key="E1-001",
            gate_id="gate-1",
            cycle=2,
            failing_categories=["correctness", "security"],
        )
        self.assertEqual(desc["story_key"], "E1-001")
        self.assertEqual(desc["gate_id"], "gate-1")
        self.assertEqual(desc["cycle"], 2)
        self.assertEqual(desc["action"], "review_continuation")
        self.assertIn("correctness", desc["failing_categories"])

    def test_descriptor_includes_trigger(self) -> None:
        desc = request_review_continuation(
            story_key="E1-001",
            gate_id="gate-1",
            cycle=1,
            failing_categories=["static"],
        )
        self.assertEqual(desc["trigger"], "gate-fail")


class RouteVerdictRemediationIntegrationTests(unittest.TestCase):
    """Verify route_gate_verdict returns remediation details on FAIL."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_remediate_includes_failing_categories(self) -> None:
        from story_automator.core.gate_orchestrator import route_gate_verdict
        gate = _gate_with_failures({
            "correctness": "FAIL",
            "security": "PASS",
        })
        gate["overall"] = "FAIL"
        result = route_gate_verdict(
            self.tmpdir, gate,
            story_key="E1-001", remediation_cycle=0, max_cycles=3,
        )
        self.assertEqual(result["action"], "remediate")
        self.assertIn("failing_categories", result)
        self.assertIn("correctness", result["failing_categories"])
        self.assertNotIn("security", result["failing_categories"])

    def test_remediate_includes_remediation_tasks(self) -> None:
        from story_automator.core.gate_orchestrator import route_gate_verdict
        gate = _gate_with_failures({"correctness": "FAIL"})
        gate["overall"] = "FAIL"
        result = route_gate_verdict(
            self.tmpdir, gate,
            story_key="E1-001", remediation_cycle=0, max_cycles=3,
        )
        self.assertEqual(result["action"], "remediate")
        self.assertIn("remediation_tasks", result)
        self.assertTrue(len(result["remediation_tasks"]) >= 1)
        self.assertIn("[AI-Review]", result["remediation_tasks"][0]["title"])

    def test_unknown_verdict_treated_as_fail(self) -> None:
        from story_automator.core.gate_orchestrator import route_gate_verdict
        gate = _gate_with_failures({"correctness": "FAIL"})
        gate["overall"] = "ERROR"
        result = route_gate_verdict(
            self.tmpdir, gate,
            story_key="E1-001", remediation_cycle=0, max_cycles=3,
        )
        self.assertIn(result["action"], ("remediate", "park"))

    def test_remediate_includes_review_continuation(self) -> None:
        from story_automator.core.gate_orchestrator import route_gate_verdict
        gate = _gate_with_failures({"correctness": "FAIL"})
        gate["overall"] = "FAIL"
        result = route_gate_verdict(
            self.tmpdir, gate,
            story_key="E1-001", remediation_cycle=1, max_cycles=3,
        )
        self.assertIn("review_continuation", result)
        self.assertEqual(result["review_continuation"]["action"], "review_continuation")
        self.assertEqual(result["review_continuation"]["cycle"], 2)


class CLISanitizationTests(unittest.TestCase):
    """Verify CLI rejects path-traversal inputs."""

    def test_resume_rejects_traversal(self) -> None:
        from io import StringIO
        from unittest.mock import patch
        from story_automator.commands.gate_cmd import gate_dispatch
        with patch("story_automator.commands.gate_cmd._project_root", return_value=self.tmpdir):
            with patch("sys.stdout", new_callable=StringIO) as out:
                code = gate_dispatch(["resume", "../../etc/passwd"])
        self.assertEqual(code, 1)
        import json
        result = json.loads(out.getvalue())
        self.assertFalse(result["ok"])

    def test_invalidate_rejects_traversal(self) -> None:
        from io import StringIO
        from unittest.mock import patch
        from story_automator.commands.gate_cmd import gate_dispatch
        with patch("story_automator.commands.gate_cmd._project_root", return_value=self.tmpdir):
            with patch("sys.stdout", new_callable=StringIO) as out:
                code = gate_dispatch(["invalidate", "../../../tmp"])
        self.assertEqual(code, 1)
        import json
        result = json.loads(out.getvalue())
        self.assertFalse(result["ok"])

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
