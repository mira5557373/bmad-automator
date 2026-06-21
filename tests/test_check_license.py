from __future__ import annotations

import json
import unittest


class LicenseCheckUsageTests(unittest.TestCase):
    def test_no_args_returns_2(self) -> None:
        from story_automator.core.checks.license_check import main

        self.assertEqual(main([]), 2)

    def test_one_arg_returns_2(self) -> None:
        from story_automator.core.checks.license_check import main

        self.assertEqual(main(["/tmp"]), 2)

    def test_two_args_returns_2(self) -> None:
        from story_automator.core.checks.license_check import main

        self.assertEqual(main(["/tmp", "[]"]), 2)

    def test_invalid_forbidden_json_returns_2(self) -> None:
        from story_automator.core.checks.license_check import main

        self.assertEqual(main(["/tmp", "not-json", "{}"]), 2)


class LicenseCheckForbiddenTests(unittest.TestCase):
    def test_no_forbidden_returns_0(self) -> None:
        from story_automator.core.checks.license_check import check_licenses

        packages = [{"name": "flask", "license": "BSD-3-Clause"}]
        violations = check_licenses(packages, [], {})
        self.assertEqual(violations, [])

    def test_forbidden_license_detected(self) -> None:
        from story_automator.core.checks.license_check import check_licenses

        packages = [
            {"name": "good-pkg", "license": "MIT"},
            {"name": "bad-pkg", "license": "BSL-1.1"},
        ]
        violations = check_licenses(packages, ["BSL-1.1"], {})
        self.assertEqual(len(violations), 1)
        self.assertIn("bad-pkg", violations[0])
        self.assertIn("BSL-1.1", violations[0])

    def test_forbidden_case_insensitive(self) -> None:
        from story_automator.core.checks.license_check import check_licenses

        packages = [{"name": "pkg", "license": "sspl-1.0"}]
        violations = check_licenses(packages, ["SSPL-1.0"], {})
        self.assertEqual(len(violations), 1)


class LicenseCheckBoundaryTests(unittest.TestCase):
    def test_boundary_violation_detected(self) -> None:
        from story_automator.core.checks.license_check import check_licenses

        packages = [{"name": "odoo-core", "license": "AGPL-3.0", "locations": ["/src/api/main.py"]}]
        boundary = {"AGPL-3.0": ["odoo-pod"]}
        violations = check_licenses(packages, [], boundary)
        self.assertEqual(len(violations), 1)
        self.assertIn("BOUNDARY", violations[0])

    def test_boundary_allowed_location(self) -> None:
        from story_automator.core.checks.license_check import check_licenses

        packages = [{"name": "odoo-core", "license": "AGPL-3.0", "locations": ["/src/odoo-pod/addon.py"]}]
        boundary = {"AGPL-3.0": ["odoo-pod"]}
        violations = check_licenses(packages, [], boundary)
        self.assertEqual(violations, [])

    def test_no_boundary_rules_no_violations(self) -> None:
        from story_automator.core.checks.license_check import check_licenses

        packages = [{"name": "pkg", "license": "AGPL-3.0", "locations": ["/src/api.py"]}]
        violations = check_licenses(packages, [], {})
        self.assertEqual(violations, [])


class ParseSyftOutputTests(unittest.TestCase):
    def test_parse_json_output(self) -> None:
        from story_automator.core.checks.license_check import parse_syft_output

        syft_json = json.dumps({
            "artifacts": [
                {"name": "flask", "version": "2.0", "licenses": [{"value": "BSD-3-Clause"}], "locations": [{"path": "/app/x.py"}]},
                {"name": "requests", "version": "2.28", "licenses": [{"value": "Apache-2.0"}], "locations": []},
            ]
        })
        packages = parse_syft_output(syft_json)
        self.assertEqual(len(packages), 2)
        self.assertEqual(packages[0]["name"], "flask")
        self.assertEqual(packages[0]["license"], "BSD-3-Clause")
        self.assertEqual(packages[1]["name"], "requests")
        self.assertEqual(packages[1]["license"], "Apache-2.0")

    def test_parse_empty_output(self) -> None:
        from story_automator.core.checks.license_check import parse_syft_output

        packages = parse_syft_output("{}")
        self.assertEqual(packages, [])

    def test_parse_invalid_json(self) -> None:
        from story_automator.core.checks.license_check import parse_syft_output

        packages = parse_syft_output("not json")
        self.assertEqual(packages, [])
