"""Core evidence collector registration (§6.2, §8 module 3).

Registers all built-in collectors for correctness, static, docs, process,
security, license, compliance, supply_chain.
"""

from __future__ import annotations

from ..collector_registry import CollectorRegistry
from .compliance import COLLECTORS as _COMPLIANCE
from .correctness import COLLECTORS as _CORRECTNESS
from .docs import COLLECTORS as _DOCS
from .license import COLLECTORS as _LICENSE
from .process import COLLECTORS as _PROCESS
from .security import COLLECTORS as _SECURITY
from .static import COLLECTORS as _STATIC
from .supply_chain import COLLECTORS as _SUPPLY_CHAIN

__all__ = ["register_core_collectors", "CORE_COLLECTOR_IDS"]

_ALL = (
    _COMPLIANCE + _CORRECTNESS + _DOCS + _LICENSE
    + _PROCESS + _SECURITY + _STATIC + _SUPPLY_CHAIN
)

CORE_COLLECTOR_IDS: frozenset[str] = frozenset(c.collector_id for c in _ALL)


def register_core_collectors(registry: CollectorRegistry) -> None:
    """Register all built-in collectors into the given registry."""
    for config in _ALL:
        registry.register(config)
