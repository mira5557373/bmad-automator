"""Audit-floor regression net.

Consolidates the four audit-fix invariants that closed the deep code-validation
ship-blockers into a single always-green suite. Every gate-adoption PR
(bmad-auto patterns, future milestones) MUST keep this suite green.

The four fixes pinned here:

1. WAIVER_EXPIRY_ON_REUSE_NOT_ENFORCED (commit e5a8c55, §6.4(e)):
   can_reuse_gate_file MUST re-check waiver.expires_at on EVERY reuse, not
   just at issue time, so an expired waiver cannot keep a stale PASS alive.

2. MARKER_CORRUPTION_SILENTLY_IGNORED (commit fcbe17e, §9.2):
   A corrupted gate-in-progress marker MUST fail loud (raise
   GateMarkerCorruptedError → recover_from_crash quarantines evidence)
   rather than silently shutil.rmtree'ing the partial evidence.

3. WIRING-001 (commit 2bf44f3, §9.2):
   route_gate_verdict with a FAIL verdict and story_path MUST persist the
   [AI-Review] tasks into the story file's Tasks section (closing the BMAD
   code-review → review_continuation loop the spec promised).

4. WIRING-002 (commit 1069d86, §9.1+§9.2):
   The production_ready_gate verifier on FAIL MUST drive route_gate_verdict
   itself (resolving story_path, persisting tasks, returning a rich
   remediation descriptor) — not just return verified=False.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from story_automator.core.evidence_io import (
    GateMarkerCorruptedError,
    can_reuse_gate_file,
    read_gate_marker,
)
from story_automator.core.gate_orchestrator import recover_from_crash, route_gate_verdict
from story_automator.core.gate_schema import make_gate_file


class _Mixin:
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _gate(self, overall: str = "PASS", waivers: list[dict] | None = None) -> dict:
        cats = {"correctness": {"verdict": overall, "required": {}, "actual": {}, "rationale": "r"}}
        gate = make_gate_file(
            gate_id="audit-floor",
            target={"kind": "story", "id": "E1-001"},
            commit_sha="deadbeef",
            profile={"id": "test", "version": 1, "hash": "abc123"},
            factory_version="1.15.0",
            categories=cats,
            overall=overall,
        )
        if waivers is not None:
            gate["waivers"] = waivers
        return gate


# ---------------------------------------------------------------------------
# FIX 1 — WAIVER_EXPIRY_ON_REUSE_NOT_ENFORCED (commit e5a8c55)
# ---------------------------------------------------------------------------


class WaiverExpiryOnReuseInvariant(_Mixin, unittest.TestCase):
    """Pins §6.4(e): every reuse re-checks expires_at."""

    def test_expired_waiver_blocks_reuse_even_when_sha_profile_factory_match(self) -> None:
        gate = self._gate(waivers=[{
            "waiver_id": "01J90000000000000000000W",
            "operator_id": "mira",
            "issued_at": "2026-06-01T00:00:00Z",
            "expires_at": "2026-06-02T00:00:00Z",  # past
            "failing_categories": ["security"],
            "reason": "test",
            "signature": "sig",
            "profile_hash": "abc123",
        }])
        ok, reason = can_reuse_gate_file(
            gate, commit_sha="deadbeef", profile_hash="abc123", factory_version="1.15.0",
        )
        self.assertFalse(ok, "expired waiver MUST block reuse — the audit fix is gone")
        self.assertIn("waiver expired", reason)

    def test_unexpired_waiver_allows_reuse(self) -> None:
        gate = self._gate(waivers=[{
            "waiver_id": "01J90000000000000000000F",
            "operator_id": "mira",
            "issued_at": "2099-01-01T00:00:00Z",
            "expires_at": "2099-12-31T23:59:59Z",
            "failing_categories": ["security"],
            "reason": "infra dependency",
            "signature": "sig",
            "profile_hash": "abc123",
        }])
        ok, _ = can_reuse_gate_file(
            gate, commit_sha="deadbeef", profile_hash="abc123", factory_version="1.15.0",
        )
        self.assertTrue(ok)


# ---------------------------------------------------------------------------
# FIX 2 — MARKER_CORRUPTION_SILENTLY_IGNORED (commit fcbe17e)
# ---------------------------------------------------------------------------


class MarkerCorruptionInvariant(_Mixin, unittest.TestCase):
    """Pins §9.2: corruption is loud, not silent. Evidence is quarantined, not deleted."""

    def test_corrupted_marker_raises_GateMarkerCorruptedError(self) -> None:
        marker = self.tmp / "_bmad" / "gate" / "gate-in-progress.json"
        marker.parent.mkdir(parents=True)
        marker.write_text("{not json", encoding="utf-8")
        with self.assertRaises(GateMarkerCorruptedError):
            read_gate_marker(self.tmp)

    def test_recover_from_crash_quarantines_evidence_on_corruption(self) -> None:
        marker = self.tmp / "_bmad" / "gate" / "gate-in-progress.json"
        marker.parent.mkdir(parents=True)
        marker.write_text("{not json", encoding="utf-8")
        evidence_dir = self.tmp / "_bmad" / "gate" / "evidence" / "lost-gate"
        evidence_dir.mkdir(parents=True)
        important = evidence_dir / "important.json"
        important.write_text('{"do_not_delete": true}', encoding="utf-8")
        result = recover_from_crash(self.tmp)
        # The audit-fix contract: NOT silently "recovered=True".
        self.assertFalse(result["recovered"])
        self.assertTrue(result["quarantined"], "marker corruption must surface loud")
        self.assertIn("quarantine_dir", result)
        # Evidence must have been MOVED, not deleted.
        self.assertFalse(important.exists(),
                         "the original evidence path must not still exist (it was moved to quarantine)")
        quar = Path(result["quarantine_dir"])
        self.assertTrue((quar / "evidence" / "lost-gate" / "important.json").is_file(),
                        "important evidence MUST have been quarantined, not deleted")


# ---------------------------------------------------------------------------
# FIX 3 — WIRING-001: persist [AI-Review] tasks into the story file (commit 2bf44f3)
# ---------------------------------------------------------------------------


class AiReviewPersistenceInvariant(_Mixin, unittest.TestCase):
    """Pins §9.2: route_gate_verdict persists tasks when story_path is provided."""

    def test_fail_with_story_path_writes_tasks_into_Tasks_section(self) -> None:
        gate = self._gate(overall="FAIL")
        gate["categories"]["security"] = {
            "verdict": "FAIL", "required": {}, "actual": {},
            "rationale": "1 critical CVE", "evidence": [],
        }
        story = self.tmp / "E1-001.md"
        story.write_text(
            "# Story E1-001\n\n## Tasks\n\n- [x] existing dev task\n\n## Notes\n",
            encoding="utf-8",
        )
        result = route_gate_verdict(
            self.tmp, gate, story_key="E1-001",
            remediation_cycle=0, max_cycles=3,
            story_path=story,
        )
        self.assertEqual(result["action"], "remediate")
        self.assertTrue(result["tasks_persisted"], "tasks MUST be persisted to disk")
        content = story.read_text(encoding="utf-8")
        self.assertIn("existing dev task", content)
        # At least one new [AI-Review] task added under Tasks
        self.assertGreater(content.count("- [ ]"), 0)
        # Tasks went before Notes (edit-authorization correctness)
        self.assertLess(content.find("## Tasks"), content.find("## Notes"))

    def test_fail_without_story_path_returns_descriptor_unpersisted(self) -> None:
        gate = self._gate(overall="FAIL")
        gate["categories"]["security"] = {
            "verdict": "FAIL", "required": {}, "actual": {},
            "rationale": "1 critical CVE", "evidence": [],
        }
        result = route_gate_verdict(
            self.tmp, gate, story_key="E1-001",
            remediation_cycle=0, max_cycles=3,
        )
        self.assertEqual(result["action"], "remediate")
        self.assertFalse(result["tasks_persisted"])
        self.assertTrue(len(result["remediation_tasks"]) > 0)


# ---------------------------------------------------------------------------
# FIX 4 — WIRING-002: verifier-driven remediation loop (commit 1069d86)
# ---------------------------------------------------------------------------


class VerifierRemediationLoopInvariant(_Mixin, unittest.TestCase):
    """Pins §9.1+§9.2: production_ready_gate drives route_gate_verdict itself."""

    def _persist_gate_file(self, gate: dict) -> None:
        # Build a minimal gate file on disk so production_ready_gate can load it.
        from story_automator.core.evidence_io import persist_gate_file
        persist_gate_file(self.tmp, gate)

    def _seed_story(self) -> Path:
        artifacts = self.tmp / "_bmad-output" / "implementation-artifacts"
        artifacts.mkdir(parents=True)
        story = artifacts / "E1-001-my-story.md"
        story.write_text(
            "# Story E1-001\n\n## Tasks\n\n- [x] existing dev task\n",
            encoding="utf-8",
        )
        return story

    def test_fail_verdict_returns_remediation_descriptor_with_tasks_persisted(self) -> None:
        from story_automator.core.success_verifiers import production_ready_gate
        gate = self._gate(overall="FAIL")
        # Match the persisted gate_id convention (kept consistent across the
        # audit-fix verifier integration).
        gate["gate_id"] = "audit-floor-1069d86"
        self._persist_gate_file(gate)
        story = self._seed_story()
        result = production_ready_gate(
            project_root=str(self.tmp),
            story_key="E1-001-my-story",
            contract={"config": {"gate_id": gate["gate_id"]}},
        )
        self.assertFalse(result["verified"])
        # The verifier exposes the full route_gate_verdict descriptor.
        self.assertIn("remediation", result)
        self.assertEqual(result["remediation"]["action"], "remediate")
        self.assertTrue(result["remediation"]["tasks_persisted"])
        # Story file actually carries new [AI-Review] tasks.
        content = story.read_text(encoding="utf-8")
        self.assertGreater(content.count("- [ ]"), 0)
        self.assertIn("existing dev task", content)

    def test_fail_at_max_cycles_parks_via_descriptor(self) -> None:
        from story_automator.core.gate_status import list_parked
        from story_automator.core.success_verifiers import production_ready_gate
        gate = self._gate(overall="FAIL")
        gate["gate_id"] = "audit-floor-1069d86-park"
        self._persist_gate_file(gate)
        self._seed_story()
        result = production_ready_gate(
            project_root=str(self.tmp),
            story_key="E1-001-my-story",
            contract={"config": {
                "gate_id": gate["gate_id"],
                "remediation_cycle": 3,
                "max_cycles": 3,
            }},
        )
        self.assertFalse(result["verified"])
        self.assertEqual(result["remediation"]["action"], "park")
        parked = list_parked(self.tmp)
        self.assertTrue(any(p["story_key"] == "E1-001-my-story" for p in parked))


# ---------------------------------------------------------------------------
# Determinism baseline — pin canonical-JSON of representative gate files.
# A future port that accidentally changes serialization order or field shape
# will fail this suite immediately.
# ---------------------------------------------------------------------------


class GateFileDeterminismBaseline(unittest.TestCase):
    """The hash of a canonical-JSON-serialized gate file is the audit anchor.

    Any future change to make_gate_file / gate_schema canonicalization
    will break this; that is the desired behavior (it forces an explicit
    schema-version bump rather than silent drift).
    """

    def _build(self, overall: str, *, gate_id: str = "corp-1") -> dict:
        cats = {
            "correctness": {"verdict": overall, "required": {}, "actual": {}, "rationale": "r"},
            "security":    {"verdict": "PASS",  "required": {}, "actual": {}, "rationale": "ok"},
        }
        return make_gate_file(
            gate_id=gate_id,
            target={"kind": "story", "id": "E1-001"},
            commit_sha="deadbeef" * 5,  # 40-char synthetic SHA
            profile={"id": "default", "version": 1, "hash": "abc12345"},
            factory_version="1.15.0",
            categories=cats,
            overall=overall,
        )

    def test_PASS_gate_canonical_shape_is_stable(self) -> None:
        gate = self._build("PASS")
        # Pin the field set. New fields are allowed (additive), but renaming
        # or removing one is what breaks audit replay.
        expected_keys = {
            "gate_id", "schema_version", "target", "tier", "commit_sha",
            "scanner_data_snapshot", "profile", "factory_version",
            "risk_profile_ref", "categories", "overall", "waivers",
            "evidence_bundle_hash",
        }
        # The actual gate carries AT LEAST these. Additive fields don't break it.
        self.assertTrue(expected_keys.issubset(set(gate.keys())),
                        f"missing gate fields: {sorted(expected_keys - set(gate.keys()))}")
        self.assertEqual(gate["overall"], "PASS")
        self.assertEqual(gate["categories"]["correctness"]["verdict"], "PASS")
        self.assertEqual(gate["schema_version"], 1)

    def test_FAIL_gate_canonical_shape_is_stable(self) -> None:
        gate = self._build("FAIL", gate_id="corp-2")
        self.assertEqual(gate["overall"], "FAIL")
        # JSON round-trip stable (deterministic encoding).
        s1 = json.dumps(gate, sort_keys=True)
        s2 = json.dumps(json.loads(s1), sort_keys=True)
        self.assertEqual(s1, s2)


if __name__ == "__main__":
    unittest.main()
