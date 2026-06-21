"""Tests for seed_template module — ref parsing, manifest validation, bundle resolution."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from story_automator.core.seed_template import (
    TEMPLATE_SCHEMA_VERSION,
    SeedTemplateError,
    load_template_manifest,
    resolve_bundle_dir,
    resolve_template_ref,
    validate_bundle,
    validate_manifest,
    version_satisfies,
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


class ResolveBundleDirTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._skill_root = Path(self._tmp) / "skills" / "bmad-story-automator"
        tpl_dir = self._skill_root / "data" / "templates" / "test-template"
        tpl_dir.mkdir(parents=True)

    def tearDown(self):
        import shutil

        shutil.rmtree(self._tmp, ignore_errors=True)

    def _patch_root(self):
        return patch(
            "story_automator.core.seed_template.bundled_story_skill_root",
            return_value=self._skill_root,
        )

    def test_existing_bundle_resolves(self):
        with self._patch_root():
            result = resolve_bundle_dir("test-template")
        self.assertTrue(result.is_dir())

    def test_missing_bundle_raises(self):
        with self._patch_root():
            with self.assertRaises(SeedTemplateError):
                resolve_bundle_dir("nonexistent-template")

    def test_path_traversal_blocked(self):
        with self._patch_root():
            with self.assertRaises(SeedTemplateError):
                resolve_bundle_dir("../evil")

    def test_result_is_absolute(self):
        with self._patch_root():
            result = resolve_bundle_dir("test-template")
        self.assertTrue(result.is_absolute())


class VersionSatisfiesTests(unittest.TestCase):
    def test_exact_match(self):
        self.assertTrue(version_satisfies("1.0.0", "1.0.0"))

    def test_exact_mismatch(self):
        self.assertFalse(version_satisfies("1.0.0", "2.0.0"))

    def test_major_wildcard_match(self):
        self.assertTrue(version_satisfies("1.2.3", "1.x"))

    def test_major_wildcard_mismatch(self):
        self.assertFalse(version_satisfies("2.0.0", "1.x"))

    def test_major_only_match(self):
        self.assertTrue(version_satisfies("1.2.3", "1"))

    def test_empty_ref_matches_any(self):
        self.assertTrue(version_satisfies("3.0.0", ""))


class LoadTemplateManifestTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._skill_root = Path(self._tmp) / "skills" / "bmad-story-automator"
        self._bundle_dir = (
            self._skill_root / "data" / "templates" / "test-template"
        )
        self._bundle_dir.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _patch_root(self):
        return patch(
            "story_automator.core.seed_template.bundled_story_skill_root",
            return_value=self._skill_root,
        )

    def _write_manifest(self, data):
        (self._bundle_dir / "manifest.json").write_text(
            json.dumps(data), encoding="utf-8"
        )

    def test_empty_ref_returns_none(self):
        with self._patch_root():
            self.assertIsNone(load_template_manifest(""))

    def test_loads_valid_manifest(self):
        self._write_manifest(_make_manifest(
            template_id="test-template", template_version="1.0.0"
        ))
        with self._patch_root():
            result = load_template_manifest("test-template@1.0.0")
        self.assertEqual(result["template_id"], "test-template")

    def test_missing_manifest_raises(self):
        with self._patch_root():
            with self.assertRaises(SeedTemplateError):
                load_template_manifest("test-template@1.0.0")

    def test_invalid_json_raises(self):
        (self._bundle_dir / "manifest.json").write_text(
            "{bad json", encoding="utf-8"
        )
        with self._patch_root():
            with self.assertRaises(SeedTemplateError):
                load_template_manifest("test-template@1.0.0")

    def test_version_mismatch_raises(self):
        self._write_manifest(_make_manifest(
            template_id="test-template", template_version="2.0.0"
        ))
        with self._patch_root():
            with self.assertRaises(SeedTemplateError):
                load_template_manifest("test-template@1.0.0")


class ValidateBundleTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._bundle_dir = Path(self._tmp) / "bundle"
        self._bundle_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _manifest_with_files(self, files_by_category):
        categories = {}
        for cat, srcs in files_by_category.items():
            categories[cat] = {
                "description": cat,
                "files": [
                    {"src": s, "dst": s.replace(".tmpl", "")}
                    for s in srcs
                ],
            }
        return _make_manifest(categories=categories)

    def test_all_files_present(self):
        src = self._bundle_dir / "a.tmpl"
        src.write_text("ok", encoding="utf-8")
        m = self._manifest_with_files({"c": ["a.tmpl"]})
        self.assertEqual(validate_bundle(self._bundle_dir, m), [])

    def test_missing_file_reported(self):
        m = self._manifest_with_files({"c": ["missing.tmpl"]})
        result = validate_bundle(self._bundle_dir, m)
        self.assertEqual(len(result), 1)
        self.assertIn("missing.tmpl", result[0])

    def test_multiple_missing(self):
        m = self._manifest_with_files({"a": ["x.tmpl"], "b": ["y.tmpl"]})
        result = validate_bundle(self._bundle_dir, m)
        self.assertEqual(len(result), 2)

    def test_empty_manifest_valid(self):
        m = _make_manifest(
            categories={"c": {"description": "empty", "files": []}}
        )
        self.assertEqual(validate_bundle(self._bundle_dir, m), [])


if __name__ == "__main__":
    unittest.main()
