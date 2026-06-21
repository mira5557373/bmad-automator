"""Tests for system collector registry wiring."""
from __future__ import annotations

import unittest

from story_automator.core.system_collector_registry import (
    SYSTEM_COLLECTORS,
    build_system_registry,
)


class SystemRegistryTests(unittest.TestCase):
    def test_all_system_collectors_present(self) -> None:
        expected_categories = {
            "reliability", "resilience", "durable_hitl",
            "blast_radius", "cost_to_serve", "progressive_delivery",
        }
        actual_categories = {c.category for c in SYSTEM_COLLECTORS}
        self.assertEqual(expected_categories, actual_categories)

    def test_build_registry(self) -> None:
        registry = build_system_registry()
        self.assertTrue(len(registry.all_collectors()) >= 10)

    def test_registry_categories(self) -> None:
        registry = build_system_registry()
        cats = registry.all_categories()
        self.assertIn("reliability", cats)
        self.assertIn("resilience", cats)
        self.assertIn("cost_to_serve", cats)

    def test_applicable_filters_by_profile(self) -> None:
        registry = build_system_registry()
        profile = {
            "categories": {"code": [], "system": ["reliability"]},
            "categories_na": ["resilience"],
        }
        applicable = registry.applicable(profile)
        cats = {c.category for c in applicable}
        self.assertIn("reliability", cats)
        self.assertNotIn("resilience", cats)

    def test_collector_ids_unique(self) -> None:
        ids = [c.collector_id for c in SYSTEM_COLLECTORS]
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
