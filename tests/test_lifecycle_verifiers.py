from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


def _make_node(*, node_id: str, verifier: str, output_artifact: str, **overrides):
    from story_automator.core.lifecycle_policy import NodeDef

    defaults = dict(
        id=node_id,
        track="bmm",
        phase=1,
        skill="bmad-x",
        validator_skill=None,
        deps=[],
        input_artifacts=[],
        output_artifact=output_artifact,
        verifier=verifier,
        gate="auto",
        modes=["greenfield"],
        agent_role="analyst",
        interactive=False,
    )
    defaults.update(overrides)
    return NodeDef(**defaults)


class LifecycleVerifiersModuleTests(unittest.TestCase):
    def test_module_imports(self) -> None:
        from story_automator.core import lifecycle_verifiers  # noqa: F401

    def test_exposes_verifier_error(self) -> None:
        from story_automator.core.lifecycle_verifiers import VerifierError

        self.assertTrue(issubclass(VerifierError, ValueError))

    def test_exposes_registry(self) -> None:
        from story_automator.core.lifecycle_verifiers import LIFECYCLE_VERIFIERS

        self.assertIsInstance(LIFECYCLE_VERIFIERS, dict)
        self.assertIn("artifact_exists", LIFECYCLE_VERIFIERS)

    def test_unknown_verifier_raises(self) -> None:
        from story_automator.core.lifecycle_verifiers import (
            VerifierError,
            run_lifecycle_verifier,
        )

        node = _make_node(
            node_id="N",
            verifier="bogus_verifier_name",
            output_artifact="docs/x.md",
        )
        with self.assertRaises(VerifierError):
            run_lifecycle_verifier("bogus_verifier_name", node=node, project_root="/tmp")


class ArtifactExistsVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_file_present_passes(self) -> None:
        from story_automator.core.lifecycle_verifiers import run_lifecycle_verifier

        artifact = self.root / "docs" / "brief.md"
        artifact.parent.mkdir(parents=True)
        artifact.write_text("# Brief\n", encoding="utf-8")
        node = _make_node(
            node_id="B1-brief",
            verifier="artifact_exists",
            output_artifact="docs/brief.md",
        )
        result = run_lifecycle_verifier("artifact_exists", node=node, project_root=str(self.root))
        self.assertTrue(result["verified"])
        self.assertEqual(result["path"], "docs/brief.md")

    def test_file_missing_fails(self) -> None:
        from story_automator.core.lifecycle_verifiers import run_lifecycle_verifier

        node = _make_node(
            node_id="B1-brief",
            verifier="artifact_exists",
            output_artifact="docs/missing.md",
        )
        result = run_lifecycle_verifier("artifact_exists", node=node, project_root=str(self.root))
        self.assertFalse(result["verified"])
        self.assertEqual(result["reason"], "artifact_missing")

    def test_directory_artifact_passes_when_non_empty(self) -> None:
        from story_automator.core.lifecycle_verifiers import run_lifecycle_verifier

        epics = self.root / "epics"
        epics.mkdir()
        (epics / "epic-1.md").write_text("# Epic 1\n", encoding="utf-8")
        node = _make_node(
            node_id="B3-epics",
            verifier="artifact_exists",
            output_artifact="epics/",
        )
        result = run_lifecycle_verifier("artifact_exists", node=node, project_root=str(self.root))
        self.assertTrue(result["verified"])

    def test_empty_directory_fails(self) -> None:
        from story_automator.core.lifecycle_verifiers import run_lifecycle_verifier

        (self.root / "epics").mkdir()
        node = _make_node(
            node_id="B3-epics",
            verifier="artifact_exists",
            output_artifact="epics/",
        )
        result = run_lifecycle_verifier("artifact_exists", node=node, project_root=str(self.root))
        self.assertFalse(result["verified"])
        self.assertEqual(result["reason"], "artifact_empty")


class StructuralCompleteVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_well_formed_md_passes(self) -> None:
        from story_automator.core.lifecycle_verifiers import run_lifecycle_verifier

        artifact = self.root / "docs" / "prd.md"
        artifact.parent.mkdir(parents=True)
        artifact.write_text(
            '---\ntitle: "PRD"\nstatus: complete\n---\n# PRD\n',
            encoding="utf-8",
        )
        node = _make_node(
            node_id="B2-prd",
            verifier="structural_complete",
            output_artifact="docs/prd.md",
        )
        result = run_lifecycle_verifier(
            "structural_complete", node=node, project_root=str(self.root)
        )
        self.assertTrue(result["verified"])

    def test_missing_artifact_fails(self) -> None:
        from story_automator.core.lifecycle_verifiers import run_lifecycle_verifier

        node = _make_node(
            node_id="B2-prd",
            verifier="structural_complete",
            output_artifact="docs/missing.md",
        )
        result = run_lifecycle_verifier(
            "structural_complete", node=node, project_root=str(self.root)
        )
        self.assertFalse(result["verified"])
        self.assertEqual(result["reason"], "artifact_missing")

    def test_no_frontmatter_fails_for_md(self) -> None:
        from story_automator.core.lifecycle_verifiers import run_lifecycle_verifier

        artifact = self.root / "docs" / "prd.md"
        artifact.parent.mkdir(parents=True)
        artifact.write_text("# PRD\nno frontmatter here\n", encoding="utf-8")
        node = _make_node(
            node_id="B2-prd",
            verifier="structural_complete",
            output_artifact="docs/prd.md",
        )
        result = run_lifecycle_verifier(
            "structural_complete", node=node, project_root=str(self.root)
        )
        self.assertFalse(result["verified"])
        self.assertEqual(result["reason"], "frontmatter_missing")

    def test_directory_artifact_passes_when_non_empty(self) -> None:
        from story_automator.core.lifecycle_verifiers import run_lifecycle_verifier

        epics = self.root / "epics"
        epics.mkdir()
        (epics / "epic-1.md").write_text("# Epic 1\n", encoding="utf-8")
        node = _make_node(
            node_id="B3-epics",
            verifier="structural_complete",
            output_artifact="epics/",
        )
        result = run_lifecycle_verifier(
            "structural_complete", node=node, project_root=str(self.root)
        )
        self.assertTrue(result["verified"])

    def test_non_md_file_passes_on_existence_only(self) -> None:
        from story_automator.core.lifecycle_verifiers import run_lifecycle_verifier

        artifact = self.root / "build" / "release.tar.gz"
        artifact.parent.mkdir(parents=True)
        artifact.write_bytes(b"\x1f\x8b\x08\x00not-actually-gzip")
        node = _make_node(
            node_id="release",
            verifier="structural_complete",
            output_artifact="build/release.tar.gz",
        )
        result = run_lifecycle_verifier(
            "structural_complete", node=node, project_root=str(self.root)
        )
        self.assertTrue(result["verified"])


class ValidatorSkillVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_calls_injected_dispatch_when_validator_skill_set(self) -> None:
        from story_automator.core.lifecycle_verifiers import run_lifecycle_verifier

        artifact = self.root / "docs" / "prd.md"
        artifact.parent.mkdir(parents=True)
        artifact.write_text("---\nstatus: complete\n---\n# PRD\n", encoding="utf-8")

        calls: list = []

        def stub_dispatch(*, validator_skill: str, node, project_root):
            calls.append((validator_skill, node.id, project_root))
            return {"verified": True, "validator": validator_skill}

        node = _make_node(
            node_id="B2-prd",
            verifier="validator_skill",
            output_artifact="docs/prd.md",
            validator_skill="bmad-validate-prd",
        )
        result = run_lifecycle_verifier(
            "validator_skill",
            node=node,
            project_root=str(self.root),
            validator_dispatch=stub_dispatch,
        )
        self.assertTrue(result["verified"])
        self.assertEqual(result["validator"], "bmad-validate-prd")
        self.assertEqual(calls, [("bmad-validate-prd", "B2-prd", str(self.root))])

    def test_missing_validator_skill_field_fails(self) -> None:
        from story_automator.core.lifecycle_verifiers import run_lifecycle_verifier

        node = _make_node(
            node_id="B2-prd",
            verifier="validator_skill",
            output_artifact="docs/prd.md",
            validator_skill=None,
        )
        result = run_lifecycle_verifier(
            "validator_skill",
            node=node,
            project_root=str(self.root),
            validator_dispatch=lambda **_: {"verified": True},
        )
        self.assertFalse(result["verified"])
        self.assertEqual(result["reason"], "validator_skill_not_configured")

    def test_dispatch_callable_required(self) -> None:
        from story_automator.core.lifecycle_verifiers import (
            VerifierError,
            run_lifecycle_verifier,
        )

        node = _make_node(
            node_id="B2-prd",
            verifier="validator_skill",
            output_artifact="docs/prd.md",
            validator_skill="bmad-validate-prd",
        )
        with self.assertRaises(VerifierError):
            run_lifecycle_verifier("validator_skill", node=node, project_root=str(self.root))

    def test_dispatch_returning_verified_false_propagates(self) -> None:
        from story_automator.core.lifecycle_verifiers import run_lifecycle_verifier

        def reject_dispatch(*, validator_skill, node, project_root):
            return {"verified": False, "reason": "validator_said_no"}

        node = _make_node(
            node_id="B2-prd",
            verifier="validator_skill",
            output_artifact="docs/prd.md",
            validator_skill="bmad-validate-prd",
        )
        result = run_lifecycle_verifier(
            "validator_skill",
            node=node,
            project_root=str(self.root),
            validator_dispatch=reject_dispatch,
        )
        self.assertFalse(result["verified"])
        self.assertEqual(result["reason"], "validator_said_no")


if __name__ == "__main__":
    unittest.main()
