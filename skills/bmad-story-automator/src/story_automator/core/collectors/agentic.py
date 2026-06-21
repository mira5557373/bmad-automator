"""Agentic-category evidence collectors (§6.2).

PASS rule (if touched): (a) pack-schema v1.2 valid, (b) AIBOM entries present,
(c) OPA constitution compiles + tests pass, (d) evals >= threshold,
(e) guardrail configuration present.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from ..collector_config import CollectorConfig

_CHECKS_DIR = Path(__file__).resolve().parent.parent / "checks"

_DEFAULT_GUARDRAIL_FILES = ["guardrails.yaml", "guardrails.json"]


def _pack_schema_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("agentic") or {}
    cmd = [
        sys.executable,
        str(_CHECKS_DIR / "pack_schema_check.py"),
        checkout,
    ]
    tools_dir = rules.get("tools_dir")
    if tools_dir:
        cmd.append(tools_dir)
    return cmd


def _aibom_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("agentic") or {}
    cmd = [
        sys.executable,
        str(_CHECKS_DIR / "aibom_check.py"),
        checkout,
    ]
    aibom_path = rules.get("aibom_path")
    if aibom_path:
        cmd.append(aibom_path)
    return cmd


def _opa_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("agentic") or {}
    policy_dir = rules.get("policy_dir", "policy")
    return [
        sys.executable,
        str(_CHECKS_DIR / "opa_check.py"),
        checkout,
        policy_dir,
    ]


def _evals_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("agentic") or {}
    custom_cmd = rules.get("eval_cmd")
    if custom_cmd and isinstance(custom_cmd, list):
        return custom_cmd
    return ["deepeval", "test", "run"]


def _guardrail_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("agentic") or {}
    files = rules.get("guardrail_files", _DEFAULT_GUARDRAIL_FILES)
    return [
        sys.executable,
        str(_CHECKS_DIR / "presence_check.py"),
        checkout,
        json.dumps(files),
    ]


PACK_SCHEMA = CollectorConfig(
    collector_id="pack-schema-agentic",
    tool="python3",
    category="agentic",
    build_cmd=_pack_schema_cmd,
    file_patterns=frozenset({"*.json", "*.yaml", "*.yml"}),
)

AIBOM_DIFF = CollectorConfig(
    collector_id="aibom-diff-agentic",
    tool="python3",
    category="agentic",
    build_cmd=_aibom_cmd,
    file_patterns=frozenset({"*.json", "*.yaml", "*.yml"}),
)

OPA = CollectorConfig(
    collector_id="opa-agentic",
    tool="python3",
    category="agentic",
    build_cmd=_opa_cmd,
    file_patterns=frozenset({"*.rego"}),
)

EVALS = CollectorConfig(
    collector_id="evals-agentic",
    tool="deepeval",
    category="agentic",
    build_cmd=_evals_cmd,
    tool_version_cmd=("deepeval", "--version"),
    file_patterns=frozenset({"*.py", "*.ts", "*.yaml"}),
    deterministic=False,
)

GUARDRAIL = CollectorConfig(
    collector_id="guardrail-agentic",
    tool="python3",
    category="agentic",
    build_cmd=_guardrail_cmd,
    file_patterns=frozenset({"*.yaml", "*.yml", "*.json"}),
)

COLLECTORS: list[CollectorConfig] = [
    PACK_SCHEMA, AIBOM_DIFF, OPA, EVALS, GUARDRAIL,
]
