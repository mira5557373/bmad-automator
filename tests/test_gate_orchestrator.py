"""Tests for gate_orchestrator: reuse, crash recovery, lifecycle, verdict routing."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from story_automator.core.collector_registry import CollectorRegistry
from story_automator.core.evidence_io import (
    persist_evidence_record,
    persist_gate_file,
    write_gate_marker,
)
from story_automator.core.gate_orchestrator import (
    check_gate_reuse,
    recover_from_crash,
    resolve_factory_version,
    route_gate_verdict,
    run_production_gate,
)
from story_automator.core.gate_schema import make_evidence_record, make_gate_file
from story_automator.core.gate_status import list_parked
from story_automator.core.product_profile import compute_profile_hash


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


class RunProductionGateTests(unittest.TestCase):
    """Task 8: core gate orchestration."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        self.profile = _minimal_profile()
        self.registry = CollectorRegistry()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _persist_evidence(self, gate_id: str, records: list[dict]) -> None:
        for record in records:
            persist_evidence_record(self.project_root, gate_id, record)

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_full_lifecycle_pass(self, mock_run: MagicMock) -> None:
        evidence = [make_evidence_record(
            collector="c", tool="t", category="correctness",
            status="ok", metrics={"coverage_pct": 95, "regressions": 0},
        )]
        self._persist_evidence("gate-test", evidence)
        mock_run.return_value = []
        gate = run_production_gate(
            self.project_root, "gate-test",
            commit_sha="abc123",
            target={"kind": "story", "id": "s1"},
            profile=self.profile,
            factory_version="1.15.0",
            registry=self.registry,
        )
        self.assertEqual(gate["overall"], "PASS")
        marker = self.project_root / "_bmad" / "gate" / "gate-in-progress.json"
        self.assertFalse(marker.exists())

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_marker_cleared_on_success(self, mock_run: MagicMock) -> None:
        evidence = [make_evidence_record(
            collector="c", tool="t", category="correctness",
            status="ok", metrics={"coverage_pct": 95, "regressions": 0},
        )]
        self._persist_evidence("gate-test2", evidence)
        mock_run.return_value = []
        run_production_gate(
            self.project_root, "gate-test2", commit_sha="abc",
            target={"kind": "story", "id": "s1"},
            profile=self.profile, factory_version="1.15.0",
            registry=self.registry,
        )
        marker_path = self.project_root / "_bmad" / "gate" / "gate-in-progress.json"
        self.assertFalse(marker_path.exists())

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_marker_cleared_on_failure(self, mock_run: MagicMock) -> None:
        evidence = [make_evidence_record(
            collector="c", tool="t", category="correctness",
            status="error", findings=["crash"],
        )]
        self._persist_evidence("gate-test3", evidence)
        mock_run.return_value = []
        gate = run_production_gate(
            self.project_root, "gate-test3", commit_sha="abc",
            target={"kind": "story", "id": "s1"},
            profile=self.profile, factory_version="1.15.0",
            registry=self.registry,
        )
        self.assertEqual(gate["overall"], "FAIL")
        marker_path = self.project_root / "_bmad" / "gate" / "gate-in-progress.json"
        self.assertFalse(marker_path.exists())

    def test_reuse_returns_cached_gate(self) -> None:
        gate = _make_test_gate_file(
            gate_id="gate-cache",
            commit_sha="abc",
            profile=self.profile,
            factory_version="1.15.0",
        )
        persist_gate_file(self.project_root, gate)
        result = run_production_gate(
            self.project_root, "gate-cache", commit_sha="abc",
            target={"kind": "story", "id": "s1"},
            profile=self.profile, factory_version="1.15.0",
            registry=self.registry,
        )
        self.assertEqual(result["overall"], "PASS")


