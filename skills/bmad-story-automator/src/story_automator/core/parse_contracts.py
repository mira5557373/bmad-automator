from __future__ import annotations

import json
from typing import Any

from .diagnostics import DiagnosticIssue, issues_from_exception, serialize_issues
from .utils import read_text


class ParseContractError(ValueError):
    def __init__(self, issues: list[DiagnosticIssue]) -> None:
        super().__init__(issues[0].message if issues else "parse contract invalid")
        self.issues = issues


def load_parse_contract(contract: dict[str, object]) -> dict[str, object]:
    parse = contract.get("parse") or {}
    try:
        payload = json.loads(read_text(str(parse.get("schemaPath") or "")))
    except Exception as exc:
        raise ParseContractError(issues_from_exception(exc, source="parse-contract", field="parse.schemaPath")) from exc
    issues = validate_parse_contract(payload)
    if issues:
        raise ParseContractError(issues)
    return payload


def validate_parse_contract(payload: object) -> list[DiagnosticIssue]:
    issues: list[DiagnosticIssue] = []
    if not isinstance(payload, dict):
        return [
            _issue(
                "invalid_type",
                "contract",
                "object",
                payload,
                "Parse contract must be an object",
                source="parse-contract",
            )
        ]
    required_keys = payload.get("requiredKeys")
    if not isinstance(required_keys, list):
        issues.append(_issue("invalid_type", "requiredKeys", "array of strings", required_keys, "Parse contract requiredKeys must be an array", source="parse-contract"))
    elif any(not isinstance(key, str) or not key.strip() for key in required_keys):
        issues.append(_issue("invalid_value", "requiredKeys", "non-empty string keys", required_keys, "Parse contract requiredKeys must contain non-empty strings", source="parse-contract"))
    schema = payload.get("schema")
    if not isinstance(schema, dict):
        issues.append(_issue("invalid_type", "schema", "object", schema, "Parse contract schema must be an object", source="parse-contract"))
    else:
        _validate_schema_contract(schema, "schema", issues)
    return issues


def validate_payload(payload: object, parse_contract: dict[str, object]) -> list[DiagnosticIssue]:
    issues: list[DiagnosticIssue] = []
    required_keys = parse_contract.get("requiredKeys") or []
    schema = parse_contract.get("schema") or {}
    if not isinstance(payload, dict):
        return [_issue("invalid_type", "payload", "object", payload, "Sub-agent output must be a JSON object")]
    for key in required_keys:
        if isinstance(key, str) and key not in payload:
            issues.append(_issue("missing_required_key", key, "present", None, f"Missing required key {key}"))
    if isinstance(schema, dict):
        _validate_schema(payload, schema, "", issues)
    return issues


def parse_failure_payload(reason: str, issues: list[DiagnosticIssue] | None = None) -> dict[str, object]:
    return {"status": "error", "reason": reason, "structuredIssues": serialize_issues(issues or [])}


def verifier_exception_payload(reason: str, exc: Exception, *, source: str, **extra: object) -> dict[str, object]:
    issues = issues_from_exception(exc, source=source)
    return {"verified": False, "reason": reason, "error": str(exc), **extra, "structuredIssues": serialize_issues(issues)}


def _validate_schema(payload: object, schema: object, path: str, issues: list[DiagnosticIssue]) -> None:
    if isinstance(schema, dict):
        if not isinstance(payload, dict):
            issues.append(_issue("invalid_type", path or "payload", "object", payload, "Expected object"))
            return
        for key, child_schema in schema.items():
            child_path = f"{path}.{key}" if path else str(key)
            if key not in payload:
                issues.append(_issue("missing_required_key", child_path, "present", None, f"Missing required key {child_path}"))
                continue
            _validate_schema(payload[key], child_schema, child_path, issues)
        return
    if not isinstance(schema, str):
        issues.append(_issue("invalid_type", path, "schema rule string", schema, "Parse schema rule must be a string"))
        return
    rule = schema.strip()
    if rule == "integer":
        if not (isinstance(payload, int) and not isinstance(payload, bool)):
            issues.append(_issue("invalid_type", path, "integer", payload, f"{path} must be an integer"))
        return
    if rule == "true|false":
        if not isinstance(payload, bool):
            issues.append(_issue("invalid_type", path, "boolean", payload, f"{path} must be true or false"))
        return
    if rule == "path or null":
        if not (payload is None or (isinstance(payload, str) and bool(payload.strip()))):
            issues.append(_issue("invalid_value", path, "path string or null", payload, f"{path} must be a path string or null"))
        return
    if "|" in rule and " " not in rule:
        allowed = rule.split("|")
        if not isinstance(payload, str) or payload not in allowed:
            issues.append(_issue("invalid_enum", path, allowed, payload, f"{path} must be one of {', '.join(allowed)}"))
        return
    if not isinstance(payload, str) or not payload.strip():
        issues.append(_issue("empty_string", path, "non-empty string", payload, f"{path} must be a non-empty string"))


def _validate_schema_contract(schema: object, path: str, issues: list[DiagnosticIssue]) -> None:
    if isinstance(schema, dict):
        for key, child_schema in schema.items():
            child_path = f"{path}.{key}" if path else str(key)
            _validate_schema_contract(child_schema, child_path, issues)
        return
    if isinstance(schema, str) and schema.strip():
        return
    issues.append(_issue("invalid_type", path, "schema rule string or object", schema, "Parse schema leaf must be a non-empty string", source="parse-contract"))


def _issue(
    issue_type: str,
    field: str,
    expected: Any,
    actual: Any,
    message: str,
    *,
    source: str = "parse-output",
) -> DiagnosticIssue:
    return DiagnosticIssue(
        type=issue_type,
        field=field,
        expected=expected,
        actual=actual,
        message=message,
        recovery="Return JSON that matches the parse contract schema.",
        code=f"PARSE_{issue_type.upper()}",
        source=source,
    )
