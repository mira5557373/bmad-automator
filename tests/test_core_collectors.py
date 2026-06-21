from __future__ import annotations

import unittest


_EXPECTED_IDS = frozenset(
    {
        # static (5)
        "ruff-static",
        "mypy-static",
        "tsc-static",
        "biome-static",
        "knip-static",
        # correctness (4)
        "pytest-correctness",
        "vitest-correctness",
        "playwright-correctness",
        "coverage-correctness",
        # docs (3)
        "doc-presence-docs",
        "api-docs-docs",
        "docusaurus-docs",
        # process (2)
        "adr-process",
        "trace-process",
        # security (4)
        "semgrep-security",
        "trivy-vuln-security",
        "osv-security",
        "gitleaks-security",
        # license (1)
        "license-check-license",
        # compliance (2)
        "compliance-rules-compliance",
        "conftest-compliance",
        # supply_chain (4)
        "sbom-supply_chain",
        "cosign-supply_chain",
        "provenance-supply_chain",
        "trivy-sbom-supply_chain",
        # invariants (2)
        "invariant-semgrep-invariants",
        "invariant-conftest-invariants",
        # traceability (1)
        "trace-traceability",
        # api_compat (2)
        "openapi-diff-api_compat",
        "schema-diff-api_compat",
        # migrations (2)
        "alembic-migrations",
        "migration-lint-migrations",
        # performance (3)
        "lighthouse-performance",
        "bundlesize-performance",
        "perf-lint-performance",
        # accessibility (1)
        "axe-accessibility",
        # observability (3)
        "otel-wiring-observability",
        "health-probe-observability",
        "slo-observability",
        # test_quality (3)
        "test-review-test_quality",
        "burn-in-test_quality",
        "hard-wait-test_quality",
        # mutation (2)
        "mutmut-mutation",
        "stryker-mutation",
        # agentic (5)
        "pack-schema-agentic",
        "aibom-diff-agentic",
        "opa-agentic",
        "evals-agentic",
        "guardrail-agentic",
    }
)

_EXPECTED_CATEGORIES = frozenset(
    {
        "correctness",
        "static",
        "docs",
        "process",
        "security",
        "license",
        "compliance",
        "supply_chain",
        "invariants",
        "traceability",
        "api_compat",
        "migrations",
        "performance",
        "accessibility",
        "observability",
        "test_quality",
        "mutation",
        "agentic",
    }
)


class RegisterCoreCollectorsTests(unittest.TestCase):
    def test_registers_all_collectors(self) -> None:
        from story_automator.core.collector_registry import CollectorRegistry
        from story_automator.core.collectors import register_core_collectors

        reg = CollectorRegistry()
        register_core_collectors(reg)
        registered_ids = {c.collector_id for c in reg.all_collectors()}
        self.assertEqual(registered_ids, _EXPECTED_IDS)

    def test_covers_all_categories(self) -> None:
        from story_automator.core.collector_registry import CollectorRegistry
        from story_automator.core.collectors import register_core_collectors

        reg = CollectorRegistry()
        register_core_collectors(reg)
        self.assertEqual(reg.all_categories(), _EXPECTED_CATEGORIES)

    def test_no_duplicate_ids(self) -> None:
        from story_automator.core.collector_registry import CollectorRegistry
        from story_automator.core.collectors import register_core_collectors

        reg = CollectorRegistry()
        register_core_collectors(reg)
        ids = [c.collector_id for c in reg.all_collectors()]
        self.assertEqual(len(ids), len(set(ids)))

    def test_double_register_raises(self) -> None:
        from story_automator.core.collector_registry import CollectorRegistry
        from story_automator.core.collectors import register_core_collectors

        reg = CollectorRegistry()
        register_core_collectors(reg)
        with self.assertRaises(ValueError):
            register_core_collectors(reg)

    def test_collector_count(self) -> None:
        from story_automator.core.collector_registry import CollectorRegistry
        from story_automator.core.collectors import register_core_collectors

        reg = CollectorRegistry()
        register_core_collectors(reg)
        self.assertEqual(len(reg.all_collectors()), 49)

    def test_exported_id_set(self) -> None:
        from story_automator.core.collectors import CORE_COLLECTOR_IDS

        self.assertEqual(CORE_COLLECTOR_IDS, _EXPECTED_IDS)


class ProfileFilteringTests(unittest.TestCase):
    def test_applicable_filters_by_profile_categories(self) -> None:
        from story_automator.core.collector_registry import CollectorRegistry
        from story_automator.core.collectors import register_core_collectors

        reg = CollectorRegistry()
        register_core_collectors(reg)
        profile = {
            "categories": {"code": ["static"]},
            "categories_na": [],
        }
        applicable = reg.applicable(profile)
        cats = {c.category for c in applicable}
        self.assertEqual(cats, {"static"})

    def test_categories_na_excludes(self) -> None:
        from story_automator.core.collector_registry import CollectorRegistry
        from story_automator.core.collectors import register_core_collectors

        reg = CollectorRegistry()
        register_core_collectors(reg)
        profile = {
            "categories": {"code": ["static", "docs"]},
            "categories_na": ["docs"],
        }
        applicable = reg.applicable(profile)
        cats = {c.category for c in applicable}
        self.assertEqual(cats, {"static"})

    def test_kill_switch_excludes_tool(self) -> None:
        from story_automator.core.collector_registry import CollectorRegistry
        from story_automator.core.collectors import register_core_collectors

        reg = CollectorRegistry()
        register_core_collectors(reg)
        profile = {
            "categories": {"code": ["static"]},
            "categories_na": [],
            "rules": {"static": {"disabled_tools": ["knip"]}},
        }
        applicable = reg.applicable(profile)
        ids = {c.collector_id for c in applicable}
        self.assertNotIn("knip-static", ids)
        self.assertIn("ruff-static", ids)

    def test_integration_categories_filter(self) -> None:
        from story_automator.core.collector_registry import CollectorRegistry
        from story_automator.core.collectors import register_core_collectors

        reg = CollectorRegistry()
        register_core_collectors(reg)
        profile = {
            "categories": {"code": [
                "traceability", "api_compat", "migrations",
                "performance", "accessibility", "observability",
            ]},
            "categories_na": [],
        }
        applicable = reg.applicable(profile)
        cats = {c.category for c in applicable}
        self.assertEqual(cats, {
            "traceability", "api_compat", "migrations",
            "performance", "accessibility", "observability",
        })
        self.assertEqual(len(applicable), 12)
