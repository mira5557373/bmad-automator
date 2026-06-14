"""Audit-trail subsystem.

Append-only, hash-chained JSONL audit log for high-value operational events.
This module is the M04 foundations slice: it ships only the key-derivation
surface and module-level exception classes. The ``AuditLog`` dataclass,
``append``, ``verify``, and ``audit_for_policy`` arrive in later milestones.
"""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import os
import pathlib
from typing import Any, Mapping, Protocol, runtime_checkable

from .common import compact_json


__all__ = [
    "AuditKeyMissing",
    "AuditLockTimeout",
    "AuditLog",
    "derive_key",
    "load_key_from_env",
]


class AuditLockTimeout(RuntimeError):
    """Raised when ``AuditLog.append`` cannot acquire the per-log file lock.

    The lock timeout is fixed at 5 seconds per REQ-07a. Catching this exception
    indicates contention or a stale lock file — never a programming error in
    the caller's payload. The message must not include the audit key.
    """


class AuditKeyMissing(RuntimeError):
    """Raised by ``audit_for_policy`` when the policy enables audit but no key is loadable.

    The runtime contract per REQ-10: if ``security.audit_trail`` is truthy and
    ``load_key_from_env()`` returns ``None``, callers refusing to open an unkeyed
    log raise this exception. The message must not include the audit key.
    """


def _hkdf_extract(salt: bytes, ikm: bytes) -> bytes:
    """RFC 5869 HKDF-Extract step using HMAC-SHA256.

    Returns the 32-byte pseudo-random key (PRK). Empty salt is treated as a
    zero-length HMAC key, matching Python's ``hmac`` semantics.
    """
    return hmac.new(salt, ikm, hashlib.sha256).digest()


def _hkdf_expand(prk: bytes, info: bytes, length: int) -> bytes:
    """RFC 5869 HKDF-Expand step using HMAC-SHA256.

    Produces ``length`` bytes of output keying material (OKM) by chaining
    HMAC blocks. Raises ``ValueError`` if ``length`` exceeds the RFC ceiling
    of 255 * 32 = 8160 bytes.
    """
    if length > 255 * hashlib.sha256().digest_size:
        raise ValueError("hkdf expand length exceeds 255 * hashlen")
    out = bytearray()
    previous = b""
    counter = 1
    while len(out) < length:
        previous = hmac.new(
            prk, previous + info + bytes([counter]), hashlib.sha256
        ).digest()
        out.extend(previous)
        counter += 1
    return bytes(out[:length])


_HKDF_DEFAULT_SALT = b"bmad-audit-v1"
_HKDF_INFO = b"audit-chain"
_KEY_LENGTH = 32


def derive_key(secret: str, *, salt: bytes = _HKDF_DEFAULT_SALT) -> bytes:
    """Derive a 32-byte audit-chain key from ``secret`` via RFC 5869 HKDF-SHA256.

    Uses ``salt`` as the HKDF salt (default ``b"bmad-audit-v1"``) and the
    fixed ``info`` value ``b"audit-chain"``. Implementation is hand-rolled on
    top of ``hmac`` + ``hashlib.sha256``; ``hashlib.pbkdf2_hmac`` is forbidden
    here per REQ-03. The returned bytes are the raw key material — never log
    or include them in repr / exception messages.
    """
    prk = _hkdf_extract(salt, secret.encode("utf-8"))
    return _hkdf_expand(prk, _HKDF_INFO, _KEY_LENGTH)


_ENV_VAR = "BMAD_AUDIT_KEY"


def load_key_from_env(env: Mapping[str, str] | None = None) -> bytes | None:
    """Return a derived audit key from the ``BMAD_AUDIT_KEY`` environment variable.

    Reads from ``env`` when provided, otherwise from ``os.environ``. Returns
    ``None`` when the variable is unset or empty — this function must never
    raise on a missing variable per REQ-04. The raw env value is consumed
    only inside ``derive_key`` and is never logged, repr'd, or included in
    error output anywhere in this module.
    """
    source: Mapping[str, str] = env if env is not None else os.environ
    raw = source.get(_ENV_VAR, "")
    if not raw:
        return None
    return derive_key(raw)


@runtime_checkable
class Event(Protocol):
    """Structural interface that ``AuditLog.append`` requires.

    The audit module never imports the concrete telemetry-events module; any
    object exposing ``event_name`` (a string class identifier) and
    ``to_dict()`` (a JSON-serialisable mapping) is acceptable. Documenting
    the contract here keeps the call-site integrations forward-compatible
    with the telemetry refactor that ships in a later milestone.
    """

    event_name: str

    def to_dict(self) -> Mapping[str, Any]: ...


def _canonical_record_bytes(
    *, seq: int, ts: str, event: str, payload: Mapping[str, Any]
) -> bytes:
    """Return the canonical byte representation hashed into ``tag``.

    The canonical form is ``compact_json({"seq","ts","event","payload"})``
    encoded as UTF-8, with the field order fixed to ``seq, ts, event,
    payload``. The ``tag`` field is intentionally excluded — including it
    would create a cyclic dependency between the record's contents and its
    own integrity tag.
    """
    return compact_json(
        {"seq": seq, "ts": ts, "event": event, "payload": payload}
    ).encode("utf-8")


_ZERO_TAG = b"\x00" * 32


def _compute_tag(*, key: bytes, prev_tag_hex: str | None, canonical: bytes) -> str:
    """Return the lowercase hex HMAC-SHA256 chain tag for one record.

    ``prev_tag_hex`` is the hex tag of the previous record, or ``None`` when
    appending seq=1 (in which case 32 zero bytes are prepended). The HMAC
    input is ``prev_tag_bytes + canonical_record_bytes`` per REQ-07.

    The key bytes are passed straight to ``hmac.new`` and never logged.
    """
    prev_bytes = _ZERO_TAG if prev_tag_hex is None else bytes.fromhex(prev_tag_hex)
    return hmac.new(key, prev_bytes + canonical, hashlib.sha256).hexdigest()


@dataclasses.dataclass(kw_only=True)
class AuditLog:
    """Append-only, hash-chained JSONL audit log.

    Fields:
      - ``path``: target JSONL file (one record per line).
      - ``key``: 32-byte HMAC-SHA256 chain key (typically from ``derive_key``).
      - ``_lock_path``: per-log advisory lock file. Defaults to
        ``path.with_suffix(path.suffix + ".lock")``; override only for tests.

    The dataclass is ``kw_only`` to keep call sites readable and to prevent
    accidental positional swaps of ``path`` and ``key`` (one a path, the other
    raw secret bytes).
    """

    path: pathlib.Path
    key: bytes
    _lock_path: pathlib.Path = dataclasses.field(default=None)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self._lock_path is None:
            self._lock_path = self.path.with_suffix(self.path.suffix + ".lock")
