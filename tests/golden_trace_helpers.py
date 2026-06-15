"""Golden-trace data types and pure helpers (M10a wedge).

The recorder, interception hooks, fixtures, and redaction layer land in
later M10 sub-milestones. Importing this module must produce no telemetry
events, no state mutations, and no claude_p invocations.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
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


@dataclass(kw_only=True)
class TraceMismatch:
    """One arrival-position divergence between an actual and a golden trace.

    `field` identifies which slot diverged (per REQ-10). `actual` and
    `expected` use PEP 604 `object | None` because a "length" mismatch may
    have no entry on one side at that arrival index.
    """

    seq: int
    field: MismatchField
    actual: object | None
    expected: object | None


@dataclass(kw_only=True)
class TraceDiff:
    """Result of comparing two traces. ``ok=True`` iff lengths match and no
    arrival position diverged."""

    matched: int
    mismatches: list[TraceMismatch]
    ok: bool

    def summary(self) -> str:
        """Human-readable summary including the arrival position and the
        diverging field of each mismatch (NFR: Diagnostics).
        """
        if self.ok:
            return f"trace ok ({self.matched} entries matched)"
        lines = [
            f"trace mismatch: {self.matched} matched, {len(self.mismatches)} mismatch(es)",
        ]
        for m in self.mismatches:
            lines.append(
                f"  seq={m.seq} field={m.field} "
                f"actual={m.actual!r} expected={m.expected!r}"
            )
        return "\n".join(lines)


def serialize_trace(entries: list[TraceEntry]) -> str:
    """Serialize entries to canonical JSON with a trailing newline (REQ-07).

    Uses ``sort_keys=True`` so payload-dict insertion order is irrelevant
    and ``separators=(",", ":")`` to produce the compact form. The trailing
    newline matches the project's JSONL/JSON conventions and keeps git
    diffs clean.
    """
    payload = [asdict(entry) for entry in entries]
    return json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"


def load_golden(path: object) -> list[TraceEntry]:  # pragma: no cover - replaced
    raise NotImplementedError


def compare_traces(  # pragma: no cover - replaced
    actual: list[TraceEntry], golden: list[TraceEntry]
) -> TraceDiff:
    raise NotImplementedError
