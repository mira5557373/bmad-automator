"""Golden-trace data types and pure helpers (M10a wedge).

The recorder, interception hooks, fixtures, and redaction layer land in
later M10 sub-milestones. Importing this module must produce no telemetry
events, no state mutations, and no claude_p invocations.
"""

from __future__ import annotations

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
class TraceEntry:  # pragma: no cover - replaced in Task 3
    pass


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
