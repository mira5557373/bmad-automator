"""Typed telemetry events for bmad-automator (M01 wedge atom).

This module provides the `Event` base @dataclass with a registry-based
discriminator mechanism (auto-registration via __init_subclass__), the
shared envelope fields (timestamp, run_id), and the serialization
helpers (to_dict, to_json_line). The forward-compatibility fallback
`UnknownEvent`, the 13 concrete typed event classes, and the
`parse_event` dispatch land in subsequent slices (m01-m2 ... m01-m4).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, ClassVar

from .common import compact_json, iso_now


@dataclass
class Event:
    """Base for all typed telemetry events.

    Concrete events declare an EVENT_TYPE classvar and become auto-
    registered via __init_subclass__. Identity-check idempotency lands
    in the next task; serialization helpers follow.
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


__all__ = [
    "Event",
    "compact_json",
    "iso_now",
]
