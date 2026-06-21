from __future__ import annotations

import json
from pathlib import Path

ESCALATION_API_VERSION = 1
VALID_SEVERITIES = frozenset({"CRITICAL", "PREFERENCE"})

_REQUIRED_FIELDS = (
    "api_version",
    "story_key",
    "severity",
    "reason",
    "originating_phase",
    "suggested_action",
    "waiver_ref",
)


class EscalationError(ValueError):
    """Raised when an escalation payload is invalid or cannot be loaded."""


def emit_escalation(
    *,
    story_key: str,
    severity: str,
    reason: str,
    originating_phase: str,
    suggested_action: str = "",
    waiver_ref: str = "",
) -> dict:
    if not isinstance(story_key, str) or not story_key.strip():
        raise EscalationError("story_key must be a non-empty string")
    if severity not in VALID_SEVERITIES:
        raise EscalationError(
            f"severity must be one of {sorted(VALID_SEVERITIES)}, got {severity!r}"
        )
    if not isinstance(reason, str) or not reason.strip():
        raise EscalationError("reason must be a non-empty string")
    if not isinstance(originating_phase, str) or not originating_phase.strip():
        raise EscalationError("originating_phase must be a non-empty string")
    if not isinstance(suggested_action, str):
        raise EscalationError("suggested_action must be a string")
    if not isinstance(waiver_ref, str):
        raise EscalationError("waiver_ref must be a string")

    return {
        "api_version": ESCALATION_API_VERSION,
        "story_key": story_key,
        "severity": severity,
        "reason": reason,
        "originating_phase": originating_phase,
        "suggested_action": suggested_action,
        "waiver_ref": waiver_ref,
    }


def write_escalation(path: str | Path, payload: dict) -> Path:
    _validate_payload(payload)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def read_escalation(path: str | Path) -> dict:
    source = Path(path)
    try:
        raw = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise EscalationError(f"cannot read escalation at {source}: {exc}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise EscalationError(f"invalid JSON in escalation at {source}: {exc}") from exc
    if not isinstance(payload, dict):
        raise EscalationError("escalation payload must be a JSON object")
    _validate_payload(payload)
    return payload


def _validate_payload(payload: dict) -> None:
    missing = [field for field in _REQUIRED_FIELDS if field not in payload]
    if missing:
        raise EscalationError(f"escalation payload missing fields: {missing}")
    if payload["api_version"] != ESCALATION_API_VERSION:
        raise EscalationError(
            f"unsupported escalation api_version: {payload['api_version']!r}"
        )
    if payload["severity"] not in VALID_SEVERITIES:
        raise EscalationError(
            f"escalation severity must be one of {sorted(VALID_SEVERITIES)}"
        )
    for field in ("story_key", "reason", "originating_phase"):
        value = payload[field]
        if not isinstance(value, str) or not value.strip():
            raise EscalationError(f"escalation field {field!r} must be a non-empty string")
    for field in ("suggested_action", "waiver_ref"):
        if not isinstance(payload[field], str):
            raise EscalationError(f"escalation field {field!r} must be a string")
