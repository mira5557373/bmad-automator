"""Regression tests for bug R2-J-02.

Evidence metric values were unchecked by ``validate_evidence_record``.  A
single ``None`` (or stray string, or NaN) value emitted by a collector
crashed the L3 worst-of reducer in ``category_rules._aggregate_metrics``
with a ``TypeError`` deep inside ``sum``/``min``/``max``, which the
orchestrator surfaced as a traceback — effectively fail-open rather than
fail-closed for the affected category.

Fix:
  1. ``validate_evidence_record`` now walks ``metrics.items()`` and
     rejects values that are not ``bool``/``int``/``float``/``str`` as
     well as ``NaN``/``+-inf`` floats.
  2. ``_aggregate_metrics`` filters out ``None`` (and other non-finite or
     non-comparable values) as defence-in-depth so a tainted record from
     a misbehaving custom collector still degrades gracefully to the
     supplied default instead of crashing the gate.
"""
from __future__ import annotations

import math
import unittest

from story_automator.core.category_rules import _aggregate_metrics
from story_automator.core.gate_schema import (
    GateSchemaError,
    validate_evidence_record,
)


def _base_record() -> dict:
    return {
        "schema_version": 1,
        "collector": "demo",
        "tool": "demo-tool",
        "tool_version": "",
        "category": "security",
        "tier": "code",
        "status": "ok",
        "metrics": {},
        "findings": [],
        "raw_output_ref": "",
        "exit_code": 0,
        "duration_ms": 0,
        "deterministic": True,
    }


class ValidateEvidenceMetricsTests(unittest.TestCase):
    """``validate_evidence_record`` must reject malformed metric values."""

    def test_none_metric_value_is_rejected(self) -> None:
        rec = _base_record()
        rec["metrics"] = {"sast_high_count": None}
        with self.assertRaises(GateSchemaError):
            validate_evidence_record(rec)

    def test_nan_metric_value_is_rejected(self) -> None:
        rec = _base_record()
        rec["metrics"] = {"coverage_pct": float("nan")}
        with self.assertRaises(GateSchemaError):
            validate_evidence_record(rec)

    def test_inf_metric_value_is_rejected(self) -> None:
        rec = _base_record()
        rec["metrics"] = {"coverage_pct": math.inf}
        with self.assertRaises(GateSchemaError):
            validate_evidence_record(rec)

    def test_scalar_values_accepted(self) -> None:
        rec = _base_record()
        rec["metrics"] = {
            "sast_high_count": 0,
            "coverage_pct": 87.5,
            "slo_breached": False,
            "strategy": "canary",
        }
        # Should not raise.
        validate_evidence_record(rec)


class AggregateMetricsDefenseInDepthTests(unittest.TestCase):
    """``_aggregate_metrics`` must not crash on a bad metric value."""

    def test_none_value_is_filtered_not_crashing_sum(self) -> None:
        ev = [
            {"metrics": {"sast_high_count": 5}},
            {"metrics": {"sast_high_count": None}},
        ]
        # Pre-fix: TypeError "unsupported operand type(s) for +: 'int' and 'NoneType'".
        self.assertEqual(_aggregate_metrics(ev, "sast_high_count", 0), 5)
