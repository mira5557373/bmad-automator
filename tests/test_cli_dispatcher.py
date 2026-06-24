"""Tests for ``core/cli_dispatcher.py`` — N6.5 Path B keystone.

The dispatcher consumes a :class:`CLIProfile` plus a :class:`SessionIntent`,
invokes a runner (default: a placeholder stub for ``claude-code``; tests inject
their own mock), detects completion via per-CLI stop-hook dialect, and falls
back to the lie-detector when the stop-hook is silent.

These tests use only injected mock runners — no real tmux, no real CLI
processes. They do exercise real git in temporary repos for the lie-detector
fallback paths (mirroring ``test_lie_detector.py``).
"""
from __future__ import annotations

import dataclasses
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

from story_automator.core.cli_dispatcher import (
    STOP_HOOK_DIALECTS,
    DispatcherError,
    DispatchResult,
    SessionIntent,
    adapter_for_stage,
    detect_stop,
    dispatch_session,
)
from story_automator.core.cli_profile import CLIProfile, claude_default
from story_automator.core.bauto_bridge.hookbus_shim import HookBusShim
from story_automator.core.verify_outcome import VerifyOutcome

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _init_repo(path: Path) -> str:
    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "t@t.com"],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "T"],
        capture_output=True, check=True,
    )
    (path / "a").write_text("1\n")
    subprocess.run(
        ["git", "-C", str(path), "add", "."], capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", "init"],
        capture_output=True, check=True,
    )
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def _add_commit(path: Path, filename: str) -> str:
    (path / filename).write_text("more\n")
    subprocess.run(
        ["git", "-C", str(path), "add", "."], capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", filename],
        capture_output=True, check=True,
    )
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def _codex_profile() -> CLIProfile:
    base = claude_default()
    return dataclasses.replace(base, cli_id="codex", binary="codex", hook_dialect="codex")


def _gemini_profile() -> CLIProfile:
    base = claude_default()
    return dataclasses.replace(
        base, cli_id="gemini-cli", binary="gemini", hook_dialect="gemini"
    )


def _none_profile() -> CLIProfile:
    base = claude_default()
    return dataclasses.replace(base, cli_id="claude-code", hook_dialect="none")


def _make_intent(workspace: str, baseline: str, *, timeout_s: float = 1800.0) -> SessionIntent:
    return SessionIntent(
        story_key="STORY-1",
        phase="dev-running",
        baseline_sha=baseline,
        prompt="/skill do-thing",
        workspace=workspace,
        timeout_s=timeout_s,
    )


def _runner(stdout_tail: str, head_sha: str, *, session_id: str = "S-1") -> Any:
    """Build an injectable runtime_invoker that returns a synthetic raw result.

    The dispatcher post-processes the raw runner output (stdout_tail +
    head_sha) into a DispatchResult. The runner returns a dict so the
    dispatcher's classification logic is the unit under test, not the
    runner's plumbing.
    """

    def _invoke(*, profile: CLIProfile, intent: SessionIntent) -> dict[str, Any]:
        return {
            "stdout_tail": stdout_tail,
            "head_sha": head_sha,
            "session_id": session_id,
            "stderr_tail": "",
            "timed_out": False,
        }

    return _invoke


def _timeout_runner(stderr_tail: str = "killed by SIGKILL after 30m"):
    def _invoke(*, profile: CLIProfile, intent: SessionIntent) -> dict[str, Any]:
        raise TimeoutError(stderr_tail)

    return _invoke


# ---------------------------------------------------------------------------
# shape tests
# ---------------------------------------------------------------------------


class SessionIntentShapeTests(unittest.TestCase):
    def test_frozen(self) -> None:
        intent = _make_intent("/tmp/ws", "abc")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            intent.story_key = "X"  # type: ignore[misc]

    def test_required_fields(self) -> None:
        intent = SessionIntent(
            story_key="S1", phase="dev-running", baseline_sha="deadbeef",
            prompt="/p", workspace="/tmp/ws",
        )
        self.assertEqual(intent.story_key, "S1")
        self.assertEqual(intent.phase, "dev-running")
        self.assertEqual(intent.baseline_sha, "deadbeef")
        self.assertEqual(intent.prompt, "/p")
        self.assertEqual(intent.workspace, "/tmp/ws")

    def test_default_timeout(self) -> None:
        intent = _make_intent("/tmp/ws", "abc")
        self.assertEqual(intent.timeout_s, 1800.0)

    def test_equality(self) -> None:
        a = _make_intent("/tmp/ws", "abc")
        b = _make_intent("/tmp/ws", "abc")
        self.assertEqual(a, b)


