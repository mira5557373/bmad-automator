"""Core evidence collector registration (§6.2, §8 module 3).

Registers all built-in collectors for correctness, static, docs, process,
security, license, compliance, supply_chain, invariants, traceability,
api_compat, migrations, performance, accessibility, observability,
test_quality, mutation, agentic.
"""

from __future__ import annotations

from ..collector_registry import CollectorRegistry
from .accessibility import COLLECTORS as _ACCESSIBILITY
from .agentic import COLLECTORS as _AGENTIC
from .api_compat import COLLECTORS as _API_COMPAT
from .compliance import COLLECTORS as _COMPLIANCE
from .correctness import COLLECTORS as _CORRECTNESS
from .docs import COLLECTORS as _DOCS
from .invariants import COLLECTORS as _INVARIANTS
from .license import COLLECTORS as _LICENSE
from .migrations import COLLECTORS as _MIGRATIONS
from .mutation import COLLECTORS as _MUTATION
from .observability import COLLECTORS as _OBSERVABILITY
from .performance import COLLECTORS as _PERFORMANCE
from .process import COLLECTORS as _PROCESS
from .security import COLLECTORS as _SECURITY
from .static import COLLECTORS as _STATIC
from .supply_chain import COLLECTORS as _SUPPLY_CHAIN
from .test_quality import COLLECTORS as _TEST_QUALITY
from .traceability import COLLECTORS as _TRACEABILITY

__all__ = ["register_core_collectors", "CORE_COLLECTOR_IDS"]

_ALL = (
    _ACCESSIBILITY + _AGENTIC + _API_COMPAT + _COMPLIANCE + _CORRECTNESS
    + _DOCS + _INVARIANTS + _LICENSE + _MIGRATIONS + _MUTATION
    + _OBSERVABILITY + _PERFORMANCE + _PROCESS + _SECURITY + _STATIC
    + _SUPPLY_CHAIN + _TEST_QUALITY + _TRACEABILITY
)

CORE_COLLECTOR_IDS: frozenset[str] = frozenset(c.collector_id for c in _ALL)


def register_core_collectors(registry: CollectorRegistry) -> None:
    """Register all built-in collectors into the given registry."""
    for config in _ALL:
        registry.register(config)
