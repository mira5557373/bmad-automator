from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from story_automator.core.escalation_emit import (
    ESCALATION_API_VERSION,
    VALID_SEVERITIES,
    EscalationError,
    emit_escalation,
    read_escalation,
    write_escalation,
)


class EmitEscalationTests(unittest.TestCase):
    def test_emit_minimal_critical_payload(self) -> None:
        payload = emit_escalation(
            story_key="1-2-foo",
            severity="CRITICAL",
            reason="gate verdict FAIL",
            originating_phase="gate",
        )
        self.assertEqual(payload["api_version"], ESCALATION_API_VERSION)
        self.assertEqual(payload["story_key"], "1-2-foo")
        self.assertEqual(payload["severity"], "CRITICAL")
        self.assertEqual(payload["reason"], "gate verdict FAIL")
        self.assertEqual(payload["originating_phase"], "gate")
        self.assertEqual(payload["suggested_action"], "")
        self.assertEqual(payload["waiver_ref"], "")

    def test_emit_preference_with_optional_fields(self) -> None:
        payload = emit_escalation(
            story_key="2-3-bar",
            severity="PREFERENCE",
            reason="profile drift detected",
            originating_phase="readiness",
            suggested_action="rerun gate with updated profile",
            waiver_ref="WAIVER-42",
        )
        self.assertEqual(payload["severity"], "PREFERENCE")
        self.assertEqual(payload["suggested_action"], "rerun gate with updated profile")
        self.assertEqual(payload["waiver_ref"], "WAIVER-42")

    def test_emit_rejects_invalid_severity(self) -> None:
        with self.assertRaises(EscalationError):
            emit_escalation(
                story_key="1-1-baz",
                severity="WARNING",
                reason="x",
                originating_phase="gate",
            )

    def test_emit_requires_non_empty_required_fields(self) -> None:
        with self.assertRaises(EscalationError):
            emit_escalation(
                story_key="",
                severity="CRITICAL",
                reason="x",
                originating_phase="gate",
            )
        with self.assertRaises(EscalationError):
            emit_escalation(
                story_key="1-1-baz",
                severity="CRITICAL",
                reason="",
                originating_phase="gate",
            )
        with self.assertRaises(EscalationError):
            emit_escalation(
                story_key="1-1-baz",
                severity="CRITICAL",
                reason="x",
                originating_phase="",
            )

    def test_valid_severities_constant(self) -> None:
        self.assertEqual(VALID_SEVERITIES, frozenset({"CRITICAL", "PREFERENCE"}))


class EscalationRoundTripTests(unittest.TestCase):
    def test_write_and_read_round_trip(self) -> None:
        payload = emit_escalation(
            story_key="3-4-qux",
            severity="CRITICAL",
            reason="missing evidence",
            originating_phase="gate",
            suggested_action="collect evidence",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "escalation.json"
            written = write_escalation(target, payload)
            self.assertEqual(written, target)
            self.assertTrue(target.is_file())
            loaded = read_escalation(target)
            self.assertEqual(loaded, payload)

    def test_write_creates_parent_dirs(self) -> None:
        payload = emit_escalation(
            story_key="5-6-zap",
            severity="PREFERENCE",
            reason="user preference",
            originating_phase="readiness",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "nested" / "dir" / "escalation.json"
            write_escalation(target, payload)
            self.assertTrue(target.is_file())

    def test_read_raises_on_invalid_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "bad.json"
            target.write_text(json.dumps({"severity": "CRITICAL"}), encoding="utf-8")
            with self.assertRaises(EscalationError):
                read_escalation(target)

    def test_read_raises_on_unknown_api_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "future.json"
            target.write_text(
                json.dumps(
                    {
                        "api_version": 999,
                        "story_key": "1-1-a",
                        "severity": "CRITICAL",
                        "reason": "x",
                        "originating_phase": "gate",
                        "suggested_action": "",
                        "waiver_ref": "",
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(EscalationError):
                read_escalation(target)


if __name__ == "__main__":
    unittest.main()
