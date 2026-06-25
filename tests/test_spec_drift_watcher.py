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

    def test_set_baseline_invokes_check_compliance_exactly_once(self):
        """Regression: set_baseline() must read state ATOMICALLY.

        Previously ``set_baseline(snapshot=None)`` called
        ``check_compliance`` twice — once via ``self.snapshot()`` and a
        second time via ``self._reread_satisfied_ids()`` — so the
        baseline dataclass and the cached id set could be derived from
        two independent reads. With LLM non-determinism (or any spec /
        working-tree change between calls) the two shards then
        disagreed, producing incoherent ``poll()`` events later
        (e.g. ``severity='OK'`` with non-empty ``requirements_lost``).

        This test pins the contract that ``set_baseline()`` performs a
        SINGLE ``check_compliance`` invocation and derives both the
        snapshot and the id set from the same verdicts list.
        """
        w = _make_watcher()
        # Two reads with DIFFERENT satisfied sets — the bug surfaced
        # only when the two internal reads disagreed.
        first_report = _report([
            _verdict(f"REQ-{i:02d}", "implemented") for i in range(1, 6)
        ])  # 5 satisfied / 5 total
        second_report = _report([
            _verdict(f"REQ-{i:02d}", "implemented") for i in range(1, 8)
        ])  # 7 satisfied / 7 total — DIFFERENT shape
        with mock.patch(
            _TARGET, side_effect=[first_report, second_report]
        ) as patched:
            w.set_baseline()
        # Only one call is allowed — the second read in the legacy code
        # is what introduced the cross-call inconsistency.
        self.assertEqual(patched.call_count, 1)
        # And the two state shards must agree: the dataclass's
        # requirements_satisfied count must match the cached id-set
        # size. Before the fix they came from different reads, so this
        # assertion would fail (5 != 7).
        self.assertEqual(
            w._baseline.requirements_satisfied,
            len(w._baseline_ids),
        )

    def test_set_baseline_yields_coherent_poll_event(self):
        """Regression: set_baseline + poll must produce a coherent event.

        With the legacy two-call ``set_baseline()`` an immediate
        ``poll()`` against the FIRST report could report
        ``severity='OK'`` (score-based, no drift) while
        ``requirements_lost`` contained REQs (id-based, two lost),
        because the cached id set came from the second internal read.
        Post-fix the cached id set matches the baseline snapshot, so an
        identical-input poll is fully OK with empty
        ``requirements_lost``.
        """
        w = _make_watcher()
        baseline_report = _report([
            _verdict(f"REQ-{i:02d}", "implemented") for i in range(1, 6)
        ])  # 5 satisfied / 5 total
        diverging_report = _report([
            _verdict(f"REQ-{i:02d}", "implemented") for i in range(1, 8)
        ])  # 7 satisfied / 7 total — diverges from baseline_report
        with mock.patch(
            _TARGET, side_effect=[baseline_report, diverging_report]
        ):
            w.set_baseline()
        # Now poll() against the SAME baseline_report. If the cached id
        # set came from the diverging second read (the bug), this
        # would produce delta=0.0 with non-empty requirements_lost.
        with mock.patch(_TARGET, return_value=baseline_report):
            event = w.poll()
        self.assertEqual(event.severity, "OK")
        self.assertAlmostEqual(event.delta, 0.0)
        self.assertEqual(event.requirements_lost, ())

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

    def test_set_baseline_docstring_matches_caller_supplied_id_set_behavior(self):
        """Regression: ``set_baseline(snapshot)`` docstring must reflect that
        the satisfied-id set is reset to empty (not "rebuilt") when the caller
        supplies a snapshot.

        Pre-fix the docstring read "Either way the satisfied-id set is rebuilt
        so requirements_lost can be computed on later polls." That sentence
        was false on the caller-supplied branch: the implementation assigns
        ``self._baseline_ids = set()`` (empty, not rebuilt), and a follow-up
        ``poll()`` therefore returns ``requirements_lost=()`` even when REQs
        have regressed. Users reading the docstring assumed id-level drift
        worked after ``set_baseline(snapshot)`` and silently got empty
        results.

        This regression test pins three contracts at once:

        1. The docstring no longer carries the misleading "Either way the
           satisfied-id set is rebuilt" sentence.
        2. The docstring documents the actual caller-supplied behavior
           (empty id set / no per-id drift detection).
        3. The behavior itself is unchanged: a caller-supplied baseline
           causes ``poll()`` to report ``requirements_lost=()`` even when
           specific REQs regressed score-wise.
        """
        import textwrap
        doc = textwrap.dedent(SpecDriftWatcher.set_baseline.__doc__ or "")
        # Pin (1): the misleading "Either way ... rebuilt" sentence is gone.
        self.assertNotIn(
            "Either way the satisfied-id set is rebuilt",
            doc,
            "set_baseline docstring still carries the pre-fix lie that the "
            "satisfied-id set is rebuilt on both branches; the caller-"
            "supplied branch actually resets it to empty.",
        )
        # Pin (2): the docstring mentions the caller-supplied empty-set
        # contract using a recognizable token. We accept either "empty"
        # or "empty set" so future rewordings retain freedom.
        self.assertIn(
            "empty",
            doc.lower(),
            "set_baseline docstring no longer documents the caller-supplied "
            "branch's empty-id-set behavior; users will assume "
            "requirements_lost works after set_baseline(snapshot).",
        )
        # Pin (3): behavior matches the documented contract — a caller-
        # supplied baseline does NOT compute requirements_lost even when
        # REQs regressed score-wise.
        w = _make_watcher()
        # Caller hands the watcher a fully-satisfied baseline snapshot.
        snap = SpecDriftSnapshot(
            score=1.0,
            requirements_total=3,
            requirements_satisfied=3,
            timestamp_iso="2026-06-24T00:00:00Z",
        )
        w.set_baseline(snap)
        # Now poll() observes a regression: REQ-02 and REQ-03 lost.
        current = _report([
            _verdict("REQ-01", "implemented"),
            _verdict("REQ-02", "partial"),
            _verdict("REQ-03", "missing"),
        ])
        with mock.patch(_TARGET, return_value=current):
            event = w.poll()
        # Score-based severity still fires (delta = 1.0 - 1/3 ~= 0.667).
        self.assertGreater(event.delta, 0.0)
        # But id-based drift is empty (because the id set was reset).
        # This is the documented behavior — and it must stay documented.
        self.assertEqual(
            event.requirements_lost,
            (),
            "Caller-supplied baseline should yield empty requirements_lost "
            "(documented behavior). If this assertion changes, the "
            "set_baseline docstring must be re-audited.",
        )


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
