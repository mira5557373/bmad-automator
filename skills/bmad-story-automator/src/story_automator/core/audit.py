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
import json as _json
import os
import pathlib
from typing import Any, Iterator, Mapping, Protocol, runtime_checkable

import filelock

from .common import compact_json, ensure_dir, iso_now


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


_TAIL_CHUNK = 4096


def _scan_last_line(handle: Any, size: int) -> bytes | None:
    """Return the last non-blank line in an open binary handle, or ``None``.

    Reads backwards from ``size`` in 4 KiB chunks. The handle's file pointer
    is left at an unspecified position; callers that intend to write
    afterwards should rely on the OS's append-mode semantics, not the
    pointer.
    """
    if size == 0:
        return None
    pos = size
    buf = b""
    while pos > 0:
        read_size = min(_TAIL_CHUNK, pos)
        pos -= read_size
        handle.seek(pos)
        buf = handle.read(read_size) + buf
        stripped = buf.rstrip(b"\r\n")
        if not stripped:
            if pos == 0:
                return None
            continue
        nl = stripped.rfind(b"\n")
        if nl >= 0:
            return stripped[nl + 1 :]
        if pos == 0:
            return stripped
    return None


def _read_last_record(path: pathlib.Path) -> dict[str, Any] | None:
    """Return the last parsed JSON record in ``path``, or ``None``.

    Opens read-only, seeks to the end, then delegates to ``_scan_last_line``
    to isolate the trailing record without re-streaming the whole file.
    Returns ``None`` when the file does not exist, is empty, or contains
    only blank lines. Malformed JSON on the last non-blank line raises
    ``json.JSONDecodeError`` — the append path treats that as a fatal
    corruption signal and propagates it.
    """
    if not path.exists():
        return None
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        last_line = _scan_last_line(handle, handle.tell())
    if last_line is None:
        return None
    return _json.loads(last_line.decode("utf-8"))


def _iter_record_lines(handle: Any) -> "Iterator[bytes]":
    """Yield each non-blank line from an open binary file handle, in order.

    The handle is consumed lazily: only one line is held in memory at a
    time. Trailing or interior blank lines are skipped. The caller is
    responsible for keeping the handle open across iteration; closing
    it mid-loop raises ``ValueError`` from the underlying read.
    """
    for raw in handle:
        line = raw.rstrip(b"\r\n")
        if not line:
            continue
        yield line


