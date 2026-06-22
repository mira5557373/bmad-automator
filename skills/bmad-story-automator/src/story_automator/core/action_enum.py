"""Action vocabulary for the production-ready gate verifier (Path B M5).

A purely additive type-hint surface: this module exposes a ``Literal``-typed
``Action`` alias plus a small canonicalisation helper. Nothing here changes
the runtime behaviour of ``gate_orchestrator.route_gate_verdict`` or any
other call site — it only lets call sites that already return action
strings annotate their return types so type-checkers can narrow them.

Vocabulary (deterministic order, used in error messages):

  * ``done``       — gate passed (or waived/concerns acceptable), commit.
  * ``remediate``  — gate failed but cycles remain; emit [AI-Review] tasks.
  * ``park``       — gate cannot make progress (risk-9, exhausted, etc.).
  * ``defer``      — gate decision deferred to a later cycle / human.
  * ``escalate``   — gate decision routed up to an operator / reviewer.

Notes:

  * ``ActionError`` subclasses ``ValueError`` so existing
    ``except ValueError:`` blocks continue to work.
  * ``canonicalize_action`` is intentionally permissive (case-insensitive,
    whitespace-stripping, accepts ``bytes``) so external inputs — CLI
    flags, JSON payloads, gate-file fields — can be normalised in one
    place before comparison.
  * The strict ``is_valid_action`` companion is case-sensitive on purpose;
    call sites that want laxity should canonicalise first.
"""
from __future__ import annotations

from typing import Literal

Action = Literal["done", "remediate", "park", "defer", "escalate"]
"""Static Literal alias for the verifier action vocabulary."""

VALID_ACTIONS: tuple[str, ...] = ("done", "remediate", "park", "defer", "escalate")
"""Runtime tuple mirror of :data:`Action` — immutable, deterministic order."""


class ActionError(ValueError):
    """Raised when an action string is not a member of ``VALID_ACTIONS``."""


def is_valid_action(value: str) -> bool:
    """Return ``True`` iff ``value`` is an exact member of ``VALID_ACTIONS``.

    Strict by design: ``"DONE"`` returns ``False``. Use
    :func:`canonicalize_action` first if you want case-insensitive checks.
    """
    return value in VALID_ACTIONS


def canonicalize_action(raw: str | bytes) -> str:
    """Normalise ``raw`` to a canonical lowercase action string.

    * ``bytes`` is decoded as UTF-8 (errors are surfaced as ``ActionError``).
    * Leading/trailing whitespace is stripped.
    * Case is folded to lowercase.
    * Anything outside :data:`VALID_ACTIONS` raises :class:`ActionError`.
    """
    if isinstance(raw, bytes):
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ActionError(
                f"action bytes not valid utf-8: {exc!r}"
            ) from exc
    elif isinstance(raw, str):
        text = raw
    else:
        raise ActionError(
            f"action must be str or bytes, got {type(raw).__name__}"
        )

    normalised = text.strip().lower()
    if normalised not in VALID_ACTIONS:
        raise ActionError(
            f"unknown action {raw!r}; expected one of {VALID_ACTIONS}"
        )
    return normalised


__all__ = [
    "Action",
    "VALID_ACTIONS",
    "ActionError",
    "is_valid_action",
    "canonicalize_action",
]
