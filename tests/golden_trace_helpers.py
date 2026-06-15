"""Golden-trace data types and pure helpers (M10a wedge).

The recorder, interception hooks, fixtures, and redaction layer land in
later M10 sub-milestones. Importing this module must produce no telemetry
events, no state mutations, and no claude_p invocations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Channel = Literal["event", "state", "claude_p"]
MismatchField = Literal["channel", "kind", "payload", "length"]

__all__ = [
    "Channel",
    "GoldenTraceError",
    "MismatchField",
    "TraceDiff",
    "TraceEntry",
    "TraceMismatch",
    "compare_traces",
    "load_golden",
    "serialize_trace",
]


class GoldenTraceError(ValueError):
    """Raised when a stored golden fixture is malformed or carries unknown channels."""


# Stubs — concrete implementations land in later tasks.
@dataclass(kw_only=True, frozen=True)
class TraceEntry:
    """One arrival-ordered observation recorded by the golden-trace recorder.

    `payload` is a JSON-object dict whose key ordering is canonicalized at
    serialize time (REQ-07 uses sort_keys=True), so callers do not need to
    pre-sort payloads to get byte-identical traces.
    """

    seq: int
    channel: Channel
    kind: str
    payload: dict[str, object]


class TraceMismatch:  # pragma: no cover - replaced in Task 4
    pass


class TraceDiff:  # pragma: no cover - replaced in Task 5
    pass


def serialize_trace(entries: list[TraceEntry]) -> str:  # pragma: no cover - replaced
    raise NotImplementedError


def load_golden(path: object) -> list[TraceEntry]:  # pragma: no cover - replaced
    raise NotImplementedError


def compare_traces(  # pragma: no cover - replaced
    actual: list[TraceEntry], golden: list[TraceEntry]
) -> TraceDiff:
    raise NotImplementedError
