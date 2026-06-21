"""Tests for the TEA scalability collector (M52, fourth NFR domain).

Scalability is the fourth TEA NFR domain (alongside performance,
reliability, security).  PASS rule: load-test headroom >= profile floor,
no static unbounded-fanout/N+1 patterns, capacity-plan referenced in
docs.

Three sub-collectors:
  * k6-scalability — k6 load profile with capacity ramp
  * scale-lint-scalability — static unbounded-fanout / unbounded-queue lint
  * capacity-plan-scalability — capacity-plan doc presence + headroom field

All emit category="scalability".
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


class K6ScalabilityCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.scalability import K6_SCALABILITY

        self.assertEqual(K6_SCALABILITY.collector_id, "k6-scalability")
        self.assertEqual(K6_SCALABILITY.tool, "k6")
        self.assertEqual(K6_SCALABILITY.category, "scalability")
        self.assertTrue(K6_SCALABILITY.deterministic)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.scalability import K6_SCALABILITY

        cmd = K6_SCALABILITY.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], "k6")
        self.assertIn("run", cmd)
        # default script path
        self.assertTrue(any(arg.endswith("scalability.js") for arg in cmd))

    def test_build_cmd_custom_script_and_namespace(self) -> None:
        from story_automator.core.collectors.scalability import K6_SCALABILITY

        profile = {
            "_runtime_env": {"namespace": "prod"},
            "rules": {"scalability": {"k6_script": "k6/custom-scale.js"}},
        }
        cmd = K6_SCALABILITY.build_cmd("/tmp/checkout", profile)
        self.assertIn("--env", cmd)
        idx = cmd.index("--env")
        self.assertEqual(cmd[idx + 1], "NAMESPACE=prod")
        self.assertIn("k6/custom-scale.js", cmd)

    def test_build_cmd_emits_results_file(self) -> None:
        from story_automator.core.collectors.scalability import K6_SCALABILITY

        cmd = K6_SCALABILITY.build_cmd("/tmp/checkout", {})
        # k6 should write deterministic JSON output for later adjudication
        out_args = [a for a in cmd if a.startswith("json=")]
        self.assertEqual(len(out_args), 1)
        self.assertTrue(out_args[0].endswith("scalability-results.json"))

    def test_version_cmd(self) -> None:
        from story_automator.core.collectors.scalability import K6_SCALABILITY

        self.assertEqual(K6_SCALABILITY.tool_version_cmd, ("k6", "version"))


class ScaleLintCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.scalability import SCALE_LINT

        self.assertEqual(SCALE_LINT.collector_id, "scale-lint-scalability")
        self.assertEqual(SCALE_LINT.tool, "python3")
        self.assertEqual(SCALE_LINT.category, "scalability")
        self.assertTrue(SCALE_LINT.deterministic)
        # Should scan a reasonable set of source languages
        self.assertIn("*.py", SCALE_LINT.file_patterns)
        self.assertIn("*.ts", SCALE_LINT.file_patterns)

    def test_build_cmd_passes_checkout_path(self) -> None:
        from story_automator.core.collectors.scalability import SCALE_LINT

        cmd = SCALE_LINT.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], sys.executable)
        self.assertTrue(cmd[1].endswith("scale_lint_check.py"))
        self.assertEqual(cmd[2], "/tmp/checkout")

    def test_build_cmd_custom_extensions(self) -> None:
        from story_automator.core.collectors.scalability import SCALE_LINT

        profile = {"rules": {"scalability": {"lint_extensions": [".py", ".go"]}}}
        cmd = SCALE_LINT.build_cmd("/tmp/checkout", profile)
        # Custom extensions are passed as a JSON-encoded final argument
        extensions = json.loads(cmd[-1])
        self.assertEqual(extensions, [".py", ".go"])

    def test_check_script_path_resolution(self) -> None:
        from story_automator.core.collectors.scalability import SCALE_LINT

        cmd = SCALE_LINT.build_cmd("/tmp/checkout", {})
        script_path = Path(cmd[1])
        # The script *path* must be absolute and live under core/checks/
        self.assertTrue(script_path.is_absolute())
        self.assertEqual(script_path.parent.name, "checks")


class CapacityPlanCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.scalability import CAPACITY_PLAN

        self.assertEqual(CAPACITY_PLAN.collector_id, "capacity-plan-scalability")
        self.assertEqual(CAPACITY_PLAN.tool, "python3")
        self.assertEqual(CAPACITY_PLAN.category, "scalability")
        self.assertTrue(CAPACITY_PLAN.deterministic)
        # Capacity plan lives in docs by convention
        self.assertIn("*.md", CAPACITY_PLAN.file_patterns)

    def test_build_cmd_default_doc_path(self) -> None:
        from story_automator.core.collectors.scalability import CAPACITY_PLAN

        cmd = CAPACITY_PLAN.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], sys.executable)
        self.assertTrue(cmd[1].endswith("capacity_plan_check.py"))
        self.assertEqual(cmd[2], "/tmp/checkout")
        # default doc path threaded through
        self.assertIn("docs/capacity-plan.md", cmd)

    def test_build_cmd_custom_doc_path(self) -> None:
        from story_automator.core.collectors.scalability import CAPACITY_PLAN

        profile = {
            "rules": {"scalability": {"capacity_plan_path": "docs/scale/plan.md"}}
        }
        cmd = CAPACITY_PLAN.build_cmd("/tmp/checkout", profile)
        self.assertIn("docs/scale/plan.md", cmd)
        self.assertNotIn("docs/capacity-plan.md", cmd)

    def test_build_cmd_min_headroom_threaded(self) -> None:
        from story_automator.core.collectors.scalability import CAPACITY_PLAN

        profile = {"rules": {"scalability": {"min_headroom_pct": 35}}}
        cmd = CAPACITY_PLAN.build_cmd("/tmp/checkout", profile)
        self.assertIn("--min-headroom-pct", cmd)
        idx = cmd.index("--min-headroom-pct")
        self.assertEqual(cmd[idx + 1], "35")


class ScalabilityCollectorListTests(unittest.TestCase):
    def test_three_collectors(self) -> None:
        from story_automator.core.collectors.scalability import COLLECTORS

        self.assertEqual(len(COLLECTORS), 3)

    def test_all_scalability_category(self) -> None:
        from story_automator.core.collectors.scalability import COLLECTORS

        for c in COLLECTORS:
            self.assertEqual(c.category, "scalability")

    def test_expected_ids(self) -> None:
        from story_automator.core.collectors.scalability import COLLECTORS

        ids = {c.collector_id for c in COLLECTORS}
        self.assertEqual(
            ids,
            {
                "k6-scalability",
                "scale-lint-scalability",
                "capacity-plan-scalability",
            },
        )

    def test_unique_collector_ids(self) -> None:
        from story_automator.core.collectors.scalability import COLLECTORS

        ids = [c.collector_id for c in COLLECTORS]
        self.assertEqual(len(ids), len(set(ids)))

    def test_collectors_are_collectorconfig(self) -> None:
        from story_automator.core.collector_config import CollectorConfig
        from story_automator.core.collectors.scalability import COLLECTORS

        for c in COLLECTORS:
            self.assertIsInstance(c, CollectorConfig)


class ScalabilityIsFourthNFRDomainTests(unittest.TestCase):
    """The point of M52: scalability sits alongside performance, reliability,
    and security as TEA's NFR domains.  These tests pin the category string
    so the adjudicator and rules layer can find it."""

    def test_category_string_is_scalability(self) -> None:
        from story_automator.core.collectors.scalability import COLLECTORS

        self.assertTrue(all(c.category == "scalability" for c in COLLECTORS))

    def test_module_distinct_from_other_nfr_modules(self) -> None:
        # Same category string is not reused by the other NFR modules.
        from story_automator.core.collectors.performance import (
            COLLECTORS as PERF,
        )
        from story_automator.core.collectors.reliability import (
            COLLECTORS as RELI,
        )
        from story_automator.core.collectors.scalability import (
            COLLECTORS as SCALE,
        )
        from story_automator.core.collectors.security import (
            COLLECTORS as SEC,
        )

        scale_cats = {c.category for c in SCALE}
        other_cats = (
            {c.category for c in PERF}
            | {c.category for c in RELI}
            | {c.category for c in SEC}
        )
        self.assertTrue(scale_cats.isdisjoint(other_cats))


if __name__ == "__main__":
    unittest.main()
