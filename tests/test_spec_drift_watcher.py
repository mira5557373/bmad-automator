"""Tests for the SpecDriftWatcher MVP (C1).

Exercises the poll-based drift detector that re-scores AC coverage and
classifies the regression severity against a baseline snapshot.

The watcher is decoupled from telemetry / persistence — these tests only
verify the in-memory contract.
"""

from __future__ import annotations

import dataclasses
import unittest
from pathlib import Path
from unittest import mock

from story_automator.core.innovation.spec_drift_watcher import (
    SpecDriftError,
    SpecDriftEvent,
    SpecDriftSnapshot,
    SpecDriftWatcher,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _verdict(req_id: str, status: str):
    """Construct a stub object shaped like ReqVerdict from spec_compliance."""

    @dataclasses.dataclass(frozen=True)
    class _V:
        req_id: str
        status: str
        evidence: str = ""
        confidence: float = 1.0

    return _V(req_id=req_id, status=status)


def _report(verdicts):
    """Construct a stub object shaped like ComplianceReport."""

    @dataclasses.dataclass(frozen=True)
    class _R:
        verdicts: list
        spec_path: str = "/tmp/spec.md"
        diff_sha: str = "deadbeef"
        model_invocation_ms: int = 1

    return _R(verdicts=list(verdicts))


def _make_watcher(*, project_root: Path | None = None, spec_path: Path | None = None,
                  baseline: SpecDriftSnapshot | None = None,
                  thresholds: dict[str, float] | None = None):
    return SpecDriftWatcher(
        project_root=project_root or Path("/tmp/proj"),
        spec_path=spec_path or Path("/tmp/spec.md"),
        baseline_snapshot=baseline,
        severity_thresholds=thresholds,
    )


# ---------------------------------------------------------------------------
# Dataclass shape
# ---------------------------------------------------------------------------


class TestDataclassShapes(unittest.TestCase):
    def test_dataclass_shapes_frozen(self):
        snap = SpecDriftSnapshot(
            score=0.9,
            requirements_total=10,
            requirements_satisfied=9,
            timestamp_iso="2026-06-22T00:00:00Z",
        )
        evt = SpecDriftEvent(
            baseline_score=0.9,
            current_score=0.8,
            delta=0.1,
            severity="INFO",
            requirements_lost=("REQ-01",),
            timestamp_iso="2026-06-22T00:00:01Z",
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            snap.score = 0.0  # type: ignore[misc]
        with self.assertRaises(dataclasses.FrozenInstanceError):
            evt.severity = "OK"  # type: ignore[misc]
        self.assertEqual(evt.requirements_lost, ("REQ-01",))


# ---------------------------------------------------------------------------
# Severity mapping
# ---------------------------------------------------------------------------


class TestSeverityMapping(unittest.TestCase):
    def test_severity_mapping_default_thresholds(self):
        w = _make_watcher()
        # delta < 0 (improved) -> OK
        self.assertEqual(w._classify_severity(-0.1), "OK")
        # 0 <= delta < 0.05 -> OK
        self.assertEqual(w._classify_severity(0.0), "OK")
        self.assertEqual(w._classify_severity(0.04), "OK")
        # 0.05 <= delta < 0.15 -> INFO
        self.assertEqual(w._classify_severity(0.05), "INFO")
        self.assertEqual(w._classify_severity(0.10), "INFO")
        # 0.15 <= delta < 0.30 -> WARNING
        self.assertEqual(w._classify_severity(0.15), "WARNING")
        self.assertEqual(w._classify_severity(0.20), "WARNING")
        # >= 0.30 -> CRITICAL
        self.assertEqual(w._classify_severity(0.30), "CRITICAL")
        self.assertEqual(w._classify_severity(0.95), "CRITICAL")

    def test_severity_mapping_custom_thresholds_validated(self):
        w = _make_watcher(thresholds={"info": 0.02, "warning": 0.04, "critical": 0.08})
        self.assertEqual(w._classify_severity(0.01), "OK")
        self.assertEqual(w._classify_severity(0.02), "INFO")
        self.assertEqual(w._classify_severity(0.04), "WARNING")
        self.assertEqual(w._classify_severity(0.08), "CRITICAL")

        # Unknown keys rejected.
        with self.assertRaises(SpecDriftError):
            _make_watcher(thresholds={"info": 0.1, "bogus": 0.5})

        # Non-monotonic thresholds rejected.
        with self.assertRaises(SpecDriftError):
            _make_watcher(thresholds={"info": 0.5, "warning": 0.3, "critical": 0.7})

        # Out-of-range values rejected.
        with self.assertRaises(SpecDriftError):
            _make_watcher(thresholds={"info": -0.1, "warning": 0.2, "critical": 0.3})


# ---------------------------------------------------------------------------
# Snapshot / poll behavior (uses spec_compliance.check_compliance)
# ---------------------------------------------------------------------------


_TARGET = "story_automator.core.innovation.spec_drift_watcher.check_compliance"


class TestSnapshotAndPoll(unittest.TestCase):
    def test_snapshot_uses_spec_compliance(self):
        w = _make_watcher()
        report = _report([_verdict("REQ-01", "implemented"), _verdict("REQ-02", "missing")])
        with mock.patch(_TARGET, return_value=report) as patched:
            snap = w.snapshot()
        self.assertEqual(patched.call_count, 1)
        self.assertEqual(snap.requirements_total, 2)
        self.assertEqual(snap.requirements_satisfied, 1)
        self.assertAlmostEqual(snap.score, 0.5)
        self.assertTrue(snap.timestamp_iso.endswith("Z"))

    def test_poll_without_baseline_takes_one(self):
        w = _make_watcher()
        report = _report([_verdict("REQ-01", "implemented")])
        with mock.patch(_TARGET, return_value=report):
            self.assertFalse(w.is_baseline_set())
            event = w.poll()
        self.assertTrue(w.is_baseline_set())
        # On the auto-baseline poll, delta is 0 (no drift yet).
        self.assertEqual(event.severity, "OK")
        self.assertAlmostEqual(event.delta, 0.0)
        self.assertAlmostEqual(event.baseline_score, event.current_score)
        self.assertEqual(event.requirements_lost, ())

    def test_poll_returns_OK_when_no_drift(self):
        w = _make_watcher()
        baseline_report = _report([
            _verdict("REQ-01", "implemented"),
            _verdict("REQ-02", "implemented"),
        ])
        with mock.patch(_TARGET, return_value=baseline_report):
            w.set_baseline()
        # Same report on poll.
        with mock.patch(_TARGET, return_value=baseline_report):
            event = w.poll()
        self.assertEqual(event.severity, "OK")
        self.assertAlmostEqual(event.delta, 0.0)
        self.assertEqual(event.requirements_lost, ())

    def test_poll_returns_INFO_when_small_drift(self):
        w = _make_watcher()
        # Baseline 10/10 implemented, then 9/10. delta = 0.10.
        baseline = _report([_verdict(f"REQ-{i:02d}", "implemented") for i in range(1, 11)])
        with mock.patch(_TARGET, return_value=baseline):
            w.set_baseline()
        regressed_verdicts = [_verdict(f"REQ-{i:02d}", "implemented") for i in range(1, 10)]
        regressed_verdicts.append(_verdict("REQ-10", "missing"))
        regressed = _report(regressed_verdicts)
        with mock.patch(_TARGET, return_value=regressed):
            event = w.poll()
        self.assertEqual(event.severity, "INFO")
        self.assertAlmostEqual(event.delta, 0.10)
        self.assertEqual(event.requirements_lost, ("REQ-10",))

    def test_poll_returns_WARNING_when_moderate_drift(self):
        w = _make_watcher()
        baseline = _report([_verdict(f"REQ-{i:02d}", "implemented") for i in range(1, 11)])
        with mock.patch(_TARGET, return_value=baseline):
            w.set_baseline()
        # 8/10 -> delta 0.20.
        regressed_verdicts = [_verdict(f"REQ-{i:02d}", "implemented") for i in range(1, 9)]
        regressed_verdicts.extend([_verdict("REQ-09", "missing"), _verdict("REQ-10", "partial")])
        with mock.patch(_TARGET, return_value=_report(regressed_verdicts)):
            event = w.poll()
        self.assertEqual(event.severity, "WARNING")
        self.assertAlmostEqual(event.delta, 0.20)
        self.assertEqual(set(event.requirements_lost), {"REQ-09", "REQ-10"})

    def test_poll_returns_CRITICAL_when_severe_drift(self):
        w = _make_watcher()
        baseline = _report([_verdict(f"REQ-{i:02d}", "implemented") for i in range(1, 11)])
        with mock.patch(_TARGET, return_value=baseline):
            w.set_baseline()
        # 5/10 -> delta 0.50.
        regressed_verdicts = [_verdict(f"REQ-{i:02d}", "implemented") for i in range(1, 6)]
        regressed_verdicts.extend(
            [_verdict(f"REQ-{i:02d}", "missing") for i in range(6, 11)]
        )
        with mock.patch(_TARGET, return_value=_report(regressed_verdicts)):
            event = w.poll()
        self.assertEqual(event.severity, "CRITICAL")
        self.assertAlmostEqual(event.delta, 0.50)
        self.assertEqual(len(event.requirements_lost), 5)

    def test_requirements_lost_correctly_diffed(self):
        w = _make_watcher()
        baseline = _report([
            _verdict("REQ-01", "implemented"),
            _verdict("REQ-02", "implemented"),
            _verdict("REQ-03", "implemented"),
        ])
        with mock.patch(_TARGET, return_value=baseline):
            w.set_baseline()
        current = _report([
            _verdict("REQ-01", "implemented"),
            _verdict("REQ-02", "partial"),
            _verdict("REQ-03", "missing"),
        ])
        with mock.patch(_TARGET, return_value=current):
            event = w.poll()
        # Lost = baseline-satisfied minus current-satisfied = {REQ-02, REQ-03}.
        self.assertEqual(set(event.requirements_lost), {"REQ-02", "REQ-03"})
        # Tuple is sorted for determinism.
        self.assertEqual(event.requirements_lost, tuple(sorted(event.requirements_lost)))


# ---------------------------------------------------------------------------
# Lifecycle / edge cases
# ---------------------------------------------------------------------------


class TestLifecycle(unittest.TestCase):
    def test_stop_is_idempotent(self):
        w = _make_watcher()
        w.stop()
        w.stop()  # No raise.
        # After stop, poll raises a SpecDriftError so callers can detect it.
        with self.assertRaises(SpecDriftError):
            with mock.patch(_TARGET, return_value=_report([])):
                w.poll()

    def test_empty_spec_no_drift(self):
        w = _make_watcher()
        empty = _report([])
        with mock.patch(_TARGET, return_value=empty):
            w.set_baseline()
        with mock.patch(_TARGET, return_value=empty):
            event = w.poll()
        # No requirements means score is 1.0 by convention (vacuously satisfied),
        # and delta is 0.
        self.assertAlmostEqual(event.baseline_score, 1.0)
        self.assertAlmostEqual(event.current_score, 1.0)
        self.assertAlmostEqual(event.delta, 0.0)
        self.assertEqual(event.severity, "OK")
        self.assertEqual(event.requirements_lost, ())

    def test_improved_coverage_yields_OK_with_negative_delta(self):
        w = _make_watcher()
        baseline = _report([
            _verdict("REQ-01", "missing"),
            _verdict("REQ-02", "missing"),
        ])
        with mock.patch(_TARGET, return_value=baseline):
            w.set_baseline()
        improved = _report([
            _verdict("REQ-01", "implemented"),
            _verdict("REQ-02", "implemented"),
        ])
        with mock.patch(_TARGET, return_value=improved):
            event = w.poll()
        self.assertEqual(event.severity, "OK")
        self.assertLess(event.delta, 0.0)
        self.assertEqual(event.requirements_lost, ())


if __name__ == "__main__":
    unittest.main()
