"""Audit-trail subsystem.

Append-only, hash-chained JSONL audit log for high-value operational events.
This module is the M04 foundations slice: it ships only the key-derivation
surface and module-level exception classes. The ``AuditLog`` dataclass,
``append``, ``verify``, and ``audit_for_policy`` arrive in later milestones.
"""

from __future__ import annotations


__all__ = [
    "AuditKeyMissing",  # noqa: F822 - defined later this milestone
    "AuditLockTimeout",  # noqa: F822 - defined later this milestone
    "derive_key",  # noqa: F822 - defined later this milestone
    "load_key_from_env",  # noqa: F822 - defined later this milestone
]
