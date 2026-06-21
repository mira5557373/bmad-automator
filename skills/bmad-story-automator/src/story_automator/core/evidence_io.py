"""Evidence I/O, migration, and gate lifecycle helpers (§6.4, §9.2, §18).

Handles persistence of evidence records and gate files to
_bmad/gate/{evidence,verdicts}/, evidence bundle hashing,
schema migration shims, gate reuse validation, and
gate-in-progress crash-safety markers.

Artifact layout: _bmad/gate/{risk,evidence,verdicts}/
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .gate_schema import (
    EVIDENCE_SCHEMA_VERSION,
    GateSchemaError,
    canonical_json,
    validate_evidence_record,
    validate_gate_file,
)
from .trust_boundary import assert_host_context
from .utils import ensure_dir, iso_now, write_atomic

_SAFE_GATE_ID = re.compile(r"^[a-zA-Z0-9._-]+$")


def _validate_gate_id(gate_id: str) -> None:
    """Reject gate_ids that could escape the artifact directory."""
    if not gate_id or not isinstance(gate_id, str):
        raise GateSchemaError("gate_id must be a non-empty string")
    if not _SAFE_GATE_ID.match(gate_id) or ".." in gate_id:
        raise GateSchemaError(
            f"gate_id contains invalid path characters: {gate_id!r}"
        )


def evidence_migrate(
    record: dict[str, Any],
    target_version: int = EVIDENCE_SCHEMA_VERSION,
) -> dict[str, Any]:
    """§6.4/§18: migrate evidence record to target schema version.

    v1 is the only known version; returns a deep copy.
    Future versions add elif branches here.
    """
    current = record.get("schema_version")
    if not isinstance(current, int) or isinstance(current, bool) or current < 1:
        raise GateSchemaError(
            "evidence.schema_version must be a positive integer"
        )
    if target_version < 1 or target_version > EVIDENCE_SCHEMA_VERSION:
        raise GateSchemaError(
            f"unknown target evidence schema version: {target_version}"
        )
    if current > target_version:
        raise GateSchemaError(
            f"cannot downgrade evidence from v{current} to v{target_version}"
        )
    return json.loads(json.dumps(record))


def compute_evidence_bundle_hash(records: list[dict[str, Any]]) -> str:
    """§18: deterministic hash over the full evidence bundle.

    Sorts by (category, collector, tool) so order of collection
    does not affect the hash. Returns 16-char hex prefix.
    """
    sorted_records = sorted(
        records,
        key=lambda r: (
            r.get("category", ""),
            r.get("collector", ""),
            r.get("tool", ""),
        ),
    )
    payload = "[" + ",".join(canonical_json(r) for r in sorted_records) + "]"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _sanitize_path_component(s: str) -> str:
    """Replace path separators and traversal sequences with underscores."""
    return s.replace("/", "_").replace("\\", "_").replace("..", "__")


def evidence_filename(record: dict[str, Any]) -> str:
    """Deterministic filename for an evidence record."""
    category = record.get("category", "unknown")
    collector = record.get("collector", "unknown")
    tool = record.get("tool", "unknown")
    return (
        f"{_sanitize_path_component(category)}--"
        f"{_sanitize_path_component(collector)}--"
        f"{_sanitize_path_component(tool)}.json"
    )


def persist_evidence_record(
    project_root: str | Path,
    gate_id: str,
    record: dict[str, Any],
) -> Path:
    """Write a validated evidence record to _bmad/gate/evidence/<gate_id>/."""
    assert_host_context("persist_evidence_record")
    _validate_gate_id(gate_id)
    validate_evidence_record(record)
    evidence_dir = Path(project_root) / "_bmad" / "gate" / "evidence" / gate_id
    ensure_dir(evidence_dir)
    filename = evidence_filename(record)
    target = evidence_dir / filename
    write_atomic(target, canonical_json(record) + "\n")
    return target


def load_evidence_bundle(
    project_root: str | Path,
    gate_id: str,
) -> list[dict[str, Any]]:
    """Load all evidence records for a gate, sorted deterministically."""
    _validate_gate_id(gate_id)
    evidence_dir = Path(project_root) / "_bmad" / "gate" / "evidence" / gate_id
    if not evidence_dir.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(evidence_dir.glob("*.json")):
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise GateSchemaError(
                f"cannot read evidence file {path.name}: {exc}"
            ) from exc
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise GateSchemaError(
                f"invalid JSON in evidence file {path.name}: {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise GateSchemaError(
                f"evidence file {path.name} must contain an object"
            )
        validate_evidence_record(data)
        records.append(data)
    records.sort(
        key=lambda r: (
            r.get("category", ""),
            r.get("collector", ""),
            r.get("tool", ""),
        ),
    )
    return records


def persist_gate_file(
    project_root: str | Path,
    gate_file: dict[str, Any],
) -> Path:
    """Write a validated gate file to _bmad/gate/verdicts/<gate_id>.json."""
    assert_host_context("persist_gate_file")
    validate_gate_file(gate_file)
    gate_id = gate_file["gate_id"]
    _validate_gate_id(gate_id)
    verdicts_dir = Path(project_root) / "_bmad" / "gate" / "verdicts"
    ensure_dir(verdicts_dir)
    target = verdicts_dir / f"{gate_id}.json"
    write_atomic(target, canonical_json(gate_file) + "\n")
    return target


def load_gate_file(
    project_root: str | Path,
    gate_id: str,
) -> dict[str, Any]:
    """Load a gate file from _bmad/gate/verdicts/<gate_id>.json."""
    _validate_gate_id(gate_id)
    path = Path(project_root) / "_bmad" / "gate" / "verdicts" / f"{gate_id}.json"
    if not path.is_file():
        raise GateSchemaError(f"gate file not found: {gate_id}")
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise GateSchemaError(
            f"cannot read gate file {gate_id}: {exc}"
        ) from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GateSchemaError(
            f"invalid JSON in gate file {gate_id}: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise GateSchemaError(f"gate file {gate_id} must contain an object")
    validate_gate_file(data)
    return data


def can_reuse_gate_file(
    gate_file: dict[str, Any],
    *,
    commit_sha: str,
    profile_hash: str,
    factory_version: str,
) -> tuple[bool, str]:
    """§9.2: gate file reusable only if all three match AND waivers still valid.

    Per §6.4(e), the Adjudicator re-checks waiver.expires_at against current
    time on every gate-file reuse (not just at issue). An expired waiver
    forces re-evaluation rather than keeping a stale PASS alive forever.
    """
    gate_sha = gate_file.get("commit_sha", "")
    if gate_sha != commit_sha:
        return False, (
            f"commit_sha mismatch: gate={gate_sha!r}, current={commit_sha!r}"
        )
    gate_profile_hash = (gate_file.get("profile") or {}).get("hash", "")
    if gate_profile_hash != profile_hash:
        return False, (
            f"profile.hash mismatch: gate={gate_profile_hash!r}, "
            f"current={profile_hash!r}"
        )
    gate_fv = gate_file.get("factory_version", "")
    if gate_fv != factory_version:
        return False, (
            f"factory_version mismatch: gate={gate_fv!r}, "
            f"current={factory_version!r}"
        )
    # §6.4(e): re-check every waiver's expires_at on each reuse. Imported
    # lazily to avoid a module-load cycle with gate_rules (which transitively
    # imports gate_schema, which imports evidence_io for marker helpers).
    waivers = gate_file.get("waivers") or []
    if waivers:
        from .gate_rules import is_waiver_expired
        for waiver in waivers:
            if not isinstance(waiver, dict):
                continue
            try:
                if is_waiver_expired(waiver):
                    waiver_id = waiver.get("waiver_id", "<unknown>")
                    return False, (
                        f"waiver expired: waiver_id={waiver_id!r} "
                        f"expires_at={waiver.get('expires_at', '')!r}"
                    )
            except Exception as exc:  # noqa: BLE001 — fail-closed on any waiver error
                waiver_id = waiver.get("waiver_id", "<unknown>")
                return False, (
                    f"waiver validation error: waiver_id={waiver_id!r} {exc}"
                )
    return True, ""


_GATE_MARKER_NAME = "gate-in-progress.json"


def _gate_marker_path(project_root: str | Path) -> Path:
    return Path(project_root) / "_bmad" / "gate" / _GATE_MARKER_NAME


def write_gate_marker(
    project_root: str | Path,
    gate_id: str,
    commit_sha: str,
) -> Path:
    """§9.2: atomic marker before collector loop starts."""
    assert_host_context("write_gate_marker")
    marker = {
        "gate_id": gate_id,
        "commit_sha": commit_sha,
        "started_at": iso_now(),
    }
    path = _gate_marker_path(project_root)
    ensure_dir(path.parent)
    write_atomic(path, canonical_json(marker) + "\n")
    return path


class GateMarkerCorruptedError(RuntimeError):
    """§9.2: a corrupted gate-in-progress marker must fail-loud, not silent.

    Raised by read_gate_marker when the marker file exists but cannot be
    parsed as valid JSON or has the wrong shape. The orchestrator's
    recover_from_crash treats this distinctly from "no marker present":
    the partial evidence is quarantined (not deleted) and an operator
    alert is emitted.
    """


def read_gate_marker(
    project_root: str | Path,
) -> dict[str, Any] | None:
    """Read gate-in-progress marker.

    Returns None when the marker file is absent (the normal "no in-flight
    gate" case).

    Raises GateMarkerCorruptedError when the marker exists but is
    unreadable or malformed. Corruption is a distinct condition from
    "no marker" — silently dropping the marker would let the orchestrator
    silently delete evidence the operator may still need to investigate
    (§9.2: "corruption is loud, not silent").
    """
    path = _gate_marker_path(project_root)
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise GateMarkerCorruptedError(
            f"gate marker unreadable: {path}: {exc}"
        ) from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GateMarkerCorruptedError(
            f"gate marker not valid JSON: {path}: {exc.msg} (line {exc.lineno})"
        ) from exc
    if not isinstance(data, dict):
        raise GateMarkerCorruptedError(
            f"gate marker must be a JSON object, got {type(data).__name__}: {path}"
        )
    return data


def clear_gate_marker(project_root: str | Path) -> None:
    """§9.2: remove marker after verdict is written (or on crash recovery)."""
    assert_host_context("clear_gate_marker")
    path = _gate_marker_path(project_root)
    try:
        path.unlink()
    except FileNotFoundError:
        pass
