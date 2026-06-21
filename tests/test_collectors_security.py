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


class OsvCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.security import OSV

        self.assertEqual(OSV.collector_id, "osv-security")
        self.assertEqual(OSV.tool, "osv-scanner")
        self.assertEqual(OSV.category, "security")
        self.assertTrue(OSV.deterministic)

    def test_build_cmd(self) -> None:
        from story_automator.core.collectors.security import OSV

        cmd = OSV.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], "osv-scanner")
        self.assertIn("scan", cmd)
        self.assertIn("--recursive", cmd)
        self.assertIn(".", cmd)

    def test_version_cmd(self) -> None:
        from story_automator.core.collectors.security import OSV

        self.assertIsNotNone(OSV.tool_version_cmd)
        self.assertIn("osv-scanner", OSV.tool_version_cmd)


class GitleaksCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.security import GITLEAKS

        self.assertEqual(GITLEAKS.collector_id, "gitleaks-security")
        self.assertEqual(GITLEAKS.tool, "gitleaks")
        self.assertEqual(GITLEAKS.category, "security")
        self.assertTrue(GITLEAKS.deterministic)

    def test_build_cmd(self) -> None:
        from story_automator.core.collectors.security import GITLEAKS

        cmd = GITLEAKS.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], "gitleaks")
        self.assertIn("detect", cmd)
        self.assertIn("--source", cmd)
        self.assertIn(".", cmd)

    def test_version_cmd(self) -> None:
        from story_automator.core.collectors.security import GITLEAKS

        self.assertIsNotNone(GITLEAKS.tool_version_cmd)
        self.assertIn("gitleaks", GITLEAKS.tool_version_cmd)


class SecurityCollectorListTests(unittest.TestCase):
    def test_four_collectors(self) -> None:
        from story_automator.core.collectors.security import COLLECTORS

        self.assertEqual(len(COLLECTORS), 4)

    def test_all_expected_ids(self) -> None:
        from story_automator.core.collectors.security import COLLECTORS

        ids = {c.collector_id for c in COLLECTORS}
        self.assertEqual(ids, {
            "semgrep-security", "trivy-vuln-security",
            "osv-security", "gitleaks-security",
        })

    def test_all_security_category(self) -> None:
        from story_automator.core.collectors.security import COLLECTORS

        for c in COLLECTORS:
            self.assertEqual(c.category, "security")

    def test_unique_collector_ids(self) -> None:
        from story_automator.core.collectors.security import COLLECTORS

        ids = [c.collector_id for c in COLLECTORS]
        self.assertEqual(len(ids), len(set(ids)))
