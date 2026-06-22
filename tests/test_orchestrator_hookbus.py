"""Tests for HookBusShim wiring into commands/orchestrator.py (Path B N6.3).

Validates that orchestrator helper actions emit the six lifecycle events
through the module-level HookBusShim:

* ``post_dev_phase`` — fires after a successful ``verify-step session_exit``.
* ``pre_review`` / ``post_review`` — bracket ``verify-code-review``.
* ``pre_gate`` / ``post_gate`` — bracket the ``gate`` subdispatcher.
* ``pre_commit`` — fires from ``commit-ready`` when a story is ready
  to commit.

Wiring is purely additive: with no hooks registered, behavior is
identical to the pre-N6.3 code path. The test exercises that
default-disabled invariant alongside the emit-order contract.
"""
from __future__ import annotations

import tempfile
import unittest
from unittest import mock

from story_automator.commands import orchestrator
from story_automator.core.bauto_bridge.hookbus_shim import (
    KNOWN_EVENTS,
    HookBusShim,
)
from story_automator.core.sprint import SprintStatus
from story_automator.core.verify_outcome import VerifyOutcome


class _Bus:
    """Test harness: a HookBusShim that records the event order it saw."""

    def __init__(self) -> None:
        self.shim = HookBusShim()
        self.fired: list[str] = []

    def register_recorder(self, event: str) -> None:
        def _cb(_ctx: dict) -> VerifyOutcome:
            self.fired.append(event)
            return VerifyOutcome.passed()

        self.shim.register(event, _cb)


def _swap_bus(bus: HookBusShim):
    return mock.patch.object(orchestrator, "_HOOK_BUS", bus)


class GetHookBusTests(unittest.TestCase):
    """The module exposes a singleton bus that the public CLI uses."""

    def test_get_hook_bus_returns_singleton(self) -> None:
        first = orchestrator.get_hook_bus()
        second = orchestrator.get_hook_bus()
        self.assertIs(first, second)

    def test_singleton_is_hookbus_shim(self) -> None:
        bus = orchestrator.get_hook_bus()
        self.assertIsInstance(bus, HookBusShim)


class CommitReadyHookTests(unittest.TestCase):
    def test_commit_ready_fires_pre_commit_when_ready(self) -> None:
        bus = _Bus()
        bus.register_recorder("pre_commit")
        status = SprintStatus(
            found=True, story="2.1", status="Done", done=True, reason=""
        )
        with tempfile.TemporaryDirectory() as tmp:
            with _swap_bus(bus.shim), \
                mock.patch.object(orchestrator, "get_project_root", return_value=tmp), \
                mock.patch.object(orchestrator, "sprint_status_get", return_value=status), \
                mock.patch.object(orchestrator, "run_cmd", return_value=("M file\n", 0)), \
                mock.patch.object(orchestrator, "_emit_safe"):
                rc = orchestrator._commit_ready(["2.1"])
        self.assertEqual(rc, 0)
        self.assertEqual(bus.fired, ["pre_commit"])

    def test_commit_ready_does_not_fire_when_not_ready(self) -> None:
        bus = _Bus()
        bus.register_recorder("pre_commit")
        status = SprintStatus(
            found=True, story="2.1", status="InProgress", done=False, reason=""
        )
        with tempfile.TemporaryDirectory() as tmp:
            with _swap_bus(bus.shim), \
                mock.patch.object(orchestrator, "get_project_root", return_value=tmp), \
                mock.patch.object(orchestrator, "sprint_status_get", return_value=status):
                rc = orchestrator._commit_ready(["2.1"])
        self.assertEqual(rc, 0)
        self.assertEqual(bus.fired, [])


class VerifyCodeReviewHookTests(unittest.TestCase):
    def test_verify_code_review_brackets_with_pre_post(self) -> None:
        bus = _Bus()
        bus.register_recorder("pre_review")
        bus.register_recorder("post_review")
        with tempfile.TemporaryDirectory() as tmp:
            with _swap_bus(bus.shim), \
                mock.patch.object(orchestrator, "get_project_root", return_value=tmp), \
                mock.patch.object(
                    orchestrator,
                    "verify_code_review_completion",
                    return_value={"verified": True, "cycle": 1, "issuesFound": 0},
                ), \
                mock.patch.object(orchestrator, "_emit_safe"):
                rc = orchestrator._verify_code_review(["2.1"])
        self.assertEqual(rc, 0)
        self.assertEqual(bus.fired, ["pre_review", "post_review"])


class GateHookTests(unittest.TestCase):
    def test_gate_subdispatch_brackets_with_pre_post(self) -> None:
        bus = _Bus()
        bus.register_recorder("pre_gate")
        bus.register_recorder("post_gate")
        with _swap_bus(bus.shim), \
            mock.patch("story_automator.commands.gate_cmd.gate_dispatch", return_value=0):
            rc = orchestrator._gate(["status"])
        self.assertEqual(rc, 0)
        self.assertEqual(bus.fired, ["pre_gate", "post_gate"])


