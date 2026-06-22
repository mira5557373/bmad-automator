"""Bugfix L5: naive ISO datetimes in waivers must raise WaiverError, not TypeError.

Bug: `_parse_iso` in `core/gate_rules.py` calls `datetime.fromisoformat(text)`
which returns a naive datetime when no timezone is present (e.g.
"2026-06-20T00:00:00" without a trailing "Z" or "+00:00"). The comparison
``now >= expires`` in ``is_waiver_expired`` then raises a bare ``TypeError``
("can't compare offset-naive and offset-aware datetimes"), which propagates
out of ``check_gate_reuse`` and crashes the orchestrator.

Fix: ``_parse_iso`` must reject naive timestamps with a ``ValueError`` so callers
that already catch ``ValueError`` (``is_waiver_expired`` -> ``WaiverError``;
``_check_ttl`` -> ``(False, reason)``) surface a clean error. The same
validation runs at ``gate_schema.validate_waiver`` time so bad waivers are
rejected at schema load rather than at the comparison site.
"""
from __future__ import annotations

import unittest

from story_automator.core.gate_rules import (
    WaiverError,
    _check_ttl,
    _parse_iso,
    is_waiver_expired,
)
from story_automator.core.gate_schema import (
    GateSchemaError,
    validate_waiver,
)


class ParseIsoRejectsNaive(unittest.TestCase):
    """`_parse_iso` must reject naive timestamps with ValueError."""

    def test_naive_iso_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            _parse_iso("2026-06-20T00:00:00")

    def test_tz_aware_z_still_parses(self) -> None:
        # Regression guard: existing "Z"-suffixed inputs MUST still work.
        result = _parse_iso("2026-06-20T00:00:00Z")
        self.assertIsNotNone(result.tzinfo)

    def test_tz_aware_offset_still_parses(self) -> None:
        result = _parse_iso("2026-06-20T00:00:00+00:00")
        self.assertIsNotNone(result.tzinfo)


class IsWaiverExpiredOnNaive(unittest.TestCase):
    """`is_waiver_expired` must surface a `WaiverError`, never a `TypeError`."""

    def test_naive_expires_at_raises_waiver_error(self) -> None:
        waiver = {"expires_at": "2026-06-20T00:00:00"}  # no tz
        with self.assertRaises(WaiverError):
            is_waiver_expired(waiver)


class CheckTtlOnNaive(unittest.TestCase):
    """`_check_ttl` must return (False, reason) on naive timestamps."""

    def test_naive_issued_at_returns_false(self) -> None:
        waiver = {
            "issued_at": "2026-06-20T00:00:00",  # no tz
            "expires_at": "2026-07-01T00:00:00Z",
        }
        ok, reason = _check_ttl(waiver)
        self.assertFalse(ok)
        self.assertIn("invalid dates", reason)


class ValidateWaiverRejectsNaive(unittest.TestCase):
    """Schema-level validation: naive ISO is a schema error, not a runtime crash."""

    def _base_waiver(self) -> dict:
        return {
            "waiver_id": "w-1",
            "operator_id": "op-1",
            "reason": "scoped exception",
            "signature": "abc",
            "profile_hash": "ph",
            "failing_categories": ["security"],
        }

    def test_naive_expires_at_rejected_at_validate_time(self) -> None:
        waiver = self._base_waiver()
        waiver["issued_at"] = "2026-06-20T00:00:00Z"
        waiver["expires_at"] = "2026-07-01T00:00:00"  # no tz
        with self.assertRaises(GateSchemaError):
            validate_waiver(waiver)

    def test_naive_issued_at_rejected_at_validate_time(self) -> None:
        waiver = self._base_waiver()
        waiver["issued_at"] = "2026-06-20T00:00:00"  # no tz
        waiver["expires_at"] = "2026-07-01T00:00:00Z"
        with self.assertRaises(GateSchemaError):
            validate_waiver(waiver)

    def test_well_formed_waiver_still_validates(self) -> None:
        waiver = self._base_waiver()
        waiver["issued_at"] = "2026-06-20T00:00:00Z"
        waiver["expires_at"] = "2026-07-01T00:00:00Z"
        # Should not raise.
        validate_waiver(waiver)


if __name__ == "__main__":
    unittest.main()
