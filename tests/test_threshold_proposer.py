"""Tests for the C5 threshold proposer (`threshold_proposer`).

Covers the AC list in spec §7.2:

1.  Below-window evidence -> None.
2.  Stable in-band evidence -> None.
3.  Above-band tail-of-window -> positive delta proposal.
4.  Below-band tail-of-window -> negative delta proposal.
5.  Delta clamped at ``max_delta_pct``.
6.  Deterministic ``proposal_id`` over identical inputs.
7.  Slug + created_at preserved on byte-identical re-emit.
8.  ``enable_drift_band_proposals=False`` blocks drift-band targets.
9.  Concurrent writers serialize via filelock.
10. Missing ``_bmad/calibration/`` created lazily.
11. Missing ``_bmad/gate/verdicts/`` returns ``None``.
12. Gates missing target_category / actual.coverage_pct dropped.
13. ``reject_proposal`` appends reject; proposal JSON unchanged.
14. Auto-supersede of a prior PENDING proposal; does NOT supersede an
    accepted prior.
15. ``evidence_window`` sorted by gate_id ASCII; deterministic across
    mtimes.
16. ``ProposerConfigError`` when ``min_evidence_window < consecutive_runs``.
17. Calibration table missing -> rationale omits calibration sentence.

All tests run inside a tempdir; nothing touches the real ``_bmad/``.
The target module is the live ``story_automator.core.gate_rules`` so
``current_value`` reads against the actual ``PRIORITY_THRESHOLDS``
constants (``P0=100, P1=95, P2=85, P3=70``). Tests target ``P3=70`` so
the synthetic coverage windows can comfortably sit either side of the
threshold without colliding with the real-world live values.
"""