class DispatchResultShapeTests(unittest.TestCase):
    def test_frozen(self) -> None:
        r = DispatchResult(
            ok=True, cli_id="claude-code", head_sha="abc", stop_reason="stop-hook",
            verify_outcome={"ok": True},
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            r.ok = False  # type: ignore[misc]

    def test_defaults(self) -> None:
        r = DispatchResult(
            ok=True, cli_id="claude-code", head_sha="abc", stop_reason="stop-hook",
            verify_outcome={"ok": True},
        )
        self.assertEqual(r.session_id, "")
        self.assertEqual(r.stderr_tail, "")

    def test_ok_is_bool(self) -> None:
        r = DispatchResult(
            ok=False, cli_id="codex", head_sha="x", stop_reason="error",
            verify_outcome={"ok": False},
        )
        self.assertIsInstance(r.ok, bool)
        self.assertFalse(r.ok)

    def test_verify_outcome_is_dict(self) -> None:
        outcome_dict = VerifyOutcome.passed().to_dict()
        r = DispatchResult(
            ok=True, cli_id="claude-code", head_sha="x", stop_reason="lie-detector",
            verify_outcome=outcome_dict,
        )
        self.assertIsInstance(r.verify_outcome, dict)
        self.assertEqual(r.verify_outcome["ok"], True)


# ---------------------------------------------------------------------------
# STOP_HOOK_DIALECTS tests
# ---------------------------------------------------------------------------


class StopHookDialectsTests(unittest.TestCase):
    def test_has_claude(self) -> None:
        self.assertIn("claude", STOP_HOOK_DIALECTS)

    def test_has_codex(self) -> None:
        self.assertIn("codex", STOP_HOOK_DIALECTS)

    def test_has_gemini(self) -> None:
        self.assertIn("gemini", STOP_HOOK_DIALECTS)

    def test_has_none(self) -> None:
        self.assertIn("none", STOP_HOOK_DIALECTS)
        self.assertEqual(STOP_HOOK_DIALECTS["none"], "")

    def test_non_none_dialects_have_non_empty_marker(self) -> None:
        for key, marker in STOP_HOOK_DIALECTS.items():
            if key == "none":
                continue
            self.assertTrue(marker, f"{key} must have a non-empty marker")


# ---------------------------------------------------------------------------
# detect_stop tests
# ---------------------------------------------------------------------------


class DetectStopTests(unittest.TestCase):
    def test_claude_marker_detected(self) -> None:
        tail = "... noise " + STOP_HOOK_DIALECTS["claude"] + " trailing"
        self.assertTrue(detect_stop(tail, "claude"))

    def test_codex_marker_not_in_gemini_tail(self) -> None:
        tail = "noise " + STOP_HOOK_DIALECTS["gemini"]
        self.assertFalse(detect_stop(tail, "codex"))

    def test_empty_stdout_false(self) -> None:
        self.assertFalse(detect_stop("", "claude"))

    def test_none_dialect_always_false(self) -> None:
        self.assertFalse(detect_stop("anything " + STOP_HOOK_DIALECTS["claude"], "none"))

    def test_case_insensitive_within_dialect(self) -> None:
        marker = STOP_HOOK_DIALECTS["codex"]
        tail = marker.upper()
        self.assertTrue(detect_stop(tail, "codex"))

    def test_trailing_whitespace_tolerated(self) -> None:
        tail = STOP_HOOK_DIALECTS["gemini"] + "   \n\n"
        self.assertTrue(detect_stop(tail, "gemini"))


# ---------------------------------------------------------------------------
# adapter_for_stage tests
# ---------------------------------------------------------------------------


class AdapterForStageTests(unittest.TestCase):
    def test_dev_stage_resolves(self) -> None:
        policy = {"adapter": {"dev": {"name": "codex"}}}
        self.assertEqual(adapter_for_stage(policy, "dev"), "codex")

    def test_review_stage_resolves(self) -> None:
        policy = {"adapter": {"review": {"name": "gemini-cli"}}}
        self.assertEqual(adapter_for_stage(policy, "review"), "gemini-cli")

    def test_triage_stage_resolves(self) -> None:
        policy = {"adapter": {"triage": {"name": "claude-code"}}}
        self.assertEqual(adapter_for_stage(policy, "triage"), "claude-code")

    def test_default_is_claude_code(self) -> None:
        self.assertEqual(adapter_for_stage({}, "dev"), "claude-code")

    def test_unknown_stage_raises(self) -> None:
        with self.assertRaises(DispatcherError):
            adapter_for_stage({}, "stranger-danger")


# ---------------------------------------------------------------------------
# dispatch_session — stop-hook detection
# ---------------------------------------------------------------------------


class DispatchSessionStopHookTests(unittest.TestCase):
    def test_claude_dialect_hits_stop_hook(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = _init_repo(Path(tmp))
            head = _add_commit(Path(tmp), "b")
            tail = "everything fine " + STOP_HOOK_DIALECTS["claude"] + " bye"
            res = dispatch_session(
                _make_intent(tmp, base),
                profile=claude_default(),
                runtime_invoker=_runner(tail, head),
            )
            self.assertEqual(res.stop_reason, "stop-hook")
            self.assertTrue(res.ok)
            self.assertEqual(res.head_sha, head)
            self.assertEqual(res.cli_id, "claude-code")

    def test_codex_dialect_hits_stop_hook(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = _init_repo(Path(tmp))
            head = _add_commit(Path(tmp), "b")
            tail = STOP_HOOK_DIALECTS["codex"]
            res = dispatch_session(
                _make_intent(tmp, base),
                profile=_codex_profile(),
                runtime_invoker=_runner(tail, head),
            )
            self.assertEqual(res.stop_reason, "stop-hook")
            self.assertTrue(res.ok)
            self.assertEqual(res.cli_id, "codex")

    def test_gemini_dialect_hits_stop_hook(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = _init_repo(Path(tmp))
            head = _add_commit(Path(tmp), "b")
            tail = STOP_HOOK_DIALECTS["gemini"]
            res = dispatch_session(
                _make_intent(tmp, base),
                profile=_gemini_profile(),
                runtime_invoker=_runner(tail, head),
            )
            self.assertEqual(res.stop_reason, "stop-hook")
            self.assertTrue(res.ok)
            self.assertEqual(res.cli_id, "gemini-cli")

    def test_none_dialect_skips_to_lie_detector(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = _init_repo(Path(tmp))
            head = _add_commit(Path(tmp), "b")
            # stdout has a claude marker but profile is "none" → must be ignored.
            tail = STOP_HOOK_DIALECTS["claude"]
            res = dispatch_session(
                _make_intent(tmp, base),
                profile=_none_profile(),
                runtime_invoker=_runner(tail, head),
            )
            self.assertEqual(res.stop_reason, "lie-detector")
            self.assertTrue(res.ok)

    def test_stop_hook_short_circuits(self) -> None:
        # Even when HEAD == baseline (which would have made lie-detector fail
        # with baseline_drift), the stop-hook marker wins.
        with tempfile.TemporaryDirectory() as tmp:
            base = _init_repo(Path(tmp))
            tail = STOP_HOOK_DIALECTS["claude"]
            res = dispatch_session(
                _make_intent(tmp, base),
                profile=claude_default(),
                runtime_invoker=_runner(tail, base),
            )
            self.assertEqual(res.stop_reason, "stop-hook")
            self.assertTrue(res.ok)


# ---------------------------------------------------------------------------
# dispatch_session — lie-detector fallback
# ---------------------------------------------------------------------------


class DispatchSessionLieDetectorFallbackTests(unittest.TestCase):
    def test_head_matches_returns_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = _init_repo(Path(tmp))
            head = _add_commit(Path(tmp), "b")
            res = dispatch_session(
                _make_intent(tmp, base),
                profile=claude_default(),
                runtime_invoker=_runner("no marker here", head),
            )
            self.assertEqual(res.stop_reason, "lie-detector")
            self.assertTrue(res.ok)
            self.assertEqual(res.verify_outcome["ok"], True)

    def test_baseline_drift_returns_not_ok(self) -> None:
        # head_sha advertised by the runner == baseline → lie-detector says
        # baseline_drift because HEAD didn't move.
        with tempfile.TemporaryDirectory() as tmp:
            base = _init_repo(Path(tmp))
            res = dispatch_session(
                _make_intent(tmp, base),
                profile=claude_default(),
                runtime_invoker=_runner("no marker", base),
            )
            self.assertEqual(res.stop_reason, "lie-detector")
            self.assertFalse(res.ok)
            self.assertEqual(res.verify_outcome["reason"], "baseline_drift")
            self.assertTrue(res.verify_outcome["fixable"])

    def test_unexpected_head_returns_error(self) -> None:
        # runner advertises a head that doesn't match what git actually says,
        # and HEAD isn't baseline either → unexpected_head retry (not
        # CRITICAL; surfaces as stop_reason="lie-detector" with ok=False).
        with tempfile.TemporaryDirectory() as tmp:
            base = _init_repo(Path(tmp))
            _add_commit(Path(tmp), "b")
            fake_head = "0" * 40
            res = dispatch_session(
                _make_intent(tmp, base),
                profile=claude_default(),
                runtime_invoker=_runner("no marker", fake_head),
            )
            self.assertEqual(res.stop_reason, "lie-detector")
            self.assertFalse(res.ok)
            self.assertEqual(res.verify_outcome["reason"], "unexpected_head")
            self.assertFalse(res.verify_outcome["fixable"])

    def test_git_unavailable_is_critical(self) -> None:
        # workspace is not a git repo at all → lie-detector escalates CRITICAL.
        with tempfile.TemporaryDirectory() as tmp:
            res = dispatch_session(
                _make_intent(tmp, "deadbeef" * 5),
                profile=claude_default(),
                runtime_invoker=_runner("no marker", "feedface" * 5),
            )
            self.assertEqual(res.stop_reason, "error")
            self.assertFalse(res.ok)
            self.assertEqual(res.verify_outcome["severity"], "CRITICAL")

    def test_verify_outcome_shape_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = _init_repo(Path(tmp))
            head = _add_commit(Path(tmp), "b")
            res = dispatch_session(
                _make_intent(tmp, base),
                profile=claude_default(),
                runtime_invoker=_runner("no marker", head),
            )
            # Wire form: must contain the four keys
            self.assertEqual(
                set(res.verify_outcome.keys()),
                {"fixable", "ok", "reason", "severity"},
            )

    def test_baseline_drift_carries_fixable_True(self) -> None:
        # Different drift type: re-verifies fixable=True is preserved.
        with tempfile.TemporaryDirectory() as tmp:
            base = _init_repo(Path(tmp))
            res = dispatch_session(
                _make_intent(tmp, base),
                profile=_codex_profile(),
                runtime_invoker=_runner("blank tail", base),
            )
            self.assertFalse(res.ok)
            self.assertTrue(res.verify_outcome["fixable"])


# ---------------------------------------------------------------------------
# dispatch_session — timeout
# ---------------------------------------------------------------------------


class DispatchSessionTimeoutTests(unittest.TestCase):
    def test_timeouterror_marks_stop_reason_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = _init_repo(Path(tmp))
            res = dispatch_session(
                _make_intent(tmp, base),
                profile=claude_default(),
                runtime_invoker=_timeout_runner(),
            )
            self.assertEqual(res.stop_reason, "timeout")
            self.assertFalse(res.ok)

    def test_stderr_tail_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = _init_repo(Path(tmp))
            res = dispatch_session(
                _make_intent(tmp, base),
                profile=claude_default(),
                runtime_invoker=_timeout_runner("died with SIGKILL"),
            )
            self.assertIn("SIGKILL", res.stderr_tail)

    def test_timeout_verify_outcome_reflects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = _init_repo(Path(tmp))
            res = dispatch_session(
                _make_intent(tmp, base),
                profile=claude_default(),
                runtime_invoker=_timeout_runner(),
            )
            self.assertFalse(res.verify_outcome["ok"])
            self.assertEqual(res.verify_outcome["reason"], "timeout")


# ---------------------------------------------------------------------------
# dispatch_session — invoker exception classification
# ---------------------------------------------------------------------------


class DispatchSessionInvokerExceptionTests(unittest.TestCase):
    """Regression: docstring promise "Never raises on CLI-side or git-side
    failure" must hold for non-TimeoutError runtime exceptions from the
    invoker. NotImplementedError is the documented exception — it
    propagates so the orchestrator can route the default-invoker switch's
    "no shim for this cli_id" signal. All other Exception subclasses
    (OSError, RuntimeError, ValueError, subprocess.CalledProcessError,
    KeyError from a misconfigured prompt_template, etc.) must surface as
    DispatchResult(stop_reason="error", ok=False).
    """

    def _raising_runner(self, exc: Exception):
        def _invoke(*, profile: CLIProfile, intent: SessionIntent) -> dict[str, Any]:
            raise exc
        return _invoke

    def test_oserror_classified_as_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = _init_repo(Path(tmp))
            res = dispatch_session(
                _make_intent(tmp, base),
                profile=claude_default(),
                runtime_invoker=self._raising_runner(OSError("boom")),
            )
            self.assertEqual(res.stop_reason, "error")
            self.assertFalse(res.ok)
            self.assertEqual(res.cli_id, "claude-code")
            self.assertEqual(res.verify_outcome["severity"], "CRITICAL")
            self.assertEqual(res.verify_outcome["reason"], "invoker_error")
            self.assertIn("OSError", res.stderr_tail)
            self.assertIn("boom", res.stderr_tail)

    def test_runtimeerror_classified_as_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = _init_repo(Path(tmp))
            res = dispatch_session(
                _make_intent(tmp, base),
                profile=claude_default(),
                runtime_invoker=self._raising_runner(RuntimeError("kaput")),
            )
            self.assertEqual(res.stop_reason, "error")
            self.assertFalse(res.ok)
            self.assertIn("RuntimeError", res.stderr_tail)

    def test_subprocess_calledprocesserror_classified_as_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = _init_repo(Path(tmp))
            exc = subprocess.CalledProcessError(
                1, ["tmux", "send-keys"], stderr=b"tmux: server not running",
            )
            res = dispatch_session(
                _make_intent(tmp, base),
                profile=claude_default(),
                runtime_invoker=self._raising_runner(exc),
            )
            self.assertEqual(res.stop_reason, "error")
            self.assertFalse(res.ok)
            self.assertIn("CalledProcessError", res.stderr_tail)

    def test_notimplementederror_propagates(self) -> None:
        # NotImplementedError is the documented routing signal for an
        # un-wired cli_id; the dispatcher must NOT classify it as an
        # invoker error so the orchestrator can route loudly. Pinned by
        # test_no_invoker_routes_through_default_invoker_for_codex in
        # test_cli_dispatcher_invokers.py.
        with tempfile.TemporaryDirectory() as tmp:
            base = _init_repo(Path(tmp))
            with self.assertRaises(NotImplementedError):
                dispatch_session(
                    _make_intent(tmp, base),
                    profile=claude_default(),
                    runtime_invoker=self._raising_runner(
                        NotImplementedError("no shim for codex"),
                    ),
                )

    def test_keyboardinterrupt_propagates(self) -> None:
        # BaseException subclasses (KeyboardInterrupt, SystemExit) must
        # still propagate — operator Ctrl-C must reach the orchestrator.
        with tempfile.TemporaryDirectory() as tmp:
            base = _init_repo(Path(tmp))
            with self.assertRaises(KeyboardInterrupt):
                dispatch_session(
                    _make_intent(tmp, base),
                    profile=claude_default(),
                    runtime_invoker=self._raising_runner(KeyboardInterrupt()),
                )


# ---------------------------------------------------------------------------
# dispatch_session — plugin integration (HookBusShim)
# ---------------------------------------------------------------------------


class DispatchSessionPluginIntegrationTests(unittest.TestCase):
    def test_hookbus_can_observe_cli_id_at_pre_review(self) -> None:
        # The HookBusShim itself doesn't currently fire from inside dispatch_session
        # (that wiring belongs to the orchestrator), but we can register a hook,
        # emit() with the dispatcher's cli_id, and verify the contract round-trip.
        seen: list[str] = []

        def hook(ctx: dict[str, Any]) -> VerifyOutcome:
            seen.append(ctx.get("cli_id", ""))
            return VerifyOutcome.passed()

        bus = HookBusShim()
        bus.register("pre_review", hook)
        with tempfile.TemporaryDirectory() as tmp:
            base = _init_repo(Path(tmp))
            head = _add_commit(Path(tmp), "b")
            res = dispatch_session(
                _make_intent(tmp, base),
                profile=claude_default(),
                runtime_invoker=_runner("no marker", head),
            )
            bus.emit("pre_review", {"cli_id": res.cli_id})
        self.assertEqual(seen, ["claude-code"])

    def test_hookbus_blocking_veto_contract(self) -> None:
        # Sanity: a blocking veto on pre_review surfaces via has_blocking_veto.
        # This locks in the integration contract that the dispatcher must
        # eventually honor; the dispatcher itself just exposes cli_id and
        # head_sha so an orchestrator-side bus can decide to halt.
        def veto(ctx: dict[str, Any]) -> VerifyOutcome:
            return VerifyOutcome.escalate("forbidden", severity="CRITICAL")

        bus = HookBusShim()
        bus.register("pre_review", veto, blocking=True)
        self.assertTrue(bus.has_blocking_veto("pre_review", {"cli_id": "claude-code"}))


if __name__ == "__main__":
    unittest.main()
