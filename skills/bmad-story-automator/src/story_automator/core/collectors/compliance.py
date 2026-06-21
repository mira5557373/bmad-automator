"""Compliance-category evidence collectors (§6.2).

PASS rule: compliance rulepack checks pass (PII-redaction, residency,
audit-envelope, consent-receipt present and correct).
Collectors: compliance-rules-compliance, conftest-compliance.
"""
from __future__ import annotations

from typing import Any

from ..collector_config import CollectorConfig


def _compliance_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("compliance") or {}
    rulepack = rules.get("rulepack_dir", "")
    config = rulepack if rulepack else "auto"
    return ["semgrep", "scan", f"--config={config}", "--error"]


def _conftest_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("compliance") or {}
    policy_dir = rules.get("conftest_policy_dir", "policy")
    return ["conftest", "test", "--policy", policy_dir, "."]


COMPLIANCE_RULES = CollectorConfig(
    collector_id="compliance-rules-compliance",
    tool="semgrep",
    category="compliance",
    build_cmd=_compliance_cmd,
    tool_version_cmd=("semgrep", "--version"),
    file_patterns=frozenset({"*.py", "*.ts", "*.tsx", "*.js", "*.jsx", "*.yaml", "*.yml"}),
)

CONFTEST = CollectorConfig(
    collector_id="conftest-compliance",
    tool="conftest",
    category="compliance",
    build_cmd=_conftest_cmd,
    tool_version_cmd=("conftest", "--version"),
    file_patterns=frozenset({"*.yaml", "*.yml", "*.json", "*.tf", "*.hcl"}),
)

COLLECTORS: list[CollectorConfig] = [COMPLIANCE_RULES, CONFTEST]
