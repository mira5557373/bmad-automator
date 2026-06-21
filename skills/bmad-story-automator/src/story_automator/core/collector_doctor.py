"""Collector preflight checks — verify tool availability before gate runs.

Checks that each applicable collector's binary is available via
shutil.which and optionally retrieves version info.
"""
from __future__ import annotations

import dataclasses
import shutil
import subprocess
from typing import Any

from .collector_config import CollectorConfig
from .collector_registry import CollectorRegistry

__all__ = [
    "DoctorResult",
    "check_collector_available",
    "preflight_check",
]

_VERSION_TIMEOUT = 10


@dataclasses.dataclass(frozen=True)
class DoctorResult:
    """Result of a single tool availability check."""

    tool: str
    available: bool
    version: str
    message: str


def check_collector_available(config: CollectorConfig) -> DoctorResult:
    """Check if a collector's tool binary is available in PATH."""
    if not shutil.which(config.tool):
        return DoctorResult(
            tool=config.tool,
            available=False,
            version="",
            message=f"{config.tool} not found in PATH",
        )
    version = ""
    if config.tool_version_cmd:
        version = _get_tool_version(config.tool_version_cmd)
    return DoctorResult(
        tool=config.tool,
        available=True,
        version=version,
        message="ok",
    )


def _get_tool_version(cmd: tuple[str, ...]) -> str:
    """Best-effort version string extraction."""
    try:
        result = subprocess.run(
            list(cmd),
            capture_output=True,
            text=True,
            timeout=_VERSION_TIMEOUT,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().split("\n")[0]
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return ""


def preflight_check(
    registry: CollectorRegistry,
    profile: dict[str, Any],
) -> tuple[bool, list[DoctorResult]]:
    """Run preflight checks for all applicable collectors.

    Returns (all_ok, list_of_results).  Skips collectors not
    applicable to the given profile.
    """
    applicable = registry.applicable(profile)
    results = [check_collector_available(c) for c in applicable]
    all_ok = all(r.available for r in results)
    return all_ok, results
