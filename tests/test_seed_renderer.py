"""Tests for seed_renderer module — variable resolution, file listing, rendering, instantiation."""

from __future__ import annotations

import unittest

import shutil
import tempfile
from pathlib import Path

from story_automator.core.seed_renderer import (
    InstantiationResult,
    SeedRenderError,
    instantiate_template,
    list_template_files,
    render_template_content,
    resolve_variables,
)


def _make_manifest_with_vars(variables):
    """Return a manifest dict with the given variables section."""
    m = {
        "schema_version": 1,
        "template_id": "test",
        "template_version": "1.0.0",
        "categories": {
            "c": {
                "description": "cat",
                "files": [{"src": "a.tmpl", "dst": "a.py"}],
            }
        },
    }
    if variables is not None:
        m["variables"] = variables
    return m


class ResolveVariablesTests(unittest.TestCase):
    def test_required_provided(self):
        m = _make_manifest_with_vars({"name": {"required": True}})
        result = resolve_variables(m, {"name": "World"})
        self.assertEqual(result["name"], "World")

    def test_required_missing_raises(self):
        m = _make_manifest_with_vars({"name": {"required": True}})
        with self.assertRaises(SeedRenderError):
            resolve_variables(m, {})

    def test_optional_uses_default(self):
        m = _make_manifest_with_vars({"port": {"default": "8080"}})
        result = resolve_variables(m, {})
        self.assertEqual(result["port"], "8080")

    def test_provided_overrides_default(self):
        m = _make_manifest_with_vars({"port": {"default": "8080"}})
        result = resolve_variables(m, {"port": "3000"})
        self.assertEqual(result["port"], "3000")

    def test_no_variables_in_manifest(self):
        m = _make_manifest_with_vars(None)
        result = resolve_variables(m, {"extra": "val"})
        self.assertEqual(result, {"extra": "val"})

    def test_extra_provided_kept(self):
        m = _make_manifest_with_vars({"name": {"required": True}})
        result = resolve_variables(m, {"name": "X", "bonus": "Y"})
        self.assertIn("bonus", result)
        self.assertEqual(result["bonus"], "Y")

    def test_empty_provided_empty_manifest(self):
        m = _make_manifest_with_vars({})
        result = resolve_variables(m, {})
        self.assertEqual(result, {})


def _make_multi_category_manifest():
    return {
        "schema_version": 1,
        "template_id": "test",
        "template_version": "1.0.0",
        "categories": {
            "contracts": {
                "description": "Contract tests",
                "files": [
                    {"src": "c/conftest.py.tmpl", "dst": "tests/contracts/conftest.py"},
                    {"src": "c/pact.py.tmpl", "dst": "tests/contracts/pact.py", "on_conflict": "overwrite"},
                ],
            },
            "network": {
                "description": "Network interception",
                "files": [
                    {"src": "n/net.py.tmpl", "dst": "tests/network/net.py"},
                ],
            },
            "empty": {
                "description": "Empty category",
                "files": [],
            },
        },
    }


class ListTemplateFilesTests(unittest.TestCase):
    def test_list_all_files(self):
        m = _make_multi_category_manifest()
        result = list_template_files(m)
        self.assertEqual(len(result), 3)
        categories = {e["category"] for e in result}
        self.assertEqual(categories, {"contracts", "network"})

    def test_filter_by_category(self):
        m = _make_multi_category_manifest()
        result = list_template_files(m, category="contracts")
        self.assertEqual(len(result), 2)
        self.assertTrue(all(e["category"] == "contracts" for e in result))

    def test_unknown_category_raises(self):
        m = _make_multi_category_manifest()
        with self.assertRaises(SeedRenderError):
            list_template_files(m, category="nonexistent")

    def test_default_on_conflict(self):
        m = _make_multi_category_manifest()
        result = list_template_files(m, category="network")
        self.assertEqual(result[0]["on_conflict"], "skip")

    def test_explicit_on_conflict(self):
        m = _make_multi_category_manifest()
        result = list_template_files(m, category="contracts")
        overwrite_entries = [e for e in result if e["on_conflict"] == "overwrite"]
        self.assertEqual(len(overwrite_entries), 1)

    def test_empty_category_files(self):
        m = _make_multi_category_manifest()
        result = list_template_files(m, category="empty")
        self.assertEqual(result, [])


