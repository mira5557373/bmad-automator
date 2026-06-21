"""Tests for gate_orchestrator: reuse checks with drift detection and crash recovery."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from story_automator.core.gate_schema import make_gate_file
from story_automator.core.evidence_io import (
    persist_gate_file,
    write_gate_marker,
)
from story_automator.core.product_profile import compute_profile_hash
from story_automator.core.gate_orchestrator import (
    check_gate_reuse,
    recover_from_crash,
)


def _minimal_profile(*, hash_override: str = "") -> dict:
    """Return a minimal valid profile dict for testing."""
    return {
        "version": 1,
        "id": "test",
        "matrix": {
            "P0": {"coverage_pct": 80, "levels": ["unit"]},
            "P1": {"coverage_pct": 60, "levels": ["unit"]},
            "P2": {"coverage_pct": 40, "levels": ["unit"]},
            "P3": {"coverage_pct": 20, "levels": ["unit"]},
        },
        "categories": {"code": ["correctness"], "system": []},
    }


def _make_test_gate_file(
    *,
    gate_id: str = "gate-001",
    commit_sha: str = "abc123",
    profile: dict | None = None,
    factory_version: str = "1.0.0",
) -> dict:
    """Build a gate file dict suitable for tests."""
    if profile is None:
        profile = _minimal_profile()
    profile_hash = compute_profile_hash(profile)
    return make_gate_file(
        gate_id=gate_id,
        target={"repo": "test-repo"},
        commit_sha=commit_sha,
        profile={"name": "test", "hash": profile_hash},
        factory_version=factory_version,
        categories={"correctness": {"verdict": "PASS", "evidence": []}},
        overall="PASS",
    )


class CheckGateReuseTests(unittest.TestCase):
    """Task 6: gate reuse check with drift detection."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        # Ensure _bmad/gate dirs exist
        (self.project_root / "_bmad" / "gate" / "verdicts").mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch.dict(os.environ, {}, clear=False)
    def test_reuse_when_all_match(self) -> None:
        """Gate file is reused when commit, profile hash, and factory version all match."""
        profile = _minimal_profile()
        gate_file = _make_test_gate_file(
            gate_id="gate-001",
            commit_sha="abc123",
            profile=profile,
            factory_version="1.0.0",
        )
        persist_gate_file(self.project_root, gate_file)

        result, reason = check_gate_reuse(
            self.project_root,
            "gate-001",
            "abc123",
            profile,
            "1.0.0",
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["gate_id"], "gate-001")
        self.assertEqual(reason, "")

    @patch.dict(os.environ, {}, clear=False)
    def test_reject_on_commit_sha_mismatch(self) -> None:
        """Reuse is rejected when commit SHA differs."""
        profile = _minimal_profile()
        gate_file = _make_test_gate_file(
            gate_id="gate-002",
            commit_sha="abc123",
            profile=profile,
            factory_version="1.0.0",
        )
        persist_gate_file(self.project_root, gate_file)

        result, reason = check_gate_reuse(
            self.project_root,
            "gate-002",
            "def456",  # different commit
            profile,
            "1.0.0",
        )
        self.assertIsNone(result)
        self.assertIn("commit_sha", reason)

    @patch.dict(os.environ, {}, clear=False)
    def test_reject_on_profile_hash_mismatch(self) -> None:
        """Reuse is rejected when profile hash computed from current profile
        does not match the hash stored in the gate file."""
        profile = _minimal_profile()
        gate_file = _make_test_gate_file(
            gate_id="gate-003",
            commit_sha="abc123",
            profile=profile,
            factory_version="1.0.0",
        )
        # Tamper: write a gate file with a hard-coded wrong hash
        gate_file["profile"]["hash"] = "aabb"
        # Write directly (bypass persist_gate_file validation for the tampered hash)
        verdicts_dir = self.project_root / "_bmad" / "gate" / "verdicts"
        (verdicts_dir / "gate-003.json").write_text(
            json.dumps(gate_file, sort_keys=True) + "\n"
        )

        result, reason = check_gate_reuse(
            self.project_root,
            "gate-003",
            "abc123",
            profile,
            "1.0.0",
        )
        self.assertIsNone(result)
        self.assertIn("profile.hash", reason)

    @patch.dict(os.environ, {}, clear=False)
    def test_reject_on_factory_version_mismatch(self) -> None:
        """Reuse is rejected when factory version differs."""
        profile = _minimal_profile()
        gate_file = _make_test_gate_file(
            gate_id="gate-004",
            commit_sha="abc123",
            profile=profile,
            factory_version="1.0.0",
        )
        persist_gate_file(self.project_root, gate_file)

        result, reason = check_gate_reuse(
            self.project_root,
            "gate-004",
            "abc123",
            profile,
            "2.0.0",  # different factory version
        )
        self.assertIsNone(result)
        self.assertIn("factory_version", reason)

    @patch.dict(os.environ, {}, clear=False)
    def test_missing_gate_returns_none(self) -> None:
        """When no gate file exists, returns (None, message)."""
        profile = _minimal_profile()
        result, reason = check_gate_reuse(
            self.project_root,
            "nonexistent-gate",
            "abc123",
            profile,
            "1.0.0",
        )
        self.assertIsNone(result)
        self.assertIn("nonexistent-gate", reason)


