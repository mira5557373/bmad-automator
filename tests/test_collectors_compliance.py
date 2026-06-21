"""Tests for the compliance collector module."""
from __future__ import annotations

import unittest


class ComplianceRulesCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.compliance import COMPLIANCE_RULES

        self.assertEqual(COMPLIANCE_RULES.collector_id, "compliance-rules-compliance")
        self.assertEqual(COMPLIANCE_RULES.tool, "semgrep")
        self.assertEqual(COMPLIANCE_RULES.category, "compliance")
        self.assertTrue(COMPLIANCE_RULES.deterministic)
        self.assertIn("*.py", COMPLIANCE_RULES.file_patterns)
        self.assertIn("*.ts", COMPLIANCE_RULES.file_patterns)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.compliance import COMPLIANCE_RULES

        cmd = COMPLIANCE_RULES.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], "semgrep")
        self.assertIn("scan", cmd)
        self.assertIn("--error", cmd)
        self.assertIn("--config=auto", cmd)

    def test_build_cmd_custom_rulepack(self) -> None:
        from story_automator.core.collectors.compliance import COMPLIANCE_RULES

        profile = {"rules": {"compliance": {"rulepack_dir": "semgrep/compliance"}}}
        cmd = COMPLIANCE_RULES.build_cmd("/tmp/checkout", profile)
        self.assertIn("--config=semgrep/compliance", cmd)
        self.assertNotIn("--config=auto", cmd)

    def test_version_cmd(self) -> None:
        from story_automator.core.collectors.compliance import COMPLIANCE_RULES

        self.assertIsNotNone(COMPLIANCE_RULES.tool_version_cmd)
        self.assertIn("semgrep", COMPLIANCE_RULES.tool_version_cmd)


class ConftestCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.compliance import CONFTEST

        self.assertEqual(CONFTEST.collector_id, "conftest-compliance")
        self.assertEqual(CONFTEST.tool, "conftest")
        self.assertEqual(CONFTEST.category, "compliance")
        self.assertTrue(CONFTEST.deterministic)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.compliance import CONFTEST

        cmd = CONFTEST.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], "conftest")
        self.assertIn("test", cmd)
        self.assertIn("--policy", cmd)
        self.assertIn("policy", cmd)

    def test_build_cmd_custom_policy_dir(self) -> None:
        from story_automator.core.collectors.compliance import CONFTEST

        profile = {"rules": {"compliance": {"conftest_policy_dir": "opa/compliance"}}}
        cmd = CONFTEST.build_cmd("/tmp/checkout", profile)
        self.assertIn("opa/compliance", cmd)

    def test_version_cmd(self) -> None:
        from story_automator.core.collectors.compliance import CONFTEST

        self.assertIsNotNone(CONFTEST.tool_version_cmd)
        self.assertIn("conftest", CONFTEST.tool_version_cmd)


class ComplianceCollectorListTests(unittest.TestCase):
    def test_two_collectors(self) -> None:
        from story_automator.core.collectors.compliance import COLLECTORS

        self.assertEqual(len(COLLECTORS), 2)

    def test_all_compliance_category(self) -> None:
        from story_automator.core.collectors.compliance import COLLECTORS

        for c in COLLECTORS:
            self.assertEqual(c.category, "compliance")

    def test_expected_ids(self) -> None:
        from story_automator.core.collectors.compliance import COLLECTORS

        ids = {c.collector_id for c in COLLECTORS}
        self.assertEqual(ids, {"compliance-rules-compliance", "conftest-compliance"})
