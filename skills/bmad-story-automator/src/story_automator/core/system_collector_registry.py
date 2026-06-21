"""System-altitude collector registry — aggregates all system collectors.

Imports each system collector module and builds a CollectorRegistry
containing all system-altitude evidence collectors for use by
the system gate orchestrator.
"""
from __future__ import annotations

from .collector_config import CollectorConfig
from .collector_registry import CollectorRegistry
from .collectors.blast_radius import COLLECTORS as BLAST_RADIUS
from .collectors.cost_to_serve import COLLECTORS as COST
from .collectors.durable_hitl import COLLECTORS as DURABLE_HITL
from .collectors.progressive_delivery import COLLECTORS as PROGRESSIVE
from .collectors.reliability import COLLECTORS as RELIABILITY
from .collectors.resilience import COLLECTORS as RESILIENCE

SYSTEM_COLLECTORS: list[CollectorConfig] = [
    *RELIABILITY,
    *RESILIENCE,
    *DURABLE_HITL,
    *BLAST_RADIUS,
    *COST,
    *PROGRESSIVE,
]


def build_system_registry() -> CollectorRegistry:
    """Build a CollectorRegistry with all system-altitude collectors."""
    registry = CollectorRegistry()
    for config in SYSTEM_COLLECTORS:
        registry.register(config)
    return registry
