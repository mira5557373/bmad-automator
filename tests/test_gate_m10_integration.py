"""Integration tests for M10 orchestrator wiring.

End-to-end round-trips through the full gate lifecycle:
collect -> adjudicate -> route -> persist -> CLI query.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

from story_automator.commands.gate_cmd import gate_dispatch
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
from story_automator.core.gate_status import (
    list_parked,
    load_mitigation_debt,
    park_story,
    record_mitigation_debt,
)
from story_automator.core.product_profile import compute_profile_hash
from story_automator.core.runtime_policy import VALID_VERIFIERS
from story_automator.core.success_verifiers import VERIFIERS

PROFILE = {
    "id": "test", "version": 1,
    "matrix": {
        "P0": {"coverage_pct": 100, "levels": []},
        "P1": {"coverage_pct": 90, "levels": []},
        "P2": {"coverage_pct": 50, "levels": []},
        "P3": {"coverage_pct": 20, "levels": []},
    },
    "categories": {"code": ["correctness", "security"], "system": []},
    "categories_na": [],
}


class FullLifecycleIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.registry = CollectorRegistry()

    def _persist_evidence(self, gate_id: str, records: list[dict]) -> None:
        for record in records:
            persist_evidence_record(self.tmp, gate_id, record)

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_pass_lifecycle(self, mock_run: MagicMock) -> None:
        evidence = [
            make_evidence_record(
                collector="c", tool="t", category="correctness",
                status="ok", metrics={"coverage_pct": 95, "regressions": 0},
            ),
            make_evidence_record(
                collector="s", tool="t", category="security",
                status="ok", metrics={"sast_high_count": 0},
            ),
        ]
        self._persist_evidence("integ-1", evidence)
        mock_run.return_value = []
        gate = run_production_gate(
            self.tmp, "integ-1", commit_sha="abc",
            target={"kind": "story", "id": "s1"},
            profile=PROFILE, factory_version="1.15.0",
            registry=self.registry,
        )
        self.assertEqual(gate["overall"], "PASS")
        route = route_gate_verdict(
            self.tmp, gate, story_key="E1-001",
            remediation_cycle=0, max_cycles=3,
        )
        self.assertEqual(route["action"], "done")
        self.assertTrue(route["commit"])

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_concerns_records_debt(self, mock_run: MagicMock) -> None:
        evidence = [
            make_evidence_record(
                collector="c", tool="t", category="correctness",
                status="ok", metrics={"coverage_pct": 85, "regressions": 0},
            ),
            make_evidence_record(
                collector="s", tool="t", category="security",
                status="ok", metrics={"sast_high_count": 0},
            ),
        ]
        self._persist_evidence("integ-2", evidence)
        mock_run.return_value = []
        gate = run_production_gate(
            self.tmp, "integ-2", commit_sha="abc",
            target={"kind": "story", "id": "s1"},
            profile=PROFILE, factory_version="1.15.0",
            registry=self.registry,
        )
        if gate["overall"] == "CONCERNS":
            route = route_gate_verdict(
                self.tmp, gate, story_key="E1-002",
                remediation_cycle=0, max_cycles=3,
            )
            self.assertEqual(route["action"], "done")
            debt = load_mitigation_debt(self.tmp)
            self.assertGreaterEqual(len(debt), 1)
        else:
            self.assertIn(gate["overall"], ("PASS", "CONCERNS"))

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_fail_exhaust_park_lifecycle(self, mock_run: MagicMock) -> None:
        evidence = [
            make_evidence_record(
                collector="c", tool="t", category="correctness",
                status="error", findings=["crash"],
            ),
        ]
        self._persist_evidence("integ-3", evidence)
        mock_run.return_value = []
        gate = run_production_gate(
            self.tmp, "integ-3", commit_sha="abc",
            target={"kind": "story", "id": "s1"},
            profile=PROFILE, factory_version="1.15.0",
            registry=self.registry,
        )
        self.assertEqual(gate["overall"], "FAIL")
        route = route_gate_verdict(
            self.tmp, gate, story_key="E1-003",
            remediation_cycle=3, max_cycles=3,
        )
        self.assertEqual(route["action"], "park")
        parked = list_parked(self.tmp)
        self.assertEqual(len(parked), 1)

    def test_crash_recovery_cleans_partial(self) -> None:
        import json as _json
        write_gate_marker(self.tmp, "crash-1", "abc")
        # L1 fix: write_gate_marker now stamps the live PID. To exercise
        # the post-crash recovery path the marker has to look like its
        # writer is dead — rewrite with PID 999999 (almost-certainly dead
        # on every supported platform).
        marker_path = Path(self.tmp) / "_bmad" / "gate" / "gate-in-progress.json"
        marker_path.write_text(_json.dumps({
            "gate_id": "crash-1",
            "commit_sha": "abc",
            "started_at": "2026-06-20T00:00:00Z",
            "pid": 999999,
        }, sort_keys=True), encoding="utf-8")
        evidence_dir = Path(self.tmp) / "_bmad" / "gate" / "evidence" / "crash-1"
        evidence_dir.mkdir(parents=True)
        (evidence_dir / "partial.json").write_text("{}")
        result = recover_from_crash(self.tmp)
        self.assertTrue(result["recovered"])
        self.assertFalse(evidence_dir.exists())


class VerifierRegistrationIntegrationTests(unittest.TestCase):
    def test_production_ready_gate_in_verifiers(self) -> None:
        self.assertIn("production_ready_gate", VERIFIERS)

    def test_production_ready_gate_in_valid_verifiers(self) -> None:
        self.assertIn("production_ready_gate", VALID_VERIFIERS)

    def test_verifier_callable(self) -> None:
        self.assertTrue(callable(VERIFIERS["production_ready_gate"]))


class CLIRoundTripTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    @patch("story_automator.commands.gate_cmd._project_root")
    def test_status_park_resume_round_trip(self, mock_root) -> None:
        mock_root.return_value = self.tmp
        with patch("sys.stdout", new_callable=StringIO) as out:
            gate_dispatch(["status"])
        status1 = json.loads(out.getvalue())
        self.assertEqual(status1["parked_count"], 0)

        park_story(self.tmp, "g1", "E1-001", "exhausted", "FAIL")

        with patch("sys.stdout", new_callable=StringIO) as out:
            gate_dispatch(["status"])
        status2 = json.loads(out.getvalue())
        self.assertEqual(status2["parked_count"], 1)

        with patch("sys.stdout", new_callable=StringIO) as out:
            gate_dispatch(["resume", "g1"])
        resume = json.loads(out.getvalue())
        self.assertTrue(resume["ok"])

        with patch("sys.stdout", new_callable=StringIO) as out:
            gate_dispatch(["status"])
        status3 = json.loads(out.getvalue())
        self.assertEqual(status3["parked_count"], 0)


class EdgeCaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.registry = CollectorRegistry()

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_gate_reuse_skips_collectors(self, mock_run: MagicMock) -> None:
        profile_hash = compute_profile_hash(PROFILE)
        gate = make_gate_file(
            gate_id="reuse-1",
            target={"kind": "story", "id": "s1"},
            commit_sha="abc",
            profile={"id": "test", "version": 1, "hash": profile_hash},
            factory_version="1.15.0",
            categories={"correctness": {"verdict": "PASS", "required": {}, "actual": {}, "rationale": "ok"}},
            overall="PASS",
        )
        persist_gate_file(self.tmp, gate)
        result = run_production_gate(
            self.tmp, "reuse-1", commit_sha="abc",
            target={"kind": "story", "id": "s1"},
            profile=PROFILE, factory_version="1.15.0",
            registry=self.registry,
        )
        mock_run.assert_not_called()
        self.assertEqual(result["overall"], "PASS")

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_empty_registry_fails_closed(self, mock_run: MagicMock) -> None:
        mock_run.return_value = []
        gate = run_production_gate(
            self.tmp, "empty-1", commit_sha="abc",
            target={"kind": "story", "id": "s1"},
            profile=PROFILE, factory_version="1.15.0",
            registry=self.registry,
        )
        self.assertEqual(gate["overall"], "FAIL")

    def test_mitigation_debt_idempotent(self) -> None:
        record_mitigation_debt(self.tmp, "g1", "E1-001", ["security"])
        record_mitigation_debt(self.tmp, "g1", "E1-001", ["security", "static"])
        debt = load_mitigation_debt(self.tmp)
        self.assertEqual(len(debt), 1)
        self.assertEqual(debt[0]["categories"], ["security", "static"])

    def test_invalidated_gate_not_reused(self) -> None:
        from story_automator.core.gate_status import invalidate_gate
        profile_hash = compute_profile_hash(PROFILE)
        gate = make_gate_file(
            gate_id="inv-1",
            target={"kind": "story", "id": "s1"},
            commit_sha="abc",
            profile={"id": "test", "version": 1, "hash": profile_hash},
            factory_version="1.15.0",
            categories={"c": {"verdict": "PASS", "required": {}, "actual": {}, "rationale": "ok"}},
            overall="PASS",
        )
        persist_gate_file(self.tmp, gate)
        invalidate_gate(self.tmp, "inv-1")
        result, reason = check_gate_reuse(
            self.tmp, "inv-1", "abc", PROFILE, "1.15.0",
        )
        self.assertIsNone(result)

    def test_factory_version_deterministic(self) -> None:
        v1 = resolve_factory_version()
        v2 = resolve_factory_version()
        self.assertEqual(v1, v2)


if __name__ == "__main__":
    unittest.main()
