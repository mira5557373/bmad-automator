"""Gate schema definitions and validation (§6.4).

Defines the evidence record, gate file, waiver, and invariant-registry
schemas used by the Adjudicator.  Schema versions are mandatory and
enable forward-compat (future schemas migrate via evidence_migrate).

Artifact layout: _bmad/gate/{risk,evidence,verdicts}/
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
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
VALID_CONFIDENCE_RANGE = range(1, 11)  # 1–10 inclusive

GATE_ARTIFACT_SUBDIRS = ("risk", "evidence", "verdicts")


class GateSchemaError(ValueError):
    pass


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def compute_waiver_signature(waiver_fields: dict[str, Any]) -> str:
    """Deterministic integrity check (not a cryptographic signature)."""
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


def make_llm_evidence_record(
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
    confidence: int,
    rationale: str,
) -> dict[str, Any]:
    if not isinstance(confidence, int) or isinstance(confidence, bool):
        raise GateSchemaError("evidence.confidence must be an integer")
    if confidence not in VALID_CONFIDENCE_RANGE:
        raise GateSchemaError(
            f"evidence.confidence must be 1..10; got {confidence}"
        )
    if not isinstance(rationale, str) or not rationale.strip():
        raise GateSchemaError("evidence.rationale must be a non-empty string")
    record = make_evidence_record(
        collector=collector,
        tool=tool,
        tool_version=tool_version,
        category=category,
        tier=tier,
        status=status,
        metrics=metrics,
        findings=findings,
        raw_output_ref=raw_output_ref,
        exit_code=exit_code,
        duration_ms=duration_ms,
        deterministic=False,
    )
    record["confidence"] = confidence
    record["rationale"] = rationale
    return record


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
    validate_schema_version(record, EVIDENCE_SCHEMA_VERSION, "evidence")
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
    metrics = record.get("metrics", {})
    if not isinstance(metrics, dict):
        raise GateSchemaError("evidence.metrics must be a dict")
    for mk, mv in metrics.items():
        if not isinstance(mk, str):
            raise GateSchemaError(
                f"evidence.metrics key must be a string; got {mk!r}"
            )
        # bool is a subclass of int — allow it explicitly.
        if isinstance(mv, bool):
            continue
        if isinstance(mv, (int, str)):
            continue
        if isinstance(mv, float):
            if math.isnan(mv) or math.isinf(mv):
                raise GateSchemaError(
                    f"evidence.metrics[{mk!r}] must be finite; got {mv!r}"
                )
            continue
        raise GateSchemaError(
            f"evidence.metrics[{mk!r}] must be bool|int|float|str; "
            f"got {type(mv).__name__}"
        )
    if not isinstance(record.get("deterministic", True), bool):
        raise GateSchemaError("evidence.deterministic must be a bool")
    tier = record.get("tier", "code")
    if not isinstance(tier, str):
        raise GateSchemaError("evidence.tier must be a string")
    exit_code = record.get("exit_code", 0)
    if not isinstance(exit_code, int) or isinstance(exit_code, bool):
        raise GateSchemaError("evidence.exit_code must be an integer")
    duration_ms = record.get("duration_ms", 0)
    if not isinstance(duration_ms, int) or isinstance(duration_ms, bool):
        raise GateSchemaError("evidence.duration_ms must be an integer")
    if duration_ms < 0:
        raise GateSchemaError("evidence.duration_ms must be >= 0")
    if not isinstance(record.get("tool_version", ""), str):
        raise GateSchemaError("evidence.tool_version must be a string")
    if not isinstance(record.get("raw_output_ref", ""), str):
        raise GateSchemaError("evidence.raw_output_ref must be a string")
    if not record.get("deterministic", True):
        conf = record.get("confidence")
        if conf is not None:
            if not isinstance(conf, int) or isinstance(conf, bool):
                raise GateSchemaError("evidence.confidence must be an integer")
            if conf not in VALID_CONFIDENCE_RANGE:
                raise GateSchemaError(
                    f"evidence.confidence must be 1..10; got {conf}"
                )
        rat = record.get("rationale")
        if rat is not None:
            if not isinstance(rat, str) or not rat.strip():
                raise GateSchemaError(
                    "evidence.rationale must be a non-empty string"
                )


def validate_gate_file(gate: dict[str, Any]) -> None:
    _require_str(gate, "gate_id", "gate")
    _require_int(gate, "schema_version", "gate")
    validate_schema_version(gate, GATE_SCHEMA_VERSION, "gate")
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
    # Reject naive (no-tz) ISO timestamps at schema-validate time so they
    # cannot crash the orchestrator later with TypeError when compared to
    # `datetime.now(timezone.utc)` inside `is_waiver_expired`.
    _require_tz_aware_iso(waiver, "issued_at")
    _require_tz_aware_iso(waiver, "expires_at")
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


def validate_schema_version(record: dict[str, Any], max_known: int, label: str) -> None:
    version = record.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise GateSchemaError(f"{label}.schema_version must be an integer")
    if version < 1:
        raise GateSchemaError(f"{label}.schema_version must be >= 1; got {version}")
    if version > max_known:
        raise GateSchemaError(f"{label}.schema_version {version} exceeds max known version {max_known}; upgrade the factory")


# ── Helpers ───────────────────────────────────────────────────────────


def _require_str(obj: dict[str, Any], key: str, label: str) -> None:
    val = obj.get(key)
    if not isinstance(val, str) or not val:
        raise GateSchemaError(f"{label}.{key} must be a non-empty string")


def _require_tz_aware_iso(waiver: dict[str, Any], key: str) -> None:
    """Reject naive ISO timestamps; they crash orchestrator comparisons."""
    text = str(waiver.get(key, "")).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise GateSchemaError(
            f"waiver.{key} is not a valid ISO 8601 timestamp: {exc}"
        ) from exc
    if parsed.tzinfo is None:
        raise GateSchemaError(
            f"waiver.{key} must include a timezone offset (e.g. 'Z' or '+00:00'); "
            f"got {waiver.get(key)!r}"
        )


def _require_int(obj: dict[str, Any], key: str, label: str) -> None:
    val = obj.get(key)
    if not isinstance(val, int) or isinstance(val, bool):
        raise GateSchemaError(f"{label}.{key} must be an integer")
