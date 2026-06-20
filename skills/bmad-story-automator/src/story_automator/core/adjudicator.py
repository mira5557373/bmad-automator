"""Adjudicator — timeout-enforced collector runner and verdict engine (§6.4, §7).

Runs evidence collectors via subprocess.run(timeout=...) with psutil
SIGKILL on expiry.  Timed-out collectors emit {status: timeout}.
The adjudicator treats timeout/error as fail-closed (§6.3).

GateDecision / GateRendered telemetry events land in their own milestone;
ride UnknownEvent forward-compat until then (§14).

Artifacts live under _bmad/gate/{risk,evidence,verdicts}/ (§14).
"""
from __future__ import annotations

import subprocess
import time
from typing import Any

from .gate_schema import (
    make_evidence_record,
    make_timeout_evidence,
)
from .product_profile import (
    DEFAULT_TIMEOUT_FALLBACK,
    DEFAULT_TIMEOUTS,
)


def resolve_timeout(profile: dict[str, Any], category: str) -> int:
    """Resolve per-category timeout from profile, falling back to defaults."""
    profile_timeouts = profile.get("timeouts") or {}
    if category in profile_timeouts:
        return int(profile_timeouts[category])
    return DEFAULT_TIMEOUTS.get(category, DEFAULT_TIMEOUT_FALLBACK)


def run_collector_with_timeout(
    cmd: list[str],
    *,
    collector: str,
    tool: str,
    category: str,
    timeout_s: int,
    cwd: str | None = None,
    tool_version: str = "",
) -> dict[str, Any]:
    """Run a collector subprocess with timeout + psutil SIGKILL on expiry.

    Uses Popen so we can get the pid for psutil tree-killing.
    §6.4: timed-out collector emits {status: timeout,
           findings: ['TIMEOUT: <tool> exceeded <N>s']}.
    §6.4: adjudicator treats timeout as error for aggregation (fail-closed).
    """
    if not cmd:
        return make_evidence_record(
            collector=collector,
            tool=tool,
            tool_version=tool_version,
            category=category,
            status="error",
            findings=["collector command is empty"],
            exit_code=127,
            duration_ms=0,
        )
    start_ms = _monotonic_ms()
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
        )
    except FileNotFoundError:
        duration_ms = _monotonic_ms() - start_ms
        return make_evidence_record(
            collector=collector,
            tool=tool,
            tool_version=tool_version,
            category=category,
            status="error",
            findings=[f"collector binary not found: {cmd[0]}"],
            exit_code=127,
            duration_ms=duration_ms,
        )
    try:
        stdout, _ = proc.communicate(timeout=timeout_s)
        duration_ms = _monotonic_ms() - start_ms
        status = "ok" if proc.returncode == 0 else "violation"
        findings = _extract_findings(stdout) if status == "violation" else []
        return make_evidence_record(
            collector=collector,
            tool=tool,
            tool_version=tool_version,
            category=category,
            status=status,
            findings=findings,
            exit_code=proc.returncode,
            duration_ms=duration_ms,
        )
    except subprocess.TimeoutExpired:
        _kill_process_tree(proc.pid)
        proc.kill()
        proc.wait()
        return make_timeout_evidence(collector, tool, category, timeout_s)
    except OSError:
        _safe_kill(proc)
        duration_ms = _monotonic_ms() - start_ms
        return make_evidence_record(
            collector=collector,
            tool=tool,
            tool_version=tool_version,
            category=category,
            status="error",
            findings=[f"collector I/O error: {cmd[0]}"],
            exit_code=-1,
            duration_ms=duration_ms,
        )


def _kill_process_tree(pid: int) -> None:
    """Best-effort psutil SIGKILL of child processes on timeout expiry."""
    try:
        import psutil
    except ImportError:
        return
    try:
        parent = psutil.Process(pid)
        for child in parent.children(recursive=True):
            child.kill()
    except (psutil.NoSuchProcess, psutil.AccessDenied, ProcessLookupError):
        pass


def _safe_kill(proc: subprocess.Popen[str]) -> None:
    """Best-effort cleanup of a Popen process after an unexpected error."""
    try:
        proc.kill()
        proc.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _monotonic_ms() -> int:
    return int(time.monotonic() * 1000)


def _extract_findings(output: str) -> list[str]:
    """Extract first few non-empty lines as findings summary."""
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return lines[:20]
