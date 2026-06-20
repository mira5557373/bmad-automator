"""Gate schema definitions and validation (§6.4).

Defines the evidence record, gate file, waiver, and invariant-registry
schemas used by the Adjudicator.  Schema versions are mandatory and
enable forward-compat (future schemas migrate via evidence_migrate).

Artifact layout: _bmad/gate/{risk,evidence,verdicts}/
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .utils import ensure_dir

EVIDENCE_SCHEMA_VERSION = 1
GATE_SCHEMA_VERSION = 1
WAIVER_SCHEMA_VERSION = 1
MAX_WAIVER_TTL_DAYS = 30

VALID_EVIDENCE_STATUSES = frozenset({"ok", "violation", "error", "timeout"})
VALID_GATE_VERDICTS = frozenset({"PASS", "CONCERNS", "FAIL", "WAIVED"})
VALID_CATEGORY_VERDICTS = frozenset({"PASS", "CONCERNS", "FAIL", "NA"})
VALID_INVARIANT_CHECK_TYPES = frozenset({
    "semgrep", "conftest", "presence", "human",
})
VALID_INVARIANT_SEVERITIES = frozenset({"FAIL", "CONCERNS"})

GATE_ARTIFACT_SUBDIRS = ("risk", "evidence", "verdicts")


class GateSchemaError(ValueError):
    pass


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def compute_waiver_signature(waiver_fields: dict[str, Any]) -> str:
    signable = {
        k: v for k, v in waiver_fields.items() if k != "signature"
    }
    payload = canonical_json(signable)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def gate_artifact_dir(project_root: str | Path, subdir: str) -> Path:
    if subdir not in GATE_ARTIFACT_SUBDIRS:
        raise GateSchemaError(
            f"invalid gate artifact subdir: {subdir!r}; "
            f"must be one of {sorted(GATE_ARTIFACT_SUBDIRS)}"
        )
    path = Path(project_root) / "_bmad" / "gate" / subdir
    ensure_dir(path)
    return path


def make_evidence_record(
    *,
    collector: str,
    tool: str,
    tool_version: str = "",
    category: str,
    tier: str = "code",
    status: str,
    metrics: dict[str, Any] | None = None,
    findings: list[str] | None = None,
    raw_output_ref: str = "",
    exit_code: int = 0,
    duration_ms: int = 0,
    deterministic: bool = True,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "collector": collector,
        "tool": tool,
        "tool_version": tool_version,
        "category": category,
        "tier": tier,
        "status": status,
        "metrics": metrics or {},
        "findings": findings or [],
        "raw_output_ref": raw_output_ref,
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "deterministic": deterministic,
    }
    validate_evidence_record(record)
    return record


def make_timeout_evidence(
    collector: str,
    tool: str,
    category: str,
    timeout_s: int,
) -> dict[str, Any]:
    return make_evidence_record(
        collector=collector,
        tool=tool,
        category=category,
        status="timeout",
        findings=[f"TIMEOUT: {tool} exceeded {timeout_s}s"],
        exit_code=-1,
        deterministic=True,
    )


def make_gate_file(
    *,
    gate_id: str,
    target: dict[str, str],
    tier: str = "code",
    commit_sha: str,
    scanner_data_snapshot: str = "",
    profile: dict[str, Any],
    factory_version: str,
    risk_profile_ref: str = "",
    categories: dict[str, Any],
    overall: str,
    waivers: list[dict[str, Any]] | None = None,
    evidence_bundle_hash: str = "",
) -> dict[str, Any]:
    gate: dict[str, Any] = {
        "gate_id": gate_id,
        "schema_version": GATE_SCHEMA_VERSION,
        "target": target,
        "tier": tier,
        "commit_sha": commit_sha,
        "scanner_data_snapshot": scanner_data_snapshot,
        "profile": profile,
        "factory_version": factory_version,
        "risk_profile_ref": risk_profile_ref,
        "categories": categories,
        "overall": overall,
        "waivers": waivers or [],
        "evidence_bundle_hash": evidence_bundle_hash,
    }
    validate_gate_file(gate)
    return gate


def make_waiver(
    *,
    waiver_id: str,
    operator_id: str,
    issued_at: str,
    expires_at: str,
    failing_categories: list[str],
    reason: str,
    profile_hash: str,
) -> dict[str, Any]:
    waiver: dict[str, Any] = {
        "waiver_id": waiver_id,
        "operator_id": operator_id,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "failing_categories": failing_categories,
        "reason": reason,
        "profile_hash": profile_hash,
    }
    waiver["signature"] = compute_waiver_signature(waiver)
    return waiver


# ── Validation ────────────────────────────────────────────────────────


def validate_evidence_record(record: dict[str, Any]) -> None:
    _require_int(record, "schema_version", "evidence")
    _require_str(record, "collector", "evidence")
    _require_str(record, "tool", "evidence")
    _require_str(record, "category", "evidence")
    status = record.get("status")
    if status not in VALID_EVIDENCE_STATUSES:
        raise GateSchemaError(
            f"evidence.status must be one of "
            f"{sorted(VALID_EVIDENCE_STATUSES)}; got {status!r}"
        )
    findings = record.get("findings")
    if not isinstance(findings, list):
        raise GateSchemaError("evidence.findings must be a list")
    if not isinstance(record.get("metrics", {}), dict):
        raise GateSchemaError("evidence.metrics must be a dict")
    if not isinstance(record.get("deterministic", True), bool):
        raise GateSchemaError("evidence.deterministic must be a bool")


def validate_gate_file(gate: dict[str, Any]) -> None:
    _require_str(gate, "gate_id", "gate")
    _require_int(gate, "schema_version", "gate")
    if not isinstance(gate.get("target"), dict):
        raise GateSchemaError("gate.target must be an object")
    _require_str(gate, "commit_sha", "gate")
    if not isinstance(gate.get("profile"), dict):
        raise GateSchemaError("gate.profile must be an object")
    _require_str(gate, "factory_version", "gate")
    if not isinstance(gate.get("categories"), dict):
        raise GateSchemaError("gate.categories must be an object")
    overall = gate.get("overall")
    if overall not in VALID_GATE_VERDICTS:
        raise GateSchemaError(
            f"gate.overall must be one of "
            f"{sorted(VALID_GATE_VERDICTS)}; got {overall!r}"
        )
    waivers = gate.get("waivers", [])
    if not isinstance(waivers, list):
        raise GateSchemaError("gate.waivers must be a list")


def validate_waiver(waiver: dict[str, Any]) -> None:
    _require_str(waiver, "waiver_id", "waiver")
    _require_str(waiver, "operator_id", "waiver")
    _require_str(waiver, "issued_at", "waiver")
    _require_str(waiver, "expires_at", "waiver")
    _require_str(waiver, "reason", "waiver")
    _require_str(waiver, "signature", "waiver")
    _require_str(waiver, "profile_hash", "waiver")
    cats = waiver.get("failing_categories")
    if not isinstance(cats, list) or not cats:
        raise GateSchemaError(
            "waiver.failing_categories must be a non-empty list"
        )
    if not all(isinstance(c, str) for c in cats):
        raise GateSchemaError(
            "waiver.failing_categories entries must be strings"
        )


def validate_invariant_entry(entry: dict[str, Any]) -> None:
    _require_str(entry, "id", "invariant")
    checkable = entry.get("checkable")
    if checkable not in ("yes", "no"):
        raise GateSchemaError(
            f"invariant.checkable must be 'yes' or 'no'; got {checkable!r}"
        )
    if checkable == "yes":
        ct = entry.get("check_type")
        if ct not in VALID_INVARIANT_CHECK_TYPES:
            raise GateSchemaError(
                f"invariant.check_type must be one of "
                f"{sorted(VALID_INVARIANT_CHECK_TYPES)}; got {ct!r}"
            )
        _require_str(entry, "rule_file", "invariant")
    severity = entry.get("severity")
    if severity not in VALID_INVARIANT_SEVERITIES:
        raise GateSchemaError(
            f"invariant.severity must be one of "
            f"{sorted(VALID_INVARIANT_SEVERITIES)}; got {severity!r}"
        )


# ── Helpers ───────────────────────────────────────────────────────────


def _require_str(obj: dict[str, Any], key: str, label: str) -> None:
    val = obj.get(key)
    if not isinstance(val, str) or not val:
        raise GateSchemaError(f"{label}.{key} must be a non-empty string")


def _require_int(obj: dict[str, Any], key: str, label: str) -> None:
    val = obj.get(key)
    if not isinstance(val, int) or isinstance(val, bool):
        raise GateSchemaError(f"{label}.{key} must be an integer")
