"""Tests for :mod:`story_automator.core.innovation.cost_evidence`.

C3 — wires per-collector cost evidence emission into the orchestrator.
The module is responsible for producing :class:`GateCostReport` files
under ``_bmad/gate/cost/<gate_id>/`` (summary + per-collector JSON) and
is invoked from :func:`run_production_gate` / :func:`run_system_gate`
when the caller supplies a ``session_usage`` :class:`UsageMetrics`.

Tests cover three groups (matching the C3 task spec):

* emission — file layout, attribution selection, round-trip load.
* gate orchestrator — opt-in via ``session_usage`` kwarg, no-op when
  the kwarg is absent (byte-identical to baseline), cost emission
  never aborts the gate, system-gate symmetry.
* gate-file embed — ``cost_total_usd`` field added when session usage
  is provided, absent when it is not.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from story_automator.core.collector_config import CollectorConfig, CollectorOutcome
from story_automator.core.innovation.cost_evidence import (
    CostEvidenceError,
    GateCostReport,
    collector_cost_path,
    emit_gate_cost_report,
    get_cost_root_dir,
    load_collector_cost_share,
    load_gate_cost_report,
    summary_path,
)
from story_automator.core.usage_parsers import UsageMetrics


SESSION = UsageMetrics(
    input_tokens=1200,
    output_tokens=400,
    total_cost_usd=0.123456,
    tool_calls_count=12,
    duration_s=60.0,
)


def _make_outcome(
    collector_id: str,
    category: str,
    *,
    duration_ms: int = 1000,
    status: str = "ok",
) -> CollectorOutcome:
    """Build a minimal :class:`CollectorOutcome` for cost emission."""

    config = CollectorConfig(
        collector_id=collector_id,
        tool="tool-" + collector_id,
        category=category,
        build_cmd=lambda checkout, profile: [],
    )
    evidence: dict[str, Any] = {
        "collector": collector_id,
        "tool": "tool-" + collector_id,
        "category": category,
        "status": status,
        "duration_ms": duration_ms,
        "tool_calls_count": 0,
    }
    return CollectorOutcome(config=config, evidence=evidence)


# ---------------------------------------------------------------------------
# Group 1 — emission unit tests
# ---------------------------------------------------------------------------


class EmissionTests(unittest.TestCase):
    """Direct emit_gate_cost_report tests against a temp project root."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.gate_id = "g-emission-001"

    def test_emit_writes_summary_json(self) -> None:
        outcomes = [_make_outcome("ruff", "static")]
        emit_gate_cost_report(self.root, self.gate_id, SESSION, outcomes)
        sp = summary_path(self.root, self.gate_id)
        self.assertTrue(sp.is_file())
        data = json.loads(sp.read_text())
        self.assertEqual(data["gate_id"], self.gate_id)
        self.assertEqual(data["collector_count"], 1)
        self.assertEqual(data["attribution_mode"], "duration")

    def test_emit_writes_per_collector_json(self) -> None:
        outcomes = [
            _make_outcome("ruff", "static", duration_ms=1000),
            _make_outcome("mypy", "static", duration_ms=2000),
        ]
        emit_gate_cost_report(self.root, self.gate_id, SESSION, outcomes)
        ruff = collector_cost_path(self.root, self.gate_id, "ruff")
        mypy = collector_cost_path(self.root, self.gate_id, "mypy")
        self.assertTrue(ruff.is_file())
        self.assertTrue(mypy.is_file())
        ruff_data = json.loads(ruff.read_text())
        self.assertEqual(ruff_data["collector_id"], "ruff")
        self.assertIn("cost_usd", ruff_data)

    def test_emit_default_attribution_mode_is_duration(self) -> None:
        outcomes = [
            _make_outcome("a", "static", duration_ms=1000),
            _make_outcome("b", "static", duration_ms=3000),
        ]
        report = emit_gate_cost_report(
            self.root, self.gate_id, SESSION, outcomes,
        )
        self.assertEqual(report.attribution_mode, "duration")
        # Duration-weighted: b should get 3x a's cost share.
        a_share, b_share = report.per_collector
        self.assertGreater(b_share.cost_usd, a_share.cost_usd)

    def test_emit_uniform_when_durations_all_zero(self) -> None:
        outcomes = [
            _make_outcome("a", "static", duration_ms=0),
            _make_outcome("b", "static", duration_ms=0),
        ]
        report = emit_gate_cost_report(
            self.root, self.gate_id, SESSION, outcomes,
        )
        # Auto-fallback when no signal is available.
        self.assertEqual(report.attribution_mode, "uniform")
        a_share, b_share = report.per_collector
        self.assertAlmostEqual(a_share.cost_usd, b_share.cost_usd)

    def test_emit_round_trip_via_load(self) -> None:
        outcomes = [_make_outcome("ruff", "static")]
        sent = emit_gate_cost_report(self.root, self.gate_id, SESSION, outcomes)
        loaded = load_gate_cost_report(self.root, self.gate_id)
        self.assertIsNotNone(loaded)
        assert loaded is not None  # narrow for type checker
        self.assertEqual(loaded.gate_id, sent.gate_id)
        self.assertEqual(loaded.collector_count, sent.collector_count)
        self.assertEqual(loaded.attribution_mode, sent.attribution_mode)
        self.assertAlmostEqual(loaded.total_cost_usd, sent.total_cost_usd)
        share = load_collector_cost_share(self.root, self.gate_id, "ruff")
        self.assertIsNotNone(share)
        assert share is not None
        self.assertEqual(share.collector_id, "ruff")

    def test_emit_sum_of_shares_equals_session_total_within_rounding(self) -> None:
        outcomes = [
            _make_outcome("a", "static", duration_ms=11),
            _make_outcome("b", "static", duration_ms=17),
            _make_outcome("c", "static", duration_ms=23),
        ]
        report = emit_gate_cost_report(
            self.root, self.gate_id, SESSION, outcomes,
        )
        total = sum(s.cost_usd for s in report.per_collector)
        self.assertAlmostEqual(total, SESSION.total_cost_usd)
        self.assertAlmostEqual(total, report.total_cost_usd)

    def test_emit_empty_collector_list_raises_CostEvidenceError(self) -> None:
        with self.assertRaises(CostEvidenceError):
            emit_gate_cost_report(self.root, self.gate_id, SESSION, [])

    def test_emit_zero_session_usage_emits_zero_shares(self) -> None:
        outcomes = [_make_outcome("a", "static"), _make_outcome("b", "static")]
        zero = UsageMetrics()
        report = emit_gate_cost_report(self.root, self.gate_id, zero, outcomes)
        self.assertEqual(report.total_cost_usd, 0.0)
        for share in report.per_collector:
            self.assertEqual(share.cost_usd, 0.0)
            self.assertEqual(share.input_tokens, 0)
            self.assertEqual(share.output_tokens, 0)

    def test_summary_contains_collector_count(self) -> None:
        outcomes = [
            _make_outcome("a", "static"),
            _make_outcome("b", "docs"),
            _make_outcome("c", "process"),
        ]
        emit_gate_cost_report(self.root, self.gate_id, SESSION, outcomes)
        sp = summary_path(self.root, self.gate_id)
        data = json.loads(sp.read_text())
        self.assertEqual(data["collector_count"], 3)

    def test_atomic_write_no_partial_file(self) -> None:
        outcomes = [_make_outcome("a", "static")]
        emit_gate_cost_report(self.root, self.gate_id, SESSION, outcomes)
        sp = summary_path(self.root, self.gate_id)
        # Atomic write should leave no .tmp- siblings.
        siblings = list(sp.parent.iterdir())
        for sibling in siblings:
            self.assertFalse(
                sibling.name.startswith(".") and ".tmp-" in sibling.name,
                f"unexpected partial file: {sibling}",
            )

    def test_duplicate_collector_id_raises_symmetrically_across_modes(
        self,
    ) -> None:
        """Regression — duration mode used to silently collapse duplicate
        collector_ids into a single dict entry while still summing both
        outcomes into ``total_duration``. That produced a report with
        ``collector_count=1`` despite two outcomes being passed, and the
        surviving share's weight was computed against the wrong total.
        Meanwhile uniform mode raised via ``_require_collectors``.

        The duplicate-id guard runs BEFORE attribution dispatch so both
        modes reject the same illegal input symmetrically — and BEFORE
        the cost directory is touched (the per-collector ``.json`` files
        would otherwise clobber on disk too).
        """

        outcomes = [
            _make_outcome("ruff", "static", duration_ms=1000),
            _make_outcome("ruff", "docs", duration_ms=3000),
        ]
        cost_dir = get_cost_root_dir(self.root, self.gate_id)
        before = list(cost_dir.iterdir()) if cost_dir.is_dir() else []
        # Duration mode (the buggy path) must now raise.
        with self.assertRaises(CostEvidenceError) as ctx_dur:
            emit_gate_cost_report(
                self.root, self.gate_id, SESSION, outcomes,
                attribution_mode="duration",
            )
        self.assertIn("duplicate collector_id", str(ctx_dur.exception))
        # Uniform mode already raised; confirm parity (same exception
        # type, same trigger).
        with self.assertRaises(CostEvidenceError) as ctx_uni:
            emit_gate_cost_report(
                self.root, self.gate_id, SESSION, outcomes,
                attribution_mode="uniform",
            )
        self.assertIn("duplicate collector_id", str(ctx_uni.exception))
        # Pre-disk-touch invariant — neither call should have written
        # cost files for a rejected input.
        after = list(cost_dir.iterdir()) if cost_dir.is_dir() else []
        self.assertEqual(before, after)

    def test_invalid_attribution_mode_raises_before_disk_touch(self) -> None:
        outcomes = [_make_outcome("a", "static")]
        cost_dir = get_cost_root_dir(self.root, self.gate_id)
        before = list(cost_dir.iterdir()) if cost_dir.is_dir() else []
        with self.assertRaises(CostEvidenceError):
            emit_gate_cost_report(
                self.root, self.gate_id, SESSION, outcomes,
                attribution_mode="bogus",
            )
        after = list(cost_dir.iterdir()) if cost_dir.is_dir() else []
        self.assertEqual(before, after)

    def test_reserved_collector_id_summary_raises_before_disk_touch(
        self,
    ) -> None:
        """Regression — a collector with ``collector_id='summary'`` used
        to silently destroy its own share. The emit loop wrote
        ``<dir>/summary.json`` carrying the per-collector payload, then
        the gate-summary writer at the end of :func:`emit_gate_cost_report`
        clobbered that same path with the :class:`GateCostReport` payload.
        The per-collector record was permanently lost, the cost dir
        listing diverged from ``summary.json``'s ``per_collector`` tuple
        (breaking the "on-disk collector set always matches summary"
        invariant the prune step documents), and a subsequent
        :func:`load_collector_cost_share` call raised
        :class:`CostEvidenceError` ('malformed collector share') because
        the gate-summary payload has no ``collector_id`` field.

        Reachable in production because the registry does not validate
        ``collector_id`` against an internal-filename allowlist; any
        future meta/aggregator collector named "summary" would silently
        corrupt cost evidence.

        Fix: reserve ``summary`` (and any future internal filenames) at
        the duplicate-id guard so emission raises BEFORE touching disk
        — symmetric with the empty-list / duplicate-id / invalid-mode
        guards already in place.
        """

        outcomes = [
            _make_outcome("summary", "static", duration_ms=1000),
        ]
        cost_dir = get_cost_root_dir(self.root, self.gate_id)
        before = list(cost_dir.iterdir()) if cost_dir.is_dir() else []
        # Duration mode (the bug's natural reproducer).
        with self.assertRaises(CostEvidenceError) as ctx_dur:
            emit_gate_cost_report(
                self.root, self.gate_id, SESSION, outcomes,
                attribution_mode="duration",
            )
        self.assertIn(
            "collides with reserved internal filename",
            str(ctx_dur.exception),
        )
        self.assertIn("summary", str(ctx_dur.exception))
        # Uniform mode — same rejection for symmetry parity with the
        # duplicate-id / invalid-mode guards.
        with self.assertRaises(CostEvidenceError) as ctx_uni:
            emit_gate_cost_report(
                self.root, self.gate_id, SESSION, outcomes,
                attribution_mode="uniform",
            )
        self.assertIn(
            "collides with reserved internal filename",
            str(ctx_uni.exception),
        )
        # Pre-disk-touch invariant — neither call should have written
        # cost files for a rejected input, otherwise the summary.json
        # destruction window would still be reachable.
        after = list(cost_dir.iterdir()) if cost_dir.is_dir() else []
        self.assertEqual(before, after)

    def test_reserved_collector_id_summary_in_mixed_set_raises(self) -> None:
        """Even when one valid collector accompanies a reserved-id
        collector, emission must reject the batch before any disk
        write — otherwise the valid collector's share would land first
        and the gate-summary write would still overwrite the
        ``summary`` collector's slot, producing the same broken
        invariant the dedicated test above exercises.
        """

        outcomes = [
            _make_outcome("ruff", "static", duration_ms=1000),
            _make_outcome("summary", "static", duration_ms=1000),
        ]
        cost_dir = get_cost_root_dir(self.root, self.gate_id)
        before = list(cost_dir.iterdir()) if cost_dir.is_dir() else []
        with self.assertRaises(CostEvidenceError):
            emit_gate_cost_report(
                self.root, self.gate_id, SESSION, outcomes,
            )
        after = list(cost_dir.iterdir()) if cost_dir.is_dir() else []
        self.assertEqual(before, after)

    def test_path_traversal_collector_id_raises_before_disk_touch(
        self,
    ) -> None:
        """Regression — a collector_id containing ``..`` / ``/`` /
        ``\\`` joined onto the per-gate cost dir resolved OUTSIDE that
        dir. For ``collector_id='../escaped'`` the per-collector file
        landed at ``cost/escaped.json`` (a sibling of the gate dir)
        rather than ``cost/<gate_id>/escaped.json``.

        That broke three documented invariants at once:

        * the prune loop only scans ``cost_dir`` so leaked sibling
          files survived across emissions;
        * ``load_collector_cost_share`` silently round-tripped the
          leaked location because it used the same Path concatenation;
        * the on-disk per-collector set diverged from the persisted
          summary.json's ``per_collector`` tuple — the "on-disk
          collector set always matches summary" invariant the prune
          step documents.

        Reachable in production because the registry only checks for
        duplicate ids (see ``CollectorRegistry.register`` at
        ``collector_registry.py:25-33``) and ``CollectorConfig.collector_id``
        is an untyped ``str`` — a hand-registered config with a
        traversal id reaches emission. Reject BEFORE disk touch,
        symmetric with the reserved-name / duplicate-id / invalid-mode
        guards already in place.
        """

        cost_root = Path(self.root) / "_bmad" / "gate" / "cost"
        for bad_id in ("../escaped", "a/b", "a\\b", ".."):
            with self.subTest(bad_id=bad_id):
                outcomes = [
                    _make_outcome(bad_id, "static", duration_ms=1000),
                ]
                # Duration mode (the bug's natural reproducer).
                with self.assertRaises(CostEvidenceError) as ctx_dur:
                    emit_gate_cost_report(
                        self.root, self.gate_id, SESSION, outcomes,
                        attribution_mode="duration",
                    )
                self.assertIn(
                    "path traversal",
                    str(ctx_dur.exception),
                )
                # Uniform mode — symmetric rejection parity with the
                # duplicate-id / reserved-name guards.
                with self.assertRaises(CostEvidenceError) as ctx_uni:
                    emit_gate_cost_report(
                        self.root, self.gate_id, SESSION, outcomes,
                        attribution_mode="uniform",
                    )
                self.assertIn(
                    "path traversal",
                    str(ctx_uni.exception),
                )
                # Pre-disk-touch invariant — no per-collector file may
                # have leaked outside the per-gate directory.
                if cost_root.is_dir():
                    siblings = sorted(
                        p.name for p in cost_root.iterdir() if p.is_file()
                    )
                    self.assertEqual(
                        siblings, [],
                        f"traversal id {bad_id!r} leaked file(s) "
                        f"into cost root: {siblings}",
                    )

    def test_path_traversal_collector_id_in_mixed_set_raises(self) -> None:
        """Mixed valid + traversal-id batch must reject the whole batch
        before any disk write — otherwise the valid collector's share
        lands first, and a partial emit leaves an inconsistent cost dir
        even though emission ultimately fails."""

        outcomes = [
            _make_outcome("ruff", "static", duration_ms=1000),
            _make_outcome("../escaped", "static", duration_ms=1000),
        ]
        cost_dir = get_cost_root_dir(self.root, self.gate_id)
        before = list(cost_dir.iterdir()) if cost_dir.is_dir() else []
        with self.assertRaises(CostEvidenceError):
            emit_gate_cost_report(
                self.root, self.gate_id, SESSION, outcomes,
            )
        after = list(cost_dir.iterdir()) if cost_dir.is_dir() else []
        self.assertEqual(before, after)

    def test_control_char_collector_id_raises_before_disk_touch(
        self,
    ) -> None:
        """Regression — a collector_id containing an embedded NUL byte
        (e.g. ``'c\\x00null'``) passed the empty-list, duplicate-id,
        reserved-name AND path-traversal guards because ``Path(cid).parts``,
        ``'/' in cid`` and ``'\\\\' in cid`` all returned False for it. The
        flow then reached :func:`get_cost_root_dir` which CREATED the
        per-gate ``_bmad/gate/cost/<gate_id>/`` dir, and the subsequent
        :func:`write_atomic_text` call raised raw stdlib
        ``ValueError('lstat: embedded null character in path')`` from
        :meth:`Path.resolve` — breaching two contracts at once:

        * the :class:`CostEvidenceError` class docstring's "operator told
          us something illegal" promise (raw ValueError leaks instead of
          CostEvidenceError);
        * the pre-disk-touch invariant the sibling
          :meth:`test_path_traversal_collector_id_raises_before_disk_touch`
          pins (the gate dir gets created on a rejected input).

        The orchestrator's broad ``except Exception`` wraps the leak so
        it never aborts an in-flight gate, but cannot un-create the
        directory. Fix: fold NUL bytes and any ASCII control character
        into the path-traversal guard so emission rejects BEFORE disk
        touch, symmetric with the existing ``..`` / ``/`` / ``\\`` /
        reserved-name guards.
        """

        cost_root = Path(self.root) / "_bmad" / "gate" / "cost"
        # Cover the natural reproducer (\x00) plus a handful of other
        # ASCII control characters that would each independently trip
        # Path.resolve / OS file-naming rules on different platforms.
        for bad_id in ("c\x00null", "a\tb", "a\nb", "\x01leading"):
            with self.subTest(bad_id=bad_id):
                outcomes = [
                    _make_outcome(bad_id, "static", duration_ms=1000),
                ]
                # Duration mode (the bug's natural reproducer).
                with self.assertRaises(CostEvidenceError) as ctx_dur:
                    emit_gate_cost_report(
                        self.root, self.gate_id, SESSION, outcomes,
                        attribution_mode="duration",
                    )
                self.assertIn(
                    "path traversal",
                    str(ctx_dur.exception),
                )
                # Uniform mode — symmetric rejection parity with the
                # duplicate-id / reserved-name / path-traversal guards.
                with self.assertRaises(CostEvidenceError) as ctx_uni:
                    emit_gate_cost_report(
                        self.root, self.gate_id, SESSION, outcomes,
                        attribution_mode="uniform",
                    )
                self.assertIn(
                    "path traversal",
                    str(ctx_uni.exception),
                )
                # Pre-disk-touch invariant — the per-gate cost dir must
                # NOT have been created. Mirrors the sibling traversal
                # test's leaked-sibling-files check but stricter: a NUL
                # byte never reaches Path.resolve, so even the per-gate
                # dir creation by ``get_cost_root_dir`` should not fire.
                self.assertFalse(
                    (cost_root / self.gate_id).exists(),
                    f"control-char id {bad_id!r} created per-gate cost "
                    f"dir before rejection",
                )

    def test_report_is_frozen_dataclass(self) -> None:
        outcomes = [_make_outcome("a", "static")]
        report = emit_gate_cost_report(
            self.root, self.gate_id, SESSION, outcomes,
        )
        self.assertIsInstance(report, GateCostReport)
        with self.assertRaises(Exception):
            # Frozen dataclasses raise FrozenInstanceError on mutation.
            report.gate_id = "mutated"  # type: ignore[misc]

    def test_load_gate_cost_report_missing_share_fields_raises_CostEvidenceError(
        self,
    ) -> None:
        """Regression — _share_from_json's bare ``data["input_tokens"]`` etc.
        used to leak ``KeyError`` out of :func:`load_gate_cost_report`,
        breaching the :class:`CostEvidenceError` contract documented at
        the class docstring ("malformed on-disk JSON during load").
        """

        cost_dir = get_cost_root_dir(self.root, self.gate_id)
        sp = cost_dir / "summary.json"
        sp.write_text(
            json.dumps(
                {
                    "gate_id": self.gate_id,
                    "session_usage": {
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "total_cost_usd": 0.0,
                        "tool_calls_count": 0,
                        "duration_s": 0.0,
                    },
                    # Missing input_tokens/output_tokens/cost_usd/duration_s
                    # /attribution_mode -- enters _share_from_json which
                    # used to raise bare KeyError.
                    "per_collector": [{"collector_id": "c1"}],
                    "attribution_mode": "uniform",
                    "total_cost_usd": 0.0,
                    "collector_count": 1,
                    "timestamp_iso": "2026-06-24T00:00:00Z",
                },
            ),
        )
        with self.assertRaises(CostEvidenceError):
            load_gate_cost_report(self.root, self.gate_id)

    def test_load_collector_cost_share_missing_fields_raises_CostEvidenceError(
        self,
    ) -> None:
        """Regression — same contract gap, but on the per-collector
        loader. A ``<collector_id>.json`` missing every required share
        field used to raise ``KeyError`` rather than the documented
        :class:`CostEvidenceError`.
        """

        path = collector_cost_path(self.root, self.gate_id, "c1")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"collector_id": "c1"}))
        with self.assertRaises(CostEvidenceError):
            load_collector_cost_share(self.root, self.gate_id, "c1")

    def test_load_gate_cost_report_null_or_string_top_fields_raises_CostEvidenceError(
        self,
    ) -> None:
        """Regression — :func:`load_gate_cost_report` used to leak raw
        ``TypeError`` / ``ValueError`` out of two unguarded coercion
        paths in the :class:`GateCostReport` constructor: (1) the
        ``_usage_from_json(...)`` call, whose five ``int(...)`` /
        ``float(...)`` casts on ``.get()`` results raise stdlib errors
        when a session_usage field is ``null`` (Python ``None``) or a
        non-numeric string; and (2) the top-level
        ``float(data.get("total_cost_usd", 0.0))`` coercion, which has
        the same hazard. Both breach the :class:`CostEvidenceError`
        class docstring contract ("malformed on-disk JSON during load")
        — operators with ``except CostEvidenceError`` handlers around
        the load surface caught raw stdlib exceptions instead. The
        sibling ``_share_from_json`` callsite inside
        :func:`load_collector_cost_share` was already pinned by
        :meth:`test_load_collector_cost_share_wrong_type_raises_CostEvidenceError`;
        this regression closes the symmetric gap.
        """

        cost_dir = get_cost_root_dir(self.root, self.gate_id)
        sp = cost_dir / "summary.json"

        # Case 1: session_usage.input_tokens = null leaks TypeError out
        # of _usage_from_json's int(data.get("input_tokens", 0)) call.
        sp.write_text(
            json.dumps(
                {
                    "gate_id": self.gate_id,
                    "session_usage": {
                        "input_tokens": None,
                        "output_tokens": 0,
                        "total_cost_usd": 0.0,
                        "tool_calls_count": 0,
                        "duration_s": 0.0,
                    },
                    "per_collector": [],
                    "attribution_mode": "uniform",
                    "total_cost_usd": 0.0,
                    "collector_count": 0,
                    "timestamp_iso": "2026-06-24T00:00:00Z",
                },
            ),
        )
        with self.assertRaises(CostEvidenceError):
            load_gate_cost_report(self.root, self.gate_id)

        # Case 2: top-level total_cost_usd = "not-a-number" leaks
        # ValueError out of float(data.get("total_cost_usd", 0.0)).
        sp.write_text(
            json.dumps(
                {
                    "gate_id": self.gate_id,
                    "session_usage": {
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "total_cost_usd": 0.0,
                        "tool_calls_count": 0,
                        "duration_s": 0.0,
                    },
                    "per_collector": [],
                    "attribution_mode": "uniform",
                    "total_cost_usd": "not-a-number",
                    "collector_count": 0,
                    "timestamp_iso": "2026-06-24T00:00:00Z",
                },
            ),
        )
        with self.assertRaises(CostEvidenceError):
            load_gate_cost_report(self.root, self.gate_id)

        # Case 3: top-level total_cost_usd = null leaks TypeError out
        # of float(data.get("total_cost_usd", 0.0)) — the .get default
        # only fires when the KEY is missing; an explicit null still
        # reaches float(None) which raises.
        sp.write_text(
            json.dumps(
                {
                    "gate_id": self.gate_id,
                    "session_usage": {
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "total_cost_usd": 0.0,
                        "tool_calls_count": 0,
                        "duration_s": 0.0,
                    },
                    "per_collector": [],
                    "attribution_mode": "uniform",
                    "total_cost_usd": None,
                    "collector_count": 0,
                    "timestamp_iso": "2026-06-24T00:00:00Z",
                },
            ),
        )
        with self.assertRaises(CostEvidenceError):
            load_gate_cost_report(self.root, self.gate_id)

    def test_emit_prunes_ghost_collector_files_on_reemit_with_smaller_set(
        self,
    ) -> None:
        """Regression — re-emitting for the same gate_id with a smaller
        collector set used to leave ghost ``<collector_id>.json`` files
        on disk for the dropped collector. ``summary.json`` correctly
        reported the new ``collector_count``, but the cost dir listing
        diverged from ``per_collector`` and ``load_collector_cost_share``
        for a dropped id returned stale data.

        Reachable in production via the FAIL → remediation cycle
        (``request_review_continuation`` propagates the same gate_id
        forward, but the new commit_sha makes ``check_gate_reuse`` re-
        run collectors) or via kill-switch flips in
        ``profile.categories_na`` between runs.
        """

        first = [
            _make_outcome("ruff", "static", duration_ms=1000),
            _make_outcome("mypy", "static", duration_ms=1000),
            _make_outcome("black", "static", duration_ms=1000),
        ]
        emit_gate_cost_report(self.root, self.gate_id, SESSION, first)
        cost_dir = get_cost_root_dir(self.root, self.gate_id)
        before = sorted(p.name for p in cost_dir.iterdir())
        self.assertEqual(
            before, ["black.json", "mypy.json", "ruff.json", "summary.json"],
        )

        second = [
            _make_outcome("ruff", "static", duration_ms=1000),
            _make_outcome("mypy", "static", duration_ms=1000),
        ]
        emit_gate_cost_report(self.root, self.gate_id, SESSION, second)

        after = sorted(p.name for p in cost_dir.iterdir())
        # Ghost black.json must be gone.
        self.assertEqual(after, ["mypy.json", "ruff.json", "summary.json"])

        # Summary and on-disk listing must agree.
        summary = load_gate_cost_report(self.root, self.gate_id)
        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertEqual(summary.collector_count, 2)
        self.assertEqual(
            sorted(s.collector_id for s in summary.per_collector),
            ["mypy", "ruff"],
        )

        # And load_collector_cost_share for the dropped id returns None
        # rather than the stale share from emission #1.
        self.assertIsNone(
            load_collector_cost_share(self.root, self.gate_id, "black"),
        )
        # Survivors still load.
        self.assertIsNotNone(
            load_collector_cost_share(self.root, self.gate_id, "ruff"),
        )

    def test_reemit_summary_write_failure_rolls_back_to_old_state(
        self,
    ) -> None:
        """Regression — re-emitting for the same gate_id with a smaller
        collector set used to PRUNE ghost ``<collector_id>.json`` files
        BEFORE writing the new ``summary.json``. If the summary write
        then failed (ENOSPC, EROFS, SIGKILL between the unlink loop and
        ``write_atomic_text`` of summary), the stale summary on disk
        from the prior emit still referenced the pruned collectors —
        but the prune step had already deleted their per-collector
        files. Result: on-disk state was inconsistent (summary listed
        {a, b, c}, files for {a only}) and a load of the dropped ids
        returned ``None`` (ghost reference).

        Fix reorders to: (1) write new per-collector files, (2) write
        summary.json, (3) prune ghost files. A failed summary write
        now rolls back cleanly: ``write_atomic_text`` writes via a
        tempfile + ``os.replace``, so the OLD summary survives intact;
        and because pruning hasn't run yet, the OLD per-collector
        files survive too. The on-disk listing still matches the OLD
        summary; the next successful re-emit fully repairs.

        Reachable in production via the FAIL → remediation cycle where
        a re-emit with a shrunk collector set races a disk-full /
        read-only-filesystem / process-crash window.
        """

        from story_automator.core.innovation import cost_evidence

        # Emit #1 — three collectors, succeeds normally.
        first = [
            _make_outcome("a", "static", duration_ms=1000),
            _make_outcome("b", "static", duration_ms=1000),
            _make_outcome("c", "static", duration_ms=1000),
        ]
        emit_gate_cost_report(self.root, self.gate_id, SESSION, first)
        cost_dir = get_cost_root_dir(self.root, self.gate_id)
        before = sorted(p.name for p in cost_dir.iterdir())
        self.assertEqual(
            before, ["a.json", "b.json", "c.json", "summary.json"],
        )
        summary_before = load_gate_cost_report(self.root, self.gate_id)
        self.assertIsNotNone(summary_before)
        assert summary_before is not None
        self.assertEqual(
            sorted(s.collector_id for s in summary_before.per_collector),
            ["a", "b", "c"],
        )

        # Emit #2 — only [a] this time, but inject an OSError on the
        # summary.json write to simulate ENOSPC / EROFS / abrupt fault.
        real_write = cost_evidence.write_atomic_text

        def flaky_write(path: Path, data: str, *, encoding: str = "utf-8") -> None:
            if path.name == "summary.json":
                raise OSError("simulated ENOSPC on summary.json write")
            real_write(path, data, encoding=encoding)

        with patch.object(cost_evidence, "write_atomic_text", flaky_write):
            with self.assertRaises(OSError):
                emit_gate_cost_report(
                    self.root, self.gate_id, SESSION,
                    [_make_outcome("a", "static", duration_ms=1000)],
                )

        # On the unfixed code (prune BEFORE summary write), this would
        # be ["a.json", "summary.json"] — b.json + c.json deleted, but
        # the stale summary still listed [a, b, c].
        #
        # On the fixed code (prune AFTER summary write), the prune
        # step is never reached when the summary write raises, so all
        # three per-collector files survive and the old summary on
        # disk still matches the on-disk collector set.
        after = sorted(p.name for p in cost_dir.iterdir())
        self.assertEqual(
            after, ["a.json", "b.json", "c.json", "summary.json"],
            "ghost files were pruned before the summary write committed "
            "— a failed summary write must roll back cleanly, leaving "
            "the OLD per-collector files matching the OLD summary",
        )

        # And the OLD summary on disk should still match what's there.
        summary_after = load_gate_cost_report(self.root, self.gate_id)
        self.assertIsNotNone(summary_after)
        assert summary_after is not None
        self.assertEqual(
            sorted(s.collector_id for s in summary_after.per_collector),
            ["a", "b", "c"],
            "old summary should be preserved when new summary write "
            "fails — atomic-replace must not partially-apply",
        )

        # And load_collector_cost_share for the (now-survived) ids
        # returns real data, not None (ghost reference).
        for cid in ("a", "b", "c"):
            self.assertIsNotNone(
                load_collector_cost_share(self.root, self.gate_id, cid),
                f"{cid}.json was pruned before summary committed",
            )

    def test_load_gate_cost_report_collector_count_derived_from_len_shares(
        self,
    ) -> None:
        """Regression — load_gate_cost_report used to read collector_count
        straight off disk via ``int(data.get("collector_count", len(shares)))``,
        treating ``len(shares)`` as a default-only fallback. Combined with
        the loud-fail-on-list-type / silent-skip-on-element-type asymmetry
        in the per_collector parse loop (which filters non-dict entries via
        ``isinstance(entry, dict)``), a hand-edited or legacy summary.json
        carrying mixed valid/junk per_collector entries plus a stale
        on-disk ``collector_count`` would round-trip into a GateCostReport
        where ``collector_count != len(per_collector)`` — silently breaking
        the natural invariant pinned by the emit-side at l.359
        (``collector_count=len(shares)``).

        Under the project's single-trusted-operator threat model this is
        observability-only (cost evidence is sibling-of-evidence, never
        re-walked for Merkle reverification, never gates a workflow), but
        the inconsistent dataclass surfaces to operator audits and the
        loader contradicted its own fail-loud pattern. Fix derives
        ``collector_count`` from ``len(shares)`` ALWAYS so the in-memory
        dataclass is internally consistent regardless of on-disk drift.
        """

        cost_dir = get_cost_root_dir(self.root, self.gate_id)
        sp = cost_dir / "summary.json"
        valid_share = {
            "collector_id": "ruff",
            "input_tokens": 100,
            "output_tokens": 50,
            "cost_usd": 0.001,
            "duration_s": 1.0,
            "attribution_mode": "uniform",
        }
        # Mixed per_collector: one valid dict + three non-dict entries
        # that the isinstance(entry, dict) filter silently drops. Stale
        # collector_count=4 on disk pretends all four were valid.
        sp.write_text(
            json.dumps(
                {
                    "gate_id": self.gate_id,
                    "session_usage": {
                        "input_tokens": 100,
                        "output_tokens": 50,
                        "total_cost_usd": 0.001,
                        "tool_calls_count": 0,
                        "duration_s": 1.0,
                    },
                    "per_collector": [valid_share, "NOT-A-DICT", 42, None],
                    "attribution_mode": "uniform",
                    "total_cost_usd": 0.001,
                    "collector_count": 4,  # deliberately stale
                    "timestamp_iso": "2026-06-24T00:00:00Z",
                },
            ),
        )
        loaded = load_gate_cost_report(self.root, self.gate_id)
        self.assertIsNotNone(loaded)
        assert loaded is not None  # narrow for type checker
        # The fix: collector_count must agree with len(per_collector),
        # mirroring the emit-side invariant. Before the fix, this
        # assertion produced collector_count=4, len(per_collector)=1.
        self.assertEqual(loaded.collector_count, len(loaded.per_collector))
        self.assertEqual(loaded.collector_count, 1)

    def test_load_collector_cost_share_wrong_type_raises_CostEvidenceError(
        self,
    ) -> None:
        """Regression — int()/float() casts inside _share_from_json
        leaked ``ValueError`` rather than the documented
        :class:`CostEvidenceError` when a field is the wrong type.
        """

        path = collector_cost_path(self.root, self.gate_id, "c1")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "collector_id": "c1",
                    "input_tokens": "not-an-int",
                    "output_tokens": 0,
                    "cost_usd": 0.0,
                    "duration_s": 0.0,
                    "attribution_mode": "uniform",
                },
            ),
        )
        with self.assertRaises(CostEvidenceError):
            load_collector_cost_share(self.root, self.gate_id, "c1")

    def test_load_paths_do_not_create_ghost_directory_on_missing_data(
        self,
    ) -> None:
        """Regression — :func:`load_gate_cost_report` and
        :func:`load_collector_cost_share` used to route through
        :func:`summary_path` / :func:`collector_cost_path` which both
        called :func:`get_cost_root_dir` — the side-effecting helper
        that calls ``ensure_dir`` to create the per-gate cost directory
        on demand. As a result, probing for a never-emitted gate_id
        correctly returned ``None`` but left an empty
        ``_bmad/gate/cost/<gate_id>/`` directory behind.

        The pollution silently breaks any future tooling that lists
        ``_bmad/gate/cost/`` subdirectories to enumerate gates with
        cost evidence — ghost dirs become indistinguishable from gates
        that emitted zero shares. The docstring on
        :func:`load_gate_cost_report` explicitly says "Returns ``None``
        when the summary file is missing" implying read-only semantics.

        Fix splits the path-computation helper from the side-effecting
        directory-creation helper: the load path uses a pure path
        joiner (``_cost_dir_path``) and only the emit path keeps using
        ``get_cost_root_dir`` (which still creates the directory on
        demand for legitimate writes).
        """

        cost_root = self.root / "_bmad" / "gate" / "cost"
        # Pre-condition — nothing exists yet.
        self.assertFalse(cost_root.exists())

        # load_gate_cost_report on a never-emitted gate must return
        # None WITHOUT creating the per-gate directory.
        self.assertIsNone(
            load_gate_cost_report(self.root, "never-emitted-gate"),
        )
        self.assertFalse(
            (cost_root / "never-emitted-gate").exists(),
            "load_gate_cost_report created a ghost per-gate cost dir "
            "even though no cost evidence exists for that gate",
        )

        # load_collector_cost_share on a never-emitted gate must also
        # return None WITHOUT creating the per-gate directory.
        self.assertIsNone(
            load_collector_cost_share(
                self.root, "another-never-emitted-gate", "some-collector",
            ),
        )
        self.assertFalse(
            (cost_root / "another-never-emitted-gate").exists(),
            "load_collector_cost_share created a ghost per-gate cost "
            "dir even though no cost evidence exists for that gate",
        )

        # And the path helpers themselves must be pure — calling them
        # without subsequently invoking emit must not touch disk.
        _ = summary_path(self.root, "pure-summary-probe")
        _ = collector_cost_path(
            self.root, "pure-collector-probe", "any-id",
        )
        self.assertFalse(
            (cost_root / "pure-summary-probe").exists(),
            "summary_path() created a ghost per-gate cost dir as a "
            "side effect — path helpers must be pure",
        )
        self.assertFalse(
            (cost_root / "pure-collector-probe").exists(),
            "collector_cost_path() created a ghost per-gate cost dir "
            "as a side effect — path helpers must be pure",
        )

        # Sanity — emit DOES still create the directory (the side
        # effect belongs on the write path, not the read path).
        outcomes = [_make_outcome("ruff", "static")]
        emit_gate_cost_report(self.root, "real-gate", SESSION, outcomes)
        self.assertTrue((cost_root / "real-gate").is_dir())

    def test_attribution_mode_vocabulary_unified_across_summary_levels(
        self,
    ) -> None:
        """Regression — top-level ``attribution_mode`` in summary.json and
        the per-collector ``attribution_mode`` inside the SAME summary
        used to carry two different closed vocabularies under one key
        name. ``cost_evidence.VALID_COST_ATTRIBUTION_MODES`` is
        ``('uniform', 'duration', 'tool-calls')`` while
        ``cost_attribution.VALID_ATTRIBUTION_MODES`` is
        ``('uniform', 'duration-weighted', 'tool-call-weighted')`` —
        the top-level value came from the cost_evidence vocab via
        ``_attribute()``'s second return, while each per_collector
        entry's value came from the cost_attribution vocab via
        ``CollectorCostShare.attribution_mode``. An operator filtering
        on ``attribution_mode`` saw mismatched strings in one document
        and ``load_collector_cost_share`` returned ``'duration-weighted'``
        while ``load_gate_cost_report`` returned ``'duration'`` for the
        same emit call.

        Fix normalizes at the persistence boundary (_share_to_json) so
        every ``attribution_mode`` string in on-disk cost evidence
        (top-level summary, per-collector entries, and
        ``<collector_id>.json`` files) is in
        :data:`VALID_COST_ATTRIBUTION_MODES`.
        """

        from story_automator.core.innovation.cost_evidence import (
            VALID_COST_ATTRIBUTION_MODES,
        )

        outcomes = [
            _make_outcome("ruff", "static", duration_ms=1000),
            _make_outcome("mypy", "static", duration_ms=3000),
        ]
        emit_gate_cost_report(self.root, self.gate_id, SESSION, outcomes)

        sp = summary_path(self.root, self.gate_id)
        data = json.loads(sp.read_text())

        top = data["attribution_mode"]
        self.assertIn(
            top, VALID_COST_ATTRIBUTION_MODES,
            f"top-level attribution_mode {top!r} not in canonical vocab",
        )
        for entry in data["per_collector"]:
            mode = entry["attribution_mode"]
            self.assertIn(
                mode, VALID_COST_ATTRIBUTION_MODES,
                f"per_collector[{entry['collector_id']!r}] attribution_mode "
                f"{mode!r} not in canonical vocab "
                f"{VALID_COST_ATTRIBUTION_MODES}",
            )
            # And both nesting levels must agree under duration mode.
            self.assertEqual(
                mode, top,
                f"per_collector[{entry['collector_id']!r}] attribution_mode "
                f"{mode!r} != top-level {top!r} — vocab divergence under "
                f"the same key name in one document",
            )

        # Round-trip via both loaders — they must also return the
        # canonical vocab (and agree with each other).
        report = load_gate_cost_report(self.root, self.gate_id)
        assert report is not None
        self.assertIn(report.attribution_mode, VALID_COST_ATTRIBUTION_MODES)
        for share in report.per_collector:
            self.assertIn(
                share.attribution_mode, VALID_COST_ATTRIBUTION_MODES,
            )
            self.assertEqual(
                share.attribution_mode, report.attribution_mode,
            )
        share_ruff = load_collector_cost_share(
            self.root, self.gate_id, "ruff",
        )
        assert share_ruff is not None
        self.assertIn(
            share_ruff.attribution_mode, VALID_COST_ATTRIBUTION_MODES,
        )
        self.assertEqual(share_ruff.attribution_mode, report.attribution_mode)

    def test_in_memory_return_value_attribution_mode_vocab_unified(
        self,
    ) -> None:
        """Regression — the IN-MEMORY GateCostReport returned by
        ``emit_gate_cost_report`` used to carry mismatched vocabularies:
        the top-level ``attribution_mode`` was normalized to the
        cost_evidence vocab (``"duration"``) via ``_attribute()``'s
        second return, but each ``per_collector[*].attribution_mode``
        carried the raw substrate vocab (``"duration-weighted"``) from
        ``attribute_cost_by_duration``. Disk emission AND
        ``load_gate_cost_report`` normalized via ``_share_to_json`` /
        ``_share_from_json``, so the regression slipped past the
        on-disk + round-tripped vocab tests above.

        Any caller iterating ``report.per_collector`` directly and
        cross-checking ``attribution_mode`` against
        :data:`VALID_COST_ATTRIBUTION_MODES` saw the off-vocab string.
        Fix normalizes each share's ``attribution_mode`` when building
        the in-memory GateCostReport so the immediate return value
        matches both disk-state and round-tripped state.
        """
        from story_automator.core.innovation.cost_evidence import (
            VALID_COST_ATTRIBUTION_MODES,
        )

        outcomes = [
            _make_outcome("ruff", "static", duration_ms=1000),
            _make_outcome("mypy", "static", duration_ms=3000),
        ]
        # NB: no disk round-trip — assert on the immediate return value.
        report = emit_gate_cost_report(
            self.root, self.gate_id, SESSION, outcomes,
        )

        # Top-level field is canonical.
        self.assertIn(
            report.attribution_mode, VALID_COST_ATTRIBUTION_MODES,
            f"top-level in-memory attribution_mode "
            f"{report.attribution_mode!r} not in canonical vocab",
        )
        # Every per-collector entry must be canonical AND agree with
        # the top-level mode under the duration path.
        for share in report.per_collector:
            self.assertIn(
                share.attribution_mode, VALID_COST_ATTRIBUTION_MODES,
                f"in-memory per_collector[{share.collector_id!r}] "
                f"attribution_mode {share.attribution_mode!r} not in "
                f"canonical vocab {VALID_COST_ATTRIBUTION_MODES}",
            )
            self.assertEqual(
                share.attribution_mode, report.attribution_mode,
                f"in-memory per_collector[{share.collector_id!r}] "
                f"attribution_mode {share.attribution_mode!r} != "
                f"top-level {report.attribution_mode!r} — vocab "
                f"divergence in the same in-memory dataclass",
            )


