"""Tests for seed_template module — ref parsing, manifest validation, bundle resolution."""

from __future__ import annotations

import unittest

from story_automator.core.seed_template import (
    TEMPLATE_SCHEMA_VERSION,
    SeedTemplateError,
    resolve_template_ref,
    validate_manifest,
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


def _make_manifest(**overrides):
    """Return a valid minimal manifest dict with overrides applied."""
    base = {
        "schema_version": TEMPLATE_SCHEMA_VERSION,
        "template_id": "test-template",
        "template_version": "1.0.0",
        "categories": {
            "contracts": {
                "description": "Contract tests",
                "files": [
                    {"src": "contracts/conftest.py.tmpl", "dst": "tests/contracts/conftest.py"}
                ],
            }
        },
    }
    base.update(overrides)
    return base


class ValidateManifestTests(unittest.TestCase):
    def test_valid_minimal_manifest(self):
        validate_manifest(_make_manifest())

    def test_valid_full_manifest(self):
        m = _make_manifest(
            description="Full template",
            variables={
                "product_name": {"required": True, "description": "Product name"},
                "port": {"required": False, "default": "8080"},
            },
        )
        m["categories"]["contracts"]["files"][0]["on_conflict"] = "overwrite"
        m["categories"]["contracts"]["files"][0]["tea_fragment"] = "pact-consumer.md"
        validate_manifest(m)

    def test_missing_schema_version(self):
        m = _make_manifest()
        del m["schema_version"]
        with self.assertRaises(SeedTemplateError):
            validate_manifest(m)

    def test_wrong_schema_version(self):
        with self.assertRaises(SeedTemplateError):
            validate_manifest(_make_manifest(schema_version=99))

    def test_missing_template_id(self):
        m = _make_manifest()
        del m["template_id"]
        with self.assertRaises(SeedTemplateError):
            validate_manifest(m)

    def test_empty_template_id(self):
        with self.assertRaises(SeedTemplateError):
            validate_manifest(_make_manifest(template_id=""))

    def test_missing_template_version(self):
        m = _make_manifest()
        del m["template_version"]
        with self.assertRaises(SeedTemplateError):
            validate_manifest(m)

    def test_missing_categories(self):
        m = _make_manifest()
        del m["categories"]
        with self.assertRaises(SeedTemplateError):
            validate_manifest(m)

    def test_empty_categories(self):
        with self.assertRaises(SeedTemplateError):
            validate_manifest(_make_manifest(categories={}))

    def test_category_missing_files(self):
        with self.assertRaises(SeedTemplateError):
            validate_manifest(_make_manifest(
                categories={"c": {"description": "no files key"}}
            ))

    def test_category_missing_description(self):
        with self.assertRaises(SeedTemplateError):
            validate_manifest(_make_manifest(
                categories={"c": {"files": []}}
            ))

    def test_file_entry_missing_src(self):
        with self.assertRaises(SeedTemplateError):
            validate_manifest(_make_manifest(
                categories={"c": {"description": "d", "files": [{"dst": "a.py"}]}}
            ))

    def test_file_entry_missing_dst(self):
        with self.assertRaises(SeedTemplateError):
            validate_manifest(_make_manifest(
                categories={"c": {"description": "d", "files": [{"src": "a.py.tmpl"}]}}
            ))

    def test_file_entry_invalid_on_conflict(self):
        with self.assertRaises(SeedTemplateError):
            validate_manifest(_make_manifest(
                categories={
                    "c": {
                        "description": "d",
                        "files": [{"src": "a.tmpl", "dst": "a.py", "on_conflict": "merge"}],
                    }
                }
            ))

    def test_variable_invalid_required_type(self):
        with self.assertRaises(SeedTemplateError):
            validate_manifest(_make_manifest(
                variables={"name": {"required": "yes"}}
            ))

    def test_duplicate_dst_across_categories(self):
        with self.assertRaises(SeedTemplateError):
            validate_manifest(_make_manifest(
                categories={
                    "a": {"description": "A", "files": [{"src": "x.tmpl", "dst": "same.py"}]},
                    "b": {"description": "B", "files": [{"src": "y.tmpl", "dst": "same.py"}]},
                }
            ))

    def test_variable_name_invalid_identifier(self):
        with self.assertRaises(SeedTemplateError):
            validate_manifest(_make_manifest(
                variables={"foo-bar": {"required": True}}
            ))


if __name__ == "__main__":
    unittest.main()