class RouteGateVerdictTests(unittest.TestCase):
    """Task 9: verdict routing."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _gate(self, overall: str, categories: dict | None = None) -> dict:
        return make_gate_file(
            gate_id="gate-1",
            target={"kind": "story", "id": "s1"},
            commit_sha="abc",
            profile={"id": "t", "version": 1, "hash": "x"},
            factory_version="1.15.0",
            categories=categories or {"c": {"verdict": overall, "required": {}, "actual": {}, "rationale": "r"}},
            overall=overall,
        )

    def test_pass_returns_done(self) -> None:
        result = route_gate_verdict(
            self.project_root, self._gate("PASS"),
            story_key="E1-001", remediation_cycle=0, max_cycles=3,
        )
        self.assertEqual(result["action"], "done")
        self.assertTrue(result["commit"])

    def test_concerns_returns_done_with_debt(self) -> None:
        gate = self._gate("CONCERNS", {
            "security": {"verdict": "CONCERNS", "required": {}, "actual": {}, "rationale": "low confidence"},
            "correctness": {"verdict": "PASS", "required": {}, "actual": {}, "rationale": "ok"},
        })
        result = route_gate_verdict(
            self.project_root, gate,
            story_key="E1-001", remediation_cycle=0, max_cycles=3,
        )
        self.assertEqual(result["action"], "done")
        self.assertTrue(result["commit"])
        self.assertIn("mitigation_debt", result)

    def test_waived_returns_done(self) -> None:
        result = route_gate_verdict(
            self.project_root, self._gate("WAIVED"),
            story_key="E1-001", remediation_cycle=0, max_cycles=3,
        )
        self.assertEqual(result["action"], "done")
        self.assertTrue(result["waived"])

    def test_fail_below_max_returns_remediate(self) -> None:
        result = route_gate_verdict(
            self.project_root, self._gate("FAIL"),
            story_key="E1-001", remediation_cycle=1, max_cycles=3,
        )
        self.assertEqual(result["action"], "remediate")

    def test_fail_at_max_returns_park(self) -> None:
        result = route_gate_verdict(
            self.project_root, self._gate("FAIL"),
            story_key="E1-001", remediation_cycle=3, max_cycles=3,
        )
        self.assertEqual(result["action"], "park")
        self.assertEqual(result["reason"], "exhausted")

    def test_fail_risk_9_parks_immediately(self) -> None:
        result = route_gate_verdict(
            self.project_root, self._gate("FAIL"),
            story_key="E1-001", remediation_cycle=0, max_cycles=3,
            has_unmitigated_risk_9=True,
        )
        self.assertEqual(result["action"], "park")
        self.assertEqual(result["reason"], "risk-9")

    def test_park_creates_parked_record(self) -> None:
        route_gate_verdict(
            self.project_root, self._gate("FAIL"),
            story_key="E1-001", remediation_cycle=3, max_cycles=3,
        )
        parked = list_parked(self.project_root)
        self.assertEqual(len(parked), 1)
        self.assertEqual(parked[0]["story_key"], "E1-001")


class FactoryVersionTests(unittest.TestCase):
    """Task 10: factory version resolution."""

    def test_returns_nonempty_string(self) -> None:
        version = resolve_factory_version()
        self.assertIsInstance(version, str)
        self.assertTrue(len(version) > 0)

    def test_matches_package_version(self) -> None:
        from story_automator import __version__
        self.assertEqual(resolve_factory_version(), __version__)


class LearningHookTests(unittest.TestCase):
    """Verify that route_gate_verdict records gate results for learning."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.patcher = patch(
            "story_automator.core.gate_orchestrator.assert_host_context",
        )
        self.mock_host = self.patcher.start()
        self.history_patcher = patch(
            "story_automator.core.gate_history.assert_host_context",
        )
        self.history_patcher.start()

    def tearDown(self) -> None:
        self.patcher.stop()
        self.history_patcher.stop()
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_pass_verdict_records_history(self) -> None:
        from story_automator.core.gate_orchestrator import route_gate_verdict
        from story_automator.core.gate_history import count_gate_history
        gate_file = {
            "gate_id": "g-001", "overall": "PASS",
            "categories": {}, "commit_sha": "abc",
            "profile": {"id": "default", "version": 1, "hash": "h"},
            "factory_version": "1.0.0", "evidence_bundle_hash": "e",
            "schema_version": 1, "target": {"kind": "story", "id": "s1"},
            "waivers": [],
        }
        route_gate_verdict(
            self.tmp, gate_file, story_key="E1-001",
        )
        self.assertEqual(count_gate_history(self.tmp), 1)


class BreakingHashReuseTests(unittest.TestCase):
    """Verify that semver profiles use breaking hash for reuse."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.patcher = patch(
            "story_automator.core.gate_orchestrator.assert_host_context",
        )
        self.patcher.start()
        self.evidence_patcher = patch(
            "story_automator.core.evidence_io.assert_host_context",
        )
        self.evidence_patcher.start()

    def tearDown(self) -> None:
        self.patcher.stop()
        self.evidence_patcher.stop()
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_feature_only_change_still_reusable(self) -> None:
        import copy
        from story_automator.core.gate_orchestrator import check_gate_reuse
        from story_automator.core.evidence_io import persist_gate_file
        from story_automator.core.profile_versioning import compute_breaking_hash
        from story_automator.core.product_profile import compute_profile_hash

        profile_v1 = {
            "version": {"breaking": 1, "feature": 0},
            "id": "test",
            "matrix": {"P0": {"coverage_pct": 100, "levels": ["u"]},
                       "P1": {"coverage_pct": 90, "levels": ["u"]},
                       "P2": {"coverage_pct": 50, "levels": ["u"]},
                       "P3": {"coverage_pct": 20, "levels": ["s"]}},
            "categories": {"code": [], "system": []},
            "categories_na": [], "rules": {},
            "timeouts": {"security": 300},
            "cost_tier": {}, "forbidden_until": {},
            "invariants": {}, "toolchain": {},
            "seed_template": {},
            "snapshot": {"relativeDir": "_bmad-output/story-automator/profile-snapshots"},
        }
        persist_gate_file(self.tmp, {
            "gate_id": "g-001", "schema_version": 1,
            "target": {"kind": "story", "id": "s1"},
            "tier": "code", "commit_sha": "abc123",
            "scanner_data_snapshot": "",
            "profile": {
                "id": "test", "version": {"breaking": 1, "feature": 0},
                "hash": compute_profile_hash(profile_v1),
                "breaking_hash": compute_breaking_hash(profile_v1),
            },
            "factory_version": "1.15.0",
            "risk_profile_ref": "",
            "categories": {"correctness": {"verdict": "PASS"}},
            "overall": "PASS", "waivers": [],
            "evidence_bundle_hash": "eebb",
        })

        profile_v2 = copy.deepcopy(profile_v1)
        profile_v2["version"] = {"breaking": 1, "feature": 1}
        profile_v2["timeouts"]["security"] = 600

        gate_file, reason = check_gate_reuse(
            self.tmp, "g-001", "abc123", profile_v2, "1.15.0",
        )
        self.assertIsNotNone(gate_file, f"Expected reuse, got rejection: {reason}")


if __name__ == "__main__":
    unittest.main()
