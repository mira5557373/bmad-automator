from __future__ import annotations

import json
import unittest


class InvariantCheckUsageTests(unittest.TestCase):
    def test_no_args_returns_2(self) -> None:
        from story_automator.core.checks.invariant_check import main

        self.assertEqual(main([]), 2)

    def test_one_arg_returns_2(self) -> None:
        from story_automator.core.checks.invariant_check import main

        self.assertEqual(main(["/tmp"]), 2)

    def test_two_args_returns_2(self) -> None:
        from story_automator.core.checks.invariant_check import main

        self.assertEqual(main(["/tmp", "semgrep"]), 2)

    def test_invalid_check_type_returns_2(self) -> None:
        from story_automator.core.checks.invariant_check import main

        self.assertEqual(main(["/tmp", "badtype", "[]"]), 2)

    def test_invalid_json_returns_2(self) -> None:
        from story_automator.core.checks.invariant_check import main

        self.assertEqual(main(["/tmp", "semgrep", "not-json"]), 2)

    def test_non_array_registry_returns_2(self) -> None:
        from story_automator.core.checks.invariant_check import main

        self.assertEqual(main(["/tmp", "semgrep", '{"a":1}']), 2)


class FilterRegistryTests(unittest.TestCase):
    def test_filters_by_check_type(self) -> None:
        from story_automator.core.checks.invariant_check import filter_registry

        registry = [
            {"id": "DG-12", "checkable": "yes", "check_type": "semgrep", "rule_file": "r1.yml", "severity": "FAIL"},
            {"id": "DG-99", "checkable": "yes", "check_type": "conftest", "rule_file": "p1.rego", "severity": "FAIL"},
            {"id": "DG-50", "checkable": "no", "check_type": "semgrep", "rule_file": "r2.yml", "severity": "FAIL"},
        ]
        result = filter_registry(registry, "semgrep")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "DG-12")

    def test_filters_out_non_checkable(self) -> None:
        from story_automator.core.checks.invariant_check import filter_registry

        registry = [
            {"id": "DG-1", "checkable": "no", "check_type": "semgrep", "rule_file": "r.yml"},
        ]
        self.assertEqual(filter_registry(registry, "semgrep"), [])

    def test_filters_out_missing_rule_file(self) -> None:
        from story_automator.core.checks.invariant_check import filter_registry

        registry = [
            {"id": "DG-1", "checkable": "yes", "check_type": "semgrep"},
        ]
        self.assertEqual(filter_registry(registry, "semgrep"), [])

    def test_empty_registry(self) -> None:
        from story_automator.core.checks.invariant_check import filter_registry

        self.assertEqual(filter_registry([], "semgrep"), [])

    def test_non_dict_entries_skipped(self) -> None:
        from story_automator.core.checks.invariant_check import filter_registry

        self.assertEqual(filter_registry(["bad", 42], "semgrep"), [])


class BuildCmdTests(unittest.TestCase):
    def test_semgrep_cmd(self) -> None:
        from story_automator.core.checks.invariant_check import build_semgrep_cmd

        entries = [
            {"rule_file": "semgrep/dg12.yml"},
            {"rule_file": "semgrep/dg13.yml"},
        ]
        cmd = build_semgrep_cmd(entries)
        self.assertEqual(cmd[0], "semgrep")
        self.assertIn("scan", cmd)
        self.assertIn("--config=semgrep/dg12.yml", cmd)
        self.assertIn("--config=semgrep/dg13.yml", cmd)
        self.assertIn("--error", cmd)

    def test_conftest_cmd(self) -> None:
        from story_automator.core.checks.invariant_check import build_conftest_cmd

        entries = [
            {"rule_file": "policy/dg4.rego"},
        ]
        cmd = build_conftest_cmd(entries)
        self.assertEqual(cmd[0], "conftest")
        self.assertIn("test", cmd)
        self.assertIn("--policy", cmd)
        self.assertIn("policy/dg4.rego", cmd)
        self.assertIn(".", cmd)


class NoMatchingEntriesTests(unittest.TestCase):
    def test_no_semgrep_entries_returns_0(self) -> None:
        from story_automator.core.checks.invariant_check import main

        registry = json.dumps([
            {"id": "DG-99", "checkable": "yes", "check_type": "conftest", "rule_file": "p.rego"},
        ])
        self.assertEqual(main(["/tmp", "semgrep", registry]), 0)

    def test_empty_registry_returns_0(self) -> None:
        from story_automator.core.checks.invariant_check import main

        self.assertEqual(main(["/tmp", "semgrep", "[]"]), 0)
