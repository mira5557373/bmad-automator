from __future__ import annotations

"""TEA Waiver <-> bauto Escalation bidirectional translator (M47).

Two vocabularies meet at this bridge:

* TEA gate **Waiver** — granted on a single gate category to suppress a FAIL
  for a bounded period. Shape (closed set):
      {category, reason, granted_by, expires_at, scope}
  plus any number of caller-supplied metadata keys.

* Bauto **Escalation** — a typed event published on the escalation bus. Shape
  (closed set):
      {api_version, kind, severity, category, reason, actor, expires_at,
       scope}
  with optional `metadata` mapping.

Semantically, a `PREFERENCE`-severity escalation says "an operator prefers to
bypass this gate" — which is exactly what a Waiver encodes. `CRITICAL`
escalations cannot be downgraded into waivers — translating one is an error.

The module is pure (no I/O, no telemetry, no logging) so it can be composed by
either side without coupling. It deliberately does NOT import from
core/telemetry_events.py — guardrail compliance.
"""

from collections.abc import Mapping
from typing import Any

__all__ = [
    "ESCALATION_API_VERSION",
    "PREFERENCE",
    "CRITICAL",
    "VALID_SEVERITIES",
    "WAIVER_FIELDS",
    "ESCALATION_FIELDS",
    "WaiverEscalationError",
    "waiver_to_escalation",
    "escalation_to_waiver",
    "is_waiver_equivalent",
    "round_trip_waiver",
]


# --- Constants ---------------------------------------------------------------

ESCALATION_API_VERSION = 1
PREFERENCE = "PREFERENCE"
CRITICAL = "CRITICAL"
VALID_SEVERITIES = frozenset({PREFERENCE, CRITICAL})

# Closed shape (excluding free-form metadata) — order matters only for docs.
WAIVER_FIELDS = ("category", "reason", "granted_by", "expires_at", "scope")
ESCALATION_FIELDS = (
    "api_version",
    "kind",
    "severity",
    "category",
    "reason",
    "actor",
    "expires_at",
    "scope",
)


class WaiverEscalationError(ValueError):
    """Raised when a waiver/escalation payload cannot be translated."""


# --- Internal helpers --------------------------------------------------------


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise WaiverEscalationError(
            f"{label} must be a mapping, got {type(value).__name__}"
        )
    return value


def _require_nonempty_str(payload: Mapping[str, Any], key: str, label: str) -> str:
    if key not in payload:
        raise WaiverEscalationError(f"{label} missing required field {key!r}")
    value = payload[key]
    if not isinstance(value, str):
        raise WaiverEscalationError(
            f"{label} field {key!r} must be a string, got {type(value).__name__}"
        )
    if not value.strip():
        raise WaiverEscalationError(f"{label} field {key!r} must not be empty")
    return value


def _extract_metadata(
    payload: Mapping[str, Any], known: tuple[str, ...]
) -> dict[str, Any]:
    return {k: payload[k] for k in payload.keys() if k not in known}


# --- Forward: waiver -> escalation ------------------------------------------


def waiver_to_escalation(waiver: Mapping[str, Any]) -> dict[str, Any]:
    """Translate a TEA Waiver into a PREFERENCE-severity escalation payload.

    The returned dict is JSON-friendly and includes a `metadata` key carrying
    any caller-supplied fields outside the closed waiver shape, so the reverse
    direction is lossless. The escalation severity is always ``PREFERENCE`` —
    a waiver never expresses a CRITICAL bypass.
    """
    mapping = _require_mapping(waiver, "waiver")
    category = _require_nonempty_str(mapping, "category", "waiver")
    reason = _require_nonempty_str(mapping, "reason", "waiver")
    granted_by = _require_nonempty_str(mapping, "granted_by", "waiver")
    expires_at = _require_nonempty_str(mapping, "expires_at", "waiver")
    scope = _require_nonempty_str(mapping, "scope", "waiver")

    metadata = _extract_metadata(mapping, WAIVER_FIELDS)

    payload: dict[str, Any] = {
        "api_version": ESCALATION_API_VERSION,
        "kind": "escalation",
        "severity": PREFERENCE,
        "category": category,
        "reason": reason,
        "actor": granted_by,
        "expires_at": expires_at,
        "scope": scope,
    }
    if metadata:
        payload["metadata"] = metadata
    return payload


# --- Reverse: escalation -> waiver ------------------------------------------


def _validate_escalation_envelope(payload: Mapping[str, Any]) -> str:
    """Return the severity string after envelope checks."""
    api_version = payload.get("api_version")
    if api_version != ESCALATION_API_VERSION:
        raise WaiverEscalationError(
            f"unsupported escalation api_version: {api_version!r}"
        )
    kind = payload.get("kind")
    if kind != "escalation":
        raise WaiverEscalationError(
            f"expected kind 'escalation', got {kind!r}"
        )
    severity = payload.get("severity")
    if severity not in VALID_SEVERITIES:
        raise WaiverEscalationError(
            f"unknown escalation severity: {severity!r}"
        )
    return severity  # type: ignore[return-value]


def escalation_to_waiver(escalation: Mapping[str, Any]) -> dict[str, Any]:
    """Translate a PREFERENCE escalation into a TEA Waiver.

    CRITICAL escalations cannot be downgraded — caller must triage those
    through the failure-triage path, not the waiver path.
    """
    mapping = _require_mapping(escalation, "escalation")
    severity = _validate_escalation_envelope(mapping)
    if severity == CRITICAL:
        raise WaiverEscalationError(
            "CRITICAL escalations cannot be translated to a waiver — "
            "they require triage, not a bypass"
        )

    category = _require_nonempty_str(mapping, "category", "escalation")
    reason = _require_nonempty_str(mapping, "reason", "escalation")
    actor = _require_nonempty_str(mapping, "actor", "escalation")
    expires_at = _require_nonempty_str(mapping, "expires_at", "escalation")
    scope = _require_nonempty_str(mapping, "scope", "escalation")

    waiver: dict[str, Any] = {
        "category": category,
        "reason": reason,
        "granted_by": actor,
        "expires_at": expires_at,
        "scope": scope,
    }

    # Surface metadata carried through the forward bridge so round-tripping is
    # lossless. We don't validate metadata contents — callers own that.
    metadata = mapping.get("metadata")
    if isinstance(metadata, Mapping):
        for key, value in metadata.items():
            if key in waiver:
                # Don't let metadata silently override structural fields.
                raise WaiverEscalationError(
                    f"escalation metadata key {key!r} collides with "
                    "structural waiver field"
                )
            waiver[key] = value
    return waiver


# --- Convenience -------------------------------------------------------------


def is_waiver_equivalent(escalation: Any) -> bool:
    """Return True iff the escalation is a well-formed PREFERENCE payload.

    Useful for callers that want to test "can I treat this escalation as a
    waiver?" without raising. Any malformed payload returns False.
    """
    if not isinstance(escalation, Mapping):
        return False
    try:
        severity = _validate_escalation_envelope(escalation)
    except WaiverEscalationError:
        return False
    return severity == PREFERENCE


def round_trip_waiver(waiver: Mapping[str, Any]) -> dict[str, Any]:
    """Validate that a waiver survives a waiver -> escalation -> waiver loop.

    Returns the rebuilt waiver. A clean round-trip is the contract that lets
    either side of the bridge own the canonical form without conversion loss.
    """
    escalation = waiver_to_escalation(waiver)
    return escalation_to_waiver(escalation)
