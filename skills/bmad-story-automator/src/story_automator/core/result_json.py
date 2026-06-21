"""Session-result schema (``result.json``) — Phase 2 wire contract.

Bridges a dev-session's self-reported claims to the gate's verifier.
The session writes a single ``result.json`` to a known location; the
gate reads it back and cross-checks the claims against on-disk
evidence + git state. This is the schema spine — Phase 3 wires the
verifier to actually consume it. We ship the schema + IO + validation
now so Phase 3 is a small, well-bounded change.

Design constraints (per docs/spec/frozen-gate-surface.md guardrail #5):

  - Wire form is deterministic: alpha-sorted keys, no timestamps,
    no PIDs, no run-IDs.
  - ``api_version`` is the SCHEMA-level version (this module). It is
    distinct from ``schema_version`` on gate files (which versions
    the gate-file shape) and from ``factory_version`` (the package
    version). A schema bump = api_version bump; readers compare
    major versions and reject mismatches loudly.
  - Atomic write via the existing ``write_atomic_text`` helper so a
    crash mid-write cannot leave a half-formed file.

Schema (api_version 1):

  {
    "api_version": 1,
    "claims": {
      "commit_sha": "<40-char hex or empty>",
      "files_changed": ["repo-relative posix paths"],
      "summary": "<one-line natural-language summary>"
    },
    "escalations": [
      {"severity": "CRITICAL"|"PREFERENCE", "reason": "<text>"}
    ],
    "spec_file": "<repo-relative posix path or empty>"
  }

Validation policies:

  - Missing top-level key (other than ``escalations``, which defaults
    to ``[]``) → :class:`ResultJsonError`.
  - Unknown extra key → :class:`ResultJsonError` (fail-closed; an LLM
    inventing fields is exactly what this schema guards against).
  - ``api_version`` MAJOR mismatch → :class:`ResultJsonApiVersionError`
    (subclass of ResultJsonError) so the caller can route by error
    type.
  - Type drift (e.g. ``files_changed`` not a list of strings) →
    :class:`ResultJsonError` with a precise pointer.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .atomic_io import write_atomic_text

RESULT_JSON_API_VERSION = 1

# Top-level keys. ``escalations`` is optional (defaults to []); the rest
# are required.
_REQUIRED_KEYS = {"api_version", "claims", "spec_file"}
_OPTIONAL_KEYS = {"escalations"}
_ALLOWED_KEYS = _REQUIRED_KEYS | _OPTIONAL_KEYS

# Required keys inside claims{}.
_REQUIRED_CLAIM_KEYS = {"commit_sha", "files_changed", "summary"}
_ALLOWED_CLAIM_KEYS = _REQUIRED_CLAIM_KEYS

# Allowed escalation severities. Mirrors VerifyOutcome.severity.
_ALLOWED_SEVERITIES = {"CRITICAL", "PREFERENCE"}


class ResultJsonError(ValueError):
    """Malformed result.json — schema violation."""


class ResultJsonApiVersionError(ResultJsonError):
    """Major api_version mismatch — caller should refuse, not coerce."""


def make_session_result(
    *,
    commit_sha: str,
    files_changed: list[str],
    summary: str,
    spec_file: str = "",
    escalations: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Build a result.json payload, alpha-key-ordered for determinism.

    The returned dict is suitable for :func:`write_result_json` or for
    direct embedding (e.g. in tests). No defensive copies — callers
    should treat the result as read-only.
    """
    if escalations is None:
        escalations = []
    payload: dict[str, Any] = {
        "api_version": RESULT_JSON_API_VERSION,
        "claims": {
            "commit_sha": commit_sha,
            "files_changed": list(files_changed),
            "summary": summary,
        },
        "escalations": list(escalations),
        "spec_file": spec_file,
    }
    # Validate once so we never persist a malformed payload.
    validate_result_json(payload)
    return payload


