"""Tests for ``run_production_gate(enable_pre_gate_verifier=True)`` wiring (Phase 3)."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from story_automator.core.collector_registry import CollectorRegistry
from story_automator.core.evidence_io import persist_evidence_record
from story_automator.core.gate_orchestrator import run_production_gate
from story_automator.core.gate_schema import make_evidence_record
from story_automator.core.result_json import (
    make_session_result,
    write_result_json,
)


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


def _add_commit(path: Path, filename: str) -> str:
    (path / filename).write_text("y\n")
    subprocess.run(
        ["git", "-C", str(path), "add", "."], capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", filename],
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


class PreGateVerifierWiringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="sa-orch-pgv-")
        self.repo = Path(self.tmpdir) / "repo"
        self.repo.mkdir()
        self.baseline = _init_repo(self.repo)
        self.result_path = Path(self.tmpdir) / "result.json"
        self.registry = CollectorRegistry()
        self.profile = _minimal_profile()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_default_off_skips_verifier(self, mock_run) -> None:
        # No result.json — verifier would fail if enabled. With default
        # off, the gate proceeds.
        record = make_evidence_record(
            collector="ok", tool="t", category="correctness",
            status="ok", metrics={"coverage_pct": 95, "regressions": 0},
        )
        persist_evidence_record(self.repo, "g-off", record)
        mock_run.return_value = []
        gate = run_production_gate(
            self.repo, "g-off",
            commit_sha=self.baseline,
            target={"kind": "story", "id": "s1"},
            profile=self.profile, factory_version="1.15.0",
            registry=self.registry,
            # enable_pre_gate_verifier defaults False
        )
        self.assertIn("overall", gate)
        self.assertEqual(gate["overall"], "PASS")

    def test_enabled_without_result_path_raises_typeerror(self) -> None:
        with self.assertRaises(TypeError):
            run_production_gate(
                self.repo, "g-noargs",
                commit_sha=self.baseline,
                target={"kind": "story", "id": "s1"},
                profile=self.profile, factory_version="1.15.0",
                registry=self.registry,
                enable_pre_gate_verifier=True,
                # result_json_path NOT provided
            )

    def test_enabled_missing_result_json_short_circuits(self) -> None:
        # result.json does not exist on disk → check 1 fails →
        # pre_gate_failed action returned without running collectors or
        # writing a marker.
        result = run_production_gate(
            self.repo, "g-missing",
            commit_sha=self.baseline,
            target={"kind": "story", "id": "s1"},
            profile=self.profile, factory_version="1.15.0",
            registry=self.registry,
            enable_pre_gate_verifier=True,
            result_json_path=self.result_path,
        )
        self.assertEqual(result["action"], "pre_gate_failed")
        self.assertEqual(result["gate_id"], "g-missing")
        self.assertEqual(result["failed_check"], "result_present")
        self.assertFalse(result["verify"]["ok"])
        # No marker should remain.
        marker = self.repo / "_bmad" / "gate" / "gate-in-progress.json"
        self.assertFalse(marker.exists())

    def test_enabled_critical_escalation_short_circuits(self) -> None:
        new_sha = _add_commit(self.repo, "b.py")
        write_result_json(self.result_path, make_session_result(
            commit_sha=new_sha,
            files_changed=["b.py"],
            summary="s",
            escalations=[
                {"severity": "CRITICAL", "reason": "data loss risk"},
            ],
        ))
        result = run_production_gate(
            self.repo, "g-crit",
            commit_sha=new_sha,
            target={"kind": "story", "id": "s1"},
            profile=self.profile, factory_version="1.15.0",
            registry=self.registry,
            enable_pre_gate_verifier=True,
            result_json_path=self.result_path,
            baseline_sha=self.baseline,
        )
        self.assertEqual(result["action"], "pre_gate_failed")
        self.assertEqual(result["failed_check"], "no_critical_escalations")
        self.assertEqual(result["verify"]["severity"], "CRITICAL")

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_enabled_and_all_checks_pass_proceeds(self, mock_run) -> None:
        new_sha = _add_commit(self.repo, "b.py")
        write_result_json(self.result_path, make_session_result(
            commit_sha=new_sha,
            files_changed=["b.py"],
            summary="s",
        ))
        record = make_evidence_record(
            collector="ok", tool="t", category="correctness",
            status="ok", metrics={"coverage_pct": 95, "regressions": 0},
        )
        persist_evidence_record(self.repo, "g-pass", record)
        mock_run.return_value = []
        result = run_production_gate(
            self.repo, "g-pass",
            commit_sha=new_sha,
            target={"kind": "story", "id": "s1"},
            profile=self.profile, factory_version="1.15.0",
            registry=self.registry,
            enable_pre_gate_verifier=True,
            result_json_path=self.result_path,
            baseline_sha=self.baseline,
        )
        self.assertEqual(result.get("overall"), "PASS")
        self.assertNotIn("action", result)


if __name__ == "__main__":
    unittest.main()
