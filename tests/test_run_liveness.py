# tests/test_run_liveness.py
"""Heartbeat-based run liveness — the shared crash-detection predicate.

The marker's pid is a transient per-step shell, so liveness is decided by the
heartbeat staleness window. Both predicates fail safe when the age cannot be
determined (corrupt/missing/malformed timestamp), each toward the side that
avoids harm for its caller.
"""

from __future__ import annotations

import unittest

from story_automator.core.atomic_io import parse_iso_seconds
from story_automator.core.run_liveness import (
    STALE_AFTER_SECONDS,
    heartbeat_age_seconds,
    run_is_live,
    run_is_stale,
)

_BASE = "2026-06-16T10:00:00Z"
_BASE_EPOCH = parse_iso_seconds(_BASE)


class RunLivenessTests(unittest.TestCase):
    def test_fresh_heartbeat_is_live_not_stale(self) -> None:
        payload = {"heartbeat": _BASE}
        now = _BASE_EPOCH + 60  # 1 minute later
        self.assertTrue(run_is_live(payload, now))
        self.assertFalse(run_is_stale(payload, now))

    def test_old_heartbeat_is_stale_not_live(self) -> None:
        payload = {"heartbeat": _BASE}
        now = _BASE_EPOCH + STALE_AFTER_SECONDS + 1
        self.assertFalse(run_is_live(payload, now))
        self.assertTrue(run_is_stale(payload, now))

    def test_exactly_at_window_is_live(self) -> None:
        payload = {"heartbeat": _BASE}
        now = _BASE_EPOCH + STALE_AFTER_SECONDS  # boundary: <= window
        self.assertTrue(run_is_live(payload, now))
        self.assertFalse(run_is_stale(payload, now))

    def test_falls_back_to_created_at_then_started_at(self) -> None:
        now = _BASE_EPOCH + 30
        self.assertTrue(run_is_live({"createdAt": _BASE}, now))
        self.assertTrue(run_is_live({"startedAt": _BASE}, now))

    def test_missing_timestamp_is_neither_live_nor_stale(self) -> None:
        # Fail-safe: unknown age must not declare live (would block re-run) nor
        # stale (would prematurely stop a healthy run).
        for payload in ({}, {"epic": "1"}):
            self.assertIsNone(heartbeat_age_seconds(payload, _BASE_EPOCH))
            self.assertFalse(run_is_live(payload, _BASE_EPOCH))
            self.assertFalse(run_is_stale(payload, _BASE_EPOCH))

    def test_malformed_timestamp_is_neither_live_nor_stale(self) -> None:
        payload = {"heartbeat": "not-a-timestamp"}
        self.assertIsNone(heartbeat_age_seconds(payload, _BASE_EPOCH))
        self.assertFalse(run_is_live(payload, _BASE_EPOCH))
        self.assertFalse(run_is_stale(payload, _BASE_EPOCH))

    def test_non_dict_payload_is_neither(self) -> None:
        for payload in (None, [], "x", 7):
            self.assertIsNone(heartbeat_age_seconds(payload, _BASE_EPOCH))
            self.assertFalse(run_is_live(payload, _BASE_EPOCH))
            self.assertFalse(run_is_stale(payload, _BASE_EPOCH))


if __name__ == "__main__":
    unittest.main()
