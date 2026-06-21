"""Tests for seed_template module — ref parsing, manifest validation, bundle resolution."""

from __future__ import annotations

import unittest

from story_automator.core.seed_template import (
    TEMPLATE_SCHEMA_VERSION,
    SeedTemplateError,
    resolve_template_ref,
)


class ResolveTemplateRefTests(unittest.TestCase):
    def test_parse_exact_version(self):
        self.assertEqual(
            resolve_template_ref("msme-erp-golden-template@1.0.0"),
            ("msme-erp-golden-template", "1.0.0"),
        )

    def test_parse_major_wildcard(self):
        self.assertEqual(
            resolve_template_ref("msme-erp-golden-template@1.x"),
            ("msme-erp-golden-template", "1.x"),
        )

    def test_parse_major_only(self):
        self.assertEqual(
            resolve_template_ref("msme-erp-golden-template@1"),
            ("msme-erp-golden-template", "1"),
        )

    def test_parse_no_version(self):
        self.assertEqual(
            resolve_template_ref("msme-erp-golden-template"),
            ("msme-erp-golden-template", ""),
        )

    def test_empty_ref(self):
        self.assertEqual(resolve_template_ref(""), ("", ""))

    def test_invalid_path_traversal(self):
        with self.assertRaises(SeedTemplateError):
            resolve_template_ref("../evil@1.0")

    def test_invalid_slashes(self):
        with self.assertRaises(SeedTemplateError):
            resolve_template_ref("foo/bar@1.0")

    def test_multiple_at_signs(self):
        with self.assertRaises(SeedTemplateError):
            resolve_template_ref("template@1.0@extra")

    def test_whitespace_ref(self):
        self.assertEqual(resolve_template_ref("  "), ("", ""))

    def test_schema_version_is_int(self):
        self.assertIsInstance(TEMPLATE_SCHEMA_VERSION, int)
        self.assertEqual(TEMPLATE_SCHEMA_VERSION, 1)


if __name__ == "__main__":
    unittest.main()
