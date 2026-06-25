"""Tests for ``core/cli_dispatcher_invokers.py`` — N6.5 follow-up.

The N6.5 dispatcher ships a thin classifier; the actual tmux-runner shim
lives in ``cli_dispatcher_invokers``. These tests verify:

  * ``default_invoker`` switches on ``profile.cli_id``: routes claude-code
    to the real shim, raises ``NotImplementedError`` (with cli_id-naming
    messages) for codex / gemini-cli / none / unknown ids.
  * ``claude_code_invoker`` builds a runner-contract dict by composing
    monkey-patchable hooks over the existing :mod:`tmux_runtime` public
    surface (spawn_session / session_status / verify_or_create_output /
    tmux_kill_session / inject_bmad_auto_env) — no tmux actually runs.
  * Timeout, env injection, and head_sha sourcing all observe the
    intent's contract.

No real tmux is spawned in these tests; we patch each module-level hook
on :mod:`cli_dispatcher_invokers`.
"""
from __future__ import annotations

import dataclasses
import os
import unittest
from typing import Any
from unittest import mock

from story_automator.core import cli_dispatcher_invokers as invokers
from story_automator.core.cli_dispatcher import (
    DispatchResult,
    SessionIntent,
    dispatch_session,
)
from story_automator.core.cli_profile import CLIProfile, claude_default


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _intent(workspace: str = "/tmp/ws", timeout_s: float = 1800.0) -> SessionIntent:
    return SessionIntent(
        story_key="STORY-1",
        phase="dev-running",
        baseline_sha="b" * 40,
        prompt="/skill do-thing",
        workspace=workspace,
        timeout_s=timeout_s,
    )


def _codex_profile() -> CLIProfile:
    return dataclasses.replace(
        claude_default(), cli_id="codex", binary="codex", hook_dialect="codex"
    )


def _gemini_profile() -> CLIProfile:
    return dataclasses.replace(
        claude_default(), cli_id="gemini-cli", binary="gemini", hook_dialect="gemini"
    )


class _StubHooks:
    """Context-managed monkey-patch for invokers module hooks.

    Defaults to a fast, happy-path stub:
      * spawn → (out="ok", code=0)
      * session_status → terminal "completed"
      * verify_output → "/tmp/output.txt"
      * read_output → "AGENT FINAL: done"
      * git_head → 40 hex 'a's
      * clock → monotonically increasing virtual time
      * sleep → no-op
      * kill_session → no-op
    """

    def __init__(self, **overrides: Any) -> None:
        self.spawn = mock.Mock(return_value=("ok", 0))
        self.status = mock.Mock(
            return_value={"status": "completed", "session_state": "success"}
        )
        self.verify = mock.Mock(return_value="/tmp/output.txt")
        self.read = mock.Mock(return_value="AGENT FINAL: done")
        self.git = mock.Mock(return_value="a" * 40)
        self.clock_seq = iter([0.0, 1.0, 2.0, 3.0, 4.0])
        self.clock = mock.Mock(side_effect=lambda: next(self.clock_seq, 9999.0))
        self.sleep = mock.Mock()
        self.kill = mock.Mock()
        for k, v in overrides.items():
            setattr(self, k, v)
        self._patchers: list[Any] = []

    def __enter__(self) -> "_StubHooks":
        targets = {
            "_spawn_session_hook": self.spawn,
            "_session_status_hook": self.status,
            "_verify_output_hook": self.verify,
            "_read_output_hook": self.read,
            "_git_head_hook": self.git,
            "_clock_hook": self.clock,
            "_sleep_hook": self.sleep,
            "_kill_session_hook": self.kill,
        }
        for name, value in targets.items():
            p = mock.patch.object(invokers, name, value)
            p.start()
            self._patchers.append(p)
        return self

    def __exit__(self, *exc: Any) -> None:
        for p in self._patchers:
            p.stop()


# ---------------------------------------------------------------------------
# default_invoker switch tests
# ---------------------------------------------------------------------------


