"""API-compatibility-category evidence collectors (§6.2).

PASS rule: no breaking REST/schema change; audit-log additive-only.
Collectors: openapi-diff-api_compat, schema-diff-api_compat.
"""
from __future__ import annotations

from typing import Any

from ..collector_config import CollectorConfig


def _openapi_diff_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("api_compat") or {}
    base = rules.get("openapi_base", "openapi-base.yaml")
    revision = rules.get("openapi_revision", "openapi.yaml")
    return ["oasdiff", "breaking", base, revision]


def _schema_diff_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("api_compat") or {}
    base = rules.get("schema_base", "openapi-base.yaml")
    revision = rules.get("schema_revision", "openapi.yaml")
    return ["oasdiff", "diff", base, revision, "--fail-on", "ERR"]


OPENAPI_DIFF = CollectorConfig(
    collector_id="openapi-diff-api_compat",
    tool="oasdiff",
    category="api_compat",
    build_cmd=_openapi_diff_cmd,
    tool_version_cmd=("oasdiff", "version"),
    file_patterns=frozenset({"*.yaml", "*.yml", "*.json"}),
)

SCHEMA_DIFF = CollectorConfig(
    collector_id="schema-diff-api_compat",
    tool="oasdiff",
    category="api_compat",
    build_cmd=_schema_diff_cmd,
    tool_version_cmd=("oasdiff", "version"),
    file_patterns=frozenset({"*.yaml", "*.yml", "*.json"}),
)

COLLECTORS: list[CollectorConfig] = [OPENAPI_DIFF, SCHEMA_DIFF]