def validate_result_json(payload: Any) -> None:
    """Raise :class:`ResultJsonError` if ``payload`` does not match the schema.

    Performs strict validation: missing keys, unknown keys, wrong
    types, and api_version major mismatches all raise. The error
    message names the precise field so debugging on a broken session
    output is mechanical.
    """
    if not isinstance(payload, dict):
        raise ResultJsonError(f"result.json must be a JSON object, got {type(payload).__name__}")

    keys = set(payload.keys())
    missing = _REQUIRED_KEYS - keys
    if missing:
        raise ResultJsonError(f"result.json missing required keys: {sorted(missing)}")
    extra = keys - _ALLOWED_KEYS
    if extra:
        raise ResultJsonError(f"result.json has unknown keys: {sorted(extra)}")

    api_version = payload["api_version"]
    if not isinstance(api_version, int):
        raise ResultJsonError(
            f"api_version must be int, got {type(api_version).__name__}"
        )
    # Major version is the integer itself (api_version 1 = major 1).
    if api_version != RESULT_JSON_API_VERSION:
        raise ResultJsonApiVersionError(
            f"api_version mismatch: file has {api_version}, "
            f"reader expects {RESULT_JSON_API_VERSION}"
        )

    spec_file = payload["spec_file"]
    if not isinstance(spec_file, str):
        raise ResultJsonError(
            f"spec_file must be str, got {type(spec_file).__name__}"
        )

    claims = payload["claims"]
    _validate_claims(claims)

    escalations = payload.get("escalations", [])
    _validate_escalations(escalations)


def _validate_claims(claims: Any) -> None:
    if not isinstance(claims, dict):
        raise ResultJsonError(
            f"claims must be an object, got {type(claims).__name__}"
        )
    keys = set(claims.keys())
    missing = _REQUIRED_CLAIM_KEYS - keys
    if missing:
        raise ResultJsonError(f"claims missing keys: {sorted(missing)}")
    extra = keys - _ALLOWED_CLAIM_KEYS
    if extra:
        raise ResultJsonError(f"claims has unknown keys: {sorted(extra)}")

    if not isinstance(claims["commit_sha"], str):
        raise ResultJsonError("claims.commit_sha must be str")
    if not isinstance(claims["summary"], str):
        raise ResultJsonError("claims.summary must be str")

    files = claims["files_changed"]
    if not isinstance(files, list) or not all(isinstance(p, str) for p in files):
        raise ResultJsonError("claims.files_changed must be a list of strings")


def _validate_escalations(escalations: Any) -> None:
    if not isinstance(escalations, list):
        raise ResultJsonError(
            f"escalations must be a list, got {type(escalations).__name__}"
        )
    for i, esc in enumerate(escalations):
        if not isinstance(esc, dict):
            raise ResultJsonError(
                f"escalations[{i}] must be an object, got {type(esc).__name__}"
            )
        if set(esc.keys()) != {"severity", "reason"}:
            raise ResultJsonError(
                f"escalations[{i}] must have exactly keys "
                f"{{severity, reason}}, got {sorted(esc.keys())}"
            )
        if esc["severity"] not in _ALLOWED_SEVERITIES:
            raise ResultJsonError(
                f"escalations[{i}].severity must be one of "
                f"{sorted(_ALLOWED_SEVERITIES)}, got {esc['severity']!r}"
            )
        if not isinstance(esc["reason"], str):
            raise ResultJsonError(f"escalations[{i}].reason must be str")


def write_result_json(path: str | Path, payload: dict[str, Any]) -> Path:
    """Atomically write ``payload`` to ``path``.

    The payload is validated before write; an invalid payload raises
    :class:`ResultJsonError` and nothing is touched on disk.
    """
    validate_result_json(payload)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    write_atomic_text(target, text)
    return target


def read_result_json(path: str | Path) -> dict[str, Any]:
    """Read and validate a result.json from disk.

    Raises :class:`ResultJsonError` (or its subclass
    :class:`ResultJsonApiVersionError`) on any schema violation,
    :class:`FileNotFoundError` if the file is absent, and
    ``json.JSONDecodeError`` on syntactically broken JSON (we let
    the stdlib exception bubble so the caller can distinguish
    "not JSON" from "wrong shape").
    """
    raw = Path(path).read_text(encoding="utf-8")
    payload = json.loads(raw)
    validate_result_json(payload)
    return payload


def critical_escalations(payload: dict[str, Any] | None) -> list[dict[str, str]]:
    """Filter the ``escalations`` list to entries with severity CRITICAL.

    Returns ``[]`` for a None payload (matches bmad-auto's helper).
    """
    if not payload:
        return []
    return [
        e for e in payload.get("escalations", [])
        if isinstance(e, dict) and e.get("severity") == "CRITICAL"
    ]


def preference_escalations(payload: dict[str, Any] | None) -> list[dict[str, str]]:
    """Filter to PREFERENCE-severity escalations. ``[]`` on None payload."""
    if not payload:
        return []
    return [
        e for e in payload.get("escalations", [])
        if isinstance(e, dict) and e.get("severity") == "PREFERENCE"
    ]
