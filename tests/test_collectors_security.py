from __future__ import annotations

import unittest


class SemgrepCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.security import SEMGREP

        self.assertEqual(SEMGREP.collector_id, "semgrep-security")
        self.assertEqual(SEMGREP.tool, "semgrep")
        self.assertEqual(SEMGREP.category, "security")
        self.assertTrue(SEMGREP.deterministic)
        self.assertIn("*.py", SEMGREP.file_patterns)
        self.assertIn("*.ts", SEMGREP.file_patterns)
        self.assertIn("*.js", SEMGREP.file_patterns)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.security import SEMGREP

        cmd = SEMGREP.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], "semgrep")
        self.assertIn("scan", cmd)
        self.assertIn("--error", cmd)

    def test_build_cmd_custom_config(self) -> None:
        from story_automator.core.collectors.security import SEMGREP

        profile = {"rules": {"security": {"semgrep_config": "p/owasp-top-ten"}}}
        cmd = SEMGREP.build_cmd("/tmp/checkout", profile)
        self.assertIn("--config=p/owasp-top-ten", cmd)

    def test_version_cmd(self) -> None:
        from story_automator.core.collectors.security import SEMGREP

        self.assertIsNotNone(SEMGREP.tool_version_cmd)
        self.assertIn("semgrep", SEMGREP.tool_version_cmd)


class TrivyVulnCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.security import TRIVY_VULN

        self.assertEqual(TRIVY_VULN.collector_id, "trivy-vuln-security")
        self.assertEqual(TRIVY_VULN.tool, "trivy")
        self.assertEqual(TRIVY_VULN.category, "security")
        self.assertTrue(TRIVY_VULN.deterministic)

    def test_build_cmd(self) -> None:
        from story_automator.core.collectors.security import TRIVY_VULN

        cmd = TRIVY_VULN.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], "trivy")
        self.assertIn("fs", cmd)
        self.assertIn("--exit-code", cmd)
        self.assertIn("1", cmd)
        self.assertIn("--scanners", cmd)
        self.assertIn("vuln", cmd)
        self.assertIn(".", cmd)

    def test_build_cmd_custom_severity(self) -> None:
        from story_automator.core.collectors.security import TRIVY_VULN

        profile = {"rules": {"security": {"trivy_severity": "CRITICAL"}}}
        cmd = TRIVY_VULN.build_cmd("/tmp/checkout", profile)
        self.assertIn("--severity", cmd)
        self.assertIn("CRITICAL", cmd)

    def test_version_cmd(self) -> None:
        from story_automator.core.collectors.security import TRIVY_VULN

        self.assertIsNotNone(TRIVY_VULN.tool_version_cmd)
        self.assertIn("trivy", TRIVY_VULN.tool_version_cmd)
