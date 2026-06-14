"""Typed telemetry events for bmad-automator (M01 wedge atom).

This module provides the `Event` base @dataclass with a registry-based
discriminator mechanism (auto-registration via __init_subclass__), the
shared envelope fields (timestamp, run_id), and the serialization
helpers (to_dict, to_json_line). The forward-compatibility fallback
`UnknownEvent`, the 13 concrete typed event classes, and the
`parse_event` dispatch land in subsequent slices (m01-m2 ... m01-m4).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, ClassVar

from .common import compact_json, iso_now


@dataclass
class Event:
    """Base for all typed telemetry events.

    Concrete events declare an EVENT_TYPE classvar and become auto-
    registered via __init_subclass__, with duplicate-EVENT_TYPE detection
    (raises RuntimeError) and identity-check idempotency under re-import.
    The to_dict and to_json_line helpers emit JSON with event_type
    sourced from the EVENT_TYPE classvar (never an instance field).
    """

    EVENT_TYPE: ClassVar[str] = ""
    _REGISTRY: ClassVar[dict[str, type[Event]]] = {}

    timestamp: str
    run_id: str

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if not cls.EVENT_TYPE:
            return
        existing = Event._REGISTRY.get(cls.EVENT_TYPE)
        if existing is not None and existing is not cls:
            raise RuntimeError(
                f"duplicate EVENT_TYPE {cls.EVENT_TYPE!r}: "
                f"{existing.__qualname__} vs {cls.__qualname__}"
            )
        Event._REGISTRY[cls.EVENT_TYPE] = cls

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict with event_type injected from the
        EVENT_TYPE classvar.

        `event_type` is never an instance field. Subclasses cannot
        accidentally desync the discriminator from the class — the
        classvar is the single source of truth, and to_dict is the
        only place it's read into the payload.
        """
        data: dict[str, Any] = {"event_type": self.EVENT_TYPE}
        data.update(asdict(self))
        return data

    def to_json_line(self) -> str:
        """Compact single-line JSON suitable for JSONL emission.

        No trailing newline — the emitter (M02, out of scope here)
        is responsible for appending `\n` per JSONL convention.
        Uses `compact_json` from `story_automator.core.common` so the
        separator policy (",", ":") and `ensure_ascii=False` matches
        the rest of the codebase. The helper is NOT duplicated.
        """
        return compact_json(self.to_dict())


@dataclass
class UnknownEvent(Event):
    """Forward-compatibility fallback for unrecognized event_type strings.

    Carries the raw event_type and the unrecognized payload fields so a
    JSONL stream produced by a newer codebase can be read by an older
    parser without data loss. NOT auto-registered: `EVENT_TYPE = ""` so
    `__init_subclass__` skips it via the empty-string early return.
    """

    EVENT_TYPE: ClassVar[str] = ""

    raw_event_type: str
    raw_fields: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Re-emit the original ``event_type`` and unrecognized fields.

        Returns a dict shaped like the wire form of any other Event:
        ``{"event_type": <raw>, "timestamp": ..., "run_id": ..., **raw_fields}``.
        The internal ``raw_event_type`` and ``raw_fields`` field names do
        NOT appear in the output — they are implementation details that
        capture the unrecognized payload, not part of the JSONL contract.
        Key order is event_type -> timestamp -> run_id -> raw_fields-in-
        insertion-order, which is the canonical order produced by every
        other Event subclass's ``to_dict``. This is the contract that
        lets REQ-04's "byte-equal to the original input line" hold for
        canonically-ordered inputs (which is everything that came out of
        ``to_json_line``).
        """
        data: dict[str, Any] = {
            "event_type": self.raw_event_type,
            "timestamp": self.timestamp,
            "run_id": self.run_id,
        }
        data.update(self.raw_fields)
        return data


def parse_event(line: str) -> Event:
    """Parse a single JSONL line into a typed ``Event`` instance.

    Dispatches by the ``event_type`` field. Known event_types route to the
    matching concrete subclass in ``Event._REGISTRY``; unknown event_types
    route to ``UnknownEvent`` (preserving the original event_type string
    and the unrecognized payload fields). Error semantics are documented
    in the M01 spec (REQ-07) and validated by the test matrix.
    """
    payload = json.loads(line)
    event_type = payload.pop("event_type")
    cls = Event._REGISTRY.get(event_type)
    if cls is None:
        return UnknownEvent(
            timestamp=payload.pop("timestamp", ""),
            run_id=payload.pop("run_id", ""),
            raw_event_type=event_type,
            raw_fields=payload,
        )
    return cls(**payload)


__all__ = [
    "Event",
    "compact_json",
    "iso_now",
]
