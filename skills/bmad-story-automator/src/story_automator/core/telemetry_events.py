"""Typed telemetry events for bmad-automator (M01 wedge atom).

This module provides the `Event` base @dataclass with a registry-based
discriminator mechanism (auto-registration via __init_subclass__), the
shared envelope fields (timestamp, run_id), and the serialization
helpers (to_dict, to_json_line). The forward-compatibility fallback
`UnknownEvent`, the 13 concrete typed event classes, and the
`parse_event` dispatch land in subsequent slices (m01-m2 ... m01-m4).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar


@dataclass
class Event:
    """Base for all typed telemetry events.

    Concrete events declare an EVENT_TYPE classvar and become auto-
    registered via __init_subclass__ (added in the next task). Round-trip
    helpers (to_dict, to_json_line) and the iso_now / compact_json re-
    exports also land in subsequent tasks of this slice.
    """

    EVENT_TYPE: ClassVar[str] = ""
    _REGISTRY: ClassVar[dict[str, type[Event]]] = {}

    timestamp: str
    run_id: str
