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


def _osv_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return ["osv-scanner", "scan", "--recursive", "."]


def _gitleaks_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return ["gitleaks", "detect", "--source", ".", "--no-banner"]


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

OSV = CollectorConfig(
    collector_id="osv-security",
    tool="osv-scanner",
    category="security",
    build_cmd=_osv_cmd,
    tool_version_cmd=("osv-scanner", "--version"),
    file_patterns=frozenset({"*.lock", "*.txt", "*.toml", "*.cfg", "package.json"}),
)

GITLEAKS = CollectorConfig(
    collector_id="gitleaks-security",
    tool="gitleaks",
    category="security",
    build_cmd=_gitleaks_cmd,
    tool_version_cmd=("gitleaks", "version"),
    file_patterns=frozenset(),
)

COLLECTORS: list[CollectorConfig] = [SEMGREP, TRIVY_VULN, OSV, GITLEAKS]
