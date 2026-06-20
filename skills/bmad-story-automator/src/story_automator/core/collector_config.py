"""Collector configuration and outcome dataclasses.

CollectorConfig declares the identity, tool, category, and command builder
for an evidence collector.  CollectorOutcome wraps the evidence record with
the config that produced it and the path where it was persisted.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any, Callable

__all__ = [
    "CollectorConfig",
    "CollectorOutcome",
]

CmdBuilder = Callable[[str, dict[str, Any]], list[str]]


@dataclasses.dataclass(frozen=True)
class CollectorConfig:
    """Declares a single evidence collector."""

    collector_id: str
    tool: str
    category: str
    build_cmd: CmdBuilder = dataclasses.field(compare=False, hash=False, repr=False)
    tool_version_cmd: tuple[str, ...] | None = None
    file_patterns: frozenset[str] = dataclasses.field(default_factory=frozenset)
    deterministic: bool = True


@dataclasses.dataclass(frozen=True)
class CollectorOutcome:
    """Result of running a single collector: config + evidence + path."""

    config: CollectorConfig
    evidence: dict[str, Any]
    persisted_path: Path | None = None
