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

    def _rewrite_marker_with_dead_pid(self, gate_id: str, commit_sha: str) -> None:
        """Replace the in-flight marker so its ``pid`` is a non-existent one.

        ``write_gate_marker`` now stamps the current process's PID (L1 fix)
        so ``recover_from_crash`` can perform a liveness check. The
        recover-orphan-evidence tests want to exercise the post-crash
        path — i.e. the writer is dead — which we simulate by overwriting
        the marker after the fact with PID 999999.
        """
        import json as _json
        marker = {
            "gate_id": gate_id,
            "commit_sha": commit_sha,
            "started_at": "2026-06-20T00:00:00Z",
            "pid": 999999,  # almost-certainly dead
        }
        path = (
            self.project_root / "_bmad" / "gate" / "gate-in-progress.json"
        )
        path.write_text(_json.dumps(marker, sort_keys=True), encoding="utf-8")

    @patch.dict(os.environ, {}, clear=False)
    def test_marker_without_verdict_cleans_up(self) -> None:
        """Marker present, no verdict -> cleans orphan evidence dir."""
        gate_id = "crash-gate-001"
        write_gate_marker(self.project_root, gate_id, "sha-crash")
        # Simulate a crashed (dead) writer so the L1 liveness check passes.
        self._rewrite_marker_with_dead_pid(gate_id, "sha-crash")

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
    def test_corrupted_marker_quarantines_evidence(self) -> None:
        """§9.2 corruption-is-loud: corrupted marker → evidence quarantined,
        not silently deleted. recover_from_crash must signal it loudly.

        L2-variant: with an extractable ``"gate_id":"..."`` fragment the
        scope is the in-flight gate ONLY (historical evidence dirs survive).
        """
        # Write a corrupted marker by hand (bypassing write_gate_marker).
        # The marker is broken JSON but still carries a salvageable
        # gate_id fragment so the targeted-quarantine scope applies.
        marker_path = (
            self.project_root / "_bmad" / "gate" / "gate-in-progress.json"
        )
        marker_path.write_text(
            '{"gate_id": "lost-gate", not valid json',
            encoding="utf-8",
        )

        # Seed an evidence directory the operator should be able to inspect
        evidence_dir = (
            self.project_root / "_bmad" / "gate" / "evidence" / "lost-gate"
        )
        evidence_dir.mkdir(parents=True)
        (evidence_dir / "dummy.json").write_text(
            '{"important": "do not delete"}', encoding="utf-8"
        )

        result = recover_from_crash(self.project_root)

        # The operator-facing contract: NOT silently "recovered=True".
        # The caller knows something needs investigation.
        self.assertFalse(result["recovered"])
        self.assertTrue(result["quarantined"])
        self.assertIn("corruption_reason", result)
        self.assertIn("quarantine_dir", result)

        # The evidence must NOT have been deleted.
        self.assertFalse(evidence_dir.exists(),
                         "evidence dir should have been MOVED out of the live tree")
        # It must have been moved into the quarantine.
        quar_dir = Path(result["quarantine_dir"])
        self.assertTrue(quar_dir.is_dir())
        quar_evidence = quar_dir / "evidence" / "lost-gate" / "dummy.json"
        self.assertTrue(quar_evidence.is_file(),
                        f"evidence should now be at {quar_evidence}")
        self.assertIn("do not delete", quar_evidence.read_text(encoding="utf-8"))

        # The corrupted marker should also be in the quarantine, so the
        # operator can see what state the orchestrator was in.
        self.assertTrue((quar_dir / "gate-in-progress.json").is_file())

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
        # Simulate a crashed (dead) writer so the L1 liveness check passes.
        self._rewrite_marker_with_dead_pid(gate_id, "sha-ok")

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

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_reuse_path_populates_unconditional_additive_fields(
        self, mock_run: MagicMock,
    ) -> None:
        """Reuse path must return the same in-memory shape as fresh runs.

        Regression for the latent bug where ``check_gate_reuse`` short-
        circuits ``run_production_gate`` before the post-evaluate block
        that unconditionally assigns ``evidence_merkle_root`` and
        ``lineage_root``. Without the fix the reuse path return dict
        lacked both keys while the fresh path always populated them, so
        a caller doing ``result["evidence_merkle_root"]`` would
        ``KeyError`` only on a cache hit.
        """
        # Fresh-path run produces a gate with both unconditional fields.
        evidence = [make_evidence_record(
            collector="c", tool="t", category="correctness",
            status="ok", metrics={"coverage_pct": 95, "regressions": 0},
        )]
        self._persist_evidence("gate-cache-keys", evidence)
        mock_run.return_value = []
        fresh = run_production_gate(
            self.project_root, "gate-cache-keys", commit_sha="abc",
            target={"kind": "story", "id": "s1"},
            profile=self.profile, factory_version="1.15.0",
            registry=self.registry,
        )
        self.assertIn("evidence_merkle_root", fresh)
        self.assertIn("lineage_root", fresh)

        # Second invocation with same (gate_id, commit, profile, fv) hits
        # the reuse path. Pre-fix this branch returned the on-disk dict
        # verbatim and the two keys were missing.
        reused = run_production_gate(
            self.project_root, "gate-cache-keys", commit_sha="abc",
            target={"kind": "story", "id": "s1"},
            profile=self.profile, factory_version="1.15.0",
            registry=self.registry,
        )
        self.assertIn(
            "evidence_merkle_root", reused,
            "reuse path must populate evidence_merkle_root to match fresh",
        )
        self.assertIn(
            "lineage_root", reused,
            "reuse path must populate lineage_root to match fresh",
        )
        # The two paths' values must agree (same on-disk evidence/lineage).
        self.assertEqual(
            reused["evidence_merkle_root"], fresh["evidence_merkle_root"],
        )
        self.assertEqual(reused["lineage_root"], fresh["lineage_root"])


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

    # WIRING-001: persist [AI-Review] tasks to the story file when story_path
    # is provided. Closes the BMAD code-review → review_continuation loop
    # the spec promised (§9.2).

    def test_remediate_without_story_path_returns_tasks_unpersisted(self) -> None:
        """Backward-compat: no story_path → tasks returned in-memory, not written."""
        gate = self._gate("FAIL", {
            "security": {"verdict": "FAIL", "required": {}, "actual": {},
                         "rationale": "1 critical CVE", "evidence": []},
        })
        result = route_gate_verdict(
            self.project_root, gate,
            story_key="E1-001", remediation_cycle=0, max_cycles=3,
        )
        self.assertEqual(result["action"], "remediate")
        self.assertFalse(result["tasks_persisted"])
        self.assertTrue(len(result["remediation_tasks"]) > 0)

    def test_remediate_with_story_path_persists_tasks_to_file(self) -> None:
        """story_path provided → tasks land in the story file's Tasks section."""
        gate = self._gate("FAIL", {
            "security": {"verdict": "FAIL", "required": {}, "actual": {},
                         "rationale": "1 critical CVE", "evidence": []},
        })
        story = self.project_root / "E1-001.md"
        story.write_text(
            "# Story E1-001\n\n## Tasks\n\n- [x] existing task\n\n## Notes\n",
            encoding="utf-8",
        )
        result = route_gate_verdict(
            self.project_root, gate,
            story_key="E1-001", remediation_cycle=0, max_cycles=3,
            story_path=story,
        )
        self.assertEqual(result["action"], "remediate")
        self.assertTrue(result["tasks_persisted"])
        self.assertNotIn("persist_error", result)
        content = story.read_text(encoding="utf-8")
        # Existing task preserved
        self.assertIn("existing task", content)
        # At least one [AI-Review] task appended under Tasks
        self.assertGreater(content.count("- [ ]"), 0)
        # Tasks went under the Tasks section, before Notes
        self.assertLess(content.find("## Tasks"), content.find("## Notes"))

    def test_remediate_with_missing_story_path_surfaces_error_not_silent(self) -> None:
        """If story_path points at a nonexistent file, the descriptor
        carries persist_error rather than silently dropping tasks."""
        gate = self._gate("FAIL", {
            "static": {"verdict": "FAIL", "required": {}, "actual": {},
                       "rationale": "mypy errors", "evidence": []},
        })
        result = route_gate_verdict(
            self.project_root, gate,
            story_key="E1-001", remediation_cycle=0, max_cycles=3,
            story_path=self.project_root / "does-not-exist.md",
        )
        self.assertEqual(result["action"], "remediate")
        self.assertFalse(result["tasks_persisted"])
        self.assertIn("persist_error", result)


