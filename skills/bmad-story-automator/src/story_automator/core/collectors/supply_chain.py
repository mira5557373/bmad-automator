"""Supply-chain-category evidence collectors (§6.2).

PASS rule: SBOM emitted, deps signed/pinned, provenance present.
Collectors: sbom-supply_chain, cosign-supply_chain, provenance-supply_chain,
            trivy-sbom-supply_chain.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from ..collector_config import CollectorConfig

_CHECKS_DIR = Path(__file__).resolve().parent.parent / "checks"

_DEFAULT_PROVENANCE_FILES = [
    ".slsa/provenance.json",
    "provenance.intoto.jsonl",
]


def _sbom_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("supply_chain") or {}
    fmt = rules.get("sbom_format", "spdx-json")
    return [
        sys.executable,
        str(_CHECKS_DIR / "sbom_check.py"),
        checkout,
        fmt,
    ]


def _cosign_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("supply_chain") or {}
    bundle = rules.get("cosign_bundle", "cosign.bundle")
    artifact = rules.get("cosign_artifact", "sbom.json")
    return ["cosign", "verify-blob", "--bundle", bundle, artifact]


def _provenance_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("supply_chain") or {}
    files = rules.get("provenance_files", _DEFAULT_PROVENANCE_FILES)
    return [
        sys.executable,
        str(_CHECKS_DIR / "presence_check.py"),
        checkout,
        json.dumps(files),
    ]


def _trivy_sbom_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("supply_chain") or {}
    severity = rules.get("trivy_severity", "HIGH,CRITICAL")
    return [
        "trivy", "sbom",
        "--exit-code", "1",
        "--severity", severity,
        ".",
    ]


SBOM = CollectorConfig(
    collector_id="sbom-supply_chain",
    tool="python3",
    category="supply_chain",
    build_cmd=_sbom_cmd,
    file_patterns=frozenset({"*.lock", "*.txt", "*.toml", "*.cfg", "package.json"}),
)

COSIGN = CollectorConfig(
    collector_id="cosign-supply_chain",
    tool="cosign",
    category="supply_chain",
    build_cmd=_cosign_cmd,
    tool_version_cmd=("cosign", "version"),
    file_patterns=frozenset(),
)

PROVENANCE = CollectorConfig(
    collector_id="provenance-supply_chain",
    tool="python3",
    category="supply_chain",
    build_cmd=_provenance_cmd,
    file_patterns=frozenset(),
)

TRIVY_SBOM = CollectorConfig(
    collector_id="trivy-sbom-supply_chain",
    tool="trivy",
    category="supply_chain",
    build_cmd=_trivy_sbom_cmd,
    tool_version_cmd=("trivy", "--version"),
    file_patterns=frozenset(),
)

COLLECTORS: list[CollectorConfig] = [SBOM, COSIGN, PROVENANCE, TRIVY_SBOM]
