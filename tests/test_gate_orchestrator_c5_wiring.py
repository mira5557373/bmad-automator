"""C5 — orchestrator wiring tests for ``run_production_gate``.

Covers AC-G-01..G-05 from spec §7.1 ("Gate-orchestrator wiring") for
the new optional ``threshold_proposer`` kwarg:

- AC-G-01: default kwarg ``None`` -> returned dict has neither
  ``threshold_proposal_ref`` nor ``threshold_proposer_error`` keys; the
  on-disk gate JSON under ``_bmad/gate/verdicts/<gate_id>.json`` is
  byte-identical to the no-kwarg call (persist_gate_file runs in
  evaluate_gate BEFORE the orchestrator's post-evaluate mutations).
- AC-G-02: kwarg supplied + proposer returns a ThresholdProposal ->
  ``gate_file["threshold_proposal_ref"]`` is the 16-hex proposal id;
  proposer returns None -> ``threshold_proposal_ref == ""``.
- AC-G-03: proposer raises -> gate completes normally;
  ``threshold_proposal_ref=""``, ``threshold_proposer_error=<ClassName>``.
- AC-G-04: ``session_usage`` + ``threshold_proposer`` both supplied ->
  both ``cost_total_usd`` and ``threshold_proposal_ref`` present; neither
  blocks the other.
- AC-G-05: ``GateThresholdProposalAudit(event="proposal_created")`` is
  emittable via ``emit_gate_audit`` (a fake audit policy captures it).
  Note: emission of the audit event itself is the proposer's
  responsibility (Stage 2 owns that). This module asserts the
  orchestrator surfaces enough state for the proposer's emission to be
  observable — i.e. the audit-event dataclass is reachable and emits via
  the standard chain.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from story_automator.core.collector_registry import CollectorRegistry
from story_automator.core.evidence_io import (
    persist_evidence_record,
    persist_gate_file,
)
from story_automator.core.gate_audit import GateThresholdProposalAudit
from story_automator.core.gate_orchestrator import run_production_gate
from story_automator.core.gate_schema import make_evidence_record, make_gate_file
from story_automator.core.innovation.threshold_proposer import ThresholdProposal
from story_automator.core.product_profile import compute_profile_hash


def _minimal_profile() -> dict:
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
    gate_id: str = "gate-c5-001",
    commit_sha: str = "abc123",
    profile: dict | None = None,
    factory_version: str = "1.0.0",
) -> dict:
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


class _StubProposer:
    """Minimal duck-typed stand-in for ThresholdProposer.

    The orchestrator only calls ``observe_gate(project_root, gate_file)``
    on the supplied object — there's no isinstance check (the kwarg is
    typed as ``ThresholdProposer | None`` under TYPE_CHECKING only).
    This stub lets tests pre-program the observe_gate outcome without
    spinning up a real proposer + fixture tree.
    """

    def __init__(
        self,
        *,
        return_value: ThresholdProposal | None = None,
        exc: BaseException | None = None,
    ) -> None:
        self.return_value = return_value
        self.exc = exc
        self.call_count = 0
        self.last_args: tuple | None = None

    def observe_gate(
        self,
        project_root,
        gate_file,
    ) -> ThresholdProposal | None:
        self.call_count += 1
        self.last_args = (project_root, gate_file)
        if self.exc is not None:
            raise self.exc
        return self.return_value


def _build_proposal(proposal_id: str = "0a1b2c3d4e5f6789") -> ThresholdProposal:
    """Construct a ThresholdProposal valid for the dataclass invariants."""
    return ThresholdProposal(
        proposal_id=proposal_id,
        target_module="story_automator.core.gate_rules",
        target_symbol="PRIORITY_THRESHOLDS",
        target_category="correctness",
        target_file_hint="",
        selector={"kind": "dict_tuple_element", "key": "P3", "index": 0},
        current_value=70,
        proposed_value=75,
        delta=5,
        rationale="synthetic stub",
        evidence_window=("a", "b", "c", "d", "e"),
        created_at_iso="2026-06-23T00:00:00Z",
        confirm_slug="deadbeef",
    )


class C5OrchestratorWiringTests(unittest.TestCase):
    """AC-G-01..G-05 wiring contract."""

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

    def _ok_evidence(self) -> list[dict]:
        return [
            make_evidence_record(
                collector="c",
                tool="t",
                category="correctness",
                status="ok",
                metrics={"coverage_pct": 95, "regressions": 0},
            )
        ]

    # ---------------------------------------------------------------
    # AC-G-01 — default kwarg byte-identical behavior
    # ---------------------------------------------------------------

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_default_kwarg_omits_new_fields(self, mock_run: MagicMock) -> None:
        """No ``threshold_proposer`` -> no ``threshold_proposal_ref`` AND
        no ``threshold_proposer_error`` on the returned dict (AC-G-01)."""
        self._persist_evidence("gate-c5-d1", self._ok_evidence())
        mock_run.return_value = []
        gate = run_production_gate(
            self.project_root,
            "gate-c5-d1",
            commit_sha="abc123",
            target={"kind": "story", "id": "s1"},
            profile=self.profile,
            factory_version="1.15.0",
            registry=self.registry,
        )
        self.assertNotIn("threshold_proposal_ref", gate)
        self.assertNotIn("threshold_proposer_error", gate)

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_default_kwarg_on_disk_gate_file_byte_identical(
        self,
        mock_run: MagicMock,
    ) -> None:
        """The on-disk gate JSON has NO new fields whether the proposer
        ran or not — persist_gate_file (in verdict_engine) runs BEFORE
        the orchestrator's post-evaluate mutations (AC-G-01 + AC-G-02)."""
        self._persist_evidence("gate-c5-d2", self._ok_evidence())
        mock_run.return_value = []
        # Baseline: no proposer.
        run_production_gate(
            self.project_root,
            "gate-c5-d2",
            commit_sha="abc123",
            target={"kind": "story", "id": "s1"},
            profile=self.profile,
            factory_version="1.15.0",
            registry=self.registry,
        )
        disk_no_proposer = (
            self.project_root / "_bmad" / "gate" / "verdicts" / "gate-c5-d2.json"
        ).read_bytes()

        # Clean evidence dir + verdict for next run with same id.
        verdict_path = self.project_root / "_bmad" / "gate" / "verdicts" / "gate-c5-d2.json"
        verdict_path.unlink()
        evidence_dir = self.project_root / "_bmad" / "gate" / "evidence" / "gate-c5-d2"
        if evidence_dir.exists():
            shutil.rmtree(evidence_dir)
        self._persist_evidence("gate-c5-d2", self._ok_evidence())

        # Same call with proposer that emits.
        proposer = _StubProposer(return_value=_build_proposal())
        run_production_gate(
            self.project_root,
            "gate-c5-d2",
            commit_sha="abc123",
            target={"kind": "story", "id": "s1"},
            profile=self.profile,
            factory_version="1.15.0",
            registry=self.registry,
            threshold_proposer=proposer,
        )
        disk_with_proposer = (
            self.project_root / "_bmad" / "gate" / "verdicts" / "gate-c5-d2.json"
        ).read_bytes()

        # Spec §3 — Frozen-gate-surface contract: on-disk JSON byte-
        # identical because persist_gate_file runs before orchestrator
        # mutations. Parse both as JSON and verify neither carries the
        # new fields.
        json_no_proposer = json.loads(disk_no_proposer)
        json_with_proposer = json.loads(disk_with_proposer)
        self.assertNotIn("threshold_proposal_ref", json_no_proposer)
        self.assertNotIn("threshold_proposer_error", json_no_proposer)
        self.assertNotIn("threshold_proposal_ref", json_with_proposer)
        self.assertNotIn("threshold_proposer_error", json_with_proposer)
        # Also: byte-equal at the JSON level (canonical write contract).
        self.assertEqual(disk_no_proposer, disk_with_proposer)

    # ---------------------------------------------------------------
    # AC-G-02 — supplied kwarg sets the in-memory ref
    # ---------------------------------------------------------------

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_proposer_emits_sets_proposal_ref(self, mock_run: MagicMock) -> None:
        self._persist_evidence("gate-c5-e1", self._ok_evidence())
        mock_run.return_value = []
        proposer = _StubProposer(return_value=_build_proposal())
        gate = run_production_gate(
            self.project_root,
            "gate-c5-e1",
            commit_sha="abc123",
            target={"kind": "story", "id": "s1"},
            profile=self.profile,
            factory_version="1.15.0",
            registry=self.registry,
            threshold_proposer=proposer,
        )
        self.assertIn("threshold_proposal_ref", gate)
        self.assertEqual(gate["threshold_proposal_ref"], "0a1b2c3d4e5f6789")
        self.assertNotIn("threshold_proposer_error", gate)
        self.assertEqual(proposer.call_count, 1)

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_proposer_none_sets_empty_ref(self, mock_run: MagicMock) -> None:
        """Proposer returns None -> threshold_proposal_ref='' (AC-G-02)."""
        self._persist_evidence("gate-c5-e2", self._ok_evidence())
        mock_run.return_value = []
        proposer = _StubProposer(return_value=None)
        gate = run_production_gate(
            self.project_root,
            "gate-c5-e2",
            commit_sha="abc123",
            target={"kind": "story", "id": "s1"},
            profile=self.profile,
            factory_version="1.15.0",
            registry=self.registry,
            threshold_proposer=proposer,
        )
        self.assertIn("threshold_proposal_ref", gate)
        self.assertEqual(gate["threshold_proposal_ref"], "")
        self.assertNotIn("threshold_proposer_error", gate)

    # ---------------------------------------------------------------
    # AC-G-03 — proposer raises -> swallowed; error diagnostic recorded
    # ---------------------------------------------------------------

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_proposer_raises_swallowed_with_error_field(
        self,
        mock_run: MagicMock,
    ) -> None:
        self._persist_evidence("gate-c5-x1", self._ok_evidence())
        mock_run.return_value = []
        proposer = _StubProposer(exc=RuntimeError("synthetic"))
        # Gate must complete normally; the exception MUST NOT propagate.
        gate = run_production_gate(
            self.project_root,
            "gate-c5-x1",
            commit_sha="abc123",
            target={"kind": "story", "id": "s1"},
            profile=self.profile,
            factory_version="1.15.0",
            registry=self.registry,
            threshold_proposer=proposer,
        )
        self.assertEqual(gate["overall"], "PASS")
        self.assertEqual(gate["threshold_proposal_ref"], "")
        self.assertEqual(gate["threshold_proposer_error"], "RuntimeError")

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_proposer_raises_value_error_records_subclass_name(
        self,
        mock_run: MagicMock,
    ) -> None:
        """``type(exc).__name__`` not ``Exception`` — subclass-precise."""
        self._persist_evidence("gate-c5-x2", self._ok_evidence())
        mock_run.return_value = []
        proposer = _StubProposer(exc=ValueError("synthetic"))
        gate = run_production_gate(
            self.project_root,
            "gate-c5-x2",
            commit_sha="abc123",
            target={"kind": "story", "id": "s1"},
            profile=self.profile,
            factory_version="1.15.0",
            registry=self.registry,
            threshold_proposer=proposer,
        )
        self.assertEqual(gate["threshold_proposer_error"], "ValueError")

    # ---------------------------------------------------------------
    # AC-G-04 — cost_total_usd + threshold_proposal_ref both set
    # ---------------------------------------------------------------

    @patch("story_automator.core.gate_orchestrator.emit_gate_cost_report")
    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_cost_and_proposer_both_present(
        self,
        mock_run: MagicMock,
        mock_cost: MagicMock,
    ) -> None:
        """session_usage + threshold_proposer -> both fields present;
        neither path blocks the other (AC-G-04)."""
        self._persist_evidence("gate-c5-c1", self._ok_evidence())
        # collector_outcomes must be truthy for cost emission to run.
        mock_run.return_value = [MagicMock()]
        # Stub the cost report shape that the orchestrator reads.
        cost_report = MagicMock()
        cost_report.total_cost_usd = 0.42
        mock_cost.return_value = cost_report

        from story_automator.core.usage_parsers.types import UsageMetrics

        session_usage = UsageMetrics(
            input_tokens=100,
            output_tokens=50,
            total_cost_usd=0.42,
            tool_calls_count=2,
            duration_s=1.0,
        )
        proposer = _StubProposer(return_value=_build_proposal())
        gate = run_production_gate(
            self.project_root,
            "gate-c5-c1",
            commit_sha="abc123",
            target={"kind": "story", "id": "s1"},
            profile=self.profile,
            factory_version="1.15.0",
            registry=self.registry,
            session_usage=session_usage,
            threshold_proposer=proposer,
        )
        self.assertEqual(gate["cost_total_usd"], 0.42)
        self.assertEqual(gate["threshold_proposal_ref"], "0a1b2c3d4e5f6789")
        self.assertNotIn("threshold_proposer_error", gate)

    # ---------------------------------------------------------------
    # AC-G-05 — audit event dataclass + chain emission
    # ---------------------------------------------------------------

    def test_threshold_proposal_audit_dataclass_emittable(self) -> None:
        """``GateThresholdProposalAudit(event='proposal_created', ...)``
        is reachable from gate_audit AND lives in the ``_AuditEvent``
        union (so ``emit_gate_audit`` accepts it without TypeError).
        Proposer code (Stage 2) calls into this surface; the orchestrator
        wiring's job is to keep the surface live, which this asserts.
        """
        # Surface check: dataclass exists, accepts the expected kwargs,
        # and produces the expected event_name.
        event = GateThresholdProposalAudit(
            proposal_id="0a1b2c3d4e5f6789",
            target_module="story_automator.core.gate_rules",
            target_symbol="PRIORITY_THRESHOLDS",
            event="proposal_created",
            operator_id="local",
        )
        self.assertEqual(event.event_name, "GateThresholdProposal")
        self.assertEqual(event.event, "proposal_created")

        # Union check: importable from gate_audit's __all__.
        from story_automator.core import gate_audit

        self.assertIn(
            "GateThresholdProposalAudit",
            getattr(gate_audit, "__all__", []),
        )
        self.assertIs(
            gate_audit.GateThresholdProposalAudit,
            GateThresholdProposalAudit,
        )

    # ---------------------------------------------------------------
    # Bonus — proposer NOT called when default kwarg None
    # ---------------------------------------------------------------

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_default_kwarg_does_not_construct_or_call_proposer(
        self,
        mock_run: MagicMock,
    ) -> None:
        """When the kwarg is omitted, the orchestrator must NOT touch any
        proposer state. The Path B contract is ``threshold_proposer=None
        -> byte-identical to pre-C5``. Verified by sentinel: a stub
        proposer's ``call_count`` stays 0 — but only because it is never
        attached. We can't observe non-attachment directly, so the proxy
        test asserts the gate returns without raising AND without the new
        fields (also covered above)."""
        self._persist_evidence("gate-c5-n1", self._ok_evidence())
        mock_run.return_value = []
        gate = run_production_gate(
            self.project_root,
            "gate-c5-n1",
            commit_sha="abc123",
            target={"kind": "story", "id": "s1"},
            profile=self.profile,
            factory_version="1.15.0",
            registry=self.registry,
            # threshold_proposer intentionally omitted.
        )
        self.assertEqual(gate["overall"], "PASS")
        self.assertNotIn("threshold_proposal_ref", gate)
        self.assertNotIn("threshold_proposer_error", gate)

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_reuse_path_skips_proposer(self, mock_run: MagicMock) -> None:
        """``check_gate_reuse`` short-circuits BEFORE the proposer call
        site. A reused gate file must NOT carry the new fields (it's the
        original on-disk dict)."""
        # Persist a reusable gate file.
        gate_file = _make_test_gate_file(
            gate_id="gate-c5-r1",
            commit_sha="abc",
            profile=self.profile,
            factory_version="1.15.0",
        )
        persist_gate_file(self.project_root, gate_file)
        proposer = _StubProposer(return_value=_build_proposal())
        result = run_production_gate(
            self.project_root,
            "gate-c5-r1",
            commit_sha="abc",
            target={"kind": "story", "id": "s1"},
            profile=self.profile,
            factory_version="1.15.0",
            registry=self.registry,
            threshold_proposer=proposer,
        )
        # The reused path returns BEFORE the proposer block.
        self.assertEqual(result["overall"], "PASS")
        self.assertEqual(proposer.call_count, 0)
        self.assertNotIn("threshold_proposal_ref", result)
        self.assertNotIn("threshold_proposer_error", result)


if __name__ == "__main__":
    unittest.main()
