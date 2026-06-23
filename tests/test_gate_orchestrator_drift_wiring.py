"""Tests for the C1 follow-up drift_watcher kwarg on run_production_gate.

The new kwarg is OPTIONAL and defaults to ``None``. When ``None``, the
gate run is byte-identical to the pre-existing behavior; when provided,
the orchestrator polls the watcher once at the start of the lifecycle
and once after evaluate_gate (before the fail_closed override). A
``.poll()`` that raises must never abort the gate — drift telemetry is
strictly advisory.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from story_automator.core.collector_registry import CollectorRegistry
from story_automator.core.evidence_io import persist_evidence_record
from story_automator.core.gate_orchestrator import run_production_gate
from story_automator.core.gate_schema import make_evidence_record


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


def _ok_evidence() -> list[dict]:
    return [make_evidence_record(
        collector="c", tool="t", category="correctness",
        status="ok", metrics={"coverage_pct": 95, "regressions": 0},
    )]


class RunProductionGateDriftWiringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        self.profile = _minimal_profile()
        self.registry = CollectorRegistry()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _persist_evidence(self, gate_id: str) -> None:
        for record in _ok_evidence():
            persist_evidence_record(self.project_root, gate_id, record)

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_run_production_gate_no_watcher_byte_identical_to_baseline(
        self, mock_run: MagicMock
    ) -> None:
        self._persist_evidence("gate-nowatch")
        mock_run.return_value = []
        gate = run_production_gate(
            self.project_root, "gate-nowatch",
            commit_sha="abc", target={"kind": "story", "id": "s1"},
            profile=self.profile, factory_version="1.15.0",
            registry=self.registry,
        )
        # Marker cleared + PASS verdict — same as the historical test.
        self.assertEqual(gate["overall"], "PASS")
        self.assertFalse(
            (self.project_root / "_bmad" / "gate" / "gate-in-progress.json").exists()
        )

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_run_production_gate_with_watcher_calls_poll_at_start_and_end(
        self, mock_run: MagicMock
    ) -> None:
        self._persist_evidence("gate-poll")
        mock_run.return_value = []
        watcher = MagicMock()
        watcher.poll.return_value = None
        gate = run_production_gate(
            self.project_root, "gate-poll",
            commit_sha="abc", target={"kind": "story", "id": "s1"},
            profile=self.profile, factory_version="1.15.0",
            registry=self.registry,
            drift_watcher=watcher,
        )
        self.assertEqual(gate["overall"], "PASS")
        self.assertEqual(watcher.poll.call_count, 2)

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_watcher_exception_does_not_break_gate(
        self, mock_run: MagicMock
    ) -> None:
        self._persist_evidence("gate-raise")
        mock_run.return_value = []
        watcher = MagicMock()
        watcher.poll.side_effect = RuntimeError("simulated drift failure")
        gate = run_production_gate(
            self.project_root, "gate-raise",
            commit_sha="abc", target={"kind": "story", "id": "s1"},
            profile=self.profile, factory_version="1.15.0",
            registry=self.registry,
            drift_watcher=watcher,
        )
        # Gate still completes despite the watcher exception.
        self.assertEqual(gate["overall"], "PASS")
        # Both polls attempted — second call must occur even after the
        # first one raised.
        self.assertEqual(watcher.poll.call_count, 2)

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_two_polls_persist_two_events_when_persistence_key_set(
        self, mock_run: MagicMock
    ) -> None:
        """End-to-end: a real watcher with a persistence_key writes two
        events to disk after a single ``run_production_gate`` call."""
        from unittest import mock as _mock
        import dataclasses
        from story_automator.core.innovation.spec_drift_persistence import (
            events_path,
        )
        from story_automator.core.innovation.spec_drift_watcher import (
            SpecDriftWatcher,
        )

        self._persist_evidence("gate-events")
        mock_run.return_value = []

        @dataclasses.dataclass(frozen=True)
        class _V:
            req_id: str
            status: str
            evidence: str = ""
            confidence: float = 1.0

        @dataclasses.dataclass(frozen=True)
        class _R:
            verdicts: list
            spec_path: str = "/tmp/spec.md"
            diff_sha: str = "deadbeef"
            model_invocation_ms: int = 1

        spec_path = self.project_root / "spec.md"
        spec_path.write_text("# spec", "utf-8")
        watcher = SpecDriftWatcher(
            project_root=self.project_root,
            spec_path=spec_path,
            persistence_key="gate-events",
        )

        report = _R(verdicts=[_V(req_id="REQ-01", status="implemented")])
        target = (
            "story_automator.core.innovation.spec_drift_watcher.check_compliance"
        )
        with _mock.patch(target, return_value=report):
            run_production_gate(
                self.project_root, "gate-events",
                commit_sha="abc",
                target={"kind": "story", "id": "s1"},
                profile=self.profile, factory_version="1.15.0",
                registry=self.registry,
                drift_watcher=watcher,
            )

        lines = events_path(self.project_root, "gate-events").read_text(
            "utf-8"
        ).splitlines()
        self.assertEqual(len(lines), 2)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
