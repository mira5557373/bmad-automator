from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path


class TelemetryEventsSurfaceTests(unittest.TestCase):
    def test_three_event_classes_exposed(self) -> None:
        from story_automator.core import telemetry_events as te

        self.assertTrue(hasattr(te, "EscalationRaised"))
        self.assertTrue(hasattr(te, "StoryStateChanged"))
        self.assertTrue(hasattr(te, "RetroAgentDispatched"))

    def test_event_name_matches_class_name(self) -> None:
        from story_automator.core.telemetry_events import (
            EscalationRaised,
            RetroAgentDispatched,
            StoryStateChanged,
        )

        self.assertEqual(EscalationRaised.event_name, "EscalationRaised")
        self.assertEqual(StoryStateChanged.event_name, "StoryStateChanged")
        self.assertEqual(RetroAgentDispatched.event_name, "RetroAgentDispatched")

    def test_to_dict_round_trip(self) -> None:
        from story_automator.core.telemetry_events import EscalationRaised

        ev = EscalationRaised(
            trigger="review-loop",
            reason="Review loop exceeded max cycles (5/5)",
            correlation_id="c-1",
        )
        d = ev.to_dict()
        self.assertEqual(
            d,
            {
                "trigger": "review-loop",
                "reason": "Review loop exceeded max cycles (5/5)",
                "correlation_id": "c-1",
            },
        )

    def test_dataclass_is_frozen_and_kw_only(self) -> None:
        # Frozen so callers can't mutate after passing to append(); kw-only
        # so call-sites stay readable across the three carriers.
        from story_automator.core.telemetry_events import StoryStateChanged

        ev = StoryStateChanged(
            story="1.2", from_status="draft", to_status="qa", correlation_id="c-2"
        )
        with self.assertRaises(Exception):
            ev.story = "x"  # type: ignore[misc]

    def test_satisfies_audit_event_protocol(self) -> None:
        from story_automator.core.audit import Event
        from story_automator.core.telemetry_events import RetroAgentDispatched

        ev = RetroAgentDispatched(
            primary="claude", fallback="false", model="", correlation_id="c-3"
        )
        # runtime_checkable Protocol: isinstance check works structurally.
        self.assertIsInstance(ev, Event)


class StateAuditWrapperTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = os.environ.pop("BMAD_AUDIT_KEY", None)

    def tearDown(self) -> None:
        os.environ.pop("BMAD_AUDIT_KEY", None)
        if self._saved is not None:
            os.environ["BMAD_AUDIT_KEY"] = self._saved

    def test_short_circuits_when_policy_disables(self) -> None:
        from story_automator.commands.state import audit_state_change

        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "audit.jsonl"
            audit_state_change(
                {},
                target,
                story="1.2",
                from_status="draft",
                to_status="qa",
                correlation_id="c-1",
            )
            self.assertFalse(target.exists())

    def test_appends_when_policy_enables_and_key_set(self) -> None:
        import json

        from story_automator.commands.state import audit_state_change

        os.environ["BMAD_AUDIT_KEY"] = "test-canary-secret"
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "audit.jsonl"
            audit_state_change(
                {"security": {"audit_trail": True}},
                target,
                story="1.2",
                from_status="draft",
                to_status="qa",
                correlation_id="c-1",
            )
            line = target.read_text(encoding="utf-8").strip()
            rec = json.loads(line)
            self.assertEqual(rec["event"], "StoryStateChanged")
            self.assertEqual(
                rec["payload"],
                {
                    "story": "1.2",
                    "from_status": "draft",
                    "to_status": "qa",
                    "correlation_id": "c-1",
                },
            )

    def test_append_failure_propagates(self) -> None:
        # Simulate a lock-held error: a held FileLock at the same path
        # makes audit_for_policy + append raise AuditLockTimeout, and the
        # wrapper must re-raise (REQ-12: failures must not be swallowed).
        import filelock

        from story_automator.commands.state import audit_state_change
        from story_automator.core.audit import AuditLockTimeout

        os.environ["BMAD_AUDIT_KEY"] = "test-canary-secret"
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "audit.jsonl"
            held = filelock.FileLock(str(target) + ".lock")
            held.acquire(timeout=1)
            try:
                with self.assertRaises(AuditLockTimeout):
                    audit_state_change(
                        {"security": {"audit_trail": True}},
                        target,
                        story="1.2",
                        from_status="draft",
                        to_status="qa",
                        correlation_id="c-1",
                    )
            finally:
                held.release()


if __name__ == "__main__":
    unittest.main()