class RecoverFromCrashTests(unittest.TestCase):
    """Task 7: crash recovery."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        (self.project_root / "_bmad" / "gate").mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch.dict(os.environ, {}, clear=False)
    def test_no_marker_returns_not_recovered(self) -> None:
        """No marker means nothing to recover."""
        result = recover_from_crash(self.project_root)
        self.assertFalse(result["recovered"])

    @patch.dict(os.environ, {}, clear=False)
    def test_marker_without_verdict_cleans_up(self) -> None:
        """Marker present, no verdict -> cleans orphan evidence dir."""
        gate_id = "crash-gate-001"
        write_gate_marker(self.project_root, gate_id, "sha-crash")

        # Create orphan evidence directory
        evidence_dir = (
            self.project_root / "_bmad" / "gate" / "evidence" / gate_id
        )
        evidence_dir.mkdir(parents=True)
        (evidence_dir / "dummy.json").write_text("{}")

        result = recover_from_crash(self.project_root)
        self.assertTrue(result["recovered"])
        self.assertEqual(result["gate_id"], gate_id)
        self.assertFalse(result["had_verdict"])
        self.assertEqual(result["commit_sha"], "sha-crash")
        # Evidence dir should be cleaned up
        self.assertFalse(evidence_dir.exists())
        # Marker should be cleared
        marker_path = (
            self.project_root / "_bmad" / "gate" / "gate-in-progress.json"
        )
        self.assertFalse(marker_path.exists())

    @patch.dict(os.environ, {}, clear=False)
    def test_marker_with_existing_verdict_clears_marker_only(self) -> None:
        """Marker present with existing verdict -> preserve verdict, clear marker."""
        profile = _minimal_profile()
        gate_id = "crash-gate-002"
        gate_file = _make_test_gate_file(
            gate_id=gate_id,
            commit_sha="sha-ok",
            profile=profile,
            factory_version="1.0.0",
        )
        persist_gate_file(self.project_root, gate_file)
        write_gate_marker(self.project_root, gate_id, "sha-ok")

        result = recover_from_crash(self.project_root)
        self.assertTrue(result["recovered"])
        self.assertEqual(result["gate_id"], gate_id)
        self.assertTrue(result["had_verdict"])
        self.assertEqual(result["commit_sha"], "sha-ok")
        # Verdict file should still exist
        verdict_path = (
            self.project_root
            / "_bmad"
            / "gate"
            / "verdicts"
            / f"{gate_id}.json"
        )
        self.assertTrue(verdict_path.exists())
        # Marker should be cleared
        marker_path = (
            self.project_root / "_bmad" / "gate" / "gate-in-progress.json"
        )
        self.assertFalse(marker_path.exists())


if __name__ == "__main__":
    unittest.main()
