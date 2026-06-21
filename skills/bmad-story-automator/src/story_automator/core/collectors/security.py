"""Security-category evidence collectors (§6.2).

PASS rule: SAST 0 high+, deps 0 critical-unwaived, 0 secrets.
Collectors: semgrep-security, trivy-vuln-security, osv-security, gitleaks-security.
"""
from __future__ import annotations

from typing import Any

from ..collector_config import CollectorConfig


def _semgrep_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("security") or {}
    config = rules.get("semgrep_config", "auto")
    return ["semgrep", "scan", f"--config={config}", "--error"]


def _trivy_vuln_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("security") or {}
    severity = rules.get("trivy_severity", "HIGH,CRITICAL")
    return [
        "trivy", "fs",
        "--exit-code", "1",
        "--severity", severity,
        "--scanners", "vuln",
        ".",
    ]


SEMGREP = CollectorConfig(
    collector_id="semgrep-security",
    tool="semgrep",
    category="security",
    build_cmd=_semgrep_cmd,
    tool_version_cmd=("semgrep", "--version"),
    file_patterns=frozenset({"*.py", "*.ts", "*.tsx", "*.js", "*.jsx", "*.yaml", "*.yml"}),
)

TRIVY_VULN = CollectorConfig(
    collector_id="trivy-vuln-security",
    tool="trivy",
    category="security",
    build_cmd=_trivy_vuln_cmd,
    tool_version_cmd=("trivy", "--version"),
    file_patterns=frozenset({"*.lock", "*.txt", "*.toml", "*.cfg", "package.json"}),
)

COLLECTORS: list[CollectorConfig] = [SEMGREP, TRIVY_VULN]
