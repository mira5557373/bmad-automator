"""Shared audit-hook plumbing for the command modules.

Lives as a leaf module under ``commands/`` so that both ``orchestrator``
and ``orchestrator_epic_agents`` can import from it without creating
an import cycle (``orchestrator`` already imports from
``orchestrator_epic_agents``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from ..core.audit import Event as _AuditEvent, audit_for_policy


def _audit_path_for(project_root: str | Path) -> Path:
    """Return the conventional audit-log path under a project root.

    The audit subsystem writes a single per-project JSONL log at
    ``<project_root>/_bmad/audit/audit.jsonl``. The directory is created
    lazily by ``AuditLog`` on the first append — callers must not
    pre-create it (REQ-14 forbids any filesystem I/O when the gate is
    off).
    """
    return Path(project_root) / "_bmad" / "audit" / "audit.jsonl"


def _maybe_audit_event(
    policy: Mapping[str, Any], audit_path: Path, event: _AuditEvent
) -> None:
    """Append ``event`` to the audit chain when the policy gate is on.

    No-op when ``audit_for_policy`` returns ``None`` — single dict lookup,
    zero I/O (REQ-14). Errors from ``AuditLog.append`` propagate; callers
    that need a failure-tolerant path must wrap explicitly.
    """
    log = audit_for_policy(policy, audit_path)
    if log is None:
        return
    log.append(event)