_REQUIRED_RECORD_FIELDS = ("seq", "ts", "event", "payload", "tag")


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
    key: bytes = dataclasses.field(repr=False)
    _lock_path: pathlib.Path = dataclasses.field(default=None, repr=False)  # type: ignore[assignment]
    _lock: filelock.FileLock = dataclasses.field(default=None, init=False, repr=False)  # type: ignore[assignment]
    # Last record we successfully appended, alongside the file size at that
    # moment. On the next append we re-stat the file; if the size is
    # unchanged the cache is still authoritative and we skip the disk
    # re-read. If the size changed, another writer must have appended
    # between our calls, so we fall back to streaming the tail from disk.
    # The lock guarantees no concurrent in-process writer; cross-process
    # safety is enforced by the size check.
    _cached_seq: int | None = dataclasses.field(default=None, init=False, repr=False)
    _cached_tag: str | None = dataclasses.field(default=None, init=False, repr=False)
    _cached_size: int | None = dataclasses.field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self._lock_path is None:
            self._lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        # Pre-create parent directories once. Append paths assume the dirs
        # exist; re-checking on every call costs ~50 us on Windows and adds
        # nothing — the lock guarantees we are the only writer.
        ensure_dir(self.path.parent)
        ensure_dir(self._lock_path.parent)
        # Reuse the same FileLock instance across appends. filelock is
        # designed for reuse and skips re-opening its underlying lock fd
        # on subsequent acquires, which trims per-append latency.
        self._lock = filelock.FileLock(str(self._lock_path))

    def append(self, event: Event) -> None:
        """Append one record to the chain, computing the tag and bumping seq.

        ``event`` is duck-typed: any object with ``event_name`` and
        ``to_dict()`` works. The serialised line is:

            {"seq": N, "ts": ISO, "event": NAME, "payload": {...}, "tag": HEX}

        followed by a single ``\\n``. All filesystem mutation is performed
        under the per-log ``filelock.FileLock`` acquired with a 5-second
        timeout — on timeout this method raises ``AuditLockTimeout``.
        """
        try:
            self._lock.acquire(timeout=5)
        except filelock.Timeout as exc:
            raise AuditLockTimeout(
                f"could not acquire audit lock within 5s: {self._lock_path}"
            ) from exc

        try:
            # Two separate opens (rb for tail-read, ab for append) are cheaper
            # than one "a+b" open on Windows by an order of magnitude: read-or-
            # write mode triggers extra FS setup costs.
            try:
                current_size = self.path.stat().st_size
            except FileNotFoundError:
                current_size = 0

            if (
                self._cached_size is not None
                and current_size == self._cached_size
                and self._cached_seq is not None
            ):
                # File untouched since our last write — trust the in-memory
                # state and skip the disk re-read. fsync invalidates Windows'
                # page cache, so re-reading would force a real disk hit each
                # call (~5 ms) and blow the 500 ms NFR.
                seq = self._cached_seq + 1
                prev_tag_hex: str | None = self._cached_tag
            elif current_size == 0:
                seq = 1
                prev_tag_hex = None
            else:
                prev = _read_last_record(self.path)
                if prev is None:
                    seq = 1
                    prev_tag_hex = None
                else:
                    seq = int(prev["seq"]) + 1
                    prev_tag_hex = prev["tag"]

            ts = iso_now()
            event_name = event.event_name
            payload = event.to_dict()
            canonical = _canonical_record_bytes(
                seq=seq, ts=ts, event=event_name, payload=payload
            )
            tag = _compute_tag(
                key=self.key, prev_tag_hex=prev_tag_hex, canonical=canonical
            )
            record = {
                "seq": seq,
                "ts": ts,
                "event": event_name,
                "payload": payload,
                "tag": tag,
            }
            line = compact_json(record) + "\n"
            line_bytes = line.encode("utf-8")

            with self.path.open("ab") as handle:
                handle.write(line_bytes)
                handle.flush()
                os.fsync(handle.fileno())

            self._cached_seq = seq
            self._cached_tag = tag
            self._cached_size = current_size + len(line_bytes)
        finally:
            self._lock.release()

    def verify(self) -> tuple[bool, int]:
        """Walk the log and recompute every chain tag.

        Returns ``(True, last_seq)`` when the chain is intact, or
        ``(False, last_valid_seq)`` on the first detected anomaly:
        malformed JSON, missing field, non-contiguous seq, or tag
        mismatch. Returns ``(True, 0)`` when the log file does not
        exist or is empty (REQ-09). Streams the file line by line and
        never buffers more than one record at a time.
        """
        if not self.path.exists():
            return (True, 0)

        last_valid_seq = 0
        prev_tag_hex: str | None = None
        with self.path.open("rb") as handle:
            for raw_line in _iter_record_lines(handle):
                try:
                    record = _json.loads(raw_line.decode("utf-8"))
                except (_json.JSONDecodeError, UnicodeDecodeError):
                    # Tampered/corrupted lines may contain non-UTF8 bytes.
                    # REQ-08 treats both as "malformed JSON" — return rather
                    # than letting UnicodeDecodeError escape the contract.
                    return (False, last_valid_seq)
                if not isinstance(record, dict):
                    return (False, last_valid_seq)
                for field in _REQUIRED_RECORD_FIELDS:
                    if field not in record:
                        return (False, last_valid_seq)
                seq = record["seq"]
                if (
                    not isinstance(seq, int)
                    or isinstance(seq, bool)
                    or seq != last_valid_seq + 1
                ):
                    return (False, last_valid_seq)
                canonical = _canonical_record_bytes(
                    seq=seq,
                    ts=record["ts"],
                    event=record["event"],
                    payload=record["payload"],
                )
                expected_tag = _compute_tag(
                    key=self.key,
                    prev_tag_hex=prev_tag_hex,
                    canonical=canonical,
                )
                tag_value = record["tag"]
                if not isinstance(tag_value, str) or len(tag_value) != 64:
                    return (False, last_valid_seq)
                if not hmac.compare_digest(expected_tag, tag_value):
                    return (False, last_valid_seq)
                last_valid_seq = seq
                prev_tag_hex = tag_value
        return (True, last_valid_seq)
