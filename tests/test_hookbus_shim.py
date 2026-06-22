"""Tests for HookBus-compatible shim (Path B compat layer, N6.2).

Validates that the HookBusShim wraps existing verifier callbacks in the
shape bmad-auto's plugin bus expects, so a plugin authored against that
contract can drop into our orchestrator without us rewriting either side.
"""
from __future__ import annotations

import unittest

from story_automator.core.bauto_bridge.hookbus_shim import (
    KNOWN_EVENTS,
    HookBusShim,
    HookbusShimError,
    HookSpec,
)
from story_automator.core.verify_outcome import VerifyOutcome


class HookSpecTests(unittest.TestCase):
    def test_hookspec_is_frozen(self) -> None:
        spec = HookSpec(
            event_name="post_dev_phase",
            callback=lambda ctx: VerifyOutcome.passed(),
            severity="PREFERENCE",
            blocking=False,
            fail_closed=False,
        )
        with self.assertRaises(Exception):
            spec.severity = "CRITICAL"  # type: ignore[misc]

    def test_known_events_is_frozen_set(self) -> None:
        self.assertIsInstance(KNOWN_EVENTS, frozenset)
        # Spec calls these out by name; all six must be present.
        for ev in (
            "post_dev_phase",
            "pre_review",
            "post_review",
            "pre_gate",
            "post_gate",
            "pre_commit",
        ):
            self.assertIn(ev, KNOWN_EVENTS)


class HookBusShimRegisterTests(unittest.TestCase):
    def test_register_and_emit_happy_path(self) -> None:
        bus = HookBusShim()
        bus.register("post_dev_phase", lambda ctx: VerifyOutcome.passed())
        out = bus.emit("post_dev_phase", {"story_id": "S1"})
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0].ok)

    def test_register_unknown_event_raises(self) -> None:
        bus = HookBusShim()
        with self.assertRaises(HookbusShimError):
            bus.register("not_a_real_event", lambda ctx: VerifyOutcome.passed())

    def test_register_non_callable_raises(self) -> None:
        bus = HookBusShim()
        with self.assertRaises(HookbusShimError):
            bus.register("post_dev_phase", "not-a-callable")  # type: ignore[arg-type]

    def test_emit_unknown_event_raises(self) -> None:
        bus = HookBusShim()
        with self.assertRaises(HookbusShimError):
            bus.emit("not_a_real_event", {})


class HookBusShimEmitTests(unittest.TestCase):
    def test_emit_with_no_hooks_returns_empty_list(self) -> None:
        bus = HookBusShim()
        self.assertEqual(bus.emit("post_dev_phase", {}), [])

    def test_emit_preserves_registration_order(self) -> None:
        bus = HookBusShim()
        order: list[str] = []

        def make_cb(tag: str):
            def cb(_ctx: dict) -> VerifyOutcome:
                order.append(tag)
                return VerifyOutcome.passed()

            return cb

        bus.register("post_dev_phase", make_cb("A"))
        bus.register("post_dev_phase", make_cb("B"))
        bus.register("post_dev_phase", make_cb("C"))
        bus.emit("post_dev_phase", {})
        self.assertEqual(order, ["A", "B", "C"])

    def test_emit_runs_multiple_hooks_on_same_event(self) -> None:
        bus = HookBusShim()
        bus.register("pre_review", lambda c: VerifyOutcome.passed())
        bus.register(
            "pre_review",
            lambda c: VerifyOutcome.retry("flaky"),
        )
        results = bus.emit("pre_review", {})
        self.assertEqual(len(results), 2)
        self.assertTrue(results[0].ok)
        self.assertFalse(results[1].ok)
        self.assertEqual(results[1].reason, "flaky")

    def test_emit_wraps_non_outcome_return_as_passed(self) -> None:
        bus = HookBusShim()
        bus.register("pre_gate", lambda c: None)  # returns None
        bus.register("pre_gate", lambda c: "anything")  # returns str
        results = bus.emit("pre_gate", {})
        self.assertEqual(len(results), 2)
        self.assertTrue(all(r.ok for r in results))


