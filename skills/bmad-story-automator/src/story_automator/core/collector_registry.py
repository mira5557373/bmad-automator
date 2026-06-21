"""Collector registry — stores, looks up, and filters collector configs.

Maps collector_id → CollectorConfig and category → [CollectorConfig].
Profile-aware filtering prunes collectors by product profile categories,
categories_na exclusions, and per-tool kill-switch rules.
"""
from __future__ import annotations

from typing import Any

from .collector_config import CollectorConfig

__all__ = [
    "CollectorRegistry",
]


class CollectorRegistry:
    """Registry of evidence collector configurations."""

    def __init__(self) -> None:
        self._by_id: dict[str, CollectorConfig] = {}
        self._by_category: dict[str, list[str]] = {}

    def register(self, config: CollectorConfig) -> None:
        if config.collector_id in self._by_id:
            raise ValueError(
                f"collector already registered: {config.collector_id!r}"
            )
        self._by_id[config.collector_id] = config
        self._by_category.setdefault(config.category, []).append(
            config.collector_id
        )

    def get(self, collector_id: str) -> CollectorConfig | None:
        return self._by_id.get(collector_id)

    def get_for_category(self, category: str) -> list[CollectorConfig]:
        ids = self._by_category.get(category, [])
        return [self._by_id[cid] for cid in sorted(ids)]

    def all_categories(self) -> set[str]:
        return set(self._by_category.keys())

    def all_collectors(self) -> list[CollectorConfig]:
        return sorted(
            self._by_id.values(),
            key=lambda c: (c.category, c.collector_id),
        )

    def is_kill_switched(
        self, config: CollectorConfig, profile: dict[str, Any]
    ) -> bool:
        """Check if a collector's tool is disabled in profile rules."""
        rules = (profile.get("rules") or {}).get(config.category) or {}
        disabled_tools = rules.get("disabled_tools") or []
        return config.tool in disabled_tools

    def applicable(
        self, profile: dict[str, Any]
    ) -> list[CollectorConfig]:
        """Return collectors whose category is active and not kill-switched.

        Active = listed in profile.categories (any tier) AND NOT in
        profile.categories_na.  Kill-switched = tool listed in
        profile.rules.<category>.disabled_tools.
        """
        active: set[str] = set()
        for tier_cats in (profile.get("categories") or {}).values():
            if isinstance(tier_cats, list):
                active.update(tier_cats)
        na = set(profile.get("categories_na") or [])
        active -= na
        result: list[CollectorConfig] = []
        for config in self._by_id.values():
            if config.category not in active:
                continue
            if self.is_kill_switched(config, profile):
                continue
            result.append(config)
        return sorted(result, key=lambda c: (c.category, c.collector_id))
