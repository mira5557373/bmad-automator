"""Core evidence collector registration (§6.2).

Registers all built-in collectors for correctness, static, docs, process.
"""

from __future__ import annotations

from ..collector_registry import CollectorRegistry
from .correctness import COLLECTORS as _CORRECTNESS
from .docs import COLLECTORS as _DOCS
from .process import COLLECTORS as _PROCESS
from .static import COLLECTORS as _STATIC

__all__ = ["register_core_collectors", "CORE_COLLECTOR_IDS"]

_ALL = _CORRECTNESS + _DOCS + _PROCESS + _STATIC

CORE_COLLECTOR_IDS: frozenset[str] = frozenset(c.collector_id for c in _ALL)


def register_core_collectors(registry: CollectorRegistry) -> None:
    """Register all built-in collectors into the given registry."""
    for config in _ALL:
        registry.register(config)
