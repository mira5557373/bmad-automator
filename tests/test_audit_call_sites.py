from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
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


class AuditHooksTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = os.environ.pop("BMAD_AUDIT_KEY", None)

    def tearDown(self) -> None:
        os.environ.pop("BMAD_AUDIT_KEY", None)
        if self._saved is not None:
            os.environ["BMAD_AUDIT_KEY"] = self._saved

    def test_audit_path_for_uses_bmad_audit_subdir(self) -> None:
        from story_automator.commands._audit_hooks import _audit_path_for

        path = _audit_path_for("/tmp/proj")
        self.assertEqual(path, Path("/tmp/proj") / "_bmad" / "audit" / "audit.jsonl")

    def test_maybe_audit_event_short_circuits_on_disabled(self) -> None:
        # REQ-14: no I/O when policy gate is off.
        from story_automator.commands._audit_hooks import _maybe_audit_event
        from story_automator.core.telemetry_events import EscalationRaised

        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "_bmad" / "audit" / "audit.jsonl"
            _maybe_audit_event(
                {},
                target,
                EscalationRaised(
                    trigger="review-loop",
                    reason="r",
                    correlation_id="c-1",
                ),
            )
            self.assertFalse(target.exists())
            # And the parent dir was never created.
            self.assertFalse(target.parent.exists())

    def test_maybe_audit_event_writes_when_enabled(self) -> None:
        import json

        from story_automator.commands._audit_hooks import _maybe_audit_event
        from story_automator.core.telemetry_events import EscalationRaised

        os.environ["BMAD_AUDIT_KEY"] = "test-canary-secret"
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "audit.jsonl"
            _maybe_audit_event(
                {"security": {"audit_trail": True}},
                target,
                EscalationRaised(
                    trigger="review-loop",
                    reason="exceeded",
                    correlation_id="c-9",
                ),
            )
            rec = json.loads(target.read_text(encoding="utf-8").strip())
            self.assertEqual(rec["event"], "EscalationRaised")
            self.assertEqual(rec["payload"]["correlation_id"], "c-9")


class EscalateAuditIntegrationTests(unittest.TestCase):
    """Integration tests for the _escalate audit hook.

    We patch the policy loader and project-root lookups in
    ``story_automator.commands.orchestrator`` so the test does not
    depend on resolving a real bundled policy under a temp project root
    (``load_runtime_policy`` with explicit state_file goes through the
    legacy-mode path which ignores ``_bmad/bmm/story-automator.policy.json``
    overrides, so toggling via that file would not engage the gate).
    """

    def setUp(self) -> None:
        self._saved_key = os.environ.pop("BMAD_AUDIT_KEY", None)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def tearDown(self) -> None:
        os.environ.pop("BMAD_AUDIT_KEY", None)
        if self._saved_key is not None:
            os.environ["BMAD_AUDIT_KEY"] = self._saved_key

    def test_escalate_short_circuits_when_gate_off(self) -> None:
        from unittest import mock

        from story_automator.commands import orchestrator as orch

        with (
            mock.patch.object(
                orch,
                "load_runtime_policy",
                return_value={"security": {"audit_trail": False}},
            ),
            mock.patch.object(orch, "get_project_root", return_value=self._tmp.name),
        ):
            buf = io.StringIO()
            with redirect_stdout(buf):
                orch._escalate(["review-loop", "cycles=99"])
        self.assertFalse(
            (Path(self._tmp.name) / "_bmad" / "audit" / "audit.jsonl").exists()
        )

    def test_escalate_appends_when_gate_on(self) -> None:
        from unittest import mock

        from story_automator.commands import orchestrator as orch

        os.environ["BMAD_AUDIT_KEY"] = "test-canary-secret"
        with (
            mock.patch.object(
                orch,
                "load_runtime_policy",
                return_value={"security": {"audit_trail": True}},
            ),
            mock.patch.object(orch, "get_project_root", return_value=self._tmp.name),
        ):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = orch._escalate(["review-loop", "cycles=99"])
        self.assertEqual(rc, 0)
        out = json.loads(buf.getvalue().strip())
        self.assertTrue(out["escalate"])

        audit_path = Path(self._tmp.name) / "_bmad" / "audit" / "audit.jsonl"
        self.assertTrue(audit_path.exists())
        rec = json.loads(audit_path.read_text(encoding="utf-8").strip())
        self.assertEqual(rec["event"], "EscalationRaised")
        self.assertEqual(rec["payload"]["trigger"], "review-loop")
        self.assertIn("Review loop exceeded", rec["payload"]["reason"])

    def test_escalate_does_not_audit_non_escalating_dispatch(self) -> None:
        # A "review-loop" dispatch under the limit returns escalate=False.
        # That is not a security event and must not produce an audit row.
        from unittest import mock

        from story_automator.commands import orchestrator as orch

        os.environ["BMAD_AUDIT_KEY"] = "test-canary-secret"
        with (
            mock.patch.object(
                orch,
                "load_runtime_policy",
                return_value={"security": {"audit_trail": True}},
            ),
            mock.patch.object(orch, "get_project_root", return_value=self._tmp.name),
        ):
            buf = io.StringIO()
            with redirect_stdout(buf):
                orch._escalate(["review-loop", "cycles=0"])
        self.assertFalse(
            (Path(self._tmp.name) / "_bmad" / "audit" / "audit.jsonl").exists()
        )

    def test_escalate_preserves_policy_error_behavior(self) -> None:
        # The legacy contract: when load_runtime_policy raises PolicyError or
        # FileNotFoundError, _escalate prints {"escalate": true, "reason":
        # str(exc)} and returns 0. The new code must keep this behaviour.
        from unittest import mock

        from story_automator.commands import orchestrator as orch
        from story_automator.core.runtime_policy import PolicyError

        with (
            mock.patch.object(
                orch, "load_runtime_policy", side_effect=PolicyError("bad policy")
            ),
            mock.patch.object(orch, "get_project_root", return_value=self._tmp.name),
        ):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = orch._escalate(["review-loop", "cycles=99"])
        self.assertEqual(rc, 0)
        out = json.loads(buf.getvalue().strip())
        self.assertTrue(out["escalate"])
        self.assertIn("bad policy", out["reason"])


if __name__ == "__main__":
    unittest.main()
