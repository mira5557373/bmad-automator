"""Tests for ``run_production_gate(enable_lie_detector=True)`` wiring (Phase 1).

The default-off flag preserves existing call sites. These tests pin:
 - default-off: the lie detector does NOT run unless explicitly enabled
 - on + HEAD matches commit_sha: gate proceeds normally
 - on + HEAD at baseline: short-circuits with ``action="baseline_drift"``
   and a ``VerifyOutcome.retry`` wire form, fixable=True
 - on + HEAD elsewhere: short-circuits with ``action="baseline_drift"``
   and ``reason="unexpected_head"``, fixable=False
 - on + short-circuit: no gate-in-progress marker is left behind, no
   evaluate_gate side effects
"""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from story_automator.core.collector_registry import CollectorRegistry
from story_automator.core.evidence_io import persist_evidence_record
from story_automator.core.gate_orchestrator import run_production_gate
from story_automator.core.gate_schema import make_evidence_record


def _init_repo(path: Path) -> str:
    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "t@t.com"],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "T"],
        capture_output=True, check=True,
    )
    (path / "a").write_text("1\n")
    subprocess.run(
        ["git", "-C", str(path), "add", "."], capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", "init"],
        capture_output=True, check=True,
    )
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def _minimal_profile() -> dict:
    return {
        "version": 1, "id": "test",
        "matrix": {
            "P0": {"coverage_pct": 80, "levels": ["unit"]},
            "P1": {"coverage_pct": 60, "levels": ["unit"]},
            "P2": {"coverage_pct": 40, "levels": ["unit"]},
            "P3": {"coverage_pct": 20, "levels": ["unit"]},
        },
        "categories": {"code": ["correctness"], "system": []},
    }


def _persist_ok_evidence(project_root: Path, gate_id: str) -> None:
    record = make_evidence_record(
        collector="c", tool="t", category="correctness",
        status="ok", metrics={"coverage_pct": 95, "regressions": 0},
    )
    persist_evidence_record(project_root, gate_id, record)


class OrchestratorLieDetectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="sa-orch-lie-")
        self.project_root = Path(self.tmpdir) / "project"
        self.project_root.mkdir()
        self.baseline = _init_repo(self.project_root)
        self.registry = CollectorRegistry()
        self.profile = _minimal_profile()

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_default_off_does_not_engage(self, mock_run: object) -> None:
        # No commit happened; HEAD == baseline; expected_sha is a lie.
        # With the flag OFF (default), the gate proceeds to evaluate and
        # returns a normal gate file.
        _persist_ok_evidence(self.project_root, "gate-noflag")
        mock_run.return_value = []  # type: ignore[attr-defined]
        gate = run_production_gate(
            self.project_root, "gate-noflag",
            commit_sha="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
            target={"kind": "story", "id": "s1"},
            profile=self.profile, factory_version="1.15.0",
            registry=self.registry,
            # enable_lie_detector defaults False
        )
        self.assertIn("overall", gate)
        self.assertEqual(gate.get("overall"), "PASS")

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_enabled_and_head_matches_proceeds(self, mock_run: object) -> None:
        _persist_ok_evidence(self.project_root, "gate-match")
        mock_run.return_value = []  # type: ignore[attr-defined]
        gate = run_production_gate(
            self.project_root, "gate-match",
            commit_sha=self.baseline,
            target={"kind": "story", "id": "s1"},
            profile=self.profile, factory_version="1.15.0",
            registry=self.registry,
            enable_lie_detector=True,
            baseline_sha=self.baseline,
        )
        self.assertEqual(gate.get("overall"), "PASS")

    def test_enabled_and_head_at_baseline_when_commit_expected(self) -> None:
        result = run_production_gate(
            self.project_root, "gate-drift",
            commit_sha="cafef00d" * 5,  # not equal to HEAD/baseline
            target={"kind": "story", "id": "s1"},
            profile=self.profile, factory_version="1.15.0",
            registry=self.registry,
            enable_lie_detector=True,
            baseline_sha=self.baseline,
        )
        self.assertEqual(result["action"], "baseline_drift")
        self.assertEqual(result["gate_id"], "gate-drift")
        verify = result["verify"]
        self.assertFalse(verify["ok"])
        self.assertEqual(verify["reason"], "baseline_drift")
        self.assertTrue(verify["fixable"])
        # No marker should remain
        marker = self.project_root / "_bmad" / "gate" / "gate-in-progress.json"
        self.assertFalse(marker.exists())

    def test_enabled_and_head_unexpected_not_fixable(self) -> None:
        # When neither baseline nor expected matches HEAD, reason is
        # unexpected_head and fixable is False.
        result = run_production_gate(
            self.project_root, "gate-unexpected",
            commit_sha="cafef00d" * 5,
            target={"kind": "story", "id": "s1"},
            profile=self.profile, factory_version="1.15.0",
            registry=self.registry,
            enable_lie_detector=True,
            baseline_sha="0badc0de" * 5,  # not HEAD
        )
        self.assertEqual(result["action"], "baseline_drift")
        verify = result["verify"]
        self.assertEqual(verify["reason"], "unexpected_head")
        self.assertFalse(verify["fixable"])


if __name__ == "__main__":
    unittest.main()