class VerifyStepHookTests(unittest.TestCase):
    def test_verify_step_session_exit_emits_post_dev_phase(self) -> None:
        bus = _Bus()
        bus.register_recorder("post_dev_phase")
        with tempfile.TemporaryDirectory() as tmp:
            with _swap_bus(bus.shim), \
                mock.patch.object(orchestrator, "get_project_root", return_value=tmp), \
                mock.patch.object(
                    orchestrator,
                    "resolve_success_contract",
                    return_value={"verifier": "session_exit"},
                ), \
                mock.patch.object(
                    orchestrator,
                    "run_success_verifier",
                    return_value={"verified": True, "step": "session_exit"},
                ):
                rc = orchestrator._verify_step(["session_exit", "2.1"])
        self.assertEqual(rc, 0)
        self.assertEqual(bus.fired, ["post_dev_phase"])

    def test_verify_step_unknown_step_emits_nothing(self) -> None:
        """Default-disabled invariant: unknown steps fire no hook."""
        bus = _Bus()
        for ev in KNOWN_EVENTS:
            bus.register_recorder(ev)
        with tempfile.TemporaryDirectory() as tmp:
            with _swap_bus(bus.shim), \
                mock.patch.object(orchestrator, "get_project_root", return_value=tmp), \
                mock.patch.object(
                    orchestrator,
                    "resolve_success_contract",
                    return_value={"verifier": "create_story_artifact"},
                ), \
                mock.patch.object(
                    orchestrator,
                    "run_success_verifier",
                    return_value={"verified": True, "step": "create_story_artifact"},
                ):
                orchestrator._verify_step(["create_story_artifact", "2.1"])
        self.assertEqual(bus.fired, [])


class FullLifecycleOrderTests(unittest.TestCase):
    """Drive the orchestrator end-to-end across all six stages and assert
    the emit order matches the dev → review → gate → commit progression
    a story walks through."""

    def test_six_stage_order(self) -> None:
        bus = _Bus()
        for ev in (
            "post_dev_phase",
            "pre_review",
            "post_review",
            "pre_gate",
            "post_gate",
            "pre_commit",
        ):
            bus.register_recorder(ev)

        status = SprintStatus(
            found=True, story="2.1", status="Done", done=True, reason=""
        )

        with tempfile.TemporaryDirectory() as tmp:
            with _swap_bus(bus.shim), \
                mock.patch.object(orchestrator, "get_project_root", return_value=tmp), \
                mock.patch.object(
                    orchestrator,
                    "resolve_success_contract",
                    return_value={"verifier": "session_exit"},
                ), \
                mock.patch.object(
                    orchestrator,
                    "run_success_verifier",
                    return_value={"verified": True},
                ), \
                mock.patch.object(
                    orchestrator,
                    "verify_code_review_completion",
                    return_value={"verified": True, "cycle": 1, "issuesFound": 0},
                ), \
                mock.patch.object(
                    orchestrator, "sprint_status_get", return_value=status
                ), \
                mock.patch.object(orchestrator, "run_cmd", return_value=("M f\n", 0)), \
                mock.patch.object(orchestrator, "_emit_safe"), \
                mock.patch(
                    "story_automator.commands.gate_cmd.gate_dispatch",
                    return_value=0,
                ):
                orchestrator._verify_step(["session_exit", "2.1"])
                orchestrator._verify_code_review(["2.1"])
                orchestrator._gate(["status"])
                orchestrator._commit_ready(["2.1"])

        self.assertEqual(
            bus.fired,
            [
                "post_dev_phase",
                "pre_review",
                "post_review",
                "pre_gate",
                "post_gate",
                "pre_commit",
            ],
        )


class BlockingVetoTests(unittest.TestCase):
    """A blocking veto on pre_gate / pre_commit / pre_review halts the
    transition with a structured error and does NOT execute the wrapped
    action.

    The orchestrator must surface the veto so the caller sees the same
    contract the rest of the gate machinery uses (no silent skip)."""

    def test_pre_commit_veto_blocks_commit_ready(self) -> None:
        bus = HookBusShim()

        def _veto(_ctx: dict) -> VerifyOutcome:
            return VerifyOutcome.escalate("plugin says no", severity="CRITICAL")

        bus.register("pre_commit", _veto, blocking=True)

        status = SprintStatus(
            found=True, story="2.1", status="Done", done=True, reason=""
        )

        ran = {"cmd": False}

        def _mock_run_cmd(*_a, **_kw):
            ran["cmd"] = True
            return ("M f\n", 0)

        with tempfile.TemporaryDirectory() as tmp:
            with _swap_bus(bus), \
                mock.patch.object(orchestrator, "get_project_root", return_value=tmp), \
                mock.patch.object(orchestrator, "sprint_status_get", return_value=status), \
                mock.patch.object(orchestrator, "run_cmd", side_effect=_mock_run_cmd), \
                mock.patch.object(orchestrator, "_emit_safe"):
                rc = orchestrator._commit_ready(["2.1"])
        self.assertNotEqual(rc, 0)
        # The action was halted before we even ran git status.
        self.assertFalse(ran["cmd"])

    def test_pre_gate_veto_blocks_gate_dispatch(self) -> None:
        bus = HookBusShim()
        bus.register(
            "pre_gate",
            lambda _ctx: VerifyOutcome.escalate("nope"),
            blocking=True,
        )
        dispatched = {"called": False}

        def _fake_dispatch(_args: list[str]) -> int:
            dispatched["called"] = True
            return 0

        with _swap_bus(bus), \
            mock.patch(
                "story_automator.commands.gate_cmd.gate_dispatch",
                side_effect=_fake_dispatch,
            ):
            rc = orchestrator._gate(["status"])
        self.assertNotEqual(rc, 0)
        self.assertFalse(dispatched["called"])


if __name__ == "__main__":
    unittest.main()
