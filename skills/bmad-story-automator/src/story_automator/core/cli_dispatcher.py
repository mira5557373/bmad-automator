"""cli_dispatcher — multi-CLI session dispatcher with stop-hook + lie-detector fallback.

This module is the N6.5 keystone of the engine-adoption Path B decision
(see ``docs/spec/2026-06-22-engine-adoption-decision.md``). It owns the
*single decision* of "did the session actually finish, and did it commit
its work?" without committing to a particular tmux runtime, terminal
emulator, or subprocess layout.

Architecture
------------

The dispatcher consumes:

  * a :class:`SessionIntent` — story key, lifecycle phase, baseline SHA,
    rendered prompt, workspace path, timeout.
  * a :class:`CLIProfile` — describes the target CLI (claude-code / codex
    / gemini-cli / a "none"-hook profile for CLIs without a stop-hook
    dialect at all). The profile's ``hook_dialect`` field picks the
    marker from :data:`STOP_HOOK_DIALECTS`.

It returns a :class:`DispatchResult` describing whether the session
succeeded (``ok``), the final HEAD of the workspace, which classification
path stopped it (``stop_reason``), and a wire-form
:class:`VerifyOutcome` for embedding in the gate-file payload.

Completion classification (in priority order):

  1. **stop-hook** — the dialect marker for ``profile.hook_dialect``
     appears (case-insensitively) in the stdout tail returned by the
     runner. The CLI told us it's done.
  2. **lie-detector** — fallback when no marker fired. Calls
     :func:`detect_baseline_drift` to verify HEAD moved beyond
     ``baseline_sha``. Pass → ``ok=True``; baseline drift → ``ok=False``
     (the session claimed work but didn't commit); unexpected HEAD →
     ``ok=False`` (third commit, not auto-retryable).
  3. **timeout** — runner raised :class:`TimeoutError`. ``ok=False``,
     ``stop_reason="timeout"``.
  4. **error** — git-layer failure escalated by the lie-detector as
     CRITICAL. ``ok=False``, ``stop_reason="error"``.

Dependency injection
--------------------

Production callers will not pass ``runtime_invoker`` and will get the
bundled :func:`_default_invoker`, which delegates to
:mod:`story_automator.core.cli_dispatcher_invokers` — a thin shim over
the existing :mod:`story_automator.core.tmux_runtime` public surface
for ``cli_id="claude-code"``. ``codex``, ``gemini-cli``, ``none``, and
unknown ids currently raise :class:`NotImplementedError` so the
orchestrator can route the failure cleanly while their built-in
runners are still being designed.

Tests pass their own ``runtime_invoker`` — a callable returning a dict
with the keys ``stdout_tail``, ``head_sha``, ``session_id``,
``stderr_tail``, and ``timed_out`` (or raising :class:`TimeoutError`).
This keeps the dispatcher fully unit-testable without spinning up tmux.

Plugin interop
--------------

The dispatcher is intentionally a thin classifier; lifecycle events for
:class:`HookBusShim` plugins (pre_dev_phase, post_dev_phase, pre_review,
post_review, pre_gate, post_gate, pre_commit) are fired by the
orchestrator on either side of the dispatcher, not from inside it. The
dispatcher *exports* the cli_id and head_sha so a plugin can correlate
its veto with the right session.

Hard guardrails honored
-----------------------

* stdlib-only.
* No timestamps, PIDs, or run-IDs leak into :class:`DispatchResult` —
  safe to embed in gate-file payloads (per the frozen-gate-surface
  guardrail).
* No touch to ``tmux_runtime.py`` public surface; the default invoker
  consumes the existing ``spawn_session`` / ``session_status`` /
  ``verify_or_create_output`` / ``inject_bmad_auto_env`` entry points
  via :mod:`cli_dispatcher_invokers`.
* No touch to ``cli_profile.CLIProfile`` (consumed only).
* No touch to ``lie_detector.detect_baseline_drift`` (consumed only).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .cli_profile import CLIProfile
from .git_utils import same_commit
from .lie_detector import detect_baseline_drift
from .verify_outcome import VerifyOutcome

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

#: Map from ``CLIProfile.hook_dialect`` value to the *stop-hook marker* the
#: CLI emits to stdout when its session ends. The dispatcher searches
#: ``stdout_tail`` for this marker (case-insensitively); the marker is the
#: ground truth that the CLI told us it's done.
#:
#: ``"none"`` maps to ``""`` so :func:`detect_stop` always returns False
#: for that dialect — the dispatcher falls straight through to the
#: lie-detector. Use ``"none"`` for CLIs whose hook config we can't
#: control.
STOP_HOOK_DIALECTS: dict[str, str] = {
    "claude": "[stop-hook] story-automator session-end claude",
    "codex": "[stop-hook] story-automator session-end codex",
    "gemini": "[stop-hook] story-automator session-end gemini",
    "none": "",
}

#: Closed set of dispatch stages that the policy file may override.
KNOWN_STAGES: frozenset[str] = frozenset({"dev", "review", "triage"})


class DispatcherError(RuntimeError):
    """Raised on invalid dispatcher configuration (e.g. unknown stage).

    Distinct type so callers can distinguish dispatcher misconfiguration
    from CLI-side runtime errors (which surface as
    ``stop_reason="error"`` in a :class:`DispatchResult`).
    """


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionIntent:
    """Inputs the dispatcher needs to launch and verify a single session.

    Attributes:
        story_key: stable story identifier (e.g. ``"STORY-1.2"``).
        phase: lifecycle phase from bauto's Phase vocabulary
            (``"dev-running"``, ``"review-running"``, ``"triage-running"``).
            The dispatcher does not introspect this value; it's passed
            through so plugins can correlate hook events.
        baseline_sha: commit the session must build atop. Used by the
            lie-detector to flag "no work committed" cases.
        prompt: rendered agent prompt (Claude/Codex/Gemini-shaped, per
            profile.prompt_template).
        workspace: absolute path to the worktree/checkout where the CLI
            should run.
        timeout_s: soft timeout in seconds. The runner is expected to
            enforce this and raise :class:`TimeoutError` on expiry.
    """

    story_key: str
    phase: str
    baseline_sha: str
    prompt: str
    workspace: str
    timeout_s: float = 1800.0


@dataclass(frozen=True)
class DispatchResult:
    """Wire-stable result of a single session dispatch.

    Determinism contract: no timestamps, no PIDs, no run-IDs — only
    classification data. Safe to embed in gate-file payloads (per
    docs/spec/frozen-gate-surface.md guardrail #6).

    Attributes:
        ok: True iff the session finished cleanly *and* committed work.
        cli_id: which CLI ran (mirrors ``profile.cli_id``).
        head_sha: final HEAD of the workspace as reported by the runner.
        stop_reason: one of ``"stop-hook"``, ``"lie-detector"``,
            ``"timeout"``, ``"error"``.
        verify_outcome: :meth:`VerifyOutcome.to_dict` wire form. For
            stop-hook paths this is ``passed()``; for lie-detector paths
            it carries the drift verdict; for timeout/error paths it
            describes the failure.
        session_id: opaque token from the runner (e.g. tmux pane id).
            Empty when the runner didn't supply one.
        stderr_tail: short tail of the runner's stderr (capped by the
            runner, not the dispatcher). Empty when the runner didn't
            supply one.
    """

    ok: bool
    cli_id: str
    head_sha: str
    stop_reason: str
    verify_outcome: dict[str, Any] = field(default_factory=dict)
    session_id: str = ""
    stderr_tail: str = ""


# ---------------------------------------------------------------------------
# detect_stop
# ---------------------------------------------------------------------------


def detect_stop(stdout_tail: str, dialect: str) -> bool:
    """True iff the dialect-specific stop-hook marker appears in ``stdout_tail``.

    The marker lookup is case-insensitive and tolerates trailing
    whitespace. Markers for unknown dialects, and the empty ``"none"``
    marker, always return False — the dispatcher will then fall through
    to the lie-detector.

    Args:
        stdout_tail: recent stdout from the runner. The dispatcher does
            not bound the tail itself — the runner caps it.
        dialect: ``profile.hook_dialect`` value (one of
            :data:`KNOWN_HOOK_DIALECTS` upstream in cli_profile).

    Returns:
        bool: True only when the dialect-specific marker is present.
    """
    marker = STOP_HOOK_DIALECTS.get(dialect, "")
    if not marker:
        return False
    if not stdout_tail:
        return False
    return marker.lower() in stdout_tail.lower()


# ---------------------------------------------------------------------------
# adapter_for_stage
# ---------------------------------------------------------------------------


def adapter_for_stage(policy: dict[str, Any], stage: str) -> str:
    """Resolve which CLI id should drive a particular pipeline stage.

    Reads ``policy["adapter"][stage]["name"]`` and defaults to
    ``"claude-code"`` for any missing key in the chain.

    Args:
        policy: free-form policy dict (typically loaded from
            ``runtime_policy.json``). The relevant slice is
            ``adapter.<stage>.name``.
        stage: one of :data:`KNOWN_STAGES`. Anything else raises
            :class:`DispatcherError` — the stage set is closed by design
            so a typo can't silently route to the default.

    Returns:
        str: a CLI id (typically one of
        :data:`story_automator.core.cli_profile.KNOWN_CLI_IDS`).

    Raises:
        DispatcherError: when ``stage`` is not in :data:`KNOWN_STAGES`.
    """
    if stage not in KNOWN_STAGES:
        raise DispatcherError(
            f"unknown stage {stage!r}; expected one of {sorted(KNOWN_STAGES)}"
        )
    adapter = policy.get("adapter") if isinstance(policy, dict) else None
    if not isinstance(adapter, dict):
        return "claude-code"
    stage_cfg = adapter.get(stage)
    if not isinstance(stage_cfg, dict):
        return "claude-code"
    name = stage_cfg.get("name")
    if not isinstance(name, str) or not name:
        return "claude-code"
    return name


# ---------------------------------------------------------------------------
# Default invoker (placeholder)
# ---------------------------------------------------------------------------


def _default_invoker(*, profile: CLIProfile, intent: SessionIntent) -> dict[str, Any]:
    """Real default invoker — switches on ``profile.cli_id``.

    Delegates to :mod:`story_automator.core.cli_dispatcher_invokers`
    which holds the concrete tmux shim for ``claude-code``. For
    ``codex``, ``gemini-cli``, ``none``, and unknown ids this raises
    :class:`NotImplementedError` with a message naming the cli_id so
    operators can route the failure.

    Tests that want to exercise the dispatcher classifier in isolation
    should always pass their own ``runtime_invoker``; this default
    invoker reaches real tmux for the claude-code path.
    """
    # Late import avoids the import cycle (cli_dispatcher_invokers
    # imports cli_dispatcher.SessionIntent via TYPE_CHECKING only) and
    # keeps tmux_runtime out of cli_dispatcher's import graph when the
    # default invoker is never called.
    from .cli_dispatcher_invokers import default_invoker as _impl

    return _impl(profile=profile, intent=intent)


# ---------------------------------------------------------------------------
# dispatch_session
# ---------------------------------------------------------------------------


def _coerce_str_field(value: Any) -> str:
    """Coerce a runner-supplied raw-dict value to ``str`` defensively.

    The invoker contract (see :func:`dispatch_session`) requires str-typed
    ``stdout_tail`` / ``head_sha`` / ``session_id`` / ``stderr_tail``
    fields, but a misbehaving runner may yield ``None`` (or any non-str).
    The naive ``str(value)`` path silently mints the literal token
    ``"None"`` (or ``"False"``, ``"0"``, etc.), which then propagates
    into :class:`DispatchResult.head_sha` — a wire-stable field embeddable
    in gate-file payloads per the frozen-gate-surface contract. We
    instead coerce non-str inputs (including ``None``) to ``""`` so a
    contract-violating runner produces an empty field rather than a
    deceptive token. The empty-string head_sha flows through the
    lie-detector to a SAFE retryable verdict (``baseline_drift``), not a
    false PASS.
    """
    if isinstance(value, str):
        return value
    return ""


def _build_timeout_result(
    *,
    profile: CLIProfile,
    intent: SessionIntent,
    stderr_tail: str,
) -> DispatchResult:
    """Construct a uniformly-shaped timeout :class:`DispatchResult`."""
    outcome = VerifyOutcome.retry("timeout", fixable=False)
    return DispatchResult(
        ok=False,
        cli_id=profile.cli_id,
        head_sha="",
        stop_reason="timeout",
        verify_outcome=outcome.to_dict(),
        session_id="",
        stderr_tail=stderr_tail,
    )


def _build_invoker_error_result(
    *,
    profile: CLIProfile,
    intent: SessionIntent,
    exc: Exception,
) -> DispatchResult:
    """Construct a uniformly-shaped ``stop_reason="error"`` :class:`DispatchResult`
    for a runtime-invoker exception.

    Per the docstring contract on :func:`dispatch_session` ("Never raises
    on CLI-side or git-side failure"), CLI runtime failures from the
    invoker (e.g. ``OSError`` from env access, ``subprocess.CalledProcessError``
    from a tmux server-down condition, ``RuntimeError`` from a misbehaving
    runner) are surfaced as ``DispatchResult`` values, not propagated.
    The escalating severity is ``CRITICAL`` so the orchestrator routes to
    operator-visible error handling, matching the git-layer CRITICAL
    branch in :func:`_classify_from_lie_detector`.
    """
    outcome = VerifyOutcome.escalate("invoker_error", severity="CRITICAL")
    return DispatchResult(
        ok=False,
        cli_id=profile.cli_id,
        head_sha="",
        stop_reason="error",
        verify_outcome=outcome.to_dict(),
        session_id="",
        stderr_tail=f"{type(exc).__name__}: {exc}",
    )


def _classify_from_lie_detector(
    *,
    profile: CLIProfile,
    intent: SessionIntent,
    head_sha: str,
    session_id: str,
    stderr_tail: str,
) -> DispatchResult:
    """Run the lie-detector and map its verdict to a :class:`DispatchResult`.

    Three terminal classifications:

    * ``outcome.ok`` → ``stop_reason="lie-detector"``, ``ok=True``.
    * ``outcome.severity == "CRITICAL"`` → git-layer failure, surfaces as
      ``stop_reason="error"`` (the lie-detector signaled the worktree is
      itself broken — not a session-retry condition).
    * Any retryable failure (baseline_drift / unexpected_head) →
      ``stop_reason="lie-detector"``, ``ok=False``. The orchestrator
      decides whether to retry based on ``outcome.fixable``.

    Pre-check: if the runner-reported ``head_sha`` equals
    ``intent.baseline_sha``, the agent itself signaled "no commit
    happened". We surface that as ``baseline_drift`` immediately rather
    than letting :func:`detect_baseline_drift` map it to ``passed()``
    (which only happens because actual-HEAD also equals baseline in that
    degenerate case).
    """
    if head_sha and same_commit(head_sha, intent.baseline_sha):
        outcome = VerifyOutcome.retry("baseline_drift", fixable=True)
        return DispatchResult(
            ok=False,
            cli_id=profile.cli_id,
            head_sha=head_sha,
            stop_reason="lie-detector",
            verify_outcome=outcome.to_dict(),
            session_id=session_id,
            stderr_tail=stderr_tail,
        )
    outcome = detect_baseline_drift(
        intent.workspace,
        expected_sha=head_sha,
        baseline_sha=intent.baseline_sha,
    )
    if outcome.severity == "CRITICAL":
        return DispatchResult(
            ok=False,
            cli_id=profile.cli_id,
            head_sha=head_sha,
            stop_reason="error",
            verify_outcome=outcome.to_dict(),
            session_id=session_id,
            stderr_tail=stderr_tail,
        )
    return DispatchResult(
        ok=outcome.ok,
        cli_id=profile.cli_id,
        head_sha=head_sha,
        stop_reason="lie-detector",
        verify_outcome=outcome.to_dict(),
        session_id=session_id,
        stderr_tail=stderr_tail,
    )


def dispatch_session(
    intent: SessionIntent,
    *,
    profile: CLIProfile,
    runtime_invoker: Callable[..., dict[str, Any]] | None = None,
) -> DispatchResult:
    """Launch one CLI session and classify its terminal state.

    Args:
        intent: :class:`SessionIntent` describing what to run.
        profile: :class:`CLIProfile` for the target CLI. ``hook_dialect``
            picks the stop-hook marker; ``cli_id`` propagates into the
            result so plugins can route on it.
        runtime_invoker: dependency-injectable runner. Callers pass a
            mock in tests; production code leaves this ``None`` to get
            :func:`_default_invoker`.

            The invoker contract is::

                invoker(*, profile, intent) -> dict[str, Any]

            with required keys ``stdout_tail`` (str) and ``head_sha``
            (str) and optional keys ``session_id`` (str), ``stderr_tail``
            (str), ``timed_out`` (bool). It may also raise
            :class:`TimeoutError`, which the dispatcher classifies as a
            timeout stop-reason.

    Returns:
        DispatchResult: classification of the session's terminal state.
        Never raises on CLI-side or git-side failure — those become
        ``stop_reason="error"`` or ``"timeout"`` with ``ok=False``.

    Raises:
        DispatcherError: only for *configuration* errors (e.g. the
            invoker returned a malformed dict). CLI runtime errors are
            surfaced as ``DispatchResult`` values, not exceptions.
    """
    invoker = runtime_invoker if runtime_invoker is not None else _default_invoker
    try:
        raw = invoker(profile=profile, intent=intent)
    except TimeoutError as exc:
        return _build_timeout_result(
            profile=profile,
            intent=intent,
            stderr_tail=str(exc),
        )
    except NotImplementedError:
        # Programmer/configuration error from the default-invoker switch
        # (codex / gemini-cli / none / unknown cli_id paths). Propagate so
        # the orchestrator can route the failure cleanly — pinned by
        # test_no_invoker_routes_through_default_invoker_for_codex.
        raise
    except Exception as exc:
        # Any other CLI/runtime exception from the invoker is surfaced as
        # a DispatchResult, not propagated. Honors the docstring contract:
        # "Never raises on CLI-side or git-side failure — those become
        # stop_reason='error' or 'timeout' with ok=False". BaseException
        # (KeyboardInterrupt, SystemExit) still propagates by design.
        return _build_invoker_error_result(
            profile=profile,
            intent=intent,
            exc=exc,
        )

    if not isinstance(raw, dict):
        raise DispatcherError(
            f"runtime_invoker must return a dict, got {type(raw).__name__}"
        )

    # The invoker may also signal a timeout via the ``timed_out`` flag
    # (alternative to raising). Treat it identically. Strict ``is True``
    # check (symmetric with :func:`_coerce_str_field`) so a contract-
    # violating runner returning ``"False"`` (str, semantically the
    # opposite), ``1``, ``["x"]``, or any other truthy non-bool does NOT
    # falsely classify a successful stop-hook session as a timeout. The
    # mis-classification would propagate ``stop_reason="timeout"`` +
    # ``ok=False`` into the wire-stable :class:`DispatchResult` consumed
    # by the orchestrator and gate-file payloads.
    if raw.get("timed_out") is True:
        return _build_timeout_result(
            profile=profile,
            intent=intent,
            stderr_tail=_coerce_str_field(raw.get("stderr_tail")),
        )

    stdout_tail = _coerce_str_field(raw.get("stdout_tail"))
    head_sha = _coerce_str_field(raw.get("head_sha"))
    session_id = _coerce_str_field(raw.get("session_id"))
    stderr_tail = _coerce_str_field(raw.get("stderr_tail"))

    # 1. Stop-hook detection wins when the CLI told us it's done.
    if detect_stop(stdout_tail, profile.hook_dialect):
        return DispatchResult(
            ok=True,
            cli_id=profile.cli_id,
            head_sha=head_sha,
            stop_reason="stop-hook",
            verify_outcome=VerifyOutcome.passed().to_dict(),
            session_id=session_id,
            stderr_tail=stderr_tail,
        )

    # 2. Fall back to lie-detector (HEAD vs. baseline).
    return _classify_from_lie_detector(
        profile=profile,
        intent=intent,
        head_sha=head_sha,
        session_id=session_id,
        stderr_tail=stderr_tail,
    )


__all__ = [
    "KNOWN_STAGES",
    "STOP_HOOK_DIALECTS",
    "DispatcherError",
    "DispatchResult",
    "SessionIntent",
    "adapter_for_stage",
    "detect_stop",
    "dispatch_session",
]