class ResolveStoryArtifactPathTests(unittest.TestCase):
    """artifact_paths.resolve_story_artifact_path: shared helper used by
    the orchestrator to find the right .md file for a story_key."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        # Place a fake implementation-artifacts dir + BMAD-style story file
        self.art_dir = self.project_root / "_bmad-output" / "implementation-artifacts"
        self.art_dir.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_exact_match_wins(self) -> None:
        from story_automator.core.artifact_paths import resolve_story_artifact_path
        (self.art_dir / "E1-001.md").write_text("# Story\n", encoding="utf-8")
        (self.art_dir / "E1-001-Login-flow.md").write_text("# Story\n", encoding="utf-8")
        result = resolve_story_artifact_path(self.project_root, "E1-001")
        self.assertEqual(result.name, "E1-001.md")

    def test_prefix_fallback(self) -> None:
        from story_automator.core.artifact_paths import resolve_story_artifact_path
        (self.art_dir / "1.2-Add-checkout-form.md").write_text("# Story\n", encoding="utf-8")
        result = resolve_story_artifact_path(self.project_root, "1.2")
        self.assertIsNotNone(result)
        self.assertEqual(result.name, "1.2-Add-checkout-form.md")

    def test_no_match_returns_none(self) -> None:
        from story_automator.core.artifact_paths import resolve_story_artifact_path
        self.assertIsNone(
            resolve_story_artifact_path(self.project_root, "E99-999")
        )

    def test_empty_key_returns_none(self) -> None:
        from story_automator.core.artifact_paths import resolve_story_artifact_path
        self.assertIsNone(resolve_story_artifact_path(self.project_root, ""))


class FactoryVersionTests(unittest.TestCase):
    """Task 10: factory version resolution."""

    def test_returns_nonempty_string(self) -> None:
        version = resolve_factory_version()
        self.assertIsInstance(version, str)
        self.assertTrue(len(version) > 0)

    def test_matches_package_version(self) -> None:
        from story_automator import __version__
        self.assertEqual(resolve_factory_version(), __version__)


if __name__ == "__main__":
    unittest.main()
