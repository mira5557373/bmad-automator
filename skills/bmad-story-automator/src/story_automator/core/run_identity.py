"""Derive a stable per-run correlation id for telemetry events.

The active marker (``.story-automator-active``) is the single per-run
sentinel: it is written once at run start by ``orchestrator-helper marker
create`` (with ``createdAt``, ``epic``, ``pid``), heartbeat-refreshed in
place, and removed at run end. Deriving the run id from those fields makes
every telemetry event emitted during one run share a single correlation
key, so a run's ``StoryStarted -> StoryCompleted -> ReviewCycle`` chain can
be joined from the ledger.

This is a pure, best-effort read: it returns ``""`` (today's behavior) when
no marker is present or it cannot be read, so an emit can never fail because
the id could not be derived.
"""

from __future__ import annotations

import json
from pathlib import Path

from .runtime_layout import active_marker_path
from .utils import md5_hex8

__all__ = ["current_run_id"]


def current_run_id(project_root: str | Path | None = None) -> str:
    """Return a stable per-run id from the active marker, or ``""`` if none.

    The id is ``"run-" + md5_hex8(createdAt|epic|pid)`` — short, deterministic,
    and self-describing in the JSONL. Returns ``""`` when the marker is absent,
    unreadable, malformed, or missing ``createdAt`` (which preserves the prior
    empty-run_id behavior, making this change purely additive).
    """
    try:
        marker = active_marker_path(project_root)
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if not isinstance(payload, dict):
        return ""
    created = str(payload.get("createdAt") or "")
    if not created:
        return ""
    epic = str(payload.get("epic") or "")
    pid = str(payload.get("pid") or "")
    return "run-" + md5_hex8(f"{created}|{epic}|{pid}")
