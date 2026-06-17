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
            run_lifecycle_verifier(
                "bogus_verifier_name", node=node, project_root="/tmp"
            )


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
        result = run_lifecycle_verifier(
            "artifact_exists", node=node, project_root=str(self.root)
        )
        self.assertTrue(result["verified"])
        self.assertEqual(result["path"], "docs/brief.md")

    def test_file_missing_fails(self) -> None:
        from story_automator.core.lifecycle_verifiers import run_lifecycle_verifier

        node = _make_node(
            node_id="B1-brief",
            verifier="artifact_exists",
            output_artifact="docs/missing.md",
        )
        result = run_lifecycle_verifier(
            "artifact_exists", node=node, project_root=str(self.root)
        )
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
        result = run_lifecycle_verifier(
            "artifact_exists", node=node, project_root=str(self.root)
        )
        self.assertTrue(result["verified"])

    def test_empty_directory_fails(self) -> None:
        from story_automator.core.lifecycle_verifiers import run_lifecycle_verifier

        (self.root / "epics").mkdir()
        node = _make_node(
            node_id="B3-epics",
            verifier="artifact_exists",
            output_artifact="epics/",
        )
        result = run_lifecycle_verifier(
            "artifact_exists", node=node, project_root=str(self.root)
        )
        self.assertFalse(result["verified"])
        self.assertEqual(result["reason"], "artifact_empty")


if __name__ == "__main__":
    unittest.main()