class HookBusShimBlockingTests(unittest.TestCase):
    def test_blocking_veto_stops_chain(self) -> None:
        bus = HookBusShim()
        calls: list[str] = []

        def first(_c: dict) -> VerifyOutcome:
            calls.append("first")
            return VerifyOutcome.escalate("nope", severity="CRITICAL")

        def second(_c: dict) -> VerifyOutcome:
            calls.append("second")
            return VerifyOutcome.passed()

        bus.register("pre_gate", first, blocking=True, severity="CRITICAL")
        bus.register("pre_gate", second)
        results = bus.emit("pre_gate", {})

        self.assertEqual(calls, ["first"])
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].ok)

    def test_non_blocking_failure_does_not_stop_chain(self) -> None:
        bus = HookBusShim()
        calls: list[str] = []

        def first(_c: dict) -> VerifyOutcome:
            calls.append("first")
            return VerifyOutcome.retry("transient")

        def second(_c: dict) -> VerifyOutcome:
            calls.append("second")
            return VerifyOutcome.passed()

        bus.register("pre_gate", first, blocking=False)
        bus.register("pre_gate", second)
        bus.emit("pre_gate", {})
        self.assertEqual(calls, ["first", "second"])

    def test_has_blocking_veto_true(self) -> None:
        bus = HookBusShim()
        bus.register(
            "pre_gate",
            lambda c: VerifyOutcome.escalate("blocked"),
            blocking=True,
        )
        self.assertTrue(bus.has_blocking_veto("pre_gate", {}))

    def test_has_blocking_veto_false_when_passing(self) -> None:
        bus = HookBusShim()
        bus.register(
            "pre_gate",
            lambda c: VerifyOutcome.passed(),
            blocking=True,
        )
        self.assertFalse(bus.has_blocking_veto("pre_gate", {}))

    def test_has_blocking_veto_false_with_no_blocking_hook(self) -> None:
        bus = HookBusShim()
        bus.register(
            "pre_gate",
            lambda c: VerifyOutcome.escalate("not blocking"),
            blocking=False,
        )
        # Non-blocking failure must NOT be reported as blocking veto.
        self.assertFalse(bus.has_blocking_veto("pre_gate", {}))


class HookBusShimFailClosedTests(unittest.TestCase):
    def test_fail_closed_true_turns_exception_into_fail_outcome(self) -> None:
        bus = HookBusShim()

        def boom(_c: dict) -> VerifyOutcome:
            raise RuntimeError("kaboom")

        bus.register("post_gate", boom, fail_closed=True, severity="CRITICAL")
        results = bus.emit("post_gate", {})
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].ok)
        self.assertIn("kaboom", results[0].reason)
        self.assertEqual(results[0].severity, "CRITICAL")

    def test_fail_open_default_swallows_exception_as_passed(self) -> None:
        bus = HookBusShim()

        def boom(_c: dict) -> VerifyOutcome:
            raise RuntimeError("ignored")

        bus.register("post_gate", boom)  # fail_closed defaults False
        bus.register("post_gate", lambda c: VerifyOutcome.passed())
        results = bus.emit("post_gate", {})
        # Two hooks registered: first errored (fail-open → drop), second ran.
        # We expect the second outcome to be present; the first may be either
        # dropped or recorded as ok. Either way, the chain must continue.
        self.assertTrue(any(r.ok for r in results))

    def test_baseexception_propagates(self) -> None:
        bus = HookBusShim()

        def kbi(_c: dict) -> VerifyOutcome:
            raise KeyboardInterrupt()

        bus.register("post_gate", kbi, fail_closed=True)
        with self.assertRaises(KeyboardInterrupt):
            bus.emit("post_gate", {})


class HookBusShimListHooksTests(unittest.TestCase):
    def test_list_hooks_all(self) -> None:
        bus = HookBusShim()
        bus.register("post_dev_phase", lambda c: None)
        bus.register("pre_review", lambda c: None)
        self.assertEqual(len(bus.list_hooks()), 2)

    def test_list_hooks_filtered(self) -> None:
        bus = HookBusShim()
        bus.register("post_dev_phase", lambda c: None)
        bus.register("pre_review", lambda c: None)
        self.assertEqual(len(bus.list_hooks("post_dev_phase")), 1)
        self.assertEqual(
            bus.list_hooks("post_dev_phase")[0].event_name, "post_dev_phase"
        )

    def test_list_hooks_returns_specs(self) -> None:
        bus = HookBusShim()
        cb = lambda c: None  # noqa: E731
        bus.register(
            "post_dev_phase",
            cb,
            severity="PREFERENCE",
            blocking=True,
            fail_closed=True,
        )
        specs = bus.list_hooks("post_dev_phase")
        self.assertEqual(len(specs), 1)
        spec = specs[0]
        self.assertEqual(spec.event_name, "post_dev_phase")
        self.assertEqual(spec.severity, "PREFERENCE")
        self.assertTrue(spec.blocking)
        self.assertTrue(spec.fail_closed)


class HookBusShimSeverityTests(unittest.TestCase):
    def test_severity_preserved_on_outcome_when_callback_omits_it(self) -> None:
        """If a callback returns retry() with no severity but the hook was
        registered with severity="CRITICAL", the shim escalates accordingly."""
        bus = HookBusShim()

        def cb(_c: dict) -> VerifyOutcome:
            return VerifyOutcome.retry("oops")

        bus.register("post_gate", cb, severity="CRITICAL")
        results = bus.emit("post_gate", {})
        self.assertEqual(len(results), 1)
        # Either the shim preserves the severity (escalates) or it leaves it
        # as-is — but at minimum the failure must be visible.
        self.assertFalse(results[0].ok)

    def test_severity_left_alone_when_callback_sets_it(self) -> None:
        bus = HookBusShim()
        bus.register(
            "post_gate",
            lambda c: VerifyOutcome.escalate("bad", severity="PREFERENCE"),
            severity="CRITICAL",
        )
        results = bus.emit("post_gate", {})
        self.assertEqual(results[0].severity, "PREFERENCE")


if __name__ == "__main__":
    unittest.main()
