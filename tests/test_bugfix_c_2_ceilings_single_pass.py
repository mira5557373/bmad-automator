"""Round-3 fix C-2 — evaluate_ceilings single-pass aggregation (Lens K).

Pins the behavior promoted from finding K-1: when multiple ceilings
share the same JSONL ledger but use different windows, the ledger
must be streamed exactly ONCE per ``evaluate_ceilings`` call — not
once per applicable ceiling.

The pre-fix code called ``_compute_spent(events_path, ceiling.window,
now_iso)`` inside a loop over ``applicable`` ceilings. With four
ceilings configured (per_run / 24h / 7d / 30d), a single gate
evaluation triggered four full ledger scans — O(N×K) where O(N) is
sufficient.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from story_automator.core.budget_ceilings import (
    BudgetCeiling,
    CeilingDecision,
    evaluate_ceilings,
)


def _write_ledger(path: Path, n_events: int) -> None:
    """Write ``n_events`` cost-bearing records to a JSONL ledger."""
    lines = []
    for i in range(n_events):
        lines.append(json.dumps({
            "event_type": "story_completed",
            "timestamp": "2026-06-22T12:00:00Z",
            "run_id": "test-run",
            "epic": "E1",
            "story_key": f"E1-{i:03d}",
            "duration_s": 1.0,
            "cost_usd": 0.10,
            "tokens_in": 1,
            "tokens_out": 1,
            "attempts": 1,
        }))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class CeilingsSinglePassTests(unittest.TestCase):
    """Pin Fix C-2: ledger opened ONCE regardless of K ceilings."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.ledger = self.root / "events.jsonl"
        _write_ledger(self.ledger, n_events=20)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_single_open_for_multiple_applicable_ceilings(self) -> None:
        ceilings = [
            BudgetCeiling(
                name="run", window="per_run",
                limit_usd=100.0, warn_at=0.8,
                gate_names=("init",),
            ),
            BudgetCeiling(
                name="day", window="24h",
                limit_usd=50.0, warn_at=0.8,
                gate_names=("init",),
            ),
            BudgetCeiling(
                name="week", window="7d",
                limit_usd=200.0, warn_at=0.8,
                gate_names=("init",),
            ),
            BudgetCeiling(
                name="month", window="30d",
                limit_usd=1000.0, warn_at=0.8,
                gate_names=("init",),
            ),
        ]

        real_open = Path.open
        open_count = {"n": 0}

        def counting_open(self_path: Path, *args: object, **kwargs: object):
            # Only count opens of the actual ledger file (not lockfiles
            # or atomic-write tmps).
            if str(self_path) == str(self.ledger):
                open_count["n"] += 1
            return real_open(self_path, *args, **kwargs)

        with mock.patch.object(Path, "open", new=counting_open):
            verdict, _ = evaluate_ceilings(
                self.ledger, "init", "2026-06-22T12:00:00Z",
                ceilings=ceilings,
            )

        # Verdict is meaningful — total spend $2 < all limits.
        self.assertEqual(verdict, CeilingDecision.ALLOW)
        # The critical invariant: ledger opened ONCE, not 4 times.
        self.assertEqual(
            open_count["n"], 1,
            f"ledger must be opened once, got {open_count['n']} opens",
        )

    def test_no_applicable_ceilings_skips_ledger_read_entirely(self) -> None:
        # Gate-name filter excludes everything → no ledger read.
        ceilings = [
            BudgetCeiling(
                name="run", window="per_run",
                limit_usd=100.0, warn_at=0.8,
                gate_names=("story_start",),  # different gate
            ),
        ]
        real_open = Path.open
        open_count = {"n": 0}

        def counting_open(self_path: Path, *args: object, **kwargs: object):
            if str(self_path) == str(self.ledger):
                open_count["n"] += 1
            return real_open(self_path, *args, **kwargs)

        with mock.patch.object(Path, "open", new=counting_open):
            verdict, reason = evaluate_ceilings(
                self.ledger, "init", "2026-06-22T12:00:00Z",
                ceilings=ceilings,
            )
        self.assertEqual(verdict, CeilingDecision.ALLOW)
        self.assertEqual(reason, "no_ceilings_configured")
        self.assertEqual(open_count["n"], 0)

    def test_verdict_matches_legacy_per_window_semantics(self) -> None:
        # Ensure the optimisation does not change the verdict — the
        # ledger has $2 spend, BLOCK at limit 1, etc.
        ceilings = [
            BudgetCeiling(
                name="cheap", window="per_run",
                limit_usd=1.0, warn_at=0.5,
                gate_names=("init",),
            ),
            BudgetCeiling(
                name="lots", window="per_run",
                limit_usd=1000.0, warn_at=0.8,
                gate_names=("init",),
            ),
        ]
        verdict, reason = evaluate_ceilings(
            self.ledger, "init", "2026-06-22T12:00:00Z",
            ceilings=ceilings,
        )
        # First ceiling exceeded → BLOCK takes precedence.
        self.assertEqual(verdict, CeilingDecision.BLOCK)
        self.assertIn("cheap", reason)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