class RenderTemplateContentTests(unittest.TestCase):
    def test_simple_substitution(self):
        self.assertEqual(
            render_template_content("Hello $name", {"name": "World"}),
            "Hello World",
        )

    def test_braced_substitution(self):
        self.assertEqual(
            render_template_content("${service}_api", {"service": "erp"}),
            "erp_api",
        )

    def test_dollar_escape(self):
        self.assertEqual(
            render_template_content("Price: $$5", {}),
            "Price: $5",
        )

    def test_missing_var_safe(self):
        self.assertEqual(
            render_template_content("Hello $unknown", {}),
            "Hello $unknown",
        )

    def test_empty_content(self):
        self.assertEqual(render_template_content("", {"x": "y"}), "")

    def test_multiline(self):
        tpl = "line1: $a\nline2: $b"
        result = render_template_content(tpl, {"a": "X", "b": "Y"})
        self.assertEqual(result, "line1: X\nline2: Y")

    def test_no_variables_passthrough(self):
        plain = "no variables here"
        self.assertEqual(render_template_content(plain, {}), plain)


class InstantiateTemplateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._bundle = Path(self._tmp) / "bundle"
        self._target = Path(self._tmp) / "target"
        self._bundle.mkdir()
        self._target.mkdir()
        self._manifest = {
            "schema_version": 1,
            "template_id": "test",
            "template_version": "1.0.0",
            "variables": {"product_name": {"required": True}},
            "categories": {
                "cat1": {
                    "description": "Category 1",
                    "files": [
                        {"src": "cat1/hello.py.tmpl", "dst": "src/hello.py"},
                    ],
                },
                "cat2": {
                    "description": "Category 2",
                    "files": [
                        {"src": "cat2/world.py.tmpl", "dst": "lib/world.py"},
                    ],
                },
            },
        }
        cat1_dir = self._bundle / "cat1"
        cat1_dir.mkdir()
        (cat1_dir / "hello.py.tmpl").write_text(
            '# $product_name\nprint("hello")\n', encoding="utf-8"
        )
        cat2_dir = self._bundle / "cat2"
        cat2_dir.mkdir()
        (cat2_dir / "world.py.tmpl").write_text(
            '# $product_name\nprint("world")\n', encoding="utf-8"
        )

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_basic_instantiation(self):
        instantiate_template(
            self._bundle, self._manifest, self._target,
            {"product_name": "MyApp"},
        )
        dst = self._target / "src" / "hello.py"
        self.assertTrue(dst.is_file())
        self.assertIn("MyApp", dst.read_text(encoding="utf-8"))

    def test_creates_parent_dirs(self):
        instantiate_template(
            self._bundle, self._manifest, self._target,
            {"product_name": "X"},
        )
        self.assertTrue((self._target / "src").is_dir())
        self.assertTrue((self._target / "lib").is_dir())

    def test_multiple_files(self):
        result = instantiate_template(
            self._bundle, self._manifest, self._target,
            {"product_name": "X"}, category="cat1",
        )
        self.assertEqual(len(result.written), 1)

    def test_multiple_categories(self):
        result = instantiate_template(
            self._bundle, self._manifest, self._target,
            {"product_name": "X"},
        )
        self.assertEqual(len(result.written), 2)

    def test_filter_by_category(self):
        result = instantiate_template(
            self._bundle, self._manifest, self._target,
            {"product_name": "X"}, category="cat2",
        )
        self.assertEqual(len(result.written), 1)
        self.assertIn("lib/world.py", result.written[0])

    def test_rendered_content(self):
        instantiate_template(
            self._bundle, self._manifest, self._target,
            {"product_name": "ACME"},
        )
        content = (self._target / "src" / "hello.py").read_text(encoding="utf-8")
        self.assertIn("ACME", content)
        self.assertNotIn("$product_name", content)

    def test_result_tracks_written(self):
        result = instantiate_template(
            self._bundle, self._manifest, self._target,
            {"product_name": "X"},
        )
        self.assertEqual(len(result.written), 2)
        self.assertEqual(len(result.skipped), 0)
        self.assertEqual(len(result.errors), 0)

    def test_instantiation_result_fields(self):
        r = InstantiationResult()
        self.assertEqual(r.written, [])
        self.assertEqual(r.skipped, [])
        self.assertEqual(r.errors, [])


if __name__ == "__main__":
    unittest.main()