class DefaultInvokerSwitchTests(unittest.TestCase):
    def test_claude_code_invoker_exists_and_callable(self) -> None:
        # 1. claude-code default invoker is callable, not a placeholder.
        self.assertTrue(callable(invokers.default_invoker))
        self.assertTrue(callable(invokers.claude_code_invoker))

    def test_claude_code_default_routes_to_shim(self) -> None:
        # 2. claude-code calls into tmux_runtime via the shim.
        with _StubHooks() as h:
            raw = invokers.default_invoker(
                profile=claude_default(), intent=_intent()
            )
        h.spawn.assert_called_once()
        # session, command, "claude", workspace
        args, _kwargs = h.spawn.call_args
        self.assertEqual(len(args), 4)
        self.assertEqual(args[2], "claude")
        self.assertEqual(args[3], "/tmp/ws")
        # The command must include the binary.
        self.assertIn("claude", args[1])
        self.assertIn("/skill do-thing", args[1])
        # Wire-shape sanity.
        self.assertEqual(set(raw.keys()),
                         {"stdout_tail", "head_sha", "session_id",
                          "stderr_tail", "timed_out"})

    def test_codex_raises_not_implemented(self) -> None:
        # 3. codex cli_id raises NotImplementedError with "codex" in message.
        with self.assertRaises(NotImplementedError) as cm:
            invokers.default_invoker(profile=_codex_profile(), intent=_intent())
        self.assertIn("codex", str(cm.exception).lower())

    def test_gemini_cli_raises_not_implemented(self) -> None:
        # 4. gemini-cli raises NotImplementedError mentioning gemini.
        with self.assertRaises(NotImplementedError) as cm:
            invokers.default_invoker(profile=_gemini_profile(), intent=_intent())
        self.assertIn("gemini", str(cm.exception).lower())

    def test_none_cli_id_raises_with_explicit_runtime_message(self) -> None:
        # 5. none cli_id raises mentioning explicit runtime_invoker.
        # We cannot construct cli_id="none" via CLIProfile validators —
        # KNOWN_CLI_IDS forbids it. So we forge one via dataclasses.replace
        # (which bypasses __post_init__) on top of a hook_dialect="none"
        # profile. The dispatcher's switch must still classify it.
        forged = dataclasses.replace(
            claude_default(), cli_id="none", hook_dialect="none"
        )
        with self.assertRaises(NotImplementedError) as cm:
            invokers.default_invoker(profile=forged, intent=_intent())
        msg = str(cm.exception)
        self.assertIn("runtime_invoker", msg)
        self.assertIn("none", msg.lower())

    def test_unknown_cli_id_raises_with_id_verbatim(self) -> None:
        # 6. unknown cli_id raises mentioning the cli_id verbatim.
        forged = dataclasses.replace(claude_default(), cli_id="aider-cli")
        with self.assertRaises(NotImplementedError) as cm:
            invokers.default_invoker(profile=forged, intent=_intent())
        self.assertIn("aider-cli", str(cm.exception))


# ---------------------------------------------------------------------------
# back-compat: dispatch_session with explicit runtime_invoker
# ---------------------------------------------------------------------------


class DispatchSessionBackCompatTests(unittest.TestCase):
    def test_explicit_runtime_invoker_still_works_for_all_cli_ids(self) -> None:
        # 7. dispatch_session with an explicit runtime_invoker continues to
        # work for all cli_ids (codex/gemini/none — back-compat invariant).
        for profile in (claude_default(), _codex_profile(), _gemini_profile()):
            def _inv(*, profile: CLIProfile, intent: SessionIntent) -> dict[str, Any]:
                return {
                    "stdout_tail": "explicit invoker ran",
                    "head_sha": "z" * 40,
                    "session_id": "S",
                    "stderr_tail": "",
                    "timed_out": False,
                }
            # Use a real (non-git) workspace to avoid lie-detector noise.
            # The lie-detector will surface as CRITICAL or unexpected_head
            # — but the point is the dispatcher *ran*, no NotImplementedError.
            res = dispatch_session(
                _intent(workspace="/tmp"),
                profile=profile,
                runtime_invoker=_inv,
            )
            self.assertIsInstance(res, DispatchResult)
            self.assertEqual(res.cli_id, profile.cli_id)


# ---------------------------------------------------------------------------
# claude_code_invoker behavior tests
# ---------------------------------------------------------------------------