# ---------------------------------------------------------------------------
# Group 2 — gate orchestrator integration
# ---------------------------------------------------------------------------


def _run_minimal_gate(
    project_root: Path,
    gate_id: str,
    *,
    session_usage: UsageMetrics | None = None,
) -> dict[str, Any]:
    """Drive :func:`run_production_gate` through patched collaborators.

    Patches the heavy lifecycle helpers so the test focuses on the cost
    emission wiring only — no real subprocess, no real git checkout.
    """

    from story_automator.core import gate_orchestrator

    target = {"kind": "story", "id": "S-1"}
    profile = {"id": "test", "version": 1}
    commit_sha = "deadbeef" * 5
    factory_version = "test-v1"

    fake_outcomes = [
        _make_outcome("ruff", "static", duration_ms=1000),
        _make_outcome("mypy", "static", duration_ms=2000),
    ]
    fake_gate_file: dict[str, Any] = {
        "gate_id": gate_id,
        "commit_sha": commit_sha,
        "overall": "PASS",
        "categories": {},
    }

    with (
        patch.object(gate_orchestrator, "assert_host_context"),
        patch.object(gate_orchestrator, "run_cleanup_janitor"),
        patch.object(
            gate_orchestrator,
            "_recover_from_crash_locked",
            return_value=({"recovered": False}, []),
        ),
        patch.object(
            gate_orchestrator, "check_gate_reuse", return_value=(None, ""),
        ),
        patch.object(gate_orchestrator, "write_gate_marker"),
        patch.object(gate_orchestrator, "clear_gate_marker"),
        patch.object(
            gate_orchestrator,
            "_run_collectors",
            return_value=fake_outcomes,
        ),
        patch.object(
            gate_orchestrator, "evaluate_gate", return_value=fake_gate_file,
        ),
        patch.object(gate_orchestrator, "compute_profile_hash", return_value="h"),
        patch(
            "story_automator.core.evidence_cache."
            "cached_load_evidence_bundle",
            return_value=[],
        ),
        patch(
            "story_automator.core.innovation.lineage_ledger.load_lineage_root",
            return_value="",
        ),
    ):
        kwargs: dict[str, Any] = {}
        if session_usage is not None:
            kwargs["session_usage"] = session_usage
        return gate_orchestrator.run_production_gate(
            project_root, gate_id,
            commit_sha=commit_sha, target=target,
            profile=profile, factory_version=factory_version,
            registry=None,  # type: ignore[arg-type]  # patched _run_collectors
            **kwargs,
        )


class OrchestratorWiringTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_run_production_gate_no_session_usage_byte_identical_to_baseline(
        self,
    ) -> None:
        gate_file = _run_minimal_gate(self.root, "g-base-1")
        # No cost_total_usd when session_usage is absent.
        self.assertNotIn("cost_total_usd", gate_file)
        cost_root = self.root / "_bmad" / "gate" / "cost"
        # Cost dir must not be created without session_usage.
        self.assertFalse(cost_root.exists())

    def test_run_production_gate_with_session_usage_emits_cost_files(
        self,
    ) -> None:
        gate_file = _run_minimal_gate(
            self.root, "g-with-usage-1", session_usage=SESSION,
        )
        self.assertIn("cost_total_usd", gate_file)
        # Files emitted under sibling-of-evidence path.
        cost_dir = self.root / "_bmad" / "gate" / "cost" / "g-with-usage-1"
        self.assertTrue(cost_dir.is_dir())
        self.assertTrue((cost_dir / "summary.json").is_file())

    def test_cost_emission_failure_does_not_break_gate(self) -> None:
        from story_automator.core import gate_orchestrator

        with patch.object(
            gate_orchestrator, "emit_gate_cost_report",
            side_effect=RuntimeError("boom"),
        ):
            # The wiring must swallow emission failures so the gate
            # still returns a verdict.
            gate_file = _run_minimal_gate(
                self.root, "g-fail-emit-1", session_usage=SESSION,
            )
        self.assertEqual(gate_file["overall"], "PASS")
        # And cost_total_usd is absent (best-effort: emission failed).
        self.assertNotIn("cost_total_usd", gate_file)

    def test_run_system_gate_symmetrically_emits_cost_when_session_usage_provided(
        self,
    ) -> None:
        from story_automator.core import system_gate

        target_epic = "E-1"
        profile = {"id": "test", "version": 1}
        commit_sha = "deadbeef" * 5
        factory_version = "test-v1"
        fake_outcomes = [_make_outcome("ruff", "static", duration_ms=1000)]
        fake_gate_file: dict[str, Any] = {
            "gate_id": "g-sys-1", "commit_sha": commit_sha,
            "overall": "PASS", "categories": {},
        }

        class _StubEnvInfo:
            provisioned = True
            env_id = "e1"
            tier = "minimal"
            namespace = "ns"
            endpoints: dict[str, str] = {}

        class _StubEnvConfig:
            tier = "minimal"

        import contextlib

        @contextlib.contextmanager
        def _stub_system_env(env_config, project_root):
            yield _StubEnvInfo()

        with (
            patch.object(system_gate, "assert_host_context"),
            patch.object(system_gate, "run_cleanup_janitor"),
            patch.object(
                system_gate, "_recover_from_crash_locked",
                return_value=({"recovered": False}, []),
            ),
            patch.object(
                system_gate, "check_gate_reuse", return_value=(None, ""),
            ),
            patch.object(
                system_gate, "build_env_config", return_value=_StubEnvConfig(),
            ),
            patch.object(system_gate, "system_env", _stub_system_env),
            patch.object(system_gate, "write_gate_marker"),
            patch.object(system_gate, "clear_gate_marker"),
            patch.object(
                system_gate, "run_gate_collectors", return_value=fake_outcomes,
            ),
            patch.object(
                system_gate, "evaluate_gate", return_value=fake_gate_file,
            ),
            patch.object(system_gate, "compute_profile_hash", return_value="h"),
            patch(
                "story_automator.core.innovation.lineage_ledger."
                "load_lineage_root",
                return_value="",
            ),
        ):
            result = system_gate.run_system_gate(
                self.root, "g-sys-1",
                epic_id=target_epic, commit_sha=commit_sha,
                epic_metadata={}, profile=profile,
                factory_version=factory_version,
                registry=None,  # type: ignore[arg-type]
                session_usage=SESSION,
            )

        self.assertIn("cost_total_usd", result)
        cost_dir = self.root / "_bmad" / "gate" / "cost" / "g-sys-1"
        self.assertTrue(cost_dir.is_dir())


# ---------------------------------------------------------------------------
# Group 3 — gate-file embed contract
# ---------------------------------------------------------------------------


class GateFileEmbedTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_gate_file_cost_total_usd_present_when_session_usage_provided(
        self,
    ) -> None:
        gate_file = _run_minimal_gate(
            self.root, "g-embed-yes", session_usage=SESSION,
        )
        self.assertIn("cost_total_usd", gate_file)
        self.assertIsInstance(gate_file["cost_total_usd"], float)
        self.assertAlmostEqual(
            gate_file["cost_total_usd"], SESSION.total_cost_usd,
        )

    def test_gate_file_cost_total_usd_absent_when_session_usage_none(
        self,
    ) -> None:
        gate_file = _run_minimal_gate(self.root, "g-embed-no")
        self.assertNotIn("cost_total_usd", gate_file)


if __name__ == "__main__":
    unittest.main()
