"""Golden-trace data types and pure helpers (M10a wedge).

The recorder, interception hooks, fixtures, and redaction layer land in
later M10 sub-milestones. Importing this module must produce no telemetry
events, no state mutations, and no claude_p invocations.
"""

from __future__ import annotations

import json
import threading
import warnings
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, cast

from story_automator.core.telemetry_emitter import TelemetryEmitter

Channel = Literal["event", "state", "claude_p"]
MismatchField = Literal["channel", "kind", "payload", "length"]

_VALID_CHANNELS: frozenset[str] = frozenset({"event", "state", "claude_p"})
_REQUIRED_KEYS: tuple[str, ...] = ("seq", "channel", "kind", "payload")
_TS_SENTINEL = "<ts>"
_REDACTED_SENTINEL = "<redacted>"
_REDACTED_EVENT_FIELDS: frozenset[str] = frozenset(
    {
        "pid",
        "session_name",
        "final_session",
        "lock_token",
        "heartbeat_counter",
    }
)

__all__ = [
    "Channel",
    "GoldenTraceError",
    "GoldenTraceRecorder",
    "MismatchField",
    "TraceDiff",
    "TraceEntry",
    "TraceMismatch",
    "compare_traces",
    "load_golden",
    "notify_claude_p",
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


def load_golden(path: Path) -> list[TraceEntry]:
    """Parse a stored golden fixture into a list of TraceEntry (REQ-08).

    Raises GoldenTraceError on malformed JSON, non-list top-level value,
    non-dict entry, missing required keys, or unknown channel.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GoldenTraceError(f"{path}: malformed JSON: {exc}") from exc
    if not isinstance(raw, list):
        raise GoldenTraceError(
            f"{path}: top-level value must be a JSON array, got {type(raw).__name__}"
        )
    entries: list[TraceEntry] = []
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            raise GoldenTraceError(
                f"{path}: entry #{idx} must be a JSON object, got {type(item).__name__}"
            )
        missing = [k for k in _REQUIRED_KEYS if k not in item]
        if missing:
            raise GoldenTraceError(
                f"{path}: entry #{idx} missing required keys: {missing}"
            )
        channel = item["channel"]
        if channel not in _VALID_CHANNELS:
            raise GoldenTraceError(
                f"{path}: entry #{idx} unknown channel {channel!r}; "
                f"expected one of {sorted(_VALID_CHANNELS)}"
            )
        payload = item["payload"]
        if not isinstance(payload, dict):
            raise GoldenTraceError(
                f"{path}: entry #{idx} payload must be an object, "
                f"got {type(payload).__name__}"
            )
        seq_value = item["seq"]
        # bool is an int subclass in Python; reject it explicitly so {"seq": true}
        # doesn't silently become seq=1.
        if not isinstance(seq_value, int) or isinstance(seq_value, bool):
            raise GoldenTraceError(
                f"{path}: entry #{idx} seq must be an integer, "
                f"got {type(seq_value).__name__}"
            )
        kind_value = item["kind"]
        if not isinstance(kind_value, str):
            raise GoldenTraceError(
                f"{path}: entry #{idx} kind must be a string, "
                f"got {type(kind_value).__name__}"
            )
        entries.append(
            TraceEntry(
                seq=seq_value,
                channel=cast(Channel, channel),
                kind=kind_value,
                payload=cast("dict[str, object]", dict(payload)),
            )
        )
    return entries


def compare_traces(actual: list[TraceEntry], golden: list[TraceEntry]) -> TraceDiff:
    """Positional comparison of two traces (REQ-09).

    Walks both lists in arrival order, recording a TraceMismatch at the
    first diverging field per index. Length divergence appends "length"
    mismatches for the tail of whichever list is longer.
    """
    mismatches: list[TraceMismatch] = []
    matched = 0
    common = min(len(actual), len(golden))
    for i in range(common):
        a = actual[i]
        g = golden[i]
        field = _first_diverging_field(a, g)
        if field is None:
            matched += 1
            continue
        mismatches.append(
            TraceMismatch(
                seq=i,
                field=field,
                actual=_field_value(a, field),
                expected=_field_value(g, field),
            )
        )
    # Tail-length mismatches (one side is longer).
    for i in range(common, len(actual)):
        mismatches.append(
            TraceMismatch(seq=i, field="length", actual=actual[i], expected=None)
        )
    for i in range(common, len(golden)):
        mismatches.append(
            TraceMismatch(seq=i, field="length", actual=None, expected=golden[i])
        )
    ok = not mismatches and len(actual) == len(golden)
    return TraceDiff(matched=matched, mismatches=mismatches, ok=ok)


def _first_diverging_field(a: TraceEntry, g: TraceEntry) -> MismatchField | None:
    """Return the first field name where two entries differ, in the order
    channel -> kind -> payload. ``seq`` is the arrival index, not a value
    to compare. Returns None if entries are equal.
    """
    if a.channel != g.channel:
        return "channel"
    if a.kind != g.kind:
        return "kind"
    if a.payload != g.payload:
        return "payload"
    return None


def _field_value(entry: TraceEntry, field: MismatchField) -> object | None:
    """Look up the value of a diverging field for diagnostics."""
    if field == "channel":
        return entry.channel
    if field == "kind":
        return entry.kind
    if field == "payload":
        return entry.payload
    # "length" is handled by the caller (one side has no entry).
    return None


def _redact_event_payload(payload: dict[str, object]) -> dict[str, object]:
    """Apply REQ-13 redaction to an event payload.

    Replaces non-deterministic fields with their sentinel:
    - ``timestamp`` -> ``"<ts>"`` (REQ-03 narrower contract)
    - ``pid``/``session_name``/``final_session``/``lock_token``/``heartbeat_counter`` -> ``"<redacted>"`` (REQ-13)

    Four-letter placeholder tokens are intentionally NOT substituted --
    REQ-13's last clause requires them to flow through verbatim.
    """
    out = dict(payload)
    if "timestamp" in out:
        out["timestamp"] = _TS_SENTINEL
    for key in _REDACTED_EVENT_FIELDS:
        if key in out:
            out[key] = _REDACTED_SENTINEL
    return out


def _to_repo_relative_posix(path: Path, *, repo_root: Path) -> str:
    """Return a repo-relative POSIX path string for ``path`` (REQ-04/05).

    If ``path`` lies inside ``repo_root``, return the relative POSIX
    form. Otherwise return ``path`` as an absolute POSIX string — the
    spec is explicit about not normalizing beyond repo-relative
    conversion (see Out of scope #4).
    """
    try:
        resolved = path.resolve()
    except OSError:
        resolved = Path(path)
    try:
        rel = resolved.relative_to(repo_root.resolve())
    except ValueError:
        return resolved.as_posix() if resolved.is_absolute() else Path(path).as_posix()
    return rel.as_posix()


def _find_repo_root(start: Path | None = None) -> Path:
    """Walk up from ``start`` (or CWD) until we find a project marker.

    Markers, in order of preference: ``pyproject.toml``, ``.git``. If
    no marker is found, fall back to the start directory itself AND
    warn — silent fallback would otherwise let CI runs with a wrong
    CWD produce fixtures full of unstable absolute paths.
    """
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").exists() or (candidate / ".git").exists():
            return candidate
    warnings.warn(
        f"GoldenTraceRecorder: no project marker (pyproject.toml or .git) "
        f"found walking up from {current}; recorded paths may stay absolute",
        stacklevel=2,
    )
    return current


def notify_claude_p(argv: list[str]) -> None:
    """Hook surface for `claude -p` invocations.

    No-op when no recorder is active. GoldenTraceRecorder.__enter__
    swaps the module-level _CLAUDE_P_HOOK slot (NOT this function
    itself) in a later task, so callers that did
    `from tests.golden_trace_helpers import notify_claude_p` still
    see the active recorder because the function body re-reads the
    module-global slot on every call.
    """
    return None


class GoldenTraceRecorder:
    """Context manager that records arrival-ordered observations of
    telemetry emits, state-document mutations, and claude_p invocations.

    See REQ-01/REQ-03/REQ-04/REQ-05/REQ-06/REQ-13/REQ-14 in the M10 spec.
    """

    def __init__(self, *, repo_root: Path | None = None) -> None:
        self._entries: list[TraceEntry] = []
        self._lock = threading.Lock()
        self._repo_root: Path = repo_root.resolve() if repo_root else _find_repo_root()
        self._installed = False

    @property
    def entries(self) -> list[TraceEntry]:
        """Defensive copy so callers cannot mutate the recorder's buffer."""
        return list(self._entries)

    def __enter__(self) -> GoldenTraceRecorder:
        if self._installed:
            raise RuntimeError("GoldenTraceRecorder is not reentrant")
        self._orig_emit = TelemetryEmitter.emit
        self._install_emit_hook()
        self._installed = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object,
    ) -> None:
        try:
            TelemetryEmitter.emit = self._orig_emit  # type: ignore[method-assign]
        finally:
            self._installed = False
        return None

    def _install_emit_hook(self) -> None:
        orig = self._orig_emit
        recorder = self

        def wrapper(emitter_self: TelemetryEmitter, event: object) -> None:
            result = orig(emitter_self, event)
            raw_payload: dict[str, object] = dict(event.to_dict())  # type: ignore[attr-defined]
            payload = _redact_event_payload(raw_payload)
            recorder._record("event", type(event).__name__, payload)
            return result

        TelemetryEmitter.emit = wrapper  # type: ignore[method-assign]

    def _record(self, channel: Channel, kind: str, payload: dict[str, object]) -> None:
        """Append one entry under the arrival lock (REQ-06).

        The lock serializes (a) the seq assignment and (b) the list
        append so that traces produced under concurrent threads receive
        deterministic, contiguous seq numbers. Operation completion
        order itself is still the underlying code's problem.
        """
        with self._lock:
            seq = len(self._entries)
            self._entries.append(
                TraceEntry(seq=seq, channel=channel, kind=kind, payload=dict(payload))
            )
