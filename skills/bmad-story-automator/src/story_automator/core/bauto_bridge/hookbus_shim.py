"""HookBusShim — Path B (compat-shim) foundation for plugin-veto interop.

This module is the first concrete step of the engine-adoption Path B
decision (see ``docs/spec/2026-06-22-engine-adoption-decision.md``).
Rather than rewrite our ``success_verifiers`` + ``gate_orchestrator``
machinery on top of bmad-auto's plugin engine, we expose a small
HookBus-shaped surface that *wraps* the existing verifiers.

A plugin authored against bmad-auto's ``HookBus`` contract (lifecycle
events, blocking veto semantics, fail-closed-on-error) can register
callbacks here and receive ``VerifyOutcome`` results from our verifier
chain — no rewrite of either side required.

Mirrored API surface (kept intentionally minimal):

* ``KNOWN_EVENTS`` — the closed set of lifecycle stages we dispatch on.
* ``HookSpec`` — frozen dataclass describing one registration.
* ``HookBusShim`` — the registry + dispatcher.
* ``HookbusShimError`` — raised on unknown event names or invalid
  callables.

Design constraints (per project hard-guardrails):

* stdlib-only — no new deps.
* No timestamps, PIDs, or run-IDs leak into ``VerifyOutcome`` so emit()
  results stay safe to embed in gate-file payloads.
* Callback exceptions never propagate by default ("fail-open"); set
  ``fail_closed=True`` to convert an exception into a FAIL outcome.
  ``BaseException`` (KeyboardInterrupt, SystemExit) always propagates.

Semantics that mirror bmad-auto's bus deliberately:

* Registration order = dispatch order.
* ``blocking=True`` + a failing outcome short-circuits the chain.
* ``severity`` on registration is the *default* severity attached to
  failures the callback returned without one of its own. If the callback
  set a severity explicitly, that value wins.

Out of scope here (deferred to a later Path B milestone):

* declarative (subprocess) hooks — only in-process Python callables.
* mutation-pipeline context — emit() takes/returns a flat ``dict`` and
  is not yet plumbed into the orchestrator.
* manifest loading — registrations happen programmatically.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..verify_outcome import VerifyOutcome

# The closed set of lifecycle stages the shim accepts. Names mirror the
# milestones the gate-orchestrator already exposes so a plugin author can
# pick the right point without learning our internal phase model.
KNOWN_EVENTS: frozenset[str] = frozenset(
    {
        "post_dev_phase",
        "pre_review",
        "post_review",
        "pre_gate",
        "post_gate",
        "pre_commit",
    }
)


class HookbusShimError(ValueError):
    """Raised when a registration or emit references an unknown event name,
    or when a non-callable is offered as a hook callback."""


# A hook callback receives the context dict (whatever the caller chose to
# emit) and returns either a ``VerifyOutcome`` or anything else — non-
# outcome return values are wrapped as ``VerifyOutcome.passed()`` so a
# plugin written for the bus-style API that returns ``None`` for success
# stays compatible.
HookCallback = Callable[[dict[str, Any]], Any]


@dataclass(frozen=True)
class HookSpec:
    """One hook registration: the event it listens to, the callback to
    invoke, and the policy flags that govern its behavior."""

    event_name: str
    callback: HookCallback
    severity: str
    blocking: bool
    fail_closed: bool


def _coerce_to_outcome(value: Any) -> VerifyOutcome:
    """Wrap whatever a callback returned into a ``VerifyOutcome``.

    Already-an-outcome values pass through untouched; anything else is
    treated as a passed verdict (mirrors bmad-auto's ``on_<stage>``
    convention of "return nothing == ok").
    """
    if isinstance(value, VerifyOutcome):
        return value
    return VerifyOutcome.passed()


def _apply_default_severity(outcome: VerifyOutcome, default: str) -> VerifyOutcome:
    """If the callback returned a *failed* outcome with no severity, stamp
    the registration's default severity onto it. Successful outcomes and
    failures the callback already labeled are returned unchanged."""
    if outcome.ok:
        return outcome
    if outcome.severity:
        return outcome
    if not default:
        return outcome
    return VerifyOutcome(
        ok=outcome.ok,
        reason=outcome.reason,
        severity=default,
        fixable=outcome.fixable,
    )


class HookBusShim:
    """A HookBus-compatible registry + dispatcher.

    Wraps in-process Python callbacks so plugin code written against
    bmad-auto's ``HookBus`` contract can run against our existing
    verifier + orchestrator chain unmodified.

    The shim itself holds no global state — callers instantiate one per
    orchestration session. Callbacks are fired in registration order;
    ``emit()`` returns the list of ``VerifyOutcome`` produced. ``blocking``
    hooks that fail short-circuit the chain.
    """

    def __init__(self) -> None:
        # Per-event ordered list of registrations. dict preserves insertion
        # order on Python 3.7+ so we can keep an event in registration order
        # without a separate counter.
        self._hooks: dict[str, list[HookSpec]] = {}

    # ----- registration --------------------------------------------------

    def register(
        self,
        event_name: str,
        callback: HookCallback,
        *,
        severity: str = "PREFERENCE",
        blocking: bool = False,
        fail_closed: bool = False,
    ) -> HookSpec:
        """Register a callback to fire on ``event_name``.

        Args:
            event_name: One of ``KNOWN_EVENTS``. Anything else raises
                ``HookbusShimError`` — the event set is closed by design.
            callback: An in-process Python callable taking a ``dict``
                context and returning ``VerifyOutcome`` (preferred) or
                anything else (treated as success).
            severity: Default severity stamped onto a failed outcome the
                callback returned without one. Mirrors bmad-auto's
                manifest ``severity`` field; ``"PREFERENCE"`` matches the
                non-critical default.
            blocking: When ``True``, a failed outcome from this callback
                short-circuits the dispatch chain — no subsequent hook
                on the same event runs. Vetoes are *not* the same as
                ordinary failures, so the orchestrator can tell them
                apart via ``has_blocking_veto``.
            fail_closed: When ``True``, a callback exception is caught and
                converted into a FAIL ``VerifyOutcome`` rather than being
                swallowed. ``BaseException`` (KeyboardInterrupt /
                SystemExit) always propagates.

        Returns:
            The ``HookSpec`` recorded — useful for tests and for
            introspection via ``list_hooks``.
        """
        if event_name not in KNOWN_EVENTS:
            raise HookbusShimError(
                f"unknown event {event_name!r}; expected one of "
                f"{sorted(KNOWN_EVENTS)}"
            )
        if not callable(callback):
            raise HookbusShimError(
                f"callback for {event_name!r} must be callable, "
                f"got {type(callback).__name__}"
            )
        spec = HookSpec(
            event_name=event_name,
            callback=callback,
            severity=severity,
            blocking=blocking,
            fail_closed=fail_closed,
        )
        self._hooks.setdefault(event_name, []).append(spec)
        return spec

    # ----- introspection -------------------------------------------------

    def list_hooks(self, event_name: str | None = None) -> list[HookSpec]:
        """Return registered hooks, optionally filtered to one event.

        Returns a new list each call so callers can mutate the result
        without disturbing the registry.
        """
        if event_name is None:
            out: list[HookSpec] = []
            for bucket in self._hooks.values():
                out.extend(bucket)
            return out
        if event_name not in KNOWN_EVENTS:
            raise HookbusShimError(
                f"unknown event {event_name!r}; expected one of "
                f"{sorted(KNOWN_EVENTS)}"
            )
        return list(self._hooks.get(event_name, ()))

    # ----- dispatch ------------------------------------------------------

    def emit(self, event_name: str, context: dict[str, Any]) -> list[VerifyOutcome]:
        """Fire every hook registered for ``event_name`` in registration order.

        Each callback is invoked with ``context`` and its return value is
        coerced into a ``VerifyOutcome`` (see ``_coerce_to_outcome``).

        Exception handling per spec:

        * default (``fail_closed=False``): the exception is swallowed and
          the chain continues; the failing hook contributes *no* outcome
          to the returned list. This matches bmad-auto's "fail-open"
          default for declarative hooks.
        * ``fail_closed=True``: the exception is caught and turned into a
          ``VerifyOutcome.escalate`` carrying the exception text as the
          reason and the registration's ``severity`` (or ``"CRITICAL"``
          when none was set).
        * ``BaseException`` (KeyboardInterrupt, SystemExit) always
          propagates so the orchestrator can shut down cleanly.

        A failing outcome from a ``blocking=True`` hook short-circuits
        the chain — subsequent hooks on the same event do not run.

        Args:
            event_name: Must be in ``KNOWN_EVENTS``.
            context: Free-form dict passed through to every callback.

        Returns:
            Outcomes in dispatch order. May be shorter than the number of
            registered hooks if a blocking veto fired or if a fail-open
            hook raised.
        """
        if event_name not in KNOWN_EVENTS:
            raise HookbusShimError(
                f"unknown event {event_name!r}; expected one of "
                f"{sorted(KNOWN_EVENTS)}"
            )
        results: list[VerifyOutcome] = []
        for spec in self._hooks.get(event_name, ()):
            try:
                raw = spec.callback(context)
            except Exception as exc:  # noqa: BLE001 — intentional broad catch
                # BaseException (KeyboardInterrupt, SystemExit) is *not*
                # subclass of Exception → will propagate naturally.
                if spec.fail_closed:
                    sev = spec.severity or "CRITICAL"
                    outcome = VerifyOutcome.escalate(
                        f"hook raised: {exc}", severity=sev
                    )
                    results.append(outcome)
                    if spec.blocking:
                        return results
                    continue
                # fail-open: swallow, contribute no outcome, keep going.
                continue
            outcome = _coerce_to_outcome(raw)
            outcome = _apply_default_severity(outcome, spec.severity)
            results.append(outcome)
            if spec.blocking and not outcome.ok:
                return results
        return results

    def has_blocking_veto(self, event_name: str, context: dict[str, Any]) -> bool:
        """Convenience: run ``emit`` and report whether any blocking hook
        produced a failed outcome.

        Used by the orchestrator to decide whether to halt before a
        verifier chain runs — semantically equivalent to "did any plugin
        say no?".
        """
        if event_name not in KNOWN_EVENTS:
            raise HookbusShimError(
                f"unknown event {event_name!r}; expected one of "
                f"{sorted(KNOWN_EVENTS)}"
            )
        # Walk hooks ourselves so we can correlate a failing outcome with
        # the *blocking* flag on its registration — emit() flattens that
        # signal out of the public result.
        for spec in self._hooks.get(event_name, ()):
            if not spec.blocking:
                # Still need to invoke non-blocking hooks? No — a non-
                # blocking failure is not a veto by definition.
                continue
            try:
                raw = spec.callback(context)
            except Exception:  # noqa: BLE001
                if spec.fail_closed:
                    # An error in a fail-closed blocking hook *is* a veto.
                    return True
                continue
            outcome = _coerce_to_outcome(raw)
            if not outcome.ok:
                return True
        return False


__all__ = [
    "HookBusShim",
    "HookSpec",
    "HookbusShimError",
    "KNOWN_EVENTS",
]