class ClaudeCodeInvokerBehaviorTests(unittest.TestCase):
    def test_timeout_kills_session_and_returns_timed_out(self) -> None:
        # 8. claude-code invoker respects intent.timeout_s: a slow
        # session_status (never terminal) drives the loop to timeout.
        # We make clock return values that exceed timeout_s on the
        # second iteration, and status always says "active".
        clock = mock.Mock(side_effect=[0.0, 0.1, 9999.0, 9999.0])
        status = mock.Mock(return_value={"status": "active", "session_state": "in_progress"})
        kill = mock.Mock()
        with _StubHooks(clock=clock, status=status, kill=kill):
            raw = invokers.claude_code_invoker(
                profile=claude_default(), intent=_intent(timeout_s=5.0),
            )
        self.assertTrue(raw["timed_out"])
        self.assertIn("timeout_s", raw["stderr_tail"])
        kill.assert_called_once()
        # head_sha is still resolved on timeout for telemetry.
        self.assertEqual(raw["head_sha"], "a" * 40)

    def test_uses_inject_bmad_auto_env(self) -> None:
        # 9. claude-code invoker uses inject_bmad_auto_env to populate
        # BMAD_AUTO_STORY_KEY etc. on the parent process env across the
        # spawn_session call (so the subprocess inherits them), then
        # restores the parent env in a finally block to avoid contaminating
        # subsequent invocations (bug E2_C9_D-SEC-04). We capture os.environ
        # values from inside the spawn hook to assert "set during spawn",
        # then assert "restored after return".
        keys = (
            "BMAD_AUTO_STORY_KEY",
            "BMAD_AUTO_PHASE",
            "BMAD_AUTO_CLI_ID",
            "BMAD_AUTO_COMMIT_SHA",
            "BMAD_AUTO_TASK_ID",
        )
        saved = {k: os.environ.pop(k, None) for k in keys}
        observed: dict[str, str | None] = {}

        def _spawn_spy(*_args: Any, **_kwargs: Any) -> tuple[str, int]:
            for k in keys:
                observed[k] = os.environ.get(k)
            return ("ok", 0)

        try:
            with _StubHooks(spawn=mock.Mock(side_effect=_spawn_spy)):
                invokers.claude_code_invoker(
                    profile=claude_default(),
                    intent=_intent(),
                )
            # Inside the spawn hook the env is populated (so tmux inherits).
            self.assertEqual(observed["BMAD_AUTO_STORY_KEY"], "STORY-1")
            self.assertEqual(observed["BMAD_AUTO_PHASE"], "dev-running")
            self.assertEqual(observed["BMAD_AUTO_CLI_ID"], "claude-code")
            self.assertEqual(observed["BMAD_AUTO_COMMIT_SHA"], "b" * 40)
            self.assertEqual(observed["BMAD_AUTO_TASK_ID"], "")
            # After the invoker returns the parent env is restored to absent.
            for k in keys:
                self.assertNotIn(k, os.environ)
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_spawn_session_receives_bmad_auto_keys_via_extra_env_kwarg(
        self,
    ) -> None:
        # Regression for the tmux-server-already-running env propagation
        # bug: mutating ``os.environ`` is NOT sufficient because
        # ``tmux new-session`` is a client RPC and the server's pane
        # shells inherit from the server's frozen start-time env plus
        # ``-e`` flags, NOT from the caller's transient env. The
        # invoker MUST forward BMAD_AUTO_* keys to ``spawn_session`` via
        # an ``extra_env`` kwarg so they land as ``tmux new-session -e
        # KEY=VAL`` args. (Pre-fix the kwarg simply did not exist and
        # the keys were silently lost for every invocation after the
        # first one in a tmux-server lifetime.)
        spawn = mock.Mock(return_value=("ok", 0))
        with _StubHooks(spawn=spawn):
            invokers.claude_code_invoker(
                profile=claude_default(),
                intent=_intent(),
            )
        spawn.assert_called_once()
        _args, kwargs = spawn.call_args
        # The kwarg must be present...
        self.assertIn(
            "extra_env",
            kwargs,
            "claude_code_invoker must forward BMAD_AUTO_* to spawn_session "
            "via the extra_env kwarg so they reach the tmux pane shell via "
            "-e flags (mutating os.environ alone is not sufficient when the "
            "tmux server is already running)",
        )
        extra_env = kwargs["extra_env"]
        self.assertIsInstance(extra_env, dict)
        # ...and must carry every BMAD_AUTO_* hook key the contract
        # promises consumers (bmad_auto_hook.py reads these).
        self.assertEqual(extra_env.get("BMAD_AUTO_STORY_KEY"), "STORY-1")
        self.assertEqual(extra_env.get("BMAD_AUTO_PHASE"), "dev-running")
        self.assertEqual(extra_env.get("BMAD_AUTO_CLI_ID"), "claude-code")
        self.assertEqual(extra_env.get("BMAD_AUTO_COMMIT_SHA"), "b" * 40)
        self.assertEqual(extra_env.get("BMAD_AUTO_TASK_ID"), "")
        # And every value must be a string (tmux -e is byte-oriented).
        for k, v in extra_env.items():
            self.assertIsInstance(
                v, str, f"extra_env[{k!r}] must be a string, got {type(v)}"
            )

    def test_head_sha_matches_git_hook_result(self) -> None:
        # 10. head_sha in returned dict matches the git rev-parse HEAD hook
        # output for intent.workspace.
        fake_sha = "deadbeef" * 5  # 40 chars
        git = mock.Mock(return_value=fake_sha)
        with _StubHooks(git=git):
            raw = invokers.claude_code_invoker(
                profile=claude_default(),
                intent=_intent(workspace="/tmp/the-ws"),
            )
        # git hook was called with the workspace path.
        git.assert_any_call("/tmp/the-ws")
        self.assertEqual(raw["head_sha"], fake_sha)

    def test_spawn_failure_returns_stderr_not_timeout(self) -> None:
        # Bonus: a spawn failure surfaces as stderr_tail (not timed_out, not crash).
        spawn = mock.Mock(return_value=("tmux not found\n", 1))
        with _StubHooks(spawn=spawn):
            raw = invokers.claude_code_invoker(
                profile=claude_default(), intent=_intent(),
            )
        self.assertFalse(raw["timed_out"])
        self.assertIn("spawn_session failed", raw["stderr_tail"])
        self.assertEqual(raw["stdout_tail"], "")

    def test_stdout_tail_is_capped(self) -> None:
        # Bonus: a huge output is tail-capped to _STDOUT_TAIL_CAP_CHARS.
        big = "x" * (invokers._STDOUT_TAIL_CAP_CHARS + 5000)
        read = mock.Mock(return_value=big)
        with _StubHooks(read=read):
            raw = invokers.claude_code_invoker(
                profile=claude_default(), intent=_intent(),
            )
        self.assertEqual(len(raw["stdout_tail"]), invokers._STDOUT_TAIL_CAP_CHARS)

    def test_prompt_template_with_extra_placeholder_does_not_crash(self) -> None:
        # Regression: ``CLIProfile``'s loader validates ``prompt_template``
        # is a non-empty string but does NOT parse its format keys. An
        # operator-authored TOML profile carrying ``prompt_template =
        # "{prompt} --ws {workspace}"`` was raising ``KeyError: 'workspace'``
        # from ``str.format`` inside ``claude_code_invoker`` because only
        # ``prompt=`` was supplied as a kwarg. That ``KeyError`` propagated
        # through ``default_invoker`` and ``dispatch_session`` (which only
        # catches ``TimeoutError``), violating its docstring contract that
        # it "Never raises on CLI-side or git-side failure". The fix
        # renders the template with a defaulting mapping so unknown
        # placeholders surface as empty strings rather than crashes.
        from types import MappingProxyType

        for template, expected_in_cmd in (
            ("{prompt} --ws {workspace}", "/skill do-thing --ws"),
            ("{prompt} sha={baseline_sha}", "/skill do-thing sha="),
            ("run {a} {b} {prompt} {c}", "/skill do-thing"),
        ):
            with self.subTest(template=template):
                profile = CLIProfile(
                    cli_id="claude-code",
                    binary="claude",
                    prompt_template=template,
                    bypass_flags=(),
                    hook_dialect="claude",
                    canonical_event_map=MappingProxyType({}),
                    skill_tree_dir=".claude/skills",
                )
                with _StubHooks() as h:
                    raw = invokers.claude_code_invoker(
                        profile=profile, intent=_intent(),
                    )
                # Wire-shape preserved; no KeyError escaped.
                self.assertEqual(
                    set(raw.keys()),
                    {"stdout_tail", "head_sha", "session_id",
                     "stderr_tail", "timed_out"},
                )
                # The rendered command reached spawn_session — the canonical
                # ``{prompt}`` placeholder was substituted, unknown
                # placeholders rendered as empty strings.
                h.spawn.assert_called_once()
                cmd = h.spawn.call_args[0][1]
                self.assertIn(expected_in_cmd, cmd)

    def test_prompt_template_extra_placeholder_classifies_at_dispatch_session(
        self,
    ) -> None:
        # End-to-end regression at the ``dispatch_session`` boundary: a
        # ``prompt_template`` carrying an unknown placeholder must surface
        # as a ``DispatchResult`` (not a bare ``KeyError`` crash through
        # ``_dispatch_via_cli_dispatcher``, which only catches
        # ``DispatcherError``).
        from types import MappingProxyType

        profile = CLIProfile(
            cli_id="claude-code",
            binary="claude",
            prompt_template="{prompt} --ws {workspace}",
            bypass_flags=(),
            hook_dialect="claude",
            canonical_event_map=MappingProxyType({}),
            skill_tree_dir=".claude/skills",
        )
        with _StubHooks():
            res = dispatch_session(
                _intent(workspace="/tmp"),
                profile=profile,
                runtime_invoker=None,
            )
        self.assertIsInstance(res, DispatchResult)
        # Must NOT report a raw KeyError leak.
        self.assertNotIn("KeyError", res.stderr_tail)

    def test_claude_code_invoker_rejects_wrong_cli_id(self) -> None:
        # Defensive: claude_code_invoker called with a non-claude profile
        # raises NotImplementedError. This guards against orchestrator
        # mis-routing past the default_invoker switch.
        with self.assertRaises(NotImplementedError):
            invokers.claude_code_invoker(
                profile=_codex_profile(), intent=_intent(),
            )

    def test_prompt_template_fail_soft_catches_both_value_and_index_error(
        self,
    ) -> None:
        # Regression for the comment-vs-code drift on the fail-soft except
        # clause at ``cli_dispatcher_invokers.py:303``: the inline rationale
        # cited only ``ValueError``-shaped triggers (``{prompt:`` and ``{0}``)
        # but the except tuple is ``(ValueError, IndexError)``. Both arms
        # are reachable in practice — out-of-range subscripts on str values
        # (e.g. ``{prompt[5]}`` when ``prompt`` is shorter than 6 chars)
        # raise ``IndexError``, NOT ``ValueError``. Without ``IndexError``
        # in the tuple the dispatcher would surface a raw ``IndexError``,
        # violating the "Never raises on CLI-side or git-side failure"
        # contract. This test exercises both exception classes and asserts
        # the wire-shape is preserved, so any future maintainer who shrinks
        # the tuple will fail the suite.
        from types import MappingProxyType

        # Verify our examples actually raise the expected exception types
        # at the language level (defensive against Python version drift).
        with self.assertRaises(ValueError):
            "{0}".format_map({"prompt": "x"})
        with self.assertRaises(ValueError):
            "{prompt:".format_map({"prompt": "x"})
        with self.assertRaises(IndexError):
            "{prompt[5]}".format_map({"prompt": "xy"})

        for template in (
            "{0}",          # positional → ValueError
            "{prompt:",     # unclosed → ValueError
            "{prompt[5]}",  # out-of-range subscript → IndexError
        ):
            with self.subTest(template=template):
                profile = CLIProfile(
                    cli_id="claude-code",
                    binary="claude",
                    prompt_template=template,
                    bypass_flags=(),
                    hook_dialect="claude",
                    canonical_event_map=MappingProxyType({}),
                    skill_tree_dir=".claude/skills",
                )
                # Use a short prompt so {prompt[5]} actually triggers
                # IndexError rather than silently succeeding.
                short_intent = SessionIntent(
                    story_key="S1",
                    phase="dev",
                    baseline_sha="b" * 40,
                    prompt="xy",
                    workspace="/tmp/ws",
                )
                with _StubHooks() as h:
                    raw = invokers.claude_code_invoker(
                        profile=profile, intent=short_intent,
                    )
                # Fail-soft path returned wire-shape, did not propagate.
                self.assertEqual(
                    set(raw.keys()),
                    {"stdout_tail", "head_sha", "session_id",
                     "stderr_tail", "timed_out"},
                )
                # The bare prompt reached the spawn command (the
                # ``intent.prompt or ""`` fallback). Confirms the except
                # clause caught the exception and substituted the prompt.
                h.spawn.assert_called_once()
                cmd = h.spawn.call_args[0][1]
                self.assertIn("xy", cmd)

    def test_empty_story_key_and_phase_do_not_crash_invoker(self) -> None:
        # Regression: ``_session_name_for`` defaults empty ``story_key`` to
        # ``"STORY"`` and empty ``phase`` to ``"phase"``, but
        # ``inject_bmad_auto_env`` strictly rejects empty values with
        # ``ValueError``. Pre-fix the invoker called ``inject_bmad_auto_env``
        # unguarded, so ``SessionIntent(story_key="", ...)`` would raise
        # ``ValueError: story_key must be a non-empty string`` before the
        # try/finally env-restore block, propagating uncaught through
        # ``default_invoker``. ``dispatch_session`` would only convert it to
        # an error result via its ``except Exception`` catch; the cleaner
        # fix is to unify the invoker's empty-value contract with
        # ``_session_name_for`` so neither helper crashes on bootstrap inputs.
        for sk, ph in (("", "dev-running"), ("STORY-1", ""), ("   ", "  ")):
            with self.subTest(story_key=repr(sk), phase=repr(ph)):
                bad_intent = SessionIntent(
                    story_key=sk,
                    phase=ph,
                    baseline_sha="b" * 40,
                    prompt="/skill do-thing",
                    workspace="/tmp/ws",
                )
                with _StubHooks():
                    raw = invokers.claude_code_invoker(
                        profile=claude_default(), intent=bad_intent,
                    )
                # Wire-shape preserved; no crash.
                self.assertEqual(
                    set(raw.keys()),
                    {"stdout_tail", "head_sha", "session_id",
                     "stderr_tail", "timed_out"},
                )
                self.assertFalse(raw["timed_out"])

    def test_none_prompt_renders_as_empty_string_not_literal_None(self) -> None:
        # Regression: ``_DefaultEmptyDict(prompt=intent.prompt)`` stored the
        # raw value verbatim. When a caller violated ``SessionIntent.prompt``'s
        # ``str`` type contract by passing ``None`` (frozen dataclass does not
        # enforce types at runtime), ``"{prompt}".format_map(_render_map)``
        # produced the literal 4-char token ``"None"`` rather than ``""``.
        # That ``"None"`` was then embedded directly into the tmux launch
        # command — inconsistent with both the fail-soft fallback in the
        # ``except`` arm (``intent.prompt or ""``) AND the explicit
        # ``str(v)``-with-no-``None`` guard a few lines below for BMAD env
        # keys. ``__missing__`` does not fire because the key IS present with
        # value ``None``, and ``str.format_map`` does not raise either — it
        # silently calls ``format(None, "")`` which returns ``"None"``.
        # The fix normalizes ``intent.prompt or ""`` at the mapping
        # construction site, symmetric with the ``except`` arm.
        bad_intent = SessionIntent(
            story_key="S1",
            phase="dev",
            baseline_sha="b" * 40,
            prompt=None,  # type: ignore[arg-type]
            workspace="/tmp/ws",
        )
        with _StubHooks() as h:
            raw = invokers.claude_code_invoker(
                profile=claude_default(), intent=bad_intent,
            )
        # Wire-shape preserved.
        self.assertEqual(
            set(raw.keys()),
            {"stdout_tail", "head_sha", "session_id",
             "stderr_tail", "timed_out"},
        )
        # Spawn must have been called exactly once.
        h.spawn.assert_called_once()
        cmd = h.spawn.call_args[0][1]
        # The literal 4-char token ``None`` must NOT have leaked into the
        # spawn command. Use a word-boundary-style check to avoid false
        # positives if the binary name itself ever happened to contain
        # ``None`` (it doesn't — ``claude_default().binary == "claude"`` —
        # but defending against future profile renames).
        tokens = cmd.split()
        self.assertNotIn(
            "None", tokens,
            msg=f"literal token 'None' leaked into spawn command: {cmd!r}",
        )

    def test_session_name_satisfies_validated_session_name_for_dirty_phase(
        self,
    ) -> None:
        # Regression: ``_session_name_for``'s docstring says the produced
        # name "must satisfy ``tmux_runtime._validated_session_name``"
        # (regex ``^[A-Za-z0-9._-]{1,160}$``). Pre-fix the implementation
        # only replaced ``_`` and ``/`` in ``intent.phase``, leaving
        # whitespace, colons, and other invalid chars intact — so a phase
        # produced by ``commands.tmux._phase_for_step('my step')`` (which
        # only does ``.strip().lower()`` and yields ``"my step-running"``)
        # would render a name that the validator rejects. Verify the
        # docstring contract holds for a realistic dirty phase that
        # production paths can produce.
        from story_automator.core import (
            cli_dispatcher_invokers as invokers_mod,
            tmux_runtime as tmux_mod,
        )

        # The exact phase that ``commands.tmux._phase_for_step('my step')``
        # produces — a literal space passes through ``.strip().lower()``.
        intent = SessionIntent(
            story_key="S1",
            phase="my step-running",
            baseline_sha="b" * 40,
            prompt="/p",
            workspace="/tmp",
        )
        name = invokers_mod._session_name_for(intent)
        # Must satisfy the validator (no exception).
        tmux_mod._validated_session_name(name)
        # And the invalid char must have been replaced (not just dropped):
        self.assertNotIn(" ", name)
        # Also check colon (another realistic dirty char from operator args).
        intent2 = SessionIntent(
            story_key="S1",
            phase="dev:running",
            baseline_sha="b" * 40,
            prompt="/p",
            workspace="/tmp",
        )
        name2 = invokers_mod._session_name_for(intent2)
        tmux_mod._validated_session_name(name2)
        self.assertNotIn(":", name2)

    def test_polling_loop_hook_failure_does_not_propagate_or_leak_session(
        self,
    ) -> None:
        # Regression: a polling-loop hook (``_session_status_hook`` here,
        # but the same pattern guards ``_clock_hook`` / ``_sleep_hook`` /
        # the timeout-branch ``_git_head_hook``) raising a realistic tmux
        # probe error must NOT propagate past ``claude_code_invoker`` —
        # the dispatcher's docstring promises "Never raises on CLI-side
        # or git-side failure". Pre-fix the entire loop unwound on
        # ``subprocess.TimeoutExpired`` (the actual exception type a
        # hung tmux probe raises — NOT a subclass of ``TimeoutError``),
        # leaking an orphan tmux session (the timeout-branch kill was
        # never reached) and bubbling out of ``dispatch_session`` past
        # its ``except TimeoutError`` handler.
        #
        # The contract this regression pins:
        #   1. Invoker returns a runner-contract dict, never raises.
        #   2. ``stderr_tail`` carries enough context for operators to
        #      diagnose ("polling failed", exception class+message).
        #   3. ``timed_out=False`` (the bug is "polling hook failed",
        #      not "session ran past timeout_s") so the dispatcher
        #      classifies it via the lie-detector / error path, not the
        #      timeout path.
        #   4. The tmux session is best-effort killed so we don't leak
        #      an orphan into the operator's tmux server.
        import subprocess as _subprocess

        for exc in (
            RuntimeError("tmux command-bus error"),
            _subprocess.TimeoutExpired("tmux", 15),
            OSError("tmux server gone"),
        ):
            with self.subTest(exception=type(exc).__name__):
                status = mock.Mock(side_effect=exc)
                kill = mock.Mock()
                with _StubHooks(status=status, kill=kill):
                    raw = invokers.claude_code_invoker(
                        profile=claude_default(), intent=_intent(timeout_s=5.0),
                    )
                # 1. Returned a dict, did not raise.
                self.assertEqual(
                    set(raw.keys()),
                    {"stdout_tail", "head_sha", "session_id",
                     "stderr_tail", "timed_out"},
                )
                # 2. Diagnostic context surfaced.
                self.assertIn("polling failed", raw["stderr_tail"])
                self.assertIn(type(exc).__name__, raw["stderr_tail"])
                # 3. NOT classified as a timeout.
                self.assertFalse(raw["timed_out"])
                # 4. Session was best-effort killed to avoid orphan leak.
                kill.assert_called_once()

    def test_polling_loop_base_exception_drains_session_before_propagating(
        self,
    ) -> None:
        # Regression: ``BaseException`` subclasses (``KeyboardInterrupt``,
        # ``SystemExit``) BYPASS the ``except Exception`` polling-loop
        # guard by Python semantics. Pre-fix, an operator Ctrl-C arriving
        # during the polling loop propagated out of ``claude_code_invoker``
        # without ever invoking ``_kill_session_hook``, leaking the spawned
        # tmux session as an orphan. ``BaseException`` propagation itself
        # is by design (the dispatcher's contract at
        # ``cli_dispatcher.py`` documents that Ctrl-C aborts the run);
        # what this test pins is that the orphan cleanup runs BEFORE the
        # interrupt propagates.
        #
        # Two contracts pinned:
        #   1. ``_kill_session_hook(session, workspace)`` is invoked
        #      exactly once with the spawned session id, even though the
        #      polling-loop guard is ``except Exception:``.
        #   2. The original ``BaseException`` still propagates (we do NOT
        #      swallow Ctrl-C — that would defeat the operator's intent).
        for exc_cls, exc_arg in (
            (KeyboardInterrupt, "operator interrupt"),
            (SystemExit, 1),
        ):
            with self.subTest(exception=exc_cls.__name__):
                status = mock.Mock(side_effect=exc_cls(exc_arg))
                kill = mock.Mock()
                with _StubHooks(status=status, kill=kill):
                    with self.assertRaises(exc_cls):
                        invokers.claude_code_invoker(
                            profile=claude_default(),
                            intent=_intent(timeout_s=5.0),
                        )
                # Session was drained before the interrupt propagated —
                # no orphan leaked into the operator's tmux server.
                kill.assert_called_once()
                # And we drained the EXACT session we spawned, not some
                # other identifier (smoke-test that the cleanup binds the
                # right name).
                killed_session = kill.call_args.args[0]
                self.assertTrue(killed_session.startswith("sa-disp-"))

    def test_polling_loop_hook_failure_classifies_at_dispatch_session(
        self,
    ) -> None:
        # End-to-end regression at the ``dispatch_session`` boundary: a
        # polling-loop hook raising ``subprocess.TimeoutExpired`` (NOT a
        # subclass of ``TimeoutError``, which the dispatcher catches
        # explicitly) must surface as a ``DispatchResult`` with
        # ``stop_reason="error"`` — not bubble out of the production
        # ``_dispatch_via_cli_dispatcher`` wrapper, which only catches
        # ``DispatcherError``.
        import subprocess as _subprocess

        status = mock.Mock(
            side_effect=_subprocess.TimeoutExpired("tmux", 15)
        )
        with _StubHooks(status=status):
            res = dispatch_session(
                _intent(workspace="/tmp", timeout_s=5.0),
                profile=claude_default(),
                runtime_invoker=None,
            )
        self.assertIsInstance(res, DispatchResult)
        # Polling failure surfaces a descriptive diagnostic, not a raw
        # crash report.
        self.assertIn("polling failed", res.stderr_tail)

    def test_empty_story_key_dispatches_to_error_or_classifies(self) -> None:
        # End-to-end regression at the dispatch_session boundary: an empty
        # story_key flowing into the invoker must not raise out of
        # ``dispatch_session`` as a bare ``ValueError``. Per the
        # ``dispatch_session`` docstring contract ("Never raises on CLI-side
        # or git-side failure"), the result must be a ``DispatchResult``.
        with _StubHooks():
            res = dispatch_session(
                SessionIntent(
                    story_key="",
                    phase="dev-running",
                    baseline_sha="b" * 40,
                    prompt="/skill do-thing",
                    workspace="/tmp",
                ),
                profile=claude_default(),
                runtime_invoker=None,
            )
        self.assertIsInstance(res, DispatchResult)
        # Must NOT classify as an unhandled invoker_error from a
        # ValueError — that would mean the invoker still crashed and the
        # dispatcher only caught it via the generic Exception fallback.
        self.assertNotIn("ValueError", res.stderr_tail)


