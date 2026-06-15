from __future__ import annotations

from pathlib import Path

__all__ = ["AtomicWriteRetryExhausted", "write_atomic_text"]


class AtomicWriteRetryExhausted(PermissionError):
    """Raised when os.replace retries are exhausted on Windows.

    Subclasses PermissionError so REQ-04's "raise the final PermissionError"
    contract is satisfied while still being a TYPED exception per the
    observability NFR (later M02 telemetry wiring can classify it by type
    rather than string-match). PermissionError is itself a subclass of
    OSError, so callers that already handle OSError keep working.
    """


def write_atomic_text(path: Path, data: str, *, encoding: str = "utf-8") -> None:
    raise NotImplementedError
