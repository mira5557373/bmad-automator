from __future__ import annotations

import json
import sys
import unittest


class LicenseCheckCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.license import LICENSE_CHECK

        self.assertEqual(LICENSE_CHECK.collector_id, "license-check-license")
        self.assertEqual(LICENSE_CHECK.tool, "python3")
        self.assertEqual(LICENSE_CHECK.category, "license")
        self.assertTrue(LICENSE_CHECK.deterministic)

    def test_build_cmd_default_rules(self) -> None:
        from story_automator.core.collectors.license import LICENSE_CHECK

        cmd = LICENSE_CHECK.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("license_check.py", cmd[1])
        self.assertEqual(cmd[2], "/tmp/checkout")
        forbidden = json.loads(cmd[3])
        self.assertEqual(forbidden, [])
        boundary = json.loads(cmd[4])
        self.assertEqual(boundary, {})

    def test_build_cmd_with_profile_rules(self) -> None:
        from story_automator.core.collectors.license import LICENSE_CHECK

        profile = {
            "rules": {
                "license": {
                    "forbidden": ["BSL-1.1", "SSPL-1.0"],
                    "boundary": {"AGPL-3.0": ["odoo-pod"]},
                },
            },
        }
        cmd = LICENSE_CHECK.build_cmd("/tmp/checkout", profile)
        forbidden = json.loads(cmd[3])
        self.assertEqual(forbidden, ["BSL-1.1", "SSPL-1.0"])
        boundary = json.loads(cmd[4])
        self.assertEqual(boundary, {"AGPL-3.0": ["odoo-pod"]})

    def test_check_script_path_exists(self) -> None:
        from story_automator.core.collectors.license import LICENSE_CHECK

        cmd = LICENSE_CHECK.build_cmd("/tmp/checkout", {})
        from pathlib import Path

        script_path = Path(cmd[1])
        self.assertTrue(script_path.exists(), f"check script missing: {script_path}")


class LicenseCollectorListTests(unittest.TestCase):
    def test_one_collector(self) -> None:
        from story_automator.core.collectors.license import COLLECTORS

        self.assertEqual(len(COLLECTORS), 1)

    def test_all_license_category(self) -> None:
        from story_automator.core.collectors.license import COLLECTORS

        for c in COLLECTORS:
            self.assertEqual(c.category, "license")

    def test_expected_id(self) -> None:
        from story_automator.core.collectors.license import COLLECTORS

        ids = {c.collector_id for c in COLLECTORS}
        self.assertEqual(ids, {"license-check-license"})