# ---------------------------------------------------------------------------
# Integration: dispatch_session w/ no runtime_invoker hits default_invoker
# ---------------------------------------------------------------------------


class DispatchSessionDefaultInvokerIntegrationTests(unittest.TestCase):
    def test_no_invoker_routes_through_default_invoker_for_codex(self) -> None:
        # dispatch_session with no runtime_invoker on a codex profile must
        # surface NotImplementedError from the switch.
        # The dispatcher does NOT catch NotImplementedError (it's a
        # programmer error, not a CLI runtime error) — it propagates.
        with self.assertRaises(NotImplementedError) as cm:
            dispatch_session(
                _intent(workspace="/tmp"),
                profile=_codex_profile(),
                runtime_invoker=None,
            )
        self.assertIn("codex", str(cm.exception).lower())

    def test_no_invoker_routes_through_default_invoker_for_claude_code(self) -> None:
        # claude-code with no runtime_invoker should reach the shim. We
        # patch the invoker module's hooks so no real tmux runs.
        with _StubHooks():
            res = dispatch_session(
                _intent(workspace="/tmp"),
                profile=claude_default(),
                runtime_invoker=None,
            )
        # We don't assert on res.ok (depends on lie-detector + workspace);
        # only that we reached a DispatchResult, not an exception.
        self.assertIsInstance(res, DispatchResult)
        self.assertEqual(res.cli_id, "claude-code")


if __name__ == "__main__":
    unittest.main()
