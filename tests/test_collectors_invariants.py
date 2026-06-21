from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


class InvariantSemgrepCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.invariants import INVARIANT_SEMGREP

        self.assertEqual(INVARIANT_SEMGREP.collector_id, "invariant-semgrep-invariants")
        self.assertEqual(INVARIANT_SEMGREP.tool, "python3")
        self.assertEqual(INVARIANT_SEMGREP.category, "invariants")
        self.assertTrue(INVARIANT_SEMGREP.deterministic)
        self.assertIn("*.py", INVARIANT_SEMGREP.file_patterns)
        self.assertIn("*.ts", INVARIANT_SEMGREP.file_patterns)

    def test_build_cmd_empty_profile(self) -> None:
        from story_automator.core.collectors.invariants import INVARIANT_SEMGREP

        cmd = INVARIANT_SEMGREP.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("invariant_check.py", cmd[1])
        self.assertEqual(cmd[2], "/tmp/checkout")
        self.assertEqual(cmd[3], "semgrep")
        registry = json.loads(cmd[4])
        self.assertEqual(registry, [])

    def test_build_cmd_with_registry(self) -> None:
        from story_automator.core.collectors.invariants import INVARIANT_SEMGREP

        profile = {
            "rules": {
                "invariants": {
                    "registry": [
                        {"id": "DG-12", "checkable": "yes", "check_type": "semgrep",
                         "rule_file": "semgrep/dg12.yml", "severity": "FAIL"},
                        {"id": "DG-13", "checkable": "yes", "check_type": "semgrep",
                         "rule_file": "semgrep/dg13.yml", "severity": "FAIL"},
                    ],
                },
            },
        }
        cmd = INVARIANT_SEMGREP.build_cmd("/tmp/checkout", profile)
        registry = json.loads(cmd[4])
        self.assertEqual(len(registry), 2)
        self.assertEqual(registry[0]["id"], "DG-12")

    def test_check_script_path_exists(self) -> None:
        from story_automator.core.collectors.invariants import INVARIANT_SEMGREP

        cmd = INVARIANT_SEMGREP.build_cmd("/tmp/checkout", {})
        script_path = Path(cmd[1])
        self.assertTrue(script_path.exists(), f"check script missing: {script_path}")


class InvariantConftestCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.invariants import INVARIANT_CONFTEST

        self.assertEqual(INVARIANT_CONFTEST.collector_id, "invariant-conftest-invariants")
        self.assertEqual(INVARIANT_CONFTEST.tool, "python3")
        self.assertEqual(INVARIANT_CONFTEST.category, "invariants")
        self.assertTrue(INVARIANT_CONFTEST.deterministic)
        self.assertIn("*.yaml", INVARIANT_CONFTEST.file_patterns)
        self.assertIn("*.json", INVARIANT_CONFTEST.file_patterns)

    def test_build_cmd_empty_profile(self) -> None:
        from story_automator.core.collectors.invariants import INVARIANT_CONFTEST

        cmd = INVARIANT_CONFTEST.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("invariant_check.py", cmd[1])
        self.assertEqual(cmd[2], "/tmp/checkout")
        self.assertEqual(cmd[3], "conftest")

    def test_build_cmd_with_registry(self) -> None:
        from story_automator.core.collectors.invariants import INVARIANT_CONFTEST

        profile = {
            "rules": {
                "invariants": {
                    "registry": [
                        {"id": "DG-4-L1", "checkable": "yes", "check_type": "conftest",
                         "rule_file": "policy/dg4.rego", "severity": "FAIL"},
                    ],
                },
            },
        }
        cmd = INVARIANT_CONFTEST.build_cmd("/tmp/checkout", profile)
        registry = json.loads(cmd[4])
        self.assertEqual(len(registry), 1)
        self.assertEqual(registry[0]["id"], "DG-4-L1")

    def test_check_script_path_exists(self) -> None:
        from story_automator.core.collectors.invariants import INVARIANT_CONFTEST

        cmd = INVARIANT_CONFTEST.build_cmd("/tmp/checkout", {})
        script_path = Path(cmd[1])
        self.assertTrue(script_path.exists(), f"check script missing: {script_path}")


class InvariantsCollectorListTests(unittest.TestCase):
    def test_two_collectors(self) -> None:
        from story_automator.core.collectors.invariants import COLLECTORS

        self.assertEqual(len(COLLECTORS), 2)

    def test_all_invariants_category(self) -> None:
        from story_automator.core.collectors.invariants import COLLECTORS

        for c in COLLECTORS:
            self.assertEqual(c.category, "invariants")

    def test_expected_ids(self) -> None:
        from story_automator.core.collectors.invariants import COLLECTORS

        ids = {c.collector_id for c in COLLECTORS}
        self.assertEqual(ids, {"invariant-semgrep-invariants", "invariant-conftest-invariants"})

    def test_unique_collector_ids(self) -> None:
        from story_automator.core.collectors.invariants import COLLECTORS

        ids = [c.collector_id for c in COLLECTORS]
        self.assertEqual(len(ids), len(set(ids)))