from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from story_automator.core.evidence_io import persist_gate_file
from story_automator.core.gate_schema import make_gate_file
from story_automator.core.innovation.threshold_decisions import (
    ACTION_ACCEPT,
    ACTION_REJECT,
    latest_decision_for,
    load_decisions,
    record_decision,
)
from story_automator.core.innovation.threshold_proposer import (
    DRIFT_BAND_SYMBOLS,
    MAX_PROPOSAL_AGE_HOURS,
    MAX_REPR_BYTES,
    PROPOSAL_SCHEMA_VERSION,
    ProposerConfigError,
    ThresholdProposal,
    ThresholdProposer,
    proposals_dir,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _build_gate(
    *,
    gate_id: str,
    category: str = "correctness",
    priority: str = "P3",
    coverage_pct: float | None = 80.0,
    overall: str = "PASS",
    include_actual: bool = True,
) -> dict:
    """Build a minimal validated gate file with one category carrying
    the ``required.priority`` + ``actual.coverage_pct`` shape that the
    proposer reads (spec §3 + §7.1 AC-P-00)."""
    cat: dict = {
        "verdict": overall,
        "required": {"priority": priority},
    }
    if include_actual and coverage_pct is not None:
        cat["actual"] = {"coverage_pct": coverage_pct}
    return make_gate_file(
        gate_id=gate_id,
        target={"kind": "story", "id": f"E1.S{gate_id[-2:]}"},
        commit_sha="cafefeed" + gate_id.replace("-", "")[-6:].rjust(6, "0"),
        profile={"id": "default", "version": 1, "hash": "11223344"},
        factory_version="0.1.0",
        categories={category: cat},
        overall=overall,
    )


def _populate_window(
    project_root: Path,
    coverages: list[float],
    *,
    priority: str = "P3",
    category: str = "correctness",
    base_id: str = "gate",
) -> list[str]:
    """Persist N gate files under ``_bmad/gate/verdicts/`` with the given
    coverages; returns the ASCII-sorted gate_id list (matches what the
    proposer will see)."""
    ids = []
    for i, cov in enumerate(coverages):
        gid = f"{base_id}-{i:03d}"
        ids.append(gid)
        gate = _build_gate(
            gate_id=gid,
            category=category,
            priority=priority,
            coverage_pct=cov,
        )
        persist_gate_file(project_root, gate)
    return sorted(ids)


def _current_gate(
    *,
    priority: str = "P3",
    coverage_pct: float = 90.0,
) -> dict:
    """A 'just-completed' gate file passed to ``observe_gate``."""
    return _build_gate(
        gate_id="gate-fresh",
        priority=priority,
        coverage_pct=coverage_pct,
    )


# ---------------------------------------------------------------------------
# Module-level dataclass + invariant sanity
# ---------------------------------------------------------------------------


class TestModuleSurface(unittest.TestCase):
    def test_drift_band_symbols_closed_set(self) -> None:
        self.assertEqual(
            DRIFT_BAND_SYMBOLS,
            frozenset({"STABLE_MAX", "MINOR_MAX", "MAJOR_MAX"}),
        )

    def test_constants_pinned(self) -> None:
        self.assertEqual(PROPOSAL_SCHEMA_VERSION, 1)
        self.assertEqual(MAX_PROPOSAL_AGE_HOURS, 168)
        self.assertEqual(MAX_REPR_BYTES, 24)

    def test_proposal_dataclass_type_invariant(self) -> None:
        """``type(proposed) is type(current)`` — int->float crosses fail."""
        with self.assertRaises(ValueError):
            ThresholdProposal(
                proposal_id="0a1b2c3d4e5f6789",
                target_module="m",
                target_symbol="s",
                target_category="correctness",
                target_file_hint="",
                selector={"kind": "name", "name": "x"},
                current_value=95,
                proposed_value=92.0,  # type mismatch
                delta=-3,
                rationale="r",
                evidence_window=("a", "b"),
                created_at_iso="2026-06-23T00:00:00Z",
                confirm_slug="deadbeef",
            )


# ---------------------------------------------------------------------------
# AC §7.2-16 — ProposerConfigError
# ---------------------------------------------------------------------------


class TestProposerConfigError(unittest.TestCase):
    def test_min_window_less_than_consecutive_runs_rejected(self) -> None:
        with self.assertRaises(ProposerConfigError):
            ThresholdProposer(min_evidence_window=2, consecutive_runs=3)

    def test_zero_consecutive_runs_rejected(self) -> None:
        with self.assertRaises(ProposerConfigError):
            ThresholdProposer(consecutive_runs=0)

    def test_band_outside_zero_to_one_rejected(self) -> None:
        with self.assertRaises(ProposerConfigError):
            ThresholdProposer(target_pass_rate_band=(1.5, 2.0))
        with self.assertRaises(ProposerConfigError):
            ThresholdProposer(target_pass_rate_band=(0.9, 0.8))  # lo >= hi

    def test_defaults_construct_cleanly(self) -> None:
        proposer = ThresholdProposer()
        self.assertEqual(proposer.min_evidence_window, 5)
        self.assertEqual(proposer.consecutive_runs, 3)
        self.assertEqual(proposer.target_pass_rate_band, (0.80, 0.95))
        self.assertEqual(proposer.max_delta_pct, 5)
        self.assertFalse(proposer.enable_drift_band_proposals)


# ---------------------------------------------------------------------------
# AC §7.2-1 — Below-window evidence -> None
# ---------------------------------------------------------------------------


class TestBelowWindow(unittest.TestCase):
    def test_too_few_matching_gates_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # Only 3 gates persisted but min_evidence_window=5.
            _populate_window(root, [85.0, 86.0, 87.0], priority="P3")
            proposer = ThresholdProposer()
            result = proposer.observe_gate(root, _current_gate(priority="P3"))
            self.assertIsNone(result)


# ---------------------------------------------------------------------------
# AC §7.2-2 — Stable in-band evidence -> None
# ---------------------------------------------------------------------------


class TestStableInBand(unittest.TestCase):
    def test_mixed_pass_fail_tail_returns_none(self) -> None:
        """When the tail-of-window is mixed (some pass, some fail at the
        current threshold), the proposer returns None — only uniform
        tails trigger a proposal."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # Mixed coverages around 70 (P3 threshold).
            _populate_window(root, [60.0, 80.0, 65.0, 85.0, 68.0], priority="P3")
            proposer = ThresholdProposer()
            result = proposer.observe_gate(root, _current_gate(priority="P3"))
            self.assertIsNone(result)


# ---------------------------------------------------------------------------
# AC §7.2-3 — Above-band tail-of-window -> positive delta
# ---------------------------------------------------------------------------


class TestAboveBandRaise(unittest.TestCase):
    def test_all_tail_pass_emits_positive_delta_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # P3 threshold=70. All 5 entries >= 70, last 3 entries all
            # well above → observed_mean=1.0 > 0.95 → raise. Mean
            # coverage ~85.0 → ceil=85 → delta=15 → clamped to 5 → 75.
            _populate_window(root, [82.0, 84.0, 85.0, 87.0, 87.0], priority="P3")
            proposer = ThresholdProposer()
            proposal = proposer.observe_gate(root, _current_gate(priority="P3"))
            self.assertIsNotNone(proposal)
            assert proposal is not None
            self.assertEqual(proposal.target_symbol, "PRIORITY_THRESHOLDS")
            self.assertEqual(proposal.target_category, "correctness")
            self.assertEqual(proposal.selector["key"], "P3")
            self.assertEqual(proposal.current_value, 70)
            self.assertEqual(proposal.proposed_value, 75)
            self.assertEqual(proposal.delta, 5)
            # Disk: proposal JSON exists under .../proposals/<id>.json.
            written = proposals_dir(root) / f"{proposal.proposal_id}.json"
            self.assertTrue(written.is_file())
            data = json.loads(written.read_text("utf-8"))
            self.assertEqual(data["confirm_slug"], proposal.confirm_slug)
            self.assertEqual(data["schema_version"], PROPOSAL_SCHEMA_VERSION)


# ---------------------------------------------------------------------------
# AC §7.2-4 — Below-band tail-of-window -> negative delta
# ---------------------------------------------------------------------------


class TestBelowBandLower(unittest.TestCase):
    def test_all_tail_fail_emits_negative_delta_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # P3 threshold=70. All entries < 70, observed_mean=0.0 < 0.80.
            # Mean=63 → floor=63 → delta=-7 → clamped to -5 → 65.
            _populate_window(root, [60.0, 62.0, 63.0, 65.0, 65.0], priority="P3")
            proposer = ThresholdProposer()
            proposal = proposer.observe_gate(root, _current_gate(priority="P3"))
            self.assertIsNotNone(proposal)
            assert proposal is not None
            self.assertEqual(proposal.current_value, 70)
            self.assertEqual(proposal.proposed_value, 65)
            self.assertEqual(proposal.delta, -5)


# ---------------------------------------------------------------------------
# AC §7.2-5 — Delta clamped at max_delta_pct
# ---------------------------------------------------------------------------


class TestDeltaClamp(unittest.TestCase):
    def test_extreme_above_band_clamped_to_max_delta(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # P3 threshold=70. All coverage=100 → mean=100, ceil=100,
            # delta=30 → clamped to max_delta_pct=5 → proposed=75.
            _populate_window(root, [100.0] * 5, priority="P3")
            proposer = ThresholdProposer(max_delta_pct=5)
            proposal = proposer.observe_gate(root, _current_gate(priority="P3"))
            self.assertIsNotNone(proposal)
            assert proposal is not None
            self.assertEqual(proposal.proposed_value, 75)
            self.assertEqual(proposal.delta, 5)

    def test_extreme_below_band_clamped_to_neg_max_delta(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _populate_window(root, [10.0] * 5, priority="P3")
            proposer = ThresholdProposer(max_delta_pct=5)
            proposal = proposer.observe_gate(root, _current_gate(priority="P3"))
            self.assertIsNotNone(proposal)
            assert proposal is not None
            self.assertEqual(proposal.proposed_value, 65)
            self.assertEqual(proposal.delta, -5)


# ---------------------------------------------------------------------------
# AC §7.2-6 — Deterministic proposal_id over identical inputs
# ---------------------------------------------------------------------------


class TestDeterministicId(unittest.TestCase):
    def test_two_proposers_same_evidence_same_id(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _populate_window(root, [82.0, 84.0, 85.0, 87.0, 87.0], priority="P3")
            p1 = ThresholdProposer()
            proposal1 = p1.observe_gate(root, _current_gate(priority="P3"))
            self.assertIsNotNone(proposal1)
            assert proposal1 is not None
            # A second proposer (fresh instance) on the SAME evidence
            # MUST produce the SAME proposal_id — proves the hash is
            # over inputs, never over wall-clock or random state.
            p2 = ThresholdProposer()
            proposal2 = p2.observe_gate(root, _current_gate(priority="P3"))
            self.assertIsNotNone(proposal2)
            assert proposal2 is not None
            self.assertEqual(proposal1.proposal_id, proposal2.proposal_id)


# ---------------------------------------------------------------------------
# AC §7.2-7 — Slug + created_at preserved on byte-identical re-emit
# ---------------------------------------------------------------------------


class TestIdempotentReEmit(unittest.TestCase):
    def test_re_emit_preserves_slug_and_created_at_bytewise(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _populate_window(root, [82.0, 84.0, 85.0, 87.0, 87.0], priority="P3")
            proposer = ThresholdProposer()
            first = proposer.observe_gate(root, _current_gate(priority="P3"))
            self.assertIsNotNone(first)
            assert first is not None
            target = proposals_dir(root) / f"{first.proposal_id}.json"
            before_bytes = target.read_bytes()
            before_mtime = target.stat().st_mtime_ns
            # Sleep so a write would be visible in mtime.
            time.sleep(0.01)

            second = proposer.observe_gate(root, _current_gate(priority="P3"))
            self.assertIsNotNone(second)
            assert second is not None
            self.assertEqual(first.proposal_id, second.proposal_id)
            self.assertEqual(first.confirm_slug, second.confirm_slug)
            self.assertEqual(first.created_at_iso, second.created_at_iso)
            # Disk is BYTE-identical and mtime did NOT advance — the
            # idempotent path bails before write_atomic_text runs.
            self.assertEqual(target.read_bytes(), before_bytes)
            self.assertEqual(target.stat().st_mtime_ns, before_mtime)


# ---------------------------------------------------------------------------
# AC §7.2-8 — enable_drift_band_proposals=False blocks drift bands
# ---------------------------------------------------------------------------


class TestDriftBandGate(unittest.TestCase):
    def test_drift_band_target_blocked_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _populate_window(root, [82.0, 84.0, 85.0, 87.0, 87.0], priority="P3")
            proposer = ThresholdProposer(target_symbol="MINOR_MAX")
            # Default enable_drift_band_proposals=False → None even when
            # the evidence window would otherwise warrant a proposal.
            self.assertIsNone(proposer.observe_gate(root, _current_gate(priority="P3")))


# ---------------------------------------------------------------------------
# AC §7.2-9 — Concurrent writers serialize via filelock
# ---------------------------------------------------------------------------


class TestConcurrentWrites(unittest.TestCase):
    def test_concurrent_observe_gate_serialize(self) -> None:
        """Two threads racing to write the SAME proposal_id: filelock
        serializes; both calls succeed; the second observes the existing
        file via the idempotent re-emit path. Disk contents are
        byte-identical to the first writer's bytes."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _populate_window(root, [82.0, 84.0, 85.0, 87.0, 87.0], priority="P3")
            results: list[ThresholdProposal | None] = [None, None]

            def _worker(i: int) -> None:
                proposer = ThresholdProposer()
                results[i] = proposer.observe_gate(root, _current_gate(priority="P3"))

            t1 = threading.Thread(target=_worker, args=(0,))
            t2 = threading.Thread(target=_worker, args=(1,))
            t1.start()
            t2.start()
            t1.join(timeout=30)
            t2.join(timeout=30)
            self.assertIsNotNone(results[0])
            self.assertIsNotNone(results[1])
            assert results[0] is not None and results[1] is not None
            # Same deterministic id; same slug (re-emit preserves it).
            self.assertEqual(results[0].proposal_id, results[1].proposal_id)
            self.assertEqual(results[0].confirm_slug, results[1].confirm_slug)
            # Exactly one proposal on disk.
            proposals = list(proposals_dir(root).iterdir())
            self.assertEqual(len(proposals), 1)


# ---------------------------------------------------------------------------
# AC §7.2-10 — Missing _bmad/calibration/ created lazily
# ---------------------------------------------------------------------------


class TestLazyCalibrationDir(unittest.TestCase):
    def test_first_observe_creates_calibration_dir(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _populate_window(root, [82.0, 84.0, 85.0, 87.0, 87.0], priority="P3")
            # _bmad/gate/verdicts/ exists (populate created it) but
            # _bmad/calibration/ does NOT.
            self.assertFalse((root / "_bmad" / "calibration").exists())
            proposer = ThresholdProposer()
            proposal = proposer.observe_gate(root, _current_gate(priority="P3"))
            self.assertIsNotNone(proposal)
            self.assertTrue((root / "_bmad" / "calibration" / "proposals").is_dir())


# ---------------------------------------------------------------------------
# AC §7.2-11 — Missing _bmad/gate/verdicts/ returns None
# ---------------------------------------------------------------------------


class TestMissingVerdictsDir(unittest.TestCase):
    def test_no_verdicts_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # No persist_gate_file calls; _bmad/gate/verdicts does NOT
            # exist.
            self.assertFalse((root / "_bmad" / "gate" / "verdicts").exists())
            proposer = ThresholdProposer()
            self.assertIsNone(proposer.observe_gate(root, _current_gate(priority="P3")))


# ---------------------------------------------------------------------------
# AC §7.2-12 — Gates missing target_category or actual.coverage_pct dropped
# ---------------------------------------------------------------------------


class TestDroppedGates(unittest.TestCase):
    def test_gates_without_coverage_dropped_from_window(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # 5 gates: 2 with valid coverage, 3 without -> window count
            # is 2 < min_evidence_window=5 -> None.
            for i, cov in enumerate([82.0, 84.0]):
                persist_gate_file(
                    root,
                    _build_gate(
                        gate_id=f"gate-{i:03d}",
                        coverage_pct=cov,
                        priority="P3",
                    ),
                )
            for i in range(3):
                persist_gate_file(
                    root,
                    _build_gate(
                        gate_id=f"gate-{i + 100:03d}",
                        priority="P3",
                        include_actual=False,
                    ),
                )
            proposer = ThresholdProposer()
            self.assertIsNone(proposer.observe_gate(root, _current_gate(priority="P3")))

    def test_gates_with_wrong_priority_dropped(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # All 5 gates marked P0 — observe_gate is called with a P3
            # current gate, so the priority registry binds it to P3 and
            # the persisted P0 gates do not match.
            for i, cov in enumerate([82.0, 84.0, 85.0, 87.0, 87.0]):
                persist_gate_file(
                    root,
                    _build_gate(
                        gate_id=f"gate-{i:03d}",
                        coverage_pct=cov,
                        priority="P0",
                    ),
                )
            proposer = ThresholdProposer()
            self.assertIsNone(proposer.observe_gate(root, _current_gate(priority="P3")))


# ---------------------------------------------------------------------------
# AC §7.2-13 — reject_proposal appends reject; proposal JSON unchanged
# ---------------------------------------------------------------------------


class TestRejectProposal(unittest.TestCase):
    def test_reject_appends_decision_without_touching_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _populate_window(root, [82.0, 84.0, 85.0, 87.0, 87.0], priority="P3")
            proposer = ThresholdProposer()
            proposal = proposer.observe_gate(root, _current_gate(priority="P3"))
            self.assertIsNotNone(proposal)
            assert proposal is not None
            target = proposals_dir(root) / f"{proposal.proposal_id}.json"
            before_bytes = target.read_bytes()

            proposer.reject_proposal(
                root,
                proposal.proposal_id,
                "need 2 more weeks of telemetry",
            )

            # Proposal JSON byte-identical post-reject.
            self.assertEqual(target.read_bytes(), before_bytes)
            # Decisions ledger has one reject for this proposal.
            decisions = load_decisions(root, proposal_id=proposal.proposal_id)
            self.assertEqual(len(decisions), 1)
            self.assertEqual(decisions[0].action, "reject")
            self.assertEqual(decisions[0].operator_note, "need 2 more weeks of telemetry")

    def test_reject_unknown_id_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            proposer = ThresholdProposer()
            with self.assertRaises(FileNotFoundError):
                proposer.reject_proposal(root, "0123456789abcdef", "n/a")


# ---------------------------------------------------------------------------
# AC §7.2-14 — Auto-supersede prior PENDING; not an accepted prior
# ---------------------------------------------------------------------------


class TestAutoSupersede(unittest.TestCase):
    def _seed_pending_proposal(self, root: Path) -> str:
        """Seed a pending proposal on the same (module, symbol, selector)
        as the live registry by constructing one directly via the
        ``ThresholdProposal`` dataclass + ``write_atomic_text``.

        Tests that follow then observe a NEW proposal with DIFFERENT
        evidence_window (hence different proposal_id) — the auto-
        supersede branch should append a ``superseded`` decision for
        the seeded one.
        """
        from story_automator.core.atomic_io import write_atomic_text
        from story_automator.core.common import compact_json

        proposals_dir(root, create=True)
        seeded = ThresholdProposal(
            proposal_id="1111aaaabbbbcccc",
            target_module="story_automator.core.gate_rules",
            target_symbol="PRIORITY_THRESHOLDS",
            target_category="correctness",
            target_file_hint="",
            selector={"kind": "dict_tuple_element", "key": "P3", "index": 0},
            current_value=70,
            proposed_value=72,
            delta=2,
            rationale="seeded",
            evidence_window=("seed-001", "seed-002"),
            created_at_iso="2026-06-22T00:00:00Z",
            confirm_slug="deadbeef",
        )
        write_atomic_text(
            proposals_dir(root) / f"{seeded.proposal_id}.json",
            compact_json(seeded.to_dict()),
        )
        return seeded.proposal_id

    def test_pending_prior_is_superseded(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            prior_id = self._seed_pending_proposal(root)
            _populate_window(root, [82.0, 84.0, 85.0, 87.0, 87.0], priority="P3")
            proposer = ThresholdProposer()
            new = proposer.observe_gate(root, _current_gate(priority="P3"))
            self.assertIsNotNone(new)
            assert new is not None
            # Prior pending now has a "superseded" decision.
            latest = latest_decision_for(root, prior_id)
            self.assertIsNotNone(latest)
            assert latest is not None
            self.assertEqual(latest.action, "superseded")
            # And the supersede note references the new id.
            self.assertIn(new.proposal_id, latest.operator_note)

    def test_accepted_prior_is_not_superseded(self) -> None:
        """Spec §3: a prior with ``latest_decision == accept`` is NOT
        auto-superseded (the operator already chose to act on it)."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            prior_id = self._seed_pending_proposal(root)
            # Mark the seeded prior as accepted.
            record_decision(root, prior_id, ACTION_ACCEPT, "local", "")
            _populate_window(root, [82.0, 84.0, 85.0, 87.0, 87.0], priority="P3")
            proposer = ThresholdProposer()
            new = proposer.observe_gate(root, _current_gate(priority="P3"))
            self.assertIsNotNone(new)
            # Last decision for the prior is still "accept" — no
            # "superseded" appended.
            latest = latest_decision_for(root, prior_id)
            self.assertIsNotNone(latest)
            assert latest is not None
            self.assertEqual(latest.action, "accept")

    def test_rejected_prior_is_not_superseded(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            prior_id = self._seed_pending_proposal(root)
            record_decision(root, prior_id, ACTION_REJECT, "local", "n/a")
            _populate_window(root, [82.0, 84.0, 85.0, 87.0, 87.0], priority="P3")
            proposer = ThresholdProposer()
            new = proposer.observe_gate(root, _current_gate(priority="P3"))
            self.assertIsNotNone(new)
            latest = latest_decision_for(root, prior_id)
            self.assertIsNotNone(latest)
            assert latest is not None
            self.assertEqual(latest.action, "reject")


# ---------------------------------------------------------------------------
# AC §7.2-15 — evidence_window sorted by gate_id ASCII (mtime-independent)
# ---------------------------------------------------------------------------


class TestEvidenceWindowSortOrder(unittest.TestCase):
    def test_window_sorted_ascending_by_gate_id(self) -> None:
        """Persist gate files in REVERSE-id order with descending mtimes;
        the proposer must still sort by ASCII gate_id and produce the
        same evidence_window."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # Persist in reverse order to deliberately spread mtimes
            # backwards relative to the lexicographic sort.
            coverages_by_id = [
                ("gate-004", 87.0),
                ("gate-003", 87.0),
                ("gate-002", 85.0),
                ("gate-001", 84.0),
                ("gate-000", 82.0),
            ]
            for gid, cov in coverages_by_id:
                persist_gate_file(
                    root,
                    _build_gate(
                        gate_id=gid,
                        priority="P3",
                        coverage_pct=cov,
                    ),
                )
                # Tiny pause so mtimes differ and the descending insert
                # order produces a descending-mtime sequence.
                time.sleep(0.01)
            proposer = ThresholdProposer()
            proposal = proposer.observe_gate(root, _current_gate(priority="P3"))
            self.assertIsNotNone(proposal)
            assert proposal is not None
            # Window is ASCII-sorted regardless of insertion order or
            # mtime; the lexicographic order is 000..004.
            self.assertEqual(
                proposal.evidence_window,
                ("gate-000", "gate-001", "gate-002", "gate-003", "gate-004"),
            )


# ---------------------------------------------------------------------------
# AC §7.2-17 — Calibration table missing -> rationale omits calibration
# ---------------------------------------------------------------------------


class TestRationaleDegradesWithoutCalibration(unittest.TestCase):
    def test_rationale_omits_calibration_sentence_without_table(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _populate_window(root, [82.0, 84.0, 85.0, 87.0, 87.0], priority="P3")
            # Force the calibration importer to fail — pin the
            # "degrades gracefully" branch directly so this test passes
            # whether or not the optional M08 module exists. The helper
            # was split out of threshold_proposer into the sibling
            # threshold_proposer_helpers module in the C5 post-impl
            # review fold-in; patch where the function lives.
            import story_automator.core.innovation.threshold_proposer_helpers as helpers

            with mock.patch.object(helpers, "_maybe_calibration_sentence", return_value=""):
                proposer = ThresholdProposer()
                proposal = proposer.observe_gate(root, _current_gate(priority="P3"))
            self.assertIsNotNone(proposal)
            assert proposal is not None
            self.assertNotIn("Calibration", proposal.rationale)


# ---------------------------------------------------------------------------
# Extra surface coverage — list_proposals + load_proposal
# ---------------------------------------------------------------------------


class TestListAndLoad(unittest.TestCase):
    def test_list_empty_when_no_proposals_dir(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            proposer = ThresholdProposer()
            self.assertEqual(proposer.list_proposals(root), [])

    def test_list_after_emit_returns_one_descending_by_ts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _populate_window(root, [82.0, 84.0, 85.0, 87.0, 87.0], priority="P3")
            proposer = ThresholdProposer()
            proposal = proposer.observe_gate(root, _current_gate(priority="P3"))
            self.assertIsNotNone(proposal)
            listing = proposer.list_proposals(root)
            self.assertEqual(len(listing), 1)
            self.assertEqual(listing[0].proposal_id, proposal.proposal_id)

    def test_load_missing_raises_filenotfounderror(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            proposer = ThresholdProposer()
            with self.assertRaises(FileNotFoundError):
                proposer.load_proposal(root, "0123456789abcdef")

    def test_load_invalid_id_raises_filenotfounderror(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            proposer = ThresholdProposer()
            with self.assertRaises(FileNotFoundError):
                proposer.load_proposal(root, "not-hex")


# ---------------------------------------------------------------------------
# Bonus — gate_file with NA verdict for the target category is dropped
# ---------------------------------------------------------------------------


class TestNaCategory(unittest.TestCase):
    def test_na_category_treated_as_missing(self) -> None:
        """Spec §3: gates whose target category verdict is NA are dropped."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # 4 valid + 1 NA; matched count = 4 < min_evidence_window=5
            for i, cov in enumerate([82.0, 84.0, 85.0, 87.0]):
                persist_gate_file(
                    root,
                    _build_gate(
                        gate_id=f"gate-{i:03d}",
                        priority="P3",
                        coverage_pct=cov,
                    ),
                )
            # NA gate — must be dropped from the window.
            na_gate = make_gate_file(
                gate_id="gate-100",
                target={"kind": "story", "id": "E1.S100"},
                commit_sha="cafefeed111111",
                profile={"id": "default", "version": 1, "hash": "11223344"},
                factory_version="0.1.0",
                categories={
                    "correctness": {
                        "verdict": "NA",
                        "required": {"priority": "P3"},
                        "actual": {"coverage_pct": 100.0},
                    }
                },
                overall="PASS",
            )
            persist_gate_file(root, na_gate)
            proposer = ThresholdProposer()
            self.assertIsNone(proposer.observe_gate(root, _current_gate(priority="P3")))


# ---------------------------------------------------------------------------
# Bonus — current gate file priority must drive the run
# ---------------------------------------------------------------------------


class TestPriorityFromGateFile(unittest.TestCase):
    def test_unknown_priority_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # The "fresh" gate file carries priority "P9" which is not
            # in the target registry — observe_gate must return None
            # before touching the verdicts dir.
            _populate_window(root, [82.0] * 5, priority="P3")
            fresh = _build_gate(
                gate_id="gate-fresh",
                priority="P9",
                coverage_pct=90.0,
            )
            proposer = ThresholdProposer()
            self.assertIsNone(proposer.observe_gate(root, fresh))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
