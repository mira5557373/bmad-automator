"""Audit-trail subsystem.

Append-only, hash-chained JSONL audit log for high-value operational events.
This module is the M04 foundations slice: it ships only the key-derivation
surface and module-level exception classes. The ``AuditLog`` dataclass,
``append``, ``verify``, and ``audit_for_policy`` arrive in later milestones.
"""

from __future__ import annotations


__all__ = [
    "AuditKeyMissing",  # noqa: F822 - defined later this milestone
    "AuditLockTimeout",
    "derive_key",  # noqa: F822 - defined later this milestone
    "load_key_from_env",  # noqa: F822 - defined later this milestone
]


class AuditLockTimeout(RuntimeError):
    """Raised when ``AuditLog.append`` cannot acquire the per-log file lock.

    The lock timeout is fixed at 5 seconds per REQ-07a. Catching this exception
    indicates contention or a stale lock file — never a programming error in
    the caller's payload. The message must not include the audit key.
    """
