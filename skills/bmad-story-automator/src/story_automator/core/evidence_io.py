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
from pathlib import Path
from typing import Any

from .gate_schema import (
    EVIDENCE_SCHEMA_VERSION,
    GATE_SCHEMA_VERSION,
    GateSchemaError,
    canonical_json,
    validate_evidence_record,
    validate_gate_file,
    validate_schema_version,
)
from .utils import ensure_dir, write_atomic


def _validate_gate_id(gate_id: str) -> None:
    """Reject gate_ids that could escape the artifact directory."""
    if not gate_id or not isinstance(gate_id, str):
        raise GateSchemaError("gate_id must be a non-empty string")
    if "/" in gate_id or "\\" in gate_id or ".." in gate_id:
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
    """Replace path separators with underscores."""
    return s.replace("/", "_").replace("\\", "_")


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
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise GateSchemaError(
                f"invalid JSON in evidence file {path.name}: {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise GateSchemaError(
                f"evidence file {path.name} must contain an object"
            )
        validate_schema_version(data, EVIDENCE_SCHEMA_VERSION, "evidence")
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
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GateSchemaError(
            f"invalid JSON in gate file {gate_id}: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise GateSchemaError(f"gate file {gate_id} must contain an object")
    validate_schema_version(data, GATE_SCHEMA_VERSION, "gate")
    validate_gate_file(data)
    return data


def can_reuse_gate_file(
    gate_file: dict[str, Any],
    *,
    commit_sha: str,
    profile_hash: str,
    factory_version: str,
) -> tuple[bool, str]:
    """§9.2: gate file reusable only if all three match."""
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
    return True, ""
