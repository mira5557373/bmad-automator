from __future__ import annotations

import json
import unittest


class SbomCheckUsageTests(unittest.TestCase):
    def test_no_args_returns_2(self) -> None:
        from story_automator.core.checks.sbom_check import main

        self.assertEqual(main([]), 2)


class ValidateSbomTests(unittest.TestCase):
    def test_valid_spdx_json(self) -> None:
        from story_automator.core.checks.sbom_check import validate_sbom

        sbom = json.dumps({
            "spdxVersion": "SPDX-2.3",
            "name": "test",
            "packages": [
                {"name": "flask", "versionInfo": "2.0"},
            ],
        })
        ok, msg = validate_sbom(sbom, "spdx-json")
        self.assertEqual(ok, True)
        self.assertIn("1 package(s) found", msg)
        self.assertIn("SPDX", msg)

    def test_valid_cyclonedx_json(self) -> None:
        from story_automator.core.checks.sbom_check import validate_sbom

        sbom = json.dumps({
            "bomFormat": "CycloneDX",
            "specVersion": "1.4",
            "components": [
                {"name": "requests", "version": "2.28"},
            ],
        })
        ok, msg = validate_sbom(sbom, "cyclonedx-json")
        self.assertEqual(ok, True)
        self.assertIn("1 component(s) found", msg)
        self.assertIn("CycloneDX", msg)

    def test_empty_json_fails(self) -> None:
        from story_automator.core.checks.sbom_check import validate_sbom

        ok, msg = validate_sbom("{}", "spdx-json")
        self.assertEqual(ok, False)
        self.assertIn("spdxVersion", msg)

    def test_invalid_json_fails(self) -> None:
        from story_automator.core.checks.sbom_check import validate_sbom

        ok, msg = validate_sbom("not json", "spdx-json")
        self.assertEqual(ok, False)
        self.assertIn("not valid JSON", msg)

    def test_empty_packages_fails(self) -> None:
        from story_automator.core.checks.sbom_check import validate_sbom

        sbom = json.dumps({
            "spdxVersion": "SPDX-2.3",
            "name": "test",
            "packages": [],
        })
        ok, msg = validate_sbom(sbom, "spdx-json")
        self.assertEqual(ok, False)
        self.assertIn("no packages", msg)
