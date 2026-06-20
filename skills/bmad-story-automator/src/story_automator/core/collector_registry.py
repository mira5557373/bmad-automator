"""Collector registry — stores, looks up, and filters collector configs.

Maps collector_id → CollectorConfig and category → [CollectorConfig].
Profile-aware filtering (categories, categories_na, kill-switch) added
in a subsequent task.
"""
from __future__ import annotations

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
