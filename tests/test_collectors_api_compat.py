# tests/test_collectors_api_compat.py
from __future__ import annotations

import unittest


class OpenapiDiffCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.api_compat import OPENAPI_DIFF

        self.assertEqual(OPENAPI_DIFF.collector_id, "openapi-diff-api_compat")
        self.assertEqual(OPENAPI_DIFF.tool, "oasdiff")
        self.assertEqual(OPENAPI_DIFF.category, "api_compat")
        self.assertTrue(OPENAPI_DIFF.deterministic)
        self.assertIn("*.yaml", OPENAPI_DIFF.file_patterns)
        self.assertIn("*.json", OPENAPI_DIFF.file_patterns)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.api_compat import OPENAPI_DIFF

        cmd = OPENAPI_DIFF.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], "oasdiff")
        self.assertIn("breaking", cmd)

    def test_build_cmd_custom_base_spec(self) -> None:
        from story_automator.core.collectors.api_compat import OPENAPI_DIFF

        profile = {
            "rules": {"api_compat": {
                "openapi_base": "api/v1/openapi-base.yaml",
                "openapi_revision": "api/v1/openapi.yaml",
            }},
        }
        cmd = OPENAPI_DIFF.build_cmd("/tmp/checkout", profile)
        self.assertIn("api/v1/openapi-base.yaml", cmd)
        self.assertIn("api/v1/openapi.yaml", cmd)

    def test_version_cmd(self) -> None:
        from story_automator.core.collectors.api_compat import OPENAPI_DIFF

        self.assertIsNotNone(OPENAPI_DIFF.tool_version_cmd)
        self.assertIn("oasdiff", OPENAPI_DIFF.tool_version_cmd)


class SchemaDiffCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.api_compat import SCHEMA_DIFF

        self.assertEqual(SCHEMA_DIFF.collector_id, "schema-diff-api_compat")
        self.assertEqual(SCHEMA_DIFF.tool, "oasdiff")
        self.assertEqual(SCHEMA_DIFF.category, "api_compat")
        self.assertTrue(SCHEMA_DIFF.deterministic)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.api_compat import SCHEMA_DIFF

        cmd = SCHEMA_DIFF.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], "oasdiff")
        self.assertIn("diff", cmd)

    def test_build_cmd_custom_specs(self) -> None:
        from story_automator.core.collectors.api_compat import SCHEMA_DIFF

        profile = {
            "rules": {"api_compat": {
                "schema_base": "schemas/base.yaml",
                "schema_revision": "schemas/current.yaml",
            }},
        }
        cmd = SCHEMA_DIFF.build_cmd("/tmp/checkout", profile)
        self.assertIn("schemas/base.yaml", cmd)
        self.assertIn("schemas/current.yaml", cmd)

    def test_version_cmd(self) -> None:
        from story_automator.core.collectors.api_compat import SCHEMA_DIFF

        self.assertIsNotNone(SCHEMA_DIFF.tool_version_cmd)
        self.assertIn("oasdiff", SCHEMA_DIFF.tool_version_cmd)


class ApiCompatCollectorListTests(unittest.TestCase):
    def test_two_collectors(self) -> None:
        from story_automator.core.collectors.api_compat import COLLECTORS

        self.assertEqual(len(COLLECTORS), 2)

    def test_all_api_compat_category(self) -> None:
        from story_automator.core.collectors.api_compat import COLLECTORS

        for c in COLLECTORS:
            self.assertEqual(c.category, "api_compat")

    def test_expected_ids(self) -> None:
        from story_automator.core.collectors.api_compat import COLLECTORS

        ids = {c.collector_id for c in COLLECTORS}
        self.assertEqual(ids, {"openapi-diff-api_compat", "schema-diff-api_compat"})

    def test_unique_collector_ids(self) -> None:
        from story_automator.core.collectors.api_compat import COLLECTORS

        ids = [c.collector_id for c in COLLECTORS]
        self.assertEqual(len(ids), len(set(ids)))
